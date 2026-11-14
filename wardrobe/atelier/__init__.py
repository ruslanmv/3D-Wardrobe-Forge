"""AA. Orders for adult clothes the catalogue did not list as their own cards.

See docs/ADULT_ATELIER.md. A card is a template that owns its cut. An order that
needs a shape Forge cannot build yet stays unbuilt, and is not given a card.
"""

from wardrobe.atelier.orders import ORDERS, built_orders, report

__all__ = ["ORDERS", "built_orders", "report"]
