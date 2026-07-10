# Agent Install Guide

This file is for coding agents (Claude Code, Cursor, Aider, Continue, Cline, etc.) acting on a user's behalf. It contains the exact non-interactive commands needed to install, verify, update, and uninstall `claude-status` — the zero-dependency status line for Claude Code.

If you are a human reader: the regular [README](README.md) has a friendlier walkthrough.

## TL;DR install (one block)

```bash
pip install -U claude-status && claude-status --install && claude-status --print-config
```

After this command:
- The package is installed (or upgraded) from PyPI.
- `~/.claude/settings.json` has `statusLine.command = "claude-status"` (any prior config is backed up to `~/.claude/settings.json.bak`).
- `--print-config` prints the current install state in a machine-readable form so you can confirm success.

The user must restart Claude Code for the status line to appear. Tell them this explicitly.

## Verify a clean install

```bash
claude-status --print-config
```

A successful install prints 9 `key=value` lines in stable order (8 original + `subagent`, appended in v0.13.0 — key=value and first-8-lines parsers keep working; a parser asserting an exact 8-line count needs updating) — values are always present (empty string when absent) so a parser can rely on a fixed line count:

```
installed=true
command=claude-status
type=command
refreshInterval=<integer or empty>
theme=<theme name; "default" when --theme not specified>
version=<package version, e.g. 0.5.5>
settings_path=<absolute path to settings.json>
settings_state=ok
subagent=<installed | installed_missing_flag | not_installed>
```

`subagent` reports the optional `subagentStatusLine` hook (per-task agent rows, v0.13.0+). To enable it on the user's behalf, add to settings.json alongside `statusLine`:

```json
"subagentStatusLine": {"type": "command", "command": "claude-status --subagent"}
```

**Exit codes** (relied on by scripts):
- `0` — installed and ready
- `1` — not installed (settings missing, statusLine missing, or statusLine points at a different tool)
- `2` — settings.json exists but is corrupt or unreadable. **Agents must NOT auto-install on exit code 2** — running `--install` would overwrite recoverable user config. Surface the stderr diagnostic to the user and stop.

If `installed=false` with exit code 1, re-run `claude-status --install` and check `claude-status --doctor` for environment issues (PATH, write permissions on `~/.claude/`).

## Install with a specific theme

```bash
claude-status --install --theme focus       # single-line layout
claude-status --install --theme nord        # nord color palette
claude-status --install --theme tokyo-night # tokyo-night palette
```

Available themes: `default`, `minimal`, `powerline`, `nord`, `tokyo-night`, `gruvbox`, `rose-pine`, `focus`.

## Update

```bash
pip install -U claude-status
```

No re-install needed — Claude Code re-runs the installed binary on every render, so the new version takes effect on the next render cycle. The user does not need to restart Claude Code for an update (only for a fresh install where `settings.json` was modified).

## Uninstall

```bash
claude-status --uninstall   # restores prior settings.json from backup
pip uninstall -y claude-status
```

`--uninstall` removes the `statusLine` config from `~/.claude/settings.json` and restores any previously-backed-up config. The PyPI package itself is removed by `pip uninstall`.

## Diagnose problems

```bash
claude-status --doctor
```

Prints Python version, install path, settings.json status, config files, write permissions, terminal capabilities, the current responsive-layout bucket, and the **per-step width-detection report** (added in v0.6.0 — shows which signal won and which were rejected, e.g. `tput cols: 80 (likely terminfo stub — rejected; no earlier TTY signal)`). Run this first when reporting any issue, especially "wrong layout on a wide terminal" on Claude Code 2.1.139+.

## Key facts for agents

- **Zero external dependencies** — pure Python stdlib only. No pip packages get pulled in. Safe to install in any Python ≥3.8 environment.
- **No daemon, no network, no background processes** — runs as a stdin-to-stdout pipe in single-digit milliseconds. Cannot leak data or affect other processes.
- **Configuration files** all live under `~/.claude/`:
  - `settings.json` — Claude Code's own config; we add a `statusLine` key.
  - `claude-status-budget.json` — daily budget, compaction threshold, OSC 8 toggle, disabled sections (all optional).
  - `claude-status-theme.json` — custom theme overrides (optional, only used with `--theme custom`).
- **Cross-platform** — tested on Linux, macOS, Windows. Python 3.8 through 3.14.
- **Public OSS, MIT licensed** — repository at https://github.com/mkalkere/claude-statusline, package at https://pypi.org/project/claude-status/.

## Common agent recipes

### "User wants a status line for Claude Code"
```bash
pip install -U claude-status && claude-status --install && claude-status --print-config
```
Then tell the user: "Restart Claude Code to see the status line."

### "User wants the focus (single-line) theme"
```bash
pip install -U claude-status && claude-status --install --theme focus
```

### "User wants a daily budget warning"
```bash
mkdir -p ~/.claude
cat > ~/.claude/claude-status-budget.json <<'JSON'
{"daily_budget_usd": 10.00}
JSON
```
The cost indicator turns yellow at 70% and red at 90% of the daily limit. No restart required.

### "Is claude-status already set up?"
```bash
if claude-status --print-config >/dev/null 2>&1; then
    echo "claude-status is installed"
else
    rc=$?
    if [ "$rc" = "2" ]; then
        echo "settings.json is corrupt — do not auto-install (would overwrite recoverable user config)"
    else
        echo "claude-status is not installed"
    fi
fi
```
Exit code 0 = installed, 1 = not installed, 2 = settings.json corrupt/unreadable (do not auto-install on this).

## Where to find more

- [README.md](README.md) — full feature list, screenshots, FAQ
- [ARCHITECTURE.md](ARCHITECTURE.md) — render pipeline, two-stage responsive layout, caching
- [CHANGELOG.md](CHANGELOG.md) — release history
- [llms.txt](llms.txt) — concise summary for LLM crawlers (machine-friendly index)
