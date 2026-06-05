"""Tests for the v0.6.3 schema-realignment contract.

Pins two reconciliations against live Claude Code statusline docs
(observed at code.claude.com as of 2026-06-04):

1. PR namespace: stdin payloads use `pr.{number, url, review_state}`
   + `workspace.repo.{host, owner, name}` in the live docs. v0.6.1
   shipped the `pr` section reading the older `github.{pr_number,
   pr_url, repo}` shape. v0.6.3 reads BOTH with truthy-value
   precedence: pr.* wins when populated, github.* is the fallback.

2. effort.level enum: live docs document the enum as low/medium/
   high/xhigh/max with ultracode collapsed into xhigh — no `ultra`
   value. v0.6.2 added `ultra` as a 6th level based on a different
   docs snapshot. v0.6.3 keeps `ultra` accepted as a silent alias
   that renders as `xhigh` at every layer (stdin, settings.json
   fresh read, cached-read return). This protects two real user
   groups: (a) anyone with `effortLevel: "ultra"` in settings.json
   because v0.6.2 told them it was valid, (b) anyone with the v0.6.2
   on-disk effort cache holding the value "ultra".

Render-based tests pass an explicit `terminal.columns: 200` because
the default theme drops the `effort` section below the 150-col
full-layout threshold (a minimal payload without an explicit wide
width would render nothing and falsely fail).
"""

import json
import os
import re
import shutil
import tempfile
import unittest


def _strip_ansi(s):
    return re.sub(r"\x1b\[[0-9;]*m", "", s)


# ─── Ultra silent-alias contract ───────────────────────────────────


class TestEffortAliasMap(unittest.TestCase):
    """Pin the alias map exactly.

    The single source of truth for what is silently rewritten is
    sessions._EFFORT_ALIASES. Strict equality on the map prevents
    accidental drift (e.g. someone adding "high" -> "max" without
    a CHANGELOG entry).
    """

    def test_alias_map_is_exactly_ultra_to_xhigh(self):
        """Asserts the v0.6.2 -> v0.6.3 silent migration:
        v0.6.2 accepted `ultra` as a distinct effort level on the
        (then-incorrect) assumption that Claude Code emitted it as a
        stored value. v0.6.3 keeps `ultra` accepted but maps it to
        `xhigh` to match Claude Code's documented effort enum.
        Adding any other alias here should be a deliberate
        CHANGELOG'd change, not a silent edit."""
        from claude_statusline.sessions import _EFFORT_ALIASES
        self.assertEqual(_EFFORT_ALIASES, {"ultra": "xhigh"})

    def test_canonical_effort_pass_through_for_documented_levels(self):
        from claude_statusline.sessions import _canonical_effort
        for level in ("low", "medium", "high", "xhigh", "max"):
            self.assertEqual(_canonical_effort(level), level)

    def test_canonical_effort_aliases_ultra(self):
        from claude_statusline.sessions import _canonical_effort
        self.assertEqual(_canonical_effort("ultra"), "xhigh")

    def test_canonical_effort_unknown_passes_through(self):
        """Caller is responsible for membership-checking against
        _VALID_EFFORT_LEVELS. _canonical_effort doesn't reject
        unknowns — it just returns the input."""
        from claude_statusline.sessions import _canonical_effort
        self.assertEqual(_canonical_effort("bogus"), "bogus")


class TestUltraAcceptedInValidSet(unittest.TestCase):
    """ultra remains in _VALID_EFFORT_LEVELS so v0.6.2 users with
    `effortLevel: "ultra"` in settings.json or with a stale on-disk
    cache value of "ultra" don't lose their effort section on
    upgrade. The alias makes the rendered output canonical."""

    def test_ultra_in_valid_set(self):
        from claude_statusline.sessions import _VALID_EFFORT_LEVELS
        self.assertIn("ultra", _VALID_EFFORT_LEVELS)

    def test_documented_levels_in_valid_set(self):
        from claude_statusline.sessions import _VALID_EFFORT_LEVELS
        for level in ("low", "medium", "high", "xhigh", "max"):
            self.assertIn(level, _VALID_EFFORT_LEVELS)


