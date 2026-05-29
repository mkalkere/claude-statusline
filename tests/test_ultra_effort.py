"""Tests for the `ultra` effort level (Opus 4.8 / /effort ultracode).

Separate module from test_all.py — claude-status uses stdlib unittest
discovery (`python -m unittest discover tests/`), which picks up every
test_*.py in tests/, so these run alongside the rest.

`ultra` is the stored value Claude Code emits on stdin for
`/effort ultracode` (Opus 4.8, 2026-05). It is xhigh plus standing
permission to launch dynamic workflows; the statusline field reports
the stored value `ultra`, not the `ultracode` display label.
"""

import json
import os
import re
import shutil
import tempfile
import unittest


def _strip_ansi(s):
    return re.sub(r"\x1b\[[0-9;]*m", "", s)


class TestUltraEffortStdin(unittest.TestCase):
    """ultra supplied via stdin effort.level.

    All render-based tests pass `terminal.columns: 200` so the
    `effort` section is eligible for the full layout — the default
    theme drops `effort` from line 2 below the 150-col full-layout
    threshold, so a minimal payload without an explicit wide width
    would render nothing and falsely fail. (The width-detection
    behavior is itself tested elsewhere; here we only care that
    ultra renders when there IS room.)
    """

    # Wide enough to guarantee the full layout keeps the effort section.
    _WIDE = {"columns": 200}

    def setUp(self):
        # _normalize() mirrors stdin effort.level to a user-scoped
        # on-disk cache (cli.py), which get_effort_level() later reads.
        # Without clearing it, these stdin tests pollute the shared
        # effort_level cache and leak a value into other tests in the
        # suite (e.g. test_all's xhigh render test) — and into each
        # other. Clear before and after every test for isolation.
        self._clear_effort_cache()

    def tearDown(self):
        self._clear_effort_cache()

    def _clear_effort_cache(self):
        from claude_statusline import sessions as sessions_mod
        try:
            cache_dir = sessions_mod._cache_dir()
            if os.path.isdir(cache_dir):
                for name in os.listdir(cache_dir):
                    if name.startswith("effort_level"):
                        try:
                            os.remove(os.path.join(cache_dir, name))
                        except OSError:
                            pass
        except OSError:
            pass

    def test_ultra_via_stdin_renders(self):
        from claude_statusline.cli import render
        data = {"effort": {"level": "ultra"}, "git_branch": "main",
                "terminal": self._WIDE}
        result = _strip_ansi(render(data, "default"))
        self.assertIn("effort:ultra", result)

    def test_ultra_via_stdin_case_insensitive(self):
        from claude_statusline.cli import render
        data = {"effort": {"level": "ULTRA"}, "git_branch": "main",
                "terminal": self._WIDE}
        result = _strip_ansi(render(data, "default"))
        self.assertIn("effort:ultra", result)

    def test_ultra_renders_in_all_themes(self):
        """Every built-in theme must render ultra without crashing."""
        from claude_statusline.cli import render
        from claude_statusline.themes import THEMES
        for theme_name in THEMES:
            data = {"effort": {"level": "ultra"}, "git_branch": "main",
                    "terminal": self._WIDE}
            result = _strip_ansi(render(data, theme_name))
            self.assertIsInstance(result, str)

    def test_ultra_uses_top_tier_color(self):
        """ultra is a TOP tier — the effort section must render in the
        top-tier color (BRIGHT_MAGENTA in the default theme), not the
        dim BRIGHT_BLACK used for the low tier.

        colorize("effort:ultra", BRIGHT_MAGENTA, BOLD) emits the color
        and BOLD codes ONCE at the front of the whole string —
        `\\x1b[95m\\x1b[1meffort:ultra\\x1b[0m` — so the color code is
        followed by `effort:`, never by `ultra`. We assert on the
        actual emitted sequence (color + BOLD + the full segment), the
        same way the existing xhigh/max tests do."""
        from claude_statusline.cli import render
        from claude_statusline import colors
        data = {"effort": {"level": "ultra"}, "git_branch": "main",
                "terminal": self._WIDE}
        raw = render(data, "default")
        self.assertIn("effort:ultra", _strip_ansi(raw))
        self.assertIn(colors.BRIGHT_MAGENTA + colors.BOLD + "effort:ultra", raw,
            "ultra effort section must render in the top-tier color + BOLD")
        self.assertNotIn(colors.BRIGHT_BLACK + colors.BOLD + "effort:ultra", raw,
            "ultra must not be dimmed (low-tier color)")

    def test_stdin_takes_precedence_over_settings(self):
        """When stdin supplies ultra, it must win over any
        settings.json value — matching existing effort precedence."""
        import claude_statusline.cli as cli_mod
        orig = cli_mod.get_effort_level
        cli_mod.get_effort_level = lambda: "high"
        try:
            data = {"effort": {"level": "ultra"}, "git_branch": "main",
                    "terminal": self._WIDE}
            result = _strip_ansi(cli_mod.render(data, "default"))
            self.assertIn("effort:ultra", result)
            self.assertNotIn("effort:high", result)
        finally:
            cli_mod.get_effort_level = orig

    def test_ultra_hidden_when_stdin_medium(self):
        """Section-hiding contract: stdin effort.level 'medium' (the
        default) must NOT render any effort section. Guards against a
        regression in the top-tier if/elif chain that always emitted
        a level.

        get_effort_level() is patched to None so the real machine's
        ~/.claude/settings.json (and its user-scoped cache, which is
        NOT under _CLAUDE_DIR) cannot leak a non-medium level into the
        render and mask the contract."""
        import claude_statusline.cli as cli_mod
        orig = cli_mod.get_effort_level
        cli_mod.get_effort_level = lambda: None
        try:
            data = {"effort": {"level": "medium"}, "git_branch": "main",
                    "terminal": self._WIDE}
            result = _strip_ansi(cli_mod.render(data, "default"))
            self.assertNotIn("effort:", result)
        finally:
            cli_mod.get_effort_level = orig

    def test_no_effort_section_when_absent(self):
        """No effort key at all → no effort section. get_effort_level()
        is patched to None so the real settings.json fallback can't
        inject a level (the user-scoped effort cache lives outside
        _CLAUDE_DIR, so just repointing the dir is insufficient)."""
        import claude_statusline.cli as cli_mod
        orig = cli_mod.get_effort_level
        cli_mod.get_effort_level = lambda: None
        try:
            data = {"git_branch": "main", "terminal": self._WIDE}
            result = _strip_ansi(cli_mod.render(data, "default"))
            self.assertNotIn("effort:", result)
        finally:
            cli_mod.get_effort_level = orig


