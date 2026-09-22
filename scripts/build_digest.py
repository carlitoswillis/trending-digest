#!/usr/bin/env python3
"""Build the weekly GitHub Trending digest (digest.md).

Stdlib only, Python 3.11+. Two modes:

    build_digest.py                          (default) fetch feed + API + history
    build_digest.py render --briefs FILE     offline: fold research briefs in

The build reads the GitHubTrendingRSS weekly feed, enriches each repo from the
GitHub REST API (stars, language, license, ...) and compares against prior
digest issues in this repository so new repos are separated from ones that are
still trending. It writes digest.json (the data, in feed order) and digest.md
(no briefs) to the working directory. The last line of digest.md is a
machine-readable marker that future runs read back to compute star deltas.

The render mode does no network: it reads digest.json and briefs.json and writes
digest.md again with a one-line brief under each entry that has one. A missing
or unreadable briefs file is logged and the digest is written without briefs,
so the issue is never blocked on the research step.
"""
import argparse
import html
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone

FEED_URL = "https://mshibanami.github.io/GitHubTrendingRSS/weekly/all.xml"
MAX_REPOS = 25
API = "https://api.github.com"
DEFAULT_REPOSITORY = "carlitoswillis/trending-digest"
ISSUE_TITLE_PREFIX = "Trending digest"
DESC_MAX = 200
API_TIMEOUT = 15
DIGEST_JSON = "digest.json"
DIGEST_MD = "digest.md"

# Brief text caps (chars, word-boundary truncation via truncate()).
WHY_NOW_MAX = 320
USE_FOR_MAX = 200
REASON_MAX = 160
VERDICTS = ("Try", "Watch", "Skip")

REPO_LINK_RE = re.compile(r"github\.com/([^/]+)/([^/#?\s]+)")
# Presence in a prior digest is read from entry lines only ("- **[owner/repo](link)**"),
# so a github.com link quoted inside a description never counts as an entry.
ENTRY_LINK_RE = re.compile(r"^- \*\*\[[^\]]*\]\((https://github\.com/[^)\s]+)\)", re.M)
# Everything after the feed's tagline paragraph is README markup we do not want.
FEED_BLOCK_RE = re.compile(r"</?(?:p|br|hr|h[1-6]|div|table|ul|ol|pre|blockquote|img)\b[^>]*>", re.I)
TRAILING_URL_RE = re.compile(r"\s*https?://\S+$")
# A backslash escapes the marker character itself ("\-", "\#"); for an ordered
# list it must go before the "." or ")" since "\1" is not a CommonMark escape.
MD_BLOCK_START_RE = re.compile(r"^([-*+#>])(?=\s|$)")
MD_ORDERED_START_RE = re.compile(r"^(\d+)([.)])(?=\s|$)")
MARKER_RE = re.compile(r"<!--\s*digest-data\s+(\{.*\})\s*-->\s*$", re.S)
MD_UNDERSCORE_RE = re.compile(r"(?<!\w)_|_(?!\w)")
MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
BARE_URL_RE = re.compile(r"\s*(?:https?://|www\.)\S+")
# GitHub autolinks @user and #123 in issue bodies after markdown rendering, so a
# backslash cannot stop them; a zero-width space after the sigil does, invisibly.
MENTION_RE = re.compile(r"@(?=\w)")
ISSUE_REF_RE = re.compile(r"#(?=\d)")
ZWSP = "​"

# Keys entry_lines()/marker_line() read from every digest.json repo entry.
RENDER_KEYS = ("name", "link", "archived", "stars", "language", "license", "description", "is_new", "weeks", "delta")


def log(msg):
    print(msg, file=sys.stderr)


# --------------------------------------------------------------------------- text