class TestUltraStdinAlias(unittest.TestCase):
    """Stdin path: `effort.level: "ultra"` is accepted and rewritten
    to `xhigh` BEFORE being stored in the normalized dict, before
    being mirrored to the disk cache, and before being rendered.

    All render-based tests use a sandboxed `_cache_dir` so the mirror
    writes go into a tempdir, not the real user cache. Same isolation
    pattern v0.6.2 settled on after Gemini caught the cache-mutation
    side-effect.
    """

    _WIDE = {"columns": 200}

    def setUp(self):
        from claude_statusline import sessions as sessions_mod
        self._sessions = sessions_mod
        self._tmp_cache = tempfile.mkdtemp(prefix="claude-v063-cache-")
        self._orig_cache_dir = sessions_mod._cache_dir
        sessions_mod._cache_dir = lambda: self._tmp_cache

    def tearDown(self):
        self._sessions._cache_dir = self._orig_cache_dir
        shutil.rmtree(self._tmp_cache, ignore_errors=True)

    def test_ultra_normalizes_to_xhigh(self):
        from claude_statusline.cli import _normalize
        n = _normalize({"effort": {"level": "ultra"}, "session_id": "x"})
        self.assertEqual(n["effort_level"], "xhigh")

    def test_ultra_uppercase_normalizes_to_xhigh(self):
        from claude_statusline.cli import _normalize
        n = _normalize({"effort": {"level": "ULTRA"}, "session_id": "x"})
        self.assertEqual(n["effort_level"], "xhigh")

    def test_ultra_renders_as_effort_xhigh(self):
        """End-to-end: an `ultra` stdin value renders as `effort:xhigh`."""
        from claude_statusline.cli import render
        data = {"effort": {"level": "ultra"}, "git_branch": "main",
                "terminal": self._WIDE}
        result = _strip_ansi(render(data, "default"))
        self.assertIn("effort:xhigh", result)
        self.assertNotIn("effort:ultra", result)

    def test_ultra_mirror_writes_canonical_value(self):
        """When stdin says ultra, the disk-cache mirror must store
        the CANONICAL value (xhigh), not the raw input. Over time
        the on-disk cache stops containing `ultra` at all — the
        alias becomes a read-only legacy path."""
        from claude_statusline.cli import _normalize
        from claude_statusline.sessions import _read_cache
        _normalize({"effort": {"level": "ultra"}, "session_id": "x"})
        cached = _read_cache("effort_level")
        self.assertIsNotNone(cached)
        self.assertEqual(cached.get("effort"), "xhigh",
            "mirror must rewrite ultra to xhigh on store")

    def test_xhigh_still_normalizes_to_xhigh(self):
        """Aliasing must not regress the canonical-value path."""
        from claude_statusline.cli import _normalize
        n = _normalize({"effort": {"level": "xhigh"}, "session_id": "x"})
        self.assertEqual(n["effort_level"], "xhigh")

    def test_ultracode_label_still_rejected(self):
        """`ultracode` is the UI display label, not a valid stored
        value. Aliasing `ultra`->`xhigh` must NOT also accept
        `ultracode` (would weaken validation)."""
        from claude_statusline.cli import _normalize
        n = _normalize({"effort": {"level": "ultracode"}, "session_id": "x"})
        self.assertIsNone(n["effort_level"])

    def test_non_string_effort_rejected(self):
        from claude_statusline.cli import _normalize
        for bad in (42, ["ultra"], {"level": "ultra"}, None):
            n = _normalize({"effort": {"level": bad}, "session_id": "x"})
            self.assertIsNone(n["effort_level"])


