# Experiment 39 - first real SKY130 PDK isolated cell (o3)

Frozen Experiment 9 weights. SPICE is the source of truth.
Experiments 1-38 were not overwritten. Teaching BSIM3 was not used as a PDK.

Controlling identity: `results/exp39_identity_correction.md`.
Historical deck names remain `circuits/exp39_o2/*`. Those files were not rerun
or edited. They implement **o3 / W2[2]**, not catalog o2.

## Decision: C - PDK EXPOSES A TECHNOLOGY LIMIT

- Automated `decide()` (first run, terminal log): **C**.
- Published follow-up decision **B** is **withdrawn**. It is retained here
  only as history. It was not permitted by `decide()` or by analog-pass.
- Official SKY130A open_pdks `1689ac3f2dc763876eaf967227c7dfe831b031ae` ran
  in ngspice-47.
- Simulated isolated cell = **o3 / W2[2]**. Simulated Rf·G = **7.803810**.
  z_ref = **−2.162419 V** (F40 vector 18). err = y_SPICE − z_o3.
- Critical catalog o2 = **W2[1]**, Rf·G = **140.893980**. o2 was **NOT**
  transistorized or simulated. Withdrawn: any claim that o2 was hosted,
  measured, or passed.
- Length-encoded W=1 um xhigh_po + behavioral TIA: |err| = 5.924e-3.
  tt/ll/hh are identical (common-mode process cancels).
- W=10 um encode |err| = 2.274e-3. SKY130 5V miller (no servo) DC |err| =
  1.663e-3; 200 us TRAN |err| = 1.667e-3.
- Analog bar 1e-3 was **not** met on any promoted inference path.
- Matching remains **UNRESOLVED**. Not silicon. Network F was not built.

No invented PDK/device/process parameters were used.

## Identity truth table (A / B / C)

| Quantity | True o2 (B, catalog) | Simulated o3 (A, SPICE) | Network (C, software) |
| --- | ---: | ---: | ---: |
| W2 index | 1 | 2 | — |
| Rf·G | 140.893980 | 7.803810 | — |
| Gtot (S) | 4.226819e-3 | 2.341143e-4 | — |
| Imax (uA) | 202.805 | 234.114 | 234.114 max (o3) |
| \|z\|max (V) | 2.459490 | 2.162419 | 2.937183 (h25) |
| Analog \|y−z\| | not simulated | measured; bar FAIL | not run |
| Matching 0.075% | UNRESOLVED | UNRESOLVED | — |

Class A = o3 SPICE. Class B = catalog o2. Class C = network software.
Do not read 140.893980 as a measured value of the SPICE cell.
2.937183 V is a software/network requirement result, not a measured
SKY130 transistor output.

## 1. Executive summary

This experiment crossed from feasibility documentation into a real open PDK.
SKY130A primitives were installed from official ciel-releases tarballs and
simulated on isolated **o3**. Same-family poly resistors track process
corners, but length-encoded geometry leaves a systematic leftover at W=1 um
(|err| = 5.924e-3, ~0.27% of |z_o3|). Wider devices reduce it. A 5V miller
TIA closes the loop and settles in 200 us with |err| = 1.667e-3, still
above the analog bar. Monte Carlo mismatch at the used Rf area is far above
the 0.075% leftover target. The cell is a LEVEL 1 model demonstration, not
silicon. Catalog o2 was extracted and is not this SPICE cell.

## 2. PDK installation / provenance

- Manager: ciel 2.6.1 (FOSSI). Windows extract used official `.tar.zst` files
  because ciel's temporary-directory cleanup raced the Windows file lock.
- Source: `https://github.com/fossi-foundation/ciel-releases/releases/download/sky130-1689ac3f2dc763876eaf967227c7dfe831b031ae/`
- Assets used: `common.tar.zst`, `sky130_fd_pr.tar.zst` only (no standard cells).
- Install path: `C:\dev\pdk` (outside the git repo). Junctions `sky130A` / `sky130B`.
- Simulator: ngspice-47, `.spiceinit` with `ngbehavior=hsa`, `skywaterpdk`, KLU.
- Teaching BSIM3, ASAP7, and hand-made cards were not substituted.

