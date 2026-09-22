#!/usr/bin/env python3
"""Offline checks for scripts/build_site.py (stdlib only; run from any cwd)."""
import contextlib
import io
import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import build_site as bs  # noqa: E402

passed = 0


def check(cond, msg):
    global passed
    if not cond:
        raise AssertionError(msg)
    passed += 1
    print(f"  ok: {msg}")


def repo(name, rank, *, new=True, weeks=1, delta=None, stars=1234, language="Python", license="MIT",
         description="A tool.", archived=False):
    return {
        "name": name, "link": f"https://github.com/{name}", "owner": name.split("/")[0], "repo": name.split("/")[1],
        "description": description, "language": language, "stars": stars, "forks": None, "topics": [],
        "license": license, "homepage": None, "archived": archived, "fallback": False,
        "is_new": new, "weeks": weeks, "delta": delta, "rank": rank,
    }


REPOS = [
    repo("acme/tool", 1, description="Fast <script>alert(1)</script> & safe"),
    repo("old/thing", 2, new=False, weeks=3, delta=1200, stars=45100, language="Rust", license=None),
    repo("big/one", 3, stars=1_234_567, license="Apache-2.0", archived=True),
    repo("ghost/none", 4, stars=None, language=None, description=""),
]
BRIEFS = {
    "ACME/tool": {"why_now": "Shipped 1.0 <b>now</b>.", "use_for": "Doing the thing.", "verdict": "Try", "reason": "you need it."},
    "old/thing": {"why_now": "Still climbing.", "use_for": "Other things.", "verdict": "Skip", "reason": "duplicate."},
    "big/one": {"why_now": "x", "use_for": "y", "verdict": "Maybe", "reason": "z"},
    "unknown/repo": {"why_now": "x", "use_for": "y", "verdict": "Try", "reason": "z"},
}

tmp = tempfile.TemporaryDirectory()
root = Path(tmp.name)
data_dir = root / "weeks"
digest_json = root / "digest.json"
briefs_json = root / "briefs.json"
digest_json.write_text(json.dumps({"date": "2026-09-21", "repos": REPOS}), encoding="utf-8")
briefs_json.write_text(json.dumps(BRIEFS), encoding="utf-8")

print("== add ==")
err = io.StringIO()
with contextlib.redirect_stderr(err):
    path = bs.add_week(str(digest_json), str(briefs_json), str(data_dir))
rec = json.loads(path.read_text(encoding="utf-8"))
by = {r["name"]: r for r in rec["repos"]}
check(path.name == "2026-09-21.json" and rec["date"] == "2026-09-21", "week file named by date")
check(by["acme/tool"]["brief"]["verdict"] == "Try", "brief matched case-insensitively")
check(by["big/one"]["brief"] is None and "invalid verdict" in err.getvalue(), "bad verdict dropped")
check(by["ghost/none"]["brief"] is None, "repo without a brief has none")
check("unknown repo" in err.getvalue(), "unknown brief key logged and ignored")

# an older week (previous ISO week) and a duplicate of the same ISO week
older = {"date": "2026-09-14", "repos": [repo("acme/tool", 1), repo("other/one", 2)]}
(data_dir / "2026-09-14.json").write_text(json.dumps(older), encoding="utf-8")
dup = {"date": "2026-09-22", "repos": [repo("dup/one", 1)]}
(data_dir / "2026-09-22.json").write_text(json.dumps(dup), encoding="utf-8")
(data_dir / "broken.json").write_text("{not json", encoding="utf-8")

print("== load_weeks ==")
with contextlib.redirect_stderr(io.StringIO()):
    weeks = bs.load_weeks(str(data_dir))
check([w["date"] for w in weeks] == ["2026-09-22", "2026-09-14"], "newest first, one per ISO week (newest date wins), broken file skipped")

print("== render ==")
out = root / "site"
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    rc = bs.render_site(str(data_dir), str(out))
check(rc == 0, "render exits 0")
check((out / ".nojekyll").exists(), ".nojekyll written")
index = (out / "index.html").read_text(encoding="utf-8")
w22 = (out / "weeks" / "2026-09-22.html").read_text(encoding="utf-8")
w14 = (out / "weeks" / "2026-09-14.html").read_text(encoding="utf-8")
check("Week of 22 September 2026" in index and "dup/one" in index, "index is the latest week")
check('href="weeks/2026-09-14.html">14 Sep</a>' in index, "index links the archive with root-relative paths")
check('href="../weeks/2026-09-22.html">22 Sep</a>' in w14 and 'href="../">Latest week</a>' in w14, "old week links up and back to latest")
check("Latest week" not in w22, "the latest week's own page has no latest link")
check('<meta name="viewport"' in index and "prefers-color-scheme: dark" in index and 'name="color-scheme"' in index, "phone viewport and dark mode tokens")

# re-render the 21 Sep week alone to check entry details
(data_dir / "2026-09-22.json").unlink()
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    bs.render_site(str(data_dir), str(out))
page = (out / "index.html").read_text(encoding="utf-8")
check("Week of 21 September 2026" in page, "21 Sep is now the index")
check("4 repos · 3 new · 1 still trending" in page, "standfirst counts")
check('<span class="try-count">1 to try</span>' in page, "Try count in the standfirst")
check(page.count('<span class="tag">Try</span>') == 1, "exactly one Try tag")
check("&lt;script&gt;" in page and "<script" not in page and "&amp; safe" in page, "description HTML escaped")
check("&lt;b&gt;now&lt;/b&gt;" in page, "brief text HTML escaped")
ranks = re.findall(r'<span class="rank" aria-hidden="true">(\d*)</span>', page)
check(ranks == ["1", "3", "4", "2"], "feed rank order within each section, new section first")
check("★ 45.1k (+1.2k) · Rust · 3rd week" in page, "returning entry metadata with delta and week")
check("★ 1.2M · Python · Apache-2.0" in page and '<span class="muted">(archived)</span>' in page, "archived entry and 1.2M stars")
ghost = page.split("ghost/none")[1].split("</li>")[0]
check('class="meta"' not in ghost and 'class="desc"' not in ghost and 'class="brief"' not in ghost, "entry with nothing but a name has only a name")
check("<strong>" not in page and "<b>" not in page, "no bold outside the name class")
check(page.count("<h2>") == 3, "two sections plus the archive heading")
check("<i>Why now.</i> Shipped" in page and "<i>Verdict.</i> Try — you need it." in page, "brief labels and verdict line")

print("== render with no data ==")
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    rc = bs.render_site(str(root / "nowhere"), str(root / "site2"))
check(rc == 1, "render without data exits 1")

print("== CLI ==")
with contextlib.redirect_stdout(io.StringIO()):
    rc = bs.main(["render", "--data-dir", str(data_dir), "--out", str(root / "site3")])
check(rc == 0 and (root / "site3" / "index.html").exists(), "render via CLI")

tmp.cleanup()
print(f"\nALL {passed} CHECKS PASSED")
