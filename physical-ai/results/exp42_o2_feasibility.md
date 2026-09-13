# Experiment 42 — o2 1 mV feasibility boundary (CLOSED)

Experiments 39, 40, and 41 were not modified. No SPICE was run.
No transistor sizes were searched. No resistor geometry was changed.
Frozen weights and the 1 mV bar are unchanged. Matching is not claimed.
Projections are **not** demonstrated circuit results.

## Central question

Is the 1 mV requirement fundamentally impossible at the current
A=1e5 / W=1 implementation, or is it reachable with a legitimate
increase in amplifier gain and/or resistor geometry while preserving
the frozen o2 weights?

**At A=1e5 / W=1: impossible** (Decision C baseline unchanged).
**Theoretically reachable** with higher A and a resistor leftover
already demonstrated at the existing W=10 encode (0.604 mV).
**Not demonstrated. No design pass.**

## Established facts (not rerun)

| Item | Value | Kind |
| --- | ---: | --- |
| Target | o2 / W2[1], Rf·G = 140.89398023224967 | Exp40 baseline |
| z_o2 | +2.459489570880132 V | Exp40 baseline |
| Exp40 y / \|err\| | 2.45254388951 V / 6.945681370132 mV | Exp40 baseline |
| Ideal-R SPICE error | -2.055833 mV | Exp41 diagnostic |
| W=1 PDK vs ideal R | -4.889848 mV | Exp41 diagnostic |
| W=10 \|err\| | 1.451758 mV | Exp41 diagnostic |
| Existing Miller \|err\| | 627.252 mV | Exp41 diagnostic |
| Exp40 Decision | **C** | unchanged |

## Question 1 — required amplifier gain

Established identity:

```
k = A / (A + 1 + Rf·G)
|k · z_o2 − z_o2| <= 1e-3
A_required = z_o2 · (1 + Rf·G) / 1e-3 − 1 − Rf·G
```

| Quantity | Value |
| --- | ---: |
| Current A | 1e+05 |
| k(A=1e5) | 0.998583070735009 |
| Predicted finite-A error at A=1e5 | -3.484922749921 mV |
| A_required for 1 mV | **348844.8705716574** |
| A_required / A_current | 3.488449 |
| A_current / A_required | 0.286660 |
| Positive safety margin at current A | **no** |
| Conventional 2× A_required | 697689.741143 |
| Analytical error at 2× A_required | -0.500102 mV |

Current A is **below** A_required by a factor of
3.488. There is no safety margin above
A_required at A=1e5. This analytical A_required is **not** assumed
physically achievable in MOS.

Finite-A error at A=1e5 already exceeds the 1 mV bar under the
established k identity (3.485 mV).

## Question 2 — perfect-resistor feasibility

Analytical first. The measured-scale column scales the Experiment 41
ideal-R SPICE error as 1/(A+1+Rf·G). That column is a projection,
not a new simulation.

| A point | A | k | Analytical err (mV) | k-bar | Measured-scale err (mV) | scale-bar |
| --- | ---: | ---: | ---: | --- | ---: | --- |
| 1e5 | 100000 | 0.998583071 | -3.484923 | FAIL | -2.055833 | FAIL |
| A_required_analytical | 348845 | 0.999593412 | -1.000000 | PASS | -0.589922 | PASS |
| A_required_measured_scale | 205733 | 0.999310776 | -1.695139 | FAIL | -1.000000 | PASS |
| 1e6 | 1e+06 | 0.999858126 | -0.348937 | PASS | -0.205846 | PASS |
| 1e7 | 1e+07 | 0.999985811 | -0.034898 | PASS | -0.020587 | PASS |
| 2x_A_required_analytical | 697690 | 0.999796664 | -0.500102 | PASS | -0.295021 | PASS |

Ideal resistors + A=1e5: **FAIL** (analytical 3.485 mV; measured 2.056 mV).
Ideal resistors + A ≥ A_required: **theoretical PASS** on the k identity.
The 1.429 mV gap (ideal-R SPICE vs k·z) means the measured-scale
A_required is lower (**205733.165630**).
Neither number is a demonstrated circuit result.

## Question 3 — resistor requirement

Experiment 41 additive split, reused (not rerun):

```
(y_W1 − z) = (y_idealR − z) + (y_W1 − y_idealR)
-6.945681 mV = -2.055833 mV + -4.889848 mV
```

| Term | W=1 (mV) | W=10 (mV) |
| --- | ---: | ---: |
| A. Finite-A / ideal-fabric (measured) | -2.055833 | -2.055833 |
| B. Deterministic resistor leftover | -4.889848 | +0.604076 |
| C. Interaction (k−1)·z·ε_R at A=1e5 | +0.0069 | -0.0009 |

Interaction is microvolts and is neglected as a design term.

Once amplifier error is reduced well below 1 mV, the resistor-side
requirement is:

- **|y_PDK − y_idealR| ≤ 1.000 mV** (absolute, this vector)
- equivalently |ε_R| ≤ 4.065884e-04 (0.0407% of z_o2)
- if ~0.2 mV amplifier residual remains: leftover ≲ 0.8 mV

