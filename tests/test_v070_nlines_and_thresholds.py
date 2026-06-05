"""Tests for v0.7.0 features: N-line statusline support (#101) and
version+confidence-gated layout-threshold relaxation (#94).

Both features are enabled by Anthropic shipping the upstream fixes:
the per-line independent width-limit landed in the 2.1.139 era
(closes #36417), and 2.1.141 ships the COLUMNS env-var handoff
(closes #22115). Before those fixes, multi-line statusline output
could be silently truncated by Ink's wrap:"truncate" and the
statusline subprocess had no reliable way to learn the real
terminal width.
"""

import copy
import os
import re
import unittest


def _strip_ansi(s):
    return re.sub(r"\x1b\[[0-9;]*m", "", s)


# ─── #101: N-line render contract ───────────────────────────────────


class TestNLineRendering(unittest.TestCase):
    """render() iterates `line1`, `line2`, `line3`, ... in the theme
    until it hits a missing key. Backward-compatible: existing 2-line
    themes stop at line3 (missing) and render exactly two rows."""

    _WIDE = {"columns": 200}

    def _make_theme(self, line_lists):
        from claude_statusline.themes import THEMES
        base = copy.deepcopy(THEMES["default"])
        for i in range(1, 10):
            base.pop("line{}".format(i), None)
        for i, lst in enumerate(line_lists, 1):
            base["line{}".format(i)] = lst
        return base

    def _register(self, name, theme):
        from claude_statusline.themes import THEMES
        THEMES[name] = theme

    def _unregister(self, name):
        from claude_statusline.themes import THEMES
        THEMES.pop(name, None)

    def test_two_line_theme_renders_two_lines(self):
        from claude_statusline.cli import render
        theme = self._make_theme([["cost"], ["branch"]])
        self._register("_nlines_2", theme)
        try:
            data = {"cost": {"total_cost_usd": 1.0},
                    "git_branch": "main", "terminal": self._WIDE}
            out = render(data, "_nlines_2")
            self.assertEqual(out.count("\n"), 1,
                "two-line theme must produce exactly one newline")
        finally:
            self._unregister("_nlines_2")

    def test_three_line_theme_renders_three_lines(self):
        from claude_statusline.cli import render
        theme = self._make_theme([["cost"], ["branch"], ["clock"]])
        self._register("_nlines_3", theme)
        try:
            data = {"cost": {"total_cost_usd": 1.0},
                    "git_branch": "main", "terminal": self._WIDE}
            out = render(data, "_nlines_3")
            self.assertEqual(out.count("\n"), 2,
                "three-line theme must produce exactly two newlines")
        finally:
            self._unregister("_nlines_3")

    def test_five_line_theme_renders_five_lines(self):
        """Push past 3 to confirm no hidden cap was introduced."""
        from claude_statusline.cli import render
        theme = self._make_theme([
            ["cost"], ["branch"], ["clock"], ["version"], ["cc_version"],
        ])
        self._register("_nlines_5", theme)
        try:
            data = {
                "cost": {"total_cost_usd": 1.0},
                "git_branch": "main",
                "version": "2.1.141",
                "terminal": self._WIDE,
            }
            out = render(data, "_nlines_5")
            self.assertEqual(out.count("\n"), 4,
                "five-line theme must produce exactly four newlines")
        finally:
            self._unregister("_nlines_5")

    def test_gap_in_numbering_stops_at_first_missing(self):
        """A theme with line1 + line2 + line4 (no line3) renders only
        the first two. Gap = end-of-rows, not skip-and-continue."""
        from claude_statusline.cli import render
        theme = self._make_theme([["cost"], ["branch"]])
        theme["line4"] = ["clock"]
        self._register("_nlines_gap", theme)
        try:
            data = {"cost": {"total_cost_usd": 1.0},
                    "git_branch": "main", "terminal": self._WIDE}
            out = render(data, "_nlines_gap")
            self.assertEqual(out.count("\n"), 1,
                "gap in line numbering stops iteration; only line1+line2 render")
        finally:
            self._unregister("_nlines_gap")

    def test_empty_lineN_produces_no_row(self):
        """A theme with line3: [] (empty list) must not emit a stray
        empty row. Preserves the contract that a row with no sections
        is silently skipped rather than printing a blank line."""
        from claude_statusline.cli import render
        theme = self._make_theme([["cost"], ["branch"], []])
        self._register("_nlines_empty3", theme)
        try:
            data = {"cost": {"total_cost_usd": 1.0},
                    "git_branch": "main", "terminal": self._WIDE}
            out = render(data, "_nlines_empty3")
            self.assertLessEqual(out.count("\n"), 2)
            self.assertFalse(out.endswith("\n\n"))
        finally:
            self._unregister("_nlines_empty3")

    def test_every_built_in_theme_still_renders_correctly(self):
        """All 8 built-in themes define line1 + line2 only. The
        N-line refactor must not have accidentally added or removed
        any row for any of them."""
        from claude_statusline.cli import render
        from claude_statusline.themes import THEMES
        for name in list(THEMES.keys()):
            t = THEMES[name]
            if "line1" not in t or "line2" not in t:
                continue
            data = {
                "context_window": {"used_percentage": 50,
                                   "current_usage": {
                                       "input_tokens": 1000,
                                       "output_tokens": 500}},
                "cost": {"total_cost_usd": 1.0},
                "git_branch": "main",
                "terminal": {"columns": 250},
            }
            out = render(data, name)
            line_count = out.count("\n") + 1 if out else 0
            # focus theme has empty line2 (1 row); others have 2
            self.assertIn(line_count, (1, 2),
                "theme {} produced {} rows; expected 1 or 2".format(
                    name, line_count))


