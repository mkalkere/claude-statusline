# claude-status

> **Zero-dependency status line for Claude Code. One command. Every metric. All platforms.**

[![PyPI version](https://img.shields.io/pypi/v/claude-status)](https://pypi.org/project/claude-status/)
[![Python 3.8–3.14](https://img.shields.io/pypi/pyversions/claude-status)](https://pypi.org/project/claude-status/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/mkalkere/claude-statusline/actions/workflows/ci.yml/badge.svg)](https://github.com/mkalkere/claude-statusline/actions)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)](https://pypi.org/project/claude-status/)
[![Downloads](https://img.shields.io/pypi/dm/claude-status)](https://pypi.org/project/claude-status/)

```
Line 1:  [████████░░░░░░░░░░░░] │ in:245K out:18K │ cache:41% │ $0.73 │ $0.73/$10 │ burn:36K/min │ (200K)
Line 2:  12m05s │ api:5m12s │ +247 -38 │ ⎇ myapp/feat/statusline │ stash:2 │ tools:42 │ sessions:3 │ Opus │ v0.2.1 │ 15:30
```

## Quick Start

```bash
pip install claude-status
claude-status --install
```

Restart Claude Code. That's it — two lines of pure signal at the bottom of your terminal.

## Why claude-status?

- **Zero dependencies** — pure Python stdlib. No `psutil`, no `colorama`, no compilation. Installs in under 2 seconds
- **Two-line layout** — glanceable metrics on line 1, context details on line 2. Nothing gets truncated
- **Every metric that matters** — 20 data points including burn rate (tokens/min), a metric no other statusline tracks
- **Responsive layout** — automatically adapts to your terminal width (full/compact/narrow)
- **7 built-in themes** — default, minimal, powerline, nord, tokyo-night, gruvbox, rose-pine
- **Budget monitoring** — set a daily spend limit, get color-coded warnings as you approach it
- **Session analytics** — tool call count and today's session count at a glance
- **Cross-platform** — tested on Windows, macOS, and Linux across Python 3.8–3.14 (21 CI jobs)
- **Interactive setup** — `--setup` wizard walks you through theme selection and budget config

## Features

### Line 1 — Metrics at a Glance
| Feature | What You See | Why It Matters |
|---------|-------------|----------------|
| Context Bar | `[████████░░░░░░░░░░░░]` | Green/yellow/red adaptive — know your context budget instantly |
| Token Counts | `in:245K out:18K` | Human-readable (K/M) — no squinting at raw numbers |
| Cache Efficiency | `cache:41%` | See how much prompt cache is saving you |
| Cost | `$0.73` | Session cost in real-time — cents for small, dollars for large |
| Burn Rate | `burn:36K/min` | Tokens/min consumption — unique to claude-status |
| Context Size | `(200K)` | Know if you're on 200K or 1M context |
| Budget | `$0.73/$10` | Color-coded daily budget tracker (green/yellow/red) |
| Context Warning | `!CTX` | Bold red alert when you exceed 200K tokens |

### Line 2 — Session Context
| Feature | What You See | Why It Matters |
|---------|-------------|----------------|
| Duration | `12m05s` | Wall-clock session time |
| API Latency | `api:5m12s` | Time spent in API calls |
| Lines Changed | `+247 -38` | Git-diff style — green additions, red removals |
| Git Branch | `⎇ feat/statusline` | Green for main/master, yellow for feature branches |
| Git Stash | `stash:2` | Number of stashed changes |
| Git Sync | `sync:+2/-1` | Commits ahead/behind remote |
| Tool Calls | `tools:42` | Number of tool calls in current session |
| Sessions Today | `sessions:3` | How many sessions you've started today |
| Vim Mode | `NORMAL` | Blue for NORMAL, green for INSERT (when vim mode is on) |
| Agent | `[Explore]` | Shows which subagent is active |
| Worktree | `wt:fix/bug-123` | Worktree branch indicator |
| Model | `Opus 4.6 (1M context)` | Active model name |
| Version | `v0.2.1` | claude-status version |
| Clock | `15:30` | Current time |

## Themes

7 built-in themes to match your terminal aesthetic. Preview all live with `claude-status --demo`.

### default — full detail, clean separators
```
[████████░░░░░░░░░░░░] │ in:245K out:18K │ cache:41% │ $0.73 │ burn:36K/min │ (200K)
12m05s │ +247 -38 │ ⎇ myapp/feat/statusline │ tools:42 │ sessions:3 │ Opus 4.6 (1M context)
```

### minimal — just the essentials
```
●●●●●●●●·············· in:245K out:18K $0.73
12m05s ⎇ feat/statusline sessions:3 Opus 4.6 (1M context)
```

### powerline — Nerd Font separators
```
████████░░░░░░░░░░░░  in:245K out:18K  cache:41%  $0.73  burn:36K/min  (200K)
12m05s  +247 -38  ⎇ feat/statusline  tools:42  sessions:3  Opus 4.6 (1M context)
```

### nord — cool blue tones
### tokyo-night — purple and blue accents
### gruvbox — warm retro palette
### rose-pine — soft muted pinks

## Installation

### pip (recommended)
```bash
pip install claude-status
claude-status --install
```

### pipx (isolated — no venv pollution)
```bash
pipx install claude-status
claude-status --install
```

### uvx (fast, modern)
```bash
uvx claude-status --install
```

### From source (contributors)
```bash
git clone https://github.com/mkalkere/claude-statusline.git
cd claude-statusline
pip install -e .
claude-status --install
```

### What `--install` does

Reads your `~/.claude/settings.json`, adds the `statusLine` entry, preserves everything else. Use `--theme` to pick a theme:

```bash
claude-status --install --theme powerline
```

> **Command not found?** Ensure your Python scripts directory is in `PATH`.
> Fallback: `python -m claude_statusline --install`

## CLI Reference

| Command | Description |
|---------|-------------|
| `claude-status --setup` | Interactive setup wizard (recommended for first use) |
| `claude-status --install` | Auto-configure Claude Code settings |
| `claude-status --install --theme nord` | Install with a specific theme |
| `claude-status --demo` | Preview all 7 themes with sample data |
| `claude-status --doctor` | Diagnostics: Python version, OS, terminal, current settings |
| `claude-status --version` | Show version |
| `claude-status --help` | Show usage |

## Budget Monitoring

Set a daily spending limit to get color-coded warnings as you approach it:

```bash
claude-status --setup  # interactive wizard sets this up for you
```

Or manually create `~/.claude/claude-status-budget.json`:

```json
{
  "daily_budget_usd": 10.00
}
```

The budget indicator changes color based on usage:
- **Green**: under 70% of budget
- **Yellow**: 70–90% of budget
- **Red (bold)**: 90%+ of budget

### Compaction Threshold

Scale the context bar relative to your compaction threshold instead of the full context window:

```json
{
  "daily_budget_usd": 10.00,
  "compaction_threshold_pct": 62
}
```

With this set, the context bar shows 100% when you reach 62% of the context window — the point where compaction triggers.

### Responsive Layout

The status line automatically adapts to your terminal width:
- **120+ columns**: full detail (all sections)
- **80–119 columns**: compact (drops extras like git stash, version, clock)
- **Under 80 columns**: narrow (essentials only — bar, tokens, cost, duration, branch)

## Manual Configuration

Add to `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "claude-status"
  }
}
```

With a theme:

```json
{
  "statusLine": {
    "type": "command",
    "command": "claude-status --theme minimal"
  }
}
```

## How It Works

Claude Code pipes session JSON to your `statusLine` command via stdin on every render cycle. `claude-status` parses it, formats 14 metrics across 2 lines, and prints to stdout. No daemon, no database, no background process — just a pure stdin-to-stdout pipe that runs in milliseconds.

## Comparison

| | claude-status | claude-statusline | ccstatusline |
|---|:-:|:-:|:-:|
| **Language** | Python | Python | Node.js |
| **Dependencies** | **0** | 2 (psutil, colorama) | npm |
| **Install time** | ~2s | ~10s | ~15s |
| **Cross-platform** | Windows, macOS, Linux | Windows, macOS, Linux | Partial |
| **Themes** | 7 + custom | 100 | 1 |
| **Burn rate** | Yes | No | No |
| **Budget monitoring** | Yes | No | No |
| **Session analytics** | Yes | No | No |
| **Two-line layout** | Yes | Yes | No |
| **Interactive setup** | `--setup` | `init` | Manual |
| **Analytics/Dashboard** | No | Yes | No |
| **Background daemon** | No | Yes | No |

**Our philosophy:** Do one thing well. Show every metric you need, nothing you don't. Install in 2 seconds, work everywhere, break never.

## FAQ

**Does this work on Windows?**
Yes! Fully tested on Windows 11, macOS, and Linux across Python 3.8–3.14.

**Can I customize the colors?**
Yes — use `--theme custom` with a `~/.claude/claude-status-theme.json` file. Override any color or layout from the built-in themes.

**How does budget monitoring work?**
Create `~/.claude/claude-status-budget.json` with `{"daily_budget_usd": 10.00}`. The cost indicator turns yellow at 70% and red at 90% of your daily limit.

**What is burn rate?**
Tokens consumed per minute — a metric unique to claude-status. Helps you gauge how fast you're using context in a session.

**Does it add any latency to Claude Code?**
No. It runs as a pure stdin-to-stdout pipe in single-digit milliseconds. No daemon, no network calls, no background processes.

**Why does the session count seem low on Windows with WSL?**
Windows and WSL have separate `~/.claude/` directories, so sessions are counted independently. The status line shows sessions from the platform it's running on.

## Troubleshooting

If claude-status doesn't appear after installation:

1. Run `claude-status --doctor` to check your setup
2. Verify `~/.claude/settings.json` contains the `statusLine` entry
3. Ensure your Python scripts directory is in your `PATH`
4. Try `python -m claude_statusline --install` as a fallback
5. Restart Claude Code after any configuration change

## Uninstall

```bash
pip uninstall claude-status
```

Then remove `"statusLine"` from `~/.claude/settings.json`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
