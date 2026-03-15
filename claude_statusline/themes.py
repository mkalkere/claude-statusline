"""Theme definitions for statusline rendering."""

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
            "bar", "tokens", "cache", "cost", "burn", "context_size", "ctx_warning",
        ],
        "line2": [
            "duration", "lines", "branch", "vim", "agent", "worktree",
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
        },
    },
    "minimal": {
        "name": "minimal",
        "separator": " ",
        "bar_filled": "●",
        "bar_empty": "·",
        "bar_left": "",
        "bar_right": "",
        "line1": [
            "bar", "tokens", "cost", "ctx_warning",
        ],
        "line2": [
            "duration", "branch",
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
            "bar", "tokens", "cache", "cost", "burn", "context_size", "ctx_warning",
        ],
        "line2": [
            "duration", "lines", "branch", "vim", "agent", "worktree",
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
        },
    },
}


def get_theme(name):
    """Get theme by name, defaulting to 'default'."""
    return THEMES.get(name, THEMES["default"])
