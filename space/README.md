---
title: MissMinutes
emoji: ⏳
colorFrom: orange
colorTo: purple
sdk: gradio
sdk_version: 6.26.0
app_file: app.py
pinned: false
license: mit
short_description: MCU Sacred Timeline search engine — grounded RAG over a temporal knowledge graph
---

# MissMinutes — Sacred Timeline Search Engine

Ask questions about any Marvel screen canon (MCU, Sony, Fox X-Men, Defenders).
Every answer is grounded in subtitle evidence with citations.

**Architecture**: Wyzie subtitle ingestion → SRT normalize/chunk → SQLite+FTS5
(lexical) + Qdrant (semantic) + Neo4j Aura (temporal KG) → hybrid retrieval →
grounded synthesis (MiniMax-M3) with faithfulness gate.

**Setup secrets** (Space Settings → Variables and secrets):
- `GMI_API_KEY`, `GMI_BASE_URL`, `GMI_MODEL`
- `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`
- `QDRANT_URL`, `QDRANT_API_KEY` — **required for the Space**: the SQLite
  corpus ships in the repo, but the 83,628-point vector store does not
  (local-mode qdrant is single-process and ~360MB). Point at Qdrant Cloud.
- `MM_HOST=0.0.0.0` — the app binds 127.0.0.1 by default (safe local dev);
  Spaces must override.
- `WYZIE_API_KEY`
- `HF_TOKEN`

Deploy: push this folder's contents to the Space git repo.
