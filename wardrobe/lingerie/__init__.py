"""Lingerie built the way lingerie is built: pattern blocks on measured landmarks.

The haul garments (``procedural._haul_sections``) make a bra, briefs and a
one-piece out of one lofted band each, re-cut at the edges. That passes the
clearance check and still is not a bra: no cups, no gore, no crotch, round
cords for straps. This package is the replacement, phase by phase, per
``docs/LINGERIE_UPGRADE_PLAN.md``. It is additive: the block kinds below are
new procedural kinds, chosen only by templates that name them, and every v1
garment keeps its code path byte for byte.
"""

#: Procedural kinds built from pattern blocks rather than bands.
LINGERIE_KINDS = frozenset({"brief-block", "bra-block", "bikini-block", "bodysuit-block"})

__all__ = ["LINGERIE_KINDS"]
