# Experiment 57 — xhigh_po leftover diagnosis

Experiments 1–56 were not modified. Behavioral TIA A=1e6. Official `tt`
only (no AGAUSS). No resistor fitting.

**Status: DEMONSTRATED**
**Decision A — LEFTOVER IS VOLTAGE-COEFFICIENT + ENCODE vs IDEAL R, NOT tt_mm**
**Realism: Level 4 PDK resistors + Level 0 behavioral TIA. Not silicon.**

The script classifier labeled this `ratio` because |err| shrinks at
small scale. The vs-ideal residual is **superlinear in |z|** — voltage
coefficient on top of the Experiment 43 geometry leftover.

## 1. Objective

Is the +0.48 mV large-array leftover random mismatch, a constant offset,
a linear ratio error, or voltage-dependent encode error?

## 2. Baseline

W=10 A=1e6 y = 2.459890565832 (Exp53 exact).
W=20 8s8p y = 2.459968223476 (Exp56 exact).

## 3. Hypothesis

H1: leftover is leftover `tt_mm` (contradicted if `tt` shows it).
H2: leftover is constant offset (err independent of scale).
H3: leftover is linear ratio (err ∝ z).
H4: leftover is xhigh_po voltco + heads (err vs ideal grows faster than z).

## 4. Method

Same frozen o2 / vec 19. Scale hidden voltages by 0.10 / 0.25 / 0.50 / 1.00.
z(s) = s·(z0 − b2) + b2. Fabrics: ideal R, W=10 single, W=20 8s8p.
A=1e6, `.lib`/official tt, no `tt_mm`.

## 5. Controls

Ideal-R finite-A. Analytic k = A/(A+1+Rf·G) = 0.999858126.

## 6. Results

### Full-scale (s=1) decomposition

| term | mV |
| --- | ---: |
| analytic k·z − z | −0.349 |
| measured ideal R − z | −0.206 |
| W=10 − ideal R | **+0.607** |
| W=20 8s8p − ideal R | **+0.684** |
| W=20 8s8p − W=10 | +0.078 |
| W=10 − z | +0.401 |
| W=20 8s8p − z | +0.479 |

W=10 − ideal = **+0.607 mV** matches Experiment 43 leftover
(+0.604 to +0.607 mV).

### Scale sweep err (mV)

| fabric | s=0.10 | s=0.25 | s=0.50 | s=1.00 |
| --- | ---: | ---: | ---: | ---: |
| ideal − z | −0.023 | −0.053 | −0.104 | −0.206 |
| W=10 − z | −0.021 | −0.012 | +0.062 | +0.401 |
| W=20 8s8p − z | −0.020 | −0.010 | +0.072 | +0.479 |
| W=10 − ideal | +0.002 | +0.042 | +0.166 | +0.607 |
| W=20 8s8p − ideal | +0.003 | +0.043 | +0.176 | +0.684 |

Ideal − z is linear in z (finite A). PDK − ideal is **superlinear**
(0.002 / 0.042 / 0.166 / 0.607). Linear 0.607·s would be
0.061 / 0.152 / 0.304 / 0.607.

At small swing, finite-A (negative) wins and |y−z| is tens of µV.
At vec 19 full swing, voltco + encode (positive) wins.

## 7. Mechanism

Official xhigh_po body has documented voltage coefficients (`bp2`, `bq2`,
`Efac`). Heads and weff set a geometry leftover even at V≈0 (tiny at
s=0.1). Array tiling adds ~78 µV more leftover vs W=10, not millivolts
of mismatch.

H1 contradicted (`tt` only). H2 contradicted (sign flips with scale).
H3 incomplete (superlinear). H4 supported.

## 8. Failure analysis

No SPICE failure. The 15/16 `tt_mm` misses in Experiments 55–56 sit on
this signed, swing-dependent floor plus a small tail.

## 9. Promotion decision

**A — DEMONSTRATED.** The analog floor is deterministic xhigh_po
voltco/encode, not official mismatch. Stop enlarging arrays as the
primary path. Physical TIA **NO**. Miller family **CLOSED**.

## 10. Claim map

- **Demonstrated:** W=10 leftover vs ideal +0.607 mV (Exp43 repeat);
  leftover superlinear in |z|; large-array tax +78 µV; small-signal
  |err| tens of µV.
- **Supported:** documented voltco is the extra full-swing term.
- **Projected:** OPA189 + tiled R will show the same leftover floor
  on vec 19; other F40 vectors with smaller |z| will look better.
- **Unknown:** other documented resistor families; Network F with PDK R.
- **Contradicted:** leftover is `tt_mm`; leftover is a DC offset;
  more area removes leftover.

## 11. Next dominant bottleneck

**Primary:** deterministic xhigh_po leftover / voltco on the worst-case
vector (~+0.40 to +0.48 mV vs z, +0.61 mV vs ideal).

**Secondary:** residual `tt_mm` tails; Track B TIA; Network F insertion.

## 12. Next experiment

Experiment 58: OPA189 Level-1 TIA on a leftover-limited tiled fabric
(W=10 8s8p or W=10 4s4p). State leftover as the analog floor. A few
`tt_mm` draws with `mc_mm_switch=1` on the official R include. Not silicon.

Decision A — LEFTOVER IS VOLTAGE-COEFFICIENT + ENCODE vs IDEAL R, NOT tt_mm.
OPA189 remains the Level-1 TIA host. Miller family remains closed.
