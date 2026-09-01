"""SRT parsing, cleaning, and scene-aware chunking.

Pipeline: raw .srt -> cues -> cleaned dialogue lines -> scene chunks.
Chunks preserve exact source boundaries (citations point to chunk_id +
cue range) per spec:6,20.
"""
import re
from dataclasses import dataclass

import srt

MIN_CHUNK_CHARS = 200
MAX_CHUNK_CHARS = 1400
SCENE_GAP_SECONDS = 4.0

NOISE_PATTERNS = [
    re.compile(r"^♪.*♪$"),
    re.compile(r"^#\w+$"),           # font colors
    re.compile(r"^\[[^\]]{0,40}\]$"),  # [SOUND DESCRIPTION]
    re.compile(r"^\([^)]{0,40}\)$"),   # (whispering)
]


@dataclass
class Cue:
    index: int
    start_s: float
    end_s: float
    text: str


@dataclass
class Chunk:
    chunk_id: str
    text: str
    start_s: float
    end_s: float
    cue_start: int
    cue_end: int


def parse_srt(content: str) -> list[Cue]:
    """Parse SRT bytes/str into cues; tolerate encoding issues."""
    if content.startswith("\ufeff"):
        content = content[1:]
    try:
        subs = list(srt.parse(content))
    except srt.SRTParseError as e:
        # last resort: strip blank lines between cues and retry
        cleaned = re.sub(r"\n{3,}", "\n\n", content)
        try:
            subs = list(srt.parse(cleaned))
        except srt.SRTParseError as e2:
            # loud with context, never a bare parse error from deep inside srt
            raise srt.SRTParseError(f"unparseable srt even after blank-line cleanup: {e2}") from e
    cues = []
    for i, s in enumerate(subs, 1):
        text = " ".join(line.strip() for line in s.content.splitlines() if line.strip())
        cues.append(Cue(i, s.start.total_seconds(), s.end.total_seconds(), text))
    return cues


def clean_cue(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)          # <i>, <font ...>
    text = re.sub(r"\{[^}]+\}", "", text)         # {\an8}
    text = re.sub(r"^#\w+#\s*", "", text)          # leading #Red# color tags
    # as a space: cue text fused with a stray timestamp ("run-->away") would
    # otherwise become one nonsense word the embedder can't see through
    text = text.replace("-->", " ")
    lines = [ln.strip() for ln in text.splitlines()]
    kept = [ln for ln in lines if ln and not any(p.match(ln) for p in NOISE_PATTERNS)]
    out = " ".join(kept)
    out = re.sub(r"\s+", " ", out).strip()
    return out


def is_scene_boundary(prev: Cue, cur: Cue) -> bool:
    return (cur.start_s - prev.end_s) >= SCENE_GAP_SECONDS


def chunk_cues(cues: list[Cue], doc_key: str) -> list[Chunk]:
    """Group cues into scene chunks; split oversized scenes on sentence ends."""
    scenes: list[list[Cue]] = []
    cur_scene: list[Cue] = []
    prev: Cue | None = None
    for c in cues:
        if prev is not None and is_scene_boundary(prev, c) and cur_scene:
            scenes.append(cur_scene)
            cur_scene = []
        cur_scene.append(c)
        prev = c
    if cur_scene:
        scenes.append(cur_scene)

    chunks: list[Chunk] = []
    for si, scene in enumerate(scenes):
        buf: list[Cue] = []
        buf_chars = 0
        for c in scene:
            line_len = len(c.text) + 1
            if buf and (buf_chars + line_len > MAX_CHUNK_CHARS or c.text.rstrip().endswith((".", "!", "?")) and buf_chars + line_len > MIN_CHUNK_CHARS):
                chunks.append(_mk(doc_key, si, buf))
                buf, buf_chars = [], 0
            buf.append(c)
            buf_chars += line_len
        if buf:
            chunks.append(_mk(doc_key, si, buf))
    # merge tiny trailing chunks within a scene is skipped: small chunks are fine for citations
    return chunks


def _mk(doc_key: str, scene_i: int, buf: list[Cue]) -> Chunk:
    text = " ".join(c.text for c in buf if c.text)
    return Chunk(
        chunk_id=f"{doc_key}#s{scene_i:04d}c{buf[0].index:05d}",
        text=text.strip(),
        start_s=buf[0].start_s,
        end_s=buf[-1].end_s,
        cue_start=buf[0].index,
        cue_end=buf[-1].index,
    )


def normalize(content: str, doc_key: str) -> tuple[list[Cue], list[Chunk]]:
    cues = [c for c in (Cue(c.index, c.start_s, c.end_s, clean_cue(c.text)) for c in parse_srt(content)) if c.text]
    chunks = chunk_cues(cues, doc_key)
    return cues, chunks
