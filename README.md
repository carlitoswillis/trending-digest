# trending-digest

Emails me a weekly GitHub Trending digest (overall + TypeScript, Python, Swift), built from GitHubTrendingRSS feeds. Runs as a scheduled GitHub Action Mondays; also runnable manually from the Actions tab.

Delivery: files a GitHub issue each week; GitHub emails the notification. No secrets needed.
Edit scripts/build_digest.py FEEDS to change languages.