## 3. Exact PDK version

- Family: sky130 / variant sky130A
- open_pdks / ciel hash: `1689ac3f2dc763876eaf967227c7dfe831b031ae`
- ciel current file records that hash.

## 4. Model inventory

| Device | Official name | Used |
|---|---|---|
| High-R poly | `sky130_fd_pr__res_xhigh_po` | yes, all isolated-o3 resistors |
| 5V NFET | `sky130_fd_pr__nfet_g5v0d10v5` | yes, miller |
| 5V PFET | `sky130_fd_pr__pfet_g5v0d10v5` | yes, miller |
| MIM | `sky130_fd_pr__cap_mim_m3_1` | area calc from `camimc` only; Cc lumped |
| Corners | tt, ll, hh, tt_mm | yes |

Labeled non-PDK: ideal `Ibias`, invert VCVS, Vin/Vref sources, **lumped**
servo C / **lumped** miller Cc.

## 5. Frozen extraction (o2 catalog vs o3 cell)

- Model: `models/scaling/F.npz` seed 9. Shape 16-32-16.
- **Class B (catalog o2, W2[1], NOT simulated):** Rf = 33333.333 ohm.
  Gtot = 4.226819e-3 S. Rf·G = 140.893980. |z|max = 2.459490 V.
  Imax = 202.805 uA.
- **Class A (simulated o3, W2[2]):** Rf = 33333.333 ohm (same TIA scale).
  Gtot = 2.341143e-4 S. Rf·G = 7.803810. L1 = 7.8038.
  Imax = 234.114 uA. z_ref = **−2.162419 V** on F40 vector 18.
- **Class C:** network software |z|max = h25 **2.937183 V**.
- Withdrawn: "test vector = max |z_o2|" and "Rf·G 140.894 measured on the
  SPICE cell."

## 6. Resistor characterization

Official card: rsheet = 2000 ohm/sq, body tc1 = -1.47e-3, Pelgrom A = 0.0347,
tnom = 25 C. Mismatch is `MC_MM_SWITCH * AGAUSS * A/sqrt(W*L)`.
body tc1 is a **card parameter**, not a measured circuit-level TCR.
Circuit-level TCR: **NOT TESTED**.

Measured W=1 um xhigh_po at 1 V (single device, not the o2 network):

| T (C) | L=15.72 um R (ohm) |
|---:|---:|
| -40 | 36999 |
| 27 | 33334 |
| 85 | 30796 |

L=16.67 um at 27 C: 35348 ohm (matches the model equation used for geometry).
Corners at L=15.72, 27 C: tt 33334, ll 28334, hh 38334 (process scale, not local mismatch).
Voltage at L=15.72, 27 C: 0.2 V / 1.0 V / 2.5 V = 33341 / 33334 / 33274 ohm.

LEVEL 1 (model) + LEVEL 2 (card documentation).

## 7. Rf*G cell (o3)

Every isolated-o3 logical resistor was replaced by `res_xhigh_po` at the same
family. Invert VCVS remains behavioral. Geometry is same-W length encoding,
not extracted common-centroid layout.

W=1 um: |Vout − z_o3| = 5.924e-3 at 27 C. **tt = ll = hh**. Common-mode
process cancels. The leftover is systematic (heads + voltage coefficient vs
length). W=10 um: |err| = 2.274e-3. Wider/longer devices reduce the leftover
but do not meet 1e-3. These errors characterize **o3**, not catalog o2.

## 8. TIA topology

Two-stage Miller, 5V FETs, dual +/-2.5 V. Ideal 80 uA Ibias (labeled).
**Lumped** Cc = 2 pF. Servo uses **lumped** 1 nF (hybrid/external). DW = 0
(no invented offset null). Neither capacitor is a demonstrated physical MIM
instance.

## 9. TIA transistor sizing

From this PDK: NFET W=5 um L=1.0 um, Vgs=1.5 V, Vds=2.5 V, |Id| = 132.04 uA.
L = 1.0 um = 2 * documented 5V Lmin 0.50 um (bin exists).
Scaled for 80 uA tail: WT=3.029, WD=WL=6.059, WON=12.118, WOP=24.236 um.

