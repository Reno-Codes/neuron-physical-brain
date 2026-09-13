==================================================
EXPERIMENT 31
HIDDEN-INVERTER DRIVE REQUIREMENT AND PHYSICAL
OUTPUT-STAGE SEARCH
==================================================

Frozen Experiment 9 weights. SPICE is the source of truth.
Experiments 1–30 were not overwritten. No Python correction,
no new encoding, no Network F in MOS, no invented foundry PDK.

==================================================

1. Objective

Determine why one OPA1656 hidden invert analog-passes on Network F
while 32 fail, and extract the minimum physical output-stage
requirements of the 32 hidden Architecture A invert stages.

Primary analog criterion: MAE ≤ 1e-3 versus the frozen NumPy
reference. Classification is reported separately.

2. Frozen baseline

- Network F, Architecture A, TIA A=1e5, invert A=1e7, Vos=0
- 32 hidden invert stages; R1=10 kΩ; target gain −1
- Nominal 12-vector MAE = 5.102e-4, acc = 1.0000
- Experiment 30 F40 XSPICE limit invert MAE ≈ 4.86e-4
- Experiment 30 1× OPA1656 MAE = 5.321e-4 (pass)
- Experiment 30 32× OPA1656 MAE = 2.638e-3 (fail, acc 1.0)

3. Experiment 30 anomaly reproduction

Reproduced on the same 12-vector set before any new candidate:

| case | MAE | max | acc | analog |
| --- | --- | --- | --- | --- |
| all 32 hidden XSPICE limit | 5.117e-4 | 3.22e-3 | 1.000 | pass |
| 1 hidden OPA1656 (invh20) | 5.321e-4 | 3.16e-3 | 1.000 | pass |
| 32 hidden OPA1656 probed | 2.638e-3 | 7.04e-3 | 1.000 | fail |

This is the Experiment 30 anomaly. Classification stays 1.0 on the
failing 32-OPA circuit. Classification is not analog equivalence.

4. Physical inverter scaling curve

OPA1656 inserted on the hy-max-ranked hidden stages, remaining
inverts stay VCVS. Shared ±15 V supplies.

| N | MAE | max | analog |
| --- | --- | --- | --- |
| 1 | 5.321e-4 | 3.16e-3 | pass |
| 2 | 5.544e-4 | 3.29e-3 | pass |
| 4 | 6.157e-4 | 3.33e-3 | pass |
| 8 | 7.155e-4 | 3.44e-3 | pass |
| 16 | 1.446e-3 | 5.87e-3 | fail |
| 32 | 2.638e-3 | 7.04e-3 | fail |

The curve is gradual, not a single-stage step. Analog MAE crosses
1e-3 between 8 and 16 simultaneous OPA inverts. That is identical
per-invert residual accumulating into the 16-output average, not a
sudden interaction at N=32.

5. Worst-stage ranking

On the 32-OPA circuit, every hidden invert has essentially the same
transfer error:

    |Vout + Vin| ≈ 996 µV
    |Vmid|       ≈ 498 µV

independent of that stage's Vin, load, or estimated current.
A_eff = |Vout|/|Vmid| therefore *tracks Vin* and is not an open-loop
gain measurement. The invert mid node is a **constant ~498 µV
virtual-ground pedestal** — the same number Experiment 24 reported
as OPA1656 TIA Vsum.

Worst-stage ranking by err MAE is therefore almost flat. The error
does not concentrate on invh20 (swing) or invh22 (load).

6. Failure mechanism hypotheses

H1 finite output current — not the OPA 1-vs-32 mechanism.
OPA isolated analog-passes at Vin=2.608 V into 7.15 kΩ and delivers
the required ~0.63 mA. Supported for the teaching miller, which
collapses at that load.

H2 output swing — not the OPA mechanism. OPA rails ±15 V. Supported
for the teaching miller (±2.5 V, isolated |err| = 1.77 V).

H3 finite closed-loop gain — rejected as the 32-OPA mechanism.
Behavioral 32-hidden A=5e3 (R1=R2) MAE = 6.79e-4 (analog-pass),
not 2.64e-3. Isolated A_eff ≈ 5234 was Vout/Vmid with Vmid stuck
at 498 µV, not a 5e3 open-loop amplifier.

