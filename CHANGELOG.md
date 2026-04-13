# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.3] - 2026-04-13

### Fixed
- **Line 2 truncation at 120-col terminals** — after #68 fixed OSC 8, Line 2 rendered correctly but was truncated with an ellipsis on 120-col terminals because Line 2's full-layout content had grown to ~225 visible chars with a worst-case realistic payload (long session, long branch/session name, all rate limits populated) over v0.3-v0.5 (rate limits, speed, commit_age, session_name, output_style, added_dirs, git_worktree, effort, cc_version, etc.). Raised the full-layout threshold from 120 to 230 cols (and the compact threshold from 80 to 100). Terminals 120-229 cols now use the compact layout, which drops the heaviest Line 2 sections. 230 buffers above the measured worst-case 225. Most terminals will land in compact layout — the safe default. Closes #70.
- Added 4 end-to-end regression tests that render with a worst-case heavy payload (realistic workspace, long branch/session name) at 80/100/120 cols and at the full-layout threshold; they assert every line's visible width fits — catches future feature additions that grow Line 2 past the threshold.
- Default fallback for `shutil.get_terminal_size()` updated from 120 to 100 (compact layout) for non-interactive contexts. Safer default than the old "assume full layout."

### Notes
- Users on terminals between 120 and 229 cols will see fewer Line 2 sections than before. To get the full layout, widen your terminal to 230+ cols.
- Users who want specific sections to always show regardless of width can use the existing `disabled_sections` config in `~/.claude/claude-status-budget.json` to hide other sections instead.

## [0.5.2] - 2026-04-12

