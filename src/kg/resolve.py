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
    # characters — avengers core
    "Iron Man": ("Character", ["Tony Stark", "Anthony Stark", "Mr. Stark", "Stark"]),
    "Captain America": ("Character", ["Steve Rogers", "Steven Rogers", "Rogers", "Cap"]),
    "Thor": ("Character", ["God of Thunder", "Point Break"]),
    "Hulk": ("Character", ["Bruce Banner", "Banner", "David Banner"]),
    "Black Widow": ("Character", ["Natasha Romanoff", "Natasha Romanov", "Natasha", "Romanoff"]),
    "Hawkeye": ("Character", ["Clint Barton", "Clinton Barton", "Barton"]),
    "Loki": ("Character", ["Loki Laufeyson", "God of Mischief"]),
    "Scarlet Witch": ("Character", ["Wanda Maximoff", "Wanda"]),
    "Quicksilver": ("Character", ["Pietro Maximoff", "Pietro"]),
    "Vision": ("Character", []),
    "War Machine": ("Character", ["Rhodey", "James Rhodes", "Rhodes"]),
    "Falcon": ("Character", ["Sam Wilson", "Samuel Wilson", "Wilson"]),
    "Winter Soldier": ("Character", ["Bucky", "Bucky Barnes", "James Barnes", "Buchanan Barnes"]),
    "Spider-Man": ("Character", ["Peter Parker", "Peter", "Spidey"]),
    "Doctor Strange": ("Character", ["Stephen Strange", "Strange", "Sorcerer Supreme"]),
    "Ant-Man": ("Character", ["Scott Lang", "Scott"]),
    "Wasp": ("Character", ["Hope van Dyne", "Hope Pym", "Hope"]),
    "Guardians of the Galaxy": ("Organization", ["Guardians"]),
    "Star-Lord": ("Character", ["Peter Quill", "Quill"]),
    "Gamora": ("Character", []),
    "Drax": ("Character", ["Drax the Destroyer"]),
    "Groot": ("Character", []),
    "Rocket": ("Character", ["Rocket Raccoon", "89P13"]),
    "Mantis": ("Character", []),
    "Nebula": ("Character", []),
    "Yondu": ("Character", ["Yondu Udonta"]),
    "Captain Marvel": ("Character", ["Carol Danvers", "Carol"]),
    "Nick Fury": ("Character", ["Fury"]),
    "Maria Hill": ("Character", ["Hill"]),
    "Phil Coulson": ("Character", ["Coulson", "Agent Coulson"]),
    "Black Panther": ("Character", ["T'Challa", "TChalla", "King T'Challa"]),
    "Shuri": ("Character", []),
    "Okoye": ("Character", []),
    "Killmonger": ("Character", ["Erik Killmonger", "N'Jadaka", "NJobu"]),
    "Shang-Chi": ("Character", ["Shaun"]),
    "Wenwu": ("Character", ["The Mandarin", "Xu Wenwu"]),
    "Xu Xialing": ("Character", ["Xialing"]),
    "Katy": ("Character", ["Katy Chen"]),
    "Eternals": ("Organization", []),
    "Sersi": ("Character", []),
    "Ikaris": ("Character", []),
    "Thena": ("Character", []),
    "Kingo": ("Character", []),
    "Sprite": ("Character", []),
    "Phastos": ("Character", []),
    "Makkari": ("Character", []),
    "Druig": ("Character", []),
    "Ajak": ("Character", []),
    "Ms. Marvel": ("Character", ["Kamala Khan", "Kamala"]),
    "Moon Knight": ("Character", ["Marc Spector", "Steven Grant", "Jake Lockley"]),
    "She-Hulk": ("Character", ["Jennifer Walters", "Jen Walters"]),
    "Ironheart": ("Character", ["Riri Williams"]),
    "Echo": ("Character", ["Maya Lopez"]),
    "Agatha Harkness": ("Character", ["Agatha"]),
    "Wonder Man": ("Character", ["Simon Williams"]),
    # villains
    "Thanos": ("Character", ["Mad Titan"]),
    "Ultron": ("Character", []),
    "Red Skull": ("Character", ["Johann Schmidt"]),
    "Loki Variant": ("Character", ["Variant Loki", "Sylvie"]),
    "He Who Remains": ("Character", ["Kang", "Kang the Conqueror", "Nathaniel Richards", "Victor Timely"]),
    "Kang the Conqueror": ("Character", ["Kang"]),
    "Dormammu": ("Character", []),
    "Killian": ("Character", ["Aldrich Killian", "Mandarin"]),
    "Vulture": ("Character", ["Adrian Toomes"]),
    "Mysterio": ("Character", ["Quentin Beck"]),
    "Hela": ("Character", []),
    "Grandmaster": ("Character", ["En Dwi Gast"]),
    "Kilmonger": ("Character", ["Erik Killmonger"]),
    "Venom": ("Character", ["Eddie Brock"]),
    "Carnage": ("Character", ["Cletus Kasady"]),
    "Morbius": ("Character", ["Michael Morbius"]),
    "Kraven": ("Character", ["Sergei Kravinoff", "Kraven the Hunter"]),
    "Madame Web": ("Character", ["Cassandra Webb", "Cassie"]),
    # x-men (fox)
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
    " Apocalypse": ("Character", ["En Sabah Nur"]),
    "Apocalypse": ("Character", ["En Sabah Nur"]),
    "Cable": ("Character", ["Nathan Summers"]),
    "Domino": ("Character", ["Neena Thurman"]),
    # spider-verse sony
    "Peter Parker": ("Character", ["Spider-Man"]),
    "Miles Morales": ("Character", ["Kid Arachnid"]),
    "Gwen Stacy": ("Character", ["Spider-Gwen", "Spider-Woman"]),
    "Doctor Octopus": ("Character", ["Doc Ock", "Otto Octavius"]),
    "Green Goblin": ("Character", ["Norman Osborn", "Goblin"]),
    "Sandman": ("Character", ["Flint Marko"]),
    "Electro": ("Character", ["Max Dillon"]),
    "Harry Osborn": ("Character", []),
    "Mary Jane": ("Character", ["MJ", "Mary Jane Watson"]),
    "Aunt May": ("Character", ["May Parker"]),
    "Uncle Ben": ("Character", ["Ben Parker"]),
    "Gwen": ("Character", ["Gwen Stacy"]),
    # defenders / street
    "Daredevil": ("Character", ["Matt Murdock", "Matthew Murdock", "The Devil of Hell's Kitchen"]),
    "Jessica Jones": ("Character", ["JJ"]),
    "Luke Cage": ("Character", ["Power Man", "Carl Lucas"]),
    "Iron Fist": ("Character", ["Danny Rand", "Daniel Rand"]),
    "Punisher": ("Character", ["Frank Castle"]),
    "Kingpin": ("Character", ["Wilson Fisk", "Fisk"]),
    "Elektra": ("Character", ["Elektra Natchios"]),
    "Bullseye": ("Character", ["Benjamin Poindexter", "Dex"]),
    "Purple Man": ("Character", ["Kilgrave", "Kevin Thompson"]),
    "Nuke": ("Character", ["Will Simpson"]),
    "Misty Knight": ("Character", []),
    "Colleen Wing": ("Character", []),
    "Claire Temple": ("Character", []),
    "Bishop": ("Character", ["Kate Bishop", "Kate"]),
    "Maya Lopez": ("Character", ["Echo"]),
    "Kingpin": ("Character", ["Wilson Fisk"]),
    "Yelena": ("Character", ["Yelena Belova"]),
    "John Walker": ("Character", ["US Agent", "U.S. Agent"]),
    "Valentina": ("Character", ["Val", "Valentina Allegra de Fontaine", "Contessa"]),
    "Sharon Carter": ("Character", ["Peggy Carter's niece"]),
    "Peggy Carter": ("Character", ["Agent Carter", "Margaret Carter"]),
    "Howard Stark": ("Character", []),
    "Obadiah Stane": ("Character", ["Obadiah", "Iron Monger"]),
    "Justin Hammer": ("Character", ["Hammer"]),
    "Ivan Vanko": ("Character", ["Whiplash"]),
    "Emil Blonsky": ("Character", ["Abomination"]),
    "Thaddeus Ross": ("Character", ["Thunderbolt Ross", "General Ross", "Ross"]),
    "Betty Ross": ("Character", ["Elizabeth Ross"]),
    "Samuel Sterns": ("Character", ["Leader"]),
    "Jane Foster": ("Character", ["Dr. Foster", "Mighty Thor"]),
    "Darcy": ("Character", ["Darcy Lewis"]),
    "Erik Selvig": ("Character", ["Selvig"]),
    "Heimdall": ("Character", []),
    "Sif": ("Character", []),
    "Odin": ("Character", ["All-Father", "Allfather"]),
    "Frigga": ("Character", []),
    "Valkyrie": ("Character", ["Brunnhilde"]),
    "Korg": ("Character", []),
    "Skurge": ("Character", ["Executioner"]),
    "Kurse": ("Character", ["Algrim"]),
    "Malekith": ("Character", []),
    "Aether": ("Object", ["Reality Stone"]),
    "Collector": ("Character", ["Taneleer Tivan"]),
    "Grandmaster": ("Character", ["En Dwi Gast"]),
    "Hank Pym": ("Character", ["Dr. Pym", "Henry Pym"]),
    "Janet van Dyne": ("Character", ["Janet Pym", "Wasp"]),
    "Cassie Lang": ("Character", ["Cassandra Lang"]),
    "Ghost": ("Character", ["Ava"]),
    "Sonny Burch": ("Character", []),
    "Bill Foster": ("Character", ["Goliath"]),
    "TVA": ("Organization", ["Time Variance Authority", "Time-Keepers", "Time Keepers"]),
    "Mobius": ("Character", ["Mobius M. Mobius", "Agent Mobius"]),
    "Ravonna Renslayer": ("Character", ["Renslayer", "Hunter B-15", "B-15"]),
    "O.B.": ("Character", ["Ouroboros", "Ouroboros A.I."]),
    "Miss Minutes": ("Character", []),
    "Minutemen": ("Organization", ["Minuteman"]),
    "Time Cell": ("Object", []),
    "Loom": ("Object", ["Temporal Loom"]),
    "Temporal Loom": ("Object", ["Loom"]),
    "He Who Remains' Office": ("Location", []),
    # objects / mcguffins
    "Tesseract": ("Object", ["Cosmic Cube", "Space Stone"]),
    "Scepter": ("Object", ["Chitauri Scepter", "Loki's Scepter", "Mind Stone"]),
    "Infinity Stones": ("Object", ["Infinity Stone", "Soul Stone", "Power Stone", "Time Stone"]),
    "Mjolnir": ("Object", ["Thor's Hammer"]),
    "Stormbreaker": ("Object", []),
    "Eye of Agamotto": ("Object", ["Time Stone"]),
    "Arc Reactor": ("Object", []),
    "Iron Man Suit": ("Object", ["Mark 42", "Mark 3", "Iron Man Armor", "suit"]),
    "Captain America's Shield": ("Object", ["Shield", "Vibranium Shield"]),
    "Winter Soldier's Arm": ("Object", ["Bionic Arm"]),
    "Ant-Man Suit": ("Object", []),
    "Yellowjacket Suit": ("Object", []),
    "Ten Rings": ("Object", ["Rings"]),
    "Death Note": ("Object", []),
    "Necrosword": ("Object", ["All-Black the Necrosword"]),
    "Gorr's Sword": ("Object", []),
    "Yellow Suit": ("Object", []),
    "Web-Shooters": ("Object", ["web fluid", "webbing"]),
    "E.D.I.T.H.": ("Object", ["EDITH", "E.D.I.T.H. glasses"]),
    "Multiverse": ("Object", ["multiversal"]),
    # organizations
    "SHIELD": ("Organization", ["S.H.I.E.L.D.", "S.H.I.E.L.D", "Strategic Homeland Intervention Enforcement Logistics Division", "S H I E L D"]),
    "HYDRA": ("Organization", ["Hail Hydra", "Hydra"]),
    "Avengers": ("Organization", ["Avengers Initiative", "Earth's Mightiest Heroes"]),
    "Asgard": ("Location", ["Asgardians"]),
    "Wakanda": ("Location", ["Wakandan"]),
    "Kamar-Taj": ("Location", ["Kamar Taj"]),
    "New York": ("Location", ["NYC", "New York City"]),
    "Stark Tower": ("Location", ["Avengers Tower", "Stark Industries Tower"]),
    "Xavier's School": ("Location", ["X-Mansion", "Xavier School for Gifted Youngsters", "Xavier Institute"]),
    "Genosha": ("Location", []),
    "Sokovia": ("Location", []),
    "Titan": ("Location", []),
    "Knowhere": ("Location", []),
    "Nova Corps": ("Organization", ["Nova Empire"]),
    "Ravagers": ("Organization", []),
    "Sakaar": ("Location", []),
    "Ego": ("Character", ["Celestial", "Ego the Living Planet"]),
    "Quantum Realm": ("Location", []),
    "Ta Lo": ("Location", ["Talo"]),
    "Talon": ("Location", []),
    "Sovereign": ("Organization", ["Sovereign people"]),
    "Ayesha": ("Character", []),
    "Adam Warlock": ("Character", []),
    "High Evolutionary": ("Character", ["Orgocorps"]),
    "Counter-Earth": ("Location", []),
    "GODS": ("Organization", ["Celestials"]),
    "Celestials": ("Organization", ["Celestial"]),
    "Eternals": ("Organization", []),
    "Deviants": ("Organization", ["Deviant"]),
    "Stark Industries": ("Organization", ["Stark"]),
    "Oscorp": ("Organization", ["Oscorp Industries", "Oscorp Tower"]),
    "Daily Bugle": ("Organization", ["The Daily Bugle"]),
    "Norman Osborn": ("Character", ["Green Goblin"]),
    "Sony": ("Organization", []),
    "Fox": ("Organization", []),
    "Defenders": ("Organization", ["The Defenders", "Defenders Maneuver"]),
    "Hand": ("Organization", ["The Hand"]),
    "Chaste": ("Organization", ["The Chaste"]),
    "Black Knife Cartel": ("Organization", []),
    "Tracksuit Mafia": ("Organization", ["Tracksuit Draculas", "Tracksuits"]),
    "Ronin": ("Character", ["Ronin identity"]),
    " Maya's Army": ("Organization", []),
    "Fisk's Empire": ("Organization", []),
    "Baker's Dozen": ("Organization", []),
    "Greek Pantheon": ("Organization", ["Olympian gods", "Olympians"]),
    "Hades": ("Character", ["Pluto"]),
    "Ares": ("Character", []),
    "Hermes": ("Character", []),
    "Dionysus": ("Character", []),
    "Hebe": ("Character", []),
    "Minerva": ("Character", ["Athena"]),
    "Hecate": ("Character", []),
    "Wanda's Spell": ("Object", ["Hex", "Westview Anomaly", "the Hex"]),
    "Westview": ("Location", []),
    "Darkhold": ("Object", ["Book of the Damned", "Book of Sins"]),
    "Mount Wundagore": ("Location", ["Wundagore"]),
    "book of vishanti": ("Object", ["Book of Vishanti", "Vishanti"]),
    "America Chavez": ("Character", ["America"]),
    "Kamartaj": ("Location", []),
    "Incursion": ("Object", ["Incursions"]),
    "Tva Loom": ("Object", ["Temporal Loom", "Loom"]),
    "Time twisting": ("Object", ["Time Twister"]),
    "Alyx": ("Object", ["Alyx 2.0"]),
    "Dark Elves": ("Organization", ["Dark Elf"]),
    "Chitauri": ("Organization", ["Chitauri army"]),
    "Leviathan": ("Object", ["Leviathans"]),
    "Outriders": ("Organization", ["Outrider"]),
    "Sakaarans": ("Organization", ["Sakaaran"]),
    "Ebony Maw": ("Character", ["Maw"]),
    "Cull Obsidian": ("Character", []),
    "Corvus Glaive": ("Character", ["Glaive"]),
    "Proxima Midnight": ("Character", ["Proxima"]),
    "Black Order": ("Organization", ["Children of Thanos", "Cull Obsidian"]),
    "Valkyrior": ("Organization", ["Valkyries"]),
    "Mar-Vell": ("Character", ["Wendy Lawson", "Carol Danvers' mentor"]),
    "Supreme Intelligence": ("Character", ["Kree Supreme Intelligence"]),
    "Kree": ("Organization", ["Kree Empire", "Kree race"]),
    "Skrulls": ("Organization", ["Skrull", "Skrull Empire"]),
    "Talos": ("Character", ["General Talos"]),
    "Soren": ("Character", []),
    "Goose": ("Character", ["Chewie", "Flerken", "cat"]),
    "Rhomann Dey": ("Character", []),
    "Irani Rael": ("Character", ["Nova Prime"]),
    "Maw": ("Character", ["Ebony Maw"]),
    "Brock Rumlow": ("Character", ["Crossbones"]),
    "Helmut Zemo": ("Character", ["Baron Zemo", "Zemo"]),
    "Everett Ross": ("Character", []),
    "T'Chaka": ("Character", []),
    "W'Kabi": ("Character", []),
    "Nakia": ("Character", []),
    "Everett K. Ross": ("Character", []),
    "Ayo": ("Character", []),
    "Dora Milaje": ("Organization", ["Dora"]),
    "Jabari": ("Organization", ["Jabari Tribe", "Jabari Tribe Leader"]),
    "M'Baku": ("Character", ["Man-Ape"]),
    "N'Jobu": ("Character", []),
    "Ulysses Klaue": ("Character", ["Klaw", "Klaue"]),
    "Hulk-Buster": ("Object", ["Hulkbuster", "Veronica"]),
    "Sam Wilson": ("Character", ["Falcon"]),
    "Wong": ("Character", ["Wong"]),
    "Ancient One": ("Character", []),
    "Kaecilius": ("Character", []),
    "Zealots": ("Organization", ["Kaecilius' Zealots"]),
    "Mordo": ("Character", ["Karl Mordo", "Baron Mordo"]),
    "Christine Palmer": ("Character", []),
    "Nicodemus West": ("Character", ["Dr. West"]),
    "Jonathan Pangborn": ("Character", []),
    "Lucian": ("Character", ["Night Nurse"]),
    "Dorito": ("Object", ["Doritos"]),
    "Mysterio's Drones": ("Object", ["drones"]),
    "Elementals": ("Organization", ["Elemental"]),
    "Quentin Beck's Illusions": ("Object", ["illusions"]),
    "Nick Fury's Skrull Spy Network": ("Organization", ["spy network"]),
    "Maria Hill": ("Character", ["Hill"]),
    "Dimitri": ("Character", []),
    "S Dmitri": ("Character", []),
    "Brad Davis": ("Character", []),
    "Betty Brant": ("Character", []),
    "Flash Thompson": ("Character", ["Flash"]),
    "MJ": ("Character", ["Michelle Jones", "Michelle Jones-Watson"]),
    "Ned": ("Character", ["Ned Leeds", "guy in the chair"]),
    "Happy Hogan": ("Character", ["Happy"]),
    "May Parker": ("Character", ["Aunt May"]),
    "Norman Osborn'": ("Character", []),
    "Otto Octavius": ("Character", ["Doc Ock", "Doctor Octopus"]),
    "Max Dillon": ("Character", ["Electro"]),
    "Flint Marko": ("Character", ["Sandman"]),
    "Curt Connors": ("Character", ["Lizard"]),
    "Peter 2": ("Character", ["Peter Two", "Rami Peter", "Friendly Neighborhood Spider-Man"]),
    "Peter 3": ("Character", ["Peter Three", "Webb Peter", "Amazing Spider-Man"]),
    "Matt Murdock": ("Character", ["Daredevil"]),
    "Stephen Odd": ("Character", []),
    "Pizza Poppa": ("Character", []),
    "Wundagore": ("Location", []),
    "Kamar Taj": ("Location", ["KamarTaj"]),
    "Mysterio'": ("Character", []),
    "Sarah": ("Character", []),
    "Maya": ("Character", ["Maya Lopez"]),
    "Kingo'": ("Character", []),
    "Iron Lad": ("Character", ["Nathaniel Richards", "He Who Remains"]),
    "Thor's Hammer": ("Object", ["Mjolnir"]),
    "Nidavellir": ("Location", ["dwarf forge"]),
    "Eitri": ("Character", ["dwarf king"]),
    "Rescue": ("Character", ["Pepper Potts", "Pepper"]),
    "Frigga": ("Character", []),
    "Rocket Raccoon": ("Character", ["Rocket", "89P13", "trash panda"]),
    "89P13": ("Character", ["Rocket"]),
    "Smart Hulk": ("Character", ["Hulk", "Professor Hulk"]),
    "Ancient One'": ("Character", []),
    "Soul World": ("Location", []),
    "Vormir": ("Location", []),
    "Red Skull's Exile": ("Location", ["Vormir"]),
    "Garden": ("Location", ["Thanos' Garden"]),
    "Time Heist": ("Object", ["time travel", "Time Heist plan"]),
    "Benatar": ("Object", ["Benatar ship"]),
    "Milano": ("Object", ["the Milano", "Milano ship"]),
    "Benatar 2": ("Object", []),
    "Knowhere": ("Location", ["Knowhere Mining Colony"]),
    "Rocket's Toy Story": ("Object", []),
    "Noor Dimension": ("Location", ["Noor", "Clandestine dimension"]),
    "Clandestines": ("Organization", ["Djinn"]),
    "Damage Control": ("Organization", ["DODC", "Department of Damage Control"]),
    "Kamran": ("Character", []),
    "Muneeba Khan": ("Character", ["Kamala's mother"]),
    "Yusuf Khan": ("Character", ["Kamala's father"]),
    "Tyesha Hillman": ("Character", []),
    "Aisha": ("Character", []),
    "Najma": ("Character", []),
    "Kareem": ("Character", ["Red Dagger"]),
    "Aamir Khan": ("Character", []),
    "Zoe Zimmer": ("Character", []),
    "Golden girls": ("Object", ["Stark Industries combat drones"]),
    "AvengerCon": ("Object", ["Avenger Con"]),
    "Shadowland": ("Location", []),
    "Sonic spear": ("Object", ["sonic weapon"]),
    "Winged protect": ("Object", ["wing suit"]),
    "Feige": ("Organization", []),
    "Daily Bugle": ("Organization", []),
    "Batroc": ("Character", ["Georges Batroc", "Batroc the Leaper"]),
    "Flag Smashers": ("Organization", ["Flag Smasher", "Karli's group"]),
    "Karli Morgenthau": ("Character", ["Karli", "Big Loki"]),
    "Power Broker": ("Character", ["Sharon Carter", "Madripoor Power Broker"]),
    "Madripoor": ("Location", ["High Town", "Low Town"]),
    "Selby": ("Character", []),
    "Zemo'": ("Character", []),
    "Nagel": ("Character", ["Dr. Nagel", "Wilfred Nagel"]),
    "Ozeknim": ("Character", []),
    "Dr. Nagel": ("Character", ["Wilfred Nagel", "Nagel"]),
    "Dovich": ("Character", []),
    "Gigi": ("Character", []),
    "DeeDee": ("Character", []),
    "Lennox": ("Character", []),
    "Hobart": ("Character", []),
    "Matias": ("Character", []),
    "Olivia Walker": ("Character", []),
    "Lemar Hoskins": ("Character", ["Battlestar"]),
    "Georges Batroc": ("Character", ["Batroc"]),
    "Ronin's Blades": ("Object", ["Ronin sword"]),
    "Captain Carter": ("Character", ["Peggy Carter", "Agent Carter"]),
    "Infinity Ultron": ("Character", ["Ultron Prime"]),
    "Guardians of the Multiverse": ("Organization", ["Guardians Multiverse"]),
    "Watcher": ("Character", ["Uatu"]),
    "Kahhori": ("Character", []),
    "Strange Supreme": ("Character", ["Doctor Strange", "Stephen Strange"]),
    "Avengers Tower": ("Location", ["Stark Tower"]),
    "HYDRA Stomper": ("Object", ["Steve Rogers' Hydra armor"]),
    "The Initiated": ("Organization", ["Initiated", "Masters of the Mystic Arts"]),
    "Masters of the Mystic Arts": ("Organization", ["Mystic Arts", "Sorcerers"]),
    "Tiamat": ("Character", ["Celestial Tiamat"]),
    "Uni-Mind": ("Object", ["Uni Mind", "unimind"]),
    "Mahd Wy'ry": ("Object", ["Mahd Wyry"]),
    "Dane Whitman": ("Character", ["Black Knight"]),
    "Black Knight": ("Character", ["Dane Whitman"]),
    "Ebony Maw'": ("Character", []),
    "Thena'": ("Character", []),
    "Sprite'": ("Character", []),
    "Kro": ("Character", ["Deviant Kro"]),
    "Arishem": ("Character", ["Celestial Arishem", "Prime Celestial"]),
    "Jstice She-Hulk": ("Character", []),
    "Titania": ("Character", ["Mary MacPherran"]),
    "Abomination": ("Character", ["Emil Blonsky"]),
    "Wrecking Crew": ("Organization", ["Wrecker", "Bulldozer", "Piledriver", "Thunderball"]),
    "Mr. Immortal": ("Character", []),
    "Leapfrog": ("Character", []),
    "Dennis Bukowski": ("Character", []),
    "Runa": ("Character", ["Light Elf"]),
    "Frog-Man": ("Character", ["Eugene Patilio", "Tadpole"]),
    "Luke Jacobson": ("Character", []),
    "Skaar": ("Character", ["Skaar, Son of Hulk"]),
    "HulkKing": ("Character", ["Todd Phelps", "KingHulk", "Intelligencia"]),
    "Intelligencia": ("Organization", []),
    "Saki": ("Character", ["Nico"]),
    "Nico Minoru": ("Character", ["Nico"]),
    "Runaways": ("Organization", ["Pride's kids", "the Runaways"]),
    "Pride": ("Organization", ["The Pride"]),
    "Alex Wilder": ("Character", []),
    "Karolina Dean": ("Character", ["Lucy in the Sky"]),
    "Gert Yorkes": ("Character", ["Old Lace"]),
    "Chase Stein": ("Character", ["Fistigons"]),
    "Molly Hernandez": ("Character", ["Molly Hayes"]),
    "Old Lace": ("Character", ["dinosaur"]),
    "Jonah": ("Character", ["Magistrate"]),
    "Tyrants": ("Organization", []),
    "Dale Yorkes": ("Character", ["Stacey Yorkes"]),
    "Stacey Yorkes": ("Character", []),
    "Victor Stein": ("Character", []),
    "Janet Stein": ("Character", []),
    "Catherine Wilder": ("Character", []),
    "Geoffrey Wilder": ("Character", []),
    "Tandy Bowen": ("Character", ["Dagger", "Lightforce"]),
    "Tyrone Johnson": ("Character", ["Cloak", "Darkforce"]),
    "Mayhem": ("Character", ["Brigid O'Reilly"]),
    "Roxxon": ("Organization", ["Roxxon Gulf", "Roxxon Corporation"]),
    "Andre Deschaine": ("Character", ["D'Spayre"]),
    "Cloak & Dagger": ("Organization", ["Cloak and Dagger"]),
    "New Orleans": ("Location", ["NOLA"]),
    "Darkforce Dimension": ("Location", ["Dark Dimension"]),
    "Lightforce": ("Object", ["lightforce dagger"]),
    "Darkforce": ("Object", ["darkforce cloak"]),
    "Voodoo": ("Character", ["Chantelle"]),
    "Chantelle": ("Character", []),
    "Otis Johnson": ("Character", []),
    "Adina Johnson": ("Character", []),
    "Father Delgado": ("Character", ["Delgado"]),
    "Detective O'Reilly": ("Character", ["Brigid O'Reilly"]),
    "Liam Walsh": ("Character", []),
    "Mina Hess": ("Character", []),
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

    def __init__(self, db_path: Path | None = None, seed: bool = True) -> None:
        self.db_path = db_path or settings.DATABASE_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
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
