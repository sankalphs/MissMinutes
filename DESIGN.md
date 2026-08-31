---
name: MissMinutes
description: The TVA's own intake terminal — an amber-phosphor chronoscope search engine over Marvel screen canon.
colors:
  phos: "#FFB74A"
  phos-hot: "#FFCE85"
  phos-dim: "#C08A2D"
  phos-ghost: "rgba(255, 183, 74, 0.14)"
  warm-white: "#FFF3DC"
  glass: "#0B0A14"
  glass-2: "#14121F"
  glass-hi: "#1A1630"
  paper: "#F0E6D2"
  paper-2: "#E8DCC0"
  ink: "#2A2118"
  ink-soft: "#5A4A38"
  ink-dim: "#6E5F4B"
  hairline: "rgba(42, 33, 24, 0.18)"
  stamp-red: "#A93226"
  pruned-red: "#D05A48"
  redline-red: "#E4604C"
  walnut: "#6B4A2B"
  button-ink: "#231A0E"
typography:
  display:
    fontFamily: "Oswald, 'Franklin Gothic Medium', 'Arial Narrow', sans-serif"
    fontSize: "clamp(46px, 6vw, 72px)"
    fontWeight: 500
    lineHeight: 1.0
    letterSpacing: "0.01em"
  headline:
    fontFamily: "Oswald, 'Franklin Gothic Medium', 'Arial Narrow', sans-serif"
    fontSize: "21px"
    fontWeight: 500
    letterSpacing: "0.05em"
  signage:
    fontFamily: "Oswald, 'Franklin Gothic Medium', 'Arial Narrow', sans-serif"
    fontSize: "13.5px"
    fontWeight: 600
    letterSpacing: "0.12em"
  stamp-type:
    fontFamily: "Oswald, 'Franklin Gothic Medium', 'Arial Narrow', sans-serif"
    fontSize: "12.5px"
    fontWeight: 600
    letterSpacing: "0.26em"
  body:
    fontFamily: "Manrope, system-ui, -apple-system, sans-serif"
    fontSize: "16.5px"
    fontWeight: 400
    lineHeight: 1.75
  label:
    fontFamily: "'IBM Plex Mono', ui-monospace, monospace"
    fontSize: "10.5px"
    fontWeight: 400
    letterSpacing: "0.16em"
  console:
    fontFamily: "'IBM Plex Mono', ui-monospace, monospace"
    fontSize: "16px"
    fontWeight: 400
    letterSpacing: "0.01em"
rounded:
  badge: "3px"
  console: "4px"
  card: "6px"
  scrollbar: "8px"
spacing:
  xs: "6px"
  sm: "12px"
  md: "20px"
  lg: "34px"
  xl: "56px"
  section: "80px"
components:
  button-primary:
    backgroundColor: "{colors.phos}"
    textColor: "{colors.button-ink}"
    typography: "{typography.signage}"
    rounded: "{rounded.console}"
    padding: "11px 20px"
    height: "auto"
  button-primary-hover:
    backgroundColor: "{colors.phos-hot}"
    textColor: "{colors.button-ink}"
  input-console:
    backgroundColor: "rgba(11, 10, 20, 0.9)"
    textColor: "{colors.phos-hot}"
    typography: "{typography.console}"
    rounded: "{rounded.console}"
    padding: "0 152px 0 50px"
    height: "60px"
  dropdown-scope:
    backgroundColor: "rgba(11, 10, 20, 0.9)"
    textColor: "{colors.phos-hot}"
    typography: "{typography.signage}"
    rounded: "{rounded.console}"
    width: "340px"
  stamp:
    textColor: "{colors.stamp-red}"
    typography: "{typography.stamp-type}"
    rounded: "{rounded.console}"
    padding: "4px 12px 3px"
  card-ruling:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.card}"
    padding: "34px 38px 30px"
  evidence-row:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    padding: "20px 6px"
  badge-branch:
    textColor: "{colors.walnut}"
    rounded: "{rounded.badge}"
    padding: "1.5px 7px"
---

# Design System: MissMinutes

Recorded 2026-08-30 from the built, verdict-passed terminal — ground truth
over intention: everything below was verified in the shipped CSS/SVG and
live in the browser. The frontmatter is the machine layer; raw CSS custom
property declarations live in `ui/DESIGN_TOKENS.md` (values identical).
Surfaces: `app.py` + `ui/app.css` + `src/ui/chronoscope.py`.

## Overview

