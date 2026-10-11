"""Authorized, atomic arrays composed from fixed-width OES32 membrane cells."""

from __future__ import annotations

import json
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from math import isfinite
from typing import TypeAlias

from oes32_membrane_shield import (
    FOLD8_RINGS,
    MU_TABLE,
    WIDTH,
    Action,
    AuthorizationError,
    CapabilityVerifier,
    LoopDenied,
    Role,
    Sector,
    SignedCapability,
)

MAX_CHANNELS = 65_536
SCHEMA = "oes32-membrane-array/v1"
FloatVector: TypeAlias = tuple[float, ...]


def validate_channel_count(channels: int) -> int:
    """Require a positive, bounded multiple of the upstream 32-slot cell width."""
    if (
        not isinstance(channels, int)
        or isinstance(channels, bool)
        or channels < WIDTH
        or channels > MAX_CHANNELS
        or channels % WIDTH != 0
    ):
        raise LoopDenied(
            f"channels must be a multiple of {WIDTH} between {WIDTH} and {MAX_CHANNELS}"
        )
    return channels


def vector_n(values: Iterable[float], channels: int, name: str = "vector") -> FloatVector:
    """Coerce a finite vector whose length matches the configured array."""
    validate_channel_count(channels)
    try:
        result = tuple(float(value) for value in values)
    except (TypeError, ValueError, OverflowError) as exc:
        raise LoopDenied(f"{name} must contain real numbers") from exc
    if len(result) != channels:
        raise LoopDenied(f"{name} must contain exactly {channels} slots")
    if not all(isfinite(value) for value in result):
        raise LoopDenied(f"{name} contains NaN or infinity")
    return result


