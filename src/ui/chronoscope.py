"""The chrono-monitor — inline SVG Sacred Timeline.

The in-show way the TVA watches the timeline: dark glass, one luminous
sacred line snaking across it, branch lines forking at diagonals with
fork-glow markers, a redline threshold, and condensed-caps readouts.
Click a branch -> postMessage('timeline-select') -> the search scopes to
that timeline. Hover a branch -> it brightens toward amber.

Pure SVG (no WebGL, no iframe, no CDN): the hero renders in one paint,
restyles from app.css, and works everywhere.

Two scenes, one registry: the full 1200x560 chronoscope for >=640px
glass, and a compact 600x360 composition (all eight branches and the
spine in frame, labels dropped) for narrow screens — `xMidYMid slice`
guillotined five branches off the mobile viewport.
"""
from __future__ import annotations

# The truthful registry: seven branches hold files; two are pruned (empty).
# Fork position t follows real chronology along the spine (2000s -> 2020s);
# reach follows archive holdings (defenders/mcu deepest).
TIMELINES = [
    {"key": "mcu",             "label": "MCU / SACRED TIMELINE", "branch": "SACRED TIMELINE"},
    {"key": "fox:xmen",        "label": "FOX X-MEN",              "branch": "FOX X-MEN"},
    {"key": "sony:rami",       "label": "TOBEY MAGUIRE'S SPIDER-MAN", "branch": "RAMI SPIDER-MAN"},
    {"key": "sony:webb",       "label": "THE AMAZING SPIDER-MAN", "branch": "WEBB SPIDER-MAN"},
    {"key": "sony:ssu",        "label": "VENOM · MORBIUS · KRAVEN · SPIDER-VERSE", "branch": "SONY UNIVERSE"},
    {"key": "defenders",       "label": "THE DEFENDERS",          "branch": "DEFENDERS"},
    {"key": "whatif",          "label": "WHAT IF...?",            "branch": "WHAT IF...?"},
    {"key": "fox:ff",          "label": "FOX FANTASTIC FOUR",    "branch": "FOX FANTASTIC FOUR", "pruned": True},
    {"key": "sony:spiderverse", "label": "SPIDER-VERSE (ANIMATED)", "branch": "SPIDER-VERSE", "pruned": True},
]

# viewBox: 1200 x 560. The spine enters low-right, arcs, recedes upper-left.
_SPINE = "M 1150 470 C 950 430, 820 360, 660 330 S 380 300, 240 240 S 90 160, 40 110"

# Branch geometry: fork point on the spine, control points, tip, label anchor.
# Tips stay above y≈310 — the console strip laps the tube's bottom band and
# laptop-height crops take everything below that (~0% hit area for the
# lowest branches before this fix).
_BRANCHES = [
    {"key": "fox:xmen",   "label": "FOX X-MEN",          "fork": (958, 418), "tip": (1042, 232), "lbl": (1058, 216), "tier": "secondary"},
    {"key": "sony:rami",  "label": "TOBEY MAGUIRE",      "fork": (872, 398), "tip": (986, 258),  "lbl": (1002, 246), "tier": "distant"},
    {"key": "sony:webb",  "label": "AMAZING SPIDER-MAN", "fork": (760, 352), "tip": (898, 296),  "lbl": (914, 284),  "tier": "distant"},
    {"key": "sony:ssu",   "label": "SONY UNIVERSE",      "fork": (640, 328), "tip": (730, 168),  "lbl": (746, 152),  "tier": "secondary"},
    {"key": "defenders",  "label": "THE DEFENDERS",      "fork": (500, 312), "tip": (430, 92),   "lbl": (446, 76),   "tier": "primary"},
    {"key": "whatif",     "label": "WHAT IF...?",       "fork": (330, 274), "tip": (180, 132),  "lbl": (164, 116),  "tier": "primary"},
    {"key": "fox:ff",     "label": "FOX FANTASTIC FOUR", "fork": (256, 252), "tip": (322, 168), "lbl": (338, 156),  "tier": "distant", "pruned": True},
    {"key": "sony:spiderverse", "label": "SPIDER-VERSE", "fork": (208, 236), "tip": (150, 330),  "lbl": (96, 348),   "tier": "distant", "pruned": True},
]

