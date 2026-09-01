"""WyzieClient tests — parse, budget accounting, hit-cache recovery, and
atomic downloads — all with faked HTTP (no wyzie calls)."""
from pathlib import Path

import pytest

import src.ingestion.wyzie as wyzie_mod
from src.ingestion.wyzie import SubtitleHit, WyzieClient


class _Resp:
    def __init__(self, status_code=200, body=None, text="", headers=None):
        self.status_code = status_code
        self._body = body
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._body


def _client(tmp_path: Path) -> WyzieClient:
    c = WyzieClient(db_path=tmp_path / "ledger.db")
    return c


def _hit_dict(i: int = 1) -> dict:
    return {"id": i, "url": f"http://x/{i}.srt", "fileName": f"a{i}.srt",
            "source": "opensubtitles", "language": "en", "ai": False,
            "isHearingImpaired": False, "media": "movie"}


def test_search_parses_hits_and_caches_them(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(wyzie_mod.httpx, "get", lambda *a, **k: _Resp(200, [_hit_dict(1), _hit_dict(2)]))
    client = _client(tmp_path)

    hits = client.search("tt0848228")
    assert [h.url for h in hits] == ["http://x/1.srt", "http://x/2.srt"]
    assert client.spent_today() == 1

    # re-run must return the CACHED hits without a second request — a crash
    # between search and download used to lose the hits for the whole day
    calls = {"n": 0}

    def _counting(*a, **k):
        calls["n"] += 1
        return _Resp(200, [_hit_dict(1)])

    monkeypatch.setattr(wyzie_mod.httpx, "get", _counting)
    again = client.search("tt0848228")
    assert [h.url for h in again] == ["http://x/1.srt", "http://x/2.srt"]
    assert calls["n"] == 0, "re-run re-spent a successful search"
    assert client.spent_today() == 1


def test_search_error_shaped_200_is_rejected(tmp_path, monkeypatch) -> None:
    """A dict body on 200 used to be wrapped as [data] and later KeyError'd."""
    monkeypatch.setattr(wyzie_mod.httpx, "get", lambda *a, **k: _Resp(200, {"error": "boom"}))
    client = _client(tmp_path)
    assert client.search("tt0000000") == []


def test_search_404_gives_up_and_ledgers(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(wyzie_mod.httpx, "get", lambda *a, **k: _Resp(404, text="nope"))
    client = _client(tmp_path)
    assert client.search("tt0000000") == []
    con_rows = client.cached_search("tt0000000")
    assert con_rows is None
    assert client.spent_today() == 0  # failures are not budget


def test_search_429_exhaustion_returns_empty_and_ledgers(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(wyzie_mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(wyzie_mod.httpx, "get", lambda *a, **k: _Resp(429, text="slow down"))
    client = _client(tmp_path)
    assert client.search("tt0000000", retries=1) == []
    # not cached as a hit, and not counted against budget — but ledgered
    assert client.cached_search("tt0000000") is None
    assert client.spent_today() == 0
    import sqlite3
    con = sqlite3.connect(client.db_path)
    statuses = [r[0] for r in con.execute("SELECT status FROM wyzie_ledger").fetchall()]
    con.close()
    assert statuses == [429]


def test_download_atomic_part_file(tmp_path, monkeypatch) -> None:
    """Mid-stream death must leave no truncated file the cache would serve."""
    dest = tmp_path / "sub.srt"

    class _FakeStream:
        def __init__(self, fail: bool):
            self.fail = fail

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def raise_for_status(self):
            pass

        def iter_bytes(self, n):
            yield b"1\n00:00:01,000 --> 00:00:02,000\nhi\n"
            if self.fail:
                raise wyzie_mod.httpx.ReadTimeout("cut mid-stream")

    monkeypatch.setattr(
        wyzie_mod.httpx, "stream",
        lambda method, url, timeout, follow_redirects: _FakeStream(fail=True),
    )
    monkeypatch.setattr(wyzie_mod.time, "sleep", lambda s: None)
    client = _client(tmp_path)
    with pytest.raises(RuntimeError):
        client.download(SubtitleHit(id="1", url="http://x/a.srt", file_name="a.srt",
                                    source="os", language="en", is_hearing_impaired=False,
                                    ai=False, media="m"), dest)
    assert not dest.exists(), "partial download leaked into the cache path"
    assert not list(tmp_path.glob("*.part")), "stale .part file left behind"

    # success path: dest written atomically, .part gone
    monkeypatch.setattr(
        wyzie_mod.httpx, "stream",
        lambda method, url, timeout, follow_redirects: _FakeStream(fail=False),
    )
    out = client.download(SubtitleHit(id="1", url="http://x/a.srt", file_name="a.srt",
                                      source="os", language="en", is_hearing_impaired=False,
                                      ai=False, media="m"), dest)
    assert out == dest and dest.stat().st_size > 0
    assert not list(tmp_path.glob("*.part"))


def test_pick_best_prefers_human_non_hi() -> None:
    ai = SubtitleHit(id="1", url="u1", file_name="ai.srt", source="x", language="en",
                     is_hearing_impaired=False, ai=True, media="m")
    human_hi = SubtitleHit(id="2", url="u2", file_name="hi.srt", source="x", language="en",
                           is_hearing_impaired=True, ai=False, media="m")
    human = SubtitleHit(id="3", url="u3", file_name="good.release.srt", source="opensubtitles",
                        language="en", is_hearing_impaired=False, ai=False, media="m")
    assert WyzieClient.pick_best([ai, human_hi, human]) is human
