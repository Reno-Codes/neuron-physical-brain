# Experiment 43 — high-gain behavioral TIA + existing W=10

Experiments 1–42 were not modified. Frozen weights were not edited.
Resistors were not fitted. SPICE was not Python-corrected.
No MOS W/L search. This is **not** a physical TIA validation.

## Central question

Is Experiment 42 Case C (existing W=10 encode + sufficiently high
behavioral A) actually demonstrable in SPICE at |Vout − z_o2| ≤ 1 mV?

**Decision A — FEASIBILITY DEMONSTRATED**

BEHAVIORAL HIGH-GAIN + W=10 is a separate claim from
**PHYSICAL TIA VALIDATED**. The latter is **not** claimed.

## Identity

- SIM_TARGET = o2 / W2[1]
- Rf·G = 140.89398023224967
- z_o2 (vec 19) = 2.459489570880132
- Compiler row W2[1] only. W2[2] blocked.
- PDK 1689ac3f2dc763876eaf967227c7dfe831b031ae

## Netlist / model changes (this experiment only)

- Compile the same isolated o2 cell as Experiments 40/41 (behavioral TIA).
- Patch **only** `En1tia` open-loop A. Invert VCVS remains A=1e7.
- W=10: Experiment 41 same-family `xhigh_po` encode, no L/W refit.
- W=1: Experiment 40 `replace_resistors_with_pdk`.
- Ideal R: catalog lumped resistors, unchanged values.
- Official SKY130A tt, .temp 27. Solver: ngspice_con, `option klu`,
  `set ngbehavior=hsa`, `set skywaterpdk`, `set ng_nomodcheck`, DC `op`,
  `set numdgt=12`. No new .options tolerances.

## Baseline reproduction (A=1e5, not overwriting 40/41)

| Config | This y (V) | Prior y (V) | \|err\| (mV) | Match \|Δy\|≤10 nV | Pass |
| --- | ---: | ---: | ---: | --- | --- |
| ideal | 2.457433737388 | 2.457433737388 | 2.055833 | True | False |
| W=1 | 2.45254388951 | 2.45254388951 | 6.945681 | True | False |
| W=10 | 2.458037812913 | 2.458037812913 | 1.451758 | True | False |

## Primary sweep — existing W=10

| A | Vout (V) | z_o2 (V) | err (mV) | \|err\| (mV) | pass |
| ---: | ---: | ---: | ---: | ---: | --- |
| 100000 | 2.458037812913 | 2.459489570880 | -1.451758 | 1.451758 | FAIL |
| 128203 | 2.458490423515 | 2.459489570880 | -0.999147 | 0.999147 | PASS |
| 200000 | 2.459066775209 | 2.459489570880 | -0.422796 | 0.422796 | PASS |
| 348845 | 2.459506074682 | 2.459489570880 | +0.016504 | 0.016504 | PASS |
| 500000 | 2.459684566409 | 2.459489570880 | +0.194996 | 0.194996 | PASS |
| 1000000 | 2.459890565832 | 2.459489570880 | +0.400995 | 0.400995 | PASS |
| 10000000 | 2.460075994832 | 2.459489570880 | +0.586424 | 0.586424 | PASS |
| 114101.5 | 2.458292066157 | 2.459489570880 | -1.197505 | 1.197505 | FAIL |
| 121152.25 | 2.458397012791 | 2.459489570880 | -1.092558 | 1.092558 | FAIL |
| 124677.62 | 2.458445037903 | 2.459489570880 | -1.044533 | 1.044533 | FAIL |
| 126440.31 | 2.458468046857 | 2.459489570880 | -1.021524 | 1.021524 | FAIL |
| 127321.66 | 2.458479312583 | 2.459489570880 | -1.010258 | 1.010258 | FAIL |
| 127762.33 | 2.458484887198 | 2.459489570880 | -1.004684 | 1.004684 | FAIL |
| 127982.66 | 2.458487660119 | 2.459489570880 | -1.001911 | 1.001911 | FAIL |
| 128092.83 | 2.458489043005 | 2.459489570880 | -1.000528 | 1.000528 | FAIL |

## Control A — ideal resistors

| A | Vout (V) | err (mV) | \|err\| (mV) | pass |
| ---: | ---: | ---: | ---: | --- |
| 100000 | 2.457433737388 | -2.055833 | 2.055833 | FAIL |
| 128203 | 2.457885699213 | -1.603872 | 1.603872 | FAIL |
| 200000 | 2.458461224348 | -1.028347 | 1.028347 | FAIL |
| 348845 | 2.458899893503 | -0.589677 | 0.589677 | PASS |
| 500000 | 2.459078129049 | -0.411442 | 0.411442 | PASS |
| 1000000 | 2.459283832756 | -0.205738 | 0.205738 | PASS |
| 10000000 | 2.459468995519 | -0.020575 | 0.020575 | PASS |
| 114101.5 | 2.457687626217 | -1.801945 | 1.801945 | FAIL |
| 121152.25 | 2.457792422408 | -1.697148 | 1.697148 | FAIL |
| 124677.62 | 2.457840378670 | -1.649192 | 1.649192 | FAIL |
| 126440.31 | 2.457863354636 | -1.626216 | 1.626216 | FAIL |
| 127321.66 | 2.457874604210 | -1.614967 | 1.614967 | FAIL |
| 127762.33 | 2.457880170833 | -1.609400 | 1.609400 | FAIL |
| 127982.66 | 2.457882939779 | -1.606631 | 1.606631 | FAIL |
| 128092.83 | 2.457884320682 | -1.605250 | 1.605250 | FAIL |

## Control B — existing W=1 at high A

