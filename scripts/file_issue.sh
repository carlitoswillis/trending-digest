#!/usr/bin/env bash
# Files this week's digest as an issue: idempotent, lock-first.
#   usage: file_issue.sh <dir containing digest.md and digest.json>
# Needs gh (GH_TOKEN) and GITHUB_REPOSITORY. Order of operations:
#   1. look for today's digest (exact title, filed by this workflow's own identity);
#   2. create it only if absent;
#   3. lock it immediately, whether new or reused;
#   4. only then tidy old digests. A cleanup failure never skips the lock; it
#      fails the job at the very end so it is visible.
set -uo pipefail

dir=${1:-.}
repo=${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}
author="app/github-actions"
failed=0

date=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["date"])' "$dir/digest.json" 2>/dev/null) \
  || date=$(date -u '+%Y-%m-%d')
[[ $date =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || { echo "::error::bad digest date" >&2; exit 1; }
title="Trending digest — $date"

# 1. existing issue for this date (any state), by this workflow's identity only
found=$(gh issue list --repo "$repo" --state all --author "$author" --limit 100 \
          --json number,title,url \
        | python3 -c '
import json, sys
title = sys.argv[1]
hits = sorted((i for i in json.load(sys.stdin) if i.get("title") == title), key=lambda i: i["number"])
print(hits[0]["url"] if hits else "")' "$title") \
  || { echo "::error::could not look up an existing digest issue" >&2; exit 1; }

# 2. create only if absent
if [ -n "$found" ]; then
  url=$found
  echo "reusing existing digest issue: $url"
else
  url=$(gh issue create --repo "$repo" --title "$title" --body-file "$dir/digest.md") \
    || { echo "::error::could not create the digest issue" >&2; exit 1; }
  echo "$url"
fi
[ -n "${GITHUB_OUTPUT:-}" ] && echo "url=$url" >> "$GITHUB_OUTPUT"

# 3. lock first
if ! gh issue lock "$url" --reason spam; then
  echo "::error::could not lock $url" >&2
  failed=1
fi

# 4. keep the repo tidy: close digests older than the newest 8
old=$(gh issue list --repo "$repo" --state open --author "$author" --limit 100 \
        --json number,title,createdAt \
      | python3 -c '
import json, sys
rows = [i for i in json.load(sys.stdin) if i.get("title", "").startswith("Trending digest")]
rows.sort(key=lambda i: i["createdAt"], reverse=True)
print("\n".join(str(i["number"]) for i in rows[8:]))') \
  || { echo "::error::cleanup could not list open digests" >&2; failed=1; old=""; }
for n in $old; do
  gh issue close "$n" --repo "$repo" || { echo "::error::cleanup could not close #$n" >&2; failed=1; }
done

exit "$failed"
