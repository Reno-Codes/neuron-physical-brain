# Experiment 40 closure — catalog o2 on official SKY130A

**CLOSED** at the first identity-correct o2 DC. No optimization. Experiment 39
was not reopened or modified. Frozen weights, PDK hash, decks, and SPICE
numbers below are historical and were not silently edited.

## Central result

The official SKY130A implementation of the actual critical o2 cell, at the
frozen geometry and parameters used, produces **6.946 mV** absolute error
and therefore **fails** the **1 mV** analog acceptance criterion.

This is not an o2/o3 bookkeeping error. Unlike Experiment 39, Experiment 40
genuinely simulated the critical o2 cell.

## Historical pair

| Experiment | Decision | What was simulated |
| --- | --- | --- |
| 39 | **C** | Identity-corrected **o3** experiment; critical o2 **not** simulated |
| 40 | **C** | Critical **o2** correctly simulated; analog bar fails at **6.946 mV** |

## Authoritative numbers (unchanged)

| Item | Value |
| --- | --- |
| Target | o2 / W2[1] |
| PDK | official SKY130A `1689ac3f2dc763876eaf967227c7dfe831b031ae` |
| Rf·G | 140.89398023224967 |
| Gtot | 4.22681940696749e-3 S |
| Imax | 202.805091 µA |
| z_o2 | +2.459489570880132 V (F40 vector 19) |
| SPICE y | 2.45254388951 V |
| error | −6.945681370132295 mV |
| \|error\| | 6.945681370132295 mV |
| Acceptance limit | 1.0 mV |
| Analog bar | **FAIL** (≈ **6.95×** the 1 mV limit) |
| tt / ll / hh | common-mode identical leftover |
| Matching | **UNRESOLVED** |
| Decision | **C** (automated `decide()`; no override) |

## Decision: C — PDK EXPOSES A TECHNOLOGY LIMIT

`decide()` requires `analog_pass` (`|y−z| <= 1e-3`) on a tested PDK-R or
miller inference DC row. The tested o2 PDK-R row does not satisfy
`analog_pass`. Letter **C** follows directly. Published override is not
permitted and was not applied.

Decision C here means: the official SKY130A o2 cell **as instantiated**
fails the existing analog bar. It does not, by itself, prove a foundry
yield, a matching PDF, or that no other geometry could pass. W=10, Miller,
and area changes were **not** run.

## Required interpretation

1. Unlike Experiment 39, Experiment 40 genuinely simulated the critical o2 cell.
2. Identity was proven before SPICE: W2[1] → Rf·G 140.893980 → Gtot
   4.226819e-3 S → Imax 202.805 µA → \|z\|max 2.459490 V.
3. The generated deck matches the o2 target (80 xhigh_po, L1 = 6.7601697,
   Rf·G = 140.89398023224967).
4. Therefore the 6.946 mV residual is a genuine result for the critical o2
   physical implementation, not an o2/o3 bookkeeping error.
5. The result fails the original 1 mV analog requirement by approximately
   **6.95×**.
6. Identical tt/ll/hh results are common-mode process behavior and are
   **not** matching evidence.
7. Matching remains **UNRESOLVED**.
8. W=10, Miller, MC, MOS mismatch, F40 classification, and temperature
   testing remain **NOT TESTED**.
9. Network-F software \|z\|max = **2.937183 V** is a separate network-level
   quantity and is not a measured SKY130 node.
10. Decision C follows the original automated rule because the tested o2
    PDK-R inference row does not satisfy analog_pass.

## 1. Target identity proof

SIM_TARGET = o2 / W2[1]

| Check | Got | Catalog | OK |
| --- | ---: | ---: | --- |
| index | 1 | 1 | True |
| Rf_Gtot | 140.89398023224967 | 140.89398023224967 | True |
| Gtot_S | 0.00422681940696749 | 0.00422681940696749 | True |
| Imax_A | 0.0002028050907723382 | 0.000202805 | True |
| z_abs_max_V | 2.459489570880132 | 2.459489570880132 | True |