H4 effective offset accumulation — supported.
Behavioral 32-hidden Vos=500 µV MAE = 2.667e-3 versus 32-OPA
MAE = 2.638e-3. Model Vos=8.75 µV MAE = 5.09e-4 (harmless).
One OPA passes because a single ~1 mV invert error is lost in the
16-output MAE. Sixteen copies cross the analog bar.

H5 linear Rout — not the miller collapse and not the OPA pedestal.
Series Rout of 4.9 kΩ on 32 hidden VCVS (A=1e5) still analog-passes
(MAE 5.13e-4) because Rout is inside the loop. Miller failure is
output-stage saturation, not a linear Thevenin resistance.

H6 supply interaction — rejected.
32 independent ±15 V supplies: MAE = 2.637665658484964e-3.
Shared supplies: MAE = 2.637665658484948e-3.
Identical to numerical noise.

H7 convergence artifact — rejected. OP completed, no convergence
warnings, 126 s.

H8 shared analog ground — not separately supported. H6 already
splits the supplies; the pedestal remains inside each macromodel.

Experiment 30 interpretation update: the 32-OPA analog fail is not
"the OPA is not good enough at drive." It is 32 copies of the
documented GWL virtual-ground residual (~498 µV), which is above
the invert Vos ceiling of ~100 µV.

7. Output current requirement

First-order |I| = |Vin| (1/R2 + 1/Rload):

    peak = 0.626 mA (invh20 at hy=2.608 V, Rload=7.15 kΩ)
    next = 0.597 mA (invh22 at its hy_max, Rload=4.91 kΩ)

Isolated VCVS sense current at those points: 0.626 mA and 0.596 mA.

Behavioral Imax on all 32 hidden inverts (F12):

| Imax | MAE | analog |
| --- | --- | --- |
| 50 µA | 1.56 | fail |
| 100 µA | 1.86 | fail |
| 200 µA | 1.14 | fail |
| 400 µA | 5.12e-4 | pass |
| 630 µA | 5.12e-4 | pass |
| 1 mA | 5.12e-4 | pass |

Extracted:

    per-invert current capability ≳ 0.40 mA
    for analog-pass on this 12-vector set

    worst-case isolated peak ≈ 0.63 mA

    simultaneous total at peak-all-hidden (not observed on F40)
    ≲ 32 × 0.63 mA = 20 mA; typical-vector sum is lower
    (probed 32-OPA mean |I| per stage ~ 50 µA)

This is a requirement extraction. It is not a physical circuit.

8. Output voltage requirement

Software hidden y max on F40 = 2.608 V. Behavioral rail-limited
32-hidden invert (XSPICE limit):

| |rail| | MAE | analog |
| --- | --- | --- |
| 1.0 V | 0.168 | fail |
| 1.5 V | 4.36e-2 | fail |
| 2.0 V | 2.20e-3 | fail |
| 2.5 V | 5.12e-4 | pass |
| 3.0 V | 5.12e-4 | pass |
| 15 V | 5.12e-4 | pass |

Absolute |Vout| ≳ 2.5 V analog-passes this set. That is not
headroom. A teaching miller supplied at ±2.5 V still fails because
the output stage cannot use those rails into 4.9–7.2 kΩ.

9. Output resistance requirement

Series Rout *inside* a high-A invert loop, 32 hidden, F12:

| Rout | MAE | analog |
| --- | --- | --- |
| 1 Ω | 5.12e-4 | pass |
| 10 Ω | 5.12e-4 | pass |
| 100 Ω | 5.12e-4 | pass |
| 1 kΩ | 5.12e-4 | pass |
| 4.9 kΩ | 5.13e-4 | pass |

Linear closed-loop Rout up to the load itself is tolerated if the
amplifier stays linear at A=1e5. The teaching miller does not stay
linear: isolated A_eff ≈ 0.95 at Vin=2.61 V. The quantitative Rout
ceiling is therefore "remain in the linear region," not a kohm
Thevenin number.

10. Gain and offset requirement

Hidden-only (input/Vref inverts stay ideal). R1=R2 for the A sweep.

| hidden A | MAE | analog |
| --- | --- | --- |
| 1e3 | 2.01e-3 | fail |
| 3e3 | 8.64e-4 | pass |
| 5e3 | 6.79e-4 | pass |
| 1e4 | 5.68e-4 | pass |
| 1e5 | 5.12e-4 | pass |

