from pathlib import Path

import pytest

from src.ingestion.normalize import chunk_cues, clean_cue, normalize, parse_srt

FIXTURE = Path(__file__).parent / "fixtures" / "pilot.srt"


@pytest.fixture(scope="module")
def content() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_parse_srt_cue_count(content: str) -> None:
    cues = parse_srt(content)
    assert len(cues) == 8
    assert cues[0].start_s == 5.0
    assert cues[7].text.startswith("Doctor Banner")


def test_clean_cue_strips_tags_and_noise(content: str) -> None:
    assert clean_cue("<i>- The Tesseract belongs to me.</i>") == "- The Tesseract belongs to me."
    assert clean_cue("{Y:i}You were made to be ruled.") == "You were made to be ruled."
    assert clean_cue("#Red# We have the Hulk") == "We have the Hulk"
    assert clean_cue("[GLASS SHATTERS]") == ""
    assert clean_cue("♪ Epic orchestral music plays ♪") == ""


def test_normalize_drops_noise_cues(content: str) -> None:
    cues, chunks = normalize(content, "doc:test")
    texts = [c.text for c in cues]
    assert not any("GLASS" in t for t in texts)
    assert not any("♪" in t for t in texts)
    assert len(cues) == 6  # 8 - 2 noise cues
    assert chunks, "should produce chunks"
    joined = " ".join(ch.text for ch in chunks)
    assert "Tesseract" in joined and "Doctor Banner" in joined


def test_scene_gap_splits_chunks(content: str) -> None:
    cues = [c for c in parse_srt(content)]
    # gap between cue 4 (ends 14.0) and cue 5 (starts 20.0) = 6s > 4s boundary
    scenes = []
    cur = [cues[0]]
    for prev, c in zip(cues, cues[1:]):
        if (c.start_s - prev.end_s) >= 4.0:
            scenes.append(cur)
            cur = []
        cur.append(c)
    scenes.append(cur)
    assert len(scenes) == 2


def test_chunk_ids_stable(content: str) -> None:
    _, chunks1 = normalize(content, "doc:the_avengers_2012")
    _, chunks2 = normalize(content, "doc:the_avengers_2012")
    assert [c.chunk_id for c in chunks1] == [c.chunk_id for c in chunks2]


def test_chunk_id_format(content: str) -> None:
    _, chunks = normalize(content, "doc:x")
    for ch in chunks:
        assert "#s" in ch.chunk_id and ch.chunk_id.startswith("doc:x#s")
