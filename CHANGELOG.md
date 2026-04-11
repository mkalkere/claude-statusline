# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
