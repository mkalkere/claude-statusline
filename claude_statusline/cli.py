"""CLI entry point for claude-status."""

import argparse
import json
import math
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

from . import __version__
from .bar import _bar_color, render_bar
from . import colors as _colors_mod
from .colors import (
    BOLD, BRIGHT_BLACK, BRIGHT_MAGENTA, BRIGHT_RED, CYAN, GREEN, RED, RESET,
    YELLOW, colorize,
)
from .formatters import (
    fmt_burn_rate, fmt_cache_pct, fmt_cost, fmt_cost_rate, fmt_countdown,
    fmt_duration, fmt_lines, fmt_speed, fmt_tokens,
)
from .git import (
    get_branch, get_git_extras, get_git_state,
    get_last_commit_age_ms, get_remote_url,
)
from .sessions import (
    _CLAUDE_DIR, _CLAUDE_DIR_REAL, _VALID_EFFORT_LEVELS,
    _canonical_effort, _count_activity_with_status,
    _parse_iso8601_ms,
    _read_cache, _write_cache,
    get_budget_config, get_budget_scope, get_clickable_links_enabled,
    get_compaction_threshold,
    get_disabled_sections, get_effort_level, get_last_assistant_timestamp_ms,
    record_and_get_daily_spend,
    get_session_activity_count,
    get_session_tool_count, get_today_session_count,
)
from .themes import THEMES, get_theme

# Percentage of context window usage that triggers the !CTX warning.
CTX_WARNING_THRESHOLD_PCT = 85

# cache_age (#92): milliseconds since the last assistant turn beyond
# which the section renders in a warning color, signalling the prompt
# cache has likely gone cold. Anthropic's prompt cache TTL is ~5
# minutes; we mirror that default here. This is a display heuristic
# only — it never changes behavior, just the color the user sees.
_CACHE_AGE_WARN_MS = 5 * 60 * 1000

# Documented review states for pr.review_state (statusline doc enum
# as of 2026-06-04). Used by _normalize to membership-check the
# captured value so a malformed upstream value never reaches
# downstream consumers. Module-private — not part of the public API
# surface. Rendered by the `pr` section via _PR_REVIEW_DISPLAY, whose
# keys must stay in sync with this set (asserted by
# TestPRReviewState.test_display_map_stays_in_sync_with_enum).
_PR_REVIEW_STATES = frozenset({
    "approved", "pending", "changes_requested", "draft",
})

# Render mapping for pr.review_state: each documented state → (short
# ASCII token, default color). The token is deliberately ASCII (not an
# emoji) so it is width-1-per-char and renders identically in every
# terminal — consistent with the rest of the statusline. Keys MUST stay
# in sync with _PR_REVIEW_STATES; the test suite asserts the two sets
# are identical so a future state added to one can't silently desync the
# other. Per-state theme override key is "pr_review_<state>".
_PR_REVIEW_DISPLAY = {
    "approved":          ("ok",    GREEN),
    "changes_requested": ("chg",   RED),
    "pending":           ("rev",   YELLOW),
    "draft":             ("draft", BRIGHT_BLACK),
}


def _force_utf8():
    """Force UTF-8 encoding on stdout for Windows compatibility."""
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _settings_path():
    """Get Claude Code settings.json path.

    Honors the ``CLAUDE_STATUSLINE_SETTINGS_PATH`` env override (same
    convention as ``CLAUDE_STATUSLINE_WIDTH``). This is the single
    chokepoint every settings read/write flows through — the override
    lets the test suite (and CI) redirect ALL settings I/O to a temp
    file centrally, so even a test that forgets to monkey-patch this
    function can never touch the real ``~/.claude/settings.json``.
    Defense-in-depth against the test-isolation footgun in #96: a
    contributor running ``python -m unittest discover tests/`` must not
    risk nuking their own Claude Code statusline config. A non-empty,
    non-whitespace value wins; anything else falls through to the real
    path so a stray empty export can't redirect writes to ``""``.
    """
    override = os.environ.get("CLAUDE_STATUSLINE_SETTINGS_PATH")
    if isinstance(override, str) and override.strip():
        return override
    home = os.path.expanduser("~")
    return os.path.join(home, ".claude", "settings.json")


def _first(*vals):
    """Return the first value that is not None."""
    for v in vals:
        if v is not None:
            return v
    return None


def _safe_num(val):
    """Coerce to a FINITE float or return None.

    Prevents crashes on non-numeric input. NaN and Infinity are
    rejected too (json.loads accepts both as bare literals): every
    consumer treats the return value as render-ready, and NaN in
    particular is poison downstream — all comparisons are False, so it
    sails through threshold checks and only blows up later inside a
    formatter's int(). "Safe" means finite.
    """
    if val is None:
        return None
    try:
        num = float(val)
    except (TypeError, ValueError):
        return None
    return num if math.isfinite(num) else None


def _osc8_link(url, text):
    """Wrap text in an OSC 8 hyperlink escape sequence.

    Disabled by default because Claude Code's Ink TUI renderer does not
    understand OSC 8 sequences — it counts the escape bytes toward line
    width and silently drops Line 2 when the branch section has a link.

    Users who run claude-status in a terminal that supports OSC 8
    (iTerm2, Kitty, WezTerm) outside of Claude Code can opt in by
    setting {"clickable_links": true} in ~/.claude/claude-status-budget.json.

    Returns plain text unless: url is present, NO_COLOR is not set,
    and the user has explicitly opted in.

    Sanitization: any URL containing a control byte (BEL, ESC, OSC
    terminator, newline, CR) that would break OUT of the OSC 8 link
    envelope is rejected — wrapping it could allow an attacker-
    controlled JSON field (e.g. stdin github.pr_url) to inject
    arbitrary terminal escape sequences. Falls back to plain text.
    """
    if not url or _colors_mod._NO_COLOR:
        return text
    if not get_clickable_links_enabled():
        return text
    # Reject URLs containing control bytes that would corrupt the
    # OSC 8 envelope. \x07 (BEL), \x1b (ESC), \x9c (ST) can break out
    # of the escape sequence; \n and \r split the rendered line.
    # We reject all C0 and the C1 ST byte rather than enumerate.
    if any(ord(c) < 0x20 or ord(c) == 0x7f or ord(c) == 0x9c for c in url):
        return text
    return "\033]8;;{}\033\\{}\033]8;;\033\\".format(url, text)


def _normalize(data):
    """Normalize Claude Code JSON into a flat dict for rendering.

    Handles the real nested schema (context_window.*, cost.*, vim.mode, etc.)
    as well as flat keys used by demo mode.
    """
    out = {}

    # Context window (nested or flat)
    cw = data.get("context_window") or {}
    cu = cw.get("current_usage") or {}
    flat_usage = data.get("current_usage") or {}

    # _safe_num on the whole context/token block — same chokepoint
    # treatment the money/time trio received in v0.11.0, applied here
    # in v0.14.0 after a probe showed `used_percentage: NaN` (a valid
    # json.loads literal, so stdin-reachable) sailing through the
    # `is not None` gates into render_bar's int() and blanking the
    # entire statusline. Garbage becomes None; every consumer already
    # treats None as "hide". Numeric strings coerce and render.
    #
    # `token_fields_corrupt` preserves the absent-vs-garbage
    # distinction the coercion would otherwise destroy: the DERIVED
    # chips (cache %, burn, speed) sum these fields with an
    # absent-means-0 rule, and silently zeroing a component that
    # upstream DID send (but garbled) would render confidently-wrong
    # ratios — a cache hit-rate inflated from 60% to 90% with no
    # visible cue (silent-failure review, reproduced). Those chips
    # hide when this flag is set; per-field sections (tokens, bar)
    # keep their own per-field visibility.
    def _coerce_token(field, raw):
        num = _safe_num(raw)
        if raw is not None and num is None:
            out["token_fields_corrupt"] = True
            # Same stderr breadcrumb as the money/time trio's
            # _num_or_note: present-but-garbage must leave a
            # diagnostic trail, not vanish silently.
            print(
                "claude-status: ignoring non-numeric {} value".format(field),
                file=sys.stderr,
            )
        return num

    out["token_fields_corrupt"] = False
    out["used_percentage"] = _coerce_token(
        "used_percentage",
        _first(cw.get("used_percentage"), flat_usage.get("used_percentage")))
    out["input_tokens"] = _coerce_token(
        "input_tokens",
        _first(cu.get("input_tokens"), flat_usage.get("input_tokens")))
    out["output_tokens"] = _coerce_token(
        "output_tokens",
        _first(cu.get("output_tokens"), flat_usage.get("output_tokens")))
    out["cache_read"] = _coerce_token("cache_read", _first(
        cu.get("cache_read_input_tokens"),
        flat_usage.get("cache_read_tokens"),
    ))
    out["cache_create"] = _coerce_token("cache_create", _first(
        cu.get("cache_creation_input_tokens"),
        flat_usage.get("cache_create_tokens"),
    ))
    out["context_size"] = _first(
        cw.get("context_window_size"),
        flat_usage.get("context_size"),
    )

    # Cost (nested or flat). The isinstance guard handles upstreams
    # that send `cost` as a number (older schemas) or string instead
    # of a dict.
    cost_obj = data.get("cost")
    cost_obj = cost_obj if isinstance(cost_obj, dict) else {}
    # _safe_num on the money/time trio: a stringified or garbage value
    # (e.g. `total_cost_usd: "abc"` from a malformed upstream) would
    # otherwise flow raw into fmt_cost/fmt_duration and throw from
    # inside render() — caught only by main()'s outer fallback, which
    # blanks the whole statusline instead of hiding one section.
    # Coercing here (same chokepoint pattern as by_category below)
    # turns garbage into None, which every consumer already treats as
    # "hide". Numeric strings ("0.5") coerce and render normally.
    #
    # The stderr breadcrumb preserves diagnosability: the old crash at
    # least left "render error: ..." on stderr (visible in Claude
    # Code's debug logs), whereas a silent hide would leave a user
    # debugging "my cost chip vanished" with nothing. present-but-
    # garbage is the ONLY case that notes; absent stays silent.
    def _num_or_note(field, raw):
        num = _safe_num(raw)
        if num is None and raw is not None:
            print(
                "claude-status: ignoring non-numeric {} value".format(field),
                file=sys.stderr,
            )
        return num

    out["cost"] = _num_or_note(
        "cost", _first(cost_obj.get("total_cost_usd"), data.get("cost_usd")))
    out["duration"] = _num_or_note(
        "duration",
        _first(cost_obj.get("total_duration_ms"), data.get("session_duration_ms")))
    out["api_duration"] = _num_or_note(
        "api_duration",
        _first(cost_obj.get("total_api_duration_ms"), data.get("api_duration_ms")))
    out["lines_added"] = _first(cost_obj.get("total_lines_added"), data.get("lines_added"))
    out["lines_removed"] = _first(cost_obj.get("total_lines_removed"), data.get("lines_removed"))

    # Per-category cost breakdown (Claude Code v2.1.150+ exposes
    # `cost.by_category` with keys like "skills", "subagents",
    # "plugins", per-MCP-server costs). We extract the largest
    # non-base category for the `cost_breakdown` section. The whole
    # dict is preserved on `n` for callers that want richer rendering.
    by_category = cost_obj.get("by_category")
    if isinstance(by_category, dict):
        # Filter to numeric, positive entries only. Coerce on store
        # via _safe_num so downstream consumers always see Python
        # floats — never the original mixed types (some JSON
        # serializers stringify numeric values, e.g. `{"mcp": "0.5"}`).
        # Without coercion, a renderer-side `isinstance(v, (int, float))`
        # filter would silently drop stringified entries and re-open
        # the ghost-cost suppression failure mode the v0.6.1 sum
        # fallback was meant to close.
        sane_categories = {}
        for k, v in by_category.items():
            if not isinstance(k, str):
                continue
            num = _safe_num(v)
            # Defense-in-depth: since v0.11.0 _safe_num itself rejects
            # nan/±inf (returns None), so this explicit isfinite is
            # redundant — but it stays because this exact hole (a
            # stringified `"inf"` coercing to float('inf'), passing
            # `num > 0`, and rendering an infinite total via the
            # sum-fallback) was opened and had to be re-guarded within
            # a single release (v0.6.1, caught pre-release), and the
            # local guard pins the contract at this boundary even if
            # _safe_num's semantics ever loosen again.
            if num is None or not math.isfinite(num) or num <= 0:
                continue
            sane_categories[k] = float(num)
        out["cost_by_category"] = sane_categories
        if sane_categories:
            top_name, top_value = max(sane_categories.items(), key=lambda kv: kv[1])
            out["cost_top_category_name"] = top_name
            out["cost_top_category_value"] = top_value
        else:
            out["cost_top_category_name"] = None
            out["cost_top_category_value"] = None
    else:
        out["cost_by_category"] = {}
        out["cost_top_category_name"] = None
        out["cost_top_category_value"] = None

    # Repository identity and current-PR info from stdin.
    #
    # Two stdin payload shapes are accepted, with truthy-value
    # precedence (the newer shape wins ONLY when populated, so an
    # empty `pr: {}` falls through to the older shape):
    #
    #   - pr.{number, url, review_state} + workspace.repo.{host, owner,
    #     name}: shape observed in live statusline payloads as of
    #     2026-06-04. Populated PR data here wins.
    #   - github.{pr_number, pr_url, repo}: observed in Claude Code
    #     2.1.148+ payloads as of 2026-05-24 (when v0.6.1's `pr`
    #     section was added). Read as a fallback so users on Claude
    #     Code releases still emitting this shape don't lose the PR
    #     badge mid-migration.
    #
    # The normalized output keys (`github_repo`, `github_pr_url`,
    # `github_pr_number`) are intentionally kept stable from v0.6.1 so
    # any custom-theme consumer or downstream caller depending on
    # those names continues to work. The keys describe what claude-
    # status STORES, not which upstream namespace they came from.
    #
    # pr.review_state is captured here and rendered by the `pr` section
    # (see _PR_REVIEW_DISPLAY and the section == "pr" block in
    # _render_sections). v0.6.3 added the capture and deferred the
    # rendering; v0.8.0 landed the renderer without re-touching this
    # normalize block.
    pr_obj = data.get("pr")
    pr_obj = pr_obj if isinstance(pr_obj, dict) else {}
    github_obj = data.get("github")
    github_obj = github_obj if isinstance(github_obj, dict) else {}

    # PR number: same int/string coercion and implausibly-large cap
    # (>=7 digits would dominate Line 2 width and probably indicate
    # corrupted upstream data; GitHub's largest known PR numbers as
    # of 2026 are in the 200k range). Applied uniformly to both
    # namespaces via this small helper so the cap can't drift.
    def _clean_pr_number(raw):
        # Int-coerce BEFORE bounds-checking — a float like 0.5 would
        # pass `0 < num < 1_000_000` and then truncate to 0, storing
        # an invalid PR number. Int the value first so the bound
        # check sees the final stored value.
        num = _safe_num(raw)
        if num is None:
            return None
        try:
            num_int = int(num)
        except (TypeError, ValueError, OverflowError):
            return None
        if not (0 < num_int < 1_000_000):
            return None
        return num_int

    pr_num = _clean_pr_number(pr_obj.get("number"))
    if pr_num is None:
        pr_num = _clean_pr_number(github_obj.get("pr_number"))
    out["github_pr_number"] = pr_num

    # PR URL: must be a non-empty string in either namespace.
    def _clean_pr_url(raw):
        return raw if isinstance(raw, str) and raw else None

    out["github_pr_url"] = (
        _clean_pr_url(pr_obj.get("url"))
        or _clean_pr_url(github_obj.get("pr_url"))
    )

    # Review state: membership-checked against the documented enum so a
    # malformed value never reaches the renderer. Rendered by the `pr`
    # section via _PR_REVIEW_DISPLAY.
    #
    # `.lower()` parity with `effort.level` / `effortLevel`: the
    # documented values are lowercase (`approved`, `pending`, etc.)
    # but normalizing before the membership check keeps us robust if
    # an upstream variant ever sends a different case.
    raw_review = pr_obj.get("review_state")
    if isinstance(raw_review, str):
        review_lower = raw_review.lower()
        out["pr_review_state"] = (
            review_lower if review_lower in _PR_REVIEW_STATES else None
        )
    else:
        out["pr_review_state"] = None

    # Repo identity: the workspace.repo shape composes host/owner/name
    # explicitly; the github.repo shape is a single "owner/name"
    # string. Both reduce to the `github_repo` field (kept stable
    # from v0.6.1) as `owner/name`. Host is captured separately for
    # future rendering but not currently surfaced.
    # isinstance guard handles non-dict `workspace` (the same shape
    # of bug the dedicated workspace block below now also defends
    # against). Without it, `workspace: "/path"` (string) would
    # crash here on .get("repo").
    _ws_obj = data.get("workspace")
    _ws_obj = _ws_obj if isinstance(_ws_obj, dict) else {}
    workspace_repo = _ws_obj.get("repo")
    workspace_repo = workspace_repo if isinstance(workspace_repo, dict) else {}
    ws_owner = workspace_repo.get("owner")
    ws_name = workspace_repo.get("name")
    if (isinstance(ws_owner, str) and ws_owner
            and isinstance(ws_name, str) and ws_name):
        out["github_repo"] = "{}/{}".format(ws_owner, ws_name)
    else:
        raw_repo = github_obj.get("repo")
        out["github_repo"] = (
            raw_repo if isinstance(raw_repo, str) and raw_repo else None
        )
    raw_host = workspace_repo.get("host")
    out["github_repo_host"] = (
        raw_host if isinstance(raw_host, str) and raw_host else None
    )

    # Vim (nested or flat). Same isinstance guard as agent / worktree
    # / cost below — without it, an upstream sending `vim: "NORMAL"`
    # as a string (or any non-dict) would crash _normalize with
    # AttributeError on .get(). Flagged by Gemini on PR #90 as the
    # same bug pattern fixed for the other three sections; adopting
    # here for consistency.
    vim_obj = data.get("vim")
    vim_obj = vim_obj if isinstance(vim_obj, dict) else {}
    out["vim_mode"] = vim_obj.get("mode") or data.get("vim_mode")

    # Agent (nested or flat). The isinstance guard prevents an
    # upstream sending `agent: "Explore"` as a string (or list/int)
    # from crashing _normalize with AttributeError on .get(). Same
    # defensive pattern as `rate_limits` below. The flat
    # `agent_name` fallback handles demo mode and older schemas.
    #
    # Both branches require non-EMPTY strings to consider a value
    # "real." Empty string from nested must NOT block the flat
    # fallback — otherwise a buggy upstream emitting `agent.name=""`
    # would silently lose a user who has flat `agent_name` set.
    agent_obj = data.get("agent")
    agent_obj = agent_obj if isinstance(agent_obj, dict) else {}
    nested_name = agent_obj.get("name")
    flat_name = data.get("agent_name")

    def _real_str(v):
        return v if isinstance(v, str) and v else None

    out["agent_name"] = _real_str(nested_name) or _real_str(flat_name)

    # Worktree (nested or flat) — same isinstance guard.
    wt_obj = data.get("worktree")
    wt_obj = wt_obj if isinstance(wt_obj, dict) else {}
    out["worktree_branch"] = wt_obj.get("branch") or data.get("worktree_branch")
    out["worktree_name"] = wt_obj.get("name")

    # Git branch
    out["git_branch"] = data.get("git_branch")

    # Project name: prefer workspace.project_dir (explicit project root),
    # fall back to last folder of current_dir / cwd
    # isinstance guard for the same reason agent/cost/vim/github get
    # one in v0.6.1: an upstream sending `workspace` as a non-dict
    # (string, list, int) would crash the subsequent .get() calls
    # with AttributeError. v0.6.1 missed this site; v0.6.3 completes
    # the pattern across _normalize.
    workspace = data.get("workspace")
    workspace = workspace if isinstance(workspace, dict) else {}
    project_dir = workspace.get("project_dir") or ""
    cwd = workspace.get("current_dir") or data.get("cwd") or ""
    best_path = project_dir or cwd
    out["project_name"] = os.path.basename(os.path.normpath(best_path)) if best_path else ""

    # Model info
    model_obj = data.get("model") or {}
    out["model_name"] = model_obj.get("display_name")

    # Session ID (for tool call counting)
    out["session_id"] = data.get("session_id") or ""

    # Transcript path (for live activity counter — tool calls since
    # the most recent user message). Stored only if it's a non-empty
    # string; downstream readers tolerate missing/invalid paths and
    # silently render no activity section, per the degrade-gracefully
    # pattern.
    transcript = data.get("transcript_path")
    out["transcript_path"] = transcript if isinstance(transcript, str) else ""

    # Session name (custom name via --name or /rename)
    out["session_name"] = data.get("session_name") or ""

    # Claude Code version
    out["cc_version"] = data.get("version") or ""

    # Rate limits (Pro/Max only, added in Claude Code v2.1.80).
    rl = data.get("rate_limits")
    rl = rl if isinstance(rl, dict) else {}
    five_h = rl.get("five_hour")
    five_h = five_h if isinstance(five_h, dict) else {}
    seven_d = rl.get("seven_day")
    seven_d = seven_d if isinstance(seven_d, dict) else {}
    # resets_at is Unix epoch seconds per Claude Code docs — convert to ms
    # for fmt_countdown() which expects milliseconds.
    #
    # Upstream bug guard (anthropics/claude-code#52326, still open):
    # on a fresh 5h/7d window with no usage data yet, Claude Code
    # returns the resets_at epoch timestamp (~1.7e9) in
    # used_percentage instead of 0/null. Without this guard, our
    # downstream clamp(0, 100) silently turns it into a false
    # `5h:100% (red)` alarm on every fresh session for Pro/Max
    # users.
    #
    # Threshold = 1e6: epoch seconds (~1.7e9) are 7+ orders of
    # magnitude above any plausible percentage, so this catches the
    # bug pattern with zero risk of false positives. We deliberately
    # do NOT use `> 100`: Anthropic could legitimately ship an
    # "overage" indicator above 100% in the future, and pre-emptively
    # hiding any value 101-999999 would silently swallow it. Values
    # in the legitimate-but-out-of-spec range (e.g. 105) still flow
    # through to the renderer's existing clamp(0, 100) at the
    # rate_limits section, so they show as `5h:100% (red)` — which
    # IS the correct UI for "user is maxed out beyond 100%".
    for period, rl_dict in [("5h", five_h), ("7d", seven_d)]:
        pct = _safe_num(rl_dict.get("used_percentage"))
        if pct is not None and pct >= 1e6:
            pct = None
        out["rate_limit_{}_pct".format(period)] = pct
        resets_sec = _safe_num(rl_dict.get("resets_at"))
        out["rate_limit_{}_resets".format(period)] = (
            resets_sec * 1000 if resets_sec is not None else None
        )

    # Output style
    style_obj = data.get("output_style")
    style_obj = style_obj if isinstance(style_obj, dict) else {}
    style_name = style_obj.get("name")
    out["output_style"] = style_name if isinstance(style_name, str) and style_name else ""

    # Added directories count
    added_dirs = workspace.get("added_dirs")
    out["added_dirs_count"] = len(added_dirs) if isinstance(added_dirs, list) else 0

    # Native git worktree indicator (v2.1.97+)
    out["git_worktree"] = bool(workspace.get("git_worktree"))

    # Effort level (Claude Code v2.1.119+ exposes this in stdin JSON
    # under data["effort"]["level"]). When present and valid, it is
    # the authoritative source — updates within one render cycle of
    # `/effort xhigh` instead of waiting up to 30s for the
    # settings.json cache to expire. When absent (older Claude Code,
    # demo mode, custom statuslines), the renderer falls back to
    # get_effort_level() which reads ~/.claude/settings.json.
    #
    # Validation against _VALID_EFFORT_LEVELS rejects malformed
    # stdin payloads (e.g. effort.level: 42 or "ultrathink") so the
    # renderer never sees garbage. "medium" is dropped here because
    # it's the default and we hide that section by contract.
    #
    # _canonical_effort() applies the silent alias `ultra` -> `xhigh`
    # at this layer too: even if a future Claude Code build emits
    # `effort.level: "ultra"` on stdin, we render `effort:xhigh` to
    # match the documented enum. Mirror to disk uses the canonical
    # value so we never WRITE `ultra` into the cache again — over
    # time the alias becomes a read-only compatibility path for
    # older on-disk caches.
    effort_obj = data.get("effort")
    effort_obj = effort_obj if isinstance(effort_obj, dict) else {}
    raw_effort = effort_obj.get("level")
    if isinstance(raw_effort, str):
        normalized = raw_effort.lower()
        if normalized in _VALID_EFFORT_LEVELS:
            canonical = _canonical_effort(normalized)
            # Stdin is the authoritative source — even "medium" is an
            # explicit user choice we must honor. We use the empty
            # string as a sentinel for "explicitly medium / hide
            # section": it satisfies the renderer's `is not None`
            # check (so the fallback to settings.json is skipped) but
            # is falsy for the `if effort:` check (so the section
            # hides). Without this, stdin medium would fall through
            # to the 30s settings.json cache and the user could see
            # a stale non-medium value for up to 30s after running
            # `/effort medium`.
            if canonical == "medium":
                out["effort_level"] = ""
            else:
                out["effort_level"] = canonical
            # Mirror to the on-disk cache so a later render that lacks
            # stdin effort (older Claude Code, mid-session client
            # switch, demo) sees the most recent authoritative value
            # via the get_effort_level() fallback instead of a stale
            # entry from before the user's last `/effort` change.
            # Read-then-compare avoids the disk write on every render
            # when the value is unchanged (cheap stat+read vs. atomic
            # write+rename on every render cycle). Best-effort: cache
            # failures must never break render.
            try:
                cached = _read_cache("effort_level")
                if cached is None or cached.get("effort") != canonical:
                    _write_cache("effort_level", {"effort": canonical})
            except Exception:
                pass
        else:
            out["effort_level"] = None
    else:
        out["effort_level"] = None

    # Extended-thinking state (thinking.enabled, documented stdin field).
    # Stored as a STRICT bool — `is True` collapses every input to exactly
    # True or False, so the renderer never sees None:
    #   enabled is True            -> True   (render the section)
    #   enabled False / absent /
    #     non-bool / non-dict      -> False  (hide)
    # We only surface the affirmative case — an "off" indicator would be
    # noise on every non-thinking session, so the "explicitly off" and
    # "field missing" inputs deliberately collapse to the same hidden
    # state. isinstance(dict) guard mirrors every other nested-object read
    # in _normalize so a malformed `thinking: "yes"` (string) can't crash.
    # Strict `is True` rather than truthiness so a stray non-bool like
    # `enabled: 1` does not masquerade as the documented boolean.
    thinking_obj = data.get("thinking")
    thinking_obj = thinking_obj if isinstance(thinking_obj, dict) else {}
    out["thinking_enabled"] = thinking_obj.get("enabled") is True

    return out


