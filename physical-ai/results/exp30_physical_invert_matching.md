==================================================
EXPERIMENT 30
PHYSICAL INVERT PRIMITIVE AND MATCHING-TECHNOLOGY SEARCH
==================================================

Frozen Experiment 9 weights. SPICE is the source of truth.
Experiments 1–29 were not overwritten. No Python correction,
no new encoding, no Network F in MOS, no invented foundry PDK.

==================================================

1. Objective

Determine whether the remaining Architecture A invert VCVS can be
replaced by a documented physical primitive without destroying the
frozen Network F analog map, and whether a local resistor technology
exists that can host the Experiment 29 Rf·G matching requirement.

Primary analog criterion: MAE ≤ 1e-3 versus the frozen NumPy
reference. Classification is reported separately and is not analog
equivalence.

2. Frozen baseline

- Network F, Architecture A, TIA A=1e5, invert A pinned at 1e7, Vos=0
- Logical invert stages on the compiled fabric: 49 amplifiers, 98 resistors
- Nominal 40-vector MAE = 4.838e-4, acc = 1.0000 (replays Experiment 29)
- Nominal 12-vector MAE = 5.102e-4, acc = 1.0000
- Experiment 29 independent 0.5% F40 MAE ≈ 4.19e-3 (analog fail)
- Experiment 29 per-neuron Rf·G 0.5% + 15% residual F40 mean MAE ≈ 8.02e-4
- Experiment 29 invert-only 0.5% F12 MAE ≈ 2.93e-3

3. Existing physical requirements

TIA finite-A floor ≈ 4.8e-4 at A=1e5. Analog bar 1e-3. Invert plus
matching must fit in the remaining ≈ 5e-4. 200 µs sampled inference
is the Experiment 27/28 regime.

Hidden ReLU voltages on the 40-vector set reach 2.608 V (11 samples
> 2.0 V; 1 sample > 2.3 V). Stimulus |Vin| ≤ 0.999 V. Output-layer
|z2| ≤ 2.46 V. A teaching miller at ±2.5 V is inside the input range
and at the edge of the hidden range.

4. Local technology/model inventory

- PDK_ROOT unset, PDK unset
- IHP SG13G2: howto at C:\ngspice\examples\IHPOpenSourcePDK. PDK tree absent.
- SkyWater SKY130: howto and example netlists at
  C:\ngspice\examples\SkywaterOpenSourcePDK. They .lib
  D:\Spice_general\open_pdks\sky130\..., which is not present.
- CMC r2_cmc: example card present
  (C:\ngspice\examples\osdi\r2_cmc\res_r2_cmc.cir). Probe failed:
  OSDI plugin not loaded (Unable to find definition of model rmodel).
  No .osdi binaries under C:\ngspice.
- Berkeley BSIM3v3 teaching cards: present (Exp 26–28 miller). MOS only.
  No resistor model, no mismatch PDF.
- TI OPA1656 / OPA171 macromodels: present. LEVEL 3 invert control.
  Internal R_OS TC1 is not a fabric resistor family.
- ngspice default R: present. Absolute ohms only. No TC1/TC2 was added.

No usable foundry PDK or compact resistor technology is installed.
A PDK o2 Rf·G cell was not built because there is no model to host it.

5. Physical invert requirement extraction

Compiled Network F invert inventory (Architecture A, not assumed):

- 49 invert amplifiers / 98 invert resistors
- By job: 16 input (inv1…inv16), 1 Vref (invref), 32 hidden (invh1…invh32)
- R1 = 10 kΩ, R2/R1 ≈ 1.0000002 at pinned A=1e7 (invert_r2 compensation)
- Target closed-loop gain: −1
- Polarity: dest = −src
- Worst hidden load: invh22, Rload ≈ 4.91 kΩ (G ≈ 2.03e-4 S)
- Worst hidden swing: invh20, hy_max = 2.608 V, Rload ≈ 7.15 kΩ
- Representative in-range hidden: invh1, hy_max = 1.37 V, Rload ≈ 8.03 kΩ
- Lightest in-range hidden: invh12, hy_max = 1.69 V, Rload ≈ 8.90 kΩ
- Settling: existing 200 µs sampled-inference regime
- Temperature: no fabric TCR is documented

Not every invert is the same physical problem.

- Input and Vref inverts copy an already-ideal stimulus. A labeled
  polarity copy (E dest 0 src 0 −1) is a system-interface substitution,
  not a neuron amplifier.
- Hidden inverts copy a computed ReLU voltage into the next-layer
  negative-weight fabric. Those 32 stages are the invert primitive.