# ─── #94: version + confidence-gated threshold relaxation ──────────


class TestParseCCVersion(unittest.TestCase):
    """Pin the version parser used to gate relaxed thresholds."""

    def test_canonical_three_part(self):
        from claude_statusline.cli import _parse_cc_version
        self.assertEqual(_parse_cc_version("2.1.141"), (2, 1, 141))

    def test_v_prefix_stripped(self):
        from claude_statusline.cli import _parse_cc_version
        self.assertEqual(_parse_cc_version("v2.1.141"), (2, 1, 141))

    def test_pre_release_suffix_stripped(self):
        from claude_statusline.cli import _parse_cc_version
        self.assertEqual(_parse_cc_version("2.1.141-rc.1"), (2, 1, 141))
        self.assertEqual(_parse_cc_version("2.1.141+build5"), (2, 1, 141))

    def test_two_part_returns_none(self):
        """Need all three components."""
        from claude_statusline.cli import _parse_cc_version
        self.assertIsNone(_parse_cc_version("2.1"))

    def test_non_string_returns_none(self):
        from claude_statusline.cli import _parse_cc_version
        for bad in (None, 42, [2, 1, 141], {"v": "2.1.141"}):
            self.assertIsNone(_parse_cc_version(bad))

    def test_empty_or_garbage_returns_none(self):
        from claude_statusline.cli import _parse_cc_version
        for bad in ("", "  ", "garbage", "a.b.c"):
            self.assertIsNone(_parse_cc_version(bad))

    def test_tuple_comparison_correct(self):
        from claude_statusline.cli import _parse_cc_version
        self.assertLess(_parse_cc_version("2.1.140"),
                        _parse_cc_version("2.1.141"))
        self.assertGreaterEqual(_parse_cc_version("2.1.141"),
                                _parse_cc_version("2.1.141"))
        self.assertGreater(_parse_cc_version("2.1.150"),
                           _parse_cc_version("2.1.141"))