# Compact composition for <640px glass: portrait 390x430 — the full scene
# is landscape and `slice` guillotined 5 of 8 branches off a 390px viewport.
# Every branch (and its label) is in frame here; forks keep the same
# chronology, newest at the foot of the spine.
_SPINE_SM = "M 200 415 C 255 380, 140 345, 200 298 C 262 254, 138 236, 200 190 C 262 144, 150 112, 205 55"
_BRANCHES_SM = [
    {"key": "fox:xmen",   "label": "FOX X-MEN",          "fork": (222, 388), "tip": (322, 366), "lbl": (322, 350), "anchor": "end",   "tier": "secondary"},
    {"key": "sony:rami",  "label": "TOBEY MAGUIRE",      "fork": (172, 320), "tip": (72, 298),  "lbl": (72, 282),  "anchor": "start", "tier": "distant"},
    {"key": "sony:webb",  "label": "AMAZING SPIDER-MAN", "fork": (222, 270), "tip": (322, 248), "lbl": (322, 232), "anchor": "end",   "tier": "distant"},
    {"key": "sony:ssu",   "label": "SONY UNIVERSE",      "fork": (172, 212), "tip": (72, 190),  "lbl": (72, 174),  "anchor": "start", "tier": "secondary"},
    {"key": "defenders",  "label": "THE DEFENDERS",      "fork": (222, 156), "tip": (322, 134), "lbl": (322, 118), "anchor": "end",   "tier": "primary"},
    {"key": "whatif",     "label": "WHAT IF...?",       "fork": (172, 100), "tip": (72, 78),   "lbl": (72, 62),   "anchor": "start", "tier": "primary"},
    {"key": "fox:ff",     "label": "FOX FANTASTIC FOUR", "fork": (208, 62),  "tip": (302, 44),  "lbl": (302, 28),  "anchor": "end",   "tier": "distant", "pruned": True},
    {"key": "sony:spiderverse", "label": "SPIDER-VERSE", "fork": (192, 46),  "tip": (96, 28),   "lbl": (96, 20),   "anchor": "start", "tier": "distant", "pruned": True},
]

# Machine readouts rendered on the console strip (app.py), not the glass
# floor — the console's lap plus laptop-height crops put the SVG floor
# behind the strip on every desktop size.
_READOUTS = [
    ("CHRONO BAY 3", "BRANCH SCAN ACTIVE"),
    ("REDLINE", "0.0031 DEVIATION"),
    ("HUNTERS", "STANDBY"),
    ("ANALYSTS", "ON DUTY"),
]

_TIER_W = {"primary": 3.2, "secondary": 2.4, "distant": 1.7}


def _branch_path(fork: tuple, tip: tuple) -> str:
    """Fork off the spine with an organic elbow — never a straight diagonal."""
    fx, fy = fork
    tx, ty = tip
    # bend the branch: first leave mostly vertical-ish, then turn to the tip
    mx = fx + (tx - fx) * 0.28
    my = fy + (ty - fy) * 0.55
    return f"M {fx} {fy} Q {mx} {my} {tx} {ty}"


def _defs(svg: list, uid: str) -> None:
    """Per-variant def ids: the desktop and compact SVGs render into the
    SAME document (app.py mounts both), so ids must not collide — url(#…)
    resolves to whichever twin comes first in document order."""
    svg.append('<defs>')
    svg.append(f'<radialGradient id="glass-{uid}" cx="42%" cy="38%" r="85%">'
               '<stop offset="0%" stop-color="#1A1630"/>'
               '<stop offset="45%" stop-color="#14121F"/>'
               '<stop offset="100%" stop-color="#0B0A14"/></radialGradient>')
    svg.append(f'<radialGradient id="forkglow-{uid}">'
               '<stop offset="0%" stop-color="#FFB74A" stop-opacity="0.9"/>'
               '<stop offset="100%" stop-color="#FFB74A" stop-opacity="0"/></radialGradient>')
    svg.append(f'<filter id="linesoft-{uid}" x="-40%" y="-40%" width="180%" height="180%">'
               '<feGaussianBlur stdDeviation="3"/></filter>')
    svg.append(f'<filter id="corehot-{uid}" x="-60%" y="-60%" width="220%" height="220%">'
               '<feGaussianBlur stdDeviation="1.1"/></filter>')
    svg.append('</defs>')


def _grid(svg: list, w: int, h: int) -> None:
    svg.append('<g stroke="#3A2E4A" stroke-width="0.6" opacity="0.28">')
    for x in range(60, w, 60):
        svg.append(f'<line x1="{x}" y1="0" x2="{x}" y2="{h}"/>')
    for y in range(40, h, 40):
        svg.append(f'<line x1="0" y1="{y}" x2="{w}" y2="{y}"/>')
    svg.append('</g>')


