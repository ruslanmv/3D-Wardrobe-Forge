"""BS1. ``GET /v1/body-surface/profiles``: the body-surface profiles this server offers.

Ids, titles, capabilities and region names only — never a template, its field, a path or its
provenance, which stay on the server. A client sends one of these ids as ``bodySurface.profileId``
on a job; the server decides the rest.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from apps.api.admin import AdminDep
from apps.api.grants import GrantDep
from wardrobe.body_surface.library import library_at
from wardrobe.config import Settings, get_settings
from wardrobe.vrm import body_detail

router = APIRouter(tags=["body-surface"])


@router.get("/body-surface/profiles")
async def list_profiles(settings: Settings = Depends(get_settings)) -> dict:
    library = library_at(str(settings.body_surface_root_path))
    return {"version": 1, "adultEnabled": settings.wardrobe_adult_body_surface, "profiles": library.public()}


def _kind(name: str) -> str:
    """An extra's family, from its name: what a client groups it under when she is asked."""
    for prefix, kind in (("tan-", "tan lines"), ("tattoo-", "tattoo"), ("piercings-", "piercings"),
                         ("writing-", "writing"), ("kisses-", "marks")):
        if name.startswith(prefix):
            return kind
    return "marks" if name in {"love-bites", "spanked"} else "decoration"


@router.get("/body-surface/catalog")
async def body_catalog(admin: AdminDep, grant: GrantDep) -> dict:
    """BD21. Every bare-body preset, state and extra, named and described, for a client.

    Why. A companion holding a read grant lists her bare looks (``WardrobeLook.body`` says which
    preset, states and extras each one has), but a name alone ("pumped-open", "piercings-labia")
    tells the conversation nothing. Here is what each one *is*: the label and the ``body`` line —
    her body in that state, in the second person — the same lines the skin pack carries. With it,
    the client tells her what her look can show and which other look carries what she is asked for,
    without opening a file or keeping a second copy of these lists in sync.

    Private: the lines describe her body explicitly, so only an admin session or a valid read grant
    reads them (any grant: the catalogue names no avatar and holds no file). Read-only; nothing here
    paints, builds or unlocks anything — a bare look still passes every gate when it is made.
    """
    if admin is None and grant is None:
        raise HTTPException(status_code=403, detail="the body catalogue needs an admin session or a grant")
    presets = body_detail.load_presets()
    states = body_detail.load_states()
    extras = body_detail.load_extras()
    return {
        "version": 1,
        "presets": {n: {"label": p.get("label") or n, "hair": p.get("hair")} for n, p in presets.items()},
        "states": {n: {"label": s.get("label") or n, "body": s.get("body")} for n, s in states.items()},
        "extras": {
            name: {"label": e.get("label") or name, "body": e.get("body"), "kind": _kind(name)}
            for name, e in extras.items()
        },
    }