## 2. Weight extraction proof

- Frozen file: `models/scaling/F.npz` seed 9. Weights were not edited.
- Row passed to compiler: **W2[1]**. b2 = 0.03221305319424547.
- W2[2] was not passed. Forbidden row 2 is blocked in the script.

## 3. Catalog-vs-simulation truth table

| Quantity | Catalog o2 | This run | Network software |
| --- | ---: | ---: | ---: |
| W2 index | 1 | 1 | — |
| Rf·G | 140.89398023224967 | 140.89398023224967 | — |
| Gtot (S) | 4.22681940696749e-3 | 4.22681940696749e-3 | — |
| Imax (µA) | 202.805 | 202.805091 | this neuron |
| \|z\|max (V) | 2.459489570880132 | 2.459489570880132 (z_o2) | 2.937183 (h25) |
| Analog \|y−z\| | — | 6.945681370132295 mV FAIL | not run |

## 4. Generated-deck identity

- Path: `circuits/exp40_o2/o2_pdk_r_behav_{tt,ll,hh}_t27.cir` (filenames preserved).
- 80 `sky130_fd_pr__res_xhigh_po`. Weight/bias count 33.
- Rf: W=1 µm, L=15.7170614549824 µm, R_target = 33333.333333333336 Ω.
- Header L1 = 6.7601697 (o2, not o3 7.8038105).
- `matches_o2_rfg`: True.

## 5. SPICE results (Phase 1)

W=1 µm xhigh_po + behavioral TIA A=1e5. Teaching models were not used.

| Quantity | tt 27 C |
| --- | ---: |
| y = v(n1lin) | 2.45254388951 V |
| vsum = v(n1p) | −2.45254388951e-5 V |
| a_eff = \|y/vsum\| | 1e5 |
| I_Rf ≈ \|y\|/Rf | 73.576 µA |
| Catalog Imax | 202.805091 µA (capability, not this vector) |

## 6. Analog error (Phase 2)

err = y_SPICE − z_o2.

| Test | y (V) | err (V) | \|err\| (mV) | pass |
| --- | ---: | ---: | ---: | --- |
| pdk_r_behav_tt_27 | 2.45254388951 | −0.006945681370132295 | 6.945681370132295 | no |
| pdk_r_behav_ll_27 | 2.45254388951 | −0.006945681370132295 | 6.945681370132295 | no |
| pdk_r_behav_hh_27 | 2.45254388951 | −0.006945681370132295 | 6.945681370132295 | no |

## 7. Process-corner result

tt = ll = hh, bit-identical. Common-mode process cancel. **Not matching.**

## 8. Matching status

**UNRESOLVED.** No new Monte Carlo. No invented mismatch PDF.

## 9. Voltage status

- o2 software \|z\|max / z_o2 = +2.459489570880132 V.
- Simulated y = 2.45254388951 V (inside ±2.5 V).
- Network software \|z\|max = 2.937183 V (h25): **not** a measured SKY130 node.

## 10. Classification

| Item | Status |
| --- | --- |
| Identity instantiation of catalog o2 | **PASS** |
| Analog bar \|y−z\| ≤ 1 mV | **FAIL** |
| tt/ll/hh DC sanity | **MEASURED** |
| Matching 0.075% | **UNRESOLVED** |
| W=10 geometry | **NOT TESTED** |
| 5 V Miller TIA | **NOT TESTED** |
| MC / MOS mismatch | **NOT TESTED** |
| F40 classification | **NOT TESTED** |
| Temperature | **NOT TESTED** |

## 11. Decision

**C — PDK EXPOSES A TECHNOLOGY LIMIT**

Automated rule only. No override.

## 12. Discrepancies

None of identity. The analog residual is a real o2-cell result at the frozen
W=1 length-encoded geometry. Experiment 41 was not started.
