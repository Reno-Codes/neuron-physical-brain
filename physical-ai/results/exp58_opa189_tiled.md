# Experiment 58 — OPA189 TIA on W=10 8s×8p

Experiments 1–57 were not modified. Level-1 TI macromodel + official
SKY130 `xhigh_po` include. Not silicon. No resistor fitting.

**Status: PARTIALLY VALIDATED**
**Decision B — OPA189 + 8s8p NOMINAL PASSES; mm SAMPLE MIXED (NOT YIELD)**
**Realism: Level 1 TIA + Level 4 PDK resistors. Not a PDK MOS TIA.**

## 1. Objective

Does the documented OPA189 host still meet 1 mV on the leftover-limited
W=10 8s×8p fabric, and do official-include `mc_mm_switch=1` draws stay
inside the leftover-dominated envelope?

## 2. Baseline

OPA189 + W=10 single y = 2.460095443162, Δy vs Experiment 45 = **0**.

## 3. Hypothesis

H1: nominal 8s8p leftover ≈ +0.48 to +0.68 mV (Exp57 floor) and still
passes 1 mV.
H2: `tt_mm` on this fabric is leftover plus a small tail (some misses).
H3: OPA189 does not add a new millivolt error beyond Exp45/46.

## 4. Method

`ngbehavior=ps`, official R `.include` (no `.lib tt`). OPA189 ±15 V.
W=10 8s×8p = 5120 `xhigh_po` units. `mc_mm_switch=1` for eight draws.
`set seed=58000+i`.

## 5. Controls

OPA189 W=10 single (Exp45/46 repeat).

## 6. Results

| config | y (V) | \|err\| (mV) | pass |
| --- | ---: | ---: | --- |
| OPA189 W=10 (repeat) | 2.460095443162 | 0.606 | True |
| OPA189 W=10 8s8p | 2.460173765013 | 0.684 | True |

### mc_mm_switch=1 n=8 (not yield)

| draw | y (V) | \|err\| (mV) | pass |
| ---: | ---: | ---: | --- |
| 0 | 2.460321054606 | 0.831 | True |
| 1 | 2.460216518957 | 0.727 | True |
| 2 | 2.460989902733 | 1.500 | False |
| 3 | 2.460249888983 | 0.760 | True |
| 4 | 2.459753210798 | 0.264 | True |
| 5 | 2.460239845779 | 0.750 | True |
| 6 | 2.460682468500 | 1.193 | False |
| 7 | 2.460607210324 | 1.118 | False |

**5/8 PASS.** Mean of the eight |err| = 0.893 mV.

## 7. Mechanism

Nominal 8s8p |err| = 0.684 mV equals Experiment 57 W=20 8s8p − ideal
(+0.684 mV) and is 78 µV above OPA189 W=10 (0.606 mV) — the same
array tax seen on the behavioral TIA. H1 and H3 hold. H2 holds:
three high-side tails miss, consistent with leftover + AGAUSS.

## 8. Failure analysis

No solver failure. Mixed mm sample is leftover-limited, not a new
macromodel break. Not yield (n=8).

## 9. Promotion decision

**B — PARTIALLY VALIDATED.** Level-1 TIA + leftover-limited tiled PDK
R meets 1 mV nominally on isolated o2 vec 19. Matching still mixed.
Physical MOS TIA **NO**. Miller family **CLOSED**. Not silicon.

## 10. Claim map

- **Demonstrated:** Exp45 OPA189 W=10 exact repeat; 8s8p nominal
  0.684 mV PASS; 5/8 include-file mm draws pass.
- **Supported:** leftover floor transfers from behavioral TIA to OPA189.
- **Projected:** other F40 vectors with smaller |z| will pass more easily.
- **Unknown:** yield; Network F with tiled R; temperature on tiled+OPA189.
- **Contradicted:** unre-sized miller as this TIA; leftover is matching.

## 11. Next dominant bottleneck

**Primary:** deterministic leftover / voltco on worst-case vec 19.

**Secondary:** `tt_mm` tails; Network F insertion; Track B MOS TIA.

## 12. Next experiment

Experiment 59: frozen F40 vectors 19 / 20 / 38 / 6 on OPA189 + W=10
8s8p (isolated). Leftover stated as the analog floor.

Decision B — OPA189 + 8s8p NOMINAL PASSES; mm SAMPLE MIXED (NOT YIELD).
OPA189 is a Level-1 macromodel host, not silicon. Miller family remains closed.
