"""Shared target definitions.

Targets package already-generated artifacts for a consuming application. They
must not perform fitting, skinning, provider calls, or VRM mutation.
"""

from __future__ import annotations

from enum import StrEnum


class TargetName(StrEnum):
    YOURFRIEND = "yourfriend"
    GENERIC = "generic"


__all__ = ["TargetName"]
