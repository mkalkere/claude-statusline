"""Session analytics — daily cost, session count, tool calls.

Reads ~/.claude/ data files to provide aggregate metrics across sessions.
Uses file-based caching to avoid expensive filesystem scans on every render.
"""

import hashlib
import json
import os
import tempfile
import time

_CACHE_TTL = 30  # seconds — longer than git cache since this is heavier

_CLAUDE_DIR = os.path.join(os.path.expanduser("~"), ".claude")
_SESSIONS_DIR = os.path.join(_CLAUDE_DIR, "sessions")
_PROJECTS_DIR = os.path.join(_CLAUDE_DIR, "projects")


def _cache_path(name):
    """Return a cache file path for a named metric."""
    return os.path.join(
        tempfile.gettempdir(),
        "claude_sl_{}".format(name),
    )


def _read_cache(name):
    """Read a cached JSON value if still fresh."""
    try:
        path = _cache_path(name)
        stat = os.stat(path)
        if time.time() - stat.st_mtime > _CACHE_TTL:
            return None
        with open(path, "r") as f:
            return json.load(f)
    except (OSError, IOError, json.JSONDecodeError, ValueError):
        return None


def _write_cache(name, value):
    """Write a JSON value to the named cache file."""
    try:
        with open(_cache_path(name), "w") as f:
            json.dump(value, f)
    except (OSError, IOError):
        pass


def _today_str():
    """Return today's date as YYYY-MM-DD string."""
    t = time.localtime()
    return "{:04d}-{:02d}-{:02d}".format(t.tm_year, t.tm_mon, t.tm_mday)


def get_today_session_count():
    """Count sessions started today by reading ~/.claude/sessions/*.json.

    Each file contains a JSON object with a 'startedAt' timestamp (ms epoch).

    Returns:
        Number of sessions started today, or 0 on error.
    """
    cached = _read_cache("sessions_today")
    if cached is not None:
        return cached.get("count", 0)

    count = 0
    today = _today_str()

    try:
        if not os.path.isdir(_SESSIONS_DIR):
            _write_cache("sessions_today", {"count": 0})
            return 0

        for fname in os.listdir(_SESSIONS_DIR):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(_SESSIONS_DIR, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                started_at = data.get("startedAt")
                if started_at:
                    # Convert ms epoch to date string
                    session_date = time.strftime(
                        "%Y-%m-%d", time.localtime(started_at / 1000)
                    )
                    if session_date == today:
                        count += 1
            except (json.JSONDecodeError, OSError, IOError, ValueError):
                continue
    except OSError:
        pass

    _write_cache("sessions_today", {"count": count})
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

    cache_key = "tools_{}".format(
        hashlib.md5(session_id.encode("utf-8", errors="replace")).hexdigest()[:12]
    )
    cached = _read_cache(cache_key)
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
                    with open(fpath, "r", encoding="utf-8") as f:
                        for line in f:
                            if '"tool_use"' in line and '"type"' in line:
                                count += 1
                except (OSError, IOError):
                    pass
                break  # Session only exists in one project
    except OSError:
        pass

    _write_cache(cache_key, {"count": count})
    return count


def get_budget_config():
    """Read daily budget threshold from ~/.claude/claude-status-budget.json.

    Expected format: {"daily_budget_usd": 10.0}

    Returns:
        Budget in USD as float, or None if not configured.
    """
    path = os.path.join(_CLAUDE_DIR, "claude-status-budget.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        budget = data.get("daily_budget_usd")
        if budget is not None:
            return float(budget)
    except (OSError, IOError, json.JSONDecodeError, ValueError, TypeError):
        pass
    return None
