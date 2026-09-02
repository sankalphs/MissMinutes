# MissMinutes

MCU Sacred Timeline search engine — grounded RAG over a provenance-aware
temporal knowledge graph built from subtitles of all Marvel-related screen
canon (MCU, Sony Spider-verse, Fox X-Men, Netflix Defenders, and branches).

```
LLM = understands and explains
Knowledge Graph (Neo4j Aura) = relationships and chronology
Vector DB (Qdrant Cloud) = semantic retrieval
SQLite FTS5 = lexical retrieval
Source subtitles = evidence
Timeline engine = temporal reasoning
```

## Architecture

```
Wyzie Subs API -> SRT ingest -> clean -> chunk -> SQLite (provenance) + Qdrant (vectors)
                                                            -> Neo4j Aura (temporal KG, GMI-extracted)
User -> Gradio (HF Space: sankalp/MissMinutes) -> FastAPI -> Query Router
     -> Hybrid retrieval (vector + lexical + graph) -> Temporal resolver
     -> Evidence layer -> Reranker -> GMI MiniMax-M3 grounded answer + citations
```

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill secrets
python scripts/smoke_tests.py
pytest                 # hermetic suite (live-API tests skip without .env)
```

Notes:
- Retrieval quality is measured offline by `python -m src.eval.retrieval_eval`
  over a 100-case golden set (`src/eval/fixtures/golden_retrieval.json`) —
  the real hybrid path with a deterministic planner, no LLM in the loop.
  Current config scores primary 0.5145 (0.3154 before the 2026-09 sweep:
  bm25-ranked lexical leg, weighted fusion, cross-encoder rerank, e5-small).
- Local dev binds `127.0.0.1:7860` (`MM_HOST=0.0.0.0` to expose; HF
  Spaces must set it).
- Qdrant local-mode holds a process-wide file lock: the app, the
  benchmark and `index_vectors.py` cannot run against the same store at
  the same time — stop one before starting the other, or point
  `QDRANT_URL` at Qdrant Cloud.
- The benchmark (`python -m src.eval.benchmark`) runs the full live
  pipeline and needs GMI credits; its gates are strict (per-sentence
  faithfulness against cited passages, word-boundary entity matching,
  cited-evidence-only retrieval).

## Phases

- [x] Phase 0 — Foundation, secrets, smoke tests (GMI live; Wyzie deferred 503)
- [x] Phase 1 — Canon inventory (all timelines, IMDB IDs)
- [x] Phase 2 — Subtitle ingestion (Wyzie, request ledger)
- [x] Phase 3 — Storage: Qdrant + Neo4j Aura + embeddings
- [x] Phase 4 — KG extraction (GMI structured output -> validated graph)
- [x] Phase 5 — Hybrid search + orchestrator
- [x] Phase 6 — Grounded synthesis + citations
- [x] Phase 7 — Gradio UI + HF Space deploy
- [ ] Phase 8 — Evaluation + hardening (benchmark gates tightened 2026-09;
      audit fixes across retrieval scope-truth, thread safety, UI state)
