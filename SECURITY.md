# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability, please report it privately:

1. **Do NOT open a public issue**
2. Email the maintainer directly (see GitHub profile)
3. Include steps to reproduce and potential impact

You should receive a response within 48 hours. Security fixes will be released as patch versions.

## Scope

This package reads from stdin and writes to stdout. It also:
- Reads/writes `~/.claude/settings.json` (via `--install`)
- Runs `git rev-parse` subprocess (for branch detection)
- Writes a cache file to the system temp directory

These are the only system interactions and the primary attack surface.
