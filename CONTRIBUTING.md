# Contributing to claude-status

Thanks for your interest in contributing! Please read our [Code of Conduct](CODE_OF_CONDUCT.md) before getting started.

## Development Setup

```bash
git clone https://github.com/mkalkere/claude-statusline.git
cd claude-statusline
pip install -e .
cp .github/hooks/pre-commit .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
```

The pre-commit hook scans for secrets (API keys, passwords) and blocks the commit if any are found.

## Running Tests

```bash
python -m unittest discover tests/
```

## Adding a Theme

1. Open `claude_statusline/themes.py`
2. Add a new entry to the `THEMES` dict following the existing pattern
3. Add the theme name to the `--theme` choices in `cli.py`
4. Add tests for the new theme in `tests/test_all.py`
5. Update `README.md` with a demo of the new theme

## Code Style

- Python 3.8 compatible — no walrus operator, no `match` statements
- Zero external dependencies — stdlib only
- Format strings use `.format()`, not f-strings (Python 3.5 compat isn't needed, but consistency matters)

## Submitting Changes

1. Fork the repo and create a feature branch
2. Make your changes with tests
3. Run `python -m unittest discover tests/` — all tests must pass
4. Open a pull request with a clear description

## Reporting Bugs

Open an issue with:
- OS and Python version
- Terminal emulator
- Output of `claude-status --doctor`
- What you expected vs what happened
