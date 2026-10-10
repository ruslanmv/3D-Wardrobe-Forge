"""OC3. The Studio's occasion helpers (apps/studio/js/occasions.js), run under node.

The page decides in that module, and only there, which occasions, styles and looks an
avatar is shown. These tests feed it this Forge's own ``GET /v1/outfits`` answer and check
the rules the page relies on: nothing private without private mode, the Private occasion
absent rather than locked, no empty style, and "Tell me what to change…" read sensibly.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from wardrobe.pipeline import outfit_dictionary as od

MODULE = Path(__file__).resolve().parents[2] / "apps" / "studio" / "js" / "occasions.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

SCRIPT = r"""
const m = await import(process.argv[1]);
const catalogue = JSON.parse(process.argv[2]);
const colours = ['black', 'white', 'red', 'dark grey', 'grey', 'navy', 'pink'];
const view = (adult) => m.visibleOccasions(catalogue, { adult }).map((o) => ({
    id: o.id,
    styles: o.styles.map((s) => ({ id: s.id, looks: s.looks.map((l) => [l.id, l.rating]) })),
}));
const store = new Map();
const storage = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, String(v)) };
const broken = { getItem: () => { throw new Error('blocked'); }, setItem: () => { throw new Error('blocked'); } };
m.usage.bump('gym', storage); m.usage.bump('gym', storage); m.usage.bump('work', storage);
const shown = m.visibleOccasions(catalogue, { adult: false });
console.log(JSON.stringify({
    general: view(false),
    adult: view(true),
    intents: [
        'something for the beach', "let's go clubbing", 'make it red', 'navy', 'a cream cropped cardigan',
        'private lingerie', 'school', '', 'Make it dark grey!',
    ].map((t) => m.readIntent(t, { colours, available: shown.map((o) => o.id) })),
    recolour: [
        m.recolour('black satin spaghetti strap bodycon mini dress', 'red', colours),
        m.recolour('dark grey long cardigan', 'pink', colours),
        m.withoutColour('white fitted tee', colours),
    ],
    pieces: m.pieces('black corset top + black slim jeans +  black stiletto ankle boots'),
    compose: [
        m.compose('black satin bodycon mini dress + black patent stiletto ankle boots', 'black patent platform boots'),
        m.compose('black satin bodycon mini dress + black patent platform boots', 'red satin bodycon mini dress'),
        m.compose('white fitted tee + blue straight jeans', 'red wrap dress'),
        m.compose('white fitted tee + blue straight jeans + white flat shoes', 'cream cropped cardigan'),
        m.compose('black satin cocktail dress', 'white cropped tee'),
        m.compose('grey blazer + white blouse + grey pencil skirt', 'navy shirt dress'),
    ],
    forYou: m.forYou(shown, m.usage.read(storage)).map((o) => o.id),
    blocked: [m.usage.read(broken), m.usage.bump('gym', broken), [...m.favourites.toggle('mira', 'look_1', broken)]],
    favourites: [...m.favourites.toggle('mira', 'look_1', storage)],
    surprise: m.surprise([{ look: { prompt: 'a' } }, { look: { prompt: 'b' } }], { avoidPrompt: 'a', random: () => 0.99 }).look.prompt,
    shelf: m.shelfGroups(
        [{ id: 1, occasion: 'work' }, { id: 2 }, { id: 3, occasion: 'gym' }, { id: 4, occasion: 'private' }],
        shown,
    ).map((g) => [g.id, g.looks.map((l) => l.id)]),
}));
"""


@pytest.fixture(scope="module")
def result(template_catalog):
    catalogue = od.catalogue(template_catalog)
    out = subprocess.run(
        ["node", "--input-type=module", "-e", SCRIPT, MODULE.as_uri(), json.dumps(catalogue)],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return json.loads(out.stdout)


def test_without_private_mode_nothing_private_is_offered(result):
    ids = [o["id"] for o in result["general"]]
    assert ids == [
        "night-out",
        "work",
        "gym",
        "sleep",
        "shopping",
        "vacation",
        "campus",
    ]  # no Private tile at all
    for occasion in result["general"]:
        for style in occasion["styles"]:
            assert style["looks"], (occasion["id"], style["id"])
            assert all(rating == "general" for _id, rating in style["looks"]), (occasion["id"], style["id"])
    beach = next(s for o in result["general"] for s in o["styles"] if s["id"] == "beach")
    assert [look for look, _ in beach["looks"]] == ["cami-denim-shorts"]  # the bikinis wait for private mode


def test_with_private_mode_the_private_occasion_and_swimwear_appear(result):
    assert result["adult"][-1]["id"] == "private"
    beach = next(s for o in result["adult"] for s in o["styles"] if s["id"] == "beach")
    assert "triangle-bikini" in [look for look, _ in beach["looks"]]


def test_what_she_is_told_is_read_as_an_occasion_a_colour_or_a_garment(result):
    beach, club, red, navy, cardigan, private, school, empty, grey = result["intents"]
    assert beach == {"kind": "occasion", "occasion": "vacation", "style": "beach"}
    assert club == {"kind": "occasion", "occasion": "night-out", "style": None}
    assert red == {"kind": "colour", "colour": "red"} and navy == {"kind": "colour", "colour": "navy"}
    assert grey == {"kind": "colour", "colour": "dark grey"}
    assert cardigan == {"kind": "garment", "prompt": "a cream cropped cardigan"}
    # Private is not shown to this avatar, so the word opens nothing: it is a garment request,
    # which the server's gate answers.
    assert private == {"kind": "garment", "prompt": "private lingerie"}
    assert school == {"kind": "occasion", "occasion": "campus", "style": None}
    assert empty is None


def test_recolour_keeps_the_cut_and_pieces_split_like_the_planner(result):
    assert result["recolour"] == [
        "red satin spaghetti strap bodycon mini dress",
        "pink long cardigan",
        "fitted tee",
    ]
    assert result["pieces"] == ["black corset top", "black slim jeans", "black stiletto ankle boots"]


def test_a_change_takes_the_place_of_what_it_replaces(result):
    """The outfit a change leaves: boots for boots, a dress for a dress or a top and bottom."""
    assert result["compose"] == [
        "black satin bodycon mini dress + black patent platform boots",
        "red satin bodycon mini dress + black patent platform boots",
        "red wrap dress",
        "white fitted tee + blue straight jeans + cream cropped cardigan + white flat shoes",
        # A top does not cover what a dress does: the Forge layers it, and so does the recipe.
        "black satin cocktail dress + white cropped tee",
        # "shirt dress" is a dress, not a shirt; the blazer is a layer and stays.
        "grey blazer + navy shirt dress",
    ]


def test_for_you_favourites_and_blocked_storage(result):
    assert result["forYou"] == ["gym"]  # chosen twice; once is not yet a habit
    assert result["favourites"] == ["look_1"]
    assert result["blocked"] == [{}, {"gym": 1}, ["look_1"]]  # blocked storage never throws
    assert result["surprise"] == "b"


def test_the_shelf_groups_by_occasion_and_hides_none(result):
    # A private-occasion look on a shelf without private mode is grouped as designed, never dropped.
    assert result["shelf"] == [["work", [1]], ["gym", [3]], ["", [2, 4]]]
