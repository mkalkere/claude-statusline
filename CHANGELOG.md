# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.2] - 2026-05-29

### Added
- **`ultra` effort level** — Claude Code emits `effort.level: "ultra"` on stdin, the stored value for `/effort ultracode` introduced alongside Opus 4.8 (2026-05-28). Valid `effort.level` values are now `low, medium, high, xhigh, max, ultra`. Previously claude-status hardcoded the valid set without `ultra`, so a real `effort.level: "ultra"` was silently rejected and the `effort:` indicator disappeared for ultracode users — the same class of bug fixed for `xhigh`/`max` in v0.5.6. Now `ultra` is accepted in both the stdin path and the settings.json fallback path, renders as the new top tier (color falls through `effort_ultra → effort_max → effort_xhigh → effort_high → BRIGHT_MAGENTA` via `_first()`), and all 8 built-in themes carry the `effort_ultra` color key (mirroring `effort_max`). The stored value `ultra` is rendered verbatim, not the `ultracode` display label — consistent with how every other tier renders its stored `effort.level` value.

### Changed
- Demo data (`--demo`), README, and a test fixture now reference **Opus 4.8 (1M context)** instead of Opus 4.7, reflecting Anthropic's current top model (released 2026-05-28).

### Notes
- **Backward compatible** — users on Claude Code releases before Opus 4.8 / ultracode see no change. The `ultracode` display label is still correctly rejected as invalid (only the stored value `ultra` is accepted), so validation is not weakened.
- **Verified non-issues for Opus 4.8**: model `display_name` renders verbatim (no hardcoded model IDs), context window unchanged (1M, same as Opus 4.7), pricing is supplied by Claude Code (`cost.total_cost_usd`; no hardcoded rates), and no new statusline stdin fields shipped in the Claude Code releases bundling Opus 4.8.
- New tests live in `tests/test_ultra_effort.py` (17 tests): stdin path, settings.json path, case-insensitivity, stdin precedence over settings.json, all-themes render, top-tier color, custom-theme fallthrough (missing key and explicit None), structural parity (every theme has `effort_ultra` mirroring `effort_max`), and `ultracode`-label / non-string / bogus-level rejection.
- All 472 tests pass (was 455, +17 new). Pure stdlib, no dependency changes.

## [0.6.1] - 2026-05-24