def _render_sections(n, order, theme):
    """Render a list of section names into formatted strings.

    Args:
        n: Normalized data dict.
        order: List of section name strings.
        theme: Theme dict.

    Returns:
        List of rendered section strings (rendered text only). Skips
        sections whose data is absent. Use _render_sections_named()
        when the caller needs to know which name produced each string
        (e.g. for width-aware fitting).
    """
    return [r for _, r in _render_sections_named(n, order, theme)]


def _render_sections_named(n, order, theme):
    """Render sections, returning (name, rendered) pairs.

    Same logic as _render_sections() but preserves the section name
    alongside each rendered string. Used by render() to drive
    _fit_to_width(), which needs to know which sections it can drop.
    """
    # `_NamedAppender` lets the existing `sections.append(...)` calls below
    # remain unchanged while transparently pairing each appended string with
    # the current section name. Avoids a wide-touch refactor of every append
    # site in this function. The guard in `append` prevents items being
    # silently tagged with `None` if a future change moves an append outside
    # the loop — `None`-tagged items are undroppable by _fit_to_width and
    # would silently overflow the line.
    class _NamedAppender:
        __slots__ = ("items", "current")
        def __init__(self):
            self.items = []
            self.current = None
        def append(self, value):
            if self.current is None:
                raise RuntimeError(
                    "_NamedAppender.append called without a current section "
                    "name — every append must follow `sections.current = section`"
                )
            self.items.append((self.current, value))

    sections = _NamedAppender()
    tc = theme["colors"]

    input_tokens = n["input_tokens"]
    output_tokens = n["output_tokens"]
    cache_read = n["cache_read"]
    cache_create = n["cache_create"]
    cost = n["cost"]
    duration = n["duration"]
    lines_added = n["lines_added"]
    lines_removed = n["lines_removed"]
    context_size = n["context_size"]
    vim_mode = n["vim_mode"]
    agent_name = n["agent_name"]
    worktree_branch = n["worktree_branch"]
    model_name = n["model_name"]
    api_duration = n["api_duration"]
    pct = n["used_percentage"]

    total_input = (input_tokens or 0) + (cache_read or 0) + (cache_create or 0)
    total_tokens = (input_tokens or 0) + (output_tokens or 0) + (cache_read or 0) + (cache_create or 0)

    for section in order:
        sections.current = section
        if section == "bar" and pct is not None:
            compaction = get_compaction_threshold()
            bar_width = theme.get("bar_width", 20)
            sections.append(render_bar(pct, bar_width, theme, compaction))

        elif section == "tokens" and (input_tokens is not None or output_tokens is not None):
            inp = fmt_tokens(input_tokens)
            out = fmt_tokens(output_tokens)
            sections.append(
                colorize("in:", tc["label"]) + colorize(inp, tc["value"]) + " "
                + colorize("out:", tc["label"]) + colorize(out, tc["value"])
            )

        elif section == "cache":
            # Hidden when any token component was present-but-garbage
            # (token_fields_corrupt): the ratio sums components with an
            # absent-means-0 rule, and silently zeroing a component
            # upstream DID send renders a confidently-wrong hit-rate
            # (60% inflating to 90% with no visible cue — reproduced
            # in review). An honest absence beats a plausible lie.
            if not n.get("token_fields_corrupt"):
                cache_str = fmt_cache_pct(cache_read, total_input)
                if cache_str:
                    sections.append(
                        colorize("cache:", tc["label"]) + colorize(cache_str, GREEN)
                    )

        elif section == "cost" and cost is not None:
            sections.append(colorize(fmt_cost(cost), tc["cost"]))

        elif section == "cost_breakdown":
            # Cost-category breakdown from `cost.by_category`
            # (Claude Code v2.1.150+). Three render paths:
            #
            # 1. Largest single category >= $0.01 — render its name
            #    and value (e.g., `mcp:$0.18`). Most useful when one
            #    category dominates spend.
            # 2. All categories below $0.01 but sum >= $0.01 —
            #    render `other:$SUM` (e.g., 10 MCP servers each at
            #    half a cent = $0.05 total). Prevents the silent
            #    "your money is being spent but we hide every line
            #    item" failure mode.
            # 3. No data present OR sum below threshold — section
            #    hides entirely. A noise-suppression contract: we
            #    surface $0.001 nowhere.
            top_name = n.get("cost_top_category_name")
            top_value = n.get("cost_top_category_value")
            # _first() rather than chained .get() defaults so that a
            # custom theme explicitly setting `cost_breakdown: null`
            # falls through to `cost` then to YELLOW, rather than
            # passing None to colorize(). (str(None) is the string
            # "None" — would render visibly broken output.)
            cb_color = _first(tc.get("cost_breakdown"), tc.get("cost"), YELLOW)
            if top_name and top_value is not None and top_value >= 0.01:
                sections.append(
                    colorize("{}:".format(top_name), tc["label"])
                    + colorize(fmt_cost(top_value), cb_color)
                )
            else:
                # Sum-fallback: even if no single category meets the
                # threshold, the cumulative spend can. Hide if sum
                # also below threshold (signal:noise contract).
                #
                # `_normalize` guarantees every value in
                # `cost_by_category` is already a coerced float
                # (stringified upstream values are converted at
                # normalization time, not filtered out here). The
                # isinstance check is kept as defense-in-depth: if a
                # future caller bypasses _normalize and pushes a
                # non-numeric value into `cost_by_category`, sum()
                # would raise TypeError without it.
                by_cat = n.get("cost_by_category") or {}
                total = sum(v for v in by_cat.values() if isinstance(v, (int, float)))
                if total >= 0.01:
                    sections.append(
                        colorize("other:", tc["label"])
                        + colorize(fmt_cost(total), cb_color)
                    )

        elif section == "pr":
            # GitHub PR context (Claude Code v2.1.148+). Renders the
            # PR number as a clickable link to pr_url when available;
            # falls back to plain text. Hidden when no PR is detected.
            pr_number = n.get("github_pr_number")
            pr_url = n.get("github_pr_url")
            if pr_number:
                # _first() rather than .get() default so a custom
                # theme that explicitly sets `pr: null` falls through
                # to CYAN rather than passing None to colorize().
                pr_color = _first(tc.get("pr"), CYAN)
                pr_text = colorize("PR#{}".format(pr_number), pr_color)
                if pr_url:
                    pr_text = _osc8_link(pr_url, pr_text)

                # Review state (pr.review_state, captured since v0.6.3,
                # rendered here). A short ASCII token rather than an
                # emoji glyph keeps it width-1-per-char and renders in
                # every terminal — same conservative choice the project
                # makes elsewhere. Appended OUTSIDE the OSC 8 link so
                # the clickable target stays exactly "PR#N" and the
                # state reads as an adjacent annotation.
                #
                # _normalize gates the value against _PR_REVIEW_STATES,
                # and TestPRReviewState asserts that set equals the
                # _PR_REVIEW_DISPLAY keys — so today every value that
                # reaches us is a valid map key. The lookup still uses
                # .get() (not a bare subscript) as defense-in-depth: if a
                # future state were ever added to one set but not the
                # other, an unmapped value degrades to a bare "PR#N"
                # (this section) rather than raising KeyError and taking
                # down the WHOLE line. Per-section graceful degradation is
                # the project contract; the sync test stays as the loud
                # signal that catches the desync in CI first.
                review = n.get("pr_review_state")
                entry = _PR_REVIEW_DISPLAY.get(review) if review else None
                if entry:
                    label, default_color = entry
                    state_color = _first(tc.get("pr_review_" + review),
                                         default_color)
                    pr_text = pr_text + " " + colorize(label, state_color)

                sections.append(pr_text)

        elif section == "burn" and total_tokens and duration \
                and not n.get("token_fields_corrupt"):
            # corrupt-gate: same rationale as the cache section — a
            # garbage component silently zeroed in total_tokens would
            # understate the burn rate with no visible cue.
            rate = fmt_burn_rate(total_tokens, duration)
            if rate != "?":
                sections.append(
                    colorize("burn:", tc["label"]) + colorize(rate, tc["value"])
                )

        elif section == "duration" and duration is not None:
            sections.append(colorize(fmt_duration(duration), tc["value"]))

        elif section == "latency" and api_duration is not None:
            lc = tc.get("latency", CYAN)
            sections.append(
                colorize("api:", tc["label"]) + colorize(fmt_duration(api_duration), lc)
            )

        elif section == "speed":
            # corrupt-gate: see the cache section.
            if n.get("token_fields_corrupt"):
                speed_str = ""
            else:
                speed_str = fmt_speed(total_tokens, api_duration)
            if speed_str:
                spc = tc.get("speed", CYAN)
                sections.append(
                    colorize("speed:", tc["label"]) + colorize(speed_str, spc)
                )

        elif section == "cost_rate":
            # Projected session cost per hour, rendered "~$3.6/hr" —
            # the leading tilde signals "projection", not a bill.
            # Session-average including idle time; fmt_cost_rate owns
            # every hide-gate (missing/garbage/NaN inputs, zero cost,
            # sub-minute sessions), so an empty string means hide.
            # Color falls through via _first() so a theme setting
            # `cost_rate: null` degrades to CYAN rather than crashing
            # colorize().
            rate_str = fmt_cost_rate(cost, duration)
            if rate_str:
                crc = _first(tc.get("cost_rate"), CYAN)
                sections.append(colorize("~" + rate_str, crc))

        elif section == "lines":
            lines_str = fmt_lines(lines_added, lines_removed)
            if lines_str:
                parts = []
                if lines_added:
                    parts.append(colorize("+{}".format(lines_added), tc["added"]))
                if lines_removed:
                    parts.append(colorize("-{}".format(lines_removed), tc["removed"]))
                sections.append(" ".join(parts))

        elif section == "branch":
            branch = n["git_branch"] or get_branch()
            if branch:
                bc = tc["branch_main"] if branch in ("main", "master") else tc["branch_feature"]
                project = n.get("project_name", "")
                remote = get_remote_url()
                if project:
                    branch_text = (
                        colorize("\u2387 " + project, CYAN)
                        + colorize("/" + branch, bc)
                    )
                else:
                    branch_text = colorize("\u2387 " + branch, bc)
                # Wrap in clickable link if remote URL available
                if remote:
                    branch_text = _osc8_link(remote, branch_text)
                sections.append(branch_text)

        elif section == "context_size" and context_size:
            # fmt_tokens (not ad-hoc //1000 math) so a 1M window renders
            # "(1M)" rather than "(1000K)". One formatting path for every
            # token-shaped number keeps K/M suffix rules consistent —
            # the old integer-division label predates 1M windows
            # becoming the default. _safe_num rejects non-numeric AND
            # non-finite window sizes (NaN/Infinity are valid to
            # Python's json.loads; _safe_num guarantees a finite float
            # or None since v0.11.0), so nothing garbage reaches int()
            # — renderers must never crash on external JSON.
            cs = _safe_num(context_size)
            if cs:
                sections.append(colorize(
                    "({})".format(fmt_tokens(int(cs))), BRIGHT_BLACK))

        elif section == "context_tokens":
            # Absolute context display "ctx:412K/1M" (#113). At 1M
            # windows a percentage hides magnitude — 40% is ~400K
            # tokens re-billed every turn. The numerator is DERIVED
            # (used_percentage × window size), not read from the token
            # fields: used_percentage is upstream's authoritative
            # fill signal and already drives the bar and !CTX, so
            # deriving keeps this chip arithmetically consistent with
            # the bar beside it (a 42% bar next to a chip reading
            # 41.2% of the window would look like a bug). The
            # input/cache token components are ambiguous as a fill
            # measure — their sum is not the documented fill.
            # Hidden when either signal is missing/garbage. Percentage
            # clamped to [0, 100] (same bounds the bar enforces) so an
            # out-of-spec upstream pct can't render ctx:12M/1M.
            cs = _safe_num(context_size)
            p = _safe_num(pct)
            if cs and cs > 0 and p is not None:
                p = max(0.0, min(100.0, p))
                # round(), not bare int(): float representation error
                # puts e.g. 1_000_000 * 4.1 / 100.0 at 40999.999…, and
                # flooring renders ctx:40K where the exact value is
                # 41K (13 such off-by-a-chip cases verified across
                # 0.1%-step percentages at a 1M window).
                # _first() for the color so a custom theme setting
                # `context_tokens: null` degrades to the default
                # instead of crashing colorize() (house convention).
                ctc = _first(tc.get("context_tokens"), BRIGHT_BLACK)
                sections.append(colorize(
                    "ctx:{}/{}".format(fmt_tokens(int(round(cs * p / 100.0))),
                                       fmt_tokens(int(cs))), ctc))

        elif section == "ctx_warning":
            # Percentage-based warning — works for any context window size
            if pct is not None and pct >= CTX_WARNING_THRESHOLD_PCT:
                sections.append(colorize("!CTX", BRIGHT_RED, BOLD))

        elif section == "vim" and vim_mode:
            vc = tc["vim_normal"] if vim_mode.upper() == "NORMAL" else tc["vim_insert"]
            sections.append(colorize(vim_mode.upper(), vc, BOLD))

        elif section == "agent" and agent_name:
            sections.append(colorize("[{}]".format(agent_name), tc["agent"]))

        elif section == "worktree" and worktree_branch:
            sections.append(colorize("wt:" + worktree_branch, YELLOW))

        elif section == "model" and model_name:
            # Newer Claude Code builds send the RAW model id as
            # display_name (observed: "claude-opus-5"), where older
            # ones sent friendly names ("Opus 4.8 (1M context)").
            # Shorten only the raw-id shape — _short_model dash-splits
            # and title-cases, so applying it to a friendly name would
            # mangle it ("(1M context)" -> "(1M Context)"). The
            # `claude-` prefix is the discriminator; everything else
            # renders byte-identical to before (#120).
            display = model_name
            if isinstance(display, str) and display.startswith("claude-"):
                # cap=None: the main line must never truncate a model
                # name mid-token. _fit_to_width drops the whole
                # section cleanly when it doesn't fit, and a capped
                # name would hide variant markers ("…-preview") the
                # user relies on.
                display = _short_model(display, cap=None) or model_name
            mc = tc.get("model", BRIGHT_MAGENTA)
            sections.append(colorize(display, mc))

        elif section == "git_state":
            branch = n["git_branch"] or get_branch()
            if branch:
                state = get_git_state()
                if state:
                    if state == "conflict":
                        sc = tc.get("git_conflict", BRIGHT_RED)
                    else:
                        sc = tc.get("git_merge", YELLOW)
                    sections.append(colorize(state, sc, BOLD))

        elif section == "commit_age":
            branch = n["git_branch"] or get_branch()
            if branch:
                age_ms = get_last_commit_age_ms()
                if age_ms is not None:
                    cac = tc.get("commit_age", BRIGHT_BLACK)
                    sections.append(
                        colorize("last:", tc["label"])
                        + colorize(fmt_duration(age_ms), cac)
                    )

        elif section == "tools":
            session_id = n.get("session_id", "")
            if session_id:
                tool_count = get_session_tool_count(session_id)
                if tool_count > 0:
                    sections.append(
                        colorize("tools:", tc["label"])
                        + colorize(str(tool_count), tc["value"])
                    )

        elif section == "activity":
            # Live tool-call counter for the current assistant turn
            # (since the most recent user message). Differs from
            # `tools` (above) which is a session-cumulative count.
            # Reads the tail of transcript_path; cached 5s; hidden
            # when zero so the section is invisible during idle.
            transcript = n.get("transcript_path", "")
            if transcript:
                act_count = get_session_activity_count(transcript)
                if act_count > 0:
                    act_color = tc.get("activity", CYAN)
                    sections.append(
                        colorize("act:", tc["label"])
                        + colorize(str(act_count), act_color)
                    )

        elif section == "cache_age":
            # Time since the most recent assistant message (#92) — a cue
            # for how long a task has been running / whether the ~5-min
            # prompt cache is still warm. Reads the transcript tail via
            # the same cached, path-validated reader as `activity`.
            #
            # We recompute the age from the (cached) timestamp against
            # the current clock on every render, so the displayed value
            # stays live-to-the-second even though the transcript read
            # itself is cached for 5s. Past _CACHE_AGE_WARN_MS the chip
            # switches to a warning color (cache likely cold).
            #
            # Hidden when: no transcript, no assistant message in the
            # tail (ts None), or the age is negative — a future-dated
            # timestamp (clock skew between the machine that wrote the
            # transcript and this render) would otherwise produce a
            # nonsense `cache_age:-3s`, so we suppress rather than show
            # it. Color falls through via _first() so a theme setting
            # `cache_age`/`cache_age_warn` to null degrades gracefully.
            transcript = n.get("transcript_path", "")
            if transcript:
                ts_ms = get_last_assistant_timestamp_ms(transcript)
                if ts_ms is not None:
                    age_ms = int(time.time() * 1000) - ts_ms
                    if age_ms >= 0:
                        if age_ms >= _CACHE_AGE_WARN_MS:
                            cagec = _first(tc.get("cache_age_warn"), YELLOW)
                        else:
                            cagec = _first(tc.get("cache_age"), BRIGHT_BLACK)
                        sections.append(
                            colorize("cache_age:", tc["label"])
                            + colorize(fmt_duration(age_ms), cagec)
                        )

        elif section == "sessions":
            count = get_today_session_count()
            if count > 0:
                sc = tc.get("sessions", CYAN)
                sections.append(
                    colorize("sessions:", tc["label"])
                    + colorize(str(count), sc)
                )

        elif section == "budget":
            # v0.12.0: the numerator is TODAY'S spend across all
            # sessions on this machine (per-session ledger files under
            # the user cache dir), matching the config key's own name
            # (daily_budget_usd) and the README's long-standing "daily
            # budget tracker" promise. Pre-v0.12.0 this compared the
            # SESSION cost against the DAILY budget — five $3 sessions
            # against a $10/day budget each showed a green 30% while
            # the day was 150% over.
            #
            # The "day:" label prefix is deliberate and load-bearing:
            # it announces the semantic change at upgrade, and it
            # permanently disambiguates this chip from the adjacent
            # per-session `cost` chip (two unexplained disagreeing
            # dollar figures would read as a bug).
            #
            # There is NO fallback mode. The total is always the ledger
            # sum (the writer runs first, so the live session is always
            # included when it has a cost); an empty or unreachable
            # ledger degrades to the live session's cost rendered as an
            # HONEST partial day total under the same label — the
            # meaning never switches, only completeness degrades.
            # Escape hatch: budget_scope "session" restores the old
            # per-session chip (no prefix) for users who calibrated
            # daily_budget_usd as a per-session ceiling.
            budget = get_budget_config()
            if budget is not None and budget > 0:
                if get_budget_scope() == "session":
                    shown = cost  # None -> hidden below
                    prefix = ""
                else:
                    session_id = n.get("session_id", "")
                    # record_and_get_daily_spend ALWAYS folds the live
                    # session's contribution in (in memory when the sid
                    # is unusable or the write fails), so found=True
                    # covers every case where there is any daily signal
                    # — no separate lower-bound branch needed here, and
                    # none is wanted: a cli-side "show raw cost" backup
                    # would over-attribute midnight-spanning sessions.
                    total, found = record_and_get_daily_spend(
                        session_id, cost, duration)
                    shown = total if found else None
                    prefix = "day:"
                if shown is not None:
                    pct_used = (shown / budget) * 100
                    if pct_used >= 90:
                        bc = BRIGHT_RED
                    elif pct_used >= 70:
                        bc = YELLOW
                    else:
                        bc = GREEN
                    # Format budget as clean dollar amount (no trailing .0)
                    if budget == int(budget):
                        budget_str = "${}".format(int(budget))
                    else:
                        budget_str = fmt_cost(budget)
                    label = "{}{}/{}".format(prefix, fmt_cost(shown), budget_str)
                    sections.append(colorize(label, bc, BOLD))

        elif section == "version":
            vc = tc.get("version", BRIGHT_BLACK)
            sections.append(colorize("v" + __version__, vc))

        elif section == "clock":
            cc = tc.get("clock", BRIGHT_BLACK)
            sections.append(colorize(time.strftime("%H:%M"), cc))

        elif section == "cc_version":
            cc_ver = n.get("cc_version", "")
            if cc_ver:
                cvc = tc.get("cc_version", BRIGHT_BLACK)
                sections.append(colorize("CC:" + cc_ver, cvc))

        elif section == "session_name":
            sname = n.get("session_name", "")
            if sname:
                snc = tc.get("session_name", CYAN)
                sections.append(colorize(
                    "\u2726 {}".format(sname), snc
                ))

        elif section == "rate_limits":
            rl_5h = n.get("rate_limit_5h_pct")
            rl_7d = n.get("rate_limit_7d_pct")
            if rl_5h is not None or rl_7d is not None:
                parts = []
                nearest_reset = None
                for label, pct_val, resets_at in [
                    ("5h", rl_5h, n.get("rate_limit_5h_resets")),
                    ("7d", rl_7d, n.get("rate_limit_7d_resets")),
                ]:
                    if pct_val is not None:
                        clamped = max(0, min(100, pct_val))
                        if clamped >= 85:
                            rc = tc.get("rate_limit_danger", BRIGHT_RED)
                        elif clamped >= 60:
                            rc = tc.get("rate_limit_warn", YELLOW)
                        else:
                            rc = tc.get("rate_limit_ok", GREEN)
                        parts.append(colorize(
                            "{}:{}%".format(label, int(clamped)), rc
                        ))
                    if resets_at is not None:
                        if nearest_reset is None or resets_at < nearest_reset:
                            nearest_reset = resets_at
                countdown = fmt_countdown(nearest_reset)
                if countdown:
                    parts.append(colorize(countdown, BRIGHT_BLACK))
                if parts:
                    sections.append(" ".join(parts))

        elif section == "output_style":
            style = n.get("output_style", "")
            if style:
                osc = tc.get("output_style", BRIGHT_BLACK)
                sections.append(colorize("style:" + style, osc))

        elif section == "added_dirs":
            dirs_count = n.get("added_dirs_count", 0)
            if dirs_count > 0:
                adc = tc.get("added_dirs", BRIGHT_BLACK)
                sections.append(colorize(
                    "dirs:+{}".format(dirs_count), adc
                ))

        elif section == "git_worktree":
            if n.get("git_worktree"):
                gwtc = tc.get("git_worktree", YELLOW)
                sections.append(colorize("gwt", gwtc))

        elif section == "effort":
            # Prefer stdin-supplied effort.level (Claude Code v2.1.119+,
            # set by _normalize). Falls back to settings.json read for
            # older Claude Code versions and demo mode. Stdin source
            # updates within one render cycle of `/effort xhigh` instead
            # of waiting for the 30s settings.json cache to expire.
            #
            # Tri-state semantics from _normalize:
            #   None → "no stdin signal at all" → fall back to
            #          get_effort_level() (settings.json with cache)
            #   ""   → "explicitly medium / hide section" → skip
            #          fallback (do NOT read stale settings.json), use
            #          empty string which fails the `if effort:` test
            #          below, hiding the section
            #   str  → "user chose this level" → use directly
            #
            # `is not None` is the correct check (not `or`) — empty
            # string IS a meaningful signal we must honor.
            stdin_effort = n.get("effort_level")
            effort = stdin_effort if stdin_effort is not None else get_effort_level()
            if effort:
                # xhigh / max are the top tiers. The `ultra` branch
                # below is RETAINED DEAD SURFACE — `_canonical_effort()`
                # in sessions.py rewrites `ultra` to `xhigh` at every
                # _normalize / get_effort_level entry point, so this
                # branch (and the `effort_ultra` color keys in all 8
                # themes) is unreachable in practice. Kept so a
                # hypothetical future Claude Code release that did
                # re-introduce a distinct `ultra` stored value would
                # reactivate it rather than require reintroduction.
                # Do not delete in a routine cleanup; see CHANGELOG
                # v0.6.3 for context.
                #
                # Color fall-through uses _first() (not nested .get)
                # so themes that explicitly set the key to None don't
                # crash colorize().
                if effort == "ultra":
                    ec = _first(tc.get("effort_ultra"),
                                tc.get("effort_max"),
                                tc.get("effort_xhigh"),
                                tc.get("effort_high"),
                                BRIGHT_MAGENTA)
                elif effort == "max":
                    ec = _first(tc.get("effort_max"),
                                tc.get("effort_xhigh"),
                                tc.get("effort_high"),
                                BRIGHT_MAGENTA)
                elif effort == "xhigh":
                    ec = _first(tc.get("effort_xhigh"),
                                tc.get("effort_high"),
                                BRIGHT_MAGENTA)
                elif effort == "high":
                    ec = _first(tc.get("effort_high"), BRIGHT_MAGENTA)
                else:
                    ec = _first(tc.get("effort_low"), BRIGHT_BLACK)
                sections.append(colorize(
                    "effort:" + effort, ec, BOLD
                ))

        elif section == "thinking":
            # Extended-thinking indicator (thinking.enabled, documented
            # stdin field). _normalize reduces the field to a strict
            # bool in n["thinking_enabled"]; we render ONLY when True —
            # an "off" badge would clutter every non-thinking session.
            # Pairs naturally with `effort`; both describe how the model
            # is reasoning this session. Color falls through via _first()
            # so a theme setting `thinking: null` degrades to BRIGHT_MAGENTA
            # rather than crashing colorize().
            if n.get("thinking_enabled"):
                thc = _first(tc.get("thinking"), BRIGHT_MAGENTA)
                sections.append(colorize("think", thc, BOLD))

        elif section == "git_extras":
            branch = n["git_branch"] or get_branch()
            if branch:
                extras = get_git_extras()
                parts = []
                if extras.get("stash", 0) > 0:
                    parts.append(colorize(
                        "stash:{}".format(extras["stash"]),
                        tc.get("git_stash", YELLOW)
                    ))
                ahead = extras.get("ahead", 0)
                behind = extras.get("behind", 0)
                if ahead or behind:
                    sync_parts = []
                    if ahead:
                        sync_parts.append("+{}".format(ahead))
                    if behind:
                        sync_parts.append("-{}".format(behind))
                    sc = tc.get("git_sync", BRIGHT_BLACK)
                    parts.append(colorize(
                        "sync:" + "/".join(sync_parts), sc
                    ))
                if parts:
                    sections.append(" ".join(parts))

    return sections.items


