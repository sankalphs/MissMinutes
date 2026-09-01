import math
import os

import pytest

from src.search.rerank import DEFAULT_RERANKER_MODEL, cross_encoder_scores


def test_unknown_model_raises() -> None:
    with pytest.raises(ValueError, match="reranker model"):
        cross_encoder_scores("Loki", ["loki text"], model_name="bogus")


def test_empty_texts_returns_empty() -> None:
    assert cross_encoder_scores("Loki", []) == []


def test_sigmoid_is_stable_at_extremes() -> None:
    from src.search.rerank import _sigmoid

    assert math.isclose(_sigmoid(0.0), 0.5)
    assert math.isclose(_sigmoid(1000.0), 1.0)
    assert math.isclose(_sigmoid(-1000.0), 0.0)


@pytest.mark.skipif(
    not os.getenv("MM_RERANK_SMOKE"),
    reason="downloads model weights; run explicitly with MM_RERANK_SMOKE=1",
)
def test_real_model_smoke() -> None:
    scores = cross_encoder_scores(
        "Who is Loki?",
        ["Loki is the god of mischief in Asgard.", "The Tesseract glows blue."],
        model_name=DEFAULT_RERANKER_MODEL,
    )
    assert len(scores) == 2
    assert all(math.isfinite(s) and 0.0 <= s <= 1.0 for s in scores)
    assert scores[0] > scores[1], "relevant passage must outrank an unrelated one"
