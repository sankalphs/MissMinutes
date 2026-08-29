---
title: MissMinutes
emoji: ⏳
colorFrom: orange
colorTo: purple
sdk: gradio
sdk_version: 5.29.0
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
- `QDRANT_URL`, `QDRANT_API_KEY`
- `WYZIE_API_KEY`
- `HF_TOKEN`

Deploy: push this folder's contents to the Space git repo.
