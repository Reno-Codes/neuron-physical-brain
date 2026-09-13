==================================================
EXPERIMENT 26
DEVICE-LEVEL PHYSICAL NEURON PRIMITIVE
==================================================

Frozen Experiment 9 weights. SPICE is the source of truth.
Experiments 1–25 were not overwritten. No Python correction of SPICE.
No per-weight calibration. No new neural encoding.

## 1. Objective

Determine whether one realistic transistor-level analog neuron primitive
can meet the Experiments 22–25 electrical requirements on the worst
Network F neuron (o2), using modeled semiconductor devices rather than
an ideal gain block, without editing frozen weights.

## 2. Requirements inherited from Experiments 22–25

- Worst neuron o2: Rf·G_tot ≈ 140.9, G_phys ≈ 4.23 mS
- Analog bar: |Vlin − z| ≤ 1e-3 (classification reported separately)
- Uncorrected |Vos| ceiling ~22 µV; 214 µV is the representative raw offset
  a summing-node servo must correct
- Bias/leakage ~13 nA analog ceiling without correction
- Sampled inference dwell ~200 µs (Exp 25); servo slower than the TIA
- 0.5% local R is the known analog floor once offset is solved (~4e-3 network)

## 3. Selected transistor model(s)

NMOS/PMOS: Berkeley BSIM3v3 v3.3.0 teaching cards shipped with ngspice
(`C:\ngspice\examples\xspice\see\CMOSOpAmp\modelcard.nmos` / `C:\ngspice\examples\xspice\see\CMOSOpAmp\modelcard.pmos`). Included, not copied.

Card limits printed on the models: L 0.35–20 µm, W 0.6–20 µm, Tox = 9 nm,
Tnom = 27 °C, kt1/ute present. Teaching circuit CMOS-OP1 uses L = 1.4 µm.

IHP SG13G2 / PSP103 is documented in ngspice `IHP-PDK-howto.txt` but
PDK_ROOT is unset and the OpenVAF osdi models are not installed.
Not used. Not invented as a substitute.

## 4. Selected topology

Two-stage Miller CMOS OTA as the TIA (CMOS-OP1 polarity: diode load on IN−,
second-stage PMOS common-source, Miller Cc from first-stage IN+ drain to out).
A second miller is a leaky inverting integrator servo from Vsum onto TIA IN+.

Rejected after measurement:
- 5-transistor OTA servo: output common-mode rails to VDD for Rload ≥ 1 MΩ
  (~10 µA offset current). Cannot sit at analog ground 0.
- Telescopic-cascode first stage at ±2.5 V: |Vlin−z| = 4.1765e+00
  (collapsed; insufficient headroom/bias). Not promoted.

## 5. Why the topology was selected

It is the documented ngspice CMOS-OP1 teaching amplifier, dual-supply adapted
so analog ground remains node 0 (Architecture A summing node). Smallest
credible virtual-ground block that uses actual BSIM devices, Rf, and the
frozen o2 resistor fabric. The purpose is not a commercial op-amp.

## 6. Device parameters actually used

- L = 1.4 µm (CMOS-OP1 teaching length)
- W from CMOS-OP1: diff 2.8, tail 5.0, load 2.8, out 14.5 / 17.4 µm
- Multiplicity m_diff=2, m_tail=2, m_out=4 (drive current; drawn W ≤ 20 µm)
- TIA Ibias = 40 µA (CMOS-OP1 used 12 µA; scaled for TIA current under 4.23 mS)
- Servo Ibias = 20 µA
- Cc = 2 pF
- TIA DW = 0.00185: unity-gain buffer null at Vin=0 (teaching-pair systematic
  imbalance). Not per-weight calibration.
- Servo DW = 0.001487: inverting-amp null at Vin=0. Required because the first
  design left Vsum stuck at the servo miller's own ~100 µV Vos → ~10 mV Vlin
  error on o2 (independent of input). Diagnosed, then nulled. Still not
  per-weight calibration.
- Servo Rin = 50000 Ω, Rleak = 1e+08 Ω, C = 1.0e-09 F
  (tau ≈ Rin·C = 5.0e-05 s)
- Drawn MOS area proxy: TIA 238.0 µm², servo 29.68 µm²
  (W·L·m on the teaching card; not die area)

## 7. Bias conditions

- Dual rails, default ±2.5 V (3.3 V-class card). Analog ground 0 V.
- Ideal Ibias into a MOS diode (remaining ideal; labeled).
- Operating temperature 27 °C unless swept.

## 8. Unit-cell schematic / netlist

