# Experiment 62 — documented precision-rectifier ReLU

Experiments 1-61 were not modified. Isolated ReLU. Not silicon.

**Status: DEMONSTRATED**
**Decision A — OPA189 + DOCUMENTED 1N4148 SUPERDIODE PASSES ISOLATED ReLU**

Reference is mathematical `max(0, Vin)`. SPICE `v(out)` is the result.
The 1N4148 card is extracted unmodified from TI TLC555.LIB in the ngspice tree.

| Fabric | n | pass | MAE (mV) | max |err| (mV) | worst Vin |
| --- | ---: | ---: | ---: | ---: | ---: |
| exp4_bsource_dsi | 28 | 28/28 | 0.0035 | 0.0261 | 2.0 |
| opa189_teaching_dsi | 28 | 28/28 | 0.0824 | 0.3694 | -3.7 |
| opa189_1n4148 | 28 | 28/28 | 0.0895 | 0.3794 | -3.7 |

XOR hidden pre-activation points on opa189_1n4148: 16/16 pass.

Decision A — OPA189 + DOCUMENTED 1N4148 SUPERDIODE PASSES ISOLATED ReLU. Level-1 OPA189 + documented 1N4148 superdiode. Not silicon.

## Next experiment

Experiment 63: compile the frozen XOR 2-4-1 network onto OPA189 TIA + this ReLU + discrete signed resistors, then SPICE-validate.
