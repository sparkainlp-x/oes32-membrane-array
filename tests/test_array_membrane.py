from __future__ import annotations

import math
import unittest

from oes32_membrane_shield import (
    Action,
    CapabilityIssuer,
    CapabilityVerifier,
    LoopDenied,
    MembraneShield,
    Role,
    Sector,
    boundary_payload,
)

from oes32_membrane_array import (
    ArrayMembrane,
    ArrayState,
    array_boundary_payload,
    array_calibration_payload,
    validate_channel_count,
)


def make_issuers() -> dict[Role, CapabilityIssuer]:
    return {
        Role.OBSERVATEUR: CapabilityIssuer.generate("observer-key", "observer", Role.OBSERVATEUR),
        Role.CALIBRATEUR: CapabilityIssuer.generate(
            "calibrator-key", "operator-a", Role.CALIBRATEUR
        ),
        Role.DECODEUR: CapabilityIssuer.generate("decoder-key", "decoder", Role.DECODEUR),
        Role.GARDIEN: CapabilityIssuer.generate("guardian-key", "operator-b", Role.GARDIEN),
    }


def make_verifier(issuers: dict[Role, CapabilityIssuer]) -> CapabilityVerifier:
    return CapabilityVerifier(
        {issuer.key_id: issuer.authority_key() for issuer in issuers.values()},
        clock=lambda: 1_000,
    )


class ArrayMembraneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.issuers = make_issuers()
        self.verifier = make_verifier(self.issuers)
        self.channels = 4096
        self.membrane = ArrayMembrane(self.verifier, channels=self.channels, tau=0.25)
        self.decoder = self.issuers[Role.DECODEUR]
        self.guardian = self.issuers[Role.GARDIEN]
        self.calibrator = self.issuers[Role.CALIBRATEUR]

    def write_capability(self, boundary: list[float], request_id: str):
        return self.decoder.issue(
            Action.WRITE,
            array_boundary_payload(boundary, self.channels),
            now=1_000,
            request_id=request_id,
        )

    def test_channel_count_is_a_bounded_multiple_of_32(self) -> None:
        for count in (32, 512, 1024, 2048, 4096, 8192, 16384, 65536):
            self.assertEqual(validate_channel_count(count), count)
        for count in (0, 31, 33, 65_568, True):
            with self.assertRaises(LoopDenied):
                validate_channel_count(count)

    def test_scales_through_65536_slots_in_atomic_updates(self) -> None:
        for channels in (2048, 4096, 8192, 16384, 65536):
            with self.subTest(channels=channels):
                boundary = [0.0] * channels
                for block in range(channels // 32):
                    boundary[block * 32] = 0.01
                membrane = ArrayMembrane(self.verifier, channels=channels, tau=0.08)
                authorization = self.decoder.issue(
                    Action.WRITE,
                    array_boundary_payload(boundary, channels),
                    now=1_000,
                    request_id=f"scale-{channels}",
                )
                result = membrane.request_flip(authorization, boundary)
                self.assertTrue(result.admitted)
                self.assertEqual(result.state.channels, channels)
                self.assertEqual(result.state.blocks, channels // 32)
                self.assertEqual(result.state.boundary, tuple(boundary))

    def test_32_slot_result_matches_upstream_state_machine(self) -> None:
        issuer = self.decoder
        base_verifier = CapabilityVerifier(
            {issuer.key_id: issuer.authority_key()}, clock=lambda: 1_000
        )
        array_verifier = CapabilityVerifier(
            {issuer.key_id: issuer.authority_key()}, clock=lambda: 1_000
        )
        base = MembraneShield(base_verifier, tau=0.5, sector=Sector.ANY)
        array = ArrayMembrane(array_verifier, channels=32, tau=0.5, sector=Sector.ANY)
        proposal = [0.0] * 32
        proposal[7] = 0.125
        base_result = base.request_flip(
            issuer.issue(
                Action.WRITE,
                boundary_payload(proposal),
                now=1_000,
                request_id="base-32-write",
            ),
            proposal,
        )
        array_result = array.request_flip(
            issuer.issue(
                Action.WRITE,
                array_boundary_payload(proposal, 32),
                now=1_000,
                request_id="array-32-write",
            ),
            proposal,
        )
        self.assertEqual(array_result.admitted, base_result.admitted)
        self.assertEqual(array_result.residual, base_result.residual)
        self.assertEqual(array_result.state.bulk, base_result.state.bulk)
        self.assertEqual(array_result.state.boundary, base_result.state.boundary)

    def test_one_bad_cell_rejects_the_whole_array_and_identifies_it(self) -> None:
        proposal = [0.01] * self.channels
        bad_block = 73
        proposal[bad_block * 32 + 11] = 0.30
        result = self.membrane.request_flip(
            self.write_capability(proposal, "atomic-breach"), proposal
        )
        self.assertFalse(result.admitted)
        self.assertEqual(result.block_index, bad_block)
        self.assertTrue(self.membrane.latched)
        self.assertEqual(self.membrane.state, ArrayState.zeros(self.channels))
        self.assertIn("array latched", result.reason)

    def test_capability_binds_all_values_and_channel_count(self) -> None:
        approved = [0.0] * self.channels
        substituted = [0.0] * self.channels
        substituted[-1] = 0.01
        capability = self.write_capability(approved, "payload-binding")
        result = self.membrane.request_flip(capability, substituted)
        self.assertFalse(result.admitted)
        self.assertIn("payload mismatch", result.reason)
        self.assertEqual(self.membrane.state, ArrayState.zeros(self.channels))
        self.assertFalse(self.membrane.latched)

    def test_symmetry_is_restarted_inside_each_32_slot_cell(self) -> None:
        membrane = ArrayMembrane(self.verifier, channels=self.channels, tau=0.5, sector=Sector.EVEN)
        valid = [0.0] * self.channels
        valid[64] = valid[80] = 0.1  # local positions 0 and 16, cell 2
        first = membrane.request_flip(
            self.decoder.issue(
                Action.WRITE,
                array_boundary_payload(valid, self.channels),
                now=1_000,
                request_id="even-cell-valid",
            ),
            valid,
        )
        self.assertTrue(first.admitted)
        invalid = list(valid)
        invalid[96] = 0.1  # local position 0 in cell 3, partner 112 remains zero
        second = membrane.request_flip(
            self.decoder.issue(
                Action.WRITE,
                array_boundary_payload(invalid, self.channels),
                now=1_000,
                request_id="even-cell-invalid",
            ),
            invalid,
        )
        self.assertFalse(second.admitted)
        self.assertEqual(second.block_index, 3)
        self.assertEqual(membrane.state.boundary, tuple(valid))

    def test_dual_approval_calibrates_complete_array_and_unlatches(self) -> None:
        proposal = [0.5] + [0.0] * (self.channels - 1)
        rejected = self.membrane.request_flip(
            self.write_capability(proposal, "latch-before-calibration"), proposal
        )
        self.assertFalse(rejected.admitted)
        new_reference = ArrayState.create([0.1] * self.channels, [0.1] * self.channels)
        payload = array_calibration_payload(new_reference)
        calibrator_approval = self.calibrator.issue(
            Action.CALIBRATE, payload, now=1_000, request_id="array-calibrator"
        )
        guardian_approval = self.guardian.issue(
            Action.CALIBRATE, payload, now=1_000, request_id="array-guardian"
        )
        self.membrane.calibrate(calibrator_approval, guardian_approval, new_reference)
        self.assertFalse(self.membrane.latched)
        self.assertEqual(self.membrane.reference, new_reference)
        self.assertEqual(self.membrane.state, new_reference)

    def test_guardian_reset_returns_all_cells_to_reference(self) -> None:
        proposal = [0.5] + [0.0] * (self.channels - 1)
        self.membrane.request_flip(self.write_capability(proposal, "reset-latch"), proposal)
        reset = self.guardian.issue(Action.WRITE, b"reset", now=1_000, request_id="array-reset")
        self.membrane.reset(reset)
        self.assertFalse(self.membrane.latched)
        self.assertEqual(self.membrane.state, self.membrane.reference)
        self.assertEqual(self.membrane.audit_events()[-1].reason, "reset")

    def test_non_finite_or_wrong_length_frame_is_refused(self) -> None:
        for proposal in ([0.0] * 31, [math.nan] * self.channels):
            capability = self.decoder.issue(
                Action.WRITE,
                array_boundary_payload([0.0] * self.channels, self.channels),
                now=1_000,
                request_id=f"bad-{id(proposal)}",
            )
            result = self.membrane.request_flip(capability, proposal)
            self.assertFalse(result.admitted)
            self.assertEqual(self.membrane.state, ArrayState.zeros(self.channels))


if __name__ == "__main__":
    unittest.main()