| hidden Vos | MAE | analog |
| --- | --- | --- |
| 0 | 5.12e-4 | pass |
| 8.75 µV | 5.09e-4 | pass |
| 22 µV | 5.15e-4 | pass |
| 100 µV | 6.91e-4 | pass |
| 214 µV | 1.16e-3 | fail |
| 500 µV | 2.67e-3 | fail |
| 1 mV | 5.40e-3 | fail |

Isolated (Exp 30, all 49 inverts): A ≳ 1e4, Vos ≲ 100 µV.
Simultaneous hidden-only: A ≳ 3e3 still analog-passes; Vos ≲ 100 µV
is unchanged. The 32-OPA pedestal (~498 µV) is 5× that Vos ceiling.

11. Multi-instance interaction tests

| test | MAE | analog |
| --- | --- | --- |
| 32 OPA shared ±15 V | 2.638e-3 | fail |
| 32 OPA independent ±15 V | 2.638e-3 | fail |
| 32 hidden VCVS A=5e3 | 6.79e-4 | pass |
| 32 hidden Vos=500 µV | 2.667e-3 | fail |
| 32 hidden Vos=8.75 µV | 5.09e-4 | pass |

There is no supply interaction. The 1-vs-32 anomaly is N copies of
the same macromodel VG residual.

12. Candidate inventory

| candidate | L | swing | drive | offset | suitability |
| --- | --- | --- | --- | --- | --- |
| XSPICE limit | 2 | ±15 V | unlimited | programmable | Exp 30 F40 analog-pass. Not physical. |
| OPA1656 | 3 | ±15 V | isolated pass | mid=498 µV | Isolated analog-pass; 16+ instances fail. |
| OPA1611 | 3 | ±15 V | isolated pass | isolated \|err\|=576 µV | Better isolated than 1656; still above the 100 µV Vos budget if the residual is a pedestal. Not 32-tested. |
| Teaching miller | 4 | ±2.5 V | fail 4.9 kΩ | DW=0.0026 | Isolated invert transfer destroyed. |
| Miller+follower | 4 | ±2.5 V | same rails | two millers | Isolated still fails (0.655 V / 1.77 V). |
| Imax/Rout/rail VCVS | 2 | swept | swept | optional | Requirement only. Not promoted. |

13. Physical output-stage experiments

| bench | Vin | \|Vout+Vin\| | analog |
| --- | --- | --- | --- |
| VCVS I-sense, worst swing | 2.608 | 5.16e-5 | pass |
| VCVS I-sense, worst Rload | 1.965 | 3.89e-5 | pass |
| OPA1656 worst swing | 2.608 | 9.96e-4 | pass |
| OPA1611 worst swing | 2.608 | 5.76e-4 | pass |
| miller worst swing | 2.608 | 1.77 | fail |
| miller+follower 1.5 V / 4.91 kΩ | 1.5 | 0.655 | fail |
| miller+follower worst swing | 2.608 | 1.77 | fail |

A documented miller follower inside the invert loop does not repair
drive/swing at ±2.5 V. One miller+follower F insertion analog-passes
MAE (5.35e-4) while the isolated invert is broken — the Experiment 30
warning stands. 4/16 miller+follower insertions were not run.

No physical candidate met the promotion rule (isolated worst-case
pass and 16 simultaneous physical inverters without unexplained
scaling failure).

14. Dynamics

Isolated OPA1656 TRAN at 100 / 200 / 500 µs: |Vout+Vin| = 9.96e-4,
equal to the OP. The invert is settled. Settling is not Network F
analog equivalence. Full-F TRAN with 32 OPA was not repeated.

15. Power

32-OPA last i(Vdd) from the probed run is macromodel static supply
current at a 30 V span, not board or silicon power. Isolated OPA1656
was ~120 mW (Exp 30). 32 × that Iq is not a promotion metric and is
not chip power.

16. Combined error budget

Directly simulated: invert transfer, Imax, rails, Rout, hidden A/Vos,
OPA 1–32 scaling, invert probes, independent supplies, miller and
miller+follower isolated, OPA TRAN.