class TestUltraSettingsJsonAlias(unittest.TestCase):
    """Settings.json fresh-read path: a user whose
    `~/.claude/settings.json` has `effortLevel: "ultra"` (because
    v0.6.2 CHANGELOG told them it was valid) reads as `xhigh` after
    upgrade — no effort section disappears, no `effort:ultra` label
    visible.

    Sandboxes both `_CLAUDE_DIR` (where settings.json is read) and
    `_cache_dir` (where the user-scoped effort cache lives) so this
    test does not touch the real contributor environment.
    """

    def setUp(self):
        from claude_statusline import sessions as sessions_mod
        self._sessions = sessions_mod
        self._tmp = tempfile.mkdtemp(prefix="claude-v063-settings-")
        self._tmp_cache = tempfile.mkdtemp(prefix="claude-v063-cache-")
        self._orig_dir = sessions_mod._CLAUDE_DIR
        self._orig_cache_dir = sessions_mod._cache_dir
        sessions_mod._CLAUDE_DIR = self._tmp
        sessions_mod._cache_dir = lambda: self._tmp_cache

    def tearDown(self):
        self._sessions._CLAUDE_DIR = self._orig_dir
        self._sessions._cache_dir = self._orig_cache_dir
        shutil.rmtree(self._tmp, ignore_errors=True)
        shutil.rmtree(self._tmp_cache, ignore_errors=True)

    def _write_settings(self, effort):
        path = os.path.join(self._tmp, "settings.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"effortLevel": effort}, f)

    def test_ultra_from_settings_aliases_to_xhigh(self):
        self._write_settings("ultra")
        self.assertEqual(self._sessions.get_effort_level(), "xhigh")

    def test_ultra_uppercase_from_settings_aliases_to_xhigh(self):
        self._write_settings("ULTRA")
        self.assertEqual(self._sessions.get_effort_level(), "xhigh")

    def test_ultracode_from_settings_still_rejected(self):
        self._write_settings("ultracode")
        self.assertIsNone(self._sessions.get_effort_level())

    def test_xhigh_from_settings_unchanged(self):
        self._write_settings("xhigh")
        self.assertEqual(self._sessions.get_effort_level(), "xhigh")


class TestUltraCachedReadAlias(unittest.TestCase):
    """Cached-read path: the user-scoped effort cache file may already
    contain `effort: "ultra"` from a v0.6.2 install. On v0.6.3
    upgrade, the FIRST call to get_effort_level() (which reads from
    that cache) must return `xhigh`, not `ultra`. Without this layer
    the silent-alias contract has a ~30s window after upgrade where
    the user still sees stale `effort:ultra`.
    """

    def setUp(self):
        from claude_statusline import sessions as sessions_mod
        self._sessions = sessions_mod
        self._tmp_cache = tempfile.mkdtemp(prefix="claude-v063-cache-")
        self._orig_cache_dir = sessions_mod._cache_dir
        sessions_mod._cache_dir = lambda: self._tmp_cache

    def tearDown(self):
        self._sessions._cache_dir = self._orig_cache_dir
        shutil.rmtree(self._tmp_cache, ignore_errors=True)

    def _seed_cache(self, value):
        # Mirror what v0.6.2's _write_cache would have stored.
        path = self._sessions._cache_path("effort_level")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"effort": value}, f)

    def test_stale_ultra_cache_returns_xhigh(self):
        """Regression-pin: v0.6.2 wrote `ultra` to the disk cache;
        v0.6.3's cached-read path must alias it on return."""
        self._seed_cache("ultra")
        self.assertEqual(self._sessions.get_effort_level(), "xhigh")

    def test_stale_xhigh_cache_returns_xhigh(self):
        self._seed_cache("xhigh")
        self.assertEqual(self._sessions.get_effort_level(), "xhigh")

    def test_stale_medium_cache_returns_none(self):
        """The cache-read path returns None for `medium` (the hidden
        default), unchanged behavior — aliasing must not regress."""
        self._seed_cache("medium")
        self.assertIsNone(self._sessions.get_effort_level())


# ─── PR namespace dual-read contract ───────────────────────────────