Finite-A sensitivity (R1 forced equal to R2; compensation removed;
12-vector F, TIA still A=1e5):

| invert A | MAE | max | analog |
| --- | --- | --- | --- |
| 1e3 | 2.340e-3 | — | fail |
| 3e3 | 1.023e-3 | — | fail |
| 1e4 | 6.243e-4 | 4.05e-3 | pass |
| 3e4 | 5.380e-4 | 3.46e-3 | pass |
| 1e5 | 5.172e-4 | 3.25e-3 | pass |
| 1e6 | 5.108e-4 | 3.17e-3 | pass |
| 1e7 | 5.102e-4 | 3.16e-3 | pass |

Pinned A=1e7 is not required for analog MAE. Uncompensated invert
A ≥ 1e4 analog-passes this 12-vector set.

Invert input-offset sensitivity (pinned invert A, 12-vector F):

| Vos | MAE | analog |
| --- | --- | --- |
| 0 | 5.102e-4 | pass |
| 22 µV | 5.652e-4 | pass |
| 100 µV | 9.078e-4 | pass |
| 214 µV | 1.505e-3 | fail |
| 1 mV | 6.037e-3 | fail |

Invert Vos must stay ≲ 100 µV to keep F inside the analog bar.
Classification stayed 1.0 through 1 mV. Classification is not analog
equivalence.

6. Candidate inventory

Ranked by documentation, then by the extracted voltage/load/gain need:

1. Keep VCVS invert (LEVEL 1/2 baseline)
2. XSPICE `limit` invert (LEVEL 2, ±15 V, documented ngspice code model)
3. Teaching miller invert (LEVEL 4, Exp 26 CMOS-OP1 W/L, ±2.5 V)
4. Miller + invert servo (Exp 28 invert_dw=0.0026 at 27 °C, not a per-input trim)
5. OPA1656 invert (LEVEL 3, ±15 V, include not copy)
6. Stimulus polarity copies for input/Vref only
7. Passive grounded divider (negative control)

No foundry invert cell is installed. W/L values were not invented;
miller sizes are the documented CMOS-OP1 / Experiment 26 card.

7. Passive alternative investigation

A resistor network to analog ground cannot implement Vout = −Vin.

KCL at a grounded tap produces a *positive* attenuation. Isolated
passive bench at Vin=2.608 V, R1=R2=10 kΩ, Rload=4.91 kΩ:

    Vout = +0.514 V    (need −2.608 V)
    |Vout+Vin| = 3.12 V

All 32 hidden inverts replaced by the same grounded tap:

    F12 MAE = 1.521, acc = 0.000

Differential subtraction still needs a physical difference element.
Charge-domain inversion is a sampled switch/C method (Experiment 27
CDS family), not a DC substitute for these 32 hidden OP stages.
Current steering changes the encoding and was not rebuilt.

Stimulus polarity copies are allowed only for Vin/Vref because those
nodes are already ideal sources. On F12 they match the VCVS baseline
to numerical noise (MAE 5.102e-4).

8. Worst-case isolated benches

Real R1=10 kΩ, R2=10 kΩ, loads from the compiled fabric.
Ideal transfer: Vout = −Vin. Analog bar |Vout+Vin| ≤ 1e-3.

| bench | Vin | |Vout+Vin| | analog | P_est |
| --- | --- | --- | --- | --- |
| VCVS R1=R2 A=1e5 | 1.5 | 3.00e-5 | pass | n/a |
| VCVS compensated A=1e7 | 2.608 | ~0 | pass | n/a |
| passive divider | 2.608 | 3.12 | fail | n/a |
| XSPICE limit | 2.608 | 5.22e-5 | pass | n/a |
| miller ±2.5 V, worst load 4.91 kΩ | 1.5 | 0.655 | fail | 0.40 mW |
| miller ±2.5 V, light load 8.9 kΩ | 1.5 | 0.205 | fail | 0.40 mW |
| miller+servo, worst load | 0.5 | 7.48e-4 | pass | 2.05 mW |
| miller ±2.5 V, worst load | 2.608 | 1.97 | fail | 0.40 mW |
| miller+servo, worst load | 1.5 | 0.655 | fail | 0.60 mW |
| miller+servo, worst load | 2.608 | 1.97 | fail | 0.61 mW |
| OPA1656 | 2.608 | 9.96e-4 | pass | 120 mW |
| miller 200 µs TRAN | 1.5 | 0.655 | fail | n/a |
| miller −40 °C (MOS .temp) | 1.5 | 0.652 | fail | 0.40 mW |
| miller 27 °C (MOS .temp) | 1.5 | 0.655 | fail | 0.40 mW |
| miller 85 °C (MOS .temp) | 1.5 | 0.656 | fail | 0.40 mW |

