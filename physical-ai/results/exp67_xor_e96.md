# Experiment 67 — E96 XOR resistor snap

Experiments 1-66 were not modified. Frozen weights not edited. Not silicon.

**Status: PARTIALLY VALIDATED**
**Decision B — E96 KEEPS CLASS; ANALOG 1 mV MISSED**

Snapped 17 weight/bias resistors to nearest E96.
XOR MAE = 9.6341 mV; max |err| = 29.8536 mV; analog 2/4; class 4/4.

| vec | y_ref (V) | y (V) | |err| (mV) | class | pass |
| ---: | ---: | ---: | ---: | ---: | --- |
| 0 | 0.001650341 | 0.001650404 | 0.0001 | 0 | True |
| 1 | 1.002524312 | 0.9938416999999999 | 8.6826 | 1 | False |
| 2 | 1.018019447 | 1.047873 | 29.8536 | 1 | False |
| 3 | 0.001650341 | 0.001650402 | 0.0001 | 0 | True |

Decision B — E96 KEEPS CLASS; ANALOG 1 mV MISSED. MIXED-LEVEL. Not silicon.

## Next experiment

Use 0.1% / exact R for analog, or accept class-only E96. I/O interface is still the MVP blocker.
