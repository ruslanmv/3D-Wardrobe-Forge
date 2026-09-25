"""Superseded by :mod:`wardrobe.pipeline.prepare_base_body`; kept so existing imports work.

The single-garment replacement stage became Base Body Prep: the strip plan is
decided for the whole outfit, the body under a garment is checked before it
comes off, and the stripped state is never stored. ``run`` is that stage.
"""

from __future__ import annotations

from wardrobe.pipeline.prepare_base_body import run

__all__ = ["run"]