Frozen Architecture A fabric (weight resistors, fine-bank dividers,
behavioral invert VCVS) → summing node n1p.
Vn1ib (0 V ammeter) → miller IN−.
Miller TIA OUT = n1lin, Rf = 1/G_WEIGHT from n1lin to n1p.
Vosinj in series with servo output to TIA IN+.
Servo: Rin from n1p to n1sint, miller inverting amp (IN+=0, IN−=n1sint),
Rleak || C from n1sint to n1srv.

Circuits: `circuits/device_neuron/`.

## 9. Worst-neuron loading

- o2 (primary): Rf·G_tot = 140.8940, G_phys = 4.2268e-03 S
- h16: Rf·G_tot = 4.9158
- h21: Rf·G_tot = 39.7878
- extra light neuron h31: Rf·G_tot = 4.9461
- Isolated o2 fabric: 80 logical resistors

## 10. Virtual-ground performance

Closed-loop neural error is the criterion, not headline open-loop A.

| case | |Vlin−z| | Vsum | A_eff=|Vlin/Vsum| | analog |
| --- | --- | --- | --- | --- |
| o2 no-servo | 7.9704e-02 | -9.5274e-04 | 1.73e+03 | False |
| o2 miller+servo | 5.6283e-05 | -6.6876e-07 | 2.58e+06 | True |

No-servo miller A_eff ≈ 1.73e3 under 4.23 mS — far below Exp 22 A ≳ 5e4 —
and analog-fails (|err| ≈ 8.0e-2). With the miller servo, residual Vsum ≈
-6.6876e-07 V and |Vlin−z| ≈ 5.6283e-05 (analog-pass).
Unity-gain buffer Vos after TIA DW null:
-4.1312e-06 V. Simple Rin=Rf TIA |err| vs −0.5 V:
5.7028e-04.

Open-loop DC with inn grounded rails the second stage; it is not used as
the neural figure of merit.

## 11. Offset performance

Vosinj is a series source in the IN+ path (circuit-level). SPICE Vlin is
compared to frozen z with no affine correction.

| Vos inject | |Vlin−z| | Vsum | Vsrv | analog |
| --- | --- | --- | --- | --- |
| 0.0000e+00 | 5.6283e-05 | -6.6876e-07 | 1.0067e-03 | True |
| 2.2000e-05 | 5.5159e-05 | -6.5542e-07 | 9.8474e-04 | True |
| 2.1402e-04 | 4.5354e-05 | -5.3898e-07 | 7.9284e-04 | True |
| 1.0000e-03 | 5.2200e-06 | -6.2368e-08 | 7.3703e-06 | True |

214 µV representative raw offset is corrected. 1 mV inject also analog-passes
on this isolated o2 bench. Correction range at DC ≥ 1 mV at 27 °C, ±2.5 V.
Raw no-servo Vsum = -9.5274e-04 V; corrected Vsum = -6.6876e-07 V.

## 12. Servo performance

MOS miller leaky integrator, not an ideal G-source integrator.
First servo DW (= TIA DW 0.00185) left Vsum ≈ +121 µV for every input vector
(servo miller Vos). That is 121 µV × (1+Rf·G_tot) ~ 10 mV on o2 — analog-fail.
Separate inverting-amp DW null (0.001487) dropped residual Vsum to
-6.6876e-07 V. Startup TRAN uses .ic v(n1srv)=0; with C=1 nF the
loop acquires within the 100 µs dwell window on o2.

## 13. Dynamic settling

Step TRAN (0 → max-|z|, delay 200 µs): |err|=5.6338e-05,
max |Vsum| during the edge = 2.0115e-02 V (expected spike),
final analog-pass.

| dwell | |Vlin−z| | Vsum final | E≈P·t (J) | analog |
| --- | --- | --- | --- | --- |
| 100 µs | 5.8995e-05 | 3.1498e-07 | 3.1526e-07 | True |
| 200 µs | 5.6286e-05 | 3.5091e-07 | 6.3052e-07 | True |
| 500 µs | 5.6286e-05 | 3.5334e-07 | 1.5763e-06 | True |
| 1000 µs | 5.6280e-05 | -1.6917e-06 | 3.1526e-06 | True |

With C=1 nF (tau ≈ 50 µs, slower than the miller TIA, faster than Exp 25's
behavioral 10 µs–vs–1 kHz conflict), 100 µs, 200 µs, 500 µs, and 1 ms all
analog-pass on this o2 step. C=5 nF required ≥ 500 µs (measured in an earlier
pass of this experiment; not the promoted operating point).

Multi-input 200 µs (zero → maxabs → neg → pos): max |err| = 2.4649e-04,
all_pass = True.

## 14. Resistor mismatch

Statistical model: each compiled resistor independently uniform in ±tol.
Tiled model: ±tol/√n_units with R_unit = 10 kΩ. Not extracted layout.
o2 fabric: 80 logical resistors, 1145 unit elements.

