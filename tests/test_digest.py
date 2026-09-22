#!/usr/bin/env python3
"""Offline harness for scripts/build_digest.py: monkeypatches urllib.request.urlopen.

Run from any directory:  python3 tests/test_digest.py
"""
import contextlib
import sys
sys.dont_write_bytecode = True  # keep scripts/__pycache__ out of the repo
import importlib.util
import io
import json
import os
import re
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "build_digest.py"
spec = importlib.util.spec_from_file_location("build_digest", SCRIPT)
bd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bd)

NOW = datetime.now(timezone.utc)
TODAY = NOW.strftime("%Y-%m-%d")
# Fixture issues are dated relative to today so the harness is stable on any day.
D1, D2, D3 = ((NOW - timedelta(days=d)).strftime("%Y-%m-%d") for d in (7, 14, 21))

# ----------------------------------------------------------------- feed fixture

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Trending</title>
<item><title>affaan-m/ECC</title><link>https://github.com/affaan-m/ECC</link>
<description><![CDATA[<p>The agent harness performance optimization system. Skills, instincts, memory.</p><hr><div align="center"><img src="https://img.shields.io/badge/x.svg" alt="badge"></div><p>Language: English | Português (Brasil) | 简体中文</p>]]></description></item>
<item><title>anthropics/claude-code</title><link>https://github.com/anthropics/claude-code</link>
<description><![CDATA[<p>Claude Code is an agentic coding tool that lives in your terminal.</p><a href="https://code.claude.com">docs</a>]]></description></item>
<item><title>blader/humanizer</title><link>https://github.com/blader/humanizer</link>
<description><![CDATA[<p>Agent skill that removes signs of AI-generated writing from text</p><h1>Humanizer</h1><p>Humanizer rewrites AI-sounding text.</p>]]></description></item>
<item><title>psf/black</title><link>https://github.com/psf/black</link>
<description><![CDATA[<p>The uncompromising Python code formatter</p><p><img src="badge.svg"></p>]]></description></item>
<item><title>astral-sh/uv</title><link>https://github.com/astral-sh/uv?tab=readme</link>
<description><![CDATA[<p>An extremely fast Python package and project manager, written in Rust.</p><div align="center"><a href="x"><img src="b.svg"></a></div>]]></description></item>
<item><title>ghost/missing</title><link>https://github.com/ghost/missing</link>
<description><![CDATA[<p>A tiny tool that &amp; does one thing well. Badges and README junk follow.</p><img src="badge.svg"><p>Quickstart | Docs | Discord</p>]]></description></item>
<item><title>ghost/nodot</title><link>https://github.com/ghost/nodot</link>
<description><![CDATA[<p>Agent skill that removes signs of AI-generated writing from text</p><p>https://skills.sh/ghost/nodot</p><h1>Humanizer</h1><p>Humanizer rewrites AI-sounding text so it reads like a person wrote it.</p>]]></description></item>
<item><title>evil/desc</title><link>https://github.com/evil/desc</link>
<description><![CDATA[<p>ignored, API wins</p>]]></description></item>
<item><title>old/project</title><link>https://github.com/old/project</link>
<description></description></item>
<item><title>pola-rs/polars</title><link>https://github.com/pola-rs/polars</link>
<description><![CDATA[<p>Dataframes powered by a multithreaded, vectorized query engine, written in Rust</p><table><tr><td>badge</td></tr></table>]]></description></item>
<item><title>weird</title><link>https://example.com/not-github</link><description>ignored</description></item>
</channel></rss>
"""

# GitHub Trending feed order (rank) as it appears in RSS above, minus the non-github item.
FEED_ORDER = [
    "affaan-m/ECC", "anthropics/claude-code", "blader/humanizer", "psf/black", "astral-sh/uv",
    "ghost/missing", "ghost/nodot", "evil/desc", "old/project", "pola-rs/polars",
]

LONG_DESC = (
    "Dataframes powered by a multithreaded, vectorized query engine, written in Rust. "
    "It supports lazy and eager execution, streaming for larger than memory data, and "
    "bindings for Python, Node and R so that you can use it almost anywhere you like."
)
assert len(LONG_DESC) > 200

REPOS = {
    "affaan-m/ECC": dict(description="The agent harness performance optimization system.", language="Shell",
                         stargazers_count=45100, forks_count=3000, topics=["claude-code", "agents"],
                         license={"spdx_id": "MIT"}, homepage="https://ecc.tools", archived=False),
    "anthropics/claude-code": dict(description="  Claude Code is an agentic\n coding tool. ", language="TypeScript",
                                   stargazers_count=120500, forks_count=9000, topics=["agent"],
                                   license={"spdx_id": "NOASSERTION"}, homepage=None, archived=False),
    "blader/humanizer": dict(description="Agent skill that removes signs of AI-generated writing from text",
                             language=None, stargazers_count=8900, forks_count=100, topics=[],
                             license=None, homepage=None, archived=False),
    "psf/black": dict(description="The uncompromising Python code formatter", language="Python",
                      stargazers_count=42000, forks_count=2500, topics=["python", "formatter"],
                      license={"spdx_id": "MIT"}, homepage="https://black.readthedocs.io", archived=False),
    "astral-sh/uv": dict(description="An extremely fast Python package and project manager, written in Rust.",
                         language="Rust", stargazers_count=71260, forks_count=2000,
                         topics=["python", "packaging", "pip", "resolver", "rust", "uv", "venv"],
                         license={"spdx_id": "Apache-2.0"}, homepage="https://docs.astral.sh/uv", archived=False),
    # ghost/missing and ghost/nodot -> HTTP 404 (handled in fake_urlopen)
    "evil/desc": dict(description="- Fast `tool` for x <!-- hidden --> see [foo/bar](https://github.com/foo/bar) **not bold** _nor italic_ snake_case, ping @maint, fixes #12, ~~old~~ docs: https://x.dev/a_b",
                      language="Python", stargazers_count=5, forks_count=0, topics=["x"], license=None,
                      homepage=None, archived=False),
    "old/project": dict(description=None, language="Python", stargazers_count=950, forks_count=10,
                        topics=[], license=None, homepage="", archived=True),
    "pola-rs/polars": dict(description=LONG_DESC, language="Rust", stargazers_count=1234567,
                           forks_count=800, topics=["dataframe", "rust"],
                           license={"spdx_id": "NOASSERTION"}, homepage=None, archived=False),
}

# -------------------------------------------------------------- history fixture

ISSUE_8_BODY = "# GitHub Trending — weekly\n\n## This week\n\n- **[alibaba/open-code-review](https://github.com/alibaba/open-code-review)** — Secure, fast, efficient, battle-tested at Alibaba's scale. Hybrid architecture code review tool: deterministic pipelines + LLM Agent, precise line-level comments, built-in multi-language ruleset (NPE, thread-safety, XSS, SQL injection), OpenAI & Anthropic compatible. https://open\n- **[anthropics/claude-code](https://github.com/anthropics/claude-code)** — Claude Code is an agentic coding tool that lives in your terminal, understands your codebase, and helps you code faster by executing routine tasks, explaining complex code, and handling git workflows - all through natural language commands. https://code.claude.com/docs/en/overvie\n- **[affaan-m/ECC](https://github.com/affaan-m/ECC)** — The agent harness performance optimization system. Skills, instincts, memory, security, and research-first development for Claude Code, Codex, Opencode, Cursor and beyond. https://ecc.tools Language: English | Português (Brasil) | 简体中文 | 繁體中文 | 日本語 | 한국어 | Türkçe | Русский | Tiến\n- **[Tencent/WeKnora](https://github.com/Tencent/WeKnora)** — Open-source LLM knowledge platform: turn raw documents into a queryable RAG, an autonomous reasoning agent, and a self-maintaining Wiki. https://weknora.weixin.qq.com | English | 简体中文 | 日本語 | 한국어 | Overview • Architecture • Key Features • Getting Started • API Reference • Develop\n- **[addyosmani/agent-skills](https://github.com/addyosmani/agent-skills)** — Production-grade engineering skills for AI coding agents. https://skills.addy.ie Agent Skills Production-grade engineering skills for AI coding agents. Skills encode the workflows, quality gates, and best practices that senior engineers use when building software. These ones are \n- **[anthropics/knowledge-work-plugins](https://github.com/anthropics/knowledge-work-plugins)** — Open source repository of plugins primarily intended for knowledge workers to use in Claude Cowork Knowledge Work Plugins Plugins that turn Claude into a specialist for your role, team, and company. Built for Claude Cowork , also compatible with Claude Code . Why Plugins Cowork l\n- **[bilawalsidhu/gods-eye-view](https://github.com/bilawalsidhu/gods-eye-view)** — A spy satellite simulator in your browser, except the data is real. Live open source spatial intelligence on a photorealistic 3D globe. https://maptheworld.ai/ 🌐 God's Eye View A spy-satellite simulator in your browser — then you realize the sources are public and the data is rea\n- **[mksglu/context-mode](https://github.com/mksglu/context-mode)** — Context window optimization for AI coding agents. Sandboxes tool output (98% reduction), persists session memory, and enforces routing across 17 platforms via MCP + hooks. https://context-mode.com Context Mode The other half of the context problem. Used across teams at The Proble\n- **[max-sixty/worktrunk](https://github.com/max-sixty/worktrunk)** — Worktrunk is a CLI for Git worktree management, designed for parallel AI agent workflows https://worktrunk.dev   Worktrunk September 2026 : Worktrunk was released at the start of the year, and has quickly become the most popular git worktree manager. It's built with love (there's\n- **[home-assistant/core](https://github.com/home-assistant/core)** — 🏡 Open source home automation that puts local control and privacy first. https://www.home-assistant.io Home Assistant |Chat Status| Open source home automation that puts local control and privacy first. Powered by a worldwide community of tinkerers and DIY enthusiasts. Perfect to\n- **[blader/humanizer](https://github.com/blader/humanizer)** — Agent skill that removes signs of AI-generated writing from text https://skills.sh/blader/humanizer Humanizer Humanizer rewrites AI-sounding text so it reads like a person wrote it, without changing what it says. Because it is just Markdown, it works with any agent that supports \n- **[stablyai/orca](https://github.com/stablyai/orca)** — Orca is the ADE for working with a fleet of parallel agents. Run any coding agent with your own subscription. Available on desktop, mobile and remote runtime. https://onOrca.dev Orca 中文 · 日本語 · 한국어 · Español · Français · Português The AI Orchestrator for 100x builders. Run Codex,\n- **[Panniantong/Agent-Reach](https://github.com/Panniantong/Agent-Reach)** — Give your AI agent eyes to see the entire internet. Read & search Twitter, Reddit, YouTube, GitHub, Bilibili, XiaoHongShu — one CLI, zero API fees. 👁️ Agent Reach 给你的 AI Agent 一键装上互联网能力 当下最稳的接入方式，替你选好、装好、体检好——接入方式会换代，你不用操心 快速开始 · English · 日本語 · 한국어 · 支持平台 · 设计理念 ❤️赞助商 想出现在这里？ 点击\n- **[heygen-com/hyperframes](https://github.com/heygen-com/hyperframes)** — Write HTML. Render video. Built for agents. Write HTML. Render video. Built for agents. Quickstart | Showcase | Playground | Catalog | Docs | Discord HyperFrames is an open-source framework for turning HTML, CSS, media, and seekable animations into deterministic MP4 videos. Use i\n- **[danny-avila/LibreChat](https://github.com/danny-avila/LibreChat)** — Enhanced ChatGPT Clone: Features Agents, MCP, Skills, DeepSeek, Anthropic, AWS, OpenAI, Responses API, Azure, Groq, o1, GPT-5, Mistral, OpenRouter, Vertex AI, Gemini, Artifacts, AI model switching, message search, Code Interpreter, langchain, DALL-E-3, OpenAPI Actions, Functions,\n- **[ayghri/i-have-adhd](https://github.com/ayghri/i-have-adhd)** — A skill to stop your coding agent from burying the answer. ADHD-friendly output. ADHD-friendly outputs. No ADHD diagnosis needed! 🇬🇧 · 🇨🇳 · 🇪🇸 · 🇧🇷 · 🇯🇵 · 🇻🇳 · 🇰🇷 · 🇮🇷 · 🇹🇭 · 🇸🇦 Install Copy/paste into your CLI prompt: Install the i-have-adhd skill/plugin from https://github.com/\n- **[cline/cline](https://github.com/cline/cline)** — Autonomous coding agent as an SDK, IDE extension, or CLI assistant. https://cline.bot Cline The open source coding agent in your IDE, terminal, & desktop. Docs Discord r/cline Feature Requests Join us! CLI Run Cline in your terminal. Interactive chat or fully headless for CI/CD a\n- **[petergyang/no-ai-slop](https://github.com/petergyang/no-ai-slop)** — Removes 20+ patterns of AI slop from any piece of writing. https://creatoreconomy.so/p/use-my-no-ai-slop-skill-to-remove-20-ai-slop-patterns No AI Slop Remove 20+ patterns of AI slop from your writing without flattening your personal voice. https://github.com/user-attachments/ass\n- **[supabase/supabase](https://github.com/supabase/supabase)** — The Postgres development platform. Supabase gives you a dedicated Postgres database to build your web, mobile, and AI applications. https://supabase.com Supabase Supabase is the Postgres development platform. We're building the features of Firebase using enterprise-grade open sou\n- **[microsoft/markitdown](https://github.com/microsoft/markitdown)** — Python tool for converting files and office documents to Markdown. MarkItDown Important MarkItDown performs I/O with the privileges of the current process. Like open() or requests.get(), it will access resources that the process itself can access. Sanitize your inputs in untruste\n- **[cilium/cilium](https://github.com/cilium/cilium)** — eBPF-based Networking, Security, and Observability https://cilium.io .. raw:: html |cii| |go-report| |clomonitor| |artifacthub| |slack| |go-doc| |rtd| |apache| |bsd| |gpl| |fossa| |gateway-api| |codespaces| Cilium is a networking, observability, and security solution with an eBPF\n"

ISSUE_7_BODY = "# GitHub Trending — weekly\n\n## This week\n\n- **[ayghri/i-have-adhd](https://github.com/ayghri/i-have-adhd)** — A skill to stop your coding agent from burying the answer. ADHD-friendly output. ADHD-friendly outputs. No ADHD diagnosis needed! 🇬🇧 · 🇨🇳 · 🇧🇷 · 🇯🇵 · 🇻🇳 · 🇰🇷 · 🇮🇷 · 🇹🇭 Install Copy/paste into your CLI prompt: Install the i-have-adhd skill/plugin from https://github.com/ayghri/i-h\n- **[affaan-m/ECC](https://github.com/affaan-m/ECC)** — The agent harness performance optimization system. Skills, instincts, memory, security, and research-first development for Claude Code, Codex, Opencode, Cursor and beyond. https://ecc.tools Language: English | Português (Brasil) | 简体中文 | 繁體中文 | 日本語 | 한국어 | Türkçe | Русский | Tiến\n- **[openai/plugins](https://github.com/openai/plugins)** — OpenAI Plugins Plugins This repository contains a curated collection of Codex plugin examples. Each plugin lives under plugins/<name>/ with a required .codex-plugin/plugin.json manifest and optional companion surfaces such as skills/ , .app.json , .mcp.json , plugin-level agents/\n- **[bilawalsidhu/gods-eye-view](https://github.com/bilawalsidhu/gods-eye-view)** — A spy satellite simulator in your browser, except the data is real. Live open source spatial intelligence on a photorealistic 3D globe. https://maptheworld.ai/ 🌐 God's Eye View A spy-satellite simulator in your browser — then you realize the sources are public and the data is rea\n- **[mksglu/context-mode](https://github.com/mksglu/context-mode)** — Context window optimization for AI coding agents. Sandboxes tool output (98% reduction), persists session memory, and enforces routing across 17 platforms via MCP + hooks. https://context-mode.com Context Mode The other half of the context problem. Used across teams at The Proble\n- **[DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail)** — Makes your AI agent think like the laziest senior dev in the room. The best code is the code you never wrote. https://ponytail.dev Ponytail He says nothing. He writes one line. It works. ~54% less code (up to 94%) · ~20% cheaper · ~27% faster · 100% safe Measured on real Claude C\n- **[tt-a1i/archify](https://github.com/tt-a1i/archify)** — Agent skill for beautiful, verifiable architecture, workflow, sequence, data-flow, and lifecycle diagrams—self-contained HTML with motion and crisp export. https://tt-a1i.github.io/archify/ English · 简体中文 Archify Turn a codebase or system description into a polished, interactive \n- **[openai/skills](https://github.com/openai/skills)** — Skills Catalog for Codex Important This repository is deprecated. For current Codex skill and plugin examples, use the OpenAI Plugins repository . If you want to add your own skills to Codex, follow the Build plugins guide, which includes instructions for creating a skill-only pl\n- **[heygen-com/hyperframes](https://github.com/heygen-com/hyperframes)** — Write HTML. Render video. Built for agents. Write HTML. Render video. Built for agents. Quickstart | Showcase | Playground | Catalog | Docs | Discord HyperFrames is an open-source framework for turning HTML, CSS, media, and seekable animations into deterministic MP4 videos. Use i\n- **[microsoft/markitdown](https://github.com/microsoft/markitdown)** — Python tool for converting files and office documents to Markdown. MarkItDown Important MarkItDown performs I/O with the privileges of the current process. Like open() or requests.get(), it will access resources that the process itself can access. Sanitize your inputs in untruste\n- **[obra/superpowers](https://github.com/obra/superpowers)** — An agentic skills framework & software development methodology that works. Superpowers Superpowers is a complete software development methodology for your coding agents, built on top of a set of composable skills and some initial instructions that make sure your agent uses them. \n- **[coreyhaines31/marketingskills](https://github.com/coreyhaines31/marketingskills)** — Marketing skills for Claude Code and AI agents. CRO, copywriting, SEO, analytics, and growth engineering. https://marketing-skills.com Marketing Skills for AI Agents A collection of AI agent skills focused on marketing tasks. Built for technical marketers and founders who want AI\n- **[ChromeDevTools/chrome-devtools-mcp](https://github.com/ChromeDevTools/chrome-devtools-mcp)** — Chrome DevTools for coding agents https://developer.chrome.com/docs/devtools/agents Chrome DevTools for agents Chrome DevTools for agents ( chrome-devtools-mcp ) lets your coding agent (such as Antigravity, Claude, Cursor or Copilot) control and inspect a live Chrome browser. It \n- **[cathrynlavery/diagram-design](https://github.com/cathrynlavery/diagram-design)** — 38 editorial diagram types for Claude Code, Codex, and Pi. Self-contained HTML + SVG. No shadows. No Mermaid slop. https://cathrynlavery.github.io/diagram-design/ Diagram Design Editorial diagrams your designer won't hate. New in 2.0 — the Loop: flywheels with a shared-memory hub\n- **[THU-MAIC/OpenMAIC](https://github.com/THU-MAIC/OpenMAIC)** — Open Multi-Agent Interactive Classroom — Get an immersive, multi-agent learning experience in just one click Get an immersive, multi-agent learning experience in just one click      English | Simplified Chinese Live Demo · Quick Start · Lemonade · FunASR · Features · Use Cases · \n- **[Tencent/WeKnora](https://github.com/Tencent/WeKnora)** — Open-source LLM knowledge platform: turn raw documents into a queryable RAG, an autonomous reasoning agent, and a self-maintaining Wiki. https://weknora.weixin.qq.com | English | 简体中文 | 日本語 | 한국어 | Overview • Architecture • Key Features • Getting Started • API Reference • Develop\n- **[blader/humanizer](https://github.com/blader/humanizer)** — Agent skill that removes signs of AI-generated writing from text https://skills.sh/blader/humanizer Humanizer Humanizer rewrites AI-sounding text so it reads like a person wrote it, without changing what it says. Because it is just Markdown, it works with any agent that supports \n- **[max-sixty/worktrunk](https://github.com/max-sixty/worktrunk)** — Worktrunk is a CLI for Git worktree management, designed for parallel AI agent workflows https://worktrunk.dev   Worktrunk September 2026 : Worktrunk was released at the start of the year, and has quickly become the most popular git worktree manager. It's built with love (there's\n- **[humanlayer/skills](https://github.com/humanlayer/skills)** — skills Claude Code skills from HumanLayer . Installation npx skills add humanlayer/skills --skill SKILLNAME Available Skills improve-claude-md Rewrites your CLAUDE.md using <important if> blocks to improve instruction adherence. npx skills add humanlayer/skills --skill improve-cl\n- **[earthtojake/text-to-cad](https://github.com/earthtojake/text-to-cad)** — A library of agent skills for CAD, CAE and CAM https://www.texttocad.dev ████████╗███████╗██╗ ██╗████████╗██████╗ ██████╗ █████╗ ██████╗ ╚══██╔══╝██╔════╝╚██╗██╔╝╚══██╔══╝╚════██╗██╔════╝██╔══██╗██╔══██╗ ██║ █████╗ ╚███╔╝ ██║ █████╔╝██║ ███████║██║ ██║ ██║ ██╔══╝ ██╔██╗ ██║ ██╔══\n- **[petergyang/no-ai-slop](https://github.com/petergyang/no-ai-slop)** — Removes 20+ patterns of AI slop from any piece of writing. https://creatoreconomy.so/p/use-my-no-ai-slop-skill-to-remove-20-ai-slop-patterns No AI Slop Remove 20+ patterns of AI slop from your writing without flattening your personal voice. https://github.com/user-attachments/ass\n- **[github/spec-kit](https://github.com/github/spec-kit)** — 💫 Toolkit to help you get started with Spec-Driven Development https://github.github.com/spec-kit/ 🌱 Spec Kit Define what to build before building it — with any AI coding agent. An open source toolkit for building high-quality software with any AI coding agent — a ready-to-use sp\n- **[kunchenguid/firstmate](https://github.com/kunchenguid/firstmate)** — Talk to one agent. Ship with a crew. firstmate Talk to one agent. Ship with a crew. What it is You can run one coding agent easily. But the moment you want three project tasks done in parallel - fixes, investigations, plans, audits - you become a tab-juggler: babysitting sessions\n"

# An older digest in the previous (language-grouped) format, with a digest-data marker.
# History parsing must keep working on every past layout.
MARKER_REPOS = {"affaan-m/ECC": 40000, "anthropics/claude-code": None, "psf/black": 41500, "Tencent/WeKnora": 7000}
ISSUE_6_BODY = (
    "# GitHub Trending — week of " + D3 + "\n\n"
    "**4 repos** · 4 new · 0 still trending\n\n"
    "## New this week\n\n"
    "### Python (1)\n"
    "- **[psf/black](https://github.com/psf/black)** — ★ 41.5k · MIT\n  The uncompromising Python code formatter\n\n"
    "### Other (3)\n"
    "- **[affaan-m/ECC](https://github.com/affaan-m/ECC)** — ★ 40k · MIT\n"
    "- **[Tencent/WeKnora](https://github.com/Tencent/WeKnora)** — ★ 7k\n"
    "- **[anthropics/claude-code](https://github.com/anthropics/claude-code)**\n\n"
    "<!-- digest-data " + json.dumps({"date": D3, "repos": MARKER_REPOS}, sort_keys=True, separators=(",", ":")) + " -->\n"
)

ISSUES = [
    {"number": 8, "title": f"Trending digest — {D1}", "body": ISSUE_8_BODY, "created_at": f"{D1}T20:05:28Z"},
    {"number": 7, "title": f"Trending digest — {D2}", "body": ISSUE_7_BODY, "created_at": f"{D2}T19:54:37Z"},
    {"number": 6, "title": f"Trending digest — {D3}", "body": ISSUE_6_BODY, "created_at": f"{D3}T19:50:00Z"},
    {"number": 5, "title": "Unrelated bug report", "body": "**[psf/black](https://github.com/psf/black)** should be ignored", "created_at": "2026-09-01T00:00:00Z"},
    {"number": 4, "title": "Trending digest — PR", "body": "**[psf/black](https://github.com/psf/black)**", "pull_request": {"url": "x"}, "created_at": "2026-08-31T00:00:00Z"},
]

# --------------------------------------------------------------- briefs fixture

BRIEFS = {
    "astral-sh/uv": {
        "why_now": "uv 1.0 shipped this month and pip-compatible resolution is now the default in most templates.",
        "use_for": "Replacing pip, venv and pip-tools in every Python project in one binary.",
        "verdict": "Try",
        "reason": "you already write Python and the switch is a one-line change.",
    },
    "pola-rs/polars": {
        "why_now": "A new streaming engine landed and the Rust 1.0 API is being stabilised.",
        "use_for": "Dataframes that do not fit in pandas memory.",
        "verdict": "Watch",
        "reason": "pandas still covers the small-data notebooks you actually run.",
    },
    "ANTHROPICS/Claude-Code": {  # key case must not matter
        "why_now": "Subagents and hooks shipped this week.",
        "use_for": "Agentic coding in the terminal.",
        "verdict": "Try",
        "reason": "you already use it daily; the new hooks are worth a look.",
    },
    "affaan-m/ECC": {
        "why_now": "Trending on the back of a viral thread.",
        "use_for": "A layer of skills and memory on top of Claude Code.",
        "verdict": "Skip",
        "reason": "duplicates what Claude Code plugins already do.",
    },
    "nobody/here": {  # unknown repo key, must be ignored
        "why_now": "x", "use_for": "y", "verdict": "Try", "reason": "z",
    },
}

# ------------------------------------------------------------------ fake urlopen

class Resp(io.BytesIO):
    status = 200

FEED_URL = bd.FEED_URL
ISSUES_URL_PART = "/repos/carlitoswillis/trending-digest/issues?"


def make_fake(*, feed_fails=False, history_fails=False):
    calls = []

    def fake_urlopen(url_or_req, timeout=None, **kw):
        if isinstance(url_or_req, urllib.request.Request):
            url, headers = url_or_req.full_url, dict(url_or_req.header_items())
        else:
            url, headers = url_or_req, {}
        calls.append({"url": url, "headers": headers, "timeout": timeout})
        if url == FEED_URL:
            if feed_fails:
                raise urllib.error.URLError("proxy 403")
            return Resp(RSS.encode())
        if ISSUES_URL_PART in url:
            if history_fails:
                raise urllib.error.URLError("network down")
            return Resp(json.dumps(ISSUES).encode())
        if url.startswith("https://api.github.com/repos/"):
            name = url[len("https://api.github.com/repos/"):]
            if name in ("ghost/missing", "ghost/nodot"):
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b'{"message":"Not Found"}'))
            if name in REPOS:
                return Resp(json.dumps({"full_name": name, **REPOS[name]}).encode())
        raise AssertionError(f"unexpected URL in fake urlopen: {url}")

    return fake_urlopen, calls


def read_if_exists(path):
    return open(path, encoding="utf-8").read() if os.path.exists(path) else None


@contextlib.contextmanager
def run_main(env=None, **fake_kw):
    """Run the build in a temp cwd with urlopen faked; the with-block runs inside that cwd."""
    fake, calls = make_fake(**fake_kw)
    real = urllib.request.urlopen
    urllib.request.urlopen = fake
    old_env = {k: os.environ.get(k) for k in ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_REPOSITORY", "DIGEST_PAGE_URL")}
    for k in old_env:
        os.environ.pop(k, None)
    os.environ.update(env or {})
    cwd = os.getcwd()
    tmp = tempfile.TemporaryDirectory()
    os.chdir(tmp.name)
    err, out = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            rc = bd.main([])
        yield {"rc": rc, "text": read_if_exists("digest.md"), "json": read_if_exists("digest.json"),
               "stderr": err.getvalue(), "stdout": out.getvalue(), "calls": calls}
    finally:
        os.chdir(cwd)
        tmp.cleanup()
        urllib.request.urlopen = real
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def run_render(briefs=None, path="briefs.json", pass_flag=True):
    """Run `render [--briefs path]` in the current (temp) cwd. No network: urlopen is a tripwire.

    briefs: a dict (written as JSON), a str (written verbatim), or None (nothing written).
    """
    if isinstance(briefs, dict):
        briefs = json.dumps(briefs)
    if briefs is not None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(briefs)
    argv = ["render"] + (["--briefs", path] if pass_flag else [])
    real = urllib.request.urlopen

    def tripwire(*a, **kw):
        raise AssertionError("render mode must not touch the network")

    urllib.request.urlopen = tripwire
    err, out = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            rc = bd.main(argv)
    finally:
        urllib.request.urlopen = real
    return {"rc": rc, "text": read_if_exists("digest.md"), "stderr": err.getvalue(), "stdout": out.getvalue()}


def section(text, heading):
    lines = text.splitlines()
    start = lines.index(heading) + 1
    body = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        body.append(line)
    return "\n".join(body)


ENTRY_RE = re.compile(r"^- \*\*\[([^\]]*)\]\([^)]*\)\*\*")
UNESCAPED_BACKTICK_RE = re.compile(r"(?<!\\)`")


def entries(text):
    """Repo names of entry lines, in document order."""
    return [m.group(1) for m in (ENTRY_RE.match(l) for l in text.splitlines()) if m]


def check_design_invariants(text):
    """The roles every rendered digest must respect, whatever the data."""
    lines = text.rstrip("\n").splitlines()
    assert lines[0].startswith(f"{len(entries(text))} repos on GitHub Trending this week · "), lines[0]
    assert not lines[0].startswith("#"), "no # title"
    assert lines[-1].startswith("<!-- digest-data ") and lines[-1].endswith(" -->"), "marker is last line"
    assert bd.MARKER_RE.search(lines[-1]), "marker parses"
    for l in lines:
        assert not l.startswith("# ") and not l.startswith("### "), f"heading level not allowed: {l!r}"
        assert not l.startswith("#") or l in ("## New this week", "## Still trending"), f"unexpected heading: {l!r}"
        body = ENTRY_RE.sub("", l) if l.startswith("- ") else l
        assert "**" not in body, f"bold outside a repo name: {l!r}"
        rest = body.replace("`Try`", "")
        assert not UNESCAPED_BACKTICK_RE.search(rest), f"code span other than the Try tag: {l!r}"
        assert "`Try`" not in l or l.startswith("- ") and l.endswith(" `Try`"), f"Try tag not at end of entry line: {l!r}"
        if l.startswith("  > "):
            assert "*Verdict.* " in l and re.search(r"\*Verdict\.\* (Try|Watch|Skip)\b", l), f"brief without a valid verdict: {l!r}"
        else:
            assert l.startswith("- ") or l.startswith("  ") or l.startswith("## ") or l.startswith("<!--") or l == "" or l is lines[0], f"stray line: {l!r}"
    # tight lists: blank lines only before headings and the marker
    for i, l in enumerate(lines):
        if l == "":
            assert lines[i + 1].startswith("## ") or lines[i + 1].startswith("<!--"), f"blank line inside a list at {i}"
    for h in ("## New this week", "## Still trending"):
        if h in lines:
            assert lines[lines.index(h) - 1] == "", f"no blank line before {h}"
    # feed order within each section
    ranks = {n: i for i, n in enumerate(FEED_ORDER)}
    for h in ("## New this week", "## Still trending"):
        if h in lines:
            names = entries(section(text, h))
            assert names == sorted(names, key=ranks.__getitem__), f"{h} not in feed order: {names}"


passed = 0


def check(cond, msg):
    global passed
    if not cond:
        raise AssertionError(msg)
    passed += 1
    print(f"  ok: {msg}")


# =============================================================== 1. main run
print("== main run (token set, 3 prior digests, one with marker) ==")
with run_main(env={"GITHUB_TOKEN": "tok123"}) as r:
    check(r["rc"] == 0, "main() returns 0")
    text = r["text"]
    print(r["stdout"].rstrip())
    print(r["stderr"].rstrip())
    print("---- digest.md (no briefs) ----")
    print(text, end="")
    print("---- end digest.md ----")

    lines = text.rstrip("\n").splitlines()
    check(lines[0] == "10 repos on GitHub Trending this week · 6 new · 4 still trending", "body starts with the standfirst line")
    check(lines[1] == "" and lines[2] == "## New this week", "one blank line then the first heading; no # title")
    check(text.endswith(" -->\n") and lines[-1].startswith("<!-- digest-data ") and lines[-2] == "", "marker is last line, one blank line before it")
    marker = json.loads(bd.MARKER_RE.search(lines[-1]).group(1))
    check(marker["date"] == TODAY and len(marker["repos"]) == 10, "marker parses with date and all 10 repos")
    check(marker["repos"]["ghost/missing"] is None and marker["repos"]["psf/black"] == 42000, "marker stars (null for fallback)")
    check(list(marker["repos"]) == sorted(marker["repos"], key=str), "marker keys sorted")
    check(json.dumps(marker, sort_keys=True, separators=(",", ":")) in lines[-1], "marker JSON is compact and sorted")
    check_design_invariants(text)
    check(True, "design invariants hold (roles, headings, spacing, feed order)")

    # header counts match sections
    new_sec = section(text, "## New this week")
    still_sec = section(text, "## Still trending")
    check(len(entries(new_sec)) == 6, "6 entries under New this week")
    check(len(entries(still_sec)) == 4, "4 entries under Still trending")
    check(not any(l.startswith("### ") for l in lines), "no language groups")
    check("`" not in new_sec.replace("\\`", ""), "no topics line anywhere")

    # New this week: feed order, not stars
    check(entries(new_sec) == ["astral-sh/uv", "ghost/missing", "ghost/nodot", "evil/desc", "old/project", "pola-rs/polars"],
          "new section in feed order (polars with 1.2M stars is last because it is last in the feed)")
    new_lines = new_sec.splitlines()
    check(new_lines[0] == "- **[astral-sh/uv](https://github.com/astral-sh/uv)** — ★ 71.3k · Rust · Apache-2.0",
          "uv line: stars · language · license (link normalised from ?tab=readme)")
    check(new_lines[1] == "  An extremely fast Python package and project manager, written in Rust.", "uv description from API")
    check(new_lines[2:6] == [
        "- **[ghost/missing](https://github.com/ghost/missing)**",
        "  A tiny tool that & does one thing well.",
        "- **[ghost/nodot](https://github.com/ghost/nodot)**",
        "  Agent skill that removes signs of AI-generated writing from text",
    ], "fallback repos: bare name line (no ' — '), first sentence of tagline, unescaped &; no-period tagline stops at the paragraph")
    check("skills.sh" not in new_lines[5] and "Humanizer" not in new_lines[5], "fallback tagline carries neither homepage URL nor README text")
    check("fallback: ghost/missing: HTTPError" in r["stderr"] and "fallback: ghost/nodot: HTTPError" in r["stderr"], "fallbacks logged to stderr")
    check(new_lines[6:8] == [
        "- **[evil/desc](https://github.com/evil/desc)** — ★ 5 · Python",
        "  \\- Fast \\`tool\\` for x &lt;!-- hidden --> see foo/bar \\*\\*not bold\\*\\* \\_nor italic\\_ snake_case, "
        "ping @​maint, fixes #​12, \\~\\~old\\~\\~ docs",
    ], "description escaped: leading list marker, backticks, HTML comment, emphasis, strikethrough neutralised; "
       "link reduced to its text, bare URL dropped, @mention and #ref autolinks broken; intraword underscore kept")
    check("](" not in new_lines[7] and "http" not in new_lines[7], "the repo name is the only link in an entry")
    check(new_lines[8] == "- **[old/project](https://github.com/old/project)** (archived) — ★ 950 · Python",
          "archived repo: (archived) after the name, stars as-is, no license, no description line")
    check(new_lines[9] == "- **[pola-rs/polars](https://github.com/pola-rs/polars)** — ★ 1.2M · Rust", "1.2M formatting, NOASSERTION license omitted")
    check(new_lines[10].startswith("  ") and new_lines[10].endswith("…") and len(new_lines[10].strip()) <= 200 and not new_lines[10].strip()[:-1].endswith(" "),
          f"long description truncated at word boundary with ellipsis ({len(new_lines[10].strip())} chars)")
    check(len(new_lines) == 11, "tight list: no blank lines between entries")
    p = bd.parse_digest(text)
    check(p["present"] >= {"evil/desc", "ghost/nodot"} and "foo/bar" not in p["present"], "a repo named inside a description does not count as presence")
    check(p["present"] == {n.lower() for n in FEED_ORDER} and p["stars"]["psf/black"] == 42000, "the new layout parses back as history (entries + marker)")

    # still trending: feed order; weeks and deltas
    still = [l for l in still_sec.splitlines() if l.startswith("- **[")]
    check(still == [
        "- **[affaan-m/ECC](https://github.com/affaan-m/ECC)** — ★ 45.1k (+5.1k) · Shell · MIT · 4th week",
        "- **[anthropics/claude-code](https://github.com/anthropics/claude-code)** — ★ 120.5k · TypeScript · 3rd week",
        "- **[blader/humanizer](https://github.com/blader/humanizer)** — ★ 8.9k · 3rd week",
        "- **[psf/black](https://github.com/psf/black)** — ★ 42k (+500) · Python · MIT · 2nd week",
    ], "still-trending lines: feed order, stars (+delta) · language · license · Nth week; no delta for null/absent marker; language/license omitted when None")
    check("  Claude Code is an agentic coding tool." in still_sec, "API description whitespace collapsed")
    check("  > " not in text, "no brief lines without briefs")

    # digest.json
    data = json.loads(r["json"])
    check(data["date"] == TODAY and [x["name"] for x in data["repos"]] == FEED_ORDER, "digest.json has the date and repos in feed order")
    check([x["rank"] for x in data["repos"]] == list(range(1, 11)), "rank stored 1..10")
    ecc = data["repos"][0]
    check(ecc["is_new"] is False and ecc["weeks"] == 4 and ecc["delta"] == 5100 and ecc["stars"] == 45100 and ecc["license"] == "MIT",
          "digest.json carries is_new/weeks/delta and metadata")
    check("feed_text" not in ecc and ecc["fallback"] is False and data["repos"][5]["fallback"] is True, "raw feed HTML left out of digest.json; fallback flag kept")

    # headers on API calls
    api_calls = [c for c in r["calls"] if c["url"].startswith("https://api.github.com/")]
    check(len([c for c in r["calls"] if c["url"] == FEED_URL]) == 1, "feed fetched exactly once")
    check(len(api_calls) == 11, "10 repo calls + 1 issues call")
    for c in api_calls:
        assert c["headers"]["Accept"] == "application/vnd.github+json", c
        assert c["headers"]["X-github-api-version"] == "2022-11-28", c
        assert c["headers"]["User-agent"] == "trending-digest", c
        assert c["headers"]["Authorization"] == "Bearer tok123", c
        assert c["timeout"] == 15, c
    check(True, "API headers, Bearer token and 15s timeout on every API call")
    check(any("state=all&per_page=20&sort=created&direction=desc" in c["url"] for c in api_calls), "issues URL query")
    check(not os.path.exists("digest.html"), "no digest.html written")

    # ------------------------------------------------ 1a. render round-trips
    print("== render: digest.json round-trips without briefs ==")
    rr = run_render(None, pass_flag=False)
    check(rr["rc"] == 0 and rr["text"] == text, "render with no --briefs reproduces digest.md byte for byte")
    rr = run_render(None, path="does-not-exist.json")
    check(rr["rc"] == 0 and rr["text"] == text, "render --briefs with a missing file: exit 0, identical digest.md")
    check("does-not-exist.json not found" in rr["stderr"], "missing briefs file logged")
    rr = run_render("{not json", path="broken.json")
    check(rr["rc"] == 0 and rr["text"] == text, "render --briefs with invalid JSON: exit 0, identical digest.md")
    check("could not read broken.json" in rr["stderr"] and "JSONDecodeError" in rr["stderr"], "invalid JSON logged with the reason")
    rr = run_render("[1, 2]", path="list.json")
    check(rr["rc"] == 0 and rr["text"] == text and "not a JSON object" in rr["stderr"], "briefs that are not an object: logged, identical digest.md")

    # ------------------------------------------------ 1b. render with briefs
    print("== render --briefs with a good file ==")
    rr = run_render(BRIEFS)
    check(rr["rc"] == 0, "render returns 0")
    btext = rr["text"]
    print(rr["stdout"].rstrip())
    print(rr["stderr"].rstrip())
    print("---- digest.md (with briefs) ----")
    print(btext, end="")
    print("---- end digest.md ----")
    check_design_invariants(btext)
    check(True, "design invariants hold with briefs")
    blines = btext.rstrip("\n").splitlines()
    check(blines[0] == lines[0] and blines[-1] == lines[-1], "standfirst and marker unchanged by briefs")
    check(entries(btext) == entries(text), "feed order preserved with briefs")
    bnew = section(btext, "## New this week").splitlines()
    check(bnew[0] == "- **[astral-sh/uv](https://github.com/astral-sh/uv)** — ★ 71.3k · Rust · Apache-2.0 `Try`", "Try tag at the end of the entry line")
    check(bnew[1] == "  An extremely fast Python package and project manager, written in Rust.", "description unchanged")
    check(bnew[2] == "  > *Why now.* uv 1.0 shipped this month and pip-compatible resolution is now the default in most templates. "
                     "*Use it for.* Replacing pip, venv and pip-tools in every Python project in one binary. "
                     "*Verdict.* Try — you already write Python and the switch is a one-line change.",
          "brief is one blockquote line under the description with the three run-in labels")
    bpolars = [l for l in bnew if l.startswith("- **[pola-rs/polars]")][0]
    check(bpolars == "- **[pola-rs/polars](https://github.com/pola-rs/polars)** — ★ 1.2M · Rust", "no tag for a Watch verdict")
    check(bnew[-1].startswith("  > *Why now.* A new streaming engine") and bnew[-1].endswith("*Verdict.* Watch — pandas still covers the small-data notebooks you actually run."),
          "Watch brief rendered")
    bstill = section(btext, "## Still trending").splitlines()
    check(bstill[0] == "- **[affaan-m/ECC](https://github.com/affaan-m/ECC)** — ★ 45.1k (+5.1k) · Shell · MIT · 4th week", "no tag for a Skip verdict")
    check(bstill[2].endswith("*Verdict.* Skip — duplicates what Claude Code plugins already do."), "Skip brief rendered")
    check(bstill[3] == "- **[anthropics/claude-code](https://github.com/anthropics/claude-code)** — ★ 120.5k · TypeScript · 3rd week `Try`",
          "briefs keys matched case-insensitively (ANTHROPICS/Claude-Code)")
    check(bstill[5] == "  > *Why now.* Subagents and hooks shipped this week. *Use it for.* Agentic coding in the terminal. "
                       "*Verdict.* Try — you already use it daily; the new hooks are worth a look.", "claude-code brief")
    check(bstill[6:8] == ["- **[blader/humanizer](https://github.com/blader/humanizer)** — ★ 8.9k · 3rd week",
                          "  Agent skill that removes signs of AI-generated writing from text"] and bstill[8].startswith("- **[psf/black]"),
          "repos without a brief: no blockquote, no tag, otherwise identical")
    check(btext.count("`Try`") == 2 and btext.count("  > ") == 4, "exactly two Try tags and four brief lines")
    check("nobody/here" not in btext and "ignoring unknown repo 'nobody/here'" in rr["stderr"], "unknown repo key ignored and logged")
    check("4 brief(s)" in rr["stdout"], "render reports the brief count")
    check(bd.parse_digest(btext)["present"] == bd.parse_digest(text)["present"] and bd.parse_digest(btext)["stars"] == bd.parse_digest(text)["stars"],
          "digest with briefs parses back as history identically (ENTRY_LINK_RE compatible)")

    # ------------------------------------------------ 1c. bad brief entries
    print("== render --briefs: bad verdict, over-long text, markdown in text ==")
    long_why = "word " * 100
    long_use = "verb " * 60
    long_reason = "why " * 60
    bad = {
        "blader/humanizer": {"why_now": "x", "use_for": "y", "verdict": "Maybe", "reason": "z"},
        "psf/black": {"why_now": "x", "use_for": "y", "verdict": "try", "reason": "z"},
        "old/project": {"why_now": "x", "use_for": "y", "reason": "z"},
        "ghost/missing": "not an object",
        "evil/desc": {"why_now": long_why, "use_for": long_use, "verdict": "Try", "reason": long_reason},
        "ghost/nodot": {
            "why_now": "**Bold** and `code` and\na newline\r\n- and a list marker",
            "use_for": "_italic_ <!-- hidden --> <b>tag</b> by @torvalds in [a thread](https://x.com/y) and #12, ~~old~~ www.x.io/z",
            "verdict": "  Watch ",
            "reason": "1. not a list > not a quote",
        },
        "pola-rs/polars": {"why_now": "", "use_for": None, "verdict": "Skip", "reason": ""},
    }
    rr = run_render(bad)
    check(rr["rc"] == 0, "render returns 0 despite bad entries")
    btext = rr["text"]
    check_design_invariants(btext)
    check(True, "design invariants hold with hostile brief text")
    err = rr["stderr"]
    check("blader/humanizer: dropping brief with invalid verdict 'Maybe'" in err, "bad verdict dropped with a stderr log")
    check("psf/black: dropping brief with invalid verdict 'try'" in err and "old/project: dropping brief with invalid verdict None" in err,
          "verdict is case-sensitive and required")
    check("ghost/missing: ignoring non-object entry" in err, "non-object entry logged")
    blines = btext.rstrip("\n").splitlines()
    for name in ("blader/humanizer", "psf/black", "old/project", "ghost/missing"):
        i = [k for k, l in enumerate(blines) if l.startswith(f"- **[{name}]")][0]
        assert "`Try`" not in blines[i] and not any(l.startswith("  > ") for l in blines[i + 1:i + 3] if not l.startswith("- ")), name
    check(True, "dropped briefs leave no tag and no blockquote")
    evil = [l for l in blines if l.startswith("  > ")]
    ev = [l for l in evil if "*Why now.* word" in l][0]
    why = ev.split("*Why now.* ")[1].split(" *Use it for.*")[0]
    use = ev.split("*Use it for.* ")[1].split(" *Verdict.*")[0]
    reason = ev.split("*Verdict.* Try — ")[1]
    check(why.endswith("…") and len(why) <= 320 and why[:-1] == why[:-1].rstrip() and why[:-1].endswith("word"), f"why_now truncated at a word boundary ({len(why)} <= 320)")
    check(use.endswith("…") and len(use) <= 200 and use[:-1].endswith("verb"), f"use_for truncated at a word boundary ({len(use)} <= 200)")
    check(reason.endswith("…") and len(reason) <= 160 and reason[:-1].endswith("why"), f"reason truncated at a word boundary ({len(reason)} <= 160)")
    i = [k for k, l in enumerate(blines) if l.startswith("- **[evil/desc]")][0]
    check(blines[i].endswith(" `Try`") and blines[i + 2] is ev, "over-long brief still tagged and placed under its entry")
    nd = [l for l in evil if "Bold" in l][0]
    check(nd == "  > *Why now.* \\*\\*Bold\\*\\* and \\`code\\` and a newline - and a list marker "
                "*Use it for.* \\_italic\\_ &lt;!-- hidden --> &lt;b>tag&lt;/b> by @​torvalds in a thread and #​12, \\~\\~old\\~\\~ "
                "*Verdict.* Watch — 1. not a list > not a quote",
          "markdown, backticks, HTML, links, mentions and newlines inside brief text neutralised and collapsed to one line; "
          "no block-start escape mid-line (no stray backslash before '- ' or '1. ')")
    check("  Watch " not in nd and blines[[k for k, l in enumerate(blines) if l.startswith("- **[ghost/nodot]")][0]].endswith("**"), "verdict whitespace stripped; Watch gets no tag")
    pol = [l for l in evil if "*Verdict.* Skip" in l][0]
    check(pol == "  > *Verdict.* Skip", "empty why_now/use_for/reason: labels omitted, verdict alone")
    check("2 brief(s)" not in rr["stdout"] and "3 brief(s)" in rr["stdout"], "three briefs survived (evil/desc, ghost/nodot, polars)")

    # ------------------------------------------------ 1d. damaged digest.json
    print("== render with a damaged digest.json: one error line, digest.md untouched ==")
    before = read_if_exists("digest.md")
    good = json.loads(read_if_exists("digest.json"))
    for label, mutate, expect in (
        ("entry missing is_new/weeks", lambda d: (d["repos"][1].pop("is_new"), d["repos"][1].pop("weeks")), "repo #2 is missing is_new, weeks"),
        ("entry is not an object", lambda d: d["repos"].__setitem__(3, "junk"), "repo #4 is not an object"),
        ("stars of the wrong type", lambda d: d["repos"][0].__setitem__("stars", "lots"), "could not render digest.json (TypeError"),
    ):
        damaged = json.loads(json.dumps(good))
        mutate(damaged)
        with open("digest.json", "w", encoding="utf-8") as f:
            json.dump(damaged, f)
        rr = run_render(BRIEFS)  # bd.main() is called directly: a traceback would escape as an exception here
        check(rr["rc"] == 1 and rr["text"] == before, f"{label}: rc 1, no traceback, digest.md left as it was")
        errs = [l for l in rr["stderr"].splitlines() if l.startswith("error: ")]
        check(len(errs) == 1 and expect in errs[0] and "run the build first" in errs[0], f"{label}: exactly one clear error line naming the problem")
    with open("digest.json", "w", encoding="utf-8") as f:
        json.dump(good, f)
    rr = run_render(BRIEFS)
    check(rr["rc"] == 0 and "4 brief(s)" in rr["stdout"] and rr["text"] != before, "restored digest.json renders again (with the good briefs this time)")

    # ------------------------------------------------ 1e. render without digest.json
    os.remove("digest.json")
    rr = run_render(BRIEFS)
    check(rr["rc"] == 1 and "could not read digest.json" in rr["stderr"], "render without digest.json fails clearly")

# ====================================================== 2. history endpoint fails
print("== history endpoint raises URLError ==")
with run_main(env={"GH_TOKEN": "gh456"}, history_fails=True) as r:
    check(r["rc"] == 0, "run succeeds")
    lines = r["text"].rstrip("\n").splitlines()
    check(lines[0] == "10 repos on GitHub Trending this week · 10 new · 0 still trending", "everything NEW")
    check("## Still trending" not in r["text"], "no still-trending section")
    check(entries(r["text"]) == FEED_ORDER, "feed order preserved")
    check("could not fetch prior digests" in r["stderr"], "history failure logged")
    check(lines[-1].startswith("<!-- digest-data "), "marker still last line")
    check_design_invariants(r["text"])
    check(True, "design invariants hold")
    check(all(c["headers"].get("Authorization") == "Bearer gh456" for c in r["calls"] if "api.github.com" in c["url"]), "GH_TOKEN honoured")

# ======================================================= 3. no token -> no auth
print("== no token in env ==")
with run_main(env={}) as r:
    check(r["rc"] == 0, "run succeeds without token")
    api_calls = [c for c in r["calls"] if "api.github.com" in c["url"]]
    check(api_calls and all("Authorization" not in c["headers"] for c in api_calls), "no Authorization header sent")

# ============================================================= 4. feed fails
print("== feed fails ==")
with run_main(env={}, feed_fails=True) as r:
    check(r["rc"] != 0, f"non-zero exit ({r['rc']})")
    check("could not fetch trending feed" in r["stderr"] and FEED_URL in r["stderr"], "clear error message on stderr")
    check(r["text"] is None and r["json"] is None, "no digest.md or digest.json written")
    check(len(r["calls"]) == 1, "no API calls after feed failure")

# ==================================================== 5. same-day rerun ignored
print("== same-day rerun does not count today's issue ==")
ISSUES.insert(0, {"number": 9, "title": f"Trending digest — {TODAY}", "body": ISSUE_6_BODY.replace(D3, TODAY), "created_at": f"{TODAY}T00:00:00Z"})
try:
    with run_main(env={}) as r:
        check(r["rc"] == 0 and "10 repos on GitHub Trending this week · 6 new · 4 still trending" in r["text"], "counts unchanged with a same-day issue present")
        check("3 prior digest(s)" in r["stdout"] and "TypeScript · 3rd week" in r["text"], "same-day issue excluded from history; week counts unchanged")
finally:
    ISSUES.pop(0)

# ============================================ 5b. duplicate past day counts once
print("== a past day that was run twice counts once ==")
ISSUES.insert(1, {"number": 10, "title": f"Trending digest — {D1}", "body": ISSUE_8_BODY, "created_at": f"{D1}T23:00:00Z"})
try:
    with run_main(env={}) as r:
        check(r["rc"] == 0 and "10 repos on GitHub Trending this week · 6 new · 4 still trending" in r["text"], "counts unchanged with a duplicate past-day issue")
        check("3 prior digest(s)" in r["stdout"] and "TypeScript · 3rd week" in r["text"], "duplicate past-day issue counted once")
finally:
    ISSUES.pop(1)

# ============================================ 5c. earlier digest this ISO week ignored
print("== a digest earlier this ISO week does not count as history ==")
_monday = NOW - timedelta(days=NOW.weekday())
SAME_WEEK = (_monday if _monday.strftime("%Y-%m-%d") != TODAY else _monday + timedelta(days=1)).strftime("%Y-%m-%d")
ISSUES.insert(0, {"number": 9, "title": f"Trending digest — {SAME_WEEK}", "body": ISSUE_6_BODY.replace(D3, SAME_WEEK), "created_at": f"{SAME_WEEK}T00:00:00Z"})
try:
    with run_main(env={}) as r:
        check(r["rc"] == 0 and "10 repos on GitHub Trending this week · 6 new · 4 still trending" in r["text"], "counts unchanged with a same-week issue present")
        check("3 prior digest(s)" in r["stdout"] and "TypeScript · 3rd week" in r["text"], "same-week issue excluded from history; week counts unchanged")
finally:
    ISSUES.pop(0)

# ===================================== 5d. two digests in one past week count once
print("== two digests on different days of one past week count once ==")
D1_NEXT = (NOW - timedelta(days=6)).strftime("%Y-%m-%d")
ISSUES.insert(0, {"number": 10, "title": f"Trending digest — {D1_NEXT}", "body": ISSUE_8_BODY, "created_at": f"{D1_NEXT}T23:00:00Z"})
try:
    with run_main(env={}) as r:
        check(r["rc"] == 0 and "3 prior digest(s)" in r["stdout"] and "TypeScript · 3rd week" in r["text"], "second digest in a past week counted once")
finally:
    ISSUES.pop(0)
check(bd.digest_week("Trending digest — 2026-09-21") == bd.digest_week("Trending digest — 2026-09-22") == (2026, 39), "same ISO week")
check(bd.digest_week("Trending digest — 2026-09-20") == (2026, 38), "sunday belongs to the previous ISO week")
check(bd.digest_week("Trending digest — PR") == "Trending digest — PR" and bd.digest_week("x — 2026-13-40") == "x — 2026-13-40", "unparsable titles fall back to the text")

# ============================================ 5e. web link in the standfirst
print("== DIGEST_PAGE_URL adds one link at the end of the standfirst ==")
with run_main(env={"DIGEST_PAGE_URL": "https://example.github.io/trending-digest/"}) as r:
    first = r["text"].splitlines()[0]
    check(first.endswith(" · [Read on the web](https://example.github.io/trending-digest/)"), "standfirst ends with the page link")
    check(first.startswith("10 repos on GitHub Trending this week · 6 new · 4 still trending"), "counts unchanged before the link")
    check(r["text"].count("Read on the web") == 1, "the link appears once")
with run_main(env={}) as r:
    check("Read on the web" not in r["text"], "no link without DIGEST_PAGE_URL")

# ================================================================ unit checks
print("== unit checks ==")
check([bd.ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 101, 111)] ==
      ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "23rd", "101st", "111th"], "ordinals")
check([bd.fmt_stars(n) for n in (0, 999, 1000, 12345, 999_499, 1_000_000, 1_234_567)] ==
      ["0", "999", "1k", "12.3k", "999.5k", "1M", "1.2M"], "star formatting")
check([bd.fmt_stars(n) for n in (999_949, 999_950, 999_999)] == ["999.9k", "1M", "1M"], "rounding carries k into M")
check(bd.fmt_delta(999_950) == "+1M", "delta uses the same carry")
check([bd.fmt_delta(d) for d in (0, 5, -5, 1200, -12345)] == ["+0", "+5", "-5", "+1.2k", "-12.3k"], "delta formatting with sign")
check(bd.truncate("a" * 200) == "a" * 200 and bd.truncate("word " * 50).endswith("…") and len(bd.truncate("word " * 50)) <= 200, "truncate boundary")
check(bd.truncate("a " + "b" * 300) == "a " + "b" * 197 + "…" and bd.truncate("-" * 300) == "", "truncate keeps text when the only space is early; empty when nothing readable")
check(bd.truncate("word " * 100, 320).endswith("…") and len(bd.truncate("word " * 100, 320)) <= 320, "truncate honours a custom limit")
check(bd.tagline_from_feed('<div align="center"><img src="b.svg"></div><p>Tagline here</p><h1>Readme</h1>') == "Tagline here"
      and bd.tagline_from_feed("Bare text https://x.io") == "Bare text" and bd.tagline_from_feed("") == "",
      "tagline: skips a leading badge block, strips trailing URL, empty in -> empty out")
_item = {"owner": "a", "repo": "b", "name": "a/b", "link": "https://github.com/a/b", "feed_text": "<p>Feed tagline.</p>", "rank": 1}
_real_fetch_repo = bd.fetch_repo
try:
    for shape in ({"license": "MIT"}, {"description": 123}, {"topics": "python", "stargazers_count": True}, []):
        bd.fetch_repo = lambda o, r, t=None, d=shape: d
        rr = bd.enrich(_item)
        assert rr["topics"] == [] and rr["stars"] is None and rr["description"] == "Feed tagline." and rr["rank"] == 1, (shape, rr)
finally:
    bd.fetch_repo = _real_fetch_repo
check(True, "unexpected API response shapes fall back instead of raising; rank survives")
check(bd.md_escape("# head") == "\\# head" and bd.md_escape("a < b") == "a < b" and bd.md_escape("#1 tool") == "#​1 tool", "md_escape edge cases")
check(bd.md_escape("1. x") == "1\\. x" and bd.md_escape("2024) y") == "2024\\) y" and bd.md_escape("1.x") == "1.x",
      "ordered-list marker: backslash before the punctuation, not the digits (\\1 is not a CommonMark escape)")
check(bd.md_escape("- a", block_start=False) == "- a" and bd.md_escape("1. a", block_start=False) == "1. a" and bd.md_escape("*a*", block_start=False) == "\\*a\\*",
      "block_start=False keeps inline escapes only")
check(bd.md_escape("**b** _i_ a_b https://x.io/a_b *c*") == "\\*\\*b\\*\\* \\_i\\_ a_b https://x.io/a_b \\*c\\*", "md_escape neutralises emphasis, keeps intraword underscores")
check(bd.md_escape("by @torvalds, see #12 and owner/repo#3, [t](u) ~~x~~ a@b.c") == "by @​torvalds, see #​12 and owner/repo#​3, \\[t](u) \\~\\~x\\~\\~ a@​b.c",
      "md_escape breaks @mention and #issue autolinks, escapes link brackets and tildes")
check(bd.strip_links("see [foo/bar](https://github.com/foo/bar) with it") == "see foo/bar with it"
      and bd.strip_links("Docs: https://x.dev/a_b") == "Docs" and bd.strip_links("Go to www.x.io/y now") == "Go to now"
      and bd.strip_links(None) == "" and bd.strip_links("plain.") == "plain.",
      "strip_links: markdown links keep their text, bare http/www URLs go, dangling punctuation trimmed")
check(bd.brief_text(123, 10) == "" and bd.brief_text("  a\n\nb  ", 10) == "a b", "brief_text: non-strings become empty, whitespace collapsed")
check(bd.brief_text("- 1. x [l](https://a.b) https://c.d", 100) == "- 1. x l", "brief_text: no block-start escape, links stripped")
check(bd.entry_lines({"name": "a/b", "link": "https://github.com/a/b", "archived": False, "stars": None, "language": None,
                      "license": None, "description": "", "is_new": True, "weeks": 1, "delta": None},
                     {"why_now": "", "use_for": "", "verdict": "Try", "reason": ""}) ==
      ["- **[a/b](https://github.com/a/b)** `Try`", "  > *Verdict.* Try"], "entry with no metadata and a Try brief: tag directly after the name, no ' — '")
p = bd.parse_digest(ISSUE_8_BODY)
check("anthropics/claude-code" in p["present"] and "user-attachments/ass" not in p["present"] and p["stars"] == {}, "presence from markdown links only; plain links in descriptions ignored; no marker")
p6 = bd.parse_digest(ISSUE_6_BODY)
check(p6["date"] == D3 and p6["stars"]["anthropics/claude-code"] is None and p6["stars"]["psf/black"] == 41500, "marker parsed")

print(f"\nALL {passed} CHECKS PASSED")
