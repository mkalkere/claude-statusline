"""Progress bar rendering with adaptive colors."""

from . import colors


def _bar_color(pct):
    """Return color code based on context usage percentage.

    Green: 0-60% (comfortable)
    Yellow: 61-85% (caution)
    Red: 86-100% (danger)
    """
    if pct <= 60:
        return colors.GREEN
    if pct <= 85:
        return colors.YELLOW
    return colors.RED


def render_bar(pct, width=20, theme=None, compaction_threshold=None):
    """Render a progress bar with adaptive coloring.

    Args:
        pct: Percentage (0-100) of context used.
        width: Character width of the bar.
        theme: Optional theme dict with 'bar_filled' and 'bar_empty' chars.
        compaction_threshold: Optional percentage (0-100) at which context
            compaction triggers. When set, the bar scales relative to this
            threshold so 100% of the bar = compaction point.

    Returns:
        Colored string like [████████░░░░░░░░░░░░]
    """
    if pct is None:
        return ""

    # Use raw percentage for color (reflects actual context fill)
    color = _bar_color(max(0, min(100, float(pct))))

    # Scale fill width relative to compaction threshold if configured
    if compaction_threshold and 0 < compaction_threshold <= 100:
        pct = (pct / compaction_threshold) * 100

    pct = max(0, min(100, int(pct)))

    filled_char = "█"
    empty_char = "░"
    left_bracket = "["
    right_bracket = "]"

    if theme:
        filled_char = theme.get("bar_filled", filled_char)
        empty_char = theme.get("bar_empty", empty_char)
        left_bracket = theme.get("bar_left", left_bracket)
        right_bracket = theme.get("bar_right", right_bracket)

    filled = int(width * pct / 100)
    empty = width - filled

    bar_content = colors.colorize(
        filled_char * filled, color
    ) + colors.colorize(
        empty_char * empty, colors.BRIGHT_BLACK
    )

    return "{}{}{}".format(left_bracket, bar_content, right_bracket)
