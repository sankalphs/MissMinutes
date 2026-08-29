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
pytest
```

## Phases

- [x] Phase 0 — Foundation, secrets, smoke tests (GMI live; Wyzie deferred 503)
- [ ] Phase 1 — Canon inventory (all timelines, IMDB IDs)
- [ ] Phase 2 — Subtitle ingestion (Wyzie, request ledger)
- [ ] Phase 3 — Storage: Qdrant + Neo4j Aura + embeddings
- [ ] Phase 4 — KG extraction (GMI structured output -> validated graph)
- [ ] Phase 5 — Hybrid search + orchestrator
- [ ] Phase 6 — Grounded synthesis + citations
- [ ] Phase 7 — Gradio UI + HF Space deploy
- [ ] Phase 8 — Evaluation + hardening
