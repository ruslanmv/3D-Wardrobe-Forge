"""DC3. Fashion collections: a dress and the boots that go with it, chosen piece by piece.

``sexy-discoteca-black`` — Sexy Discoteca, All Black — is a short black bodycon dress and
four pairs of black boots that make four different nights out of it: stiletto ankle boots,
platforms, combat boots and over-the-knee boots. It is a *menu*, not a new kind of request.
Every choice here is words the planner already reads, so a collection look is planned,
fitted, gated and stored exactly as if the prompt had been typed: the dress is
``dress-mini-bodycon-v1`` with its straps, neckline, back and finish asked for by name, and
each boot is the template its words select (``wardrobe.geometry.boots``). Nothing here is
underwear or sheer, so nothing here needs an adult declaration, and nothing grants one.

The Studio builds its Collection panel from ``catalogue()``. It makes the dress once, then
puts each pair of boots on *that look* (``baseLookId``): changing boots re-fits the boots
and re-stands her on their heels (``wardrobe.vrm.stance``), and never rebuilds the dress.
The four outfit presets (``wardrobe.pipeline.look_presets``) are the same choices made in
one job each.
"""

from __future__ import annotations

#: Choices are (id, title, the words they add to the prompt).
COLLECTIONS: dict[str, dict] = {
    "sexy-discoteca-black": {
        "title": "Sexy Discoteca",
        "subtitle": "All Black",
        "colour": "black",
        "description": "A short black bodycon dress and four black boots: four nights out.",
        "dress": {
            "templateId": "dress-mini-bodycon-v1",
            "noun": "bodycon mini dress",
            "options": {
                "straps": [
                    ("spaghetti", "Spaghetti straps", "spaghetti strap"),
                    ("strapless", "Strapless", "strapless"),
                    ("cross-back", "Cross-back", "cross-back"),
                ],
                "neckline": [("straight", "Straight", ""), ("sweetheart", "Sweetheart", "sweetheart")],
                "back": [("closed", "Closed", ""), ("open", "Open back", "open back")],
                "material": [
                    ("matte", "Matte", "matte"),
                    ("satin", "Satin", "satin"),
                    ("glossy", "Glossy", "glossy"),
                    ("leather", "Leather", "leather"),
                ],
            },
            "defaults": {
                "straps": "spaghetti",
                "neckline": "straight",
                "back": "closed",
                "material": "satin",
            },
        },
        "boots": [
            {
                "id": "stiletto-ankle",
                "letter": "A",
                "title": "Stiletto ankle boots",
                "noun": "stiletto ankle boots",
                "templateId": "shoes-stiletto-ankle-boots-v1",
                "material": "patent",
                "points": ["Pointed toe", "95 mm needle heel", "Fitted ankle shaft"],
            },
            {
                "id": "platform",
                "letter": "B",
                "title": "Platform boots",
                "noun": "platform boots",
                "templateId": "shoes-platform-boots-v1",
                "material": "patent",
                "points": ["55 mm platform", "150 mm block heel", "Inside zip, below the knee"],
            },
            {
                "id": "combat",
                "letter": "C",
                "title": "Combat boots",
                "noun": "combat boots",
                "templateId": "shoes-combat-boots-v1",
                "material": "matte-leather",
                "points": ["Lugged sole", "Front laces, eyelets", "Padded collar"],
            },
            {
                "id": "over-knee",
                "letter": "D",
                "title": "Over-the-knee boots",
                "noun": "over-the-knee boots",
                "templateId": "shoes-over-knee-boots-v1",
                "material": "stretch-leather",
                "heels": {
                    "block": ("over-the-knee boots", "shoes-over-knee-boots-v1"),
                    "stiletto": ("over-the-knee stiletto boots", "shoes-over-knee-stiletto-boots-v1"),
                },
                "points": ["Shaft above the knee", "Slim, close to the leg", "Block or stiletto heel"],
            },
        ],
        "bootMaterials": [
            ("patent", "Patent", "patent"),
            ("matte-leather", "Matte leather", "matte leather"),
            ("suede", "Suede", "suede"),
            ("stretch-leather", "Stretch leather", "stretch leather"),
        ],
        # The four outfits, one per boot: each is a look preset (wardrobe.pipeline.look_presets)
        # and a starting point in the Studio's Collection panel.
        "presets": [
            {
                "id": "discoteca_stiletto_ankle",
                "title": "Stiletto ankle boots",
                "boot": "stiletto-ankle",
                "dress": {},
            },
            {
                "id": "discoteca_platform",
                "title": "Platform boots",
                "boot": "platform",
                "dress": {"straps": "strapless", "neckline": "sweetheart", "material": "satin"},
            },
            {
                "id": "discoteca_combat",
                "title": "Combat boots",
                "boot": "combat",
                "dress": {"straps": "cross-back", "material": "leather"},
            },
            {
                "id": "discoteca_over_knee",
                "title": "Over-the-knee boots",
                "boot": "over-knee",
                "dress": {"straps": "strapless", "material": "matte"},
            },
        ],
    },
}