def _branch_group(svg: list, key: str, label: str, fork: tuple, tip: tuple,
                  tier: str, pruned: bool, lbl: tuple | None, anchor: str, uid: str) -> None:
    p = _branch_path(fork, tip)
    cls = "branch" + (" pruned" if pruned else "")
    gcls = "branch-g" + (" pruned" if pruned else "")
    w = _TIER_W[tier]
    fx, fy = fork
    if pruned:
        # announced as an inert image, not a focusable button that does nothing
        svg.append(f'<g class="{gcls}" data-key="{key}" '
                   f'data-label="{label}" data-pruned="1" role="img" aria-disabled="true" '
                   f'aria-label="{label} (pruned — no files)">')
    else:
        svg.append(f'<g class="{gcls}" data-key="{key}" '
                   f'data-label="{label}" data-pruned="0" tabindex="0" role="button" '
                   f'aria-label="Scope search to {label}">')
    svg.append(f'<path class="{cls} sleeve" d="{p}" stroke-width="{w * 3}" filter="url(#linesoft-{uid})"/>')
    svg.append(f'<path class="{cls} core" d="{p}" stroke-width="{w}"/>')
    r = {"primary": 14, "secondary": 10, "distant": 7}[tier]
    svg.append(f'<circle class="fork" cx="{fx}" cy="{fy}" r="{r}" fill="url(#forkglow-{uid})"/>')
    svg.append(f'<circle class="fork-dot" cx="{fx}" cy="{fy}" r="2.2"/>')
    if lbl is not None:
        lx, ly = lbl
        svg.append(f'<text class="b-label" x="{lx}" y="{ly}" '
                   f'text-anchor="{anchor}">{label}</text>')
    svg.append(f'<path class="hit" d="{p}" stroke-width="26"/>')
    svg.append('</g>')


def chronoscope_svg(compact: bool = False) -> str:
    """The chrono-monitor SVG, served inline in the Blocks page.

    compact=True renders the portrait composition (390x430) for narrow
    glass — every branch and label in frame. Readouts live on the console
    strip (app.py), not on the SVG floor where the lap covered them.
    """
    if compact:
        w, h, spine, branches, uid = 390, 430, _SPINE_SM, _BRANCHES_SM, "m"
    else:
        w, h, spine, branches, uid = 1200, 560, _SPINE, _BRANCHES, "d"
    svg = [f'<svg class="chronoscope" viewBox="0 0 {w} {h}" '
           f'preserveAspectRatio="xMidYMid slice" '
           f'role="group" aria-label="Chrono-monitor: the Sacred Timeline with branch '
           f'timelines. Branch lines are buttons that scope the search to that '
           f'timeline; the scope dropdown below is the keyboard alternative.">']
    _defs(svg, uid)
    svg.append(f'<rect width="{w}" height="{h}" fill="url(#glass-{uid})"/>')
    _grid(svg, w, h)

    # --- the Sacred Timeline: layered luminous spine + its mcu branch group --
    # The spine is itself the mcu branch: one selectable group carrying both
    # the sacred path and a fat hit path along it, so MCU evidence rows can
    # light it via the evidence-hover bridge (they are 31.5% of the corpus).
    svg.append('<g class="branch-g" data-key="mcu" data-label="MCU / SACRED TIMELINE" '
               'data-pruned="0" tabindex="0" role="button" '
               'aria-label="Scope search to the Sacred Timeline (MCU)">')
    svg.append(f'<path class="spine sleeve" d="{spine}" filter="url(#linesoft-{uid})"/>')
    svg.append(f'<path class="spine core" d="{spine}" filter="url(#corehot-{uid})"/>')
    svg.append(f'<path class="hit spine-hit" d="{spine}" stroke-width="26"/>')
    svg.append('</g>')

    for b in branches:
        _branch_group(
            svg, b["key"], b["label"], b["fork"], b["tip"], b["tier"],
            bool(b.get("pruned")), b.get("lbl"), b.get("anchor", "start"), uid,
        )

    if not compact:
        # --- redline: the point-of-no-return threshold -------------------------
        svg.append('<g class="redline-g" opacity="0.85">'
                   '<line class="redline" x1="180" y1="520" x2="330" y2="60"/>'
                   '<text class="redline-txt" x="196" y="542">RED LINE — DO NOT CROSS</text>'
                   '</g>')

    svg.append('</svg>')
    return "".join(svg)
