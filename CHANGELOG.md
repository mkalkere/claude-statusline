# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.15.0] - 2026-07-24

Layout-correctness release, from a user report showing Line 2 cut mid-token (`effort:xhi…`) while Line 1 sat ~70% empty.

### Fixed

- **Line 2 no longer overflows into Claude Code's truncation** ([#118](https://github.com/mkalkere/claude-statusline/issues/118)). The ellipsis in that report was not ours — at the time this project emitted `…` only in subagent rows — it was Claude Code's Ink renderer cutting a line we handed it that was too wide. The width we detect is the *terminal* width, but the status line renders inside a padded panel, so the usable row is narrower. We were fitting to the reported width exactly (line 2 measured 186 columns at a detected 190), leaving nothing for the panel's own chrome.

  Lines are now fitted to `detected_width − _FIT_SAFETY_MARGIN`. The margin is deliberately generous rather than minimal: the failure is asymmetric — too small costs a truncated section plus a visible ellipsis, too large costs a couple of columns nobody notices. It also buys headroom for `_visible_width`'s documented width-1 approximation for CJK/emoji. The margin **scales with confidence**: a width pinned via `CLAUDE_STATUSLINE_WIDTH` gets **no margin at all** (the user is asserting usable width, not reporting a terminal size — that is what makes the override a real edge-to-edge escape hatch); a width a real probe won gets the normal margin; a fallback *guess* gets a wider one, because Claude Code 2.1.139+ can run hooks without terminal access and guessing wide is the expensive direction to be wrong in (on Claude Code < 2.1.141 a Line 1 overflow drops Line 2 entirely).

  **The inconsistency behind the bug:** the subagent path has reserved a margin since v0.13.0 for exactly this reason; the main path never got the same treatment. Now it does.