class TestUltraEffortValidSet(unittest.TestCase):
    """ultra accepted in _VALID_EFFORT_LEVELS (gates both paths)."""

    def test_ultra_in_valid_set(self):
        from claude_statusline.sessions import _VALID_EFFORT_LEVELS
        self.assertIn("ultra", _VALID_EFFORT_LEVELS)

    def test_ultra_normalized_from_stdin(self):
        from claude_statusline.cli import _normalize
        n = _normalize({"effort": {"level": "ultra"}, "session_id": "x"})
        self.assertEqual(n["effort_level"], "ultra")

    def test_ultra_uppercase_normalized(self):
        from claude_statusline.cli import _normalize
        n = _normalize({"effort": {"level": "ULTRA"}, "session_id": "x"})
        self.assertEqual(n["effort_level"], "ultra")

    def test_ultracode_label_rejected(self):
        """"ultracode" is the DISPLAY label, not the stored value.
        Claude Code emits "ultra" on stdin, so "ultracode" itself is
        not a valid stored value and must be rejected."""
        from claude_statusline.cli import _normalize
        n = _normalize({"effort": {"level": "ultracode"}, "session_id": "x"})
        self.assertIsNone(n["effort_level"])

    def test_bogus_still_rejected(self):
        """Adding ultra must not weaken rejection of invalid levels."""
        from claude_statusline.cli import _normalize
        n = _normalize({"effort": {"level": "ludicrous"}, "session_id": "x"})
        self.assertIsNone(n["effort_level"])

    def test_non_string_ultra_rejected(self):
        """Non-string effort.level (e.g. 42) must not crash and must
        be rejected — parity with existing _normalize robustness."""
        from claude_statusline.cli import _normalize
        for bad in (42, ["ultra"], {"level": "ultra"}, None):
            n = _normalize({"effort": {"level": bad}, "session_id": "x"})
            self.assertIsNone(n["effort_level"])