def flatten_html(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return html.unescape(re.sub(r"\s+", " ", s)).strip()


def clean_text(s):
    return re.sub(r"\s+", " ", s or "").strip()


def truncate(s, limit=DESC_MAX):
    """Cut at a word boundary and append an ellipsis only when longer than limit.

    The word boundary is only honoured when it keeps at least half the budget,
    so one very long token (a URL, say) cannot shrink the result to "a…".
    Returns "" when nothing readable is left, so the caller omits the line.
    """
    if len(s) <= limit:
        return s
    cut = s[: limit - 1]
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    cut = cut.rstrip(" ,;:-—")
    return cut + "…" if cut else ""


def first_sentence(text):
    m = re.match(r"(.+?[.!?])(?=\s|$)", text)
    return m.group(1) if m else text


def tagline_from_feed(raw):
    """Feed fallback: the tagline paragraph only, first sentence, capped at DESC_MAX.

    The feed description is the repo tagline followed by the homepage and the top of
    the README as HTML, so cut on HTML structure first (end of the first paragraph or
    the first block-level tag), then drop a trailing bare URL, then apply the
    sentence / length caps to the flattened text.
    """
    head = ""
    for chunk in FEED_BLOCK_RE.split(raw or ""):  # first block with visible text wins
        head = flatten_html(chunk)
        if head:
            break
    head = TRAILING_URL_RE.sub("", head).strip()
    return truncate(first_sentence(head))


def strip_links(s):
    """Plain prose only: markdown links keep their text, bare URLs go.

    The repo name is the only link in the digest; a second link in the muted
    layer (or in a brief) competes with it on the scan. GFM autolinks bare
    http(s):// and www. URLs, so they are removed rather than escaped.
    """
    s = MD_LINK_RE.sub(r"\1", s or "")
    s = BARE_URL_RE.sub("", s)
    return clean_text(s).rstrip(" ,;:-—")


def md_escape(s, block_start=True):
    """Keep a free-text line from changing the markdown structure around it.

    Escapes a leading block marker ("- ", "# ", "> ", "1. " ...) so the description
    cannot become a nested list, heading or blockquote inside the entry (skipped
    with block_start=False for text that never starts a line, such as brief
    fields), neutralises backticks (a code span is reserved for the Try tag),
    asterisks and word-boundary underscores (bold is reserved for repo names,
    italics for the brief labels), link brackets and strikethrough tildes, breaks
    @user and #123 autolinks (a stray @mention in a public issue notifies that
    user) and anything that looks like an HTML tag or comment (an unclosed "<!--"
    would hide the rest of the digest up to the marker's "-->"). Intraword
    underscores (snake_case, URLs) are left alone: they cannot open emphasis in GFM.
    """
    if block_start:
        s = MD_BLOCK_START_RE.sub(r"\\\1", s)
        s = MD_ORDERED_START_RE.sub(r"\1\\\2", s)
    s = s.replace("`", "\\`").replace("*", "\\*").replace("[", "\\[").replace("~", "\\~")
    s = MD_UNDERSCORE_RE.sub(r"\\_", s)
    s = MENTION_RE.sub("@" + ZWSP, s)
    s = ISSUE_REF_RE.sub("#" + ZWSP, s)
    return re.sub(r"<(?=[/!?A-Za-z])", "&lt;", s)


def fmt_stars(n):
    """<1000 as-is, <1M as 12.3k, else 1.2M; rounding carries into the next unit."""
    if n < 1000:
        return str(n)
    k = round(n / 1000, 1)
    if k < 1000:
        return f"{k:.1f}".removesuffix(".0") + "k"
    return f"{round(n / 1_000_000, 1):.1f}".removesuffix(".0") + "M"


def fmt_delta(d):
    return ("-" if d < 0 else "+") + fmt_stars(abs(d))


def ordinal(n):
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# ------------------------------------------------------------------------ network


def api_headers(token):
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "trending-digest",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def get_json(url, token=None, timeout=API_TIMEOUT):
    req = urllib.request.Request(url, headers=api_headers(token))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def fetch_feed(url=FEED_URL):
    """Return up to MAX_REPOS feed items as dicts: owner, repo, name, link, feed_text, rank.

    rank is the 1-based position in the feed; the digest is rendered in that order.
    """
    with urllib.request.urlopen(url, timeout=30) as r:
        root = ET.fromstring(r.read())
    items, seen = [], set()
    for item in root.iter("item"):
        link = (item.findtext("link") or "").strip()
        m = REPO_LINK_RE.search(link)
        if not m:
            log(f"skipping feed item with unrecognised link: {link!r}")
            continue
        owner, repo = m.group(1), m.group(2)
        name = f"{owner}/{repo}"
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        items.append({
            "owner": owner,
            "repo": repo,
            "name": name,
            "link": f"https://github.com/{name}",
            "feed_text": item.findtext("description") or "",
            "rank": len(items) + 1,
        })
        if len(items) >= MAX_REPOS:
            break
    return items


def fetch_repo(owner, repo, token=None):
    return get_json(f"{API}/repos/{owner}/{repo}", token)


def fetch_history(repository=None, token=None):
    """Return prior digest issues (title, body, created_at), newest first."""
    repository = repository or os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPOSITORY
    url = f"{API}/repos/{repository}/issues?state=all&per_page=20&sort=created&direction=desc"
    issues = get_json(url, token)
    if not isinstance(issues, list):
        raise ValueError("issues endpoint did not return a list")
    out = []
    for issue in issues:
        if not isinstance(issue, dict) or "pull_request" in issue:
            continue
        title = issue.get("title") or ""
        if title.startswith(ISSUE_TITLE_PREFIX):
            out.append({
                "title": title,
                "body": issue.get("body") or "",
                "created_at": issue.get("created_at") or "",
            })
    out.sort(key=lambda i: i["created_at"], reverse=True)
    return out


# ------------------------------------------------------------------------- model


def fallback_repo(item):
    return {
        **item,
        "description": tagline_from_feed(item["feed_text"]),
        "language": None,
        "stars": None,
        "forks": None,
        "topics": [],
        "license": None,
        "homepage": None,
        "archived": False,
        "fallback": True,
    }


def enrich(item, token=None):
    """Merge GitHub API metadata into a feed item; never raises."""
    try:
        data = fetch_repo(item["owner"], item["repo"], token)
        if not isinstance(data, dict):
            raise ValueError("unexpected JSON shape")
        return repo_from_api(item, data)
    except Exception as e:  # HTTPError, URLError, timeout, bad JSON, unexpected shape ...
        log(f"fallback: {item['name']}: {type(e).__name__}: {e}")
        return fallback_repo(item)


def repo_from_api(item, data):
    """Pick the fields we render out of a /repos/{owner}/{repo} response, defensively."""
    lic = data.get("license")
    license_id = lic.get("spdx_id") if isinstance(lic, dict) else None
    if not isinstance(license_id, str) or license_id in ("", "NOASSERTION"):
        license_id = None
    stars = data.get("stargazers_count")
    forks = data.get("forks_count")
    desc = data.get("description")
    description = clean_text(desc if isinstance(desc, str) else "") or tagline_from_feed(item["feed_text"])
    topics = data.get("topics")
    language = data.get("language")
    homepage = data.get("homepage")
    return {
        **item,
        "description": description,
        "language": language if isinstance(language, str) and language else None,
        "stars": stars if isinstance(stars, int) and not isinstance(stars, bool) else None,
        "forks": forks if isinstance(forks, int) and not isinstance(forks, bool) else None,
        "topics": [t for t in topics if isinstance(t, str)] if isinstance(topics, list) else [],
        "license": license_id,
        "homepage": homepage if isinstance(homepage, str) and homepage else None,
        "archived": bool(data.get("archived")),
        "fallback": False,
    }


def parse_digest(body):
    """Extract repos present in a prior digest body and the star map from its marker."""
    present, stars, date = set(), {}, None
    for m in ENTRY_LINK_RE.finditer(body):
        lm = REPO_LINK_RE.search(m.group(1))
        if lm:
            present.add(f"{lm.group(1)}/{lm.group(2)}".lower())
    lines = body.rstrip().splitlines()
    if lines:
        mm = MARKER_RE.search(lines[-1])
        if mm:
            try:
                data = json.loads(mm.group(1))
                date = data.get("date")
                for name, value in (data.get("repos") or {}).items():
                    present.add(name.lower())
                    stars[name.lower()] = value if isinstance(value, int) else None
            except (ValueError, AttributeError) as e:
                log(f"ignoring unreadable digest-data marker: {e}")
    return {"present": present, "stars": stars, "date": date}


def digest_week(text):
    """ISO (year, week) of the YYYY-MM-DD that ends a digest title; the text itself if none."""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})\s*$", text or "")
    if not m:
        return text
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isocalendar()[:2]
    except ValueError:
        return text


