"""CLI entry point for claude-status."""

import argparse
import json
import os
import platform
import shutil
import sys

from . import __version__
from .bar import render_bar
from .colors import (
    BOLD, BRIGHT_BLACK, BRIGHT_MAGENTA, BRIGHT_RED, CYAN, GREEN, RED, RESET,
    YELLOW, colorize,
)
from .formatters import (
    fmt_burn_rate, fmt_cache_pct, fmt_cost, fmt_duration, fmt_lines, fmt_tokens,
)
from .git import get_branch
from .themes import THEMES, get_theme

# Percentage of context window usage that triggers the !CTX warning.
CTX_WARNING_THRESHOLD_PCT = 85


def _force_utf8():
    """Force UTF-8 encoding on stdout for Windows compatibility."""
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _settings_path():
    """Get Claude Code settings.json path."""
    home = os.path.expanduser("~")
    return os.path.join(home, ".claude", "settings.json")


def _normalize(data):
    """Normalize Claude Code JSON into a flat dict for rendering.

    Handles the real nested schema (context_window.*, cost.*, vim.mode, etc.)
    as well as flat keys used by demo mode.
    """
    out = {}

    # Context window (nested or flat)
    cw = data.get("context_window") or {}
    cu = cw.get("current_usage") or {}
    flat_usage = data.get("current_usage") or {}

    out["used_percentage"] = cw.get("used_percentage") or flat_usage.get("used_percentage")
    out["input_tokens"] = cu.get("input_tokens") or flat_usage.get("input_tokens")
    out["output_tokens"] = cu.get("output_tokens") or flat_usage.get("output_tokens")
    out["cache_read"] = (
        cu.get("cache_read_input_tokens")
        or flat_usage.get("cache_read_tokens")
    )
    out["cache_create"] = (
        cu.get("cache_creation_input_tokens")
        or flat_usage.get("cache_create_tokens")
    )
    out["context_size"] = (
        cw.get("context_window_size")
        or flat_usage.get("context_size")
    )

    # Cost (nested or flat)
    cost_obj = data.get("cost") or {}
    out["cost"] = cost_obj.get("total_cost_usd") or data.get("cost_usd")
    out["duration"] = cost_obj.get("total_duration_ms") or data.get("session_duration_ms")
    out["api_duration"] = cost_obj.get("total_api_duration_ms") or data.get("api_duration_ms")
    out["lines_added"] = cost_obj.get("total_lines_added") or data.get("lines_added")
    out["lines_removed"] = cost_obj.get("total_lines_removed") or data.get("lines_removed")

    # Booleans
    out["exceeds_200k"] = data.get("exceeds_200k_tokens", False)

    # Vim (nested or flat)
    vim_obj = data.get("vim") or {}
    out["vim_mode"] = vim_obj.get("mode") or data.get("vim_mode")

    # Agent (nested or flat)
    agent_obj = data.get("agent") or {}
    out["agent_name"] = agent_obj.get("name") or data.get("agent_name")

    # Worktree (nested or flat)
    wt_obj = data.get("worktree") or {}
    out["worktree_branch"] = wt_obj.get("branch") or data.get("worktree_branch")
    out["worktree_name"] = wt_obj.get("name")

    # Git branch
    out["git_branch"] = data.get("git_branch")

    # Project name: prefer workspace.project_dir (explicit project root),
    # fall back to last folder of current_dir / cwd
    workspace = data.get("workspace") or {}
    project_dir = workspace.get("project_dir") or ""
    cwd = workspace.get("current_dir") or data.get("cwd") or ""
    best_path = project_dir or cwd
    out["project_name"] = os.path.basename(os.path.normpath(best_path)) if best_path else ""

    # Model info
    model_obj = data.get("model") or {}
    out["model_name"] = model_obj.get("display_name")

    return out


