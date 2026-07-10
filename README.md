# claude-status

> **Zero-dependency status line for Claude Code. One command. Every metric. All platforms.**

[![PyPI version](https://img.shields.io/pypi/v/claude-status)](https://pypi.org/project/claude-status/)
[![Python 3.8–3.14](https://img.shields.io/pypi/pyversions/claude-status)](https://pypi.org/project/claude-status/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/mkalkere/claude-statusline/actions/workflows/ci.yml/badge.svg)](https://github.com/mkalkere/claude-statusline/actions)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)](https://pypi.org/project/claude-status/)
[![Downloads](https://img.shields.io/pypi/dm/claude-status)](https://pypi.org/project/claude-status/)

**Try it now — no install, no config change:**

```bash
uvx claude-status --demo    # or: pipx run claude-status --demo
```

![claude-status default theme](https://raw.githubusercontent.com/mkalkere/claude-statusline/main/assets/themes/default.svg)

```
Line 1:  [████████░░░░░░░░░░░░] │ in:412K out:18K │ cache:46% │ $0.73 │ burn:66K/min
Line 2:  5h:34% 7d:18% ~2h │ (1M) │ 12m05s │ +247 -38 │ ⎇ myapp/feat/statusline │ ✦ refactor auth │ Sonnet 5 │ effort:high │ v0.10.0 │ CC:2.1.197 │ 15:30
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
| Token Counts | `in:412K out:18K` | Human-readable (K/M) — no squinting at raw numbers |
| Cache Hit Ratio | `cache:87%` | Of cacheable prompt input, how much actually hit the cache — close to 100% means cache-friendly prompts |
| Cost | `$0.73` | Session cost in real-time — cents for small, dollars for large |
| Budget | `day:$7.4/$10` | Color-coded daily budget tracker (green/yellow/red). Sums today's spend across all sessions on this machine (v0.12.0+); set `"budget_scope": "session"` in the config for the old per-session comparison. |
| Burn Rate | `burn:37K/min` | Tokens/min consumption — unique to claude-status |
| Cost Rate | `~$3.6/hr` | Projected session cost per hour (session average, includes idle time; the `~` marks it as a projection). Hidden for sessions under a minute. Opt-in via custom theme. |
| Rate Limits | `5h:34% 7d:18% ~2h` | API usage limits with reset countdown (Pro/Max only) |
| Context Size | `(1M)` | Know if you're on a 200K or 1M context window |
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
| Activity | `act:3` | Live tool-call counter for the current assistant turn — resets on each user prompt (opt-in; reads transcript tail, 5s cache, hidden when zero) |
| Cache Age | `cache_age:4m12s` | Time since the last assistant turn — a cue for how long a task has run and whether the ~5-min prompt cache is still warm. Warning color past 5 min. Reads the last assistant message timestamp from the transcript tail (opt-in; 5s cache, hidden when unavailable). |
| Sessions Today | `sessions:3` | How many sessions you've started today |
| Session Name | `✦ refactor auth` | Custom session name (via `--name` or `/rename`) |
| Vim Mode | `NORMAL` | Blue for NORMAL, green for INSERT |
| Agent | `[Explore]` | Shows which subagent is active |
| Worktree | `wt:fix/bug-123` | Claude Code worktree branch indicator |
| Model | `Sonnet 5` | Active model name |
| Output Style | `style:explanatory` | Active output style when set |
| Added Dirs | `dirs:+2` | Extra directories added via `/add-dir` |
| Effort Level | `effort:high` | Thinking effort: `low`, `high`, `xhigh`, or `max`. Shown when non-default. Read from stdin JSON `effort.level` (Claude Code v2.1.119+) for instant updates; falls back to `~/.claude/settings.json` for older versions. (The `/effort ultracode` setting reports as `xhigh` per Claude Code's documented enum; an `ultra` value from earlier installs is accepted as a silent alias that renders as `xhigh`.) |
| Thinking | `think` | Shown when extended thinking is enabled for the session. Reads `thinking.enabled` from stdin; surfaces only the on state (an off badge would be noise). Opt-in via custom theme. |
| Pull Request | `PR#86 ok` | Current GitHub PR number when detected, clickable to the PR page via OSC 8. Reads `pr.number` / `pr.url` from stdin (newer Claude Code releases) with `github.pr_number` / `github.pr_url` as a fallback for older releases. When `pr.review_state` is present, a short status token follows the number: `ok` (approved), `chg` (changes requested), `rev` (pending review), `draft`. Opt-in via custom theme. |
| Cost Breakdown | `mcp:$0.80` | Largest non-base cost category from `cost.by_category` (newer Claude Code releases). Falls back to `other:$N` (sum) when no single category exceeds $0.01 but multiple together do. Opt-in via custom theme. |
| Version | `v0.10.0` | claude-status version |
| CC Version | `CC:2.1.197` | Claude Code application version |
| Clock | `15:30` | Current time |

## Themes

8 built-in themes to match your terminal aesthetic. Preview all live with `claude-status --demo`. Screenshots below show each theme rendered with one fixed dark palette — themes select ANSI colors; your own terminal palette supplies the exact hues.

### default — full detail, clean separators
![default theme](https://raw.githubusercontent.com/mkalkere/claude-statusline/main/assets/themes/default.svg)

### minimal — just the essentials
![minimal theme](https://raw.githubusercontent.com/mkalkere/claude-statusline/main/assets/themes/minimal.svg)

### powerline — Nerd Font separators
![powerline theme](https://raw.githubusercontent.com/mkalkere/claude-statusline/main/assets/themes/powerline.svg)

### focus — single line, minimal footprint
![focus theme](https://raw.githubusercontent.com/mkalkere/claude-statusline/main/assets/themes/focus.svg)

### nord — cool blue tones
![nord theme](https://raw.githubusercontent.com/mkalkere/claude-statusline/main/assets/themes/nord.svg)

### tokyo-night — purple and blue accents
![tokyo-night theme](https://raw.githubusercontent.com/mkalkere/claude-statusline/main/assets/themes/tokyo-night.svg)

### gruvbox — warm retro palette
![gruvbox theme](https://raw.githubusercontent.com/mkalkere/claude-statusline/main/assets/themes/gruvbox.svg)

### rose-pine — soft muted pinks
![rose-pine theme](https://raw.githubusercontent.com/mkalkere/claude-statusline/main/assets/themes/rose-pine.svg)

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

### Detecting your real terminal width

Claude Code spawns the statusLine command as a subprocess with stdin piped — there is no TTY and no `COLUMNS` env var, so naive width detection always returns the fallback. Until Anthropic ships terminal dimensions in the stdin JSON ([anthropics/claude-code#22115](https://github.com/anthropics/claude-code/issues/22115), still open), claude-status walks a fallback chain to recover the real width: stdin `terminal.columns` → `COLUMNS` env → `shutil.get_terminal_size` → `os.get_terminal_size(fd)` → **process-tree walk** (find a TTY-owning ancestor process, Linux only) → `stty size < /dev/tty` → `tput cols 2>/dev/tty`. Run `claude-status --doctor` to see which signal won on your machine and which signals lied or fell through.

**Claude Code 2.1.139+ regression handling.** 2.1.139 (2026-05-11) shipped "hooks now run without terminal access," which closed the `/dev/tty` escape hatch and — more dangerously — caused `tput cols` to confidently return its terminfo default (80 for most `TERM` values) instead of failing. v0.6.0 added two specific defenses: a stub-detection heuristic that rejects `tput cols == 80` when no earlier TTY probe succeeded (the 2.1.139 fingerprint), and a process-tree walk that reads the controlling terminal of an ancestor process on Linux. Without these, users on 2.1.139 with a 220-col terminal were silently rendering an 80-col layout.

**Override when detection still gets it wrong.** Set `CLAUDE_STATUSLINE_WIDTH=N` to force a specific layout width regardless of detection. Useful for headless CI, nested multiplexers where every probe lies, or when you want a narrower layout than your terminal actually offers (e.g. `CLAUDE_STATUSLINE_WIDTH=120` on a 200-col terminal). Out-of-range or non-numeric values fall through silently — set it back to empty or unset it to restore auto-detection.

This design exists because Claude Code's TUI uses Ink `<Text wrap="truncate">` on the statusline ([anthropics/claude-code#28750](https://github.com/anthropics/claude-code/issues/28750), the per-line truncation case was fixed in 2.1.141 via [#58028](https://github.com/anthropics/claude-code/issues/58028), but the underlying terminal-width detection problem is still unfixed): if Line 1 overflows the terminal, Line 2 may be silently dropped on older Claude Code releases. Measuring our actual rendered width and dropping low-priority sections one at a time prevents this without sacrificing useful information on wider terminals.

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
Create `~/.claude/claude-status-budget.json` with `{"daily_budget_usd": 10.00}`. The chip renders `day:$7.4/$10` — today's spend summed across all your sessions on this machine — turning yellow at 70% and red at 90% of your daily limit. Three things to know:

- **Per machine.** The total comes from local session records, so it will undercount your real bill if you also run Claude Code on another computer.
- **Accumulates from the moment you upgrade** to v0.12.0 — on the first day the total may miss sessions from earlier that morning.
- **Prefer the old behavior?** Versions before v0.12.0 compared only the *current session's* cost against the daily budget. If you calibrated your number as a per-session ceiling, set `"budget_scope": "session"` in the same config file to keep that comparison (the chip then renders without the `day:` prefix).

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

Upgrade to the latest release (`pip install -U claude-status`). The status line auto-adapts to your terminal width — no configuration needed. If you want a single-line display regardless of width, switch to the `focus` theme (`claude-status --install --theme focus`). Originally tracked upstream at anthropics/claude-code#28750 (auto-closed in March without engagement); Claude Code 2.1.141 later shipped a partial fix via [#58028](https://github.com/anthropics/claude-code/issues/58028) for the per-line truncation case. The underlying terminal-width detection problem ([#22115](https://github.com/anthropics/claude-code/issues/22115)) is still open, so claude-status's adaptive layout remains load-bearing.

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