Open-loop OP with both inputs at 0 sat near **-2.31 V** (large model offset).
Closed-loop still regulates. Quiescent |Idd| = 329 uA (one TIA, inputs 0).
OL gain extraction: **NOT TESTED** (`gain_max_abs` was null).

## 10. DC results (o3, z_ref = −2.162419 V)

| Test | y (V) | \|err\| | Analog pass |
|---|---:|---:|---|
| PDK R + behavioral TIA tt 27 C | -2.15649 | 5.924e-3 | no |
| same, ll / hh | identical | 5.924e-3 | no |
| PDK R W=10 um | -2.16014 | 2.274e-3 | no |
| miller no-servo 27 C | -2.16076 | 1.663e-3 | no |
| miller + servo DC | -2.19436 | 3.194e-2 | no (integrator DC is not the inference OP) |

## 11. Transient results (o3)

Behavioral PDK-R fabric, step at t=0, sample at t_stop (wrdata; print-after-tran
was not parseable):

| t_stop | \|err\| |
|---:|---:|
| 100 us | 5.924e-3 |
| 200 us | 5.924e-3 |
| 500 us | 5.924e-3 |
| 1 ms | 5.924e-3 |

Settled by 100 us on this o3 + behavioral TIA. Miller no-servo 200 us:
|err| = 1.667e-3 (matches its DC).

## 12. Temperature

PDK R + behavioral TIA on **o3**, tt (fabric |err| only):

| T | \|err\| |
|---:|---:|
| -40 C | 6.636e-3 |
| 27 C | 5.924e-3 |
| 85 C | 5.896e-3 |

Single-device R(T) is in §6. Miller temperature sweep: **NOT TESTED**.
Circuit-level TCR: **NOT TESTED**.

## 13. Leakage

Miller input ammeter at 27 C: **4.4e-19 A**. Far below the 13 nA architecture
ceiling. 85 C FET leakage: **NOT TESTED**.

## 14. Capacitor feasibility

`camimc` typical = 2.00e-15 F/um2 (official r+c card).
This is a **density/area estimate**, not a layout and not a simulated MIM.

| C | Area |
|---|---|
| 1 pF | 0.0005 mm2 (realistic) |
| 10 pF | 0.005 mm2 (realistic) |
| 100 pF | 0.05 mm2 (large but possible) |
| 1 nF | 0.5 mm2 (impractical on-die) |
| 2 nF | 1.0 mm2 (impractical on-die) |

2 nF ≈ 1 mm². Experiment 28 stack 5 nF/neuron = 2.5 mm2 at this density.
In-circuit Cc and servo C remain **lumped**.

## 15. Mismatch / Monte Carlo

PDK provides `tt_mm` / `mc_mm_switch` / AGAUSS. **MONTE CARLO SUPPORTED**
at n=20 on o3 + behavioral TIA (resistor AGAUSS). MOS mismatch: **NOT TESTED**.
MC n>=100: **NOT TESTED**.

n=20, isolated o3, PDK R + behavioral TIA, tt_mm, 27 C:

- MAE = 0.0196 V
- max = 0.0501 V
- std = 0.0119 V
- p95 = 0.0399 V

Used Rf WL = 15.7 um2. Model Pelgrom sigma ≈ **0.875%** (1σ body ΔR/R).
Target leftover 0.075% needs WL ≈ **2141 um2** (2140.604 um2 unrounded).
**MATCHING FEASIBILITY UNRESOLVED** at the geometry used.
This does not demonstrate that catalog o2 meets 0.075%.
LEVEL 1 only. Not a foundry yield. Not LEVEL 3 silicon.

## 16. Power

One miller TIA (inputs 0): |Idd| = 329 uA on +/-2.5 V → ~1.65 mW rail product
(|I|*5 V). Not chip power. Not OPA189 macromodel Iq. Resistor dissipation
on the o3 vector was not separately integrated.

## 17. Requirement comparison