- **Line 1 can actually fill** ([#119](https://github.com/mkalkere/claude-statusline/issues/119)). Line 1 rendered at a constant 57 visible columns at *every* terminal width (verified 150/170/190/200/220) — not a fit failure but a static composition problem: six themes assigned 6 sections to Line 1 and 25 to Line 2, and two of the six are conditional. Meanwhile Line 2 shed real data: at the reported width `version` was dropped by our own fit logic, while `cc_version` and `clock` survived it only to be cut by Claude Code's truncation (at 170 columns all three were ours).

  `burn`, `rate_limits`, and `context_size` move from Line 2 to Line 1 in the six full themes (`default`, `powerline`, `nord`, `tokyo-night`, `gruvbox`, `rose-pine`). Measured on the reported session at 190 columns: **Line 1 57 → 93, Line 2 186 → 153.** `minimal` and `focus` are deliberately sparse designs and are untouched (pinned by exact-composition tests).

  This also **makes the code match the README**, which has listed Burn Rate, Rate Limits, and Context Size under "Line 1 — Metrics at a Glance" all along. The docs were right; the themes were wrong.

- **Raw model IDs are shortened** ([#120](https://github.com/mkalkere/claude-statusline/issues/120)). Newer Claude Code builds send the raw id as `model.display_name` (observed: `claude-opus-5`), where older builds sent friendly names. Raw ids now render through the existing `_short_model()` — `claude-opus-5` → `Opus 5` — saving columns on a width-starved line. Guarded: `_short_model` dash-splits and title-cases, so it is applied **only** to `claude-`-prefixed values; friendly names like `Opus 4.8 (1M context)` render byte-identical to before (pinned).

- **Model names are never truncated mid-token on the main line.** `_short_model()` gained a `cap` parameter; subagent rows keep the per-row cap, the main line passes `cap=None` because `_fit_to_width` already drops the whole section cleanly when it doesn't fit. A bracketed variant marker (`claude-sonnet-4-5-20250929[1m]` → `Sonnet 4.5 [1m]`) now survives the date strip instead of being silently dropped — it tells you which context variant the session is on.
- **`--doctor` reports the effective fit width** (`Fit width: 186 (detected 190 - safety margin 4)`), so a section that vanished after this upgrade is diagnosable rather than mysterious.

### Notes

- **Visible change for every user of the six full themes**: three sections move from Line 2 up to Line 1. Nothing is removed and no configuration changes.
- **Custom themes inherit** their base theme's `lineN` lists for any line they don't define themselves, so a custom theme that overrides only colors — or only one line — sees the same move. A custom theme that overrides *only* `line2`, copied from the pre-v0.15.0 default, would have paired its stale `line2` with the rebalanced `line1` and rendered `burn`/`rate_limits`/`context_size` twice; `render()` now enforces a **render-at-most-once invariant** across rows (first line wins), which also protects hand-written themes that list a section on two lines by mistake.
- Theme screenshots in the README were regenerated for the new layout.
- Dynamic overflow promotion (spilling Line 2 sections up when Line 1 has room) is deliberately **not** in this release — it is real new layout logic and is filed as [#121](https://github.com/mkalkere/claude-statusline/issues/121) for a design pass.
- 746 tests pass (+18: a mutation-verified width-headroom sweep across a contiguous 100-300 column range (a seven-point sample was replaced after mutation testing showed it missed every boundary width and would have been vacuous), a regression pin reproducing the reported session shape, the three-section promotion, a no-section-on-two-lines invariant across every theme, exact-composition pins for `minimal`/`focus`, and the model shortener's raw-vs-friendly guard). Pure stdlib, zero dependencies, as always.

## [0.14.1] - 2026-07-16

### Added

- **Repo-link footer at the end of `--demo` output** ([#116](https://github.com/mkalkere/claude-statusline/issues/116)) — `--demo` is the discovery funnel (the README's first CTA is `uvx claude-status --demo`, reaching people who haven't installed yet), and a repo link at the end of a demo is expected showcase content. Static line: no network, no state, no marker files. Statusline renders, `--install`, and `--print-config` are untouched.
- **Design note for the record:** star-*detection* ("only ask if they haven't starred") was evaluated and rejected — it would require reading the user's GitHub identity (authenticated API or shelling into their `gh` CLI) and would be this package's first-ever network call, breaking the documented no-daemon/no-network/cannot-leak-data promise (AGENTS.md: "No daemon, no network, no background processes"). That promise outranks growth mechanics.

- **Model names are never truncated mid-token on the main line.** `_short_model()` gained a `cap` parameter; subagent rows keep the per-row cap, the main line passes `cap=None` because `_fit_to_width` already drops the whole section cleanly when it doesn't fit. A bracketed variant marker (`claude-sonnet-4-5-20250929[1m]` → `Sonnet 4.5 [1m]`) now survives the date strip instead of being silently dropped — it tells you which context variant the session is on.
- **`--doctor` reports the effective fit width** (`Fit width: 186 (detected 190 - safety margin 4)`), so a section that vanished after this upgrade is diagnosable rather than mysterious.

### Notes

- All remaining `timeout=10` subprocess tests aligned at 15s (same load-dependent flake class fixed for the 5s batch in v0.14.0 — one of the v0.13 e2e tests hit it under load during this release’s verification).
- 728 tests pass (+1: the demo-footer pin alongside the existing demo assertions). Pure stdlib, zero dependencies, as always.

## [0.14.0] - 2026-07-16

### Added

- **`context_tokens` section** ([#113](https://github.com/mkalkere/claude-statusline/issues/113)) — absolute context display, `ctx:412K/1M`. At 1M-token windows a percentage hides magnitude: 40% means ~400K tokens re-billed on every turn. Opt-in via custom theme, droppable under width pressure.

  - **Derived, not read**: the numerator is `used_percentage × context_window_size` rather than the raw token fields. `used_percentage` is upstream's authoritative fill signal and already drives the bar and `!CTX`, so deriving keeps the chip arithmetically consistent with the bar beside it — a 42% bar next to a chip implying 41.2% would read as a bug. The input/cache token components are ambiguous as a fill measure (their sum is not the documented fill).
  - Percentage clamped to [0, 100] (the bar's own bounds), so an out-of-spec upstream value can't render `ctx:2.5M/1M`. Hidden when either signal is missing or garbage; `0%` legitimately renders `ctx:0/1M` (zeros are values, not absences).

- **Star-ask epilogue in `--setup`** ([#114](https://github.com/mkalkere/claude-statusline/issues/114)) — one polite line after a successful wizard run pointing at the GitHub repo. Success path only (aborted setup prints nothing extra), `--setup` only (`--install` is the agents/CI path where no human reads output), no tracking, no repetition mechanism.

### Fixed

- **`used_percentage: NaN` blanked the entire statusline.** `json.loads` accepts bare `NaN`, and the context/token fields flowed raw through `_normalize` — NaN passed every `is not None` gate and detonated in `render_bar`'s `int()`. The whole context/token block (`used_percentage`, `input_tokens`, `output_tokens`, `cache_read`, `cache_create`) now gets the same treatment the money/time trio received in v0.11.0 — `_safe_num` coercion at the `_normalize` chokepoint plus the stderr breadcrumb for present-but-garbage values: garbage becomes `None` (section hides), numeric strings coerce and render, zeros survive as zeros. Found by this release's own hidden-when-garbage test matrix — the third time a new feature's test probes have caught a pre-existing stdin-reachable crash (v0.11: cost/duration; v0.13: closed-stdin NameError; now this).

- **Model names are never truncated mid-token on the main line.** `_short_model()` gained a `cap` parameter; subagent rows keep the per-row cap, the main line passes `cap=None` because `_fit_to_width` already drops the whole section cleanly when it doesn't fit. A bracketed variant marker (`claude-sonnet-4-5-20250929[1m]` → `Sonnet 4.5 [1m]`) now survives the date strip instead of being silently dropped — it tells you which context variant the session is on.
- **`--doctor` reports the effective fit width** (`Fit width: 186 (detected 190 - safety margin 4)`), so a section that vanished after this upgrade is diagnosable rather than mysterious.

### Notes

- Test-infra: four stale 5-second subprocess timeouts bumped to 15s — the suite now spawns more subprocess tests (the star-ask contract tests), and Windows process cold-start under load intermittently exceeded 5s, intermittently failing an unrelated pre-existing test (three of ten local runs under load). Load-dependent flakes violate the determinism rule regardless of which test they bite.
- **Derived chips refuse corrupted inputs**: `cache %`, `burn`, and `speed` sum token components with an absent-means-0 rule; coercion would have let a present-but-garbage component be silently zeroed, rendering a confidently-wrong ratio (a cache hit-rate inflating 60% → 90% with no visible cue — reproduced in review). A `token_fields_corrupt` flag now hides those three chips whenever any component was present-but-garbage; genuinely-absent fields keep the longstanding absent-means-0 behavior.
- **`context_tokens` rounds, not floors** — float representation error puts e.g. `1M × 4.1%` at 40999.999…, and a bare `int()` rendered `ctx:40K` where the exact value is 41K. Also: a custom theme setting `context_tokens: null` now degrades to the default color via `_first()` (house convention) instead of crashing the line, and a failed budget save during `--setup` no longer reports the unsaved budget in the completion summary.
- 727 tests pass (+23 net; 2 POSIX-only permission pins skip on Windows and run on the Linux/macOS CI legs: derivation/clamp/zero/hidden matrices for the new chip, droppable membership, the NaN-blanks-line regression with the full coercion matrix, and the star-ask's three contract points — exactly-once on success, absent on abort, absent from `--install`). Pure stdlib, zero dependencies, as always.

## [0.13.0] - 2026-07-09

### Added

- **Per-subagent status rows** ([#110](https://github.com/mkalkere/claude-statusline/issues/110), closes [#91](https://github.com/mkalkere/claude-statusline/issues/91)) — claude-status now serves Claude Code's `subagentStatusLine` hook: each running subagent task renders as `[Explore] [███░░░░░] 41% · 23s · Sonnet 5` (name, per-task context bar + percentage, elapsed time, model) in the agent panel. One binary, both hooks — add alongside your `statusLine` entry:

  ```json
  "subagentStatusLine": {"type": "command", "command": "claude-status --subagent"}
  ```

  - **`--subagent` is the documented interface**; a subagent payload arriving on the bare command is auto-detected as a fallback (with a stderr note suggesting the flag). With the flag, every error path prints nothing — a JSONL consumer never sees a stray statusline or the main hook's `?` fallback (a truncated payload that merely *looks* subagent-shaped also suppresses `?`).
  - **Emitted per the documented upstream contract**: JSONL `{"id", "content"}` per task; ids echo back as their original JSON type; a task that can't be rendered (malformed, finished, or nothing fits the width) is **omitted** — upstream's default row always beats a hidden or garbled one, and empty content (which hides a row) is never emitted.
  - **Status-aware**: terminal statuses (completed/failed/cancelled/…) hand the row back to Claude Code's default rendering — no forever-ticking elapsed timer on finished tasks. Unknown statuses fail open (render).
  - **Degrades per segment**: percentage needs `tokenCount` ≥ 0 AND `contextWindowSize` > 0 (displayed pct clamps at 100); elapsed accepts `startTime` as ISO-8601, epoch seconds, or epoch milliseconds (magnitude-banded — the format is undocumented upstream) and drops on clock skew or >7-day ages; the model chip shortens ids (`claude-sonnet-5-20250707` → `Sonnet 5`). On pre-2.1.205 Claude Code (no model/context fields) rows show `[name] 23s`.
  - **Width policy**: rows fit the panel's `columns` (with a small margin); drop order model → bar → elapsed, minimum `[name] 41%`, name truncation with ellipsis; percentage colors use the same 60/85 bands as the main context bar. Task names are control-character-stripped before embedding (terminal-escape injection guard).
  - **Zero side effects**: subagent rendering never touches `_normalize`, git, caches, or the daily-spend ledger — the hook fires once per refresh tick per panel. Pinned by a test.
  - **Install funnel**: `--setup` gains an opt-in question that writes the key (theme-propagated); `--install` prints the ready-to-paste snippet; `--uninstall` removes a claude-status-owned `subagentStatusLine`; `--print-config` gains a 9th `subagent=` line (appended — key=value parsers keep working; exact-8-line-count parsers need a one-line update); `--doctor` reports the hook's config state.
  - Design went through two adversarial reviews before implementation (which set the envelope-only payload discriminator — `tasks: []` is a valid subagent payload; malformed elements can never flip the mode — and the never-empty-content rule) plus the standard four-agent review after.

- **Model names are never truncated mid-token on the main line.** `_short_model()` gained a `cap` parameter; subagent rows keep the per-row cap, the main line passes `cap=None` because `_fit_to_width` already drops the whole section cleanly when it doesn't fit. A bracketed variant marker (`claude-sonnet-4-5-20250929[1m]` → `Sonnet 4.5 [1m]`) now survives the date strip instead of being silently dropped — it tells you which context variant the session is on.
- **`--doctor` reports the effective fit width** (`Fit width: 186 (detected 190 - safety margin 4)`), so a section that vanished after this upgrade is diagnosable rather than mysterious.

### Notes

- **#91 closes as completed-with-delta**: it asked for a subagent runtime timer in the *main statusline's* agent section; the elapsed timer ships in the *agent panel* rows instead, because upstream provides `startTime` only on the subagent hook — the main-hook data #91 hoped for never materialized.
- The main statusline is completely unchanged unless you add the new settings key.
- 704 tests pass (+51: discriminator matrix, JSONL shape/purity incl. subprocess-level pins for both modes, id-type preservation, status matrix, startTime format bands incl. bool rejection, width drop-order and narrow-panel honesty, NaN-id invalid-JSONL guard, control-char stripping, model-shortener matrix, all-themes sweep, zero-side-effects pins at BOTH the renderer and the main() dispatch level, the full install-funnel matrix — hook install/preserve/corrupt-settings, uninstall foreign-hook/sub-only/stale-.bak scenarios, print-config variants — and the print-config 9-line contract update). Pure stdlib, zero dependencies, as always.

## [0.12.0] - 2026-07-09

### Changed — ⚠️ the `budget` section's meaning is fixed (and its label changes)

- **The budget chip now compares TODAY'S spend — summed across all your sessions on this machine — against `daily_budget_usd`, and is labeled `day:$7.4/$10`.** Before v0.12.0 it compared only the *current session's* cost against the daily budget: five $3 sessions against a $10/day budget each showed a comfortable green $3.0/$10 while the day was actually at 150% of budget. The config key's own name (`daily_budget_usd`), the README ("daily budget tracker"), and the FAQ ("your daily limit") were always unanimous that the contract is daily; the display was the wrong half. The `day:` prefix is deliberate: it announces the change at the moment of upgrade and permanently disambiguates the chip from the adjacent per-session `cost` chip.

  - **Escape hatch:** if you calibrated `daily_budget_usd` as a per-*session* ceiling under the old behavior, set `"budget_scope": "session"` in `~/.claude/claude-status-budget.json` — the chip reverts to the per-session comparison (no `day:` prefix).
  - **Day-one note:** totals accumulate from the moment you upgrade; on the first day the chip may undercount sessions from earlier that morning.
  - **Per machine:** the total is built from local session records; it will undercount your real bill if you also run Claude Code elsewhere. (Documented in the FAQ.)

### Added

- **Per-session daily spend ledger** — one small JSON file per (local day, session) in the user-scoped cache dir, storing the session's cumulative cost (monotonic via `max`) and an attribution base so a session spanning midnight contributes only its post-midnight growth to the new day. Whether a session "started today" is derived from `cost.total_duration_ms` (start ≈ now − duration): started-today sessions get full attribution (this is also what makes upgrade day honest — a mid-session upgrade shows the session's real spend, not $0); older sessions count growth only; missing duration falls back to growth-only (undercounts one turn, never overcounts).

  The design went through two adversarial reviews **before implementation**; choices that trace directly to findings:
  - **Writer-then-reader in one pass, no substitution rule** — an earlier draft's "substitute live cost if larger" compared a cumulative against a day-contribution (units mismatch) and would have re-inflated midnight-spanning sessions by their full prior-day spend.
  - **Raw no-TTL ledger reads** (`_read_ledger`) — reusing the 30s-TTL cache reader would have re-captured the attribution base after every pause longer than 30 seconds, sawtoothing the day total toward zero.
  - **No fallback mode.** The chip's meaning never switches: the live session's *contribution* (per the attribution rules above) is ALWAYS folded into the total — from its ledger file, or computed in memory when the session id is unusable, the write fails, or the ledger is skipped — so a chip labeled `day:` can never silently exclude the session in front of you, and never reverts to per-session semantics with an identical-looking label. When the ledger is empty, the total degrades to the live session's contribution alone: an honest lower bound.
  - **Clamps both ends** — negative/garbage costs are clamped in the writer and contributions floored at 0 in the reader, so a garbage negative baseline can't manufacture phantom spend.
  - **Documented, accepted limitations:** totals are per-machine; a temp-dir wipe mid-day permanently drops that day's *prior* spend (undercount only); a resumed session whose upstream counter jumps to a higher historical baseline mid-day over-attributes the jump to today (not detectable from stdin); two live processes sharing one session id can transiently regress each other's ledger entry via `max()` races (self-heals on the next write).

- **`budget_scope` config key** — `"daily"` (default) or `"session"`, read from the existing `claude-status-budget.json` with the same 30s shared cache; unknown values fall through to daily. Reading uses `.get` with a default so a config dict cached by an older version (key absent) can't `KeyError` during the upgrade window.

### Fixed

- **Cache directory hardened to `0o700`** — the user-scoped cache dir name is predictable (md5 of the home path) and `exist_ok=True` would silently adopt a directory pre-created by another local user. That mattered less when the dir held tool counts; now that it holds per-session spend records, both are hardened best-effort: directories the user owns are repaired to `0o700`; a foreign-owned pre-created directory cannot be repaired (the chmod fails and is swallowed), which is why the ledger additionally refuses to operate in the shared-tempdir fallback. Created with `mode=0o700` and re-`chmod`ed if it already exists; no-op-equivalent on Windows where the temp dir is already per-user.

- **Model names are never truncated mid-token on the main line.** `_short_model()` gained a `cap` parameter; subagent rows keep the per-row cap, the main line passes `cap=None` because `_fit_to_width` already drops the whole section cleanly when it doesn't fit. A bracketed variant marker (`claude-sonnet-4-5-20250929[1m]` → `Sonnet 4.5 [1m]`) now survives the date strip instead of being silently dropped — it tells you which context variant the session is on.
- **`--doctor` reports the effective fit width** (`Fit width: 186 (detected 190 - safety margin 4)`), so a section that vanished after this upgrade is diagnosable rather than mysterious.

### Notes

- The ledger reuses the existing infrastructure end to end: atomic `tmp + os.replace` writes, the user-scoped cache dir, and the existing 2-day mtime cleanup — today's files are rewritten all day (fresh mtime) and age out naturally after the day passes. No new pruning code.
- **`--demo` and the setup wizard stub the spend recorder** — an unstubbed preview render on a machine with a real budget config would have written the fake demo cost into the user's REAL daily ledger (monotonic max — it could not self-correct until midnight). Same class of fix at the test-suite level: `setUpModule` now redirects the entire cache dir to a throwaway location, so no test can ever write phantom spend into a maintainer's live chip (the #96 incident pattern, closed at the same chokepoint style).
- **Garbage durations can't crash the render** — `time.localtime` raises `OverflowError`/`OSError` for epoch values outside time_t range (a duration like `9e18` ms is finite, so `_safe_num` passes it); the started-today classifier now catches these and degrades to the conservative base. Found by review, reproduced before fixing.
- 655 tests (+31): attribution rules (started-today / midnight-spanning / missing-duration / in-memory no-sid variants), monotonicity, negative-clamp with the exact-value pin, corrupt/garbage/`.tmp`-leftover ledger files, day-boundary and midnight determinism via an injected noon clock, shared-sid interleave self-healing, shared-tempdir poisoning guard, unreachable-cache-dir degrade, garbage-duration crash regression, end-to-end chip rendering with color bands computed on the *total*, the scope escape hatch (unit AND through the real config-file parse), upgrade-day lower-bound, and the `0o700` create/repair pins (POSIX-only; skip on Windows, run on the Linux/macOS CI legs). 653 pass + 2 platform skips on Windows; all 655 on POSIX. Pure stdlib, zero dependencies, as always.

## [0.11.0] - 2026-07-09

### Added

- **`cost_rate` section** — renders `~$3.6/hr`, the session's projected cost per hour, from fields already on stdin (`cost.total_cost_usd` / `cost.total_duration_ms`). Pure arithmetic: no new data sources, no price tables, no vendor pricing knowledge (the cost field already reflects whatever pricing applies). Opt-in via custom theme, matching the `thinking` / `pr` / `cache_age` rollout.

  - **Session-average by design** — total cost over total wall-clock time, *including idle*. It answers "what is this session costing per hour of being open", not "what would the current burst cost if sustained". A windowed recent-activity rate needs cached samples and is deliberately deferred.
  - **The `~` prefix marks it as a projection**, not a bill — pinned by a test so a refactor can't silently turn the chip into a bill-looking number.
  - **Hidden whenever the projection would be meaningless**: missing/garbage/NaN/Infinity inputs, zero or negative cost, sessions under one minute (`_COST_RATE_MIN_DURATION_MS` — a session's first seconds extrapolate absurdly, e.g. a $0.05 startup burst over 8s "projects" to $22/hr), and rates below rendering resolution (< $0.0005/hr would show a zero-looking `0c/hr` chip for a positive cost).
  - Reuses `fmt_cost` for the dollar formatting, so the rate renders with the same conventions as the cost section (cents under a penny, `$0.XX` under a dollar, one decimal under $10, whole dollars above).

### Fixed

- **Garbage `cost` / `duration` values could blank the whole statusline.** A malformed upstream value (`total_cost_usd: "abc"`) flowed raw into `fmt_cost`/`fmt_duration` and threw from inside `render()` — caught only by `main()`'s outer handler, which blanks the entire statusline (stderr note, empty stdout) instead of hiding one section. The money/time trio (`cost`, `duration`, `api_duration`) is now coerced through `_safe_num` at the `_normalize` chokepoint (the house pattern), so garbage becomes `None` and every consumer already treats `None` as "hide". Numeric strings (`"0.5"`) coerce and render normally (pinned end-to-end). A present-but-garbage value leaves a one-line stderr breadcrumb (`claude-status: ignoring non-numeric cost value`) so the old crash's diagnostic trail isn't lost to a silent hide; absent fields stay silent. Found by this release's own new-feature tests probing garbage inputs.

- **`_safe_num` now guarantees a FINITE float or None.** Previously `float("nan")`/`float("inf")` passed through — and NaN is poison downstream: every comparison is False, so it sails through threshold checks and detonates later inside a formatter's `int()`. `json.loads` accepts bare `NaN`/`Infinity`, so this was reachable from stdin. All existing `_safe_num` call sites treat `None` as "hide/skip", so the tightened contract is strictly safer; the one pre-existing explicit `isfinite` guard (cost-category filtering) is retained as documented defense-in-depth. Two concrete crashes and one lie this closes:
  - `rate_limits.five_hour.resets_at: Infinity` previously reached `fmt_countdown`'s `int()` → `OverflowError` (not in its except tuple) → whole line blanked. Now hidden. `fmt_countdown` also gained `OverflowError` in its own except tuple so the hole stays shut even if `_safe_num` ever loosens.
  - `used_percentage: NaN` previously sailed past the `>= 1e6` sanity cap (NaN comparisons are all False) into `min(100, nan)` → Python returns **100** → the statusline rendered a false danger-red `5h:100%` for garbage input. Now hidden — a masked wrong output replaced by an honest absence.

- **Model names are never truncated mid-token on the main line.** `_short_model()` gained a `cap` parameter; subagent rows keep the per-row cap, the main line passes `cap=None` because `_fit_to_width` already drops the whole section cleanly when it doesn't fit. A bracketed variant marker (`claude-sonnet-4-5-20250929[1m]` → `Sonnet 4.5 [1m]`) now survives the date strip instead of being silently dropped — it tells you which context variant the session is on.
- **`--doctor` reports the effective fit width** (`Fit width: 186 (detected 190 - safety margin 4)`), so a section that vanished after this upgrade is diagnosable rather than mysterious.

### Notes

- No changes to any default theme — `cost_rate` must be added to a custom theme's line list to appear. No rendering changes for existing sections beyond the garbage-input hardening above (which only affects payloads that previously crashed the render).
- 624 tests pass (+21: formatter gates including boundary/garbage/non-finite/sub-resolution matrices, exact-value pin at the 60s gate, end-to-end section rendering with the tilde pin, droppable membership, `_safe_num` finite-contract pins, garbage cost AND duration/latency/speed render coverage, and the stringified-numerics e2e pin). Pure stdlib, zero dependencies, as always.

## [0.10.0] - 2026-07-09

1M-context readiness release. Claude Code's default model now ships a
1,000,000-token context window, which surfaced three long-dormant
rendering blemishes — all confirmed by running the renderer against
1M-shaped payloads before fixing. Plus a first-impression refresh:
theme screenshots, current demo data, and PyPI metadata.

### Fixed

- **`(1000K)` → `(1M)` context-size label** — the `context_size` section used ad-hoc integer division (`size // 1000` + `"K"`), written when 200K was the dominant window size. A 1M window rendered as `(1000K)`. Now formatted through `fmt_tokens` — one formatting path for every token-shaped number, so K/M suffix rules stay consistent. `(200K)` and `(500K)` render exactly as before.

- **`1.0M` → `1M` trailing-zero strip in `fmt_tokens`** — the K branch already stripped the trailing `.0` (`1000` → `1K`) but the M branch didn't (`1_000_000` → `1.0M`). Same strip rule applied; meaningful decimals are kept (`2.5M`, `1.5M` unchanged). With 1M-window models as the default, `1.0M`-shaped values had become an every-render sight.

- **Bar color / `!CTX` badge threshold alignment** — `_bar_color` went red only above 85% while the `!CTX` danger badge fires at ≥ 85%: at exactly 85% users saw a yellow "caution" bar beside a red danger badge. The bar's red band now starts at 85 to match `CTX_WARNING_THRESHOLD_PCT`. The two constants live in different modules (circular-import constraint), so a new cross-module test (`TestBarCtxWarningAlignment`) keeps them in lockstep.

### Changed

- **`_demo_data()` refreshed to a current default session** — 1M context window with internally consistent numbers (42% ≈ 412K input tokens), current model display name and Claude Code version, populated `pr` block, `thinking` enabled, explicit `effort` level. `--demo` and the README now show what a new user actually sees.

- **README first-impression overhaul** — theme screenshots (SVG) for all 8 themes, including the four color themes that previously had a heading and *no example at all*; a "Try it now" `uvx claude-status --demo` one-liner under the badges (zero-install preview); every stale example updated (old model names, `(200K)`, pre-1M token counts, old version strings).

- **PyPI metadata** — Development Status classifier promoted from Beta to Production/Stable (v0.10.0 is the 34th tagged release, with a 21-job test matrix across 3 OSes × Python 3.8–3.14), Documentation project URL added, and `context-usage` / `usage-tracking` keywords added.

### Added

- **`scripts/render_svg.py`** — repo tooling (not part of the package; pure stdlib like everything else) that renders `--demo` output for each theme into deterministic, git-diffable SVG terminal cards under `assets/themes/`. Every live-data source is pinned during generation — tool counts, commit age, git extras/state, clock, rate-limit countdown, AND all user-config readers (budget, compaction threshold, disabled sections, clickable links) plus the `CLAUDE_STATUSLINE_*` env overrides — so regeneration is byte-identical across runs and machines, and a maintainer's personal `~/.claude` config can never leak into public assets. Writes are atomic (`os.replace`, same pattern as the package's cache writes). Regenerate with `python scripts/render_svg.py` after any theme/section/demo change.

- **`context_size` hardening** — the section now gates the window size through `_safe_num` + `isfinite`, so a non-numeric, `NaN`, or `Infinity` `context_window_size` (all reachable via `json.loads`) hides the section instead of throwing into `render()`'s outer catch. The pre-existing behavior for garbage input was also a crash (different exception), so this is strictly an improvement, now pinned by tests.

- **Model names are never truncated mid-token on the main line.** `_short_model()` gained a `cap` parameter; subagent rows keep the per-row cap, the main line passes `cap=None` because `_fit_to_width` already drops the whole section cleanly when it doesn't fit. A bracketed variant marker (`claude-sonnet-4-5-20250929[1m]` → `Sonnet 4.5 [1m]`) now survives the date strip instead of being silently dropped — it tells you which context variant the session is on.
- **`--doctor` reports the effective fit width** (`Fit width: 186 (detected 190 - safety margin 4)`), so a section that vanished after this upgrade is diagnosable rather than mysterious.

### Notes

- No behavioral changes for 200K-window sessions beyond the 85%-boundary bar color (previously yellow at exactly 85%, now red — matching the `!CTX` badge that was already firing at that percentage).
- 603 tests pass (+14: M-suffix strip cases including the `9_999_999 → "10M"` two-digit-strip convergence and the `999_999` K/M seam, cross-module threshold-alignment pins, context-size label coverage at 950/200K/500K/1M, and non-numeric/NaN/Infinity window hardening). Pure stdlib, zero dependencies, as always.

## [0.9.0] - 2026-07-02

### Added

- **`cache_age` section** ([#92](https://github.com/mkalkere/claude-statusline/issues/92)) — renders `cache_age:4m12s`, the wall-clock time since the last assistant turn. Useful as a cue for how long a long-running task has been going and, in particular, whether Anthropic's ~5-minute prompt cache is still warm. Past the cache TTL (`_CACHE_AGE_WARN_MS`, 5 min) the chip switches to a warning color to flag that the cache has likely gone cold; under it, a muted default color. Opt-in via custom theme, matching the rollout of `thinking` / `pr` / `cost_breakdown`.

  - **Reads real, already-present data.** The age is derived from the `timestamp` field of the most recent assistant message in `transcript_path` — the same stdin field the `activity` section already tail-reads. No new stdin dependency, no undocumented-file parsing.

  - **Reuses the proven transcript reader.** `get_last_assistant_timestamp_ms()` mirrors `get_session_activity_count()`'s defense-in-depth exactly: the `transcript_path` must resolve (via `realpath`, symlink-aware) under `~/.claude/` before any read; only the last 64 KiB is tail-read (the newest assistant message is always at EOF, so no 1 MiB retry is needed as it is for the activity reader's backward walk to a *user* message); and every error path — invalid/non-string path, missing/empty/unreadable file, no assistant message in the window, unparseable timestamp — degrades to `None` so the section hides rather than crashes.

  - **Live-to-the-second despite caching.** The reader caches the *timestamp* (not the derived age) for 5 s, and the renderer recomputes the age against the current clock every render — so the displayed value ticks up smoothly while the transcript read stays cached. A cache *miss* is cached too (as a `{"ts": None}` sentinel) so a long user-only pause doesn't re-tail the file every render.

  - **Clock-skew safe.** A future-dated last message (skew between the machine that wrote the transcript and the one rendering) yields a negative age; the section hides rather than render a nonsense `cache_age:-3s`. `--doctor` reports the future-dated case explicitly so a silently-hidden section still leaves a diagnostic trail.

  - **Python 3.8+ safe timestamp parse.** `_parse_iso8601_ms()` swaps a trailing `Z` for `+00:00` before `datetime.fromisoformat()` so it parses the transcript's `2026-07-02T23:00:49.920Z` form on Python 3.8–3.10 (where `fromisoformat` doesn't accept `Z`) as well as 3.11+. A naive timestamp with no offset is assumed UTC rather than crashed on.

- **Model names are never truncated mid-token on the main line.** `_short_model()` gained a `cap` parameter; subagent rows keep the per-row cap, the main line passes `cap=None` because `_fit_to_width` already drops the whole section cleanly when it doesn't fit. A bracketed variant marker (`claude-sonnet-4-5-20250929[1m]` → `Sonnet 4.5 [1m]`) now survives the date strip instead of being silently dropped — it tells you which context variant the session is on.
- **`--doctor` reports the effective fit width** (`Fit width: 186 (detected 190 - safety margin 4)`), so a section that vanished after this upgrade is diagnosable rather than mysterious.

### Notes

- **Pure upstream-field consumer**, consistent with `thinking` / `pr`: reads a documented stdin-derived field and degrades gracefully when absent. No new heuristics, no dependency changes, pure stdlib.
- **Dropped early under width pressure** — `cache_age` is listed in `_COMPACT_DROP` (which feeds the narrow and precise-fit drop priorities) so it sheds before essential sections on narrow terminals. The bar/tokens/cost/branch identity is never dropped.
- **`--doctor` gained a `Cache age:` probe line** alongside the existing `Activity:`/`Parse:` transcript diagnostics, so users debugging a missing `cache_age` section can see whether the last assistant timestamp is extractable and what age it yields.
- All 585 tests pass (was 564, +21 new: ISO-8601 parser edge cases, the tail extractor with path-validation / caching / schema-fallback coverage, and end-to-end render including the warn threshold, future-timestamp hiding, and droppable membership). Pure stdlib, no dependency changes.
- Closes [#92](https://github.com/mkalkere/claude-statusline/issues/92).

## [0.8.1] - 2026-06-27

### Fixed

- **Test isolation from the real `~/.claude/settings.json`** ([#96](https://github.com/mkalkere/claude-statusline/issues/96)) — during v0.6.1 verification the maintainer's real settings file was found nulled after a test run: an install/uninstall test had written to the real file instead of a tmpfile. The install/uninstall tests do each monkey-patch `cli._settings_path`, but that is opt-in and a future test could forget it. Hardened two ways, both at module scope in `tests/test_all.py`:

  1. **`_settings_path()` now honors a `CLAUDE_STATUSLINE_SETTINGS_PATH` env override** (same convention as `CLAUDE_STATUSLINE_WIDTH`). `setUpModule()` points it at a throwaway temp directory for the whole suite run, so even a test that forgets to monkey-patch the function writes there — never to the real file. A non-empty, non-whitespace value wins; a blank value falls through to the real path so a stray empty export can't redirect writes to `""`. This is the single chokepoint every settings read/write flows through.
  2. **Regression guard** — `setUpModule()` snapshots a sha256 of the real settings file before any test runs (tri-state: hex digest / `None` if genuinely absent / a distinct sentinel if present-but-unreadable, so a transient read failure can't mask a later deletion), and `tearDownModule()` asserts it is unchanged after the whole module run. The assertion lives in `tearDownModule` — not a test method — because that provably runs after *every* test, including the uninstall tests that sort alphabetically after any guard method and caused the original incident. `TestSettingsIsolation` pins the two mechanisms: the `_settings_path()` override contract (non-blank wins verbatim; blank/whitespace/unset fall through to the real path) and an end-to-end check that an *unpatched* `cmd_install` writes to the redirect and leaves the real file byte-identical.

- **Model names are never truncated mid-token on the main line.** `_short_model()` gained a `cap` parameter; subagent rows keep the per-row cap, the main line passes `cap=None` because `_fit_to_width` already drops the whole section cleanly when it doesn't fit. A bracketed variant marker (`claude-sonnet-4-5-20250929[1m]` → `Sonnet 4.5 [1m]`) now survives the date strip instead of being silently dropped — it tells you which context variant the session is on.
- **`--doctor` reports the effective fit width** (`Fit width: 186 (detected 190 - safety margin 4)`), so a section that vanished after this upgrade is diagnosable rather than mysterious.

### Notes

- Production behavior is **unchanged** for end users — `_settings_path()` only consults the new env var, which is unset in normal use, so it resolves to `~/.claude/settings.json` exactly as before. The override exists for test/CI isolation.
- **Subprocess-spawning tests that control the settings location via `HOME`/`USERPROFILE` must drop the override** from the child env (`env.pop("CLAUDE_STATUSLINE_SETTINGS_PATH", None)`), since it intentionally wins over `expanduser("~")`. Fixed in `test_subprocess_invocation_returns_correct_exit_code`; documented in the `docs/RELEASE.md` failure-mode catalog per the issue's acceptance criteria.
- All 564 tests pass (was 562, +2 net new: the `_settings_path()` override contract test and the unpatched-install-writes-to-redirect guard; the real-file-unchanged assertion runs in `tearDownModule`). Pure stdlib, no dependency changes.
- Closes [#96](https://github.com/mkalkere/claude-statusline/issues/96).

## [0.8.0] - 2026-06-27

### Added

- **PR review-state rendering** ([#99](https://github.com/mkalkere/claude-statusline/issues/99) follow-up) — the `pr` section now renders `pr.review_state` as a short token appended to the PR number: `PR#1234 ok` (approved), `chg` (changes_requested), `rev` (pending), `draft`. The value was already captured and enum-validated in `_normalize()` since v0.6.3 (which deferred rendering to a follow-up); this release adds the renderer with no change to the capture path. The token is appended **outside** the OSC 8 hyperlink envelope so the clickable target stays exactly `PR#N` and the state reads as an adjacent annotation. Per-state color is themeable via `pr_review_<state>` keys (default: green/red/yellow/dim), falling through with `_first()` so a theme setting the key to `null` degrades to the default rather than crashing. Hidden — section degrades to bare `PR#N` — whenever `review_state` is absent or fails the documented enum (`approved`/`pending`/`changes_requested`/`draft`); the lookup is total over every value that survives normalization, so a desync between the validation set and the render map can't `KeyError`. A deliberately ASCII token (not an emoji) keeps it width-1-per-char and renders identically in every terminal, consistent with the rest of the statusline. Opt-in: rides along automatically wherever the `pr` section is already enabled.

- **`thinking` section** — renders a `think` badge from the documented `thinking.enabled` stdin boolean. Surfaces only the affirmative case (`thinking.enabled` strictly `True`): an "off" indicator would be noise on every non-thinking session. `_normalize()` reduces the field to a strict bool via `is True` (not truthiness), so a malformed non-bool like `enabled: 1` does not masquerade as the documented value, and an `isinstance(dict)` guard mirrors every other nested-object read so `thinking: "yes"` (string) can't crash. Pairs naturally with `effort` — both describe how the model is reasoning this session. Color is themeable via the `thinking` key (default magenta). Opt-in via custom theme initially, matching the rollout of `pr` / `cost_breakdown`; may promote to a default-theme section if user feedback is positive.

- **Model names are never truncated mid-token on the main line.** `_short_model()` gained a `cap` parameter; subagent rows keep the per-row cap, the main line passes `cap=None` because `_fit_to_width` already drops the whole section cleanly when it doesn't fit. A bracketed variant marker (`claude-sonnet-4-5-20250929[1m]` → `Sonnet 4.5 [1m]`) now survives the date strip instead of being silently dropped — it tells you which context variant the session is on.
- **`--doctor` reports the effective fit width** (`Fit width: 186 (detected 190 - safety margin 4)`), so a section that vanished after this upgrade is diagnosable rather than mysterious.

### Notes

- **Both features are pure upstream-field consumers.** No new heuristics, no config parsing of undocumented files — they read documented stdin fields and degrade gracefully when absent, exactly like every other section. Verified against the live Claude Code statusline schema as of 2026-06-27. The audit that motivated this release also confirmed the `COLUMNS`/`LINES` env handoff is already consumed by the width-detection chain and `context_window.remaining_percentage` is already derivable — neither needed new code.
- **`thinking` and `pr` (with review state) are dropped early under width pressure** — both are listed in `_COMPACT_DROP` (which feeds the narrow and precise-fit drop priorities) so they shed before essential sections on narrow terminals. The bar/tokens/cost/branch identity is never dropped.
- All 562 tests pass (was 549, +13 net new in `tests/test_all.py`: 9 for `pr.review_state` (enum accept, case-insensitivity across single- and multi-word states, unknown/non-string reject, per-state token render, bare-PR fallback, render-map↔enum sync guard, per-state theme color override applied, null-override fall-through to default color, and `_COMPACT_DROP` membership) and 4 for `thinking` (strict-True normalize, renders-when-enabled, hidden for off/absent/malformed, and `_COMPACT_DROP` membership)). Pure stdlib, no dependency changes.
- Closes the `pr.review_state` rendering follow-up from [#99](https://github.com/mkalkere/claude-statusline/issues/99).

## [0.7.0] - 2026-06-05

### Added

- **N-line statusline support** ([#101](https://github.com/mkalkere/claude-statusline/issues/101)) — themes can now define `line3`, `line4`, etc, and `render()` will produce that many rows. The hardcoded 2-line ceiling at `cli.py:render()` is gone, replaced by a loop that iterates `lineN` keys in the theme until it hits a missing index. Backward compatible: every built-in theme (and every existing user `~/.claude/claude-status-theme.json`) defines only `line1` + `line2` and stops at `line3` (missing), producing exactly two rows — identical to v0.6.3. Themes that opt in to a third (or further) row see it render, subject to the same per-row adaptive layout (`_apply_responsive` + `_fit_to_width`) that v0.6.0's two-line layout used. The "gap in numbering" case (e.g., `line1` + `line2` + `line4` with no `line3`) is treated as "end of rows" rather than "skip and continue" — matches the user mental model that statusline rows are contiguous and keeps the loop bounded.

  This feature was previously blocked on Claude Code's Ink TUI silently truncating lines past Line 1 ([anthropics/claude-code#28750](https://github.com/anthropics/claude-code/issues/28750), [#36417](https://github.com/anthropics/claude-code/issues/36417)). Both are now closed: the per-line independent width-limit fix landed in the 2.1.139 era and resolved #36417, and 2.1.141 ships the `COLUMNS` env-var handoff per its release notes (closes [#22115](https://github.com/anthropics/claude-code/issues/22115)). The official statusline docs explicitly support multi-row output. On narrow terminals, rows past Line 1 can still be dropped by Claude Code's intentional rendering behavior (#28750 closed as "not planned") — not something claude-status can override.

### Changed

- **Layout thresholds relax on Claude Code 2.1.141+** ([#94](https://github.com/mkalkere/claude-statusline/issues/94)) — `_FULL_LAYOUT_MIN_COLS` drops from 150 to 110 and `_COMPACT_LAYOUT_MIN_COLS` from 100 to 80 when BOTH gates pass: (a) `version` from stdin parses as Claude Code 2.1.141 or later (the release that ships the `COLUMNS` env handoff making width detection trustworthy), AND (b) the width-detection chain found a high-confidence signal (a real probe succeeded, not the safe-default fallback path).

  Conservative thresholds remain the default for older Claude Code, for the no-trustworthy-signal case, and for any path where data is absent. This preserves the v0.5.4 safety contract from [#72](https://github.com/mkalkere/claude-statusline/issues/72) and protects users on older Claude Code or stuck on the 2.1.139 width-detection regression. For users on 2.1.141+ with a real terminal width, the practical effect is **sections that were dropped by the coarse pre-filter on 100-149 col terminals are now retained** (e.g., `version`, `rate_limits`, `effort`, `tools` at 120 cols on a 2.1.141 session).

  Decision logic lives in two new functions in `cli.py`: `_parse_cc_version()` (converts the stdin `version` string to a comparable 3-tuple, rejecting non-string / garbage / fewer-than-3-parts inputs by returning None) and `_layout_thresholds(data, width_confidence_high)` (returns the threshold pair). `_apply_responsive()` now accepts the thresholds as keyword arguments (with the conservative pair as defaults, so existing callers that pass only `term_width` still get the safe behavior).

- **Model names are never truncated mid-token on the main line.** `_short_model()` gained a `cap` parameter; subagent rows keep the per-row cap, the main line passes `cap=None` because `_fit_to_width` already drops the whole section cleanly when it doesn't fit. A bracketed variant marker (`claude-sonnet-4-5-20250929[1m]` → `Sonnet 4.5 [1m]`) now survives the date strip instead of being silently dropped — it tells you which context variant the session is on.
- **`--doctor` reports the effective fit width** (`Fit width: 186 (detected 190 - safety margin 4)`), so a section that vanished after this upgrade is diagnosable rather than mysterious.

### Notes

- **Backward compatibility.** Every existing theme renders identically to v0.6.3 — the 2-line hardcode removal was a *capability* change, not a *behavior* change. Every user on Claude Code older than 2.1.141 also renders identically — the threshold relaxation is gated, not unconditional. The only visible-output change is for users who EITHER opt into a 3+ line theme OR run on Claude Code ≥ 2.1.141 with a high-confidence terminal width and a 100-149 col terminal.
- **`render()` now uses `_detect_terminal_width_report()` instead of `_detect_terminal_width()`** so it can derive width-detection confidence from the per-step report. This is internal plumbing — `--doctor` already used the report variant in v0.6.0, so no observable change there.
- **Custom themes can now opt into N-line layouts** — fixed during the v0.7.0 review cycle: `themes.load_custom_theme()` previously hardcoded `line1`/`line2` only, silently dropping any `lineN` keys for N≥3 from `~/.claude/claude-status-theme.json`. Without this fix the v0.7.0 N-line capability would have been unreachable for any user using `theme: custom`. Now accepts every `lineN` key (regex `line\d+` with isinstance-list guard).
- All 549 tests pass (was 507, +42 net new in `tests/test_v070_nlines_and_thresholds.py`: 6 for N-line render contract, 7 for `_parse_cc_version()` (canonical, prefix, suffix, arity, type, garbage, ordering), 7 for `_layout_thresholds()` gate truth table, 3 end-to-end render tests, 3 for the `(winner` substring contract (real-report check + bidirectional stub-report tests), 6 for the custom-theme N-line accept path (line3/line5/double-digit/list-required/garbage-rejected/backward-compat), 2 for `_apply_responsive` × N-line interaction (line3 droppable filter + disabled-sections × line3), 2 for the strip-order fix (leading whitespace before `v`), 3 for `_layout_thresholds` non-dict data robustness (list / string / int defaults to conservative without crashing), and 3 for the custom-theme leading-zero key normalization (`"line01"` → `"line1"`, `"line003"` → `"line3"`, `"line0"` silently skipped without clobbering legitimate line1). Pure stdlib, no dependency changes.
- Closes [#101](https://github.com/mkalkere/claude-statusline/issues/101) and [#94](https://github.com/mkalkere/claude-statusline/issues/94).

## [0.6.3] - 2026-06-04

### Changed

- **Schema realignment** ([#99](https://github.com/mkalkere/claude-statusline/issues/99)) — the stdin schema described in the live Claude Code statusline docs has shifted since v0.6.1 and v0.6.2 shipped. v0.6.3 reconciles claude-status against that schema while keeping every prior shape working as a fallback so no user upgrading from v0.6.1 or v0.6.2 loses a section mid-migration.

  - **PR / repo namespace.** v0.6.1's `pr` section read `github.{pr_number, pr_url}` and `github.repo`. The live docs schema now lists these under `pr.{number, url, review_state}` and `workspace.repo.{host, owner, name}` with no `github.*` namespace at all. v0.6.3 reads BOTH with truthy-value precedence: the new shape wins when populated, the older shape is the fallback. The normalized output keys (`github_repo`, `github_pr_url`, `github_pr_number`) are kept unchanged from v0.6.1 so any custom-theme consumer depending on those names continues to work; the keys describe what claude-status STORES, not which upstream namespace they came from. PR numbers are validated through a single `_clean_pr_number()` helper so the implausibly-large cap stays uniform across both branches. `pr.review_state` is captured internally but not rendered in this release (rendering tracked separately for a follow-up).

  - **`effort.level` enum: `ultra` is now a silent alias for `xhigh`.** v0.6.2 added `ultra` as a 6th accepted level documenting it as the stored value Claude Code emits for `/effort ultracode`. The live effort doc and statusline doc list valid `effort.level` values as `low, medium, high, xhigh, max` only, with an explicit note that ultracode is not a distinct level — it reports as `xhigh`. v0.6.3 keeps `ultra` accepted in the validation set so two real user groups continue to render an effort section after upgrade: (a) anyone whose `~/.claude/settings.json` still has `effortLevel: "ultra"` because v0.6.2 told them it was valid, and (b) anyone whose claude-status disk cache was written by v0.6.2 with that value. The alias is applied at three layers — stdin normalize, settings.json fresh read, and cache-read return — so a stale on-disk cache from a v0.6.2 install renders correctly from the very first render after upgrade with no 30-second window where the user still sees `effort:ultra`. **Visible change: users who previously saw `effort:ultra` will see `effort:xhigh` after upgrading.** Both labels describe the same setting; only the label changes to match the documented enum.

- **`workspace` isinstance guard at `_normalize`** — v0.6.1 added isinstance guards across `agent`, `cost`, `vim`, `github`, and `worktree` (#88, #87, Gemini PR #90 review) but missed `workspace`. A non-dict `workspace` value from an upstream variant would crash `_normalize` with AttributeError on the subsequent `.get()` calls, caught only by `main()`'s outer try/except. v0.6.3 closes the gap so the same defensive pattern is uniform across `_normalize`.

- **Model names are never truncated mid-token on the main line.** `_short_model()` gained a `cap` parameter; subagent rows keep the per-row cap, the main line passes `cap=None` because `_fit_to_width` already drops the whole section cleanly when it doesn't fit. A bracketed variant marker (`claude-sonnet-4-5-20250929[1m]` → `Sonnet 4.5 [1m]`) now survives the date strip instead of being silently dropped — it tells you which context variant the session is on.
- **`--doctor` reports the effective fit width** (`Fit width: 186 (detected 190 - safety margin 4)`), so a section that vanished after this upgrade is diagnosable rather than mysterious.

### Notes

- **Prior CHANGELOG entries are not edited.** v0.6.1 and v0.6.2 published the schema and enum claims that the live docs have since contradicted. The release-history rule on this project is that already-shipped CHANGELOG blocks are frozen; later entries reference earlier ones by version name and supersede the factual claims rather than rewriting them. The v0.6.1 #87 entry continues to describe what v0.6.1 read (`github.pr_number`); the v0.6.2 #97 entry continues to describe what v0.6.2 added (the `ultra` level). v0.6.3 reconciles both.

- **Backward compatibility.** A user on Claude Code releases still emitting `github.*` keeps seeing the PR badge unchanged. A user whose `effortLevel` is `"ultra"` in settings.json keeps seeing an effort section (now `effort:xhigh`). No section silently disappears across the v0.6.2 → v0.6.3 upgrade.

- **`effort_ultra` theme keys retained as documented dead surface.** The silent alias means the `if effort == "ultra"` branch in `cli.py` and the `effort_ultra` color keys in all 8 themes are no longer reachable in practice (alias rewrites to `xhigh` before render). They are retained with explicit source comments rather than removed so a future cleanup PR doesn't delete them without context, and so a hypothetical future Claude Code release that did re-introduce a distinct `ultra` stored value would reactivate them rather than require reintroduction.

- All 507 tests pass (was 477, +30 net new in `tests/test_ultra_effort.py`: alias-map strict equality with explanatory docstring, ultra at all three layers, stale-cache rehydration scenario, stdin-overrides-stale-cache convergence, dual-namespace precedence including the both-populated and per-field empty cases, shared PR-number cap on both branches with boundary cases at 0 / negative / 999_999 / fractional-truncated, `workspace.repo` composition with empty-string and partial-fallthrough variants, `pr.review_state` capture + rejection + case-normalization, and the workspace isinstance guard at both `_normalize` sites). Pure stdlib, no dependency changes.

- Closes [#99](https://github.com/mkalkere/claude-statusline/issues/99).

## [0.6.2] - 2026-05-29

### Added
- **`ultra` effort level** — Claude Code emits `effort.level: "ultra"` on stdin, the stored value for `/effort ultracode` introduced alongside Opus 4.8 (2026-05-28). Valid `effort.level` values are now `low, medium, high, xhigh, max, ultra`. Previously claude-status hardcoded the valid set without `ultra`, so a real `effort.level: "ultra"` was silently rejected and the `effort:` indicator disappeared for ultracode users — the same class of bug fixed for `xhigh`/`max` in v0.5.6. Now `ultra` is accepted in both the stdin path and the settings.json fallback path, renders as the new top tier (color falls through `effort_ultra → effort_max → effort_xhigh → effort_high → BRIGHT_MAGENTA` via `_first()`), and all 8 built-in themes carry the `effort_ultra` color key (mirroring `effort_max`). The stored value `ultra` is rendered verbatim, not the `ultracode` display label — consistent with how every other tier renders its stored `effort.level` value.

### Changed
- Demo data (`--demo`), README, and a test fixture now reference **Opus 4.8 (1M context)** instead of Opus 4.7, reflecting Anthropic's current top model (released 2026-05-28).

- **Model names are never truncated mid-token on the main line.** `_short_model()` gained a `cap` parameter; subagent rows keep the per-row cap, the main line passes `cap=None` because `_fit_to_width` already drops the whole section cleanly when it doesn't fit. A bracketed variant marker (`claude-sonnet-4-5-20250929[1m]` → `Sonnet 4.5 [1m]`) now survives the date strip instead of being silently dropped — it tells you which context variant the session is on.
- **`--doctor` reports the effective fit width** (`Fit width: 186 (detected 190 - safety margin 4)`), so a section that vanished after this upgrade is diagnosable rather than mysterious.

### Notes
- **Backward compatible** — users on Claude Code releases before Opus 4.8 / ultracode see no change. The `ultracode` display label is still correctly rejected as invalid (only the stored value `ultra` is accepted), so validation is not weakened.
- **Verified non-issues for Opus 4.8**: model `display_name` renders verbatim (no hardcoded model IDs), context window unchanged (1M, same as Opus 4.7), pricing is supplied by Claude Code (`cost.total_cost_usd`; no hardcoded rates), and no new statusline stdin fields shipped in the Claude Code releases bundling Opus 4.8.
- New tests live in `tests/test_ultra_effort.py` (20 tests): stdin path, settings.json path, case-insensitivity, stdin precedence over settings.json, all-themes render, top-tier color, section-hiding when medium/absent, custom-theme fallthrough (missing key and explicit None), structural parity (every theme has `effort_ultra` mirroring `effort_max`), and `ultracode`-label / non-string / bogus-level rejection. Render-based tests pass an explicit wide `terminal.columns` so the `effort` section is eligible for the full layout (the default theme drops it below the 150-col threshold).
- All 477 tests pass (was 455, +22 new). Pure stdlib, no dependency changes.

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

- **Model names are never truncated mid-token on the main line.** `_short_model()` gained a `cap` parameter; subagent rows keep the per-row cap, the main line passes `cap=None` because `_fit_to_width` already drops the whole section cleanly when it doesn't fit. A bracketed variant marker (`claude-sonnet-4-5-20250929[1m]` → `Sonnet 4.5 [1m]`) now survives the date strip instead of being silently dropped — it tells you which context variant the session is on.
- **`--doctor` reports the effective fit width** (`Fit width: 186 (detected 190 - safety margin 4)`), so a section that vanished after this upgrade is diagnosable rather than mysterious.

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

- **Model names are never truncated mid-token on the main line.** `_short_model()` gained a `cap` parameter; subagent rows keep the per-row cap, the main line passes `cap=None` because `_fit_to_width` already drops the whole section cleanly when it doesn't fit. A bracketed variant marker (`claude-sonnet-4-5-20250929[1m]` → `Sonnet 4.5 [1m]`) now survives the date strip instead of being silently dropped — it tells you which context variant the session is on.
- **`--doctor` reports the effective fit width** (`Fit width: 186 (detected 190 - safety margin 4)`), so a section that vanished after this upgrade is diagnosable rather than mysterious.

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

- **Model names are never truncated mid-token on the main line.** `_short_model()` gained a `cap` parameter; subagent rows keep the per-row cap, the main line passes `cap=None` because `_fit_to_width` already drops the whole section cleanly when it doesn't fit. A bracketed variant marker (`claude-sonnet-4-5-20250929[1m]` → `Sonnet 4.5 [1m]`) now survives the date strip instead of being silently dropped — it tells you which context variant the session is on.
- **`--doctor` reports the effective fit width** (`Fit width: 186 (detected 190 - safety margin 4)`), so a section that vanished after this upgrade is diagnosable rather than mysterious.

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

- **Model names are never truncated mid-token on the main line.** `_short_model()` gained a `cap` parameter; subagent rows keep the per-row cap, the main line passes `cap=None` because `_fit_to_width` already drops the whole section cleanly when it doesn't fit. A bracketed variant marker (`claude-sonnet-4-5-20250929[1m]` → `Sonnet 4.5 [1m]`) now survives the date strip instead of being silently dropped — it tells you which context variant the session is on.
- **`--doctor` reports the effective fit width** (`Fit width: 186 (detected 190 - safety margin 4)`), so a section that vanished after this upgrade is diagnosable rather than mysterious.

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

- **Model names are never truncated mid-token on the main line.** `_short_model()` gained a `cap` parameter; subagent rows keep the per-row cap, the main line passes `cap=None` because `_fit_to_width` already drops the whole section cleanly when it doesn't fit. A bracketed variant marker (`claude-sonnet-4-5-20250929[1m]` → `Sonnet 4.5 [1m]`) now survives the date strip instead of being silently dropped — it tells you which context variant the session is on.
- **`--doctor` reports the effective fit width** (`Fit width: 186 (detected 190 - safety margin 4)`), so a section that vanished after this upgrade is diagnosable rather than mysterious.

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

- **Model names are never truncated mid-token on the main line.** `_short_model()` gained a `cap` parameter; subagent rows keep the per-row cap, the main line passes `cap=None` because `_fit_to_width` already drops the whole section cleanly when it doesn't fit. A bracketed variant marker (`claude-sonnet-4-5-20250929[1m]` → `Sonnet 4.5 [1m]`) now survives the date strip instead of being silently dropped — it tells you which context variant the session is on.
- **`--doctor` reports the effective fit width** (`Fit width: 186 (detected 190 - safety margin 4)`), so a section that vanished after this upgrade is diagnosable rather than mysterious.

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

- **Model names are never truncated mid-token on the main line.** `_short_model()` gained a `cap` parameter; subagent rows keep the per-row cap, the main line passes `cap=None` because `_fit_to_width` already drops the whole section cleanly when it doesn't fit. A bracketed variant marker (`claude-sonnet-4-5-20250929[1m]` → `Sonnet 4.5 [1m]`) now survives the date strip instead of being silently dropped — it tells you which context variant the session is on.
- **`--doctor` reports the effective fit width** (`Fit width: 186 (detected 190 - safety margin 4)`), so a section that vanished after this upgrade is diagnosable rather than mysterious.

### Notes
- Anthropic's underlying `wrap:"truncate"` bug (anthropics/claude-code#28750) remains unaddressed upstream — the issue was closed by stalebot after 30 days of inactivity following the reporter's root-cause trace. Our two-stage layout makes the workaround tighter: instead of dropping the entire compact-bucket of sections at a single width threshold, we measure and drop only what actually doesn't fit.
- Users who previously saw a sparse Line 2 between the compact and full thresholds will see additional sections automatically. No config change required.
- Closes #73.

## [0.5.3] - 2026-04-13

### Fixed
- **Line 2 truncation at 120-col terminals** — after #68 fixed OSC 8, Line 2 rendered correctly but was truncated with an ellipsis on 120-col terminals because Line 2's full-layout content had grown to ~225 visible chars with a worst-case realistic payload (long session, long branch/session name, all rate limits populated) over v0.3-v0.5 (rate limits, speed, commit_age, session_name, output_style, added_dirs, git_worktree, effort, cc_version, etc.). Raised the full-layout threshold from 120 to 230 cols (and the compact threshold from 80 to 100). Terminals 120-229 cols now use the compact layout, which drops the heaviest Line 2 sections. 230 buffers above the measured worst-case 225. Most terminals will land in compact layout — the safe default. Closes #70.
- Added 4 end-to-end regression tests that render with a worst-case heavy payload (realistic workspace, long branch/session name) at 80/100/120 cols and at the full-layout threshold; they assert every line's visible width fits — catches future feature additions that grow Line 2 past the threshold.
- Default fallback for `shutil.get_terminal_size()` updated from 120 to 100 (compact layout) for non-interactive contexts. Safer default than the old "assume full layout."

- **Model names are never truncated mid-token on the main line.** `_short_model()` gained a `cap` parameter; subagent rows keep the per-row cap, the main line passes `cap=None` because `_fit_to_width` already drops the whole section cleanly when it doesn't fit. A bracketed variant marker (`claude-sonnet-4-5-20250929[1m]` → `Sonnet 4.5 [1m]`) now survives the date strip instead of being silently dropped — it tells you which context variant the session is on.
- **`--doctor` reports the effective fit width** (`Fit width: 186 (detected 190 - safety margin 4)`), so a section that vanished after this upgrade is diagnosable rather than mysterious.

### Notes
- Users on terminals between 120 and 229 cols will see fewer Line 2 sections than before. To get the full layout, widen your terminal to 230+ cols.
- Users who want specific sections to always show regardless of width can use the existing `disabled_sections` config in `~/.claude/claude-status-budget.json` to hide other sections instead.

## [0.5.2] - 2026-04-12

### Fixed
- **Line 2 disappearing — real root cause** — OSC 8 clickable hyperlink escape sequences (added in v0.5.0, #63) add ~180 bytes per link but are invisible to the user. Claude Code's Ink TUI `<Text wrap="truncate">` doesn't recognize OSC 8 sequences — it counts those escape bytes toward line width, miscalculates Line 2 as ~200+ chars wide, and silently drops it. This is independent of Line 1 content. Closes #68.
- OSC 8 clickable links are now **disabled by default**. Opt in via `"clickable_links": true` in `~/.claude/claude-status-budget.json` for users who run claude-status in a supporting terminal (iTerm2, Kitty, WezTerm) outside of Claude Code.

- **Model names are never truncated mid-token on the main line.** `_short_model()` gained a `cap` parameter; subagent rows keep the per-row cap, the main line passes `cap=None` because `_fit_to_width` already drops the whole section cleanly when it doesn't fit. A bracketed variant marker (`claude-sonnet-4-5-20250929[1m]` → `Sonnet 4.5 [1m]`) now survives the date strip instead of being silently dropped — it tells you which context variant the session is on.
- **`--doctor` reports the effective fit width** (`Fit width: 186 (detected 190 - safety margin 4)`), so a section that vanished after this upgrade is diagnosable rather than mysterious.

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
