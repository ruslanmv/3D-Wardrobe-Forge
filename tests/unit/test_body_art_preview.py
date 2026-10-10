"""BA5. A look with a tattoo on her back is pictured from behind — by the web renderer only."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from wardrobe.body_art.contract import BodyArtRequest
from wardrobe.body_art.decorate import Outcome
from wardrobe.hosiery import previews
from wardrobe.materials.png import encode_png
from wardrobe.pipeline import render_preview

pytest.importorskip("PIL")


def _context(backend: str, applied: bool = True):
    warnings: list[str] = []
    outcome = Outcome(
        request=BodyArtRequest(design="tribal-wings-01", placement="upper-back"),
        rating="general",
        applied=applied,
    )
    return SimpleNamespace(
        record=SimpleNamespace(request=SimpleNamespace(options=SimpleNamespace(preview_backend=backend))),
        settings=SimpleNamespace(wardrobe_preview_backend="native"),
        output_bytes=b"vrm",
        preview_bytes=b"front",
        extra_previews={},
        body_art=[outcome],
        warn=warnings.append,
        warnings=warnings,
    )


@pytest.fixture
def web(monkeypatch):
    calls: list[list[dict]] = []
    picture = np.full((40, 30, 4), 255, dtype=np.uint8)

    def render_web(views):
        calls.append(views)
        return {view["name"]: encode_png(picture) for view in views}

    monkeypatch.setattr(previews, "web_available", lambda: True)
    monkeypatch.setattr(previews, "render_web", render_web)
    return calls


def test_the_back_view_becomes_the_preview_and_the_front_is_kept(web):
    context = _context("web")
    render_preview.body_art_views(context)
    assert web and web[0][0]["yaw"] == 180 and web[0][0]["vrm"] == b"vrm"
    assert context.preview_bytes[:4] == b"RIFF"  # webp
    assert context.extra_previews["preview-back.webp"] == context.preview_bytes
    assert context.extra_previews["preview-front.webp"] == b"front"
    assert "thumb.webp" in context.extra_previews
    assert not context.warnings


def test_without_the_web_backend_the_front_stays_and_the_report_says_so(web):
    context = _context("native")
    render_preview.body_art_views(context)
    assert not web  # the flat rasteriser would paint the decal as a block of ink colour
    assert context.preview_bytes == b"front" and not context.extra_previews
    assert context.warnings == [render_preview.BACK_VIEW_MISSING]


def test_a_tattoo_that_was_not_applied_changes_no_picture(web):
    context = _context("web", applied=False)
    render_preview.body_art_views(context)
    assert not web and context.preview_bytes == b"front" and not context.warnings
