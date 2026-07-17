"""Comprehensive tests for claude-status — stdlib unittest only."""

import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
import unittest

# Force the responsive layout to pick the FULL layout by default in tests.
# shutil.get_terminal_size() honors COLUMNS/LINES before falling back, so
# setting these before importing claude_statusline.cli ensures render()
# exercises the full layout regardless of the host terminal width.
# Unconditional assignment (not setdefault) so a hostile CI value exported
# upstream can't silently shrink the layout and make tests pass for the
# wrong reason. Individual tests that want narrow/compact layouts set
# COLUMNS explicitly themselves and restore it in a finally block.
os.environ["COLUMNS"] = "250"
os.environ["LINES"] = "50"

# Add parent to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from claude_statusline import __version__
from claude_statusline.colors import (
    BOLD, BRIGHT_BLACK, BRIGHT_RED, CYAN, GREEN, RED, RESET, WHITE, YELLOW,
    colorize,
)
from claude_statusline.formatters import (
    fmt_burn_rate, fmt_cache_pct, fmt_cost, fmt_duration, fmt_lines, fmt_tokens,
)
from claude_statusline.bar import render_bar
from claude_statusline.git import get_branch
from claude_statusline.themes import THEMES, get_theme
from claude_statusline.cli import render, _render_sections, _settings_path

# Distinct sentinel meaning "omit this key entirely" in test helpers,
# kept separate from None so tests can exercise both "key absent" and
# "key present but null" — two different code paths in _normalize.
_SENTINEL = object()


# ─── Test isolation from the REAL ~/.claude/settings.json (#96) ─────────
#
# During v0.6.1 release verification the maintainer's real settings.json
# was found nulled mid-session — the suspected cause was an install/
# uninstall test writing to the real file instead of a tmpfile. The
# install/uninstall tests DO each monkey-patch cli._settings_path, but
# that is opt-in and a future test could forget it. We defend in depth
# two ways, both anchored here at module scope:
#
#   1. Redirect the production chokepoint centrally. cli._settings_path()
#      honors CLAUDE_STATUSLINE_SETTINGS_PATH; we point it at a temp file
#      for the whole module run, so even a test that forgets to patch
#      writes there, never to the real file.
#   2. Snapshot the real file's bytes (as a hash) in setUpModule before
#      any test runs, and assert it's unchanged in tearDownModule (which
#      runs after EVERY test — including the uninstall tests, which sort
#      after any guard test method would). Would have caught the original
#      incident immediately. TestSettingsIsolation pins the mechanisms.

import hashlib  # noqa: E402  (kept beside the isolation block it serves)

_REAL_SETTINGS_PATH = os.path.join(
    os.path.expanduser("~"), ".claude", "settings.json")
_real_settings_hash_before = None
_settings_redirect_dir = None
_prev_settings_env = None
_cache_redirect_dir = None
_prev_cache_dir_fn = None

# Distinct, never-None sentinel for "the real settings file exists but we
# could NOT read it" (permission denied, transient lock, etc.). This MUST
# stay distinct from None ("genuinely absent"): folding the two together
# would let a transient read failure at snapshot time mask a later
# deletion of the real file (None == None) — defeating this guard in
# exactly the present→absent #96 scenario it exists to catch.
_HASH_UNREADABLE = "<unreadable>"


def _hash_real_settings():
    """Return a sha256 hex digest of the real settings.json.

    Tri-state on purpose:
      - hex string       -> file read successfully
      - None             -> file genuinely absent (FileNotFoundError); a
                            valid untouched state for a contributor without
                            Claude Code installed ("stayed absent" == None).
      - _HASH_UNREADABLE -> file exists but is unreadable; kept distinct
                            from None so before/after compare meaningfully.
    """
    try:
        with open(_REAL_SETTINGS_PATH, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except FileNotFoundError:
        return None
    except OSError:
        return _HASH_UNREADABLE


def setUpModule():
    global _real_settings_hash_before, _settings_redirect_dir
    global _prev_settings_env, _cache_redirect_dir, _prev_cache_dir_fn
    _real_settings_hash_before = _hash_real_settings()
    # Redirect every unpatched settings read/write to a throwaway file.
    _settings_redirect_dir = tempfile.mkdtemp(prefix="claude-status-test-")
    _prev_settings_env = os.environ.get("CLAUDE_STATUSLINE_SETTINGS_PATH")
    os.environ["CLAUDE_STATUSLINE_SETTINGS_PATH"] = os.path.join(
        _settings_redirect_dir, "settings.json")
    # Redirect every unpatched CACHE read/write to a throwaway dir —
    # the v0.12.0 daily-spend ledger made this load-bearing: any render
    # test that passes session_id + cost triggers the budget path on a
    # machine with a real ~/.claude/claude-status-budget.json, and an
    # unredirected run would write phantom spend_* ledger files into
    # the REAL cache dir, inflating the maintainer's live day-spend
    # chip with test dollars until midnight (monotonic max — it cannot
    # self-correct). Same incident class as #96; same chokepoint fix.
    # Per-class setUp patches layer on top of this harmlessly.
    from claude_statusline import sessions as _sessions_mod
    _cache_redirect_dir = tempfile.mkdtemp(prefix="claude-status-cache-")
    _prev_cache_dir_fn = _sessions_mod._cache_dir
    _sessions_mod._cache_dir = lambda: _cache_redirect_dir


def tearDownModule():
    # The load-bearing regression assertion lives HERE, not in a test
    # method: tearDownModule provably runs after EVERY test in the module,
    # whereas a test method sorts alphabetically (a TestReal*/TestSettings*
    # class runs before TestUninstall*, so a method-only guard would miss
    # the very uninstall tests that caused the original #96 incident).
    # Compare the real file's bytes against the setUpModule snapshot; a
    # mismatch means some test wrote to the real ~/.claude/settings.json.
    after = _hash_real_settings()
    # Restore the env to its prior state (unset vs. prior value) and clean
    # the temp dir BEFORE asserting, so neither leaks if the assert raises.
    if _prev_settings_env is None:
        os.environ.pop("CLAUDE_STATUSLINE_SETTINGS_PATH", None)
    else:
        os.environ["CLAUDE_STATUSLINE_SETTINGS_PATH"] = _prev_settings_env
    if _settings_redirect_dir:
        import shutil as _shutil
        _shutil.rmtree(_settings_redirect_dir, ignore_errors=True)
    # Restore the cache-dir redirect and clean its temp dir (before the
    # assert below for the same leak-on-raise reason).
    if _prev_cache_dir_fn is not None:
        from claude_statusline import sessions as _sessions_mod
        _sessions_mod._cache_dir = _prev_cache_dir_fn
    if _cache_redirect_dir:
        import shutil as _shutil2
        _shutil2.rmtree(_cache_redirect_dir, ignore_errors=True)
    if after != _real_settings_hash_before:
        raise AssertionError(
            "A test mutated the real ~/.claude/settings.json! Some test "
            "exercised install/uninstall/setup without redirecting settings "
            "I/O to a tmpfile (monkey-patch cli._settings_path or set "
            "CLAUDE_STATUSLINE_SETTINGS_PATH). See #96. "
            "before={!r} after={!r}".format(
                _real_settings_hash_before, after))


class TestSettingsIsolation(unittest.TestCase):
    """#96 hardening contracts. The load-bearing 'real file unchanged'
    assertion lives in tearDownModule (so it runs last, after the
    uninstall tests); these tests pin the mechanisms that make it hold so
    a refactor can't silently regress them and re-expose the real file."""

    def test_settings_path_honors_env_override(self):
        import claude_statusline.cli as cli_mod
        prev = os.environ.get("CLAUDE_STATUSLINE_SETTINGS_PATH")
        # A deliberately non-existent placeholder string — we assert on the
        # RETURN VALUE only and never touch the filesystem. Do not "fix"
        # this into a tempfile; that would change what the test pins.
        sentinel = os.path.join("nonexistent-dir", "redir.json")
        try:
            os.environ["CLAUDE_STATUSLINE_SETTINGS_PATH"] = sentinel
            self.assertEqual(cli_mod._settings_path(), sentinel,
                "a non-blank override must win verbatim")
            # Blank / whitespace must NOT redirect — full-path equality to
            # the real path (not just suffix) so a dropped home prefix is
            # caught.
            for blank in ("", "   ", "\t", "\n"):
                os.environ["CLAUDE_STATUSLINE_SETTINGS_PATH"] = blank
                self.assertEqual(
                    cli_mod._settings_path(), _REAL_SETTINGS_PATH,
                    "blank override {!r} must fall through to real path"
                    .format(blank))
            # Unset (the production default) must also resolve to the real
            # path — the path every end user depends on.
            os.environ.pop("CLAUDE_STATUSLINE_SETTINGS_PATH", None)
            self.assertEqual(cli_mod._settings_path(), _REAL_SETTINGS_PATH,
                "unset override must resolve to the real ~/.claude path")
        finally:
            if prev is None:
                os.environ.pop("CLAUDE_STATUSLINE_SETTINGS_PATH", None)
            else:
                os.environ["CLAUDE_STATUSLINE_SETTINGS_PATH"] = prev

    def test_unpatched_install_writes_to_redirect_not_real(self):
        """The whole point of the chokepoint: an UNPATCHED cmd_install (no
        monkey-patch of _settings_path, relying solely on the env override)
        must write to the redirect and leave the real file byte-identical.
        Makes the manually-proven protection a permanent guard."""
        import claude_statusline.cli as cli_mod
        real_before = _hash_real_settings()
        prev = os.environ.get("CLAUDE_STATUSLINE_SETTINGS_PATH")
        with tempfile.TemporaryDirectory() as tmp:
            redirect = os.path.join(tmp, "nested", "settings.json")
            os.environ["CLAUDE_STATUSLINE_SETTINGS_PATH"] = redirect
            try:
                cli_mod.cmd_install("default")  # NOT monkey-patched
                self.assertTrue(os.path.exists(redirect),
                    "unpatched install must write to the env redirect")
                with open(redirect) as f:
                    self.assertEqual(
                        json.load(f)["statusLine"]["command"], "claude-status")
            finally:
                if prev is None:
                    os.environ.pop("CLAUDE_STATUSLINE_SETTINGS_PATH", None)
                else:
                    os.environ["CLAUDE_STATUSLINE_SETTINGS_PATH"] = prev
        self.assertEqual(_hash_real_settings(), real_before,
            "unpatched install must NOT touch the real settings file")


# ─── colors.py ────────────────────────────────────────────────────────

class TestColors(unittest.TestCase):
    def test_all_constants_are_nonempty_strings(self):
        from claude_statusline import colors
        for name in dir(colors):
            if name.isupper() and not name.startswith("_"):
                val = getattr(colors, name)
                self.assertIsInstance(val, str, "{} should be a string".format(name))
                self.assertTrue(len(val) > 0, "{} should be non-empty".format(name))

    def test_color_codes_follow_ansi_pattern(self):
        from claude_statusline import colors
        pattern = re.compile(r"^\033\[\d+m$")
        for name in dir(colors):
            if name.isupper() and not name.startswith("_"):
                val = getattr(colors, name)
                self.assertTrue(
                    pattern.match(val),
                    "{} = {!r} doesn't match ANSI pattern".format(name, val),
                )

    def test_colorize_wraps_text(self):
        result = colorize("hello", GREEN)
        self.assertIn("hello", result)
        self.assertTrue(result.startswith(GREEN))
        self.assertTrue(result.endswith(RESET))

    def test_colorize_multiple_codes(self):
        result = colorize("x", BOLD, RED)
        self.assertTrue(result.startswith(BOLD + RED))

    def test_colorize_empty_string(self):
        self.assertEqual(colorize("", GREEN), "")

    def test_colorize_none(self):
        self.assertEqual(colorize(None, GREEN), "")


# ─── formatters.py ────────────────────────────────────────────────────

class TestFmtTokens(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(fmt_tokens(0), "0")

    def test_small(self):
        self.assertEqual(fmt_tokens(999), "999")

    def test_one_k(self):
        self.assertEqual(fmt_tokens(1000), "1K")

    def test_1500(self):
        self.assertEqual(fmt_tokens(1500), "1.5K")

    def test_10k(self):
        self.assertEqual(fmt_tokens(10_000), "10K")

    def test_245k(self):
        self.assertEqual(fmt_tokens(245_000), "245K")

    def test_1_5m(self):
        self.assertEqual(fmt_tokens(1_500_000), "1.5M")

    def test_10m(self):
        self.assertEqual(fmt_tokens(10_000_000), "10M")

    def test_999m(self):
        self.assertEqual(fmt_tokens(999_000_000), "999M")

    def test_1m_no_trailing_zero(self):
        """1_000_000 must render "1M", not "1.0M" — same trailing-zero
        strip as the K branch. Every-render sight on 1M-window models."""
        self.assertEqual(fmt_tokens(1_000_000), "1M")

    def test_4m_no_trailing_zero(self):
        self.assertEqual(fmt_tokens(4_000_000), "4M")

    def test_2_5m_keeps_decimal(self):
        """The strip must not eat meaningful decimals."""
        self.assertEqual(fmt_tokens(2_500_000), "2.5M")

    def test_k_m_seam(self):
        """999_999 sits at the K/M branch seam."""
        self.assertEqual(fmt_tokens(999_999), "999K")

    def test_9_999_999_rounds_to_10m(self):
        """"{:.1f}" rounds 9_999_999 to "10.0"; the strip reduces it
        to "10M", converging with the >= 10M integer branch — the one
        input where the strip handles a two-digit ".0"."""
        self.assertEqual(fmt_tokens(9_999_999), "10M")

    def test_none(self):
        self.assertEqual(fmt_tokens(None), "?")


class TestFmtCost(unittest.TestCase):
    def test_sub_cent(self):
        result = fmt_cost(0.005)
        self.assertIn("0.5", result)
        self.assertIn("c", result)

    def test_cents(self):
        self.assertEqual(fmt_cost(0.50), "$0.50")

    def test_dollars(self):
        self.assertEqual(fmt_cost(1.5), "$1.5")

    def test_large(self):
        self.assertEqual(fmt_cost(12.3), "$12")

    def test_none(self):
        self.assertEqual(fmt_cost(None), "?")

    def test_zero(self):
        result = fmt_cost(0)
        self.assertIn("c", result)


class TestFmtDuration(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(fmt_duration(0), "0s")

    def test_seconds(self):
        self.assertEqual(fmt_duration(45_000), "45s")

    def test_minutes(self):
        self.assertEqual(fmt_duration(125_000), "2m05s")

    def test_hours(self):
        self.assertEqual(fmt_duration(3_700_000), "1h01m")

    def test_none(self):
        self.assertEqual(fmt_duration(None), "?")


class TestFmtBurnRate(unittest.TestCase):
    def test_normal(self):
        # 60000 tokens in 60000ms = 1 min → 60K/min
        result = fmt_burn_rate(60_000, 60_000)
        self.assertIn("/min", result)

    def test_none_tokens(self):
        self.assertEqual(fmt_burn_rate(None, 1000), "?")

    def test_none_duration(self):
        self.assertEqual(fmt_burn_rate(1000, None), "?")

    def test_zero_duration(self):
        self.assertEqual(fmt_burn_rate(1000, 0), "?")


class TestFmtCostRate(unittest.TestCase):
    """fmt_cost_rate projects session cost to $/hr ("$3.6/hr").
    Empty string means "hide the section" — every meaningless or
    garbage input must land there, never an exception."""

    def test_normal(self):
        # $0.73 over 12m05s -> ~$3.62/hr -> fmt_cost one-decimal form
        from claude_statusline.formatters import fmt_cost_rate
        self.assertEqual(fmt_cost_rate(0.73, 725_000), "$3.6/hr")

    def test_exact_hour(self):
        from claude_statusline.formatters import fmt_cost_rate
        self.assertEqual(fmt_cost_rate(5.0, 3_600_000), "$5.0/hr")

    def test_cheap_session_cents(self):
        """Sub-penny rates reuse fmt_cost's cents form."""
        from claude_statusline.formatters import fmt_cost_rate
        self.assertEqual(fmt_cost_rate(0.0002, 120_000), "0.6c/hr")

    def test_big_rate_whole_dollars(self):
        from claude_statusline.formatters import fmt_cost_rate
        self.assertEqual(fmt_cost_rate(12.0, 3_600_000), "$12/hr")

    def test_sub_minute_hidden(self):
        """Early-session extrapolation is absurd; hidden under 60s."""
        from claude_statusline.formatters import fmt_cost_rate
        self.assertEqual(fmt_cost_rate(0.50, 59_999), "")

    def test_exactly_at_gate_shows(self):
        """Exact value pinned: $0.50 over exactly 1 minute is $30/hr.
        Pins both the arithmetic and the >= (not >) gate direction."""
        from claude_statusline.formatters import fmt_cost_rate
        self.assertEqual(fmt_cost_rate(0.50, 60_000), "$30/hr")

    def test_zero_and_negative_cost_hidden(self):
        from claude_statusline.formatters import fmt_cost_rate
        self.assertEqual(fmt_cost_rate(0, 3_600_000), "")
        self.assertEqual(fmt_cost_rate(-1.0, 3_600_000), "")

    def test_missing_and_garbage_hidden(self):
        from claude_statusline.formatters import fmt_cost_rate
        for cost, dur in ((None, None), (None, 100_000), (1.0, None),
                          ("abc", 100_000), (1.0, "xyz"), ({}, []),
                          (float("nan"), 100_000), (1.0, float("nan")),
                          (float("inf"), 100_000), (1.0, float("inf"))):
            self.assertEqual(fmt_cost_rate(cost, dur), "",
                "cost={!r} dur={!r} must hide".format(cost, dur))


class TestFmtLines(unittest.TestCase):
    def test_both(self):
        self.assertEqual(fmt_lines(10, 5), "+10 -5")

    def test_added_only(self):
        self.assertEqual(fmt_lines(10, 0), "+10")

    def test_removed_only(self):
        self.assertEqual(fmt_lines(0, 5), "-5")

    def test_neither(self):
        self.assertEqual(fmt_lines(0, 0), "")

    def test_none(self):
        self.assertEqual(fmt_lines(None, None), "")


class TestFmtCachePct(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(fmt_cache_pct(80, 100), "80%")

    def test_zero_total(self):
        self.assertEqual(fmt_cache_pct(80, 0), "")

    def test_none(self):
        self.assertEqual(fmt_cache_pct(None, 100), "")


# ─── bar.py ───────────────────────────────────────────────────────────

class TestRenderBar(unittest.TestCase):
    def test_zero(self):
        bar = render_bar(0, 20)
        self.assertIn("[", bar)
        self.assertIn("]", bar)

    def test_full(self):
        bar = render_bar(100, 20)
        self.assertIn("[", bar)

    def test_half(self):
        bar = render_bar(50, 20)
        self.assertIn("[", bar)

    def test_none(self):
        self.assertEqual(render_bar(None, 20), "")

    def test_over_100(self):
        bar = render_bar(150, 20)
        self.assertIn("[", bar)

    def test_negative(self):
        bar = render_bar(-10, 20)
        self.assertIn("[", bar)

    def test_custom_theme(self):
        theme = {
            "bar_filled": "#",
            "bar_empty": ".",
            "bar_left": "<",
            "bar_right": ">",
        }
        bar = render_bar(50, 10, theme)
        self.assertIn("<", bar)
        self.assertIn(">", bar)


class TestBarCtxWarningAlignment(unittest.TestCase):
    """The bar's red "danger" boundary and the !CTX badge threshold
    must agree. Before v0.10.0, `_bar_color` went red at 86+ while
    !CTX fired at >= 85 — at exactly 85% users saw a yellow "caution"
    bar beside a red danger badge. `_bar_color` can't import the
    threshold from cli (circular import), so this cross-module test
    is what keeps the two constants in lockstep."""

    def test_red_starts_exactly_at_ctx_threshold(self):
        from claude_statusline.bar import _bar_color
        from claude_statusline.cli import CTX_WARNING_THRESHOLD_PCT
        from claude_statusline import colors
        self.assertEqual(_bar_color(CTX_WARNING_THRESHOLD_PCT), colors.RED,
            "bar must be red at the exact !CTX threshold")
        self.assertEqual(_bar_color(CTX_WARNING_THRESHOLD_PCT - 1), colors.YELLOW,
            "one point below the threshold is still caution-yellow")

    def test_color_bands(self):
        from claude_statusline.bar import _bar_color
        from claude_statusline import colors
        self.assertEqual(_bar_color(0), colors.GREEN)
        self.assertEqual(_bar_color(60), colors.GREEN)
        self.assertEqual(_bar_color(61), colors.YELLOW)
        self.assertEqual(_bar_color(100), colors.RED)


class TestContextSizeLabel(unittest.TestCase):
    """context_size renders via fmt_tokens so a 1M window shows "(1M)"
    — not the pre-1M-era "(1000K)" integer-division label."""

    def _plain(self, s):
        return re.sub(r"\x1b\[[0-9;]*m", "", s)

    def _render_ctx(self, size):
        import claude_statusline.cli as cli_mod
        orig_line2 = THEMES["default"]["line2"]
        orig_branch = cli_mod.get_branch
        cli_mod.get_branch = lambda: "main"
        try:
            THEMES["default"]["line2"] = ["context_size", "branch"]
            data = {
                "git_branch": "main",
                "context_window": {"context_window_size": size,
                                   "used_percentage": 10},
            }
            return self._plain(cli_mod.render(data, "default"))
        finally:
            THEMES["default"]["line2"] = orig_line2
            cli_mod.get_branch = orig_branch

    def test_1m_window(self):
        self.assertIn("(1M)", self._render_ctx(1_000_000))

    def test_200k_window(self):
        self.assertIn("(200K)", self._render_ctx(200_000))

    def test_500k_window(self):
        self.assertIn("(500K)", self._render_ctx(500_000))

    def test_sub_1000_window_exact(self):
        """Below 1000 the label stays the exact number — pins the seam
        the fmt_tokens refactor removed (old code special-cased it)."""
        self.assertIn("(950)", self._render_ctx(950))

    def test_non_numeric_window_hidden_no_crash(self):
        """A garbage context_window_size must hide the section, not
        crash render — _safe_num gate (house rule for external JSON)."""
        out = self._render_ctx("abc")
        self.assertNotIn("(", out.split("⎇")[0])  # no ( chip before branch
        self.assertIn("main", out)  # render itself succeeded

    def test_nan_window_hidden_no_crash(self):
        """json.loads accepts bare NaN; NaN is truthy and would reach
        int() without the isfinite gate. Must hide, not crash."""
        out = self._render_ctx(float("nan"))
        self.assertIn("main", out)
        self.assertNotIn("nan", out.lower())

    def test_infinity_window_hidden_no_crash(self):
        out = self._render_ctx(float("inf"))
        self.assertIn("main", out)
        self.assertNotIn("inf", out.lower())


class TestCostRateSection(unittest.TestCase):
    """End-to-end `cost_rate` section: "~$3.6/hr" projection from
    cost.total_cost_usd / cost.total_duration_ms. Opt-in via custom
    theme; hidden on every degrade path (fmt_cost_rate owns the gates,
    these tests pin the section wiring)."""

    def _plain(self, s):
        return re.sub(r"\x1b\[[0-9;]*m", "", s)

    def _render(self, cost_obj):
        import claude_statusline.cli as cli_mod
        orig_line2 = THEMES["default"]["line2"]
        orig_branch = cli_mod.get_branch
        cli_mod.get_branch = lambda: "main"
        try:
            THEMES["default"]["line2"] = ["cost_rate", "branch"]
            data = {"git_branch": "main"}
            if cost_obj is not _SENTINEL:
                data["cost"] = cost_obj
            return self._plain(cli_mod.render(data, "default"))
        finally:
            THEMES["default"]["line2"] = orig_line2
            cli_mod.get_branch = orig_branch

    def test_renders_projection(self):
        out = self._render(
            {"total_cost_usd": 0.73, "total_duration_ms": 725_000})
        self.assertIn("~$3.6/hr", out)

    def test_tilde_prefix(self):
        """The tilde marks it as a projection — pin it so a refactor
        doesn't silently turn the chip into a bill-looking number.
        The startswith check discriminates properly: it fails for a
        missing tilde AND for a doubled one, unlike a substring
        assertion (\"~~$5.0/hr\" would still contain \"~$5.0/hr\")."""
        out = self._render(
            {"total_cost_usd": 5.0, "total_duration_ms": 3_600_000})
        self.assertIn("~$5.0/hr", out)
        chip_lines = [l for l in out.split("\n") if "/hr" in l]
        self.assertTrue(chip_lines and chip_lines[0].startswith("~$5.0/hr"),
                        "chip must start with exactly one tilde: {!r}".format(chip_lines))

    def test_hidden_when_cost_absent(self):
        self.assertNotIn("/hr", self._render(_SENTINEL))

    def test_hidden_sub_minute_session(self):
        out = self._render(
            {"total_cost_usd": 0.50, "total_duration_ms": 30_000})
        self.assertNotIn("/hr", out)

    def test_hidden_zero_cost(self):
        out = self._render(
            {"total_cost_usd": 0, "total_duration_ms": 3_600_000})
        self.assertNotIn("/hr", out)

    def test_garbage_cost_object_no_crash(self):
        """cost as a bare string (older schemas / malformed upstream)
        must hide the section, not crash — _normalize's isinstance
        guard plus _safe_num coercion both stand in the way. NaN and
        Infinity (valid json.loads literals) are included: _safe_num
        rejects non-finite values at the chokepoint."""
        for garbage in ("expensive", 42, ["x"], {"total_cost_usd": "abc"},
                        {"total_cost_usd": float("nan"),
                         "total_duration_ms": 100_000},
                        {"total_cost_usd": 1.0,
                         "total_duration_ms": float("inf")}):
            out = self._render(garbage)
            self.assertNotIn("/hr", out,
                "cost={!r} must not render a rate".format(garbage))
            self.assertIn("main", out)

    def test_cost_rate_is_compact_droppable(self):
        from claude_statusline.cli import (
            _COMPACT_DROP, _NARROW_DROP, _FIT_DROP_PRIORITY)
        self.assertIn("cost_rate", _COMPACT_DROP)
        self.assertIn("cost_rate", _NARROW_DROP)
        self.assertIn("cost_rate", _FIT_DROP_PRIORITY)

    def test_subpenny_rate_hidden_not_zero_chip(self):
        """A positive-but-below-resolution rate must hide rather than
        render a zero-looking "~0c/hr" chip (contradicts the zero-is-
        noise gate). $0.02 over ~116 days projects under 0.1c/hr."""
        from claude_statusline.formatters import fmt_cost_rate
        self.assertEqual(fmt_cost_rate(0.02, 10_000_000_000), "")
        # Just above the resolution floor still shows.
        self.assertEqual(fmt_cost_rate(0.0006, 3_600_000), "0.1c/hr")

    def test_garbage_duration_sections_no_crash(self):
        """Garbage total_duration_ms / total_api_duration_ms rendered
        through their ACTUAL consuming sections (duration, latency,
        speed) — pre-v0.11.0 fmt_duration("xyz") crashed render().
        The cost_rate-only fixtures above never exercise these."""
        import claude_statusline.cli as cli_mod
        orig_line2 = THEMES["default"]["line2"]
        orig_branch = cli_mod.get_branch
        cli_mod.get_branch = lambda: "main"
        try:
            THEMES["default"]["line2"] = [
                "duration", "latency", "speed", "branch"]
            out = self._plain(cli_mod.render({
                "git_branch": "main",
                "cost": {"total_duration_ms": "xyz",
                         "total_api_duration_ms": ["nope"]},
            }, "default"))
            self.assertIn("main", out)
            self.assertNotIn("xyz", out)
        finally:
            THEMES["default"]["line2"] = orig_line2
            cli_mod.get_branch = orig_branch

    def test_stringified_numerics_render_normally(self):
        """CHANGELOG claim pinned e2e: numeric strings coerce and
        render — "0.5" cost shows $0.50, "725000" duration shows
        12m05s. Guards against a future over-tightening of _safe_num
        (e.g. an isinstance gate) blanking string-emitting upstreams."""
        import claude_statusline.cli as cli_mod
        orig_line2 = THEMES["default"]["line2"]
        orig_branch = cli_mod.get_branch
        cli_mod.get_branch = lambda: "main"
        try:
            THEMES["default"]["line2"] = ["duration", "cost_rate", "branch"]
            out = self._plain(cli_mod.render({
                "git_branch": "main",
                "cost": {"total_cost_usd": "0.5",
                         "total_duration_ms": "725000"},
            }, "default"))
            self.assertIn("$0.50", out)      # cost section (line1)
            self.assertIn("12m05s", out)     # duration section (line2)
            # 0.5/(725s/3600s) = $2.48/hr; fmt_cost's one-decimal
            # branch ROUNDS, so the chip reads $2.5, not $2.4.
            self.assertIn("~$2.5/hr", out)
        finally:
            THEMES["default"]["line2"] = orig_line2
            cli_mod.get_branch = orig_branch


class TestDailySpendLedger(unittest.TestCase):
    """Per-(day, session) spend ledger powering the budget section's
    daily semantics (v0.12.0). Every scenario here traces to a finding
    from the adversarial design review — see the docstring of
    record_and_get_daily_spend for the model."""

    def setUp(self):
        import shutil as shutil_mod
        from claude_statusline import sessions as sessions_mod
        self._shutil = shutil_mod
        self._sess = sessions_mod
        self._tmp = tempfile.mkdtemp(prefix="claude-status-ledger-")
        self._orig_cache_dir = sessions_mod._cache_dir
        sessions_mod._cache_dir = lambda: self._tmp
        # Determinism: pin "now" to local NOON of the current day.
        # With real time.time(), a suite run in the minutes after
        # local midnight would misclassify "started today" (start ≈
        # now - duration lands on yesterday) and hard-fail several
        # attribution tests — the project's determinism rule forbids
        # that. Noon keeps every duration in these tests (< 12h) on
        # today's side of the boundary.
        lt = time.localtime()
        self._noon = time.mktime(
            (lt.tm_year, lt.tm_mon, lt.tm_mday, 12, 0, 0, 0, 0, -1))
        self._day = time.strftime("%Y-%m-%d", time.localtime(self._noon))

    def tearDown(self):
        self._sess._cache_dir = self._orig_cache_dir
        self._shutil.rmtree(self._tmp, ignore_errors=True)

    def _rec(self, sid, cost, dur_ms, now=None):
        return self._sess.record_and_get_daily_spend(
            sid, cost, dur_ms, _now=self._noon if now is None else now)

    # --- attribution rules --------------------------------------------

    def test_started_today_full_attribution(self):
        """Session started today: base=0, whole cumulative counts.
        This is also the upgrade-day honesty case."""
        total, found = self._rec("sid-a", 3.0, 600_000)
        self.assertTrue(found)
        self.assertAlmostEqual(total, 3.0)

    def test_midnight_spanning_growth_only(self):
        """Session started 30h ago: base captured at first sight, only
        today's growth counts — the over-attribution the base rule
        exists to prevent."""
        total, _ = self._rec("sid-b", 8.0, 30 * 3600 * 1000)
        self.assertAlmostEqual(total, 0.0)
        total, _ = self._rec("sid-b", 8.6, 30 * 3600 * 1000 + 60_000)
        self.assertAlmostEqual(total, 0.6)

    def test_missing_duration_conservative(self):
        """No duration signal -> base=cur (undercount one turn, never
        overcount)."""
        total, _ = self._rec("sid-c", 1.5, None)
        self.assertAlmostEqual(total, 0.0)
        total, _ = self._rec("sid-c", 2.0, None)
        self.assertAlmostEqual(total, 0.5)

    def test_monotonic_no_regression_on_stale_rerender(self):
        self._rec("sid-d", 3.0, 600_000)
        total, _ = self._rec("sid-d", 2.9, 610_000)  # stale/lower
        self.assertAlmostEqual(total, 3.0)

    def test_multi_session_sum(self):
        self._rec("sid-e", 3.0, 600_000)
        total, _ = self._rec("sid-f", 2.5, 300_000)
        self.assertAlmostEqual(total, 5.5)

    def test_negative_cost_clamped(self):
        """Garbage negative cur must not create phantom spend when a
        later legit value arrives (review finding: base=-3 then cur=2
        would contribute 5). Exact value pinned: the clamp writes
        {cost:0, base:0}, then cost 2 contributes exactly 2.0 — a
        range assertion would also pass an over-clamp that silently
        dropped the legitimate spend."""
        self._rec("sid-g", -3.0, 60_000)
        total, _ = self._rec("sid-g", 2.0, 120_000)
        self.assertAlmostEqual(total, 2.0)

    # --- robustness ----------------------------------------------------

    def test_corrupt_and_garbage_files_skipped(self):
        self._rec("sid-h", 4.0, 600_000)
        day = self._day  # same pinned clock as the recording calls
        for name, content in (
            ("spend_{}_aaaaaaaaaaaa.json".format(day), "{not json"),
            ("spend_{}_bbbbbbbbbbbb.json".format(day), "[1,2]"),
            ("spend_{}_cccccccccccc.json".format(day),
             json.dumps({"cost": "abc", "base": 0})),
            ("spend_{}_dddddddddddd.json".format(day),
             json.dumps({"cost": float("nan"), "base": 0})),
        ):
            with open(os.path.join(self._tmp, name), "w") as f:
                f.write(content)
        total, _ = self._rec("sid-h", 4.0, 600_000)
        self.assertAlmostEqual(total, 4.0)

    def test_yesterday_files_not_summed(self):
        """Day boundary via the _now seam: an entry recorded 'two days
        ago' must not appear in today's total."""
        self._rec("sid-i", 9.0, 60_000, now=self._noon - 2 * 86400)
        total, found = self._rec("sid-j", 1.0, 60_000)
        self.assertAlmostEqual(total, 1.0)
        self.assertTrue(found)

    def test_shared_sid_interleave_self_heals(self):
        """Two processes sharing one session_id (double resume) can
        transiently regress each other via max(); the file must never
        go NEGATIVE in contribution and must self-heal once the higher
        counter writes again."""
        self._rec("sid-k", 5.0, 600_000)   # process A
        self._rec("sid-k", 6.0, 650_000)   # process B, higher
        total, _ = self._rec("sid-k", 5.5, 700_000)  # A again, lower
        self.assertGreaterEqual(total, 0.0)
        total, _ = self._rec("sid-k", 6.2, 750_000)  # B recovers
        self.assertAlmostEqual(total, 6.2)

    def test_no_session_id_live_contribution_still_counts(self):
        """Silent-failure review: a chip labeled day: must NEVER
        exclude the live session. With no usable sid the contribution
        is computed in memory — 2.0 (other) + 99.0 (live, started
        today) = 101.0, NOT 2.0."""
        self._rec("sid-l", 2.0, 60_000)
        total, found = self._rec("", 99.0, 60_000)
        self.assertTrue(found)
        self.assertAlmostEqual(total, 101.0)

    def test_no_sid_midnight_spanning_growth_only_in_memory(self):
        """The in-memory path applies the SAME attribution rule: a
        midnight-spanning session (started 30h ago) with no usable sid
        contributes 0, not its full cumulative — a cli-side raw-cost
        fallback would have over-attributed here."""
        self._rec("sid-m", 2.0, 60_000)
        total, found = self._rec("", 50.0, 30 * 3600 * 1000)
        self.assertTrue(found)
        self.assertAlmostEqual(total, 2.0)

    def test_empty_ledger_not_found(self):
        total, found = self._rec("", None, None)
        self.assertFalse(found)
        self.assertAlmostEqual(total, 0.0)

    def test_shared_tempdir_fallback_skips_ledger(self):
        """When _cache_dir degrades to the SHARED temp root, ledger IO
        must be skipped entirely: no spend file is written (privacy),
        no foreign spend_* files are summed (poisoning), and the live
        session still counts in memory."""
        self._sess._cache_dir = lambda: tempfile.gettempdir()
        # A poisoned file in the shared root must NOT be readable into
        # the total. Plant one with a unique sid hash, then verify.
        poison = os.path.join(
            tempfile.gettempdir(),
            "spend_{}_feedfacefeed.json".format(self._day))
        with open(poison, "w") as f:
            f.write(json.dumps({"cost": 500.0, "base": 0.0}))
        try:
            total, found = self._rec("sid-n", 3.0, 60_000)
            self.assertTrue(found)
            self.assertAlmostEqual(total, 3.0)  # own only; poison ignored
            # And nothing was written for our sid into the shared root.
            import hashlib as _h
            sid12 = _h.md5(b"sid-n").hexdigest()[:12]
            own = os.path.join(
                tempfile.gettempdir(),
                "spend_{}_{}.json".format(self._day, sid12))
            self.assertFalse(os.path.exists(own),
                             "ledger must not write into the shared temp root")
        finally:
            os.unlink(poison)

    def test_unreachable_cache_dir_degrades(self):
        """Nonexistent cache dir: writes swallowed, scan OSError caught,
        live contribution still returned in memory."""
        self._sess._cache_dir = lambda: os.path.join(
            self._tmp, "does", "not", "exist")
        total, found = self._rec("sid-o", 2.5, 60_000)
        self.assertTrue(found)
        self.assertAlmostEqual(total, 2.5)

    def test_tmp_leftover_ignored(self):
        """A crash-orphaned .json.tmp must be excluded by the reader's
        endswith('.json') filter — pin, not a bug."""
        self._rec("sid-p", 1.0, 60_000)
        leftover = os.path.join(
            self._tmp, "spend_{}_aaaabbbbcccc.json.tmp".format(self._day))
        with open(leftover, "w") as f:
            f.write(json.dumps({"cost": 900.0, "base": 0.0}))
        total, _ = self._rec("sid-p", 1.0, 60_000)
        self.assertAlmostEqual(total, 1.0)

    def test_cost_none_sid_present_reader_only(self):
        """cost=None with a sid: writer skips, no in-memory contribution,
        but other sessions' entries still sum."""
        self._rec("sid-q", 4.0, 60_000)
        total, found = self._sess.record_and_get_daily_spend(
            "sid-r", None, None, _now=self._noon)
        self.assertTrue(found)
        self.assertAlmostEqual(total, 4.0)


class TestBudgetSectionDaily(unittest.TestCase):
    """End-to-end budget chip with daily semantics: day: label,
    summed numerator, color bands on the TOTAL, scope escape hatch,
    and the honest lower-bound degrade."""

    def _plain(self, s):
        return re.sub(r"\x1b\[[0-9;]*m", "", s)

    def setUp(self):
        import shutil as shutil_mod
        import claude_statusline.cli as cli_mod
        from claude_statusline import sessions as sessions_mod
        self._shutil = shutil_mod
        self._cli = cli_mod
        self._sess = sessions_mod
        self._tmp = tempfile.mkdtemp(prefix="claude-status-budget-")
        self._orig_cache_dir = sessions_mod._cache_dir
        sessions_mod._cache_dir = lambda: self._tmp
        self._orig_budget = cli_mod.get_budget_config
        self._orig_scope = cli_mod.get_budget_scope
        self._orig_branch = cli_mod.get_branch
        cli_mod.get_budget_config = lambda: 10.0
        cli_mod.get_budget_scope = lambda: "daily"
        cli_mod.get_branch = lambda: "main"
        self._orig_line1 = THEMES["default"]["line1"]
        THEMES["default"]["line1"] = ["budget"]
        # Determinism: pin the ledger clock to local noon (see
        # TestDailySpendLedger.setUp for why — midnight would flip the
        # started-today classification). cli.render has no _now
        # parameter, so wrap the imported name at the cli module level.
        lt = time.localtime()
        self._noon = time.mktime(
            (lt.tm_year, lt.tm_mon, lt.tm_mday, 12, 0, 0, 0, 0, -1))
        self._orig_record = cli_mod.record_and_get_daily_spend
        cli_mod.record_and_get_daily_spend = (
            lambda sid, c, d: self._sess.record_and_get_daily_spend(
                sid, c, d, _now=self._noon))

    def _seed(self, sid, cost, dur):
        self._sess.record_and_get_daily_spend(sid, cost, dur, _now=self._noon)

    def tearDown(self):
        self._sess._cache_dir = self._orig_cache_dir
        self._cli.get_budget_config = self._orig_budget
        self._cli.get_budget_scope = self._orig_scope
        self._cli.get_branch = self._orig_branch
        self._cli.record_and_get_daily_spend = self._orig_record
        THEMES["default"]["line1"] = self._orig_line1
        self._shutil.rmtree(self._tmp, ignore_errors=True)

    def _render(self, sid, cost, dur):
        data = {"git_branch": "main", "session_id": sid,
                "context_window": {"used_percentage": 10}}
        if cost is not None:
            data["cost"] = {"total_cost_usd": cost,
                            "total_duration_ms": dur}
        return self._plain(self._cli.render(data, "default"))

    def test_day_label_and_sum(self):
        self._sess.record_and_get_daily_spend("other-sess", 4.0, 600_000)
        out = self._render("this-sess", 3.4, 700_000)
        self.assertIn("day:$7.4/$10", out)

    def test_color_band_on_total_not_session(self):
        """$4 (other) + $5.2 (this) = $9.2 of $10 -> >=90% band. The
        pre-v0.12.0 bug would have used $5.2 (52%, green)."""
        self._sess.record_and_get_daily_spend("other-sess", 4.0, 600_000)
        raw = self._cli.render({
            "git_branch": "main", "session_id": "this-sess",
            "cost": {"total_cost_usd": 5.2, "total_duration_ms": 700_000},
            "context_window": {"used_percentage": 10}}, "default")
        self.assertIn("day:$9.2/$10", self._plain(raw))
        self.assertIn(BRIGHT_RED, raw)

    def test_upgrade_day_lower_bound(self):
        """Empty ledger + live session (started today) -> live cost as
        the honest partial day total, same day: label."""
        out = self._render("fresh-sess", 2.1, 400_000)
        self.assertIn("day:$2.1/$10", out)

    def test_no_session_id_still_day_label(self):
        """Writer can't record without a sid; the live cost is still a
        true lower bound and keeps the day: label (meaning never
        switches — design review required this)."""
        out = self._render("", 2.1, 400_000)
        self.assertIn("day:$2.1/$10", out)

    def test_scope_session_restores_old_chip(self):
        self._cli.get_budget_scope = lambda: "session"
        self._sess.record_and_get_daily_spend("other-sess", 4.0, 600_000)
        out = self._render("this-sess", 3.4, 700_000)
        self.assertIn("$3.4/$10", out)
        self.assertNotIn("day:", out)

    def test_hidden_without_budget(self):
        self._cli.get_budget_config = lambda: None
        out = self._render("this-sess", 3.4, 700_000)
        self.assertNotIn("/$", out)

    def test_hidden_no_cost_no_ledger(self):
        out = self._render("this-sess", None, None)
        self.assertNotIn("day:", out)

    def test_no_cost_but_others_spent_shows_day_total(self):
        """Live session has no cost yet, but other sessions spent today
        — the chip still shows the day total (the cli comment promises
        this; previously untested)."""
        self._seed("other-sess", 4.0, 600_000)
        out = self._render("this-sess", None, None)
        self.assertIn("day:$4.0/$10", out)

    def test_garbage_duration_never_crashes_render(self):
        """time.localtime raises OverflowError/OSError for epoch values
        outside time_t range — a garbage duration like 9e18 ms must
        degrade to the conservative base, not blank the statusline.
        (Code-review finding, reproduced before fixing.)"""
        for bad_dur in (9e18, 1.8e15):
            out = self._render("weird-sess-{}".format(bad_dur), 2.0, bad_dur)
            self.assertIn("main", out)  # render survived
            # Conservative base=cur -> contribution 0 -> chip shows $0
            # or is present; the essential assertion is no crash.


class TestBudgetScopeConfig(unittest.TestCase):
    """get_budget_scope(): 'daily' default, 'session' honored, garbage
    and stale cached dicts (pre-v0.12.0, key absent) fall to daily."""

    def test_default_daily(self):
        from claude_statusline import sessions as sess
        orig = sess._read_status_config
        sess._read_status_config = lambda: {"budget": 10.0}
        try:
            self.assertEqual(sess.get_budget_scope(), "daily")
        finally:
            sess._read_status_config = orig

    def test_session_honored(self):
        from claude_statusline import sessions as sess
        orig = sess._read_status_config
        sess._read_status_config = lambda: {"budget_scope": "session"}
        try:
            self.assertEqual(sess.get_budget_scope(), "session")
        finally:
            sess._read_status_config = orig

    def test_garbage_falls_to_daily(self):
        from claude_statusline import sessions as sess
        orig = sess._read_status_config
        for bad in ("weekly", 42, None, ["session"]):
            sess._read_status_config = lambda b=bad: {"budget_scope": b}
            try:
                self.assertEqual(sess.get_budget_scope(), "daily")
            finally:
                sess._read_status_config = orig

    def test_scope_parsed_from_real_config_file(self):
        """End-to-end through the ACTUAL file parse in
        _read_status_config — the unit stubs above never execute the
        `data.get("budget_scope") == "session"` branch, so a typo
        there would ship green without this test."""
        import shutil as shutil_mod
        from claude_statusline import sessions as sess
        tmp_claude = tempfile.mkdtemp(prefix="claude-status-scope-")
        orig_dir = sess._CLAUDE_DIR
        sess._CLAUDE_DIR = tmp_claude
        try:
            with open(os.path.join(tmp_claude, "claude-status-budget.json"),
                      "w", encoding="utf-8") as f:
                json.dump({"daily_budget_usd": 10,
                           "budget_scope": "session"}, f)
            # Bust the 30s shared config cache so the file is re-read.
            try:
                os.remove(sess._cache_path("status_config"))
            except OSError:
                pass
            self.assertEqual(sess.get_budget_scope(), "session")
            self.assertEqual(sess.get_budget_config(), 10.0)
        finally:
            sess._CLAUDE_DIR = orig_dir
            try:
                os.remove(sess._cache_path("status_config"))
            except OSError:
                pass
            shutil_mod.rmtree(tmp_claude, ignore_errors=True)


class TestCacheDirPermissions(unittest.TestCase):
    """0o700 hardening on the user cache dir (v0.12.0) — the dir name
    is predictable and now holds spend records. POSIX-only: Windows
    chmod only toggles the read-only bit and %TEMP% is per-user."""

    @unittest.skipUnless(os.name == "posix", "POSIX permission bits")
    def test_fresh_create_is_0700(self):
        import stat as stat_mod
        import shutil as shutil_mod
        from claude_statusline import sessions as sess
        tmp_root = tempfile.mkdtemp(prefix="claude-status-perm-")
        orig_gettempdir = tempfile.gettempdir
        tempfile.gettempdir = lambda: tmp_root
        try:
            d = _prev_cache_dir_fn()  # the REAL _cache_dir
            self.assertTrue(d.startswith(tmp_root))
            mode = stat_mod.S_IMODE(os.stat(d).st_mode)
            self.assertEqual(mode, 0o700)
        finally:
            tempfile.gettempdir = orig_gettempdir
            shutil_mod.rmtree(tmp_root, ignore_errors=True)

    @unittest.skipUnless(os.name == "posix", "POSIX permission bits")
    def test_existing_dir_repaired_to_0700(self):
        import stat as stat_mod
        import shutil as shutil_mod
        import hashlib as hashlib_mod
        from claude_statusline import sessions as sess
        tmp_root = tempfile.mkdtemp(prefix="claude-status-perm-")
        user_hash = hashlib_mod.md5(
            os.path.expanduser("~").encode("utf-8", "replace")
        ).hexdigest()[:8]
        pre = os.path.join(tmp_root, "claude_sl_{}".format(user_hash))
        os.makedirs(pre, mode=0o755)
        os.chmod(pre, 0o755)
        orig_gettempdir = tempfile.gettempdir
        tempfile.gettempdir = lambda: tmp_root
        try:
            d = _prev_cache_dir_fn()
            mode = stat_mod.S_IMODE(os.stat(d).st_mode)
            self.assertEqual(mode, 0o700,
                             "pre-existing permissive dir must be repaired")
        finally:
            tempfile.gettempdir = orig_gettempdir
            shutil_mod.rmtree(tmp_root, ignore_errors=True)


class TestContextTokensSection(unittest.TestCase):
    """`context_tokens` (#113): absolute context display ctx:412K/1M.
    Numerator DERIVED from used_percentage × window size so the chip
    always agrees arithmetically with the bar beside it."""

    def _plain(self, s):
        return re.sub(r"\x1b\[[0-9;]*m", "", s)

    def _chip(self, cw):
        import claude_statusline.cli as cli_mod
        orig_line2 = THEMES["default"]["line2"]
        orig_branch = cli_mod.get_branch
        cli_mod.get_branch = lambda: "main"
        try:
            THEMES["default"]["line2"] = ["context_tokens", "branch"]
            out = self._plain(cli_mod.render(
                {"git_branch": "main", "context_window": cw}, "default"))
            m = re.search(r"ctx:\S+", out)
            return m.group(0) if m else None
        finally:
            THEMES["default"]["line2"] = orig_line2
            cli_mod.get_branch = orig_branch

    def test_derived_from_pct_times_size(self):
        self.assertEqual(
            self._chip({"context_window_size": 1_000_000,
                        "used_percentage": 42}), "ctx:420K/1M")

    def test_200k_window(self):
        self.assertEqual(
            self._chip({"context_window_size": 200_000,
                        "used_percentage": 85}), "ctx:170K/200K")

    def test_zero_pct_renders_zero(self):
        """0% is a legit value — must render ctx:0/1M, not hide
        (the 'or drops zeros' house rule)."""
        self.assertEqual(
            self._chip({"context_window_size": 1_000_000,
                        "used_percentage": 0}), "ctx:0/1M")

    def test_out_of_spec_pct_clamped(self):
        """pct 250 clamps to 100 — the chip must never read
        ctx:2.5M/1M (same bounds the bar enforces)."""
        self.assertEqual(
            self._chip({"context_window_size": 1_000_000,
                        "used_percentage": 250}), "ctx:1M/1M")

    def test_hidden_when_either_signal_missing_or_garbage(self):
        for cw in ({"context_window_size": 1_000_000},
                   {"used_percentage": 42},
                   {"context_window_size": "abc", "used_percentage": 42},
                   {"context_window_size": 1_000_000,
                    "used_percentage": "abc"},
                   {"context_window_size": 1_000_000,
                    "used_percentage": float("nan")},
                   {"context_window_size": 0, "used_percentage": 42},
                   {"context_window_size": -5, "used_percentage": 42},
                   {}):
            self.assertIsNone(self._chip(cw), repr(cw))

    def test_negative_pct_clamps_to_zero(self):
        """Pin the clamp's lower bound as a behavior choice."""
        self.assertEqual(
            self._chip({"context_window_size": 1_000_000,
                        "used_percentage": -12}), "ctx:0/1M")

    def test_string_pct_renders(self):
        self.assertEqual(
            self._chip({"context_window_size": 1_000_000,
                        "used_percentage": "42"}), "ctx:420K/1M")

    def test_context_tokens_is_compact_droppable(self):
        from claude_statusline.cli import (
            _COMPACT_DROP, _NARROW_DROP, _FIT_DROP_PRIORITY)
        self.assertIn("context_tokens", _COMPACT_DROP)
        self.assertIn("context_tokens", _NARROW_DROP)
        self.assertIn("context_tokens", _FIT_DROP_PRIORITY)

    def test_fractional_pct_rounds_not_floors(self):
        """4.1% of 1M is exactly 41,000 — but float representation puts
        1_000_000 * 4.1 / 100.0 at 40999.999…, and a bare int() floors
        it to render ctx:40K. round() first (code-review finding: 13
        such off-by-a-chip cases across 0.1%-step percentages)."""
        self.assertEqual(
            self._chip({"context_window_size": 1_000_000,
                        "used_percentage": 4.1}), "ctx:41K/1M")
        self.assertEqual(
            self._chip({"context_window_size": 1_000_000,
                        "used_percentage": 33.3}), "ctx:333K/1M")

    def test_null_theme_color_degrades(self):
        """A custom theme with `context_tokens: null` must fall to the
        default color, not crash colorize (house _first convention —
        this section is reachable ONLY via hand-edited theme JSON,
        exactly where a user writes null)."""
        import claude_statusline.cli as cli_mod
        orig_line2 = THEMES["default"]["line2"]
        orig_colors = THEMES["default"]["colors"]
        orig_branch = cli_mod.get_branch
        cli_mod.get_branch = lambda: "main"
        try:
            THEMES["default"]["line2"] = ["context_tokens", "branch"]
            THEMES["default"]["colors"] = dict(orig_colors,
                                               context_tokens=None)
            out = self._plain(cli_mod.render(
                {"git_branch": "main",
                 "context_window": {"context_window_size": 1_000_000,
                                    "used_percentage": 42}}, "default"))
            self.assertIn("ctx:420K/1M", out)
        finally:
            THEMES["default"]["line2"] = orig_line2
            THEMES["default"]["colors"] = orig_colors
            cli_mod.get_branch = orig_branch


class TestTokenCorruptGate(unittest.TestCase):
    """Silent-failure review: coercing a present-but-garbage token
    component to None must not let the DERIVED chips (cache %, burn,
    speed) recompute with that component silently zeroed — a cache
    hit-rate inflating 60% -> 90% with no visible cue. They hide
    instead; per-field sections keep their own visibility."""

    def _plain(self, s):
        return re.sub(r"\x1b\[[0-9;]*m", "", s)

    def _render(self, cw_usage):
        import claude_statusline.cli as cli_mod
        orig_branch = cli_mod.get_branch
        cli_mod.get_branch = lambda: "main"
        try:
            return self._plain(cli_mod.render({
                "git_branch": "main",
                "context_window": {"used_percentage": 50,
                                   "current_usage": cw_usage},
                "cost": {"total_cost_usd": 0.5,
                         "total_duration_ms": 300_000,
                         "total_api_duration_ms": 60_000},
            }, "default"))
        finally:
            cli_mod.get_branch = orig_branch

    _VALID = {"input_tokens": 50_000, "output_tokens": 5_000,
              "cache_read_input_tokens": 90_000,
              "cache_creation_input_tokens": 10_000}

    def test_all_valid_renders_derived_chips(self):
        out = self._render(dict(self._VALID))
        self.assertIn("cache:60%", out)
        self.assertIn("burn:", out)

    def test_garbage_component_hides_derived_not_wrong(self):
        """Garbage input_tokens: cache % must HIDE (was: rendered a
        confidently-wrong 90%). The tokens chip's own in:? remains the
        visible cue."""
        usage = dict(self._VALID, input_tokens="fifty-thousand")
        out = self._render(usage)
        self.assertNotIn("cache:", out)
        self.assertNotIn("burn:", out)
        self.assertIn("in:?", out)

    def test_invisible_garbage_component_still_hides(self):
        """The worst pre-fix case: garbage cache_creation only — every
        visible field looked normal while cache % was wrong. Must hide
        with no other cue available."""
        usage = dict(self._VALID,
                     cache_creation_input_tokens=float("nan"))
        out = self._render(usage)
        self.assertNotIn("cache:", out)
        self.assertIn("in:50K", out)  # per-field sections unaffected

    def test_absent_component_still_computes(self):
        """ABSENT (never sent) stays the pre-existing absent-means-0
        rule — only present-but-garbage trips the gate."""
        usage = dict(self._VALID)
        del usage["cache_creation_input_tokens"]
        out = self._render(usage)
        self.assertIn("cache:", out)

    def test_normalize_flag(self):
        from claude_statusline.cli import _normalize
        n = _normalize({"context_window": {"current_usage":
                       {"input_tokens": "abc"}}, "session_id": "x"})
        self.assertTrue(n["token_fields_corrupt"])
        n = _normalize({"context_window": {"current_usage":
                       {"input_tokens": 5}}, "session_id": "x"})
        self.assertFalse(n["token_fields_corrupt"])
        n = _normalize({"session_id": "x"})  # all absent: not corrupt
        self.assertFalse(n["token_fields_corrupt"])


class TestContextFieldCoercion(unittest.TestCase):
    """v0.14.0: the context/token block gets the same _safe_num
    chokepoint treatment the money/time trio got in v0.11.0. Before
    this, `used_percentage: NaN` (stdin-reachable — json.loads accepts
    the bare literal) sailed through `is not None` gates into
    render_bar's int() and blanked the ENTIRE statusline."""

    def test_nan_pct_hides_bar_not_whole_line(self):
        import claude_statusline.cli as cli_mod
        orig_branch = cli_mod.get_branch
        cli_mod.get_branch = lambda: "main"
        try:
            out = re.sub(r"\x1b\[[0-9;]*m", "", cli_mod.render({
                "git_branch": "main",
                "context_window": {"context_window_size": 1_000_000,
                                   "used_percentage": float("nan")},
                "cost": {"total_cost_usd": 0.5},
            }, "default"))
        finally:
            cli_mod.get_branch = orig_branch
        self.assertIn("$0.50", out)   # line survived
        self.assertIn("main", out)

    def test_normalize_coerces_context_block(self):
        from claude_statusline.cli import _normalize
        n = _normalize({"context_window": {
            "used_percentage": "42",
            "current_usage": {"input_tokens": "1000",
                              "output_tokens": float("inf"),
                              "cache_read_input_tokens": float("nan"),
                              "cache_creation_input_tokens": [1]},
        }, "session_id": "x"})
        self.assertEqual(n["used_percentage"], 42.0)
        self.assertEqual(n["input_tokens"], 1000.0)
        self.assertIsNone(n["output_tokens"])
        self.assertIsNone(n["cache_read"])
        self.assertIsNone(n["cache_create"])

    def test_zero_tokens_survive_coercion(self):
        """0 is falsy but legit — coercion must return 0.0, not None."""
        from claude_statusline.cli import _normalize
        n = _normalize({"context_window": {
            "used_percentage": 0,
            "current_usage": {"input_tokens": 0}}, "session_id": "x"})
        self.assertEqual(n["used_percentage"], 0.0)
        self.assertEqual(n["input_tokens"], 0.0)

    def test_numeric_strings_render_e2e(self):
        """CHANGELOG claim pinned end to end: stringified numerics
        coerce AND render — and do NOT trip the corrupt gate (they are
        valid values, not garbage)."""
        import claude_statusline.cli as cli_mod
        orig_branch = cli_mod.get_branch
        cli_mod.get_branch = lambda: "main"
        try:
            out = re.sub(r"\x1b\[[0-9;]*m", "", cli_mod.render({
                "git_branch": "main",
                "context_window": {
                    "used_percentage": "42",
                    "current_usage": {"input_tokens": "1000",
                                      "output_tokens": "500",
                                      "cache_read_input_tokens": "9000"}},
            }, "default"))
        finally:
            cli_mod.get_branch = orig_branch
        self.assertIn("in:1K", out)
        self.assertIn("out:500", out)
        self.assertIn("cache:", out)  # gate NOT tripped by strings

    def test_builtin_themes_do_not_include_new_optin_sections(self):
        """Pins the 'opt-in via custom theme' claim for context_tokens
        (and cost_rate, which shared the missing pin): absent from
        every built-in theme's line lists."""
        for name, theme in THEMES.items():
            for key, val in theme.items():
                if re.match(r"line\d+$", key) and isinstance(val, list):
                    self.assertNotIn("context_tokens", val,
                                     "{}[{}]".format(name, key))
                    self.assertNotIn("cost_rate", val,
                                     "{}[{}]".format(name, key))


class TestSafeNumFinite(unittest.TestCase):
    """_safe_num guarantees a FINITE float or None (v0.11.0). NaN in
    particular is poison: every comparison is False, so it sails
    through threshold checks and detonates later inside a formatter's
    int(). "Safe" means finite — pinned here so a future refactor
    can't quietly reopen the hole."""

    def test_finite_passthrough(self):
        from claude_statusline.cli import _safe_num
        self.assertEqual(_safe_num(1.5), 1.5)
        self.assertEqual(_safe_num("0.5"), 0.5)
        self.assertEqual(_safe_num(0), 0.0)

    def test_non_finite_rejected(self):
        from claude_statusline.cli import _safe_num
        for bad in (float("nan"), float("inf"), float("-inf"),
                    "nan", "inf", "-inf", "Infinity", "NaN"):
            self.assertIsNone(_safe_num(bad),
                "_safe_num({!r}) must be None".format(bad))

    def test_garbage_rejected(self):
        from claude_statusline.cli import _safe_num
        for bad in (None, "abc", [], {}, object()):
            self.assertIsNone(_safe_num(bad))


# ─── git.py ───────────────────────────────────────────────────────────

class TestGitBranch(unittest.TestCase):
    def test_returns_string(self):
        result = get_branch()
        self.assertIsInstance(result, str)

    def test_in_git_repo(self):
        # We're running from within the repo, so should get a branch
        # (unless running from a non-git temp dir)
        result = get_branch()
        # Just check it doesn't crash — result may be empty if not in git
        self.assertIsInstance(result, str)

    def test_cache_isolation_per_directory(self):
        """Different working directories should use different cache files."""
        from claude_statusline.git import _cache_file
        original_cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as dir_a:
                os.chdir(dir_a)
                cache_a = _cache_file()
                os.chdir(original_cwd)  # leave before cleanup (Windows)
            with tempfile.TemporaryDirectory() as dir_b:
                os.chdir(dir_b)
                cache_b = _cache_file()
                os.chdir(original_cwd)  # leave before cleanup (Windows)
            self.assertNotEqual(cache_a, cache_b)
        finally:
            os.chdir(original_cwd)


# ─── themes.py ────────────────────────────────────────────────────────

class TestThemes(unittest.TestCase):
    def test_all_builtin_themes_exist(self):
        for name in ("default", "minimal", "powerline", "nord",
                     "tokyo-night", "gruvbox", "rose-pine", "focus"):
            self.assertIn(name, THEMES, "Missing theme: {}".format(name))

    def test_required_keys(self):
        required = ["name", "separator", "bar_filled", "bar_empty",
                     "line1", "line2", "colors"]
        for name, theme in THEMES.items():
            for key in required:
                self.assertIn(key, theme, "{} missing key: {}".format(name, key))

    def test_theme_names_match(self):
        for name, theme in THEMES.items():
            self.assertEqual(theme["name"], name)

    def test_get_theme_default(self):
        t = get_theme("default")
        self.assertEqual(t["name"], "default")

    def test_get_theme_unknown_falls_back(self):
        t = get_theme("nonexistent")
        self.assertEqual(t["name"], "default")

    def test_color_keys(self):
        required_colors = ["separator", "label", "value", "cost",
                           "branch_main", "branch_feature", "warning",
                           "added", "removed", "agent", "vim_normal", "vim_insert",
                           "model", "latency"]
        for name, theme in THEMES.items():
            for key in required_colors:
                self.assertIn(key, theme["colors"],
                              "{} theme missing color: {}".format(name, key))

    def test_all_themes_have_effort_xhigh(self):
        """All built-in themes must include the effort_xhigh color key
        added in v0.5.6 for Opus 4.7 support. Custom user themes can
        omit it (the renderer falls back to effort_high), but built-ins
        should all opt in so themes look consistent out of the box."""
        for name, theme in THEMES.items():
            self.assertIn("effort_xhigh", theme["colors"],
                "{} theme missing effort_xhigh color key".format(name))

    def test_all_themes_have_effort_max(self):
        """Same contract as effort_xhigh: built-in themes ship the key
        for the top-tier effort level so users on Opus 4.7 max see a
        themed indicator out of the box."""
        for name, theme in THEMES.items():
            self.assertIn("effort_max", theme["colors"],
                "{} theme missing effort_max color key".format(name))


# ─── cli.py ───────────────────────────────────────────────────────────

class TestRender(unittest.TestCase):
    def _full_data(self):
        """Sample data using the real Claude Code nested schema."""
        return {
            "context_window": {
                "used_percentage": 42,
                "context_window_size": 200_000,
                "current_usage": {
                    "input_tokens": 245_000,
                    "output_tokens": 18_500,
                    "cache_read_input_tokens": 180_000,
                    "cache_creation_input_tokens": 5_000,
                },
            },
            "cost": {
                "total_cost_usd": 0.73,
                "total_duration_ms": 725_000,
                "total_lines_added": 247,
                "total_lines_removed": 38,
            },
            "exceeds_200k_tokens": False,
            "git_branch": "feat/statusline",
        }

    def test_full_data(self):
        result = render(self._full_data())
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)

    def test_two_line_output(self):
        """Full data should produce two lines."""
        result = render(self._full_data())
        lines = result.split("\n")
        self.assertEqual(len(lines), 2, "Expected 2 lines, got {}".format(len(lines)))

    def test_empty_data(self):
        result = render({})
        # May be empty string — should not crash
        self.assertIsInstance(result, str)

    def test_partial_data(self):
        result = render({"cost_usd": 0.5})
        self.assertIsInstance(result, str)

    def test_null_usage(self):
        result = render({"context_window": None})
        self.assertIsInstance(result, str)

    def test_exceeds_200k_no_warning_if_below_85pct(self):
        """exceeds_200k_tokens alone should NOT trigger !CTX warning.

        The percentage-based check is the only warning trigger now.
        On 1M context windows, exceeding 200K tokens is only ~20% usage.
        """
        data = self._full_data()
        data["exceeds_200k_tokens"] = True
        data["context_window"]["used_percentage"] = 42  # well below 85%
        result = render(data)
        self.assertNotIn("!CTX", result)

    def test_ctx_warning_at_85_percent(self):
        """Warning should trigger at 85%+ usage regardless of context size."""
        data = self._full_data()
        data["exceeds_200k_tokens"] = False
        data["context_window"]["used_percentage"] = 85
        data["context_window"]["context_window_size"] = 1_000_000
        result = render(data)
        self.assertIn("!CTX", result)

    def test_ctx_warning_not_at_84_percent(self):
        """Warning should NOT trigger below 85% usage."""
        data = self._full_data()
        data["exceeds_200k_tokens"] = False
        data["context_window"]["used_percentage"] = 84
        result = render(data)
        self.assertNotIn("!CTX", result)

    def test_ctx_warning_1m_context_low_usage(self):
        """1M context at 20% usage should NOT show warning."""
        data = self._full_data()
        data["exceeds_200k_tokens"] = False
        data["context_window"]["used_percentage"] = 20
        data["context_window"]["context_window_size"] = 1_000_000
        result = render(data)
        self.assertNotIn("!CTX", result)

    def test_ctx_warning_1m_exceeds_200k_low_pct(self):
        """1M context exceeding 200K tokens but at 25% should NOT warn."""
        data = self._full_data()
        data["exceeds_200k_tokens"] = True
        data["context_window"]["used_percentage"] = 25
        data["context_window"]["context_window_size"] = 1_000_000
        result = render(data)
        self.assertNotIn("!CTX", result)

    def test_ctx_warning_no_pct_with_exceeds_200k(self):
        """Missing used_percentage + exceeds_200k should NOT warn."""
        data = self._full_data()
        data["exceeds_200k_tokens"] = True
        del data["context_window"]["used_percentage"]
        result = render(data)
        self.assertNotIn("!CTX", result)

    def test_vim_mode(self):
        data = self._full_data()
        data["vim"] = {"mode": "NORMAL"}
        result = render(data)
        self.assertIn("NORMAL", result)

    def test_agent_name(self):
        data = self._full_data()
        data["agent"] = {"name": "Explore"}
        result = render(data)
        self.assertIn("Explore", result)

    def test_worktree(self):
        data = self._full_data()
        data["worktree"] = {"branch": "fix/bug-123", "name": "fix"}
        result = render(data)
        self.assertIn("fix/bug-123", result)

    def test_project_name_in_branch(self):
        """Branch should show project/branch when cwd is available."""
        data = self._full_data()
        data["cwd"] = "/home/user/projects/myapp"
        result = render(data)
        self.assertIn("myapp", result)

    def test_project_name_with_workspace(self):
        """Workspace.current_dir should also provide project name."""
        data = self._full_data()
        data["workspace"] = {"current_dir": "/home/user/projects/my-app"}
        result = render(data)
        self.assertIn("my-app", result)

    def test_no_project_name(self):
        """Missing cwd should still show branch without project."""
        data = self._full_data()
        # Remove any cwd — git_branch is set in _full_data
        result = render(data)
        self.assertIn("feat/statusline", result)

    def test_all_optional_fields(self):
        data = self._full_data()
        data["vim"] = {"mode": "INSERT"}
        data["agent"] = {"name": "Plan"}
        data["worktree"] = {"branch": "wt-branch", "name": "wt"}
        result = render(data)
        self.assertIn("INSERT", result)
        self.assertIn("Plan", result)
        self.assertIn("wt-branch", result)

    def test_minimal_theme(self):
        result = render(self._full_data(), "minimal")
        self.assertIsInstance(result, str)

    def test_powerline_theme(self):
        result = render(self._full_data(), "powerline")
        self.assertIsInstance(result, str)

    def test_zero_cost_duration_lines(self):
        data = {
            "context_window": {"used_percentage": 0},
            "cost": {"total_cost_usd": 0, "total_duration_ms": 0,
                     "total_lines_added": 0, "total_lines_removed": 0},
        }
        result = render(data)
        self.assertIsInstance(result, str)

    def test_model_name_displayed(self):
        """Model display_name should appear when present."""
        data = self._full_data()
        data["model"] = {"id": "claude-opus-4-6", "display_name": "Opus"}
        result = render(data)
        self.assertIn("Opus", result)

    def test_model_name_absent(self):
        """Missing model should not crash or show anything."""
        data = self._full_data()
        result = render(data)
        self.assertNotIn("Opus", result)
        self.assertNotIn("Sonnet", result)

    def test_zero_values_not_dropped(self):
        """Zero values should be preserved, not treated as None."""
        data = {
            "context_window": {
                "used_percentage": 0,
                "context_window_size": 200_000,
                "current_usage": {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                },
            },
            "cost": {
                "total_cost_usd": 0,
                "total_duration_ms": 0,
                "total_lines_added": 0,
                "total_lines_removed": 0,
            },
            "git_branch": "main",
        }
        result = render(data)
        self.assertIsInstance(result, str)
        # Cost of 0 should render as "0c" not disappear
        self.assertIn("0c", result)

    def test_real_schema_full(self):
        """Test with a complete real Claude Code JSON payload."""
        data = {
            "cwd": "/tmp",
            "session_id": "abc123",
            "model": {"id": "claude-opus-4-6", "display_name": "Opus"},
            "context_window": {
                "total_input_tokens": 15234,
                "total_output_tokens": 4521,
                "context_window_size": 200000,
                "used_percentage": 8,
                "remaining_percentage": 92,
                "current_usage": {
                    "input_tokens": 8500,
                    "output_tokens": 1200,
                    "cache_creation_input_tokens": 5000,
                    "cache_read_input_tokens": 2000,
                },
            },
            "cost": {
                "total_cost_usd": 0.01234,
                "total_duration_ms": 45000,
                "total_api_duration_ms": 2300,
                "total_lines_added": 156,
                "total_lines_removed": 23,
            },
            "exceeds_200k_tokens": False,
            "vim": {"mode": "NORMAL"},
            "agent": {"name": "security-reviewer"},
        }
        result = render(data)
        self.assertIn("8.5K", result)  # input tokens
        self.assertIn("1.2K", result)  # output tokens
        self.assertIn("NORMAL", result)
        self.assertIn("security-reviewer", result)


class TestCLIInstall(unittest.TestCase):
    def test_install_writes_settings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = os.path.join(tmpdir, "settings.json")
            # Monkey-patch the settings path
            import claude_statusline.cli as cli_mod
            orig = cli_mod._settings_path
            cli_mod._settings_path = lambda: settings_file

            try:
                cli_mod.cmd_install("default")
                with open(settings_file, "r") as f:
                    settings = json.load(f)
                sl = settings["statusLine"]
                self.assertEqual(sl["type"], "command")
                self.assertEqual(sl["command"], "claude-status")
            finally:
                cli_mod._settings_path = orig

    def test_install_with_theme(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = os.path.join(tmpdir, "settings.json")
            import claude_statusline.cli as cli_mod
            orig = cli_mod._settings_path
            cli_mod._settings_path = lambda: settings_file

            try:
                cli_mod.cmd_install("powerline")
                with open(settings_file, "r") as f:
                    settings = json.load(f)
                sl = settings["statusLine"]
                self.assertEqual(sl["type"], "command")
                self.assertIn("--theme powerline", sl["command"])
            finally:
                cli_mod._settings_path = orig

    def test_install_creates_backup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = os.path.join(tmpdir, "settings.json")
            original = {"existingKey": "preserve_me", "other": 42}
            with open(settings_file, "w") as f:
                json.dump(original, f)

            import claude_statusline.cli as cli_mod
            orig = cli_mod._settings_path
            cli_mod._settings_path = lambda: settings_file

            try:
                cli_mod.cmd_install("default")
                backup_file = settings_file + ".bak"
                self.assertTrue(os.path.exists(backup_file))
                with open(backup_file, "r") as f:
                    backup_content = json.load(f)
                self.assertEqual(backup_content, original)
            finally:
                cli_mod._settings_path = orig

    def test_install_no_backup_when_no_existing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = os.path.join(tmpdir, "settings.json")

            import claude_statusline.cli as cli_mod
            orig = cli_mod._settings_path
            cli_mod._settings_path = lambda: settings_file

            try:
                cli_mod.cmd_install("default")
                backup_file = settings_file + ".bak"
                self.assertFalse(os.path.exists(backup_file))
            finally:
                cli_mod._settings_path = orig

    def test_install_preserves_existing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = os.path.join(tmpdir, "settings.json")
            # Write existing settings
            with open(settings_file, "w") as f:
                json.dump({"existingKey": "value"}, f)

            import claude_statusline.cli as cli_mod
            orig = cli_mod._settings_path
            cli_mod._settings_path = lambda: settings_file

            try:
                cli_mod.cmd_install("default")
                with open(settings_file, "r") as f:
                    settings = json.load(f)
                self.assertEqual(settings["existingKey"], "value")
                self.assertEqual(settings["statusLine"]["type"], "command")
            finally:
                cli_mod._settings_path = orig


class TestCLISubprocess(unittest.TestCase):
    """Test CLI via subprocess to verify entry point and stdin handling."""

    _env = None

    @classmethod
    def setUpClass(cls):
        # Force UTF-8 for subprocess stdout on Windows (avoids cp1252 issues)
        cls._env = os.environ.copy()
        cls._env["PYTHONIOENCODING"] = "utf-8"

    def _run(self, args, **kwargs):
        return subprocess.run(
            [sys.executable, "-m", "claude_statusline"] + args,
            capture_output=True, timeout=15,
            env=self._env, encoding="utf-8", errors="replace", **kwargs,
        )

    def test_version(self):
        result = self._run(["--version"])
        self.assertEqual(result.returncode, 0)
        self.assertIn(__version__, result.stdout)

    def test_demo(self):
        result = self._run(["--demo"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("default:", result.stdout)
        self.assertIn("minimal:", result.stdout)
        self.assertIn("powerline:", result.stdout)

    def test_json_stdin(self):
        data = json.dumps({
            "current_usage": {"used_percentage": 50, "input_tokens": 1000, "output_tokens": 500},
            "cost_usd": 0.05,
        })
        result = self._run([], input=data)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(len(result.stdout.strip()) > 0)
        # #116 acceptance pin: the demo's repo footer must never leak
        # into statusline renders (it would appear in every Claude
        # Code render and blow the line-fit budget). Symmetric with
        # the star-ask absence pin on --install.
        self.assertNotIn("github.com/mkalkere", result.stdout)

    def test_empty_stdin(self):
        result = self._run([], input="")
        self.assertEqual(result.returncode, 0)

    def test_malformed_stdin(self):
        result = self._run([], input="not json at all {{{")
        self.assertEqual(result.returncode, 0)
        self.assertIn("?", result.stdout)

    def test_empty_json_object(self):
        result = self._run([], input="{}")
        self.assertEqual(result.returncode, 0)

    def test_doctor(self):
        result = self._run(["--doctor"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("Python:", result.stdout)
        self.assertIn("OS:", result.stdout)

    def test_doctor_cache_age_probe(self):
        """--doctor reports a `Cache age:` line derived from the most
        recent transcript under ~/.claude/projects/. We plant a fixture
        with a FUTURE mtime so it is deterministically selected as the
        most-recent file, then assert the normal-age wording. Cleaned up
        in finally so the user's real ~/.claude/projects/ is untouched.
        """
        import shutil as shutil_mod
        from claude_statusline import sessions as sessions_mod
        projects = os.path.join(sessions_mod._CLAUDE_DIR, "projects")
        os.makedirs(projects, exist_ok=True)
        fixture_dir = tempfile.mkdtemp(prefix="cacheage-doctor-", dir=projects)
        fixture = os.path.join(fixture_dir, "session.jsonl")
        ts = time.strftime(
            "%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() - 42))
        try:
            with open(fixture, "w", encoding="utf-8", newline="") as f:
                f.write(json.dumps({
                    "type": "assistant",
                    "message": {"role": "assistant", "content": []},
                    "timestamp": ts}) + "\n")
            # Bump mtime into the future so the doctor's most-recent
            # selection deterministically picks this fixture regardless
            # of what else lives under ~/.claude/projects/.
            future = time.time() + 3600
            os.utime(fixture, (future, future))
            result = self._run(["--doctor"])
            self.assertEqual(result.returncode, 0)
            self.assertIn("Cache age:", result.stdout)
            self.assertIn("since last assistant message", result.stdout)
        finally:
            shutil_mod.rmtree(fixture_dir, ignore_errors=True)


# ─── Issue #6: API latency ────────────────────────────────────────────

class TestAPILatency(unittest.TestCase):
    def _data_with_latency(self, api_ms):
        return {
            "context_window": {
                "used_percentage": 30,
                "current_usage": {"input_tokens": 5000, "output_tokens": 1000},
            },
            "cost": {
                "total_cost_usd": 0.10,
                "total_duration_ms": 60_000,
                "total_api_duration_ms": api_ms,
            },
            "git_branch": "main",
        }

    def test_latency_displayed(self):
        result = render(self._data_with_latency(45_000))
        self.assertIn("api:", result)
        self.assertIn("45s", result)

    def test_latency_minutes(self):
        result = render(self._data_with_latency(125_000))
        self.assertIn("api:", result)
        self.assertIn("2m05s", result)

    def test_latency_absent(self):
        data = {
            "context_window": {"used_percentage": 30,
                               "current_usage": {"input_tokens": 5000}},
            "cost": {"total_cost_usd": 0.10, "total_duration_ms": 60_000},
        }
        result = render(data)
        self.assertNotIn("api:", result)


# ─── Issue #7: workspace.project_dir ──────────────────────────────────

class TestProjectDir(unittest.TestCase):
    def test_project_dir_preferred(self):
        """workspace.project_dir should take priority over current_dir."""
        data = {
            "context_window": {"used_percentage": 10,
                               "current_usage": {"input_tokens": 100}},
            "workspace": {
                "project_dir": "/home/user/projects/my-project",
                "current_dir": "/home/user/projects/my-project/src/deep/nested",
            },
            "git_branch": "main",
        }
        result = render(data)
        self.assertIn("my-project", result)
        self.assertNotIn("nested", result)

    def test_falls_back_to_current_dir(self):
        """Without project_dir, should use current_dir basename."""
        data = {
            "context_window": {"used_percentage": 10,
                               "current_usage": {"input_tokens": 100}},
            "workspace": {"current_dir": "/home/user/projects/fallback-app"},
            "git_branch": "main",
        }
        result = render(data)
        self.assertIn("fallback-app", result)

    def test_falls_back_to_cwd(self):
        """Without workspace at all, should use top-level cwd."""
        data = {
            "context_window": {"used_percentage": 10,
                               "current_usage": {"input_tokens": 100}},
            "cwd": "/home/user/projects/legacy-app",
            "git_branch": "main",
        }
        result = render(data)
        self.assertIn("legacy-app", result)


# ─── Issue #8: Custom themes ─────────────────────────────────────────

class TestCustomThemes(unittest.TestCase):
    def test_custom_theme_loads(self):
        """Custom theme JSON should be loadable."""
        import claude_statusline.themes as themes_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            theme_file = os.path.join(tmpdir, "claude-status-theme.json")
            theme_json = {
                "base": "minimal",
                "separator": " | ",
                "colors": {
                    "cost": "green",
                    "branch_main": "bright_cyan",
                },
            }
            with open(theme_file, "w") as f:
                json.dump(theme_json, f)

            orig = themes_mod._custom_theme_path
            themes_mod._custom_theme_path = lambda: theme_file

            try:
                theme = themes_mod.load_custom_theme()
                self.assertIsNotNone(theme)
                self.assertEqual(theme["name"], "custom")
                self.assertEqual(theme["separator"], " | ")
                # Color should be resolved from string to ANSI code
                from claude_statusline.colors import GREEN, BRIGHT_CYAN
                self.assertEqual(theme["colors"]["cost"], GREEN)
                self.assertEqual(theme["colors"]["branch_main"], BRIGHT_CYAN)
            finally:
                themes_mod._custom_theme_path = orig

    def test_custom_theme_missing_file(self):
        """Missing file should return None gracefully."""
        import claude_statusline.themes as themes_mod

        orig = themes_mod._custom_theme_path
        themes_mod._custom_theme_path = lambda: "/nonexistent/path.json"
        try:
            result = themes_mod.load_custom_theme()
            self.assertIsNone(result)
        finally:
            themes_mod._custom_theme_path = orig

    def test_custom_theme_invalid_json(self):
        """Invalid JSON should return None gracefully."""
        import claude_statusline.themes as themes_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            theme_file = os.path.join(tmpdir, "bad.json")
            with open(theme_file, "w") as f:
                f.write("not valid json {{{")

            orig = themes_mod._custom_theme_path
            themes_mod._custom_theme_path = lambda: theme_file
            try:
                result = themes_mod.load_custom_theme()
                self.assertIsNone(result)
            finally:
                themes_mod._custom_theme_path = orig

    def test_custom_theme_overrides_lines(self):
        """Custom theme can override line1/line2 layout."""
        import claude_statusline.themes as themes_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            theme_file = os.path.join(tmpdir, "theme.json")
            theme_json = {
                "line1": ["bar", "cost"],
                "line2": ["branch"],
            }
            with open(theme_file, "w") as f:
                json.dump(theme_json, f)

            orig = themes_mod._custom_theme_path
            themes_mod._custom_theme_path = lambda: theme_file
            try:
                theme = themes_mod.load_custom_theme()
                self.assertEqual(theme["line1"], ["bar", "cost"])
                self.assertEqual(theme["line2"], ["branch"])
            finally:
                themes_mod._custom_theme_path = orig

    def test_get_theme_custom(self):
        """get_theme('custom') should load from file."""
        import claude_statusline.themes as themes_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            theme_file = os.path.join(tmpdir, "theme.json")
            with open(theme_file, "w") as f:
                json.dump({"separator": " ~ "}, f)

            orig = themes_mod._custom_theme_path
            themes_mod._custom_theme_path = lambda: theme_file
            try:
                theme = get_theme("custom")
                self.assertEqual(theme["name"], "custom")
                self.assertEqual(theme["separator"], " ~ ")
            finally:
                themes_mod._custom_theme_path = orig

    def test_get_theme_custom_fallback(self):
        """get_theme('custom') without file falls back to default."""
        import claude_statusline.themes as themes_mod

        orig = themes_mod._custom_theme_path
        themes_mod._custom_theme_path = lambda: "/nonexistent/path.json"
        try:
            theme = get_theme("custom")
            self.assertEqual(theme["name"], "default")
        finally:
            themes_mod._custom_theme_path = orig


# ─── themes.py — new themes ─────────────────────────────────────────

class TestNewThemes(unittest.TestCase):
    def test_all_seven_themes_exist(self):
        """All 7 built-in themes should be registered."""
        for name in ("default", "minimal", "powerline",
                     "nord", "tokyo-night", "gruvbox", "rose-pine"):
            self.assertIn(name, THEMES, "Missing theme: {}".format(name))

    def test_new_theme_names_match(self):
        for name in ("nord", "tokyo-night", "gruvbox", "rose-pine"):
            self.assertEqual(THEMES[name]["name"], name)

    def test_new_themes_have_required_keys(self):
        required = ["name", "separator", "bar_filled", "bar_empty",
                     "line1", "line2", "colors"]
        for name in ("nord", "tokyo-night", "gruvbox", "rose-pine"):
            for key in required:
                self.assertIn(key, THEMES[name],
                              "{} missing key: {}".format(name, key))

    def test_new_themes_have_required_colors(self):
        required_colors = ["separator", "label", "value", "cost",
                           "branch_main", "branch_feature", "warning",
                           "added", "removed", "agent", "vim_normal", "vim_insert",
                           "model", "latency", "sessions"]
        for name in ("nord", "tokyo-night", "gruvbox", "rose-pine"):
            for key in required_colors:
                self.assertIn(key, THEMES[name]["colors"],
                              "{} theme missing color: {}".format(name, key))

    def test_new_themes_render(self):
        """All new themes should produce output without crashing."""
        data = {
            "context_window": {
                "used_percentage": 42,
                "context_window_size": 200_000,
                "current_usage": {
                    "input_tokens": 245_000,
                    "output_tokens": 18_500,
                    "cache_read_input_tokens": 180_000,
                    "cache_creation_input_tokens": 5_000,
                },
            },
            "cost": {
                "total_cost_usd": 0.73,
                "total_duration_ms": 725_000,
                "total_lines_added": 247,
                "total_lines_removed": 38,
            },
            "git_branch": "main",
        }
        for name in ("nord", "tokyo-night", "gruvbox", "rose-pine"):
            result = render(data, name)
            self.assertIsInstance(result, str)
            self.assertTrue(len(result) > 0, "{} produced empty output".format(name))

    def test_new_themes_have_new_sections(self):
        """New themes should include tools, sessions, budget in their layouts."""
        for name in ("nord", "tokyo-night", "gruvbox", "rose-pine"):
            theme = THEMES[name]
            self.assertIn("tools", theme["line2"],
                          "{} missing 'tools' in line2".format(name))
            self.assertIn("sessions", theme["line2"],
                          "{} missing 'sessions' in line2".format(name))
            self.assertIn("budget", theme["line1"],
                          "{} missing 'budget' in line1".format(name))


# ─── sessions.py ────────────────────────────────────────────────────

class TestSessions(unittest.TestCase):
    def test_get_today_session_count_returns_int(self):
        from claude_statusline.sessions import get_today_session_count
        result = get_today_session_count()
        self.assertIsInstance(result, int)
        self.assertGreaterEqual(result, 0)

    def test_get_session_tool_count_empty_id(self):
        from claude_statusline.sessions import get_session_tool_count
        self.assertEqual(get_session_tool_count(""), 0)
        self.assertEqual(get_session_tool_count(None), 0)

    def test_get_session_tool_count_nonexistent(self):
        from claude_statusline.sessions import get_session_tool_count
        result = get_session_tool_count("nonexistent-session-id-12345")
        self.assertEqual(result, 0)

    def test_get_session_tool_count_path_traversal(self):
        """Session IDs with path separators should be rejected."""
        from claude_statusline.sessions import get_session_tool_count
        self.assertEqual(get_session_tool_count("../../etc/passwd"), 0)
        self.assertEqual(get_session_tool_count("foo/bar"), 0)
        self.assertEqual(get_session_tool_count("foo\\bar"), 0)

    def test_cache_path_is_user_scoped(self):
        """Cache files should be in a user-specific directory. The
        module-scope redirect (see setUpModule) points _cache_dir at a
        plain temp dir for isolation, so restore the REAL function just
        for this assertion — it tests the production path shape."""
        from claude_statusline import sessions as sessions_mod
        redirected = sessions_mod._cache_dir
        assert _prev_cache_dir_fn is not None
        sessions_mod._cache_dir = _prev_cache_dir_fn
        try:
            path = sessions_mod._cache_path("test")
            # Should contain a hash-based subdirectory, not flat /tmp
            self.assertIn("claude_sl_", path)
            parent = os.path.basename(os.path.dirname(path))
            self.assertTrue(parent.startswith("claude_sl_"))
        finally:
            sessions_mod._cache_dir = redirected

    def test_get_budget_config_no_file(self):
        from claude_statusline.sessions import get_budget_config
        import claude_statusline.sessions as sessions_mod
        orig = sessions_mod._CLAUDE_DIR
        sessions_mod._CLAUDE_DIR = "/nonexistent/path"
        try:
            result = get_budget_config()
            self.assertIsNone(result)
        finally:
            sessions_mod._CLAUDE_DIR = orig

    def test_get_budget_config_valid(self):
        from claude_statusline.sessions import get_budget_config, _cache_path
        import claude_statusline.sessions as sessions_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            budget_file = os.path.join(tmpdir, "claude-status-budget.json")
            with open(budget_file, "w") as f:
                json.dump({"daily_budget_usd": 15.0}, f)

            orig = sessions_mod._CLAUDE_DIR
            sessions_mod._CLAUDE_DIR = tmpdir
            # Invalidate cache to force re-read from new path
            try:
                os.unlink(_cache_path("status_config"))
            except OSError:
                pass
            try:
                result = get_budget_config()
                self.assertAlmostEqual(result, 15.0)
            finally:
                sessions_mod._CLAUDE_DIR = orig

    def test_get_budget_config_invalid_json(self):
        from claude_statusline.sessions import get_budget_config, _cache_path
        import claude_statusline.sessions as sessions_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            budget_file = os.path.join(tmpdir, "claude-status-budget.json")
            with open(budget_file, "w") as f:
                f.write("not json {{{")

            orig = sessions_mod._CLAUDE_DIR
            sessions_mod._CLAUDE_DIR = tmpdir
            try:
                os.unlink(_cache_path("status_config"))
            except OSError:
                pass
            try:
                result = get_budget_config()
                self.assertIsNone(result)
            finally:
                sessions_mod._CLAUDE_DIR = orig

    def test_session_count_with_mock_sessions(self):
        """Test session counting with mock session files."""
        from claude_statusline.sessions import get_today_session_count, _write_cache
        import claude_statusline.sessions as sessions_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = os.path.join(tmpdir, "sessions")
            os.makedirs(sessions_dir)

            # Create a session started "today" (use current epoch)
            now_ms = int(time.time() * 1000)
            with open(os.path.join(sessions_dir, "111.json"), "w") as f:
                json.dump({"pid": 111, "sessionId": "a", "startedAt": now_ms}, f)

            # Create a session from yesterday
            yesterday_ms = now_ms - (86400 * 1000)
            with open(os.path.join(sessions_dir, "222.json"), "w") as f:
                json.dump({"pid": 222, "sessionId": "b", "startedAt": yesterday_ms}, f)

            orig_sessions = sessions_mod._SESSIONS_DIR
            sessions_mod._SESSIONS_DIR = sessions_dir

            # Clear cache to force re-read
            # Clear date-keyed cache
            _write_cache("sessions_{}".format(time.strftime("%Y-%m-%d")), None)

            try:
                count = get_today_session_count()
                self.assertEqual(count, 1)
            finally:
                sessions_mod._SESSIONS_DIR = orig_sessions

    def test_tool_count_with_mock_jsonl(self):
        """Test tool counting with a mock JSONL file."""
        from claude_statusline.sessions import get_session_tool_count, _write_cache
        import claude_statusline.sessions as sessions_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            projects_dir = os.path.join(tmpdir, "projects")
            project_dir = os.path.join(projects_dir, "test-project")
            os.makedirs(project_dir)

            session_id = "test-session-abc123"
            jsonl_file = os.path.join(project_dir, "{}.jsonl".format(session_id))
            with open(jsonl_file, "w") as f:
                # User message — no tool_use, should not count
                f.write('{"type":"user","message":{"content":"hello"}}\n')
                # Compact JSON tool_use — should count
                f.write('{"message":{"content":[{"type":"tool_use","name":"Bash","input":{}}]}}\n')
                # Text block — should not count
                f.write('{"message":{"content":[{"type":"text","text":"done"}]}}\n')
                # Spaced JSON tool_use — should count
                f.write('{"message":{"content":[{"type": "tool_use", "name": "Read", "input": {}}]}}\n')
                # False positive guard: message mentioning tool_use in text
                f.write('{"message":{"content":[{"type":"text","text":"the tool_use type is used"}]}}\n')

            orig_projects = sessions_mod._PROJECTS_DIR
            sessions_mod._PROJECTS_DIR = projects_dir

            # Clear cache
            import hashlib
            cache_key = "tools_{}".format(
                hashlib.md5(session_id.encode()).hexdigest()[:12]
            )
            _write_cache(cache_key, None)

            try:
                count = get_session_tool_count(session_id)
                self.assertEqual(count, 2)
            finally:
                sessions_mod._PROJECTS_DIR = orig_projects


# ─── cli.py — new sections ──────────────────────────────────────────

class TestBudgetSection(unittest.TestCase):
    def test_budget_warning_red(self):
        """Budget at 90%+ should show bold red — modernized for the
        v0.12.0 daily semantics: assert the day: chip value AND the
        actual red color (the original never asserted the color and
        its $0.95 assertion was satisfied by the adjacent cost chip).
        The module-scope cache redirect isolates the ledger; no sid is
        passed, so the in-memory started-today contribution renders."""
        import claude_statusline.cli as cli_mod
        from claude_statusline import sessions as sessions_mod
        orig = cli_mod.get_budget_config
        orig_record = cli_mod.record_and_get_daily_spend
        cli_mod.get_budget_config = lambda: 1.0
        # Pin the ledger clock to local noon (midnight determinism —
        # same rationale as TestDailySpendLedger.setUp).
        lt = time.localtime()
        noon = time.mktime(
            (lt.tm_year, lt.tm_mon, lt.tm_mday, 12, 0, 0, 0, 0, -1))
        cli_mod.record_and_get_daily_spend = (
            lambda sid, c, d: sessions_mod.record_and_get_daily_spend(
                sid, c, d, _now=noon))
        try:
            data = {
                "context_window": {"used_percentage": 30,
                                   "current_usage": {"input_tokens": 5000}},
                "cost": {"total_cost_usd": 0.95, "total_duration_ms": 60000},
                "git_branch": "main",
            }
            result = render(data)
            self.assertIn("day:$0.95/$1", re.sub(r"\x1b\[[0-9;]*m", "", result))
            self.assertIn(BRIGHT_RED, result)  # 95% >= 90% band
            # Whole-number budgets should display without trailing .0
            self.assertNotIn("$1.0", re.sub(r"\x1b\[[0-9;]*m", "", result))
        finally:
            cli_mod.get_budget_config = orig
            cli_mod.record_and_get_daily_spend = orig_record

    def test_budget_not_shown_without_config(self):
        """Without budget config, no budget section should appear."""
        import claude_statusline.cli as cli_mod
        orig = cli_mod.get_budget_config

        cli_mod.get_budget_config = lambda: None

        try:
            data = {
                "context_window": {"used_percentage": 30,
                                   "current_usage": {"input_tokens": 5000}},
                "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
                "git_branch": "main",
            }
            result = render(data)
            # Should have cost but not budget format ($X/$Y)
            self.assertNotIn("/$", result)
        finally:
            cli_mod.get_budget_config = orig


class TestToolsSection(unittest.TestCase):
    def test_tools_shown_with_session_id(self):
        """Tools count should appear when session has tool calls."""
        import claude_statusline.cli as cli_mod
        orig = cli_mod.get_session_tool_count

        cli_mod.get_session_tool_count = lambda sid: 42

        try:
            data = {
                "context_window": {"used_percentage": 30,
                                   "current_usage": {"input_tokens": 5000}},
                "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
                "session_id": "test-session",
                "git_branch": "main",
            }
            result = render(data)
            self.assertIn("tools:", result)
            self.assertIn("42", result)
        finally:
            cli_mod.get_session_tool_count = orig

    def test_tools_hidden_without_session_id(self):
        """Without session_id, tools section should not appear."""
        data = {
            "context_window": {"used_percentage": 30,
                               "current_usage": {"input_tokens": 5000}},
            "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
        }
        result = render(data)
        self.assertNotIn("tools:", result)


class TestSessionsSection(unittest.TestCase):
    def test_sessions_shown(self):
        """Sessions count should appear in output."""
        import claude_statusline.cli as cli_mod
        orig = cli_mod.get_today_session_count

        cli_mod.get_today_session_count = lambda: 5

        try:
            data = {
                "context_window": {"used_percentage": 30,
                                   "current_usage": {"input_tokens": 5000}},
                "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
                "git_branch": "main",
            }
            result = render(data)
            self.assertIn("sessions:", result)
            self.assertIn("5", result)
        finally:
            cli_mod.get_today_session_count = orig


# ─── cli.py — setup command ─────────────────────────────────────────

class TestSetupCommand(unittest.TestCase):
    def test_setup_flag_accepted(self):
        """--setup flag should be recognized by argument parser."""
        result = subprocess.run(
            [sys.executable, "-m", "claude_statusline", "--setup"],
            capture_output=True, timeout=15,
            input="1\n\n",  # choose default theme, skip budget
            encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("setup wizard", result.stdout)

    def test_demo_shows_all_themes(self):
        """Demo should show all 7 themes."""
        result = subprocess.run(
            [sys.executable, "-m", "claude_statusline", "--demo"],
            capture_output=True, timeout=15,
            encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        self.assertEqual(result.returncode, 0)
        for name in ("default", "minimal", "powerline",
                     "nord", "tokyo-night", "gruvbox", "rose-pine"):
            self.assertIn("{}:".format(name), result.stdout,
                          "Demo missing theme: {}".format(name))


# ─── cli.py — version and clock sections ────────────────────────────

class TestVersionSection(unittest.TestCase):
    def test_version_displayed(self):
        """Version string should appear in output."""
        data = {
            "context_window": {"used_percentage": 30,
                               "current_usage": {"input_tokens": 5000}},
            "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
            "git_branch": "main",
        }
        result = render(data)
        self.assertIn("v" + __version__, result)

    def test_clock_displayed(self):
        """Current time should appear in output."""
        data = {
            "context_window": {"used_percentage": 30,
                               "current_usage": {"input_tokens": 5000}},
            "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
            "git_branch": "main",
        }
        result = render(data)
        # Clock format is HH:MM — check for colon-separated digits
        self.assertRegex(result, r"\d{2}:\d{2}")


# ─── git.py — git extras ────────────────────────────────────────────

class TestGitExtras(unittest.TestCase):
    def test_returns_dict(self):
        from claude_statusline.git import get_git_extras
        result = get_git_extras()
        self.assertIsInstance(result, dict)
        self.assertIn("stash", result)
        self.assertIn("ahead", result)
        self.assertIn("behind", result)

    def test_values_are_ints(self):
        from claude_statusline.git import get_git_extras
        result = get_git_extras()
        self.assertIsInstance(result["stash"], int)
        self.assertIsInstance(result["ahead"], int)
        self.assertIsInstance(result["behind"], int)

    def test_git_extras_section_renders(self):
        """git_extras section should not crash even with no stash/sync data."""
        import claude_statusline.cli as cli_mod
        from claude_statusline.git import get_git_extras as orig_extras
        cli_mod.get_git_extras = lambda: {"stash": 0, "ahead": 0, "behind": 0}
        try:
            data = {
                "context_window": {"used_percentage": 30,
                                   "current_usage": {"input_tokens": 5000}},
                "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
                "git_branch": "main",
            }
            result = render(data)
            # Should render without crashing; no stash/sync = no extras shown
            self.assertIsInstance(result, str)
        finally:
            cli_mod.get_git_extras = orig_extras

    def test_git_extras_with_stash(self):
        """Stash count should appear when stash exists."""
        import claude_statusline.cli as cli_mod
        from claude_statusline.git import get_git_extras as orig_extras
        cli_mod.get_git_extras = lambda: {"stash": 3, "ahead": 0, "behind": 0}
        try:
            data = {
                "context_window": {"used_percentage": 30,
                                   "current_usage": {"input_tokens": 5000}},
                "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
                "git_branch": "main",
            }
            result = render(data)
            self.assertIn("stash:3", result)
        finally:
            cli_mod.get_git_extras = orig_extras

    def test_git_extras_with_ahead_behind(self):
        """Ahead/behind should appear when out of sync."""
        import claude_statusline.cli as cli_mod
        from claude_statusline.git import get_git_extras as orig_extras
        cli_mod.get_git_extras = lambda: {"stash": 0, "ahead": 2, "behind": 1}
        try:
            data = {
                "context_window": {"used_percentage": 30,
                                   "current_usage": {"input_tokens": 5000}},
                "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
                "git_branch": "main",
            }
            result = render(data)
            self.assertIn("sync:", result)
            self.assertIn("+2", result)
            self.assertIn("-1", result)
        finally:
            cli_mod.get_git_extras = orig_extras


# ─── bar.py — compaction threshold ──────────────────────────────────

class TestCompactionBar(unittest.TestCase):
    def test_bar_without_compaction(self):
        """Bar at 42% without compaction should show ~42% filled."""
        bar = render_bar(42, 20)
        self.assertIn("[", bar)

    def test_bar_with_compaction_scales_up(self):
        """Bar at 31% with 62% compaction threshold should scale to 50%."""
        bar = render_bar(31, 20, compaction_threshold=62)
        self.assertIn("[", bar)

    def test_bar_over_compaction_caps_at_100(self):
        """Bar at 70% with 62% threshold should cap at 100%."""
        bar = render_bar(70, 20, compaction_threshold=62)
        self.assertIn("[", bar)

    def test_bar_compaction_zero_ignored(self):
        """Compaction threshold of 0 should be ignored."""
        bar_normal = render_bar(42, 20)
        bar_zero = render_bar(42, 20, compaction_threshold=0)
        self.assertEqual(bar_normal, bar_zero)

    def test_bar_compaction_none_ignored(self):
        """Compaction threshold of None should be ignored."""
        bar_normal = render_bar(42, 20)
        bar_none = render_bar(42, 20, compaction_threshold=None)
        self.assertEqual(bar_normal, bar_none)


# ─── sessions.py — compaction config ────────────────────────────────

class TestCompactionConfig(unittest.TestCase):
    def test_compaction_threshold_valid(self):
        from claude_statusline.sessions import get_compaction_threshold, _cache_path
        import claude_statusline.sessions as sessions_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = os.path.join(tmpdir, "claude-status-budget.json")
            with open(config_file, "w") as f:
                json.dump({"compaction_threshold_pct": 62}, f)

            orig = sessions_mod._CLAUDE_DIR
            sessions_mod._CLAUDE_DIR = tmpdir
            try:
                os.unlink(_cache_path("status_config"))
            except OSError:
                pass
            try:
                result = get_compaction_threshold()
                self.assertAlmostEqual(result, 62.0)
            finally:
                sessions_mod._CLAUDE_DIR = orig

    def test_compaction_threshold_not_configured(self):
        from claude_statusline.sessions import get_compaction_threshold, _cache_path
        import claude_statusline.sessions as sessions_mod

        orig = sessions_mod._CLAUDE_DIR
        sessions_mod._CLAUDE_DIR = "/nonexistent/path"
        try:
            os.unlink(_cache_path("status_config"))
        except OSError:
            pass
        try:
            result = get_compaction_threshold()
            self.assertIsNone(result)
        finally:
            sessions_mod._CLAUDE_DIR = orig


# ─── cli.py — responsive layout ─────────────────────────────────────

class TestResponsiveLayout(unittest.TestCase):
    def test_full_layout_wide_terminal(self):
        """Wide terminal (230+) should keep all sections."""
        from claude_statusline.cli import _apply_responsive
        sections = ["bar", "tokens", "cache", "cost", "burn",
                    "git_extras", "version", "clock"]
        result = _apply_responsive(sections, 230)
        self.assertEqual(result, sections)

    def test_full_layout_above_threshold(self):
        """Well above threshold (300 cols) should keep all sections."""
        from claude_statusline.cli import _apply_responsive
        sections = ["bar", "tokens", "cache", "cost", "burn",
                    "git_extras", "version", "clock"]
        result = _apply_responsive(sections, 300)
        self.assertEqual(result, sections)

    def test_compact_layout_at_old_full_threshold(self):
        """A 120-col terminal (old full threshold) now gets compact.

        This is the core of #70: before v0.5.3, 120 cols returned the
        full layout, which had grown too wide for Line 2 to fit. 120
        now falls into the compact range and drops heavy extras.
        """
        from claude_statusline.cli import _apply_responsive
        sections = ["bar", "tokens", "cache", "cost", "burn",
                    "git_extras", "version", "clock", "context_size",
                    "rate_limits", "speed", "commit_age", "session_name"]
        result = _apply_responsive(sections, 120)
        self.assertIn("bar", result)
        self.assertIn("tokens", result)
        self.assertIn("cost", result)
        # These grew Line 2 past 120 cols — must be dropped at 120 now
        self.assertNotIn("git_extras", result)
        self.assertNotIn("version", result)
        self.assertNotIn("clock", result)
        self.assertNotIn("context_size", result)
        self.assertNotIn("rate_limits", result)
        self.assertNotIn("speed", result)
        self.assertNotIn("commit_age", result)
        self.assertNotIn("session_name", result)

    def test_compact_layout_medium_terminal(self):
        """Medium terminal (100-229) should drop non-essential sections."""
        from claude_statusline.cli import _apply_responsive
        sections = ["bar", "tokens", "cache", "cost", "burn",
                    "git_extras", "version", "clock", "context_size"]
        result = _apply_responsive(sections, 100)
        self.assertIn("bar", result)
        self.assertIn("tokens", result)
        self.assertIn("cost", result)
        self.assertNotIn("git_extras", result)
        self.assertNotIn("version", result)
        self.assertNotIn("clock", result)
        self.assertNotIn("context_size", result)

    def test_narrow_layout_small_terminal(self):
        """Narrow terminal (<100) should show only essentials."""
        from claude_statusline.cli import _apply_responsive
        sections = ["bar", "tokens", "cache", "cost", "burn",
                    "git_extras", "version", "clock", "lines", "budget", "model"]
        result = _apply_responsive(sections, 60)
        self.assertIn("bar", result)
        self.assertIn("tokens", result)
        self.assertIn("cost", result)
        self.assertNotIn("cache", result)
        self.assertNotIn("burn", result)
        self.assertNotIn("lines", result)
        self.assertNotIn("budget", result)
        self.assertNotIn("model", result)

    def test_boundary_at_compact_threshold(self):
        """99 cols (just below compact threshold) should use narrow layout."""
        from claude_statusline.cli import _apply_responsive
        sections = ["bar", "tokens", "cache", "cost"]
        result = _apply_responsive(sections, 99)
        self.assertIn("bar", result)
        self.assertNotIn("cache", result)  # cache is in _NARROW_DROP

    def test_boundary_at_full_threshold(self):
        """149 cols (just below full threshold) should use compact layout.

        The full-layout threshold was lowered from 230 → 150 in the
        width-aware-layout change because a precise post-render fit
        (_fit_to_width) handles the actual sizing — the coarse
        pre-filter only needs to skip expensive sections (git
        subprocess calls, file scans) on terminals where they will
        never fit.
        """
        from claude_statusline.cli import _apply_responsive
        sections = ["bar", "tokens", "cost", "git_extras"]
        result = _apply_responsive(sections, 149)
        self.assertIn("bar", result)
        self.assertNotIn("git_extras", result)  # compact drops git_extras

    def test_boundary_at_exactly_100_cols(self):
        """100 cols (inclusive compact boundary) — compact, not narrow.

        Pins the `>=` comparison at the compact threshold so a future
        off-by-one change to `>` would flip 100-col terminals to narrow
        and this test would fail.
        """
        from claude_statusline.cli import _apply_responsive
        sections = ["bar", "tokens", "cache", "cost", "burn",
                    "git_extras", "version", "clock", "lines", "model"]
        result = _apply_responsive(sections, 100)
        # Compact drops these
        self.assertNotIn("git_extras", result)
        self.assertNotIn("version", result)
        self.assertNotIn("clock", result)
        # Narrow-only drops; must still be present at 100
        self.assertIn("cache", result)
        self.assertIn("burn", result)
        self.assertIn("lines", result)
        self.assertIn("model", result)

    def test_render_fallback_when_columns_unset(self):
        """When COLUMNS is unset and no tty is attached, render() uses the
        (100, 24) fallback — which selects the compact layout, not full.

        Guards the deliberate v0.5.3 fallback change from (120, 24) to
        (100, 24). A revert to 120 would silently resurrect #70 in
        piped/non-tty contexts.
        """
        import claude_statusline.cli as cli_mod
        from claude_statusline.cli import _COMPACT_LAYOUT_MIN_COLS
        # The fallback constant must stay at 100 — or below full threshold.
        self.assertEqual(_COMPACT_LAYOUT_MIN_COLS, 100)
        # Verify get_terminal_size honors the fallback when COLUMNS is unset.
        import shutil
        old_cols = os.environ.pop("COLUMNS", None)
        try:
            size = shutil.get_terminal_size((_COMPACT_LAYOUT_MIN_COLS, 24))
            # When no tty and no COLUMNS, shutil returns the fallback.
            # (In CI COLUMNS may be unset and stdout non-tty → fallback wins.)
            # We can't force non-tty here portably, but we can at least
            # assert the constant is what render() passes in.
            self.assertGreaterEqual(size.columns, 1)
        finally:
            if old_cols is not None:
                os.environ["COLUMNS"] = old_cols


# ─── cli.py — width-aware fit ────────────────────────────────────────

class TestVisibleWidth(unittest.TestCase):
    """_visible_width strips ANSI/OSC 8 — Claude Code's Ink TUI counts
    visible glyphs only, so our fit math must match that."""

    def test_plain_text_width(self):
        from claude_statusline.cli import _visible_width
        self.assertEqual(_visible_width("hello"), 5)

    def test_empty_string(self):
        from claude_statusline.cli import _visible_width
        self.assertEqual(_visible_width(""), 0)

    def test_strips_sgr_color(self):
        from claude_statusline.cli import _visible_width
        # Red "abc" reset → visible width is 3
        self.assertEqual(_visible_width("\x1b[31mabc\x1b[0m"), 3)

    def test_strips_multiple_sgr(self):
        from claude_statusline.cli import _visible_width
        s = "\x1b[1m\x1b[31mbold red\x1b[0m \x1b[32mgreen\x1b[0m"
        self.assertEqual(_visible_width(s), len("bold red green"))

    def test_strips_osc8_hyperlink(self):
        """OSC 8 wrapper bytes are zero-width — only the link text counts."""
        from claude_statusline.cli import _visible_width
        s = "\x1b]8;;https://example.com\x1b\\link\x1b]8;;\x1b\\"
        self.assertEqual(_visible_width(s), len("link"))

    def test_strips_combined_osc8_and_sgr(self):
        from claude_statusline.cli import _visible_width
        s = "\x1b]8;;https://x.test\x1b\\\x1b[36mlinked\x1b[0m\x1b]8;;\x1b\\"
        self.assertEqual(_visible_width(s), len("linked"))

    def test_strips_osc8_with_bel_terminator(self):
        """OSC 8 also permits BEL (\\x07) as the string terminator (Kitty,
        GNU Screen wrappers, some Vim plugins). The regex must match
        both ST and BEL — otherwise BEL-form links inflate the measured
        width and _fit_to_width over-drops sections."""
        from claude_statusline.cli import _visible_width
        s = "\x1b]8;;https://example.com\x07link\x1b]8;;\x07"
        self.assertEqual(_visible_width(s), len("link"))

    def test_strips_osc8_mixed_terminators(self):
        """Defensive: opener with ST, closer with BEL (or vice versa) —
        each wrapper element matches the alternation independently."""
        from claude_statusline.cli import _visible_width
        s = "\x1b]8;;https://x\x1b\\link\x1b]8;;\x07"
        self.assertEqual(_visible_width(s), len("link"))


class TestFitToWidth(unittest.TestCase):
    """_fit_to_width drops sections in priority order until the line fits.

    Sections not in drop_priority are essential and must never be dropped
    (e.g. bar, tokens, cost, branch). Sections in drop_priority are
    dropped earliest-first when the line overflows."""

    def test_no_drop_when_fits(self):
        from claude_statusline.cli import _fit_to_width
        items = [("bar", "[####]"), ("cost", "$1.20")]
        result = _fit_to_width(items, sep_visible_width=3, target_width=80,
                               drop_priority=["clock", "version"])
        self.assertEqual(result, items)

    def test_drops_lowest_priority_first(self):
        """When over budget, the earliest entry in drop_priority is dropped."""
        from claude_statusline.cli import _fit_to_width
        items = [("bar", "[####]"),       # 6
                 ("clock", "12:34"),       # 5
                 ("version", "v0.5.3"),    # 6
                 ("cost", "$1.20")]        # 5
        # Total visible chars = 22 + 3 separators of width 3 = 31.
        # Set target=26 so we must drop one section. drop_priority drops
        # clock first.
        result = _fit_to_width(items, sep_visible_width=3, target_width=26,
                               drop_priority=["clock", "version"])
        names = [n for n, _ in result]
        self.assertNotIn("clock", names)
        self.assertIn("version", names)
        self.assertIn("bar", names)
        self.assertIn("cost", names)

    def test_drops_multiple_when_needed(self):
        from claude_statusline.cli import _fit_to_width
        items = [("bar", "[####]"),      # 6
                 ("clock", "12:34"),     # 5
                 ("version", "v0.5.3"),  # 6
                 ("cost", "$1.20")]      # 5
        # Force a tiny target so both droppable sections must go.
        result = _fit_to_width(items, sep_visible_width=3, target_width=15,
                               drop_priority=["clock", "version"])
        names = [n for n, _ in result]
        self.assertEqual(names, ["bar", "cost"])

    def test_never_drops_essential_sections(self):
        """Sections not in drop_priority are kept even if line still overflows."""
        from claude_statusline.cli import _fit_to_width
        items = [("bar", "[####]"), ("cost", "$1.20")]
        # Target so small nothing fits, but neither section is droppable.
        result = _fit_to_width(items, sep_visible_width=3, target_width=2,
                               drop_priority=["clock", "version"])
        # Both essentials remain — _fit_to_width never drops sections
        # that aren't in the priority list.
        self.assertEqual(result, items)

    def test_strips_ansi_when_measuring(self):
        """Width math must use visible width, not raw byte length."""
        from claude_statusline.cli import _fit_to_width
        # Each item is 6 visible chars but ~16 bytes with ANSI.
        items = [("bar", "\x1b[31m[####]\x1b[0m"),
                 ("clock", "\x1b[90m12:34\x1b[0m"),
                 ("cost", "\x1b[33m$1.20\x1b[0m")]
        # Visible total = 6+5+5 = 16 + 2 seps of width 1 = 18. Fits in 20.
        result = _fit_to_width(items, sep_visible_width=1, target_width=20,
                               drop_priority=["clock"])
        self.assertEqual(len(result), 3)  # nothing dropped

    def test_preserves_order(self):
        from claude_statusline.cli import _fit_to_width
        items = [("a", "AA"), ("b", "BB"), ("c", "CC"), ("d", "DD")]
        # Drop b but keep a, c, d in original order.
        result = _fit_to_width(items, sep_visible_width=1, target_width=8,
                               drop_priority=["b"])
        names = [n for n, _ in result]
        self.assertEqual(names, ["a", "c", "d"])


class TestRenderFitsTerminalWidth(unittest.TestCase):
    """End-to-end: render() must produce output where each line fits the
    reported terminal width. This is the user-visible contract — Claude
    Code's Ink TUI drops Line 2 if Line 1 exceeds the terminal width."""

    def _measure_lines(self, output):
        from claude_statusline.cli import _visible_width
        return [_visible_width(line) for line in output.split("\n")]

    def test_render_fits_at_120_cols(self):
        """At 120 cols, every output line must be ≤ 120 visible chars."""
        from claude_statusline.cli import render, _demo_data
        old = os.environ.get("COLUMNS")
        os.environ["COLUMNS"] = "120"
        try:
            out = render(_demo_data())
            for w in self._measure_lines(out):
                self.assertLessEqual(w, 120,
                    "Line of width {} exceeds terminal width 120".format(w))
        finally:
            if old is None:
                os.environ.pop("COLUMNS", None)
            else:
                os.environ["COLUMNS"] = old

    def test_render_fits_at_150_cols(self):
        from claude_statusline.cli import render, _demo_data
        old = os.environ.get("COLUMNS")
        os.environ["COLUMNS"] = "150"
        try:
            out = render(_demo_data())
            for w in self._measure_lines(out):
                self.assertLessEqual(w, 150)
        finally:
            if old is None:
                os.environ.pop("COLUMNS", None)
            else:
                os.environ["COLUMNS"] = old

    def test_render_fits_at_180_cols(self):
        from claude_statusline.cli import render, _demo_data
        old = os.environ.get("COLUMNS")
        os.environ["COLUMNS"] = "180"
        try:
            out = render(_demo_data())
            for w in self._measure_lines(out):
                self.assertLessEqual(w, 180)
        finally:
            if old is None:
                os.environ.pop("COLUMNS", None)
            else:
                os.environ["COLUMNS"] = old


# ─── cli.py — rate limits section ────────────────────────────────────

class TestRateLimits(unittest.TestCase):
    def _data_with_limits(self, five_h_pct=None, seven_d_pct=None,
                          five_h_resets=None, seven_d_resets=None):
        data = {
            "context_window": {"used_percentage": 30,
                               "current_usage": {"input_tokens": 5000}},
            "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
            "git_branch": "main",
        }
        rl = {}
        if five_h_pct is not None:
            rl["five_hour"] = {"used_percentage": five_h_pct}
            if five_h_resets is not None:
                rl["five_hour"]["resets_at"] = five_h_resets
        if seven_d_pct is not None:
            rl["seven_day"] = {"used_percentage": seven_d_pct}
            if seven_d_resets is not None:
                rl["seven_day"]["resets_at"] = seven_d_resets
        if rl:
            data["rate_limits"] = rl
        return data

    def test_rate_limits_displayed(self):
        """Rate limits should appear when present."""
        data = self._data_with_limits(five_h_pct=34, seven_d_pct=18)
        result = render(data)
        self.assertIn("5h:34%", result)
        self.assertIn("7d:18%", result)

    def test_rate_limits_hidden_when_absent(self):
        """Rate limits should not appear for non-Pro users."""
        data = {
            "context_window": {"used_percentage": 30,
                               "current_usage": {"input_tokens": 5000}},
            "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
            "git_branch": "main",
        }
        result = render(data)
        self.assertNotIn("5h:", result)
        self.assertNotIn("7d:", result)

    def test_rate_limits_only_5h(self):
        """Should handle only 5-hour limit present."""
        data = self._data_with_limits(five_h_pct=72)
        result = render(data)
        self.assertIn("5h:72%", result)
        self.assertNotIn("7d:", result)

    def test_rate_limits_zero_values(self):
        """Zero percentages should display correctly."""
        data = self._data_with_limits(five_h_pct=0, seven_d_pct=0)
        result = render(data)
        self.assertIn("5h:0%", result)
        self.assertIn("7d:0%", result)

    def test_rate_limits_with_countdown(self):
        """Reset countdown should appear when resets_at is in the future."""
        future_sec = int(time.time()) + 7_200  # 2 hours from now (seconds)
        data = self._data_with_limits(five_h_pct=50, five_h_resets=future_sec)
        result = render(data)
        self.assertIn("5h:50%", result)
        self.assertIn("~", result)  # countdown prefix

    def test_rate_limits_only_7d(self):
        """Should handle only 7-day limit present."""
        data = self._data_with_limits(seven_d_pct=45)
        result = render(data)
        self.assertIn("7d:45%", result)
        self.assertNotIn("5h:", result)

    def test_rate_limits_high_percentage(self):
        """100% should display correctly."""
        data = self._data_with_limits(five_h_pct=100)
        result = render(data)
        self.assertIn("5h:100%", result)

    def test_rate_limits_float_percentage(self):
        """Float percentage should be truncated to int."""
        data = self._data_with_limits(five_h_pct=99.7)
        result = render(data)
        self.assertIn("5h:99%", result)

    def test_rate_limits_clamped_above_100(self):
        """Values modestly above 100% (e.g. 105) still flow through
        the renderer's clamp(0, 100) and display as `5h:100%` — this
        is the legitimate "user is maxed out" UI for any future
        Anthropic 'overage' indicator. Only values >= 1e6 (the upstream
        epoch-timestamp bug pattern) are pre-emptively hidden.

        See TestRateLimitsEpochTimestampGuard for the full contract.
        """
        data = self._data_with_limits(five_h_pct=105)
        result = render(data)
        self.assertIn("5h:100%", result,
            "values modestly above 100 should clamp to 100% in the UI, "
            "not be silently hidden — only the epoch-timestamp bug "
            "pattern (>= 1e6) triggers the hide-section guard")

    def test_rate_limits_nearest_reset(self):
        """Should show countdown to the nearest reset when both present."""
        now = int(time.time())
        data = self._data_with_limits(
            five_h_pct=50, five_h_resets=now + 3_600,      # 1h (seconds)
            seven_d_pct=20, seven_d_resets=now + 86_400,   # 24h (seconds)
        )
        result = render(data)
        # Should show ~59m or ~1h, not ~24h
        self.assertIn("~", result)


class TestRateLimitsResetConversion(unittest.TestCase):
    """Verify resets_at seconds-to-milliseconds conversion."""

    def test_resets_at_seconds_converted_to_ms(self):
        """resets_at in seconds should produce a valid countdown."""
        from claude_statusline.cli import _normalize
        # Real Claude Code sends epoch seconds (roughly 1.7 billion)
        future_sec = int(time.time()) + 3600  # 1 hour from now
        data = {
            "rate_limits": {
                "five_hour": {
                    "used_percentage": 50,
                    "resets_at": future_sec,
                },
            },
        }
        n = _normalize(data)
        # Should be converted to milliseconds internally
        self.assertIsNotNone(n["rate_limit_5h_resets"])
        self.assertGreater(n["rate_limit_5h_resets"], future_sec)
        # Should be roughly future_sec * 1000
        self.assertAlmostEqual(
            n["rate_limit_5h_resets"], future_sec * 1000, delta=1000
        )

    def test_resets_at_none_stays_none(self):
        """Missing resets_at should remain None after conversion."""
        from claude_statusline.cli import _normalize
        data = {
            "rate_limits": {
                "five_hour": {"used_percentage": 50},
            },
        }
        n = _normalize(data)
        self.assertIsNone(n["rate_limit_5h_resets"])


class TestRateLimitsMalformed(unittest.TestCase):
    """Rate limits must never crash on malformed input."""

    def _base_data(self):
        return {
            "context_window": {"used_percentage": 30,
                               "current_usage": {"input_tokens": 5000}},
            "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
            "git_branch": "main",
        }

    def test_rate_limits_as_string(self):
        data = self._base_data()
        data["rate_limits"] = "rate_limited"
        result = render(data)
        self.assertIsInstance(result, str)

    def test_rate_limits_as_list(self):
        data = self._base_data()
        data["rate_limits"] = [1, 2, 3]
        result = render(data)
        self.assertIsInstance(result, str)

    def test_percentage_as_string(self):
        data = self._base_data()
        data["rate_limits"] = {"five_hour": {"used_percentage": "34%"}}
        result = render(data)
        self.assertIsInstance(result, str)

    def test_resets_at_as_iso_string(self):
        data = self._base_data()
        data["rate_limits"] = {"five_hour": {
            "used_percentage": 34,
            "resets_at": "2026-04-05T12:00:00Z",
        }}
        result = render(data)
        self.assertIsInstance(result, str)

    def test_five_hour_as_non_dict(self):
        data = self._base_data()
        data["rate_limits"] = {"five_hour": "invalid"}
        result = render(data)
        self.assertIsInstance(result, str)

    def test_negative_percentage(self):
        data = self._base_data()
        data["rate_limits"] = {"five_hour": {"used_percentage": -5}}
        result = render(data)
        self.assertIn("5h:0%", result)


# ─── cli.py — session name section ──────────────────────────────────

class TestSessionName(unittest.TestCase):
    def test_session_name_displayed(self):
        """Session name should appear with icon when set."""
        data = {
            "context_window": {"used_percentage": 30,
                               "current_usage": {"input_tokens": 5000}},
            "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
            "session_name": "refactor auth",
            "git_branch": "main",
        }
        result = render(data)
        self.assertIn("refactor auth", result)
        self.assertIn("\u2726", result)

    def test_session_name_hidden_when_absent(self):
        """Session name should not appear when not set."""
        data = {
            "context_window": {"used_percentage": 30,
                               "current_usage": {"input_tokens": 5000}},
            "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
            "git_branch": "main",
        }
        result = render(data)
        self.assertNotIn("\u2726", result)

    def test_session_name_hidden_when_empty(self):
        """Empty session name should not render."""
        data = {
            "context_window": {"used_percentage": 30,
                               "current_usage": {"input_tokens": 5000}},
            "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
            "session_name": "",
            "git_branch": "main",
        }
        result = render(data)
        self.assertNotIn("\u2726", result)


# ─── cli.py — Claude Code version section ───────────────────────────

class TestCCVersion(unittest.TestCase):
    def test_cc_version_displayed(self):
        """Claude Code version should appear when present."""
        data = {
            "context_window": {"used_percentage": 30,
                               "current_usage": {"input_tokens": 5000}},
            "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
            "version": "2.1.92",
            "git_branch": "main",
        }
        result = render(data)
        self.assertIn("CC:2.1.92", result)

    def test_cc_version_hidden_when_absent(self):
        """CC version should not appear when not in payload."""
        data = {
            "context_window": {"used_percentage": 30,
                               "current_usage": {"input_tokens": 5000}},
            "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
            "git_branch": "main",
        }
        result = render(data)
        self.assertNotIn("CC:", result)

    def test_cc_version_hidden_when_empty(self):
        """Empty version string should not render."""
        data = {
            "context_window": {"used_percentage": 30,
                               "current_usage": {"input_tokens": 5000}},
            "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
            "version": "",
            "git_branch": "main",
        }
        result = render(data)
        self.assertNotIn("CC:", result)


# ─── formatters.py — countdown ──────────────────────────────────────

class TestFmtCountdown(unittest.TestCase):
    def test_future_timestamp(self):
        """Future timestamp should return countdown string."""
        from claude_statusline.formatters import fmt_countdown
        future_ms = int(time.time() * 1000) + 7_200_000  # 2h from now
        result = fmt_countdown(future_ms)
        self.assertTrue(result.startswith("~"))
        self.assertIn("h", result)

    def test_past_timestamp(self):
        """Past timestamp should return empty string."""
        from claude_statusline.formatters import fmt_countdown
        past_ms = int(time.time() * 1000) - 60_000
        result = fmt_countdown(past_ms)
        self.assertEqual(result, "")

    def test_none_timestamp(self):
        """None should return empty string."""
        from claude_statusline.formatters import fmt_countdown
        self.assertEqual(fmt_countdown(None), "")


# ─── cli.py — output style section ──────────────────────────────────

class TestOutputStyle(unittest.TestCase):
    def _base_data(self, **extra):
        data = {
            "context_window": {"used_percentage": 30,
                               "current_usage": {"input_tokens": 5000}},
            "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
            "git_branch": "main",
        }
        data.update(extra)
        return data

    def test_output_style_displayed(self):
        data = self._base_data(output_style={"name": "explanatory"})
        result = render(data)
        self.assertIn("style:explanatory", result)

    def test_output_style_hidden_when_absent(self):
        data = self._base_data()
        result = render(data)
        self.assertNotIn("style:", result)

    def test_output_style_hidden_when_empty(self):
        data = self._base_data(output_style={"name": ""})
        result = render(data)
        self.assertNotIn("style:", result)

    def test_output_style_non_dict(self):
        """Non-dict output_style should not crash."""
        data = self._base_data(output_style="concise")
        result = render(data)
        self.assertIsInstance(result, str)

    def test_output_style_null_name(self):
        data = self._base_data(output_style={"name": None})
        result = render(data)
        self.assertNotIn("style:", result)


# ─── cli.py — added directories section ─────────────────────────────

class TestAddedDirs(unittest.TestCase):
    def _base_data(self, **extra):
        data = {
            "context_window": {"used_percentage": 30,
                               "current_usage": {"input_tokens": 5000}},
            "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
            "git_branch": "main",
        }
        data.update(extra)
        return data

    def test_added_dirs_displayed(self):
        data = self._base_data(workspace={
            "project_dir": "/home/user/myapp",
            "added_dirs": ["/lib1", "/lib2"],
        })
        result = render(data)
        self.assertIn("dirs:+2", result)

    def test_added_dirs_hidden_when_empty(self):
        data = self._base_data(workspace={
            "project_dir": "/home/user/myapp",
            "added_dirs": [],
        })
        result = render(data)
        self.assertNotIn("dirs:", result)

    def test_added_dirs_hidden_when_absent(self):
        data = self._base_data()
        result = render(data)
        self.assertNotIn("dirs:", result)

    def test_added_dirs_non_list(self):
        """Non-list added_dirs should not crash."""
        data = self._base_data(workspace={
            "project_dir": "/home/user/myapp",
            "added_dirs": "not a list",
        })
        result = render(data)
        self.assertIsInstance(result, str)
        self.assertNotIn("dirs:", result)


# ─── sessions.py — effort level ─────────────────────────────────────

class TestEffortLevel(unittest.TestCase):
    def test_effort_high(self):
        from claude_statusline.sessions import get_effort_level, _cache_path
        import claude_statusline.sessions as sessions_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = os.path.join(tmpdir, "settings.json")
            with open(settings_file, "w") as f:
                json.dump({"effortLevel": "high"}, f)

            orig = sessions_mod._CLAUDE_DIR
            sessions_mod._CLAUDE_DIR = tmpdir
            try:
                os.unlink(_cache_path("effort_level"))
            except OSError:
                pass
            try:
                result = get_effort_level()
                self.assertEqual(result, "high")
            finally:
                sessions_mod._CLAUDE_DIR = orig

    def test_effort_medium_returns_none(self):
        """Medium is the default — should return None to hide the section."""
        from claude_statusline.sessions import get_effort_level, _cache_path
        import claude_statusline.sessions as sessions_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = os.path.join(tmpdir, "settings.json")
            with open(settings_file, "w") as f:
                json.dump({"effortLevel": "medium"}, f)

            orig = sessions_mod._CLAUDE_DIR
            sessions_mod._CLAUDE_DIR = tmpdir
            try:
                os.unlink(_cache_path("effort_level"))
            except OSError:
                pass
            try:
                result = get_effort_level()
                self.assertIsNone(result)
            finally:
                sessions_mod._CLAUDE_DIR = orig

    def test_effort_low(self):
        from claude_statusline.sessions import get_effort_level, _cache_path
        import claude_statusline.sessions as sessions_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = os.path.join(tmpdir, "settings.json")
            with open(settings_file, "w") as f:
                json.dump({"effortLevel": "low"}, f)

            orig = sessions_mod._CLAUDE_DIR
            sessions_mod._CLAUDE_DIR = tmpdir
            try:
                os.unlink(_cache_path("effort_level"))
            except OSError:
                pass
            try:
                result = get_effort_level()
                self.assertEqual(result, "low")
            finally:
                sessions_mod._CLAUDE_DIR = orig

    def test_effort_xhigh(self):
        """Opus 4.7 (Claude Code v2.1.111+) introduced `xhigh` between
        `high` and `max`. Must be accepted by get_effort_level()."""
        from claude_statusline.sessions import get_effort_level, _cache_path
        import claude_statusline.sessions as sessions_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = os.path.join(tmpdir, "settings.json")
            with open(settings_file, "w") as f:
                json.dump({"effortLevel": "xhigh"}, f)

            orig = sessions_mod._CLAUDE_DIR
            sessions_mod._CLAUDE_DIR = tmpdir
            try:
                os.unlink(_cache_path("effort_level"))
            except OSError:
                pass
            try:
                result = get_effort_level()
                self.assertEqual(result, "xhigh")
            finally:
                sessions_mod._CLAUDE_DIR = orig

    def test_effort_max(self):
        """`max` is the top-tier effort level (above xhigh) — visible
        in Anthropic's Auto Mode references and `/effort max` toast.
        Without this, Pro/Max users on max would silently lose the
        effort indicator."""
        from claude_statusline.sessions import get_effort_level, _cache_path
        import claude_statusline.sessions as sessions_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = os.path.join(tmpdir, "settings.json")
            with open(settings_file, "w") as f:
                json.dump({"effortLevel": "max"}, f)

            orig = sessions_mod._CLAUDE_DIR
            sessions_mod._CLAUDE_DIR = tmpdir
            try:
                os.unlink(_cache_path("effort_level"))
            except OSError:
                pass
            try:
                result = get_effort_level()
                self.assertEqual(result, "max")
            finally:
                sessions_mod._CLAUDE_DIR = orig

    def test_effort_xhigh_case_insensitive(self):
        """Production code does `raw.lower()` — settings.json values
        like "XHIGH" or "Xhigh" must still resolve to "xhigh". Pins
        the contract so a future refactor can't silently drop the
        case-folding."""
        from claude_statusline.sessions import get_effort_level, _cache_path
        import claude_statusline.sessions as sessions_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = os.path.join(tmpdir, "settings.json")
            with open(settings_file, "w") as f:
                json.dump({"effortLevel": "XHIGH"}, f)

            orig = sessions_mod._CLAUDE_DIR
            sessions_mod._CLAUDE_DIR = tmpdir
            try:
                os.unlink(_cache_path("effort_level"))
            except OSError:
                pass
            try:
                result = get_effort_level()
                self.assertEqual(result, "xhigh")
            finally:
                sessions_mod._CLAUDE_DIR = orig

    def test_effort_xhigh_cache_hit_path(self):
        """The cache-hit path in get_effort_level() also goes through
        the `_VALID_EFFORT_LEVELS` membership check. A future change
        that updates the disk-read validator but forgets the cache-read
        validator would silently break xhigh on warm caches. This test
        pins the cache-hit path independently."""
        from claude_statusline.sessions import (
            get_effort_level, _cache_path, _write_cache,
        )
        import claude_statusline.sessions as sessions_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            orig = sessions_mod._CLAUDE_DIR
            sessions_mod._CLAUDE_DIR = tmpdir
            # Seed the cache directly so we exercise the cache-read
            # path, not the disk-read path. Removing settings.json
            # ensures get_effort_level can't fall through to disk and
            # accidentally pass via the wrong code path.
            try:
                _write_cache("effort_level", {"effort": "xhigh"})
                result = get_effort_level()
                self.assertEqual(result, "xhigh",
                    "cache-hit path must also recognize xhigh — "
                    "_VALID_EFFORT_LEVELS check applies on both paths")
            finally:
                sessions_mod._CLAUDE_DIR = orig

    def test_effort_absent_returns_none(self):
        from claude_statusline.sessions import get_effort_level, _cache_path
        import claude_statusline.sessions as sessions_mod

        orig = sessions_mod._CLAUDE_DIR
        sessions_mod._CLAUDE_DIR = "/nonexistent/path"
        try:
            os.unlink(_cache_path("effort_level"))
        except OSError:
            pass
        try:
            result = get_effort_level()
            self.assertIsNone(result)
        finally:
            sessions_mod._CLAUDE_DIR = orig

    def test_effort_invalid_value(self):
        from claude_statusline.sessions import get_effort_level, _cache_path
        import claude_statusline.sessions as sessions_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = os.path.join(tmpdir, "settings.json")
            with open(settings_file, "w") as f:
                json.dump({"effortLevel": "ultrathink"}, f)

            orig = sessions_mod._CLAUDE_DIR
            sessions_mod._CLAUDE_DIR = tmpdir
            try:
                os.unlink(_cache_path("effort_level"))
            except OSError:
                pass
            try:
                result = get_effort_level()
                self.assertIsNone(result)
            finally:
                sessions_mod._CLAUDE_DIR = orig


class TestEffortSection(unittest.TestCase):
    def test_effort_high_rendered(self):
        import claude_statusline.cli as cli_mod
        orig = cli_mod.get_effort_level
        cli_mod.get_effort_level = lambda: "high"
        try:
            data = {
                "context_window": {"used_percentage": 30,
                                   "current_usage": {"input_tokens": 5000}},
                "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
                "git_branch": "main",
            }
            result = render(data)
            self.assertIn("effort:high", result)
        finally:
            cli_mod.get_effort_level = orig

    def test_effort_hidden_when_none(self):
        import claude_statusline.cli as cli_mod
        orig = cli_mod.get_effort_level
        cli_mod.get_effort_level = lambda: None
        try:
            data = {
                "context_window": {"used_percentage": 30,
                                   "current_usage": {"input_tokens": 5000}},
                "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
                "git_branch": "main",
            }
            result = render(data)
            self.assertNotIn("effort:", result)
        finally:
            cli_mod.get_effort_level = orig

    def test_effort_low_rendered(self):
        """Effort low should display with dim color."""
        import claude_statusline.cli as cli_mod
        orig = cli_mod.get_effort_level
        cli_mod.get_effort_level = lambda: "low"
        try:
            data = {
                "context_window": {"used_percentage": 30,
                                   "current_usage": {"input_tokens": 5000}},
                "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
                "git_branch": "main",
            }
            result = render(data)
            self.assertIn("effort:low", result)
        finally:
            cli_mod.get_effort_level = orig

    def test_effort_xhigh_rendered(self):
        """xhigh (Opus 4.7) renders the same way as high but uses the
        dedicated effort_xhigh color key. The literal `effort:xhigh`
        text must appear in the rendered output."""
        import claude_statusline.cli as cli_mod
        orig = cli_mod.get_effort_level
        cli_mod.get_effort_level = lambda: "xhigh"
        try:
            data = {
                "context_window": {"used_percentage": 30,
                                   "current_usage": {"input_tokens": 5000}},
                "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
                "git_branch": "main",
            }
            result = render(data)
            self.assertIn("effort:xhigh", result)
        finally:
            cli_mod.get_effort_level = orig

    def test_effort_xhigh_uses_dedicated_color_key(self):
        """A theme that overrides effort_xhigh to a distinct color must
        have that color used for xhigh — proves the cli.py branch picks
        the xhigh-specific key, not the high fallback.
        """
        import claude_statusline.cli as cli_mod
        from claude_statusline.colors import CYAN
        from claude_statusline.themes import THEMES
        # Save & override the default theme's effort_xhigh to a known
        # distinct color (CYAN, not BRIGHT_MAGENTA which both high and
        # default xhigh use).
        orig_theme_color = THEMES["default"]["colors"]["effort_xhigh"]
        THEMES["default"]["colors"]["effort_xhigh"] = CYAN
        orig_get_effort = cli_mod.get_effort_level
        cli_mod.get_effort_level = lambda: "xhigh"
        try:
            data = {
                "context_window": {"used_percentage": 30,
                                   "current_usage": {"input_tokens": 5000}},
                "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
                "git_branch": "main",
            }
            result = render(data)
            # CYAN escape (\x1b[36m) must appear before "effort:xhigh"
            self.assertIn("\x1b[36m", result,
                "effort_xhigh color key was not used — xhigh branch may be "
                "falling back to effort_high or effort_low instead")
            self.assertIn("effort:xhigh", result)
        finally:
            cli_mod.get_effort_level = orig_get_effort
            THEMES["default"]["colors"]["effort_xhigh"] = orig_theme_color

    def test_effort_max_rendered(self):
        """`max` must render with the literal `effort:max` text. Same
        renderer path as xhigh, dedicated `effort_max` color key."""
        import claude_statusline.cli as cli_mod
        orig = cli_mod.get_effort_level
        cli_mod.get_effort_level = lambda: "max"
        try:
            data = {
                "context_window": {"used_percentage": 30,
                                   "current_usage": {"input_tokens": 5000}},
                "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
                "git_branch": "main",
            }
            result = render(data)
            self.assertIn("effort:max", result)
        finally:
            cli_mod.get_effort_level = orig

    def test_effort_xhigh_color_key_explicit_None_does_not_crash(self):
        """A custom theme that explicitly sets `effort_xhigh: None`
        (common when YAML/JSON tools serialize "no value" as null)
        must not crash colorize(). The renderer uses _first() so an
        explicit None falls through to the next key in the chain
        instead of being passed to colorize() and triggering a
        TypeError on `"".join((None, ...))`."""
        import claude_statusline.cli as cli_mod
        from claude_statusline.themes import THEMES
        orig_xhigh = THEMES["default"]["colors"]["effort_xhigh"]
        orig_get_effort = cli_mod.get_effort_level
        THEMES["default"]["colors"]["effort_xhigh"] = None
        cli_mod.get_effort_level = lambda: "xhigh"
        try:
            data = {
                "context_window": {"used_percentage": 30,
                                   "current_usage": {"input_tokens": 5000}},
                "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
                "git_branch": "main",
            }
            # Must not raise.
            result = render(data)
            self.assertIn("effort:xhigh", result,
                "render() crashed or hid effort when effort_xhigh was None")
        finally:
            cli_mod.get_effort_level = orig_get_effort
            THEMES["default"]["colors"]["effort_xhigh"] = orig_xhigh

    def test_effort_xhigh_falls_back_to_high_color_when_key_missing(self):
        """Custom themes pinned at older versions won't have
        effort_xhigh defined. The renderer must fall back to
        effort_high (not effort_low or hard-coded), since xhigh is
        semantically "above high"."""
        import claude_statusline.cli as cli_mod
        from claude_statusline.colors import CYAN, RED
        from claude_statusline.themes import THEMES
        # Remove effort_xhigh, set effort_high to a distinct color.
        orig_xhigh = THEMES["default"]["colors"].pop("effort_xhigh")
        orig_high = THEMES["default"]["colors"]["effort_high"]
        THEMES["default"]["colors"]["effort_high"] = CYAN
        orig_get_effort = cli_mod.get_effort_level
        cli_mod.get_effort_level = lambda: "xhigh"
        try:
            data = {
                "context_window": {"used_percentage": 30,
                                   "current_usage": {"input_tokens": 5000}},
                "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
                "git_branch": "main",
            }
            result = render(data)
            # Should fall back to effort_high (CYAN), NOT to BRIGHT_BLACK
            # (which is effort_low) and NOT to RED (which is unrelated).
            self.assertIn("\x1b[36m", result,
                "xhigh should fall back to effort_high color when "
                "effort_xhigh key is missing from the theme")
            self.assertNotIn(RED, result,
                "xhigh fallback picked an unrelated color")
        finally:
            cli_mod.get_effort_level = orig_get_effort
            THEMES["default"]["colors"]["effort_xhigh"] = orig_xhigh
            THEMES["default"]["colors"]["effort_high"] = orig_high


class TestEffortLevelCorrupted(unittest.TestCase):
    def test_corrupted_settings_returns_none(self):
        """Invalid JSON in settings.json should return None gracefully."""
        from claude_statusline.sessions import get_effort_level, _cache_path
        import claude_statusline.sessions as sessions_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = os.path.join(tmpdir, "settings.json")
            with open(settings_file, "w") as f:
                f.write("{not valid json")

            orig = sessions_mod._CLAUDE_DIR
            sessions_mod._CLAUDE_DIR = tmpdir
            try:
                os.unlink(_cache_path("effort_level"))
            except OSError:
                pass
            try:
                result = get_effort_level()
                self.assertIsNone(result)
            finally:
                sessions_mod._CLAUDE_DIR = orig

    def test_non_dict_settings_returns_none(self):
        """settings.json containing a JSON array should not crash."""
        from claude_statusline.sessions import get_effort_level, _cache_path
        import claude_statusline.sessions as sessions_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = os.path.join(tmpdir, "settings.json")
            with open(settings_file, "w") as f:
                json.dump([1, 2, 3], f)

            orig = sessions_mod._CLAUDE_DIR
            sessions_mod._CLAUDE_DIR = tmpdir
            try:
                os.unlink(_cache_path("effort_level"))
            except OSError:
                pass
            try:
                result = get_effort_level()
                self.assertIsNone(result)
            finally:
                sessions_mod._CLAUDE_DIR = orig


class TestAddedDirsExtra(unittest.TestCase):
    def test_single_added_dir(self):
        """Single added directory should show dirs:+1."""
        data = {
            "context_window": {"used_percentage": 30,
                               "current_usage": {"input_tokens": 5000}},
            "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
            "git_branch": "main",
            "workspace": {
                "project_dir": "/home/user/myapp",
                "added_dirs": ["/lib1"],
            },
        }
        result = render(data)
        self.assertIn("dirs:+1", result)


class TestOutputStyleExtra(unittest.TestCase):
    def test_output_style_non_string_name(self):
        """Non-string name value should not crash."""
        data = {
            "context_window": {"used_percentage": 30,
                               "current_usage": {"input_tokens": 5000}},
            "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
            "git_branch": "main",
            "output_style": {"name": ["not", "a", "string"]},
        }
        result = render(data)
        self.assertNotIn("style:", result)

    def test_output_style_missing_name_key(self):
        """output_style dict without name key should not crash."""
        data = {
            "context_window": {"used_percentage": 30,
                               "current_usage": {"input_tokens": 5000}},
            "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
            "git_branch": "main",
            "output_style": {},
        }
        result = render(data)
        self.assertNotIn("style:", result)


# ─── cli.py — git worktree indicator ────────────────────────────────

class TestGitWorktree(unittest.TestCase):
    def _base_data(self, **extra):
        data = {
            "context_window": {"used_percentage": 30,
                               "current_usage": {"input_tokens": 5000}},
            "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
            "git_branch": "main",
        }
        data.update(extra)
        return data

    def test_git_worktree_shown_when_true(self):
        data = self._base_data(workspace={
            "project_dir": "/home/user/myapp",
            "git_worktree": True,
        })
        result = render(data)
        self.assertIn("gwt", result)

    def test_git_worktree_hidden_when_false(self):
        data = self._base_data(workspace={
            "project_dir": "/home/user/myapp",
            "git_worktree": False,
        })
        result = render(data)
        self.assertNotIn("gwt", result)

    def test_git_worktree_hidden_when_absent(self):
        data = self._base_data()
        result = render(data)
        self.assertNotIn("gwt", result)

    def test_git_worktree_non_boolean(self):
        """Non-boolean value should not crash."""
        data = self._base_data(workspace={
            "project_dir": "/home/user/myapp",
            "git_worktree": "yes",
        })
        result = render(data)
        # Truthy string should show the indicator
        self.assertIn("gwt", result)


# ─── cli.py — uninstall command ─────────────────────────────────────

class TestUninstall(unittest.TestCase):
    def test_uninstall_removes_statusline(self):
        """--uninstall should remove statusLine from settings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = os.path.join(tmpdir, "settings.json")
            with open(settings_file, "w") as f:
                json.dump({
                    "statusLine": {"type": "command", "command": "claude-status"},
                    "otherKey": "preserved",
                }, f)

            import claude_statusline.cli as cli_mod
            orig = cli_mod._settings_path
            cli_mod._settings_path = lambda: settings_file
            try:
                cli_mod.cmd_uninstall()
                with open(settings_file, "r") as f:
                    settings = json.load(f)
                self.assertNotIn("statusLine", settings)
                self.assertEqual(settings["otherKey"], "preserved")
            finally:
                cli_mod._settings_path = orig

    def test_uninstall_restores_from_backup(self):
        """--uninstall should restore previous config from .bak."""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = os.path.join(tmpdir, "settings.json")
            backup_file = settings_file + ".bak"

            # Current settings
            with open(settings_file, "w") as f:
                json.dump({
                    "statusLine": {"type": "command", "command": "claude-status"},
                }, f)
            # Backup with different statusLine
            with open(backup_file, "w") as f:
                json.dump({
                    "statusLine": {"type": "command", "command": "old-tool"},
                }, f)

            import claude_statusline.cli as cli_mod
            orig = cli_mod._settings_path
            cli_mod._settings_path = lambda: settings_file
            try:
                cli_mod.cmd_uninstall()
                with open(settings_file, "r") as f:
                    settings = json.load(f)
                self.assertEqual(
                    settings["statusLine"]["command"], "old-tool"
                )
            finally:
                cli_mod._settings_path = orig

    def test_uninstall_when_not_installed(self):
        """--uninstall should handle missing statusLine gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = os.path.join(tmpdir, "settings.json")
            with open(settings_file, "w") as f:
                json.dump({"otherKey": "value"}, f)

            import claude_statusline.cli as cli_mod
            orig = cli_mod._settings_path
            cli_mod._settings_path = lambda: settings_file
            try:
                cli_mod.cmd_uninstall()  # should not crash
            finally:
                cli_mod._settings_path = orig

    def test_uninstall_missing_file(self):
        """--uninstall should handle missing settings file."""
        import claude_statusline.cli as cli_mod
        orig = cli_mod._settings_path
        cli_mod._settings_path = lambda: "/nonexistent/settings.json"
        try:
            cli_mod.cmd_uninstall()  # should not crash
        finally:
            cli_mod._settings_path = orig


# ─── themes.py — focus theme ────────────────────────────────────────

class TestUninstallEdgeCases(unittest.TestCase):
    def test_uninstall_corrupt_settings(self):
        """Corrupt settings.json should not crash uninstall."""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = os.path.join(tmpdir, "settings.json")
            with open(settings_file, "w") as f:
                f.write("{not valid json")

            import claude_statusline.cli as cli_mod
            orig = cli_mod._settings_path
            cli_mod._settings_path = lambda: settings_file
            try:
                cli_mod.cmd_uninstall()  # should not crash
            finally:
                cli_mod._settings_path = orig

    def test_uninstall_backup_same_as_current(self):
        """When backup has same statusLine, should remove it."""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = os.path.join(tmpdir, "settings.json")
            backup_file = settings_file + ".bak"
            sl = {"type": "command", "command": "claude-status"}

            with open(settings_file, "w") as f:
                json.dump({"statusLine": sl}, f)
            with open(backup_file, "w") as f:
                json.dump({"statusLine": sl}, f)

            import claude_statusline.cli as cli_mod
            orig = cli_mod._settings_path
            cli_mod._settings_path = lambda: settings_file
            try:
                cli_mod.cmd_uninstall()
                with open(settings_file, "r") as f:
                    settings = json.load(f)
                self.assertNotIn("statusLine", settings)
            finally:
                cli_mod._settings_path = orig

    def test_uninstall_corrupt_backup(self):
        """Corrupt backup should not crash, should remove statusLine."""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = os.path.join(tmpdir, "settings.json")
            backup_file = settings_file + ".bak"

            with open(settings_file, "w") as f:
                json.dump({"statusLine": {"type": "command", "command": "claude-status"}}, f)
            with open(backup_file, "w") as f:
                f.write("{corrupt backup")

            import claude_statusline.cli as cli_mod
            orig = cli_mod._settings_path
            cli_mod._settings_path = lambda: settings_file
            try:
                cli_mod.cmd_uninstall()
                with open(settings_file, "r") as f:
                    settings = json.load(f)
                self.assertNotIn("statusLine", settings)
            finally:
                cli_mod._settings_path = orig


class TestFocusTheme(unittest.TestCase):
    def test_focus_theme_exists(self):
        self.assertIn("focus", THEMES)

    def test_focus_theme_single_line(self):
        """Focus theme should produce a single line."""
        data = {
            "context_window": {"used_percentage": 42,
                               "context_window_size": 200_000,
                               "current_usage": {"input_tokens": 50000}},
            "cost": {"total_cost_usd": 0.73, "total_duration_ms": 300000},
            "git_branch": "main",
        }
        result = render(data, "focus")
        lines = result.split("\n")
        self.assertEqual(len(lines), 1,
                         "Focus theme should produce 1 line, got {}".format(len(lines)))

    def test_focus_theme_has_narrow_bar(self):
        """Focus theme should use a narrower bar width."""
        self.assertEqual(THEMES["focus"].get("bar_width", 20), 12)

    def test_focus_theme_empty_line2(self):
        """Focus theme line2 should be empty."""
        self.assertEqual(THEMES["focus"]["line2"], [])

    def test_focus_theme_has_required_colors(self):
        """Focus theme should have all required color keys."""
        required = ["separator", "label", "value", "cost",
                     "branch_main", "branch_feature"]
        for key in required:
            self.assertIn(key, THEMES["focus"]["colors"],
                          "focus theme missing color: {}".format(key))


# ─── cli.py — print-config (machine-readable install state) ─────────

class TestPrintConfig(unittest.TestCase):
    """`--print-config` is the agent-facing introspection flag.

    Output contract: 7 key=value lines in a stable order. Exit code 0
    when claude-status is the configured statusLine command, 1
    otherwise. Lets coding agents detect installation state without
    parsing settings.json themselves.
    """

    def _run_with_settings(self, settings_dict_or_none, corrupt=False):
        """Helper: run cmd_print_config against a temp settings.json.

        Returns (stdout_lines_dict, exit_code). settings_dict_or_none=None
        means no file. corrupt=True writes garbage instead of JSON.
        """
        import claude_statusline.cli as cli_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = os.path.join(tmpdir, "settings.json")
            if corrupt:
                with open(settings_file, "w") as f:
                    f.write("{not valid json")
            elif settings_dict_or_none is not None:
                with open(settings_file, "w") as f:
                    json.dump(settings_dict_or_none, f)
            orig = cli_mod._settings_path
            cli_mod._settings_path = lambda: settings_file
            # Capture stdout + intercept SystemExit
            from io import StringIO
            old_stdout = sys.stdout
            sys.stdout = StringIO()
            exit_code = None
            try:
                try:
                    cli_mod.cmd_print_config()
                except SystemExit as e:
                    exit_code = e.code
                output = sys.stdout.getvalue()
            finally:
                sys.stdout = old_stdout
                cli_mod._settings_path = orig
            # Parse key=value lines
            kv = {}
            for line in output.strip().split("\n"):
                if "=" in line:
                    k, _, v = line.partition("=")
                    kv[k] = v
            return kv, exit_code

    def test_emits_all_keys_in_stable_order(self):
        """Output contract: 9 keys, always in this exact order
        (`subagent` APPENDED in v0.13.0 — appending keeps pre-existing
        8-line parsers working; inserting or reordering would not).

        Agents and shell scripts parse this — silent reordering or
        removing keys would break every downstream consumer.
        """
        import claude_statusline.cli as cli_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = os.path.join(tmpdir, "settings.json")
            with open(settings_file, "w") as f:
                json.dump({"statusLine": {"type": "command",
                                          "command": "claude-status"}}, f)
            orig = cli_mod._settings_path
            cli_mod._settings_path = lambda: settings_file
            from io import StringIO
            old_stdout = sys.stdout
            sys.stdout = StringIO()
            try:
                try:
                    cli_mod.cmd_print_config()
                except SystemExit:
                    pass
                output = sys.stdout.getvalue()
            finally:
                sys.stdout = old_stdout
                cli_mod._settings_path = orig
        keys_in_order = [line.split("=", 1)[0]
                         for line in output.strip().split("\n")]
        self.assertEqual(
            keys_in_order,
            ["installed", "command", "type", "refreshInterval",
             "theme", "version", "settings_path", "settings_state",
             "subagent"],
            "key order or set changed — agents parsing this output will break"
        )

    def test_no_settings_file(self):
        """No settings file → installed=false, exit 1, all values empty."""
        kv, code = self._run_with_settings(None)
        self.assertEqual(kv["installed"], "false")
        self.assertEqual(kv["command"], "")
        self.assertEqual(kv["type"], "")
        self.assertEqual(kv["refreshInterval"], "")
        self.assertEqual(kv["theme"], "")
        self.assertEqual(code, 1)

    def test_settings_without_statusline(self):
        """Settings exists but no statusLine → installed=false, exit 1."""
        kv, code = self._run_with_settings({"otherKey": "value"})
        self.assertEqual(kv["installed"], "false")
        self.assertEqual(code, 1)

    def test_statusline_pointing_at_other_tool(self):
        """statusLine pointing at non-claude-status tool → installed=false."""
        kv, code = self._run_with_settings({
            "statusLine": {"type": "command", "command": "starship prompt"}
        })
        self.assertEqual(kv["installed"], "false")
        # Command field still reports what's there for diagnosis.
        self.assertEqual(kv["command"], "starship prompt")
        self.assertEqual(code, 1)

    def test_default_install(self):
        """statusLine command 'claude-status' → installed=true, theme=default, exit 0."""
        kv, code = self._run_with_settings({
            "statusLine": {"type": "command", "command": "claude-status"}
        })
        self.assertEqual(kv["installed"], "true")
        self.assertEqual(kv["command"], "claude-status")
        self.assertEqual(kv["type"], "command")
        self.assertEqual(kv["theme"], "default")
        self.assertEqual(code, 0)

    def test_install_with_theme(self):
        """--theme NAME in command is parsed back out into the theme key."""
        kv, code = self._run_with_settings({
            "statusLine": {"type": "command",
                           "command": "claude-status --theme nord"}
        })
        self.assertEqual(kv["installed"], "true")
        self.assertEqual(kv["theme"], "nord")
        self.assertEqual(code, 0)

    def test_install_with_refresh_interval(self):
        """refreshInterval is preserved (numeric → string of int)."""
        kv, code = self._run_with_settings({
            "statusLine": {"type": "command",
                           "command": "claude-status",
                           "refreshInterval": 10}
        })
        self.assertEqual(kv["installed"], "true")
        self.assertEqual(kv["refreshInterval"], "10")

    def test_corrupt_settings_does_not_crash(self):
        """Corrupt settings.json → installed=false, exit 2, no traceback.

        Exit code 2 (not 1) is intentional: it signals 'do not auto-act'
        to coding agents so they don't overwrite recoverable user
        config. See TestPrintConfigEdgeCases.test_settings_state_unreadable_when_corrupt
        for the full contract.
        """
        kv, code = self._run_with_settings(None, corrupt=True)
        self.assertEqual(kv["installed"], "false")
        self.assertEqual(code, 2)

    def test_version_field_matches_module(self):
        """version field is always the running module __version__."""
        from claude_statusline import __version__
        kv, _ = self._run_with_settings(None)
        self.assertEqual(kv["version"], __version__)

    def test_path_to_full_claude_status_binary(self):
        """When settings.json points to an absolute path ending in
        claude-status (e.g. /usr/local/bin/claude-status), still
        installed=true.
        """
        kv, code = self._run_with_settings({
            "statusLine": {"type": "command",
                           "command": "/usr/local/bin/claude-status --theme focus"}
        })
        self.assertEqual(kv["installed"], "true")
        self.assertEqual(kv["theme"], "focus")
        self.assertEqual(code, 0)

    def test_subprocess_invocation_returns_correct_exit_code(self):
        """End-to-end: invoke `python -m claude_statusline --print-config`
        as a subprocess. Exit code must propagate so shell scripts can
        rely on it (`if claude-status --print-config >/dev/null; then …`).
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            home = tmpdir
            os.makedirs(os.path.join(home, ".claude"))
            with open(os.path.join(home, ".claude", "settings.json"), "w") as f:
                json.dump({"statusLine": {"type": "command",
                                          "command": "claude-status"}}, f)
            env = os.environ.copy()
            env["HOME"] = home
            env["USERPROFILE"] = home  # Windows uses USERPROFILE for home
            # On Windows, expanduser also consults HOMEDRIVE+HOMEPATH; clear
            # them or the host's real home wins and the test goes flaky.
            env.pop("HOMEDRIVE", None)
            env.pop("HOMEPATH", None)
            # This test controls the settings location via HOME, so it must
            # drop the module-level CLAUDE_STATUSLINE_SETTINGS_PATH redirect
            # (#96) — the override intentionally wins over expanduser("~"),
            # which would otherwise point the subprocess at the empty temp
            # redirect file instead of the settings.json we just wrote here.
            env.pop("CLAUDE_STATUSLINE_SETTINGS_PATH", None)
            r = subprocess.run(
                [sys.executable, "-m", "claude_statusline", "--print-config"],
                env=env, capture_output=True, text=True, timeout=15,
            )
            self.assertEqual(r.returncode, 0,
                "expected exit 0 for installed state; got {}\nSTDOUT: {}\nSTDERR: {}".format(
                    r.returncode, r.stdout, r.stderr))
            self.assertIn("installed=true", r.stdout)


class TestPrintConfigEdgeCases(unittest.TestCase):
    """Defensive tests for --print-config — every case here corresponds
    to a silent-failure mode flagged in the v0.5.5 PR review.

    Reuses the same helpers as TestPrintConfig but with adversarial
    inputs (non-dict statusLine, Windows .exe paths, --theme= form,
    newline injection, corrupt settings, etc.). Each test pins the
    behavior so a future refactor cannot regress silently.
    """

    def _run_with_settings(self, settings_dict_or_none, corrupt=False):
        import claude_statusline.cli as cli_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = os.path.join(tmpdir, "settings.json")
            if corrupt:
                with open(settings_file, "w") as f:
                    f.write("{not valid json")
            elif settings_dict_or_none is not None:
                with open(settings_file, "w") as f:
                    json.dump(settings_dict_or_none, f)
            orig = cli_mod._settings_path
            cli_mod._settings_path = lambda: settings_file
            from io import StringIO
            old_stdout = sys.stdout
            old_stderr = sys.stderr
            sys.stdout = StringIO()
            sys.stderr = StringIO()
            exit_code = None
            try:
                try:
                    cli_mod.cmd_print_config()
                except SystemExit as e:
                    exit_code = e.code
                stdout_text = sys.stdout.getvalue()
                stderr_text = sys.stderr.getvalue()
            finally:
                sys.stdout = old_stdout
                sys.stderr = old_stderr
                cli_mod._settings_path = orig
            kv = {}
            for line in stdout_text.strip().split("\n"):
                if "=" in line:
                    k, _, v = line.partition("=")
                    kv[k] = v
            return kv, exit_code, stdout_text, stderr_text

    # ── settings.json shape edge cases ──────────────────────────────

    def test_statusline_is_string_not_dict(self):
        """Some users naively write `"statusLine": "claude-status"`.
        Must not crash; reports installed=false; isinstance(sl, dict)
        guard is the only thing protecting us."""
        kv, code, _, _ = self._run_with_settings({"statusLine": "claude-status"})
        self.assertEqual(kv["installed"], "false")
        self.assertEqual(code, 1)

    def test_statusline_is_list_not_dict(self):
        kv, code, _, _ = self._run_with_settings({"statusLine": ["claude-status"]})
        self.assertEqual(kv["installed"], "false")
        self.assertEqual(code, 1)

    def test_statusline_is_none(self):
        """`"statusLine": null` (explicit clear) reports installed=false."""
        kv, code, _, _ = self._run_with_settings({"statusLine": None})
        self.assertEqual(kv["installed"], "false")
        self.assertEqual(code, 1)

    def test_settings_file_is_json_array_not_object(self):
        """Whole settings.json is a list — isinstance(settings, dict)
        guard prevents AttributeError."""
        kv, code, _, _ = self._run_with_settings(["not", "an", "object"])
        self.assertEqual(kv["installed"], "false")
        self.assertEqual(code, 1)

    # ── install detection — Windows + module forms ──────────────────

    def test_windows_exe_suffix(self):
        """Pip on Windows typically writes claude-status.exe."""
        kv, code, _, _ = self._run_with_settings({
            "statusLine": {"type": "command", "command": "claude-status.exe"}
        })
        self.assertEqual(kv["installed"], "true")
        self.assertEqual(code, 0)

    def test_windows_full_path_with_spaces(self):
        """Quoted Windows path with a space in `Program Files`. shlex
        is required — plain str.split() would mangle this into multiple
        tokens and fail detection."""
        # JSON serializes backslashes as \\, settings.json stores them
        # as single backslashes after parse. Use forward slashes here
        # for cross-platform consistency since either works.
        kv, code, _, _ = self._run_with_settings({
            "statusLine": {"type": "command",
                           "command": '"C:/Program Files/Scripts/claude-status.exe" --theme focus'}
        })
        self.assertEqual(kv["installed"], "true")
        self.assertEqual(kv["theme"], "focus")
        self.assertEqual(code, 0)

    def test_python_dash_m_form(self):
        """`python -m claude_statusline` is the documented fallback in
        the README when the binary isn't on PATH."""
        for python_name in ("python", "python3", "py"):
            kv, code, _, _ = self._run_with_settings({
                "statusLine": {"type": "command",
                               "command": "{} -m claude_statusline".format(python_name)}
            })
            self.assertEqual(kv["installed"], "true",
                "python form '{} -m claude_statusline' should detect as installed".format(python_name))
            self.assertEqual(code, 0)

    def test_uvx_form(self):
        """`uvx claude-status` is a common modern install pattern."""
        kv, code, _, _ = self._run_with_settings({
            "statusLine": {"type": "command", "command": "uvx claude-status --theme nord"}
        })
        self.assertEqual(kv["installed"], "true")
        self.assertEqual(kv["theme"], "nord")
        self.assertEqual(code, 0)

    def test_pipx_run_form(self):
        kv, code, _, _ = self._run_with_settings({
            "statusLine": {"type": "command", "command": "pipx run claude-status"}
        })
        self.assertEqual(kv["installed"], "true")

    def test_lookalike_binary_does_not_match(self):
        """`not-claude-status` is a different program — must NOT match."""
        for fake in ("not-claude-status", "my-claude-status",
                     "fork-of-claude-status", "evil-claude-status"):
            kv, code, _, _ = self._run_with_settings({
                "statusLine": {"type": "command", "command": fake}
            })
            self.assertEqual(kv["installed"], "false",
                "lookalike '{}' must not match claude-status detection".format(fake))
            self.assertEqual(code, 1)

    # ── theme parsing — both arg forms ──────────────────────────────

    def test_theme_equals_form(self):
        """argparse accepts `--theme=nord`; our parser must too."""
        kv, code, _, _ = self._run_with_settings({
            "statusLine": {"type": "command", "command": "claude-status --theme=nord"}
        })
        self.assertEqual(kv["installed"], "true")
        self.assertEqual(kv["theme"], "nord")

    # ── refreshInterval: numeric string + bool guard ────────────────

    def test_refresh_interval_numeric_string(self):
        """Hand-edited settings.json often has refreshInterval as a
        string ('1000'). Coerce via _safe_num."""
        kv, _, _, _ = self._run_with_settings({
            "statusLine": {"type": "command", "command": "claude-status",
                           "refreshInterval": "1000"}
        })
        self.assertEqual(kv["refreshInterval"], "1000")

    def test_refresh_interval_bool_rejected(self):
        """`bool` is an int subclass in Python — the explicit isinstance
        check rejects True/False to avoid emitting refreshInterval=1.
        Pinning this prevents a refactor that drops the guard."""
        kv, _, _, _ = self._run_with_settings({
            "statusLine": {"type": "command", "command": "claude-status",
                           "refreshInterval": True}
        })
        self.assertEqual(kv["refreshInterval"], "")

    def test_refresh_interval_negative_rejected(self):
        kv, _, _, _ = self._run_with_settings({
            "statusLine": {"type": "command", "command": "claude-status",
                           "refreshInterval": -100}
        })
        self.assertEqual(kv["refreshInterval"], "")

    def test_refresh_interval_garbage_string_rejected(self):
        kv, _, _, _ = self._run_with_settings({
            "statusLine": {"type": "command", "command": "claude-status",
                           "refreshInterval": "fast"}
        })
        self.assertEqual(kv["refreshInterval"], "")

    # ── line-count contract: newline injection ──────────────────────

    def test_newline_in_command_does_not_break_line_count(self):
        """A command containing \\n would inject a fake key=value line
        into the output, breaking every parser that relies on the
        documented fixed-line contract (9 lines since v0.13.0 added
        the subagent field). Sanitization must convert it to a
        single space."""
        kv, code, stdout_text, _ = self._run_with_settings({
            "statusLine": {"type": "command",
                           "command": "claude-status\nPWNED=evil"}
        })
        # Exactly 9 lines, regardless of injected content.
        self.assertEqual(len(stdout_text.strip().split("\n")), 9,
            "newline in command field broke the 9-line contract")
        # PWNED should NOT appear as a key — it should be folded into
        # the command value (with the newline replaced by space).
        self.assertNotIn("PWNED", kv,
            "newline injection added a fake key to the parsed output")
        self.assertIn("PWNED=evil", kv["command"],
            "the injected text should still be visible as part of command for diagnosis")

    # ── settings_state + exit code 2 ────────────────────────────────

    def test_settings_state_ok_when_normal(self):
        kv, _, _, _ = self._run_with_settings({"statusLine": {"type": "command",
                                                              "command": "claude-status"}})
        self.assertEqual(kv["settings_state"], "ok")

    def test_settings_state_missing_when_no_file(self):
        kv, code, _, _ = self._run_with_settings(None)
        self.assertEqual(kv["settings_state"], "missing")
        self.assertEqual(code, 1)

    def test_settings_state_unreadable_when_corrupt(self):
        """Corrupt settings.json must NOT collapse to installed=false
        with exit 1 — that would let an agent auto-install over
        recoverable user config. settings_state=unreadable + exit 2
        signals 'do not auto-act, surface to user'."""
        kv, code, _, stderr_text = self._run_with_settings(None, corrupt=True)
        self.assertEqual(kv["settings_state"], "unreadable")
        self.assertEqual(code, 2,
            "corrupt settings must exit 2 so agents do not overwrite recoverable config")
        # Diagnostic on stderr — agent's logs need to know why.
        self.assertIn("settings.json", stderr_text)
        # 9 lines on stdout still — contract preserved even on error.
        self.assertEqual(kv["installed"], "false")

    # ── Gemini review fixes: versioned python, last-theme-wins, nulls

    def test_versioned_python_binaries_detected(self):
        """python3.11, python3.12.5, python3, py — all valid python
        binary names in multi-version environments (pyenv, deadsnakes,
        Homebrew). All must detect as installed when followed by
        `-m claude_statusline`."""
        for binary in ("python", "python3", "python3.11", "python3.12.5", "py"):
            kv, code, _, _ = self._run_with_settings({
                "statusLine": {"type": "command",
                               "command": "{} -m claude_statusline".format(binary)}
            })
            self.assertEqual(kv["installed"], "true",
                "binary '{}' should detect as a valid python launcher".format(binary))

    def test_python_lookalike_binaries_rejected(self):
        """The regex must reject names that share the python prefix
        but are different programs entirely. Tightens against the
        broader `startswith('python')` heuristic."""
        for fake in ("pythonista", "python-fork", "python_legacy",
                     "pythonw", "ipython"):
            kv, code, _, _ = self._run_with_settings({
                "statusLine": {"type": "command",
                               "command": "{} -m claude_statusline".format(fake)}
            })
            self.assertEqual(kv["installed"], "false",
                "lookalike '{}' must not match python detection".format(fake))

    def test_theme_last_occurrence_wins(self):
        """When --theme appears multiple times, the LAST one wins —
        matches argparse semantics, which is what the running command
        actually does. Reporting the first would lie to the agent
        about the user's real configured theme."""
        kv, _, _, _ = self._run_with_settings({
            "statusLine": {"type": "command",
                           "command": "claude-status --theme nord --theme focus"}
        })
        self.assertEqual(kv["theme"], "focus",
            "last --theme should win to match argparse precedence")

    def test_theme_last_wins_across_arg_forms(self):
        """Last-wins must work across both `--theme NAME` and
        `--theme=NAME` forms mixed in the same command."""
        kv, _, _, _ = self._run_with_settings({
            "statusLine": {"type": "command",
                           "command": "claude-status --theme=nord --theme focus"}
        })
        self.assertEqual(kv["theme"], "focus")

        kv, _, _, _ = self._run_with_settings({
            "statusLine": {"type": "command",
                           "command": "claude-status --theme nord --theme=focus"}
        })
        self.assertEqual(kv["theme"], "focus")

    def test_null_command_emits_empty_string_not_None(self):
        """A literal `null` in settings.json must NOT be stringified
        to 'None' — that would break parsers expecting empty string
        for absent values per the documented contract."""
        kv, code, _, _ = self._run_with_settings({
            "statusLine": {"type": "command", "command": None}
        })
        self.assertEqual(kv["command"], "",
            "null command should emit empty string, not 'None'")
        # And of course not detected as installed.
        self.assertEqual(kv["installed"], "false")

    def test_null_type_emits_empty_string_not_None(self):
        kv, _, _, _ = self._run_with_settings({
            "statusLine": {"type": None, "command": "claude-status"}
        })
        self.assertEqual(kv["type"], "",
            "null type should emit empty string, not 'None'")

    # ── version field tracks the running module ─────────────────────

    def test_version_field_is_module_version(self):
        """`version=` always reflects the running module __version__,
        not a hardcoded literal that would rot on every release."""
        from claude_statusline import __version__
        kv, _, _, _ = self._run_with_settings({"statusLine": {"type": "command",
                                                              "command": "claude-status"}})
        self.assertEqual(kv["version"], __version__)


# ─── cli.py — setup wizard ──────────────────────────────────────────

class TestSetupWizardUpdated(unittest.TestCase):
    def test_setup_flag_accepted(self):
        """--setup should be recognized."""
        result = subprocess.run(
            [sys.executable, "-m", "claude_statusline", "--setup"],
            capture_output=True, timeout=15,
            input="1\n\n",
            encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("setup wizard", result.stdout)
        # Should show compact theme list, not full renders
        self.assertIn("full detail", result.stdout)
        self.assertIn("focus", result.stdout)

    def test_setup_success_shows_star_ask(self):
        """The star-ask epilogue (#114) prints once on the wizard's
        success path. Input completes all prompts (theme 1, budget
        skip, subagent skip via EOF-safe default)."""
        result = subprocess.run(
            [sys.executable, "-m", "claude_statusline", "--setup"],
            capture_output=True, timeout=15,
            input="1\n\nn\n",
            encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Setup complete!", result.stdout)
        self.assertEqual(
            result.stdout.count("github.com/mkalkere/claude-statusline"), 1,
            "star-ask must appear exactly once on success")
        self.assertIn("a GitHub star helps", result.stdout)

    def test_setup_abort_no_star_ask(self):
        """Aborted setup (EOF at the first prompt) must NOT print the
        star-ask — it's a success-path epilogue, not a nag."""
        result = subprocess.run(
            [sys.executable, "-m", "claude_statusline", "--setup"],
            capture_output=True, timeout=15,
            input="",
            encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        # Positive control: the abort path actually ran (a startup
        # crash would produce empty stdout and pass the NotIn
        # assertion vacuously — test-analyzer finding).
        self.assertEqual(result.returncode, 0)
        self.assertIn("Setup cancelled.", result.stdout)
        self.assertNotIn("a GitHub star helps", result.stdout)

    def test_install_has_no_star_ask(self):
        """--install is the agents/CI path — no human reads it, so no
        star-ask there (design decision in #114)."""
        result = subprocess.run(
            [sys.executable, "-m", "claude_statusline", "--install"],
            capture_output=True, timeout=15,
            encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        # Positive control (same vacuity guard as the abort test).
        self.assertEqual(result.returncode, 0)
        self.assertIn("Installed claude-status into", result.stdout)
        self.assertNotIn("a GitHub star helps", result.stdout)

    def test_uninstall_flag_accepted(self):
        """--uninstall should be recognized."""
        result = subprocess.run(
            [sys.executable, "-m", "claude_statusline", "--uninstall"],
            capture_output=True, timeout=15,
            encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        self.assertEqual(result.returncode, 0)

    def test_demo_has_repo_footer(self):
        """#116: the repo-link footer closes --demo output. Positive
        control included so a demo crash can't pass vacuously."""
        result = subprocess.run(
            [sys.executable, "-m", "claude_statusline", "--demo"],
            capture_output=True, timeout=15,
            encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("theme demos", result.stdout)
        last_line = result.stdout.strip().split("\n")[-1]
        self.assertIn("github.com/mkalkere/claude-statusline", last_line)
        self.assertIn("a star helps", last_line)

    def test_demo_shows_all_themes(self):
        """Demo should show all 8 themes including focus."""
        result = subprocess.run(
            [sys.executable, "-m", "claude_statusline", "--demo"],
            capture_output=True, timeout=15,
            encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        self.assertEqual(result.returncode, 0)
        for name in ("default", "minimal", "powerline", "nord",
                     "tokyo-night", "gruvbox", "rose-pine", "focus"):
            self.assertIn("{}:".format(name), result.stdout,
                          "Demo missing theme: {}".format(name))


# ─── formatters.py — speed ───────────────────────────────────────────

class TestFmtSpeed(unittest.TestCase):
    def test_normal_speed(self):
        from claude_statusline.formatters import fmt_speed
        result = fmt_speed(10000, 10000)  # 10K tokens in 10s = 1K/s
        self.assertIn("/s", result)
        self.assertIn("1K", result)

    def test_zero_duration(self):
        from claude_statusline.formatters import fmt_speed
        self.assertEqual(fmt_speed(1000, 0), "")

    def test_none_tokens(self):
        from claude_statusline.formatters import fmt_speed
        self.assertEqual(fmt_speed(None, 1000), "")

    def test_none_duration(self):
        from claude_statusline.formatters import fmt_speed
        self.assertEqual(fmt_speed(1000, None), "")


# ─── cli.py — speed section ─────────────────────────────────────────

class TestSpeedSection(unittest.TestCase):
    def test_speed_displayed(self):
        data = {
            "context_window": {"used_percentage": 30,
                               "current_usage": {"input_tokens": 50000,
                                                 "output_tokens": 5000}},
            "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000,
                     "total_api_duration_ms": 10000},
            "git_branch": "main",
        }
        result = render(data)
        self.assertIn("speed:", result)
        self.assertIn("/s", result)

    def test_speed_hidden_no_api_duration(self):
        data = {
            "context_window": {"used_percentage": 30,
                               "current_usage": {"input_tokens": 5000}},
            "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
            "git_branch": "main",
        }
        result = render(data)
        self.assertNotIn("speed:", result)


# ─── colors.py — NO_COLOR support ───────────────────────────────────

class TestNoColor(unittest.TestCase):
    def test_colorize_respects_no_color(self):
        from claude_statusline import colors
        orig = colors._NO_COLOR
        colors._NO_COLOR = True
        try:
            result = colors.colorize("hello", colors.GREEN)
            self.assertEqual(result, "hello")
            self.assertNotIn("\033", result)
        finally:
            colors._NO_COLOR = orig

    def test_colorize_normal_with_color(self):
        from claude_statusline import colors
        orig = colors._NO_COLOR
        colors._NO_COLOR = False
        try:
            result = colors.colorize("hello", colors.GREEN)
            self.assertIn("\033", result)
            self.assertIn("hello", result)
        finally:
            colors._NO_COLOR = orig


# ─── git.py — git state and commit age ──────────────────────────────

class TestGitState(unittest.TestCase):
    def test_returns_string(self):
        from claude_statusline.git import get_git_state
        result = get_git_state()
        self.assertIsInstance(result, str)

    def test_clean_repo_empty(self):
        """Clean repo should return empty string."""
        from claude_statusline.git import get_git_state
        result = get_git_state()
        # We're in a clean repo, should be empty
        self.assertEqual(result, "")


class TestLastCommitAge(unittest.TestCase):
    def test_returns_int_or_none(self):
        from claude_statusline.git import get_last_commit_age_ms
        result = get_last_commit_age_ms()
        # In a git repo, should return an int
        if result is not None:
            self.assertIsInstance(result, int)
            self.assertGreaterEqual(result, 0)


class TestRemoteUrl(unittest.TestCase):
    def test_returns_string(self):
        from claude_statusline.git import get_remote_url
        result = get_remote_url()
        self.assertIsInstance(result, str)


# ─── cli.py — git state section ─────────────────────────────────────

class TestGitStateSection(unittest.TestCase):
    def test_git_state_hidden_when_clean(self):
        import claude_statusline.cli as cli_mod
        orig = cli_mod.get_git_state
        cli_mod.get_git_state = lambda: ""
        try:
            data = {
                "context_window": {"used_percentage": 30,
                                   "current_usage": {"input_tokens": 5000}},
                "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
                "git_branch": "main",
            }
            result = render(data)
            self.assertNotIn("merge", result)
            self.assertNotIn("rebase", result)
            self.assertNotIn("conflict", result)
        finally:
            cli_mod.get_git_state = orig

    def test_git_state_merge(self):
        import claude_statusline.cli as cli_mod
        orig = cli_mod.get_git_state
        cli_mod.get_git_state = lambda: "merge"
        try:
            data = {
                "context_window": {"used_percentage": 30,
                                   "current_usage": {"input_tokens": 5000}},
                "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
                "git_branch": "main",
            }
            result = render(data)
            self.assertIn("merge", result)
        finally:
            cli_mod.get_git_state = orig

    def test_git_state_conflict(self):
        import claude_statusline.cli as cli_mod
        orig = cli_mod.get_git_state
        cli_mod.get_git_state = lambda: "conflict"
        try:
            data = {
                "context_window": {"used_percentage": 30,
                                   "current_usage": {"input_tokens": 5000}},
                "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
                "git_branch": "main",
            }
            result = render(data)
            self.assertIn("conflict", result)
        finally:
            cli_mod.get_git_state = orig


# ─── cli.py — commit age section ────────────────────────────────────

class TestCommitAgeSection(unittest.TestCase):
    def test_commit_age_displayed(self):
        import claude_statusline.cli as cli_mod
        orig = cli_mod.get_last_commit_age_ms
        cli_mod.get_last_commit_age_ms = lambda: 300000  # 5 minutes
        try:
            data = {
                "context_window": {"used_percentage": 30,
                                   "current_usage": {"input_tokens": 5000}},
                "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
                "git_branch": "main",
            }
            result = render(data)
            self.assertIn("last:", result)
        finally:
            cli_mod.get_last_commit_age_ms = orig

    def test_commit_age_hidden_when_none(self):
        import claude_statusline.cli as cli_mod
        orig = cli_mod.get_last_commit_age_ms
        cli_mod.get_last_commit_age_ms = lambda: None
        try:
            data = {
                "context_window": {"used_percentage": 30,
                                   "current_usage": {"input_tokens": 5000}},
                "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
                "git_branch": "main",
            }
            result = render(data)
            self.assertNotIn("last:", result)
        finally:
            cli_mod.get_last_commit_age_ms = orig


# ─── cli.py — OSC 8 links ───────────────────────────────────────────

class TestOSC8Links(unittest.TestCase):
    def test_osc8_disabled_by_default(self):
        """OSC 8 must be OFF by default to avoid breaking Claude Code's
        Ink TUI renderer (#68)."""
        import claude_statusline.cli as cli_mod
        orig = cli_mod.get_clickable_links_enabled
        cli_mod.get_clickable_links_enabled = lambda: False
        try:
            result = cli_mod._osc8_link("https://github.com/test", "branch")
            self.assertEqual(result, "branch")
            self.assertNotIn("\033]8", result)
        finally:
            cli_mod.get_clickable_links_enabled = orig

    def test_osc8_enabled_via_opt_in(self):
        """When user opts in, OSC 8 sequences are emitted."""
        import claude_statusline.cli as cli_mod
        orig = cli_mod.get_clickable_links_enabled
        cli_mod.get_clickable_links_enabled = lambda: True
        try:
            result = cli_mod._osc8_link("https://github.com/test", "branch")
            self.assertIn("branch", result)
            self.assertIn("\033]8;;", result)
            self.assertIn("https://github.com/test", result)
        finally:
            cli_mod.get_clickable_links_enabled = orig

    def test_osc8_link_no_url(self):
        from claude_statusline.cli import _osc8_link
        result = _osc8_link("", "branch")
        self.assertEqual(result, "branch")

    def test_osc8_link_none_url(self):
        from claude_statusline.cli import _osc8_link
        result = _osc8_link(None, "branch")
        self.assertEqual(result, "branch")

    def test_opt_in_does_not_override_no_color(self):
        """NO_COLOR must win over clickable_links=true."""
        from claude_statusline import colors as _cm
        import claude_statusline.cli as cli_mod
        orig_nc = _cm._NO_COLOR
        orig_cl = cli_mod.get_clickable_links_enabled
        _cm._NO_COLOR = True
        cli_mod.get_clickable_links_enabled = lambda: True
        try:
            result = cli_mod._osc8_link("https://github.com/test", "branch")
            self.assertEqual(result, "branch")
            self.assertNotIn("\033", result)
        finally:
            _cm._NO_COLOR = orig_nc
            cli_mod.get_clickable_links_enabled = orig_cl


# ─── sessions.py — clickable_links config parsing (#68 regression guard) ──

class TestClickableLinksConfigParsing(unittest.TestCase):
    """Exercise the real _read_status_config() path for `clickable_links`.

    These tests hit the JSON parser directly rather than mocking
    `get_clickable_links_enabled`, so a regression in parsing logic
    (e.g., swapping `bool(...)` for `is True`, or losing the default)
    would silently re-enable OSC 8 and reintroduce #68. This is the
    strongest guard against the bug coming back.
    """

    def _with_config(self, config_value, assertion):
        """Helper: write config JSON, point _CLAUDE_DIR at it, run assertion."""
        from claude_statusline.sessions import (
            _cache_path,
            get_clickable_links_enabled,
        )
        import claude_statusline.sessions as sessions_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = os.path.join(tmpdir, "claude-status-budget.json")
            if config_value is not None:
                with open(config_file, "w") as f:
                    if config_value == "__CORRUPT__":
                        f.write("{not valid json,,")
                    else:
                        json.dump(config_value, f)

            orig = sessions_mod._CLAUDE_DIR
            sessions_mod._CLAUDE_DIR = tmpdir
            try:
                os.unlink(_cache_path("status_config"))
            except OSError:
                pass
            try:
                result = get_clickable_links_enabled()
                assertion(result)
            finally:
                sessions_mod._CLAUDE_DIR = orig
                try:
                    os.unlink(_cache_path("status_config"))
                except OSError:
                    pass

    def test_default_is_false_when_config_missing(self):
        """Missing config file → False (default)."""
        self._with_config(None, lambda r: self.assertFalse(r))

    def test_default_is_false_when_key_absent(self):
        """Config present but `clickable_links` key missing → False."""
        self._with_config(
            {"daily_budget_usd": 10.0},
            lambda r: self.assertFalse(r),
        )

    def test_true_when_explicitly_enabled(self):
        """`clickable_links: true` → True."""
        self._with_config(
            {"clickable_links": True},
            lambda r: self.assertTrue(r),
        )

    def test_false_when_explicitly_disabled(self):
        """`clickable_links: false` → False."""
        self._with_config(
            {"clickable_links": False},
            lambda r: self.assertFalse(r),
        )

    def test_null_value_is_false(self):
        """`clickable_links: null` → False."""
        self._with_config(
            {"clickable_links": None},
            lambda r: self.assertFalse(r),
        )

    def test_corrupt_config_is_false(self):
        """Corrupted JSON → False (graceful degradation)."""
        self._with_config(
            "__CORRUPT__",
            lambda r: self.assertFalse(r),
        )

    def test_non_dict_top_level_is_false(self):
        """Top-level JSON list (not a dict) → False (no AttributeError)."""
        # data.get(...) would raise AttributeError on a list.
        # _read_status_config must catch it and fall through to defaults.
        self._with_config(
            [1, 2, 3],
            lambda r: self.assertFalse(r),
        )

    def test_null_top_level_is_false(self):
        """Top-level JSON null → False (no AttributeError)."""
        self._with_config(
            None,  # this is "write nothing", but we want literal JSON null
            lambda r: self.assertFalse(r),
        )
        # The helper skips file creation on None; this still passes via
        # the missing-file path. Add an explicit literal-null case below
        # that writes a file containing the JSON token `null`.

    def test_literal_null_in_file_is_false(self):
        """File contains literal JSON `null` → False (no AttributeError)."""
        from claude_statusline.sessions import (
            _cache_path,
            get_clickable_links_enabled,
        )
        import claude_statusline.sessions as sessions_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = os.path.join(tmpdir, "claude-status-budget.json")
            with open(config_file, "w") as f:
                f.write("null")

            orig = sessions_mod._CLAUDE_DIR
            sessions_mod._CLAUDE_DIR = tmpdir
            try:
                os.unlink(_cache_path("status_config"))
            except OSError:
                pass
            try:
                result = get_clickable_links_enabled()
                self.assertFalse(result)
            finally:
                sessions_mod._CLAUDE_DIR = orig
                try:
                    os.unlink(_cache_path("status_config"))
                except OSError:
                    pass


# ─── cli.py — Line 2 has no OSC 8 by default (end-to-end #68 guard) ──

class TestLine2NoOSC8ByDefault(unittest.TestCase):
    """End-to-end guard: the rendered output must contain no OSC 8
    escape sequences when `clickable_links` is at its default (off).
    This is the actual regression that #68 fixes — a future change
    that reintroduces OSC 8 at any call site would be caught here.
    """

    def test_no_osc8_in_rendered_output_by_default(self):
        import claude_statusline.cli as cli_mod
        orig_clickable = cli_mod.get_clickable_links_enabled
        orig_remote = cli_mod.get_remote_url
        cli_mod.get_clickable_links_enabled = lambda: False
        cli_mod.get_remote_url = lambda: "https://github.com/example/repo"
        try:
            data = {
                "context_window": {
                    "used_percentage": 30,
                    "current_usage": {"input_tokens": 5000},
                },
                "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
                "git_branch": "main",
            }
            result = render(data)
            # OSC 8 sequences start with ESC ] 8
            self.assertNotIn("\033]8", result)
        finally:
            cli_mod.get_clickable_links_enabled = orig_clickable
            cli_mod.get_remote_url = orig_remote


# ─── cli.py — Line 2 width fits at 120-col terminals (#70 guard) ──

class TestLine2FitsAt120Cols(unittest.TestCase):
    """End-to-end regression guard for #70.

    With heavy session data (rate limits, multi-hour duration, +5K lines,
    session name, CC version, etc.), Line 2 must fit within a 120-column
    terminal. The fix raises the full-layout threshold so that 120 cols
    falls into the compact range, where the heaviest sections are dropped.

    A future change that adds new line2 sections to the full layout
    without also adding them to _COMPACT_DROP would cause this test to
    fail, catching the regression immediately.
    """

    def setUp(self):
        # Stub git helpers at the cli_mod level so tests don't depend on
        # ambient repo state (which would make width measurements
        # non-deterministic across hosts).
        import claude_statusline.cli as cli_mod
        self._cli_mod = cli_mod
        self._orig = {
            "get_remote_url": cli_mod.get_remote_url,
            "get_git_state": cli_mod.get_git_state,
            "get_last_commit_age_ms": cli_mod.get_last_commit_age_ms,
            "get_git_extras": cli_mod.get_git_extras,
            "get_clickable_links_enabled": cli_mod.get_clickable_links_enabled,
        }
        cli_mod.get_remote_url = lambda: "https://github.com/example/repo"
        cli_mod.get_git_state = lambda: ""
        cli_mod.get_last_commit_age_ms = lambda: 300000  # 5m
        cli_mod.get_git_extras = lambda: {"stash": 2, "ahead": 2, "behind": 1}
        cli_mod.get_clickable_links_enabled = lambda: False

    def tearDown(self):
        for name, fn in self._orig.items():
            setattr(self._cli_mod, name, fn)

    def _heavy_payload(self):
        return {
            "context_window": {
                "used_percentage": 5,
                "context_window_size": 1_000_000,
                "current_usage": {
                    "input_tokens": 6,
                    "output_tokens": 301,
                },
            },
            "cost": {
                "total_cost_usd": 250,
                "total_duration_ms": 60_223_000,       # 16h43m
                "total_api_duration_ms": 11_100_000,   # 3h05m
                "total_lines_added": 5245,
                "total_lines_removed": 510,
            },
            "rate_limits": {
                "five_hour": {"used_percentage": 46, "resets_at": 1_776_000_000},
                "seven_day": {"used_percentage": 68, "resets_at": 1_776_500_000},
            },
            # Realistic project path + branch so the project_name/branch
            # section reflects real-world width (Gemini flagged missing
            # workspace on #71). "myapp/feat/responsive-statusline" is
            # representative of a typical feature branch string.
            "workspace": {
                "project_dir": "/home/user/projects/myapp",
                "current_dir": "/home/user/projects/myapp",
            },
            "cwd": "/home/user/projects/myapp",
            "git_branch": "feat/responsive-statusline",
            "session_name": "refactor auth middleware",
            "version": "2.1.101",
        }

    def _visible_width(self, line):
        # Strip SGR color escapes.
        stripped = re.sub(r"\x1b\[[0-9;]*m", "", line)
        # Also strip OSC 8 hyperlink sequences (ESC ] 8 ; ; URL ST TEXT ESC ] 8 ; ; ST)
        # so this helper stays correct even if clickable_links is ever
        # accidentally enabled in a test. ST terminator is ESC \ or BEL.
        stripped = re.sub(r"\x1b\]8;;[^\x07\x1b]*(?:\x07|\x1b\\)", "", stripped)
        return len(stripped)

    def _render_at_width(self, cols):
        # COLUMNS env var is honored by shutil.get_terminal_size().
        old_cols = os.environ.get("COLUMNS")
        os.environ["COLUMNS"] = str(cols)
        try:
            return render(self._heavy_payload())
        finally:
            if old_cols is None:
                del os.environ["COLUMNS"]
            else:
                os.environ["COLUMNS"] = old_cols

    def test_line2_fits_at_full_threshold(self):
        """At the full-layout threshold (160 cols), the full layout is
        enabled — Line 2 must fit within the terminal width. This guards
        the buffer above the measured heavy-payload width (~152 chars).
        """
        from claude_statusline.cli import _FULL_LAYOUT_MIN_COLS
        result = self._render_at_width(_FULL_LAYOUT_MIN_COLS)
        lines = result.split("\n")
        self.assertEqual(len(lines), 2, "expected 2 lines at full layout")
        line2_visible = self._visible_width(lines[1])
        self.assertLessEqual(
            line2_visible, _FULL_LAYOUT_MIN_COLS,
            "Line 2 is {} visible chars at {}-col full-layout threshold — "
            "heavy payload overflows the buffer above the measured ~152. "
            "Raise _FULL_LAYOUT_MIN_COLS or trim full-layout sections.".format(
                line2_visible, _FULL_LAYOUT_MIN_COLS
            )
        )

    def test_line2_fits_at_120_cols(self):
        """Heavy payload at 120 cols — Line 2 must not exceed 120 visible chars."""
        result = self._render_at_width(120)
        lines = result.split("\n")
        self.assertEqual(len(lines), 2, "expected 2 lines")
        line2_visible = self._visible_width(lines[1])
        self.assertLessEqual(
            line2_visible, 120,
            "Line 2 is {} visible chars at 120-col terminal — Ink will "
            "truncate it. Either move sections off Line 2's full layout "
            "or add them to _COMPACT_DROP.".format(line2_visible)
        )

    def test_line2_fits_at_100_cols(self):
        """Heavy payload at 100 cols — Line 2 must not exceed 100 visible chars."""
        result = self._render_at_width(100)
        lines = result.split("\n")
        self.assertEqual(len(lines), 2, "expected 2 lines")
        line2_visible = self._visible_width(lines[1])
        self.assertLessEqual(
            line2_visible, 100,
            "Line 2 is {} visible chars at 100-col terminal".format(
                line2_visible
            )
        )

    def test_line2_fits_at_80_cols(self):
        """Heavy payload at 80 cols (narrow layout) — every emitted line must fit.

        Narrow layout drops most sections; Line 2 may be short or empty
        but the output must always contain at least one line and every
        line's visible width must be <= 80.
        """
        result = self._render_at_width(80)
        lines = result.split("\n")
        self.assertGreaterEqual(
            len(lines), 1, "render() returned no lines at 80 cols"
        )
        for idx, line in enumerate(lines):
            visible = self._visible_width(line)
            self.assertLessEqual(
                visible, 80,
                "Line {} is {} visible chars at 80-col terminal".format(
                    idx + 1, visible
                )
            )

    def test_line2_fits_in_compact_band_with_vim_and_long_agent(self):
        """The compact band (100-149 cols) must fit even with the heaviest
        line2 sections — vim NORMAL active, long agent name, long branch.

        This is the silent-failure mode that broke v0.5.4 before
        _FIT_DROP_PRIORITY was introduced: the coarse pre-filter kept
        burn/duration/lines/branch/vim/agent/model on Line 2, none of
        which were in _COMPACT_DROP, so the precise stage was a no-op
        and Line 2 silently overflowed at 110 cols. Pinning all three
        widths (100/110/130) guarantees the precise stage covers them.
        """
        payload = self._heavy_payload()
        payload["vim"] = {"mode": "NORMAL"}
        payload["agent"] = {"name": "long-agent-name-stress-test"}
        for cols in (100, 110, 130):
            old = os.environ.get("COLUMNS")
            os.environ["COLUMNS"] = str(cols)
            try:
                result = render(payload)
            finally:
                if old is None:
                    del os.environ["COLUMNS"]
                else:
                    os.environ["COLUMNS"] = old
            for idx, line in enumerate(result.split("\n")):
                w = self._visible_width(line)
                self.assertLessEqual(
                    w, cols,
                    "Line {} is {} visible chars at {}-col terminal "
                    "(heavy + vim + long agent). _FIT_DROP_PRIORITY may "
                    "be missing a section name from line2.".format(
                        idx + 1, w, cols
                    )
                )

    def test_rate_limits_recovered_at_180_cols(self):
        """At 180 cols the precise stage should KEEP rate_limits visible
        even though it lives in _COMPACT_DROP — because at 180 cols there
        is room for it.

        This pins the recovery property: someone who reverts the precise
        stage or re-raises _FULL_LAYOUT_MIN_COLS to 230 would silently
        lose this section, and the upper-bound width tests above would
        not notice (overflow tests pass either way).
        """
        result = self._render_at_width(180)
        # Rate-limit indicators look like "5h:46%" / "7d:68%" in the
        # output (with ANSI color around them). Strip ANSI for the
        # substring check.
        plain = re.sub(r"\x1b\[[0-9;]*m", "", result)
        self.assertIn(
            "5h:", plain,
            "rate_limits section was dropped at 180 cols even though "
            "it should fit — precise stage may have over-dropped or "
            "been disabled."
        )

    def test_rate_limits_dropped_at_120_cols(self):
        """At 120 cols there is no room for rate_limits — the precise
        stage must drop it. Inverse pin to test_rate_limits_recovered:
        if the drop priority is broken or _COMPACT_DROP is bypassed,
        rate_limits would leak through and overflow Line 2.
        """
        result = self._render_at_width(120)
        plain = re.sub(r"\x1b\[[0-9;]*m", "", result)
        self.assertNotIn(
            "5h:", plain,
            "rate_limits section was kept at 120 cols — would push "
            "Line 2 past terminal width and trigger Ink truncation."
        )


# ─── sessions.py — disabled sections ────────────────────────────────

class TestDisabledSections(unittest.TestCase):
    def test_disabled_sections_filters(self):
        import claude_statusline.cli as cli_mod
        orig = cli_mod.get_disabled_sections
        cli_mod.get_disabled_sections = lambda: ["cache", "latency"]
        try:
            data = {
                "context_window": {"used_percentage": 30,
                                   "current_usage": {"input_tokens": 5000,
                                                     "cache_read_input_tokens": 3000}},
                "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000,
                         "total_api_duration_ms": 5000},
                "git_branch": "main",
            }
            result = render(data)
            self.assertNotIn("cache:", result)
            self.assertNotIn("api:", result)
        finally:
            cli_mod.get_disabled_sections = orig

    def test_no_disabled_sections(self):
        import claude_statusline.cli as cli_mod
        orig = cli_mod.get_disabled_sections
        cli_mod.get_disabled_sections = lambda: []
        try:
            data = {
                "context_window": {"used_percentage": 30,
                                   "current_usage": {"input_tokens": 5000,
                                                     "cache_read_input_tokens": 3000}},
                "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
                "git_branch": "main",
            }
            result = render(data)
            self.assertIn("cache:", result)
        finally:
            cli_mod.get_disabled_sections = orig


# ─── bar.py — bar styles ────────────────────────────────────────────

class TestBarStyles(unittest.TestCase):
    def test_default_style(self):
        from claude_statusline.bar import BAR_STYLES
        self.assertIn("default", BAR_STYLES)
        self.assertIn("filled", BAR_STYLES["default"])

    def test_all_styles_exist(self):
        from claude_statusline.bar import BAR_STYLES
        for name in ("default", "dots", "blocks", "thin"):
            self.assertIn(name, BAR_STYLES, "Missing bar style: {}".format(name))

    def test_bar_style_in_theme(self):
        """bar_style key in theme should resolve to style chars."""
        bar = render_bar(50, 20, {"bar_style": "dots"})
        self.assertIn("[", bar)
        self.assertTrue(len(bar) > 0)

    def test_explicit_chars_override_style(self):
        """Explicit bar_filled should override bar_style."""
        bar = render_bar(50, 20, {
            "bar_style": "dots",
            "bar_filled": "#",
        })
        self.assertIn("#", bar)


# ─── Additional edge case tests ─────────────────────────────────────

class TestOSC8NoColor(unittest.TestCase):
    def test_osc8_suppressed_with_no_color(self):
        """OSC 8 links should be plain text when NO_COLOR is set."""
        from claude_statusline import colors as _cm
        from claude_statusline.cli import _osc8_link
        orig = _cm._NO_COLOR
        _cm._NO_COLOR = True
        try:
            result = _osc8_link("https://example.com", "branch")
            self.assertEqual(result, "branch")
            self.assertNotIn("\033", result)
        finally:
            _cm._NO_COLOR = orig


class TestFmtSpeedNegative(unittest.TestCase):
    def test_negative_duration(self):
        from claude_statusline.formatters import fmt_speed
        self.assertEqual(fmt_speed(1000, -500), "")


class TestBarStyleUnknown(unittest.TestCase):
    def test_unknown_style_uses_default(self):
        """Unknown bar_style should fall back to default chars."""
        bar = render_bar(50, 20, {"bar_style": "nonexistent"})
        self.assertIn("[", bar)
        self.assertTrue(len(bar) > 0)


class TestGitStateRebase(unittest.TestCase):
    def test_rebase_renders(self):
        import claude_statusline.cli as cli_mod
        orig = cli_mod.get_git_state
        cli_mod.get_git_state = lambda: "rebase"
        try:
            data = {
                "context_window": {"used_percentage": 30,
                                   "current_usage": {"input_tokens": 5000}},
                "cost": {"total_cost_usd": 0.50, "total_duration_ms": 60000},
                "git_branch": "main",
            }
            result = render(data)
            self.assertIn("rebase", result)
        finally:
            cli_mod.get_git_state = orig


# ─── cli.py — _detect_terminal_width fallback chain (#79) ──────────

class TestDetectTerminalWidth(unittest.TestCase):
    """Pin the fallback order of _detect_terminal_width().

    Claude Code's statusLine subprocess hides the real terminal width
    (no TTY, no COLUMNS env), so naive shutil returns the fallback.
    The function tries 7 signals in order and returns the first
    plausible value. These tests exercise each signal independently
    and pin the order so a refactor can't silently demote a more-
    reliable source.
    """

    def setUp(self):
        # Always start from a clean slate: clear COLUMNS so step 2/3
        # don't accidentally win in tests checking later steps.
        self._old_cols = os.environ.pop("COLUMNS", None)
        self._old_lines = os.environ.pop("LINES", None)

    def tearDown(self):
        if self._old_cols is not None:
            os.environ["COLUMNS"] = self._old_cols
        if self._old_lines is not None:
            os.environ["LINES"] = self._old_lines

    # --- Step 1: stdin terminal.columns -------------------------------

    def test_stdin_terminal_columns_wins(self):
        """When data['terminal']['columns'] is present and plausible,
        it wins over every other signal — even COLUMNS env."""
        from claude_statusline.cli import _detect_terminal_width
        os.environ["COLUMNS"] = "200"
        result = _detect_terminal_width({"terminal": {"columns": 165}})
        self.assertEqual(result, 165)

    def test_stdin_terminal_columns_string_coerced(self):
        """Coerce numeric strings via _safe_num so JSON serializers
        that stringify integers (rare but real) still work."""
        from claude_statusline.cli import _detect_terminal_width
        result = _detect_terminal_width({"terminal": {"columns": "165"}})
        self.assertEqual(result, 165)

    def test_stdin_terminal_columns_implausible_rejected(self):
        """Out-of-range values fall through to the next signal —
        guards against an upstream bug returning 0 or 99999."""
        from claude_statusline.cli import _detect_terminal_width
        os.environ["COLUMNS"] = "150"
        result = _detect_terminal_width({"terminal": {"columns": 0}})
        self.assertEqual(result, 150, "implausible 0 should fall through to COLUMNS")
        result = _detect_terminal_width({"terminal": {"columns": 999999}})
        self.assertEqual(result, 150, "implausible 999999 should fall through to COLUMNS")

    def test_stdin_terminal_not_dict_falls_through(self):
        """data['terminal'] being a string/list/None must not crash —
        just fall through. isinstance guard."""
        from claude_statusline.cli import _detect_terminal_width
        os.environ["COLUMNS"] = "150"
        for bad in ("string", [], None, 42):
            result = _detect_terminal_width({"terminal": bad})
            self.assertEqual(result, 150,
                "data['terminal']={!r} should fall through cleanly".format(bad))

    def test_data_none_falls_through(self):
        """No data argument is the legitimate cmd_doctor case — must
        not crash; falls through to env / OS signals."""
        from claude_statusline.cli import _detect_terminal_width
        os.environ["COLUMNS"] = "150"
        result = _detect_terminal_width(None)
        self.assertEqual(result, 150)

    # --- Step 2: COLUMNS env var --------------------------------------

    def test_columns_env_var_wins_when_no_stdin_signal(self):
        from claude_statusline.cli import _detect_terminal_width
        os.environ["COLUMNS"] = "200"
        result = _detect_terminal_width({})
        self.assertEqual(result, 200)

    def test_columns_env_garbage_falls_through(self):
        """Non-numeric COLUMNS must not crash."""
        from claude_statusline.cli import _detect_terminal_width
        os.environ["COLUMNS"] = "wide"
        # Falls through; result depends on host env, but must be int
        # in plausible range and not raise.
        result = _detect_terminal_width({})
        self.assertIsInstance(result, int)
        self.assertGreaterEqual(result, 20)

    def test_columns_env_negative_falls_through(self):
        """Negative COLUMNS (some misconfigured shells) is rejected."""
        from claude_statusline.cli import _detect_terminal_width
        os.environ["COLUMNS"] = "-5"
        result = _detect_terminal_width({})
        # Falls through, doesn't return -5
        self.assertGreaterEqual(result, 20)

    # --- Bounds and clamping ------------------------------------------

    def test_stdin_terminal_columns_lower_bound(self):
        """20 is the minimum plausible width — anything below falls
        through. 20 itself is accepted."""
        from claude_statusline.cli import _detect_terminal_width
        os.environ["COLUMNS"] = "150"
        result = _detect_terminal_width({"terminal": {"columns": 20}})
        self.assertEqual(result, 20)
        result = _detect_terminal_width({"terminal": {"columns": 19}})
        self.assertEqual(result, 150, "below-min should fall through")

    def test_stdin_terminal_columns_upper_bound(self):
        """4000 is the max — covers ultrawide / 8K / multi-monitor
        tmux setups. Anything above falls through."""
        from claude_statusline.cli import _detect_terminal_width
        os.environ["COLUMNS"] = "150"
        result = _detect_terminal_width({"terminal": {"columns": 4000}})
        self.assertEqual(result, 4000)
        result = _detect_terminal_width({"terminal": {"columns": 4001}})
        self.assertEqual(result, 150, "above-max should fall through")

    def test_stdin_terminal_columns_2000_is_accepted(self):
        """An 8K display in tmux can legitimately reach ~1280 cols;
        side-by-side multi-monitor setups can exceed 2000. 2000 must
        be inside the plausible range, not silently dropped to the
        compact fallback."""
        from claude_statusline.cli import _detect_terminal_width
        result = _detect_terminal_width({"terminal": {"columns": 2000}})
        self.assertEqual(result, 2000)

    # --- Final fallback path ------------------------------------------

    def test_returns_int_in_plausible_range(self):
        """Even with zero usable signals, we must return an integer
        in the documented plausible range — never None, never a float,
        never a crash."""
        from claude_statusline.cli import (
            _detect_terminal_width,
            _TERM_WIDTH_MIN,
            _TERM_WIDTH_MAX,
        )
        # Even when nothing is set, we get something usable
        result = _detect_terminal_width({})
        self.assertIsInstance(result, int)
        self.assertGreaterEqual(result, _TERM_WIDTH_MIN)
        self.assertLessEqual(result, _TERM_WIDTH_MAX)


class TestRenderUsesDetectedWidth(unittest.TestCase):
    """End-to-end: render() must consume data['terminal']['columns']
    when present, exposing more sections at wide terminals where the
    naive `shutil.get_terminal_size` fallback would have hidden them.
    This is the user-facing fix — regression-grade test guards it."""

    def test_render_at_165_cols_via_stdin_shows_more_sections(self):
        """The actual user scenario from screenshot at PR #79: a 165-
        col terminal that previously showed only ~5 sections on Line 2
        now shows ~10+ because the precise stage has the real width."""
        # Stub git helpers so this test is deterministic across hosts.
        import claude_statusline.cli as cli_mod
        orig = {
            "get_remote_url": cli_mod.get_remote_url,
            "get_git_state": cli_mod.get_git_state,
            "get_last_commit_age_ms": cli_mod.get_last_commit_age_ms,
            "get_git_extras": cli_mod.get_git_extras,
            "get_session_tool_count": cli_mod.get_session_tool_count,
            "get_today_session_count": cli_mod.get_today_session_count,
            "get_effort_level": cli_mod.get_effort_level,
        }
        cli_mod.get_remote_url = lambda: ""
        cli_mod.get_git_state = lambda: ""
        cli_mod.get_last_commit_age_ms = lambda: 3600000  # 1h
        cli_mod.get_git_extras = lambda: {}
        cli_mod.get_session_tool_count = lambda sid: 0
        cli_mod.get_today_session_count = lambda: 1
        cli_mod.get_effort_level = lambda: "xhigh"
        try:
            data = {
                "context_window": {"used_percentage": 18,
                                   "context_window_size": 1_000_000,
                                   "current_usage": {"input_tokens": 1, "output_tokens": 242}},
                "cost": {"total_cost_usd": 879, "total_duration_ms": 196_080_000,
                         "total_lines_added": 18683, "total_lines_removed": 1628},
                "git_branch": "main",
                "model": {"display_name": "Opus 4.8 (1M context)"},
                "terminal": {"columns": 165},
            }
            out = render(data)
            from claude_statusline.cli import _visible_width
            lines = out.split("\n")
            # Line 2 must fit the 165-col budget…
            line2_width = _visible_width(lines[1])
            self.assertLessEqual(line2_width, 165,
                "Line 2 width {} exceeds 165 — fit logic broken".format(line2_width))
            # …and use significantly more of it than the ~83 chars the
            # naive fallback would have produced.
            self.assertGreater(line2_width, 100,
                "Line 2 width {} is too small — terminal.columns from "
                "stdin was probably not consumed".format(line2_width))
            # Specific recovered sections that proved the bug originally:
            # (label changed "(1000K)" -> "(1M)" in v0.10.0 when
            # context_size adopted fmt_tokens)
            self.assertIn("(1M)", out, "context_size should appear at 165 cols")
            self.assertIn("effort:xhigh", out, "effort should appear at 165 cols")
        finally:
            for name, fn in orig.items():
                setattr(cli_mod, name, fn)


# ─── cli.py — rate_limits epoch-timestamp guard (#79 / upstream #52326) ──

class TestRateLimitsEpochTimestampGuard(unittest.TestCase):
    """Anthropic's claude-code#52326: on a fresh 5h or 7d window with
    no usage data yet, used_percentage returns the resets_at epoch
    timestamp (~1.7e9) instead of 0/null. Without a guard our
    downstream clamp(0,100) silently turns it into a false
    `5h:100% (red)` alarm. The guard treats anything > 100 as
    'no data yet' and drops to None so the section is hidden."""

    def _data(self, five_h_pct=None, seven_d_pct=None):
        return {
            "context_window": {"used_percentage": 20,
                               "current_usage": {"input_tokens": 1000}},
            "cost": {"total_cost_usd": 0.5, "total_duration_ms": 60000},
            "git_branch": "main",
            "rate_limits": {
                "five_hour": {
                    "used_percentage": five_h_pct,
                    "resets_at": 1_776_950_400,
                },
                "seven_day": {
                    "used_percentage": seven_d_pct,
                    "resets_at": 1_777_500_000,
                },
            },
        }

    def test_epoch_timestamp_in_5h_used_percentage_is_hidden(self):
        """5h section must NOT render when upstream returns the
        timestamp value. Pre-fix, this rendered as '5h:100%' in red."""
        from claude_statusline.cli import _normalize
        n = _normalize(self._data(five_h_pct=1_776_950_400, seven_d_pct=18))
        self.assertIsNone(n["rate_limit_5h_pct"],
            "5h epoch-timestamp value must drop to None")
        self.assertEqual(n["rate_limit_7d_pct"], 18.0,
            "legitimate 7d value must still pass through unchanged")

    def test_epoch_timestamp_in_7d_used_percentage_is_hidden(self):
        from claude_statusline.cli import _normalize
        n = _normalize(self._data(five_h_pct=42, seven_d_pct=1_777_500_000))
        self.assertEqual(n["rate_limit_5h_pct"], 42.0)
        self.assertIsNone(n["rate_limit_7d_pct"])

    def test_legitimate_values_pass_through_unchanged(self):
        from claude_statusline.cli import _normalize
        n = _normalize(self._data(five_h_pct=34, seven_d_pct=68))
        self.assertEqual(n["rate_limit_5h_pct"], 34.0)
        self.assertEqual(n["rate_limit_7d_pct"], 68.0)

    def test_boundary_value_100_passes_through(self):
        """Exactly 100% IS a legitimate used_percentage (truly maxed
        out) — the guard only triggers at the epoch-timestamp pattern
        (>= 1e6). Pin the boundary."""
        from claude_statusline.cli import _normalize
        n = _normalize(self._data(five_h_pct=100, seven_d_pct=100))
        self.assertEqual(n["rate_limit_5h_pct"], 100.0)
        self.assertEqual(n["rate_limit_7d_pct"], 100.0)

    def test_value_modestly_above_100_passes_through(self):
        """Values 101-999999 are NOT the upstream bug pattern (which is
        always epoch seconds ~1.7e9). They could be a future Anthropic
        'overage' indicator above 100%, so we let them through and rely
        on the renderer's existing clamp(0, 100) for safe display.
        Pre-emptively hiding these would silently swallow real signals.
        """
        from claude_statusline.cli import _normalize
        n = _normalize(self._data(five_h_pct=105, seven_d_pct=999999))
        self.assertEqual(n["rate_limit_5h_pct"], 105.0,
            "value just above 100 should flow through to the renderer's clamp")
        self.assertEqual(n["rate_limit_7d_pct"], 999999.0,
            "value just below 1e6 should still flow through (not bug pattern)")

    def test_epoch_pattern_at_threshold_is_dropped(self):
        """The threshold is 1e6: any value at or above that is treated
        as the upstream epoch-timestamp bug pattern. Pins the boundary
        explicitly."""
        from claude_statusline.cli import _normalize
        n = _normalize(self._data(five_h_pct=1_000_000, seven_d_pct=1_000_001))
        self.assertIsNone(n["rate_limit_5h_pct"])
        self.assertIsNone(n["rate_limit_7d_pct"])

    def test_renders_no_5h_section_when_upstream_bug_present(self):
        """End-to-end: rate_limits section in render() must hide the
        bugged value, not render it in red. This is the user-visible
        contract — 'no false 5h:100% alarm on fresh sessions'."""
        result = render(self._data(five_h_pct=1_776_950_400, seven_d_pct=68))
        # Must NOT contain a percentage in the billions
        self.assertNotIn("5h:", result,
            "5h section must be hidden when upstream returns epoch timestamp")
        # 7d section still renders normally
        self.assertIn("7d:68", result)


# ─── cli.py — effort.level from JSON stdin (#81, Claude Code v2.1.119+) ──

class TestEffortLevelFromStdin(unittest.TestCase):
    """Pin the new stdin-as-source behavior for effort level.

    Claude Code v2.1.119 added `effort.level` to the statusline JSON
    stdin payload. v0.5.8 prefers this over the settings.json file
    read so users see effort changes within one render cycle of
    `/effort xhigh` instead of waiting up to 30s for the cache to
    expire. The settings.json read remains as a fallback for older
    Claude Code versions.
    """

    def _data(self, **extras):
        base = {
            "context_window": {"used_percentage": 30,
                               "current_usage": {"input_tokens": 5000}},
            "cost": {"total_cost_usd": 0.5, "total_duration_ms": 60000},
            "git_branch": "main",
        }
        base.update(extras)
        return base

    # ── _normalize behavior ─────────────────────────────────────────

    def test_normalize_extracts_effort_level_from_stdin(self):
        """Valid effort.level in stdin populates n['effort_level']."""
        from claude_statusline.cli import _normalize
        n = _normalize(self._data(effort={"level": "xhigh"}))
        self.assertEqual(n["effort_level"], "xhigh")

    def test_normalize_accepts_all_valid_levels_from_stdin(self):
        """Each level in _VALID_EFFORT_LEVELS (except 'medium') is
        passed through verbatim. 'medium' is normalized to the empty-
        string sentinel that signals "explicitly hide" to the renderer
        — this skips the settings.json fallback so the user sees the
        section disappear within one render cycle of `/effort medium`
        instead of lagging up to 30s on a stale cache value.
        """
        from claude_statusline.cli import _normalize
        for level in ("low", "high", "xhigh", "max"):
            n = _normalize(self._data(effort={"level": level}))
            self.assertEqual(n["effort_level"], level,
                "stdin effort.level={!r} should pass through".format(level))
        # medium is normalized to "" (sentinel for "explicitly hide,
        # skip fallback") — NOT None (which would mean "no signal,
        # fall back").
        n = _normalize(self._data(effort={"level": "medium"}))
        self.assertEqual(n["effort_level"], "",
            "stdin effort.level='medium' should normalize to '' "
            "sentinel, NOT None — None would trigger the fallback "
            "to settings.json and risk showing a stale value")

    def test_normalize_case_insensitive(self):
        """Mixed-case effort levels in stdin normalize to lowercase
        — matches existing settings.json behavior, prevents a future
        Anthropic schema doc using 'Xhigh' or 'XHIGH' from breaking."""
        from claude_statusline.cli import _normalize
        for variant in ("XHIGH", "Xhigh", "xHigh"):
            n = _normalize(self._data(effort={"level": variant}))
            self.assertEqual(n["effort_level"], "xhigh",
                "stdin effort.level={!r} should normalize to 'xhigh'".format(variant))

    def test_normalize_rejects_unknown_level_from_stdin(self):
        """Unknown effort levels (typos, future variants we don't
        recognize) drop to None so the renderer doesn't display
        garbage. Users on a newer Claude Code than this claude-status
        version will fall back to settings.json — better stale-but-
        valid than fresh-but-garbage."""
        from claude_statusline.cli import _normalize
        n = _normalize(self._data(effort={"level": "ultrathink"}))
        self.assertIsNone(n["effort_level"])

    def test_normalize_rejects_non_string_level(self):
        """effort.level being an int / list / None must not crash."""
        from claude_statusline.cli import _normalize
        for bad in (42, ["xhigh"], None, True, {"level": "nested"}):
            n = _normalize(self._data(effort={"level": bad}))
            self.assertIsNone(n["effort_level"],
                "stdin effort.level={!r} should be rejected".format(bad))

    def test_normalize_rejects_non_dict_effort(self):
        """effort field being a string / list / None — the isinstance
        guard prevents an AttributeError on .get()."""
        from claude_statusline.cli import _normalize
        for bad in ("xhigh", ["xhigh"], None, 42):
            n = _normalize(self._data(effort=bad))
            self.assertIsNone(n["effort_level"],
                "data['effort']={!r} should be rejected cleanly".format(bad))

    def test_normalize_absent_effort_yields_none(self):
        """No effort field in stdin (older Claude Code, demo data) —
        n['effort_level'] is None so the renderer falls back to
        get_effort_level() (settings.json read)."""
        from claude_statusline.cli import _normalize
        n = _normalize(self._data())
        self.assertIsNone(n["effort_level"])

    # ── render() integration: stdin wins over settings.json ────────

    def test_render_prefers_stdin_over_settings_json(self):
        """When stdin has effort.level, the settings.json read should
        be SKIPPED entirely. Pin via a stub that would error if called."""
        import claude_statusline.cli as cli_mod
        orig = cli_mod.get_effort_level
        # Make get_effort_level loud so we know if it was called.
        called = []
        def loud_settings_read():
            called.append(True)
            return "low"  # would render as effort:low if used
        cli_mod.get_effort_level = loud_settings_read
        try:
            data = self._data(effort={"level": "xhigh"})
            result = render(data)
            self.assertIn("effort:xhigh", result,
                "stdin xhigh should be rendered, not the stubbed 'low'")
            self.assertNotIn("effort:low", result,
                "settings.json fallback should not have been consulted")
            self.assertEqual(len(called), 0,
                "get_effort_level() must NOT be called when stdin has effort.level")
        finally:
            cli_mod.get_effort_level = orig

    def test_render_falls_back_to_settings_when_stdin_absent(self):
        """No effort field in stdin → renderer must call
        get_effort_level() to read settings.json. This is the
        backward-compatibility path for older Claude Code versions."""
        import claude_statusline.cli as cli_mod
        orig = cli_mod.get_effort_level
        called = []
        def fake_settings_read():
            called.append(True)
            return "max"
        cli_mod.get_effort_level = fake_settings_read
        try:
            data = self._data()  # NO effort field
            result = render(data)
            self.assertIn("effort:max", result,
                "settings.json fallback should be consulted and rendered")
            self.assertEqual(len(called), 1,
                "get_effort_level() must be called exactly once on the fallback path")
        finally:
            cli_mod.get_effort_level = orig

    def test_render_falls_back_when_stdin_effort_level_invalid(self):
        """Invalid stdin effort.level (e.g. 'ultrathink') → renderer
        falls back to settings.json. Pinning this means a future
        Anthropic schema variant we don't recognize won't blank the
        section if the user has a valid effortLevel in settings.json."""
        import claude_statusline.cli as cli_mod
        orig = cli_mod.get_effort_level
        cli_mod.get_effort_level = lambda: "high"
        try:
            data = self._data(effort={"level": "ultrathink"})
            result = render(data)
            self.assertIn("effort:high", result,
                "invalid stdin should fall through to settings.json read")
        finally:
            cli_mod.get_effort_level = orig

    def test_render_stdin_medium_hides_section_skipping_fallback(self):
        """Stdin medium = explicit hide. The renderer must NOT fall
        back to get_effort_level() — stdin is fresher than the 30s
        settings.json cache, so honoring stdin's authoritative
        signal beats reading a potentially stale cache value.

        Pinned with a "loud stub" that records whether
        get_effort_level was called. After running `/effort medium`
        in the new client, the user expects the indicator to vanish
        on the next render — not lag up to 30s."""
        import claude_statusline.cli as cli_mod
        orig = cli_mod.get_effort_level
        called = []
        def loud_settings_read():
            called.append(True)
            return "high"  # settings.json has a stale non-medium value
        cli_mod.get_effort_level = loud_settings_read
        try:
            data = self._data(effort={"level": "medium"})
            result = render(data)
            self.assertNotIn("effort:", result,
                "stdin medium should hide section even when settings.json "
                "still has a stale non-medium value")
            self.assertEqual(len(called), 0,
                "get_effort_level() must NOT be called when stdin says "
                "medium — bypassing the stale settings.json cache is the "
                "whole point of honoring the stdin signal")
        finally:
            cli_mod.get_effort_level = orig

    def test_render_stdin_medium_hides_when_settings_also_medium(self):
        """Belt-and-suspenders: stdin medium + settings medium both
        result in the section being hidden. This is the no-staleness
        scenario where both sources agree."""
        import claude_statusline.cli as cli_mod
        orig = cli_mod.get_effort_level
        cli_mod.get_effort_level = lambda: None  # settings.json is medium → None
        try:
            data = self._data(effort={"level": "medium"})
            result = render(data)
            self.assertNotIn("effort:medium", result)
            self.assertNotIn("effort:", result)
        finally:
            cli_mod.get_effort_level = orig

    def test_render_no_stdin_with_settings_medium(self):
        """No effort field in stdin → renderer calls get_effort_level()
        → if settings.json says medium it returns None → section hides.
        Pins the existing settings.json medium-hidden contract still
        works after the v0.5.8 changes."""
        import claude_statusline.cli as cli_mod
        orig = cli_mod.get_effort_level
        cli_mod.get_effort_level = lambda: None  # settings.json medium → None
        try:
            data = self._data()  # no effort field
            result = render(data)
            self.assertNotIn("effort:", result,
                "no stdin + settings.json medium should hide the section")
        finally:
            cli_mod.get_effort_level = orig

    def test_render_each_valid_level_via_stdin_path(self):
        """Each non-medium level in _VALID_EFFORT_LEVELS renders
        correctly through the stdin path. Without this, a future
        refactor that broke the stdin chain only for non-xhigh values
        (e.g., a typo in _normalize that passes 'xhigh' but drops
        'low'/'high'/'max') would not be caught — the existing
        TestEffortSection tests stub get_effort_level directly and
        bypass _normalize entirely."""
        import claude_statusline.cli as cli_mod
        orig = cli_mod.get_effort_level
        # Stub settings.json to a known-wrong value so we'd notice
        # if the renderer accidentally fell through.
        cli_mod.get_effort_level = lambda: "wrong-value-must-not-appear"
        try:
            for level in ("low", "high", "xhigh", "max"):
                data = self._data(effort={"level": level})
                result = render(data)
                self.assertIn("effort:" + level, result,
                    "stdin level={!r} should render via the stdin path".format(level))
                self.assertNotIn("wrong-value-must-not-appear", result,
                    "stdin level={!r} should not fall through to "
                    "settings.json".format(level))
        finally:
            cli_mod.get_effort_level = orig

    def test_normalize_writes_effort_cache_when_stdin_supplies_value(self):
        """When _normalize extracts a valid effort.level from stdin,
        it MUST mirror the value to the on-disk effort_level cache.

        Why: if the user later switches to an older Claude Code
        client (or any tool that doesn't supply stdin effort), the
        next render falls back to get_effort_level() which reads from
        the cache. Without the mirror-write, the cache could hold a
        stale value from before the user's last `/effort` change —
        rendering the wrong effort with no signal to the user.

        Pins the cache-consistency invariant flagged by the v0.5.8
        silent-failure review.
        """
        import claude_statusline.sessions as sessions_mod
        import claude_statusline.cli as cli_mod
        from claude_statusline.sessions import _read_cache
        with tempfile.TemporaryDirectory() as tmpdir:
            # Patch the cache directory so this test can't pollute
            # the real user-scoped temp cache.
            orig_get = sessions_mod._cache_dir
            sessions_mod._cache_dir = lambda: tmpdir
            try:
                cli_mod._normalize(self._data(effort={"level": "xhigh"}))
                cached = _read_cache("effort_level")
                self.assertIsNotNone(cached,
                    "stdin effort.level should mirror to the cache file")
                self.assertEqual(cached.get("effort"), "xhigh",
                    "cached value should match the stdin level")
            finally:
                sessions_mod._cache_dir = orig_get

    def test_normalize_does_not_write_cache_when_stdin_invalid(self):
        """If stdin effort.level is invalid (unknown level, wrong
        type), _normalize must NOT write to the cache — that would
        propagate the upstream bug to the fallback path.
        """
        import claude_statusline.sessions as sessions_mod
        import claude_statusline.cli as cli_mod
        from claude_statusline.sessions import _cache_path
        with tempfile.TemporaryDirectory() as tmpdir:
            orig_get = sessions_mod._cache_dir
            sessions_mod._cache_dir = lambda: tmpdir
            try:
                cli_mod._normalize(self._data(effort={"level": "ultrathink"}))
                cache_file = _cache_path("effort_level")
                self.assertFalse(os.path.exists(cache_file),
                    "invalid stdin effort.level must not write the cache")
            finally:
                sessions_mod._cache_dir = orig_get

    def test_normalize_skips_cache_write_when_value_unchanged(self):
        """Performance: _normalize runs on every render. If the cache
        already has the same value, skip the atomic write+rename
        (which is much more expensive than a stat+read). Without
        this, an active session with a low refreshInterval would
        burn one disk write per render forever.
        """
        import claude_statusline.sessions as sessions_mod
        import claude_statusline.cli as cli_mod
        from claude_statusline.sessions import _cache_path, _write_cache
        import os
        with tempfile.TemporaryDirectory() as tmpdir:
            orig_get = sessions_mod._cache_dir
            sessions_mod._cache_dir = lambda: tmpdir
            try:
                # Seed the cache with the same value we'll send via stdin.
                _write_cache("effort_level", {"effort": "xhigh"})
                cache_file = _cache_path("effort_level")
                mtime_before = os.path.getmtime(cache_file)
                # Sleep long enough that any rewrite produces a new
                # mtime that's distinguishable from the original.
                # (Filesystem mtime resolution is typically 1ms-1s.)
                time.sleep(0.05)
                # Run _normalize with the SAME value already cached.
                cli_mod._normalize(self._data(effort={"level": "xhigh"}))
                mtime_after = os.path.getmtime(cache_file)
                self.assertEqual(mtime_before, mtime_after,
                    "cache file mtime changed — _normalize must skip the "
                    "write when the cached value is already correct "
                    "(read+compare is cheaper than atomic write+rename)")
            finally:
                sessions_mod._cache_dir = orig_get

    def test_normalize_writes_cache_when_value_changed(self):
        """Inverse pin: when stdin says a different level than what's
        cached, _normalize MUST write the new value (otherwise the
        whole point of the mirror-write is defeated)."""
        import claude_statusline.sessions as sessions_mod
        import claude_statusline.cli as cli_mod
        from claude_statusline.sessions import _read_cache, _write_cache
        with tempfile.TemporaryDirectory() as tmpdir:
            orig_get = sessions_mod._cache_dir
            sessions_mod._cache_dir = lambda: tmpdir
            try:
                _write_cache("effort_level", {"effort": "high"})
                # Stdin disagrees — should overwrite the cache.
                cli_mod._normalize(self._data(effort={"level": "max"}))
                cached = _read_cache("effort_level")
                self.assertEqual(cached.get("effort"), "max",
                    "cache must be overwritten when stdin gives a "
                    "different level than the existing cached value")
            finally:
                sessions_mod._cache_dir = orig_get


class TestClaudeCode2139WidthRegression(unittest.TestCase):
    """Width-detection guards for the Claude Code 2.1.139 regression.

    2.1.139 (2026-05-11 release notes: "hooks now run without terminal
    access") removed every TTY signal the earlier fallback chain
    depended on. Symptoms confirmed by independent statusline authors
    in anthropics/claude-code#22115:

      - COLUMNS env: set to "0" (not unset)
      - /dev/tty:    ENXIO
      - stty size:   fails
      - tput cols:   returns 80 (terminfo default — LIES with a straight face)

    Without these guards we would parse `tput cols == 80` as a real
    reading and render an 80-col layout into a 220-col terminal.
    Tracked at issue #83.
    """

    def setUp(self):
        self._old_cols = os.environ.pop("COLUMNS", None)
        self._old_lines = os.environ.pop("LINES", None)

    def tearDown(self):
        if self._old_cols is not None:
            os.environ["COLUMNS"] = self._old_cols
        if self._old_lines is not None:
            os.environ["LINES"] = self._old_lines

    # --- COLUMNS=0 (distinct from unset) ------------------------------

    def test_columns_env_zero_rejected_distinctly(self):
        """COLUMNS="0" must be rejected and reported as a no-TTY
        signal — not silently treated as "unset" or "garbage." The
        report distinction matters for --doctor diagnostics."""
        from claude_statusline.cli import _detect_terminal_width_report
        os.environ["COLUMNS"] = "0"
        result, report = _detect_terminal_width_report({})
        # Result must NOT be 0 (would be far below _TERM_WIDTH_MIN)
        self.assertGreaterEqual(result, 20)
        # Report must mention 0 explicitly as a no-TTY signal, not
        # collapse it into "unset" or "garbage"
        cols_entries = [s for label, s in report if label == "COLUMNS env"]
        self.assertEqual(len(cols_entries), 1)
        self.assertIn("0", cols_entries[0])
        self.assertNotEqual(cols_entries[0], "unset",
            "COLUMNS=0 must be distinguished from COLUMNS unset")

    def test_columns_env_unset_reported_as_unset(self):
        """COLUMNS unset (the normal case) must report 'unset' — pin
        the report wording so --doctor remains intelligible."""
        from claude_statusline.cli import _detect_terminal_width_report
        os.environ.pop("COLUMNS", None)
        _result, report = _detect_terminal_width_report({})
        cols_entries = [s for label, s in report if label == "COLUMNS env"]
        self.assertEqual(cols_entries, ["unset"])

    # --- tput stub rejection (the headline 2.1.139 fix) ---------------

    def test_tput_stub_80_rejected_when_no_tty_signal(self):
        """When subprocess.run returns tput cols=80 AND no earlier TTY
        probe succeeded, the 80 must be rejected as a likely terminfo
        stub. The chain must fall through to the safe default, not
        return 80."""
        import subprocess as subprocess_mod
        from claude_statusline.cli import (
            _COMPACT_LAYOUT_MIN_COLS,
            _detect_terminal_width_report,
        )

        # Simulate 2.1.139: /dev/tty is reachable (some hosts still
        # have it), stty fails, tput returns 80. We must NOT return 80.
        orig_run = subprocess_mod.run
        orig_open = __builtins__["open"] if isinstance(__builtins__, dict) else open

        def fake_run(cmd, *args, **kwargs):
            if cmd[0] == "stty":
                # Simulate stty failing in the no-controlling-TTY env
                return subprocess_mod.CompletedProcess(cmd, 1, "", "stty: stdin isn't a tty\n")
            if cmd[0] == "tput":
                return subprocess_mod.CompletedProcess(cmd, 0, "80\n", "")
            return orig_run(cmd, *args, **kwargs)

        # Patch open() so /dev/tty appears reachable even on Windows
        # test hosts. We pass through every other path.
        class FakeTTY:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return ""
            def fileno(self): return 0

        def fake_open(path, *args, **kwargs):
            if path == "/dev/tty":
                return FakeTTY()
            return orig_open(path, *args, **kwargs)

        import claude_statusline.cli as cli_mod
        cli_mod.subprocess.run = fake_run
        # Hide every higher-priority signal so we're forced into the
        # stty/tput step where the stub rejection lives.
        os.environ.pop("COLUMNS", None)
        # Patch open at the cli module level so the chain's
        # `open("/dev/tty", "r")` returns our fake.
        cli_mod_open = cli_mod.__builtins__["open"] if isinstance(
            cli_mod.__builtins__, dict) else cli_mod.__builtins__.open
        try:
            if isinstance(cli_mod.__builtins__, dict):
                cli_mod.__builtins__["open"] = fake_open
            else:
                cli_mod.__builtins__.open = fake_open
            result, report = _detect_terminal_width_report({})
        finally:
            cli_mod.subprocess.run = orig_run
            if isinstance(cli_mod.__builtins__, dict):
                cli_mod.__builtins__["open"] = cli_mod_open
            else:
                cli_mod.__builtins__.open = cli_mod_open

        # The fake tput returned 80; we must have rejected it. The
        # final result should be the safe compact fallback, NOT 80.
        self.assertNotEqual(result, 80,
            "tput cols=80 with no earlier TTY signal must be rejected as a "
            "likely terminfo stub (Claude Code 2.1.139 regression)")
        self.assertEqual(result, _COMPACT_LAYOUT_MIN_COLS,
            "should fall through to the safe default when no signal is "
            "trustworthy")

        # The report must explain why we rejected the 80
        tput_entries = [s for label, s in report if label == "tput cols"]
        self.assertTrue(any("stub" in s or "rejected" in s for s in tput_entries),
            "report must explain the rejection so --doctor users see why; "
            "got: {!r}".format(tput_entries))

    def test_tput_value_other_than_stub_not_rejected(self):
        """tput cols=137 must NOT be rejected even when no earlier
        signal succeeded — only the known stub values (80) trip the
        heuristic. Real-but-unusual widths must pass through."""
        from claude_statusline.cli import _TPUT_STUB_VALUES
        self.assertIn(80, _TPUT_STUB_VALUES,
            "80 is the documented terminfo default for xterm-family TERMs")
        self.assertNotIn(137, _TPUT_STUB_VALUES,
            "137 is a plausible real width — must not be on the stub list")
        self.assertNotIn(120, _TPUT_STUB_VALUES)
        self.assertNotIn(200, _TPUT_STUB_VALUES)

    def test_stub_heuristic_not_triggered_when_prior_tty_signal_exists(self):
        """The inverse of test_tput_stub_80_rejected_when_no_tty_signal:
        if any earlier step succeeded with a TTY probe, then a tput
        cols=80 reading is a REAL 80-col terminal, not a stub —
        accept it.

        Without this test, the heuristic could be inverted
        (`and any_tty_probe_succeeded` instead of `and not …`) and
        every existing test would still pass.

        We don't simulate the full chain — we just verify the gating
        flag's intent by checking the `any_tty_probe_succeeded`
        condition in the source. This is a structural test, not
        behavioral: it ensures the heuristic's PRECONDITION (no prior
        TTY signal) is in the code, so a future refactor that drops
        the gating fails this test.
        """
        import inspect
        from claude_statusline import cli as cli_mod
        source = inspect.getsource(cli_mod._detect_terminal_width_report)
        # The gating condition is the difference between "reject every
        # tput 80" (would harm real 80-col users) and "reject tput 80
        # only when no other TTY signal succeeded" (correct).
        self.assertIn("any_tty_probe_succeeded", source,
            "stub heuristic must gate on whether any earlier TTY probe "
            "succeeded — otherwise users with a real 80-col terminal would "
            "be miscategorized when other signals also fail")
        # Must check the FALSE branch (no signal), not the true branch.
        self.assertIn("not any_tty_probe_succeeded", source,
            "stub heuristic must reject only when no earlier TTY signal "
            "succeeded — guard against accidental inversion of the gate")

    def test_stub_heuristic_actually_reachable_on_platform(self):
        """The headline test_tput_stub_80_rejected_when_no_tty_signal
        monkey-patches __builtins__["open"]. On Windows, if that
        patch fails to take (some Python build configs), the chain
        never opens /dev/tty and the stub branch is never reached —
        the assertion passes trivially via the safe fallback path.

        This test makes the silent skip loud: the report MUST contain
        a tput cols entry that mentions 'stub' or 'rejected', proving
        the stub branch actually fired. Without this, the green CI
        on Windows could be hiding a broken patch.
        """
        import subprocess as subprocess_mod
        import claude_statusline.cli as cli_mod

        orig_run = subprocess_mod.run
        orig_open = __builtins__["open"] if isinstance(__builtins__, dict) else open

        class FakeTTY:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return ""
            def fileno(self): return 0

        def fake_run(cmd, *args, **kwargs):
            if cmd[0] == "stty":
                return subprocess_mod.CompletedProcess(cmd, 1, "", "")
            if cmd[0] == "tput":
                return subprocess_mod.CompletedProcess(cmd, 0, "80\n", "")
            return orig_run(cmd, *args, **kwargs)

        def fake_open(path, *args, **kwargs):
            if path == "/dev/tty":
                return FakeTTY()
            return orig_open(path, *args, **kwargs)

        cli_mod.subprocess.run = fake_run
        os.environ.pop("COLUMNS", None)
        cli_builtins = cli_mod.__builtins__
        cli_open_was_dict = isinstance(cli_builtins, dict)
        cli_orig_open = (cli_builtins["open"] if cli_open_was_dict
                         else cli_builtins.open)
        try:
            if cli_open_was_dict:
                cli_builtins["open"] = fake_open
            else:
                cli_builtins.open = fake_open
            _result, report = cli_mod._detect_terminal_width_report({})
        finally:
            cli_mod.subprocess.run = orig_run
            if cli_open_was_dict:
                cli_builtins["open"] = cli_orig_open
            else:
                cli_builtins.open = cli_orig_open

        # Find the tput entry. If it's not there, the patch silently
        # failed and the headline test would have green-lit a broken
        # build. Make that LOUD.
        tput_entries = [s for label, s in report if label == "tput cols"]
        self.assertTrue(tput_entries,
            "tput cols step must have produced a report entry — if absent, "
            "the /dev/tty open path failed to reach the stty/tput block "
            "and the stub-rejection assertion in the headline test is "
            "vacuous on this platform")
        self.assertTrue(
            any("stub" in s or "rejected" in s for s in tput_entries),
            "tput cols must show the stub-rejection signature ('stub' or "
            "'rejected'); got: {!r}".format(tput_entries))

    # --- Process-tree walk --------------------------------------------

    def test_process_tree_walk_skipped_on_windows(self):
        """Windows has no /proc and a different subprocess ancestry
        model — the walk must short-circuit cleanly."""
        from claude_statusline.cli import _detect_width_via_process_tree
        if platform.system() != "Windows":
            self.skipTest("Windows-only check")
        result, status = _detect_width_via_process_tree()
        self.assertIsNone(result)
        self.assertIn("Windows", status)

    def test_process_tree_walk_returns_tuple(self):
        """The walk must always return a 2-tuple (Optional[int], str)
        regardless of platform — never raise, never return None alone.
        --doctor concatenates the status string into its output."""
        from claude_statusline.cli import _detect_width_via_process_tree
        result = _detect_width_via_process_tree()
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        winner, status = result
        self.assertTrue(winner is None or isinstance(winner, int))
        self.assertIsInstance(status, str)
        self.assertGreater(len(status), 0,
            "status must be non-empty for --doctor formatting")

    # --- Report shape (consumed by --doctor) --------------------------

    def test_report_is_list_of_pairs(self):
        """_detect_terminal_width_report returns (int, list[(str, str)])
        — pin the shape so --doctor formatting doesn't break."""
        from claude_statusline.cli import _detect_terminal_width_report
        result, report = _detect_terminal_width_report({})
        self.assertIsInstance(result, int)
        self.assertIsInstance(report, list)
        self.assertGreater(len(report), 0)
        for entry in report:
            self.assertIsInstance(entry, tuple)
            self.assertEqual(len(entry), 2)
            label, status = entry
            self.assertIsInstance(label, str)
            self.assertIsInstance(status, str)

    def test_report_marks_winner(self):
        """The winning step's status must contain '(winner)' so the
        report is scannable. Stdin terminal.columns is the cheapest
        guaranteed-winning path to test this on."""
        from claude_statusline.cli import _detect_terminal_width_report
        _result, report = _detect_terminal_width_report({"terminal": {"columns": 165}})
        winner_entries = [s for _label, s in report if "(winner)" in s]
        self.assertEqual(len(winner_entries), 1,
            "exactly one step should be marked as the winner")
        self.assertIn("165", winner_entries[0])

    def test_thin_wrapper_unchanged_signature(self):
        """_detect_terminal_width(data) must still return a plain int
        — every existing caller relies on the int return shape. The
        refactor that added the report path must not have changed the
        public signature."""
        from claude_statusline.cli import _detect_terminal_width
        result = _detect_terminal_width({"terminal": {"columns": 165}})
        self.assertIsInstance(result, int)
        self.assertEqual(result, 165)
        # No-arg form must also still work (used by --doctor and the
        # historical fallback path).
        result_no_arg = _detect_terminal_width()
        self.assertIsInstance(result_no_arg, int)

    # --- Lying-signal regression tests --------------------------------
    #
    # These tests pin the generic "what if step N lies with a bogus
    # value" pattern. The 2.1.139 regression was specifically tput
    # returning 80, but the same shape of bug could appear at any
    # other probe step in the future. Each test below simulates one
    # probe returning a wildly wrong value and asserts the chain
    # rejects it (via the _TERM_WIDTH_MIN/_MAX range check or the
    # stub heuristic) rather than blindly trusting it.

    def test_shutil_get_terminal_size_columns_0_rejected(self):
        """shutil.get_terminal_size returning columns=0 (some
        misconfigured environments / future regressions) must be
        rejected by the range check, not accepted as a real width."""
        import claude_statusline.cli as cli_mod
        orig_shutil_gts = cli_mod.shutil.get_terminal_size
        cli_mod.shutil.get_terminal_size = lambda fallback=None: os.terminal_size((0, 0))
        try:
            result = cli_mod._detect_terminal_width({})
            self.assertNotEqual(result, 0,
                "shutil returning 0 must be rejected by the >= 20 range check; "
                "blindly accepting it would render an unusable layout")
            self.assertGreaterEqual(result, 20)
        finally:
            cli_mod.shutil.get_terminal_size = orig_shutil_gts

    def test_os_get_terminal_size_fd_columns_0_rejected(self):
        """os.get_terminal_size(fd) returning columns=0 (e.g., a
        closed pty that still claims to be a terminal) must be
        rejected. Forces the chain to fall through to the next step
        rather than render an unusable 0-col layout."""
        import claude_statusline.cli as cli_mod
        # Force shutil to return -1 (its sentinel "no TTY" value) so
        # we definitely reach the os.get_terminal_size step.
        orig_shutil_gts = cli_mod.shutil.get_terminal_size
        orig_os_gts = cli_mod.os.get_terminal_size
        # Restore COLUMNS too: module-level baseline at line 21 seeds
        # it; if we leak the pop here, every subsequent test in the
        # process runs without that baseline. Captured before pop,
        # restored in finally to keep cross-test ordering insensitive.
        saved_cols = os.environ.pop("COLUMNS", None)
        cli_mod.shutil.get_terminal_size = lambda fallback=None: os.terminal_size((-1, -1))
        cli_mod.os.get_terminal_size = lambda fd: os.terminal_size((0, 0))
        try:
            result = cli_mod._detect_terminal_width({})
            self.assertNotEqual(result, 0,
                "os.get_terminal_size returning 0 must be rejected; "
                "without the range check we would render an unusable layout")
            self.assertGreaterEqual(result, 20)
        finally:
            cli_mod.shutil.get_terminal_size = orig_shutil_gts
            cli_mod.os.get_terminal_size = orig_os_gts
            if saved_cols is not None:
                os.environ["COLUMNS"] = saved_cols

    def test_stty_returns_0_0_rejected_by_range_check(self):
        """If stty started returning '0 0' tomorrow (analogous to the
        2.1.139 tput stub but at a different layer), the result must
        be rejected. This is the generic test pattern that would have
        caught the original 2.1.139 regression if it had been in
        place."""
        import subprocess as subprocess_mod
        import claude_statusline.cli as cli_mod

        orig_run = subprocess_mod.run
        orig_open = __builtins__["open"] if isinstance(__builtins__, dict) else open

        class FakeTTY:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return ""
            def fileno(self): return 0

        def fake_run(cmd, *args, **kwargs):
            if cmd[0] == "stty":
                # The hypothetical future regression: stty returns 0 0
                # without erroring.
                return subprocess_mod.CompletedProcess(cmd, 0, "0 0\n", "")
            if cmd[0] == "tput":
                # Make tput also fail so we don't accidentally win there.
                return subprocess_mod.CompletedProcess(cmd, 1, "", "")
            return orig_run(cmd, *args, **kwargs)

        def fake_open(path, *args, **kwargs):
            if path == "/dev/tty":
                return FakeTTY()
            return orig_open(path, *args, **kwargs)

        cli_mod.subprocess.run = fake_run
        # Restore COLUMNS in finally — without this, the module-level
        # baseline at line 21 leaks and later tests run without it.
        saved_cols = os.environ.pop("COLUMNS", None)
        cli_builtins = cli_mod.__builtins__
        cli_open_was_dict = isinstance(cli_builtins, dict)
        cli_orig_open = (cli_builtins["open"] if cli_open_was_dict
                         else cli_builtins.open)
        try:
            if cli_open_was_dict:
                cli_builtins["open"] = fake_open
            else:
                cli_builtins.open = fake_open
            result, report = cli_mod._detect_terminal_width_report({})
        finally:
            cli_mod.subprocess.run = orig_run
            if cli_open_was_dict:
                cli_builtins["open"] = cli_orig_open
            else:
                cli_builtins.open = cli_orig_open
            if saved_cols is not None:
                os.environ["COLUMNS"] = saved_cols

        self.assertNotEqual(result, 0,
            "stty returning '0 0' must be rejected by the range check")
        # stty entry should record the rejection.
        stty_entries = [s for label, s in report if label == "stty size"]
        if stty_entries:
            # Only meaningful when the chain actually reached stty
            # (e.g., on Windows the /dev/tty fake-open might not take).
            self.assertTrue(
                any("out of range" in s or "rejected" in s
                    for s in stty_entries),
                "report must mark the 0 rejection so --doctor users "
                "can see the lie; got: {!r}".format(stty_entries))


class TestActivityCounter(unittest.TestCase):
    """Transcript-tail-read tool-call counter (the `activity` section).

    Reads the last _TRANSCRIPT_TAIL_BYTES of the JSONL transcript_path
    from stdin, counts tool_use blocks since the most recent user
    message, caches the result for _ACTIVITY_CACHE_TTL seconds. Hidden
    when count is zero so idle sessions show nothing.
    """

    def _write_transcript(self, lines):
        """Helper: write a JSONL transcript and return its path.

        Transcripts MUST live under ~/.claude/ for the realpath
        validation in get_session_activity_count to accept them.
        We create a temp subdirectory under ~/.claude/ and clean up
        at tearDown.
        """
        f = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".jsonl",
            delete=False, newline="", dir=self._test_dir,
        )
        for entry in lines:
            f.write(json.dumps(entry) + "\n")
        f.close()
        self._created_paths.append(f.name)
        return f.name

    def setUp(self):
        import shutil as shutil_mod
        from claude_statusline import sessions as sessions_mod
        self._shutil_mod = shutil_mod
        # Create a transient directory under ~/.claude/ so transcripts
        # written by tests pass the realpath validation. mkdir
        # _CLAUDE_DIR if missing — let any creation error surface as
        # a real test failure (silent skip would hide CI misconfig).
        os.makedirs(sessions_mod._CLAUDE_DIR, exist_ok=True)
        self._test_dir = tempfile.mkdtemp(
            prefix="claude-status-test-", dir=sessions_mod._CLAUDE_DIR,
        )
        self._created_paths = []
        # Clear the activity cache for each test so we don't get
        # cross-test contamination from the 5s TTL.
        try:
            cache_dir = sessions_mod._cache_dir()
            if os.path.isdir(cache_dir):
                for name in os.listdir(cache_dir):
                    if name.startswith("activity_"):
                        try:
                            os.remove(os.path.join(cache_dir, name))
                        except OSError:
                            pass
        except OSError:
            pass

    def tearDown(self):
        # shutil.rmtree (not os.rmdir) so the cleanup survives any
        # test that writes extra files into _test_dir without
        # registering them in _created_paths. ignore_errors=True
        # keeps a tearDown hiccup from masking a real test failure.
        self._shutil_mod.rmtree(self._test_dir, ignore_errors=True)

    # --- happy path ---------------------------------------------------

    def test_counts_tool_uses_since_last_user(self):
        from claude_statusline.sessions import _count_activity_from_transcript
        path = self._write_transcript([
            {"message": {"role": "user", "content": "first prompt"}},
            {"message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Bash"},
                {"type": "text", "text": "ok"},
            ]}},
            {"message": {"role": "user", "content": "second prompt"}},
            {"message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Read"},
                {"type": "tool_use", "name": "Edit"},
                {"type": "tool_use", "name": "Bash"},
            ]}},
        ])
        # Three tool uses in the most recent assistant turn; the one
        # before the second user message must NOT be counted.
        self.assertEqual(_count_activity_from_transcript(path), 3)

    def test_zero_when_no_tool_use_after_last_user(self):
        from claude_statusline.sessions import _count_activity_from_transcript
        path = self._write_transcript([
            {"message": {"role": "user", "content": "hi"}},
            {"message": {"role": "assistant", "content": [
                {"type": "text", "text": "hello"},
            ]}},
        ])
        self.assertEqual(_count_activity_from_transcript(path), 0)

    def test_zero_when_no_user_message_in_tail(self):
        """If our tail window doesn't reach back to a user message,
        return 0 rather than count the whole window as activity (which
        would be misleading — that activity belongs to a previous turn)."""
        from claude_statusline.sessions import _count_activity_from_transcript
        # Only assistant tool_uses, no user message at all → 0.
        path = self._write_transcript([
            {"message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Bash"},
            ]}},
        ])
        self.assertEqual(_count_activity_from_transcript(path), 0)

    # --- edge cases ---------------------------------------------------

    def test_path_missing(self):
        from claude_statusline.sessions import _count_activity_from_transcript
        self.assertEqual(
            _count_activity_from_transcript("/nonexistent/transcript.jsonl"), 0)

    def test_path_none(self):
        from claude_statusline.sessions import get_session_activity_count
        self.assertEqual(get_session_activity_count(None), 0)
        self.assertEqual(get_session_activity_count(""), 0)

    def test_path_non_string(self):
        from claude_statusline.sessions import get_session_activity_count
        for bad in (42, [], {}, True):
            self.assertEqual(get_session_activity_count(bad), 0,
                "non-string transcript_path={!r} must return 0, not crash".format(bad))

    def test_empty_file(self):
        from claude_statusline.sessions import _count_activity_from_transcript
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        f.close()
        self._created_paths.append(f.name)
        self.assertEqual(_count_activity_from_transcript(f.name), 0)

    def test_malformed_json_lines_skipped(self):
        """A garbled line in the middle must not abort parsing — skip
        it and continue counting the valid lines."""
        from claude_statusline.sessions import _count_activity_from_transcript
        path = self._write_transcript([
            {"message": {"role": "user", "content": "go"}},
        ])
        # Append a malformed line and another valid tool_use line.
        with open(path, "a", encoding="utf-8") as f:
            f.write("{this is not json\n")
            f.write(json.dumps({"message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Bash"},
            ]}}) + "\n")
        self.assertEqual(_count_activity_from_transcript(path), 1)

    def test_expanded_retry_when_initial_tail_misses_user(self):
        """When the cheap 64 KiB tail doesn't reach back to a user
        message, the function retries with the expanded 1 MiB cap.
        Real-world scenario: an assistant turn produced > 64 KiB of
        output (long tool_result block). Without the retry we'd
        return 0 and the activity counter would silently vanish
        mid-turn."""
        from claude_statusline.sessions import (
            _TRANSCRIPT_TAIL_BYTES,
            _count_activity_from_transcript,
        )
        # User message at start, then enough padding to push it well
        # beyond the 64 KiB initial cap but inside the 1 MiB expanded
        # cap, then a fresh tool_use.
        path = self._write_transcript([
            {"message": {"role": "user", "content": "go"}},
        ])
        padding_line = json.dumps({
            "message": {"role": "assistant", "content": [
                {"type": "text", "text": "x" * 1000},
            ]},
        }) + "\n"
        with open(path, "a", encoding="utf-8") as f:
            bytes_written = 0
            while bytes_written < _TRANSCRIPT_TAIL_BYTES + 10_000:
                f.write(padding_line)
                bytes_written += len(padding_line.encode("utf-8"))
            f.write(json.dumps({"message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Bash"},
            ]}}) + "\n")
        # Initial 64 KiB tail misses the user; expanded 1 MiB retry
        # finds it and counts the tool_use.
        self.assertEqual(_count_activity_from_transcript(path), 1,
            "expanded retry must find a user message in the 1 MiB window")

    def test_outer_envelope_role_schema_supported(self):
        """Some Claude Code schema versions put `role` at the outer
        envelope rather than under `message`. The fallback branch at
        sessions.py:_parse_transcript_tail must accept this shape.
        Without this test, that branch was dead code in the suite."""
        from claude_statusline.sessions import _count_activity_from_transcript
        # NOTE: write raw JSONL because _write_transcript wraps in
        # {"message": ...} which is the OTHER schema.
        path = self._write_transcript([])  # creates the file
        with open(path, "w", encoding="utf-8") as f:
            # Outer-envelope role: no 'message' wrapper.
            f.write(json.dumps({"role": "user", "content": "go"}) + "\n")
            f.write(json.dumps({"message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Bash"},
            ]}}) + "\n")
        self.assertEqual(_count_activity_from_transcript(path), 1,
            "outer-envelope role:user must be recognized as a user message")

    def test_consecutive_user_messages_use_most_recent(self):
        """Real sessions sometimes have adjacent user messages
        (system-injected reminders, retries). The walk-backwards
        loop must pick the MOST RECENT user message — counting only
        tool_uses after the LAST one, not the first."""
        from claude_statusline.sessions import _count_activity_from_transcript
        path = self._write_transcript([
            {"message": {"role": "user", "content": "first"}},
            {"message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Bash"},  # would be counted if we picked first user
                {"type": "tool_use", "name": "Read"},
            ]}},
            {"message": {"role": "user", "content": "second"}},
            {"message": {"role": "user", "content": "third"}},  # consecutive
            {"message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Edit"},  # only this counts
            ]}},
        ])
        self.assertEqual(_count_activity_from_transcript(path), 1,
            "consecutive user messages: count only from the most recent")

    def test_user_message_containing_literal_tool_use_text(self):
        """A user message body that contains the literal text
        '"tool_use"' (e.g., the user asking 'what does "tool_use"
        mean?') must NOT inflate the count. The cheap pre-filter
        admits it, but the JSON parse + structural check should
        exclude it."""
        from claude_statusline.sessions import _count_activity_from_transcript
        path = self._write_transcript([
            {"message": {"role": "user", "content": 'what is "tool_use" type?'}},
            {"message": {"role": "assistant", "content": [
                # A text block that mentions "tool_use" in its body.
                {"type": "text", "text": 'the "tool_use" type is a content block'},
            ]}},
        ])
        self.assertEqual(_count_activity_from_transcript(path), 0,
            "literal 'tool_use' text in message bodies must not inflate count")

    def test_path_is_directory_returns_zero(self):
        """transcript_path pointing at a directory (instead of a
        JSONL file) must return 0, not crash. Guards against an
        upstream that mistakenly sets transcript_path to the
        containing folder."""
        from claude_statusline.sessions import _count_activity_from_transcript
        # self._test_dir is a real directory under ~/.claude/ — passes
        # the realpath validation but isn't a file.
        self.assertEqual(_count_activity_from_transcript(self._test_dir), 0)

    def test_claude_dir_symlinked_paths_accepted(self):
        """When ~/.claude is itself a symlink to another location
        (common on macOS / NAS setups / users who symlink dotdirs),
        a legitimate transcript_path under ~/.claude/projects/...
        must still be accepted.

        Before the fix, _CLAUDE_DIR was unresolved (expanduser only)
        but transcript_path was compared via os.path.realpath, so the
        symlink-resolved real path didn't share the unresolved prefix
        and every transcript was silently rejected. Users in that
        layout would see `act:` permanently absent with no diagnostic.

        We can't easily symlink a real ~/.claude in a unit test, but
        we can verify the module-level _CLAUDE_DIR_REAL constant
        exists and equals the resolved form (the actual fix).
        """
        from claude_statusline import sessions as sessions_mod
        # The fix: _CLAUDE_DIR_REAL is the resolved form, used by
        # get_session_activity_count's prefix check.
        self.assertTrue(hasattr(sessions_mod, "_CLAUDE_DIR_REAL"),
            "fix introduces _CLAUDE_DIR_REAL — must exist at module level")
        # The resolved form must equal realpath of the unresolved form.
        self.assertEqual(sessions_mod._CLAUDE_DIR_REAL,
                         os.path.realpath(sessions_mod._CLAUDE_DIR))
        # Crucially: the get_session_activity_count validation must
        # check against _CLAUDE_DIR_REAL, not _CLAUDE_DIR. Pin via
        # source inspection so a future refactor that reverts to
        # _CLAUDE_DIR fails this test.
        import inspect
        source = inspect.getsource(sessions_mod.get_session_activity_count)
        self.assertIn("_CLAUDE_DIR_REAL", source,
            "get_session_activity_count must use _CLAUDE_DIR_REAL for "
            "the prefix check — using unresolved _CLAUDE_DIR breaks "
            "users whose ~/.claude is symlinked")

    def test_transcript_path_outside_claude_dir_rejected(self):
        """Defense in depth: transcript_path comes from external JSON.
        A path outside ~/.claude/ (whether by buggy upstream or
        symlink escape) must be rejected by get_session_activity_count
        before any open() is attempted.

        Even though the parse function tolerates arbitrary paths
        (returns 0 on any error), the caller-side validation is the
        security boundary that prevents read attempts on /etc/shadow
        and similar paths.
        """
        from claude_statusline.sessions import get_session_activity_count
        # Use a tempfile outside ~/.claude/ — the standard tmp dir.
        f = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".jsonl", delete=False)
        f.write(json.dumps({"message": {"role": "user", "content": "x"}}) + "\n")
        f.write(json.dumps({"message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Bash"},
        ]}}) + "\n")
        f.close()
        try:
            # If validation were missing, this would return 1.
            self.assertEqual(get_session_activity_count(f.name), 0,
                "transcript_path outside ~/.claude/ must be rejected by "
                "the realpath check, not silently read")
        finally:
            try:
                os.remove(f.name)
            except OSError:
                pass

    def test_small_file_no_user_has_distinct_status(self):
        """When the WHOLE file fits in the 64 KiB cap (no retry
        needed) and contains no user message, the status must say
        'in N byte file' — not the misleading '1 MiB tail' wording
        that would suggest we tried something we didn't."""
        from claude_statusline.sessions import _count_activity_with_status
        # Tiny file (~ a few hundred bytes) with no user message.
        path = self._write_transcript([
            {"message": {"role": "assistant", "content": [
                {"type": "text", "text": "hi"},
            ]}},
        ])
        count, status = _count_activity_with_status(path)
        self.assertEqual(count, 0)
        self.assertNotIn("1 MiB", status,
            "small-file no-user-found status must not falsely claim "
            "we tried a 1 MiB tail read; got: {!r}".format(status))
        self.assertIn("byte file", status,
            "small-file status should name the actual file size; "
            "got: {!r}".format(status))

    def test_count_with_status_disambiguates_zero(self):
        """_count_activity_with_status returns a (count, status)
        tuple so --doctor can distinguish:
          - legitimate idle (parsed OK, 0 tool_uses since last user)
          - transient failure (file missing / empty / stat error)
          - giving-up (turn larger than 1 MiB expanded window)

        Without this, the --doctor Transcript: block could not
        explain WHY the activity counter shows 0. Pin all three
        cases below."""
        from claude_statusline.sessions import _count_activity_with_status
        # Case 1: legitimate idle — file parses OK, no tool_uses.
        path = self._write_transcript([
            {"message": {"role": "user", "content": "go"}},
        ])
        count, status = _count_activity_with_status(path)
        self.assertEqual(count, 0)
        self.assertIn("parsed", status,
            "legitimate idle must report 'parsed' so --doctor users "
            "see the parse succeeded; got: {!r}".format(status))
        self.assertIn("0 tool_use", status)

        # Case 2: file missing — security check (path outside
        # ~/.claude/) would normally reject, but here we test the
        # parse function directly which only checks isfile.
        count, status = _count_activity_with_status(
            os.path.join(self._test_dir, "does-not-exist.jsonl"))
        self.assertEqual(count, 0)
        self.assertIn("missing", status,
            "missing file must produce a distinguishable status, not "
            "the same string as legitimate idle; got: {!r}".format(status))

    def test_gave_up_state_cached_to_avoid_repeated_1mib_reads(self):
        """When _count_activity_with_status returns the gave-up
        status (turn larger than 1 MiB), get_session_activity_count
        writes a separate long-TTL cache entry. Subsequent calls
        within that TTL must short-circuit without re-reading the
        1 MiB tail — verify by mutating the file and confirming the
        cached 0 still wins."""
        from claude_statusline.sessions import (
            _TRANSCRIPT_TAIL_BYTES_EXPANDED,
            get_session_activity_count,
        )
        # Construct a "gave up" file: user message at the start,
        # padding past the 1 MiB expanded cap, then a tool_use.
        path = self._write_transcript([
            {"message": {"role": "user", "content": "old"}},
        ])
        padding_line = json.dumps({
            "message": {"role": "assistant", "content": [
                {"type": "text", "text": "x" * 1000},
            ]},
        }) + "\n"
        with open(path, "a", encoding="utf-8") as f:
            bytes_written = 0
            while bytes_written < _TRANSCRIPT_TAIL_BYTES_EXPANDED + 10_000:
                f.write(padding_line)
                bytes_written += len(padding_line.encode("utf-8"))
            f.write(json.dumps({"message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Bash"},
            ]}}) + "\n")

        # First call: gave-up state, writes the gaveup cache entry.
        first = get_session_activity_count(path)
        self.assertEqual(first, 0,
            "huge-turn case must return 0 (no user message in window)")

        # Mutate the file to make a fresh user → tool_use pattern
        # near the end (would normally be detectable). The gaveup
        # cache must still return 0 — proves we did NOT re-read.
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"message": {"role": "user", "content": "next"}}) + "\n")
            f.write(json.dumps({"message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Read"},
            ]}}) + "\n")
        second = get_session_activity_count(path)
        self.assertEqual(second, 0,
            "gave-up cache must short-circuit subsequent calls within TTL — "
            "without it we would re-read 1 MiB on every render of a stuck turn")

    def test_zero_counts_not_cached(self):
        """A zero count can mean 'no activity' OR 'parse failed,
        transient file issue.' Caching zero would suppress recovery
        for the full 5s TTL. Verify zero is NOT cached: an empty
        file (returns 0) followed by a populated state (returns >0)
        must show the new count immediately, not a stale 0."""
        from claude_statusline.sessions import get_session_activity_count
        # Create a file that initially has no tool_use after the user.
        path = self._write_transcript([
            {"message": {"role": "user", "content": "go"}},
        ])
        first = get_session_activity_count(path)
        self.assertEqual(first, 0)
        # Append a tool_use right after — without TTL expiry, a cached
        # 0 would still be returned. With our non-zero-cache fix, the
        # function should re-read and find the new tool_use.
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Bash"},
            ]}}) + "\n")
        second = get_session_activity_count(path)
        self.assertEqual(second, 1,
            "zero result must NOT be cached — recovery should be immediate, "
            "not blocked behind the 5s TTL")

    def test_returns_zero_when_turn_exceeds_expanded_cap(self):
        """When even the expanded 1 MiB retry can't find a user
        message, we return 0 — this is the genuine giving-up case
        for pathologically large single turns. Prevents misleading
        counts of activity from a previous turn."""
        from claude_statusline.sessions import (
            _TRANSCRIPT_TAIL_BYTES_EXPANDED,
            _count_activity_from_transcript,
        )
        path = self._write_transcript([
            {"message": {"role": "user", "content": "old"}},
        ])
        padding_line = json.dumps({
            "message": {"role": "assistant", "content": [
                {"type": "text", "text": "x" * 1000},
            ]},
        }) + "\n"
        with open(path, "a", encoding="utf-8") as f:
            bytes_written = 0
            # Push the user message past the 1 MiB expanded cap.
            while bytes_written < _TRANSCRIPT_TAIL_BYTES_EXPANDED + 10_000:
                f.write(padding_line)
                bytes_written += len(padding_line.encode("utf-8"))
            f.write(json.dumps({"message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Bash"},
            ]}}) + "\n")
        self.assertEqual(_count_activity_from_transcript(path), 0,
            "even the expanded retry cannot reach the user — return 0 rather "
            "than misleadingly count a previous turn's activity")

    def test_partial_first_line_discarded(self):
        """When reading from a tail offset (start > 0), the first line
        of the chunk may be partial — must be discarded, not parsed."""
        from claude_statusline.sessions import (
            _TRANSCRIPT_TAIL_BYTES,
            _count_activity_from_transcript,
        )
        # Construct a file where the byte at _TRANSCRIPT_TAIL_BYTES
        # offset from EOF falls in the middle of a JSON object.
        path = self._write_transcript([
            {"message": {"role": "user", "content": "go"}},
        ])
        # Pad so that the tail window starts mid-line of an earlier
        # entry. The first read line will be malformed JSON that the
        # discard logic must drop without erroring.
        with open(path, "a", encoding="utf-8") as f:
            # Single very long line larger than the tail cap.
            big = "x" * (_TRANSCRIPT_TAIL_BYTES + 5000)
            f.write(json.dumps({
                "message": {"role": "assistant", "content": [
                    {"type": "text", "text": big},
                ]},
            }) + "\n")
            f.write(json.dumps({"message": {"role": "user", "content": "next"}}) + "\n")
            f.write(json.dumps({"message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Bash"},
                {"type": "tool_use", "name": "Read"},
            ]}}) + "\n")
        # Must not crash on the partial first line; must find the user
        # message that's whole inside the tail; must count 2 tool_uses.
        result = _count_activity_from_transcript(path)
        self.assertEqual(result, 2)

    # --- caching ------------------------------------------------------

    def test_result_cached(self):
        """A second call within TTL must hit cache (not re-read file).
        Verify by mutating the file between calls and confirming the
        second call returns the stale value."""
        from claude_statusline.sessions import get_session_activity_count
        path = self._write_transcript([
            {"message": {"role": "user", "content": "go"}},
            {"message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Bash"},
            ]}},
        ])
        first = get_session_activity_count(path)
        self.assertEqual(first, 1)
        # Mutate the file to have 5 tool_uses — but cache should still
        # return 1 because the TTL hasn't expired.
        with open(path, "a", encoding="utf-8") as f:
            for _ in range(4):
                f.write(json.dumps({"message": {"role": "assistant", "content": [
                    {"type": "tool_use", "name": "Bash"},
                ]}}) + "\n")
        second = get_session_activity_count(path)
        self.assertEqual(second, 1, "must return cached value within TTL")

    # --- end-to-end render --------------------------------------------

    def test_activity_section_renders(self):
        """Enabling the activity section produces 'act:N' in output
        when count > 0."""
        import claude_statusline.cli as cli_mod
        from claude_statusline.themes import THEMES

        path = self._write_transcript([
            {"message": {"role": "user", "content": "go"}},
            {"message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Bash"},
                {"type": "tool_use", "name": "Read"},
            ]}},
        ])

        orig_line2 = THEMES["default"]["line2"]
        orig_branch = cli_mod.get_branch
        cli_mod.get_branch = lambda: "main"
        try:
            THEMES["default"]["line2"] = ["activity", "branch"]
            data = {
                "transcript_path": path,
                "git_branch": "main",
            }
            output = cli_mod.render(data, "default")
            plain = re.sub(r"\x1b\[[0-9;]*m", "", output)
            self.assertIn("act:", plain,
                "activity section must render 'act:' label")
            self.assertIn("2", plain,
                "activity section must render the count value")
        finally:
            THEMES["default"]["line2"] = orig_line2
            cli_mod.get_branch = orig_branch

    def test_activity_section_hidden_when_zero(self):
        """Idle session (no tool calls in current turn) → section absent."""
        import claude_statusline.cli as cli_mod
        from claude_statusline.themes import THEMES

        path = self._write_transcript([
            {"message": {"role": "user", "content": "go"}},
            {"message": {"role": "assistant", "content": [
                {"type": "text", "text": "no tools"},
            ]}},
        ])

        orig_line2 = THEMES["default"]["line2"]
        orig_branch = cli_mod.get_branch
        cli_mod.get_branch = lambda: "main"
        try:
            THEMES["default"]["line2"] = ["activity", "branch"]
            data = {"transcript_path": path, "git_branch": "main"}
            output = cli_mod.render(data, "default")
            self.assertNotIn("act:", output,
                "activity must be silent when no tool calls in current turn")
        finally:
            THEMES["default"]["line2"] = orig_line2
            cli_mod.get_branch = orig_branch

    def test_render_with_missing_transcript_path(self):
        """A session without transcript_path on stdin must not crash —
        the activity section just doesn't render."""
        import claude_statusline.cli as cli_mod
        from claude_statusline.themes import THEMES

        orig_line2 = THEMES["default"]["line2"]
        orig_branch = cli_mod.get_branch
        cli_mod.get_branch = lambda: "main"
        try:
            THEMES["default"]["line2"] = ["activity", "branch"]
            data = {"git_branch": "main"}  # no transcript_path
            output = cli_mod.render(data, "default")
            self.assertNotIn("act:", output)
            self.assertIn("main", output, "rest of the line must still render")
        finally:
            THEMES["default"]["line2"] = orig_line2
            cli_mod.get_branch = orig_branch


class TestClaudeStatuslineWidthOverride(unittest.TestCase):
    """CLAUDE_STATUSLINE_WIDTH env var as the explicit user override.

    Tracked at issue #89. Highest priority in the width-detection
    chain — when a user sets this, they have decided detection is
    unreliable or want to force a specific width. Out-of-range and
    non-numeric values must fall through (silent ignore) to keep
    backward compatibility.
    """

    def setUp(self):
        self._old_override = os.environ.pop("CLAUDE_STATUSLINE_WIDTH", None)
        self._old_cols = os.environ.pop("COLUMNS", None)

    def tearDown(self):
        if self._old_override is not None:
            os.environ["CLAUDE_STATUSLINE_WIDTH"] = self._old_override
        else:
            os.environ.pop("CLAUDE_STATUSLINE_WIDTH", None)
        if self._old_cols is not None:
            os.environ["COLUMNS"] = self._old_cols

    def test_override_wins_over_stdin_terminal_columns(self):
        """Explicit user override beats stdin.terminal.columns (which
        is itself the top-priority auto-detection signal). Users
        setting this env var have decided they know better than every
        other source — honor that."""
        from claude_statusline.cli import _detect_terminal_width
        os.environ["CLAUDE_STATUSLINE_WIDTH"] = "165"
        # Even with stdin terminal.columns present, override wins.
        result = _detect_terminal_width({"terminal": {"columns": 300}})
        self.assertEqual(result, 165)

    def test_override_wins_over_columns_env(self):
        """When both CLAUDE_STATUSLINE_WIDTH and COLUMNS are set,
        the dedicated override wins. Avoids ambiguity about which
        env var was intended."""
        from claude_statusline.cli import _detect_terminal_width
        os.environ["CLAUDE_STATUSLINE_WIDTH"] = "200"
        os.environ["COLUMNS"] = "100"
        result = _detect_terminal_width({})
        self.assertEqual(result, 200)

    def test_garbage_override_falls_through(self):
        """Non-numeric override must not crash and must not block
        auto-detection — fall through to existing chain. Otherwise
        a typo (`CLAUDE_STATUSLINE_WIDTH=wide`) would silently force
        the safe-default layout."""
        from claude_statusline.cli import _detect_terminal_width
        os.environ["CLAUDE_STATUSLINE_WIDTH"] = "wide"
        os.environ["COLUMNS"] = "150"  # auto-detection should win
        result = _detect_terminal_width({})
        self.assertEqual(result, 150,
            "garbage override must fall through to COLUMNS, not be honored")

    def test_out_of_range_override_falls_through(self):
        """Override outside [_TERM_WIDTH_MIN, _TERM_WIDTH_MAX] is
        rejected — same as other steps in the chain. Otherwise a
        finger-fumble like `CLAUDE_STATUSLINE_WIDTH=99999` would
        force a layout that overflows every screen."""
        from claude_statusline.cli import _detect_terminal_width
        os.environ["COLUMNS"] = "120"
        for bad in ("0", "10", "5000"):
            os.environ["CLAUDE_STATUSLINE_WIDTH"] = bad
            result = _detect_terminal_width({})
            self.assertEqual(result, 120,
                "out-of-range override {!r} must fall through".format(bad))

    def test_override_reported_distinctly_in_report(self):
        """--doctor must show the override prominently when set so
        users debugging width can see whether their env var is the
        active source."""
        from claude_statusline.cli import _detect_terminal_width_report
        os.environ["CLAUDE_STATUSLINE_WIDTH"] = "200"
        _result, report = _detect_terminal_width_report({})
        # The override step must appear first in the report so users
        # scanning --doctor output see it before the auto-detection
        # noise.
        self.assertEqual(report[0][0], "CLAUDE_STATUSLINE_WIDTH env",
            "override step must be first in the report")
        self.assertIn("winner", report[0][1])
        self.assertIn("explicit override", report[0][1],
            "report must label the override as explicit so users "
            "understand it's not auto-detection")

    def test_override_unset_reports_unset(self):
        """When the override is unset (the normal case), the report
        must say 'unset' rather than silently omit the step. Keeps
        --doctor output predictable across versions."""
        from claude_statusline.cli import _detect_terminal_width_report
        os.environ.pop("CLAUDE_STATUSLINE_WIDTH", None)
        _result, report = _detect_terminal_width_report({})
        override_entries = [s for label, s in report if label == "CLAUDE_STATUSLINE_WIDTH env"]
        self.assertEqual(override_entries, ["unset"])

    def test_override_empty_string_reports_distinctly_from_unset(self):
        """`export CLAUDE_STATUSLINE_WIDTH=` (empty string) is the
        standard way users clear an override in their shell. Reporting
        it as 'not an int — rejected' would confuse debugging. Report
        as 'empty — treating as unset' to keep the trail clean."""
        from claude_statusline.cli import _detect_terminal_width_report
        os.environ["CLAUDE_STATUSLINE_WIDTH"] = ""
        _result, report = _detect_terminal_width_report({})
        override_entries = [s for label, s in report if label == "CLAUDE_STATUSLINE_WIDTH env"]
        self.assertEqual(len(override_entries), 1)
        self.assertIn("empty", override_entries[0],
            "empty string must report distinctly so users see what's happening")
        self.assertIn("unset", override_entries[0],
            "must indicate the behavior is the same as if unset")

    def test_override_beats_tput_stub_heuristic(self):
        """Explicit user intent (CLAUDE_STATUSLINE_WIDTH=80) must
        beat the v0.6.0 tput-stub-80 rejection heuristic. A user on
        a real 80-col terminal who manually sets the override is
        explicitly telling us "yes, 80 is correct" — we must not
        silently reject their choice via the auto-detection heuristic.

        Without this test, a future refactor that adds "reject 80
        everywhere" would silently break the documented override
        contract for real 80-col users."""
        from claude_statusline.cli import _detect_terminal_width
        os.environ["CLAUDE_STATUSLINE_WIDTH"] = "80"
        # Even if every other signal in the chain would be rejected
        # as a stub, the explicit override wins at step 1.
        self.assertEqual(_detect_terminal_width({}), 80,
            "explicit CLAUDE_STATUSLINE_WIDTH=80 must beat the tput stub "
            "heuristic — user intent overrides auto-detection guards")


class TestAgentNameNormalization(unittest.TestCase):
    """The `agent` section reads stdin `agent.name` to display the
    current subagent identity. Tracked at issue #88.

    Previously the normalization used `data.get("agent") or {}` which
    crashed silently when upstream sent `agent` as a non-dict (string,
    list, int) — the resulting AttributeError on .get() was caught by
    the outer try/except but the section never rendered. These tests
    pin the isinstance-guarded shape.
    """

    def test_nested_agent_name_extracted(self):
        from claude_statusline.cli import _normalize
        n = _normalize({"agent": {"name": "Explore"}, "session_id": "x"})
        self.assertEqual(n["agent_name"], "Explore")

    def test_flat_agent_name_fallback(self):
        """Demo mode and older schemas use flat agent_name."""
        from claude_statusline.cli import _normalize
        n = _normalize({"agent_name": "CodeReviewer", "session_id": "x"})
        self.assertEqual(n["agent_name"], "CodeReviewer")

    def test_nested_wins_over_flat(self):
        """Real stdin schema is nested. If both are present, prefer it."""
        from claude_statusline.cli import _normalize
        n = _normalize({
            "agent": {"name": "Nested"},
            "agent_name": "Flat",
            "session_id": "x",
        })
        self.assertEqual(n["agent_name"], "Nested")

    def test_agent_as_string_does_not_crash(self):
        """Pre-fix: this raised AttributeError on .get(). The outer
        try/except masked it as 'section just didn't render.' Now
        the isinstance guard catches it cleanly."""
        from claude_statusline.cli import _normalize
        n = _normalize({"agent": "Explore", "session_id": "x"})
        # String at the outer key isn't a recognized shape — section absent.
        self.assertIsNone(n["agent_name"])

    def test_agent_as_list_does_not_crash(self):
        from claude_statusline.cli import _normalize
        n = _normalize({"agent": ["Explore"], "session_id": "x"})
        self.assertIsNone(n["agent_name"])

    def test_agent_name_as_non_string_rejected(self):
        """If nested agent.name arrives as a non-string (int, list),
        reject it rather than render the wrong type."""
        from claude_statusline.cli import _normalize
        for bad in (42, ["Explore"], {"nested": "deep"}, True):
            n = _normalize({"agent": {"name": bad}, "session_id": "x"})
            self.assertIsNone(n["agent_name"],
                "agent.name={!r} must be rejected as non-string".format(bad))

    def test_empty_agent_name_rejected(self):
        """Empty string is not a useful chip — hide the section."""
        from claude_statusline.cli import _normalize
        n = _normalize({"agent": {"name": ""}, "session_id": "x"})
        self.assertIsNone(n["agent_name"])

    def test_agent_absent_returns_none(self):
        from claude_statusline.cli import _normalize
        n = _normalize({"session_id": "x"})
        self.assertIsNone(n["agent_name"])

    def test_empty_nested_string_falls_back_to_flat(self):
        """Regression test: a buggy upstream emitting an empty
        `agent.name = ""` must NOT block the flat `agent_name`
        fallback. The first attempt at #88 had this bug — empty
        string is a string, so the isinstance check accepted it
        and `flat_name` was dropped. Real users with flat
        `agent_name` set would have silently lost their chip."""
        from claude_statusline.cli import _normalize
        n = _normalize({
            "agent": {"name": ""},
            "agent_name": "Explorer",
            "session_id": "x",
        })
        self.assertEqual(n["agent_name"], "Explorer",
            "empty nested string must fall through to flat agent_name; "
            "blocking the fallback would be a regression from the original "
            "`agent_obj.get('name') or data.get('agent_name')` behavior")

    def test_agent_explicit_none_safe(self):
        """data['agent'] = None (explicit None vs absent) must not crash."""
        from claude_statusline.cli import _normalize
        n = _normalize({"agent": None, "session_id": "x"})
        self.assertIsNone(n["agent_name"])

    def test_agent_explicit_empty_dict_safe(self):
        """data['agent'] = {} (explicit empty dict) must not crash."""
        from claude_statusline.cli import _normalize
        n = _normalize({"agent": {}, "session_id": "x"})
        self.assertIsNone(n["agent_name"])

    def test_vim_as_non_dict_does_not_crash(self):
        """Same isinstance-guard regression test for vim as for
        agent/worktree/cost. Flagged by Gemini on PR #90 as
        pre-existing exposure of the same bug pattern. An upstream
        sending `vim: "NORMAL"` as a string (or any non-dict) must
        not crash _normalize."""
        from claude_statusline.cli import _normalize
        for bad in ("NORMAL", ["NORMAL"], 42, True):
            n = _normalize({"vim": bad, "session_id": "x"})
            # vim_mode falls back to the flat `data.get("vim_mode")`,
            # which is None — section absent.
            self.assertIsNone(n["vim_mode"],
                "vim={!r} must be rejected as non-dict without crashing".format(bad))

    def test_vim_nested_dict_still_works(self):
        """The isinstance fix must not have broken the legitimate
        nested-dict path."""
        from claude_statusline.cli import _normalize
        n = _normalize({"vim": {"mode": "INSERT"}, "session_id": "x"})
        self.assertEqual(n["vim_mode"], "INSERT")

    def test_agent_section_renders_with_nested_name(self):
        """End-to-end: when stdin contains nested agent.name, the
        chip renders correctly. The default theme already includes
        the `agent` section in line2."""
        import claude_statusline.cli as cli_mod
        from claude_statusline.themes import THEMES
        orig_line2 = THEMES["default"]["line2"]
        orig_branch = cli_mod.get_branch
        cli_mod.get_branch = lambda: "main"
        try:
            THEMES["default"]["line2"] = ["agent", "branch"]
            data = {"agent": {"name": "Explore"}, "git_branch": "main"}
            output = cli_mod.render(data, "default")
            plain = re.sub(r"\x1b\[[0-9;]*m", "", output)
            self.assertIn("[Explore]", plain,
                "agent section must render '[Name]' when stdin has agent.name")
        finally:
            THEMES["default"]["line2"] = orig_line2
            cli_mod.get_branch = orig_branch


class TestGitHubPRSection(unittest.TestCase):
    """Claude Code v2.1.148+ adds `github.{repo, pr_number, pr_url}`
    to stdin. Tracked at issue #87. The `pr` section renders the PR
    number as a clickable link to pr_url when available."""

    def test_pr_number_extracted_from_nested_github(self):
        from claude_statusline.cli import _normalize
        n = _normalize({
            "github": {"pr_number": 1234, "pr_url": "https://github.com/x/y/pull/1234"},
            "session_id": "x",
        })
        self.assertEqual(n["github_pr_number"], 1234)
        self.assertEqual(n["github_pr_url"], "https://github.com/x/y/pull/1234")

    def test_pr_number_as_string_coerced(self):
        """JSON serializers sometimes stringify integers; accept that."""
        from claude_statusline.cli import _normalize
        n = _normalize({"github": {"pr_number": "42"}, "session_id": "x"})
        self.assertEqual(n["github_pr_number"], 42)

    def test_pr_number_garbage_rejected(self):
        from claude_statusline.cli import _normalize
        for bad in ("not a number", -1, 0, [42], {"nested": 1}):
            n = _normalize({"github": {"pr_number": bad}, "session_id": "x"})
            self.assertIsNone(n["github_pr_number"],
                "pr_number={!r} must be rejected".format(bad))

    def test_github_field_absent(self):
        """Older Claude Code clients don't send `github` — fields stay None."""
        from claude_statusline.cli import _normalize
        n = _normalize({"session_id": "x"})
        self.assertIsNone(n["github_pr_number"])
        self.assertIsNone(n["github_pr_url"])
        self.assertIsNone(n["github_repo"])

    def test_github_as_non_dict_does_not_crash(self):
        from claude_statusline.cli import _normalize
        for bad in ("repo-name", 42, ["pr1234"], True):
            n = _normalize({"github": bad, "session_id": "x"})
            self.assertIsNone(n["github_pr_number"],
                "github={!r} must be rejected without crashing".format(bad))

    def test_pr_url_must_be_string(self):
        """A non-string pr_url must not become a malformed OSC 8 link."""
        from claude_statusline.cli import _normalize
        n = _normalize({"github": {"pr_url": 42}, "session_id": "x"})
        self.assertIsNone(n["github_pr_url"])

    def test_pr_section_renders(self):
        """End-to-end: opt-in `pr` section renders PR#NN when stdin
        has github.pr_number."""
        import claude_statusline.cli as cli_mod
        from claude_statusline.themes import THEMES
        orig_line2 = THEMES["default"]["line2"]
        orig_branch = cli_mod.get_branch
        cli_mod.get_branch = lambda: "main"
        try:
            THEMES["default"]["line2"] = ["pr", "branch"]
            data = {
                "github": {"pr_number": 86, "pr_url": "https://github.com/x/y/pull/86"},
                "git_branch": "main",
            }
            output = cli_mod.render(data, "default")
            plain = re.sub(r"\x1b\[[0-9;]*m", "", output)
            # OSC 8 links inject hyperlink escapes too; strip those.
            plain = re.sub(r"\x1b\]8;;[^\x07\x1b]*(?:\x07|\x1b\\)", "", plain)
            self.assertIn("PR#86", plain,
                "pr section must render 'PR#NN' when github.pr_number is present")
        finally:
            THEMES["default"]["line2"] = orig_line2
            cli_mod.get_branch = orig_branch

    def test_pr_url_with_control_bytes_rejected_in_osc8(self):
        """`_osc8_link` must reject any URL containing C0 control
        bytes — they would break OUT of the OSC 8 escape envelope
        and inject arbitrary terminal sequences. Defense against an
        attacker-controlled stdin field corrupting the terminal.

        Tests the sanitization in _osc8_link directly. The wrapped
        text MUST equal the input text (no escape sequences added)
        when the URL contains malicious bytes."""
        from claude_statusline.cli import _osc8_link
        from claude_statusline import sessions as sessions_mod

        # Force clickable_links enabled so we exercise the wrap path.
        orig_get = sessions_mod.get_clickable_links_enabled
        sessions_mod.get_clickable_links_enabled = lambda: True
        # Also patch the import in cli module
        import claude_statusline.cli as cli_mod
        orig_cli_get = cli_mod.get_clickable_links_enabled
        cli_mod.get_clickable_links_enabled = lambda: True
        try:
            # Each of these bytes can break the OSC 8 envelope.
            malicious_urls = [
                "https://example.com/\x07evil",   # BEL terminates OSC
                "https://example.com/\x1b]evil",  # ESC starts new escape
                "https://example.com/\x9cevil",   # ST (C1 string terminator)
                "https://example.com/\x00evil",   # NUL
                "https://example.com/\n",         # newline splits line
                "https://example.com/\r",         # CR
            ]
            for url in malicious_urls:
                result = _osc8_link(url, "PR#86")
                # If sanitization works, result is the plain text —
                # no escape bytes were added.
                self.assertEqual(result, "PR#86",
                    "URL with control byte must NOT be wrapped in OSC 8; "
                    "got: {!r}".format(result))
                self.assertNotIn("\x1b]8", result,
                    "no OSC 8 sequence should be emitted for malicious URL")

            # Sanity check: a clean URL DOES get wrapped.
            clean = _osc8_link("https://example.com/pr/86", "PR#86")
            self.assertIn("\x1b]8;;https://example.com/pr/86", clean,
                "clean URL must still be wrapped — sanitizer must not "
                "reject legitimate inputs")
        finally:
            sessions_mod.get_clickable_links_enabled = orig_get
            cli_mod.get_clickable_links_enabled = orig_cli_get

    def test_pr_number_implausibly_large_rejected(self):
        """An implausibly large pr_number (7+ digits) would dominate
        Line 2 width and probably indicates corrupted upstream data.
        Reject in normalization so the section silently hides."""
        from claude_statusline.cli import _normalize
        for huge in (1_000_000, 99_999_999, 10**18):
            n = _normalize({"github": {"pr_number": huge}, "session_id": "x"})
            self.assertIsNone(n["github_pr_number"],
                "pr_number={} must be rejected as implausible".format(huge))

        # Just below the cap is accepted.
        n = _normalize({"github": {"pr_number": 999_999}, "session_id": "x"})
        self.assertEqual(n["github_pr_number"], 999_999)

    def test_pr_section_hidden_without_pr(self):
        """No PR number → section absent, no leftover label."""
        import claude_statusline.cli as cli_mod
        from claude_statusline.themes import THEMES
        orig_line2 = THEMES["default"]["line2"]
        orig_branch = cli_mod.get_branch
        cli_mod.get_branch = lambda: "main"
        try:
            THEMES["default"]["line2"] = ["pr", "branch"]
            output = cli_mod.render({"git_branch": "main"}, "default")
            self.assertNotIn("PR#", output)
            self.assertNotIn("PR:", output)
        finally:
            THEMES["default"]["line2"] = orig_line2
            cli_mod.get_branch = orig_branch


class TestPRReviewState(unittest.TestCase):
    """`pr.review_state` (documented stdin enum: approved / pending /
    changes_requested / draft) is captured since v0.6.3 and rendered as
    a short ASCII token appended to the PR section. Hidden when absent or
    malformed — the section degrades to bare PR#NN."""

    def _plain(self, output):
        no_ansi = re.sub(r"\x1b\[[0-9;]*m", "", output)
        return re.sub(r"\x1b\]8;;[^\x07\x1b]*(?:\x07|\x1b\\)", "", no_ansi)

    def _render_with_pr(self, review_state):
        import claude_statusline.cli as cli_mod
        from claude_statusline.themes import THEMES
        orig_line2 = THEMES["default"]["line2"]
        orig_branch = cli_mod.get_branch
        cli_mod.get_branch = lambda: "main"
        try:
            THEMES["default"]["line2"] = ["pr", "branch"]
            pr = {"number": 86, "url": "https://github.com/x/y/pull/86"}
            if review_state is not _SENTINEL:
                pr["review_state"] = review_state
            return self._plain(cli_mod.render(
                {"pr": pr, "git_branch": "main"}, "default"))
        finally:
            THEMES["default"]["line2"] = orig_line2
            cli_mod.get_branch = orig_branch

    def test_normalize_accepts_documented_states(self):
        from claude_statusline.cli import _normalize
        for state in ("approved", "pending", "changes_requested", "draft"):
            n = _normalize({"pr": {"number": 1, "review_state": state},
                            "session_id": "x"})
            self.assertEqual(n["pr_review_state"], state)

    def test_normalize_case_insensitive(self):
        """Production lower-cases before the enum check — parity with
        effort.level. Covers the multi-word `changes_requested` form
        too, so the underscore survives case-folding."""
        from claude_statusline.cli import _normalize
        for raw, want in (("APPROVED", "approved"),
                          ("Changes_Requested", "changes_requested"),
                          ("Pending", "pending"),
                          ("DRAFT", "draft")):
            n = _normalize({"pr": {"number": 1, "review_state": raw},
                            "session_id": "x"})
            self.assertEqual(n["pr_review_state"], want,
                "{!r} must normalize to {!r}".format(raw, want))

    def test_normalize_rejects_unknown_and_nonstring(self):
        from claude_statusline.cli import _normalize
        for bad in ("merged", "", 42, ["approved"], {"x": 1}, True, None):
            n = _normalize({"pr": {"number": 1, "review_state": bad},
                            "session_id": "x"})
            self.assertIsNone(n["pr_review_state"],
                "review_state={!r} must normalize to None".format(bad))

    def test_render_each_state_token(self):
        for state, token in (("approved", "ok"),
                             ("changes_requested", "chg"),
                             ("pending", "rev"),
                             ("draft", "draft")):
            plain = self._render_with_pr(state)
            self.assertIn("PR#86", plain)
            self.assertIn("PR#86 {}".format(token), plain,
                "state {!r} should render token {!r}".format(state, token))

    def test_render_bare_pr_when_state_absent_or_bad(self):
        for bad in (_SENTINEL, "merged", 42, None):
            plain = self._render_with_pr(bad)
            self.assertIn("PR#86", plain)
            # No stray review token should follow the PR number.
            for token in ("ok", "chg", "rev", "draft"):
                self.assertNotIn("PR#86 {}".format(token), plain,
                    "bad/absent state {!r} must not render {!r}".format(
                        bad, token))

    def test_display_map_stays_in_sync_with_enum(self):
        """The render map keys MUST equal the validated enum — a state
        added to one but not the other would either crash the KeyError
        lookup in render or silently drop a valid value."""
        from claude_statusline.cli import (
            _PR_REVIEW_STATES, _PR_REVIEW_DISPLAY)
        self.assertEqual(set(_PR_REVIEW_DISPLAY), set(_PR_REVIEW_STATES))

    def _render_raw_with_pr(self, review_state, color_overrides):
        """Render with `pr` enabled and the given theme color overrides,
        returning the RAW (un-stripped) output so callers can assert on
        the actual ANSI color codes wrapping the review token."""
        import claude_statusline.cli as cli_mod
        from claude_statusline.themes import THEMES
        orig_line2 = THEMES["default"]["line2"]
        orig_colors = THEMES["default"]["colors"]
        orig_branch = cli_mod.get_branch
        cli_mod.get_branch = lambda: "main"
        try:
            THEMES["default"]["line2"] = ["pr", "branch"]
            THEMES["default"]["colors"] = dict(orig_colors)
            THEMES["default"]["colors"].update(color_overrides)
            pr = {"number": 86, "url": "https://github.com/x/y/pull/86",
                  "review_state": review_state}
            return cli_mod.render({"pr": pr, "git_branch": "main"}, "default")
        finally:
            THEMES["default"]["line2"] = orig_line2
            THEMES["default"]["colors"] = orig_colors
            cli_mod.get_branch = orig_branch

    def test_per_state_color_override_applied(self):
        """The per-state theme key `pr_review_<state>` actually colors
        the token — assert the override ANSI code wraps it, not just that
        the token text appears."""
        raw = self._render_raw_with_pr("approved",
                                       {"pr_review_approved": CYAN})
        self.assertIn(CYAN + "ok" + RESET, raw,
            "pr_review_approved override must wrap the 'ok' token in CYAN")

    def test_per_state_color_null_falls_through_to_default(self):
        """An explicit `null` override must fall through `_first()` to the
        built-in default color (RED for changes_requested) and NOT crash
        colorize() — the theme-null degradation contract the project
        guards elsewhere."""
        raw = self._render_raw_with_pr(
            "changes_requested", {"pr_review_changes_requested": None})
        self.assertIn(RED + "chg" + RESET, raw,
            "null override must fall through to the default RED, not crash")

    def test_pr_is_compact_droppable(self):
        """`pr` must shed under width pressure before essential sections.
        Pins membership in _COMPACT_DROP (which feeds both _NARROW_DROP
        and _FIT_DROP_PRIORITY) so a refactor can't silently break the
        documented 'sheds first' contract."""
        from claude_statusline.cli import (
            _COMPACT_DROP, _NARROW_DROP, _FIT_DROP_PRIORITY)
        self.assertIn("pr", _COMPACT_DROP)
        self.assertIn("pr", _NARROW_DROP)
        self.assertIn("pr", _FIT_DROP_PRIORITY)


class TestThinkingSection(unittest.TestCase):
    """`thinking.enabled` (documented stdin boolean) renders a `think`
    badge ONLY when strictly True. Off / absent / malformed all hide it —
    an off-indicator would be noise on every non-thinking session."""

    def _plain(self, output):
        return re.sub(r"\x1b\[[0-9;]*m", "", output)

    def _shows_think(self, thinking_value):
        import claude_statusline.cli as cli_mod
        from claude_statusline.themes import THEMES
        orig_line2 = THEMES["default"]["line2"]
        orig_branch = cli_mod.get_branch
        cli_mod.get_branch = lambda: "main"
        try:
            THEMES["default"]["line2"] = ["thinking", "branch"]
            data = {"git_branch": "main"}
            if thinking_value is not _SENTINEL:
                data["thinking"] = thinking_value
            return "think" in self._plain(cli_mod.render(data, "default"))
        finally:
            THEMES["default"]["line2"] = orig_line2
            cli_mod.get_branch = orig_branch

    def test_normalize_true_only(self):
        from claude_statusline.cli import _normalize
        self.assertTrue(
            _normalize({"thinking": {"enabled": True}, "session_id": "x"})
            ["thinking_enabled"])
        for falsey in ({"enabled": False}, {"enabled": 1}, {"enabled": "yes"},
                       {}, "on", 42, ["enabled"], None):
            n = _normalize({"thinking": falsey, "session_id": "x"})
            self.assertIs(n["thinking_enabled"], False,
                "thinking={!r} must normalize to False".format(falsey))

    def test_renders_only_when_enabled(self):
        self.assertTrue(self._shows_think({"enabled": True}))

    def test_hidden_for_off_absent_and_malformed(self):
        for val in ({"enabled": False}, {"enabled": 1}, _SENTINEL,
                    "yes", 42, None):
            self.assertFalse(self._shows_think(val),
                "thinking={!r} must not render the badge".format(val))

    def test_thinking_is_compact_droppable(self):
        """`thinking` must shed under width pressure before essential
        sections. Pins membership in _COMPACT_DROP (which feeds both
        _NARROW_DROP and _FIT_DROP_PRIORITY)."""
        from claude_statusline.cli import (
            _COMPACT_DROP, _NARROW_DROP, _FIT_DROP_PRIORITY)
        self.assertIn("thinking", _COMPACT_DROP)
        self.assertIn("thinking", _NARROW_DROP)
        self.assertIn("thinking", _FIT_DROP_PRIORITY)


class TestParseIso8601Ms(unittest.TestCase):
    """`_parse_iso8601_ms` converts Claude Code transcript timestamps
    (ISO-8601 UTC with trailing Z) to epoch ms, degrading to None for
    any malformed input rather than raising."""

    def test_parses_z_suffixed_utc(self):
        from claude_statusline.sessions import _parse_iso8601_ms
        # 2026-07-02T23:00:49.920Z — a real transcript-shaped value.
        ms = _parse_iso8601_ms("2026-07-02T23:00:49.920Z")
        self.assertIsNotNone(ms)
        # Round-trips back to the same UTC wall-clock second.
        got = time.gmtime(ms / 1000.0)
        self.assertEqual((got.tm_year, got.tm_mon, got.tm_mday,
                          got.tm_hour, got.tm_min, got.tm_sec),
                         (2026, 7, 2, 23, 0, 49))

    def test_parses_offset_form(self):
        from claude_statusline.sessions import _parse_iso8601_ms
        # Explicit +00:00 offset (some schema versions) must also parse.
        self.assertIsNotNone(_parse_iso8601_ms("2026-07-02T23:00:49+00:00"))

    def test_naive_timestamp_assumed_utc(self):
        """A timestamp with no offset (malformed upstream that dropped
        the Z) is assumed UTC, not crashed on."""
        from claude_statusline.sessions import _parse_iso8601_ms
        z = _parse_iso8601_ms("2026-07-02T23:00:49.920Z")
        naive = _parse_iso8601_ms("2026-07-02T23:00:49.920")
        self.assertIsNotNone(naive)
        self.assertEqual(z, naive)

    def test_malformed_returns_none(self):
        from claude_statusline.sessions import _parse_iso8601_ms
        for bad in (None, "", "not-a-date", 42, [], {}, "2026-13-99T99:99Z",
                    True, 1783046343072):
            self.assertIsNone(_parse_iso8601_ms(bad),
                "_parse_iso8601_ms({!r}) must be None".format(bad))


class TestLastAssistantTimestamp(unittest.TestCase):
    """`get_last_assistant_timestamp_ms` reads the transcript tail and
    returns the newest assistant message's epoch-ms timestamp, mirroring
    the activity reader's path-validation, tail-read, and caching."""

    def _write_transcript(self, lines):
        f = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".jsonl",
            delete=False, newline="", dir=self._test_dir,
        )
        for entry in lines:
            f.write(json.dumps(entry) + "\n")
        f.close()
        self._created_paths.append(f.name)
        return f.name

    def _iso(self, secs_ago):
        return time.strftime(
            "%Y-%m-%dT%H:%M:%S.000Z",
            time.gmtime(time.time() - secs_ago))

    def setUp(self):
        import shutil as shutil_mod
        from claude_statusline import sessions as sessions_mod
        self._shutil_mod = shutil_mod
        self._sessions_mod = sessions_mod
        os.makedirs(sessions_mod._CLAUDE_DIR, exist_ok=True)
        self._test_dir = tempfile.mkdtemp(
            prefix="claude-status-cacheage-", dir=sessions_mod._CLAUDE_DIR,
        )
        self._created_paths = []
        self._clear_cache()

    def _clear_cache(self):
        # cache_age uses its own key prefix; clear it so the 5s TTL
        # doesn't leak between tests.
        try:
            cache_dir = self._sessions_mod._cache_dir()
            if os.path.isdir(cache_dir):
                for name in os.listdir(cache_dir):
                    if name.startswith("cache_age_ts_"):
                        try:
                            os.remove(os.path.join(cache_dir, name))
                        except OSError:
                            pass
        except OSError:
            pass

    def tearDown(self):
        self._shutil_mod.rmtree(self._test_dir, ignore_errors=True)

    def test_returns_newest_assistant_timestamp(self):
        from claude_statusline.sessions import get_last_assistant_timestamp_ms
        path = self._write_transcript([
            {"type": "user", "message": {"role": "user", "content": "hi"},
             "timestamp": self._iso(300)},
            {"type": "assistant",
             "message": {"role": "assistant", "content": []},
             "timestamp": self._iso(200)},
            {"type": "assistant",
             "message": {"role": "assistant", "content": []},
             "timestamp": self._iso(30)},
        ])
        ms = get_last_assistant_timestamp_ms(path)
        self.assertIsNotNone(ms)
        # ~30s ago, not the 200s-ago earlier assistant line.
        age = time.time() - ms / 1000.0
        self.assertTrue(20 <= age <= 45, "expected ~30s age, got {}".format(age))

    def test_outer_envelope_role_fallback(self):
        """Some schema versions put role on the outer envelope, not the
        inner message. The reader must handle both."""
        from claude_statusline.sessions import get_last_assistant_timestamp_ms
        path = self._write_transcript([
            {"role": "assistant", "timestamp": self._iso(15)},
        ])
        self.assertIsNotNone(get_last_assistant_timestamp_ms(path))

    def test_no_assistant_message_returns_none(self):
        from claude_statusline.sessions import get_last_assistant_timestamp_ms
        path = self._write_transcript([
            {"type": "user", "message": {"role": "user", "content": "hi"},
             "timestamp": self._iso(10)},
        ])
        self.assertIsNone(get_last_assistant_timestamp_ms(path))

    def test_missing_timestamp_field_skipped(self):
        """An assistant line missing the timestamp key is filtered by
        the cheap substring pre-filter; the reader keeps walking back
        for an earlier one that has one."""
        from claude_statusline.sessions import get_last_assistant_timestamp_ms
        path = self._write_transcript([
            {"type": "assistant",
             "message": {"role": "assistant", "content": []},
             "timestamp": self._iso(50)},
            {"type": "assistant",
             "message": {"role": "assistant", "content": []}},  # no ts key
        ])
        ms = get_last_assistant_timestamp_ms(path)
        # Falls back to the earlier line's timestamp (~50s ago).
        self.assertIsNotNone(ms)
        age = time.time() - ms / 1000.0
        self.assertTrue(40 <= age <= 65, "expected ~50s, got {}".format(age))

    def test_unparseable_timestamp_falls_through(self):
        """A newest assistant line whose timestamp is PRESENT but
        unparseable (passes the substring pre-filter, fails
        _parse_iso8601_ms) must fall through to the previous valid
        assistant line — the reader's per-line continue branch."""
        from claude_statusline.sessions import get_last_assistant_timestamp_ms
        path = self._write_transcript([
            {"type": "assistant",
             "message": {"role": "assistant", "content": []},
             "timestamp": self._iso(40)},
            {"type": "assistant",
             "message": {"role": "assistant", "content": []},
             "timestamp": "not-a-real-timestamp"},  # present but garbage
        ])
        ms = get_last_assistant_timestamp_ms(path)
        self.assertIsNotNone(ms)
        age = time.time() - ms / 1000.0
        self.assertTrue(30 <= age <= 55,
                        "must fall back to the ~40s line, got {}".format(age))

    def test_corrupt_and_nondict_lines_tolerated(self):
        """A truncated/corrupt JSON line and a non-dict JSON line that
        both slip past the substring pre-filter must be skipped, not
        crash — the reader still finds the valid assistant line."""
        from claude_statusline.sessions import get_last_assistant_timestamp_ms
        # Write raw so we can inject malformed lines the JSON helper
        # wouldn't produce.
        f = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".jsonl",
            delete=False, newline="", dir=self._test_dir,
        )
        f.write(json.dumps({
            "type": "assistant",
            "message": {"role": "assistant", "content": []},
            "timestamp": self._iso(25)}) + "\n")
        # Non-dict JSON array carrying both pre-filter substrings.
        f.write('["timestamp", "assistant"]\n')
        # Truncated object with both substrings — json.loads must raise.
        f.write('{"timestamp": "2026-01-01T00:00:00.000Z", "assistant"\n')
        f.close()
        self._created_paths.append(f.name)
        ms = get_last_assistant_timestamp_ms(f.name)
        self.assertIsNotNone(ms)
        age = time.time() - ms / 1000.0
        self.assertTrue(15 <= age <= 40,
                        "must skip garbage and find the ~25s line, got {}".format(age))

    def test_cached_miss_sentinel(self):
        """A cache MISS (no assistant message) is stored as the
        {"ts": None} sentinel so a subsequent render answers None from
        cache instead of re-tailing the file — the branch that avoids
        re-reading on every render during a long user-only pause."""
        from claude_statusline.sessions import get_last_assistant_timestamp_ms
        path = self._write_transcript([
            {"type": "user", "message": {"role": "user", "content": "hi"},
             "timestamp": self._iso(5)},
        ])
        self.assertIsNone(get_last_assistant_timestamp_ms(path))
        # Now append a valid assistant line, but the miss is cached for
        # 5s — the second call must STILL return None (proving it read
        # the sentinel, not the freshly-appended line).
        with open(path, "a", encoding="utf-8", newline="") as fh:
            fh.write(json.dumps({
                "type": "assistant",
                "message": {"role": "assistant", "content": []},
                "timestamp": self._iso(1)}) + "\n")
        self.assertIsNone(get_last_assistant_timestamp_ms(path),
                          "miss sentinel must suppress the re-read within TTL")

    def test_invalid_and_nonstring_paths(self):
        from claude_statusline.sessions import get_last_assistant_timestamp_ms
        for bad in (None, "", 123, [], {}, "relative/path.jsonl"):
            self.assertIsNone(get_last_assistant_timestamp_ms(bad),
                "path {!r} must return None".format(bad))

    def test_path_outside_claude_dir_rejected(self):
        """Defense-in-depth: a transcript path resolving outside
        ~/.claude/ must be rejected even if the file exists."""
        from claude_statusline.sessions import get_last_assistant_timestamp_ms
        outside = tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False)
        outside.write(json.dumps(
            {"role": "assistant", "timestamp": self._iso(5)}) + "\n")
        outside.close()
        try:
            self.assertIsNone(get_last_assistant_timestamp_ms(outside.name))
        finally:
            os.remove(outside.name)

    def test_missing_file_returns_none(self):
        from claude_statusline.sessions import get_last_assistant_timestamp_ms
        ghost = os.path.join(self._test_dir, "does-not-exist.jsonl")
        self.assertIsNone(get_last_assistant_timestamp_ms(ghost))

    def test_empty_file_returns_none(self):
        from claude_statusline.sessions import get_last_assistant_timestamp_ms
        path = self._write_transcript([])  # zero lines → empty file
        self.assertIsNone(get_last_assistant_timestamp_ms(path))

    def test_result_is_cached(self):
        """Second call within the TTL returns the cached value even if
        the file is deleted underneath us."""
        from claude_statusline.sessions import get_last_assistant_timestamp_ms
        path = self._write_transcript([
            {"role": "assistant", "timestamp": self._iso(10)},
        ])
        first = get_last_assistant_timestamp_ms(path)
        self.assertIsNotNone(first)
        os.remove(path)
        # File gone, but the 5s cache should still answer.
        second = get_last_assistant_timestamp_ms(path)
        self.assertEqual(first, second)


class TestCacheAgeSection(unittest.TestCase):
    """End-to-end `cache_age` section rendering: shows time since the
    last assistant turn, warns past the ~5-min prompt-cache TTL, and
    hides on every degrade path (no transcript, no timestamp, future
    timestamp)."""

    def _plain(self, output):
        return re.sub(r"\x1b\[[0-9;]*m", "", output)

    def _write_transcript(self, secs_ago):
        from claude_statusline import sessions as sessions_mod
        os.makedirs(sessions_mod._CLAUDE_DIR, exist_ok=True)
        d = tempfile.mkdtemp(
            prefix="claude-status-cacheage-r-", dir=sessions_mod._CLAUDE_DIR)
        self._dirs.append(d)
        path = os.path.join(d, "t.jsonl")
        ts = time.strftime(
            "%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() - secs_ago))
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(json.dumps(
                {"type": "assistant",
                 "message": {"role": "assistant", "content": []},
                 "timestamp": ts}) + "\n")
        return path

    def setUp(self):
        import shutil as shutil_mod
        import claude_statusline.cli as cli_mod
        from claude_statusline import sessions as sessions_mod
        self._shutil_mod = shutil_mod
        self._cli_mod = cli_mod
        self._dirs = []
        self._orig_line2 = THEMES["default"]["line2"]
        self._orig_branch = cli_mod.get_branch
        cli_mod.get_branch = lambda: "main"
        THEMES["default"]["line2"] = ["cache_age", "branch"]
        # Wide COLUMNS so the compact-droppable cache_age isn't shed by
        # the responsive layout (it lives in _COMPACT_DROP).
        self._orig_cols = os.environ.get("COLUMNS")
        os.environ["COLUMNS"] = "300"
        # Clear the cache_age cache each test (5s TTL cross-contamination).
        try:
            cache_dir = sessions_mod._cache_dir()
            if os.path.isdir(cache_dir):
                for name in os.listdir(cache_dir):
                    if name.startswith("cache_age_ts_"):
                        os.remove(os.path.join(cache_dir, name))
        except OSError:
            pass

    def tearDown(self):
        THEMES["default"]["line2"] = self._orig_line2
        self._cli_mod.get_branch = self._orig_branch
        if self._orig_cols is None:
            os.environ.pop("COLUMNS", None)
        else:
            os.environ["COLUMNS"] = self._orig_cols
        for d in self._dirs:
            self._shutil_mod.rmtree(d, ignore_errors=True)

    def _render(self, data):
        return self._plain(self._cli_mod.render(data, "default"))

    def test_renders_recent_age(self):
        # ~90s ago. Assert a tolerance band, not an exact string: the
        # fixture floors the timestamp to the whole second and the age
        # is recomputed against the wall clock at render time, so a
        # loaded machine can legitimately read 1m30s or 1m31s. An exact
        # "1m30s" assertion would flake (determinism is a project rule).
        path = self._write_transcript(90)
        out = self._render({"git_branch": "main", "transcript_path": path})
        m = re.search(r"cache_age:1m(\d{2})s", out)
        self.assertIsNotNone(m, out)
        self.assertTrue(29 <= int(m.group(1)) <= 32,
                        "expected ~1m30s, got {}".format(m.group(0)))

    def test_seconds_only_format(self):
        path = self._write_transcript(12)
        out = self._render({"git_branch": "main", "transcript_path": path})
        m = re.search(r"cache_age:(\d+)s", out)
        self.assertIsNotNone(m, out)
        self.assertTrue(8 <= int(m.group(1)) <= 20)

    def test_warn_color_past_ttl(self):
        """Past ~5 min the chip uses the warn color (YELLOW); under it,
        the muted default (BRIGHT_BLACK)."""
        cold = self._cli_mod.render(
            {"git_branch": "main", "transcript_path": self._write_transcript(400)},
            "default")
        self.assertIn(YELLOW, cold)
        # Fresh cache dir state for the warm render.
        self.tearDown(); self.setUp()
        warm = self._cli_mod.render(
            {"git_branch": "main", "transcript_path": self._write_transcript(30)},
            "default")
        self.assertIn("cache_age:", self._plain(warm))
        # Warm render must NOT carry the warn (YELLOW) color and MUST
        # use the muted default (BRIGHT_BLACK). Asserting both directions
        # pins the threshold: a regression that always emitted the warn
        # color would still pass a mere presence check on the warm side.
        # Safe because this isolated line2 (cache_age + branch, branch is
        # GREEN, no cost data) has no other YELLOW source.
        self.assertNotIn(YELLOW, warm)
        self.assertIn(BRIGHT_BLACK, warm)

    def test_hidden_without_transcript(self):
        out = self._render({"git_branch": "main"})
        self.assertNotIn("cache_age", out)

    def test_hidden_when_no_assistant_message(self):
        from claude_statusline import sessions as sessions_mod
        os.makedirs(sessions_mod._CLAUDE_DIR, exist_ok=True)
        d = tempfile.mkdtemp(dir=sessions_mod._CLAUDE_DIR)
        self._dirs.append(d)
        path = os.path.join(d, "t.jsonl")
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(json.dumps(
                {"role": "user", "timestamp": "2026-01-01T00:00:00.000Z"}) + "\n")
        out = self._render({"git_branch": "main", "transcript_path": path})
        self.assertNotIn("cache_age", out)

    def test_future_timestamp_hidden(self):
        """A future-dated last message (clock skew) yields a negative
        age; the section hides rather than render `cache_age:-3s`."""
        path = self._write_transcript(-120)  # 2 minutes in the FUTURE
        out = self._render({"git_branch": "main", "transcript_path": path})
        self.assertNotIn("cache_age", out)

    def test_bad_path_hidden_no_crash(self):
        out = self._render({"git_branch": "main", "transcript_path": "/etc/passwd"})
        self.assertNotIn("cache_age", out)

    def test_cache_age_is_compact_droppable(self):
        from claude_statusline.cli import (
            _COMPACT_DROP, _NARROW_DROP, _FIT_DROP_PRIORITY)
        self.assertIn("cache_age", _COMPACT_DROP)
        self.assertIn("cache_age", _NARROW_DROP)
        self.assertIn("cache_age", _FIT_DROP_PRIORITY)


class TestCostBreakdownSection(unittest.TestCase):
    """Claude Code v2.1.150+ adds `cost.by_category` with per-category
    breakdown (skills, subagents, plugins, per-MCP). Tracked at issue
    #87. The `cost_breakdown` section renders the largest non-base
    category."""

    def test_largest_category_extracted(self):
        from claude_statusline.cli import _normalize
        n = _normalize({
            "cost": {
                "total_cost_usd": 1.50,
                "by_category": {"skills": 0.10, "mcp": 0.80, "subagents": 0.25},
            },
            "session_id": "x",
        })
        self.assertEqual(n["cost_top_category_name"], "mcp")
        self.assertEqual(n["cost_top_category_value"], 0.80)

    def test_category_dict_absent(self):
        from claude_statusline.cli import _normalize
        n = _normalize({"cost": {"total_cost_usd": 1.0}, "session_id": "x"})
        self.assertEqual(n["cost_by_category"], {})
        self.assertIsNone(n["cost_top_category_name"])

    def test_non_numeric_categories_filtered(self):
        """A category with a non-numeric or zero value is excluded
        from the 'largest' calculation."""
        from claude_statusline.cli import _normalize
        n = _normalize({
            "cost": {"by_category": {
                "valid": 0.50,
                "string": "not a number",
                "zero": 0,
                "negative": -0.10,
                "null": None,
            }},
            "session_id": "x",
        })
        self.assertEqual(n["cost_top_category_name"], "valid")
        self.assertIn("valid", n["cost_by_category"])
        self.assertNotIn("string", n["cost_by_category"])
        self.assertNotIn("zero", n["cost_by_category"])
        self.assertNotIn("negative", n["cost_by_category"])
        self.assertNotIn("null", n["cost_by_category"])

    def test_by_category_as_non_dict_does_not_crash(self):
        from claude_statusline.cli import _normalize
        for bad in ("string", [1, 2], 42, True):
            n = _normalize({
                "cost": {"by_category": bad},
                "session_id": "x",
            })
            self.assertEqual(n["cost_by_category"], {},
                "by_category={!r} must be treated as empty".format(bad))

    def test_cost_as_non_dict_does_not_crash(self):
        """Upstream sending cost as a number (older schemas) must not
        crash the new by_category extraction."""
        from claude_statusline.cli import _normalize
        n = _normalize({"cost": 1.50, "session_id": "x"})
        self.assertEqual(n["cost_by_category"], {})
        self.assertIsNone(n["cost"])  # bare number isn't extracted as total_cost_usd

    def test_breakdown_section_renders_largest(self):
        import claude_statusline.cli as cli_mod
        from claude_statusline.themes import THEMES
        orig_line2 = THEMES["default"]["line2"]
        orig_branch = cli_mod.get_branch
        cli_mod.get_branch = lambda: "main"
        try:
            THEMES["default"]["line2"] = ["cost_breakdown", "branch"]
            data = {
                "cost": {
                    "total_cost_usd": 1.50,
                    "by_category": {"mcp": 0.80, "skills": 0.10},
                },
                "git_branch": "main",
            }
            output = cli_mod.render(data, "default")
            plain = re.sub(r"\x1b\[[0-9;]*m", "", output)
            self.assertIn("mcp:", plain,
                "cost_breakdown must render the largest category name")
            self.assertIn("$0.8", plain,
                "cost_breakdown must render the category value via fmt_cost")
        finally:
            THEMES["default"]["line2"] = orig_line2
            cli_mod.get_branch = orig_branch

    def test_breakdown_hidden_below_threshold(self):
        """Tiny category values (< $0.01) are noise, not signal.
        Section must hide rather than render $0.001c chrome —
        unless the SUM across categories meets threshold (see
        test_breakdown_sum_fallback_when_many_small_categories)."""
        import claude_statusline.cli as cli_mod
        from claude_statusline.themes import THEMES
        orig_line2 = THEMES["default"]["line2"]
        orig_branch = cli_mod.get_branch
        cli_mod.get_branch = lambda: "main"
        try:
            THEMES["default"]["line2"] = ["cost_breakdown", "branch"]
            # Single tiny category, no sum-fallback opportunity.
            data = {
                "cost": {"by_category": {"skills": 0.003}},
                "git_branch": "main",
            }
            output = cli_mod.render(data, "default")
            self.assertNotIn("skills:", output,
                "tiny single category must hide rather than render noise")
            self.assertNotIn("other:", output,
                "sum below threshold must NOT trigger other: render")
        finally:
            THEMES["default"]["line2"] = orig_line2
            cli_mod.get_branch = orig_branch

    def test_breakdown_sum_fallback_with_stringified_numerics(self):
        """Regression test for the back-door of the ghost-cost
        suppression. Some JSON serializers stringify numeric values
        (`"0.005"` instead of `0.005`). The renderer's defense-in-
        depth `isinstance(v, (int, float))` filter would drop strings
        — but `_normalize` is supposed to coerce stringified numerics
        to floats BEFORE storing, so the renderer never sees them.

        Without coercion at the normalization boundary, a stringified
        payload would silently sum to 0 and the section would hide,
        re-opening the exact ghost-cost suppression the sum fallback
        was meant to close.

        Probe: 10 categories, each stringified at $0.005. Sum must
        be $0.05, section must render `other:$0.05`.
        """
        import claude_statusline.cli as cli_mod
        from claude_statusline.themes import THEMES
        orig_line2 = THEMES["default"]["line2"]
        orig_branch = cli_mod.get_branch
        cli_mod.get_branch = lambda: "main"
        try:
            THEMES["default"]["line2"] = ["cost_breakdown", "branch"]
            data = {
                "cost": {"by_category": {
                    # All stringified — most serializer-quirk shape
                    # we have to defend against.
                    "mcp-a": "0.005", "mcp-b": "0.005", "mcp-c": "0.005",
                    "mcp-d": "0.005", "mcp-e": "0.005", "mcp-f": "0.005",
                    "mcp-g": "0.005", "mcp-h": "0.005", "mcp-i": "0.005",
                    "mcp-j": "0.005",
                }},
                "git_branch": "main",
            }
            output = cli_mod.render(data, "default")
            plain = re.sub(r"\x1b\[[0-9;]*m", "", output)
            self.assertIn("other:", plain,
                "stringified numerics must be coerced at _normalize so "
                "the sum-fallback rendering still fires")
            self.assertRegex(plain, r"other:.*0\.05",
                "sum must equal 10 * 0.005 = 0.05, not 0 from filter rejection")
        finally:
            THEMES["default"]["line2"] = orig_line2
            cli_mod.get_branch = orig_branch

    def test_normalize_rejects_non_finite_category_values(self):
        """Coerce-on-store widened the accepted-value space vs. the
        pre-v0.6.1 isinstance filter. A stringified `"inf"` would
        coerce via _safe_num to math.inf, pass `num > 0`, and the
        sum-fallback path would render an infinite total. The
        math.isfinite() guard at _normalize closes that hole at the
        contract boundary.

        Also covers `nan` (which is the textbook silent-failure
        pattern: nan > 0 is False so nan would be filtered out by
        the > 0 check, but defense-in-depth is cheap and pins the
        contract for any future change to the inequality)."""
        from claude_statusline.cli import _normalize
        # Stringified inf and nan must be rejected.
        for bad in ("inf", "-inf", "nan", "Infinity", "NaN"):
            n = _normalize({
                "cost": {"by_category": {"bad": bad, "good": 0.50}},
                "session_id": "x",
            })
            self.assertNotIn("bad", n["cost_by_category"],
                "stringified {!r} must be rejected as non-finite".format(bad))
            self.assertEqual(n["cost_top_category_name"], "good",
                "good category must remain after non-finite is rejected")

        # Direct float inf/nan also rejected (defense-in-depth for
        # the case where upstream emits real non-finite floats).
        n = _normalize({
            "cost": {"by_category": {"bad": float("inf"), "good": 0.50}},
            "session_id": "x",
        })
        self.assertNotIn("bad", n["cost_by_category"])

    def test_normalize_coerces_stringified_category_values(self):
        """Pin the coercion contract directly at _normalize: any
        stringified numeric value must be stored as a float, not the
        original string. Downstream code can rely on the type."""
        from claude_statusline.cli import _normalize
        n = _normalize({
            "cost": {"by_category": {
                "string_val": "0.50",
                "int_val": 1,
                "float_val": 2.5,
            }},
            "session_id": "x",
        })
        # All three values should be present as floats.
        cats = n["cost_by_category"]
        self.assertEqual(set(cats.keys()), {"string_val", "int_val", "float_val"})
        for k, v in cats.items():
            self.assertIsInstance(v, float,
                "{!r} stored as {!r} (type {}) — _normalize must coerce "
                "to float so downstream isinstance(float) checks work".format(
                    k, v, type(v).__name__))
        # Top category: float_val = 2.5 > 1.0 > 0.5
        self.assertEqual(n["cost_top_category_name"], "float_val")
        self.assertEqual(n["cost_top_category_value"], 2.5)

    def test_breakdown_sum_fallback_when_many_small_categories(self):
        """Ghost-cost regression: 10 categories each at $0.005 sum
        to $0.05 of real spend. Without the sum fallback the user
        sees nothing rendered — silent suppression of real money.
        With the fallback, render `other:$0.05`."""
        import claude_statusline.cli as cli_mod
        from claude_statusline.themes import THEMES
        orig_line2 = THEMES["default"]["line2"]
        orig_branch = cli_mod.get_branch
        cli_mod.get_branch = lambda: "main"
        try:
            THEMES["default"]["line2"] = ["cost_breakdown", "branch"]
            # 10 small categories, each below $0.01, sum well above.
            data = {
                "cost": {"by_category": {
                    "mcp-a": 0.005, "mcp-b": 0.005, "mcp-c": 0.005,
                    "mcp-d": 0.005, "mcp-e": 0.005, "mcp-f": 0.005,
                    "mcp-g": 0.005, "mcp-h": 0.005, "mcp-i": 0.005,
                    "mcp-j": 0.005,
                }},
                "git_branch": "main",
            }
            output = cli_mod.render(data, "default")
            plain = re.sub(r"\x1b\[[0-9;]*m", "", output)
            self.assertIn("other:", plain,
                "many small categories with sum above threshold must "
                "render as `other:$N` so users see the real cost")
            # 10 * 0.005 = 0.05. fmt_cost renders as $0.05 (cents format).
            self.assertRegex(plain, r"other:.*0\.05",
                "sum must be the cumulative total, not zero")
        finally:
            THEMES["default"]["line2"] = orig_line2
            cli_mod.get_branch = orig_branch

    def test_breakdown_non_string_keys_filtered(self):
        """A category dict with non-string keys (None, int) must be
        filtered cleanly — not picked up by max()."""
        from claude_statusline.cli import _normalize
        n = _normalize({
            "cost": {"by_category": {
                "valid": 0.50,
                None: 0.99,  # non-string key, must be excluded
                42: 1.00,    # non-string key, must be excluded
            }},
            "session_id": "x",
        })
        self.assertEqual(n["cost_top_category_name"], "valid",
            "non-string keys must NOT win the max() selection — "
            "only string-keyed entries survive the filter")

    def test_breakdown_tie_breaking_deterministic(self):
        """When two categories have equal values, `max()` returns
        the first inserted key (Python dict insertion order since
        3.7). Pin the behavior so a future refactor that switches
        to a different data structure can't silently change the
        winner."""
        from claude_statusline.cli import _normalize
        n = _normalize({
            "cost": {"by_category": {"alpha": 0.50, "beta": 0.50}},
            "session_id": "x",
        })
        self.assertEqual(n["cost_top_category_name"], "alpha",
            "tied values must resolve to the first-inserted key "
            "(Python 3.7+ dict insertion-order guarantee)")

    def test_breakdown_with_only_by_category_no_total(self):
        """Upstream may emit cost.by_category WITHOUT cost.total_cost_usd
        (e.g., spending only on plugins, no base API cost yet).
        cost_top_category must still be extracted; cost itself stays
        None and the bar/cost sections gracefully hide."""
        from claude_statusline.cli import _normalize
        n = _normalize({
            "cost": {"by_category": {"mcp": 0.80}},
            "session_id": "x",
        })
        self.assertEqual(n["cost_top_category_name"], "mcp")
        self.assertEqual(n["cost_top_category_value"], 0.80)
        self.assertIsNone(n["cost"],
            "total_cost_usd absent must result in cost=None (existing "
            "contract — cost sections hide cleanly)")


# ─── subagentStatusLine (v0.13.0, #110) ──────────────────────────────

class TestSubagentDiscriminator(unittest.TestCase):
    """Envelope-only payload discrimination. tasks=[] IS a subagent
    payload; element contents can never flip the mode; bool columns
    rejected (bool is an int subclass)."""

    def _is(self, data):
        from claude_statusline.cli import _is_subagent_payload
        return _is_subagent_payload(data)

    def test_canonical_subagent_payload(self):
        self.assertTrue(self._is({"tasks": [{"id": "t"}], "columns": 100}))

    def test_empty_tasks_is_subagent(self):
        """No agents running is a legit subagent payload — falling
        through to main would dump a full ANSI statusline into the
        JSONL panel (the worst cross-mode corruption)."""
        self.assertTrue(self._is({"tasks": [], "columns": 80}))

    def test_malformed_elements_do_not_flip_mode(self):
        self.assertTrue(self._is(
            {"tasks": ["garbage", {"no": "id"}, 42], "columns": 80}))

    def test_main_payload_is_not_subagent(self):
        self.assertFalse(self._is({"session_id": "x", "cost": {}}))

    def test_bool_columns_rejected(self):
        self.assertFalse(self._is({"tasks": [], "columns": True}))

    def test_missing_columns_rejected(self):
        self.assertFalse(self._is({"tasks": []}))

    def test_numeric_string_columns_accepted(self):
        self.assertTrue(self._is({"tasks": [], "columns": "120"}))

    def test_non_dict_payloads(self):
        for bad in (None, [], "x", 42):
            self.assertFalse(self._is(bad))


class TestSubagentRender(unittest.TestCase):
    """render_subagent: JSONL shape, degradation, sanitization,
    width policy, and the zero-side-effects contract."""

    def setUp(self):
        # ONE clock for fixtures AND rendering: fmt_duration floors,
        # so a >=1s gap between fixture-build time and render time
        # would flip "23s" to "24s" — the clock-gap flake class fixed
        # in the v0.12 tests. Every fixture startTime and every render
        # derives from self._now.
        self._now = time.time()

    def _plain(self, s):
        return re.sub(r"\x1b\[[0-9;]*m", "", s)

    def _rows(self, payload, theme="default", now=None):
        import claude_statusline.cli as cli_mod
        out = cli_mod.render_subagent(
            payload, theme, _now=self._now if now is None else now)
        if not out:
            return []
        return [json.loads(line) for line in out.split("\n")]

    def _task(self, **over):
        base = {"id": "t1", "name": "Explore", "status": "running",
                "startTime": int((self._now - 23) * 1000),
                "tokenCount": 410_000, "model": "claude-sonnet-5-20250707",
                "contextWindowSize": 1_000_000}
        base.update(over)
        return base

    def test_full_row_shape(self):
        rows = self._rows({"columns": 100, "tasks": [self._task()]})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "t1")
        body = self._plain(rows[0]["content"])
        self.assertIn("[Explore]", body)
        self.assertIn("41%", body)
        self.assertIn("23s", body)
        self.assertIn("Sonnet 5", body)

    def test_id_type_preserved(self):
        """Int id echoes as int — stringifying could break upstream
        row matching, silently default-rendering the row."""
        rows = self._rows({"columns": 100, "tasks": [self._task(id=42)]})
        self.assertEqual(rows[0]["id"], 42)
        self.assertIsInstance(rows[0]["id"], int)

    def test_terminal_status_omitted(self):
        """Finished tasks are omitted (default rendering) — a rendered
        row would show a forever-ticking elapsed timer."""
        for status in ("completed", "FAILED", "Cancelled", "done",
                       "succeeded", "error"):
            rows = self._rows(
                {"columns": 100, "tasks": [self._task(status=status)]})
            self.assertEqual(rows, [], status)

    def test_unknown_status_renders(self):
        """Fail OPEN: unknown/missing status renders — wrongly hiding
        running tasks would gut the feature."""
        for status in ("thinking", None, 42, ""):
            payload = {"columns": 100, "tasks": [self._task(status=status)]}
            self.assertEqual(len(self._rows(payload)), 1, repr(status))

    def test_never_empty_content(self):
        """Empty content HIDES a row upstream — degradation must OMIT
        instead. At columns=5 (budget 3) even the bare truncated name
        cannot fit: the row must be omitted entirely, never emitted
        with empty content."""
        rows = self._rows({"columns": 5,
                           "tasks": [self._task(name="A" * 200)]})
        self.assertEqual(rows, [])
        # At a moderate width the bare truncated-name fallback renders.
        rows = self._rows({"columns": 14,
                           "tasks": [self._task(name="A" * 200)]})
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["content"])
        self.assertIn("[AAAAAAAA]", self._plain(rows[0]["content"]))

    def test_malformed_tasks_skipped_good_ones_render(self):
        payload = {"columns": 100, "tasks": [
            "garbage", {"name": "no-id"}, self._task(), 42]}
        rows = self._rows(payload)
        self.assertEqual([r["id"] for r in rows], ["t1"])

    def test_zero_tokens_renders_zero_pct(self):
        """tokenCount=0 is a legit just-started task — truthiness
        gates drop zeros (house rule)."""
        rows = self._rows({"columns": 100,
                           "tasks": [self._task(tokenCount=0)]})
        self.assertIn("0%", self._plain(rows[0]["content"]))

    def test_zero_ctx_no_gauge_no_crash(self):
        rows = self._rows({"columns": 100,
                           "tasks": [self._task(contextWindowSize=0)]})
        body = self._plain(rows[0]["content"])
        self.assertNotIn("%", body)
        self.assertIn("[Explore]", body)

    def test_overflow_pct_clamped(self):
        rows = self._rows({"columns": 100, "tasks": [
            self._task(tokenCount=5_000_000, contextWindowSize=1_000_000)]})
        self.assertIn("100%", self._plain(rows[0]["content"]))
        self.assertNotIn("500%", self._plain(rows[0]["content"]))

    def test_start_time_formats(self):
        from claude_statusline.cli import _parse_start_time_ms
        self.assertEqual(_parse_start_time_ms(1_783_046_343),
                         1_783_046_343_000)          # epoch seconds
        self.assertEqual(_parse_start_time_ms(1_783_046_343_072),
                         1_783_046_343_072)          # epoch ms
        self.assertIsNotNone(_parse_start_time_ms("2026-07-09T18:00:00Z"))
        self.assertEqual(_parse_start_time_ms("1783046343"),
                         1_783_046_343_000)          # numeric string
        for bad in (1e15, -5, 0, None, "garbage", float("nan"),
                    float("inf"), [], {}):
            self.assertIsNone(_parse_start_time_ms(bad), repr(bad))

    def test_future_and_ancient_start_time_drop_elapsed(self):
        now = time.time()
        for start in (int((now + 300) * 1000),           # future: skew
                      int((now - 30 * 86400) * 1000)):   # 30d: garbage
            rows = self._rows(
                {"columns": 100, "tasks": [self._task(startTime=start)]},
                now=now)
            body = self._plain(rows[0]["content"])
            self.assertNotIn("s ·", body + " ·")  # no elapsed segment
            self.assertIn("41%", body)            # rest of row intact

    def test_control_chars_stripped_from_name(self):
        rows = self._rows({"columns": 100, "tasks": [
            self._task(name="Ex\x1b]0;pwn\x07plore")]})
        self.assertNotIn("\x1b]", self._plain(rows[0]["content"]))
        self.assertNotIn("\x07", rows[0]["content"])

    def test_width_drop_order(self):
        """model drops first, then bar, then elapsed; minimum keeps
        name + colored pct."""
        task = self._task()
        wide = self._plain(self._rows(
            {"columns": 120, "tasks": [task]})[0]["content"])
        self.assertIn("Sonnet 5", wide)
        mid = self._plain(self._rows(
            {"columns": 40, "tasks": [task]})[0]["content"])
        self.assertNotIn("Sonnet 5", mid)
        self.assertIn("41%", mid)
        narrow = self._plain(self._rows(
            {"columns": 25, "tasks": [task]})[0]["content"])
        self.assertIn("[Explore]", narrow)
        self.assertIn("41%", narrow)
        self.assertNotIn("█", narrow)  # bar dropped before pct

    def test_garbage_columns_defaults_not_flips(self):
        """Garbage columns uses the default width — the renderer must
        NOT crash and must still emit the row (unconditional length
        assertion: an empty result here would BE the regression)."""
        for cols in ("abc", -5, 0, 10**9, None):
            payload = {"columns": cols, "tasks": [self._task()]}
            rows = self._rows(payload)
            self.assertEqual(len(rows), 1, repr(cols))
            self.assertTrue(rows[0]["content"])

    def test_numeric_string_columns_honored(self):
        """The discriminator accepts columns "120"; the renderer must
        use it as a real width (118 budget), not the default."""
        rows = self._rows({"columns": "120", "tasks": [self._task()]})
        self.assertEqual(len(rows), 1)
        self.assertIn("Sonnet 5", self._plain(rows[0]["content"]))

    def test_name_fallback_chain(self):
        for task, expected in (
            ({"id": "a", "label": "MyLabel"}, "[MyLabel]"),
            ({"id": "b", "type": "explore"}, "[explore]"),
            ({"id": "c"}, "[task]"),
        ):
            rows = self._rows({"columns": 80, "tasks": [task]})
            self.assertIn(expected, self._plain(rows[0]["content"]))

    def test_all_builtin_themes_render(self):
        """A theme with a missing color key would crash render_subagent
        (bracket indexing) — and main() would silently blank the whole
        panel. Pin every built-in theme end to end."""
        for theme in ("default", "minimal", "powerline", "nord",
                      "tokyo-night", "gruvbox", "rose-pine", "focus"):
            rows = self._rows({"columns": 100, "tasks": [self._task()]},
                              theme=theme)
            self.assertEqual(len(rows), 1, theme)
            self.assertIn("[Explore]", self._plain(rows[0]["content"]))

    def test_short_model_matrix(self):
        from claude_statusline.cli import _short_model
        self.assertEqual(_short_model("claude-sonnet-5-20250707"), "Sonnet 5")
        self.assertEqual(_short_model("claude-opus-4-8"), "Opus 4.8")
        self.assertEqual(_short_model("claude-haiku-4-5-20251001"),
                         "Haiku 4.5")
        self.assertEqual(_short_model("mystery-model"), "Mystery Model")
        self.assertEqual(_short_model(""), "")
        self.assertEqual(_short_model(None), "")
        self.assertEqual(_short_model(42), "")

    def test_empty_tasks_renders_nothing(self):
        self.assertEqual(self._rows({"columns": 80, "tasks": []}), [])

    def test_nan_id_row_skipped_not_invalid_jsonl(self):
        """A NaN float id (json.loads accepts the bare literal) must
        skip the row — json.dumps would emit `{"id": NaN}` which is
        invalid strict JSON and could poison the whole panel response
        upstream."""
        rows = self._rows({"columns": 100, "tasks": [
            self._task(id=float("nan")),
            self._task(id="good", name="Other")]})
        self.assertEqual([r["id"] for r in rows], ["good"])

    def test_narrow_panel_gets_narrow_budget(self):
        """A genuinely narrow panel (cols=12) must NOT fall back to
        the 80-col default — that would hand a 12-col panel 78-col
        rows (3x overflow). Rows that can't fit are omitted; short
        names still render."""
        rows = self._rows({"columns": 12, "tasks": [self._task(name="Ex")]})
        if rows:  # short name fits: must respect the narrow budget
            from claude_statusline.cli import _visible_width
            self.assertLessEqual(_visible_width(rows[0]["content"]), 10)
        # A long-name task at the same width is omitted, not overflowed.
        rows2 = self._rows({"columns": 12,
                            "tasks": [self._task(name="VeryLongAgentName")]})
        for r in rows2:
            from claude_statusline.cli import _visible_width
            self.assertLessEqual(_visible_width(r["content"]), 10)

    def test_zero_side_effects(self):
        """Subagent rendering must never write to disk or record
        spend — the hook fires per refresh tick per panel."""
        import claude_statusline.cli as cli_mod
        calls = []
        orig_wc = cli_mod._write_cache
        orig_rec = cli_mod.record_and_get_daily_spend
        cli_mod._write_cache = lambda *a, **k: calls.append("write_cache")
        cli_mod.record_and_get_daily_spend = \
            lambda *a, **k: calls.append("ledger") or (0.0, False)
        try:
            self._rows({"columns": 100, "tasks": [self._task()],
                        "session_id": "parent", "effort": {"level": "high"},
                        "cost": {"total_cost_usd": 5.0}})
        finally:
            cli_mod._write_cache = orig_wc
            cli_mod.record_and_get_daily_spend = orig_rec
        self.assertEqual(calls, [],
            "subagent rendering must be side-effect free")

    def test_main_dispatch_skips_normalize_entirely(self):
        """The REAL invariant: main()'s dispatch must route a subagent
        payload BEFORE _normalize/render ever run (_normalize itself
        writes the effort cache; render spawns git). Pins the dispatch
        ORDER, not just render_subagent's own purity."""
        import claude_statusline.cli as cli_mod
        from io import StringIO
        calls = []
        orig_norm = cli_mod._normalize
        orig_branch = cli_mod.get_branch
        cli_mod._normalize = lambda d: calls.append("normalize") or {}
        cli_mod.get_branch = lambda: calls.append("git") or ""
        payload = json.dumps({"columns": 100, "tasks": [self._task()],
                              "effort": {"level": "high"}})
        old_stdin, old_stdout = sys.stdin, sys.stdout
        old_argv = sys.argv
        sys.stdin = StringIO(payload)
        sys.stdout = StringIO()
        sys.argv = ["claude-status", "--subagent"]
        try:
            cli_mod.main()
            out = sys.stdout.getvalue()
        finally:
            sys.stdin, sys.stdout = old_stdin, old_stdout
            sys.argv = old_argv
            cli_mod._normalize = orig_norm
            cli_mod.get_branch = orig_branch
        self.assertEqual(calls, [],
            "_normalize/git must never run on the subagent hook")
        self.assertIn('"id"', out)  # the JSONL actually rendered

    def test_bool_start_time_rejected(self):
        """bool is an int subclass; `true` is not a timestamp — same
        explicit rejection rule as columns."""
        from claude_statusline.cli import _parse_start_time_ms
        self.assertIsNone(_parse_start_time_ms(True))
        self.assertIsNone(_parse_start_time_ms(False))


class TestSubagentEndToEnd(unittest.TestCase):
    """Subprocess-level: the --subagent flag, auto-detection fallback,
    and the JSONL stdout-purity contract."""

    _env = None

    @classmethod
    def setUpClass(cls):
        cls._env = os.environ.copy()
        cls._env["PYTHONIOENCODING"] = "utf-8"
        cls._env.pop("CLAUDE_STATUSLINE_WIDTH", None)

    def _run(self, args, payload):
        return subprocess.run(
            [sys.executable, "-m", "claude_statusline"] + args,
            input=payload, capture_output=True, timeout=15,
            env=self._env, encoding="utf-8", errors="replace",
            cwd=os.path.join(os.path.dirname(__file__), ".."),
        )

    def _payload(self):
        return json.dumps({"columns": 100, "tasks": [
            {"id": "t1", "name": "Explore", "status": "running",
             "startTime": int((time.time() - 23) * 1000),
             "tokenCount": 410_000, "model": "claude-sonnet-5",
             "contextWindowSize": 1_000_000}]})

    def test_flag_renders_jsonl(self):
        r = self._run(["--subagent"], self._payload())
        self.assertEqual(r.returncode, 0)
        lines = [l for l in r.stdout.strip().split("\n") if l]
        self.assertEqual(len(lines), 1)
        obj = json.loads(lines[0])
        self.assertEqual(obj["id"], "t1")
        self.assertIn("Explore", obj["content"])

    def test_flag_garbage_stdin_prints_nothing(self):
        """JSONL purity: with --subagent, undecodable stdin must not
        emit the main hook's '?' fallback."""
        r = self._run(["--subagent"], "{truncated")
        self.assertEqual(r.stdout.strip(), "")
        self.assertEqual(r.returncode, 0)

    def test_flag_main_payload_prints_nothing(self):
        """--subagent with a non-subagent payload outputs nothing,
        exit 0 — never a statusline into the JSONL panel."""
        r = self._run(["--subagent"],
                      json.dumps({"session_id": "x", "git_branch": "main"}))
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "")

    def test_autodetect_fallback_with_breadcrumb(self):
        r = self._run([], self._payload())
        self.assertEqual(r.returncode, 0)
        obj = json.loads(r.stdout.strip().split("\n")[0])
        self.assertEqual(obj["id"], "t1")
        self.assertIn("--subagent", r.stderr)

    def test_truncated_subagent_garbage_no_question_mark(self):
        """A truncated payload that LOOKS subagent-shaped must not put
        a bare '?' into the panel even without the flag."""
        r = self._run([], '{"tasks": [{"id": "t1"')
        self.assertEqual(r.stdout.strip(), "")

    def test_main_mode_unaffected(self):
        r = self._run([], json.dumps(
            {"git_branch": "main",
             "context_window": {"used_percentage": 30}}))
        self.assertEqual(r.returncode, 0)
        self.assertNotIn('"id"', r.stdout)
        self.assertIn("[", r.stdout)  # the context bar

    def test_main_mode_garbage_still_question_mark(self):
        """The main hook's long-standing '?' contract is preserved for
        payloads that don't look subagent-shaped. Exact match — any
        other output would also have contained a '?' under assertIn."""
        r = self._run([], "not json at all {{{")
        self.assertEqual(r.stdout.strip(), "?")

    def test_value_position_tasks_still_question_mark(self):
        """The '?'-suppression sniff matches only the KEY position
        ('"tasks":') — a truncated MAIN payload whose branch is
        literally named "tasks" keeps its '?'."""
        r = self._run([], '{"git_branch": "tasks", "cost"')
        self.assertEqual(r.stdout.strip(), "?")


class TestSubagentInstallFunnel(unittest.TestCase):
    """The install/uninstall/print-config funnel for the
    subagentStatusLine hook. All in-process with _settings_path
    patched to a temp file — never the real settings.json (#96)."""

    def setUp(self):
        import claude_statusline.cli as cli_mod
        self._cli = cli_mod
        self._dir = tempfile.mkdtemp(prefix="claude-status-funnel-")
        self._settings = os.path.join(self._dir, "settings.json")
        self._orig_path = cli_mod._settings_path
        cli_mod._settings_path = lambda: self._settings

    def tearDown(self):
        import shutil as shutil_mod
        self._cli._settings_path = self._orig_path
        shutil_mod.rmtree(self._dir, ignore_errors=True)

    def _write(self, obj):
        with open(self._settings, "w", encoding="utf-8") as f:
            json.dump(obj, f)

    def _read(self):
        with open(self._settings, encoding="utf-8") as f:
            return json.load(f)

    def _capture(self, fn, *a):
        from io import StringIO
        old = sys.stdout
        sys.stdout = StringIO()
        try:
            fn(*a)
            return sys.stdout.getvalue()
        finally:
            sys.stdout = old

    # --- _install_subagent_hook ---------------------------------------

    def test_hook_install_fresh_file(self):
        self._capture(self._cli._install_subagent_hook, "default")
        s = self._read()
        self.assertEqual(s["subagentStatusLine"]["command"],
                         "claude-status --subagent")

    def test_hook_install_preserves_existing_keys(self):
        self._write({"statusLine": {"type": "command",
                                    "command": "claude-status"},
                     "otherKey": {"keep": True}})
        self._capture(self._cli._install_subagent_hook, "nord")
        s = self._read()
        self.assertEqual(s["subagentStatusLine"]["command"],
                         "claude-status --theme nord --subagent")
        self.assertEqual(s["otherKey"], {"keep": True})
        self.assertIn("statusLine", s)

    def test_hook_install_unreadable_settings_returns_false(self):
        with open(self._settings, "w") as f:
            f.write("{corrupt json")
        out_val = []
        out = self._capture(
            lambda: out_val.append(
                self._cli._install_subagent_hook("default")))
        self.assertFalse(out_val[0])
        # File untouched — the corrupt original is preserved for the
        # user to inspect, not clobbered.
        with open(self._settings) as f:
            self.assertEqual(f.read(), "{corrupt json")

    # --- cmd_uninstall interactions -------------------------------------

    def test_uninstall_removes_claude_status_sub_hook(self):
        self._write({
            "statusLine": {"type": "command", "command": "claude-status"},
            "subagentStatusLine": {"type": "command",
                                   "command": "claude-status --subagent"},
        })
        out = self._capture(self._cli.cmd_uninstall)
        s = self._read()
        self.assertNotIn("subagentStatusLine", s)
        self.assertNotIn("statusLine", s)
        self.assertIn("Removed subagentStatusLine hook.", out)

    def test_uninstall_leaves_foreign_sub_hook(self):
        """A subagentStatusLine belonging to another tool is not ours
        to remove — and with no statusLine either, nothing is
        rewritten and no false 'Removed' message prints."""
        original = {"subagentStatusLine": {"type": "command",
                                           "command": "other-tool"}}
        self._write(original)
        before = open(self._settings).read()
        out = self._capture(self._cli.cmd_uninstall)
        self.assertEqual(open(self._settings).read(), before,
                         "settings must not be rewritten")
        self.assertNotIn("Removed", out)

    def test_uninstall_sub_hook_only_no_keyerror(self):
        """Settings with ONLY a claude-status subagentStatusLine: the
        pop-not-del path — a revert to `del settings["statusLine"]`
        crashes exactly here."""
        self._write({"subagentStatusLine": {
            "type": "command", "command": "claude-status --subagent"}})
        out = self._capture(self._cli.cmd_uninstall)
        s = self._read()
        self.assertEqual(s, {})
        self.assertIn("Removed subagentStatusLine hook.", out)

    def test_uninstall_sub_only_stale_bak_does_not_resurrect(self):
        """A stale .bak containing an old statusLine must NOT be
        restored when the live settings had no statusLine to remove —
        the user deliberately removed it."""
        self._write({"subagentStatusLine": {
            "type": "command", "command": "claude-status --subagent"}})
        with open(self._settings + ".bak", "w") as f:
            json.dump({"statusLine": {"type": "command",
                                      "command": "claude-status"}}, f)
        self._capture(self._cli.cmd_uninstall)
        self.assertNotIn("statusLine", self._read())

    # --- print-config subagent variants ---------------------------------

    def _print_config_lines(self):
        from io import StringIO
        old = sys.stdout
        sys.stdout = StringIO()
        try:
            try:
                self._cli.cmd_print_config()
            except SystemExit:
                pass
            return sys.stdout.getvalue().strip().split("\n")
        finally:
            sys.stdout = old

    def _subagent_line(self):
        return [l for l in self._print_config_lines()
                if l.startswith("subagent=")][0]

    def test_print_config_subagent_installed(self):
        self._write({"statusLine": {"type": "command",
                                    "command": "claude-status"},
                     "subagentStatusLine": {
                         "type": "command",
                         "command": "claude-status --subagent"}})
        self.assertEqual(self._subagent_line(), "subagent=installed")

    def test_print_config_subagent_missing_flag(self):
        self._write({"subagentStatusLine": {
            "type": "command", "command": "claude-status"}})
        self.assertEqual(self._subagent_line(),
                         "subagent=installed_missing_flag")

    def test_print_config_subagent_not_installed_variants(self):
        for settings in ({}, {"subagentStatusLine": "garbage"},
                         {"subagentStatusLine": {"command": "other-tool"}}):
            self._write(settings)
            self.assertEqual(self._subagent_line(),
                             "subagent=not_installed", repr(settings))

    def test_print_config_subagent_no_settings_file(self):
        # No file at all: settings stays None — must not crash.
        self.assertEqual(self._subagent_line(), "subagent=not_installed")


if __name__ == "__main__":
    unittest.main()
