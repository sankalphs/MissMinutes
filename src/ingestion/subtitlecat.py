"""Subtitlecat provider — search + English SRT download, no API key.

Wyzie has been hard-down (503, all nodes degraded) for extended periods,
so subtitlecat.com is the primary subtitle source. It's scrape-based:
  /index.php?search=<q>  -> rows of detail links
  /subs/<id>/<name>.html -> language table with -en.srt direct links
Downloads are direct, keyless, and served as application/octet-stream.
All lookups are cached in the source_cache table so re-runs cost nothing.
"""
import logging
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urljoin

import httpx

from src.config import settings

logger = logging.getLogger(__name__)

BASE = "https://www.subtitlecat.com/"
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}


@dataclass
class CatHit:
    detail_url: str
    release_name: str


class SubtitlecatClient:
    """Scrape-based client with disk + SQLite cache and polite retries."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or settings.DATABASE_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_cache()
        self._http = httpx.Client(headers=UA, timeout=30, follow_redirects=True)

    def _init_cache(self) -> None:
        con = sqlite3.connect(self.db_path)
        con.execute(
            """CREATE TABLE IF NOT EXISTS source_cache (
                cache_key TEXT PRIMARY KEY,
                url TEXT,
                status TEXT,
                found_at TEXT
            )"""
        )
        con.commit()
        con.close()

    def _cache_get(self, key: str) -> tuple[str, str] | None:
        con = sqlite3.connect(self.db_path)
        row = con.execute(
            "SELECT url, status FROM source_cache WHERE cache_key = ?", (key,)
        ).fetchone()
        con.close()
        return (row[0], row[1]) if row else None

    def _cache_put(self, key: str, url: str, status: str) -> None:
        con = sqlite3.connect(self.db_path)
        con.execute(
            """INSERT INTO source_cache (cache_key, url, status, found_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(cache_key) DO UPDATE SET
                 url = excluded.url, status = excluded.status, found_at = excluded.found_at""",
            (key, url, status, datetime.now(timezone.utc).isoformat()),
        )
        con.commit()
        con.close()

    def _get(self, url: str, retries: int = 5, **kw) -> httpx.Response:
        for attempt in range(retries):
            try:
                r = self._http.get(url, **kw)
                if r.status_code in (429, 503):
                    time.sleep(5 * (attempt + 1))
                    continue
                return r
            except httpx.HTTPError as e:
                logger.debug("retry %s on %s: %s", attempt, url, e)
                time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"GET failed after {retries} tries: {url}")

    # ---------- search ----------

    def search_detail_pages(self, query: str, limit: int = 40) -> list[CatHit]:
        """Search subtitlecat; return detail-page hits."""
        r = self._get(
            BASE + "index.php",
            params={"search": query, "show": str(max(limit, 20))},
        )
        if r.status_code != 200:
            return []
        hits = []
        seen = set()
        for m in re.finditer(
            r"href=['\"]([^'\"]*subs/[^'\"]*\.html)['\"]", r.text
        ):
            href = m.group(1)
            if href in seen:
                continue
            seen.add(href)
            name = re.sub(r"^subs/\d+/", "", href).removesuffix(".html")
            hits.append(CatHit(detail_url=urljoin(BASE, href), release_name=name))
            if len(hits) >= limit:
                break
        return hits

    def english_srt_url(self, detail_url: str) -> str | None:
        """From a detail page, find the pure-English .srt direct link."""
        r = self._get(detail_url)
        if r.status_code != 200:
            return None
        m = re.search(r"href=['\"]([^'\"]*-en\.srt)['\"]", r.text)
        if not m:
            return None
        return urljoin(BASE, m.group(1))

    def download(self, url: str, dest: Path, min_cues: int = 150) -> Path:
        """Download SRT content to dest (cached on disk). English + length verified."""
        if dest.exists() and dest.stat().st_size > 0:
            return dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        r = self._get(url)
        if r.status_code != 200 or len(r.content) < 2000:
            raise RuntimeError(f"bad srt download: {url} ({r.status_code}, {len(r.content)} bytes)")
        # subtitlecat sometimes serves HTML error pages — guard
        if b"<html" in r.content[:400].lower():
            raise RuntimeError(f"html instead of srt: {url}")
        text = r.content.decode("utf-8", errors="ignore")
        if not _is_mostly_english(text):
            raise RuntimeError(f"non-english srt rejected: {url}")
        n_cues = len(re.findall(r"-->", text))
        if n_cues < min_cues:
            raise RuntimeError(f"truncated srt rejected ({n_cues} cues): {url}")
        dest.write_bytes(r.content)
        return dest

    # ---------- high-level: find english srt for a target ----------

    def find_english_srt(
        self, title: str, year: int | None, season: int | None, episode: int | None
    ) -> tuple[Path, str] | None:
        """Try search queries in priority order; return (local_path, source_name).

        Cached: subsequent calls with the same target return instantly.
        """
        cache_key = self._cache_key(title, year, season, episode)
        tag = cache_key.rsplit("|", 1)[-1]

        cached = self._cache_get(cache_key)
        if cached:
            url, status = cached
            if status == "miss":
                return None
            release = _release_from_url(url)
        else:
            found = self._search_once(title, year, season, episode)
            if found is None:
                return None
            url, release = found

        # deterministic local filename from cache key
        safe = re.sub(r"[^a-z0-9]+", "_", _norm(f"{title}_{tag}")).strip("_")
        dest = settings.RAW_DIR / "subtitlecat" / f"{safe}.srt"
        if not dest.exists() or dest.stat().st_size == 0:
            if not self._srt_is_good(url, min_cues=150):
                # cached URL went stale/broken — drop it and re-search once
                self.invalidate(title, year, season, episode)
                fresh = self._search_once(title, year, season, episode)
                if fresh is None:
                    return None
                url, release = fresh
        try:
            self.download(url, dest, min_cues=150)
        except RuntimeError:
            self.invalidate(title, year, season, episode)
            return None
        return dest, release

    def _search_once(
        self, title: str, year: int | None, season: int | None, episode: int | None
    ) -> tuple[str, str] | None:
        """Uncached search; returns (srt_url, release_name) or None."""
        queries = self._queries(title, year, season, episode)
        for q in queries:
            hits = self.search_detail_pages(q, limit=40)
            ranked = self._rank(hits, title, year, season, episode)
            for best in ranked[:5]:
                detail_url = self.english_srt_url(best.detail_url)
                if detail_url and self._srt_is_good(detail_url, min_cues=150):
                    self._cache_put(self._cache_key(title, year, season, episode), detail_url, "hit")
                    return detail_url, best.release_name
            time.sleep(1.0)
        self._cache_put(self._cache_key(title, year, season, episode), "", "miss")
        return None

    def invalidate(self, title: str, year: int | None, season: int | None, episode: int | None) -> None:
        """Drop the cached pick for a target (e.g. wrong content guard)."""
        con = sqlite3.connect(self.db_path)
        con.execute(
            "DELETE FROM source_cache WHERE cache_key = ?",
            (self._cache_key(title, year, season, episode),),
        )
        con.commit()
        con.close()

    @staticmethod
    def _cache_key(title: str, year: int | None, season: int | None, episode: int | None) -> str:
        if season is not None:
            tag = f"s{season:02d}e{episode:02d}"
        else:
            tag = "movie"
        return f"subcat:{_norm(title)}|{year}|{tag}"

    @staticmethod
    def _queries(title: str, year: int | None, season: int | None, episode: int | None) -> list[str]:
        if season is not None:
            base = title.replace(":", " ").replace("'", "")
            return [
                f"{base} S{season:02d}E{episode:02d}",
                f"{base}.{season}x{episode:02d}",
                f"{base} {season}x{episode}",
            ]
        return [f"{title} {year}", f"{title}.{year}"]

    def _srt_is_good(self, url: str, min_cues: int = 150) -> bool:
        """Content probe: download and sanity-check bytes, language, length.

        The '-en.srt' suffix on subtitlecat is unreliable (serves Chinese
        bilingual dubs, Arabic translations, truncated files); verify before
        accepting. min_cues filters partial uploads (a real episode has 300+,
        a movie 800+; 150 is the floor for shorts like I Am Groot).
        """
        try:
            r = self._get(url)
            if r.status_code != 200 or len(r.content) < 2000:
                return False
            if b"<html" in r.content[:400].lower():
                return False
            text = r.content.decode("utf-8", errors="ignore")
            if not _is_mostly_english(text):
                return False
            n_cues = len(re.findall(r"-->", text))
            return n_cues >= min_cues
        except Exception:
            return False

    def _rank(
        self,
        hits: list[CatHit],
        title: str,
        year: int | None,
        season: int | None,
        episode: int | None,
    ) -> list[CatHit]:
        """Rank hits by release-name match quality, best first.

        Strict: for series the SxxEyy marker must be present AND the title
        must match as a contiguous normalized phrase (stops 'Project Loki'
        style false matches for e.g. 'Loki').
        """
        tnorm = _norm(title)
        tphrase = " ".join(tnorm.split())
        scored: list[tuple[int, CatHit]] = []
        for h in hits:
            rnorm = _norm(h.release_name)
            if season is not None:
                # episode marker must be present in some common form
                ep_hit = (
                    re.search(rf"\bs0?{season:d}\s?e0?{episode:d}\b", rnorm.replace(".", " "))
                    or re.search(rf"\b{season}x0?{episode:d}\b", rnorm)
                )
                if not ep_hit:
                    continue
                # reject hits clearly about a different episode
                other_eps = {
                    (str(int(a)), str(int(b)))
                    for a, b in re.findall(r"\bs(\d+)e(\d+)\b", rnorm)
                }
                if other_eps and (str(season), str(episode)) not in other_eps:
                    continue
            score = 0
            if tphrase and tphrase in rnorm:
                score += 8
            else:
                words = [w for w in tnorm.split() if len(w) > 2]
                if not words or not all(w in rnorm for w in words):
                    continue  # release has nothing to do with the title
                # short titles (e.g. 'Loki') match spam like 'Project.Loki';
                # require the release to START with the title token instead
                if len(words) <= 1:
                    first_tok = rnorm.split()[0] if rnorm.split() else ""
                    if first_tok != tphrase:
                        continue
                score += 3
            if year and re.search(rf"\b{year}\b", h.release_name):
                score += 2
            if season is not None:
                if re.search(rf"\bs0?{season:d}\s?e0?{episode:d}\b", rnorm.replace(".", " ")):
                    score += 4
                if re.search(r"\b(1080|720|2160)p\b", rnorm):
                    score += 1
            # prefer real English releases over translations/machine output
            if re.search(r"\bweb[\s.|-]*(dl|rip)\b", rnorm) or "dsnp" in rnorm or "bluray" in rnorm or "web" in rnorm:
                score += 1
            if "-hi" in rnorm or ".hi." in rnorm:
                score -= 1
            if "www." in rnorm or "http" in rnorm:
                score -= 2  # spam releases
            if score > 0:
                scored.append((score, h))
        scored.sort(key=lambda x: -x[0])
        return [h for _, h in scored]

    def close(self) -> None:
        self._http.close()


def _norm(s: str) -> str:
    """Lowercase, strip punctuation/spaces — for fuzzy name matching."""
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _is_mostly_english(srt_text: str) -> bool:
    """True if the letters in the text are overwhelmingly Latin-script."""
    letters = re.findall(r"\w", srt_text)
    if not letters:
        return False
    latin = sum(1 for ch in letters if ch.isascii() and ch.isalpha())
    non_latin = sum(1 for ch in letters if not ch.isascii())
    # also reject mojibake replacement chars
    junk = srt_text.count("\ufffd")
    return latin >= 20 and non_latin / len(letters) < 0.15 and junk < 10


def _release_from_url(url: str) -> str:
    """Extract the release name from a subtitlecat -en.srt URL."""
    name = url.rsplit("/", 1)[-1].removesuffix("-en.srt").removesuffix(".srt")
    return name
