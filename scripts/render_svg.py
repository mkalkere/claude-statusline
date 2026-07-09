"""Generate README theme screenshots (SVG) from --demo output.

Repo tooling only — NOT part of the claude-status package. Pure
stdlib, like everything else in this repo. Regenerate after any
change to themes, sections, or _demo_data():

    python scripts/render_svg.py

Writes one SVG per built-in theme to assets/themes/<name>.svg. The
SVGs are plain text elements (no rasterization), so they stay crisp
at any zoom, diff cleanly in git, and weigh a few KB each.

Why SVG instead of a terminal screenshot PNG: reproducible from code
(no manual capture step to forget), no font/DPI drift between
maintainer machines, and README renders identically on GitHub, light
or dark mode, at any width.
"""

import os
import re
import sys

# Import the LOCAL source tree, not any pip-installed claude-status.
# Running `python scripts/render_svg.py` puts scripts/ (not the repo
# root) at sys.path[0], which would silently import the installed
# package — the exact gotcha documented in docs/RELEASE.md.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

os.environ["FORCE_COLOR"] = "1"   # colors even when stdout is a pipe
os.environ["COLUMNS"] = "165"     # full layout, matches README examples
os.environ["LINES"] = "50"
# User-level overrides would defeat the pinned width/settings and make
# the generated assets machine-dependent: CLAUDE_STATUSLINE_WIDTH
# outranks COLUMNS in the width chain, and the settings-path override
# redirects config reads. Drop both for the duration of generation.
os.environ.pop("CLAUDE_STATUSLINE_WIDTH", None)
os.environ.pop("CLAUDE_STATUSLINE_SETTINGS_PATH", None)

import claude_statusline.cli as cli  # noqa: E402  (path setup above)

THEMES = (
    "default", "minimal", "powerline", "nord",
    "tokyo-night", "gruvbox", "rose-pine", "focus",
)

# 16-color ANSI -> hex. One FIXED dark palette (Tokyo Night hues) for
# every screenshot — it plays the role a terminal's palette plays for
# real ANSI output. Themes choose ANSI codes; this table chooses what
# those codes look like in the README. Chosen for legibility on
# GitHub's light AND dark page backgrounds (the SVG carries its own
# background rect, so page theme doesn't bleed through).
PALETTE = {
    30: "#565f89", 31: "#f7768e", 32: "#9ece6a", 33: "#e0af68",
    34: "#7aa2f7", 35: "#bb9af7", 36: "#7dcfff", 37: "#c0caf5",
    90: "#565f89", 91: "#ff7a93", 92: "#b9f27c", 93: "#ff9e64",
    94: "#7da6ff", 95: "#c0a7f5", 96: "#a4daff", 97: "#e6ecff",
}
DEFAULT_FG = "#c0caf5"
BG = "#16161e"
BORDER = "#2f3549"

FONT = ("ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, "
        "'Liberation Mono', monospace")
FONT_SIZE = 14
CHAR_W = 8.43   # monospace advance at 14px — close enough across fonts
LINE_H = 22
PAD_X = 20
HEADER_H = 40   # traffic-light dots row
PAD_BOTTOM = 16

_SGR = re.compile(r"\x1b\[([0-9;]*)m")
_OSC8 = re.compile(r"\x1b\]8;;[^\x1b]*\x1b\\")