# Responsive layout breakpoints (in terminal columns).
#
# These are the COARSE pre-filter thresholds — render() applies a
# precise width-aware fit (_fit_to_width) on top of this, dropping
# low-priority sections one at a time until each line fits the actual
# terminal width.
#
# History: thresholds were originally 120/80, then raised to 230/100
# in v0.5.3 (#70) because Line 2 could reach ~225 visible chars in the
# worst case and Claude Code's Ink TUI truncates Line 2 when Line 1
# overflows. The 230 threshold was overly conservative — it meant
# almost every real terminal (120-200 cols) lost ~19 sections at once.
# Lowered to 150/100 once the precise stage was added: above 150 cols,
# all sections are eligible and the precise stage trims as needed.
# Below 150 we still pre-filter the heaviest sections so we don't pay
# the cost of rendering them (git subprocess calls, file scans for
# tools/sessions, etc.) on terminals where they'll never fit anyway.
_FULL_LAYOUT_MIN_COLS = 150
_COMPACT_LAYOUT_MIN_COLS = 100

# Relaxed thresholds, used only when BOTH gates pass:
#   (a) Claude Code version >= 2.1.141 (so COLUMNS env is passed to
#       the subprocess per anthropics/claude-code#22115, and per-line
#       width-limit calculation is fixed per #36417), AND
#   (b) the width-detection chain found a high-confidence signal
#       (not the safe-default fallback path).
#
# When both gates pass, the underlying truncation/width-detection
# risks the conservative thresholds were defending against are gone,
# so we can recover sections on 100-149 col terminals that the
# conservative full-layout threshold of 150 was hiding.
#
# When either gate fails (older Claude Code, no trustworthy width
# signal, etc.), we fall back to the conservative thresholds so a
# user with no reliable width source never has Line 2 silently
# truncated. See `_layout_thresholds()` for the decision logic.
_FULL_LAYOUT_MIN_COLS_RELAXED = 110
_COMPACT_LAYOUT_MIN_COLS_RELAXED = 80