def _words(options: list[tuple], choice: str | None) -> str:
    return next((words for key, _title, words in options if key == choice), "")


def dress_prompt(collection: str, choices: dict | None = None) -> str:
    """The dress as the planner reads it: "black satin spaghetti strap … bodycon mini dress"."""
    spec = COLLECTIONS[collection]
    dress = spec["dress"]
    picked = {**dress["defaults"], **(choices or {})}
    parts = (
        [spec["colour"]]
        + [
            _words(dress["options"][key], picked.get(key))
            for key in ("material", "straps", "neckline", "back")
        ]
        + [dress["noun"]]
    )
    return " ".join(part for part in parts if part)


def boots_prompt(collection: str, boot: str, material: str | None = None, heel: str | None = None) -> str:
    """One pair of the collection's boots: "black patent stiletto ankle boots"."""
    spec = COLLECTIONS[collection]
    entry = next(b for b in spec["boots"] if b["id"] == boot)
    noun = entry["heels"][heel][0] if heel and "heels" in entry and heel in entry["heels"] else entry["noun"]
    words = _words(spec["bootMaterials"], material or entry["material"])
    return " ".join(part for part in (spec["colour"], words, noun) if part)


def outfit_prompt(
    collection: str,
    boot: str,
    dress: dict | None = None,
    material: str | None = None,
    heel: str | None = None,
) -> str:
    return f"{dress_prompt(collection, dress)} + {boots_prompt(collection, boot, material, heel)}"


def look_presets() -> dict[str, dict]:
    """Every collection outfit as a look preset (wardrobe.pipeline.look_presets): id -> entry."""
    return {
        preset["id"]: {
            "title": f"{spec['title'].split()[-1]} · {preset['title']}",
            "prompt": outfit_prompt(key, preset["boot"], preset["dress"]),
            "collection": key,
        }
        for key, spec in COLLECTIONS.items()
        for preset in spec["presets"]
    }


def catalogue() -> list[dict]:
    """The collections as the Studio lists them: every choice with the words it adds."""
    out = []
    for key, spec in COLLECTIONS.items():
        dress = spec["dress"]
        out.append(
            {
                "id": key,
                "title": spec["title"],
                "subtitle": spec["subtitle"],
                "colour": spec["colour"],
                "description": spec["description"],
                "dress": {
                    "templateId": dress["templateId"],
                    "options": {
                        name: [{"id": k, "title": t, "words": w} for k, t, w in values]
                        for name, values in dress["options"].items()
                    },
                    "defaults": dict(dress["defaults"]),
                    "noun": dress["noun"],
                    "prompt": dress_prompt(key),
                },
                "boots": [
                    {
                        **{k: v for k, v in boot.items() if k != "heels"},
                        "heels": sorted(boot.get("heels", {})),
                        "heelNouns": {
                            heel: noun for heel, (noun, _template) in boot.get("heels", {}).items()
                        },
                        "prompt": boots_prompt(key, boot["id"]),
                    }
                    for boot in spec["boots"]
                ],
                "bootMaterials": [{"id": k, "title": t, "words": w} for k, t, w in spec["bootMaterials"]],
                "presets": [
                    {**preset, "prompt": outfit_prompt(key, preset["boot"], preset["dress"])}
                    for preset in spec["presets"]
                ],
            }
        )
    return out


__all__ = ["COLLECTIONS", "boots_prompt", "catalogue", "dress_prompt", "look_presets", "outfit_prompt"]