class TestLayoutThresholds(unittest.TestCase):
    """`_layout_thresholds(data, width_confidence_high)` returns the
    threshold pair — relaxed (110/80) only when BOTH gates pass."""

    def test_both_gates_pass_returns_relaxed(self):
        from claude_statusline.cli import (
            _layout_thresholds,
            _FULL_LAYOUT_MIN_COLS_RELAXED,
            _COMPACT_LAYOUT_MIN_COLS_RELAXED,
        )
        full, compact = _layout_thresholds(
            {"version": "2.1.141"}, width_confidence_high=True)
        self.assertEqual(full, _FULL_LAYOUT_MIN_COLS_RELAXED)
        self.assertEqual(compact, _COMPACT_LAYOUT_MIN_COLS_RELAXED)

    def test_version_below_gate_returns_conservative(self):
        from claude_statusline.cli import (
            _layout_thresholds,
            _FULL_LAYOUT_MIN_COLS,
            _COMPACT_LAYOUT_MIN_COLS,
        )
        full, compact = _layout_thresholds(
            {"version": "2.1.140"}, width_confidence_high=True)
        self.assertEqual(full, _FULL_LAYOUT_MIN_COLS)
        self.assertEqual(compact, _COMPACT_LAYOUT_MIN_COLS)

    def test_low_confidence_width_returns_conservative(self):
        from claude_statusline.cli import (
            _layout_thresholds,
            _FULL_LAYOUT_MIN_COLS,
        )
        full, _compact = _layout_thresholds(
            {"version": "2.1.141"}, width_confidence_high=False)
        self.assertEqual(full, _FULL_LAYOUT_MIN_COLS)

    def test_missing_version_returns_conservative(self):
        from claude_statusline.cli import (
            _layout_thresholds,
            _FULL_LAYOUT_MIN_COLS,
        )
        full, _compact = _layout_thresholds(
            {}, width_confidence_high=True)
        self.assertEqual(full, _FULL_LAYOUT_MIN_COLS)

    def test_none_data_returns_conservative(self):
        from claude_statusline.cli import (
            _layout_thresholds,
            _FULL_LAYOUT_MIN_COLS,
        )
        full, _compact = _layout_thresholds(None, width_confidence_high=True)
        self.assertEqual(full, _FULL_LAYOUT_MIN_COLS)

    def test_garbage_version_returns_conservative(self):
        from claude_statusline.cli import (
            _layout_thresholds,
            _FULL_LAYOUT_MIN_COLS,
        )
        full, _compact = _layout_thresholds(
            {"version": "garbage"}, width_confidence_high=True)
        self.assertEqual(full, _FULL_LAYOUT_MIN_COLS)

    def test_high_version_passes_gate(self):
        from claude_statusline.cli import (
            _layout_thresholds,
            _FULL_LAYOUT_MIN_COLS_RELAXED,
        )
        full, _ = _layout_thresholds(
            {"version": "2.1.200"}, width_confidence_high=True)
        self.assertEqual(full, _FULL_LAYOUT_MIN_COLS_RELAXED)
        full, _ = _layout_thresholds(
            {"version": "3.0.0"}, width_confidence_high=True)
        self.assertEqual(full, _FULL_LAYOUT_MIN_COLS_RELAXED)


class TestEndToEndRelaxedLayout(unittest.TestCase):
    """End-to-end: with both gates satisfied, sections dropped by
    conservative thresholds at 120 cols become visible."""

    def test_section_recovered_at_120_cols_with_gates(self):
        from claude_statusline.cli import render
        from claude_statusline.themes import THEMES
        base = copy.deepcopy(THEMES["default"])
        base["line1"] = ["bar", "tokens"]
        base["line2"] = ["version", "branch"]
        THEMES["_relaxed_120"] = base
        try:
            data = {
                "version": "2.1.141",
                "context_window": {"used_percentage": 30,
                                   "current_usage": {
                                       "input_tokens": 1000,
                                       "output_tokens": 500}},
                "git_branch": "main",
                "terminal": {"columns": 120},
            }
            out = _strip_ansi(render(data, "_relaxed_120"))
            # Assert the exact released version rather than the loose
            # `v0.` prefix — forces this test to fail (and get updated)
            # the moment __init__.py is bumped, which is the release
            # runbook's expectation per docs/RELEASE.md.
            from claude_statusline import __version__
            self.assertIn("v" + __version__, out,
                "version section should be visible at 120 cols when both "
                "gates pass (2.1.141 + high-confidence width)")
        finally:
            THEMES.pop("_relaxed_120", None)

    def test_section_dropped_at_120_cols_with_old_version(self):
        from claude_statusline.cli import render
        from claude_statusline.themes import THEMES
        base = copy.deepcopy(THEMES["default"])
        base["line1"] = ["bar", "tokens"]
        base["line2"] = ["version", "branch"]
        THEMES["_relaxed_120_old"] = base
        try:
            data = {
                "version": "2.1.140",  # below gate
                "context_window": {"used_percentage": 30,
                                   "current_usage": {
                                       "input_tokens": 1000,
                                       "output_tokens": 500}},
                "git_branch": "main",
                "terminal": {"columns": 120},
            }
            out = _strip_ansi(render(data, "_relaxed_120_old"))
            self.assertNotIn("v0.", out,
                "version section should NOT be visible at 120 cols with "
                "Claude Code 2.1.140 (gate fails)")
        finally:
            THEMES.pop("_relaxed_120_old", None)

    def test_no_regression_at_250_cols(self):
        """At a width above BOTH threshold pairs' full bands, the
        gate path doesn't matter — the SET of rendered sections must
        be identical regardless of Claude Code version. The
        `cc_version` section legitimately shows the input version
        string ("CC:2.1.141" vs "CC:2.1.140"), so compare on
        section structure rather than byte-identical output."""
        from claude_statusline.cli import render
        data_new = {
            "version": "2.1.141",
            "context_window": {"used_percentage": 30,
                               "current_usage": {
                                   "input_tokens": 1000,
                                   "output_tokens": 500}},
            "git_branch": "main",
            "terminal": {"columns": 250},
        }
        data_old = dict(data_new)
        data_old["version"] = "2.1.140"
        out_new = _strip_ansi(render(data_new, "default"))
        out_old = _strip_ansi(render(data_old, "default"))
        # Normalize away the cc_version value (CC:X.Y.Z varies by version)
        out_new_norm = re.sub(r"CC:[\d.]+", "CC:_VER_", out_new)
        out_old_norm = re.sub(r"CC:[\d.]+", "CC:_VER_", out_old)
        self.assertEqual(out_new_norm, out_old_norm,
            "at width >= both thresholds (250 cols), version gate "
            "must not change the section structure of the output")