### Added
- **`CLAUDE_STATUSLINE_WIDTH` env var override** ([#89](https://github.com/mkalkere/claude-statusline/issues/89)) — explicit user override for terminal width detection. Highest priority in the chain: set to an integer in `[20, 4000]` to force a specific layout width regardless of auto-detection. Useful for headless CI, nested multiplexers where every probe lies, or cosmetic preference. Out-of-range / non-numeric values fall through silently to the existing 8-step chain (backward compatible). `--doctor` reports the override state first in the Width detection chain block so users debugging width can see whether their env var is the active source.
- **`pr` section** ([#87](https://github.com/mkalkere/claude-statusline/issues/87)) — renders the current GitHub PR number (`PR#86`) when newer Claude Code releases supply `github.pr_number` in the stdin JSON. When `github.pr_url` is also present, the section is wrapped in an OSC 8 hyperlink to the PR page (terminals that support OSC 8 make it clickable; others render the text unchanged). Hidden when no PR context is detected. Opt-in via custom theme. Normalized fields also include `github_repo` and `github_pr_url` for callers that want richer rendering. PR URLs are sanitized against terminal-escape-injection (any URL containing a control byte is rendered as plain text rather than wrapped in OSC 8) — defense against an attacker-controlled stdin payload corrupting the terminal display.
- **`cost_breakdown` section** ([#87](https://github.com/mkalkere/claude-statusline/issues/87)) — renders the largest non-base cost category (`mcp:$0.80`, `subagents:$0.25`, etc) when newer Claude Code releases supply `cost.by_category` in the stdin JSON. When no single category exceeds $0.01 but the sum across categories does, renders `other:$N` instead — prevents a "ghost cost" failure where many small categories sum to real money but each individually hides. Filters out non-numeric, zero, and negative values. Section hides entirely when no category data is present or sum is below threshold. Opt-in via custom theme.

### Fixed
- **`agent` section now activates reliably** ([#88](https://github.com/mkalkere/claude-statusline/issues/88)) — the previous `data.get("agent") or {}` normalization crashed silently with AttributeError when upstream sent `agent` as a non-dict (string, list, int). The outer try/except masked it as "section just didn't render," leaving users wondering why `[Explore]` never appeared. Now uses the project-standard isinstance guard, accepts both nested (`agent.name`) and flat (`agent_name`) schemas, validates the result is a non-empty string. The `worktree` section was rewritten with the same guard since it had the identical bug shape.
- **`cost` normalization now isinstance-guarded** — same defensive pattern as the above. An upstream sending `cost: 1.50` (bare number) instead of `cost: {"total_cost_usd": 1.50}` (dict) would have crashed the new `cost.by_category` extraction; now it falls through cleanly with an empty breakdown.
- **`vim` normalization now isinstance-guarded** — completing the bug-pattern fix across all `_normalize` sections that had the same exposure. An upstream sending `vim: "NORMAL"` (string) instead of `vim: {"mode": "NORMAL"}` (dict) would have crashed with AttributeError on `.get()`. Flagged by the Gemini code-review bot on PR #90 as the same shape we were fixing for `agent`/`worktree`/`cost`.
- **Color extraction in the new `pr` and `cost_breakdown` sections** now uses the `_first()` helper rather than `.get()` chained defaults, so a custom theme that explicitly sets a color key to `null` falls through to the default rather than passing `None` to `colorize()` (which would render the string `"None"` instead of crashing). Adopts the existing project pattern from the `effort` section.

### Notes
- **Backward compatible** — every existing theme/section keeps working unchanged. The three new sections (`pr`, `cost_breakdown`, env override behavior) are opt-in. Users on Claude Code releases before v2.1.148 / v2.1.150 see no change; users on newer releases get the new fields surfaced when they opt in via custom theme.
- **2.1.141 upstream Line-2 fix investigated** — Claude Code 2.1.141 shipped a fix for the per-line statusline truncation behavior ([anthropics/claude-code#58028](https://github.com/anthropics/claude-code/issues/58028) closed COMPLETED 2026-05-12). Investigation concluded the fix is PARTIAL: per-line truncation is fixed, but the underlying terminal-width detection problem ([#22115](https://github.com/anthropics/claude-code/issues/22115), still open as of this release) is unchanged. **Layout thresholds remain at `_FULL_LAYOUT_MIN_COLS = 150` and `_COMPACT_LAYOUT_MIN_COLS = 100`** — relaxing them would push Line 2 over the cliff on the still-common misdetection path. A future release may gate threshold relaxation on `version >= 2.1.141 AND high-confidence width detection`. Documented in `docs/RELEASE.md` failure-mode catalog.
- All 455 tests pass (was 409, +46 new). Pure stdlib, no dependency changes.
- Closes [#87](https://github.com/mkalkere/claude-statusline/issues/87), [#88](https://github.com/mkalkere/claude-statusline/issues/88), [#89](https://github.com/mkalkere/claude-statusline/issues/89).

## [0.6.0] - 2026-05-16

### Fixed
- **Width detection for Claude Code 2.1.139+** ([#83](https://github.com/mkalkere/claude-statusline/issues/83)) — 2.1.139 (2026-05-11) shipped "hooks now run without terminal access," which removed the last TTY-based escape hatch the earlier fallback chain relied on. The headline failure: on Linux/macOS, `tput cols` no longer fails when the subprocess has no TTY — it confidently returns its terminfo default (80 for `xterm`/`xterm-256color`/`vt100`/`ansi`). That value passed our `[20, 4000]` plausibility range, so we rendered an 80-col layout into the user's real (often 120–220 col) terminal. Independently confirmed by multiple statusline authors in [anthropics/claude-code#22115](https://github.com/anthropics/claude-code/issues/22115) on 2026-05-12. Three defenses added:
  - **`tput cols == 80` rejected as a likely terminfo stub** when every prior TTY probe failed. A user with a genuine 80-col terminal would have been caught earlier by `shutil.get_terminal_size` or `os.get_terminal_size(fd)`; reaching the stty/tput step with no earlier TTY signal is the 2.1.139 fingerprint. The rejection list is a single-element frozenset (`{80}`) so future stub values can be added cheaply.
  - **`COLUMNS=0` rejected and reported distinctly from unset.** Observed in no-TTY hook subprocesses on 2.1.139+: the env var is set to "0" rather than left absent. Treating that as a real value would have returned 0 from step 2 (failing our `>= 20` guard but only after silently shaping subsequent diagnostics). The report distinction matters for `--doctor`.
  - **Process-tree walk added as a new fallback step.** Linux walks `/proc/<ancestor_pid>/fd/2` up the ancestor chain (starting from PPID), looking for a process that still owns the controlling terminal (the user's shell or Claude Code's main TUI process). macOS lacks the equivalent `/proc/<pid>/fd` exposure so the walk degrades to checking PPID then bailing — that's acceptable: the user gets the safe fallback width, same as before this step existed. Capped at 16 ancestors and protected by a visited set to defuse pathological process trees. The fd is opened with `O_NOCTTY | O_NONBLOCK` so an ancestor's TTY cannot become this process's controlling terminal.

### Added
- **`activity` section** ([#84](https://github.com/mkalkere/claude-statusline/issues/84)) — live tool-call counter for the *current assistant turn*, distinct from the existing `tools:` section (which is session-cumulative). Renders as `act:3` and is hidden when zero so idle sessions show nothing. Reads the tail of `transcript_path` from stdin (64 KiB initial cap, 1 MiB expanded retry if the first read missed the user message), counts `tool_use` content blocks on assistant messages since the most recent `role: "user"` line, caches the non-zero result for 5 seconds (zero is recomputed each call so transient parse failures recover immediately). Tolerates: missing file, empty file, malformed JSON lines (skipped individually), partial first line when reading from a tail offset (discarded — with a guard for the case where the chunk starts at exactly a `\n` byte and no truncation occurred), no user message in either window (returns 0 rather than misleadingly counting a previous turn's activity), file rotation/truncation mid-session, both outer-envelope and message-wrapped `role` schemas, non-string `transcript_path` from upstream schema changes. **Path validation:** `transcript_path` comes from external JSON, so `get_session_activity_count` rejects any path whose `os.path.realpath` resolves outside `~/.claude/` before any `open()` is attempted (defense in depth — Claude Code only ever writes transcripts under that tree). Opt-in via custom theme — not added to the default layout to avoid silently changing every user's statusline.
- **`--doctor` width-detection report** — each step of the detection chain is now listed with the value it returned and why it won or was rejected (e.g., `tput cols: 80 (likely terminfo stub — rejected; no earlier TTY signal)`). When a user reports "my layout looks wrong on a wide terminal," they can paste this section to show exactly which signal lied. Backed by a new `_detect_terminal_width_report(data)` helper that returns `(int, list[(label, status)])`; the existing `_detect_terminal_width(data)` thin wrapper preserves the int return shape every other caller relies on.
- **`--doctor` transcript probe** — when the `activity` section silently disappears, users had no way to distinguish "no tool calls in current turn" from "transcript parse failed." The new `Transcript:` block in `--doctor` finds the most-recent JSONL under `~/.claude/projects/`, reports its size and mtime, runs the activity counter against it, and prints a `Parse:` line that disambiguates the `count == 0` causes (idle / file missing / file empty / file too small to contain a user / single turn larger than 1 MiB tail window). Backed by `_count_activity_with_status(path)` which returns `(int, str)`; `get_session_activity_count` is a thin wrapper that discards the status to keep its int-only API. When `~/.claude/` is a symlink to a non-existent target (broken symlink to an unmounted volume etc), `--doctor` prints an explicit WARNING naming the bad symlink — without this hint users see "file missing" for every transcript with no clue that the dotdir itself is the root cause.
- **Negative cache for the "gave up — turn larger than 1 MiB" case.** Without it, an active assistant turn that exceeds the 1 MiB expanded tail would trigger a 1 MiB read on every render until the user sent the next prompt. A separate cache key with a 30s TTL short-circuits subsequent renders. Worst-case staleness after the user sends a new prompt is one render cycle.
- New tests: 9 for the 2.1.139 width regression (`TestClaudeCode2139WidthRegression` — covers `COLUMNS=0` distinct from unset, `tput cols=80` stub rejection with a non-stub control case, process-tree walk shape on Windows and POSIX, report-list invariants, thin-wrapper signature preservation), and the rest in `TestActivityCounter` for `_count_activity_from_transcript` and `get_session_activity_count` (happy path / zero / no user in tail / missing path / None path / non-string path / empty file / malformed JSON lines / tail-read cap verification with a > 64 KiB file / partial first line discard / TTL cache behavior / end-to-end render with and without `transcript_path`).

### Changed
- **`_detect_terminal_width` refactored** into a thin wrapper around `_detect_terminal_width_report`. Public signature unchanged (`(data=None) -> int`) so every existing caller keeps working. The chain now tracks whether any TTY probe succeeded earlier in the chain — that flag drives the stub-rejection heuristic in step 7. Step 5 (process-tree walk) is new; original steps 5/6 (`stty`/`tput`) renumbered to 6/7 in the docstring and the `--doctor` output.
- **pyproject.toml keywords expanded** to cover competitor-comparison search traffic (`claude-code-statusline`, `agentic`, `ai-agent`, `subagent`, `cost-tracking`, `responsive-layout`, `terminal-width`, `prompt-cache`, `prompt-engineering`, `git-status`, `observability`, `devtool`, `statusbar`, `tokens`, `context-tracking`).

### Notes
- **Backward compatible** — every existing theme/section keeps working unchanged. The new `activity` section is opt-in via custom theme. The width-detection fix is transparent: users on Claude Code < 2.1.139 see no behavior change; users on 2.1.139+ see correct layouts instead of squeezed 80-col ones.
- **Clarified `cache:` docstring** — the existing `cache:N%` indicator already computes prompt cache hit ratio (`cache_read / (cache_read + cache_creation + input_tokens)`) because that's what its `total_input` argument is. The docstring previously said "cache efficiency as percentage," which was vague enough to invite a duplicate. The output value is unchanged for every user; only the inline documentation was made precise.
- All 409 tests pass (was 370, +39 new). Pure stdlib, no dependency changes.
- **Why we ship instead of waiting for upstream:** [anthropics/claude-code#28750](https://github.com/anthropics/claude-code/issues/28750) (Line 2 truncation) was closed without engagement after 30 days of inactivity; [#22115](https://github.com/anthropics/claude-code/issues/22115) (pass terminal columns via stdin/env) is still open with no implementation; [#52326](https://github.com/anthropics/claude-code/issues/52326) (rate_limits epoch bug, guarded in v0.5.7) is still open. The downstream-fix posture has become permanent for this project — every upstream bug ticket that touches the statusline render path is closing without engagement, so claude-status needs to be the layer that absorbs the impact.

## [0.5.8] - 2026-05-10

### Changed
- **Effort level now read from JSON stdin first** (Claude Code v2.1.119+ exposes `effort.level` in the statusline payload). When stdin contains a valid `effort.level`, that's the authoritative source — the effort indicator updates within one render cycle of `/effort xhigh` instead of waiting up to 30s for the `~/.claude/settings.json` cache to expire. The settings.json read remains as a fallback for older Claude Code versions, demo mode, and custom statuslines that don't supply the field.
- Stdin `effort.level: "medium"` is now treated as an explicit "hide section" signal (not a "no preference, fall through" signal). _normalize sets `out["effort_level"]` to an empty-string sentinel that fails the renderer's truthy check → section hides immediately. Previously, stdin medium fell through to the settings.json cache and could show a stale non-medium value for up to 30s after running `/effort medium`.
- When `_normalize` extracts a valid effort.level from stdin, it also mirrors the value to the on-disk effort_level cache. This keeps the two sources consistent across mid-session client switches: a render that later falls back to the settings.json-cache path (because stdin omits the field) reads the most recent authoritative value instead of a stale entry from before the user's last `/effort` change. The mirror-write is deduplicated via a read+compare guard — if the cache already has the same value, the write is skipped (read+compare is much cheaper than the atomic write+rename of the cache file, important for active sessions with low refreshInterval).

### Added
- 18 new tests in `TestEffortLevelFromStdin` covering: valid level extraction (low / high / xhigh / max all pass through; medium normalized to "" sentinel), case-insensitivity (`XHIGH` → `xhigh`), unknown-level rejection (`ultrathink` → fall through to settings.json), non-string `effort.level` (int / list / None / bool / nested dict — all rejected cleanly), non-dict `effort` field rejection, absent-effort fallback, end-to-end render preferring stdin over settings.json (verified via "loud stub" that records calls — settings.json read MUST NOT happen when stdin has a valid value), end-to-end render falling back to settings.json when stdin lacks the field, invalid-stdin fall-through to settings.json, stdin-medium hides section AND skips the settings.json fallback (verified via loud stub: `get_effort_level` MUST NOT be called even when stdin says medium), both-medium case, each valid level rendering through the stdin path independently, cache mirror-write on valid stdin, cache NOT-written on invalid stdin, cache write skipped when value unchanged, cache write happens when value changed.

### Notes
- **Backward compatible** — users on older Claude Code (no `effort` field in stdin) see no behavior change. Users on v2.1.119+ get faster effort updates with no config required.
- All 370 tests pass (was 352, +18 new). Pure stdlib, no dependency changes.
- Internal review: 4 PR-review agents consulted before push. Silent-failure agent flagged a HIGH-severity cache-staleness risk on mid-session client switches (stdin path never refreshed the on-disk cache); fixed via the cache-mirror behavior. Comment-analyzer flagged that the renderer's `or` truthiness could be misread; switched to explicit `is not None`. Gemini code review on the PR flagged that stdin medium falling through to settings.json was its own staleness footgun (the user just ran `/effort medium` but sees the indicator linger for 30s on a stale non-medium cache value); fixed by treating stdin medium as an explicit hide via the empty-string sentinel. Gemini also flagged that the cache mirror-write was happening on every render; added a read+compare deduplication guard.
- Closes #81.

## [0.5.7] - 2026-05-09

### Added
- **Terminal width detection fallback chain** — Claude Code spawns the statusLine command as a subprocess with stdin piped (no TTY, no `COLUMNS` env var), so naive `shutil.get_terminal_size()` always returns the fallback `(100, 24)`. Result: a user with a 165-col terminal would only see ~83 chars on Line 2, with sections like `rate_limits`, `context_size`, `clock`, `effort`, `version`, `last:`, `style:`, `dirs:` silently hidden. New `_detect_terminal_width()` tries 7 signals in order until one returns a plausible value: stdin `terminal.columns` (forward-compat for whenever Anthropic ships it) → `COLUMNS` env → `shutil.get_terminal_size` → `os.get_terminal_size(fd)` for stderr/stdout/stdin → `stty size < /dev/tty` → `tput cols 2>/dev/tty` → existing `_COMPACT_LAYOUT_MIN_COLS` fallback. Plausible-range guard (20–4000 cols, wide enough for ultrawide / 8K / multi-monitor tmux setups) rejects 0, negative, or absurd values from any source. Each step is wrapped in try/except so missing tools / closed `/dev/tty` fall through silently. Tracked upstream at [anthropics/claude-code#22115](https://github.com/anthropics/claude-code/issues/22115).
- 12 new tests for the width detection — 11 unit tests (`TestDetectTerminalWidth`: each fallback step, boundary values 20/4000, implausible-input rejection, garbage env vars, non-dict stdin shapes, 2000-col ultrawide acceptance) plus 1 end-to-end render test (`TestRenderUsesDetectedWidth`) that proves a 165-col terminal now shows recovered sections (`(1000K)`, `effort:xhigh`).
- `--doctor` now reports both the naive `shutil` width and the detected fallback width side-by-side, so users can see whether our recovery worked on their box.

### Fixed
- **Defensive guard against upstream rate_limits bug** ([anthropics/claude-code#52326](https://github.com/anthropics/claude-code/issues/52326), still open) — on a fresh 5h or 7d window with no usage data yet, Claude Code returns the `resets_at` epoch timestamp (~1.7e9) in `used_percentage` instead of 0/null. Previously our `clamp(0,100)` silently turned this into a false `5h:100% (red)` alarm on every fresh session for Pro/Max subscribers. Now values >= 1e6 (the epoch-timestamp pattern, 7+ orders of magnitude above any plausible percentage) are treated as "no data yet" and the section is hidden. Values 101-999999 still flow through to the renderer's clamp(0,100) — these are NOT the bug pattern and could be a future Anthropic "overage" indicator above 100% that we shouldn't pre-emptively hide.
- 6 new tests in `TestRateLimitsEpochTimestampGuard` covering 5h epoch hidden, 7d epoch hidden, boundary at 100 (legitimate maxed value passes), boundary at 1e6 (just hits the guard), end-to-end render of the bugged value, and that legitimate values pass through.

### Notes
- Together these two fixes are the most user-visible improvement since v0.5.4 — every claude-status user with a wide terminal will see significantly more sections after upgrading, with no config required.
- Closes #79.

## [0.5.6] - 2026-04-24

### Added
- **`xhigh` and `max` effort level support** — Claude Code v2.1.111 (released 2026-04-16) introduced the `xhigh` effort level for Opus 4.7, sitting between `high` and `max`. `max` is the top-tier value visible in Anthropic's Auto Mode references and `/effort max` UI. Previously claude-status rejected both as unknown levels and silently hid the `effort:` indicator for users running Opus 4.7 with xhigh or max thinking. Now `get_effort_level()` accepts both, the renderer wires dedicated `effort_xhigh` and `effort_max` color branches, and all 8 built-in themes ship the new color keys (default to `BRIGHT_MAGENTA` to match `effort_high`). Closes #77.
- Custom themes pinned at older versions still work — the renderer uses `_first()` to walk a fallback chain (`effort_max` → `effort_xhigh` → `effort_high` → hardcoded magenta), and explicit `None` values in custom themes (common when YAML/JSON tools serialize "no value" as `null`) no longer crash `colorize()`.
- 11 new tests covering: xhigh + max accepted by `get_effort_level()` (both disk-read and cache-hit paths), case-insensitivity, both rendered with the literal `effort:xhigh`/`effort:max` text, dedicated color keys actually used, fallback chain when keys are missing, explicit `None` in a theme key falls through safely, and all 8 built-in themes ship both new keys.

### Changed
- Demo data (`--demo`) now uses `Opus 4.7 (1M context)` instead of `Opus 4.6` to reflect Anthropic's current top model.

### Notes
- Other models (Sonnet, Haiku, older Opus releases) fall back to `high` per Anthropic's docs — no behavior change for users on those models. Users on Opus 4.7 with xhigh or max configured will simply start seeing the indicator after upgrading.
- Claude Code v2.1.119 (released 2026-04-23) shipped `effort.level` and `thinking.enabled` in the statusline JSON stdin payload. claude-status currently reads effort from `~/.claude/settings.json`; consuming the new JSON fields is tracked as a follow-up so we don't double-source.

## [0.5.5] - 2026-04-16

### Added
- **`--print-config` flag** — emits current install state in a deterministic key=value form for coding agents and shell scripts. Output contract: 8 keys (`installed`, `command`, `type`, `refreshInterval`, `theme`, `version`, `settings_path`, `settings_state`) in stable order, every line always present. Three exit codes: `0` installed, `1` not installed, `2` settings.json corrupt or unreadable (agents must NOT auto-install on `2` — would overwrite recoverable user config). Newlines in command/path values are sanitized so the line count stays fixed.
- Install detection covers the full set of working install patterns: direct binary (`claude-status`, `claude-status.exe`, full Windows paths with spaces), module form (`python -m claude_statusline`, `py -m claude_statusline`), runner forms (`uvx claude-status`, `pipx run claude-status`). Strict basename equality rejects substring lookalikes (`not-claude-status`, `my-claude-status-fork`).
- Theme parsing handles both argparse forms (`--theme nord` and `--theme=nord`).
- `refreshInterval` accepts numeric strings (common in hand-edited settings.json) via `_safe_num`. Booleans and negative values are explicitly rejected.
- **`AGENTS.md`** — one-page install guide for coding agents (Claude Code, Cursor, Aider, Continue, Cline, etc.) with the non-interactive one-liner, verification, update, uninstall, theme installs, budget configuration, and common recipes.
- **README "For Coding Agents" section** — copy-paste-ready install block visible above the fold for both human readers and crawlers.
- 37 new tests for `--print-config` covering: stable key order, missing/corrupt/unreadable settings, non-dict statusLine (string/list/None/array), Windows `.exe`, full paths with spaces, `python -m`/`uvx`/`pipx` forms (including versioned binaries `python3.11`, `python3.12.5`), lookalike rejection (both `not-claude-status` style and `pythonista`/`ipython` style), both `--theme` arg forms, last-`--theme`-wins precedence (matches argparse), refreshInterval coercion (numeric string, bool, negative, garbage), null command/type fields → empty string, newline injection sanitization, settings_state contract, and end-to-end subprocess exit code propagation.

### Changed
- **`llms.txt` refreshed** — corrected v0.5.4 details (test count, two-stage layout description, threshold constants 150/100), added new flags, added link to AGENTS.md.
- **PyPI keywords broadened** — added `claude-code-plugin`, `coding-agent`, `agent-tooling`, `ai-coding`, `llm-tooling`, `ai-developer-tools` so PyPI search surfaces the project for terms agents and users actually search for.
- **GitHub repo topics** — added `coding-agent` and `agent-tooling` to the repo (now at the 20-topic GitHub limit).

### Notes
- The discoverability changes target two audiences: (1) LLM crawlers / answer engines (Perplexity, Phind, ChatGPT/Claude search, Gemini) via `llms.txt` and prominent README placement; (2) coding agents acting on a user's behalf via `AGENTS.md` and `--print-config` for machine-readable state.
- No behavior changes to the rendered status line itself — this release is purely additive (new flag, new docs, new metadata).
- Closes #74.

## [0.5.4] - 2026-04-16

### Added
- **Width-aware adaptive layout** — render() now performs a precise post-render fit on each line: it measures actual visible width (stripping ANSI/OSC 8 escapes) and drops sections in priority order one at a time until the line fits the terminal. This recovers sections like `rate_limits`, `speed`, `version`, `clock`, `commit_age`, etc. on terminals between the compact band and full layout where the v0.5.3 compact bucket would have hidden them all unconditionally.
- New tests cover ANSI/OSC 8 stripping (including BEL-terminated OSC 8 used by Kitty/Screen), the priority-based drop algorithm, end-to-end width fit, and recovery (rate_limits visible at 180 cols, dropped at 120 cols).

### Changed
- Lowered the full-layout pre-filter threshold from 230 → 150 cols. Above 150, all sections are eligible and the precise stage trims as needed. Below 150, the coarse pre-filter still skips the heaviest sections (git subprocess calls, file scans for tools/sessions) so we don't pay rendering cost on terminals where they won't fit.
- Two-stage layout: coarse pre-filter (`_apply_responsive`) picks an eligible section list by terminal-width bucket, then precise fit (`_fit_to_width`) trims after rendering. The precise stage uses `_FIT_DROP_PRIORITY`, which extends `_COMPACT_DROP` with last-resort drops (vim, agent, lines, duration, burn, model, cache, budget) so the compact band (100-149 cols) can also reach a fitting result with heavy data.
- `--doctor` now reports the actual layout thresholds (driven by the constants) instead of hardcoded values that drifted in v0.5.3 → v0.5.4.

### Fixed
- OSC 8 hyperlink regex now matches both string-terminator forms (ST `\x1b\\` and BEL `\x07`) so width measurement stays accurate when text passes through emitters that use BEL.

### Notes
- Anthropic's underlying `wrap:"truncate"` bug (anthropics/claude-code#28750) remains unaddressed upstream — the issue was closed by stalebot after 30 days of inactivity following the reporter's root-cause trace. Our two-stage layout makes the workaround tighter: instead of dropping the entire compact-bucket of sections at a single width threshold, we measure and drop only what actually doesn't fit.
- Users who previously saw a sparse Line 2 between the compact and full thresholds will see additional sections automatically. No config change required.
- Closes #73.

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
