"""Entity resolution v2 — canon-seeded, alias-aware, O(1) lookups.

The v1 resolver full-scanned the entities table per lookup and had no canon
knowledge, so "Tony Stark" and "Stark" and "Mr. Stark" became separate nodes
and the graph fragmented. v2:
- seeds known canon entities (characters, objects, orgs, locations) with
  aliases so common variants collapse onto one canonical id up front
- holds alias->id and name->id dicts in memory; SQLite is just persistence
- embedding similarity only as a tie-breaker for unseen names (deferred:
  flagged in `unresolved`, never auto-merged)
"""
import json
import re
import sqlite3
from pathlib import Path

from src.config import settings

STOPWORDS = {"the", "a", "an", "of"}

# Canon seeds: canonical_name -> type, aliases. Deliberately compact — covers
# the entities that appear across nearly every ingested title.
CANON_SEEDS: dict[str, tuple[str, list[str]]] = {
    # ---- avengers core (canonical hero name first, civilian identities as aliases)
    "Iron Man": ("Character", ["Tony Stark", "Anthony Stark", "Mr. Stark"]),
    "Captain America": ("Character", ["Steve Rogers", "Steven Rogers", "Cap", "Rogers"]),
    "Thor": ("Character", ["God of Thunder"]),
    "Hulk": ("Character", ["Bruce Banner", "Banner", "Smart Hulk", "David Banner"]),
    "Black Widow": ("Character", ["Natasha Romanoff", "Natasha", "Romanoff", "Yelena Belova"]),
    "Hawkeye": ("Character", ["Clint Barton", "Clinton Barton", "Barton", "Kate Bishop", "Ronin"]),
    "War Machine": ("Character", ["Rhodey", "James Rhodes", "Rhodes"]),
    "Falcon": ("Character", ["Sam Wilson", "Samuel Wilson", "Wilson", "John Walker", "US Agent"]),
    "Winter Soldier": ("Character", ["Bucky", "Bucky Barnes", "James Barnes", "Buchanan Barnes"]),
    "Scarlet Witch": ("Character", ["Wanda Maximoff", "Wanda", "Wanda's Spell"]),
    "Quicksilver": ("Character", ["Pietro Maximoff", "Pietro"]),
    "Vision": ("Character", []),
    "Spider-Man": ("Character", ["Peter Parker", "Spidey", "Miles Morales", "Kid Arachnid"]),
    "Doctor Strange": ("Character", ["Stephen Strange", "Strange", "Sorcerer Supreme", "Strange Supreme"]),
    "Ant-Man": ("Character", ["Scott Lang", "Scott"]),
    "Wasp": ("Character", ["Hope van Dyne", "Hope Pym", "Hope", "Janet van Dyne", "Janet Pym"]),
    "Captain Marvel": ("Character", ["Carol Danvers", "Carol", "Mar-Vell", "Wendy Lawson"]),
    "Rescue": ("Character", ["Pepper Potts", "Pepper"]),
    "Nick Fury": ("Character", ["Fury"]),
    "Maria Hill": ("Character", ["Hill"]),
    "Phil Coulson": ("Character", ["Coulson", "Agent Coulson"]),
    "Black Panther": ("Character", ["T'Challa", "King T'Challa", "TChalla"]),
    "Shang-Chi": ("Character", ["Shaun"]),
    "Ms. Marvel": ("Character", ["Kamala Khan", "Kamala"]),
    "Moon Knight": ("Character", ["Marc Spector", "Steven Grant", "Jake Lockley"]),
    "She-Hulk": ("Character", ["Jennifer Walters", "Jen Walters"]),
    "Ironheart": ("Character", ["Riri Williams"]),
    "Wonder Man": ("Character", ["Simon Williams"]),
    "Shuri": ("Character", []),
    "Okoye": ("Character", []),
    "Nakia": ("Character", []),
    "M'Baku": ("Character", ["Man-Ape"]),
    "Wong": ("Character", []),
    "Ancient One": ("Character", []),
    "Mordo": ("Character", ["Karl Mordo", "Baron Mordo"]),
    "America Chavez": ("Character", ["America"]),
    "Captain Carter": ("Character", ["Peggy Carter", "Agent Carter", "Margaret Carter"]),
    "Watcher": ("Character", ["Uatu"]),
    "Kahhori": ("Character", []),

    # ---- guardians / cosmic
    "Star-Lord": ("Character", ["Peter Quill", "Quill", "Peter 2", "Peter Two", "Rami Peter"]),
    "Gamora": ("Character", []),
    "Drax": ("Character", ["Drax the Destroyer"]),
    "Groot": ("Character", []),
    "Rocket": ("Character", ["Rocket Raccoon", "89P13", "trash panda"]),
    "Mantis": ("Character", []),
    "Nebula": ("Character", []),
    "Yondu": ("Character", ["Yondu Udonta"]),
    "Korg": ("Character", []),
    "Valkyrie": ("Character", ["Brunnhilde"]),
    "Adam Warlock": ("Character", []),
    "Ayesha": ("Character", []),
    "Ego": ("Character", ["Celestial", "Ego the Living Planet"]),
    "High Evolutionary": ("Character", ["Orgocorps"]),
    "Goose": ("Character", ["Chewie", "Flerken", "cat"]),

    # ---- villains
    "Thanos": ("Character", ["Mad Titan"]),
    "Ultron": ("Character", ["Infinity Ultron", "Ultron Prime"]),
    "Red Skull": ("Character", ["Johann Schmidt"]),
    "He Who Remains": ("Character", ["Kang", "Kang the Conqueror", "Nathaniel Richards", "Victor Timely", "Iron Lad"]),
    "Sylvie": ("Character", ["Loki Variant", "Variant Loki"]),
    "Dormammu": ("Character", []),
    "Aldrich Killian": ("Character", ["Mandarin"]),
    "Vulture": ("Character", ["Adrian Toomes"]),
    "Mysterio": ("Character", ["Quentin Beck", "Mysterio's Drones", "Quentin Beck's Illusions"]),
    "Hela": ("Character", []),
    "Grandmaster": ("Character", ["En Dwi Gast"]),
    "Killmonger": ("Character", ["Erik Killmonger", "N'Jadaka", "NJobu"]),
    "Ulysses Klaue": ("Character", ["Klaw", "Klaue"]),
    "Ebony Maw": ("Character", ["Maw"]),
    "Cull Obsidian": ("Character", []),
    "Corvus Glaive": ("Character", ["Glaive"]),
    "Proxima Midnight": ("Character", ["Proxima"]),
    "Kaecilius": ("Character", []),
    "Kilmonger": ("Character", []),
    "Kang the Conqueror": ("Character", []),
    "Batroc": ("Character", ["Georges Batroc", "Batroc the Leaper"]),
    "Flag Smashers": ("Organization", ["Flag Smasher", "Karli Morgenthau", "Karli"]),
    "Power Broker": ("Character", []),
    "Helmut Zemo": ("Character", ["Baron Zemo", "Zemo"]),
    "Brock Rumlow": ("Character", ["Crossbones"]),
    "Emil Blonsky": ("Character", ["Abomination"]),
    "Kree Sentry": ("Object", []),

    # ---- sony spider-verse
    "Venom": ("Character", ["Eddie Brock"]),
    "Carnage": ("Character", ["Cletus Kasady"]),
    "Morbius": ("Character", ["Michael Morbius"]),
    "Kraven": ("Character", ["Sergei Kravinoff", "Kraven the Hunter"]),
    "Madame Web": ("Character", ["Cassandra Webb", "Cassie Webb"]),
    "Green Goblin": ("Character", ["Norman Osborn", "Goblin"]),
    "Doctor Octopus": ("Character", ["Doc Ock", "Otto Octavius"]),
    "Electro": ("Character", ["Max Dillon"]),
    "Sandman": ("Character", ["Flint Marko"]),
    "Lizard": ("Character", ["Curt Connors"]),
    "Harry Osborn": ("Character", []),
    "Mary Jane": ("Character", ["MJ", "Mary Jane Watson", "Michelle Jones", "Michelle Jones-Watson"]),
    "Aunt May": ("Character", ["May Parker"]),
    "Uncle Ben": ("Character", ["Ben Parker"]),
    "Gwen Stacy": ("Character", ["Spider-Gwen", "Spider-Woman", "Gwen"]),
    "Spider-Man 2 Peter": ("Character", ["Peter 2", "Peter Two"]),
    "Spider-Man 3 Peter": ("Character", ["Peter 3", "Peter Three"]),

    # ---- fox x-men
    "Wolverine": ("Character", ["Logan", "James Howlett", "Weapon X"]),
    "Professor X": ("Character", ["Charles Xavier", "Professor Xavier"]),
    "Magneto": ("Character", ["Erik Lehnsherr", "Max Eisenhardt"]),
    "Mystique": ("Character", ["Raven Darkholme", "Raven"]),
    "Storm": ("Character", ["Ororo Munroe"]),
    "Jean Grey": ("Character", ["Phoenix", "Dark Phoenix", "Marvel Girl"]),
    "Cyclops": ("Character", ["Scott Summers"]),
    "Beast": ("Character", ["Hank McCoy"]),
    "Nightcrawler": ("Character", ["Kurt Wagner"]),
    "Rogue": ("Character", ["Anna Marie"]),
    "Iceman": ("Character", ["Bobby Drake"]),
    "Deadpool": ("Character", ["Wade Wilson", "Wade", "Merc with a Mouth"]),
    "Colossus": ("Character", ["Piotr Rasputin"]),
    "Sabretooth": ("Character", ["Victor Creed"]),
    "William Stryker": ("Character", ["Stryker"]),
    "Apocalypse": ("Character", ["En Sabah Nur"]),
    "Cable": ("Character", ["Nathan Summers"]),
    "Domino": ("Character", ["Neena Thurman"]),
    "X-23": ("Character", ["Laura", "Laura Kinney"]),

    # ---- defenders / street level
    "Daredevil": ("Character", ["Matt Murdock", "Matthew Murdock", "The Devil of Hell's Kitchen"]),
    "Jessica Jones": ("Character", ["JJ"]),
    "Luke Cage": ("Character", ["Power Man", "Carl Lucas"]),
    "Iron Fist": ("Character", ["Danny Rand", "Daniel Rand"]),
    "Punisher": ("Character", ["Frank Castle"]),
    "Kingpin": ("Character", ["Wilson Fisk", "Fisk"]),
    "Elektra": ("Character", ["Elektra Natchios"]),
    "Bullseye": ("Character", ["Benjamin Poindexter", "Dex"]),
    "Purple Man": ("Character", ["Kilgrave", "Kevin Thompson"]),
    "Misty Knight": ("Character", []),
    "Colleen Wing": ("Character", []),
    "Claire Temple": ("Character", []),
    "Skye": ("Character", ["Daisy Johnson", "Quake", "Daisy"]),
    "Jemma Simmons": ("Character", ["Simmons"]),
    "Leo Fitz": ("Character", ["Fitz"]),
    "Grant Ward": ("Character", ["Ward"]),
    "Melinda May": ("Character", ["May", "The Cavalry"]),
    "Fitz-Simmons": ("Character", []),
    "Karen Page": ("Character", []),
    "Foggy Nelson": ("Character", ["Foggy"]),
    "Trish Walker": ("Character", ["Patsy", "Hellcat"]),
    "Malcolm Ducasse": ("Character", []),
    "Jeri Hogarth": ("Character", []),
    "Will Simpson": ("Character", ["Nuke"]),
    "Rafael Reyes": ("Character", []),

    # ---- loki / tva
    "Loki": ("Character", ["Loki Laufeyson", "God of Mischief"]),
    "Mobius": ("Character", ["Mobius M. Mobius", "Agent Mobius"]),
    "Ravonna Renslayer": ("Character", ["Renslayer"]),
    "Hunter B-15": ("Character", ["B-15"]),
    "Miss Minutes": ("Character", []),
    "O.B.": ("Character", ["Ouroboros"]),
    "TVA": ("Organization", ["Time Variance Authority", "Time-Keepers", "Time Keepers"]),
    "Minutemen": ("Organization", ["Minuteman"]),
    "Time Keepers": ("Organization", ["Time-Keepers"]),

    # ---- objects / mcguffins
    "Tesseract": ("Object", ["Cosmic Cube", "Space Stone"]),
    "Scepter": ("Object", ["Chitauri Scepter", "Loki's Scepter", "Mind Stone"]),
    "Infinity Stones": ("Object", ["Infinity Stone", "Soul Stone", "Power Stone", "Time Stone"]),
    "Mjolnir": ("Object", ["Thor's Hammer"]),
    "Stormbreaker": ("Object", []),
    "Eye of Agamotto": ("Object", []),
    "Arc Reactor": ("Object", []),
    "Captain America's Shield": ("Object", ["Shield", "Vibranium Shield"]),
    "Ant-Man Suit": ("Object", []),
    "Ten Rings": ("Object", ["Rings"]),
    "Web-Shooters": ("Object", ["web fluid", "webbing"]),
    "E.D.I.T.H.": ("Object", ["EDITH"]),
    "Darkhold": ("Object", ["Book of the Damned", "Book of Sins"]),
    "Book of Vishanti": ("Object", ["Vishanti"]),
    "Temporal Loom": ("Object", ["Loom", "Tva Loom"]),
    "Time Twister": ("Object", ["Time twisting"]),
    "Necrosword": ("Object", ["All-Black the Necrosword"]),
    "Hulkbuster": ("Object", ["Hulk-Buster", "Veronica"]),
    "Pym Particles": ("Object", ["pym particle"]),

    # ---- organizations
    "SHIELD": ("Organization", ["S.H.I.E.L.D.", "S.H.I.E.L.D", "Strategic Homeland Intervention Enforcement Logistics Division", "S H I E L D"]),
    "HYDRA": ("Organization", ["Hail Hydra", "Hydra"]),
    "Avengers": ("Organization", ["Avengers Initiative", "Earth's Mightiest Heroes", "Guardians of the Multiverse"]),
    "Stark Industries": ("Organization", []),
    "Guardians of the Galaxy": ("Organization", ["Guardians"]),
    "Black Order": ("Organization", ["Children of Thanos"]),
    "Nova Corps": ("Organization", ["Nova Empire", "Nova Prime"]),
    "Ravagers": ("Organization", []),
    "Sovereign": ("Organization", []),
    "Kree": ("Organization", ["Kree Empire", "Kree race", "Supreme Intelligence"]),
    "Skrulls": ("Organization", ["Skrull", "Skrull Empire"]),
    "Talos": ("Character", ["General Talos"]),
    "Chitauri": ("Organization", ["Chitauri army"]),
    "Outriders": ("Organization", ["Outrider"]),
    "Dark Elves": ("Organization", ["Dark Elf"]),
    "Dora Milaje": ("Organization", ["Dora"]),
    "Wakandan Army": ("Organization", []),
    "Damage Control": ("Organization", ["DODC", "Department of Damage Control"]),
    "Oscorp": ("Organization", ["Oscorp Industries", "Oscorp Tower"]),
    "Daily Bugle": ("Organization", ["The Daily Bugle"]),
    "Defenders": ("Organization", ["The Defenders", "Defenders Maneuver"]),
    "Hand": ("Organization", ["The Hand"]),
    "Chaste": ("Organization", ["The Chaste"]),
    "Tracksuit Mafia": ("Organization", ["Tracksuit Draculas", "Tracksuits"]),
    "Roxxon": ("Organization", ["Roxxon Gulf", "Roxxon Corporation"]),
    "The Pride": ("Organization", ["Pride"]),
    "Runaways": ("Organization", ["Pride's kids"]),
    "Clandestines": ("Organization", ["Djinn"]),
    "Eternals": ("Organization", ["Eternal"]),
    "Deviants": ("Organization", ["Deviant"]),
    "Celestials": ("Organization", ["Celestial", "Arishem", "Tiamat"]),
    "Masters of the Mystic Arts": ("Organization", ["Mystic Arts", "Sorcerers", "Zealots"]),
    "Wrecking Crew": ("Organization", ["Wrecker", "Bulldozer", "Piledriver", "Thunderball"]),
    "Intelligencia": ("Organization", []),
    "Greek Pantheon": ("Organization", ["Olympian gods", "Olympians"]),

    # ---- locations
    "Asgard": ("Location", ["Asgardians"]),
    "Wakanda": ("Location", ["Wakandan"]),
    "Kamar-Taj": ("Location", ["Kamar Taj", "Kamartaj", "KamarTaj"]),
    "New York": ("Location", ["NYC", "New York City"]),
    "Stark Tower": ("Location", ["Avengers Tower"]),
    "Xavier's School": ("Location", ["X-Mansion", "Xavier School for Gifted Youngsters", "Xavier Institute"]),
    "Sokovia": ("Location", []),
    "Titan": ("Location", []),
    "Knowhere": ("Location", []),
    "Sakaar": ("Location", []),
    "Quantum Realm": ("Location", []),
    "Ta Lo": ("Location", ["Talo"]),
    "Sovereign Planet": ("Location", []),
    "Counter-Earth": ("Location", []),
    "Westview": ("Location", []),
    "Madripoor": ("Location", ["High Town", "Low Town"]),
    "New Orleans": ("Location", ["NOLA"]),
    "Vormir": ("Location", []),
    "Soul World": ("Location", []),
    "Nidavellir": ("Location", ["dwarf forge"]),
    "Mount Wundagore": ("Location", ["Wundagore"]),
    "Dark Dimension": ("Location", ["Darkforce Dimension"]),
    "Noor Dimension": ("Location", ["Noor"]),
    "Genosha": ("Location", []),

    # ---- misc supporting
    "Odin": ("Character", ["All-Father", "Allfather"]),
    "Frigga": ("Character", []),
    "Heimdall": ("Character", []),
    "Sif": ("Character", []),
    "Jane Foster": ("Character", ["Dr. Foster", "Mighty Thor"]),
    "Darcy Lewis": ("Character", ["Darcy"]),
    "Erik Selvig": ("Character", ["Selvig"]),
    "Hank Pym": ("Character", ["Dr. Pym", "Henry Pym"]),
    "Cassie Lang": ("Character", ["Cassandra Lang"]),
    "Bill Foster": ("Character", ["Goliath"]),
    "Thaddeus Ross": ("Character", ["Thunderbolt Ross", "General Ross", "Ross"]),
    "Betty Ross": ("Character", ["Elizabeth Ross"]),
    "Samuel Sterns": ("Character", ["Leader"]),
    "Howard Stark": ("Character", []),
    "Obadiah Stane": ("Character", ["Obadiah", "Iron Monger"]),
    "Justin Hammer": ("Character", ["Hammer"]),
    "Ivan Vanko": ("Character", ["Whiplash"]),
    "Happy Hogan": ("Character", ["Happy"]),
    "Ned Leeds": ("Character", ["Ned", "guy in the chair"]),
    "Flash Thompson": ("Character", ["Flash"]),
    "Betty Brant": ("Character", []),
    "Everett Ross": ("Character", ["Everett K. Ross"]),
    "Sharon Carter": ("Character", []),
    "Valentina": ("Character", ["Val", "Valentina Allegra de Fontaine", "Contessa"]),
    "T'Chaka": ("Character", []),
    "W'Kabi": ("Character", []),
    "Ayo": ("Character", []),
    "Wenwu": ("Character", ["Xu Wenwu"]),
    "Xu Xialing": ("Character", ["Xialing"]),
    "Katy Chen": ("Character", ["Katy"]),
    "Sersi": ("Character", []),
    "Ikaris": ("Character", []),
    "Thena": ("Character", []),
    "Kingo": ("Character", []),
    "Sprite": ("Character", []),
    "Phastos": ("Character", []),
    "Makkari": ("Character", []),
    "Druig": ("Character", []),
    "Ajak": ("Character", []),
    "Dane Whitman": ("Character", ["Black Knight"]),
    "Kro": ("Character", []),
    "Titania": ("Character", ["Mary MacPherran"]),
    "Skaar": ("Character", ["Skaar, Son of Hulk"]),
    "Mr. Immortal": ("Character", []),
    "Leapfrog": ("Character", []),
    "Nico Minoru": ("Character", ["Nico"]),
    "Alex Wilder": ("Character", []),
    "Karolina Dean": ("Character", ["Lucy in the Sky"]),
    "Gert Yorkes": ("Character", []),
    "Chase Stein": ("Character", []),
    "Molly Hernandez": ("Character", ["Molly Hayes"]),
    "Jonah": ("Character", ["Magistrate"]),
    "Tandy Bowen": ("Character", ["Dagger"]),
    "Tyrone Johnson": ("Character", ["Cloak"]),
    "Mayhem": ("Character", ["Brigid O'Reilly", "Detective O'Reilly"]),
    "Andre Deschaine": ("Character", ["D'Spayre"]),
    "Maya Lopez": ("Character", ["Echo"]),
    "Agatha Harkness": ("Character", ["Agatha"]),
    "Wanda's Hex": ("Object", ["Hex", "Westview Anomaly", "the Hex"]),
    "Time Heist": ("Event", ["time heist plan", "time travel plan"]),
    "Multiverse": ("Object", ["multiversal"]),
    "Multiversal War": ("Event", ["multiverse war"]),
    "Incursions": ("Event", ["Incursion"]),
    "Snap": ("Event", ["the Snap", "Blip", "the Blip"]),
    "Battle of New York": ("Event", ["Battle of NY"]),
    "Chitauri Invasion": ("Event", ["Chitauri attack", "alien invasion of New York"]),
    "Snap That Started It All": ("Event", []),
}


