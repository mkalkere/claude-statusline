"""Tests for v0.7.0 features: N-line statusline support (#101) and
version+confidence-gated layout-threshold relaxation (#94).

Both features are enabled by Anthropic shipping the upstream fix in
Claude Code 2.1.141 (closes #36417 per-line truncation + #22115
COLUMNS env handoff). Before that fix, multi-line statusline output
could be silently truncated by Ink's wrap:"truncate" and the
statusline subprocess had no reliable way to learn the real terminal
width. Both behaviors are documented as fixed today (2026-06-05).
"""

import copy
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
            self.assertIn("v0.", out,
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


if __name__ == "__main__":
    unittest.main()
