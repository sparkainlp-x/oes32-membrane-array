# Assumptions and limits

- The existing OES32 shield is the normative 32-slot cell contract; its API and existing repositories are not modified.
- Larger channel arrays are consecutive 32-slot cells with identical per-cell residual and symmetry rules.
- A signed capability covers the complete vector and channel count. This prototype performs one verifier check for an all-array update, not one authority decision per cell.
- The commit is atomic in the Python object: validation completes for every cell before a new immutable state is assigned.
- A residual breach in any cell trips one array-wide latch. The result reports the cell containing the worst residual.
- Counts 2,048 through 65,536 demonstrate software representation, not physical feasibility, independent information, throughput, or performance.
- The only tested signals are deterministic generated values; no field, sensor, biological, medical, or quantum result is asserted.
