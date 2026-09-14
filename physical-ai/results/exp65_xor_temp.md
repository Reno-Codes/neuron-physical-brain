# Experiment 65 — compiler XOR temperature

Experiments 1-64 were not modified. Frozen xor_model.npz. Not silicon.

**Status: PARTIALLY VALIDATED**
**Decision B — CLASS HOLDS AT ALL TEMPS; ANALOG 1 mV MISSED**

Discrete resistors have no TCR card (not invented). Temperature is in the OPA189 and 1N4148 macromodels.
27 C repeat vs Exp64 dy = [0.0, 0.0, 0.0, 0.0]

| T (C) | vec | y (V) | |err| (mV) | class | pass |
| ---: | ---: | ---: | ---: | ---: | --- |
| -40.0 | 0 | 0.001651031 | 0.0007 | 0 | True |
| -40.0 | 1 | 1.002524 | 0.0003 | 1 | True |
| -40.0 | 2 | 1.018018 | 0.0014 | 1 | True |
| -40.0 | 3 | 0.001651031 | 0.0007 | 0 | True |
| 27.0 | 0 | 0.001645123 | 0.0052 | 0 | True |
| 27.0 | 1 | 1.002511 | 0.0133 | 1 | True |
| 27.0 | 2 | 1.018006 | 0.0134 | 1 | True |
| 27.0 | 3 | 0.001645121 | 0.0052 | 0 | True |
| 85.0 | 0 | 0.001162691 | 0.4876 | 0 | True |
| 85.0 | 1 | 1.001445 | 1.0793 | 1 | False |
| 85.0 | 2 | 1.016937 | 1.0824 | 1 | False |
| 85.0 | 3 | 0.001161186 | 0.4892 | 0 | True |

Decision B — CLASS HOLDS AT ALL TEMPS; ANALOG 1 mV MISSED. MIXED-LEVEL. Ideal discrete R. Not silicon.

## Next experiment

Bound the failing temperature. Discrete R still have no TCR card.
