"""Git branch detection with cross-platform caching."""

import hashlib
import json
import os
import subprocess
import tempfile
import time

_CACHE_TTL = 5  # seconds


def _cache_file():
    """Return a per-directory cache file path.

    Uses a short hash of the current working directory so that
    concurrent sessions in different repos do not share cache state.
    """
    try:
        cwd = os.getcwd()
    except OSError:
        cwd = ""
    suffix = hashlib.md5(cwd.encode("utf-8", errors="replace")).hexdigest()[:12]
    return os.path.join(tempfile.gettempdir(), "claude_sl_cache_{}".format(suffix))


def _read_cache():
    """Read cached git branch if still fresh."""
    try:
        path = _cache_file()
        stat = os.stat(path)
        if time.time() - stat.st_mtime > _CACHE_TTL:
            return None
        with open(path, "r") as f:
            return f.read().strip()
    except (OSError, IOError):
        return None


def _write_cache(branch):
    """Write branch name to cache file."""
    try:
        with open(_cache_file(), "w") as f:
            f.write(branch)
    except (OSError, IOError):
        pass


def get_branch():
    """Get current git branch name.

    Uses a file-based cache with 5s TTL to avoid subprocess overhead
    on every statusline render.

    Returns:
        Branch name string, or empty string if not in a git repo.
    """
    cached = _read_cache()
    if cached is not None:
        return cached

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            branch = result.stdout.strip()
            _write_cache(branch)
            return branch
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    _write_cache("")
    return ""


def _extras_cache_file():
    """Return user-scoped cache file path for git extras."""
    try:
        cwd = os.getcwd()
    except OSError:
        cwd = ""
    user_hash = hashlib.md5(
        os.path.expanduser("~").encode("utf-8", "replace")
    ).hexdigest()[:8]
    suffix = hashlib.md5(cwd.encode("utf-8", errors="replace")).hexdigest()[:12]
    cache_dir = os.path.join(
        tempfile.gettempdir(), "claude_sl_{}".format(user_hash)
    )
    try:
        os.makedirs(cache_dir, exist_ok=True)
    except OSError:
        cache_dir = tempfile.gettempdir()
    return os.path.join(cache_dir, "extras_{}".format(suffix))


def _read_extras_cache():
    """Read cached git extras if still fresh."""
    try:
        path = _extras_cache_file()
        stat = os.stat(path)
        if time.time() - stat.st_mtime > _CACHE_TTL:
            return None
        with open(path, "r") as f:
            return json.load(f)
    except (OSError, IOError, json.JSONDecodeError, ValueError):
        return None


def _write_extras_cache(data):
    """Write git extras to cache file atomically."""
    target = _extras_cache_file()
    tmp = target + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, target)
    except (OSError, IOError):
        try:
            os.unlink(tmp)
        except OSError:
            pass


def get_git_extras():
    """Get stash count and ahead/behind remote tracking info.

    Uses fast, index-only git operations with 5s TTL cache.
    Returns early with zeros if not in a git repo (avoids wasted
    subprocess calls for non-git or non-VCS projects).

    Returns:
        Dict with keys 'stash' (int), 'ahead' (int), 'behind' (int).
    """
    cached = _read_extras_cache()
    if cached is not None:
        return cached

    result = {"stash": 0, "ahead": 0, "behind": 0}

    # Quick check: skip if not in a git repo
    if not get_branch():
        _write_extras_cache(result)
        return result

    # Stash count
    try:
        proc = subprocess.run(
            ["git", "stash", "list"],
            capture_output=True, text=True, timeout=2,
        )
        if proc.returncode == 0:
            lines = proc.stdout.strip().splitlines()
            result["stash"] = len(lines) if lines and lines[0] else 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    # Ahead/behind remote
    try:
        proc = subprocess.run(
            ["git", "rev-list", "--count", "--left-right", "HEAD...@{u}"],
            capture_output=True, text=True, timeout=2,
        )
        if proc.returncode == 0:
            parts = proc.stdout.strip().split()
            if len(parts) == 2:
                result["ahead"] = int(parts[0])
                result["behind"] = int(parts[1])
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError, ValueError):
        pass

    _write_extras_cache(result)
    return result
