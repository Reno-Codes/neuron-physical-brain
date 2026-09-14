# Experiment 55 — 64× documented resistor area under tt_mm

Experiments 1–54 were not modified. Behavioral TIA A=1e6. Official
SKY130 `tt_mm` AGAUSS, not foundry yield. No resistor fitting.

**Status: PARTIALLY VALIDATED**
**Decision B — w10_8s8p MEAN IN BAR, PASS 15/16 (NOT YIELD)**
**Realism: Level 4 PDK resistors + Level 0 behavioral TIA. Not silicon.**

## 1. Objective

Does 64× documented area — W=10 8s×8p or W=20 4s×4p — put the frozen
o2 `tt_mm` sample all inside 1 mV, or does leftover now dominate the
remaining misses?

## 2. Baseline

Experiment 54 W=10 4s×4p nominal y = 2.459965130621 repeated exactly
(Δy = 0). Independent 4s4p n=16: 10/16, mean 0.806 mV, max 2.248 mV
(Exp54 was 11/16, mean 0.815 mV — same mechanism).

## 3. Hypothesis

H1: 8s8p (N=8, 1/N = 0.125 vs W=10) continues the 1/N trend and may
all-pass.
H2: leftover ~+0.48 mV occupies half the high-side 1 mV budget, so
positive tails fail first.
H3: W=20 4s4p (64×, 1280 devices) matches 8s8p (64×, 5120 devices).
H4: W=20 2s2p (16×, 320 devices) matches Exp54 4s4p.

## 4. Method

Same frozen o2 / vec 19 / A=1e6 / official tt and tt_mm as Experiment 54.
`set seed=55000+draw`.

| config | area vs W=10 | devices | ΣWL (µm²) |
| --- | ---: | ---: | ---: |
| w10_4s4p | 16× | 1280 | 8.31e6 |
| w20_2s2p | 16× | 320 | 8.34e6 |
| w20_4s4p | 64× | 1280 | 3.33e7 |
| w10_8s8p | 64× | 5120 | 3.32e7 |

## 5. Controls

- 4s4p nominal exact Exp54 repeat.
- Independent 4s4p `tt_mm` sample.
- W=20 2s2p as a cheaper 16× control.

## 6. Results

### Nominal leftover (all PASS)

| config | y (V) | \|err\| (mV) |
| --- | ---: | ---: |
| w10_4s4p | 2.459965130621 | 0.475560 |
| w20_2s2p | 2.459963984492 | 0.474414 |
| w20_4s4p | 2.459967375665 | 0.477805 |
| w10_8s8p | 2.459968859764 | 0.479289 |

Leftover is pinned near +0.48 mV for every large array.

### tt_mm cell (n=16, not yield)

| config | pass | mean (mV) | max (mV) | std (mV) |
| --- | ---: | ---: | ---: | ---: |
| w10_4s4p | 10/16 | 0.806 | 2.248 | 0.700 |
| w20_2s2p | 12/16 | 0.764 | 2.200 | 0.685 |
| w20_4s4p | 14/16 | 0.638 | 1.432 | 0.403 |
| w10_8s8p | 15/16 | 0.530 | 1.360 | 0.355 |

### Signed 8s8p errors

z = +2.459489570880 V. Nominal leftover = **+0.479 mV**.
14/16 draws have y > z. The single fail is draw 11: y = 2.460849 V,
err = **+1.360 mV** (leftover plus a positive tail). Two draws sit
slightly below z (−0.070, −0.167 mV) and still pass.

High-side room in the 1 mV bar is only 1.000 − 0.479 = **0.521 mV**.

## 7. Mechanism

Area averaging continues: 16× → 64× drops mean 0.806 → 0.530 mV and
max 2.25 → 1.36 mV. W=20 4s4p (1280 devices) is close to 8s8p (5120
devices) — width plus array can replace raw instance count.

H2 is supported: leftover is a signed offset, so the analog bar is
one-sided. Matching is no longer the only limiter.

H3 is partly true (14/16 vs 15/16). H4 is supported (12/16 vs Exp54 11/16).

## 8. Failure analysis

The remaining 8s8p miss is not a solver failure. It is leftover +
positive AGAUSS. Further area should shrink the tail; it will not
remove the +0.48 mV floor.

## 9. Promotion decision

**B — PARTIALLY VALIDATED.** 64× documented area puts 15/16 draws
inside 1 mV. Not all-pass. Not yield. Not silicon. Physical TIA **NO**.
Miller family **CLOSED**.

## 10. Claim map

- **Demonstrated:** 4s4p Exp54 repeat; 8s8p 15/16 mean 0.530 mV;
  leftover floor +0.48 mV on large arrays; W=20 4s4p 14/16.
- **Supported:** leftover makes the 1 mV bar one-sided; 1/N still
  acts on the random part.
- **Projected:** W=20 8s8p (256× vs W=10) may clear the last tail.
- **Unknown:** yield; silicon; OPA189 + large array; Network F.
- **Contradicted:** “more tiling removes leftover”; leftover is
  geometry/voltco, not AGAUSS.

## 11. Next dominant bottleneck

**Primary:** signed leftover (~+0.48 mV) plus residual `tt_mm` tails
on 64× arrays.

**Secondary:** Track B TIA (miller closed); Network F PDK-R insertion.

## 12. Next experiment

Experiment 56: W=20 8s×8p (256× vs W=10, 5120 devices — same instance
count as 8s8p). If the last tail dies, leftover is the remaining
analog limiter. Still not yield.

Decision B — w10_8s8p MEAN IN BAR, PASS 15/16 (NOT YIELD).
tt_mm is official model AGAUSS, not a foundry lot. OPA189 remains the
Level-1 TIA host. Miller family remains closed.
