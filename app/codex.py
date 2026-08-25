"""Derived codex profiles: diet, behavior, likes/dislikes, beloved/loathed terrain.

Deterministic per entry — same slug always yields the same profile, no storage.
Ponytail: pure stdlib derivation from existing fields (name/family/habitat/danger/
alignment). If entries later carry hand-authored codex text, prefer it and fall
back to this only when the field is empty.
"""
from __future__ import annotations

import random
from typing import Any

# Family keyword -> theme key (first match wins)
_THEMES: list[tuple[str, str]] = [
    ("aquatic", "aquatic"), ("serpent", "aquatic"), ("abyss", "aquatic"),
    ("forest", "forest"), ("plant", "forest"),
    ("avian", "sky"), ("cosmic", "cosmic"), ("celestial", "cosmic"), ("extraterre", "cosmic"),
    ("infernal", "infernal"), ("demon", "infernal"),
    ("undead", "undead"), ("spectral", "undead"),
    ("arachnid", "swarm"), ("insect", "swarm"),
    ("beast", "beast"), ("fae beast", "beast"), ("chimera", "beast"), ("amphib", "beast"),
    ("fae", "fae"), ("construct", "construct"), ("goblinkin", "construct"),
    ("draconic", "beast"), ("giant", "beast"), ("shapeshift", "fae"),
    ("yokai", "fae"), ("spirit", "fae"), ("elemental", "construct"),
]

_DIET = {
    "aquatic": ["reef fish and river shellfish", "kelp, crayfish, and stolen nets of sardines", "freshwater eels and waterweed shoots"],
    "forest": ["wild berries, honeycomb, and tender shoots", "forest fruits, nuts, and the occasional egg", "sap, blossoms, and grubs from rotting logs"],
    "sky": ["small birds caught in open air", "mountain goats and high-roosting fowl", "wind-borne seeds and cliff-nesting birds"],
    "cosmic": ["starlight siphoned through open water or glass", "meteor iron and the warmth of reflected moons", "prayers, offered freely, and moonlit dew"],
    "infernal": ["warm emotion — pride works best, fear in a pinch", "burnt offerings and candle flame", "vital heat, sipped slowly from willing donors"],
    "undead": ["life essence drawn from lingering warmth", "memories of the recently living", "grave-candle smoke and old grief"],
    "swarm": ["aphid honeydew and bark sap", "carrion, leaf litter, and ripe fallen fruit", "nectar, pollen, and smaller swarms"],
    "beast": ["red meat and root vegetables", "game birds, river fish, and wild tubers", "whatever the herd brings down, shared by rank"],
    "fae": ["milk and honey left on doorsteps", "ripened fruit, sweet cream, and borrowed songs", "dew wine and the first bite of any harvest"],
    "construct": ["lamp oil, coal, and polished metal shavings", "ambient magic and steady attention", "oiled rags, warm hearths, and fresh rainwater"],
}
_SIDE = {
    "aquatic": "cracked urchins", "forest": "charred chestnuts", "sky": "cloudberries",
    "cosmic": "sugar-glass ornaments", "infernal": "spiced wine", "undead": "warm bread",
    "swarm": "overripe figs", "beast": "smoked trout", "fae": "sweetened cream", "construct": "linseed oil",
}

_CYCLE = {"aquatic": "dusk-active", "sky": "dawn-active", "cosmic": "most lively under open night sky",
          "infernal": "nocturnal", "undead": "strictly nocturnal", "forest": "crepuscular",
          "swarm": "warm-afternoon active", "beast": "diurnal", "fae": "twilight-active", "construct": "keeps no cycle at all"}
_SOCIAL = ["solitary outside of mating season", "mated pairs holding shared ground", "small prides of three to five",
           "loose covens that gather at new moon", "a dominant dame with grown daughters in tow", "solitary, but loyal to a chosen settlement"]

