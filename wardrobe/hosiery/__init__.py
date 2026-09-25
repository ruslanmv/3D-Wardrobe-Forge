"""Hosiery and suspenders: stockings, belts, straps, hardware and the reveal.

One fit model. The stockings are fitted like any legwear and then *publish*
their top band (``contract.FittedStockingTop``); the straps and their hardware
are built from it, and the outer hem is solved against it. Nothing downstream
recomputes where a stocking top is. See docs/HOSIERY.md.

Kept import-light on purpose: the domain models import ``options`` from here.
"""