# Minimum Claude Code version that ships per-line truncation fix
# (#36417, in the 2.1.139 era) AND the COLUMNS env var handoff
# (#22115, in 2.1.141). Parsed from stdin `version` field as a
# 3-tuple of ints. Pin 2.1.141 — the COLUMNS env is the load-bearing
# signal that makes relaxed thresholds safe.
_RELAXED_MIN_CC_VERSION = (2, 1, 141)

# Sections to drop at each width breakpoint (widest first).
# Below _FULL_LAYOUT_MIN_COLS: drop least-essential sections progressively.
_COMPACT_DROP = [
    "git_extras", "version", "cc_version", "clock", "worktree",
    "sessions", "tools", "activity", "cache_age", "latency", "context_size",
    "session_name", "rate_limits", "output_style", "added_dirs", "effort",
    "git_worktree", "speed", "cost_rate", "context_tokens", "git_state",
    "commit_age", "cost_breakdown", "pr", "thinking",
]
_NARROW_DROP = _COMPACT_DROP + [
    "cache", "burn", "lines", "budget", "agent", "model",
]

# Drop priority for the precise post-render fit (_fit_to_width).
# Earlier entries are dropped first. Extends _COMPACT_DROP with last-resort
# drops so the precise stage can always reach a fitting result even when
# the coarse pre-filter has already kept the compact subset. Sections NOT
# listed here (bar, tokens, cost, branch, ctx_warning) are truly essential
# and never dropped — every line keeps the bar+tokens+cost identity even
# at extreme widths.
#
# Ordering rationale: extras first (same as _COMPACT_DROP), then visual
# decorations (vim, agent), then sections that carry derived/recomputable
# info (lines, burn, duration are derivable from cost+tokens), then model
# (still useful but visible elsewhere in Claude Code's UI), then cache
# (a percentage that changes slowly), and finally budget (the one section
# users explicitly opted into via config — drop only if truly nothing else
# fits). bar/tokens/cost/branch/ctx_warning are deliberately omitted —
# losing those would defeat the statusline's purpose.
_FIT_DROP_PRIORITY = _COMPACT_DROP + [
    "vim", "agent", "worktree", "lines", "duration", "burn",
    "model", "cache", "budget",
]


# Plausibility bounds for a detected terminal width. Anything outside
# this range is treated as garbage and ignored — protects against
# `stty size` returning 0 0 on a closed pty, an OS reporting absurd
# widths, or stdin JSON containing a stringified value that coerced
# to a wild number.
#
# Upper bound 4000 covers ultrawide / 8K / multi-monitor tmux setups
# (a 7680px display at 6px monospace cells = ~1280 cols; side-by-side
# 5K monitors in tmux can exceed 2000 cols). Going wider has no
# rendering cost — the layout only cares about the 100/150 thresholds —
# and rejecting a real 1280-col terminal would silently drop the user
# back into compact layout.
_TERM_WIDTH_MIN = 20
_TERM_WIDTH_MAX = 4000

# Columns held back when fitting each rendered line (#118). The width
# we detect is the TERMINAL width, but Claude Code renders the status
# line inside a padded panel, so the usable row is narrower than what
# we're told. Fitting to the reported width exactly let a full line 2
# spill past the panel edge, where Claude Code's Ink renderer truncated
# it mid-token ("effort:xhi…") — losing a whole section and showing an
# ellipsis we never emitted.
#
# The subagent path has reserved a margin since v0.13.0
# (_SUBAGENT_COLUMNS_MARGIN) for exactly this reason; this back-applies
# the same discipline to the main lines.
#
# Sized deliberately generous rather than minimal: the failure is
# asymmetric — too small costs a truncated section plus a visible
# ellipsis, too large costs a couple of columns nobody notices. It also
# buys headroom for _visible_width's documented width-1 approximation
# for CJK/emoji (a branch name with wide glyphs under-measures today).
# The margin SCALES WITH CONFIDENCE, because a margin is insurance
# against being wrong about the width:
#
#   pinned (CLAUDE_STATUSLINE_WIDTH)  -> 0. The user is asserting the
#       usable width, not reporting a terminal size. Honouring the
#       override exactly is what makes it a real escape hatch for
#       anyone who wants edge-to-edge output.
#   a real probe won                  -> _FIT_SAFETY_MARGIN. We know
#       the terminal width; we're only covering the panel's chrome.
#   nothing won (fallback guess)      -> _FIT_SAFETY_MARGIN_UNTRUSTED.
#       Claude Code 2.1.139+ can run hooks without terminal access, so
#       the chain may fall back to _COMPACT_LAYOUT_MIN_COLS — a guess
#       that can overshoot a narrow split pane by tens of columns. On
#       Claude Code < 2.1.141 a Line 1 overflow silently drops Line 2
#       entirely, so guessing wide is the expensive direction to be
#       wrong in. A margin can't rescue a 28-column error, but the
#       less we trust the number the more headroom we keep.
_FIT_SAFETY_MARGIN = 4
_FIT_SAFETY_MARGIN_UNTRUSTED = 8


def _fit_margin(width_report):
    """Columns to hold back when fitting, given the detection report.

    See _FIT_SAFETY_MARGIN for the rationale. Reads the same per-step
    status strings render() uses for `width_confidence_high`; the
    explicit-override step is the only one whose winning status says
    "explicit override", which is what makes it distinguishable from
    a probe that merely succeeded.
    """
    pinned = False
    confident = False
    for _label, status in width_report:
        if "(winner" not in status:
            continue
        confident = True
        if "explicit override" in status:
            pinned = True
    if pinned:
        return 0
    return _FIT_SAFETY_MARGIN if confident else _FIT_SAFETY_MARGIN_UNTRUSTED

# Common terminfo "cols" defaults that `tput cols` returns when invoked
# without a controlling TTY. Claude Code 2.1.139+ runs hooks "without
# terminal access" (release notes, 2026-05-11), which causes tput to
# fall back to the terminfo default for $TERM rather than reporting an
# error. The most common stub value is 80 (xterm / xterm-256color /
# vt100 / ansi all default to 80 cols). When we see `tput cols == 80`
# AND every prior TTY probe failed, it is almost certainly the stub —
# accepting it would render an 80-col layout into the user's real
# (often 120+) terminal. We reject it and fall through to the next
# signal. A user who genuinely has an 80-col terminal will have been
# caught earlier by shutil/os.get_terminal_size if any TTY was
# reachable; if none were reachable, we cannot distinguish a real
# 80 from the stub and choose to fall through (the safe default keeps
# Line 2 visible; rendering at 80 when the real width is 200 hides
# half the statusline).
_TPUT_STUB_VALUES = frozenset({80})


def _detect_terminal_width(data=None):
    """Detect the user's actual terminal width.

    Thin wrapper around :func:`_detect_terminal_width_report` that
    returns just the winning value. See that function for the full
    fallback chain and the stub-rejection logic for Claude Code
    2.1.139+ (which removed all terminal access from hooks).
    """
    winner, _report = _detect_terminal_width_report(data)
    return winner


def _detect_terminal_width_report(data=None):
    """Detect terminal width and return both the winner and a per-step report.

    Claude Code spawns the statusLine command as a child process with
    stdin piped — there is no TTY, no `COLUMNS` env var, and
    `shutil.get_terminal_size()` returns its fallback. As a result we
    can't tell from the subprocess context alone whether the user has
    a 100-col terminal or a 300-col one, and our two-stage layout
    silently trims to the fallback width.

    Tracked upstream at anthropics/claude-code#22115 (open since Jan
    2026, no upstream fix). Worse, Claude Code 2.1.139 (2026-05-11)
    shipped "hooks now run without terminal access," which closed the
    `/dev/tty` escape hatch our stty/tput steps relied on AND caused
    `tput cols` to return its terminfo stub (typically 80) instead of
    failing — leaving the earlier fallback chain unable to detect
    the lie. This rewrite adds two defenses: a process-tree walk that
    reads the controlling terminal of an ancestor process (Linux), and
    a stub-detection heuristic that rejects `tput cols == 80` when
    no other TTY probe succeeded. Tracked at #83.

    Order (each step caught and ignored on any error):

    1. ``CLAUDE_STATUSLINE_WIDTH`` env var — explicit user override.
       Highest priority: when a user sets this, they are telling us
       to skip detection entirely. Useful for headless CI, nested
       multiplexers where every other probe lies, or when the user
       wants to force a specific layout width regardless of what
       the terminal reports.
    2. ``data["terminal"]["columns"]`` from stdin JSON — defensive
       forward-compat for whenever Anthropic adds it.
    3. ``COLUMNS`` env var — some shell wrappers / users export it.
       ``COLUMNS=0`` is rejected and reported distinctly from unset:
       observed in no-TTY hook subprocesses on 2.1.139+, where the
       presence-of-zero is itself a signal (not a missing variable).
    4. ``shutil.get_terminal_size()`` honoring ``COLUMNS`` and any
       stdout TTY (rarely TTY in our context but cheap to check).
    5. ``os.get_terminal_size(N)`` against a TTY file descriptor
       (stderr/stdout in case one of them is unexpectedly a TTY).
    6. Process-tree walk: try ``os.get_terminal_size`` on the stderr
       fd of each ancestor process. Works on Linux when an ancestor
       still owns the controlling terminal even though we don't.
       macOS lacks an equivalent `/proc/<pid>/fd` exposure and
       degrades to "checked PPID then bailed."
    7. ``stty size < /dev/tty`` — works on Linux/macOS/WSL when
       ``/dev/tty`` is reachable. Often unreachable on 2.1.139+.
    8. ``tput cols 2>/dev/tty`` — alternate POSIX path. Subject to
       stub-value rejection: if `tput` returns a known terminfo
       default AND every prior TTY probe failed, the result is
       treated as a lie and rejected.
    9. Fallback ``_COMPACT_LAYOUT_MIN_COLS`` — safe default that keeps
       Line 2 readable when no signal is trustworthy.

    Args:
        data: Optional parsed stdin JSON dict. If present and contains
            a numeric ``terminal.columns`` value (int, float, or
            numeric string — accepted via ``_safe_num``), that is
            preferred over auto-detection signals (but NOT over the
            explicit ``CLAUDE_STATUSLINE_WIDTH`` env override).

    Returns:
        Tuple of ``(winner_int, report_list)`` where ``winner_int`` is
        the detected width (always within ``[_TERM_WIDTH_MIN,
        _TERM_WIDTH_MAX]``) and ``report_list`` is a list of
        ``(step_label, status_string)`` tuples in chain order. The
        report is consumed by ``--doctor`` to show which signal won
        and which signals lied or fell through.
    """
    report = []

    # Track whether any earlier step found a real TTY signal. Used by
    # the tput-stub heuristic: if every prior probe failed, an exactly-
    # default tput return is treated as the stub, not a real reading.
    any_tty_probe_succeeded = False

    # 1. Explicit CLAUDE_STATUSLINE_WIDTH env override.
    # Highest priority — when the user sets this, they have decided
    # detection is unreliable or want to force a specific width.
    # Out-of-range / non-numeric values fall through to auto-detection.
    # Empty string is treated as "unset" rather than "garbage" because
    # `export CLAUDE_STATUSLINE_WIDTH=` is how users disable the
    # override in their shell, and reporting it as "not an int" would
    # confuse the debugging trail.
    override = os.environ.get("CLAUDE_STATUSLINE_WIDTH")
    if override is None or override == "":
        report.append((
            "CLAUDE_STATUSLINE_WIDTH env",
            "unset" if override is None else "empty — treating as unset",
        ))
    else:
        try:
            cols = int(override)
            if _TERM_WIDTH_MIN <= cols <= _TERM_WIDTH_MAX:
                report.append(("CLAUDE_STATUSLINE_WIDTH env", f"{cols} (winner — explicit override)"))
                return cols, report
            report.append((
                "CLAUDE_STATUSLINE_WIDTH env",
                f"{cols} out of range [{_TERM_WIDTH_MIN}, {_TERM_WIDTH_MAX}] — rejected",
            ))
        except (ValueError, TypeError):
            report.append(("CLAUDE_STATUSLINE_WIDTH env", f"{override!r} not an int — rejected"))

    # 2. Stdin JSON terminal.columns (forward-compat).
    if isinstance(data, dict):
        term_obj = data.get("terminal")
        if isinstance(term_obj, dict):
            cols = _safe_num(term_obj.get("columns"))
            if cols is not None and _TERM_WIDTH_MIN <= cols <= _TERM_WIDTH_MAX:
                report.append(("stdin.terminal.columns", f"{int(cols)} (winner)"))
                return int(cols), report
            report.append((
                "stdin.terminal.columns",
                f"present but out of range ({cols!r}) — rejected" if cols is not None
                else "field present but not numeric — rejected",
            ))
        else:
            report.append(("stdin.terminal.columns", "absent"))
    else:
        report.append(("stdin.terminal.columns", "no stdin data"))

    # 3. COLUMNS env var.
    cols_env = os.environ.get("COLUMNS")
    if cols_env is None:
        report.append(("COLUMNS env", "unset"))
    else:
        try:
            cols = int(cols_env)
            if cols == 0:
                # 2.1.139 failure mode — distinct from unset.
                report.append(("COLUMNS env", "set to 0 — likely no-TTY subprocess, rejected"))
            elif _TERM_WIDTH_MIN <= cols <= _TERM_WIDTH_MAX:
                report.append(("COLUMNS env", f"{cols} (winner)"))
                return cols, report
            else:
                report.append(("COLUMNS env", f"{cols} out of range — rejected"))
        except (ValueError, TypeError):
            report.append(("COLUMNS env", f"{cols_env!r} not an int — rejected"))

    # 4. shutil.get_terminal_size — checks COLUMNS again then any
    # stdout TTY. Cheap; no external process. Skip its fallback
    # path (which would just return our compact default early) by
    # passing a sentinel and only trusting non-sentinel results.
    try:
        size = shutil.get_terminal_size((-1, -1))
        if size.columns == -1:
            report.append(("shutil.get_terminal_size", "no TTY (fallback)"))
        elif _TERM_WIDTH_MIN <= size.columns <= _TERM_WIDTH_MAX:
            any_tty_probe_succeeded = True
            report.append(("shutil.get_terminal_size", f"{size.columns} (winner)"))
            return size.columns, report
        else:
            report.append(("shutil.get_terminal_size", f"{size.columns} out of range — rejected"))
    except (OSError, ValueError) as exc:
        report.append(("shutil.get_terminal_size", f"error: {exc}"))

    # 5. os.get_terminal_size on each std fd — Claude Code closes
    # stdin (it's our JSON pipe) but stderr is often inherited from
    # the parent TTY.
    fd_winner = None
    fd_status = []
    for fd_num, fd_name in ((2, "stderr"), (1, "stdout"), (0, "stdin")):
        try:
            size = os.get_terminal_size(fd_num)
            if _TERM_WIDTH_MIN <= size.columns <= _TERM_WIDTH_MAX:
                fd_winner = (fd_name, size.columns)
                break
            fd_status.append(f"{fd_name}={size.columns} out of range")
        except (OSError, AttributeError) as exc:
            fd_status.append(f"{fd_name}=ENOTTY/{type(exc).__name__}")
    if fd_winner is not None:
        any_tty_probe_succeeded = True
        report.append((
            "os.get_terminal_size(fd)",
            f"{fd_winner[1]} via {fd_winner[0]} (winner)",
        ))
        return fd_winner[1], report
    report.append(("os.get_terminal_size(fd)", "; ".join(fd_status) or "no fds"))

    # 6. Process-tree walk — try the stderr fd of each ancestor process.
    # Linux/macOS only (Windows has no /proc and process ancestry of
    # subprocess hooks is structured differently). When Claude Code
    # 2.1.139+ strips terminal access from the immediate hook process,
    # an ancestor (the user's shell, the Claude Code main process)
    # often still owns the controlling terminal.
    walk_result, walk_status = _detect_width_via_process_tree()
    if walk_result is not None:
        any_tty_probe_succeeded = True
        report.append(("process-tree walk", f"{walk_result} (winner; {walk_status})"))
        return walk_result, report
    report.append(("process-tree walk", walk_status))

    # 7+8. stty size / tput cols against /dev/tty — the most reliable
    # POSIX path historically. Captures the controlling terminal's
    # real width even when stdin/stdout are pipes. /dev/tty doesn't
    # exist on Windows, where stty/tput are also typically absent —
    # all of these raise FileNotFoundError or OSError, caught and
    # fall through. On Claude Code 2.1.139+ /dev/tty is unreachable
    # and tput returns its terminfo stub (see _TPUT_STUB_VALUES).
    #
    # The /dev/tty open is shared across both subprocesses so we pay
    # the open() syscall once; if it fails we skip both probes
    # atomically. stty is tried first because its output format
    # ("rows cols") is more uniform across platforms; tput is the
    # backstop for systems where stty isn't installed but ncurses is.
    try:
        with open("/dev/tty", "r") as tty:
            for cmd_name, cmd, parser in (
                ("stty size", ["stty", "size"], lambda s: int(s.split()[1])),
                ("tput cols", ["tput", "cols"], lambda s: int(s.strip())),
            ):
                try:
                    result = subprocess.run(
                        cmd, stdin=tty,
                        capture_output=True, text=True, timeout=1,
                    )
                    if result.returncode == 0:
                        cols = parser(result.stdout)
                        # Stub-detection heuristic for tput on 2.1.139+:
                        # if tput says exactly a terminfo default and we
                        # never got a real TTY signal earlier in the
                        # chain, it is almost certainly the stub.
                        if (cmd_name == "tput cols"
                                and cols in _TPUT_STUB_VALUES
                                and not any_tty_probe_succeeded):
                            report.append((
                                cmd_name,
                                f"{cols} (likely terminfo stub — rejected; "
                                "no earlier TTY signal)",
                            ))
                            continue
                        if _TERM_WIDTH_MIN <= cols <= _TERM_WIDTH_MAX:
                            any_tty_probe_succeeded = True
                            report.append((cmd_name, f"{cols} (winner)"))
                            return cols, report
                        report.append((cmd_name, f"{cols} out of range — rejected"))
                    else:
                        report.append((cmd_name, f"exit {result.returncode}"))
                except (OSError, ValueError, IndexError,
                        subprocess.SubprocessError, FileNotFoundError) as exc:
                    report.append((cmd_name, f"error: {type(exc).__name__}"))
                    continue
    except (OSError, FileNotFoundError) as exc:
        report.append(("/dev/tty", f"unreachable: {type(exc).__name__}"))

    # 9. Last-resort fallback — _COMPACT_LAYOUT_MIN_COLS keeps Line 2
    # readable when no signal is trustworthy.
    report.append(("fallback", f"{_COMPACT_LAYOUT_MIN_COLS} (no signal trusted)"))
    return _COMPACT_LAYOUT_MIN_COLS, report


