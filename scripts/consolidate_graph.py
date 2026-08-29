"""One-time graph consolidation — merge duplicate nodes created by v1 seeds.

For each Character/Object/Organization/Location node whose name resolves
(via the clean canon resolver) to a DIFFERENT canonical id, re-create its
edges against the canonical node, then delete the duplicate.
Run: python scripts/consolidate_graph.py [--dry-run]
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.graph.schema import Graph  # noqa: E402
from src.kg.resolve import EntityResolver  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("consolidate")


MERGE_QUERY = """
MATCH (dup {id: $dup})-[r]-(other)
WHERE other.id <> $can
RETURN type(r) AS rel,
       startNode(r).id AS src_id,
       endNode(r).id AS dst_id,
       properties(r) AS props
"""


def consolidate(dry_run: bool = False) -> int:
    r = EntityResolver()
    g = Graph()
    merged = 0
    with g.session() as s:
        for label in ("Character", "Object", "Organization", "Location"):
            nodes = s.run(f"MATCH (n:{label}) RETURN n.id AS id, n.name AS name").data()
            for n in nodes:
                cid, name = n["id"], n["name"]
                if not name:
                    continue
                canonical = r.resolve(name, label)
                if canonical == cid:
                    continue
                # canonical node must exist; if not, rename dup instead of merging
                exists = s.run(
                    "MATCH (x {id: $can}) RETURN count(x) AS c", can=canonical
                ).single()["c"]
                if exists == 0:
                    if not dry_run:
                        s.run(
                            "MATCH (n {id: $dup}) SET n.id = $can",
                            dup=cid, can=canonical,
                        )
                    log.info("renamed %s -> %s", cid, canonical)
                    merged += 1
                    continue
                edges = s.run(MERGE_QUERY, dup=cid, can=canonical).data()
                if not dry_run:
                    for e in edges:
                        rel, src_id, dst_id, props = e["rel"], e["src_id"], e["dst_id"], e["props"]
                        # swap the dup endpoint for the canonical id
                        if src_id == cid:
                            src_id = canonical
                        if dst_id == cid:
                            dst_id = canonical
                        s.run(
                            f"""MATCH (a {{id: $src}}), (b {{id: $dst}})
                                MERGE (a)-[x:{rel}]->(b)
                                ON CREATE SET x += $props""",
                            src=src_id, dst=dst_id, props=props,
                        )
                    # delete all dup relationships then the node
                    s.run(
                        "MATCH (dup {id: $dup})-[r]-() DELETE r", dup=cid
                    )
                    s.run("MATCH (dup {id: $dup}) DELETE dup", dup=cid)
                log.info("merged %s (%s, %d edges) -> %s", cid, name, len(edges), canonical)
                merged += 1
    g.close()
    return merged


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    n = consolidate(dry_run=dry)
    print(f"{'would merge' if dry else 'merged'}: {n} nodes")
