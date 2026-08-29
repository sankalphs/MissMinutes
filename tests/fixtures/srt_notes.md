SRT fixture used by ingestion tests — synthetic dialogue resembling
subtitle output (noise tags, HI cues, scene gaps).

## Structure
- Cues 1-4: one continuous scene (Loki / Tesseract dialogue, <4s gaps)
- Cue 5: after a 6s gap -> new scene
- Cue 6: hearing-impaired style [GLASS SHATTERS] noise
- Cue 7: music noise ♪...♪

Chunking: cues within a scene merge until ~1400 chars or sentence end
after ~200 chars; chunk_id format doc_key#sSSSScCCCCC (scene + first cue).
