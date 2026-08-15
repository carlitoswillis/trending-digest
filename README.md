# trending-digest

Emails me a weekly GitHub Trending digest (overall + TypeScript, Python, Swift), built from GitHubTrendingRSS feeds. Runs as a scheduled GitHub Action Mondays; also runnable manually from the Actions tab.

Secrets: MAIL_USERNAME (gmail address), MAIL_PASSWORD (gmail app password).
Edit scripts/build_digest.py FEEDS to change languages.