Miller mechanism: output-stage current / swing, not offset and not
settling. At Vin=1.5 V / 4.91 kΩ, Vout hangs near −0.85 V and Vmid
rises to 0.33 V (the loop has lost virtual ground). Servo nulls the
small-signal offset at Vin=0.5 V but does not recover 1.5 V into
4.91 kΩ. 200 µs TRAN settles to the same failed DC. MOS `.temp` moves
the already-failed error by a few mV; that is amplifier temperature,
not Rf·G.

OPA1656 isolated just meets the analog bar at the worst hidden swing
(|err|=9.96e-4). Simulated Iq·30 V ≈ 120 mW is the macromodel supply
current, not a fabric power budget.

9. Matching analysis

Invert resistors only. TIA fabric nominal. Network F, 12 vectors,
8 draws. Limited Monte Carlo, not a yield.

| mode | tol | MAE mean | worst | analog pass |
| --- | --- | --- | --- | --- |
| independent | 0.075% | 6.390e-4 | 7.149e-4 | 8/8 |
| independent | 0.15% | 9.194e-4 | 1.094e-3 | 5/8 |
| independent | 0.5% | 2.587e-3 | 3.151e-3 | 0/8 |
| independent | 1.0% | 5.095e-3 | 6.163e-3 | 0/8 |
| pair-matched | 0.075–1% | 5.102e-4 | 5.102e-4 | 8/8 |
| common-mode invert | 0.075–1% | 5.102e-4 | 5.102e-4 | 8/8 |

Pair-matched and common-mode invert *scale* are invisible: R1 and R2
move together, the ratio stays 1, closed-loop gain stays −1.

Systematic invert R2/R1 (all 49 pairs, one signed ratio error, no MC):

| R2/R1 − 1 | MAE | max | analog |
| --- | --- | --- | --- |
| −0.5% | 5.503e-3 | 2.53e-2 | fail |
| −0.15% | 1.835e-3 | 9.83e-3 | fail |
| −0.075% | 1.101e-3 | 6.49e-3 | fail |
| +0.075% | 8.815e-4 | 1.90e-3 | pass |
| +0.15% | 1.642e-3 | 4.59e-3 | fail |
| +0.5% | 5.362e-3 | 1.91e-2 | fail |

Extracted invert matching relationship:

    Preserve each invert pair's R1/R2 ratio.

    Unmatched or systematic ratio error must stay ≲ 0.075%
    to remain inside the leftover analog budget after the
    TIA finite-A floor. The signed −0.075% case is already
    over the bar (MAE 1.10e-3). Independent random invert
    mismatch of 0.075% mean-passes; 0.15% mean-passes but
    the worst draw does not.

This is the same numerical ceiling Experiment 29 reported for leftover
unmatched local error on the full fabric. It is still a SPICE threshold
on these abstractions, not a foundry ppm spec.

10. Temperature analysis

No fabric resistor TCR is documented. Default ngspice R has none;
none was invented. IHP / SkyWater / r2_cmc are not usable, so
−40 / 27 / 85 °C ratio drift of Rf·G was not simulated.

MOS `.temp` on the isolated teaching miller invert (already
drive-limited at Vin=1.5 V) gave |err| = 0.652 / 0.655 / 0.656 V
at −40 / 27 / 85 °C. That does not test Architecture A ratios.

Temperature-correlated invert-resistor drift remains unvalidated.

11. Limited full-network insertion

VCVS TIA stages were not replaced. Hidden ReLU B-sources were not
replaced. Progressive invert insertion, 12-vector F unless noted.

| insertion | MAE | max | acc | analog |
| --- | --- | --- | --- | --- |
| baseline VCVS invert | 5.102e-4 | 3.16e-3 | 1.000 | pass |
| stimulus polarity input+vref | 5.102e-4 | 3.16e-3 | 1.000 | pass |
| all hidden XSPICE limit | 5.117e-4 | 3.22e-3 | 1.000 | pass |
| polarity + hidden limit | 5.117e-4 | 3.22e-3 | 1.000 | pass |
| one in-range hidden miller (invh1) | 4.724e-4 | 3.16e-3 | 1.000 | pass* |
| one in-range hidden miller+servo | 4.887e-4 | 3.16e-3 | 1.000 | pass* |
| worst hidden miller (invh20) | 7.549e-4 | 6.73e-3 | 1.000 | pass* |
| worst hidden miller+servo | 5.243e-4 | 3.16e-3 | 1.000 | pass* |
| one worst hidden OPA1656 | 5.321e-4 | 3.16e-3 | 1.000 | pass |
| passive divider all hidden | 1.521 | 4.15 | 0.000 | fail |
| all hidden OPA1656 | 2.638e-3 | 7.04e-3 | 1.000 | fail |
| F40 polarity + hidden limit | 4.859e-4 | 3.49e-3 | 1.000 | pass |

