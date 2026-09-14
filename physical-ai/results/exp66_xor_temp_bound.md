# Experiment 66 — XOR temperature bound

Experiments 1-65 were not modified. Not silicon.

**Status: DEMONSTRATED**
**Decision A — ANALOG 1 mV HOLDS AT 55 C AND 70 C; 85 C REMAINS THE BOUNDARY**

| T (C) | vec | |err| (mV) | pass |
| ---: | ---: | ---: | --- |
| 55.0 | 0 | 0.0600 | True |
| 55.0 | 1 | 0.1343 | True |
| 55.0 | 2 | 0.1344 | True |
| 55.0 | 3 | 0.0600 | True |
| 70.0 | 0 | 0.1794 | True |
| 70.0 | 1 | 0.3973 | True |
| 70.0 | 2 | 0.3984 | True |
| 70.0 | 3 | 0.1797 | True |

Decision A — ANALOG 1 mV HOLDS AT 55 C AND 70 C; 85 C REMAINS THE BOUNDARY. MIXED-LEVEL. Not silicon.

## Next experiment

Promote XOR compile analog range as -40 to 70 C (ideal discrete R). 85 C is class-only. Next MVP step is the DAC/ADC interface, not more temp points.
