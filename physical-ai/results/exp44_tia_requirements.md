# Experiment 44 — physical high-gain TIA requirement extraction

Experiments 1–43 were not modified. Frozen weights were not edited.
No MOS W/L was invented. This does **not** validate a physical TIA.

## Central question

What must a physical amplifier provide to realize the Experiment 43
W=10 behavioral feasibility point on frozen o2?

**Status: REQUIREMENTS EXTRACTED**
**Decision R — REQUIREMENTS EXTRACTED; PHYSICAL TIA NOT VALIDATED**

## Claim map

| Claim | Category |
| --- | --- |
| Exp43 W=10 + A≥128203 meets 1 mV | Demonstrated (prior) |
| Behavioral A is VCVS open-loop gain, not loop gain T | Demonstrated (this experiment, identity + OP) |
| Loop gain T = A/(1+Rf·G) | Supported (Exp21/22 identity; measured k tracks) |
| Isolated o2 W=10 leftover ≈ +0.604 mV | Demonstrated (Exp41/43) |
| Existing SKY130 Miller realizes A_cross | Contradicted (Exp41 a_eff≈245, 627 mV) |
| Physical TIA exists | Unknown |
| Matching / temperature / F40 / 2.937 V | Unknown |

## A. Behavioral A vs loop gain

Architecture A TIA: `Vout = −A · Vsum`, k = A/(A+1+Rf·G) = T/(T+1)
with **T = A/(1+Rf·G)**.

| A (VCVS open-loop) | T (loop gain) | T dB | k | 1−k |
| ---: | ---: | ---: | ---: | ---: |
| 128203 | 903.5126 | 59.12 | 0.998894432 | 1.105568e-03 |
| 200000 | 1409.5031 | 62.98 | 0.999291033 | 7.089669e-04 |
| 1000000 | 7047.5153 | 76.96 | 0.999858126 | 1.418738e-04 |
| 100000 | 704.7515 | 56.96 | 0.998583071 | 1.416929e-03 |
| 348844.87 | 2458.4896 | 67.81 | 0.999593412 | 4.065884e-04 |

A = 128203 is **not** a 102 dB loop-gain requirement. It is a
**59.12 dB loop-gain** requirement
(T ≈ 903.5) on this Rf·G = 140.893980 load.
A single-stage transistor amplifier must still provide **open-loop**
A_ol ≳ 128203 in this topology, because β = 1/(1+Rf·G) is tiny.
A nested Vsum servo (Exp24/26) is a different topology: it can
remove the k-scale error without that A_ol. That is an alternative
path, not demonstrated here on W=10 SKY130.

## B. Measured operating point (W=10, frozen vec 19)

| A | Vout (V) | Vsum (V) | a_eff | I_amp (A) | I_Rf (A) | err (mV) | pass |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 128203 | 2.458490423515 | -1.917654e-05 | 128203.00000027627 | -7.3710837562e-05 | 7.3710837562e-05 | -0.999147 | PASS |
| 200000 | 2.459066775209 | -1.229533e-05 | 200000.000000732 | -7.37279015199e-05 | 7.372790151991e-05 | -0.422796 | PASS |
| 1000000 | 2.459890565832 | -2.459891e-06 | 1000000.0000008132 | -7.37522913576e-05 | 7.375229135764e-05 | +0.400995 | PASS |

Software z_o2 = 2.459489570880132 V. Isolated output swing on this vector is
|z| = 2.459 V. Network-F |z|max = 2.937183 V is **not**
this experiment and remains unhosted.

## C. Independent error-source sweeps (W=10, A=2e5 unless noted)

### Offset Vos (summing-node referred)

| A | Vos (µV) | err (mV) | pass |
| ---: | ---: | ---: | --- |
| 200000 | +0.000 | -0.422796 | PASS |
| 200000 | +1.000 | -0.339073 | PASS |
| 200000 | +2.000 | -0.255351 | PASS |
| 200000 | +3.000 | -0.171629 | PASS |
| 200000 | +5.000 | -0.004184 | PASS |
| 200000 | +7.000 | +0.163260 | PASS |
| 200000 | +10.000 | +0.414427 | PASS |
| 200000 | +22.000 | +1.419095 | FAIL |
| 200000 | -2.000 | -0.590240 | PASS |
| 200000 | -5.000 | -0.841407 | PASS |
| 128203 | +0.000 | -0.999147 | PASS |
| 128203 | +1.000 | -0.915445 | PASS |
| 128203 | -1.000 | -1.082850 | FAIL |
| 128203 | +2.000 | -0.831742 | PASS |
| 128203 | -2.000 | -1.166553 | FAIL |

