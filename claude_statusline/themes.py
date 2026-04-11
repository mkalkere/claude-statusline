"""Theme definitions for statusline rendering."""

import copy
import json
import os

from . import colors

THEMES = {
    "default": {
        "name": "default",
        "separator": " │ ",
        "bar_filled": "█",
        "bar_empty": "░",
        "bar_left": "[",
        "bar_right": "]",
        "line1": [
            "bar", "tokens", "cache", "cost", "budget", "burn", "ctx_warning",
        ],
        "line2": [
            "rate_limits", "context_size", "duration", "latency", "speed",
            "lines", "branch", "git_extras", "git_state", "commit_age",
            "tools", "sessions", "session_name",
            "vim", "agent", "worktree", "model", "output_style", "added_dirs",
            "git_worktree", "effort", "version", "cc_version", "clock",
        ],
        "colors": {
            "separator": colors.BRIGHT_BLACK,
            "label": colors.BRIGHT_BLACK,
            "value": colors.WHITE,
            "cost": colors.YELLOW,
            "branch_main": colors.GREEN,
            "branch_feature": colors.YELLOW,
            "warning": colors.BRIGHT_RED,
            "added": colors.GREEN,
            "removed": colors.RED,
            "agent": colors.CYAN,
            "vim_normal": colors.BLUE,
            "vim_insert": colors.GREEN,
            "model": colors.BRIGHT_MAGENTA,
            "latency": colors.CYAN,
            "sessions": colors.CYAN,
            "session_name": colors.CYAN,
            "version": colors.BRIGHT_BLACK,
            "cc_version": colors.BRIGHT_BLACK,
            "clock": colors.BRIGHT_BLACK,
            "git_stash": colors.YELLOW,
            "git_sync": colors.BRIGHT_BLACK,
            "rate_limit_ok": colors.GREEN,
            "rate_limit_warn": colors.YELLOW,
            "rate_limit_danger": colors.BRIGHT_RED,
            "output_style": colors.BRIGHT_BLACK,
            "added_dirs": colors.BRIGHT_BLACK,
            "effort_high": colors.BRIGHT_MAGENTA,
            "effort_low": colors.BRIGHT_BLACK,
            "git_worktree": colors.YELLOW,
            "speed": colors.CYAN,
            "git_conflict": colors.BRIGHT_RED,
            "git_merge": colors.YELLOW,
            "commit_age": colors.BRIGHT_BLACK,
        },
    },
    # Minimal shows only essential metrics — see line1/line2 lists below
    # for exactly what's included. All other sections are omitted.
    "minimal": {
        "name": "minimal",
        "separator": " ",
        "bar_filled": "●",
        "bar_empty": "·",
        "bar_left": "",
        "bar_right": "",
        "line1": [
            "bar", "tokens", "cost", "rate_limits", "ctx_warning",
        ],
        "line2": [
            "duration", "latency", "branch", "sessions", "session_name",
            "model", "effort", "clock",
        ],
        "colors": {
            "separator": colors.BRIGHT_BLACK,
            "label": colors.BRIGHT_BLACK,
            "value": colors.WHITE,
            "cost": colors.YELLOW,
            "branch_main": colors.GREEN,
            "branch_feature": colors.YELLOW,
            "warning": colors.BRIGHT_RED,
            "added": colors.GREEN,
            "removed": colors.RED,
            "agent": colors.CYAN,
            "vim_normal": colors.BLUE,
            "vim_insert": colors.GREEN,
            "model": colors.BRIGHT_MAGENTA,
            "latency": colors.CYAN,
            "sessions": colors.CYAN,
            "session_name": colors.CYAN,
            "version": colors.BRIGHT_BLACK,
            "cc_version": colors.BRIGHT_BLACK,
            "clock": colors.BRIGHT_BLACK,
            "git_stash": colors.YELLOW,
            "git_sync": colors.BRIGHT_BLACK,
            "rate_limit_ok": colors.GREEN,
            "rate_limit_warn": colors.YELLOW,
            "rate_limit_danger": colors.BRIGHT_RED,
            "output_style": colors.BRIGHT_BLACK,
            "added_dirs": colors.BRIGHT_BLACK,
            "effort_high": colors.BRIGHT_MAGENTA,
            "effort_low": colors.BRIGHT_BLACK,
            "git_worktree": colors.YELLOW,
            "speed": colors.CYAN,
            "git_conflict": colors.BRIGHT_RED,
            "git_merge": colors.YELLOW,
            "commit_age": colors.BRIGHT_BLACK,
        },
    },
    "powerline": {
        "name": "powerline",
        "separator": " \ue0b0 ",
        "bar_filled": "█",
        "bar_empty": "░",
        "bar_left": "",
        "bar_right": "",
        "line1": [
            "bar", "tokens", "cache", "cost", "budget", "burn", "ctx_warning",
        ],
        "line2": [
            "rate_limits", "context_size", "duration", "latency", "speed",
            "lines", "branch", "git_extras", "git_state", "commit_age",
            "tools", "sessions", "session_name",
            "vim", "agent", "worktree", "model", "output_style", "added_dirs",
            "git_worktree", "effort", "version", "cc_version", "clock",
        ],
        "colors": {
            "separator": colors.BRIGHT_BLACK,
            "label": colors.BRIGHT_BLACK,
            "value": colors.WHITE,
            "cost": colors.YELLOW,
            "branch_main": colors.GREEN,
            "branch_feature": colors.YELLOW,
            "warning": colors.BRIGHT_RED,
            "added": colors.GREEN,
            "removed": colors.RED,
            "agent": colors.CYAN,
            "vim_normal": colors.BLUE,
            "vim_insert": colors.GREEN,
            "model": colors.BRIGHT_MAGENTA,
            "latency": colors.CYAN,
            "sessions": colors.CYAN,
            "version": colors.BRIGHT_BLACK,
            "clock": colors.BRIGHT_BLACK,
            "git_stash": colors.YELLOW,
            "git_sync": colors.BRIGHT_BLACK,
            "session_name": colors.CYAN,
            "cc_version": colors.BRIGHT_BLACK,
            "rate_limit_ok": colors.GREEN,
            "rate_limit_warn": colors.YELLOW,
            "rate_limit_danger": colors.BRIGHT_RED,
            "output_style": colors.BRIGHT_BLACK,
            "added_dirs": colors.BRIGHT_BLACK,
            "effort_high": colors.BRIGHT_MAGENTA,
            "effort_low": colors.BRIGHT_BLACK,
            "git_worktree": colors.YELLOW,
            "speed": colors.CYAN,
            "git_conflict": colors.BRIGHT_RED,
            "git_merge": colors.YELLOW,
            "commit_age": colors.BRIGHT_BLACK,
        },
    },
    "nord": {
        "name": "nord",
        "separator": " │ ",
        "bar_filled": "█",
        "bar_empty": "░",
        "bar_left": "[",
        "bar_right": "]",
        "line1": [
            "bar", "tokens", "cache", "cost", "budget", "burn", "ctx_warning",
        ],
        "line2": [
            "rate_limits", "context_size", "duration", "latency", "speed",
            "lines", "branch", "git_extras", "git_state", "commit_age",
            "tools", "sessions", "session_name",
            "vim", "agent", "worktree", "model", "output_style", "added_dirs",
            "git_worktree", "effort", "version", "cc_version", "clock",
        ],
        "colors": {
            "separator": colors.BRIGHT_BLACK,
            "label": colors.BRIGHT_BLACK,
            "value": colors.BRIGHT_CYAN,
            "cost": colors.BRIGHT_YELLOW,
            "branch_main": colors.CYAN,
            "branch_feature": colors.BRIGHT_BLUE,
            "warning": colors.BRIGHT_RED,
            "added": colors.GREEN,
            "removed": colors.RED,
            "agent": colors.BRIGHT_CYAN,
            "vim_normal": colors.BRIGHT_BLUE,
            "vim_insert": colors.CYAN,
            "model": colors.BRIGHT_CYAN,
            "latency": colors.BRIGHT_BLUE,
            "sessions": colors.BRIGHT_CYAN,
            "version": colors.BRIGHT_BLACK,
            "clock": colors.BRIGHT_BLACK,
            "git_stash": colors.BRIGHT_YELLOW,
            "git_sync": colors.BRIGHT_BLACK,
            "session_name": colors.CYAN,
            "cc_version": colors.BRIGHT_BLACK,
            "rate_limit_ok": colors.GREEN,
            "rate_limit_warn": colors.YELLOW,
            "rate_limit_danger": colors.BRIGHT_RED,
            "output_style": colors.BRIGHT_BLACK,
            "added_dirs": colors.BRIGHT_BLACK,
            "effort_high": colors.BRIGHT_MAGENTA,
            "effort_low": colors.BRIGHT_BLACK,
            "git_worktree": colors.YELLOW,
            "speed": colors.CYAN,
            "git_conflict": colors.BRIGHT_RED,
            "git_merge": colors.YELLOW,
            "commit_age": colors.BRIGHT_BLACK,
        },
    },
    "tokyo-night": {
        "name": "tokyo-night",
        "separator": " │ ",
        "bar_filled": "█",
        "bar_empty": "░",
        "bar_left": "[",
        "bar_right": "]",
        "line1": [
            "bar", "tokens", "cache", "cost", "budget", "burn", "ctx_warning",
        ],
        "line2": [
            "rate_limits", "context_size", "duration", "latency", "speed",
            "lines", "branch", "git_extras", "git_state", "commit_age",
            "tools", "sessions", "session_name",
            "vim", "agent", "worktree", "model", "output_style", "added_dirs",
            "git_worktree", "effort", "version", "cc_version", "clock",
        ],
        "colors": {
            "separator": colors.BRIGHT_BLACK,
            "label": colors.BRIGHT_BLACK,
            "value": colors.BRIGHT_BLUE,
            "cost": colors.BRIGHT_YELLOW,
            "branch_main": colors.GREEN,
            "branch_feature": colors.BRIGHT_MAGENTA,
            "warning": colors.BRIGHT_RED,
            "added": colors.GREEN,
            "removed": colors.RED,
            "agent": colors.BRIGHT_CYAN,
            "vim_normal": colors.BRIGHT_BLUE,
            "vim_insert": colors.GREEN,
            "model": colors.BRIGHT_MAGENTA,
            "latency": colors.BRIGHT_CYAN,
            "sessions": colors.BRIGHT_CYAN,
            "version": colors.BRIGHT_BLACK,
            "clock": colors.BRIGHT_BLACK,
            "git_stash": colors.BRIGHT_YELLOW,
            "git_sync": colors.BRIGHT_BLACK,
            "session_name": colors.CYAN,
            "cc_version": colors.BRIGHT_BLACK,
            "rate_limit_ok": colors.GREEN,
            "rate_limit_warn": colors.YELLOW,
            "rate_limit_danger": colors.BRIGHT_RED,
            "output_style": colors.BRIGHT_BLACK,
            "added_dirs": colors.BRIGHT_BLACK,
            "effort_high": colors.BRIGHT_MAGENTA,
            "effort_low": colors.BRIGHT_BLACK,
            "git_worktree": colors.YELLOW,
            "speed": colors.CYAN,
            "git_conflict": colors.BRIGHT_RED,
            "git_merge": colors.YELLOW,
            "commit_age": colors.BRIGHT_BLACK,
        },
    },
    "gruvbox": {
        "name": "gruvbox",
        "separator": " │ ",
        "bar_filled": "█",
        "bar_empty": "░",
        "bar_left": "[",
        "bar_right": "]",
        "line1": [
            "bar", "tokens", "cache", "cost", "budget", "burn", "ctx_warning",
        ],
        "line2": [
            "rate_limits", "context_size", "duration", "latency", "speed",
            "lines", "branch", "git_extras", "git_state", "commit_age",
            "tools", "sessions", "session_name",
            "vim", "agent", "worktree", "model", "output_style", "added_dirs",
            "git_worktree", "effort", "version", "cc_version", "clock",
        ],
        "colors": {
            "separator": colors.BRIGHT_BLACK,
            "label": colors.BRIGHT_BLACK,
            "value": colors.BRIGHT_YELLOW,
            "cost": colors.YELLOW,
            "branch_main": colors.GREEN,
            "branch_feature": colors.YELLOW,
            "warning": colors.BRIGHT_RED,
            "added": colors.GREEN,
            "removed": colors.RED,
            "agent": colors.BRIGHT_CYAN,
            "vim_normal": colors.BRIGHT_BLUE,
            "vim_insert": colors.BRIGHT_GREEN,
            "model": colors.BRIGHT_MAGENTA,
            "latency": colors.CYAN,
            "sessions": colors.BRIGHT_CYAN,
            "version": colors.BRIGHT_BLACK,
            "clock": colors.BRIGHT_BLACK,
            "git_stash": colors.YELLOW,
            "git_sync": colors.BRIGHT_BLACK,
            "session_name": colors.CYAN,
            "cc_version": colors.BRIGHT_BLACK,
            "rate_limit_ok": colors.GREEN,
            "rate_limit_warn": colors.YELLOW,
            "rate_limit_danger": colors.BRIGHT_RED,
            "output_style": colors.BRIGHT_BLACK,
            "added_dirs": colors.BRIGHT_BLACK,
            "effort_high": colors.BRIGHT_MAGENTA,
            "effort_low": colors.BRIGHT_BLACK,
            "git_worktree": colors.YELLOW,
            "speed": colors.CYAN,
            "git_conflict": colors.BRIGHT_RED,
            "git_merge": colors.YELLOW,
            "commit_age": colors.BRIGHT_BLACK,
        },
    },
    "rose-pine": {
        "name": "rose-pine",
        "separator": " │ ",
        "bar_filled": "█",
        "bar_empty": "░",
        "bar_left": "[",
        "bar_right": "]",
        "line1": [
            "bar", "tokens", "cache", "cost", "budget", "burn", "ctx_warning",
        ],
        "line2": [
            "rate_limits", "context_size", "duration", "latency", "speed",
            "lines", "branch", "git_extras", "git_state", "commit_age",
            "tools", "sessions", "session_name",
            "vim", "agent", "worktree", "model", "output_style", "added_dirs",
            "git_worktree", "effort", "version", "cc_version", "clock",
        ],
        "colors": {
            "separator": colors.BRIGHT_BLACK,
            "label": colors.BRIGHT_BLACK,
            "value": colors.BRIGHT_WHITE,
            "cost": colors.BRIGHT_YELLOW,
            "branch_main": colors.GREEN,
            "branch_feature": colors.MAGENTA,
            "warning": colors.BRIGHT_RED,
            "added": colors.GREEN,
            "removed": colors.RED,
            "agent": colors.CYAN,
            "vim_normal": colors.MAGENTA,
            "vim_insert": colors.GREEN,
            "model": colors.MAGENTA,
            "latency": colors.CYAN,
            "sessions": colors.CYAN,
            "version": colors.BRIGHT_BLACK,
            "clock": colors.BRIGHT_BLACK,
            "git_stash": colors.YELLOW,
            "git_sync": colors.BRIGHT_BLACK,
            "session_name": colors.CYAN,
            "cc_version": colors.BRIGHT_BLACK,
            "rate_limit_ok": colors.GREEN,
            "rate_limit_warn": colors.YELLOW,
            "rate_limit_danger": colors.BRIGHT_RED,
            "output_style": colors.BRIGHT_BLACK,
            "added_dirs": colors.BRIGHT_BLACK,
            "effort_high": colors.BRIGHT_MAGENTA,
            "effort_low": colors.BRIGHT_BLACK,
            "git_worktree": colors.YELLOW,
            "speed": colors.CYAN,
            "git_conflict": colors.BRIGHT_RED,
            "git_merge": colors.YELLOW,
            "commit_age": colors.BRIGHT_BLACK,
        },
    },
    # Focus: single-line theme for minimal vertical footprint.
    # Shows only the most essential at-a-glance metrics.
    "focus": {
        "name": "focus",
        "separator": " │ ",
        "bar_filled": "█",
        "bar_empty": "░",
        "bar_left": "[",
        "bar_right": "]",
        "bar_width": 12,
        "line1": [
            "bar", "cost", "rate_limits", "branch", "effort", "clock",
        ],
        "line2": [],
        "colors": {
            "separator": colors.BRIGHT_BLACK,
            "label": colors.BRIGHT_BLACK,
            "value": colors.WHITE,
            "cost": colors.YELLOW,
            "branch_main": colors.GREEN,
            "branch_feature": colors.YELLOW,
            "warning": colors.BRIGHT_RED,
            "added": colors.GREEN,
            "removed": colors.RED,
            "agent": colors.CYAN,
            "vim_normal": colors.BLUE,
            "vim_insert": colors.GREEN,
            "model": colors.BRIGHT_MAGENTA,
            "latency": colors.CYAN,
            "sessions": colors.CYAN,
            "session_name": colors.CYAN,
            "version": colors.BRIGHT_BLACK,
            "cc_version": colors.BRIGHT_BLACK,
            "clock": colors.BRIGHT_BLACK,
            "git_stash": colors.YELLOW,
            "git_sync": colors.BRIGHT_BLACK,
            "rate_limit_ok": colors.GREEN,
            "rate_limit_warn": colors.YELLOW,
            "rate_limit_danger": colors.BRIGHT_RED,
            "output_style": colors.BRIGHT_BLACK,
            "added_dirs": colors.BRIGHT_BLACK,
            "effort_high": colors.BRIGHT_MAGENTA,
            "effort_low": colors.BRIGHT_BLACK,
            "git_worktree": colors.YELLOW,
            "speed": colors.CYAN,
            "git_conflict": colors.BRIGHT_RED,
            "git_merge": colors.YELLOW,
            "commit_age": colors.BRIGHT_BLACK,
        },
    },
}