def _detect_width_via_process_tree():
    """Walk the parent process chain looking for a TTY-owning ancestor.

    Returns ``(width_int, status_string)`` where ``width_int`` is the
    detected width (or ``None`` if no ancestor has a usable TTY) and
    ``status_string`` describes what happened (for --doctor output).

    Linux/macOS only — Windows has no /proc and a different ancestry
    model for subprocess hooks. The walk stops at PID 1 or after a
    safety cap of 16 ancestors (deep nesting like
    shell→Claude Code→hook→our binary is realistic; pathological
    fork chains are not).
    """
    # Windows: no /proc, no inheritable controlling terminal across
    # subprocess boundaries in this fashion. Bail cheap.
    if platform.system() == "Windows":
        return None, "skipped on Windows"

    try:
        pid = os.getppid()
    except (OSError, AttributeError):
        return None, "getppid unavailable"

    visited = set()
    max_depth = 16
    checked = []

    for _ in range(max_depth):
        if pid <= 1 or pid in visited:
            break
        visited.add(pid)
        checked.append(pid)

        # Try opening the ancestor's stderr fd and reading its size.
        # This works when the ancestor inherited the controlling
        # terminal — common for the user's shell and Claude Code's
        # main TUI process.
        #
        # Low-level os.open with O_NOCTTY + O_NONBLOCK is required:
        # /proc/<pid>/fd/2 is a symlink to the actual TTY device
        # (e.g. /dev/pts/3). A plain open() can interact with TTY
        # job control on some kernels (rare SIGTTIN/SIGTTOU on
        # background process groups) and could in principle make
        # the TTY our controlling terminal. O_NOCTTY explicitly
        # opts out of both behaviors; O_NONBLOCK avoids any block
        # on devices where open() can stall.
        stderr_path = f"/proc/{pid}/fd/2"
        fd = -1
        try:
            fd = os.open(
                stderr_path,
                os.O_RDONLY | getattr(os, "O_NOCTTY", 0) | getattr(os, "O_NONBLOCK", 0),
            )
            try:
                size = os.get_terminal_size(fd)
                if _TERM_WIDTH_MIN <= size.columns <= _TERM_WIDTH_MAX:
                    return size.columns, f"pid {pid} stderr"
            except (OSError, AttributeError):
                pass
        except (OSError, FileNotFoundError, PermissionError):
            # /proc not present (macOS by default) or fd not readable.
            # On macOS the equivalent of /proc/<pid>/fd is not exposed,
            # so this whole walk degrades to "checked PPID then bailed."
            # That's acceptable: the user gets the safe fallback width,
            # same as before this step existed.
            pass
        finally:
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass

        # Advance to the next ancestor by reading /proc/<pid>/stat
        # (Linux). On macOS this fails and we exit the loop.
        try:
            with open(f"/proc/{pid}/stat", "r") as fh:
                # Format: pid (comm) state ppid ...
                # `comm` may contain spaces or parens, so split from the
                # right of the closing paren.
                stat = fh.read()
                rparen = stat.rfind(")")
                if rparen < 0:
                    break
                fields = stat[rparen + 1:].split()
                if len(fields) < 2:
                    break
                pid = int(fields[1])
        except (OSError, ValueError, FileNotFoundError):
            break

    if not checked:
        return None, "no ancestors checked"
    return None, f"walked {len(checked)} ancestor(s), no TTY found"


def _parse_cc_version(raw):
    """Parse a Claude Code version string into a comparable 3-tuple.

    Accepts forms like "2.1.141", "2.1.141-rc.1", "v2.1.141". Returns
    None for absent / non-string / non-numeric inputs so callers can
    treat the absence as "version unknown — use conservative
    thresholds." Only the first three dot-separated numeric components
    are used; suffixes after a non-digit are ignored.
    """
    if not isinstance(raw, str) or not raw:
        return None
    # Strip whitespace first, then the optional `v` prefix, then any
    # whitespace remaining between `v` and the digits. Asymmetric
    # order (lstrip-v before strip-ws) would silently reject
    # "  v2.1.141" because the leading whitespace blocks the lstrip.
    s = raw.strip()
    if s.startswith("v"):
        s = s[1:].lstrip()
    parts = s.split(".")
    out = []
    for part in parts[:3]:
        # Trim trailing non-digit suffix ("141-rc.1" → "141")
        digits = ""
        for ch in part:
            if ch.isdigit():
                digits += ch
            else:
                break
        if not digits:
            return None
        try:
            out.append(int(digits))
        except (TypeError, ValueError):
            return None
    if len(out) < 3:
        return None
    return tuple(out)


def _layout_thresholds(data, width_confidence_high):
    """Return (full_min, compact_min) — the layout thresholds to use
    for this render.

    Returns the RELAXED thresholds (110 / 80) only when BOTH gates
    pass: Claude Code version >= 2.1.141 AND width detection found a
    high-confidence signal. Otherwise returns the conservative
    thresholds (150 / 100) — the safe default that protects users
    on older Claude Code or with no trustworthy width source.

    `width_confidence_high` is set by render() from the width-detection
    chain — True iff a real probe succeeded (not the safe-default
    fallback path).
    """
    # Explicit isinstance(dict) guard — `(data or {})` only protects
    # against falsy values (None / False / 0 / "" / []). A truthy non-
    # dict (a non-empty list or string) would pass through and crash
    # on .get(). Same defensive pattern as _normalize uses throughout.
    cc_version = _parse_cc_version(
        data.get("version") if isinstance(data, dict) else None)
    if (cc_version is not None
            and cc_version >= _RELAXED_MIN_CC_VERSION
            and width_confidence_high):
        return _FULL_LAYOUT_MIN_COLS_RELAXED, _COMPACT_LAYOUT_MIN_COLS_RELAXED
    return _FULL_LAYOUT_MIN_COLS, _COMPACT_LAYOUT_MIN_COLS


def _apply_responsive(sections_list, term_width,
                      full_min=_FULL_LAYOUT_MIN_COLS,
                      compact_min=_COMPACT_LAYOUT_MIN_COLS):
    """Filter section list based on terminal width.

    Default thresholds (conservative): 150 full / 100 compact.
    Relaxed thresholds (110 / 80) passed by render() when both
    Claude Code version and width-detection confidence support it
    (see `_layout_thresholds`).

    >= full_min cols:    full layout (no changes)
    compact_min - full_min cols: compact (drop non-essential extras)
    < compact_min cols:  narrow (essentials only)

    Coarse pre-filter only — the precise fit is performed by
    _fit_to_width() after sections are rendered, so a user at any
    width above the narrow band can see additional sections when
    their actual rendered width allows.
    """
    if term_width >= full_min:
        return sections_list

    if term_width >= compact_min:
        drop = set(_COMPACT_DROP)
    else:
        drop = set(_NARROW_DROP)

    return [s for s in sections_list if s not in drop]


# Match SGR escapes (\x1b[…m) and OSC 8 hyperlink wrappers. OSC 8 has
# two valid string terminators per the ECMA-48 spec: ST (\x1b\\) and
# BEL (\x07). Several emitters (Kitty, GNU Screen wrappers, some Vim
# plugins) use BEL, so we must match both — otherwise BEL-form links
# count as visible bytes and _fit_to_width over-drops sections.
# Both SGR and OSC 8 contribute zero visible width but inflate raw
# byte length.
_ANSI_SGR_RE = re.compile(r"\x1b\[[0-9;]*m")
_OSC8_RE = re.compile(r"\x1b\]8;;[^\x07\x1b]*(?:\x07|\x1b\\)")

# Match Python binary names: python, python3, python3.11, python3.12.5,
# but NOT pythonista, python-fork, python_legacy. Used by --print-config
# install detection to recognize `python -m claude_statusline` invocations
# across multi-version environments (pyenv, deadsnakes, Homebrew).
_PYTHON_BIN_RE = re.compile(r"^python(\d+(\.\d+)*)?$")


def _visible_width(s):
    """Visible character width of a string after stripping ANSI + OSC 8.

    Approximation: counts each remaining code point as width 1. Wide
    East-Asian characters and emoji are under-counted as 1 instead of 2,
    but our statusline glyphs (\u2387 for branch, \u2726 for session,
    bar blocks, etc.) are all single-width — so this matches reality
    for our content. The unicodedata.east_asian_width path is omitted
    intentionally to keep zero dependencies and stay deterministic.
    """
    s = _OSC8_RE.sub("", s)
    s = _ANSI_SGR_RE.sub("", s)
    return len(s)


def _fit_to_width(named_items, sep_visible_width, target_width, drop_priority):
    """Drop low-priority sections until the joined output fits target_width.

    Args:
        named_items: List of (name, rendered) tuples from
            _render_sections_named().
        sep_visible_width: Visible width of the separator between sections.
        target_width: Maximum allowed visible width (terminal columns).
        drop_priority: Ordered list of section names — earliest entries are
            dropped first when the line overflows. Sections not listed here
            are considered essential and are never dropped.

    Returns:
        New list of (name, rendered) tuples that fit within target_width.
        Order of surviving sections is preserved.

    Width math: each visible char counts as 1. Each rendered section is
    measured once up front, then maintained incrementally as sections
    are dropped — avoids re-stripping ANSI on every survivor on every
    drop iteration (suggested by Gemini code review on PR #72).
    """
    if not named_items:
        return []

    # Pre-compute each section's visible width once so we never re-strip
    # ANSI on a survivor we've already measured.
    items = [(name, rendered, _visible_width(rendered))
             for (name, rendered) in named_items]
    total = sum(w for _, _, w in items) + sep_visible_width * (len(items) - 1)

    if total <= target_width:
        return [(n, r) for (n, r, _) in items]

    for drop_name in drop_priority:
        if total <= target_width:
            break
        # Partition by name. Recompute total via:
        #   total' = (total before) - sum(dropped widths) - (count_dropped) * sep
        #   then cap so we never count a separator that wasn't there
        #   (when the survivors list ends up empty or had nothing to
        #   begin with).
        kept = [(n, r, w) for (n, r, w) in items if n != drop_name]
        if len(kept) == len(items):
            continue  # nothing matched this drop_name
        dropped_width = sum(w for (n, _, w) in items if n == drop_name)
        # Separator count change: items had len(items)-1 separators,
        # kept has max(0, len(kept)-1). Subtract the difference.
        old_seps = max(0, len(items) - 1)
        new_seps = max(0, len(kept) - 1)
        total -= dropped_width + (old_seps - new_seps) * sep_visible_width
        items = kept

    return [(n, r) for (n, r, _) in items]


def render(data, theme_name="default"):
    """Render the statusline as one or two lines.

    Two-stage layout adaptation:

    1. Coarse pre-filter (_apply_responsive) — picks a section list
       based on terminal width buckets:
       - >= 150 cols: full layout (all sections eligible)
       - 100-149 cols: compact (drops the heaviest extras up front
         so we don't pay rendering cost on terminals where they
         won't fit)
       - < 100 cols: narrow (essentials only)

    2. Precise width-aware fit (_fit_to_width) — renders the surviving
       sections, measures actual visible width (stripping ANSI/OSC 8),
       and drops sections in _FIT_DROP_PRIORITY order one at a time
       until each line fits the terminal. This recovers sections like
       rate_limits, speed, version, etc. on 150-220 col terminals
       where the static compact bucket would have hidden them
       unnecessarily — and also handles the compact band (100-149)
       where the kept sections might still overflow with heavy data
       (long agent name, vim mode active, long branch+session).

    Stage 2 exists because Claude Code's Ink TUI uses wrap:"truncate"
    on the statusline (anthropics/claude-code#28750, still unfixed) —
    if Line 1 overflows, Line 2 is silently dropped. Measuring our
    actual rendered width and shrinking until we fit prevents this.

    Args:
        data: Parsed JSON dict from Claude Code.
        theme_name: Name of theme to use.

    Returns:
        Formatted statusline string (may contain newline for two-line output).
    """
    theme = get_theme(theme_name)
    n = _normalize(data)
    sep = colorize(theme["separator"], theme["colors"]["separator"])
    sep_width = _visible_width(sep)

    # Detect terminal width via fallback chain — Claude Code's
    # statusLine subprocess context hides this from us, so naive
    # `shutil.get_terminal_size()` always returns the fallback. See
    # `_detect_terminal_width()` for the full chain (stdin JSON →
    # COLUMNS → shutil → /dev/tty stty/tput → compact default).
    # _detect_terminal_width_report() returns (winner, report). The
    # report lets us tell whether the winning value came from a real
    # probe (high confidence) or the safe-default fallback (low). We
    # use confidence to gate the relaxed layout thresholds — only
    # high-confidence width + new-enough Claude Code unlocks the
    # 110/80 thresholds that recover sections on 100-149 col
    # terminals.
    #
    # NB: the substring `"(winner"` is a LOAD-BEARING CONTRACT with
    # _detect_terminal_width_report. Every winning branch in that
    # function appends a status containing "(winner..." (verified
    # 2026-06-05 across all 9 chain steps); the fallback path uses
    # "(no signal trusted)" and rejected probes use "rejected" /
    # "out of range" — none of those contain "(winner". A future
    # refactor that renames the marker (e.g., to "selected", "best",
    # an enum, or restructured tuple field) MUST update this site in
    # tandem, or relaxed thresholds silently stop firing on every
    # render with no error. Test coverage:
    # tests.test_v070_nlines_and_thresholds.TestWidthConfidenceContract.
    term_width, width_report = _detect_terminal_width_report(data)
    width_confidence_high = any(
        "(winner" in status for _, status in width_report
    )
    full_min, compact_min = _layout_thresholds(data, width_confidence_high)

    # Collect every `lineN` key the theme defines, starting at line1
    # and stopping at the first missing index (gap in numbering is
    # treated as the end — keeps the loop bounded and matches the
    # user mental model that statusline rows are contiguous).
    #
    # Backward compat: themes that define only `line1` and `line2`
    # stop at `line3` (missing) and render exactly two rows, same as
    # every release through v0.6.3. Themes that opt in to a third
    # (or further) row by adding `line3` etc render that many rows.
    #
    # Upstream context: Claude Code 2.1.139+ correctly truncates
    # each line independently at terminal width (per anthropics/
    # claude-code#36417, closed), and 2.1.141 passes `COLUMNS` /
    # `LINES` env vars to the statusline subprocess (closes #22115),
    # so multi-row output renders cleanly on modern Claude Code.
    # On narrow terminals, rows past Line 1 can still be dropped by
    # Claude Code's intentional rendering behavior (#28750 closed
    # as "won't fix") — not something claude-status can override.
    disabled = set(get_disabled_sections())
    raw_lines = []  # list of section-name lists, one per row
    seen_sections = set()  # enforces render-at-most-once across rows
    i = 1
    while True:
        key = "line{}".format(i)
        if key not in theme:
            break
        sections = _apply_responsive(theme[key], term_width,
                                     full_min=full_min,
                                     compact_min=compact_min)
        if disabled:
            sections = [s for s in sections if s not in disabled]
        # A section renders at most ONCE per statusline, first line
        # wins. Built-in themes satisfy this by construction, but a
        # CUSTOM theme inherits its base theme's lineN lists for every
        # line it doesn't itself define (themes.load_custom_theme) — so
        # a custom theme that overrides only `line2`, copied from a
        # pre-v0.15.0 default, pairs its old line2 with the rebalanced
        # line1 and would otherwise render burn/rate_limits/
        # context_size twice. Also protects hand-written themes that
        # list a section on two lines by mistake.
        sections = [s for s in sections if s not in seen_sections]
        seen_sections.update(sections)
        raw_lines.append(sections)
        i += 1

    # Render + width-fit each row independently.
    #
    # Precise width-aware fit drop priority is _FIT_DROP_PRIORITY —
    # extends _COMPACT_DROP with last-resort drops (vim, agent, lines,
    # duration, burn, model, cache, budget) so the precise stage can
    # always reach a fitting result. Without these last-resort entries,
    # the compact band (100-149 cols) silently overflows because most
    # surviving line2 sections wouldn't be droppable. Sections not in
    # this list (bar, tokens, cost, branch, ctx_warning) are truly
    # essential and never dropped here.
    # Stage 2 fits to the width MINUS a confidence-scaled margin (see
    # _FIT_SAFETY_MARGIN). Note stage 1 (_apply_responsive, above)
    # deliberately buckets on the raw term_width: it is a render-cost
    # pre-filter choosing which sections are worth computing, while
    # this stage is the authoritative "does it actually fit" decision.
    lines = []
    fit_width = max(_TERM_WIDTH_MIN, term_width - _fit_margin(width_report))
    for row in raw_lines:
        named = _render_sections_named(n, row, theme)
        named = _fit_to_width(named, sep_width, fit_width, _FIT_DROP_PRIORITY)
        if named:
            lines.append(sep.join(r for _, r in named))

    return "\n".join(lines)