### Leakage into the summing node

| Ileak (A) | err (mV) | pass |
| ---: | ---: | --- |
| 0.000e+00 | -0.422796 | PASS |
| 1.000e-09 | -0.456154 | PASS |
| 3.000e-09 | -0.522870 | PASS |
| 1.000e-08 | -0.756378 | PASS |
| 1.300e-08 | -0.856453 | PASS |
| 3.000e-08 | -1.423542 | FAIL |

### Open-loop Rout (inside the Rf loop)

| Rout (Ω) | err (mV) | pass |
| ---: | ---: | --- |
| 0 | -0.422796 | PASS |
| 10 | -0.423104 | PASS |
| 100 | -0.425882 | PASS |
| 1000 | -0.453659 | PASS |
| 10000 | -0.731391 | PASS |
| 20000 | -1.039909 | FAIL |
| 50000 | -1.965006 | FAIL |

### Output clip rails (behavioral)

| ±rail (V) | Vout (V) | err (mV) | pass |
| ---: | ---: | ---: | --- |
| 2.46 | 2.459066775209 | -0.422796 | PASS |
| 2.5 | 2.459066775209 | -0.422796 | PASS |
| 2.55 | 2.459066775209 | -0.422796 | PASS |
| 2.6 | 2.459066775209 | -0.422796 | PASS |
| 3 | 2.459066775209 | -0.422796 | PASS |
| 5 | 2.459066775209 | -0.422796 | PASS |

### 200 µs settling (behavioral single pole, not transistor GBW)

| fp (Hz) | tau_cl (s) | y(200 µs) | |err| vs z (mV) | pass |
| ---: | ---: | ---: | ---: | --- |
| 10 | 1.129156417447311e-05 | 2.459067000000 | 0.422571 | PASS |
| 100 | 1.129156417447311e-06 | 2.459067000000 | 0.422571 | PASS |
| 1000 | 1.1291564174473111e-07 | 2.459067000000 | 0.422571 | PASS |
| 10000 | 1.129156417447311e-08 | 2.458869000000 | 0.620571 | PASS |
| 0 | 0.0 | 2.459070000000 | 0.419571 | PASS |

## D. Extracted budgets (isolated W=10 o2, |y−z|≤1 mV)

| Quantity | Budget | Basis |
| --- | ---: | --- |
| VCVS / opamp open-loop A_ol (this topology) | ≥ 128203 | Exp43 measured A_cross |
| Loop gain T = A/(1+Rf·G) | ≥ 903.5126 (59.12 dB) | same crossing |
| Comfortable A_ol (measured extra margin) | ≥ 200000 | Exp43 A=2e5, |err|=0.423 mV |
| |Vsum| | ≤ 1.917654e-05 V | A_cross OP \|y\|/A |
| |Vos| (summing-node) | A=2e5: pass at +10 uV (|err|=0.414 mV), fail at +22 uV (1.419 mV). At A_cross, -1 uV fails (1.083 mV); +1 uV still passes. | Vos sweep; leftover already uses ~0.60 mV |
| |Ileak| into sum | A=2e5: pass at 13 nA (|err|=0.856 mV), fail at 30 nA (1.424 mV) | Ileak sweep |
| Rout | A=2e5: pass at 10 kOhm (|err|=0.731 mV), fail at 20 kOhm (1.040 mV) | Rout sweep |
| Output swing (this vector) | ≥ 2.458490 V | measured Vout / clip |
| Output current | ≥ 7.371084e-05 A | measured I_amp at A_cross |
| Feedback current | ≥ 7.371084e-05 A | measured I_Rf |
| Settling | ≤ 200 µs | project sampled-inference dwell |
| Open-loop fp for 200 µs (behavioral) | All measured poles (10, 100, 1k, 10k Hz) and no-pole TRAN pass |y-z|<=1 mV at 200 us; fp=10/100/1k match DC to ~0.2 uV | TRAN sweep |
| Supply (isolated o2 only) | Behavioral clip at +/-2.46 V still passes this vector (Vout=2.459 V). This is not MOS headroom; a real amp needs Vdsat above 2.459 V. SKY130 5V family can host +/-2.5 V rails. Network-F 2.937 V is outside this budget. | clip sweep + SKY130 5 V family |
| Network-F 2.937 V | NOT IN THIS BUDGET | unhosted |

