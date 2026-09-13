# Experiment 46 — OPA189 TIA promotion on W=10 o2

Experiments 1–45 were not modified. Frozen weights unchanged.
Official tt resistor include from Experiment 45. No MOS W/L.
No Python correction. Not silicon. Isolated cell only.

**Status: PARTIALLY VALIDATED**
**Decision A — OPA189 TIA PROMOTED ON ISOLATED W=10 o2 (DC/TRAN/TEMP)**

## DC repeat (vec 19, OPA189 ±15 V)

- y = 2.460095443162  |err| = 0.605872 mV  pass = True  Δ vs Exp45 = 0.0

## Frozen F40 vectors (OPA189 ±15 V)

| vector | role | z (V) | y (V) | |err| (mV) | pass |
| ---: | --- | ---: | ---: | ---: | --- |
| 19 | max_|z|_established_o2 | 2.459489570880132 | 2.460095443162 | 0.605872 | True |
| 20 | most_negative_z | -0.9189118796786009 | -0.918480753305 | 0.431126 | True |
| 38 | mid_|z| | 0.980936703627777 | 0.9809145377816 | 0.022166 | True |
| 6 | lower_|z| | 0.13371324763011014 | 0.1337547173074 | 0.041470 | True |

## 200 µs transient (vec 19)

| name | method | y (V) | |err| (mV) | pass |
| --- | --- | ---: | ---: | --- |
| opa189_pm15_tran200u | default | 2.460095 | 0.605429 | True |

## Temperature DC (vec 19, OPA189 ±15 V)

| T (C) | y (V) | |err| (mV) | Vsum (V) | pass |
| ---: | ---: | ---: | ---: | --- |
| -40.0 | 2.459899516483 | 0.409946 | -3.20899402304e-07 | True |
| 27.0 | 2.460095443162 | 0.605872 | 1.408843641134e-08 | True |
| 85.0 | 2.460126424196 | 0.636853 | 3.040787746318e-07 | True |

## Extra supplies (DC vec 19)

| Candidate | ±V | y (V) | |err| (mV) | pass |
| --- | ---: | ---: | ---: | --- |
| OPA189 | 5.0 | 2.459989888341 | 0.500317 | True |
| OPA388 | 2.5 | 2.460104142955 | 0.614572 | True |

Decision A — OPA189 TIA PROMOTED ON ISOLATED W=10 o2 (DC/TRAN/TEMP). OPA189 remains a vendor macromodel, not a SKY130 MOS TIA and not silicon. Network F was not tested. Matching remains unresolved.

- Physical TIA validated: **NO** (macromodel ≠ PDK MOS ≠ silicon)
- Matching: **UNRESOLVED**
- Network F: **NOT TESTED**
- Experiment 40 Decision C: **unchanged**
- Experiment 45 Decision A: **unchanged** (isolated DC)

## Next experiment

Experiment 47: multi-copy / representative insertion of the same OPA189 TIA, still on frozen Architecture A, without claiming Network F or silicon. In parallel, resistor matching remains UNRESOLVED.

