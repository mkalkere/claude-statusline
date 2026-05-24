# Release Playbook

This is the runbook a maintainer uses to ship a release of `claude-status` to PyPI. It exists because the rules in [CLAUDE.md](../CLAUDE.md) (test before commit, run the PR review plugin, create a release, verify on PyPI) describe *what* to do but not *how* or *in what order*. After several releases the workflow stabilized; this file captures it.

Read [CONTRIBUTING.md](../CONTRIBUTING.md) for first-time setup and [CLAUDE.md](../CLAUDE.md) for the project-wide non-negotiables. This document assumes you have both.

## When to use this

Every shipped release follows this playbook. A "release" is anything that bumps the version in `claude_statusline/__init__.py` and `pyproject.toml` and ends with a new tag on PyPI. There is no separate "small fix" path — even patch releases run through the same steps because the cost of skipping is silent regressions and the cost of running it is short.

If a change does not need to bump the version (typo in a comment, internal-only refactor with no behavioral effect), it can go to `main` via the normal PR flow without releasing. The playbook starts at the moment you decide a release is needed.

## Pre-flight

Before opening a branch, answer four questions:

1. **What problem does this release solve?** State it as one sentence. If you cannot, the release is not ready to be scoped.
2. **What is the smallest reasonable scope?** Default to one logical change per release. If two unrelated changes both need to ship, prefer two releases over one bundled release — easier to revert, easier to attribute regressions.
3. **Is there an open issue describing the problem?** If not, file one before branching. Public issues give users a discoverable URL for the change, let contributors weigh in early, and create a stable reference for the CHANGELOG and PR.
4. **What version bump does this warrant?** Follow [Semantic Versioning](https://semver.org/):
   - Patch (`0.x.y` → `0.x.(y+1)`) — bug fixes, no new user-facing features, no API changes.
   - Minor (`0.x.y` → `0.(x+1).0`) — new features, new sections, new themes, new CLI flags. The default for additive work.
   - Major (`x.0.0` → `(x+1).0.0`) — breaking changes to the CLI, config file format, or stdin schema we consume. Avoid these; we have many users.

## The branch-to-merge cycle

### 1. Branch

```bash
git checkout main
git pull --ff-only
git checkout -b <type>/<short-description>
```

Branch name convention: `feat/`, `fix/`, `docs/`, `chore/` prefix, then kebab-case description. The branch name shows up in the PR title and merge commit by default — pick something a contributor reading `git log` six months from now will understand.

Verify the test suite is green BEFORE making any changes:

```bash
python -m unittest discover tests/
```

A green baseline matters because if a later test failure is ambiguous, you want to be able to say "the test was passing on this commit" without doubt. Note the test count — it should grow over the release.

### 2. Implement

Keep commits **logically chunked**. One commit per discrete change. Example from a recent release:

- `fix(#NN): width detection regression on Claude Code 2.1.139+`
- `feat(#NN): activity counter and cache hit ratio sections`
- `chore: v0.6.0 — docs, version bump, expanded SEO keywords`

The chunking lets reviewers focus, lets `git bisect` find regressions, and lets you back out one change without disturbing others. Avoid mega-commits.

Run tests after each logical change. If a change breaks a test, the cause is local and obvious; if you batch ten changes and then run tests, you have ten suspects.

### 3. Run the review cycle

This is the project's quality gate. CLAUDE.md says "run all 4 agents and iterate until zero issues." Here is what that means in practice.

**The four agents** (from the `pr-review-toolkit` plugin):

| Agent | Hunts for |
|---|---|
| `code-reviewer` | Bugs, logic errors, security, project-convention violations |
| `pr-test-analyzer` | Test coverage gaps, missing inverse cases, untested branches |
| `silent-failure-hunter` | Inadequate error handling, fallbacks that mask real failures, swallowed exceptions |
| `comment-analyzer` | Comments that are inaccurate, stale, or fabricate claims |

**How to brief an agent.** A terse "review my code" produces shallow output. A specific brief produces actionable findings. Include four things:

1. **Context the agent needs** — files changed, what the change accomplishes, why.
2. **Things you already considered** — so the agent doesn't re-flag what you already addressed.
3. **Specific concerns to hunt for** — your hypotheses about where bugs might hide.
4. **Output format** — severity + file:line + fix. Cap the response length.

Example brief shape:

> Review branch `feat/foo` (3 commits, +500/-50 lines). Context: we changed X to handle Y because Z. We already considered A and rejected it because B. Specifically hunt for: (1) does the new X path handle empty input?, (2) is the cache-write atomic across the new branch?, (3) are the new tests deterministic?. Output: severity, file:line, problem, fix. Under 500 words.

**The cycle pattern**:

```
implement → 4 agents in parallel → batch fixes by severity → commit per logical fix → re-review the deltas → repeat
```

**When to stop.** The "zero issues" rule from CLAUDE.md needs interpretation. Stop when:

- Latest pass returns zero HIGH/MEDIUM findings, AND
- All LOW findings are either (a) fixed, (b) deferred to a tracked follow-up issue with reasoning, or (c) explicitly accepted with a comment explaining why.

You will hit diminishing returns. Cycle 1 typically finds CRITICAL/HIGH issues. Cycle 2 finds MEDIUM issues introduced by cycle 1 fixes. Cycle 3 is mostly LOW polish. Cycle 4+ is rare and usually means scope crept during the cycles — consider freezing scope and shipping.

**The "drop a feature when review reveals it's redundant" rule.** If review uncovers that a new feature is mathematically or behaviorally identical to an existing one, drop the new feature rather than ship duplicated functionality. The right answer is sometimes "less code." Document the drop in the CHANGELOG so users understand the decision.

### 4. Update CHANGELOG, version, and supporting docs

Before opening the PR:

- [ ] Bump `claude_statusline/__init__.py` `__version__`
- [ ] Bump `pyproject.toml` `version`
- [ ] Add a new section at the top of `CHANGELOG.md` with the version and date
- [ ] Follow the existing CHANGELOG structure: `### Added`, `### Changed`, `### Fixed`, `### Notes`
- [ ] In `### Notes`, state the new test count and the previous count (e.g. "All 409 tests pass (was 370, +39 new)")
- [ ] Update README feature tables and FAQ if the change is user-facing
- [ ] Update `AGENTS.md` if the change affects how coding agents install or configure the tool
- [ ] Update `pyproject.toml` keywords if the change introduces new search terms users would type

### 5. Open the PR

Push the branch and open a PR:

```bash
git push -u origin <branch>
gh pr create --title "<type>(#NN): short description" --body "<see below>"
```

PR body template:

```markdown
## Summary
- <one-bullet what changed>
- <one-bullet why>
- <one-bullet what was deferred and why>

## Closes
- Closes #NN
- Closes #MM

## Test plan
- [x] Full suite passes (N tests)
- [x] Smoke test of the new feature
- [x] Reviewed by all 4 agents through N cycles
- [x] CI matrix passes
```

The 21-job CI matrix (3 OS × 7 Python versions) runs automatically. Wait for it to complete before merging. **Do not merge red.**

### 6. Address Gemini review

GitHub's Gemini code-review bot posts comments on every PR. Read each carefully:

- Genuine bug or security issue → fix in a new commit on the branch.
- Suggestion you disagree with → reply on the PR with the reasoning. Don't silently dismiss.
- Style preference that conflicts with this codebase's conventions → reply citing the convention.

Never amend or force-push to address Gemini comments — use separate fix commits. Force-pushing an open PR rewrites the commit SHAs reviewers have already looked at, invalidates inline review threads, and makes `git bisect` harder. Separate fix commits keep the conversation linear.

### 7. Merge

Branch protection requires one approving review. Two paths:

- **External reviewer approved**: `gh pr merge <N> --squash`
- **Solo maintainer with full agent + Gemini trail**: `gh pr merge <N> --squash --admin`

The `--admin` flag bypasses the "require 1 approving review" rule using admin privileges. `enforce_admins: false` on the repo sanctions this for solo maintainers, but the bypass should always be explicit and documented in the merge — never automatic.

Squash-merge keeps `main` history linear. The merge commit subject becomes the squashed commit on `main`; use a clear, version-indicative subject.

### 8. Release

```bash
git checkout main
git pull --ff-only
# Extract the new version's CHANGELOG section
awk '/^## \[X.Y.Z\]/,/^## \[/' CHANGELOG.md | sed '$d' > /tmp/release-notes.md
gh release create vX.Y.Z --title "vX.Y.Z — short description" --notes-file /tmp/release-notes.md --target main
```

Creating the release triggers the `Publish to PyPI` GitHub Actions workflow automatically. Watch it:

```bash
gh run watch <run-id> --exit-status
```

Past runs complete in 25-60 seconds. If it fails, investigate before doing anything else — a failed publish means PyPI has the old version while the GitHub release claims the new one, which confuses users.

### 9. Verify on PyPI

```bash
# Confirm PyPI shows the new version
curl -sS -A "Mozilla/5.0" https://pypi.org/pypi/claude-status/json | python -c "import json,sys; print('latest:', json.load(sys.stdin)['info']['version'])"

# Install in a fresh venv and smoke-test
python -m venv /tmp/release-verify
/tmp/release-verify/Scripts/pip install --quiet claude-status==X.Y.Z  # Windows
# or: /tmp/release-verify/bin/pip install --quiet claude-status==X.Y.Z  # POSIX
/tmp/release-verify/Scripts/claude-status --version
# Render a sample stdin payload to confirm output renders correctly
```

This step is non-negotiable. PyPI publish has succeeded in CI before but produced a broken artifact (missing files, wrong entry point); only an actual install catches that.

### 10. Close issues and clean up

```bash
# Issues are usually auto-closed by merge syntax in the commit, but verify:
gh issue list --state open
# If anything related is still open, close with a release-linking comment:
gh issue close NN --comment "Fixed in vX.Y.Z. See https://github.com/.../releases/tag/vX.Y.Z."

# Delete the local branch (remote is auto-deleted by repo setting)
git branch -D <branch>

# Clean tmp
rm -rf /tmp/release-verify /tmp/release-notes.md
```

## Failure-mode catalog

These are upstream and host pitfalls the project has hit. Documented here so a future maintainer does not re-derive them. When you encounter one of these patterns, the playbook below is faster than first-principles debugging.

### Claude Code stdin schema changes

Claude Code's stdin JSON evolves quickly. Recent additions we track or have already integrated:

- `effort.level` (v2.1.119+) — thinking effort level. Integrated v0.5.8.
- `terminal.columns` (proposed, [#22115](https://github.com/anthropics/claude-code/issues/22115)) — terminal width. Forward-compat code in place; honored when present.
- `github.{pr_number, pr_url, repo}` (v2.1.148+) — PR context. Track integration status in CHANGELOG.
- Per-category cost breakdown (v2.1.150+) — `cost.by_category`. Track integration status.

When a new field appears, ask three questions before integrating: (1) is the field stable in Anthropic's docs or only observed in releases? (2) what does the field look like when absent (older Claude Code clients still need to work)? (3) does it warrant a new section or extend an existing one?

### Width detection regressions

Claude Code's hook subprocess context changes over releases in ways that break terminal-width detection:

- **2.1.139** (2026-05-11) — "hooks now run without terminal access" closed the `/dev/tty` escape hatch. `tput cols` started returning its terminfo stub (typically 80) without erroring. Defense: stub-rejection heuristic + process-tree walk + per-step `--doctor` report. See `_detect_terminal_width_report` in `cli.py`.

When investigating a new width-detection bug, run `claude-status --doctor` and inspect the `Width detection chain:` block. Every probe step reports its outcome ("winner", "rejected", "out of range", error type). The bug is usually visible in the chain output — a step that succeeded with a wildly wrong value, or a step that lied (returned 0 or a stub default without erroring).

If a new lower-layer signal starts lying, add a regression test in `TestClaudeCode2139WidthRegression` following the `test_*_returns_0_*_rejected_by_range_check` pattern. The generic "lying-signal" test pattern catches the next regression of this shape automatically.

### Line 2 truncation

Claude Code's TUI used `<Text wrap="truncate">` for the statusline, which silently truncated or dropped Line 2 when Line 1 overflowed terminal width. Tracked at [#28750](https://github.com/anthropics/claude-code/issues/28750) (closed without fix in 2026-03). Defense: two-stage adaptive layout (`_apply_responsive` coarse pre-filter + `_fit_to_width` precise post-render fit). See `cli.py` and the ARCHITECTURE.md "Responsive Layout" section.

**Status update (2026-05-12):** Claude Code 2.1.141 shipped a fix for the per-line truncation behavior (each line now truncates independently at terminal width rather than the cumulative-cap-eats-subsequent-lines pattern). The fix is tracked at [#58028](https://github.com/anthropics/claude-code/issues/58028) (closed COMPLETED 2026-05-12), a distinct issue from the older [#28750](https://github.com/anthropics/claude-code/issues/28750) which described the user-visible symptom. The fix makes our Stage-2 `_fit_to_width` more effective when width detection succeeds — but does NOT change the width-detection picture. [#22115](https://github.com/anthropics/claude-code/issues/22115) (request: pass terminal columns in stdin) is still open as of v0.6.1, and the 2.1.139 "hooks now run without terminal access" regression means we still cannot trust the subprocess context to know the real terminal width in many configurations. **Keep `_FULL_LAYOUT_MIN_COLS = 150` and `_COMPACT_LAYOUT_MIN_COLS = 100` conservative.** A future release may gate threshold relaxation on `version >= 2.1.141 AND high-confidence width detection`, but only after community feedback confirms the upstream fix is reliable across terminal emulators.

When investigating a "Line 2 disappeared" report: (1) run `claude-status --doctor` and check `Columns:` reflects the user's real terminal width; (2) check whether OSC 8 links are enabled (their invisible escape bytes inflate measured width); (3) ask what version of Claude Code — 2.1.141+ has the upstream per-line fix, but if width detection is also failing the user can set `CLAUDE_STATUSLINE_WIDTH` as an override.

### Rate-limits epoch timestamp bug

On a fresh 5h or 7d window with no usage data yet, Claude Code returns the `resets_at` epoch timestamp (~1.7e9) in `used_percentage` instead of 0 or null. Tracked at [#52326](https://github.com/anthropics/claude-code/issues/52326), still open. Defense: values >= 1e6 are treated as "no data yet" and the section is hidden. See `_normalize` in `cli.py` and `TestRateLimitsEpochTimestampGuard`.

### Settings file corruption

Tests that install/uninstall the statusline via `--install` and `--uninstall` can leave `~/.claude/settings.json` empty or partially written if the test process is killed. The install command is defensive (preserves other keys, atomic write via `os.replace()`), but a killed process between read and write can corrupt. After running install/uninstall tests, verify your own settings file: `cat ~/.claude/settings.json | python -m json.tool`.

### Transcript path security

`transcript_path` comes from external JSON on stdin. A malicious or buggy upstream could supply an arbitrary path. Defense: `get_session_activity_count` rejects any path whose `os.path.realpath` resolves outside `~/.claude/`. Use `_CLAUDE_DIR_REAL` for the comparison so users with a symlinked `~/.claude/` (common on macOS / NAS setups) are not silently locked out.

When investigating "the `activity` section is silently absent": run `claude-status --doctor` and inspect the `Transcript:` block. The `Parse:` line disambiguates between idle / file missing / no user in window / dangling symlink.

## Conventions that keep showing up

These are decisions made repeatedly across releases that are worth pinning here:

- **Cache only non-zero counts** for any "live" metric where zero can mean either "no activity" or "transient parse failure." Caching zero blocks recovery for the full TTL window. See `get_session_activity_count`.
- **`O_NOCTTY | O_NONBLOCK`** when opening anything that might be a TTY device (e.g., `/proc/<pid>/fd/2`). Without `O_NOCTTY`, an ancestor's TTY can become the current process's controlling terminal, with rare SIGTTIN/SIGTTOU on background process groups.
- **Resolve `_CLAUDE_DIR_REAL` once at module load**, not per-call. The realpath cost is tiny but doing it once is cleaner.
- **Distinguish read-error from no-result** in parse functions that return numeric counts. Returning `0` on read error conflates with "successfully read, no matches" and produces misleading diagnostics.
- **Status strings should disambiguate the cause of every zero**. If a function can return 0 for multiple reasons, return `(count, status_str)` and have the caller log or display the status when relevant.
- **Add the lying-signal regression test pattern** for any new probe step that could silently return a wrong value. The pattern is short, mechanical, and prevents the next upstream regression of the same shape.
- **Inline imports inside `try` blocks hide programmer errors** as runtime failures. Prefer module-top imports so `ImportError` surfaces at startup.
- **Narrow `except` clauses to expected failure modes.** `except Exception` swallows programmer errors. Prefer `except (OSError, ValueError, json.JSONDecodeError)` or whatever the actual expected set is.

## What this playbook does NOT cover

- Setting up the development environment for the first time → see [CONTRIBUTING.md](../CONTRIBUTING.md).
- The architecture and module layout → see [ARCHITECTURE.md](../ARCHITECTURE.md).
- The rules that never change → see [CLAUDE.md](../CLAUDE.md).
- Security disclosure process → see [SECURITY.md](../SECURITY.md).
- How to install the package as a user → see [README.md](../README.md).
- How a coding agent installs the package on a user's behalf → see [AGENTS.md](../AGENTS.md).