**Creative North Star: "The TVA's own intake terminal"** — a search engine
wearing the Time Variance Authority's amber chronoscope, not a space archive.

The terminal is one machine and one desk. The first viewport is a cathode
chrono-monitor: dark glass, an inline-SVG Sacred Timeline snaking across it
with six live branch lines and two pruned stubs, scanlines, phosphor bloom,
and a walnut glow rolling off the tube's base. Miss Minutes greets the
Variant from the screen (upper-left brand block, warm-white condensed
signage under an amber halo). The console strip attached beneath the tube
carries the TVA's own input line — amber mono text on glass, a `>` prompt
glyph, a FILE REQUEST action key — and pulls up 224px over the tube's bottom
band so monitor and console read as one instrument. While a request is in
flight the phosphor sweep retraces across the glass. Rulings land below on
cream intake paper: a rubber-stamped card whose every claim cites subtitle
evidence, an evidence annex with branch badges and file numbers, and a mono
status line that names the retrieval legs that served the answer.

The system is bilingual by surface. **Glass speaks phosphor and mono** —
anything the machine emits (readouts, file numbers, status, the input line
itself) is amber IBM Plex Mono on near-black glass. **Paper speaks ink and
stamps** — the office voice is Manrope, the institution's signage is
condensed Oswald, and red is spent only where the bureaucracy acts. This is
the committed TVA world (Loki production design: amber cathode
chronoscopes, mid-century office language) with one committed
anti-reference: the former dark-blue cinematic void with generic gold
filament. It ships inside Gradio 6.26, fully neutralized — no framework
chrome survives the reskin — with the chronoscope as pure inline SVG (no
WebGL, no iframe, no CDN).

**Key Characteristics:**
- One CRT, one console strip, one paper stack — three surfaces, one bureaucracy
- Amber phosphor on dark glass; cream intake paper with form ink
- Oswald signage / Manrope office voice / IBM Plex Mono machine speech
- The chronoscope is the interface: click a branch to scope the search
- Every ruling is rubber-stamped and cites its subtitle evidence
- Degradation is honest: the status line names the dead retrieval leg
- Motion is CRT-honest (sweep, retrace, blink) and fully disabled under `prefers-reduced-motion`
- Framework-invisible: injected CSS + one head-injected bridge script carry the whole world

## Colors

Two matched families — emitted light on glass, printed ink on paper — plus
red for the bureaucracy's actions, spent sparingly on both.