### Fixed
- **Line 2 disappearing — real root cause** — OSC 8 clickable hyperlink escape sequences (added in v0.5.0, #63) add ~180 bytes per link but are invisible to the user. Claude Code's Ink TUI `<Text wrap="truncate">` doesn't recognize OSC 8 sequences — it counts those escape bytes toward line width, miscalculates Line 2 as ~200+ chars wide, and silently drops it. This is independent of Line 1 content. Closes #68.
- OSC 8 clickable links are now **disabled by default**. Opt in via `"clickable_links": true` in `~/.claude/claude-status-budget.json` for users who run claude-status in a supporting terminal (iTerm2, Kitty, WezTerm) outside of Claude Code.

### Notes
- Anthropic closed the upstream fix request (anthropics/claude-code#28750) as NOT_PLANNED after 30 days of inactivity. This patch is our workaround.

## [0.5.1] - 2026-04-12

### Fixed
- **Line 2 still disappearing** — moved `burn` from Line 1 to Line 2, reducing Line 1 visible width to ~55 chars max. With high cost values ($1179+), Line 1 was reaching 121 visible chars, triggering the Ink truncation at 120 cols. Closes #66.

## [0.5.0] - 2026-04-11

### Added
- **Token speed display** (`speed:1.2K/s`) — real-time token throughput computed from tokens / API duration. Closes #57.
- **Progress bar style presets** — 4 named styles: default, dots, blocks, thin. Configurable via `bar_style` key in themes. Closes #59.
- **Git merge/rebase/conflict indicators** — detects repo state via .git file checks and lightweight git commands. Red for conflicts, yellow for merge/rebase. Closes #60.
- **Time since last commit** (`last:5m`) — shows how long ago the last commit was made. Closes #61.
- **NO_COLOR / FORCE_COLOR support** — respects the NO_COLOR standard (https://no-color.org/) and FORCE_COLOR override. Closes #62.
- **Clickable OSC 8 links** — git branch section is now clickable in supported terminals (iTerm2, Kitty, WezTerm). Opens repo URL in browser. Closes #63.
- **Per-section enable/disable** — configure `disabled_sections` in budget JSON to hide specific sections without a custom theme. Closes #64.
- `fmt_speed()` formatter, `BAR_STYLES` dict, `get_git_state()`, `get_last_commit_age_ms()`, `get_remote_url()`, `get_disabled_sections()`

### Changed
- All full-detail themes updated with `speed`, `git_state`, `commit_age` sections and color keys
- All new sections on Line 2 only (preserves Line 1 truncation workaround)
- Compact layout drops all new sections at <120 cols

## [0.4.3] - 2026-04-11

### Fixed
- **!CTX warning showing at low context usage on 1M windows** — the `exceeds_200k_tokens` flag is a fixed 200K threshold that fires at ~20% usage on 1M context windows. Removed this legacy fallback; `!CTX` now only triggers at 85%+ of actual context window usage via the percentage-based check. Closes #55.

## [0.4.2] - 2026-04-10

### Fixed
- **Line 2 disappearing on some terminals** — rebalanced default layout by moving `rate_limits` and `context_size` from Line 1 to Line 2, keeping Line 1 under ~90 characters. This works around a Claude Code rendering limitation (anthropics/claude-code#28750) where long Line 1 silently drops all subsequent lines. Closes #52.

### Changed
- Default, powerline, nord, tokyo-night, gruvbox, rose-pine themes all rebalanced
- Line 2 now starts with rate limits and context size for immediate visibility
- README FAQ documents the Line 2 visibility limitation and workarounds

## [0.4.1] - 2026-04-10

### Added
- **ARCHITECTURE.md** — documents module structure, data flow, design principles, caching strategy, and testing approach for contributors and tooling. Closes #48.
- **llms.txt** — structured project summary for AI agent discoverability, following the emerging convention for developer tools. Closes #50.
- **Enhanced `--doctor` diagnostics** — now checks PATH, validates config files (budget.json, theme.json), verifies Python compatibility, checks directory permissions, shows terminal layout mode, and reports `refreshInterval` setting. Closes #49.

## [0.4.0] - 2026-04-10

### Added
- **`--uninstall` command** — cleanly removes statusLine from settings.json and restores previous config from backup if available. Closes #43.
- **`focus` theme** — single-line layout showing only essentials (bar, cost, rate limits, branch, effort, clock) with a narrow 12-char bar for minimal vertical footprint. Closes #44.
- **Git worktree indicator** (`gwt`) — displays when inside a native git worktree (from `workspace.git_worktree`, Claude Code v2.1.97+). Closes #41.
- **`refreshInterval` documentation** — README now documents periodic status line updates via the `refreshInterval` setting (Claude Code v2.1.97+). Closes #42.

### Changed
- **Setup wizard redesigned** — shows compact 1-line descriptions per theme instead of full 2-line renders. Previews only the selected theme after choice. Mentions `refreshInterval` and `--uninstall` in summary. Closes #45.
- **Comprehensive README refresh** — new 30-Second Setup section, updated feature tables (27+ data points), complete CLI reference with `--uninstall`, `refreshInterval` in all config examples, expanded FAQ, improved Uninstall section. Closes #46.
- 8 built-in themes (was 7) — all updated with `git_worktree` section and color key
- Bar width now configurable per theme via `bar_width` key

## [0.3.2] - 2026-04-08

### Fixed
- **Rate limit reset countdown was showing wrong time** — `resets_at` is Unix epoch seconds per Claude Code docs, but was being treated as milliseconds. Now correctly converts seconds to milliseconds in `_normalize()`. Closes #39.
- Demo data updated to use seconds for `resets_at` (matching real Claude Code behavior)

## [0.3.1] - 2026-04-06

### Added
- **Output style indicator** — displays active output style (e.g., `style:explanatory`) when configured. Hidden when not set. Closes #35.
- **Added directories count** — shows `dirs:+N` when extra workspace directories are added via `/add-dir`. Closes #36.
- **Thinking effort level** — displays `effort:high` or `effort:low` when set to non-default. Reads from `~/.claude/settings.json` with 30s cache. Hidden at default (medium). Closes #37.

### Changed
- All themes updated with `output_style`, `added_dirs`, and `effort` sections
- Minimal theme includes `effort` (high-impact setting worth showing even in compact view)
- Responsive layout drops all three new sections in compact mode (<120 cols)

## [0.3.0] - 2026-04-05

### Added
- **Rate limit display** — shows 5-hour and 7-day API usage percentages with color-coded thresholds (green/yellow/red at 60%/85%) and reset countdown timer. Only appears for Claude.ai Pro/Max subscribers. Data comes from Claude Code's stdin JSON — no network calls. Closes #31.
- **Session name display** — shows custom session name set via `claude --name` or `/rename` command. Uses ✦ prefix for visual distinction. Closes #32.
- **Claude Code version** — shows `CC:X.Y.Z` alongside the tool version. Closes #33.
- `fmt_countdown()` formatter for human-readable reset countdown timers

### Changed
- All themes updated with `rate_limits`, `session_name`, and `cc_version` sections
- Responsive layout drops `session_name` and `cc_version` in compact mode
- Issue #13 closed — superseded by #31 (rate limits now available in stdin JSON)

## [0.2.2] - 2026-04-03

### Fixed
- **Critical**: `_normalize()` no longer drops zero values — `0` for cost, tokens, duration, etc. is now correctly preserved instead of being treated as `None`
- **Critical**: `--theme` help text now clarifies it's per-render only; directs users to `--install --theme` or `--setup` for persistence
- Burn rate calculation now includes `cache_create` tokens — previously understated consumption
- Bar color with compaction threshold uses raw context percentage — no more misleading red bar at 55% actual usage
- Session count cache key includes date — prevents stale counts across midnight
- Tool count cache TTL reduced from 30s to 10s — more responsive during active sessions
- Git cache uses 60s TTL for "not available" state — avoids repeated subprocess timeouts when git is missing
- Corrupt `settings.json` warning now mentions the `.bak` backup file
- Narrow layout (<80 cols) drops `model` section to prevent line wrapping
- Bar color threshold uses float precision — `85.5%` now correctly shows red, not yellow
- Periodic cache cleanup removes files older than 2 days to prevent accumulation

## [0.2.1] - 2026-04-03

### Added
- Version display (`v0.2.1`) and current time clock (`HH:MM`) in status line
- Enhanced git status: stash count (`stash:N`) and ahead/behind remote sync (`sync:+2/-1`)
- Context bar scaling relative to compaction threshold via `compaction_threshold_pct` config
- Responsive layout: automatically adapts sections based on terminal width (120+/80-119/<80 cols)

### Changed
- All full-detail themes now include `git_extras`, `version`, and `clock` sections
- Issue #13 (API usage limits) deferred — conflicts with zero-network-calls design

## [0.2.0] - 2026-04-03

### Added
- 4 new built-in themes: `nord`, `tokyo-night`, `gruvbox`, `rose-pine` (7 total)
- Budget monitoring with color-coded warnings via `~/.claude/claude-status-budget.json`
- Tool call count display (`tools:N`) — counts tool_use entries in current session JSONL
- Today's session count display (`sessions:N`) — reads `~/.claude/sessions/` metadata
- Interactive `--setup` wizard for guided theme selection and budget configuration
- New `sessions.py` module for reading `~/.claude/` data files with file-based caching

### Changed
- All full-detail themes now include `budget`, `tools`, and `sessions` sections
- `--demo` now previews all 7 themes
- Theme choices expanded in `--theme` and `--install` CLI arguments

## [0.1.6] - 2026-03-19

### Added
- API latency metric (`api:` section) showing time spent in API calls via `total_api_duration_ms`
- Custom theme support via `~/.claude/claude-status-theme.json` (`--theme custom`)
- `latency` color key in all built-in themes

### Changed
- Project name now uses `workspace.project_dir` (explicit project root) instead of basename of `current_dir`, preventing wrong names in nested subdirectories

## [0.1.5] - 2026-03-19

### Added
- Active model name display in status line (e.g., Opus, Sonnet, Haiku)
- `settings.json.bak` backup before `--install` modifies settings

### Fixed
- Context warning (`!CTX`) now uses percentage-based threshold (85%+) instead of hardcoded 200K boolean; works correctly with 1M token context windows
- Git cache now uses per-directory files to prevent wrong branch names in concurrent sessions

## [0.1.4] - 2026-03-14

### Added
- Project name in branch indicator (e.g., `myapp/main` instead of just `main`)
- Secret scanning in CI workflow and pre-commit hook
- Tests for project name feature

## [0.1.3] - 2026-03-14

### Fixed
- statusLine config must be an object with `type` and `command`, not a plain string

## [0.1.2] - 2026-03-14

### Changed
- README rewrite for clarity and visual appeal on PyPI

## [0.1.1] - 2026-03-14

### Changed
- Renamed PyPI package to `claude-status`
- Updated README for PyPI listing

## [0.1.0] - 2026-03-14

### Added
- Initial release
- Context bar with adaptive green/yellow/red coloring
- Token counts (input/output) with human-readable formatting
- Cache efficiency percentage
- Cost tracking in USD
- Session duration display
- Lines changed with git-diff style colors
- Git branch detection with color coding
- Context size indicator (200K/1M)
- Burn rate (tokens/min) — unique feature
- !CTX warning when exceeding 200K tokens
- Vim mode indicator (NORMAL/INSERT)
- Agent name display
- Worktree branch indicator
- Three themes: default, minimal, powerline
- `--install` auto-configuration for Claude Code
- `--demo` preview mode
- `--doctor` diagnostics
- Cross-platform support (Windows, macOS, Linux)
- Zero external dependencies