class TestWidthConfidenceContract(unittest.TestCase):
    """Regression pins for the (winner substring contract.

    render() derives width_confidence_high via:
        any("(winner" in status for _, status in width_report)

    The substring "(winner" is a load-bearing contract with
    _detect_terminal_width_report. A future refactor that renames the
    marker (e.g., to "selected" or "best", or restructures the report
    shape) would silently flip width_confidence_high to False on
    every render — relaxed thresholds would never fire. These tests
    pin the contract bidirectionally so such a refactor breaks the
    test rather than silently regressing the feature.
    """

    def _run_render_with_report(self, fake_report):
        """Render once with the width-detection report stubbed to the
        supplied list of (label, status) tuples. Returns the rendered
        output AND the actual width passed to _apply_responsive
        (captured via stubbing) so callers can pin both the
        confidence-derivation AND the threshold selection."""
        import copy
        import claude_statusline.cli as cli_mod
        from claude_statusline.themes import THEMES

        orig_report = cli_mod._detect_terminal_width_report
        cli_mod._detect_terminal_width_report = lambda data=None: (120, fake_report)

        base = copy.deepcopy(THEMES["default"])
        base["line1"] = ["bar", "tokens"]
        base["line2"] = ["version", "branch"]
        THEMES["_width_contract"] = base
        try:
            data = {
                "version": "2.1.141",
                "context_window": {"used_percentage": 30,
                                   "current_usage": {
                                       "input_tokens": 1000,
                                       "output_tokens": 500}},
                "git_branch": "main",
            }
            return _strip_ansi(cli_mod.render(data, "_width_contract"))
        finally:
            THEMES.pop("_width_contract", None)
            cli_mod._detect_terminal_width_report = orig_report

    def test_winner_marker_enables_relaxed(self):
        """A report whose status contains '(winner' must trigger the
        relaxed-threshold path — section renders at 120 cols."""
        out = self._run_render_with_report([
            ("stub_source", "120 (winner)"),
        ])
        from claude_statusline import __version__
        self.assertIn("v" + __version__, out,
            "report with '(winner' status must enable relaxed thresholds")

    def test_missing_winner_marker_keeps_conservative(self):
        """A report whose statuses do NOT contain '(winner' (e.g., a
        future refactor renamed it) must keep the conservative
        thresholds — section does NOT render at 120 cols. This is
        the regression-guard for the load-bearing substring."""
        out = self._run_render_with_report([
            ("stub_source", "120 selected"),  # no "(winner"
        ])
        from claude_statusline import __version__
        self.assertNotIn("v" + __version__, out,
            "report without '(winner' status must keep conservative "
            "thresholds — if this test starts failing, the substring "
            "contract in render() likely diverged from "
            "_detect_terminal_width_report's status format")

    def test_real_report_contains_winner_marker(self):
        """Belt-and-suspenders: call the real
        _detect_terminal_width_report with a winning stdin value and
        verify it actually does append '(winner' somewhere. Pins the
        OTHER side of the contract — if a refactor of
        _detect_terminal_width_report changes the marker, this test
        catches it independently of any consumer."""
        from claude_statusline.cli import _detect_terminal_width_report
        _result, report = _detect_terminal_width_report(
            {"terminal": {"columns": 200}})
        markers = [s for _, s in report if "(winner" in s]
        self.assertTrue(markers,
            "real _detect_terminal_width_report must append a status "
            "containing '(winner' for the winning step")


