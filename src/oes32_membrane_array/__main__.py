"""Run a deterministic synthetic acceptance pass at several array sizes."""

from __future__ import annotations

from oes32_membrane_shield import Action, CapabilityIssuer, CapabilityVerifier, Role

from .core import ArrayMembrane, ArrayState, array_boundary_payload


def main() -> None:
    sizes = (32, 512, 1024, 2048, 4096, 8192, 16384, 65536)
    print("SYNTHETIC STRUCTURAL DEMO — not hardware performance or field evidence")
    print(f"{'slots':>8} {'32-slot cells':>14} {'accepted':>10} {'max residual':>14}")
    for channels in sizes:
        decoder = CapabilityIssuer.generate(
            f"decoder-{channels}", f"synthetic-demo-{channels}", Role.DECODEUR
        )
        verifier = CapabilityVerifier({decoder.key_id: decoder.authority_key()})
        membrane = ArrayMembrane(verifier, ArrayState.zeros(channels), tau=0.08)
        boundary = [0.0] * channels
        for block in range(channels // 32):
            boundary[block * 32] = 0.01
        capability = decoder.issue(
            Action.WRITE,
            array_boundary_payload(boundary, channels),
            request_id=f"scale-demo-{channels}",
        )
        result = membrane.request_flip(capability, boundary)
        print(
            f"{channels:>8} {channels // 32:>14} {str(result.admitted):>10} "
            f"{result.residual:>14.6f}"
        )
        if not result.admitted:
            raise SystemExit(f"synthetic update failed at {channels} channels: {result.reason}")
    print("\nEvery value above comes from a generated vector and one software state transition.")


if __name__ == "__main__":
    main()