*F MAE of a single miller insertion is not invert-transfer validation.
Isolated miller |Vout+Vin| is 0.20–1.97 V on the same primitive. One
broken hidden invert can hide inside a 16-output average. Isolated
benches are the invert source of truth.

All 32 hidden millers were not inserted: the isolated primitive
already failed the extracted swing/load requirement.

All 32 hidden OPA1656 stages analog-fail (MAE 2.64e-3) while
classification stays 1.0. Dominant mechanism: macromodel offset /
closed-loop residual stacking. Isolated one-amp |err| is already
9.96e-4; thirty-two of them do not stay inside the leftover budget.
Simulated time 113 s. Acc 1.0 is not analog equivalence.

F40 polarity + XSPICE limit MAE 4.859e-4 versus nominal 4.838e-4.
That is the LEVEL 2 invert replacement of the frozen analog map.

12. Resistor technology / PDK investigation

Directly present:

- IHP howto text. PDK_ROOT unset. ihp-sg13g2 tree absent.
- SkyWater howto + example inverter netlist pointing at a
  non-existent D:\Spice_general\open_pdks path.
- r2_cmc example card (rsh=200, tc1=1.5e-4). Those numbers are the
  example, not a foundry. The OSDI binary is not installed, so the
  card cannot be instantiated.
- Teaching-card BSIM3v3: MOS only.
- Default ngspice R: absolute value only.

Therefore Experiment 29's 0.075% local-residual requirement is still
a behavioral matching specification. It is not tied to a sheet
resistance, geometry, common-centroid layout, or foundry mismatch
PDF.

B2/B3/B4 geometry, TCR, and matching-structure tests in a real
resistor model were not run. The missing evidence is the technology
model itself, not a Monte Carlo recipe.

13. Combined error budget

| contribution | size | label |
| --- | --- | --- |
| frozen ideal dump | numerical | carry-over |
| behavioral TIA A=1e5 | F40 MAE 4.84e-4 | carry-over / this run |
| invert VCVS → XSPICE limit (all hidden + polarity) | F40 MAE 4.86e-4 | directly simulated |
| invert finite A (R1=R2) A=1e4 | F12 MAE 6.24e-4 | directly simulated |
| invert Vos = 100 µV | F12 MAE 9.08e-4 | directly simulated |
| invert Vos = 214 µV | F12 MAE 1.50e-3 | directly simulated |
| invert pair-matched any tested scale | F12 MAE 5.10e-4 | directly simulated |
| invert systematic |R2/R1−1| = 0.075% | F12 MAE 8.81e-4 / 1.10e-3 | directly simulated |
| invert independent 0.5% | F12 mean MAE 2.59e-3 | directly simulated |
| one OPA1656 hidden invert | F12 MAE 5.32e-4 | directly simulated |
| all 32 OPA1656 hidden inverts | F12 MAE 2.64e-3 | directly simulated |
| isolated miller at fabric load/swing | \|err\| 0.20–1.97 V | directly simulated |
| Exp 29 Rf·G 0.5% + 15% residual | F40 mean 8.02e-4 | behavioral carry-over |
| leftover unmatched local ≲ 0.075% | Exp 29 ceiling | inferred; invert systematic agrees |
| resistor TCR / foundry mismatch | — | not validated (no model) |
| MOS invert of every hidden node at 2.61 V | — | not validated; isolated fails |
| full-F 200 µs TRAN with physical inverts | — | not validated (DC OP insertion; isolated TRAN only) |

Do not stack the unvalidated PDK row onto a passing LEVEL 2 invert
and call the analog map physically hosted.

14. What passed

- Nominal F40 replay
- Input/Vref stimulus polarity copies
- XSPICE `limit` on all 32 hidden inverts (F12 and F40 analog-pass)
- Isolated XSPICE limit at Vin=2.608 V
- Isolated OPA1656 at Vin=2.608 V (just inside 1e-3)
- One worst-hidden OPA1656 insertion
- Invert pair-matched and common-mode scale (invisible)
- Invert A ≥ 1e4 with R1=R2
- Invert Vos ≤ 100 µV
- Miller+servo only at Vin=0.5 V into 4.91 kΩ (offset-limited case)

15. What failed