def array_boundary_payload(boundary: Iterable[float], channels: int | None = None) -> bytes:
    """Canonical capability payload binding the complete array and its size."""
    if channels is None:
        try:
            values = tuple(float(value) for value in boundary)
        except (TypeError, ValueError, OverflowError) as exc:
            raise LoopDenied("boundary must contain real numbers") from exc
        channels = len(values)
    else:
        values = vector_n(boundary, channels, "boundary")
    values = vector_n(values, channels, "boundary")
    return json.dumps(
        {"boundary": values, "channels": channels, "schema": SCHEMA},
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def array_calibration_payload(reference: ArrayState) -> bytes:
    """Canonical payload for dual approval of a complete array reference."""
    if not isinstance(reference, ArrayState):
        raise TypeError("reference must be an ArrayState")
    return json.dumps(
        {
            "bulk": reference.bulk,
            "boundary": reference.boundary,
            "channels": reference.channels,
            "schema": SCHEMA,
        },
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


@dataclass(frozen=True)
class ArrayState:
    """Immutable full-array bulk and boundary state, stored as flat vectors."""

    bulk: FloatVector
    boundary: FloatVector

    def __post_init__(self) -> None:
        try:
            bulk = tuple(float(value) for value in self.bulk)
            boundary = tuple(float(value) for value in self.boundary)
        except (TypeError, ValueError, OverflowError) as exc:
            raise LoopDenied("state vectors must contain real numbers") from exc
        if len(bulk) != len(boundary):
            raise LoopDenied("bulk and boundary must have equal channel counts")
        channels = validate_channel_count(len(bulk))
        object.__setattr__(self, "bulk", vector_n(bulk, channels, "bulk"))
        object.__setattr__(self, "boundary", vector_n(boundary, channels, "boundary"))

    @property
    def channels(self) -> int:
        return len(self.bulk)

    @property
    def blocks(self) -> int:
        return self.channels // WIDTH

    @classmethod
    def zeros(cls, channels: int) -> ArrayState:
        validate_channel_count(channels)
        zero = (0.0,) * channels
        return cls(zero, zero)

    @classmethod
    def create(cls, bulk: Iterable[float], boundary: Iterable[float]) -> ArrayState:
        return cls(tuple(bulk), tuple(boundary))


@dataclass(frozen=True)
class ArrayResult:
    """Outcome of one all-or-nothing array update."""

    cycle: int
    admitted: bool
    reason: str
    residual: float
    state: ArrayState
    block_index: int | None = None


@dataclass(frozen=True)
class ArrayAuditEvent:
    """Non-sensitive metadata for an array authorization/state decision."""

    timestamp_ns: int
    role: str
    subject: str
    request_id: str
    admitted: bool
    reason: str
    residual: float
    block_index: int | None


def _sector_valid(delta: Sequence[float], sector: Sector, epsilon: float) -> bool:
    """Apply the upstream symmetry rule independently inside one 32-slot cell."""
    if sector is Sector.ANY:
        return True
    if sector is Sector.EVEN:
        return all(abs(delta[i] - delta[MU_TABLE[i]]) <= epsilon for i in range(WIDTH // 2))
    if sector is Sector.ODD:
        return all(abs(delta[i] + delta[MU_TABLE[i]]) <= epsilon for i in range(WIDTH // 2))
    if sector is Sector.FOLD8:
        return all(
            abs(delta[ring[index]] - delta[ring[(index + 1) % 8]]) <= epsilon
            for ring in FOLD8_RINGS
            for index in range(8)
        )
    raise ValueError("unsupported sector")


def _residual(a: Sequence[float], b: Sequence[float]) -> float:
    return max((abs(x - y) for x, y in zip(a, b, strict=True)), default=0.0)


class ArrayMembrane:
    """A fixed-width OES32 membrane array with one global atomic commit boundary.

    Each adjacent group of 32 slots applies the upstream residual and symmetry
    rules independently. Authorization is bound to the entire flattened frame,
    so blocks cannot be individually substituted or partially authorized.
    """

    def __init__(
        self,
        verifier: CapabilityVerifier,
        reference: ArrayState | None = None,
        *,
        channels: int | None = None,
        tau: float = 0.08,
        sector: Sector = Sector.ANY,
        epsilon: float = 1e-9,
        audit_size: int = 1024,
    ) -> None:
        if not isinstance(verifier, CapabilityVerifier):
            raise ValueError("verifier must be a CapabilityVerifier")
        if not isinstance(sector, Sector):
            raise ValueError("sector must be a Sector value")
        if not isfinite(float(tau)) or tau < 0:
            raise ValueError("tau must be finite and non-negative")
        if not isfinite(float(epsilon)) or epsilon < 0:
            raise ValueError("epsilon must be finite and non-negative")
        if not isinstance(audit_size, int) or isinstance(audit_size, bool) or audit_size < 1:
            raise ValueError("audit_size must be a positive integer")
        if channels is None:
            channels = reference.channels if reference is not None else WIDTH
        if reference is not None:
            if not isinstance(reference, ArrayState):
                raise ValueError("reference must be an ArrayState")
            if channels != reference.channels:
                raise ValueError("channels must match the reference state")
        assert channels is not None
        self.channels = validate_channel_count(channels)
        self.blocks = self.channels // WIDTH
        self._verifier = verifier
        self.reference = reference or ArrayState.zeros(self.channels)
        self.state = self.reference
        self.tau = float(tau)
        self.sector = sector
        self.epsilon = float(epsilon)
        self.cycle = 0
        self.latched = False
        self._audit_log: list[ArrayAuditEvent | None] = [None] * audit_size
        self._audit_ptr = 0

    @property
    def audit_size(self) -> int:
        return len(self._audit_log)

    def audit_events(self) -> tuple[ArrayAuditEvent, ...]:
        events = [event for event in self._audit_log if event is not None]
        if len(events) < self.audit_size or self._audit_ptr == 0:
            return tuple(events)
        return tuple(self._audit_log[self._audit_ptr :] + self._audit_log[: self._audit_ptr])  # type: ignore[arg-type]

    def _record(
        self,
        capability: SignedCapability,
        admitted: bool,
        reason: str,
        residual: float,
        block_index: int | None = None,
    ) -> None:
        self._audit_log[self._audit_ptr] = ArrayAuditEvent(
            time.perf_counter_ns(),
            capability.role.value,
            capability.subject,
            capability.request_id,
            admitted,
            reason,
            residual,
            block_index,
        )
        self._audit_ptr = (self._audit_ptr + 1) % self.audit_size

    def reset(self, authorization: SignedCapability) -> None:
        """Reset the global latch only with a guardian write capability."""
        try:
            verified = self._verifier.verify(
                authorization, action=Action.WRITE, role=Role.GARDIEN, payload=b"reset"
            )
        except AuthorizationError as exc:
            raise LoopDenied(str(exc)) from exc
        self.state = self.reference
        self.latched = False
        self._record(verified, True, "reset", 0.0)

    def observe(self, authorization: SignedCapability) -> ArrayState:
        """Return current array state after verifying observer authorization."""
        try:
            verified = self._verifier.verify(
                authorization, action=Action.OBSERVE, role=Role.OBSERVATEUR
            )
        except AuthorizationError as exc:
            raise LoopDenied(str(exc)) from exc
        self._record(verified, True, "observe success", 0.0)
        return self.state

    def calibrate(
        self,
        calibrator_approval: SignedCapability,
        guardian_approval: SignedCapability,
        new_reference: ArrayState,
    ) -> None:
        """Replace the complete reference using independent dual approval."""
        if not isinstance(new_reference, ArrayState):
            raise TypeError("new_reference must be an ArrayState")
        if new_reference.channels != self.channels:
            raise LoopDenied("calibration channel count does not match membrane")
        if not isinstance(calibrator_approval, SignedCapability) or not isinstance(
            guardian_approval, SignedCapability
        ):
            raise LoopDenied("calibration approvals have invalid type")
        if {calibrator_approval.role, guardian_approval.role} != {
            Role.CALIBRATEUR,
            Role.GARDIEN,
        }:
            raise LoopDenied("calibration requires Calibrateur and Gardien approvals")
        try:
            approvals = self._verifier.verify_independent_pair(
                calibrator_approval,
                guardian_approval,
                action=Action.CALIBRATE,
                payload=array_calibration_payload(new_reference),
            )
        except AuthorizationError as exc:
            raise LoopDenied(str(exc)) from exc
        self.reference = new_reference
        self.state = new_reference
        self.latched = False
        self._record(approvals[0], True, "dual-control calibration updated", 0.0)
        self._record(approvals[1], True, "dual-control calibration updated", 0.0)

    def request_flip(
        self,
        authorization: SignedCapability,
        new_boundary: Iterable[float],
        *,
        syndrome_ok: bool = True,
        logical_ok: bool = True,
    ) -> ArrayResult:
        """Validate all cells, then commit once; any failure preserves every cell."""
        self.cycle += 1
        try:
            boundary = vector_n(new_boundary, self.channels, "new_boundary")
            verified = self._verifier.verify(
                authorization,
                action=Action.WRITE,
                role=authorization.role,
                payload=array_boundary_payload(boundary, self.channels),
            )
        except (AuthorizationError, LoopDenied, AttributeError) as exc:
            return ArrayResult(self.cycle, False, str(exc), float("inf"), self.state)
        if verified.role not in (Role.DECODEUR, Role.GARDIEN):
            reason = f"role {verified.role.value} denied write access"
            self._record(verified, False, reason, float("inf"))
            return ArrayResult(self.cycle, False, reason, float("inf"), self.state)
        if self.latched:
            self._record(verified, False, "array is latched", float("inf"))
            return ArrayResult(self.cycle, False, "array is latched", float("inf"), self.state)
        if not syndrome_ok:
            self._record(verified, False, "syndrome rejected", 0.0)
            return ArrayResult(self.cycle, False, "syndrome rejected", 0.0, self.state)
        if not logical_ok:
            self._record(verified, False, "logical check rejected", 0.0)
            return ArrayResult(self.cycle, False, "logical check rejected", 0.0, self.state)

        delta_boundary = tuple(
            new_value - old_value
            for new_value, old_value in zip(boundary, self.state.boundary, strict=True)
        )
        new_bulk = tuple(
            old_value + delta
            for old_value, delta in zip(self.state.bulk, delta_boundary, strict=True)
        )
        block_residuals: list[float] = []
        for start in range(0, self.channels, WIDTH):
            stop = start + WIDTH
            block_residuals.append(
                max(
                    _residual(boundary[start:stop], self.reference.boundary[start:stop]),
                    _residual(new_bulk[start:stop], self.reference.bulk[start:stop]),
                )
            )
        residual = max(block_residuals, default=0.0)
        worst_block = block_residuals.index(residual) if block_residuals else None
        if residual > self.tau:
            self.latched = True
            self._record(verified, False, "residual breach; array latched", residual, worst_block)
            return ArrayResult(
                self.cycle,
                False,
                "residual breach; array latched",
                residual,
                self.state,
                worst_block,
            )

        for block_index, start in enumerate(range(0, self.channels, WIDTH)):
            stop = start + WIDTH
            boundary_delta = tuple(
                x - y
                for x, y in zip(
                    boundary[start:stop], self.reference.boundary[start:stop], strict=True
                )
            )
            bulk_delta = tuple(
                x - y
                for x, y in zip(new_bulk[start:stop], self.reference.bulk[start:stop], strict=True)
            )
            if not _sector_valid(boundary_delta, self.sector, self.epsilon):
                reason = "boundary symmetry rejected"
                self._record(verified, False, reason, residual, block_index)
                return ArrayResult(self.cycle, False, reason, residual, self.state, block_index)
            if not _sector_valid(bulk_delta, self.sector, self.epsilon):
                reason = "bulk symmetry rejected"
                self._record(verified, False, reason, residual, block_index)
                return ArrayResult(self.cycle, False, reason, residual, self.state, block_index)

        self.state = ArrayState(new_bulk, boundary)
        self._record(verified, True, "admitted", residual)
        return ArrayResult(self.cycle, True, "admitted", residual, self.state, None)