_LOVED = {
    "aquatic": "slow, deep water with overhanging shade", "forest": "old-growth shade with moss underfoot",
    "sky": "high thermals and uncrowded ridgelines", "cosmic": "open ground with an unbroken view of the sky",
    "infernal": "warm stone, low light, and iron-banked coals", "undead": "still, dry dark that holds a chill",
    "swarm": "damp timber and undisturbed leaf piles", "beast": "open meadow edge with quick cover nearby",
    "fae": "ring-fenced groves and liminal hour light", "construct": "swept rooms with one steady heat source",
}
# habitat keyword -> loathed biome
_HATE_ENV = [
    (r"sea|ocean|river|lake|cenote|water|marsh|whirlpool|willow|flood", "high, dry altitude — thin air and no water deep enough to sink into"),
    (r"desert|dune|salt|tomb|necropoli|canyon|mesa", "waterlogged ground — soaked soil reads to her as drowning waiting to happen"),
    (r"snow|glacier|frost|winter|ice|cold|northern|highland|loch", "sweltering lowland heat — it dulls the senses and shortens the temper"),
    (r"volcan|sulfur|ember|lava|forge|fire", "deep cold — frost seeps into the joints and slows the blood"),
    (r"forest|grove|orchard|meadow|clearing|willow", "treeless sprawl — bare horizons leave her exposed and ill-tempered"),
    (r"cave|cavern|underground|deep|mine", "wide-open plains — no walls, no shadow, nowhere to listen"),
    (r"city|estate|market|home|inn|crossroad|road|bridge", "howling wilderness — too quiet, and nothing to trade"),
    (r"ruin|temple|crypt|shrine", "bright, busy reconstruction — scaffolding and crowds offend the old quiet"),
]
_GENERIC_HATE = "anywhere crowded, loud, and freshly painted"
_DISLIKES = ["iron left bare where she walks", "stagnant water", "whistling indoors", "broken promises", "mirrors at dusk",
             "the smell of wet dog", "unswept thresholds", "being photographed", "cold tea", "dogs, on principle",
             "bells after dark", "salt across a doorway"]
_LIKES = ["rain on warm stone", "shiny things she can pocket", "long unhurried grooming", "stories told correctly",
          "fresh linen", "being admired at a polite distance", "birdsong before sunrise", "well-kept gardens",
          "the smell of old books", "moonlight on water", "haggling for the joy of it", "quiet company"]

_DISPO = {"Unknown": "wary", "Chaotic": "mercurial", "Neutral": "even-tempered", "Lawful": "ceremonious",
          "Good": "warm-hearted", "Evil": "cold-eyed", "Friendly": "cordial", "Hostile": "ill-disposed"}
_AGGRO = {1: "retreats from conflict and only fights when cornered",
          2: "warns first, and means the warning",
          3: "escalates quickly but accepts a sincere apology",
          4: "gives no second warning and holds grudges in writing",
          5: "treats trespass as a declaration of intent"}


def _pick(rng: random.Random, pool: list[str]) -> str:
    return pool[rng.randrange(len(pool))]


def _theme(family: str) -> str:
    f = (family or "").lower()
    for needle, theme in _THEMES:
        if needle in f:
            return theme
    return "beast"


def _hated(habitat: str) -> str:
    h = (habitat or "").lower()
    for pattern, line in _HATE_ENV:
        import re
        if re.search(pattern, h):
            return line
    return _GENERIC_HATE


def build(entry: dict[str, Any]) -> dict[str, str]:
    """Stable naturalist profile derived from the entry's own fields."""
    rng = random.Random(f"codex:{entry.get('slug') or entry.get('name')}")
    theme = _theme(str(entry.get("family") or ""))
    danger = max(1, min(5, int(entry.get("danger") or 2)))
    alignment = str(entry.get("alignment") or "Unknown")
    habitat = str(entry.get("habitat") or "unrecorded range")
    dispo = next((v for k, v in _DISPO.items() if k.lower() in alignment.lower()), "wary")
    social = _pick(rng, _SOCIAL)
    return {
        "diet": f"Primarily {_pick(rng, _DIET[theme])}; never turns down {_SIDE[theme]}.",
        "behavior": f"{_CYCLE[theme].capitalize()}, {social}. Toward strangers she is {dispo}, and {_AGGRO[danger]}.",
        "likes": ", ".join(sorted(rng.sample(_LIKES, 3))),
        "dislikes": ", ".join(sorted(rng.sample(_DISLIKES, 3))),
        "loved_environment": f"Thrives around {habitat.lower() if 'official profile' not in habitat.lower() else 'her ancestral range'} — {_LOVED[theme]}.",
        "hated_environment": _hated(habitat),
    }


if __name__ == "__main__":
    # self-check: stable, distinct, complete
    a = build({"slug": "yuki-onna", "name": "Yuki-onna", "family": "Winter Spirit", "danger": 4, "alignment": "Neutral", "habitat": "Snowbound passes"})
    b = build({"slug": "yuki-onna", "name": "Yuki-onna", "family": "Winter Spirit", "danger": 4, "alignment": "Neutral", "habitat": "Snowbound passes"})
    c = build({"slug": "alraune", "name": "Alraune", "family": "Plant Spirit", "danger": 3, "alignment": "Chaotic", "habitat": "Forest clearings"})
    assert a == b, "profile must be deterministic"
    assert set(a) == {"diet", "behavior", "likes", "dislikes", "loved_environment", "hated_environment"}
    assert a["diet"] != c["diet"] or a["likes"] != c["likes"], "different species should diverge"
    assert a["hated_environment"] != a["loved_environment"]
    print("codex self-check OK")
    print(a["diet"]); print(a["behavior"]); print(a["likes"]); print(a["hated_environment"])