# ─── subagentStatusLine support (v0.13.0, #110) ──────────────────────
#
# Claude Code's `subagentStatusLine` settings hook feeds a command
# `columns` + a `tasks[]` array on stdin and renders each emitted
# JSONL line `{"id": <task id>, "content": <row body>}` as that
# task's row in the agent panel. One binary serves both hooks:
# `claude-status --subagent` is the documented interface; a payload
# arriving on the plain command is auto-detected as a convenience
# fallback (stderr breadcrumb suggests the flag).

# Terminal task statuses: rows are emitted only for tasks that are
# (or may be) running. Omitting the id for finished tasks hands the
# row back to upstream's default rendering — and kills the
# forever-ticking elapsed timer a finished task would otherwise show.
# Upstream's status enum is not documented; this set is deliberately
# broad and matching is case-insensitive. Unknown/missing status
# fails OPEN (render): wrongly rendering a live row for a new
# terminal status is a cosmetic staleness bug, while wrongly hiding
# running tasks would gut the feature.
_TERMINAL_TASK_STATUSES = frozenset({
    "completed", "complete", "done", "failed", "error", "errored",
    "cancelled", "canceled", "aborted", "success", "succeeded",
    "finished", "killed", "timeout", "timed_out",
})

# Free text from task definitions is embedded into terminal output —
# strip C0/C1 control characters so a task name can't smuggle escape
# sequences into the user's terminal (same threat model as the OSC 8
# URL sanitizer above).
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")

# Trailing date stamp on model IDs ("claude-sonnet-5-20250707").
# Trailing "-YYYYMMDD", optionally followed by a bracketed variant
# marker (real ids appear as "claude-sonnet-4-5-20250929[1m]").
# The marker is captured so it can be re-appended — dropping it
# would hide which context variant the session is on.
_MODEL_DATE_RE = re.compile(r"-\d{8}(\[[^\]]*\])?$")

_SUBAGENT_NAME_MAX = 24         # name segment cap (with ellipsis)
_SUBAGENT_COLUMNS_DEFAULT = 80  # when columns is garbage after tasks qualified
_SUBAGENT_COLUMNS_MARGIN = 2    # upstream may spend row budget on its own glyphs
_SUBAGENT_ELAPSED_MAX_MS = 7 * 24 * 3600 * 1000  # >7d elapsed = garbage clock


def _is_subagent_payload(data):
    """Envelope-only discriminator for subagentStatusLine payloads.

    True iff `tasks` is a LIST and `columns` is numeric (bool
    excluded — it passes isinstance(int)). Deliberately nothing else:

    - `tasks: []` (no agents running) IS a subagent payload — the
      correct output is nothing, not a full ANSI statusline dumped
      into the JSONL panel.
    - Malformed ELEMENTS never flip the mode: element validation
      happens per-row in render_subagent with skip, because one bad
      task turning the whole payload into cross-mode corruption is
      the worst available failure.
    - There is no documented discriminator field upstream; this
      inference (tasks + columns together) is the narrowest signal
      the documented schema provides. A future MAIN payload growing
      both keys would misroute — the --subagent flag exists so
      correctly-configured users never depend on this inference.
    """
    if not isinstance(data, dict):
        return False
    if not isinstance(data.get("tasks"), list):
        return False
    cols = data.get("columns")
    if isinstance(cols, bool):
        return False
    return _safe_num(cols) is not None


def _parse_start_time_ms(value):
    """Task startTime -> epoch ms, or None. Format is NOT documented
    upstream, so accept the three plausible encodings:

    - ISO-8601 string ("2026-07-09T18:00:00.000Z") via the transcript
      timestamp parser.
    - Epoch numbers, disambiguated by magnitude: < 1e11 -> seconds
      (1e11 s is year 5138), 1e11..1e14 -> milliseconds (1e11 ms is
      1973), >= 1e14 -> microseconds-or-garbage, rejected. The bands
      cannot collide for ~3000 years.
    - Numeric strings coerce via _safe_num (which also kills
      NaN/Infinity — both valid json.loads output). Bools are
      rejected explicitly (same rule as columns: bool is an int
      subclass and `true` is not a timestamp).
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        iso = _parse_iso8601_ms(value)
        if iso is not None:
            return iso
    num = _safe_num(value)
    if num is None or num <= 0:
        return None
    if num < 1e11:
        return int(num * 1000)
    if num < 1e14:
        return int(num)
    return None


def _sanitize_row_text(value):
    """Control-char-stripped, length-capped text for row embedding."""
    if not isinstance(value, str):
        return ""
    text = _CONTROL_CHARS_RE.sub("", value).strip()
    if len(text) > _SUBAGENT_NAME_MAX:
        text = text[:_SUBAGENT_NAME_MAX - 1] + "…"
    return text


def _short_model(model_id, cap=_SUBAGENT_NAME_MAX):
    """Compact display for a model id: "claude-sonnet-5-20250707"
    -> "Sonnet 5", "claude-opus-4-8" -> "Opus 4.8". Trailing numeric
    id parts are version components, joined with dots. Unknown shapes
    degrade to the sanitized, dash-split, title-cased raw id.

    Control-strip WITHOUT the length cap first: _sanitize_row_text's
    24-char truncation would eat the trailing "-YYYYMMDD" before the
    date regex could strip it ("claude-haiku-4-5-20251001" is 25
    chars). The cap is applied to the final short form instead.

    `cap` truncates the result with an ellipsis; subagent rows pass the
    default because their width budget is fixed per row. The MAIN
    status line must pass cap=None: `_fit_to_width` already drops the
    whole `model` section when it doesn't fit, and it drops cleanly
    rather than mid-token. Capping there would (a) hide a variant
    marker the user relies on ("…-preview" truncated away) and (b)
    make this project emit the very mid-token "…" that v0.15.0's own
    diagnosis attributes exclusively to Claude Code's renderer."""
    if not isinstance(model_id, str):
        return ""
    text = _CONTROL_CHARS_RE.sub("", model_id).strip()
    if not text:
        return ""
    # Strip the trailing date, but KEEP any bracketed variant marker it
    # carried ("...-20250929[1m]" -> suffix "[1m]"): the marker tells
    # the user which context variant the session is on, so dropping it
    # would be silent information loss.
    date_match = _MODEL_DATE_RE.search(text)
    variant_suffix = (date_match.group(1) or "") if date_match else ""
    text = _MODEL_DATE_RE.sub("", text)
    if text.startswith("claude-"):
        text = text[len("claude-"):]
    parts = [p for p in text.split("-") if p]
    version = []
    while parts and parts[-1].isdigit():
        version.insert(0, parts.pop())
    family = " ".join(parts).title()
    if family and version:
        short = "{} {}".format(family, ".".join(version))
    else:
        short = family or ".".join(version)
    if short and variant_suffix:
        short += " " + variant_suffix
    if cap is not None and len(short) > cap:
        short = short[:cap - 1] + "…"
    return short


def render_subagent(data, theme_name="default", _now=None):
    """Render a subagentStatusLine payload to JSONL row overrides.

    Contract (documented upstream): one `{"id", "content"}` JSON
    object per line; a task whose id is omitted keeps its default
    rendering; empty content HIDES a row. Consequences honored here:

    - A task we cannot render (non-dict, no id, terminal status, or
      nothing fits the width) is OMITTED — default rendering always
      beats a hidden or garbled row. Empty content is never emitted:
      a degradation path must not blank the user's panel.
    - The id is echoed back as its ORIGINAL JSON value (int stays
      int) so upstream's row matching cannot miss.
    - ZERO disk writes and zero subprocess spawns happen here: this
      never calls _normalize (which mirrors the effort cache to
      disk), never touches git, and never records daily spend. The
      hook fires once per refresh tick per panel — side effects would
      multiply.

    Row shape, fitted to `columns` minus a small margin (upstream may
    spend part of the budget on its own glyphs — unverified):

        [Explore] [███░░░░░] 41% · 23s · Sonnet 5

    Drop order under width pressure: model -> bar -> elapsed; the
    minimum row is "[name] 41%" (or "[name] 23s" on pre-2.1.205
    payloads, which omit model/contextWindowSize). Percent color uses
    the same 60/85 bands as the main context bar, so the panel and
    the statusline agree on what "danger" looks like.
    """
    theme = get_theme(theme_name)
    tc = theme["colors"]
    now_ms = int((time.time() if _now is None else _now) * 1000)

    # Trust any small positive width: a genuinely narrow panel must
    # get a narrow budget (rows that can't fit are OMITTED — upstream's
    # default rendering is the honest degrade). Falling back to the
    # 80-col default for small values would invert the contract: a
    # 19-col panel would receive 78-col rows, overflowing 3x. The
    # default is reserved for genuine garbage (missing/non-positive/
    # absurd).
    cols = data.get("columns")
    cols_num = None if isinstance(cols, bool) else _safe_num(cols)
    if cols_num is None or cols_num <= 0 or cols_num > 4000:
        width_budget = _SUBAGENT_COLUMNS_DEFAULT
    else:
        width_budget = int(cols_num)
    width_budget -= _SUBAGENT_COLUMNS_MARGIN

    lines = []
    for task in data.get("tasks", []):
        if not isinstance(task, dict):
            continue
        task_id = task.get("id")
        if task_id is None:
            continue

        status = task.get("status")
        if isinstance(status, str) and \
                status.strip().lower() in _TERMINAL_TASK_STATUSES:
            continue  # finished: upstream's default row, no live timer

        name = ""
        for key in ("name", "label", "type"):
            name = _sanitize_row_text(task.get(key))
            if name:
                break
        if not name:
            name = "task"
        name_seg = colorize("[{}]".format(name), tc["agent"])

        # Context percentage: tokenCount may legitimately be 0 (a 0%
        # bar); contextWindowSize must be strictly positive (guards
        # ZeroDivision). Displayed pct clamps to 100 — upstream lag
        # can put tokenCount above the window and "[####] 412%" is a
        # lie either way (same rationale as the rate-limits clamp).
        tokens = _safe_num(task.get("tokenCount"))
        ctx = _safe_num(task.get("contextWindowSize"))
        pct_seg = bar_seg = None
        if tokens is not None and tokens >= 0 and ctx is not None and ctx > 0:
            pct = min(100.0, (tokens / ctx) * 100.0)
            pct_seg = colorize("{:.0f}%".format(pct), _bar_color(pct))
            bar_seg = render_bar(pct, width=8, theme=theme)

        # Elapsed: negative (future startTime / clock skew) and
        # absurd (>7d) ages drop the segment — cache_age precedent.
        elapsed_seg = None
        start_ms = _parse_start_time_ms(task.get("startTime"))
        if start_ms is not None:
            age_ms = now_ms - start_ms
            if 0 <= age_ms <= _SUBAGENT_ELAPSED_MAX_MS:
                elapsed_seg = colorize(fmt_duration(age_ms), tc["value"])

        model_seg = None
        short = _short_model(task.get("model"))
        if short:
            model_seg = colorize(short, tc.get("model", BRIGHT_BLACK))

        # Assemble at full detail, then drop model -> bar -> elapsed
        # until the row fits. Never pad; never emit an empty row.
        def _assemble(with_model, with_bar, with_elapsed):
            parts = [name_seg]
            gauge = " ".join(p for p in (
                bar_seg if with_bar else None, pct_seg) if p)
            if gauge:
                parts.append(gauge)
            if with_elapsed and elapsed_seg:
                parts.append(elapsed_seg)
            if with_model and model_seg:
                parts.append(model_seg)
            head = parts[0]
            rest = parts[1:]
            if not rest:
                return head
            return head + " " + " · ".join(rest)

        row = None
        for wm, wb, we in ((True, True, True), (False, True, True),
                           (False, False, True), (False, False, False)):
            candidate = _assemble(wm, wb, we)
            if _visible_width(candidate) <= width_budget:
                row = candidate
                break
        if row is None:
            # Even "[name]"/"[name] 41%" overflows: truncate the name
            # harder; if that still can't fit, omit the row entirely.
            bare = colorize("[{}]".format(name[:8]), tc["agent"])
            if _visible_width(bare) <= width_budget:
                row = bare
            else:
                continue

        # allow_nan=False + skip: a NaN/Infinity float id (json.loads
        # accepts the bare literals) would otherwise serialize as
        # `{"id": NaN, ...}` — invalid strict JSON that upstream's
        # JSON.parse throws on, potentially poisoning EVERY row in the
        # response. One bad task must never take down the panel.
        try:
            lines.append(json.dumps(
                {"id": task_id, "content": row}, allow_nan=False))
        except ValueError:
            continue

    return "\n".join(lines)


def _demo_data():
    """Generate sample data for demo mode using the real nested schema.

    Kept representative of a CURRENT default session (Sonnet 5 era:
    1M context window, populated pr block, thinking on) so --demo and
    the README screenshots generated from it show what a new user will
    actually see. Numbers are roughly consistent: 42% of a 1M window
    ≈ the 412K input tokens shown.
    """
    return {
        "context_window": {
            "used_percentage": 42,
            "context_window_size": 1_000_000,
            "current_usage": {
                "input_tokens": 412_000,
                "output_tokens": 18_500,
                "cache_read_input_tokens": 365_000,
                "cache_creation_input_tokens": 12_000,
            },
        },
        "cost": {
            "total_cost_usd": 0.73,
            "total_duration_ms": 725_000,
            "total_api_duration_ms": 312_000,
            "total_lines_added": 247,
            "total_lines_removed": 38,
        },
        "exceeds_200k_tokens": False,
        "git_branch": "feat/statusline",
        "cwd": "/home/user/projects/myapp",
        "workspace": {
            "project_dir": "/home/user/projects/myapp",
            "current_dir": "/home/user/projects/myapp/src",
            "added_dirs": ["/home/user/projects/shared-lib"],
            "git_worktree": False,
        },
        "model": {
            "display_name": "Sonnet 5",
        },
        "session_id": "demo-session",
        "session_name": "refactor auth",
        "version": "2.1.197",
        "output_style": {"name": "explanatory"},
        "effort": {"level": "high"},
        "thinking": {"enabled": True},
        "pr": {
            "number": 1234,
            "url": "https://github.com/user/myapp/pull/1234",
            "review_state": "approved",
        },
        "rate_limits": {
            "five_hour": {
                "used_percentage": 34,
                "resets_at": int(time.time()) + 7_200,  # 2 hours from now (seconds)
            },
            "seven_day": {
                "used_percentage": 18,
                "resets_at": int(time.time()) + 432_000,  # 5 days from now (seconds)
            },
        },
    }


def _print_indented(text, indent="  "):
    """Print multiline text with consistent indentation."""
    for line in text.split("\n"):
        print(indent + line)


