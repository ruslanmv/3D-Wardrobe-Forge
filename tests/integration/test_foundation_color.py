"""FC1. ``options.foundationColor``: the colour of the foundation Auto Foundation adds.

Try-On lets her choose the colour once and keeps it under every look of the haul. Pinned
here: the foundation is made in that colour and says so; the next look keeps it while the
colour is unchanged, and replaces it — never doubles it — when the colour changes, half by
half where the new clothes go (a half under clothes she keeps changes with them); a name
that is not a colour is refused; and a job that never asks is unchanged.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tests.integration.test_auto_foundation import body, dress, foundation  # noqa: F401 - fixture
from wardrobe.domain.jobs import JobOptions
from wardrobe.vrm.document import GltfDocument

OUTFIT = "white crop top + blue straight jeans"


def colours(data: bytes) -> dict[str, tuple[str | None, list[float]]]:
    """templateId -> (the colour its tag records, its material's base colour) per Forge foundation."""
    document = GltfDocument.from_bytes(data)
    out = {}
    for node in document.nodes:
        tag = (node.get("extras") or {}).get("wardrobeForge") or {}
        if tag.get("kind") == "garment" and tag.get("role") == "foundation" and "mesh" in node:
            primitive = document.meshes[node["mesh"]]["primitives"][0]
            material = document.materials[primitive["material"]]
            base = material.get("pbrMetallicRoughness", {}).get("baseColorFactor", [1, 1, 1, 1])
            out[tag["templateId"]] = (tag.get("foundationColor"), base)
    return out


def test_a_foundation_colour_is_a_colour_from_the_vocabulary():
    assert JobOptions.model_validate({"foundationColor": " Black "}).foundation_color == "black"
    with pytest.raises(ValidationError):
        JobOptions.model_validate({"foundationColor": "black lace thong"})
    assert JobOptions().foundation_color is None


async def test_the_foundation_is_made_in_the_colour_asked_and_says_so(orchestrator, store, body):  # noqa: F811
    _, look = await dress(orchestrator, store, body, OUTFIT, ensureFoundation=True, foundationColor="black")
    made = colours(look)
    assert made, "no foundation was added"
    for colour, base in made.values():
        assert colour == "black"
        assert max(base[:3]) < 0.1  # black, not the beige it used to be


async def test_the_same_colour_is_kept_and_another_replaces_it(orchestrator, store, body):  # noqa: F811
    _, black = await dress(orchestrator, store, body, OUTFIT, ensureFoundation=True, foundationColor="black")
    _, kept = await dress(
        orchestrator, store, black, "pink fitted tee", ensureFoundation=True, foundationColor="black"
    )
    # Unchanged colour: the very same garments carried over, nothing added.
    assert foundation(kept) == foundation(black)

    # A new colour under a new top: that half is replaced, never doubled. The jeans are carried
    # over, and the half under them with them: it changes when they do, not by taking them off.
    _, red = await dress(orchestrator, store, black, "pink fitted tee", ensureFoundation=True, foundationColor="red")
    after = colours(red)
    assert after["top-tube-v1"][0] == "red" and after["top-tube-v1"][1][0] > 2 * after["top-tube-v1"][1][1]
    assert foundation(red)["shorts-slip-v1"] == foundation(black)["shorts-slip-v1"]
    assert len(after) == len(colours(black))

    # A dress covers both halves: the whole foundation is the new colour.
    _, dressed = await dress(
        orchestrator, store, red, "black bodycon mini dress", ensureFoundation=True, foundationColor="white"
    )
    assert {colour for colour, _ in colours(dressed).values()} == {"white"}


async def test_without_a_colour_nothing_is_tagged(orchestrator, store, body):  # noqa: F811
    _, look = await dress(orchestrator, store, body, OUTFIT, ensureFoundation=True)
    assert {colour for colour, _ in colours(look).values()} == {None}


def test_a_strapless_outfit_gets_a_strapless_foundation_on_any_avatar(template_catalog):
    """FC3. The full-cup bra's straps showed on her shoulders above a strapless bodycon."""
    from wardrobe.domain.looks import OutfitRequest
    from wardrobe.pipeline.generate_garment import ensure_foundation
    from wardrobe.pipeline.plan_outfit_stack import plan_outfit_stack

    for prompt, upper in (
        ("black strapless bodycon mini dress", "white seamless tube top"),
        ("black bodycon mini dress", "white seamless full-cup bra"),
    ):
        request = OutfitRequest(prompt=prompt)
        plan = plan_outfit_stack(request, template_catalog)
        _, added = ensure_foundation(plan, request, template_catalog, [], depicts_adult=True, color="white")
        assert added[0] == upper, (prompt, added)