class TestUltraEffortSettingsJson(unittest.TestCase):
    """ultra accepted via the settings.json fallback path
    (get_effort_level), for older Claude Code without stdin effort.
    Uses a temp _CLAUDE_DIR so the real ~/.claude is never touched
    (see issue #96)."""

    def setUp(self):
        from claude_statusline import sessions as sessions_mod
        self._sessions = sessions_mod
        self._tmp = tempfile.mkdtemp(prefix="claude-ultra-test-")
        self._orig_dir = sessions_mod._CLAUDE_DIR
        sessions_mod._CLAUDE_DIR = self._tmp
        self._clear_effort_cache()

    def tearDown(self):
        self._sessions._CLAUDE_DIR = self._orig_dir
        shutil.rmtree(self._tmp, ignore_errors=True)
        self._clear_effort_cache()

    def _clear_effort_cache(self):
        try:
            cache_dir = self._sessions._cache_dir()
            if os.path.isdir(cache_dir):
                for name in os.listdir(cache_dir):
                    if name.startswith("effort_level"):
                        try:
                            os.remove(os.path.join(cache_dir, name))
                        except OSError:
                            pass
        except OSError:
            pass

    def _write_settings(self, effort):
        path = os.path.join(self._tmp, "settings.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"effortLevel": effort}, f)

    def test_ultra_from_settings_json(self):
        self._write_settings("ultra")
        self.assertEqual(self._sessions.get_effort_level(), "ultra")

    def test_ultra_uppercase_from_settings_json(self):
        self._write_settings("ULTRA")
        self.assertEqual(self._sessions.get_effort_level(), "ultra")

    def test_ultracode_label_rejected_from_settings(self):
        self._write_settings("ultracode")
        self.assertIsNone(self._sessions.get_effort_level())


class TestUltraEffortCustomThemeFallthrough(unittest.TestCase):
    """A custom theme that lacks effort_ultra must still render ultra
    via the _first() fallthrough chain, never crashing."""

    def test_theme_without_effort_ultra_falls_through(self):
        import claude_statusline.cli as cli_mod
        from claude_statusline.themes import THEMES
        import copy
        base = copy.deepcopy(THEMES["default"])
        base["colors"].pop("effort_ultra", None)
        THEMES["_ultra_test"] = base
        try:
            data = {"effort": {"level": "ultra"}, "git_branch": "main",
                    "terminal": {"columns": 200}}
            result = _strip_ansi(cli_mod.render(data, "_ultra_test"))
            self.assertIn("effort:ultra", result)
        finally:
            THEMES.pop("_ultra_test", None)

    def test_theme_with_effort_ultra_none_falls_through(self):
        """effort_ultra explicitly None must not pass None to
        colorize() — _first() skips it."""
        import claude_statusline.cli as cli_mod
        from claude_statusline.themes import THEMES
        import copy
        base = copy.deepcopy(THEMES["default"])
        base["colors"]["effort_ultra"] = None
        THEMES["_ultra_none_test"] = base
        try:
            data = {"effort": {"level": "ultra"}, "git_branch": "main",
                    "terminal": {"columns": 200}}
            result = _strip_ansi(cli_mod.render(data, "_ultra_none_test"))
            self.assertIn("effort:ultra", result)
        finally:
            THEMES.pop("_ultra_none_test", None)


class TestAllThemesHaveEffortUltra(unittest.TestCase):
    """Structural parity: every built-in theme carries effort_ultra,
    mirroring effort_max."""

    def test_every_theme_has_effort_ultra(self):
        from claude_statusline.themes import THEMES
        missing = [
            name for name, t in THEMES.items()
            if "effort_ultra" not in t.get("colors", {})
        ]
        self.assertEqual(missing, [],
            "themes missing effort_ultra: {}".format(missing))

    def test_effort_ultra_mirrors_effort_max(self):
        from claude_statusline.themes import THEMES
        for name, t in THEMES.items():
            colors = t.get("colors", {})
            self.assertEqual(
                colors.get("effort_ultra"), colors.get("effort_max"),
                "theme {}: effort_ultra should mirror effort_max".format(name))


class TestDemoModelVersion(unittest.TestCase):
    """The --demo / _demo_data model display_name was bumped to
    Opus 4.8. Guard against it silently reverting."""

    def test_demo_data_shows_opus_4_8(self):
        from claude_statusline.cli import _demo_data
        d = _demo_data()
        self.assertEqual(d["model"]["display_name"], "Opus 4.8 (1M context)")

    def test_demo_renders_opus_4_8(self):
        from claude_statusline.cli import _demo_data, render
        result = _strip_ansi(render(_demo_data(), "default"))
        self.assertIn("Opus 4.8", result)


if __name__ == "__main__":
    unittest.main()
