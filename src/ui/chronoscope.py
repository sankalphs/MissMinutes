"""The chrono-monitor — inline SVG Sacred Timeline.

The in-show way the TVA watches the timeline: dark glass, one luminous
sacred line snaking across it, branch lines forking at diagonals with
fork-glow markers, a redline threshold, and condensed-caps readouts.
Click a branch -> postMessage('timeline-select') -> the search scopes to
that timeline. Hover a branch -> it brightens toward amber.

Pure SVG (no WebGL, no iframe, no CDN): the hero renders in one paint,
restyles from app.css, and works everywhere.
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
_BRANCHES = [
    {"key": "fox:xmen",   "label": "FOX X-MEN",          "fork": (958, 418), "tip": (1042, 232), "lbl": (1058, 216), "tier": "secondary"},
    {"key": "sony:rami",  "label": "TOBEY MAGUIRE",      "fork": (872, 398), "tip": (992, 470),  "lbl": (1008, 492), "tier": "distant"},
    {"key": "sony:webb",  "label": "AMAZING SPIDER-MAN", "fork": (760, 352), "tip": (900, 318),  "lbl": (916, 306),  "tier": "distant"},
    {"key": "sony:ssu",   "label": "SONY UNIVERSE",      "fork": (640, 328), "tip": (730, 168),  "lbl": (746, 152),  "tier": "secondary"},
    {"key": "defenders",  "label": "THE DEFENDERS",      "fork": (500, 312), "tip": (430, 92),   "lbl": (446, 76),   "tier": "primary"},
    {"key": "whatif",     "label": "WHAT IF...?",       "fork": (330, 274), "tip": (180, 132),  "lbl": (164, 116),  "tier": "primary"},
    {"key": "fox:ff",     "label": "FOX FANTASTIC FOUR", "fork": (256, 252), "tip": (322, 168), "lbl": (338, 156),  "tier": "distant", "pruned": True},
    {"key": "sony:spiderverse", "label": "SPIDER-VERSE", "fork": (208, 236), "tip": (150, 330),  "lbl": (96, 348),   "tier": "distant", "pruned": True},
]

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


def chronoscope_svg() -> str:
    """The full chrono-monitor SVG, served inline in the Blocks page."""
    svg = [f'<svg id="chronoscope" viewBox="0 0 1200 560" '
           f'role="img" aria-label="The Sacred Timeline with branch timelines" '
           f'preserveAspectRatio="xMidYMid slice">']

    # --- deep glass: the CRT's dark field ---------------------------------
    svg.append('<defs>')
    svg.append('<radialGradient id="glass" cx="42%" cy="38%" r="85%">'
               '<stop offset="0%" stop-color="#1A1630"/>'
               '<stop offset="45%" stop-color="#14121F"/>'
               '<stop offset="100%" stop-color="#0B0A14"/></radialGradient>')
    svg.append('<radialGradient id="forkglow">'
               '<stop offset="0%" stop-color="#FFB74A" stop-opacity="0.9"/>'
               '<stop offset="100%" stop-color="#FFB74A" stop-opacity="0"/></radialGradient>')
    svg.append('<filter id="linesoft" x="-40%" y="-40%" width="180%" height="180%">'
               '<feGaussianBlur stdDeviation="3"/></filter>')
    svg.append('<filter id="corehot" x="-60%" y="-60%" width="220%" height="220%">'
               '<feGaussianBlur stdDeviation="1.1"/></filter>')
    svg.append('</defs>')

    svg.append('<rect width="1200" height="560" fill="url(#glass)"/>')

    # faint grid: the monitor's reference graticule
    svg.append('<g stroke="#3A2E4A" stroke-width="0.6" opacity="0.28">')
    for x in range(60, 1200, 60):
        svg.append(f'<line x1="{x}" y1="0" x2="{x}" y2="560"/>')
    for y in range(40, 560, 40):
        svg.append(f'<line x1="0" y1="{y}" x2="1200" y2="{y}"/>')
    svg.append('</g>')

    # --- the Sacred Timeline: layered luminous spine ----------------------
    svg.append(f'<path class="spine sleeve" d="{_SPINE}" filter="url(#linesoft)"/>')
    svg.append(f'<path class="spine core" d="{_SPINE}" filter="url(#corehot)"/>')

    # --- branches ---------------------------------------------------------
    for b in _BRANCHES:
        p = _branch_path(b["fork"], b["tip"])
        cls = "branch" + (" pruned" if b.get("pruned") else "")
        gcls = "branch-g" + (" pruned" if b.get("pruned") else "")
        w = _TIER_W[b["tier"]]
        fx, fy = b["fork"]
        lx, ly = b["lbl"]
        svg.append(f'<g class="{gcls}" data-key="{b["key"]}" '
                   f'data-label="{b["label"]}" data-pruned="{1 if b.get("pruned") else 0}">')
        svg.append(f'<path class="{cls} sleeve" d="{p}" stroke-width="{w * 3}" filter="url(#linesoft)"/>')
        svg.append(f'<path class="{cls} core" d="{p}" stroke-width="{w}"/>')
        # fork glow
        r = {"primary": 14, "secondary": 10, "distant": 7}[b["tier"]]
        svg.append(f'<circle class="fork" cx="{fx}" cy="{fy}" r="{r}" fill="url(#forkglow)"/>')
        svg.append(f'<circle class="fork-dot" cx="{fx}" cy="{fy}" r="2.2"/>')
        # label
        svg.append(f'<text class="b-label" x="{lx}" y="{ly}">{b["label"]}</text>')
        # invisible fat hit area for picking
        svg.append(f'<path class="hit" d="{p}" stroke-width="26"/>')
        svg.append('</g>')

    # --- redline: the point-of-no-return threshold -------------------------
    svg.append('<g class="redline-g" opacity="0.85">'
               '<line class="redline" x1="180" y1="520" x2="330" y2="60"/>'
               '<text class="redline-txt" x="196" y="542">RED LINE — DO NOT CROSS</text>'
               '</g>')

    # --- readouts ----------------------------------------------------------
    svg.append('<g class="readouts">')
    for i, (k, v) in enumerate(_READOUTS):
        x = 48 + i * 288
        svg.append(f'<text class="ro-k" x="{x}" y="530">{k}</text>')
        svg.append(f'<text class="ro-v" x="{x}" y="546">{v}</text>')
    svg.append('</g>')

    svg.append('</svg>')
    return "".join(svg)
