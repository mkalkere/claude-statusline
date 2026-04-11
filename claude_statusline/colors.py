"""ANSI color constants and helpers."""

import os

# Respect NO_COLOR (https://no-color.org/) and FORCE_COLOR standards.
# NO_COLOR: any non-empty value suppresses ANSI codes.
# FORCE_COLOR: overrides NO_COLOR to force color output.
_NO_COLOR = bool(os.environ.get("NO_COLOR")) and not os.environ.get("FORCE_COLOR")

# Reset
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

# Foreground colors
BLACK = "\033[30m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"

# Bright foreground
BRIGHT_BLACK = "\033[90m"
BRIGHT_RED = "\033[91m"
BRIGHT_GREEN = "\033[92m"
BRIGHT_YELLOW = "\033[93m"
BRIGHT_BLUE = "\033[94m"
BRIGHT_MAGENTA = "\033[95m"
BRIGHT_CYAN = "\033[96m"
BRIGHT_WHITE = "\033[97m"

# Background colors
BG_BLACK = "\033[40m"
BG_RED = "\033[41m"
BG_GREEN = "\033[42m"
BG_YELLOW = "\033[43m"
BG_BLUE = "\033[44m"
BG_MAGENTA = "\033[45m"
BG_CYAN = "\033[46m"
BG_WHITE = "\033[47m"

# Bright background
BG_BRIGHT_BLACK = "\033[100m"
BG_BRIGHT_RED = "\033[101m"
BG_BRIGHT_GREEN = "\033[102m"


def colorize(text, *codes):
    """Wrap text with ANSI color codes and reset.

    Respects NO_COLOR standard — returns plain text when NO_COLOR is set.
    """
    if not text:
        return ""
    if _NO_COLOR:
        return str(text)
    return "".join(codes) + str(text) + RESET