| Metric | Exp37 requirement | Result | Class | Status |
|---|---:|---|---|---|
| Catalog o2 Rf*Gtot | ~140.9 | 140.893980 | B | catalog only; **not measured** on the SPICE cell |
| Simulated cell Rf*Gtot | (o2 was intended) | 7.803810 | A | measured on **o3** |
| residual ratio error | <=0.075% | UNRESOLVED (Pelgrom 0.875% at used Rf; MC n=20 MAE 0.0196) | A/B | UNRESOLVED |
| output swing | network software 2.937183 V; catalog o2 2.459490 V | o3 \|z_ref\| = 2.162419 V fits +/-2.5 V; 2.937183 V is software, not a SKY130 Vout | A vs C | network C fails +/-2.5 V; o3 A does not clip |
| current | 234.114 uA is network-max I (o3); o2 Imax = 202.805 uA | 5V FET Id 132.04 uA at W=5 L=1; tail sized 80 uA | A/B/C | FET Id measured; tail user-selected |
| gain | ~1e5 behavioral / 4.88e4 analog | behavioral a_eff=1e5; miller OL sat at -2.31 V | A | OL gain extraction **NOT TESTED** |
| settling | <=200 us | o3 behav settled by 100 us; miller 200 us matches its DC | A | measured on o3 |
| leakage | ~13 nA ceiling | 4.4e-19 A at 27 C | A | 85 C FET leak **NOT TESTED** |
| temperature | -40...85 C | o3 fabric \|err\| exercised; leftover remains | A | miller vs T **NOT TESTED**; circuit TCR **NOT TESTED** |
| capacitor | 1-2 nF previous | 2 nF = 1.0 mm2 at 2 fF/um2 | estimate | density only; Cc/servo C **lumped** |
| mismatch | technology-dependent | tt_mm n=20; UNRESOLVED vs 0.075% | A | MOS mismatch **NOT TESTED**; n>=100 **NOT TESTED** |
| F40 classification | 100% (prior mixed-level) | — | — | **NOT TESTED** |

## 18. Demonstrated vs documented vs unknown

| Property | Claim level | Note |
|---|---|---|
| SKY130 in ngspice | LEVEL 1 | this experiment |
| xhigh_po rsheet/TCR/Pelgrom | LEVEL 1+2 | official model card; circuit TCR NOT TESTED |
| MIM 2 fF/um2 | LEVEL 2 | camimc typical; area estimate only |
| 5V FET family | LEVEL 2 | g5v0 device docs + bins |
| isolated o3 PDK R map | LEVEL 1 | analog bar not met |
| isolated o2 PDK R map | not demonstrated | **withdrawn** |
| SKY130 miller TIA | LEVEL 1 | not silicon; 27 C only |
| 0.075% leftover | UNRESOLVED | used area too small in the model |
| 85 C FET leak | NOT TESTED | not a separate bench |
| silicon PCM | not LEVEL 3 | no measured silicon |
| F40 / classification / chip | NOT TESTED | forbidden here |

## 19. Limitations

- One isolated **o3** cell only. Catalog o2 was not simulated.
- Invert / ReLU remain behavioral.
- Ideal Ibias is not a PDK current source.
- Miller Cc and servo C are **lumped**.
- Open-loop miller sat; closed-loop is the inference result.
- Length encoding leaves a systematic leftover; W=10 helps, does not finish it.
- No layout extraction.
- Historical filenames still say `o2`; identity is o3.

## 20. Final decision

**C - PDK EXPOSES A TECHNOLOGY LIMIT**

`decide()` requires analog_pass (`|y−z| <= 1e-3`) on a PDK-R or miller
inference DC row for letter B. Every promoted inference path failed that
bar, so `decide()` returned **C**. Follow-up hardcoded **B** is withdrawn.

What was demonstrated: official SKY130A models; isolated frozen **o3**;
common-mode corner cancel; 200 us settle-to-DC on this fabric; analog bar
FAIL; matching UNRESOLVED.

What was not demonstrated: catalog o2; analog pass; leftover 0.075%;
measured 2.937183 V on a SKY130 node; on-die MIM for 1-2 nF.

Next investigation (not started here): the **actual catalog o2** cell
(W2[1], Rf·G = 140.893980) on official SKY130A, with PDK-justified resistor
area and/or a map that can host software |z|max = 2.937183 V inside a
documented 5 V span. Do not transistorize Network F. Do not invent a
mismatch PDF.
