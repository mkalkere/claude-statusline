# Agent Install Guide

This file is for coding agents (Claude Code, Cursor, Aider, Continue, Cline, etc.) acting on a user's behalf. It contains the exact non-interactive commands needed to install, verify, update, and uninstall `claude-status` — the zero-dependency status line for Claude Code.

If you are a human reader: the regular [README](README.md) has a friendlier walkthrough.

## TL;DR install (one block)

```bash
pip install -U claude-status && claude-status --install && claude-status --print-config
```

After this command:
- The package is installed (or upgraded) from PyPI.
- `~/.claude/settings.json` has `statusLine.command = "claude-status"` (any prior config is backed up to `~/.claude/settings.json.claude-status-backup`).
- `--print-config` prints the current install state in a machine-readable form so you can confirm success.

The user must restart Claude Code for the status line to appear. Tell them this explicitly.

## Verify a clean install

```bash
claude-status --print-config
```

A successful install prints (machine-readable, stable across versions):

```
installed=true
command=claude-status
type=command
refreshInterval=<absent or integer>
theme=<theme name or "default">
version=0.5.4
settings_path=/home/user/.claude/settings.json
```

If `installed=false`, the install did not complete — re-run `claude-status --install` and check `claude-status --doctor` for environment issues (PATH, write permissions on `~/.claude/`).

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

Prints Python version, install path, settings.json status, config files, write permissions, terminal capabilities, and the current responsive-layout bucket. Run this first when reporting any issue.

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
claude-status --print-config 2>/dev/null | grep -q '^installed=true'
```
Returns exit code 0 if installed, 1 otherwise. Safe in scripts.

## Where to find more

- [README.md](README.md) — full feature list, screenshots, FAQ
- [ARCHITECTURE.md](ARCHITECTURE.md) — render pipeline, two-stage responsive layout, caching
- [CHANGELOG.md](CHANGELOG.md) — release history
- [llms.txt](llms.txt) — concise summary for LLM crawlers (machine-friendly index)