### Primary
- **Amber Phosphor** (#FFB74A): the TVA screen accent. Everything the machine emits on glass at full strength — the FILE REQUEST key fill, live branch strokes, fork dots, topbar brand, the blinking status dot, selection-note text, spine sleeve glow.
- **Focused Phosphor** (#FFCE85): the hot sibling for focused and hover states — input-line text, hovered/selected branch strokes, hero-hint text, hovered dropdown items, the button's hover fill.
- **Dimmed Phosphor** (#C08A2D): de-emphasized amber text on glass, tuned to AA — topbar status, readout keys, input placeholder, dropdown arrows, resting dropdown items.
- **Phosphor Ghost Wash** (rgba(255,183,74,0.14)): the only amber used as a *fill* — evidence-row hover on paper and dropdown-item hover on glass.
- **Tube White** (#FFF3DC): warm white, never pure #FFF — the display headline on the glass and the Sacred Timeline's core stroke.

### Secondary
- **Rubber-Stamp Red** (#A93226): the paper-side red — every stamp (RULING ISSUED / PENDING FILE REQUEST / REQUEST REJECTED), the warn flag, and the docket links' hover underline. The `--danger` token aliases it.
- **Redline Red** (#E4604C): the elevated red that lives on glass — the dashed threshold line and its "RED LINE — DO NOT CROSS" caption.
- **Pruned Red** (#D05A48): the muted red for pruned branch stubs and their labels on the dark field.

### Tertiary
- **Walnut Paneling** (#6B4A2B): mid-century office wood — evidence numerals, branch badges and their borders, the scrollbar thumb, and the walnut glow radiating from the tube's base.

### Neutral
- **CRT Glass** (#0B0A14): the monitor's dark field — chrono gradient base, input-line fill (at 0.9 alpha), dropdown container fill.
- **Tube Edge** (#14121F): the glass gradient's roll-off at the tube's foot, the console strip's base, the dropdown options-panel fill.
- **Glass Bloom Center** (#1A1630): the SVG radial gradient's faint center highlight inside the chronoscope.
- **Intake Paper** (#F0E6D2): cream file folder — the ruling card and evidence-row ground; also the lede/greeting text color on glass.
- **Desk Ground** (#E8DCC0): the page beneath the paper — `html`/`body` background, scrollbar track.
- **Form Ink** (#2A2118): primary text and borders on paper — ruling paragraphs, the ruling card's 1.5px border.
- **Secondary Ink** (#5A4A38): evidence quotes, docket links at rest, colophon bolds.
- **Tertiary Ink** (#6E5F4B): smallest paper text, AA at small sizes — labels, FILE meta, status line, sources, colophon.
- **Paper Hairline** (rgba(42,33,24,0.18)): the 1.5px divider grammar between evidence rows and the dashed sources rule.
- **Console Ink** (#231A0E): the dark text *and* border on the amber action key — ink pressed into a phosphor keycap.

### Named Rules
**The Two Surfaces Rule.** Glass glows; paper sits. Amber light (#FFB74A /
#FFCE85 / #FFF3DC) lives on dark glass; ink lives on cream paper. No
paper-styled element ever lands on the tube; no console-glass element ever
lands on the desk.

**The One Redline Rule.** Red on glass exists exactly twice — the threshold
line and the pruned stubs. Red on paper exists only where the bureaucracy
acts: stamps, warnings, violation underlines. Red is never decorative.

**The Phosphor Budget Rule.** Amber is emitted light with a budget. The only
large amber fill is the single action key (FILE REQUEST); everywhere else
amber is stroke, text, or a 0.14 ghost wash.

## Typography

**Signage Font:** Oswald (fallbacks: Franklin Gothic Medium, Arial Narrow) — 400/500/600, the TVA's confirmed condensed signage tradition.
**Body Font:** Manrope (system-ui, -apple-system) — variable 200–800, the office voice.
**Machine Font:** IBM Plex Mono (ui-monospace) — 400/500, everything the machine says.

**Character:** A three-voice bureaucracy — the institution shouts in condensed caps (Oswald), the archivist talks in warm rounded prose (Manrope), and the machine types in mono. Faces load via Google Fonts `@import` inside the injected CSS (gradio 6 drops head links).

### Hierarchy
- **Display** (Oswald 500, clamp(46px–72px), line-height 1.0, tracking 0.01em): "Miss Minutes" on the tube — Tube White with a 26px amber halo text-shadow plus a deep drop. Mobile clamps to 40–56px.
- **Headline** (Oswald 500, 21px, tracking 0.05em, uppercase): section headings on paper — "Evidence from the timeline".
- **Signage / Title** (Oswald 600, 13.5px, tracking 0.12em): action keys; the topbar brand runs wider (0.3em). Stamps: 12.5px / 0.26em. Small labels: 13px / 0.14em. Evidence headings and branch labels on glass: 15px / 0.14em. Selection-note: 11.5px / 0.2em. Docket link heading: 13px / 0.14em uppercase.
- **Body** (Manrope 400, 16.5px, line-height 1.75): the ruling paragraphs. Lede on glass: 15px / 1.55, max 40ch. Greeting: 15.5px / 1.65, max 56ch. Evidence titles: Manrope 700, 15px. Quotes: 14px / 1.65. Docket links: 14.5px. Warn: 13.5px.
- **Machine Label** (IBM Plex Mono 400, 10.5px, tracking 0.16em, uppercase): status line, colophon, sources, topbar status. FILE meta: 10px / 0.12em. Hero hint: 10px / 0.22em. Readouts on glass: keys 11px dim, values 13px at 0.18em.

### Named Rules
**The Machine Speaks Mono Rule.** If the machine says it (readouts, file numbers, chunk ids, status, the input line), it is IBM Plex Mono — usually uppercase with wide tracking (0.12em–0.22em). Humans use Manrope; the institution uses Oswald.

**The Warm-White Rule.** No pure #FFFFFF anywhere. White on glass is Tube White (#FFF3DC); "black" is the glass family (#0B0A14 / #14121F) or Console Ink (#231A0E) on keycaps.

## Layout

A single vertical instrument: full-bleed hero and console strip, then a 760px paper column (`--content-w: 760px`) centered on Desk Ground. The hero and topbar break out of gradio's prose container via `.prose:has(> #chrono)`; all paper content stays constrained to 760px with 24px side padding.

### Zone anatomy (top to bottom)

| Zone | Measurement | Notes |
|---|---|---|
| **CRT topbar** | absolute, full width, padding 20px 34px, z-20 | Brand left: 20px diamond SVG (outlined diamond + solid inner) + "TIME VARIANCE AUTHORITY" in Oswald 600 13.5px / 0.3em, amber with glow. Status right: mono 10.5px / 0.16em "SACRED TIMELINE · STABLE" + 6px blinking amber dot. `pointer-events: none`. A `#skip-link` (visually hidden until focused) is the first focusable element. |
| **The tube** (`#chrono`) | min-height 74vh desktop / 58vh ≤768px, full width | Background: walnut radial glow (at 50% 105%) over glass→glass-2 vertical gradient. `--console-lap: 120px` — the single number both the strip's pull-up and the CRT overlay/sweep bottom inset derive from (the old hardcoded −224px/288px pair covered branch tips and the readouts on every laptop height). Two SVG scenes, one per breakpoint: `#chrono-desktop` (1200×560) and `#chrono-mobile` (390×430 portrait, every branch and label in frame — `slice` used to guillotine 5 of 8 branches off a 390px viewport). `.crt-overlay`/`.sweep` inset `0 0 var(--console-lap) 0`. Bezel ring via `::before`, brand block upper-left, hero hint upper-right. Z-stack: SVG base → overlay (5) → sweep + bezel (6) → brandblock (10) → topbar (20). |
| **Console strip** (`#searchzone`) | full width, `margin-top: -120px` (= `--console-lap`), padding 26px clamp(24px,6vw,96px) 30px, z-8 | Dark glass gradient (rgba(15,13,26,0.98) → glass-2), 1.5px amber 0.25 border-top, upward shadow 0 -18px 60px. Children centered: **machine readouts band** (CHRONO BAY 3 / REDLINE / HUNTERS / ANALYSTS — moved off the SVG floor, which the lap covered on every desktop size), input row (fixed 60px height, max 760px — multi-line queries scroll internally instead of tearing the strip), Miss Minutes greeting (max 56ch), scope dropdown (340px), selection-note + flight-note. |
| **Paper zone** | 760px column on Desk Ground | Docket examples (60px top margin) → `#read` divider (80px top; 1.5px × 44px vertical hairline, centered) → ruling card (padding 34px 38px 30px) → evidence annex (56px top; rows on a 48px-numeral + 1fr grid, 18px column gap, each row an `#ev-nn` anchor target) → pipeline status (14px top) → colophon (100px top, 60px bottom padding). |

### Responsive (≤768px)
- Topbar tightens (16px 20px); the status readout drops; brand runs 12px / 0.2em.
- Tube drops to 58vh; `--console-lap` zeroes and the overlay/sweep insets go to 0.
- **The compact chronoscope takes over** (`#chrono-mobile`, 390×430 portrait): every branch, fork and label in frame and tappable — the full landscape scene under `slice` put 5 of 8 branches off-screen. The desktop scene is `display: none`d.
- The console strip **stacks naturally** (margin-top 0, padding 24px 20px 26px); readouts wrap at 9px.
- Brand block re-anchors from upper-left to the tube's foot (left/right 24px, bottom 76px) and clamps to 40–56px; lede tightens to 13.5px.
- Input line: 56px height, 14px mono, right padding 120px. Button: 12px, padding 10px 14px. Ruling card: padding 26px 24px 24px. Evidence grid: 36px + 1fr, 14px gap.

## Elevation & Depth

Hybrid, split by surface. **On glass, depth is light, not shadow**: phosphor bloom, glow text-shadows, the vignette, and the bezel's inset ring carry the tube. Where shadows do appear on glass they are *black* and mean physical recession into the console. **On paper, exactly one shadow exists** — the ruling card's blurred offset: a photocopied card lifting off the desk.

### Shadow Vocabulary
- **Strip uplift** (`0 -18px 60px rgba(5,4,10,0.7)`): the console strip shadowing the tube above it.
- **Console control** (`0 6px 24px rgba(0,0,0,0.55)`): the input line recessed into the console glass.
- **Options panel** (`inset 0 0 0 200px #14121F, 0 14px 44px rgba(0,0,0,0.65)`): the scope dropdown's open list, floating as dark glass.
- **Action key** (`0 3px 10px rgba(0,0,0,0.5)`): FILE REQUEST's keycap lift.
- **Stamped card** (`4px 6px 24px rgba(42,33,24,0.28)`): the ruling card — ink-tinted, offset down-right, heavily blurred.

### Named Rules
**The One Paper Shadow Rule.** Nothing on the paper stack casts a shadow except the ruling card. Evidence rows, badges, and dividers are flat print; depth on paper is conveyed by borders and hairlines.

## Shapes

Squared, bureaucratic, slightly rounded as if cut by a paper guillotine: 4px on console controls (input, key, dropdown), 6px on the ruling card, 3px on branch badges, 8px on the scrollbar thumb. Borders are the dominant form language — 1.5px on interactive edges (card, input, dropdown, console border-top, evidence dividers), 2px on stamps (the rubber block), 1px on badges and the sources rule (dashed). The chronoscope itself is all stroke geometry: round linecaps, organic quadratic-elbow branches (never straight diagonals), a dashed 10-7 redline, soft Gaussian filters for sleeve/glow. The one deliberate asymmetry: stamps are rotated −2.2deg, as if hand-pressed.

## Components

### Input line — the console's query field
- **Shape:** 4px radius, 60px tall (fixed, `!important` — gradio's auto-grow inline style loses to it), full width of the 760px search row; multi-line queries scroll internally (`overflow-y: auto`, `line-height` normal) instead of growing the box and tearing the strip's geometry.
- **Fill:** near-black glass (rgba(11,10,20,0.9)) with a 1.5px amber 0.35 border; text is Focused Phosphor (#FFCE85) in IBM Plex Mono 16px / 0.01em; placeholder in Dimmed Phosphor.
- **Prompt glyph:** a `>` in mono 16px 500, amber, absolutely positioned at 20px left — the terminal caret.
- **Focus:** border solidifies to full amber + a 3px amber 0.18 ring joins the shadow stack; `outline: none` is absorbed by that ring. Under `:focus-visible` globally, everything gets a 2px amber outline, offset 2.
- **Padding reserves the keycap:** right 152px so the FILE REQUEST button nests inside the line's right end; left 50px clears the `>`.

### Buttons
- **Primary — FILE REQUEST:** amber #FFB74A fill, Console Ink text and 1.5px border (a dark rim on the keycap), Oswald 600 13.5px / 0.12em, 11px 20px padding, 4px radius, absolutely positioned inside the input line's right end (right 8px, vertically centered). Hover: fills Focused Phosphor, lifts 1px. Active: presses down 1px. No secondary/ghost buttons exist.
- **Docket links (examples):** not buttons visually — Manrope 14.5px ink-soft text with an invisible 1.5px underline sweep (12% inset) that fills rubber-stamp red on hover while the text darkens to full ink.

### Dropdown — the scope dial
- **Closed:** same console-glass language as the input: rgba(11,10,20,0.9) fill, 1.5px amber 0.35 border, 4px radius, 340px wide, Oswald 13px / 0.12em Focused-Phosphor text, chevron in Dimmed Phosphor. Hover/focus-within brightens the border to full amber.
- **Open list:** solid Tube Edge (#14121F) panel, same amber border, heavy black drop; items are Oswald 13px in Dimmed Phosphor that fill Phosphor Ghost + Focused Phosphor on hover/active. Pruned timelines are absent from the list entirely — the dropdown never advertises an empty branch.
- **Selection note:** "SCOPE LOCKED — [TIMELINE]" in Oswald 11.5px / 0.2em amber caps beneath the dial.

### Stamps — the ruling's rubber block
- **Style:** Oswald 600 12.5px / 0.26em uppercase in Rubber-Stamp Red, 2px solid red border, 4px radius, 4px 12px 3px padding, rotated −2.2deg, 0.9 opacity.
- **States:** `RULING ISSUED` (success), `PENDING FILE REQUEST` (empty), `REQUEST REJECTED` (pipeline error — paired with an apologetic archivist message).

### Evidence rows — the case-file annex
- **Slots:** exactly the evidence rows the LLM may cite (`EVIDENCE_LIMIT` = 6, shared by synthesis and UI — a 12-seen/6-rendered mismatch once hid the citations the ruling actually used). Rows are `id='ev-nn'` anchor targets for the ruling's `[n]` chips.
- **Grid:** 48px numeral column + 1fr body, 18px gap, 20px 6px padding, 1.5px hairline separators (top of each row; bottom on the last).
- **Numeral:** mono 12px in Walnut (a wooden file marker).
- **Body stack:** title (Manrope 700 15px ink) → branch badge → FILE meta → quote.
- **Branch badge:** Oswald 10px / 0.16em uppercase in Walnut, 1px walnut 0.55 border, 3px radius, 1.5px 7px padding — **the chunk's real `timeline_id` from the store payload** (never guessed from the title: the old heuristic badged Spider-Man: Homecoming as RAMI and Deadpool & Wolverine as FOX X-MEN). Graph rows badge KNOWLEDGE GRAPH.
- **FILE meta:** mono 10px / 0.12em uppercase in Tertiary Ink — the chunk id, the citation address.
- **Quote:** 14px / 1.65 in Secondary Ink — the subtitle passage itself, ellipsized only when actually truncated.
- **Hover:** the whole row washes Phosphor Ghost **and lights the matching branch on the chronoscope above** (the evidence-hover bridge — the spine for MCU rows).

### Status line — pipeline truth
- `#pipeline-status`: mono 10.5px / 0.16em uppercase, centered, Tertiary Ink. One word per retrieval leg, always in GRAPH · VECTOR · LEXICAL order, each in one of three states: plain (this ruling's citations include evidence the leg served), `(NO FILES)` (healthy, nothing this ruling used), or `UNREACHABLE` (backend could not be reached — never conflated with empty). Prefix `FILE PROCESSED`, or `FILE PROCESSED (DEGRADED)` when any leg is down; `NO BACKENDS REACHABLE — THE ARCHIVE IS DARK` when all three die; `NO EVIDENCE ON THIS BRANCH` when nothing was retrievable. Elapsed seconds always trail. In-flight requests show `REVIEWING FILE — THE ARCHIVIST IS CONSULTING THE RECORD…` in `#flight-note` (text, so reduced-motion users still get progress; the sweep is the motion tier of the same signal).

### Warn flag
- Inline-flex, Rubber-Stamp Red 13.5px Manrope, led by a 15px hand-drawn SVG triangle (2px stroke, exclamation mark + dot). Appears inside the ruling card when the synthesizer reports uncertainty.

### Colophon
- Mono 10.5px / 0.14em uppercase Tertiary Ink, centered: the pipeline's named parts (Neo4j Aura · Qdrant · MiniMax-M3) and the standing promise — "every claim cites subtitle evidence."

### Chronoscope — the signature component
Two inline-SVG scenes from one registry: the desktop composition (viewBox 1200×560, `xMidYMid slice`) and a 390×430 portrait (`#chrono-mobile`) for narrow glass where every branch and label fits in frame. `role="group"` with a full label — children stay in the a11y tree because the branches ARE buttons. Structure, back to front:
- **Glass field:** radial gradient (#1A1630 → #14121F → #0B0A14), then a faint violet graticule grid (stroke #3A2E4A at 0.28 opacity, 60px × 40px cells).
- **The Sacred Timeline spine:** one path entering low-right, arcing, receding upper-left (`M 1150 470 …`), drawn twice — a 2.6px Tube White core with a hot 1.1px blur, inside a 9px amber 0.22 sleeve with a 3px soft blur. **The spine is the mcu branch**: a `branch-g` group (`role="button"`, data-key="mcu") carrying both paths plus a 26px-wide hit path — MCU evidence rows light it via the hover bridge, and clicking it scopes to the Sacred Timeline.
- **Eight branches in three tiers:** fork point on the spine, organic quadratic elbow (28% x / 55% y control bend), tip; each drawn as a tier-weighted core (3.2 / 2.4 / 1.7px stroke by tier: primary, secondary, distant) over a 3× sleeve, wrapped in a `branch-g` button group. Fork glow: a radial-gradient circle (14 / 10 / 7px by tier) + a 2.2px Focused Phosphor dot. Six live branches (Fox X-Men, Rami, Webb, Sony Universe, Defenders, What If...?) + two pruned stubs (Fox Fantastic Four, Spider-Verse) in Pruned Red at 0.4 opacity with matching labels. Branch tips stay above y≈310 in the desktop viewBox — below that, laptop-height crops plus the console lap made them unclickable (the TOBEY branch had a 0% hit area at 1280×720 before this).
- **Labels:** Oswald 15px 500 / 0.14em amber (12px on mobile, `text-anchor` per side), base opacity 0 (hidden), stroked 3.5px in near-black glass for legibility (paint-order: stroke), fading to 0.95 on hover / evidence-hover / selected / focus-visible. Fork radius bumps to 3.4 when selected.
- **Hit areas:** every branch path carries an invisible 26px-wide twin path for picking — live ones get `cursor: pointer`, pruned get `not-allowed`. The spine has one too.
- **The redline:** one dashed (10-7) 1.6px Redline-Red line climbing the lower-left with "RED LINE — DO NOT CROSS" in mono 11px / 0.2em — the single threshold.
- **Readouts:** four status pairs (CHRONO BAY 3, REDLINE, HUNTERS, ANALYSTS) in mono caps — **on the console strip's own glass** (`#searchzone`), not the SVG floor: the floor sat behind the strip's lap on every desktop size, drawn and never seen.
- **Chronology is truth:** fork positions follow real chronology along the spine (2000s → 2020s); branch reach follows archive holdings. The registry never shows a timeline the corpus doesn't hold.

### Motion
All motion is CRT-honest — light behaving like light, nothing bouncing:
- **Phosphor sweep (the authored moment):** a 26%-tall horizontal amber gradient band that on load descends into place once (1.6s cubic-bezier(0.16,1,0.3,1), 0.4s delay). While a request is in flight, the same band retraces down the glass forever (3.2s linear, infinite, 0.85 opacity) — the console "thinking."
- **Status blink:** the topbar's 6px amber dot pulses 1→0.35 opacity every 2.4s with an 0.7 glow.
- **Hovers:** branch cores snap to full opacity + Focused Phosphor stroke and labels fade in (0.3s ease); input border and ring shift 0.2s; the key lifts 1px (0.15s); evidence rows wash 0.2s; dropdown items 0.15s. Docket underlines sweep in 0.2s.
- **Reduced motion:** one global kill — `prefers-reduced-motion: reduce` zeroes every animation and transition (`!important`, all elements) and hard-hides `.sweep` entirely.

### Interaction bridges
All behaviors live in one head-injected script (`HERO_JS` via `gr.mount_gradio_app(head=…)`), built on the shipped DOM:
- **Click-to-scope:** clicking a live branch's hit area toggles selection, mirrors it onto every branch's selected class (both scenes), sets `aria-pressed`, writes "SCOPE LOCKED — [LABEL]" into the selection-note (aria-live), and pushes the timeline key into a hidden bridge textbox (`#scope-tb`, native value setter + input event) — gradio's own `.change` handler then maps key → dropdown label. Pruned branches refuse and explain ("PRUNED — NO FILES ON THIS BRANCH"). Branches are real `role="button"` SVG groups — tabbable and Enter/Space-activatable.
- **Scope echo (the reverse bridge):** the dropdown's `.change` handler re-emits the bridge block with the chosen label in `#scope-echo`; a body-level MutationObserver reads it and syncs SVG selection + note. Both paths converge on the echo, so the dropdown can never disagree with the glass (the old one-way bridge left a lit branch reading "SCOPE LOCKED" while the scope was actually All).
- **Evidence-hover highlight:** hovering an evidence row adds `.hover` to the matching chronoscope branch group — including the spine for `mcu` rows (the spine IS the mcu branch group; 31.5% of the corpus previously lit nothing).
- **Citation jumps:** `[n]` markers in the ruling are amber link chips (`#ev-nn` anchors) — click one, the evidence row scrolls into view.
- **Pending mirror (the load-bearing hack):** gradio marks in-flight requests with `.pending` on the button block, but gradio's CSS re-scoping makes body-level classes unreachable — so a MutationObserver on body class attributes toggles `.processing` on `#chrono` (the sweep retrace) and writes the in-flight note. A capture-phase click guard swallows FILE REQUEST clicks while `.pending` is up — impatience clicks no longer stack 40s searches in the queue.

### Accessibility
- **Contrast (verified):** Tertiary Ink on Intake Paper 7.5:1; Secondary Ink on Paper 7.3:1; Form Ink on Glass 15.5:1; Stamp Red on Paper 5.3:1; Dimmed Phosphor on Glass 5.5:1; Focused Phosphor on input-glass 9.9:1; amber on near-black glass 8.9:1. The pruned-reds are the marginal cases (D05A48 on glass 4.6:1, used at 0.55–0.4 opacity for deliberately dimmed labels; E4604C redline caption 4.8:1) — the redline is signage, not body copy, and stays short.
- **Focus:** global `:focus-visible` = 2px solid amber outline, 2px offset; the input line's focus is a full border shift + 3px amber ring; branch groups light their core + label on focus-visible.
- **Reduced motion:** all animation and transition killed; the sweep is removed from the layout; progress feedback is text (`#flight-note`), not animation.
- **Semantics:** the chronoscope SVG is `role="group"` with a full label and its branches are real `role="button"` SVG groups (tabbable, Enter/Space-activatable, `aria-pressed` for selection state) — pruned branches are `tabindex=-1` + `aria-disabled`; the scope dropdown remains the listing alternative. Both console controls carry accessible names (aria-labels re-applied by the bridge when gradio re-renders); `#scope-tb` is `visibility: hidden` + `tabindex=-1` (never a tab trap); hidden gradio footer chrome is removed from the tab order; decorative layers (overlay, sweep, bezel, readouts band) are `aria-hidden`; the warn triangle is aria-hidden with adjacent text. A `#skip-link` lands keyboard users on the request line in one jump.
- **Live regions:** the selection-note, the flight note and the pipeline status are `aria-live="polite"` — a 40-second search announces its own completion; the evidence annex announces new rows.
- **Selection:** text selection is amber (rgba(255,183,74,0.35)) with ink text — the browser surfaces belong to this world too. Scrollbars are themed in both engines: walnut thumb with paper-2 track.

### Gradio integration truths (for future maintainers)
The world ships as CSS + one script injected into Gradio 6.26 (`gradio==6.26.0`). Hard-won facts, all verified live:
- **Gradio re-scopes all injected CSS** — every selector arrives wrapped as `.gradio-container.gradio-container-6-26-0 .contain …`. Body-level class hooks (`body.processing`) are therefore unreachable from injected CSS; state must be mirrored onto an element you own (here: `#chrono.processing`).
- **`js=` never executes** — `gr.Blocks(js=…)` in 6.26 silently does nothing. Ship interactivity via `gr.mount_gradio_app(head=…)` instead.
- **`gr.HTML` `<script>` tags don't execute** — same head= route; the bridge script lives in `HERO_JS`.
- **`visible=False` components don't render at all** in 6.26 — you cannot render-then-hide one for scripting purposes. Render the component and collapse it with CSS instead (`#scope-tb` is height 0 / opacity 0 / pointer-events none).
- **Font loading:** gradio 6 drops head font links — the Google Fonts `@import` lives at the top of the injected CSS.
- **Footer removal:** `footer.wrap.svelte-zxu34v { display: none !important }` (the svelte-scoped selector is the one that lands).
- **Neutralization is a layer:** `.main`, `.gap`, `.block`, `.form`, `.contain`, `.wrap`, `footer` etc. get `background: transparent !important; border: none !important; box-shadow: none !important;` — the page must not reveal its framework. The hero escapes gradio's prose container via `.prose:has(> #chrono) { max-width: none }`.
- **The prompt glyph is a `::before` on the input's wrap** (gradio's own wrapper), so it survives gradio's DOM.
- **The native-value-setter trick** (`Object.getOwnPropertyDescriptor(proto, 'value').set`) is required for programmatic textbox writes that gradio's change handlers actually see.

## Do's and Don'ts

### Do:
- **Do** keep the three-surface split: phosphor-on-glass for the tube and console, ink-on-paper for everything below the strip. When adding a component, ask which surface it lives on and inherit that family only.
- **Do** give every machine utterance (ids, readouts, status, latency) to IBM Plex Mono in uppercase with 0.12em–0.22em tracking.
- **Do** mirror gradio state onto owned elements with a MutationObserver rather than fighting the re-scoped selector wall.
- **Do** keep the timeline registry truthful: never draw or list a branch the corpus doesn't hold; pruned branches stay pruned red, unclickable, and absent from the dropdown.
- **Do** reproduce degradation honesty: any new failure path must land in the status line's mono tier vocabulary.
- **Do** hide the sweep and kill all motion under `prefers-reduced-motion`, and keep 2px amber `:focus-visible` everywhere.
- **Do** use 1.5px borders as the default edge on interactive elements, and reserve 2px red borders for stamps only.

### Don't:
- **Don't** reach for the anti-reference: dark-blue cinematic void, generic gold filament, purple gradients, glows on paper, or any space-archive framing.
- **Don't** put pure white (#FFF) or pure black (#000) in any surface — use Tube White, the glass family, or Console Ink.
- **Don't** use red decoratively; it exists only for stamps, warnings, the redline, and pruned state.
- **Don't** add a second large amber fill; FILE REQUEST is the only keycap.
- **Don't** introduce motion that isn't CRT-honest (no bounce, no spring, no parallax).
- **Don't** trust gradio's `js=`, `gr.HTML` scripts, `visible=False` scripting, or body-level class hooks — verified dead in 6.26; use `head=` and owned-element mirrors.
- **Don't** restyle raw gradio chrome piecemeal without the neutralization layer; new gradio components arrive with their own backgrounds, borders, and shadows that must be zeroed before the world's styles apply.