class TestPRDualNamespacePrecedence(unittest.TestCase):
    """v0.6.3 reads both `pr.{number, url}` (live-docs shape) and
    `github.{pr_number, pr_url}` (v0.6.1 shape) with truthy-value
    precedence: the live-docs shape wins when populated; falls
    through cleanly to the legacy shape when not.
    """

    def test_pr_namespace_populates(self):
        from claude_statusline.cli import _normalize
        n = _normalize({
            "pr": {"number": 1234, "url": "https://x/pr/1234"},
            "session_id": "x",
        })
        self.assertEqual(n["github_pr_number"], 1234)
        self.assertEqual(n["github_pr_url"], "https://x/pr/1234")

    def test_github_namespace_fallback(self):
        from claude_statusline.cli import _normalize
        n = _normalize({
            "github": {"pr_number": 86, "pr_url": "https://x/pr/86"},
            "session_id": "x",
        })
        self.assertEqual(n["github_pr_number"], 86)
        self.assertEqual(n["github_pr_url"], "https://x/pr/86")

    def test_pr_wins_over_github_when_both_populated(self):
        """A buggy transitional Claude Code build emitting BOTH must
        be resolved deterministically. Live-docs shape wins."""
        from claude_statusline.cli import _normalize
        n = _normalize({
            "pr": {"number": 100, "url": "https://x/pr/100"},
            "github": {"pr_number": 200, "pr_url": "https://x/pr/200"},
            "session_id": "x",
        })
        self.assertEqual(n["github_pr_number"], 100)
        self.assertEqual(n["github_pr_url"], "https://x/pr/100")

    def test_empty_pr_object_falls_through_to_github(self):
        """Truthy-value precedence (not key-presence): an empty
        `pr: {}` does NOT shadow the legacy github.* values."""
        from claude_statusline.cli import _normalize
        n = _normalize({
            "pr": {},
            "github": {"pr_number": 86},
            "session_id": "x",
        })
        self.assertEqual(n["github_pr_number"], 86)

    def test_pr_with_only_url_falls_through_for_number(self):
        """Per-field truthy precedence: a `pr` with only `url`
        populated leaves `number` to fall back to github.pr_number."""
        from claude_statusline.cli import _normalize
        n = _normalize({
            "pr": {"url": "https://x/pr/200"},
            "github": {"pr_number": 86, "pr_url": "https://x/pr/86"},
            "session_id": "x",
        })
        self.assertEqual(n["github_pr_number"], 86)
        # pr.url is populated, so it wins
        self.assertEqual(n["github_pr_url"], "https://x/pr/200")

    def test_neither_namespace_present_yields_none(self):
        from claude_statusline.cli import _normalize
        n = _normalize({"session_id": "x"})
        self.assertIsNone(n["github_pr_number"])
        self.assertIsNone(n["github_pr_url"])
        self.assertIsNone(n["github_repo"])

    def test_pr_number_cap_applies_to_pr_namespace(self):
        """The implausibly-large cap (1_000_000) must apply uniformly
        regardless of namespace — a bug in only one branch lets
        garbage through."""
        from claude_statusline.cli import _normalize
        for huge in (1_000_000, 99_999_999):
            n = _normalize({"pr": {"number": huge}, "session_id": "x"})
            self.assertIsNone(n["github_pr_number"],
                "pr.number={} must be rejected as implausible".format(huge))

    def test_pr_number_cap_applies_to_github_namespace(self):
        from claude_statusline.cli import _normalize
        for huge in (1_000_000, 99_999_999):
            n = _normalize({"github": {"pr_number": huge}, "session_id": "x"})
            self.assertIsNone(n["github_pr_number"],
                "github.pr_number={} must be rejected as implausible".format(huge))

    def test_pr_number_string_coerced_in_pr_namespace(self):
        """JSON serializers sometimes stringify integers; pr.number
        must accept the string form via _safe_num."""
        from claude_statusline.cli import _normalize
        n = _normalize({"pr": {"number": "42"}, "session_id": "x"})
        self.assertEqual(n["github_pr_number"], 42)


class TestWorkspaceRepo(unittest.TestCase):
    """v0.6.3 reads `workspace.repo.{host, owner, name}` from the
    live-docs schema. Composes `owner/name` into the stable
    `github_repo` field name (v0.6.1 contract) so any custom-theme
    consumer of that field continues to work. `host` is captured
    separately for future use."""

    def test_workspace_repo_composes_owner_slash_name(self):
        from claude_statusline.cli import _normalize
        n = _normalize({
            "workspace": {"repo": {
                "host": "github.com",
                "owner": "anthropics",
                "name": "claude-code",
            }},
            "session_id": "x",
        })
        self.assertEqual(n["github_repo"], "anthropics/claude-code")
        self.assertEqual(n["github_repo_host"], "github.com")

    def test_workspace_repo_wins_over_github_repo(self):
        from claude_statusline.cli import _normalize
        n = _normalize({
            "workspace": {"repo": {"owner": "a", "name": "b"}},
            "github": {"repo": "x/y"},
            "session_id": "x",
        })
        self.assertEqual(n["github_repo"], "a/b")

    def test_github_repo_string_fallback(self):
        from claude_statusline.cli import _normalize
        n = _normalize({
            "github": {"repo": "anthropics/claude-code"},
            "session_id": "x",
        })
        self.assertEqual(n["github_repo"], "anthropics/claude-code")
        self.assertIsNone(n["github_repo_host"])

    def test_workspace_repo_partial_falls_through(self):
        """A workspace.repo missing owner OR name (incomplete) must
        fall back to github.repo rather than render a malformed
        `None/foo` or `foo/None` string."""
        from claude_statusline.cli import _normalize
        n = _normalize({
            "workspace": {"repo": {"name": "foo"}},  # no owner
            "github": {"repo": "x/y"},
            "session_id": "x",
        })
        self.assertEqual(n["github_repo"], "x/y")


