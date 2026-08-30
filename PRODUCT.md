# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Marvel fans and canon obsessives asking questions about Marvel screen canon
(movies and series across every timeline — MCU, Sony, Fox, the Defenders
shows, What If...?). They open the site mid-argument or mid-rewatch, want a
fast, trustworthy answer, and want to see the exact subtitle passage it came
from. Secondary audience: the builder (Sankalp) demoing the RAG pipeline.

## Product Purpose

MissMinutes is a grounded RAG search engine over Marvel screen canon: every
answer is synthesized ONLY from ingested subtitle evidence (493 documents,
83,628 chunks), with citations pointing at the exact chunk. Success = the
visitor gets a correct answer with verifiable provenance in seconds, and the
multiverse structure (which timeline a fact belongs to) is visible and
navigable.

## Positioning

Provenance-aware search over a temporal knowledge graph: hybrid retrieval
(Neo4j graph + Qdrant vectors + SQLite FTS5) with a faithfulness-gated
synthesis. A wiki can't cite the exact subtitle line; a chatbot can't prove
where its answer came from. Miss Minutes shows its evidence.

## Operating Context

Single-page web app: cinematic hero (the Sacred Timeline with branch
timelines), one search field with a timeline scope filter, examples, answer
with citations, evidence list. Stack: Gradio 6 mounted on a Starlette app
(`python app.py` → port 7860). Corpus is fully ingested and static at query
time; ingestion is a separate offline pipeline.

## Capabilities and Constraints

- Query path: LLM query plan → hybrid retrieval → grounded synthesis with
  citation markers, faithfulness gate, uncertainty reporting.
- Nine-timeline taxonomy in the planner enum; corpus actually holds documents
  for: mcu, whatif, sony:rami, sony:webb, sony:ssu (which contains the
  Spider-Verse animated films), fox:xmen, defenders. `sony:spiderverse` and
  `fox:ff` have zero documents (UI must not advertise them as searchable).
- GMI (MiniMax-M3) and Neo4j Aura are load-bearing without fallbacks in the
  current code; Qdrant has a local-mode fallback; FTS5 is always available.
  Search must degrade gracefully when any single backend is down.
- All answers must remain evidence-grounded — no outside knowledge, ever.

## Brand Commitments

- Name: MissMinutes (the TVA's cartoon mascot from the Loki series).
- World (user-locked, redesign 2026-08): the REAL Time Variance Authority —
  amber cathode CRT chronoscopes, mid-century bureaucratic office language,
  retro propaganda-poster voice, Miss Minutes' Southern warmth. The former
  blue-void cinematic look is the anti-reference.
- Hero (user-locked): a 2D SVG/CSS chrono-monitor (the in-show way the TVA
  displays the timeline) — no WebGL, no CDN dependencies.
- Architecture (user-locked): keep Gradio; reskin through CSS + JS bridges.
- UI copy uses in-universe terminology: Variant, nexus event, red line,
  pruned, sequence violation, chrono-monitor, "For all time. Always."

## Evidence on Hand

- `data/missminutes.db` — 493 documents / 83,628 chunks (real subtitles).
- `data/processed/qdrant/` — local vector store, 83,628 points.
- Neo4j Aura — 50.6k nodes / 167k relationships.
- `data/canon/inventory.json` — verified canon inventory with IMDB IDs.
- `data/processed/benchmark_report.json` — 9/9 benchmark questions passing.
- Miss Minutes verbatim quotes and TVA visual references gathered in the
  2026-08 redesign research pass (Loki S1E1 training video, Polygon/Farahani
  production-design interview, MCU Fandom wiki).

## Product Principles

1. Every claim cites subtitle evidence — provenance is the product.
2. The multiverse structure is the interface: timeline scope is visual,
   navigable, and truthful (never advertise an empty branch).
3. Degrade gracefully: one dead backend must never kill a search.
4. Complexity belongs at the adapter boundary; orchestration stays pure.
5. The TVA world is commitment, not garnish — amber CRT, paper forms,
   mid-century signage, Miss Minutes' voice everywhere.

## Accessibility & Inclusion

Reduced-motion respected (CRT flicker/scanline animation disabled under
`prefers-reduced-motion`); focus-visible states in amber; text contrast on
paper and CRT surfaces meets WCAG AA.
