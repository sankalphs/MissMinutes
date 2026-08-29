"""KG build orchestrator — extract (LLM, cached) then load (Neo4j, batched).

Usage:
  python scripts/build_kg.py --extract --model MiniMaxAI/MiniMax-M3 [--limit N] [--doc-prefix doc:loki]
  python scripts/build_kg.py --load --model MiniMaxAI/MiniMax-M3
  python scripts/build_kg.py --extract --load ...   # both
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings  # noqa: E402
from src.graph.schema import Graph  # noqa: E402
from src.ingestion.store import Store  # noqa: E402
from src.kg.extract import ensure_cache, run_extraction, select_chunks  # noqa: E402
from src.kg.load import load_all  # noqa: E402
from src.kg.resolve import EntityResolver  # noqa: E402
from src.llm.client import GMIClient  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("build_kg")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--extract", action="store_true")
    ap.add_argument("--load", action="store_true")
    ap.add_argument("--model", default=settings.GMI_MODEL)
    ap.add_argument("--limit", type=int, default=None, help="extract only first N chunks")
    ap.add_argument("--doc-prefix", default=None)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    if not (args.extract or args.load):
        ap.error("choose --extract and/or --load")

    store = Store()
    ensure_cache(store.path)

    if args.extract:
        chunks = select_chunks(
            store.path,
            doc_prefix=args.doc_prefix,
            only_missing_for=(args.model,),
        )
        if args.limit:
            chunks = chunks[: args.limit]
        log.info("extracting %d chunks (model=%s, workers=%d)", len(chunks), args.model, args.workers)
        llm = GMIClient(timeout=180.0)
        totals = run_extraction(llm, store.path, chunks, workers=args.workers)
        log.info("extraction done: %s", totals)

    if args.load:
        graph = Graph()
        graph.init_schema()
        graph.seed_timelines()
        # reset canon entity seeds into the resolver each load (idempotent);
        # deferred persistence — bulk flush at the end
        resolver = EntityResolver(defer_persist=True)
        totals = load_all(graph, resolver, store, model=args.model, doc_prefix=args.doc_prefix)
        resolver.flush()
        graph.close()
        log.info("load done: %s", totals)


if __name__ == "__main__":
    main()