def classify(repos, digests):
    """Annotate each repo with is_new, weeks and delta. digests is newest first."""
    for r in repos:
        key = r["name"].lower()
        seen_in = [d for d in digests if key in d["present"]]
        r["is_new"] = not seen_in
        r["weeks"] = 1 + len(seen_in)
        r["delta"] = None
        if r["stars"] is not None:
            for d in digests:
                prev = d["stars"].get(key)
                if prev is not None:
                    r["delta"] = r["stars"] - prev
                    break


# ------------------------------------------------------------------------ briefs


def brief_text(value, limit):
    """One-line, escaped, capped brief field; "" when the value is unusable."""
    if not isinstance(value, str):
        return ""
    # Brief fields follow a run-in label mid-line, so a leading "- " or "1. " can
    # never open a block there; only the inline escapes apply.
    return md_escape(truncate(strip_links(value), limit), block_start=False)


def clean_brief(name, raw):
    """Validate one briefs.json entry; None (with a log line) when it must be dropped."""
    if not isinstance(raw, dict):
        log(f"briefs: {name}: ignoring non-object entry")
        return None
    verdict = raw.get("verdict")
    verdict = verdict.strip() if isinstance(verdict, str) else verdict
    if verdict not in VERDICTS:
        log(f"briefs: {name}: dropping brief with invalid verdict {verdict!r} (expected one of {', '.join(VERDICTS)})")
        return None
    return {
        "why_now": brief_text(raw.get("why_now"), WHY_NOW_MAX),
        "use_for": brief_text(raw.get("use_for"), USE_FOR_MAX),
        "verdict": verdict,
        "reason": brief_text(raw.get("reason"), REASON_MAX),
    }