def cmd_demo():
    """Show demo output for all themes."""
    data = _demo_data()

    # Mock session functions so demo shows tools/sessions sections.
    # The daily-spend recorder MUST be stubbed too: a demo render on a
    # machine with a real budget config would otherwise write the fake
    # "demo-session" $0.73 into the user's REAL spend ledger and
    # inflate their live day: chip until midnight (monotonic max —
    # cannot self-correct). The stub echoes the demo cost back as the
    # day total so the budget chip still demos meaningfully.
    import claude_statusline.cli as _self
    _orig_tool_count = _self.get_session_tool_count
    _orig_session_count = _self.get_today_session_count
    _orig_record_spend = _self.record_and_get_daily_spend
    _self.get_session_tool_count = lambda sid: 42
    _self.get_today_session_count = lambda: 3
    _self.record_and_get_daily_spend = (
        lambda sid, c, d: (c, True) if c is not None else (0.0, False))

    try:
        print("claude-status v{} — theme demos\n".format(__version__))
        for name in ("default", "minimal", "powerline", "nord", "tokyo-night", "gruvbox", "rose-pine", "focus"):
            print("  {}:".format(name))
            _print_indented(render(data, name))
            print()

        # Also show warning state (93% triggers !CTX via percentage check)
        warn_data = json.loads(json.dumps(data))
        warn_data["context_window"]["used_percentage"] = 93
        print("  warning state (93% usage):")
        _print_indented(render(warn_data, "default"))
        print()

        # Show with optional fields
        full_data = json.loads(json.dumps(data))
        full_data["vim"] = {"mode": "NORMAL"}
        full_data["agent"] = {"name": "Explore"}
        full_data["worktree"] = {"branch": "fix/bug-123", "name": "bug-fix"}
        print("  all fields (vim + agent + worktree):")
        _print_indented(render(full_data, "default"))
        print()
        # Repo-link footer (#116): --demo is the discovery funnel (the
        # README's first CTA is `uvx claude-status --demo`, reaching
        # people who haven't installed yet). A repo link at the end of
        # a demo is expected showcase content. Static line — no
        # network, no state, no marker files; star-DETECTION was
        # evaluated and rejected (it would need the user's GitHub
        # identity and would be this package's first network call,
        # breaking the documented "no network" promise).
        print("Repo & docs: https://github.com/mkalkere/claude-statusline"
              " — a star helps others find it")
    finally:
        try:
            _self.get_session_tool_count = _orig_tool_count
        except Exception:
            pass
        try:
            _self.get_today_session_count = _orig_session_count
        except Exception:
            pass
        try:
            _self.record_and_get_daily_spend = _orig_record_spend
        except Exception:
            pass


def _sanitize_field(value):
    """Strip newlines and carriage returns so emitted fields stay on one line.

    The --print-config output contract promises a stable 8-line shape;
    a stray newline in (e.g.) command would inject a fake key=value
    line and break parsers downstream.
    """
    return str(value).replace("\r", " ").replace("\n", " ")


def _is_claude_status_invocation(parts):
    """Detect whether a tokenized command actually launches claude-status.

    Handles all the install patterns that produce a working status line:
    - Direct binary: `claude-status`, `claude-status.exe`,
      `/usr/local/bin/claude-status`, `C:\\path\\claude-status.exe`
    - Module form: `python -m claude_statusline`, `py -m claude_statusline`
    - Runner forms: `uvx claude-status`, `pipx run claude-status`

    Strict basename-equality is used (not endswith) so lookalike
    binaries like `not-claude-status` or `my-claude-status-fork` do
    not falsely match.
    """
    if not parts:
        return False
    head = os.path.basename(parts[0]).lower()
    # strip .exe suffix on Windows-style invocations
    if head.endswith(".exe"):
        head = head[:-4]
    if head == "claude-status":
        return True
    # python -m claude_statusline. Accept any versioned binary
    # (python, python3, python3.11, python3.12.5, py) — common in
    # multi-version setups (pyenv, deadsnakes, Homebrew). The regex
    # is tighter than startswith("python"), which would also accept
    # unrelated names like "pythonista" or "python-fork".
    if (head == "py" or _PYTHON_BIN_RE.match(head)) and "-m" in parts:
        try:
            mod = parts[parts.index("-m") + 1]
        except (IndexError, ValueError):
            return False
        return mod in ("claude_statusline", "claude_statusline.cli")
    # uvx claude-status / pipx run claude-status
    if head in ("uvx", "pipx") and "claude-status" in parts:
        return True
    return False


def _extract_theme(parts):
    """Pull the --theme value out of a tokenized command.

    Accepts both space form (`--theme nord`) and equals form
    (`--theme=nord`) — argparse upstream accepts both, so we must too.

    When --theme appears multiple times (e.g. `claude-status --theme
    nord --theme focus`), the LAST occurrence wins to match argparse's
    semantics — that's what the user's running command actually does,
    so reporting it accurately is what an introspecting agent needs.

    Returns "default" if no --theme was specified, "" if parts is empty.
    """
    if not parts:
        return ""
    theme = "default"
    i = 0
    while i < len(parts):
        tok = parts[i]
        if tok == "--theme" and i + 1 < len(parts):
            theme = parts[i + 1]
            i += 2
            continue
        if tok.startswith("--theme="):
            theme = tok.split("=", 1)[1]
        i += 1
    return theme


def cmd_print_config():
    """Print current install state in a deterministic key=value form.

    Designed for coding agents and shell scripts. Output is a stable
    9-line block (8 original lines + `subagent`, appended in v0.13.0
    so existing key=value and first-8-lines parsers keep working; a
    parser asserting an exact 8-line count does need updating) —
    fields are always emitted in the same order, every field always
    appears, and values containing newlines are sanitized so the line
    count stays fixed.

    Output keys (in order):
      installed         true | false
      command           verbatim statusLine.command (newlines stripped)
      type              verbatim statusLine.type
      refreshInterval   integer or empty
      theme             theme name, "default", or empty
      version           running module version
      settings_path     absolute path to the settings.json we inspected
      settings_state    ok | missing | unreadable
      subagent          installed | installed_missing_flag | not_installed
                        (state of the subagentStatusLine hook; the
                        _missing_flag variant means the hook points at
                        claude-status but lacks --subagent)

    Exit codes:
      0  installed (statusLine.command launches claude-status)
      1  not installed (settings missing OR statusLine missing OR
         statusLine points at a different tool)
      2  settings.json exists but is corrupt or unreadable —
         caller MUST NOT auto-install (would overwrite recoverable
         user config)

    Agents: use `if claude-status --print-config >/dev/null; then …`
    for a clean installed-check. Always treat exit code 2 as a hard
    stop and surface to the user — never auto-install over it.
    """
    settings_file = _settings_path()
    installed = False
    cmd_str = ""
    sl_type = ""
    refresh = ""
    theme = ""
    settings_state = "missing"
    settings = None  # stays None when the settings file doesn't exist

    if os.path.exists(settings_file):
        try:
            with open(settings_file, "r", encoding="utf-8") as f:
                settings = json.load(f)
            settings_state = "ok"
        except json.JSONDecodeError as exc:
            print("claude-status: settings.json corrupt: line {} col {}: {}".format(
                exc.lineno, exc.colno, exc.msg), file=sys.stderr)
            settings = None
            settings_state = "unreadable"
        except (IOError, OSError, UnicodeDecodeError) as exc:
            print("claude-status: settings.json unreadable: {}: {}".format(
                type(exc).__name__, exc), file=sys.stderr)
            settings = None
            settings_state = "unreadable"
        if isinstance(settings, dict):
            sl = settings.get("statusLine")
            if isinstance(sl, dict):
                # Explicit null check before str() — settings.json may
                # contain `"type": null` from a tool that cleared the
                # field. str(None) would emit the literal "None",
                # breaking the documented "empty string when absent"
                # contract.
                sl_type_raw = sl.get("type")
                sl_type = str(sl_type_raw) if sl_type_raw is not None else ""
                cmd_raw = sl.get("command")
                cmd_str = (cmd_raw if isinstance(cmd_raw, str)
                           else (str(cmd_raw) if cmd_raw is not None else ""))
                # refreshInterval: accept int/float (reject bool subclass)
                # AND numeric strings, since hand-edited settings.json
                # often stringify numbers. _safe_num handles both.
                ri = sl.get("refreshInterval")
                if isinstance(ri, bool):
                    pass  # bool is an int subclass — drop explicitly
                else:
                    n = _safe_num(ri)
                    if n is not None and n >= 0:
                        refresh = str(int(n))
                # Tokenize the command. shlex handles quoted paths
                # like "C:\Program Files\Scripts\claude-status.exe"
                # that plain str.split would mangle. posix=True is
                # used unconditionally — settings.json values use
                # shell-style quoting regardless of host OS, and
                # posix=False on Windows leaves the quotes attached
                # to the token, breaking basename comparison.
                try:
                    parts = shlex.split(cmd_str, posix=True)
                except ValueError:
                    parts = cmd_str.split()
                if _is_claude_status_invocation(parts):
                    installed = True
                    theme = _extract_theme(parts)

    # subagentStatusLine state (v0.13.0): appended as an EXTRA line
    # after the original 8 so existing key=value parsers keep working;
    # the docstring documents the addition.
    subagent_state = "not_installed"
    if isinstance(settings, dict):
        sub = settings.get("subagentStatusLine")
        if isinstance(sub, dict) and \
                "claude-status" in str(sub.get("command", "")):
            subagent_state = ("installed"
                              if "--subagent" in str(sub.get("command", ""))
                              else "installed_missing_flag")

    print("installed={}".format("true" if installed else "false"))
    print("command={}".format(_sanitize_field(cmd_str)))
    print("type={}".format(_sanitize_field(sl_type)))
    print("refreshInterval={}".format(refresh))
    print("theme={}".format(_sanitize_field(theme)))
    print("version={}".format(__version__))
    print("settings_path={}".format(_sanitize_field(settings_file)))
    print("settings_state={}".format(settings_state))
    print("subagent={}".format(subagent_state))
    if settings_state == "unreadable":
        sys.exit(2)
    sys.exit(0 if installed else 1)


def _subagent_command(theme_name="default"):
    """The settings.json command string for the subagent hook —
    same construction as the statusLine command, plus --subagent."""
    cmd = "claude-status"
    if theme_name != "default":
        cmd += " --theme {}".format(theme_name)
    return cmd + " --subagent"


