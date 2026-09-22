"""API configuration.

Configuration lives in :mod:`wardrobe.config` so the worker and the CLI share
it; this module re-exports it for the API's own imports.
"""

from wardrobe.config import REPO_ROOT, Settings, get_settings, settings

__all__ = ["Settings", "get_settings", "settings", "REPO_ROOT"]
