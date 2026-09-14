# Experiment 64 — inverting precision rectifier + compiler XOR

Experiments 1-63 were not modified. Frozen xor_model.npz. Not silicon.

**Status: DEMONSTRATED**
**Decision A — COMPILER-GENERATED XOR CIRCUIT MATCHES FROZEN SOFTWARE**

Closed: single-diode network OP abort; bidirectional clamp follower (negatives pass).
Primitive: textbook two-diode inverting rectifier, documented 1N4148.
Reference for isolated test is `max(-Vin, 0)`. Hidden TIA supplies `-z`.

Isolated: 28/28 pass, MAE=0.0089 mV.

XOR MAE = 0.0093 mV; max |err| = 0.0134 mV; analog 4/4; class 4/4.

| vec | x | y_ref (V) | y (V) | |err| (mV) | class | pass |
| ---: | --- | ---: | ---: | ---: | ---: | --- |
| 0 | [0.0, 0.0] | 0.001650341 | 0.001645123 | 0.0052 | 0 | True |
| 1 | [0.0, 1.0] | 1.002524312 | 1.002511 | 0.0133 | 1 | True |
| 2 | [1.0, 0.0] | 1.018019447 | 1.018006 | 0.0134 | 1 | True |
| 3 | [1.0, 1.0] | 0.001650341 | 0.001645121 | 0.0052 | 0 | True |

Decision A — COMPILER-GENERATED XOR CIRCUIT MATCHES FROZEN SOFTWARE. MIXED-LEVEL. Not silicon.

## Next experiment

First compiler-generated mixed-level XOR circuit is a PCB MVP candidate. Next: temperature on this netlist, then a real input interface. Do not reopen miller.
