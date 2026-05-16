"""Session analytics — daily cost, session count, tool calls.

Reads ~/.claude/ data files to provide aggregate metrics across sessions.
Uses file-based caching to avoid expensive filesystem scans on every render.
"""

import hashlib
import json
import os
import re
import tempfile
import time

_CACHE_TTL = 30  # seconds — longer than git cache since this is heavier
_TOOL_CACHE_TTL = 10  # seconds — shorter for active session metrics
_ACTIVITY_CACHE_TTL = 5  # seconds — shortest, this metric is "right now"

# Maximum bytes to tail-read from the session transcript JSONL when
# counting tool calls since the last user message. 64 KiB is the
# first attempt; if the tail doesn't reach back to a user message we
# retry with the expanded cap below. The two-step strategy keeps the
# render hot path cheap for typical turns (single small reads) but
# still recovers a correct count when one assistant turn produced
# very large output (e.g. a long tool_result block).
_TRANSCRIPT_TAIL_BYTES = 64 * 1024
# Expanded tail when the initial read missed the preceding user
# message. 1 MiB comfortably covers a single turn that contains
# multiple ~100 KiB tool_result blocks — rare but real. Going wider
# would let pathological transcripts dominate render latency, so we
# cap here and accept undercount in that extreme edge.
_TRANSCRIPT_TAIL_BYTES_EXPANDED = 1024 * 1024

_CLAUDE_DIR = os.path.join(os.path.expanduser("~"), ".claude")
_SESSIONS_DIR = os.path.join(_CLAUDE_DIR, "sessions")
_PROJECTS_DIR = os.path.join(_CLAUDE_DIR, "projects")

# Valid session IDs contain only alphanumeric chars, hyphens, and underscores.
_SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _cache_dir():
    """Return a user-scoped cache directory to avoid multi-user collisions."""
    user_hash = hashlib.md5(
        os.path.expanduser("~").encode("utf-8", "replace")
    ).hexdigest()[:8]
    path = os.path.join(tempfile.gettempdir(), "claude_sl_{}".format(user_hash))
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        return tempfile.gettempdir()
    return path


def _cache_path(name):
    """Return a cache file path for a named metric."""
    return os.path.join(_cache_dir(), name)


def _read_cache(name, ttl=None):
    """Read a cached JSON value if still fresh."""
    try:
        path = _cache_path(name)
        stat = os.stat(path)
        if time.time() - stat.st_mtime > (ttl or _CACHE_TTL):
            return None
        with open(path, "r") as f:
            return json.load(f)
    except (OSError, IOError, json.JSONDecodeError, ValueError):
        return None


_last_cleanup = 0


def _write_cache(name, value):
    """Write a JSON value to the named cache file atomically.

    Periodically cleans up stale cache files (at most once per hour).
    """
    global _last_cleanup
    target = _cache_path(name)
    tmp = target + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(value, f)
        os.replace(tmp, target)
    except (OSError, IOError):
        try:
            os.unlink(tmp)
        except OSError:
            pass

    # Periodic cleanup (at most once per hour)
    now = time.time()
    if now - _last_cleanup > 3600:
        _last_cleanup = now
        _cleanup_stale_cache()


def _cleanup_stale_cache():
    """Remove cache files older than 2 days to prevent accumulation."""
    try:
        cache_dir = _cache_dir()
        now = time.time()
        for entry in os.scandir(cache_dir):
            if entry.is_file() and not entry.name.endswith(".tmp"):
                try:
                    if now - entry.stat().st_mtime > 172800:  # 2 days
                        os.unlink(entry.path)
                except OSError:
                    pass
    except OSError:
        pass


def _today_str():
    """Return today's date as YYYY-MM-DD string."""
    t = time.localtime()
    return "{:04d}-{:02d}-{:02d}".format(t.tm_year, t.tm_mon, t.tm_mday)


