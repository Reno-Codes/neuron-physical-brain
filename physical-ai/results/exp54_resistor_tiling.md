# Experiment 54 — documented resistor area / unit tiling under tt_mm

Experiments 1–53 were not modified. Behavioral TIA A=1e6. Official
SKY130 `tt_mm` AGAUSS, not foundry yield. No resistor fitting.
No Python correction of SPICE voltages.

**Status: PARTIALLY VALIDATED**
**Decision B — 4s4p MEAN |err| IN 1 mV BAR BUT SAMPLE NOT ALL-PASS (NOT YIELD)**
**Realism: Level 4 PDK resistors + Level 0 behavioral TIA. Not silicon.**

## 1. Objective

Does documented SKY130 `xhigh_po` geometry — width scaling or same-W
series-parallel unit arrays — reduce official `tt_mm` mismatch enough
that the frozen o2 cell stays inside the 1 mV bar more often than the
Experiment 53 W=10 single-device encode?

Separate deterministic leftover from random AGAUSS. Do not declare yield.

## 2. Baseline

Experiment 53 nominal file re-simulated: y = 2.459890565832, Δy = 0.
This experiment's new W=10 nominal matches that value exactly.

Independent W=10 `tt_mm` n=16: **5/16 PASS**, mean |err| = **2.810 mV**,
max = **8.932 mV**. Experiment 53 was 1/8, mean 3.23 mV, max 8.51 mV.
Same mechanism, larger sample, not the same draws.

## 3. Hypothesis

Official installed card (`sky130_fd_pr__res_xhigh_po.model.spice`):

- body: `res_match = 0.0347/sqrt(w*l*mult) * MC_MM_SWITCH * AGAUSS`
- head: `rend_mm = 0.0472/sqrt(w)`

H1: a same-W N×N unit array averages uncorrelated AGAUSS as ~1/N and
does not change deterministic leftover (heads preserved in series-parallel
of identical units).
H2: W=20 same-family encode reduces both leftover and mismatch (confounded).
H3: 4-series of R/4 (same total area, more heads, shorter L) does **not**
improve body mismatch and may worsen it.
H4: leftover stays set by W=10 geometry (~0.40 mV) and is not the 1 mV limiter.

## 4. Method

Frozen catalog o2 / W2[1], vec 19, z = +2.459489570880132 V.
Behavioral TIA A=1e6. Official `.lib tt` / `.lib tt_mm`. `.temp 27`.
`set seed=54000+draw` in `.control` (reproducibility of this experiment
only; not paired across configs because instance counts differ).

| config | mechanism | devices | ΣWL (µm²) | area vs W=10 |
| --- | --- | ---: | ---: | ---: |
| w10 | Exp53 single | 80 | 5.20e5 | 1× |
| w20 | same-family width | 80 | 2.08e6 | ~4× |
| w10_2s2p | 2s×2p identical units | 320 | 2.08e6 | 4× |
| w10_4s4p | 4s×4p identical units | 1280 | 8.31e6 | 16× |
| w10_s4 | 4-series of R/4 | 320 | 5.19e5 | 1× (control) |

W=40 single was not used: longest divider L would exceed the existing
W=10 encoder search bound (L_max at W=20 = 7867 µm, still inside 8000 µm).

## 5. Controls

- Exp53 nominal file (exact voltage repeat).
- New W=10 nominal (must match Exp53).
- Nominal `tt` for every fabric (deterministic leftover, AGAUSS off).
- Same-area series-split (H3 falsifier).
- 1:1 invert-unit ratio primitive (not the neuron).

## 6. Results

### Nominal leftover (tt, no AGAUSS)

| config | y (V) | \|err\| (mV) | pass |
| --- | ---: | ---: | --- |
| w10 | 2.459890565832 | 0.400995 | True |
| w20 | 2.459950421434 | 0.460851 | True |
| w10_2s2p | 2.459950214853 | 0.460644 | True |
| w10_4s4p | 2.459965130621 | 0.475560 | True |
| w10_s4 | 2.459915689635 | 0.426119 | True |

All leftover values remain inside the 1 mV bar. Tiling raises leftover
by 60–75 µV (voltage-coefficient / extra internal nodes), not millivolts.

