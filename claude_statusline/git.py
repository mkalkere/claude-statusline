"""Git branch detection with cross-platform caching."""

import hashlib
import json
import os
import subprocess
import tempfile
import time

_CACHE_TTL = 5  # seconds
_NO_GIT_CACHE_TTL = 60  # seconds — longer TTL when git is not available


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
    """Read cached git branch if still fresh.

    Uses a longer TTL for empty values (git not available) to avoid
    repeated subprocess timeouts on systems without git.
    """
    try:
        path = _cache_file()
        stat = os.stat(path)
        with open(path, "r") as f:
            value = f.read().strip()
        # Use longer TTL when git is not available (empty cache)
        ttl = _NO_GIT_CACHE_TTL if not value else _CACHE_TTL
        if time.time() - stat.st_mtime > ttl:
            return None
        return value
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
    if cached is not None and "stash" in cached:
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

    cached = _read_extras_cache() or {}
    cached.update(result)
    _write_extras_cache(cached)
    return result


def get_git_state():
    """Detect if the repo is in a merge, rebase, or has conflicts.

    Uses file-existence checks after resolving .git dir via subprocess.
    Cached with 5s TTL.

    Returns:
        String: 'merge', 'rebase', 'conflict', or empty string.
    """
    cached = _read_extras_cache()
    if cached is not None and "git_state" in cached:
        return cached.get("git_state", "")

    state = ""

    if not get_branch():
        return state

    try:
        # Find .git directory
        proc = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True, text=True, timeout=2,
        )
        if proc.returncode != 0:
            return state
        git_dir = proc.stdout.strip()

        # Check for merge, rebase, cherry-pick, or revert
        if os.path.isfile(os.path.join(git_dir, "MERGE_HEAD")):
            state = "merge"
        elif (os.path.isdir(os.path.join(git_dir, "rebase-merge"))
              or os.path.isdir(os.path.join(git_dir, "rebase-apply"))):
            state = "rebase"
        elif os.path.isfile(os.path.join(git_dir, "CHERRY_PICK_HEAD")):
            state = "cherry-pick"
        elif os.path.isfile(os.path.join(git_dir, "REVERT_HEAD")):
            state = "revert"

        # Check for conflicts (during merge or rebase)
        if state:
            try:
                proc = subprocess.run(
                    ["git", "diff", "--name-only", "--diff-filter=U"],
                    capture_output=True, text=True, timeout=2,
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    state = "conflict"
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                pass

    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    # Write to cache
    cached = _read_extras_cache() or {}
    cached["git_state"] = state
    _write_extras_cache(cached)
    return state


def get_last_commit_age_ms():
    """Get milliseconds since the last commit.

    Cached with 5s TTL via the shared extras cache.

    Returns:
        Milliseconds since last commit, or None if unavailable.
    """
    cached = _read_extras_cache()
    if cached is not None and "commit_age_ms" in cached:
        val = cached.get("commit_age_ms")
        return val

    if not get_branch():
        return None

    try:
        proc = subprocess.run(
            ["git", "log", "-1", "--format=%ct"],
            capture_output=True, text=True, timeout=2,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            commit_epoch = int(proc.stdout.strip())
            age_ms = int((time.time() - commit_epoch) * 1000)
            result = max(0, age_ms)
            cached = _read_extras_cache() or {}
            cached["commit_age_ms"] = result
            _write_extras_cache(cached)
            return result
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError, ValueError):
        pass

    return None


def get_remote_url():
    """Get the HTTPS URL of the git remote origin.

    Converts SSH URLs to HTTPS. Cached with 5s TTL via shared extras cache.

    Returns:
        HTTPS URL string, or empty string if unavailable.
    """
    cached = _read_extras_cache()
    if cached is not None and "remote_url" in cached:
        return cached.get("remote_url", "")

    url = ""
    if not get_branch():
        return url

    try:
        proc = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=2,
        )
        if proc.returncode == 0:
            raw = proc.stdout.strip()
            # Convert SSH to HTTPS
            if raw.startswith("git@"):
                raw = raw.replace(":", "/", 1).replace("git@", "https://", 1)
            if raw.endswith(".git"):
                raw = raw[:-4]
            if raw.startswith("https://"):
                url = raw
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    cached = _read_extras_cache() or {}
    cached["remote_url"] = url
    _write_extras_cache(cached)
    return url
