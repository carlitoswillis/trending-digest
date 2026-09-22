# trending-digest

Emails me a weekly GitHub Trending digest built from the GitHubTrendingRSS weekly feed. Each entry carries stars, language and license from the GitHub API, and repos are split into "new this week" versus "still trending" (with week count and star delta) by comparing against the previous digest issues. Runs as a scheduled GitHub Action Mondays; also runnable manually from the Actions tab.

Delivery: files a GitHub issue each week; GitHub emails the notification. The base digest needs no secrets.

## Research briefs (optional)

With one secret set, the workflow runs Claude Code in the runner after the digest is built. For each repo it reads the README, the latest release, the most-discussed open issues and recent web coverage, then writes a one-line brief under the entry: *Why now.* *Use it for.* *Verdict.* (Try / Watch / Skip, with a reason). Repos with a Try verdict get a `Try` tag on their scan line. The instructions Claude follows are in `scripts/brief_prompt.md`.

No API key is involved: usage bills the Claude subscription tied to the OAuth token.

Setup:

1. Locally, run `claude setup-token` and copy the token it prints.
2. In the repo, add it as the Actions secret `CLAUDE_CODE_OAUTH_TOKEN` (Settings → Secrets and variables → Actions).

That is all. The research step is `continue-on-error` with a 25-minute timeout, so the issue is filed every week whether or not briefs succeeded; repos without a brief simply show no blockquote.

Claude reads untrusted content (READMEs, web pages), so the workflow boxes it in: research runs in a read-only `build` job (no token that can write issues reaches it), its only writable file is `briefs.json`, and the fold step renders from the build's own copy of `digest.json` after restoring tracked files. A second `file` job with `issues: write` posts the result.

Switch it off (any one of these):

- Set the repo variable `DIGEST_ANALYSIS` to `off` (Settings → Secrets and variables → Actions → Variables).
- Run the workflow manually with the "Add Claude research briefs" checkbox unticked.
- Delete the `CLAUDE_CODE_OAUTH_TOKEN` secret.

The "Decide whether to research" step logs which of these applied.

## The web version

Each run also records the week under `data/weeks/` and deploys a designed, phone-first page to GitHub Pages with an archive of past weeks. The email's first line links to it. The `publish` job enables Pages on first run; if it fails, enable Pages with source "GitHub Actions" under Settings → Pages. Pages requires the repo to be public on a free plan.

## Development

    python3 tests/test_digest.py
    python3 tests/test_site.py

`scripts/build_digest.py` builds `digest.json` and `digest.md`; `scripts/build_digest.py render --briefs briefs.json` folds briefs into `digest.md` offline. See `CLAUDE.md` for the digest's design rules.
