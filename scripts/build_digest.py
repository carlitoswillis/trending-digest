#!/usr/bin/env python3
"""Build the weekly GitHub Trending digest (digest.md).

Stdlib only, Python 3.11+. Reads the GitHubTrendingRSS weekly feed, enriches
each repo from the GitHub REST API (stars, language, topics, license) and
compares against prior digest issues in this repository so new repos are
separated from ones that are still trending. Writes digest.md to the working
directory; the last line is a machine-readable marker that future runs read
back to compute star deltas.
"""
import html
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

FEED_URL = "https://mshibanami.github.io/GitHubTrendingRSS/weekly/all.xml"
MAX_REPOS = 25
API = "https://api.github.com"
DEFAULT_REPOSITORY = "carlitoswillis/trending-digest"
ISSUE_TITLE_PREFIX = "Trending digest"
DESC_MAX = 200
MAX_TOPICS = 5
API_TIMEOUT = 15

REPO_LINK_RE = re.compile(r"github\.com/([^/]+)/([^/#?\s]+)")
# Presence in a prior digest is read from entry lines only ("- **[owner/repo](link)**"),
# so a github.com link quoted inside a description never counts as an entry.
ENTRY_LINK_RE = re.compile(r"^- \*\*\[[^\]]*\]\((https://github\.com/[^)\s]+)\)", re.M)
# Everything after the feed's tagline paragraph is README markup we do not want.
FEED_BLOCK_RE = re.compile(r"</?(?:p|br|hr|h[1-6]|div|table|ul|ol|pre|blockquote|img)\b[^>]*>", re.I)
TRAILING_URL_RE = re.compile(r"\s*https?://\S+$")
MD_BLOCK_START_RE = re.compile(r"^([-*+#>]|\d+[.)])(?=\s|$)")
MARKER_RE = re.compile(r"<!--\s*digest-data\s+(\{.*\})\s*-->\s*$", re.S)


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


def md_escape(s):
    """Keep a free-text line from changing the markdown structure around it.

    Escapes a leading block marker ("- ", "# ", "> ", "1. " ...) so the description
    cannot become a nested list, heading or blockquote inside the entry, neutralises
    backticks (an unbalanced one would swallow the topics line) and anything that
    looks like an HTML tag or comment (an unclosed "<!--" would hide the rest of the
    digest up to the marker's "-->").
    """
    s = MD_BLOCK_START_RE.sub(r"\\\1", s)
    s = s.replace("`", "\\`")
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
    """Return up to MAX_REPOS feed items as dicts: owner, repo, name, link, feed_text."""
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


# ------------------------------------------------------------------------ render


def star_key(r):
    return (r["stars"] is None, -(r["stars"] or 0), r["name"].lower())


def group_by_language(repos):
    groups = {}
    for r in repos:
        groups.setdefault(r["language"] or "Other", []).append(r)
    order = sorted(groups.items(), key=lambda kv: (kv[0] == "Other", -len(kv[1]), kv[0].lower()))
    return [(lang, sorted(group, key=star_key)) for lang, group in order]


def entry_lines(r, new):
    name = f"**[{r['name']}]({r['link']})**"
    if r["archived"]:
        name += " (archived)"
    meta = []
    if r["stars"] is not None:
        s = "★ " + fmt_stars(r["stars"])
        if not new and r["delta"] is not None:
            s += f" ({fmt_delta(r['delta'])})"
        meta.append(s)
    if new:
        if r["license"]:
            meta.append(r["license"])
    else:
        meta.append(f"{ordinal(r['weeks'])} week")
        if r["language"]:
            meta.append(r["language"])
    lines = [f"- {name}" + (" — " + " · ".join(meta) if meta else "")]
    description = md_escape(truncate(r["description"] or ""))
    if description:
        lines.append("  " + description)
    if new and r["topics"]:
        lines.append("  " + " ".join(f"`{t}`" for t in r["topics"][:MAX_TOPICS]))
    return lines


def marker_line(repos, date):
    data = {"date": date, "repos": {r["name"]: r["stars"] for r in repos}}
    return "<!-- digest-data " + json.dumps(data, sort_keys=True, separators=(",", ":")) + " -->"


def render(repos, date):
    new = [r for r in repos if r["is_new"]]
    returning = sorted((r for r in repos if not r["is_new"]), key=star_key)
    out = [
        f"# GitHub Trending — week of {date}",
        "",
        f"**{len(repos)} repos** · {len(new)} new · {len(returning)} still trending",
        "",
    ]
    if new:
        out += ["## New this week", ""]
        for lang, group in group_by_language(new):
            out.append(f"### {lang} ({len(group)})")
            for r in group:
                out += entry_lines(r, new=True)
            out.append("")
    if returning:
        out.append("## Still trending")
        for r in returning:
            out += entry_lines(r, new=False)
        out.append("")
    out.append(marker_line(repos, date))
    return "\n".join(out) + "\n"


# -------------------------------------------------------------------------- main


def main():
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
    # A re-run on the same day must not count today's own digest as history.
    digests = [parse_digest(i["body"]) for i in issues if not i["title"].endswith(today)]

    classify(repos, digests)
    text = render(repos, today)
    with open("digest.md", "w", encoding="utf-8") as f:
        f.write(text)

    new = sum(r["is_new"] for r in repos)
    fallbacks = sum(r["fallback"] for r in repos)
    print(
        f"wrote digest.md: {len(repos)} repos, {new} new, {len(repos) - new} still trending, "
        f"{fallbacks} API fallback(s), {len(digests)} prior digest(s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
