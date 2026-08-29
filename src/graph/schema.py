"""Neo4j Aura graph — schema, constraints, timeline seeds, validated writes.

Node labels: Character, Event, Movie, Series, Episode, Location, Object,
Organization, Timeline. Relationship types are an allowlist; all Cypher is
parameterized. LLM output NEVER touches the graph directly (spec:40) —
everything passes through the validators in src/kg/validate.py.
"""
import logging
from typing import Any

from neo4j import GraphDatabase

from src.config import settings

logger = logging.getLogger(__name__)

NODE_LABELS = {
    "Character", "Event", "Movie", "Series", "Episode",
    "Location", "Object", "Organization", "Timeline",
}

REL_TYPES = {
    "PARTICIPATES_IN",   # Character -> Event
    "APPEARS_IN",        # Character -> Movie/Episode
    "MEMBER_OF",         # Character -> Organization
    "USES",              # Character -> Object
    "OCCURS_IN",         # Event -> Timeline
    "DEPICTED_IN",       # Event/Episode/Movie -> Timeline/Document
    "OCCURS_AT",         # Event -> Location
    "BEFORE",            # Event -> Event
    "AFTER",             # Event -> Event
    "DURING",            # Event -> Event
    "CAUSES",            # Event -> Event
    "BRANCHES_FROM",     # Timeline -> Timeline
    "INVOLVES",          # Event -> Object
    "KNOWS",             # Character -> Character
    "ENEMY_OF",          # Character -> Character
    "ALLIED_WITH",       # Character -> Character
    "FAMILY_OF",         # Character -> Character
    "ROMANTIC_WITH",     # Character -> Character
}

TIMELINE_SEED = [
    {"id": "timeline:mcu", "name": "MCU / Sacred Timeline", "parent": None},
    {"id": "timeline:whatif", "name": "What If...? Branches", "parent": "timeline:mcu"},
    {"id": "timeline:sony:rami", "name": "Sony — Rami Spider-Man Trilogy", "parent": None},
    {"id": "timeline:sony:webb", "name": "Sony — Amazing Spider-Man", "parent": None},
    {"id": "timeline:sony:ssu", "name": "Sony — Spider-Man Universe", "parent": None},
    {"id": "timeline:fox:xmen", "name": "Fox — X-Men", "parent": None},
    {"id": "timeline:defenders", "name": "Defenders / Street Level", "parent": "timeline:mcu"},
]


class Graph:
    def __init__(self) -> None:
        self.driver = GraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD),
        )

    def close(self) -> None:
        self.driver.close()

    def session(self):
        return self.driver.session(database=settings.NEO4J_DATABASE)

    # ---------- schema ----------

    def init_schema(self) -> None:
        with self.session() as s:
            for label in NODE_LABELS:
                s.run(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE")
            s.run("CREATE INDEX IF NOT EXISTS FOR (n:Event) ON (n.canonical_date)")
            s.run("CREATE INDEX IF NOT EXISTS FOR (n:Timeline) ON (n.name)")
        logger.info("schema initialized: %d labels, %d rel types", len(NODE_LABELS), len(REL_TYPES))

    def seed_timelines(self) -> None:
        with self.session() as s:
            for t in TIMELINE_SEED:
                s.run(
                    """MERGE (tl:Timeline {id: $id})
                       ON CREATE SET tl.name = $name
                       WITH tl
                       MATCH (p:Timeline {id: $parent}) WHERE p.id IS NOT NULL
                       MERGE (tl)-[:BRANCHES_FROM]->(p)""",
                    **t,
                )
        logger.info("timelines seeded: %d", len(TIMELINE_SEED))

    # ---------- validated entity/event/rel writes (called only by kg loaders) ----------

    def merge_entity(self, entity: dict, props: dict) -> None:
        label = entity["type"]
        assert label in NODE_LABELS, f"bad label {label}"
        with self.session() as s:
            s.run(
                f"""MERGE (n:{label} {{id: $id}})
                    ON CREATE SET n.name = $name, n.created_at = timestamp()
                    SET n += $props""",
                id=entity["id"], name=entity["name"], props=props,
            )

    def merge_rel(self, src_id: str, rel: str, dst_id: str, props: dict) -> None:
        assert rel in REL_TYPES, f"bad rel {rel}"
        with self.session() as s:
            s.run(
                f"""MATCH (a {{id: $src}}), (b {{id: $dst}})
                    MERGE (a)-[r:{rel}]->(b)
                    ON CREATE SET r += $props, r.created_at = timestamp()""",
                src=src_id, dst=dst_id, props=props,
            )

    def count(self, label: str) -> int:
        with self.session() as s:
            return s.run(f"MATCH (n:{label}) RETURN count(n) AS c").single()["c"]

    def health(self) -> dict[str, Any]:
        with self.session() as s:
            r = s.run("RETURN 1 AS ok").single()
            assert r and r["ok"] == 1
        info = self.driver.get_server_info()
        return {"ok": True, "version": info.agent}


if __name__ == "__main__":
    g = Graph()
    print(g.health())
    g.init_schema()
    g.seed_timelines()
    print("timelines:", g.count("Timeline"))
    g.close()
