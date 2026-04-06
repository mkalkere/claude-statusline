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


def _read_status_config():
    """Read ~/.claude/claude-status-budget.json once, cache both values.

    Returns:
        Dict with 'budget' (float or None) and 'threshold' (float or None).
    """
    cached = _read_cache("status_config")
    if cached is not None:
        return cached

    result = {"budget": None, "threshold": None}
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
    except (OSError, IOError, json.JSONDecodeError, ValueError, TypeError):
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


_VALID_EFFORT_LEVELS = {"low", "medium", "high"}


def get_effort_level():
    """Read thinking effort level from ~/.claude/settings.json.

    Valid values: "low", "medium", "high". Returns None if not
    configured, invalid, or set to the default "medium".
    Uses 30s cache to avoid hitting disk on every render.

    Returns:
        Effort level string ("low" or "high"), or None if medium/absent.
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
        pass

    # Only return non-default levels (medium is the default, skip it)
    if effort == "medium":
        effort = None
    _write_cache("effort_level", {"effort": effort})
    return effort
