# claude-status

> **Zero-dependency status line for Claude Code. One command. Every metric. All platforms.**

[![PyPI version](https://img.shields.io/pypi/v/claude-status)](https://pypi.org/project/claude-status/)
[![Python 3.8–3.14](https://img.shields.io/pypi/pyversions/claude-status)](https://pypi.org/project/claude-status/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/mkalkere/claude-statusline/actions/workflows/ci.yml/badge.svg)](https://github.com/mkalkere/claude-statusline/actions)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)](https://pypi.org/project/claude-status/)
[![Downloads](https://img.shields.io/pypi/dm/claude-status)](https://pypi.org/project/claude-status/)

```
Line 1:  [████████░░░░░░░░░░░░] │ in:245K out:18K │ cache:41% │ $0.73 │ burn:36K/min │ (200K)
Line 2:  12m05s │ api:2m31s │ +247 -38 │ ⎇ trader/main │ Opus 4.6 (1M context) │ [Explore] │ wt:fix/bug-123
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
- **Every metric that matters** — 14 data points including burn rate (tokens/min), a metric no other statusline tracks
- **Cross-platform** — tested on Windows, macOS, and Linux across Python 3.8–3.14 (21 CI jobs)
- **Instant setup** — `--install` auto-configures Claude Code. No manual JSON editing

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
| Context Warning | `!CTX` | Bold red alert when you exceed 200K tokens |

### Line 2 — Session Context
| Feature | What You See | Why It Matters |
|---------|-------------|----------------|
| Duration | `12m05s` | Wall-clock session time |
| Lines Changed | `+247 -38` | Git-diff style — green additions, red removals |
| Git Branch | `⎇ feat/statusline` | Green for main/master, yellow for feature branches |
| Vim Mode | `NORMAL` | Blue for NORMAL, green for INSERT (when vim mode is on) |
| Agent | `[Explore]` | Shows which subagent is active |
| Worktree | `wt:fix/bug-123` | Worktree branch indicator |

## Themes

### default — full detail, clean separators
```
[████████░░░░░░░░░░░░] │ in:245K out:18K │ cache:41% │ $0.73 │ burn:36K/min │ (200K)
12m05s │ +247 -38 │ ⎇ feat/statusline
```

### minimal — just the essentials
```
●●●●●●●●·············· in:245K out:18K $0.73
12m05s ⎇ feat/statusline
```

### powerline — Nerd Font separators
```
████████░░░░░░░░░░░░  in:245K out:18K  cache:41%  $0.73  burn:36K/min  (200K)
12m05s  +247 -38  ⎇ feat/statusline
```

Preview all themes live: `claude-status --demo`

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
| `claude-status --install` | Auto-configure Claude Code settings |
| `claude-status --install --theme powerline` | Install with a specific theme |
| `claude-status --demo` | Preview all 3 themes with sample data |
| `claude-status --doctor` | Diagnostics: Python version, OS, terminal, current settings |
| `claude-status --version` | Show version |
| `claude-status --help` | Show usage |

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
| **Themes** | 3 | 100 | 1 |
| **Burn rate** | Yes | No | No |
| **Two-line layout** | Yes | Yes | No |
| **Auto-install** | `--install` | `init` | Manual |
| **Analytics/Dashboard** | No | Yes | No |
| **Background daemon** | No | Yes | No |

**Our philosophy:** Do one thing well. Show every metric you need, nothing you don't. Install in 2 seconds, work everywhere, break never.

## Uninstall

```bash
pip uninstall claude-status
```

Then remove `"statusLine"` from `~/.claude/settings.json`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