def get_today_session_count():
    """Count sessions started today by reading ~/.claude/sessions/*.json.

    Each file contains a JSON object with a 'startedAt' timestamp (ms epoch).
    Uses os.scandir with mtime filtering to skip stale files efficiently.

    Returns:
        Number of sessions started today, or 0 on error.
    """
    today = _today_str()
    cache_key = "sessions_{}".format(today)
    cached = _read_cache(cache_key)
    if cached is not None:
        return cached.get("count", 0)

    count = 0

    try:
        if not os.path.isdir(_SESSIONS_DIR):
            _write_cache(cache_key, {"count": 0})
            return 0

        now = time.time()
        for entry in os.scandir(_SESSIONS_DIR):
            if not entry.name.endswith(".json") or not entry.is_file():
                continue
            # Skip files not modified in the last 24h
            try:
                if now - entry.stat().st_mtime > 86400:
                    continue
            except OSError:
                continue
            try:
                with open(entry.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                started_at = data.get("startedAt")
                if started_at:
                    session_date = time.strftime(
                        "%Y-%m-%d", time.localtime(started_at / 1000)
                    )
                    if session_date == today:
                        count += 1
            except (json.JSONDecodeError, OSError, IOError,
                    ValueError, TypeError, AttributeError):
                continue
    except OSError:
        pass

    _write_cache(cache_key, {"count": count})
    return count


def get_session_tool_count(session_id):
    """Count tool_use entries in a session's JSONL file.

    Scans all project directories for the session JSONL and counts
    lines containing tool_use content.

    Args:
        session_id: The session UUID string.

    Returns:
        Number of tool calls in the session, or 0 if not found.
    """
    if not session_id:
        return 0

    # Validate session_id to prevent path traversal
    if not _SESSION_ID_RE.match(session_id):
        return 0

    cache_key = "tools_{}".format(
        hashlib.md5(session_id.encode("utf-8", errors="replace")).hexdigest()[:12]
    )
    cached = _read_cache(cache_key, ttl=_TOOL_CACHE_TTL)
    if cached is not None:
        return cached.get("count", 0)

    count = 0
    jsonl_name = "{}.jsonl".format(session_id)

    try:
        if not os.path.isdir(_PROJECTS_DIR):
            return 0

        for project in os.listdir(_PROJECTS_DIR):
            fpath = os.path.join(_PROJECTS_DIR, project, jsonl_name)
            if os.path.isfile(fpath):
                try:
                    with open(fpath, "r", encoding="utf-8",
                              errors="replace") as f:
                        for line in f:
                            # Quick pre-filter before expensive JSON parse
                            if '"tool_use"' not in line:
                                continue
                            try:
                                entry = json.loads(line)
                            except (json.JSONDecodeError, ValueError):
                                continue
                            # Count tool_use in message content array
                            msg = entry.get("message") or {}
                            content = msg.get("content")
                            if isinstance(content, list):
                                for block in content:
                                    if (isinstance(block, dict)
                                            and block.get("type") == "tool_use"):
                                        count += 1
                except (OSError, IOError):
                    pass
                break  # Session only exists in one project
    except OSError:
        pass

    _write_cache(cache_key, {"count": count})
    return count


def get_session_activity_count(transcript_path):
    """Count tool_use entries in the *current assistant turn* of a session.

    Differs from ``get_session_tool_count`` (which counts the whole
    session): this counts only since the most recent ``role: "user"``
    line, so it answers "how many tool calls is the assistant making
    *right now*." The count resets to 0 when the user sends the next
    message and ticks up as the assistant uses tools to respond.

    Reads only the tail of the transcript file (last
    ``_TRANSCRIPT_TAIL_BYTES``), which:
      - keeps the render hot path in single-digit ms even on multi-MB
        sessions;
      - tolerates the rare case where the user message preceding the
        current turn was further back than the tail window (in which
        case we'd undercount — but the alternative is full-file scan
        on every render, which we explicitly do not want);
      - tolerates the transcript file being rotated, truncated, or
        absent entirely (all errors silently swallowed → return 0).

    Args:
        transcript_path: Path to the session transcript JSONL, taken
            directly from Claude Code's stdin JSON. Validated as a
            real, regular file before any read.

    Returns:
        Count of ``tool_use`` content blocks on assistant messages
        since the most recent user message. 0 when the path is
        invalid, the file can't be read, parsing fails, or no user
        message exists in the tail (in which case the count is
        meaningless and 0 is the safe degrade).
    """
    if not transcript_path or not isinstance(transcript_path, str):
        return 0

    # Defense-in-depth: transcript_path comes from external JSON. A
    # buggy upstream or malicious wrapper could pass an arbitrary
    # path or a symlink that resolves elsewhere. Claude Code writes
    # transcripts under ~/.claude/ (typically projects/<slug>/...),
    # so we require the resolved real path to live there. Matches the
    # _SESSION_ID_RE regex pattern already used for session IDs.
    try:
        real = os.path.realpath(transcript_path)
        if not real.startswith(_CLAUDE_DIR + os.sep) and real != _CLAUDE_DIR:
            return 0
    except (OSError, ValueError):
        return 0

    # Cache by hashed path. Multiple sessions in the same wall-clock
    # second would collide on the same cache file without this.
    cache_key = "activity_{}".format(
        hashlib.md5(
            transcript_path.encode("utf-8", errors="replace")
        ).hexdigest()[:12]
    )
    cached = _read_cache(cache_key, ttl=_ACTIVITY_CACHE_TTL)
    if cached is not None:
        return cached.get("count", 0)

    count = _count_activity_from_transcript(transcript_path)
    # Cache only non-zero counts. A zero can mean either "no activity
    # in current turn" (legitimate) or "parse failed / file missing /
    # transient rotation" (transient, recovers within ms). Caching
    # zero would freeze that transient state for the full TTL window
    # and the user would see no activity for up to 5s after recovery.
    # Non-zero counts are stable enough to cache; an active turn keeps
    # producing tool_uses so even a "stale" cached 3 will be
    # superseded by the next refresh.
    if count > 0:
        _write_cache(cache_key, {"count": count})
    return count


def _count_activity_from_transcript(transcript_path):
    """Pure-function tail-read + parse. No caching — that's the caller's
    job. Split out so tests can exercise the parse logic without
    having to defeat the TTL cache.

    Reads the last _TRANSCRIPT_TAIL_BYTES; if the preceding user
    message wasn't in that window, retries once with the expanded cap
    so single-turn output up to ~1 MiB still produces a correct count.
    """
    try:
        if not os.path.isfile(transcript_path):
            return 0
        size = os.path.getsize(transcript_path)
        if size <= 0:
            return 0
    except (OSError, IOError):
        return 0

    # First attempt: cheap 64 KiB tail. Covers the vast majority of
    # turns. Only retry with the expanded cap if no user message was
    # found in the initial window.
    count = _parse_transcript_tail(transcript_path, size, _TRANSCRIPT_TAIL_BYTES)
    if count is not None:
        return count

    # Expanded retry — but only if the file is bigger than the first
    # cap (otherwise the result is identical and we'd waste a read).
    if size > _TRANSCRIPT_TAIL_BYTES:
        count = _parse_transcript_tail(
            transcript_path, size, _TRANSCRIPT_TAIL_BYTES_EXPANDED)
        if count is not None:
            return count

    # Two reads still couldn't find a user message — the assistant
    # turn is genuinely larger than 1 MiB, or the file is malformed.
    # Return 0 rather than count window contents (which would belong
    # to a previous turn).
    return 0


def _parse_transcript_tail(transcript_path, size, tail_bytes):
    """Read tail_bytes from the end of transcript_path and count
    tool_use blocks since the most recent user message.

    Returns the count (int >= 0) when a user message was found in the
    window, or None when no user message was found (signals to the
    caller that a wider window might find one).
    """
    try:
        start = max(0, size - tail_bytes)
        with open(transcript_path, "rb") as f:
            f.seek(start)
            chunk = f.read()
    except (OSError, IOError):
        return 0

    try:
        text = chunk.decode("utf-8", errors="replace")
    except (UnicodeDecodeError, AttributeError):
        return 0

    # Discard the first (possibly truncated) line when we started
    # mid-file. The special case: if the very first byte of our chunk
    # is '\n', the previous line ended exactly at `start - 1` and our
    # `lines[0]` is the empty string — no truncation, no discard
    # needed. Without this guard we'd drop a real complete line.
    lines = text.split("\n")
    if start > 0 and lines and not chunk.startswith(b"\n"):
        lines = lines[1:]

    # Walk backwards: find the most recent user message. Pre-filter
    # on a cheap substring to avoid json.loads on every line (a
    # session JSONL can be thousands of lines).
    last_user_idx = -1
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i]
        if '"role"' not in line or '"user"' not in line:
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        # Claude Code's transcript wraps the role on the inner message
        # object, not the outer envelope, on most schema versions.
        if isinstance(entry, dict):
            msg = entry.get("message")
            if isinstance(msg, dict) and msg.get("role") == "user":
                last_user_idx = i
                break
            # Fallback: some schema versions put role at the outer envelope.
            if entry.get("role") == "user":
                last_user_idx = i
                break

    # No user message in this window — signal the caller that a wider
    # read might find one.
    if last_user_idx < 0:
        return None

    # Count tool_use blocks on assistant messages between the user
    # message and EOF.
    count = 0
    for line in lines[last_user_idx + 1:]:
        if '"tool_use"' not in line:
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(entry, dict):
            continue
        msg = entry.get("message") or {}
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                count += 1
    return count


