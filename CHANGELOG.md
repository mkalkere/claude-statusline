# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
