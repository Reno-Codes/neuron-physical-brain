# Experiment 63 — compiler-generated XOR MVP (CLOSED — OP abort)

Experiments 1-62 were not modified. Frozen `xor_model.npz`. Not silicon.

**Status: TECHNOLOGY BOUNDARY (single-diode network OP)**
**Decision C — SIMPLE SUPERDIODE OP ABORTS IN THE 4-ReLU NETLIST**

The compiler did emit Architecture A artifacts under `physical_design/xor_2_4_1/`. It also refused an unsupported `tanh` hidden activation. SPICE OP then aborted on every XOR vector:

```
doAnalyses: OP: Timestep too small; trouble with xh1d:d_1n4148_1-instance d.xh1d.d1
```

During the failed OP, `i(Vdd)` was on the order of 77 A — unphysical rail current from four ReLU amplifiers sitting at −15 V (all hidden pre-activations are negative on `[0,0]`).

Isolated single-diode ReLU still stands (Experiment 62). The network-scale failure is saturation of the simple superdiode, not a weight error and not a Python correction.

## Next experiment

Experiment 64: same documented 1N4148, two-diode anti-saturation precision rectifier, then recompile XOR.
