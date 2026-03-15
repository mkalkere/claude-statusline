"""Git branch detection with cross-platform caching."""

import os
import subprocess
import tempfile
import time

_CACHE_FILE = os.path.join(tempfile.gettempdir(), "claude_statusline_git_cache")
_CACHE_TTL = 5  # seconds


def _read_cache():
    """Read cached git branch if still fresh."""
    try:
        stat = os.stat(_CACHE_FILE)
        if time.time() - stat.st_mtime > _CACHE_TTL:
            return None
        with open(_CACHE_FILE, "r") as f:
            return f.read().strip()
    except (OSError, IOError):
        return None


def _write_cache(branch):
    """Write branch name to cache file."""
    try:
        with open(_CACHE_FILE, "w") as f:
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