- Passive invert (isolated and all-hidden F)
- Teaching miller invert at the extracted hidden swing/load
  (output drive / swing; servo does not fix it; 200 µs is not the issue)
- All 32 hidden OPA1656 (MAE 2.64e-3; classification still 1.0)
- Independent invert 0.5%
- Systematic invert ratio |0.15%| and −0.075%
- Invert Vos = 214 µV
- Any PDK-backed Rf·G temperature or mismatch test (no model)

Preserved useful failures: passive KCL bound; miller drive/swing bound;
OPA network-scale offset stacking; F MAE hiding a broken invert.

16. What remains ideal

- Architecture A TIA E-sources (not rebuilt here)
- Hidden ReLU B-sources
- Vin / Vref stimulus, except the labeled polarity copies
- Default ngspice resistors (no TCR, no geometry, no mismatch PDF)
- Invert VCVS on any stage not replaced in a given insertion

17. Physical realism level

- LEVEL 2 XSPICE `limit` invert: documented structured replacement.
  Preserves the frozen F analog map. Not a transistor.
- LEVEL 3 OPA1656 invert: documented macromodel. Isolated one-amp
  analog-passes; thirty-two hidden stages do not.
- LEVEL 4 teaching-card miller invert: same Experiment 26 card, not a
  PDK, not silicon. Isolated invert transfer fails at fabric load/swing.
- No LEVEL 5 / 6.
- No resistor technology above default ngspice R.

18. Limitations

- Limited Monte Carlo (8 draws); not a yield
- IHP / SkyWater / r2_cmc OSDI not usable here
- Teaching miller rails ±2.5 V; W/L were not invented to “fix” swing
- Network F was not transistorized
- Full-F 200 µs TRAN with physical inverts was not run
- OPA1656 120 mW is macromodel Iq, not a die power claim
- Experiment 29 matching abstractions were not rebuilt

19. Experiment 31 recommendation

Do not rebuild the encoding. Do not edit frozen weights. Do not
transistorize Network F. Do not invent TCR or mismatch PDFs.

Chosen direction: B. The physical invert primitive is the next
dominant bottleneck.

LEVEL 2 `limit` can hold the analog map, but that is the same
realism class as the remaining TIA VCVS. The documented transistor
invert cannot drive ~4.9 kΩ to hidden y ≈ 2.61 V. The documented
LEVEL 3 macromodel cannot replace all 32 hidden stages inside the
analog bar. Making the invert more physical currently destroys the
map or the invert transfer.

Experiment 31 should search for a *documented* invert whose output
can meet the extracted hidden load/swing (or prove that no local
model can). Do not invent ±5 V / ±15 V MOS supplies for the 0.35 µm
teaching card. Do not treat F MAE of one miller insertion as invert
validation.

A parallel gap remains: install a documented PDK (IHP SG13G2 or
SkyWater howto exists; PDK_ROOT is unset) and repeat the o2 Rf·G
cell with that resistor family. That is direction C. It was not
chosen as dominant because the physical invert still cannot implement
the extracted 32 hidden stages.

20. Final status

PHYSICAL INVERT PRIMITIVE PARTIALLY VALIDATED

Next direction: B. Physical invert primitive is the next dominant bottleneck

Answers:

1. Can the behavioral invert VCVS be replaced by a physically
   documented primitive without destroying the frozen map?
   LEVEL 2 XSPICE limit: yes (F40 MAE 4.86e-4). LEVEL 3 all-hidden
   OPA1656: no (MAE 2.64e-3). LEVEL 4 teaching miller: no
   (isolated |err| up to 1.97 V). One-stage F insertion can hide
   a broken invert.

2. Actual invert requirements: 32 hidden gain=−1 stages; Vin ≤ 1 V;
   hy to 2.61 V; worst load 4.91 kΩ; 200 µs; invert A ≳ 1e4 if
   R1=R2; invert Vos ≲ 100 µV; R1/R2 residual ≲ 0.075%. Input/Vref
   inverts do not need a transistor amplifier.

3. Passive / ratio-only invert: no. Demonstrated, not only argued.

4. Matching relationship: preserve each invert pair's R1/R2 ratio.
   Common-mode pair scale is invisible. Systematic or unmatched
   ratio ≲ 0.075%.

5. Documented resistor PDK locally: no. Howtos only.

6. Does its resistor behavior support Experiment 29? Not testable.

7. Missing technology evidence: installed IHP or SkyWater tree,
   resistor TCR, geometry parameters that the model actually
   supports, a mismatch mechanism the model actually provides,
   and a compiled r2_cmc OSDI plugin. Do not invent those.

SPICE is the source of truth. Frozen Experiment 9 weights were not edited.
