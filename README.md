# OES32 Membrane Array

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23307951.svg)](https://doi.org/10.5281/zenodo.23307951)

A small companion prototype that composes the existing **fixed 32-slot OES32 membrane contract** into larger arrays without changing the upstream `oes32-membrane-shield` API. It supports **32 through 65,536 channel slots**, always as a whole number of 32-slot cells; the included scale demonstration exercises 2,048, 4,096, 8,192, 16,384 and 65,536.

> This is a software state-machine prototype using generated numbers. It is not a physical membrane, sensor array, hardware implementation, field result, medical device, or performance benchmark.

## What changes at scale

The original [`oes32-membrane-shield`](https://github.com/sparkainlp-x/oes32-membrane-shield) remains a 32-slot API. This project treats that width as a **cell contract**: a 4,096-slot array consists of 128 independent 32-slot policy cells, and a 65,536-slot array consists of 2,048. Residual limits and symmetry rules restart at each cell boundary; the fixed OES32 cell definition is not stretched or reinterpreted.

A single external Ed25519 capability authorizes the complete flattened frame and includes the channel count in its signed payload. The array validates every cell before changing any state. If any cell fails, the update is rejected as one transaction, state remains unchanged, and a residual breach latches the array-wide circuit breaker. This avoids partially committing good cells when another cell fails.

Calibration similarly covers the full array and requires independent `CALIBRATEUR` and `GARDIEN` approvals. Private signing keys remain outside the membrane; this code uses the upstream public-key verifier and role model. Each cell's symmetry validator uses the upstream 32-slot tables and tolerances.

## Run the scale demonstration

Python 3.10+ is required. The package depends on the tagged upstream OES32 shield and its `cryptography` dependency.

```bash
python -m pip install -e .
python -m oes32_membrane_array
```

The demo applies one synthetic, authorized update at each size and reports slot count, 32-slot cell count, admission, and residual. Those columns demonstrate structural scale and a software decision only; no latency or throughput claim is made.

To run tests from a local checkout of both repositories without installing the upstream package separately:

```bash
PYTHONPATH=../oes32-membrane-shield/src:src python -m unittest discover -s tests -v
```

The test suite includes exact 32-slot behavior comparison against the upstream state machine, large-array transactions through 65,536 slots, all-or-nothing rejection of a bad cell, authorization payload binding, per-cell symmetry, dual approval, and guardian reset.

## Contract and limits

- Channel count must be a multiple of 32 and no greater than 65,536.
- The signed write payload contains the entire array frame. A capability for one channel count or vector cannot authorize another.
- Updates are evaluated against immutable reference bulk/boundary vectors. Bulk changes use the upstream rule: add each boundary delta to the corresponding current bulk value.
- Residual is the maximum component-wise deviation from the reference over all cells, equivalent to the maximum of the per-cell residuals.
- The whole array latches if any cell exceeds `tau`; reset requires a guardian capability.
- A configured symmetry sector is enforced independently within every consecutive 32-slot cell.
- Inputs and tests are synthetic. There is no measured channel hardware, real-world data, fault-injection campaign, deployment profile, or independent security review of this new composition layer.

This design is intentionally a **scale-out wrapper**, not a claim that more modeled slots carry more independent information or that a software array can be realized at the same size in hardware. The capacity counts are configuration counts only.

## License

AGPL-3.0-only, matching the current upstream membrane shield. See [LICENSE](LICENSE) for the full terms.

## Cite

Concept DOI (all versions): [10.5281/zenodo.23307951](https://doi.org/10.5281/zenodo.23307951). v0.1.0: [10.5281/zenodo.23307952](https://doi.org/10.5281/zenodo.23307952). See [CITATION.cff](CITATION.cff).