| tol | model | N | mean |Vlin−z| | max |Vlin−z| |
| --- | --- | --- | --- | --- |
| 0.00% | lumped | 1 | 5.6283e-05 | 5.6283e-05 |
| 0.10% | lumped | 6 | 6.9220e-04 | 1.0707e-03 |
| 0.25% | lumped | 6 | 3.7210e-03 | 8.1109e-03 |
| 0.50% | lumped | 6 | 1.0203e-02 | 1.9727e-02 |
| 1.00% | lumped | 6 | 1.5354e-02 | 2.6467e-02 |
| 0.50% | tiled | 6 | 6.9323e-03 | 9.2092e-03 |

0.1% lumped analog-passes this isolated o2 vector (MAE 6.9e-4).
0.25% and 0.5% analog-fail. 0.5% tiling reduces MAE from 1.02e-2 to 6.93e-3
but does not recover 1e-3. After offset is solved, resistor matching remains
the analog floor — same conclusion as Experiments 24–25, now on the MOS cell.

## 15. Transistor mismatch

BSIM3 teaching card has no foundry mismatch PDF. Geometric DW on the TIA
diff pair is the explicit variation (servo DW held at its inverting null).

| TIA DW | |Vlin−z| | Vsum | analog |
| --- | --- | --- | --- |
| 0.00000 | 1.0529e-04 | -1.2507e-06 | True |
| 0.00185 | 5.6283e-05 | -6.6876e-07 | True |
| 0.01000 | 1.5960e-04 | 1.8950e-06 | True |
| -0.01000 | 3.7025e-04 | -4.3972e-06 | True |

±1% DW on the TIA pair still analog-passes with the servo on. Device mismatch
is not the dominant analog error once the servo miller is nulled.

## 16. Supply sweep

| rails | |Vlin−z| | Vsum | P_sim (W) | analog |
| --- | --- | --- | --- | --- |
| ±1.65 V | 1.9383e-01 | -2.3111e-03 | 2.0389e-03 | False |
| ±2.5 V | 5.6283e-05 | -6.6876e-07 | 3.1526e-03 | True |
| ±3.3 V | 9.3638e-04 | 1.1197e-05 | 4.2351e-03 | True |
| ±5.0 V | 2.5907e-03 | 3.0972e-05 | 6.6521e-03 | False |
| ±15.0 V | 1.2813e-02 | 1.5316e-04 | 2.4271e-02 | False |

±2.5 V is the operating point. ±3.3 V analog-passes on o2 but is already
above a 3.3 V-class abs-max if interpreted as |Vds|~6.6 V. ±1.65 V clips
o2 |z| ≈ 1.73 V. ±5 V and ±15 V are overvoltage negative controls for Tox=9 nm;
they also analog-fail. Do not take ±15 V as an integrated-system rail.

## 17. Temperature

`.temp` uses kt1/kt2/ute on the teaching card. Not a foundry industrial model.

| T | |Vlin−z| | Vsum | analog |
| --- | --- | --- | --- |
| -40.0 °C | 4.0447e-03 | 4.8350e-05 | False |
| 27.0 °C | 5.6283e-05 | -6.6876e-07 | True |
| 85.0 °C | 4.8168e-03 | -5.7572e-05 | False |

The DW/servo null is at 27 °C. −40 °C and 85 °C analog-fail (~4e-3).
Temperature is a real remaining limitation of this primitive.

## 18. Simulated power

o2 miller+servo: Idd = 6.3052e-04 A, I(Vss) = 5.7867e-04 A,
P = |Idd|·(VDD−VSS) = 3.1526e-03 W ≈ 3.15 mW.
Approximate energy at 200 µs dwell: 6.3052e-07 J ≈ 630.52 nJ.

Label: transistor-level simulated power of ONE isolated neuron in ngspice.
Not Network F, not board power, not silicon power. Invert VCVS currents are
behavioral extras and are not included as a physical invert stage.

## 19. Analog MAE

Isolated-neuron |Vlin−z| (linear, frozen z). Analog bar 1e-3.

o2 vectors:
| step | z | Vlin | |err| | Vsum | analog |
| --- | --- | --- | --- | --- | --- |
| zero | 3.2213e-02 | 3.2207e-02 | 5.9901e-06 | -7.1513e-08 | True |
| unit | -1.6331e-01 | -1.6331e-01 | 2.6946e-07 | -3.5775e-09 | True |
| maxabs | 1.7286e+00 | 1.7285e+00 | 5.6283e-05 | -6.6876e-07 | True |
| pos | 1.7286e+00 | 1.7285e+00 | 5.6283e-05 | -6.6876e-07 | True |
| neg | -6.2892e-01 | -6.2891e-01 | 1.3618e-05 | 1.6135e-07 | True |

