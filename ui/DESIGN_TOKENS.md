"""MissMinutes design tokens — the real TVA world (2026-08 redesign).

Subject: the Time Variance Authority's field terminal — an amber cathode
chrono-monitor with its own console input line, over cream intake
paperwork. Audience: Marvel fans asking canon questions. Job: file the
query, receive the stamped ruling, read the cited evidence.

Palette (research-verified: Loki production designer Kasra Farahani via
Polygon; MCU Fandom wiki). Values match ui/app.css exactly:

  Cathode glass (monitor + console strip):
  --glass       #0B0A14   CRT dark glass (chrono-monitor field)
  --glass-2     #14121F   tube edge roll-off / console strip base
  --phos        #FFB74A   amber phosphor — TVA screens, Miss Minutes
  --phos-hot    #FFCE85   focused/hover/input text on glass
  --phos-dim    #C08A2D   de-emphasized amber TEXT on glass (AA)
  --phos-ghost  rgba(255,183,74,0.14)  hover fill on paper

  Office paper (intake forms, rulings, evidence):
  --paper       #F0E6D2   TVA intake paper (cream file folder)
  --paper-2     #E8DCC0   page ground beneath the paper
  --ink         #2A2118   form ink on paper
  --ink-soft    #5A4A38   secondary ink
  --ink-dim     #6E5F4B   tertiary ink (AA at small sizes)
  --stamp       #A93226   rubber-stamp red (status, redline) — AA on paper
  --danger      #A93226   danger role aliases stamp
  --brown       #6B4A2B   walnut paneling / evidence numerals

  On glass, pruned/redline reds sit higher: #D05A48 (pruned labels),
  #E4604C (redline) — AA on the dark field.

Type: signage = Oswald (Franklin Gothic Condensed tradition — the TVA's
confirmed signage face), body = Manrope, mono = IBM Plex Mono (the
console input line, readouts, file numbers, chunk ids).

Signature: the full-viewport chrono-monitor — inline SVG Sacred Timeline
with six live branch lines, two pruned stubs, fork-glow markers, one
dashed redline threshold, scanline overlay, condensed-caps readouts, and
a phosphor sweep that loads once and retraces while a request is in
flight. Click a branch to scope the search. The console strip attached
beneath the tube carries the input line and scope dial; rulings land on
paper below, rubber-stamped.
