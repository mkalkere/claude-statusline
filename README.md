# claude-status

> **Zero-dependency status line for Claude Code. One command. Every metric. All platforms.**

[![PyPI version](https://img.shields.io/pypi/v/claude-status)](https://pypi.org/project/claude-status/)
[![Python 3.8–3.14](https://img.shields.io/pypi/pyversions/claude-status)](https://pypi.org/project/claude-status/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/mkalkere/claude-statusline/actions/workflows/ci.yml/badge.svg)](https://github.com/mkalkere/claude-statusline/actions)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)](https://pypi.org/project/claude-status/)
[![Downloads](https://img.shields.io/pypi/dm/claude-status)](https://pypi.org/project/claude-status/)

```
Line 1:  [████████░░░░░░░░░░░░] │ in:245K out:18K │ cache:41% │ $0.73 │ burn:37K/min
Line 2:  5h:34% 7d:18% ~2h │ (200K) │ 12m05s │ +247 -38 │ ⎇ myapp/feat/statusline │ ✦ refactor auth │ Opus │ effort:high │ v0.5.0 │ CC:2.1.92 │ 15:30
```

## 30-Second Setup

```bash
pip install claude-status
claude-status --setup
```

The setup wizard walks you through theme selection, budget configuration, and installs everything automatically. Restart Claude Code and you're done.

## Why claude-status?

- **Zero dependencies** — pure Python stdlib. No `psutil`, no `colorama`, no compilation. Installs in under 2 seconds
- **Every metric that matters** — 30+ data points including burn rate (tokens/min), rate limit tracking, and effort level
- **Rate limit awareness** — see your 5-hour and 7-day API usage at a glance with color-coded warnings and reset countdown
- **Responsive layout** — automatically adapts to your terminal width (full/compact/narrow)
- **NO_COLOR / FORCE_COLOR support** — respects terminal color standards
- **Clickable git branch** *(opt-in)* — OSC 8 links open repo in browser in iTerm2, Kitty, WezTerm. Off by default because Claude Code's TUI doesn't understand OSC 8 and would drop Line 2. Enable with `"clickable_links": true`.
- **Per-section toggle** — disable any section via config without a custom theme
- **8 built-in themes** — default, minimal, powerline, nord, tokyo-night, gruvbox, rose-pine, focus
- **Budget monitoring** — set a daily spend limit, get color-coded warnings as you approach it
- **Session analytics** — tool call count and today's session count at a glance
- **Cross-platform** — tested on Windows, macOS, and Linux across Python 3.8–3.14 (21 CI jobs)
- **Interactive setup** — `--setup` wizard walks you through theme selection and budget config
- **Clean uninstall** — `--uninstall` restores your previous configuration

## Features

### Line 1 — Metrics at a Glance
| Feature | What You See | Why It Matters |
|---------|-------------|----------------|
| Context Bar | `[████████░░░░░░░░░░░░]` | Green/yellow/red adaptive — know your context budget instantly |
| Token Counts | `in:245K out:18K` | Human-readable (K/M) — no squinting at raw numbers |
| Cache Efficiency | `cache:41%` | See how much prompt cache is saving you |
| Cost | `$0.73` | Session cost in real-time — cents for small, dollars for large |
| Budget | `$0.73/$10` | Color-coded daily budget tracker (green/yellow/red) |
| Burn Rate | `burn:37K/min` | Tokens/min consumption — unique to claude-status |
| Rate Limits | `5h:34% 7d:18% ~2h` | API usage limits with reset countdown (Pro/Max only) |
| Context Size | `(200K)` | Know if you're on 200K or 1M context |
| Context Warning | `!CTX` | Bold red alert at 85%+ context usage |

### Line 2 — Session Context
| Feature | What You See | Why It Matters |
|---------|-------------|----------------|
| Duration | `12m05s` | Wall-clock session time |
| API Latency | `api:5m12s` | Time spent in API calls |
| Lines Changed | `+247 -38` | Git-diff style — green additions, red removals |
| Git Branch | `⎇ myapp/feat/statusline` | Project name + branch, color-coded |
| Git Stash | `stash:2` | Number of stashed changes |
| Git Sync | `sync:+2/-1` | Commits ahead/behind remote |
| Git State | `merge` / `conflict` | Merge/rebase/conflict indicator |
| Commit Age | `last:5m` | Time since last commit |
| Token Speed | `speed:1.2K/s` | Token throughput (tokens/sec) |
| Git Worktree | `gwt` | Indicator when inside a native git worktree |
| Tool Calls | `tools:42` | Number of tool calls in current session |
| Sessions Today | `sessions:3` | How many sessions you've started today |
| Session Name | `✦ refactor auth` | Custom session name (via `--name` or `/rename`) |
| Vim Mode | `NORMAL` | Blue for NORMAL, green for INSERT |
| Agent | `[Explore]` | Shows which subagent is active |
| Worktree | `wt:fix/bug-123` | Claude Code worktree branch indicator |
| Model | `Opus` | Active model name |
| Output Style | `style:explanatory` | Active output style when set |
| Added Dirs | `dirs:+2` | Extra directories added via `/add-dir` |
| Effort Level | `effort:high` | Thinking effort (shown when non-default) |
| Version | `v0.5.0` | claude-status version |
| CC Version | `CC:2.1.92` | Claude Code application version |
| Clock | `15:30` | Current time |

## Themes

8 built-in themes to match your terminal aesthetic. Preview all live with `claude-status --demo`.

### default — full detail, clean separators
```
[████████░░░░░░░░░░░░] │ in:245K out:18K │ cache:41% │ $0.73 │ burn:37K/min
5h:34% 7d:18% ~2h │ (200K) │ 12m05s │ +247 -38 │ ⎇ myapp/feat/statusline │ ✦ refactor auth │ Opus │ effort:high │ v0.5.0 │ CC:2.1.92 │ 15:30
```

### minimal — just the essentials
```
●●●●●●●●·············· in:245K out:18K $0.73 5h:34% 7d:18%
12m05s ⎇ feat/statusline sessions:3 Opus 15:30
```

### powerline — Nerd Font separators
```
████████░░░░░░░░░░░░  in:245K out:18K  cache:41%  $0.73  burn:37K/min
5h:34% 7d:18% ~2h  (200K)  12m05s  +247 -38  ⎇ myapp/feat/statusline  ✦ refactor auth  Opus  effort:high  v0.5.0  CC:2.1.92  15:30
```

### focus — single line, minimal footprint
```
[████████░░░░] │ $0.73 │ 5h:34% 7d:18% ~2h │ ⎇ main │ effort:high │ 15:30
```

### nord — cool blue tones
### tokyo-night — purple and blue accents
### gruvbox — warm retro palette
### rose-pine — soft muted pinks

## Installation

### pip (recommended)
```bash
pip install claude-status
claude-status --setup
```

### pipx (isolated — no venv pollution)
```bash
pipx install claude-status
claude-status --setup
```

### uvx (fast, modern)
```bash
uvx claude-status --setup
```

### From source (contributors)
```bash
git clone https://github.com/mkalkere/claude-statusline.git
cd claude-statusline
pip install -e .
claude-status --setup
```

### What `--setup` does

Walks you through theme selection with a compact preview, optional budget configuration, and writes the statusLine entry to `~/.claude/settings.json`. Preserves all your existing settings.

> **Command not found?** Ensure your Python scripts directory is in `PATH`.
> Fallback: `python -m claude_statusline --setup`

## For Coding Agents (Claude Code, Cursor, Aider, Continue, …)

If you're a coding agent installing this on a user's behalf, use the non-interactive one-liner:

```bash
pip install -U claude-status && claude-status --install && claude-status --print-config
```

That installs the package, writes the `statusLine` entry to `~/.claude/settings.json` (backing up any prior config), and prints the current install state in a deterministic key=value format you can parse to confirm success. The user must restart Claude Code for the new status line to appear.

For full agent recipes (themes, budget, verification, uninstall, troubleshooting), see [AGENTS.md](AGENTS.md).

## CLI Reference

| Command | Description |
|---------|-------------|
| `claude-status --setup` | Interactive setup wizard (recommended for first use) |
| `claude-status --install` | Auto-configure Claude Code settings (non-interactive) |
| `claude-status --install --theme nord` | Install with a specific theme |
| `claude-status --uninstall` | Remove from Claude Code settings (restores previous config) |
| `claude-status --print-config` | Show current install state in machine-readable form (for scripts/agents) |
| `claude-status --demo` | Preview all 8 themes with sample data |
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
  "daily_budget_usd": 10.00,
  "compaction_threshold_pct": 62
}
```

**Budget thresholds:**
- **Green**: under 70% of budget
- **Yellow**: 70–90% of budget
- **Red (bold)**: 90%+ of budget

**Compaction threshold:** When set, the context bar scales relative to the compaction point instead of the full context window. At 62%, the bar shows 100% when you reach 62% of the context window — the point where compaction triggers.

## Periodic Updates

By default, the status line updates after each assistant message. Add `refreshInterval` to your config for periodic updates — this keeps the clock, session count, and rate limit countdown current:

```json
{
  "statusLine": {
    "type": "command",
    "command": "claude-status --theme default",
    "refreshInterval": 10
  }
}
```

This runs the status line every 10 seconds in addition to the standard update triggers.

## Responsive Layout

The status line automatically adapts to your terminal width via a two-stage process:

1. **Coarse pre-filter** picks an eligible section list by terminal width:
   - **150+ columns**: full layout (all sections eligible)
   - **100–149 columns**: compact (drops the heaviest extras up front so we don't pay rendering cost on terminals where they won't fit)
   - **Under 100 columns**: narrow (essentials only — bar, tokens, cost, duration, branch)

2. **Precise width-aware fit** then measures the actual rendered width of each line (stripping invisible ANSI/OSC 8 escapes) and drops sections in priority order until the line fits the terminal. This means a 180-col terminal sees rate_limits, speed, version, etc., even though the static compact bucket would have hidden them — and a 110-col terminal stays within bounds even with heavy data (long agent name, vim mode active, long branch + session name).

The bar, tokens, cost, branch, and `!CTX` warning are always preserved — even at extreme widths, the statusline keeps its core identity.

This design exists because Claude Code's TUI uses Ink `<Text wrap="truncate">` on the statusline (anthropics/claude-code#28750, still unaddressed upstream): if Line 1 overflows the terminal, Line 2 is silently dropped. Measuring our actual rendered width and dropping low-priority sections one at a time prevents this without sacrificing useful information on wider terminals.

## Manual Configuration

Add to `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "claude-status",
    "refreshInterval": 10
  }
}
```

With a theme:

```json
{
  "statusLine": {
    "type": "command",
    "command": "claude-status --theme focus",
    "refreshInterval": 10
  }
}
```

## How It Works

Claude Code pipes session JSON to your `statusLine` command via stdin on every render cycle (and every `refreshInterval` seconds if configured). `claude-status` parses it, formats 27+ metrics across up to 2 lines, and prints to stdout. No daemon, no database, no background process — just a pure stdin-to-stdout pipe that runs in milliseconds.

## FAQ

**Does this work on Windows?**
Yes! Fully tested on Windows 11, macOS, and Linux across Python 3.8–3.14.

**Can I customize the colors?**
Yes — use `--theme custom` with a `~/.claude/claude-status-theme.json` file. Override any color or layout from the built-in themes.

**How does budget monitoring work?**
Create `~/.claude/claude-status-budget.json` with `{"daily_budget_usd": 10.00}`. The cost indicator turns yellow at 70% and red at 90% of your daily limit.

**What is burn rate?**
Tokens consumed per minute. Helps you gauge how fast you're using context in a session.

**Do I need a Pro/Max subscription for rate limit tracking?**
Yes. The `rate_limits` field is only included in the Claude Code JSON payload for Pro/Max subscribers. The section is automatically hidden for other users — no configuration needed.

**How often does the status line update?**
By default, after each assistant message. Add `"refreshInterval": 10` to your statusLine config for periodic updates every 10 seconds — recommended for keeping the clock and rate limit countdown current.

**Can I use a single-line layout?**
Yes — use the `focus` theme: `claude-status --install --theme focus`. It shows only the essentials on one line.

**Why is only Line 1 showing / Line 2 is missing or truncated?**
Claude Code's TUI uses Ink `<Text wrap="truncate">` which silently drops or truncates lines that exceed the terminal width. Several things can trigger this, all fixed:

1. **Line 1 visibly overflows** — fixed in v0.4.2 and v0.5.1 by moving sections to Line 2.
2. **OSC 8 clickable links add invisible escape bytes** — fixed in v0.5.2 by disabling OSC 8 by default.
3. **Line 2 grows past terminal width with heavy data** — fixed in v0.5.4 with a width-aware adaptive layout that measures actual rendered width and drops low-priority sections one at a time until each line fits. The full-layout threshold is now 150 cols (down from 230 in v0.5.3), and the precise post-render fit handles overflow gracefully across the entire range.

Upgrade to the latest release (`pip install -U claude-status`). The status line auto-adapts to your terminal width — no configuration needed. If you want a single-line display regardless of width, switch to the `focus` theme (`claude-status --install --theme focus`). Tracked upstream at anthropics/claude-code#28750 (closed without a fix after 30 days of inactivity).

**Does it add any latency to Claude Code?**
No. It runs as a pure stdin-to-stdout pipe in single-digit milliseconds. No daemon, no network calls, no background processes.

**Why does the session count seem low on Windows with WSL?**
Windows and WSL have separate `~/.claude/` directories, so sessions are counted independently. The status line shows sessions from the platform it's running on.

## Troubleshooting

If claude-status doesn't appear after installation:

1. Run `claude-status --doctor` to check your setup
2. Verify `~/.claude/settings.json` contains the `statusLine` entry
3. Ensure your Python scripts directory is in your `PATH`
4. Try `python -m claude_statusline --setup` as a fallback
5. Restart Claude Code after any configuration change

## Uninstall

```bash
claude-status --uninstall
```

This removes the statusLine entry from your settings and restores your previous configuration if a backup exists. Then:

```bash
pip uninstall claude-status
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
