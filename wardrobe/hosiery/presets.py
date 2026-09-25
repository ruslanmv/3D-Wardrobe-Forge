"""Named hosiery looks: a prompt plus the hosiery, belt and reveal blocks that make it.

A preset is only a shorthand for a request someone could write out in full. It
fills the blocks a request leaves empty and never overrides one it sets, so
``{"preset": "glimpse_black", "reveal": {"level": "discreet"}}`` is the glimpse
look made discreet. It grants nothing: every garment in a preset is planned and
gated exactly as if it had been typed (the suspender belt is underwear, the
sheer stockings expose the body).

``classic_black_mini_dress`` is the reference look: a black mini dress over a
black classic belt it hides, flat black straps with silver clips, and sheer 20
denier stockings with wide opaque tops and a darker rolled edge. It shows its
tops when she sits (glimpse).
"""

from __future__ import annotations

PRESETS: dict[str, dict] = {
    "classic_black_mini_dress": {
        "title": "Classic black mini dress",
        "prompt": "black bodycon mini dress",
        "hosiery": {"type": "sheer", "denier": 20, "color": "black", "topStyle": "wide", "rolledEdge": True},
        "suspenderBelt": {"style": "classic", "color": "black", "strapCount": 4,
                          "hardware": {"color": "silver"}, "visibility": "hidden_under_skirt"},
        "reveal": {"level": "glimpse"},
    },
    "discreet_black": {
        "title": "Discreet",
        "prompt": "black knee-length pencil skirt + white fitted blouse",
        "hosiery": {"type": "sheer", "denier": 20, "color": "black", "topStyle": "plain"},
        "suspenderBelt": {"style": "classic", "color": "black", "hardware": {"color": "silver"}},
        "reveal": {"level": "discreet"},
    },
    "glimpse_black": {
        "title": "Glimpse",
        "prompt": "black mini skirt + black fitted top",
        "hosiery": {"type": "sheer", "denier": 15, "color": "black", "topStyle": "wide"},
        "suspenderBelt": {"style": "classic", "color": "black", "hardware": {"color": "silver"}},
        "reveal": {"level": "glimpse"},
    },
    "statement_black": {
        "title": "Statement",
        "prompt": "black bodycon mini dress",
        "hosiery": {"type": "sheer", "denier": 20, "color": "black", "topStyle": "wide"},
        "suspenderBelt": {"style": "classic", "color": "black", "strapCount": 4,
                          "hardware": {"color": "silver"}, "visibility": "straps_only"},
        "reveal": {"level": "statement"},
    },
    "vintage_seamed": {
        "title": "Vintage seamed",
        "prompt": "black pencil skirt + white fitted blouse",
        "hosiery": {"type": "seamed", "denier": 15, "color": "black", "topStyle": "wide",
                    "backSeam": {"enabled": True}},
        "suspenderBelt": {"style": "high_waisted", "color": "black", "strapCount": 6,
                          "hardware": {"color": "gold"}},
        "reveal": {"level": "discreet"},
    },
    "fishnet_black": {
        "title": "Fishnet",
        "prompt": "black mini skirt + black fitted top",
        "hosiery": {"type": "fishnet", "color": "black", "topStyle": "plain"},
        "suspenderBelt": {"style": "classic", "color": "black", "hardware": {"color": "black"}},
        "reveal": {"level": "glimpse"},
    },
}

#: The request blocks a preset may fill.
BLOCKS = ("hosiery", "suspenderBelt", "reveal")


def expand(request):
    """``request`` with its preset's blocks filled in where it left them empty.

    The prompt is the preset's only when the request's prompt *is* the preset's
    name: a client that sends ``{"preset": "fishnet_black", "prompt": "fishnet_black"}``
    gets the whole look; one that sends its own prompt keeps it.
    """
    name = getattr(request, "preset", None)
    if not name:
        return request
    preset = PRESETS.get(name)
    if preset is None:
        from wardrobe.errors import PlanningError

        raise PlanningError(f"unknown hosiery preset {name!r}; known: {sorted(PRESETS)}")
    from wardrobe.hosiery.options import HosieryOptions, RevealOptions, SuspenderBeltOptions

    update: dict = {}
    for block, model, field in (("hosiery", HosieryOptions, "hosiery"),
                                ("suspenderBelt", SuspenderBeltOptions, "suspender_belt"),
                                ("reveal", RevealOptions, "reveal")):
        if getattr(request, field) is None and block in preset:
            update[field] = model.model_validate(preset[block])
    if request.prompt.strip().lower() in {name, preset["title"].lower()}:
        update["prompt"] = preset["prompt"]
    return request.model_copy(update=update)


def catalogue() -> list[dict]:
    """The presets as the Studio and ``/v1/vocabulary`` list them."""
    return [{"id": name, **preset} for name, preset in PRESETS.items()]


__all__ = ["BLOCKS", "PRESETS", "catalogue", "expand"]
