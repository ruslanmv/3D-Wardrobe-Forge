"""Prompt -> a layered outfit: which garments, in which order next to the body.

"Black lace bralette + matching briefs under a sheer fitted mini dress" is three
garments, and the order they go on is not the order they were written: the
briefs are next to the body whatever the sentence says. So the prompt is split
into garments, each planned on its own by :func:`plan_outfit`, and each placed
by what it *is*:

    1 foundation   underwear, swimwear          next to the body
    2 legwear      stockings                    over the foundation, under skirts
    3 main         tops, skirts, trousers
    4 one-piece    dresses, jumpsuits, nightwear
    5 outer        jackets, cardigans, coats
    6 shoes

A prompt that names one garment plans exactly as before — one plan, no layers —
so nothing that worked changes. A split only happens when every piece names a
garment: "a dress with pockets" is one dress, not a dress and some pockets.
"""

from __future__ import annotations

import re

from wardrobe.domain.garments import GarmentTemplate, TemplateCatalog
from wardrobe.domain.looks import OutfitPlan, OutfitRequest
from wardrobe.hosiery import planning as hosiery_planning
from wardrobe.hosiery import presets as hosiery_presets
from wardrobe.materials.finishes import FINISH_KEYWORDS, OPACITY_KEYWORDS, PATTERN_KEYWORDS
from wardrobe.pipeline.plan_outfit import parse_prompt, plan_outfit
from wardrobe.vrm.garments import KIND_REGIONS

#: (rank, role) by what a garment is.
FOUNDATION = (1, "foundation")
#: S2. What a skirt is worn over. Innermost like a foundation, so it is fitted first
#: and the skirt clears it, but not a foundation: it is not underwear, it does not
#: decide what of her own clothes comes off, and it does not make a job fail where
#: her avatar has no body under her clothes (prepare_base_body keeps them instead).
LINER = (1, "liner")
LEGWEAR = (2, "legwear")
MAIN = (3, "main")
ONE_PIECE = (4, "one-piece")
OUTER = (5, "outer")
SHOES = (6, "shoes")

_CONNECTORS = re.compile(
    r"\s*(?:\+|;|\bunderneath\b|\bunder\b|\bbeneath\b|\bover\b|\bon top of\b|\bwith\b|\bplus\b|"
    r"\band(?=\s+(?:an?|the|matching)\b))\s*",
    re.IGNORECASE,
)
_ARTICLE = re.compile(r"^(?:an?|the)\s+", re.IGNORECASE)

#: Overrides a layered request applies to its outermost garment only (see ``plan_outfit_stack``).
_OVERRIDES = ("color", "silhouette", "hem", "finish", "pattern", "opacity", "coverage", "straps", "neckline")


def layer_of(template: GarmentTemplate | None, category: str) -> tuple[int, str]:
    """Where a garment goes in the stack, from its category and its shape."""
    if category in {"underwear", "swimwear"}:
        return FOUNDATION
    if category == "legwear":
        return LEGWEAR
    if category == "shoes":
        return SHOES
    kind = template.procedural_kind if template is not None else category
    if kind == "slip-shorts":
        return LINER
    if kind in {"jacket", "cropped-jacket"}:
        return OUTER
    if KIND_REGIONS.get(kind) == frozenset({"upper", "lower"}):
        return ONE_PIECE
    return MAIN


def split_prompt(prompt: str) -> list[str]:
    """The garments a prompt names, as separate prompts; one element when it names one."""
    pieces = [_ARTICLE.sub("", piece.strip(" ,.")) for piece in _CONNECTORS.split(prompt)]
    pieces = [piece for piece in pieces if piece]
    merged: list[str] = []
    for piece in pieces:
        if parse_prompt(piece).category is None and merged:
            merged[-1] = f"{merged[-1]} {piece}"  # "with pockets" belongs to the garment before it
        else:
            merged.append(piece)
    if len(merged) < 2 or any(parse_prompt(piece).category is None for piece in merged):
        return [prompt]
    return _carry_matching(merged)