def canonical_id(kind: str, name: str) -> str:
    words = re.sub(r"[^a-zA-Z0-9 ]", "", name.lower()).split()
    words = [w for w in words if w not in STOPWORDS]
    return f"{kind}:" + "_".join(words) if words else f"{kind}:{name.lower().strip()}"


class EntityResolver:
    """Maps extracted names -> canonical ids via alias table + canon seeds.

    In-memory dict lookups; SQLite persists entities and aliases. No full
    scans. Unresolvable names become deterministic ids (new entities).
    """

    def __init__(self, db_path: Path | None = None, seed: bool = True,
                 defer_persist: bool = False) -> None:
        self.db_path = db_path or settings.DATABASE_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._defer_persist = defer_persist
        self._dirty: set[str] = set()
        con = sqlite3.connect(self.db_path)
        con.execute(
            """CREATE TABLE IF NOT EXISTS entities (
                canonical_id TEXT PRIMARY KEY,
                canonical_name TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                aliases TEXT NOT NULL DEFAULT '[]',
                embedding BLOB
            )"""
        )
        con.execute(
            """CREATE TABLE IF NOT EXISTS conflicts (id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT, claim TEXT, source TEXT, confidence REAL, created_at TEXT)"""
        )
        con.commit()
        con.close()

        # in-memory indexes: alias -> candidate canonical ids (an alias can be
        # ambiguous, e.g. 'Stark' the character vs 'Stark' the company)
        self._by_alias: dict[str, list[str]] = {}
        self._entities: dict[str, dict] = {}  # canonical_id -> {name, type, aliases}
        self._load()
        if seed:
            self._seed_canon()

    # ---------- persistence ----------

    def _load(self) -> None:
        con = sqlite3.connect(self.db_path)
        for cid, name, etype, aliases_json in con.execute(
            "SELECT canonical_id, canonical_name, entity_type, aliases FROM entities"
        ).fetchall():
            self._entities[cid] = {"name": name, "type": etype, "aliases": json.loads(aliases_json)}
            for a in [name, *json.loads(aliases_json)]:
                self._by_alias.setdefault(a.strip().lower(), []).append(cid)
        con.close()

    def _persist(self, cid: str) -> None:
        ent = self._entities[cid]
        if self._defer_persist:
            self._dirty.add(cid)
            return
        con = sqlite3.connect(self.db_path)
        con.execute(
            """INSERT INTO entities (canonical_id, canonical_name, entity_type, aliases)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(canonical_id) DO UPDATE SET
                 aliases = excluded.aliases, canonical_name = excluded.canonical_name""",
            (cid, ent["name"], ent["type"], json.dumps(sorted(set(ent["aliases"])))),
        )
        con.commit()
        con.close()

    def flush(self) -> None:
        """Persist deferred entity updates in one transaction."""
        if not self._defer_persist or not self._dirty:
            return
        con = sqlite3.connect(self.db_path)
        rows = []
        for cid in self._dirty:
            ent = self._entities.get(cid)
            if ent:
                rows.append((cid, ent["name"], ent["type"], json.dumps(sorted(set(ent["aliases"])))))
        con.executemany(
            """INSERT INTO entities (canonical_id, canonical_name, entity_type, aliases)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(canonical_id) DO UPDATE SET
                 aliases = excluded.aliases, canonical_name = excluded.canonical_name""",
            rows,
        )
        con.commit()
        con.close()
        self._dirty.clear()

    def _index_alias(self, alias: str, cid: str) -> None:
        key = alias.strip().lower()
        if not key:
            return
        cands = self._by_alias.setdefault(key, [])
        if cid not in cands:
            cands.append(cid)

    # ---------- canon seeds ----------

    def _seed_canon(self) -> None:
        for name, (etype, aliases) in CANON_SEEDS.items():
            if not name.strip() or not name.strip().isascii():
                continue
            self.register(name.strip(), etype, aliases)

    # ---------- public API ----------

    def resolve(self, name: str, entity_type: str) -> str:
        """Resolve to an existing canonical id, or a fresh deterministic one.

        Ambiguous aliases (multiple candidates) resolve to the candidate
        matching the requested type; if no type matches, the first candidate.
        """
        cands = self._by_alias.get(name.strip().lower(), [])
        if len(cands) == 1:
            return cands[0]
        if len(cands) > 1:
            for cid in cands:
                if self._entities[cid]["type"].lower() == entity_type.lower():
                    return cid
            return cands[0]
        return canonical_id(entity_type.lower(), name)

    def register(self, name: str, entity_type: str, aliases: list[str] | None = None) -> str:
        """Register an entity; merge only into same-type existing entities.

        Prevents cross-type alias captures (e.g. the org 'SHIELD' being
        swallowed by the object 'Captain America's Shield' via the 'shield'
        alias): if the only alias candidate has a different type, a fresh
        type-qualified entity is created instead.
        """
        cid = canonical_id(entity_type.lower(), name)
        ent = self._entities.get(cid)
        if ent is None:
            # maybe an alias of an existing SAME-type entity
            for cand in self._by_alias.get(name.strip().lower(), []):
                if self._entities[cand]["type"].lower() == entity_type.lower():
                    cid = cand
                    ent = self._entities[cand]
                    break
        merged = list(aliases or [])
        if ent is None:
            ent = {"name": name.strip(), "type": entity_type, "aliases": merged}
            self._entities[cid] = ent
        else:
            ent["aliases"] = sorted({*ent["aliases"], *(aliases or [])})
        # index the canonical name + aliases
        self._index_alias(ent["name"], cid)
        for a in ent["aliases"]:
            self._index_alias(a, cid)
        self._persist(cid)
        return cid

    def known_entities(self) -> list[dict]:
        return [
            {"id": cid, "name": e["name"], "type": e["type"], "aliases": e["aliases"]}
            for cid, e in self._entities.items()
        ]

    def record_conflict(self, subject: str, claim: str, source: str, confidence: float) -> None:
        from datetime import datetime, timezone

        con = sqlite3.connect(self.db_path)
        con.execute(
            "INSERT INTO conflicts (subject, claim, source, confidence, created_at) VALUES (?, ?, ?, ?, ?)",
            (subject, claim, source, confidence, datetime.now(timezone.utc).isoformat()),
        )
        con.commit()
        con.close()

    def stats(self) -> dict:
        from collections import Counter

        return {
            "entities": len(self._entities),
            "aliases": sum(len(v) for v in self._by_alias.values()),
            "by_type": dict(Counter(e["type"] for e in self._entities.values())),
        }