### tt_mm cell |y−z| (n=16 each, not yield)

| config | pass | mean (mV) | median (mV) | max (mV) | std (mV) | mean / w10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| w10 | 5/16 | 2.810 | 1.813 | 8.932 | 2.682 | 1.00 |
| w20 | 7/16 | 1.391 | 1.310 | 4.190 | 1.281 | 0.50 |
| w10_2s2p | 9/16 | 1.321 | 0.916 | 3.552 | 1.098 | 0.47 |
| w10_4s4p | 11/16 | 0.815 | 0.680 | 1.920 | 0.548 | 0.29 |
| w10_s4 | 0/16 | 3.344 | 3.116 | 6.866 | 1.970 | 1.19 |

1/N for N=2 is 0.50; measured 2s2p = 0.47. 1/N for N=4 is 0.25;
measured 4s4p = 0.29 (leftover floor ~0.48 mV prevents a clean 0.25).

### 1:1 invert-unit ratio |ΔR/R| (n=24, primitive)

| config | mean \|Rrel\| | max |
| --- | ---: | ---: |
| w10 | 0.1174% | 0.4028% |
| w20 | 0.0722% | 0.1979% |
| w10_2s2p | 0.1003% | 0.2805% |
| w10_4s4p | 0.0374% | 0.1219% |

Nominal tt ratio is 0.0 for every config (identical units).

## 7. Mechanism

The official body term scales as 1/sqrt(W L) per unit. An N×N array of
identical units has N² independent draws and equivalent resistance R,
so the array σ drops as 1/N. W=20 at fixed R grows L ≈ 2× and area ≈ 4×,
so body σ halves — matching the observed 2.81 → 1.39 mV.

Same-area 4-series of R/4 shortens L, raises per-unit body σ, and adds
heads. The cell got **worse** (0/16). Segmentation without area is not a
matching fix under this model.

H4 is only partly right: leftover stays <1 mV, but it rose from 0.401 mV
to 0.476 mV at 4s4p. That is a small deterministic tax, not the 1.92 mV
worst draw.

## 8. Failure analysis

4s4p still has 5/16 draws above 1 mV (worst 1.920 mV). This is remaining
random mismatch plus leftover, not a solver failure (all 80 cell draws
converged). It is not a yield number (n=16).

W=10 single remains insufficient, consistent with Experiment 53.

## 9. Promotion decision

**B — PARTIALLY VALIDATED.** Documented unit tiling improves official
`tt_mm` behavior in the direction the installed model predicts. Mean
4s4p |err| is inside the analog bar. The sample is not all-pass.
Not silicon. Not yield. Physical TIA still **NO**. Miller family stays
**CLOSED**.

## 10. Claim map

- **Demonstrated:** Exp53 nominal exact repeat; W=10 n=16 still mixed
  (5/16); 4s4p mean 0.815 mV, 11/16 pass; 2s2p ≈ W=20 at 4× area;
  same-area series-split 0/16.
- **Supported:** official 1/sqrt(WL) body averaging; leftover remains
  sub-mV for these encodes.
- **Projected:** 64× documented area (8s8p or W=20 4s4p) may put the
  worst-of-16 under 1 mV.
- **Unknown:** yield; silicon PCM; tiled R inside Network F; OPA189 +
  tiled R; temperature on tiled fabric.
- **Contradicted:** W=10 single as a matching solution; same-area
  series segmentation as a matching solution.

## 11. Next dominant bottleneck

**Primary:** random `tt_mm` tails on the 16× W=10 array (5/16 still miss).

**Secondary tracks:** leftover tax of large arrays (~75 µV); Track B
physical TIA (miller family closed); Network F insertion of PDK R.

## 12. Next experiment

Experiment 55: 64× documented area — W=10 8s×8p and/or W=20 4s×4p —
same frozen o2, same A=1e6, n≥16. Still not yield.

Decision B — 4s4p MEAN |err| IN 1 mV BAR BUT SAMPLE NOT ALL-PASS (NOT YIELD).
tt_mm is official model AGAUSS, not a foundry lot. OPA189 remains the
Level-1 TIA host. Miller family remains closed.
