"""Backward-compatible imports for the canonical schema module.

New code must import contracts from :mod:`privacy_proxy.schemas`.  This module
defines no Pydantic models, preventing a second incompatible class hierarchy.
"""

from privacy_proxy.schemas import (
    DetectedPII,
    DetectionTier,
    EntityType,
    ParsedRequest,
    ProxyContext,
    TextSegment,
    UserContext,
)

__all__ = [
    "DetectedPII",
    "DetectionTier",
    "EntityType",
    "ParsedRequest",
    "ProxyContext",
    "TextSegment",
    "UserContext",
]