def _render_sections(n, order, theme):
    """Render a list of section names into formatted strings.

    Args:
        n: Normalized data dict.
        order: List of section name strings.
        theme: Theme dict.

    Returns:
        List of rendered section strings.
    """
    sections = []
    tc = theme["colors"]

    input_tokens = n["input_tokens"]
    output_tokens = n["output_tokens"]
    cache_read = n["cache_read"]
    cache_create = n["cache_create"]
    cost = n["cost"]
    duration = n["duration"]
    lines_added = n["lines_added"]
    lines_removed = n["lines_removed"]
    context_size = n["context_size"]
    exceeds_200k = n["exceeds_200k"]
    vim_mode = n["vim_mode"]
    agent_name = n["agent_name"]
    worktree_branch = n["worktree_branch"]
    model_name = n["model_name"]
    api_duration = n["api_duration"]
    pct = n["used_percentage"]

    total_input = (input_tokens or 0) + (cache_read or 0) + (cache_create or 0)
    total_tokens = (input_tokens or 0) + (output_tokens or 0) + (cache_read or 0)

    for section in order:
        if section == "bar" and pct is not None:
            sections.append(render_bar(pct, 20, theme))

        elif section == "tokens" and (input_tokens is not None or output_tokens is not None):
            inp = fmt_tokens(input_tokens)
            out = fmt_tokens(output_tokens)
            sections.append(
                colorize("in:", tc["label"]) + colorize(inp, tc["value"]) + " "
                + colorize("out:", tc["label"]) + colorize(out, tc["value"])
            )

        elif section == "cache":
            cache_str = fmt_cache_pct(cache_read, total_input)
            if cache_str:
                sections.append(
                    colorize("cache:", tc["label"]) + colorize(cache_str, GREEN)
                )

        elif section == "cost" and cost is not None:
            sections.append(colorize(fmt_cost(cost), tc["cost"]))

        elif section == "burn" and total_tokens and duration:
            rate = fmt_burn_rate(total_tokens, duration)
            if rate != "?":
                sections.append(
                    colorize("burn:", tc["label"]) + colorize(rate, tc["value"])
                )

        elif section == "duration" and duration is not None:
            sections.append(colorize(fmt_duration(duration), tc["value"]))

        elif section == "latency" and api_duration is not None:
            lc = tc.get("latency", CYAN)
            sections.append(
                colorize("api:", tc["label"]) + colorize(fmt_duration(api_duration), lc)
            )

        elif section == "lines":
            lines_str = fmt_lines(lines_added, lines_removed)
            if lines_str:
                parts = []
                if lines_added:
                    parts.append(colorize("+{}".format(lines_added), tc["added"]))
                if lines_removed:
                    parts.append(colorize("-{}".format(lines_removed), tc["removed"]))
                sections.append(" ".join(parts))

        elif section == "branch":
            branch = n["git_branch"] or get_branch()
            if branch:
                bc = tc["branch_main"] if branch in ("main", "master") else tc["branch_feature"]
                project = n.get("project_name", "")
                if project:
                    sections.append(
                        colorize("\u2387 " + project, CYAN) +
                        colorize("/" + branch, bc)
                    )
                else:
                    sections.append(colorize("\u2387 " + branch, bc))

        elif section == "context_size" and context_size:
            label = "{}K".format(context_size // 1000) if context_size >= 1000 else str(context_size)
            sections.append(colorize("({})".format(label), BRIGHT_BLACK))

        elif section == "ctx_warning":
            # Prefer percentage-based warning (works for any context window size)
            # Fall back to exceeds_200k_tokens for backward compatibility
            if (pct is not None and pct >= CTX_WARNING_THRESHOLD_PCT) or exceeds_200k:
                sections.append(colorize("!CTX", BRIGHT_RED, BOLD))

        elif section == "vim" and vim_mode:
            vc = tc["vim_normal"] if vim_mode.upper() == "NORMAL" else tc["vim_insert"]
            sections.append(colorize(vim_mode.upper(), vc, BOLD))

        elif section == "agent" and agent_name:
            sections.append(colorize("[{}]".format(agent_name), tc["agent"]))

        elif section == "worktree" and worktree_branch:
            sections.append(colorize("wt:" + worktree_branch, YELLOW))

        elif section == "model" and model_name:
            mc = tc.get("model", BRIGHT_MAGENTA)
            sections.append(colorize(model_name, mc))

    return sections


def render(data, theme_name="default"):
    """Render the statusline as one or two lines.

    Line 1: context bar, tokens, cache, cost, burn rate, context size, warnings
    Line 2: duration, lines changed, git branch, vim mode, agent, worktree

    Args:
        data: Parsed JSON dict from Claude Code.
        theme_name: Name of theme to use.

    Returns:
        Formatted statusline string (may contain newline for two-line output).
    """
    theme = get_theme(theme_name)
    n = _normalize(data)
    sep = colorize(theme["separator"], theme["colors"]["separator"])

    line1_sections = _render_sections(n, theme["line1"], theme)
    line2_sections = _render_sections(n, theme["line2"], theme)

    lines = []
    if line1_sections:
        lines.append(sep.join(line1_sections))
    if line2_sections:
        lines.append(sep.join(line2_sections))

    return "\n".join(lines)


def _demo_data():
    """Generate sample data for demo mode using the real nested schema."""
    return {
        "context_window": {
            "used_percentage": 42,
            "context_window_size": 200_000,
            "current_usage": {
                "input_tokens": 245_000,
                "output_tokens": 18_500,
                "cache_read_input_tokens": 180_000,
                "cache_creation_input_tokens": 5_000,
            },
        },
        "cost": {
            "total_cost_usd": 0.73,
            "total_duration_ms": 725_000,
            "total_api_duration_ms": 312_000,
            "total_lines_added": 247,
            "total_lines_removed": 38,
        },
        "exceeds_200k_tokens": False,
        "git_branch": "feat/statusline",
        "cwd": "/home/user/projects/myapp",
        "workspace": {
            "project_dir": "/home/user/projects/myapp",
            "current_dir": "/home/user/projects/myapp/src",
        },
        "model": {
            "display_name": "Opus 4.6 (1M context)",
        },
    }


def _print_indented(text, indent="  "):
    """Print multiline text with consistent indentation."""
    for line in text.split("\n"):
        print(indent + line)


def cmd_demo():
    """Show demo output for all themes."""
    data = _demo_data()
    print("claude-status v{} — theme demos\n".format(__version__))
    for name in ("default", "minimal", "powerline"):
        print("  {}:".format(name))
        _print_indented(render(data, name))
        print()

    # Also show warning state
    warn_data = json.loads(json.dumps(data))
    warn_data["exceeds_200k_tokens"] = True
    warn_data["context_window"]["used_percentage"] = 93
    print("  warning state (93% usage):")
    _print_indented(render(warn_data, "default"))
    print()

    # Show with optional fields
    full_data = json.loads(json.dumps(data))
    full_data["vim"] = {"mode": "NORMAL"}
    full_data["agent"] = {"name": "Explore"}
    full_data["worktree"] = {"branch": "fix/bug-123", "name": "bug-fix"}
    print("  all fields (vim + agent + worktree):")
    _print_indented(render(full_data, "default"))
    print()


def cmd_install(theme_name="default"):
    """Install claude-status into Claude Code settings."""
    settings_file = _settings_path()
    settings = {}

    # Read existing settings and create backup
    if os.path.exists(settings_file):
        backup_file = settings_file + ".bak"
        try:
            shutil.copy2(settings_file, backup_file)
        except OSError:
            pass  # Best-effort backup
        try:
            with open(settings_file, "r", encoding="utf-8") as f:
                settings = json.load(f)
        except (json.JSONDecodeError, IOError):
            print("Warning: could not parse existing settings.json, creating new one")

    # Build command
    cmd = "claude-status"
    if theme_name != "default":
        cmd += " --theme {}".format(theme_name)

    # Update statusLine config (must be an object with type + command)
    settings["statusLine"] = {
        "type": "command",
        "command": cmd,
    }

    # Ensure directory exists
    os.makedirs(os.path.dirname(settings_file), exist_ok=True)

    # Write settings
    with open(settings_file, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")

    print("Installed claude-status into {}".format(settings_file))
    print("  statusLine: {}".format(cmd))
    print()
    print("Restart Claude Code to see your new status line!")


def cmd_doctor():
    """Run diagnostics and print system info."""
    print("claude-status v{} — diagnostics\n".format(__version__))

    print("System:")
    print("  Python:   {} ({})".format(platform.python_version(), sys.executable))
    print("  OS:       {} {}".format(platform.system(), platform.release()))
    print("  Platform: {}".format(platform.platform()))
    print("  Encoding: {}".format(sys.stdout.encoding))
    print()

    # Check settings
    settings_file = _settings_path()
    print("Claude Code:")
    print("  Settings: {}".format(settings_file))
    if os.path.exists(settings_file):
        try:
            with open(settings_file, "r", encoding="utf-8") as f:
                settings = json.load(f)
            sl = settings.get("statusLine", "(not configured)")
            print("  statusLine: {}".format(sl))
        except Exception as e:
            print("  Error reading settings: {}".format(e))
    else:
        print("  Settings file not found")
    print()

    # Check git
    branch = get_branch()
    print("Git:")
    print("  Branch: {}".format(branch or "(not in a git repo)"))
    print()

    # Terminal capabilities
    print("Terminal:")
    term = os.environ.get("TERM", "(not set)")
    print("  TERM: {}".format(term))
    print("  Unicode test: █░▓ \u2387 \ue0b0")
    print()


def main():
    """Main entry point."""
    _force_utf8()

    parser = argparse.ArgumentParser(
        prog="claude-status",
        description="Beautiful status line for Claude Code",
    )
    parser.add_argument("--version", action="version", version="%(prog)s " + __version__)
    parser.add_argument("--demo", action="store_true", help="Show demo output for all themes")
    parser.add_argument("--install", action="store_true", help="Install into Claude Code settings")
    parser.add_argument("--doctor", action="store_true", help="Run diagnostics")
    parser.add_argument("--theme", default="default",
                        choices=["default", "minimal", "powerline", "custom"],
                        help="Theme to use (default: default). "
                             "'custom' loads ~/.claude/claude-status-theme.json")

    args = parser.parse_args()

    if args.demo:
        cmd_demo()
        return

    if args.install:
        cmd_install(args.theme)
        return

    if args.doctor:
        cmd_doctor()
        return

    # Normal mode: read JSON from stdin, output statusline
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        print("?")
        return
    except KeyboardInterrupt:
        return

    output = render(data, args.theme)
    if output:
        print(output)


if __name__ == "__main__":
    main()
