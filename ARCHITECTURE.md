# Architecture

This document describes the internal structure of claude-status for contributors and tooling.

## Module Overview

```
claude_statusline/
├── __init__.py        # Version string (__version__)
├── __main__.py        # Entry point for python -m
├── cli.py             # CLI commands, data normalization, section rendering
├── bar.py             # Progress bar with adaptive coloring
├── colors.py          # ANSI color constants and colorize() helper
├── formatters.py      # Human-readable formatting (tokens, cost, duration)
├── git.py             # Git branch detection and extras (stash, ahead/behind)
├── sessions.py        # Session analytics, budget/effort config, cache management
└── themes.py          # 8 built-in themes + custom theme loader
```

## Data Flow

```
┌─────────────┐     stdin      ┌──────────────┐     stdout     ┌─────────────┐
│ Claude Code  │ ──── JSON ───→│ claude-status │ ──── ANSI ───→│  Terminal    │
│ (host app)   │               │  (this tool)  │    text        │ (status bar)│
└─────────────┘               └──────────────┘               └─────────────┘
```

### Render Pipeline

1. **`main()`** reads JSON from stdin
2. **`_normalize(data)`** flattens the nested Claude Code JSON into a flat dict, handling both old and new schema formats
3. **`_apply_responsive(sections, term_width)`** filters sections based on terminal width (120+/80-119/<80 cols)
4. **`_render_sections(normalized, order, theme)`** renders each section name into a colored string
5. **`render(data, theme_name)`** joins sections with themed separators into 1-2 lines
6. Output is printed to stdout

### Section Rendering

Each section in the theme's `line1`/`line2` list maps to a conditional renderer in `_render_sections()`. Sections only render when their data is present — missing data means the section is silently hidden, never an error.

## Design Principles

### Zero Dependencies
Pure Python stdlib only. No pip packages, no compilation, no runtime downloads. This ensures sub-2-second installs and zero supply chain risk.

### Never Crash
The status line runs on every prompt render. A crash means the user's terminal shows a Python traceback instead of useful metrics. Every external data source (stdin JSON, git subprocess, config files, cache files) is wrapped in exception handling that degrades gracefully to empty output.

- `_normalize()` uses `isinstance()` checks before `.get()` on external JSON
- `_safe_num()` coerces external numeric values or returns `None`
- `_first()` provides zero-safe fallback (unlike `or` which drops `0`)
- `render()` call in `main()` is wrapped in try/except as defense-in-depth
- Render errors emit to stderr, never to stdout

### File-Based Caching

Git and session data is cached to temp files to avoid expensive subprocess/filesystem operations on every render cycle.

| Data | TTL | Why |
|------|-----|-----|
| Git branch | 5s | Changes frequently during development |
| Git not available | 60s | Avoids repeated subprocess timeouts |
| Tool call count | 10s | Changes during active sessions |
| Session count | 30s | Only changes when new sessions start |
| Budget/compaction config | 30s | Rarely changes |
| Effort level | 30s | Toggles are infrequent |

Cache files are:
- **User-scoped** — stored in a `claude_sl_<user_hash>/` subdirectory of the system temp dir
- **Atomic** — written via `os.replace()` to prevent partial reads
- **Self-cleaning** — files older than 2 days are removed periodically

### Responsive Layout

Sections are dropped progressively based on terminal width:

- **120+ cols**: Full layout (all sections)
- **80-119 cols**: Compact (drops git_extras, version, cc_version, clock, worktree, sessions, tools, latency, context_size, session_name, rate_limits, output_style, added_dirs, effort, git_worktree)
- **<80 cols**: Narrow (additionally drops cache, burn, lines, budget, agent, model)

## Themes

Each theme is a dict with:
- `name` — theme identifier
- `separator` — string between sections (e.g., ` │ `)
- `bar_filled`, `bar_empty`, `bar_left`, `bar_right` — progress bar characters
- `bar_width` — bar character width (default: 20, focus: 12)
- `line1`, `line2` — ordered lists of section names to render
- `colors` — dict mapping color keys to ANSI escape codes

Custom themes override any keys from a base theme via `~/.claude/claude-status-theme.json`.

## Configuration Files

| File | Purpose |
|------|---------|
| `~/.claude/settings.json` | Claude Code settings, includes `statusLine` config |
| `~/.claude/claude-status-budget.json` | Daily budget limit and compaction threshold |
| `~/.claude/claude-status-theme.json` | Custom theme overrides |
| `~/.claude/sessions/*.json` | Session metadata (startedAt, pid, entrypoint) |
| `~/.claude/projects/<slug>/*.jsonl` | Session conversation data (tool call counting) |

## Testing

- **Framework**: stdlib `unittest` only (no pytest, no mock library)
- **Strategy**: test behavior via rendered output, not implementation details
- **Edge cases**: present, absent, empty, zero, non-dict, non-list, corrupted JSON
- **Isolation**: monkey-patch at `cli_mod` level for section rendering tests; clear cache files before config tests
- **CI**: 21-job matrix (3 OS x 7 Python versions: 3.8-3.14)