def _xml_escape(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _spans(line):
    """Parse one ANSI line into [(text, fg_hex, bold, dim)] spans."""
    line = _OSC8.sub("", line)
    spans = []
    fg, bold, dim = DEFAULT_FG, False, False
    pos = 0
    for m in _SGR.finditer(line):
        if m.start() > pos:
            spans.append((line[pos:m.start()], fg, bold, dim))
        codes = [int(c) if c else 0 for c in (m.group(1) or "0").split(";")]
        # Extended-color sequences (38;5;N / 38;2;R;G;B and the 48;
        # background forms) carry parameters that collide with basic
        # SGR codes — a naive per-param walk would read the "5" or the
        # RGB components as standalone codes and silently corrupt the
        # colors. colors.py is strictly 16-color today, so simply skip
        # the whole group if one appears (loud-ish: the span keeps the
        # previous color rather than inventing a wrong one).
        if 38 in codes or 48 in codes:
            pos = m.end()
            continue
        for c in codes:
            if c == 0:
                fg, bold, dim = DEFAULT_FG, False, False
            elif c == 1:
                bold = True
            elif c == 2:
                dim = True
            elif c == 39:
                fg = DEFAULT_FG
            elif c in PALETTE:
                fg = PALETTE[c]
            # backgrounds (40s/100s) unused by any theme; ignored
        pos = m.end()
    if pos < len(line):
        spans.append((line[pos:], fg, bold, dim))
    return spans


def render_svg(ansi_text):
    """Convert multi-line ANSI text to an SVG terminal card."""
    lines = ansi_text.split("\n")
    plain_len = max(
        len(_SGR.sub("", _OSC8.sub("", ln))) for ln in lines
    )
    width = int(plain_len * CHAR_W) + 2 * PAD_X
    height = HEADER_H + LINE_H * len(lines) + PAD_BOTTOM

    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        'viewBox="0 0 {w} {h}" font-family="{font}" font-size="{fs}">'.format(
            w=width, h=height, font=FONT, fs=FONT_SIZE),
        '<rect width="{w}" height="{h}" rx="10" fill="{bg}" '
        'stroke="{border}" stroke-width="1"/>'.format(
            w=width, h=height, bg=BG, border=BORDER),
        '<circle cx="24" cy="20" r="6" fill="#ff5f57"/>',
        '<circle cx="44" cy="20" r="6" fill="#febc2e"/>',
        '<circle cx="64" cy="20" r="6" fill="#28c840"/>',
    ]
    y = HEADER_H + LINE_H - 6
    for line in lines:
        tspans = []
        for text, fg, bold, dim in _spans(line):
            if not text:
                continue
            attrs = ['fill="{}"'.format(fg)]
            if bold:
                attrs.append('font-weight="bold"')
            if dim:
                attrs.append('opacity="0.6"')
            tspans.append("<tspan {}>{}</tspan>".format(
                " ".join(attrs), _xml_escape(text)))
        parts.append(
            '<text x="{x}" y="{y}" xml:space="preserve">{spans}</text>'.format(
                x=PAD_X, y=y, spans="".join(tspans)))
        y += LINE_H
    parts.append("</svg>")
    return "\n".join(parts)


def main():
    out_dir = os.path.join(_REPO_ROOT, "assets", "themes")
    os.makedirs(out_dir, exist_ok=True)

    data = cli._demo_data()
    # _demo_data's resets_at is "now + 2h/5d"; fmt_countdown measures
    # against a LATER time.time() call, so "+7200" renders ~1h59m —
    # and could flip to ~2h00m when generation lands within ~1ms of an
    # integer-second boundary. Add a 30s margin so the rendered
    # countdown string is stable for any realistic render latency.
    import time as _time
    data["rate_limits"]["five_hour"]["resets_at"] = int(_time.time()) + 7_230
    data["rate_limits"]["seven_day"]["resets_at"] = int(_time.time()) + 432_030

    # Same live-data mocks as cmd_demo(), plus every other section that
    # reads live machine state (commit age, git extras/state, clock) so
    # regenerating assets is deterministic — a repo that happens to be
    # ahead of remote, mid-rebase, or carrying stashes must not inject
    # its own tokens into the checked-in screenshots.
    orig = {
        "get_session_tool_count": cli.get_session_tool_count,
        "get_today_session_count": cli.get_today_session_count,
        "get_last_commit_age_ms": cli.get_last_commit_age_ms,
        "get_git_extras": cli.get_git_extras,
        "get_git_state": cli.get_git_state,
        # User-config readers MUST be pinned too: render() reads
        # ~/.claude/claude-status-budget.json (through a 30s shared
        # cache), so an unpinned run would silently bake the
        # maintainer's personal daily budget — or residue from a
        # recent test run — into public README assets.
        "get_budget_config": cli.get_budget_config,
        "get_compaction_threshold": cli.get_compaction_threshold,
        "get_disabled_sections": cli.get_disabled_sections,
        "get_clickable_links_enabled": cli.get_clickable_links_enabled,
    }
    cli.get_session_tool_count = lambda sid: 42
    cli.get_today_session_count = lambda: 3
    cli.get_last_commit_age_ms = lambda: 300_000  # "last:5m"
    cli.get_git_extras = lambda: {"stash": 0, "ahead": 0, "behind": 0}
    cli.get_git_state = lambda: ""
    cli.get_budget_config = lambda: None
    cli.get_compaction_threshold = lambda: None
    cli.get_disabled_sections = lambda: []
    cli.get_clickable_links_enabled = lambda: False
    orig_strftime = cli.time.strftime
    cli.time.strftime = (
        lambda fmt, *a: "15:30" if fmt == "%H:%M" else orig_strftime(fmt, *a)
    )
    try:
        for name in THEMES:
            ansi = cli.render(data, name)
            svg = render_svg(ansi)
            path = os.path.join(out_dir, "{}.svg".format(name))
            # Write-then-replace (same atomic pattern as the package's
            # cache writes) so an exception mid-generation can't leave
            # a truncated checked-in asset behind.
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                f.write(svg + "\n")
            os.replace(tmp, path)
            print("wrote {}".format(os.path.relpath(path, _REPO_ROOT)))
    finally:
        for attr, fn in orig.items():
            setattr(cli, attr, fn)
        cli.time.strftime = orig_strftime


if __name__ == "__main__":
    main()
