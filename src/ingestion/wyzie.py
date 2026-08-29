"""Wyzie Subs client with a request ledger and daily budget enforcement.

The free key allows 1000 search requests / UTC day. Every request is recorded
in the SQLite ledger so re-runs never double-spend. 503 (service outage) is
retried with backoff and NOT counted against budget (fails before accounting).
"""
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

from src.config import settings

logger = logging.getLogger(__name__)


@dataclass
class SubtitleHit:
    id: str
    url: str
    file_name: str
    source: str
    language: str
    is_hearing_impaired: bool
    ai: bool
    media: str


class WyzieBudgetExceeded(Exception):
    pass


class WyzieClient:
    def __init__(self, db_path: Path | None = None) -> None:
        self.base_url = settings.WYZIE_BASE_URL
        self.key = settings.WYZIE_API_KEY
        self.daily_limit = settings.WYZIE_DAILY_LIMIT
        self.db_path = db_path or settings.DATABASE_PATH
        self._init_ledger()

    # ---------- ledger ----------

    def _init_ledger(self) -> None:
        import sqlite3

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.db_path)
        con.execute(
            """CREATE TABLE IF NOT EXISTS wyzie_ledger (
                ts TEXT NOT NULL,
                utc_day TEXT NOT NULL,
                kind TEXT NOT NULL,
                target TEXT NOT NULL,
                status INTEGER NOT NULL
            )"""
        )
        con.commit()
        con.close()

    def _utc_day(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _log_request(self, kind: str, target: str, status: int) -> None:
        import sqlite3

        con = sqlite3.connect(self.db_path)
        con.execute(
            "INSERT INTO wyzie_ledger (ts, utc_day, kind, target, status) VALUES (?, ?, ?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), self._utc_day(), kind, target, status),
        )
        con.commit()
        con.close()

    def spent_today(self) -> int:
        import sqlite3

        con = sqlite3.connect(self.db_path)
        cur = con.execute(
            "SELECT COUNT(*) FROM wyzie_ledger WHERE utc_day = ? AND status = 200",
            (self._utc_day(),),
        )
        n = cur.fetchone()[0]
        con.close()
        return n

    def already_searched(self, target: str) -> bool:
        import sqlite3

        con = sqlite3.connect(self.db_path)
        cur = con.execute(
            "SELECT 1 FROM wyzie_ledger WHERE kind = 'search' AND target = ? AND status = 200 LIMIT 1",
            (target,),
        )
        found = cur.fetchone() is not None
        con.close()
        return found

    # ---------- search ----------

    def search(
        self,
        imdb_id: str,
        season: int | None = None,
        episode: int | None = None,
        retries: int = 4,
    ) -> list[SubtitleHit]:
        """Search subtitles. target string is the resume key (id[/s/e])."""
        target = imdb_id if season is None else f"{imdb_id}/{season}/{episode}"
        if self.already_searched(target):
            logger.debug("ledger skip: %s", target)
            return []
        if self.spent_today() >= self.daily_limit:
            raise WyzieBudgetExceeded(
                f"daily limit {self.daily_limit} reached ({self.spent_today()} spent)"
            )

        params = {"id": imdb_id, "language": "en", "format": "srt", "key": self.key}
        if season is not None and episode is not None:
            params["season"] = season
            params["episode"] = episode

        for attempt in range(retries + 1):
            resp = httpx.get(f"{self.base_url}/search", params=params, timeout=30)
            if resp.status_code == 200:
                self._log_request("search", target, 200)
                data = resp.json()
                items = data if isinstance(data, list) else [data]
                return [self._hit(i) for i in items if i.get("url")]
            if resp.status_code in (429, 503):
                wait = 5 * (attempt + 1)
                if resp.status_code == 429:
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        wait = int(retry_after) + 1
                logger.info("wyzie %s on %s; sleep %ss", resp.status_code, target, wait)
                time.sleep(wait)
                continue
            # other errors: 4xx means bad request/key — log and give up on target
            self._log_request("search", target, resp.status_code)
            logger.warning("wyzie %s on %s: %s", resp.status_code, target, resp.text[:200])
            return []
        logger.error("wyzie retries exhausted for %s", target)
        return []

    @staticmethod
    def _hit(item: dict) -> SubtitleHit:
        return SubtitleHit(
            id=str(item.get("id", "")),
            url=item["url"],
            file_name=item.get("fileName", ""),
            source=item.get("source", ""),
            language=item.get("language", ""),
            is_hearing_impaired=bool(item.get("isHearingImaired", item.get("isHearingImpaired", False))),
            ai=bool(item.get("ai", False)),
            media=item.get("media", ""),
        )

    @staticmethod
    def pick_best(hits: list[SubtitleHit]) -> SubtitleHit | None:
        """English non-AI, non-HI, srt from the most reliable source."""
        if not hits:
            return None

        def score(h: SubtitleHit) -> tuple:
            return (
                0 if h.ai else 1,               # prefer human subs
                0 if h.is_hearing_impaired else 1,  # prefer non-HI
                1 if h.source == "opensubtitles" else 0,
                len(h.file_name),                # fuller release name = more specific
            )

        return sorted(hits, key=score, reverse=True)[0]

    def download(self, hit: SubtitleHit, dest: Path) -> Path:
        """Download subtitle file (URL is direct, key-less — not budget-metered)."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and dest.stat().st_size > 0:
            return dest
        for attempt in range(3):
            try:
                with httpx.stream("GET", hit.url, timeout=60, follow_redirects=True) as r:
                    r.raise_for_status()
                    with open(dest, "wb") as f:
                        for chunk in r.iter_bytes(8192):
                            f.write(chunk)
                if dest.stat().st_size > 0:
                    return dest
            except httpx.HTTPError as e:
                logger.warning("download retry %s: %s", attempt, e)
                time.sleep(3 * (attempt + 1))
        raise RuntimeError(f"download failed: {hit.url}")
