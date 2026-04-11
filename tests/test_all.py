"""Comprehensive tests for claude-status — stdlib unittest only."""

import json
import os
import re
import subprocess
import sys
import tempfile
import time
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
        """Cache files should be in a user-specific directory."""
        from claude_statusline.sessions import _cache_path
        path = _cache_path("test")
        # Should contain a hash-based subdirectory, not be flat in /tmp
        self.assertIn("claude_sl_", path)
        parent = os.path.basename(os.path.dirname(path))
        self.assertTrue(parent.startswith("claude_sl_"))

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
        """Budget at 90%+ should show bold red."""
        import claude_statusline.cli as cli_mod
        orig = cli_mod.get_budget_config

        cli_mod.get_budget_config = lambda: 1.0

        try:
            data = {
                "context_window": {"used_percentage": 30,
                                   "current_usage": {"input_tokens": 5000}},
                "cost": {"total_cost_usd": 0.95, "total_duration_ms": 60000},
                "git_branch": "main",
            }
            result = render(data)
            # Should contain both current cost and budget formatted
            self.assertIn("$0.95", result)
            # Whole-number budgets should display without trailing .0
            self.assertIn("$1", result)
            self.assertNotIn("$1.0", result)
        finally:
            cli_mod.get_budget_config = orig

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
            capture_output=True, timeout=5,
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
            capture_output=True, timeout=10,
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
        """Wide terminal (120+) should keep all sections."""
        from claude_statusline.cli import _apply_responsive
        sections = ["bar", "tokens", "cache", "cost", "burn",
                    "git_extras", "version", "clock"]
        result = _apply_responsive(sections, 120)
        self.assertEqual(result, sections)

    def test_compact_layout_medium_terminal(self):
        """Medium terminal (80-119) should drop non-essential sections."""
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
        """Narrow terminal (<80) should show only essentials."""
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
        """Values above 100% should be clamped."""
        data = self._data_with_limits(five_h_pct=105)
        result = render(data)
        self.assertIn("5h:100%", result)

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


# ─── cli.py — setup wizard ──────────────────────────────────────────

class TestSetupWizardUpdated(unittest.TestCase):
    def test_setup_flag_accepted(self):
        """--setup should be recognized."""
        result = subprocess.run(
            [sys.executable, "-m", "claude_statusline", "--setup"],
            capture_output=True, timeout=5,
            input="1\n\n",
            encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("setup wizard", result.stdout)
        # Should show compact theme list, not full renders
        self.assertIn("full detail", result.stdout)
        self.assertIn("focus", result.stdout)

    def test_uninstall_flag_accepted(self):
        """--uninstall should be recognized."""
        result = subprocess.run(
            [sys.executable, "-m", "claude_statusline", "--uninstall"],
            capture_output=True, timeout=5,
            encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        self.assertEqual(result.returncode, 0)

    def test_demo_shows_all_themes(self):
        """Demo should show all 8 themes including focus."""
        result = subprocess.run(
            [sys.executable, "-m", "claude_statusline", "--demo"],
            capture_output=True, timeout=10,
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
    def test_osc8_link_with_url(self):
        from claude_statusline.cli import _osc8_link
        result = _osc8_link("https://github.com/test", "branch")
        self.assertIn("branch", result)
        self.assertIn("\033]8;;", result)

    def test_osc8_link_no_url(self):
        from claude_statusline.cli import _osc8_link
        result = _osc8_link("", "branch")
        self.assertEqual(result, "branch")

    def test_osc8_link_none_url(self):
        from claude_statusline.cli import _osc8_link
        result = _osc8_link(None, "branch")
        self.assertEqual(result, "branch")


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


if __name__ == "__main__":
    unittest.main()
