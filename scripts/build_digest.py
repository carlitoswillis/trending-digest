#!/usr/bin/env python3
"""Build an HTML email digest from GitHubTrendingRSS weekly feeds.

Zero dependencies — stdlib only. Writes digest.html to the working directory.
"""
import html
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET

FEEDS = [
    ("This week", "https://mshibanami.github.io/GitHubTrendingRSS/weekly/all.xml"),
]
PER_FEED = 25

def fetch_items(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        tree = ET.parse(r)
    items = []
    for item in tree.iter("item"):
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        desc = item.findtext("description") or ""
        # Descriptions embed stars/language; strip tags for a plain summary.
        desc = re.sub(r"<[^>]+>", " ", desc)
        desc = html.unescape(re.sub(r"\s+", " ", desc)).strip()
        items.append((title, link, desc[:280]))
    return items[:PER_FEED]

def main():
    sections = []
    for name, url in FEEDS:
        try:
            items = fetch_items(url)
        except Exception as e:  # a dead feed shouldn't kill the digest
            sections.append(f"<h2>{name}</h2><p><em>feed error: {html.escape(str(e))}</em></p>")
            continue
        rows = "".join(
            f'<li style="margin-bottom:10px"><a href="{html.escape(link)}">'
            f"<strong>{html.escape(title)}</strong></a><br>"
            f'<span style="color:#555">{html.escape(desc)}</span></li>'
            for title, link, desc in items
        )
        sections.append(f"<h2 style='border-bottom:1px solid #ddd'>{name}</h2><ul>{rows}</ul>")
    body = (
        "<div style='font-family:-apple-system,Helvetica,sans-serif;max-width:680px'>"
        "<h1>GitHub Trending — weekly</h1>" + "".join(sections) + "</div>"
    )
    with open("digest.html", "w") as f:
        f.write(body)
    md = ["# GitHub Trending — weekly\n"]
    for name, url in FEEDS:
        try:
            items = fetch_items(url)
        except Exception as e:
            md.append(f"## {name}\n\n_feed error: {e}_\n")
            continue
        md.append(f"## {name}\n")
        for title, link, desc in items:
            md.append(f"- **[{title}]({link})** — {desc}")
        md.append("")
    with open("digest.md", "w") as f:
        f.write("\n".join(md))
    print(f"wrote digest.html ({len(body)} bytes) and digest.md")

if __name__ == "__main__":
    sys.exit(main())