def load_briefs(path, names=()):
    """Read briefs.json into {lowercased "owner/repo": brief}. Never raises.

    Any problem with the file as a whole (missing, unreadable, not JSON, not an
    object) is logged and yields {} so the digest still ships without briefs.
    Unknown repo keys are logged and ignored.
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        log(f"briefs: {path} not found; rendering without briefs")
        return {}
    except (OSError, ValueError) as e:
        log(f"briefs: could not read {path} ({type(e).__name__}: {e}); rendering without briefs")
        return {}
    if not isinstance(data, dict):
        log(f"briefs: {path} is not a JSON object; rendering without briefs")
        return {}
    known = {n.lower() for n in names}
    briefs = {}
    for name, raw in data.items():
        key = str(name).strip().lower()
        if known and key not in known:
            log(f"briefs: ignoring unknown repo {name!r}")
            continue
        brief = clean_brief(name, raw)
        if brief is not None:
            briefs[key] = brief
    return briefs


# ------------------------------------------------------------------------ render


def rank_key(r):
    return (r.get("rank") is None, r.get("rank") or 0, r["name"].lower())


def entry_lines(r, brief=None):
    """The lines for one repo: entry line, optional description, optional brief.

    Entry line: bold name (the only bold in the body), "(archived)", then the plain
    metadata "stars (+delta) · language · license · Nth week" with unavailable
    segments omitted, then the `Try` tag (the only code span) when the brief says so.
    """
    new = r["is_new"]
    name = f"**[{r['name']}]({r['link']})**"
    if r["archived"]:
        name += " (archived)"
    meta = []
    if r["stars"] is not None:
        s = "★ " + fmt_stars(r["stars"])
        if not new and r["delta"] is not None:
            s += f" ({fmt_delta(r['delta'])})"
        meta.append(s)
    if r["language"]:
        meta.append(r["language"])
    if r["license"]:
        meta.append(r["license"])
    if not new:
        meta.append(f"{ordinal(r['weeks'])} week")
    line = f"- {name}"
    if meta:
        line += " — " + " · ".join(meta)
    if brief and brief["verdict"] == "Try":
        line += " `Try`"
    lines = [line]
    description = md_escape(truncate(strip_links(r["description"])))
    if description:
        lines.append("  " + description)
    if brief:
        lines.append("  " + brief_line(brief))
    return lines


def brief_line(brief):
    """One blockquote line with the three run-in italic labels."""
    parts = []
    if brief["why_now"]:
        parts.append(f"*Why now.* {brief['why_now']}")
    if brief["use_for"]:
        parts.append(f"*Use it for.* {brief['use_for']}")
    verdict = brief["verdict"]
    if brief["reason"]:
        verdict += f" — {brief['reason']}"
    parts.append(f"*Verdict.* {verdict}")
    return "> " + " ".join(parts)


def marker_line(repos, date):
    data = {"date": date, "repos": {r["name"]: r["stars"] for r in repos}}
    return "<!-- digest-data " + json.dumps(data, sort_keys=True, separators=(",", ":")) + " -->"


def plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def render(repos, date, briefs=None):
    """digest.md body: standfirst, the two ranked sections, the marker line last.

    Both sections keep GitHub Trending feed order (rank). Lists are tight; there is
    one blank line before each heading and before the marker.
    """
    briefs = briefs or {}
    repos = sorted(repos, key=rank_key)
    new = [r for r in repos if r["is_new"]]
    returning = [r for r in repos if not r["is_new"]]
    out = [f"{plural(len(repos), 'repo')} on GitHub Trending this week · {len(new)} new · {len(returning)} still trending"]
    for heading, group in (("## New this week", new), ("## Still trending", returning)):
        if not group:
            continue
        out += ["", heading]
        for r in group:
            out += entry_lines(r, briefs.get(r["name"].lower()))
    out += ["", marker_line(repos, date)]
    return "\n".join(out) + "\n"


# -------------------------------------------------------------------------- main


def write_text(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def build():
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or None
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        items = fetch_feed()
    except Exception as e:
        log(f"error: could not fetch trending feed {FEED_URL}: {type(e).__name__}: {e}")
        return 1
    if not items:
        log(f"error: trending feed {FEED_URL} contained no repos")
        return 1

    repos = [enrich(item, token) for item in items]

    try:
        issues = fetch_history(token=token)
    except Exception as e:
        log(f"warning: could not fetch prior digests ({type(e).__name__}: {e}); treating every repo as new")
        issues = []
    # History is one digest per ISO week: a re-run this week must not count this
    # week's earlier digest as history, and a past week that was run twice counts
    # once (newest issue wins; issues arrive newest first).
    this_week = digest_week(today)
    digests, seen_weeks = [], set()
    for issue in issues:
        week = digest_week(issue["title"])
        if week == this_week or week in seen_weeks:
            continue
        seen_weeks.add(week)
        digests.append(parse_digest(issue["body"]))

    classify(repos, digests)
    # digest.json is the input to the research step and to `render`; the raw feed
    # HTML is the one field nobody downstream needs.
    data = {"date": today, "repos": [{k: v for k, v in r.items() if k != "feed_text"} for r in repos]}
    write_text(DIGEST_JSON, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    write_text(DIGEST_MD, render(repos, today))

    new = sum(r["is_new"] for r in repos)
    fallbacks = sum(r["fallback"] for r in repos)
    print(
        f"wrote {DIGEST_MD} and {DIGEST_JSON}: {len(repos)} repos, {new} new, {len(repos) - new} still trending, "
        f"{fallbacks} API fallback(s), {len(digests)} prior digest(s)"
    )
    return 0


def render_from_files(briefs_path=None):
    try:
        with open(DIGEST_JSON, encoding="utf-8") as f:
            data = json.load(f)
        repos, date = data["repos"], data["date"]
        if not isinstance(repos, list) or not isinstance(date, str):
            raise ValueError("unexpected shape")
    except (OSError, ValueError, KeyError, TypeError) as e:
        log(f"error: could not read {DIGEST_JSON} ({type(e).__name__}: {e}); run the build first")
        return 1
    # A damaged digest.json must fail with one clear line, not a traceback, and
    # must leave the build's digest.md in place (the workflow files that instead).
    for i, r in enumerate(repos, 1):
        if not isinstance(r, dict):
            log(f"error: {DIGEST_JSON} repo #{i} is not an object; run the build first")
            return 1
        missing = [k for k in RENDER_KEYS if k not in r]
        if missing:
            log(f"error: {DIGEST_JSON} repo #{i} is missing {', '.join(missing)}; run the build first")
            return 1
    briefs = load_briefs(briefs_path, [r["name"] for r in repos]) if briefs_path else {}
    try:
        text = render(repos, date, briefs)
    except Exception as e:  # a field of the wrong type, say; digest.md is untouched
        log(f"error: could not render {DIGEST_JSON} ({type(e).__name__}: {e}); run the build first")
        return 1
    write_text(DIGEST_MD, text)
    print(f"wrote {DIGEST_MD}: {len(repos)} repos, {len(briefs)} brief(s)")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("build", help="fetch feed, API and history; write digest.json and digest.md (default)")
    rp = sub.add_parser("render", help="offline: re-render digest.md from digest.json, folding briefs in")
    rp.add_argument("--briefs", metavar="FILE", help="briefs.json written by the research step")
    args = parser.parse_args(argv)
    if args.command == "render":
        return render_from_files(args.briefs)
    return build()


if __name__ == "__main__":
    sys.exit(main())
