#!/usr/bin/env python3
"""Build the GitHub Pages site for the weekly digest.

Stdlib only. Two commands:

    build_site.py add DIGEST_JSON [--briefs BRIEFS_JSON] [--data-dir data/weeks]
        Record one week: writes data/weeks/YYYY-MM-DD.json with the briefs merged in.

    build_site.py render [--data-dir data/weeks] [--out site]
        Render every recorded week: site/index.html (latest), site/weeks/DATE.html.

The page follows the digest's design system (CLAUDE.md), translated to HTML:
bold is the repo name, the one accent is the Try tag, the brief is an indented
note under its entry, italics are the brief's three labels, two section headings.
The signature gesture is the rank column: GitHub Trending's own rank, hanging to
the left of every entry, is the ruler the eye runs down.
"""
import argparse
import html
import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_digest as bd  # noqa: E402

DATA_DIR = "data/weeks"
OUT_DIR = "site"
MAX_WEEKS = 52
SITE_TITLE = "GitHub Trending, weekly"


# ------------------------------------------------------------------------- data


def week_path(data_dir, day):
    return Path(data_dir) / f"{day}.json"


def add_week(digest_json, briefs_json=None, data_dir=DATA_DIR):
    """Merge digest.json + briefs.json into one record for the week and save it."""
    with open(digest_json, encoding="utf-8") as f:
        data = json.load(f)
    repos, day = data["repos"], data["date"]
    date.fromisoformat(day)  # validate
    # plain text: the page escapes for HTML at render time
    briefs = bd.load_briefs(briefs_json, [r["name"] for r in repos], escape=False) if briefs_json else {}
    for r in repos:
        r["brief"] = briefs.get(r["name"].lower())
    record = {"date": day, "repos": repos}
    path = week_path(data_dir, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    return path


def load_weeks(data_dir=DATA_DIR):
    """All recorded weeks, newest first, one per ISO week (newest date wins)."""
    weeks, seen = [], set()
    files = sorted(Path(data_dir).glob("*.json"), reverse=True) if Path(data_dir).is_dir() else []
    for path in files:
        try:
            with open(path, encoding="utf-8") as f:
                record = json.load(f)
            day = date.fromisoformat(record["date"])
            repos = record["repos"]
            if not isinstance(repos, list):
                raise ValueError("repos is not a list")
        except (OSError, ValueError, KeyError, TypeError) as e:
            bd.log(f"skipping {path}: {type(e).__name__}: {e}")
            continue
        key = day.isocalendar()[:2]
        if key in seen:
            continue
        seen.add(key)
        weeks.append(record)
    return weeks[:MAX_WEEKS]


# ------------------------------------------------------------------------ render


def esc(s):
    return html.escape(s or "", quote=True)


def long_date(day):
    d = date.fromisoformat(day)
    return f"{d.day} {d.strftime('%B %Y')}"


def short_date(day):
    d = date.fromisoformat(day)
    return f"{d.day} {d.strftime('%b')}"


def week_slug(day):
    return f"weeks/{day}.html"


def entry_html(r):
    new = r.get("is_new", True)
    brief = r.get("brief")
    is_try = bool(brief and brief.get("verdict") == "Try")
    name = esc(r["name"])
    if r.get("archived"):
        name += ' <span class="muted">(archived)</span>'
    meta = []
    stars = r.get("stars")
    if stars is not None:
        s = "★ " + bd.fmt_stars(stars)
        if not new and r.get("delta") is not None:
            s += f" ({bd.fmt_delta(r['delta'])})"
        meta.append(s)
    if r.get("language"):
        meta.append(esc(r["language"]))
    if r.get("license"):
        meta.append(esc(r["license"]))
    if not new:
        meta.append(f"{bd.ordinal(r.get('weeks', 2))} week")
    rank = r.get("rank")
    lines = [
        f'<li class="entry" value="{int(rank) if rank else 0}">',
        f'<span class="rank" aria-hidden="true">{int(rank) if rank else ""}</span>',
        '<div class="body">',
        f'<p class="head"><a class="name" href="{esc(r["link"])}">{name}</a>'
        + (' <span class="tag">Try</span>' if is_try else "")
        + "</p>",
    ]
    if meta:
        lines.append(f'<p class="meta">{" · ".join(meta)}</p>')
    description = bd.truncate(bd.strip_links(r.get("description") or ""))
    if description:
        lines.append(f'<p class="desc">{esc(description)}</p>')
    if brief:
        parts = []
        if brief.get("why_now"):
            parts.append(f"<i>Why now.</i> {esc(brief['why_now'])}")
        if brief.get("use_for"):
            parts.append(f"<i>Use it for.</i> {esc(brief['use_for'])}")
        verdict = esc(brief.get("verdict", ""))
        if brief.get("reason"):
            verdict += f" — {esc(brief['reason'])}"
        parts.append(f"<i>Verdict.</i> {verdict}")
        lines.append(f'<p class="brief">{" ".join(parts)}</p>')
    lines += ["</div>", "</li>"]
    return "\n".join(lines)


def section_html(heading, repos):
    if not repos:
        return ""
    items = "\n".join(entry_html(r) for r in repos)
    return f'<section>\n<h2>{esc(heading)}</h2>\n<ol class="shelf">\n{items}\n</ol>\n</section>'


def standfirst(repos, new, returning):
    tries = sum(1 for r in repos if r.get("brief") and r["brief"].get("verdict") == "Try")
    # the kicker above already says "GitHub Trending, weekly"; do not repeat it
    parts = [bd.plural(len(repos), "repo"), f"{len(new)} new", f"{len(returning)} still trending"]
    text = " · ".join(esc(p) for p in parts)
    if tries:
        text += f' · <span class="try-count">{tries} to try</span>'
    return text


def page_html(record, weeks, *, is_index, root):
    """One week's page. `root` is the relative path prefix back to the site root."""
    day = record["date"]
    repos = sorted(record["repos"], key=bd.rank_key)
    new = [r for r in repos if r.get("is_new", True)]
    returning = [r for r in repos if not r.get("is_new", True)]
    others = [w for w in weeks if w["date"] != day]
    archive = ""
    if others:
        links = " · ".join(
            f'<a href="{root}{week_slug(w["date"])}">{esc(short_date(w["date"]))}</a>' for w in others
        )
        archive = f'<h2>Other weeks</h2>\n<p class="archive">{links}</p>'
    latest_note = ""
    if not is_index and weeks and weeks[0]["date"] != day:
        latest_note = f'<p class="muted"><a href="{root}">Latest week</a></p>'
    title = f"Week of {long_date(day)}"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" media="(prefers-color-scheme: light)" content="#faf9f6">
<meta name="theme-color" media="(prefers-color-scheme: dark)" content="#151412">
<title>{esc(title)} · {SITE_TITLE}</title>
<style>{CSS}</style>
</head>
<body>
<main>
<header>
<p class="kicker">{SITE_TITLE}</p>
<h1>{esc(title)}</h1>
<p class="standfirst">{standfirst(repos, new, returning)}</p>
{latest_note}
</header>
{section_html("New this week", new)}
{section_html("Still trending", returning)}
<footer>
{archive}
<p class="colophon">Ranks are GitHub Trending's weekly order via GitHubTrendingRSS; stars, language and license from the GitHub API; briefs written by Claude in the weekly Action.</p>
</footer>
</main>
</body>
</html>
"""


CSS = """
:root {
  --ground: #faf9f6; --ink: #1a1a18; --muted: #6f6d67; --line: #e3e1da; --signal: #9a2c07;
  --u: 8px;
  --f-micro: 13px; --f-body: 16px; --f-sub: 20px; --f-section: 25px; --f-title: 31px;
  --measure: 36rem;
}
@media (prefers-color-scheme: dark) {
  :root { --ground: #151412; --ink: #ebe9e3; --muted: #96948c; --line: #2e2c28; --signal: #ffa580; }
}
* { box-sizing: border-box; }
html { background: var(--ground); color: var(--ink); -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  font-size: var(--f-body); line-height: 1.5;
}
main {
  max-width: calc(var(--measure) + 3rem);
  margin: 0 auto;
  padding: calc(6 * var(--u)) 1rem calc(12 * var(--u));
}
@media (min-width: 40rem) {
  main { padding: calc(10 * var(--u)) 2rem calc(16 * var(--u)); }
  .entry { column-gap: 1rem; }
  header, footer, h2 { margin-left: 3.5rem; }
}
a { color: inherit; text-decoration: none; }
a:hover, a:focus-visible { text-decoration: underline; text-underline-offset: 0.15em; }
p { margin: 0; }
.muted { color: var(--muted); }

header { margin-left: 3rem; }
.kicker { font-size: var(--f-micro); color: var(--muted); line-height: 1.4; }
h1 { font-size: var(--f-title); font-weight: 700; line-height: 1.1; letter-spacing: -0.01em; margin: var(--u) 0 0; }
.standfirst { font-size: var(--f-body); color: var(--muted); margin-top: calc(2 * var(--u)); }
.try-count { color: var(--signal); font-weight: 700; white-space: nowrap; }
header .muted { margin-top: var(--u); font-size: var(--f-micro); }

h2 { font-size: var(--f-section); font-weight: 700; line-height: 1.2; margin: calc(8 * var(--u)) 0 calc(3 * var(--u)) 3rem; }

.shelf { list-style: none; margin: 0; padding: 0; }
.entry { display: grid; grid-template-columns: 2.5rem 1fr; column-gap: 0.5rem; padding-bottom: calc(3 * var(--u)); }
.entry:last-child { padding-bottom: 0; }
.rank {
  font-size: var(--f-sub); line-height: 1.2; font-variant-numeric: tabular-nums;
  color: var(--muted); text-align: right; padding-top: 0.05em;
}
.body { min-width: 0; }
.head { line-height: 1.5; }
.name { font-weight: 700; overflow-wrap: anywhere; }
.tag { color: var(--signal); font-weight: 700; font-size: var(--f-micro); letter-spacing: 0.02em; margin-left: 0.5rem; }
.meta { font-size: var(--f-micro); line-height: 1.4; color: var(--muted); font-variant-numeric: tabular-nums; }
.desc { margin-top: calc(0.5 * var(--u)); }
.brief { margin-top: var(--u); padding-left: calc(1.5 * var(--u)); border-left: 2px solid var(--line); }
.brief i { color: var(--muted); }

footer { margin-left: 3rem; }
.archive { color: var(--muted); }
.archive a { color: var(--ink); }
.colophon { margin-top: calc(8 * var(--u)); font-size: var(--f-micro); line-height: 1.4; color: var(--muted); }
"""


def render_site(data_dir=DATA_DIR, out_dir=OUT_DIR):
    weeks = load_weeks(data_dir)
    if not weeks:
        bd.log(f"error: no week records in {data_dir}; run `add` first")
        return 1
    out = Path(out_dir)
    (out / "weeks").mkdir(parents=True, exist_ok=True)
    for i, record in enumerate(weeks):
        (out / "weeks" / f"{record['date']}.html").write_text(
            page_html(record, weeks, is_index=False, root="../"), encoding="utf-8"
        )
    (out / "index.html").write_text(page_html(weeks[0], weeks, is_index=True, root=""), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    print(f"wrote {out}/index.html and {len(weeks)} week page(s); latest {weeks[0]['date']}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    ap = sub.add_parser("add", help="record one week from digest.json (+ briefs.json)")
    ap.add_argument("digest_json")
    ap.add_argument("--briefs", metavar="FILE")
    ap.add_argument("--data-dir", default=DATA_DIR)
    rp = sub.add_parser("render", help="render every recorded week into the site directory")
    rp.add_argument("--data-dir", default=DATA_DIR)
    rp.add_argument("--out", default=OUT_DIR)
    args = parser.parse_args(argv)
    if args.command == "add":
        path = add_week(args.digest_json, args.briefs, args.data_dir)
        print(f"recorded {path}")
        return 0
    return render_site(args.data_dir, args.out)


if __name__ == "__main__":
    sys.exit(main())
