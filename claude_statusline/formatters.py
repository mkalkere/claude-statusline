"""Formatting functions for tokens, cost, duration, and burn rate."""


def fmt_tokens(n):
    """Format token count with human-readable suffix.

    0-999: exact number
    1K-999K: with K suffix (1 decimal if < 10K)
    1M+: with M suffix (1 decimal if < 10M)
    """
    if n is None:
        return "?"
    n = int(n)
    if n < 1000:
        return str(n)
    if n < 10_000:
        val = n / 1000
        formatted = "{:.1f}".format(val)
        # Strip trailing zero after decimal: 1.0 → 1, but keep 1.5
        if formatted.endswith("0") and "." in formatted:
            formatted = formatted[:-1].rstrip(".")
        return formatted + "K"
    if n < 1_000_000:
        val = n / 1000
        return "{}K".format(int(val))
    if n < 10_000_000:
        val = n / 1_000_000
        return "{:.1f}M".format(val)
    val = n / 1_000_000
    return "{}M".format(int(val))


def fmt_cost(cost):
    """Format cost in USD.

    < $0.01: show as cents (e.g., 0.5c)
    < $1.00: show as $0.XX
    >= $1.00: show as $X.X or $XX
    """
    if cost is None:
        return "?"
    cost = float(cost)
    if cost < 0.01:
        cents = cost * 100
        formatted = "{:.1f}".format(cents)
        if formatted.endswith("0") and "." in formatted:
            formatted = formatted[:-1].rstrip(".")
        return formatted + "c"
    if cost < 1.0:
        return "${:.2f}".format(cost)
    if cost < 10.0:
        return "${:.1f}".format(cost)
    return "${}".format(int(cost))


def fmt_duration(ms):
    """Format duration from milliseconds to human-readable.

    0-59s: Xs
    1-59m: XmYYs
    1h+: XhYYm
    """
    if ms is None:
        return "?"
    ms = int(ms)
    total_seconds = ms // 1000
    if total_seconds < 60:
        return "{}s".format(total_seconds)
    if total_seconds < 3600:
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return "{}m{:02d}s".format(minutes, seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    return "{}h{:02d}m".format(hours, minutes)


def fmt_burn_rate(total_tokens, duration_ms):
    """Calculate and format burn rate as tokens/min.

    Returns formatted string like '2.5K/min' or '150/min'.
    """
    if total_tokens is None or duration_ms is None:
        return "?"
    if duration_ms <= 0:
        return "?"
    minutes = duration_ms / 60_000
    if minutes <= 0:
        return "?"
    rate = total_tokens / minutes
    return "{}/min".format(fmt_tokens(int(rate)))


def fmt_lines(added, removed):
    """Format lines changed in git-diff style."""
    parts = []
    if added:
        parts.append("+{}".format(added))
    if removed:
        parts.append("-{}".format(removed))
    return " ".join(parts) if parts else ""


def fmt_cache_pct(cache_read, total_input):
    """Format cache efficiency as percentage."""
    if not cache_read or not total_input or total_input <= 0:
        return ""
    pct = (cache_read / total_input) * 100
    return "{}%".format(int(pct))
