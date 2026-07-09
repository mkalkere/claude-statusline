"""Formatting functions for tokens, cost, duration, and burn rate."""

import math
import time

# Minimum session duration before a $/hr projection is shown. A
# session's first seconds extrapolate absurdly (a $0.05 startup burst
# over 8s "projects" to $22/hr), so the cost_rate section stays hidden
# until the average has something real behind it. One minute is the
# smallest window where the session-average starts being meaningful;
# it also matches the intuition that a projection needs history.
_COST_RATE_MIN_DURATION_MS = 60_000


def fmt_tokens(n):
    """Format token count with human-readable suffix.

    0-999: exact number
    1K-999K: with K suffix (1 decimal if < 10K, trailing .0 stripped)
    1M+: with M suffix (1 decimal if < 10M, trailing .0 stripped)
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
        formatted = "{:.1f}".format(val)
        # Strip trailing zero after decimal: 1.0 → 1, but keep 1.5 —
        # same rule as the K branch above. Matters since 1M-context
        # models made "1.0M"-shaped values an every-render sight.
        if formatted.endswith("0") and "." in formatted:
            formatted = formatted[:-1].rstrip(".")
        return formatted + "M"
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


def fmt_cost_rate(cost, duration_ms):
    """Project session cost to dollars per hour: "$3.6/hr".

    Session-average by design: total cost over total wall-clock time,
    INCLUDING idle time — this answers "what is this session costing
    me per hour of it being open", not "what would the current burst
    cost if sustained". (A windowed recent-activity rate is a possible
    future refinement; it needs cached samples and is deliberately out
    of scope here.)

    Returns "" (section hidden) when the projection would be
    meaningless or the inputs are garbage:
      - cost or duration missing / non-numeric / NaN / Infinity
      - cost <= 0 (a zero session projects to $0/hr — noise)
      - duration under _COST_RATE_MIN_DURATION_MS (early-session
        extrapolation is absurd; see the constant's comment)
      - rate below fmt_cost's rendering resolution (< $0.0005/hr),
        which would show a zero-looking "0c/hr" chip for a positive
        cost — same noise the zero gate exists to suppress

    Reuses fmt_cost for the dollar formatting so rate and cost render
    with identical conventions (cents under a penny, $0.XX under a
    dollar, one decimal under $10, whole dollars above).
    """
    try:
        c = float(cost)
        d = float(duration_ms)
    except (TypeError, ValueError):
        return ""
    if not (math.isfinite(c) and math.isfinite(d)):
        return ""
    if c <= 0 or d < _COST_RATE_MIN_DURATION_MS:
        return ""
    rate = c / (d / 3_600_000)
    if not math.isfinite(rate):
        return ""
    # Below fmt_cost's rendering resolution the chip would read
    # "0c/hr" — a zero-looking projection for a positive cost, which
    # contradicts the "zero projection is noise" gate above. fmt_cost's
    # cents branch shows one decimal, so anything under half of 0.1c
    # (rate < $0.0005/hr) rounds to "0.0" and gets hidden instead.
    if rate < 0.0005:
        return ""
    return fmt_cost(rate) + "/hr"


def fmt_lines(added, removed):
    """Format lines changed in git-diff style."""
    parts = []
    if added:
        parts.append("+{}".format(added))
    if removed:
        parts.append("-{}".format(removed))
    return " ".join(parts) if parts else ""


def fmt_cache_pct(cache_read, total_input):
    """Format prompt cache hit ratio as a percentage.

    Called with total_input = cache_read + cache_creation + input
    (everything that could have been served from cache). The result
    is "of the cacheable prompt input, how much actually hit the
    cache" — close to 100% means the dynamic portion of each prompt
    is small relative to the cached prefix.
    """
    if not cache_read or not total_input or total_input <= 0:
        return ""
    pct = (cache_read / total_input) * 100
    return "{}%".format(int(pct))


def fmt_countdown(resets_at_ms):
    """Format a reset countdown from a Unix epoch timestamp (ms).

    Returns human-readable time remaining like '~2h15m', '~45m', or '~5m'.
    Returns empty string if the timestamp is in the past, invalid, or
    less than 1 second remaining.
    """
    if resets_at_ms is None:
        return ""
    try:
        now_ms = int(time.time() * 1000)
        remaining_ms = int(resets_at_ms) - now_ms
    except (TypeError, ValueError, OverflowError):
        # OverflowError: int(float("inf")). Since v0.11.0 _safe_num
        # rejects non-finite values upstream so inf can't reach here
        # from stdin — but this local catch pins the hole shut
        # independently, so a future loosening of _safe_num can't
        # silently reintroduce a whole-line crash. (Same tuple as
        # _clean_pr_number's handler in cli.py.)
        return ""
    if remaining_ms < 1000:
        return ""
    return "~{}".format(fmt_duration(remaining_ms))


def fmt_speed(total_tokens, api_duration_ms):
    """Format token throughput as tokens per second.

    Returns formatted string like '1.2K/s' or '850/s'.
    Returns empty string if data is insufficient.
    """
    if total_tokens is None or api_duration_ms is None:
        return ""
    if api_duration_ms <= 0:
        return ""
    seconds = api_duration_ms / 1000
    if seconds <= 0:
        return ""
    tps = total_tokens / seconds
    return "{}/s".format(fmt_tokens(int(tps)))
