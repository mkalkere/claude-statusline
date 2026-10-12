#!/usr/bin/env python3
"""Measure how often the status line's layout changes during a session.

Repo tooling, not shipped in the package. Used to check that the
overflow spill (cli._spill_dropped) does not make sections come and go
noticeably more often than the per-line fit already does, and to
reproduce the figures quoted for it in CHANGELOG.md:

    python scripts/layout_churn.py

It renders simulated sessions — 600 frames, 30 seconds apart, with
cost, token counts, the rate-limit countdown and the commit age all
moving — at every second width from 160 to 220, once with the spill
off and once with it on, and counts the frames in which any section
is on a different line (or has appeared or disappeared) compared with
the frame before. Two seeded sessions per profile, so the run is
identical every time.

Everything that reads the clock, git, or user configuration is pinned
(the same discipline as render_svg.py), so the result does not depend
on the machine it runs on.
"""

import os
import random
import sys
import time as real_time

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

# A width override or a redirected settings path would change what is
# measured; clear them before the package reads the environment.
os.environ.pop("CLAUDE_STATUSLINE_WIDTH", None)
os.environ.pop("COLUMNS", None)

import claude_statusline.cli as cli  # noqa: E402
import claude_statusline.formatters as formatters  # noqa: E402

START = 1_800_000_000          # fixed "now" for frame 0, epoch seconds
FRAMES = 600
FRAME_SECONDS = 30
WIDTHS = list(range(160, 221, 2))
SEEDS = (1, 2)

PROFILES = {
    # Long branch, a session name, an output style, an added directory,
    # and vim mode / an agent / stash and unpushed commits coming and
    # going: Line 2 overflows at most of these widths.
    "busy": dict(branch="feat/statusline", name="refactor auth",
                 style="explanatory", dirs=["/home/user/projects/lib"],
                 busy=True),
    # Short branch and nothing optional: Line 2 usually fits.
    "plain": dict(branch="main", name="", style="default", dirs=[],
                  busy=False),
}


class _Clock(object):
    """Stand-in for the `time` module, frozen at the current frame."""

    now = START

    def time(self):
        return _Clock.now

    def strftime(self, fmt, t=None):
        return real_time.strftime(
            fmt, real_time.gmtime(_Clock.now) if t is None else t)

    def __getattr__(self, name):
        return getattr(real_time, name)


_STATE = {"commit_age": 30_000, "tools": 0,
          "extras": {"stash": 0, "ahead": 0, "behind": 0}}
_RECORD = {"fit": [], "final": None}


def _pin_everything():
    clock = _Clock()
    cli.time = clock
    formatters.time = clock
    cli.get_branch = lambda: "main"
    cli.get_remote_url = lambda: ""
    cli.get_git_state = lambda: ""
    cli.get_last_commit_age_ms = lambda: _STATE["commit_age"]
    cli.get_git_extras = lambda: _STATE["extras"]
    cli.get_clickable_links_enabled = lambda: False
    cli.get_session_tool_count = lambda sid: _STATE["tools"]
    cli.get_today_session_count = lambda: 3
    cli.get_effort_level = lambda: "high"
    cli.get_budget_config = lambda: None
    cli.get_compaction_threshold = lambda: None
    cli.get_disabled_sections = lambda: []
    cli.record_and_get_daily_spend = lambda *a, **k: (0.0, False)

    # Record section NAMES per line (not rendered text, which changes
    # every frame): what the per-line fit kept, and what the spill
    # stage returned when it ran.
    real_fit = cli._fit_to_width
    real_spill = cli._spill_dropped

    def fit(named, sep_width, target, priority):
        kept = real_fit(named, sep_width, target, priority)
        _RECORD["fit"].append(tuple(name for name, _ in kept))
        return kept

    def spill(rows, sep_width, target, priority):
        out = real_spill(rows, sep_width, target, priority)
        _RECORD["final"] = tuple(
            tuple(name for name, _ in row) for row in out)
        return out

    cli._fit_to_width = fit
    cli._spill_dropped = spill