Other neurons (max-|z| vector, miller+servo):
| tag | Rf·G_tot | |err| | Vsum | analog |
| --- | --- | --- | --- | --- |
| h16 | 4.9158e+00 | 2.4414e-06 | 3.7270e-07 | True |
| h21 | 3.9788e+01 | 1.6593e-05 | 5.4326e-07 | True |
| h31 | 4.9461e+00 | 4.9946e-06 | -7.7383e-07 | True |

o2 no-servo analog_pass=False. o2 servo analog_pass=True.

## 20. Classification

Network F was not built from transistors (forbidden by the experiment brief).
Isolated linear o2 is not an argmax classifier. Sign(Vlin) vs sign(z) on the
five representative vectors: preserved.
Neuron-level analog pass/fail is the metric that applies.

## 21. Failure mechanisms

- 0.5% lumped resistor mismatch on isolated o2: mean |Vlin−z| ≈ 1.02e-2 (tiled 6.93e-3). Analog floor after offset is solved.
- Temperature: DW/servo null is at 27 °C; −40 °C and 85 °C analog-fail (~4e-3).
- ±1.65 V clips o2 |z| ≈ 1.73 V (headroom).
- ±5 V and ±15 V are overvoltage for Tox=9 nm teaching card; analog also degrades.
- Telescopic cascode at ±2.5 V collapsed (headroom/bias).
- 5T OTA servo output common-mode rails for high-Z load.
- BSIM3 teaching card gate current is 0; the 13 nA leakage requirement is not device-validated.
- IHP SG13G2 is not installed; this is not a foundry PDK and not silicon.

## 22. Comparison against behavioral L/A primitive

- LEVEL 2 behavioral TIA A=1e5 Vos=0 on the same o2 fabric: |Vlin−z| = 1.4449e-03
  (finite-A floor; labeled reference, not the device claim).
- Exp 24/25 LEVEL 2 servo DC on o2 vs z ≈ 1e-8 (ideal G-source integrator).
- MOS miller no-servo: |err| = 7.9704e-02, A_eff ≈ 1.7e3.
- MOS miller+servo: |err| = 5.6283e-05, better than behavioral
  finite-A L because residual Vsum is ~0.7 µV rather than Vlin/A.
  Still worse than the LEVEL 2 ideal-integrator servo (1e-8).

## 23. Physical realism level

LEVEL 4 device-level ngspice BSIM3v3 teaching card. Not LEVEL 5–6. Not board power. Not silicon. IHP PDK not installed.

## 24. What is still ideal

- Vin / Vref independent sources
- Architecture A invert op-amps (E-source VCVS, A=1e7)
- Ideal Ibias into MOS diodes
- Lumped servo C (not MIM/MOM layout)
- Fine-bank divider ratios (resistors are physical; taps unbuffered by MOS)
- Geometric DW nulls (one-time amplifier self-balance, not a foundry mismatch PDF)
- BSIM3 gate current is 0 in this card — leakage requirement not device-validated

## 25. What is now physically demonstrated

- A documented BSIM3 two-stage miller can hold a TIA loop on the real frozen
  o2 fabric at G_tot ≈ 4.23 mS and ±2.5 V
- A second miller leaky integrator can correct 214 µV (and 1 mV) injected offset
  without Python correction, reaching analog |Vlin−z| ≈ 5.6e-5 on o2 at 27 °C
- Sampled inference at 100–1000 µs dwell is analog-stable with C=1 nF
- Transistor-level simulated power of that cell ≈ 3.15 mW (~0.63 nJ / 200 µs)
- h16, h21, and light h31 analog-pass (G_tot sensitivity)
- 5T OTA is the wrong servo output stage; cascode first stage collapsed at ±2.5 V
- 0.5% R remains the analog floor; tiling helps but does not recover 1e-3 on o2

## 26. Recommendation for Experiment 27

Experiment 27 should not rebuild the encoding and should not transistorize Network F. The teaching-card miller+servo analog-passes frozen o2 at 27 °C, ±2.5 V, 100–1000 µs dwell. Remaining physical gaps: (1) install IHP SG13G2 or another documented PDK so leakage, mismatch PDFs, and temperature are not teaching-card artefacts; (2) resistor matching / tiling — 0.5% local R still analog-fails (MAE 1.0203e-02); (3) temperature-stable offset (DW null at 27 °C fails at −40/85 °C). Clocked MOS auto-zero is a candidate for (3). Do not invent MOS parameters. Do not retrain.

## FINAL STATUS

DEVICE-LEVEL PRIMITIVE PARTIALLY VALIDATED

SPICE is the source of truth. Frozen Experiment 9 weights were not edited.