Exp22 network-F analog A≥4.88e4 remains valid for **ideal-R network MAE**.
It is **not** sufficient for isolated W=10 o2 |y−z|≤1 mV. The leftover
+0.604 mV resistor residual consumes most of the 1 mV bar, so this
cell needs A_ol ≳ 1.28e5 in the uncompensated topology.

## E. What destroys the bar first

On the uncompensated W=10 o2 cell the 1 mV bar is already almost consumed by deterministic resistor leftover (+0.60 mV) plus residual finite-A. At A=A_cross the remaining signed budget is ~0.85 µV (|err|=0.999147 mV). Extra Vos of a few µV, nA-class leak, or clipping below the measured Vout will fail first. Existing Miller gain (a_eff≈245) fails by hundreds of millivolts — gain is the largest single gap versus A_ol≥128203.

## F. Documented technology vs these budgets

No transistor was sized. Comparison uses prior measured cells and
installed-file inventory only.

- SKY130A installed: **True**. 5 V FET family documented.
- Existing Exp41 Miller on this o2 cell: a_eff ≈ **245**, |err| = **627 mV**.
  That is **523× below** A_ol=128203. Contradicted as a no-resize solution.
- IHP SG13G2 installed: **False**.
- GF180MCU installed: **False**.
- Vendor macromodels present: ['opa189', 'opa192', 'opa388'].
- ngspice OPA examples: ['C:\\ngspice\\examples\\optran\\models\\opa1656.lib', 'C:\\ngspice\\examples\\optran\\models\\OPA1611.LIB', 'C:\\ngspice\\examples\\p-to-n-examples\\OPA171.txt'].
- Exp23/24: OPA171/1656 headline Vos is not the loaded Vsum at Rf·G=141.
- Exp24 servo can null Vsum and remove finite-A k-error on **ideal R**.
  That path is not re-validated here on W=10 SKY130.

## Competing hypotheses after this experiment

| ID | Statement | Status |
| --- | --- | --- |
| H1 | Physical amp cannot reach A_ol=1.28e5 as a single Miller | Supported (Exp41 a_eff=245) |
| H2 | Resistor leftover dominates once A is large | Demonstrated |
| H3 | A=1.28e5 is an artifact; loop gain is only ~900 | Demonstrated (both true: A_ol vs T) |
| H4 | Nested servo / AZ can replace raw A_ol | Supported on ideal R (Exp24/26); **untested on W=10 SKY130** |
| H5 | ±2.5 V SKY130 rails cannot host 2.46 V with real headroom | Tested behaviorally via clip; see clip table |
| H6 | Partitioning the map avoids the TIA | Not tested |

## Conclusion

A physical Architecture-A TIA on this W=10 o2 cell must provide open-loop A_ol ≥ 128203 (loop gain T ≥ 903.5, 59.12 dB) at Vout≈2.458490423515 V, |Vsum|≤1.918e-05 V, |Iout|≥7.3710837562e-05 A. A=128203 is open-loop gain, not loop gain. The Exp41 Miller (a_eff≈245) does not meet it. Vos/Ileak budgets are tight because leftover already uses ~0.60 mV of the 1 mV bar. PHYSICAL TIA VALIDATED is not claimed.

## Status

- Experiment 44: **REQUIREMENTS EXTRACTED**
- Decision: **R — REQUIREMENTS EXTRACTED; PHYSICAL TIA NOT VALIDATED**
- Physical TIA validated: **NO**
- Matching: **UNRESOLVED**
- Temperature: **NOT TESTED** (requirement listed, not swept in PDK TCR)
- Network-F 2.937 V: **NOT DEMONSTRATED**
- Experiment 40 Decision C: **unchanged**

## Next experiment

Experiment 45: Level-1 documented macromodel search against these budgets on the same W=10 o2 cell (OPA189 / OPA388 / OPA1656 already on disk; do not invent W/L). Separately, a servo/AZ topology test on W=10 SKY130 is the H4 falsifier. Do not transistor-resize the Exp39 Miller as the first move.

