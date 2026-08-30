"""Process-long shared pipeline clients.

Per-request construction churned four connections per search and collided
on Qdrant's local-mode file lock under the gradio queue's concurrency.
Orchestration stays pure — callers take what they need from here.
"""
from __future__ import annotations

import threading

from src.graph.schema import Graph
from src.ingestion.store import Store
from src.llm.client import GMIClient
from src.vector.qdrant import VectorStore

_lock = threading.Lock()
_store: Store | None = None
_vector: VectorStore | None = None
_graph: Graph | None = None
_llm: GMIClient | None = None


def get_store() -> Store:
    global _store
    with _lock:
        if _store is None:
            _store = Store()
    return _store


def get_vector() -> VectorStore:
    global _vector
    with _lock:
        if _vector is None:
            _vector = VectorStore()
    return _vector


def get_graph() -> Graph:
    global _graph
    with _lock:
        if _graph is None:
            _graph = Graph()
    return _graph


def get_llm() -> GMIClient:
    global _llm
    with _lock:
        if _llm is None:
            _llm = GMIClient()
    return _llm
