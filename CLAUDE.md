# Project Rules — claude-statusline

## Non-negotiable rules

1. **NEVER add AI attribution** — No "Co-Authored-By", "Generated with", "Written by", or any reference to Claude, Gemini, or any AI tool in commits, PRs, release notes, documentation, or any output. Zero exceptions.

2. **No secrets or credentials** — Never commit API keys, tokens, passwords, paths with real usernames, or any sensitive data. All paths in code/tests must use generic placeholders like `/home/user/projects/myapp`.

3. **Zero external dependencies** — Pure Python stdlib only. No pip packages. This is a core selling point of the project. Never add dependencies without explicit approval.

4. **No references to other projects** — Don't mention competitor tools, internal projects, company names, or other repos in code, commits, or docs.

5. **High code quality** — This is a public open-source project on PyPI. Every change is visible to the community. Code must be production-grade.

## Development practices

- Always run the full test suite before committing
- Always run the PR review plugin (all 4 agents: code-reviewer, test-analyzer, silent-failure-hunter, comment-analyzer) and iterate until zero issues
- Check Gemini PR comments and address them
- Keep CHANGELOG.md up to date with every version
- Update README feature tables and examples when adding features
- Bump version in both `__init__.py` and `pyproject.toml`
- After merge, create a GitHub release to trigger PyPI publish
- Close related GitHub issues after release
- Install from PyPI and verify the release works

## Code patterns

- Use `_first()` helper for numeric fields (not `or` which drops zeros)
- Use `_safe_num()` for coercing external numeric values
- Use `isinstance()` checks before `.get()` on external JSON data
- All section renderers must degrade gracefully — never crash
- `render()` call in `main()` is wrapped in try/except as defense-in-depth
- Cache reads use TTL-based file caching in user-scoped temp directories
- Cache writes use atomic `os.replace()` pattern
- Git operations use 5s cache TTL, "not available" state uses 60s TTL
- Tool count uses 10s TTL, other session data uses 30s TTL

## Testing

- stdlib `unittest` only — no pytest, no mock library
- Tests must be deterministic (provide explicit `git_branch` in test data, don't depend on environment)
- Test all edge cases: present, absent, empty, zero, non-dict, non-list, corrupted JSON
- Monkey-patch at the `cli_mod` level when testing section renderers
- Clear cache files before tests that depend on fresh reads

## SEO and discoverability

- Keep pyproject.toml keywords comprehensive
- README must have FAQ and Troubleshooting sections
- Feature tables must list every metric with example output
- Comparison table must be kept current
