# Physical AI MVP v1 — freeze provenance

Machine-generated hashes: `FROZEN_PROVENANCE.json`.

The validated compiler package is **read-only**. Hardware lives here:

`physical-ai/hardware/mvp_v1_xor_2_4_1/`

Neural topology, frozen weights, and compiled resistances come from
`physical-ai/physical_design/xor_2_4_1/` without silent edits.

Do not modify Experiments 1–67. Do not edit `W1`, `b1`, `W2`, `b2`.

SHA-256 of the frozen netlist:

`28dccd8121a1032d69a2b08633737db0b2f10c8996f68ed2271520ec58c3b9cb`  `netlist.cir`

SHA-256 of the frozen model:

`b7448b17347bbf64cce6a72e10ebfb623255a6278917d4349e54e02cc216bb6b`  `xor_model.npz`

Hardware revision **MVP-H1** adds only support circuitry and resistor *realization*:

- power connectors, decoupling, test points, input switches, a real 1.000 V reference
- 0.1% (or two-part E192) implementations of the **same** compiled ohms
- omission of the 1 pF SPICE-only capacitors (audit: output Δy = 0.0 V)

That is not a new neural architecture.