def _session(profile, seed, width):
    """Yield one stdin payload per frame."""
    rng = random.Random(seed)
    cost, tokens_in, tokens_out, used = 0.05, 20_000, 500, 3.0
    added = removed = 0
    _STATE.update(commit_age=30_000, tools=0)
    for frame in range(FRAMES):
        _Clock.now = START + frame * FRAME_SECONDS
        cost += rng.choice((0, 0.01, 0.04, 0.2))
        tokens_in += rng.choice((0, 800, 4000, 15000))
        tokens_out += rng.choice((0, 50, 400))
        used = min(96.0, used + rng.choice((0, 0.1, 0.3)))
        added += rng.choice((0, 0, 3, 40))
        removed += rng.choice((0, 0, 1, 9))
        _STATE["tools"] += rng.choice((0, 1, 2))
        _STATE["commit_age"] += FRAME_SECONDS * 1000
        if rng.random() < 0.02:
            _STATE["commit_age"] = 5_000
        data = {
            "terminal": {"columns": width},
            "version": "2.1.197",
            "session_id": "simulated",
            "git_branch": profile["branch"],
            "workspace": {"project_dir": "/home/user/projects/myapp",
                          "added_dirs": profile["dirs"]},
            "model": {"display_name": "Sonnet 5"},
            "effort": {"level": "high"},
            "output_style": {"name": profile["style"]},
            "session_name": profile["name"],
            "cost": {"total_cost_usd": cost,
                     "total_duration_ms": frame * 30_000 + 5000,
                     "total_api_duration_ms": frame * 11_000 + 1000,
                     "total_lines_added": added,
                     "total_lines_removed": removed},
            "context_window": {
                "used_percentage": used,
                "context_window_size": 1_000_000,
                "current_usage": {
                    "input_tokens": tokens_in,
                    "output_tokens": tokens_out,
                    "cache_read_input_tokens": tokens_in // 2,
                    "cache_creation_input_tokens": 1200}},
            "rate_limits": {
                "five_hour": {"used_percentage": 10 + frame / 12.0,
                              "resets_at": START + 5 * 3600},
                "seven_day": {"used_percentage": 18,
                              "resets_at": START + 5 * 86400}},
        }
        if profile["busy"]:
            if (frame // 40) % 3 == 1:
                data["vim"] = {"mode": "INSERT" if frame % 2 else "NORMAL"}
            if (frame // 55) % 2 == 1:
                data["agent"] = {"name": "Explore"}
            _STATE["extras"] = {"stash": 1 if frame > 200 else 0,
                                "ahead": (frame // 90) % 3, "behind": 0}
        else:
            _STATE["extras"] = {"stash": 0, "ahead": 0, "behind": 0}
        yield data


def _run(profile, seed, width, spill_on):
    """Return (frames whose layout changed, sections shown in total)."""
    cli.get_spill_override = lambda: None if spill_on else False
    changed = shown = 0
    previous = None
    for data in _session(PROFILES[profile], seed, width):
        _RECORD["fit"], _RECORD["final"] = [], None
        cli.render(data, "default")
        layout = _RECORD["final"]
        if layout is None:
            layout = tuple(_RECORD["fit"])
        shown += sum(len(row) for row in layout)
        if previous is not None and layout != previous:
            changed += 1
        previous = layout
    return changed, shown


def main():
    _pin_everything()
    transitions = (FRAMES - 1) * len(SEEDS) * len(WIDTHS)
    renders = FRAMES * len(SEEDS) * len(WIDTHS)
    print("{} sessions x {} widths ({}-{}, step 2) x {} frames: "
          "{} frame-to-frame transitions per row below".format(
              len(SEEDS), len(WIDTHS), WIDTHS[0], WIDTHS[-1], FRAMES,
              transitions))
    print()
    print("{:<8} {:<6} {:>15} {:>20}".format(
        "profile", "spill", "changed frames", "avg sections shown"))
    for profile in PROFILES:
        for spill_on in (False, True):
            changed = shown = 0
            for width in WIDTHS:
                for seed in SEEDS:
                    c, s = _run(profile, seed, width, spill_on)
                    changed += c
                    shown += s
            print("{:<8} {:<6} {:>15,d} {:>20.1f}".format(
                profile, "on" if spill_on else "off", changed,
                shown / float(renders)))


if __name__ == "__main__":
    main()