class TestPRReviewStateCapture(unittest.TestCase):
    """v0.6.3 captures pr.review_state internally but does not
    render it (renderer ships in a separate release). Membership-
    check rejects malformed values so a downstream consumer never
    sees garbage."""

    def test_review_state_captured(self):
        from claude_statusline.cli import _normalize
        for state in ("approved", "pending", "changes_requested", "draft"):
            n = _normalize({
                "pr": {"number": 1, "review_state": state},
                "session_id": "x",
            })
            self.assertEqual(n["pr_review_state"], state,
                "{} should be accepted".format(state))

    def test_review_state_unknown_rejected(self):
        from claude_statusline.cli import _normalize
        n = _normalize({
            "pr": {"number": 1, "review_state": "rejected"},  # not in enum
            "session_id": "x",
        })
        self.assertIsNone(n["pr_review_state"])

    def test_review_state_non_string_rejected(self):
        from claude_statusline.cli import _normalize
        n = _normalize({
            "pr": {"number": 1, "review_state": 42},
            "session_id": "x",
        })
        self.assertIsNone(n["pr_review_state"])

    def test_review_state_absent_when_no_pr_object(self):
        from claude_statusline.cli import _normalize
        n = _normalize({"session_id": "x"})
        self.assertIsNone(n["pr_review_state"])


# ─── Workspace isinstance guard (v0.6.1 missed this site) ──────────


class TestWorkspaceIsinstanceGuard(unittest.TestCase):
    """v0.6.1 added isinstance guards for agent/cost/vim/github/
    worktree at _normalize but missed `workspace`. v0.6.3 closes
    the gap — a non-dict workspace value must not crash _normalize."""

    def test_workspace_none(self):
        from claude_statusline.cli import _normalize
        n = _normalize({"workspace": None, "session_id": "x"})
        self.assertEqual(n["project_name"], "")
        self.assertEqual(n["added_dirs_count"], 0)
        self.assertFalse(n["git_worktree"])

    def test_workspace_as_string(self):
        from claude_statusline.cli import _normalize
        n = _normalize({"workspace": "/path", "session_id": "x"})
        self.assertEqual(n["project_name"], "")

    def test_workspace_as_list(self):
        from claude_statusline.cli import _normalize
        n = _normalize({"workspace": ["x"], "session_id": "x"})
        self.assertEqual(n["project_name"], "")

    def test_workspace_as_int(self):
        from claude_statusline.cli import _normalize
        n = _normalize({"workspace": 42, "session_id": "x"})
        self.assertEqual(n["project_name"], "")

    def test_workspace_empty_dict(self):
        from claude_statusline.cli import _normalize
        n = _normalize({"workspace": {}, "session_id": "x"})
        self.assertEqual(n["project_name"], "")
        self.assertEqual(n["added_dirs_count"], 0)
        self.assertFalse(n["git_worktree"])

    def test_workspace_populated_dict_still_works(self):
        from claude_statusline.cli import _normalize
        n = _normalize({
            "workspace": {
                "project_dir": "/home/user/projects/myapp",
                "added_dirs": ["/x", "/y"],
                "git_worktree": True,
            },
            "session_id": "x",
        })
        self.assertEqual(n["project_name"], "myapp")
        self.assertEqual(n["added_dirs_count"], 2)
        self.assertTrue(n["git_worktree"])


# ─── Themes structural parity (kept from v0.6.2) ───────────────────


class TestEffortUltraThemeKeysRetained(unittest.TestCase):
    """The effort_ultra theme keys ship retained in v0.6.3 as
    documented dead surface — the ultra silent alias means the
    `if effort == "ultra"` branch in cli.py is now unreachable in
    practice (alias rewrites to xhigh before render), but a future
    Claude Code release that emits a truly distinct stored value
    could reactivate it. Removing the keys would be a public
    reversal best done separately, not inside the realignment.
    Pinning the keys here documents the intentional retention."""

    def test_every_theme_has_effort_ultra(self):
        from claude_statusline.themes import THEMES
        missing = [
            n for n, t in THEMES.items()
            if "effort_ultra" not in t.get("colors", {})
        ]
        self.assertEqual(missing, [],
            "themes missing effort_ultra: {}".format(missing))

    def test_effort_ultra_mirrors_effort_max(self):
        from claude_statusline.themes import THEMES
        for n, t in THEMES.items():
            c = t.get("colors", {})
            self.assertEqual(c.get("effort_ultra"), c.get("effort_max"),
                "theme {}: effort_ultra should mirror effort_max".format(n))


if __name__ == "__main__":
    unittest.main()