W=1 leftover 4.890 mV **fails** that resistor budget.
W=10 leftover 0.604 mV **meets** that resistor budget.
This is deterministic accuracy, not matching. No mismatch PDF.

## Question 4 — existing W=10 boundary

Existing W=10 signed err = -1.451758 mV, |err| = 1.451758 mV (0.451758 mV above the bar).

That remainder is consistent with residual finite-A (2.056 mV) plus
resistor leftover (+0.604076 mV):
-2.055833 + +0.604076 = -1.451758 mV
(recovers the Experiment 41 W=10 total).

If A → ∞ and leftover stays at the measured W=10 value:
|err| → **0.604581 mV < 1 mV**.

Under the additive model, W=10 theoretically crosses the bar at
A ≳ **128203.097513**.

**If amplifier gain were made sufficiently large, the existing W=10
physical resistor implementation is theoretically capable of PASS.**

It is **not** declared passed. No W=10 + high-A simulation was run.

## Question 5 — geometry requirement (direction only)

No sweep. No design change.

| Encode | Leftover vs ideal R | Infinite-A |err| | Deterministic bar |
| --- | ---: | ---: | --- |
| W=1 (Exp40) | -4.889848 mV | 4.893939 mV | FAIL |
| W=10 (Exp41 diagnostic) | +0.604076 mV | 0.604581 mV | meets bound |

Direction: increase same-family `xhigh_po` width from W=1 toward the
already-established W=10 encode. Leftover **changes sign** between
those two points, so a leftover zero exists in (1, 10) µm. Locating
it would be an optimization and is **not** performed.

### Deterministic-error geometry (this experiment)

Need |y_PDK − y_idealR| ≤ 1 mV after A is solved. Existing W=10
leftover already sits inside that bound. W=1 does not. This is **not**
evidence that matching is satisfied.

### Pelgrom / matching geometry (separate)

| Item | Value |
| --- | ---: |
| Model Pelgrom A | 0.0347 |
| Used Rf W=1 WL | 15.72 µm² |
| Used 1σ body | 0.875% |
| WL for 0.075% 1σ | 2140.604 µm² |
| 0.075% of z_o2 | 1.845 mV |

**MATCHING = UNRESOLVED.** 0.075% of this |z| is 1.845 mV, which is
a different quantity from the 1.000 mV analog bar. Do not conflate.

## Question 6 — decision tree

| Case | Configuration | Boundary | Demonstrated? |
| --- | --- | --- | --- |
| A | Ideal R + A=1e5 | **FAIL** (analytical -3.485 mV; measured -2.056 mV) | Exp41 diagnostic |
| B | Ideal R + A ≥ A_required | **theoretical PASS** (A_required = 348844.871) | **no** |
| C | Existing W=10 + sufficiently high A | **theoretically capable of PASS** (∞-A leftover +0.605 mV) | **no** |
| D | Existing W=1 + sufficiently high A | **theoretical FAIL** (∞-A leftover -4.894 mV) | implied by Exp41 split |
| E | Existing Exp39 Miller, no resize | **FAIL** (-627.3 mV) | Exp41 diagnostic; not optimized |

## Conclusion

The 1 mV bar is fundamentally missed at the current A=1e5 / W=1 implementation. It is theoretically reachable on this frozen o2 vector by raising amplifier gain and using a resistor implementation whose deterministic leftover is already at the established W=10 magnitude (0.604 mV). That is a future experiment, not a result of Experiment 42.

The current implementation fails for two independent reasons:

1. **Amplifier:** A=1e5 is below A_required. Finite-A alone fails the bar.
2. **Resistor:** W=1 leftover 4.890 mV fails even at infinite A.

Raising A cannot save W=1. Changing geometry cannot save A=1e5
(ideal R is already 2.056 mV off). Both must move.
The existing Miller implementation is Case E and is not a path
inside this experiment.

## Minimum legitimate next investigations

Not started. Not implemented.

1. Behavioral TIA at A >= A_required (or 1e6) + existing W=10 encode on frozen o2 — first demonstration candidate for Case C.
2. Behavioral TIA at high A + ideal lumped R — confirm Case B and the analytical vs measured-scale A_required gap.
3. Only after a high-A behavioral pass: a new experiment for a transistor TIA that actually delivers that A at +2.46 V. Do not treat Exp39 Miller resize as that experiment.
4. Matching remains a separate campaign. Do not invent a mismatch PDF.
5. Network-F 2.937 V hosting remains a separate voltage-range test.
6. Do not change frozen weights, the 1 mV bar, or physical parameters unless a new experiment redefines them.

## Status

- Experiment 40 Decision C: **unchanged**
- Matching: **UNRESOLVED**
- F40 classification: **NOT TESTED**
- Temperature: **NOT TESTED**
- Network-F 2.937183 V hosting: **NOT DEMONSTRATED**
- Experiment 42: feasibility boundary only; **no design pass**

No Experiment 43. No optimization.