def _read_status_config():
    """Read ~/.claude/claude-status-budget.json once, cache all values.

    Returns:
        Dict with 'budget', 'threshold', 'disabled', and 'clickable_links'.
    """
    cached = _read_cache("status_config")
    if cached is not None:
        return cached

    result = {
        "budget": None,
        "threshold": None,
        "disabled": [],
        "clickable_links": False,
    }
    path = os.path.join(_CLAUDE_DIR, "claude-status-budget.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        budget = data.get("daily_budget_usd")
        if budget is not None:
            result["budget"] = float(budget)
        threshold = data.get("compaction_threshold_pct")
        if threshold is not None:
            threshold = float(threshold)
            if 0 < threshold <= 100:
                result["threshold"] = threshold
        disabled = data.get("disabled_sections")
        if isinstance(disabled, list):
            result["disabled"] = [s for s in disabled if isinstance(s, str)]
        result["clickable_links"] = bool(data.get("clickable_links", False))
    except (OSError, IOError, json.JSONDecodeError,
            ValueError, TypeError, AttributeError):
        # AttributeError covers non-dict JSON (null, list, scalar) —
        # data.get(...) would otherwise raise. Matches the pattern
        # used by get_today_session_count and get_effort_level.
        pass
    _write_cache("status_config", result)
    return result


def get_budget_config():
    """Read daily budget threshold from ~/.claude/claude-status-budget.json.

    Expected format: {"daily_budget_usd": 10.0}
    Uses 30s cache shared with compaction config to avoid redundant file reads.

    Returns:
        Budget in USD as float, or None if not configured.
    """
    config = _read_status_config()
    val = config.get("budget")
    return float(val) if val is not None else None


def get_compaction_threshold():
    """Read compaction threshold from ~/.claude/claude-status-budget.json.

    Expected format: {"compaction_threshold_pct": 62}
    Uses 30s cache shared with budget config to avoid redundant file reads.

    Returns:
        Compaction threshold as float (0-100), or None if not configured.
    """
    config = _read_status_config()
    val = config.get("threshold")
    return float(val) if val is not None else None


_VALID_EFFORT_LEVELS = {"low", "medium", "high", "xhigh", "max"}


def get_effort_level():
    """Read thinking effort level from ~/.claude/settings.json.

    Valid values: "low", "medium", "high", "xhigh", "max". Returns
    None if not configured, invalid, or set to the default "medium".
    Uses 30s cache to avoid hitting disk on every render.

    `xhigh` was introduced in Claude Code v2.1.111 (2026-04) for
    Opus 4.7, sitting between `high` and `max`. `max` is the top
    tier (visible in `/effort max` and Auto Mode references). Other
    models fall back to `high` per Anthropic's docs, so this set is
    the union of valid levels across all models.

    Returns:
        Effort level string ("low", "high", "xhigh", or "max"), or
        None if medium/absent.
    """
    cached = _read_cache("effort_level")
    if cached is not None:
        val = cached.get("effort")
        if val in _VALID_EFFORT_LEVELS and val != "medium":
            return val
        return None

    settings_path = os.path.join(_CLAUDE_DIR, "settings.json")
    effort = None
    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
        raw = data.get("effortLevel", "")
        if isinstance(raw, str) and raw.lower() in _VALID_EFFORT_LEVELS:
            effort = raw.lower()
    except (OSError, IOError, json.JSONDecodeError, ValueError,
            TypeError, AttributeError):
        # Don't cache failure — retry next cycle
        return None

    # Only return non-default levels (medium is the default, skip it)
    if effort == "medium":
        effort = None
    _write_cache("effort_level", {"effort": effort})
    return effort


def get_disabled_sections():
    """Read disabled sections from ~/.claude/claude-status-budget.json.

    Expected format: {"disabled_sections": ["cache", "latency"]}
    Uses 30s cache shared with budget/compaction config.

    Returns:
        List of section name strings to hide, or empty list.
    """
    config = _read_status_config()
    return config.get("disabled", [])


def get_clickable_links_enabled():
    """Read whether OSC 8 clickable links are enabled.

    Expected format: {"clickable_links": true}
    Defaults to False because OSC 8 escape sequences confuse Claude Code's
    Ink TUI renderer and can cause Line 2 of the status line to disappear.
    Opt-in for users who run claude-status in a supporting terminal
    outside of Claude Code (iTerm2, Kitty, WezTerm).

    Returns:
        True if opted in, False otherwise (default).
    """
    # _read_status_config() already coerces to bool and defaults to False,
    # so we trust the parser's contract and return the value directly.
    config = _read_status_config()
    return config.get("clickable_links", False)
