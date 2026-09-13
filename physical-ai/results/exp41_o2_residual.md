# Experiment 41 — o2 residual decomposition (CLOSED diagnostic)

Experiments 39 and 40 were not modified. Weights and the 1 mV bar were not
changed. Diagnostics are not a design solution. Experiment 40 Decision **C**
is unchanged.

## Central question

Why is the actual critical o2 cell 6.946 mV from z_o2, and which portion is
the current PDK resistor implementation versus the amplifier implementation?

## Baseline (Experiment 40, not rerun)

| Item | Value | Kind |
| --- | --- | --- |
| Target | o2 / W2[1], Rf·G = 140.89398023224967 | Exp40 baseline |
| z_o2 | +2.459489570880132 V | Exp40 baseline |
| y | 2.45254388951 V | Exp40 baseline |
| err / \|err\| | −6.945681370132295 mV | Exp40 baseline |
| Analog bar 1.000 mV | **FAIL** | Exp40 baseline |
| Decision | **C** | unchanged |

## Step 1 — finite-A (analytical, before any new SPICE)

k = A / (A + 1 + Rf·G) = **0.998583070735** at A = 1e5.

| Quantity | Voltage | Error vs z_o2 |
| --- | ---: | ---: |
| Software z_o2 | 2.459489570880 V | 0 |
| Predicted k·z | 2.456004648130 V | **−3.484923 mV** |
| Exp40 SPICE y | 2.452543889510 V | −6.945681 mV |
| Unexplained vs k·z | — | **−3.460759 mV** |

**Can finite-A plausibly explain 6.946 mV? No.** It predicts 3.485 mV
(50.2% of the total) and **already exceeds the 1 mV bar** even if resistors
are ideal. The simple identity over-predicts the ideal-fabric error (see
ideal-R SPICE below).

## Diagnostics (controlled, not design solutions)

Identity: SIM_TARGET = o2 / W2[1]. Compiler row W2[1] only.

| Configuration | Kind | y (V) | err (mV) | \|err\| (mV) | \|err\|≤1 mV |
| --- | --- | ---: | ---: | ---: | --- |
| Ideal lumped R + behavioral TIA | controlled diagnostic | 2.457433737388 | −2.055833 | 2.056 | no |
| W=1 PDK R + behavioral TIA | Exp40 baseline | 2.452543889510 | −6.945681 | 6.946 | no |
| W=10 same-family encode + behavioral TIA | controlled diagnostic | 2.458037812913 | −1.451758 | 1.452 | no |
| Exp39 5 V Miller, no resize, W=1 PDK R | controlled diagnostic | 1.832237285033 | −627.252 | 627.252 | no |

W=10 does **not** pass the analog bar. Do not treat it as a solution.
Miller does **not** close the o2 loop within 1 mV (a_eff ≈ 245; Idd ≈ 564 µA;
input current 3.4e−19 A). It does not demonstrate headroom for software
Network-F 2.937183 V.

## Additive split of the Experiment 40 residual

```
(y_W1 − z) = (y_idealR − z) + (y_W1 − y_idealR)
−6.945681 mV = −2.055833 mV + −4.889848 mV
```

- **Amplifier + ideal fabric** (behavioral A=1e5, lumped catalog R): **2.056 mV**
- **PDK W=1 xhigh_po vs those ideal R**: **4.890 mV**
- Sum recovers the Experiment 40 residual exactly.

## Mechanism table

| Mechanism | Predicted contribution | Measured contribution | Residual explained |
| --- | ---: | ---: | ---: |
| Finite A | −3.485 mV (k·z − z) | −2.056 mV (ideal-R SPICE − z) | Amplifier/ideal-fabric share of Exp40; **cannot** explain 6.946 mV |
| Resistor heads / length encoding | L-encode matches R_target in the V=0 card equation | W=1 vs ideal R: **−4.890 mV**; W=10 vs ideal R: **+0.604 mV** | Primary PDK share of Exp40 at W=1 |
| Voltage coefficient | Card voltco; common-mode Rf·G cancel | Rf W=1: R(0.2 V)=33334.37 Ω, R(2.45 V)=33270.79 Ω, ΔR/R=−0.191% | Partial; leftover is **differential** VC / heads vs L, not a global scale |
| Transistor operating point | Not in Exp40 baseline | Miller y=1.832 V, \|err\|=627 mV | **Not** the Exp40 6.946 mV mechanism |
| Interaction | Finite-A and PDK leftover add in y−z | 2.056 + 4.890 = 6.946 mV | Explains Exp40 total |
| Other | Invert VCVS; tnom 25 C vs .temp 27 C | ideal-R − k·z = **+1.429 mV** | Simple k·z is not exact SPICE identity |

## Geometry sensitivity (not optimization)

| W (µm) | \|y−z\| (mV) | y − y_idealR (mV) |
| ---: | ---: | ---: |
| 1 (baseline) | 6.946 | −4.890 |
| 10 (diagnostic) | 1.452 | +0.604 |

W=10 reduces deterministic PDK leftover versus ideal R to well under 1 mV,
but **\|y−z\| remains 1.452 mV** because the ideal-R fabric is already
2.056 mV from z. **Geometry alone cannot put \|y−z\| under 1 mV** at A=1e5
without changing gain or compensating finite-A (that would be a new design
experiment, not done here).

Deterministic-error geometry ≠ Pelgrom/matching geometry. Used Rf W=1
WL ≈ 15.72 µm², model body σ ≈ 0.875% (1σ). **MATCHING = UNRESOLVED.**

## Conclusion

The 6.946 mV Experiment 40 residual is **not** a single “technology limit”
and **not** an identity bug.

It is the sum of:

1. **Amplifier implementation** (uncompensated A=1e5 on Rf·G = 140.894),
   measured as **2.056 mV** on ideal catalog resistors — already above 1 mV.
2. **PDK W=1 xhigh_po implementation** (heads / length encoding / differential
   VC), measured as **4.890 mV** versus that ideal-R bench.

Finite-A cannot explain the full 6.946 mV. The official SKY130A W=1 encode
is the larger share. W=10 shrinks the PDK share but still **FAIL**s the bar.
The existing Miller, unre-sized, does **not** close this +2.46 V o2 vector.

## Status

- Experiment 40 Decision C: **unchanged**
- Matching: **UNRESOLVED**
- F40 classification: **NOT TESTED**
- Temperature: **NOT TESTED**
- Network-F 2.937183 V hosting: **NOT DEMONSTRATED**
- W=10 / Miller: diagnostics only

No Experiment 42. No optimization.