class TestCustomThemeNLineSupport(unittest.TestCase):
    """v0.7.0 CRITICAL fix: load_custom_theme() must accept lineN
    for N>=3, not just line1/line2. Without this, a user using
    `theme: custom` couldn't opt into the N-line feature even
    though v0.7.0 CHANGELOG advertised it.
    """

    def _write_custom(self, payload):
        """Write a custom theme JSON to a temp dir, monkey-patch
        _custom_theme_path, return the cleanup function."""
        import json
        import tempfile
        from claude_statusline import themes as themes_mod
        self._tmp = tempfile.mkdtemp(prefix="claude-v070-customtheme-")
        path = os.path.join(self._tmp, "custom.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        self._orig_path = themes_mod._custom_theme_path
        themes_mod._custom_theme_path = lambda: path

    def tearDown(self):
        import shutil
        from claude_statusline import themes as themes_mod
        if hasattr(self, "_orig_path"):
            themes_mod._custom_theme_path = self._orig_path
        if hasattr(self, "_tmp"):
            shutil.rmtree(self._tmp, ignore_errors=True)

    def test_custom_theme_line3_accepted(self):
        from claude_statusline.themes import load_custom_theme
        self._write_custom({
            "base": "default",
            "line3": ["version", "clock"],
        })
        theme = load_custom_theme()
        self.assertIsNotNone(theme)
        self.assertEqual(theme["line3"], ["version", "clock"],
            "custom theme line3 must be loaded (was silently dropped pre-v0.7.0)")

    def test_custom_theme_line5_accepted(self):
        from claude_statusline.themes import load_custom_theme
        self._write_custom({
            "base": "default",
            "line3": ["x"],
            "line4": ["y"],
            "line5": ["z"],
        })
        theme = load_custom_theme()
        self.assertEqual(theme["line3"], ["x"])
        self.assertEqual(theme["line4"], ["y"])
        self.assertEqual(theme["line5"], ["z"])

    def test_custom_theme_line1_line2_still_work(self):
        """The fix replaced a hardcoded line1+line2 path with a
        generalized loop. Backward compat: existing custom themes
        with only line1+line2 must still work identically."""
        from claude_statusline.themes import load_custom_theme
        self._write_custom({
            "base": "default",
            "line1": ["cost"],
            "line2": ["branch"],
        })
        theme = load_custom_theme()
        self.assertEqual(theme["line1"], ["cost"])
        self.assertEqual(theme["line2"], ["branch"])

    def test_custom_theme_line_n_must_be_list(self):
        """A lineN value that isn't a list is rejected silently (the
        base theme's value is kept). Prevents a user typo like
        `"line3": "version"` from crashing the renderer."""
        from claude_statusline.themes import load_custom_theme
        self._write_custom({
            "base": "default",
            "line3": "not a list",
        })
        theme = load_custom_theme()
        # Base default has no line3, so the bad value must not be
        # stored either.
        self.assertNotIn("line3", theme,
            "non-list lineN value must be rejected without setting key")

    def test_custom_theme_lineNN_two_digits(self):
        """Be sure the lineN matcher accepts double-digit indices —
        a user with `line10` should work even if it's exotic."""
        from claude_statusline.themes import load_custom_theme
        self._write_custom({"base": "default", "line10": ["clock"]})
        theme = load_custom_theme()
        self.assertEqual(theme["line10"], ["clock"])

    def test_custom_theme_lineX_garbage_rejected(self):
        """`linex` / `line` / `line-3` / `lineA` are not valid keys
        and must NOT be copied into the theme."""
        from claude_statusline.themes import load_custom_theme
        self._write_custom({
            "base": "default",
            "linex": ["x"],
            "line": ["y"],
            "line-3": ["z"],
            "lineA": ["a"],
        })
        theme = load_custom_theme()
        for bad_key in ("linex", "line", "line-3", "lineA"):
            self.assertNotIn(bad_key, theme,
                "garbage key {!r} must not be copied".format(bad_key))


class TestNLineAdaptiveInteraction(unittest.TestCase):
    """Pin that _apply_responsive fires per-row in a multi-line
    theme. Without this, the loop could accidentally share state
    across rows or skip the filter entirely for line3+."""

    def test_line3_droppable_section_dropped_at_narrow(self):
        """At a width below the conservative compact threshold, a
        droppable section in line3 must be filtered out — same as it
        would be in line2."""
        import copy
        from claude_statusline.cli import render
        from claude_statusline.themes import THEMES
        base = copy.deepcopy(THEMES["default"])
        base["line1"] = ["bar"]
        base["line2"] = ["branch"]
        # `version` is in _COMPACT_DROP, so it should be filtered at
        # narrow widths.
        base["line3"] = ["version"]
        THEMES["_nline_adaptive"] = base
        try:
            data = {
                # Old version so the conservative thresholds apply
                "version": "2.1.140",
                "context_window": {"used_percentage": 30,
                                   "current_usage": {
                                       "input_tokens": 1000,
                                       "output_tokens": 500}},
                "git_branch": "main",
                "terminal": {"columns": 90},  # below 100 = narrow
            }
            out = _strip_ansi(render(data, "_nline_adaptive"))
            self.assertNotIn("v2.1.140", out,
                "line3 must be subject to _apply_responsive — version "
                "is in _COMPACT_DROP and should be filtered at 90 cols")
        finally:
            THEMES.pop("_nline_adaptive", None)

    def test_disabled_sections_filter_applies_to_line3(self):
        """The disabled-sections filter runs inside the per-row loop.
        Confirm it actually filters out a disabled section that lives
        in line3, not just line1/line2."""
        import copy
        import claude_statusline.cli as cli_mod
        from claude_statusline.themes import THEMES
        base = copy.deepcopy(THEMES["default"])
        base["line1"] = ["cost"]
        base["line2"] = ["branch"]
        base["line3"] = ["clock"]
        THEMES["_nline_disabled"] = base
        orig_disabled = cli_mod.get_disabled_sections
        cli_mod.get_disabled_sections = lambda: ["clock"]
        try:
            data = {"cost": {"total_cost_usd": 1.0},
                    "git_branch": "main",
                    "terminal": {"columns": 200}}
            out = cli_mod.render(data, "_nline_disabled")
            # clock is disabled, so line3 has no sections to render
            # and is silently skipped — output has 2 lines, not 3.
            self.assertEqual(out.count("\n"), 1,
                "disabled section in line3 must be filtered; row "
                "with no surviving sections is silently skipped")
        finally:
            THEMES.pop("_nline_disabled", None)
            cli_mod.get_disabled_sections = orig_disabled


class TestParseCCVersionStripOrder(unittest.TestCase):
    """Regression for the strip-order fix: leading whitespace before
    the `v` prefix must work, not just `v` followed by digits."""

    def test_leading_whitespace_before_v(self):
        from claude_statusline.cli import _parse_cc_version
        # All of these should parse to (2, 1, 141)
        self.assertEqual(_parse_cc_version("  v2.1.141"), (2, 1, 141))
        self.assertEqual(_parse_cc_version("\tv2.1.141"), (2, 1, 141))
        self.assertEqual(_parse_cc_version(" v2.1.141 "), (2, 1, 141))

    def test_whitespace_after_v(self):
        """Whitespace between `v` and digits also handled."""
        from claude_statusline.cli import _parse_cc_version
        self.assertEqual(_parse_cc_version("v 2.1.141"), (2, 1, 141))


if __name__ == "__main__":
    unittest.main()
