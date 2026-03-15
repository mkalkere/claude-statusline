"""Comprehensive tests for claude-statusline — stdlib unittest only."""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

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


# ─── themes.py ────────────────────────────────────────────────────────

class TestThemes(unittest.TestCase):
    def test_all_three_exist(self):
        self.assertIn("default", THEMES)
        self.assertIn("minimal", THEMES)
        self.assertIn("powerline", THEMES)

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
                           "added", "removed", "agent", "vim_normal", "vim_insert"]
        for name, theme in THEMES.items():
            for key in required_colors:
                self.assertIn(key, theme["colors"],
                              "{} theme missing color: {}".format(name, key))


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

    def test_exceeds_200k(self):
        data = self._full_data()
        data["exceeds_200k_tokens"] = True
        result = render(data)
        self.assertIn("!CTX", result)

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
                self.assertEqual(settings["statusLine"], "claude-statusline")
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
                self.assertIn("--theme powerline", settings["statusLine"])
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
                self.assertEqual(settings["statusLine"], "claude-statusline")
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
            capture_output=True, timeout=10,
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


if __name__ == "__main__":
    unittest.main()
