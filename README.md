# claude-statusline

**Beautiful, informative status line for Claude Code — zero dependencies, cross-platform.**

[![PyPI version](https://img.shields.io/pypi/v/claude-statusline)](https://pypi.org/project/claude-statusline/)
[![Python versions](https://img.shields.io/pypi/pyversions/claude-statusline)](https://pypi.org/project/claude-statusline/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/mkalkere/claude-statusline/actions/workflows/ci.yml/badge.svg)](https://github.com/mkalkere/claude-statusline/actions)

```
[████████░░░░░░░░░░░░] in:245K out:18K cache:78% $0.73 burn:2.1K/min 12m05s +247 -38 ⎇ feat/statusline (200K)
```

## Why claude-statusline?

- **Zero dependencies** — pure Python stdlib, installs in seconds
- **Cross-platform** — Windows, macOS, Linux — tested on all three
- **pip install** — no npm, no cargo, no compilation

## Quick Start

```bash
pip install claude-statusline
claude-statusline --install
```

Restart Claude Code. Done.

## Installation

### pip (recommended)
```bash
pip install claude-statusline
claude-statusline --install
```

### pipx (isolated)
```bash
pipx install claude-statusline
claude-statusline --install
```

### uvx (fast)
```bash
uvx claude-statusline --install
```

### From source
```bash
git clone https://github.com/mkalkere/claude-statusline.git
cd claude-statusline
pip install -e .
claude-statusline --install
```

### What `--install` does

Adds `statusLine` to `~/.claude/settings.json` — preserves all existing settings.
Use `--theme` to pick a theme: `claude-statusline --install --theme powerline`

> **Command not found?** Make sure your Python scripts directory is in PATH.
> Fallback: `python -m claude_statusline --install`

## Features

| Feature | Description |
|---------|-------------|
| Context bar | 20-char progress bar, green/yellow/red adaptive |
| Token counts | Input/output with human-readable formatting (245K, 1.2M) |
| Cache efficiency | % of tokens served from prompt cache |
| Cost tracking | Session cost in USD |
| Burn rate | Tokens/min consumption rate |
| Session duration | Wall-clock time |
| Lines changed | +added / -removed with git-diff colors |
| Git branch | Color-coded (green=main, yellow=feature) |
| Context size | (200K) vs (1M) indicator |
| !CTX warning | Red alert when exceeding 200K tokens |
| Vim mode | NORMAL/INSERT indicator |
| Agent name | Shows active subagent |
| Worktree | Branch indicator when in worktree |

## Themes

### default
```
[████████░░░░░░░░░░░░] │ in:245K out:18K │ cache:78% │ $0.73 │ burn:2.1K/min │ 12m05s │ +247 -38 │ ⎇ feat/statusline │ (200K)
```

### minimal
```
●●●●●●●●·············· 245K $0.73 12m05s ⎇ feat/statusline
```

### powerline
```
████████░░░░░░░░░░░░  in:245K out:18K  cache:78%  $0.73  burn:2.1K/min  12m05s  +247 -38  ⎇ feat/statusline  (200K)
```

Preview all themes: `claude-statusline --demo`

## CLI Reference

| Command | Description |
|---------|-------------|
| `claude-statusline --install` | Auto-configure Claude Code |
| `claude-statusline --install --theme powerline` | Install with specific theme |
| `claude-statusline --demo` | Preview all themes with sample data |
| `claude-statusline --doctor` | Diagnostics: Python, OS, terminal, settings |
| `claude-statusline --version` | Version info |
| `claude-statusline --help` | Usage |

## Manual Configuration

If you prefer manual setup, add to `~/.claude/settings.json`:

```json
{
  "statusLine": "claude-statusline"
}
```

Or with a theme:

```json
{
  "statusLine": "claude-statusline --theme minimal"
}
```

## Comparison

| Feature | claude-statusline | ccstatusline | claude-powerline |
|---------|:-:|:-:|:-:|
| Language | Python | Node.js | Bash |
| Dependencies | 0 | npm | bash-only |
| pip install | Yes | No | No |
| Cross-platform | Yes | Partial | Unix only |
| Themes | 3 | 1 | 1 |
| Burn rate | Yes | No | No |
| Auto-install | Yes | Manual | Manual |

## Uninstall

```bash
pip uninstall claude-statusline
```

Then remove `"statusLine"` from `~/.claude/settings.json`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