def _carry_matching(pieces: list[str]) -> list[str]:
    """"Matching briefs" take the colour and pattern of the garment before them."""
    carried: list[str] = []
    for piece in pieces:
        if re.search(r"\bmatching\b", piece, re.IGNORECASE) and carried:
            source = parse_prompt(carried[-1])
            words = []
            if source.color_name and parse_prompt(piece).color_name is None:
                words.append(source.color_name)
            target = parse_prompt(piece)
            if source.pattern and target.pattern is None:
                words.append(PATTERN_KEYWORDS[source.pattern][0])
            # The fabric too: "burgundy mesh bralette + matching briefs" are both mesh.
            if source.opacity is not None and target.opacity is None:
                words.append(_word_for(OPACITY_KEYWORDS, source.opacity, carried[-1]))
            if source.finish and target.finish is None:
                words.append(_word_for(FINISH_KEYWORDS, source.finish, carried[-1]))
            # The word has done its job; left in, it matches the "matching set"
            # template and turns a pair of briefs into a whole lingerie set.
            piece = re.sub(r"\bmatching\s*", "", piece, flags=re.IGNORECASE).strip()
            if words:
                piece = f"{' '.join(words)} {piece}"
        carried.append(piece)
    return carried


def _word_for(table: dict, key, text: str) -> str:
    """The word from ``table[key]`` that ``text`` actually used, so the carried word is the same one."""
    for word in sorted(table[key], key=len, reverse=True):
        if re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text, re.IGNORECASE):
            return word
    return table[key][0]


def plan_outfit_stack(
    request: OutfitRequest, catalog: TemplateCatalog, *, beneath: list[OutfitRequest] | tuple = ()
) -> OutfitPlan:
    """One plan, or a layered plan whose ``layers`` are its garments, inner first.

    ``beneath`` adds garments the pipeline puts under the request's own (a
    foundation, a skirt liner). They are added after the request is split into
    its garments and its overrides placed: passing them as extra ``layers``
    instead made "a tee + a skirt" one layer and lost the tee (S2).
    """
    request = hosiery_presets.expand(request)
    return hosiery_planning.apply(_plan_stack(request, catalog, list(beneath)), request, catalog)


def _plan_stack(request: OutfitRequest, catalog: TemplateCatalog, beneath: list[OutfitRequest]) -> OutfitPlan:
    if request.layers:
        requests = [layer.model_copy(update={"layers": None}) for layer in request.layers]
    else:
        pieces = split_prompt(request.prompt)
        if len(pieces) == 1 and not beneath:
            return _placed(plan_outfit(request, catalog), catalog)
        if len(pieces) == 1:
            pieces = [request.prompt]
        requests = [OutfitRequest(prompt=piece, mode=request.mode) for piece in pieces]
        # The request's explicit choices (the Studio's controls) are about the
        # garment on top — the one the viewer sees — not the ones beneath it.
        outermost = max(range(len(requests)), key=lambda i: _rank(requests[i], catalog))
        chosen = {key: getattr(request, key) for key in _OVERRIDES if getattr(request, key) is not None}
        requests[outermost] = requests[outermost].model_copy(update=chosen)
    requests = [layer.model_copy(update={"layers": None}) for layer in beneath] + requests

    plans = sorted((_placed(plan_outfit(r, catalog), catalog) for r in requests), key=lambda p: p.layer)
    if len(plans) == 1:
        return plans[0]
    return _stack(plans)


def _rank(request: OutfitRequest, catalog: TemplateCatalog) -> int:
    return _placed(plan_outfit(request, catalog), catalog).layer


def _placed(plan: OutfitPlan, catalog: TemplateCatalog) -> OutfitPlan:
    template = catalog.get(plan.template_id) if plan.template_id else None
    rank, role = layer_of(template, plan.category)
    return plan.model_copy(update={"layer": rank, "role": role})


def _stack(plans: list[OutfitPlan]) -> OutfitPlan:
    outer = plans[-1]
    notes = [note for plan in plans for note in plan.notes]
    return outer.model_copy(
        update={
            "name": " + ".join(plan.name for plan in plans)[:100],
            "layers": plans,
            "requires_adult": any(plan.requires_adult for plan in plans),
            "keywords": sorted({word for plan in plans for word in plan.keywords}),
            "confidence": min(plan.confidence for plan in plans),
            "notes": list(dict.fromkeys(notes)),
        }
    )


__all__ = ["layer_of", "plan_outfit_stack", "split_prompt"]
