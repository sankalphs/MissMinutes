# Canon Inventory

`inventory.json` — 92 Marvel-related titles (movies + series) across all
timelines: MCU (`mcu`), What If...? branches (`whatif`), Sony Rami/Webb/SSU
(`sony:rami`, `sony:webb`, `sony:ssu`), Fox X-Men (`fox:xmen`), and
ABC/Netflix street-level (`defenders`). 527 total TV episodes.

Every `imdb_id` is verified against IMDb's suggestion API
(`scripts/build_canon_inventory.py`, re-runnable to re-verify).
Used by the Wyzie Subs fetcher to locate subtitles: movies use `id=imdb_id`,
series use `id=imdb_id&season=S&episode=E`.
