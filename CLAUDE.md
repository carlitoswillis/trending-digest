# trending-digest

A GitHub Action that files a weekly issue summarising GitHub Trending (from the
GitHubTrendingRSS weekly feed plus GitHub API metadata and per-repo history), and
optionally adds Claude-written research briefs. GitHub emails the issue as the digest.

## Running the tests

    python3 tests/test_digest.py
    python3 tests/test_site.py

No dependencies beyond the Python 3 standard library. `.github/workflows/test.yml`
runs the same command on push and pull request.

## Script interface

- `python3 scripts/build_digest.py` fetches feed, API and history; writes `digest.json`
  and `digest.md` (no briefs). Exits 1 on feed failure.
- `python3 scripts/build_digest.py render --briefs briefs.json` is offline: reads
  `digest.json` and `briefs.json`, writes `digest.md` with briefs folded in. A missing
  or unparseable `briefs.json` is logged and rendering continues without briefs, exit 0.
- `briefs.json`: `{"owner/repo": {"why_now", "use_for", "verdict", "reason"}}`, keys
  matched case-insensitively, unknown keys ignored, verdict must be Try/Watch/Skip
  (anything else drops that brief with a stderr log).
- `DIGEST_PAGE_URL` (env, optional) adds the one non-repo link, "Read on the web",
  at the end of digest.md's first line.
- `python3 scripts/build_site.py add digest.json --briefs briefs.json` records the week
  as `data/weeks/YYYY-MM-DD.json` (briefs merged in as plain text).
  `python3 scripts/build_site.py render --out site` renders every recorded week, one
  per ISO week, into `site/` (index.html = latest, weeks/DATE.html, .nojekyll).

## The site (GitHub Pages)

The `publish` job in `digest.yml` (needs `build`; `contents: write`, `pages: write`,
`id-token: write`) records the week, commits `data/weeks/` back to the branch that ran,
renders `site/` and deploys it with `actions/deploy-pages`. It is independent of the
`file` job: a site failure never blocks the email. The site is the designed reading
surface; the email is the Monday nudge and links to it.

## Research briefs (Claude in the runner)

`digest.yml` runs `anthropics/claude-code-action@v1` with the OAuth token secret;
Claude follows `scripts/brief_prompt.md` and writes `briefs.json`. The step is
`continue-on-error` with a timeout; the issue is always filed. Two jobs: `build`
(read-only permissions: checkout, build, gate, research, fold, upload `digest.md`)
and `file` (`issues: write`: download, `gh issue create`). Claude's allowlist writes
only `briefs.json`; the fold step runs `git checkout -- .` and restores the build's
`digest.json`/`digest.md` from `$RUNNER_TEMP` first, and is itself
`continue-on-error`. Switch-off paths:

1. Repo variable `DIGEST_ANALYSIS=off`.
2. Manual run with the "Add Claude research briefs" checkbox off.
3. Delete the `CLAUDE_CODE_OAUTH_TOKEN` secret.

Shell in `run:` steps never contains `${{ }}`; values pass through `env:`.

## Design system for the digest body (do not restyle)

Medium: a GitHub issue body in GitHub-flavored markdown, read mostly as the
notification email on a phone (Gmail: no CSS, `<details>` renders expanded,
blockquotes indent with a left bar) and on github.com. Reading mode: scanned.
Idea: a shelf, ranked as GitHub ranks it. One scan line per repo; the brief is the
card you pull.

Each presentation device has exactly one job:

| Device          | Its only job                                                     |
| --------------- | ---------------------------------------------------------------- |
| bold `**`       | the repo name (linked). Nothing else is bold.                    |
| plain text      | metadata and description (the muted layer)                       |
| code span `` ` `` | the single accent: `Try` at the end of an entry line, only when the verdict is Try. No other code spans; topics are not shown. |
| blockquote `>`  | the brief, one line, indented under its entry                    |
| italics `*`     | the three run-in labels inside a brief only: *Why now.* *Use it for.* *Verdict.* |
| headings        | `##` for the two sections only. No `#` title, no `###` groups.  |

Rules:

- Sections: `## New this week` then `## Still trending`. New vs returning is the
  only classification; it is carried by section plus the "Nth week" metadata.
- Order within a section: GitHub Trending feed order (rank), never stars.
- Entry line: `- **[owner/repo](url)** — ★ stars (+delta, returning only) · language
  · license · Nth week (returning only)` then `` `Try` `` if applicable. Omit
  unavailable segments; if none remain, omit the ` — `. "(archived)" stays after the name.
- Second line: the one-line description with the existing truncation rules.
- Third line (only when a brief exists): `> *Why now.* … *Use it for.* … *Verdict.*
  Try|Watch|Skip — reason.` Text is md-escaped, newlines collapsed; caps: why_now 320,
  use_for 200, reason 160 chars, word-boundary truncation via `truncate()`.
- No brief (analysis off or failed for that repo): the blockquote and the tag are
  absent; everything else is identical.
- Spacing: tight lists, one blank line before each `##`, the `<!-- digest-data -->`
  marker line last. First line: `N repos on GitHub Trending this week · X new · Y still trending`.
- Any new output surface (issue body, comments, files, anything else a reader sees)
  follows the same roles: same devices, same single jobs, same order rules.

### The same system on the site (scripts/build_site.py)

Same content model, same jobs, translated to HTML with real type and space:

- Type scale 1.25 from 16px: 13 micro (meta, kicker, colophon), 16 body, 20 rank
  numerals, 25 section headings, 31 title. Weights 400 and 700 only. System font stack.
- Spacing unit 8px: 4 inside an entry, 8 before a brief, 24 between entries, 64
  before a section heading. Single column, measure 36rem, 16px gutters on phones.
- Color roles as CSS tokens on `:root` with a dark set under `prefers-color-scheme`:
  ground, ink, muted, line, signal. `signal` is spent only on the Try tag and the
  "N to try" count. Contrast verified with the graphic-design skill's contrast script.
- Signature gesture: the rank column. GitHub Trending's own rank hangs left of every
  entry as the ruler the eye runs down; ranks are non-contiguous per section on purpose.
- The brief is a left-ruled note under its entry; labels italic and muted.
- Before changing the CSS, render `site/index.html` in Chromium at 375px (inside a
  375px iframe: headless Chromium enforces a minimum window width) and at 1200px, in
  light and dark, and critique the screenshots with the graphic-design skill.
