# Christchurch rent growth skill

An agent skill that charts Christchurch City rent growth from the latest MBIE / Tenancy Services rental bond data and drafts a rent-review message for a landlord.

On each run the agent asks for the property address and current weekly rent, downloads the current official release, and writes a chart (PNG and PDF), monthly CSV, and summary JSON to `runs/<date>/` in the folder it was opened in. It finishes with an example landlord message, with the proposed rent rounded to the nearest $5.

## Install

Ask your agent:

> Install the skill from https://github.com/future3OOO/christchurch-rent-growth/tree/main/skills/christchurch-rent-growth

Or install it by hand by copying `skills/christchurch-rent-growth/` into your agent's skills folder:

| Agent | Skills folder |
|---|---|
| Codex | `~/.codex/skills/` |
| Claude Code | `~/.claude/skills/` |
| Per project | `.agents/skills/` in the project |

Start a new session after installing, then ask for a Christchurch rent review.

## Requirements

Python 3.8 or newer and internet access. The skill installs Matplotlib into `runs/.venv` on first use if it is missing. Works on Windows, macOS, and Linux.