def _install_subagent_hook(theme_name="default"):
    """Write the subagentStatusLine key into settings.json.

    Returns True on success. Read-modify-ATOMIC-write (tmp +
    os.replace); deliberately makes NO .bak of its own — the only
    caller is the --setup wizard's opt-in question, which runs
    seconds after cmd_install already created settings.json.bak.
    Never called unconditionally: the setting's minimum Claude Code
    version is undocumented upstream, and interactive setup is where
    the user can check their version.
    """
    settings_file = _settings_path()
    settings = {}
    if os.path.exists(settings_file):
        try:
            with open(settings_file, "r", encoding="utf-8") as f:
                settings = json.load(f)
            if not isinstance(settings, dict):
                settings = {}
        except (json.JSONDecodeError, IOError) as e:
            print("  Warning: could not read settings: {}".format(e))
            return False
    settings["subagentStatusLine"] = {
        "type": "command",
        "command": _subagent_command(theme_name),
    }
    # Atomic write (tmp + os.replace, the ledger/cache pattern): a
    # disk-full mid-dump on a plain open() would leave settings.json
    # truncated mid-JSON — corrupting the user's Claude Code config is
    # the #96 incident class and never acceptable from a wizard step.
    tmp = settings_file + ".tmp"
    try:
        os.makedirs(os.path.dirname(settings_file), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
            f.write("\n")
        os.replace(tmp, settings_file)
    except OSError as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        print("  Warning: could not write settings: {}".format(e))
        print("  Your settings.json was NOT modified (atomic write "
              "failed before replace); a .bak from the install step "
              "may also exist alongside it.")
        return False
    print("  subagentStatusLine: {}".format(_subagent_command(theme_name)))
    return True


def cmd_install(theme_name="default"):
    """Install claude-status into Claude Code settings."""
    settings_file = _settings_path()
    settings = {}

    # Read existing settings and create backup
    if os.path.exists(settings_file):
        backup_file = settings_file + ".bak"
        try:
            shutil.copy2(settings_file, backup_file)
        except OSError as e:
            print("Warning: could not create backup: {}".format(e),
                  file=sys.stderr)
        try:
            with open(settings_file, "r", encoding="utf-8") as f:
                settings = json.load(f)
        except (json.JSONDecodeError, IOError):
            print("Warning: could not parse existing settings.json")
            print("  Backup saved to: {}.bak".format(settings_file))
            print("  Creating new settings with statusLine config only")

    # Build command
    cmd = "claude-status"
    if theme_name != "default":
        cmd += " --theme {}".format(theme_name)

    # Update statusLine config (must be an object with type + command)
    settings["statusLine"] = {
        "type": "command",
        "command": cmd,
    }

    # Ensure directory exists
    os.makedirs(os.path.dirname(settings_file), exist_ok=True)

    # Write settings
    with open(settings_file, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")

    print("Installed claude-status into {}".format(settings_file))
    print("  statusLine: {}".format(cmd))
    print()
    print("Restart Claude Code to see your new status line!")
    print()
    print("Optional — per-subagent status rows in the agent panel")
    print("(model/context fields need Claude Code 2.1.205+). Add to")
    print("your settings.json, or run claude-status --setup:")
    print()
    print('  "subagentStatusLine": {{"type": "command", '
          '"command": "{}"}}'.format(_subagent_command(theme_name)))


def cmd_uninstall():
    """Remove claude-status from Claude Code settings.

    Removes the statusLine key from settings.json. If a .bak backup
    exists with a previous statusLine config, offers to restore it.
    """
    settings_file = _settings_path()

    if not os.path.exists(settings_file):
        print("No settings file found at {}".format(settings_file))
        return

    try:
        with open(settings_file, "r", encoding="utf-8") as f:
            settings = json.load(f)
        if not isinstance(settings, dict):
            settings = {}
    except (json.JSONDecodeError, IOError) as e:
        print("Error: could not read {}: {}".format(settings_file, e))
        return

    if "statusLine" not in settings and "subagentStatusLine" not in settings:
        print("claude-status is not installed (no statusLine in settings).")
        return

    # Remove the subagent hook if it points at claude-status —
    # shipping an installer for a key the uninstaller strands would
    # be a bug. A subagentStatusLine belonging to some other tool is
    # left alone.
    had_statusline = "statusLine" in settings
    removed_sub = False
    sub = settings.get("subagentStatusLine")
    if isinstance(sub, dict) and "claude-status" in str(sub.get("command", "")):
        del settings["subagentStatusLine"]
        removed_sub = True

    if not had_statusline and not removed_sub:
        # Only a FOREIGN subagentStatusLine exists: nothing of ours to
        # remove. Don't rewrite (and reformat) the user's settings, and
        # don't print a false "Removed statusLine" message.
        print("claude-status is not installed "
              "(the subagentStatusLine present belongs to another tool).")
        return

    # Check for backup with previous statusLine config. Gated on the
    # settings actually HAVING had a statusLine: without the gate, a
    # subagent-hook-only uninstall against a stale .bak would resurrect
    # a statusLine the user had deliberately removed.
    backup_file = settings_file + ".bak"
    restored = False
    if had_statusline and os.path.exists(backup_file):
        try:
            with open(backup_file, "r", encoding="utf-8") as f:
                backup = json.load(f)
            if not isinstance(backup, dict):
                backup = {}
            prev_sl = backup.get("statusLine")
            if prev_sl and prev_sl != settings.get("statusLine"):
                settings["statusLine"] = prev_sl
                restored = True
        except (json.JSONDecodeError, IOError) as e:
            print("Warning: backup exists but could not be read: {}".format(e),
                  file=sys.stderr)

    if not restored:
        # pop, not del: this path also serves subagent-hook-only
        # payloads where "statusLine" is legitimately absent.
        settings.pop("statusLine", None)

    try:
        with open(settings_file, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except IOError as e:
        print("Error writing settings: {}".format(e))
        return

    if removed_sub:
        print("Removed subagentStatusLine hook.")
    if restored:
        print("Restored previous statusLine config from backup.")
        print("  statusLine: {}".format(settings.get("statusLine")))
    elif had_statusline:
        print("Removed statusLine from {}".format(settings_file))

    print()
    print("Restart Claude Code for the change to take effect.")
    print("To fully uninstall: pip uninstall claude-status")


_THEME_DESCRIPTIONS = {
    "default": "full detail, clean separators",
    "minimal": "essentials only, compact",
    "powerline": "Nerd Font separators",
    "nord": "cool blue tones",
    "tokyo-night": "purple and blue accents",
    "gruvbox": "warm retro palette",
    "rose-pine": "soft muted pinks",
    "focus": "single line, minimal footprint",
}


def cmd_setup():
    """Interactive setup wizard for first-time configuration."""
    print("claude-status v{} — setup wizard\n".format(__version__))

    # Step 1: Show theme list with short descriptions
    theme_names = ["default", "minimal", "powerline",
                   "nord", "tokyo-night", "gruvbox", "rose-pine", "focus"]

    print("Available themes:\n")
    for i, name in enumerate(theme_names, 1):
        desc = _THEME_DESCRIPTIONS.get(name, "")
        print("  [{}] {:12s} — {}".format(i, name, desc))

    custom_idx = len(theme_names) + 1
    print("  [{}] {:12s} — load from ~/.claude/claude-status-theme.json".format(
        custom_idx, "custom"
    ))
    print()

    try:
        choice = input("Choose a theme [1-{}] (default: 1): ".format(
            custom_idx
        )).strip()
    except (EOFError, KeyboardInterrupt):
        print("\nSetup cancelled.")
        return

    if not choice:
        theme_choice = "default"
    else:
        try:
            idx = int(choice) - 1
            if idx == len(theme_names):
                theme_choice = "custom"
            elif 0 <= idx < len(theme_names):
                theme_choice = theme_names[idx]
            else:
                print("Invalid choice, using default.")
                theme_choice = "default"
        except ValueError:
            print("Invalid choice, using default.")
            theme_choice = "default"

    # Show preview of selected theme
    data = _demo_data()

    import claude_statusline.cli as _self
    _orig_tool_count = _self.get_session_tool_count
    _orig_session_count = _self.get_today_session_count
    # Stub the spend recorder for the same reason as cmd_demo: the
    # setup wizard runs on exactly the machine where the user just
    # configured a real budget, and an unstubbed preview render would
    # write the fake demo cost into their REAL daily ledger.
    _orig_record_spend = _self.record_and_get_daily_spend
    _self.get_session_tool_count = lambda sid: 42
    _self.get_today_session_count = lambda: 3
    _self.record_and_get_daily_spend = (
        lambda sid, c, d: (c, True) if c is not None else (0.0, False))

    try:
        print("\n  Preview:")
        _print_indented(render(data, theme_choice), "    ")
        print()
    finally:
        try:
            _self.get_session_tool_count = _orig_tool_count
        except Exception:
            pass
        try:
            _self.get_today_session_count = _orig_session_count
        except Exception:
            pass
        try:
            _self.record_and_get_daily_spend = _orig_record_spend
        except Exception:
            pass

    # Step 2: Budget configuration
    try:
        budget_input = input(
            "Set a daily budget in USD? (e.g., 10.00, or press Enter to skip): "
        ).strip()
    except (EOFError, KeyboardInterrupt):
        print("\nSetup cancelled.")
        return

    budget = None
    if budget_input:
        try:
            budget = float(budget_input.lstrip("$"))
            if budget <= 0:
                print("Budget must be positive, skipping.")
                budget = None
        except ValueError:
            print("Invalid amount, skipping budget.")

    # Step 3: Write budget config if set
    if budget is not None:
        budget_path = os.path.join(
            os.path.expanduser("~"), ".claude", "claude-status-budget.json"
        )
        try:
            os.makedirs(os.path.dirname(budget_path), exist_ok=True)
            with open(budget_path, "w", encoding="utf-8") as f:
                json.dump({"daily_budget_usd": budget}, f, indent=2)
                f.write("\n")
            print("  Budget saved: ${:.2f}/day".format(budget))
        except OSError as e:
            print("  Warning: could not save budget config: {}".format(e))
            # Reset so the Step-5 summary doesn't claim a budget that
            # was never written — a masked-wrong success message.
            budget = None

    # Step 4: Install statusLine config
    print()
    cmd_install(theme_choice)

    # Step 4b: optional per-subagent rows (v0.13.0). Opt-in question
    # rather than unconditional write: --setup is interactive, so the
    # user can check their Claude Code version; the setting's own
    # minimum version is not documented upstream, and writing an
    # unknown settings key on an old Claude Code may surface warnings.
    subagent_enabled = False
    try:
        sub_input = input(
            "Also enable per-subagent status rows in the agent panel?\n"
            "  (task name, context %, elapsed — model/context need "
            "Claude Code 2.1.205+) [y/N]: "
        ).strip().lower()
    except (EOFError, KeyboardInterrupt):
        sub_input = ""
    if sub_input in ("y", "yes"):
        subagent_enabled = _install_subagent_hook(theme_choice)

    # Step 5: Summary
    print()
    print("Setup complete!")
    print("  Theme: {}".format(theme_choice))
    if budget is not None:
        print("  Budget: ${:.2f}/day".format(budget))
    if subagent_enabled:
        print("  Subagent rows: enabled")
    print()
    print("Tip: Add \"refreshInterval\": 10 to your statusLine config")
    print("     for periodic updates (clock, sessions, rate limits).")
    print()
    print("Preview all themes: claude-status --demo")
    print("Diagnostics: claude-status --doctor")
    print("Uninstall: claude-status --uninstall")
    # Star-ask epilogue (#114): printed ONLY here, on the interactive
    # wizard's success path — never in --install (the agents/CI path,
    # where no human reads it) and never interleaved with functional
    # output. Successful installers are the only people who can grow
    # the project's discoverability; one polite line, no tracking,
    # no repetition mechanism.
    print()
    print("If claude-status is useful to you, a GitHub star helps")
    print("others find it: https://github.com/mkalkere/claude-statusline")


def cmd_doctor():
    """Run diagnostics and print system info."""
    print("claude-status v{} — diagnostics\n".format(__version__))

    # System info
    print("System:")
    print("  Python:   {} ({})".format(platform.python_version(), sys.executable))
    if sys.version_info[:2] < (3, 8):
        print("  WARNING:  Python 3.8+ required")
    print("  OS:       {} {}".format(platform.system(), platform.release()))
    print("  Platform: {}".format(platform.platform()))
    print("  Encoding: {}".format(sys.stdout.encoding))
    print()

    # PATH check
    print("PATH:")
    which = shutil.which("claude-status")
    if which:
        print("  claude-status: {}".format(which))
    else:
        print("  claude-status: NOT FOUND in PATH")
        print("  Try: python -m claude_statusline --install")
    print()

    # Check settings
    settings_file = _settings_path()
    print("Claude Code:")
    print("  Settings: {}".format(settings_file))
    if os.path.exists(settings_file):
        try:
            with open(settings_file, "r", encoding="utf-8") as f:
                settings = json.load(f)
            sl = settings.get("statusLine", "(not configured)")
            print("  statusLine: {}".format(sl))
            sub = settings.get("subagentStatusLine")
            if sub is None:
                print("  subagentStatusLine: (not configured — per-task "
                      "agent rows disabled; see README)")
            else:
                print("  subagentStatusLine: {}".format(sub))
                if isinstance(sub, dict) and \
                        "claude-status" in str(sub.get("command", "")) and \
                        "--subagent" not in str(sub.get("command", "")):
                    print("    note: command lacks --subagent — "
                          "auto-detection covers it, but emits a "
                          "per-tick stderr reminder; add the flag to "
                          "silence it")
            if isinstance(sl, dict):
                ri = sl.get("refreshInterval")
                if ri:
                    print("  refreshInterval: {}s".format(ri))
        except Exception as e:
            print("  Error reading settings: {}: {}".format(type(e).__name__, e))
    else:
        print("  Settings file not found")
    print()

    # Config file validation
    home = os.path.expanduser("~")
    claude_dir = os.path.join(home, ".claude")
    print("Config files:")
    budget_path = os.path.join(claude_dir, "claude-status-budget.json")
    if os.path.isfile(budget_path):
        try:
            with open(budget_path, "r", encoding="utf-8") as f:
                budget_data = json.load(f)
            print("  Budget: {} (valid)".format(budget_path))
            if isinstance(budget_data, dict):
                if "daily_budget_usd" in budget_data:
                    print("    daily_budget_usd: {}".format(budget_data["daily_budget_usd"]))
                if "compaction_threshold_pct" in budget_data:
                    print("    compaction_threshold_pct: {}".format(budget_data["compaction_threshold_pct"]))
        except (json.JSONDecodeError, IOError) as e:
            print("  Budget: {} (INVALID: {})".format(budget_path, e))
    else:
        print("  Budget: not configured")

    theme_path = os.path.join(claude_dir, "claude-status-theme.json")
    if os.path.isfile(theme_path):
        try:
            with open(theme_path, "r", encoding="utf-8") as f:
                json.load(f)
            print("  Theme:  {} (valid)".format(theme_path))
        except (json.JSONDecodeError, IOError) as e:
            print("  Theme:  {} (INVALID: {})".format(theme_path, e))
    else:
        print("  Theme:  not configured")
    print()

    # Permissions
    print("Permissions:")
    if os.path.isdir(claude_dir):
        print("  ~/.claude/: {}".format(
            "writable" if os.access(claude_dir, os.W_OK) else "NOT WRITABLE"
        ))
    else:
        print("  ~/.claude/: directory not found")
    tmp = tempfile.gettempdir()
    print("  Temp dir:   {} ({})".format(
        tmp, "writable" if os.access(tmp, os.W_OK) else "NOT WRITABLE"
    ))
    print()

    # Check git
    branch = get_branch()
    print("Git:")
    print("  Branch: {}".format(branch or "(not in a git repo)"))
    print()

    # Transcript health — useful when diagnosing why the `activity`
    # section is silently absent. Scans the most-recent transcript
    # under ~/.claude/projects/ so the user doesn't have to find one
    # by hand. Skipped silently if the projects dir doesn't exist or
    # no transcripts are found (legitimate case for first-run users).
    print("Transcript:")
    # If ~/.claude is a symlink to a non-existent target (e.g.
    # unmounted volume, archived dir), every downstream check
    # silently returns "file missing" with no hint that the root
    # cause is the broken symlink. Flag that here so users debugging
    # a vanished `activity` section see the actual root cause.
    if _CLAUDE_DIR_REAL != _CLAUDE_DIR and not os.path.exists(_CLAUDE_DIR_REAL):
        print("  WARNING: ~/.claude is a symlink to a non-existent target:")
        print("           {} -> {}".format(_CLAUDE_DIR, _CLAUDE_DIR_REAL))
        print("           Mount the target or fix the symlink to restore activity counting.")
    projects_dir = os.path.join(claude_dir, "projects")
    most_recent = None
    try:
        if os.path.isdir(projects_dir):
            candidates = []
            for project in os.listdir(projects_dir):
                project_path = os.path.join(projects_dir, project)
                if not os.path.isdir(project_path):
                    continue
                for name in os.listdir(project_path):
                    if not name.endswith(".jsonl"):
                        continue
                    full = os.path.join(project_path, name)
                    try:
                        candidates.append((os.path.getmtime(full), full))
                    except OSError:
                        continue
            if candidates:
                candidates.sort()
                most_recent = candidates[-1][1]
    except OSError:
        pass
    if most_recent is None:
        print("  No transcripts found under ~/.claude/projects/")
        print("  (The `activity` section needs transcript_path on stdin from Claude Code.)")
    else:
        try:
            size = os.path.getsize(most_recent)
            mtime = os.path.getmtime(most_recent)
            age = max(0, time.time() - mtime)
            print("  Most recent: {}".format(most_recent))
            print("  Size:        {} bytes".format(size))
            print("  Modified:    {:.0f}s ago".format(age))
            # Probe the activity counter with the status-returning
            # variant so users can distinguish "no activity yet" (idle)
            # from "parse failed / window too small" (giving-up). The
            # plain get_session_activity_count would lose that detail.
            count, status = _count_activity_with_status(most_recent)
            print("  Activity:    {} tool_use(s) since last user message".format(count))
            print("  Parse:       {}".format(status))
            # Probe the cache_age reader too so users debugging a
            # missing `cache_age` section can see whether the last
            # assistant timestamp is extractable and what age it
            # yields. A future-dated timestamp (clock skew) is reported
            # explicitly since the renderer hides it — otherwise the
            # section would silently vanish with no diagnostic trail.
            ts_ms = get_last_assistant_timestamp_ms(most_recent)
            if ts_ms is None:
                print("  Cache age:   no assistant timestamp in tail window")
            else:
                age_s = time.time() - ts_ms / 1000.0
                if age_s < 0:
                    print("  Cache age:   last assistant message is future-dated "
                          "by {:.0f}s (clock skew) — section hidden".format(-age_s))
                else:
                    print("  Cache age:   {:.0f}s since last assistant message".format(age_s))
        except (OSError, ValueError) as exc:
            # Narrow to expected failure modes; programmer errors
            # (AttributeError, ImportError) bubble up so they're seen.
            print("  Could not probe transcript: {}: {}".format(
                type(exc).__name__, exc))
    print()

    # Terminal capabilities — show both the naive shutil value AND
    # the value our fallback chain detects, so users can see whether
    # our recovery worked when Claude Code's subprocess context hid
    # the real width.
    print("Terminal:")
    term = os.environ.get("TERM", "(not set)")
    naive_cols = shutil.get_terminal_size((_COMPACT_LAYOUT_MIN_COLS, 24)).columns
    detected_cols, width_report = _detect_terminal_width_report()
    print("  TERM:    {}".format(term))
    print("  Columns: {} (shutil naive: {})".format(detected_cols, naive_cols))
    _margin = _fit_margin(width_report)
    print("  Fit width: {} (detected {} - safety margin {})".format(
        max(_TERM_WIDTH_MIN, detected_cols - _margin),
        detected_cols, _margin))
    cols = detected_cols
    if cols >= _FULL_LAYOUT_MIN_COLS:
        print("  Layout:  full (>= {} cols)".format(_FULL_LAYOUT_MIN_COLS))
    elif cols >= _COMPACT_LAYOUT_MIN_COLS:
        print("  Layout:  compact ({}-{} cols)".format(
            _COMPACT_LAYOUT_MIN_COLS, _FULL_LAYOUT_MIN_COLS - 1))
    else:
        print("  Layout:  narrow (< {} cols)".format(_COMPACT_LAYOUT_MIN_COLS))

    # Active layout thresholds (v0.7.0 #94): the conservative pair
    # (150/100) is the safe default. Relaxed pair (110/80) unlocks
    # only when BOTH gates pass — Claude Code version >= 2.1.141 AND
    # high-confidence width detection. Print the gate state so a
    # user troubleshooting "why don't I see the recovered sections
    # at 120 cols on 2.1.141?" can see which gate is failing without
    # reading source.
    #
    # `--doctor` runs without stdin, so we can only report the
    # conservative-default path here. The actual per-render gate
    # decision in render() depends on the stdin `version` field and
    # the actual width-detection winner — neither available outside
    # a live render. We document the gate logic so the user knows
    # what to check.
    version_gate_passes = False
    width_gate_passes = any("(winner" in status for _, status in width_report)
    relaxed_active = version_gate_passes and width_gate_passes
    print("  Thresholds: conservative full={} compact={} (relaxed full={} compact={})".format(
        _FULL_LAYOUT_MIN_COLS, _COMPACT_LAYOUT_MIN_COLS,
        _FULL_LAYOUT_MIN_COLS_RELAXED, _COMPACT_LAYOUT_MIN_COLS_RELAXED))
    print("  Relaxed gates (per render): version >= 2.1.141 AND high-confidence width")
    print("  In --doctor (no stdin): width_gate={} (version_gate is render-time only)".format(
        width_gate_passes))
    print("  Note:    precise width-aware fit further trims sections to fit")
    print("  Unicode: \u2588\u2591\u2593 \u2387 \ue0b0")
    # Per-step width-detection report. Shows which signal won and
    # which signals were rejected (including the 2.1.139 tput stub).
    # Useful when a user reports "my layout looks wrong on a wide
    # terminal" \u2014 they can paste this section to show whether tput
    # lied, /dev/tty was unreachable, etc.
    print("  Width detection chain:")
    for step_label, status in width_report:
        print("    {:32} {}".format(step_label, status))
    print()


def main():
    """Main entry point."""
    _force_utf8()

    parser = argparse.ArgumentParser(
        prog="claude-status",
        description="Beautiful status line for Claude Code",
    )
    parser.add_argument("--version", action="version", version="%(prog)s " + __version__)
    parser.add_argument("--demo", action="store_true", help="Show demo output for all themes")
    parser.add_argument("--install", action="store_true", help="Install into Claude Code settings")
    parser.add_argument("--uninstall", action="store_true", help="Remove from Claude Code settings")
    parser.add_argument("--setup", action="store_true", help="Interactive setup wizard")
    parser.add_argument("--doctor", action="store_true", help="Run diagnostics")
    parser.add_argument("--print-config", action="store_true",
                        dest="print_config",
                        help="Print install state in machine-readable form (for scripts/agents)")
    parser.add_argument("--subagent", action="store_true",
                        help="Render subagentStatusLine task rows (JSONL) "
                             "instead of the statusline")
    parser.add_argument("--theme", default="default",
                        choices=["default", "minimal", "powerline",
                                 "nord", "tokyo-night", "gruvbox", "rose-pine",
                                 "focus", "custom"],
                        help="Theme for this render (default: default). "
                             "Use --install --theme NAME or --setup to persist. "
                             "'custom' loads ~/.claude/claude-status-theme.json")

    args = parser.parse_args()

    if args.demo:
        cmd_demo()
        return

    if args.install:
        cmd_install(args.theme)
        return

    if args.uninstall:
        cmd_uninstall()
        return

    if args.setup:
        cmd_setup()
        return

    if args.doctor:
        cmd_doctor()
        return

    if args.print_config:
        cmd_print_config()
        return

    # Normal mode: read JSON from stdin, output statusline
    raw = ""  # pre-bind: stdin.read() itself can raise ValueError
    # (io.UnsupportedOperation on a closed stdin IS a ValueError
    # subclass), and the handler below dereferences `raw`.
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        # JSONL purity: in subagent mode (or anything that even LOOKS
        # like a truncated subagent payload) a bare "?" line would be
        # injected into the agent panel's JSONL stream. Print nothing
        # there; keep the long-standing "?" for the main hook.
        # '"tasks":' (with colon) so only a KEY position matches — a
        # truncated MAIN payload whose git branch is literally named
        # "tasks" must still get its long-standing "?".
        if not args.subagent and '"tasks":' not in (raw or ""):
            print("?")
        else:
            print("claude-status: undecodable subagent payload",
                  file=sys.stderr)
        return
    except KeyboardInterrupt:
        return

    # subagentStatusLine dispatch — BEFORE render()/_normalize, which
    # have side effects (effort-cache mirror, git subprocesses, spend
    # ledger) that must never run on the per-tick subagent hook.
    # --subagent is the documented interface; auto-detection is a
    # convenience fallback for users who pasted the bare command.
    if args.subagent or _is_subagent_payload(data):
        if not args.subagent:
            print("claude-status: subagent payload auto-detected; "
                  "prefer \"claude-status --subagent\" in "
                  "subagentStatusLine settings", file=sys.stderr)
        try:
            output = render_subagent(data, args.theme) \
                if _is_subagent_payload(data) else ""
        except Exception as exc:
            print("claude-status: subagent render error: {}".format(exc),
                  file=sys.stderr)
            output = ""
        if output:
            print(output)
        return

    try:
        output = render(data, args.theme)
    except Exception as exc:
        print("claude-status: render error: {}".format(exc), file=sys.stderr)
        output = ""
    if output:
        print(output)


if __name__ == "__main__":
    main()