# Map of color name strings to ANSI codes for user theme files.
_COLOR_MAP = {
    "black": colors.BLACK,
    "red": colors.RED,
    "green": colors.GREEN,
    "yellow": colors.YELLOW,
    "blue": colors.BLUE,
    "magenta": colors.MAGENTA,
    "cyan": colors.CYAN,
    "white": colors.WHITE,
    "bright_black": colors.BRIGHT_BLACK,
    "bright_red": colors.BRIGHT_RED,
    "bright_green": colors.BRIGHT_GREEN,
    "bright_yellow": colors.BRIGHT_YELLOW,
    "bright_blue": colors.BRIGHT_BLUE,
    "bright_magenta": colors.BRIGHT_MAGENTA,
    "bright_cyan": colors.BRIGHT_CYAN,
    "bright_white": colors.BRIGHT_WHITE,
    "bold": colors.BOLD,
    "reset": colors.RESET,
}


def _resolve_colors(color_dict):
    """Convert color name strings to ANSI codes."""
    resolved = {}
    for key, value in color_dict.items():
        if isinstance(value, str):
            resolved[key] = _COLOR_MAP.get(value.lower(), value)
        else:
            resolved[key] = value
    return resolved


def _custom_theme_path():
    """Return the path to the user custom theme file."""
    home = os.path.expanduser("~")
    return os.path.join(home, ".claude", "claude-status-theme.json")