Carry-over: TIA A=1e5 floor ≈ 4.8e-4, Exp 29 Rf·G matching, Exp 30
F40 limit invert.

Not validated: foundry resistor mismatch, TCR, MOS Network F, silicon
layout, chip power.

Do not stack a LEVEL 2 Imax pass with an OPA isolated pass and call
32 physical inverts validated.

17. What passed

- Exp 30 reproduction (limit, 1 OPA, 32 OPA)
- OPA scaling curve
- Vos=500 µV behavioral reconstruction of the 32-OPA MAE
- Independent-supply mechanism test (null result)
- Imax / rail / Rout / hidden A / hidden Vos extraction
- Isolated OPA1656 and OPA1611 invert transfer (just / comfortably inside 1e-3)
- Isolated VCVS current measurement (0.626 mA peak)

18. What failed

- 16 and 32 hidden OPA1656 (analog MAE; acc still 1.0)
- Teaching miller invert at fabric load/swing
- Miller + documented miller follower
- Hidden Vos = 214 µV
- Behavioral |rail| ≤ 2.0 V
- Behavioral Imax ≤ 200 µA
- Passive invert (Exp 30; not reopened)

19. What remains ideal

- Architecture A TIA E-sources
- Hidden ReLU B-sources
- Input/Vref invert VCVS except where replaced
- Default ngspice resistors

20. Physical realism level

LEVEL 2 requirement carriers. LEVEL 3 OPA1656/OPA1611. LEVEL 4
teaching miller and miller+follower. No LEVEL 5/6.

21. Limitations

- Most sweeps are 12-vector F; F40 limit is Experiment 30 carry-over
- Invert current on F is estimated from node voltages except isolated Vsense
- OPA1611 was not scaled to 16/32 (isolated residual still 576 µV)
- W/L and rails were not invented
- Network F was not transistorized

22. Experiment 32 recommendation

Do not rebuild the encoding. Do not transistorize Network F. Do not
invent W/L or MOS supplies.

The 1-vs-32 OPA question is answered. The remaining gap is that no
*documented* physical invert meets all of: 0.63 mA, |Vout|≳2.5 V
with headroom, invert Vos≲100 µV at 32 instances.

Experiment 32 should either (i) accept the LEVEL 2 XSPICE limit
invert as the Architecture A invert and host Experiment 29 on a
documented resistor PDK, or (ii) obtain a documented amplifier whose
invert virtual-ground residual stays ≲ 100 µV under the hidden load
and then repeat the 1–16–32 scaling rule. Do not treat F MAE of one
OPA insertion as invert validation. Do not retrain.

23. Final status

PHYSICAL HIDDEN INVERTER NOT YET VALIDATED

Next direction: D. Available documented device models are insufficient
to implement the extracted hidden-inverter requirements. The 1-vs-32
OPA question is answered: identical VG residual accumulates; it is
not a supply interaction.

Answers:

1. Why 1 OPA passes and 32 fail?
   Each OPA invert has a ~498 µV mid pedestal (~996 µV Vout+Vin),
   matching Exp 24 TIA Vsum. One copy is hidden in F MAE. Sixteen
   copies cross 1e-3. Independent supplies do not change the MAE.
   Behavioral Vos=500 µV reproduces 2.64e-3.

2. Output current? ≳ 0.40 mA per invert for F12 analog-pass;
   worst-case isolated peak 0.63 mA.

3. Output swing? Absolute |Vout| ≳ 2.5 V on this set. Teaching-card
   ±2.5 V still lacks headroom/drive.

4. Max Rout? Linear closed-loop series R up to 4.9 kΩ analog-passes
   at A=1e5. The miller is not in that linear regime.

5. Gain and offset? Hidden-only A ≳ 3e3 analog-passes; Vos ≲ 100 µV
   still binds (214 µV fails). 32-instance requirement is the Vos
   ceiling, not the isolated A_eff number.

6. Simultaneous interaction? No supply interaction. Yes, N-copy
   accumulation of an intrinsic macromodel residual.

7. Can any documented physical primitive meet this?
   Not in this environment. LEVEL 2 limit can. LEVEL 3 OPA cannot
   at N≥16. LEVEL 4 miller cannot isolated.

SPICE is the source of truth. Frozen Experiment 9 weights were not edited.
