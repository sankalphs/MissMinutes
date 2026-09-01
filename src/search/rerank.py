"""Cross-encoder reranking — the final ordering for retrieved chunks.

The reranker replaces the fused chunk scores for the top-24 pool only
(see hybrid.rerank) — graph rows keep their fixed capped scores, so
grounded subtitle passages can be reordered but never crowded out.

Models load lazily, once per process, behind a lock: the app serves
Gradio threads and a model must never be half-constructed into the
singleton while another thread scores against it.
"""
import math
import os
import threading

# measured on the golden set (exp/rerank): the MiniLM cross-encoder beats
# the 6x-costlier bge-reranker-base on every metric at ~100 ms/query
DEFAULT_RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

_MODEL_NAMES = {
    "bge": "BAAI/bge-reranker-base",
    "msmarco": "cross-encoder/ms-marco-MiniLM-L-6-v2",
}

_lock = threading.Lock()
_models: dict[str, object] = {}


def _get_model(name: str):
    """Lazy per-model singleton: first call loads, later calls reuse."""
    if name in _models:
        return _models[name]
    with _lock:
        if name not in _models:  # double-checked: a racing thread may have won
            import torch
            from sentence_transformers import CrossEncoder

            torch.set_num_threads(min(8, os.cpu_count() or 1))
            _models[name] = CrossEncoder(name)
    return _models[name]


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def cross_encoder_scores(query: str, texts: list[str],
                         model_name: str = DEFAULT_RERANKER_MODEL) -> list[float]:
    """Score each (query, text) pair, 0..1, aligned with `texts`.

    Raw model outputs are mapped to 0..1 — sigmoid applied to all scores
    when any falls outside that range. Unknown model names raise
    ValueError (a misconfigured reranker must not silently score nothing).
    """
    if model_name not in _MODEL_NAMES.values():
        raise ValueError(
            f"reranker model must be one of {sorted(_MODEL_NAMES.values())}, got {model_name!r}"
        )
    if not texts:
        return []
    model = _get_model(model_name)
    raw = model.predict([(query, t) for t in texts], batch_size=16)
    scores = [float(s) for s in raw]
    if any(s < 0.0 or s > 1.0 for s in scores):
        scores = [_sigmoid(s) for s in scores]
    return scores
