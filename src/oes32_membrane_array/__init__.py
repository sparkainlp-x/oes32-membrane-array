"""Scalable array composition for fixed-width OES32 membrane cells."""

from .core import (
    MAX_CHANNELS,
    ArrayAuditEvent,
    ArrayMembrane,
    ArrayResult,
    ArrayState,
    array_boundary_payload,
    array_calibration_payload,
    validate_channel_count,
    vector_n,
)

__all__ = [
    "MAX_CHANNELS",
    "ArrayAuditEvent",
    "ArrayMembrane",
    "ArrayResult",
    "ArrayState",
    "array_boundary_payload",
    "array_calibration_payload",
    "validate_channel_count",
    "vector_n",
]

__version__ = "0.1.0"
