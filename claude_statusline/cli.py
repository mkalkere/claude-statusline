"""CLI entry point for claude-status."""

import argparse
import json
import os
import platform
import shutil
import sys
import tempfile
import time

from . import __version__
from .bar import render_bar
from .colors import (
    BOLD, BRIGHT_BLACK, BRIGHT_MAGENTA, BRIGHT_RED, CYAN, GREEN, RED, RESET,
    YELLOW, colorize,
)
from .formatters import (
    fmt_burn_rate, fmt_cache_pct, fmt_cost, fmt_countdown, fmt_duration,
    fmt_lines, fmt_tokens,
)
from .git import get_branch, get_git_extras
from .sessions import (
    get_budget_config, get_compaction_threshold, get_effort_level,
    get_session_tool_count, get_today_session_count,
)
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


def _first(*vals):
    """Return the first value that is not None."""
    for v in vals:
        if v is not None:
            return v
    return None


def _safe_num(val):
    """Coerce to float or return None. Prevents crashes on non-numeric input."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


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

    out["used_percentage"] = _first(cw.get("used_percentage"), flat_usage.get("used_percentage"))
    out["input_tokens"] = _first(cu.get("input_tokens"), flat_usage.get("input_tokens"))
    out["output_tokens"] = _first(cu.get("output_tokens"), flat_usage.get("output_tokens"))
    out["cache_read"] = _first(
        cu.get("cache_read_input_tokens"),
        flat_usage.get("cache_read_tokens"),
    )
    out["cache_create"] = _first(
        cu.get("cache_creation_input_tokens"),
        flat_usage.get("cache_create_tokens"),
    )
    out["context_size"] = _first(
        cw.get("context_window_size"),
        flat_usage.get("context_size"),
    )

    # Cost (nested or flat)
    cost_obj = data.get("cost") or {}
    out["cost"] = _first(cost_obj.get("total_cost_usd"), data.get("cost_usd"))
    out["duration"] = _first(cost_obj.get("total_duration_ms"), data.get("session_duration_ms"))
    out["api_duration"] = _first(cost_obj.get("total_api_duration_ms"), data.get("api_duration_ms"))
    out["lines_added"] = _first(cost_obj.get("total_lines_added"), data.get("lines_added"))
    out["lines_removed"] = _first(cost_obj.get("total_lines_removed"), data.get("lines_removed"))

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

    # Session ID (for tool call counting)
    out["session_id"] = data.get("session_id") or ""

    # Session name (custom name via --name or /rename)
    out["session_name"] = data.get("session_name") or ""

    # Claude Code version
    out["cc_version"] = data.get("version") or ""

    # Rate limits (Pro/Max only, added in Claude Code v2.1.80)
    rl = data.get("rate_limits")
    rl = rl if isinstance(rl, dict) else {}
    five_h = rl.get("five_hour")
    five_h = five_h if isinstance(five_h, dict) else {}
    seven_d = rl.get("seven_day")
    seven_d = seven_d if isinstance(seven_d, dict) else {}
    # resets_at is Unix epoch seconds per Claude Code docs — convert to ms
    # for fmt_countdown() which expects milliseconds
    for period, rl_dict in [("5h", five_h), ("7d", seven_d)]:
        out["rate_limit_{}_pct".format(period)] = _safe_num(rl_dict.get("used_percentage"))
        resets_sec = _safe_num(rl_dict.get("resets_at"))
        out["rate_limit_{}_resets".format(period)] = (
            resets_sec * 1000 if resets_sec is not None else None
        )

    # Output style
    style_obj = data.get("output_style")
    style_obj = style_obj if isinstance(style_obj, dict) else {}
    style_name = style_obj.get("name")
    out["output_style"] = style_name if isinstance(style_name, str) and style_name else ""

    # Added directories count
    added_dirs = workspace.get("added_dirs")
    out["added_dirs_count"] = len(added_dirs) if isinstance(added_dirs, list) else 0

    # Native git worktree indicator (v2.1.97+)
    out["git_worktree"] = bool(workspace.get("git_worktree"))

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
    vim_mode = n["vim_mode"]
    agent_name = n["agent_name"]
    worktree_branch = n["worktree_branch"]
    model_name = n["model_name"]
    api_duration = n["api_duration"]
    pct = n["used_percentage"]

    total_input = (input_tokens or 0) + (cache_read or 0) + (cache_create or 0)
    total_tokens = (input_tokens or 0) + (output_tokens or 0) + (cache_read or 0) + (cache_create or 0)

    for section in order:
        if section == "bar" and pct is not None:
            compaction = get_compaction_threshold()
            bar_width = theme.get("bar_width", 20)
            sections.append(render_bar(pct, bar_width, theme, compaction))

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
            # Percentage-based warning — works for any context window size
            if pct is not None and pct >= CTX_WARNING_THRESHOLD_PCT:
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

        elif section == "tools":
            session_id = n.get("session_id", "")
            if session_id:
                tool_count = get_session_tool_count(session_id)
                if tool_count > 0:
                    sections.append(
                        colorize("tools:", tc["label"])
                        + colorize(str(tool_count), tc["value"])
                    )

        elif section == "sessions":
            count = get_today_session_count()
            if count > 0:
                sc = tc.get("sessions", CYAN)
                sections.append(
                    colorize("sessions:", tc["label"])
                    + colorize(str(count), sc)
                )

        elif section == "budget":
            if cost is not None:
                budget = get_budget_config()
                if budget is not None and budget > 0:
                    pct_used = (cost / budget) * 100
                    if pct_used >= 90:
                        bc = BRIGHT_RED
                    elif pct_used >= 70:
                        bc = YELLOW
                    else:
                        bc = GREEN
                    # Format budget as clean dollar amount (no trailing .0)
                    if budget == int(budget):
                        budget_str = "${}".format(int(budget))
                    else:
                        budget_str = fmt_cost(budget)
                    label = "{}/{}".format(fmt_cost(cost), budget_str)
                    sections.append(colorize(label, bc, BOLD))

        elif section == "version":
            vc = tc.get("version", BRIGHT_BLACK)
            sections.append(colorize("v" + __version__, vc))

        elif section == "clock":
            cc = tc.get("clock", BRIGHT_BLACK)
            sections.append(colorize(time.strftime("%H:%M"), cc))

        elif section == "cc_version":
            cc_ver = n.get("cc_version", "")
            if cc_ver:
                cvc = tc.get("cc_version", BRIGHT_BLACK)
                sections.append(colorize("CC:" + cc_ver, cvc))

        elif section == "session_name":
            sname = n.get("session_name", "")
            if sname:
                snc = tc.get("session_name", CYAN)
                sections.append(colorize(
                    "\u2726 {}".format(sname), snc
                ))

        elif section == "rate_limits":
            rl_5h = n.get("rate_limit_5h_pct")
            rl_7d = n.get("rate_limit_7d_pct")
            if rl_5h is not None or rl_7d is not None:
                parts = []
                nearest_reset = None
                for label, pct_val, resets_at in [
                    ("5h", rl_5h, n.get("rate_limit_5h_resets")),
                    ("7d", rl_7d, n.get("rate_limit_7d_resets")),
                ]:
                    if pct_val is not None:
                        clamped = max(0, min(100, pct_val))
                        if clamped >= 85:
                            rc = tc.get("rate_limit_danger", BRIGHT_RED)
                        elif clamped >= 60:
                            rc = tc.get("rate_limit_warn", YELLOW)
                        else:
                            rc = tc.get("rate_limit_ok", GREEN)
                        parts.append(colorize(
                            "{}:{}%".format(label, int(clamped)), rc
                        ))
                    if resets_at is not None:
                        if nearest_reset is None or resets_at < nearest_reset:
                            nearest_reset = resets_at
                countdown = fmt_countdown(nearest_reset)
                if countdown:
                    parts.append(colorize(countdown, BRIGHT_BLACK))
                if parts:
                    sections.append(" ".join(parts))

        elif section == "output_style":
            style = n.get("output_style", "")
            if style:
                osc = tc.get("output_style", BRIGHT_BLACK)
                sections.append(colorize("style:" + style, osc))

        elif section == "added_dirs":
            dirs_count = n.get("added_dirs_count", 0)
            if dirs_count > 0:
                adc = tc.get("added_dirs", BRIGHT_BLACK)
                sections.append(colorize(
                    "dirs:+{}".format(dirs_count), adc
                ))

        elif section == "git_worktree":
            if n.get("git_worktree"):
                gwtc = tc.get("git_worktree", YELLOW)
                sections.append(colorize("gwt", gwtc))

        elif section == "effort":
            effort = get_effort_level()
            if effort:
                if effort == "high":
                    ec = tc.get("effort_high", BRIGHT_MAGENTA)
                else:
                    ec = tc.get("effort_low", BRIGHT_BLACK)
                sections.append(colorize(
                    "effort:" + effort, ec, BOLD
                ))

        elif section == "git_extras":
            branch = n["git_branch"] or get_branch()
            if branch:
                extras = get_git_extras()
                parts = []
                if extras.get("stash", 0) > 0:
                    parts.append(colorize(
                        "stash:{}".format(extras["stash"]),
                        tc.get("git_stash", YELLOW)
                    ))
                ahead = extras.get("ahead", 0)
                behind = extras.get("behind", 0)
                if ahead or behind:
                    sync_parts = []
                    if ahead:
                        sync_parts.append("+{}".format(ahead))
                    if behind:
                        sync_parts.append("-{}".format(behind))
                    sc = tc.get("git_sync", BRIGHT_BLACK)
                    parts.append(colorize(
                        "sync:" + "/".join(sync_parts), sc
                    ))
                if parts:
                    sections.append(" ".join(parts))

    return sections


# Sections to drop at each width breakpoint (widest first).
# Below 120 cols: drop least-essential sections progressively.
_COMPACT_DROP = [
    "git_extras", "version", "cc_version", "clock", "worktree",
    "sessions", "tools", "latency", "context_size", "session_name",
    "rate_limits", "output_style", "added_dirs", "effort", "git_worktree",
]
_NARROW_DROP = _COMPACT_DROP + [
    "cache", "burn", "lines", "budget", "agent", "model",
]


def _apply_responsive(sections_list, term_width):
    """Filter section list based on terminal width.

    >= 120 cols: full layout (no changes)
    80-119 cols: compact (drop non-essential extras)
    < 80 cols:   narrow (essentials only)
    """
    if term_width >= 120:
        return sections_list

    if term_width >= 80:
        drop = set(_COMPACT_DROP)
    else:
        drop = set(_NARROW_DROP)

    return [s for s in sections_list if s not in drop]


def render(data, theme_name="default"):
    """Render the statusline as one or two lines.

    Automatically adapts layout based on terminal width:
    - >= 120 cols: full detail
    - 80-119 cols: compact (drops extras like git_extras, version, clock)
    - < 80 cols: narrow (essentials only — bar, tokens, cost, duration, branch)

    Args:
        data: Parsed JSON dict from Claude Code.
        theme_name: Name of theme to use.

    Returns:
        Formatted statusline string (may contain newline for two-line output).
    """
    theme = get_theme(theme_name)
    n = _normalize(data)
    sep = colorize(theme["separator"], theme["colors"]["separator"])

    term_width = shutil.get_terminal_size((120, 24)).columns
    line1 = _apply_responsive(theme["line1"], term_width)
    line2 = _apply_responsive(theme["line2"], term_width)

    line1_sections = _render_sections(n, line1, theme)
    line2_sections = _render_sections(n, line2, theme)

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
            "added_dirs": ["/home/user/projects/shared-lib"],
            "git_worktree": False,
        },
        "model": {
            "display_name": "Opus 4.6 (1M context)",
        },
        "session_id": "demo-session",
        "session_name": "refactor auth",
        "version": "2.1.92",
        "output_style": {"name": "explanatory"},
        "rate_limits": {
            "five_hour": {
                "used_percentage": 34,
                "resets_at": int(time.time()) + 7_200,  # 2 hours from now (seconds)
            },
            "seven_day": {
                "used_percentage": 18,
                "resets_at": int(time.time()) + 432_000,  # 5 days from now (seconds)
            },
        },
    }


def _print_indented(text, indent="  "):
    """Print multiline text with consistent indentation."""
    for line in text.split("\n"):
        print(indent + line)


def cmd_demo():
    """Show demo output for all themes."""
    data = _demo_data()

    # Mock session functions so demo shows tools/sessions sections
    import claude_statusline.cli as _self
    _orig_tool_count = _self.get_session_tool_count
    _orig_session_count = _self.get_today_session_count
    _self.get_session_tool_count = lambda sid: 42
    _self.get_today_session_count = lambda: 3

    try:
        print("claude-status v{} — theme demos\n".format(__version__))
        for name in ("default", "minimal", "powerline", "nord", "tokyo-night", "gruvbox", "rose-pine", "focus"):
            print("  {}:".format(name))
            _print_indented(render(data, name))
            print()

        # Also show warning state (93% triggers !CTX via percentage check)
        warn_data = json.loads(json.dumps(data))
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
    finally:
        try:
            _self.get_session_tool_count = _orig_tool_count
        except Exception:
            pass
        try:
            _self.get_today_session_count = _orig_session_count
        except Exception:
            pass


def cmd_install(theme_name="default"):
    """Install claude-status into Claude Code settings."""
    settings_file = _settings_path()
    settings = {}

    # Read existing settings and create backup
    if os.path.exists(settings_file):
        backup_file = settings_file + ".bak"
        try:
            shutil.copy2(settings_file, backup_file)
        except OSError as e:
            print("Warning: could not create backup: {}".format(e),
                  file=sys.stderr)
        try:
            with open(settings_file, "r", encoding="utf-8") as f:
                settings = json.load(f)
        except (json.JSONDecodeError, IOError):
            print("Warning: could not parse existing settings.json")
            print("  Backup saved to: {}.bak".format(settings_file))
            print("  Creating new settings with statusLine config only")

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


def cmd_uninstall():
    """Remove claude-status from Claude Code settings.

    Removes the statusLine key from settings.json. If a .bak backup
    exists with a previous statusLine config, offers to restore it.
    """
    settings_file = _settings_path()

    if not os.path.exists(settings_file):
        print("No settings file found at {}".format(settings_file))
        return

    try:
        with open(settings_file, "r", encoding="utf-8") as f:
            settings = json.load(f)
        if not isinstance(settings, dict):
            settings = {}
    except (json.JSONDecodeError, IOError) as e:
        print("Error: could not read {}: {}".format(settings_file, e))
        return

    if "statusLine" not in settings:
        print("claude-status is not installed (no statusLine in settings).")
        return

    # Check for backup with previous statusLine config
    backup_file = settings_file + ".bak"
    restored = False
    if os.path.exists(backup_file):
        try:
            with open(backup_file, "r", encoding="utf-8") as f:
                backup = json.load(f)
            if not isinstance(backup, dict):
                backup = {}
            prev_sl = backup.get("statusLine")
            if prev_sl and prev_sl != settings.get("statusLine"):
                settings["statusLine"] = prev_sl
                restored = True
        except (json.JSONDecodeError, IOError) as e:
            print("Warning: backup exists but could not be read: {}".format(e),
                  file=sys.stderr)

    if not restored:
        del settings["statusLine"]

    try:
        with open(settings_file, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except IOError as e:
        print("Error writing settings: {}".format(e))
        return

    if restored:
        print("Restored previous statusLine config from backup.")
        print("  statusLine: {}".format(settings.get("statusLine")))
    else:
        print("Removed statusLine from {}".format(settings_file))

    print()
    print("Restart Claude Code for the change to take effect.")
    print("To fully uninstall: pip uninstall claude-status")


_THEME_DESCRIPTIONS = {
    "default": "full detail, clean separators",
    "minimal": "essentials only, compact",
    "powerline": "Nerd Font separators",
    "nord": "cool blue tones",
    "tokyo-night": "purple and blue accents",
    "gruvbox": "warm retro palette",
    "rose-pine": "soft muted pinks",
    "focus": "single line, minimal footprint",
}


def cmd_setup():
    """Interactive setup wizard for first-time configuration."""
    print("claude-status v{} — setup wizard\n".format(__version__))

    # Step 1: Show theme list with short descriptions
    theme_names = ["default", "minimal", "powerline",
                   "nord", "tokyo-night", "gruvbox", "rose-pine", "focus"]

    print("Available themes:\n")
    for i, name in enumerate(theme_names, 1):
        desc = _THEME_DESCRIPTIONS.get(name, "")
        print("  [{}] {:12s} — {}".format(i, name, desc))

    custom_idx = len(theme_names) + 1
    print("  [{}] {:12s} — load from ~/.claude/claude-status-theme.json".format(
        custom_idx, "custom"
    ))
    print()

    try:
        choice = input("Choose a theme [1-{}] (default: 1): ".format(
            custom_idx
        )).strip()
    except (EOFError, KeyboardInterrupt):
        print("\nSetup cancelled.")
        return

    if not choice:
        theme_choice = "default"
    else:
        try:
            idx = int(choice) - 1
            if idx == len(theme_names):
                theme_choice = "custom"
            elif 0 <= idx < len(theme_names):
                theme_choice = theme_names[idx]
            else:
                print("Invalid choice, using default.")
                theme_choice = "default"
        except ValueError:
            print("Invalid choice, using default.")
            theme_choice = "default"

    # Show preview of selected theme
    data = _demo_data()

    import claude_statusline.cli as _self
    _orig_tool_count = _self.get_session_tool_count
    _orig_session_count = _self.get_today_session_count
    _self.get_session_tool_count = lambda sid: 42
    _self.get_today_session_count = lambda: 3

    try:
        print("\n  Preview:")
        _print_indented(render(data, theme_choice), "    ")
        print()
    finally:
        try:
            _self.get_session_tool_count = _orig_tool_count
        except Exception:
            pass
        try:
            _self.get_today_session_count = _orig_session_count
        except Exception:
            pass

    # Step 2: Budget configuration
    try:
        budget_input = input(
            "Set a daily budget in USD? (e.g., 10.00, or press Enter to skip): "
        ).strip()
    except (EOFError, KeyboardInterrupt):
        print("\nSetup cancelled.")
        return

    budget = None
    if budget_input:
        try:
            budget = float(budget_input.lstrip("$"))
            if budget <= 0:
                print("Budget must be positive, skipping.")
                budget = None
        except ValueError:
            print("Invalid amount, skipping budget.")

    # Step 3: Write budget config if set
    if budget is not None:
        budget_path = os.path.join(
            os.path.expanduser("~"), ".claude", "claude-status-budget.json"
        )
        try:
            os.makedirs(os.path.dirname(budget_path), exist_ok=True)
            with open(budget_path, "w", encoding="utf-8") as f:
                json.dump({"daily_budget_usd": budget}, f, indent=2)
                f.write("\n")
            print("  Budget saved: ${:.2f}/day".format(budget))
        except OSError as e:
            print("  Warning: could not save budget config: {}".format(e))

    # Step 4: Install statusLine config
    print()
    cmd_install(theme_choice)

    # Step 5: Summary
    print()
    print("Setup complete!")
    print("  Theme: {}".format(theme_choice))
    if budget is not None:
        print("  Budget: ${:.2f}/day".format(budget))
    print()
    print("Tip: Add \"refreshInterval\": 10 to your statusLine config")
    print("     for periodic updates (clock, sessions, rate limits).")
    print()
    print("Preview all themes: claude-status --demo")
    print("Diagnostics: claude-status --doctor")
    print("Uninstall: claude-status --uninstall")


def cmd_doctor():
    """Run diagnostics and print system info."""
    print("claude-status v{} — diagnostics\n".format(__version__))

    # System info
    print("System:")
    print("  Python:   {} ({})".format(platform.python_version(), sys.executable))
    if sys.version_info[:2] < (3, 8):
        print("  WARNING:  Python 3.8+ required")
    print("  OS:       {} {}".format(platform.system(), platform.release()))
    print("  Platform: {}".format(platform.platform()))
    print("  Encoding: {}".format(sys.stdout.encoding))
    print()

    # PATH check
    print("PATH:")
    which = shutil.which("claude-status")
    if which:
        print("  claude-status: {}".format(which))
    else:
        print("  claude-status: NOT FOUND in PATH")
        print("  Try: python -m claude_statusline --install")
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
            if isinstance(sl, dict):
                ri = sl.get("refreshInterval")
                if ri:
                    print("  refreshInterval: {}s".format(ri))
        except Exception as e:
            print("  Error reading settings: {}: {}".format(type(e).__name__, e))
    else:
        print("  Settings file not found")
    print()

    # Config file validation
    home = os.path.expanduser("~")
    claude_dir = os.path.join(home, ".claude")
    print("Config files:")
    budget_path = os.path.join(claude_dir, "claude-status-budget.json")
    if os.path.isfile(budget_path):
        try:
            with open(budget_path, "r", encoding="utf-8") as f:
                budget_data = json.load(f)
            print("  Budget: {} (valid)".format(budget_path))
            if isinstance(budget_data, dict):
                if "daily_budget_usd" in budget_data:
                    print("    daily_budget_usd: {}".format(budget_data["daily_budget_usd"]))
                if "compaction_threshold_pct" in budget_data:
                    print("    compaction_threshold_pct: {}".format(budget_data["compaction_threshold_pct"]))
        except (json.JSONDecodeError, IOError) as e:
            print("  Budget: {} (INVALID: {})".format(budget_path, e))
    else:
        print("  Budget: not configured")

    theme_path = os.path.join(claude_dir, "claude-status-theme.json")
    if os.path.isfile(theme_path):
        try:
            with open(theme_path, "r", encoding="utf-8") as f:
                json.load(f)
            print("  Theme:  {} (valid)".format(theme_path))
        except (json.JSONDecodeError, IOError) as e:
            print("  Theme:  {} (INVALID: {})".format(theme_path, e))
    else:
        print("  Theme:  not configured")
    print()

    # Permissions
    print("Permissions:")
    if os.path.isdir(claude_dir):
        print("  ~/.claude/: {}".format(
            "writable" if os.access(claude_dir, os.W_OK) else "NOT WRITABLE"
        ))
    else:
        print("  ~/.claude/: directory not found")
    tmp = tempfile.gettempdir()
    print("  Temp dir:   {} ({})".format(
        tmp, "writable" if os.access(tmp, os.W_OK) else "NOT WRITABLE"
    ))
    print()

    # Check git
    branch = get_branch()
    print("Git:")
    print("  Branch: {}".format(branch or "(not in a git repo)"))
    print()

    # Terminal capabilities
    print("Terminal:")
    term = os.environ.get("TERM", "(not set)")
    cols = shutil.get_terminal_size((120, 24)).columns
    print("  TERM:    {}".format(term))
    print("  Columns: {}".format(cols))
    if cols >= 120:
        print("  Layout:  full")
    elif cols >= 80:
        print("  Layout:  compact")
    else:
        print("  Layout:  narrow")
    print("  Unicode: \u2588\u2591\u2593 \u2387 \ue0b0")
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
    parser.add_argument("--uninstall", action="store_true", help="Remove from Claude Code settings")
    parser.add_argument("--setup", action="store_true", help="Interactive setup wizard")
    parser.add_argument("--doctor", action="store_true", help="Run diagnostics")
    parser.add_argument("--theme", default="default",
                        choices=["default", "minimal", "powerline",
                                 "nord", "tokyo-night", "gruvbox", "rose-pine",
                                 "focus", "custom"],
                        help="Theme for this render (default: default). "
                             "Use --install --theme NAME or --setup to persist. "
                             "'custom' loads ~/.claude/claude-status-theme.json")

    args = parser.parse_args()

    if args.demo:
        cmd_demo()
        return

    if args.install:
        cmd_install(args.theme)
        return

    if args.uninstall:
        cmd_uninstall()
        return

    if args.setup:
        cmd_setup()
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

    try:
        output = render(data, args.theme)
    except Exception as exc:
        print("claude-status: render error: {}".format(exc), file=sys.stderr)
        output = ""
    if output:
        print(output)


if __name__ == "__main__":
    main()