def load_custom_theme():
    """Load user-defined custom theme from ~/.claude/claude-status-theme.json.

    The JSON file can override any theme keys. Missing keys are filled
    from the 'default' built-in theme. Color values can be color name
    strings like "green", "bright_cyan", etc.

    Returns:
        Theme dict if file exists and is valid, None otherwise.
    """
    path = _custom_theme_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            user = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    if not isinstance(user, dict):
        return None

    # Start from a copy of the base theme the user chose (or default)
    base_name = user.get("base", "default")
    base = THEMES.get(base_name, THEMES["default"])
    theme = copy.deepcopy(base)
    theme["name"] = "custom"

    # Override simple keys
    for key in ("separator", "bar_filled", "bar_empty", "bar_left", "bar_right"):
        if key in user:
            theme[key] = user[key]

    # Override line layout
    if "line1" in user and isinstance(user["line1"], list):
        theme["line1"] = user["line1"]
    if "line2" in user and isinstance(user["line2"], list):
        theme["line2"] = user["line2"]

    # Override / merge colors
    if "colors" in user and isinstance(user["colors"], dict):
        resolved = _resolve_colors(user["colors"])
        theme["colors"].update(resolved)

    return theme


def get_theme(name):
    """Get theme by name, defaulting to 'default'.

    If name is 'custom', attempts to load from the user theme file.
    """
    if name == "custom":
        custom = load_custom_theme()
        if custom:
            return custom
        import sys
        path = _custom_theme_path()
        if os.path.isfile(path):
            print("Warning: could not load custom theme from {}".format(path),
                  file=sys.stderr)
    return THEMES.get(name, THEMES["default"])
