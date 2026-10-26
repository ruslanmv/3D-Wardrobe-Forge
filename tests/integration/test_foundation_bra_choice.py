"""Which bra Auto Foundation puts under an outfit (MG3, FC1, FC3).

Pinned because it is a design decision, not a fit detail: on an avatar Forge declares adult
the foundation is the tailored full-cup bra and briefs — the canonical white set, cups, straps
and all — under every outfit except a strapless one (FC3), where the full-cup bra's straps
would stand alone on her shoulders and the seamless tube top is used instead. Spaghetti straps
and open backs keep the full-cup bra: it is the bra the look is designed with, and replacing it
(FC4, proposed on its own branch) was declined. An avatar not declared adult gets clothes, not
underwear: the tube top and slip shorts, whatever the outfit.

Planning only: no geometry is built, so this runs in milliseconds and fails on any change to
the choice, including a change of name or colour.
"""

from __future__ import annotations

import pytest

from wardrobe.domain.looks import OutfitRequest
from wardrobe.pipeline.generate_garment import ensure_foundation
from wardrobe.pipeline.plan_outfit_stack import plan_outfit_stack

FULL_CUP = "white seamless full-cup bra"
TUBE_TOP = "white seamless tube top"
BRIEFS = "white seamless briefs"

OUTFITS = [
    # outfit, upper half on an adult-declared avatar
    ("black satin spaghetti strap open back bodycon mini dress", FULL_CUP),
    ("black spaghetti strap bodycon mini dress", FULL_CUP),
    ("black open back bodycon mini dress", FULL_CUP),
    ("black bodycon mini dress", FULL_CUP),
    ("white crop top + blue straight jeans", FULL_CUP),
    ("black strapless bodycon mini dress", TUBE_TOP),
]


def added(prompt: str, catalog, *, adult: bool) -> list[str]:
    request = OutfitRequest(prompt=prompt)
    plan = plan_outfit_stack(request, catalog)
    _, prompts = ensure_foundation(plan, request, catalog, [], depicts_adult=adult, color="white")
    return prompts


@pytest.mark.parametrize("prompt, upper", OUTFITS)
def test_an_adult_declared_avatar_keeps_the_full_cup_bra_unless_the_outfit_is_strapless(
    template_catalog, prompt, upper
):
    prompts = added(prompt, template_catalog, adult=True)
    assert prompts[0] == upper, (prompt, prompts)


@pytest.mark.parametrize("prompt", [p for p, _ in OUTFITS if "dress" in p])
def test_a_dress_gets_both_halves_and_the_lower_is_the_briefs(template_catalog, prompt):
    assert added(prompt, template_catalog, adult=True)[1:] == [BRIEFS]


@pytest.mark.parametrize("prompt", [p for p, _ in OUTFITS])
def test_an_avatar_not_declared_adult_gets_the_tube_top_whatever_the_outfit(template_catalog, prompt):
    assert added(prompt, template_catalog, adult=False)[0] == TUBE_TOP


def test_the_full_cup_bra_is_the_full_cup_template(template_catalog):
    """The prompt resolves to the canonical template, so the bra's geometry is the shipped one."""
    plan = plan_outfit_stack(OutfitRequest(prompt=FULL_CUP), template_catalog)
    assert plan.template_id == "under-bra-full-v2"