| A | Vout (V) | err (mV) | \|err\| (mV) | leftover vs ideal (mV) | pass |
| ---: | ---: | ---: | ---: | ---: | --- |
| 100000 | 2.452543889510 | -6.945681 | 6.945681 | -4.889847878000175 | FAIL |
| 348845 | 2.453998371263 | -5.491200 | 5.491200 | -4.9015222400004 | FAIL |
| 1000000 | 2.454379249789 | -5.110321 | 5.110321 | -4.904582966999804 | FAIL |
| 10000000 | 2.454562935919 | -4.926635 | 4.926635 | -4.906059599999679 | FAIL |

## Control C — A=1e7 asymptotic trio

| Fabric | Vout (V) | err (mV) | \|err\| (mV) | pass |
| --- | ---: | ---: | ---: | --- |
| ideal | 2.459468995519 | -0.020575 | 0.020575 | PASS |
| W=1 | 2.454562935919 | -4.926635 | 4.926635 | FAIL |
| W=10 | 2.460075994832 | +0.586424 | 0.586424 | PASS |

## Gain-boundary extraction

- Experiment 42 predicted A_cross ≈ 128203.097513
- Measured last FAIL A = 128092.83203125
- Measured first PASS A = 128203.0
- Measured A_cross (bisection midpoint / first pass) = 128203.0
- Predicted − measured = 0.09751266831881367
- Model was not adjusted to force agreement.

## Error decomposition (W=10 vs ideal R at same A)

| A | total (mV) | finite-A / ideal (mV) | resistor leftover (mV) | leftover − Exp41 +0.604 (mV) |
| ---: | ---: | ---: | ---: | ---: |
| 100000 | -1.451758 | -2.055833 | +0.604076 | +0.000000 |
| 128203 | -0.999147 | -1.603872 | +0.604724 | +0.000649 |
| 200000 | -0.422796 | -1.028347 | +0.605551 | +0.001475 |
| 348845 | +0.016504 | -0.589677 | +0.606181 | +0.002106 |
| 500000 | +0.194996 | -0.411442 | +0.606437 | +0.002362 |
| 1000000 | +0.400995 | -0.205738 | +0.606733 | +0.002658 |
| 10000000 | +0.586424 | -0.020575 | +0.606999 | +0.002924 |
| 114101.5 | -1.197505 | -1.801945 | +0.604440 | +0.000364 |
| 121152.25 | -1.092558 | -1.697148 | +0.604590 | +0.000515 |
| 124677.62 | -1.044533 | -1.649192 | +0.604659 | +0.000584 |
| 126440.31 | -1.021524 | -1.626216 | +0.604692 | +0.000617 |
| 127321.66 | -1.010258 | -1.614967 | +0.604708 | +0.000633 |
| 127762.33 | -1.004684 | -1.609400 | +0.604716 | +0.000641 |
| 127982.66 | -1.001911 | -1.606631 | +0.604720 | +0.000645 |
| 128092.83 | -1.000528 | -1.605250 | +0.604722 | +0.000647 |

## Repeat run

- Repeat of `w10_a1000000`: y=2.459890565832 |err|=0.400995 mV Δy=0.0 reproducible=True

## Sensitivity (frozen F40 vectors, same W=10 encode)

Operating A = 1000000.0

| Vector | Role | z (V) | Vout (V) | err (mV) | pass |
| ---: | --- | ---: | ---: | ---: | --- |
| 19 | max_|z|_established_o2 | 2.459489570880 | 2.459890565832 | +0.400995 | PASS |
| 20 | most_negative_z | -0.918911879679 | -0.918403704654 | +0.508175 | PASS |
| 38 | mid_|z| | 0.980936703628 | 0.980833201871 | -0.103502 | PASS |
| 6 | lower_|z| | 0.133713247630 | 0.133744062295 | +0.030815 | PASS |

## Gates

- weights_unchanged: **True**
- w10_unfitted: **True**
- no_python_correction: **True**
- reproducible: **True**
- baseline_reproduced: **True**

## Demonstrated versus projected

- Experiment 42 Case C: DEMONSTRATED in SPICE (behavioral TIA + existing W=10)
- Behavioral high-gain + W=10 feasibility: BEHAVIORAL HIGH-GAIN + W=10 FEASIBILITY DEMONSTRATED
- Physical TIA validated: **NO**
- Matching: **UNRESOLVED**
- Temperature: **NOT TESTED**
- Network-F 2.937 V hosting: **NOT DEMONSTRATED**
- F40 network: **NOT TESTED**

## Conclusion

Decision A — FEASIBILITY DEMONSTRATED. Case C status: DEMONSTRATED in SPICE (behavioral TIA + existing W=10). Measured A_cross=128203.0; Exp42 prediction 128203.098; difference 0.09751266831881367. PHYSICAL TIA VALIDATED is not claimed. W=10 leftover ranged +0.6041 to +0.6070 mV (Exp41 reference +0.6041 mV).

## Recommended Experiment 44 (not started)

Extract what a physical amplifier must provide to realize the
measured behavioral A_cross at the actual o2 operating point:

- required open-loop / effective loop gain
- output swing at the measured operating point
- input / summing-node error budget
- output current
- bandwidth / 200 µs settling
- temperature range
- PDK supply / device-limit compatibility

Do not start transistor redesign in Experiment 43.

## Status

- Experiment 40 Decision C: **unchanged**
- Experiment 42 boundary: **unchanged** (now measured, not rewritten)
- Experiment 43 decision: **A — FEASIBILITY DEMONSTRATED**
- PHYSICAL TIA VALIDATED: **NO**

No Experiment 44 started. No MOS optimization.

