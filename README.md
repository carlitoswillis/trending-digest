# trending-digest

Emails me a weekly GitHub Trending digest built from the GitHubTrendingRSS weekly feed. Each entry carries stars, language, license and topics from the GitHub API, and repos are split into "new this week" versus "still trending" (with week count and star delta) by comparing against the previous digest issues. Runs as a scheduled GitHub Action Mondays; also runnable manually from the Actions tab.

Delivery: files a GitHub issue each week; GitHub emails the notification. No secrets needed.
