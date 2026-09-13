==================================================
EXPERIMENT 25
TRANSIENT VALIDATION OF THE VIRTUAL-GROUND SERVO
==================================================

Frozen Experiment 9 weights. SPICE is the source of truth.
Experiments 1–24 were not overwritten. Analog MAE and classification are separate.
No Python affine correction, output calibration, or per-weight calibration.

## 1. Objective

Determine whether the Experiment 24 summing-node servo can function dynamically
for analog inference: nested-loop stability, settling, offset correction, and
changing inputs, while preserving the frozen analog map.

This is not a new weight-encoding experiment. The resistor fabric is unchanged.

## 2. Baseline reproduction

DC operating-point reproduction of Experiment 24 (same generate_inputs seeds):

| case | MAE | max abs | acc | failed |
|---|---:|---:|---:|---|
| A L Vos=0 | 3.4423e-04 | 8.6042e-04 | 1.0000 | False |
| A L Vos=214 µV | 5.0930e-03 | 8.5523e-03 | 0.9900 | False |
| A servo 214 µV | 5.0939e-09 | 8.5539e-09 | 1.0000 | False |
| F L Vos=0 | 4.8383e-04 | 3.4319e-03 | 1.0000 | False |
| F L Vos=214 µV | 7.3721e-03 | 2.2816e-02 | 1.0000 | False |
| F servo 214 µV | 7.3755e-09 | 2.2840e-08 | 1.0000 | False |

Network F servo MAE 7.38e-9 matches Experiment 24 (7.38e-9). Network A servo
MAE 5.09e-9 matches. Uncorrected F L + 214 µV MAE 7.37e-3 matches.
Uncorrected Network A at 214 µV is analog-fail (MAE 5.09e-3) and drops one of
100 classification vectors (acc 0.99); the servo restores analog noise-floor MAE
and 100% class. DC baseline is intact. Transient work proceeded.

Worst compiled neuron remains o2 with Rf·G_tot = 1.4089e+02.
Also tested h16 (Rf·G_tot = 4.9158e+00) and h21 (Rf·G_tot = 3.9788e+01).

Isolated o2 no-servo TRAN vs frozen z:
- L Vos=0: |Vlin−z| = 1.44e-3 (finite-A loading; analog-fail vs z on this neuron)
- L Vos=214 µV: |Vlin−z| = 1.64e-2

## 3. Servo circuit definition

LEVEL 2 OTA-C leaky integrator on each XSPICE `limit` TIA:

    Gsrv  int 0  vg 0  gm     ; I = gm · Vsum
    Cint  int 0  C
    Rint  int 0  1e9
    Bplus plus 0 V = v(osref) + v(int)
    tau = C/gm     DC gain Vsum→Vint = gm·R = 1e6

Sign: Vsum > 0 discharges C so IN+ falls. Finite C is explicit; this is not an
algebraic Laplace 1/s. The TIA remains XSPICE `limit` (algebraic) unless a
behavioral output RC pole is inserted (Exp 22 method, retargeted onto A-devices).
That pole is not transistor fT.

Correction range at this LEVEL is the unbounded B-source; |Vint| is measured.
UIC cold-start uses `.ic v(*int)=0`. Offset-then-step TRAN starts from the OP
(servo already nulled at Vin=0) then PULSE-steps Vin. Those two initial
conditions are reported separately.

## 4. Unit-cell transient results

All o2 / h16 / h21 cases at Exp 24 tau=1 ms, algebraic TIA, Vos=214 µV:
- stable (no oscillation flag, no divergence)
- final |Vlin−z| ~ 1e-8 to 1e-7 (analog-pass vs frozen z)
- UIC cold start on o2 also analog-passes (1.18e-7) after ~2.8 ms
- offset-then-step analog equivalence is reached essentially at the Vin step
  for the algebraic TIA (inner loop is infinite-BW); reported t_after_step is
  then a timestep artifact, not a mechanical delay

The servo does **not** drive Vlin to 0 at DC or after a settled step. Nulling
Vsum is virtual-ground operation. Vint settles near −Vos (plus a small
finite-A residue ~ Vlin/A).

## 5. Stability sweep

o2, Vos=214 µV, A=1e5, offset-then-step, max-|z| hidden activation.

### Algebraic TIA (servo C is the only dynamics)

| tau (s) | |Vlin−z| | t after step to 1e-3 | osc |
|---:|---:|---:|---|
| 1.0000e-08 | 1.6459e-08 | 1.0000e-08 | False |
| 1.0000e-07 | 1.6459e-08 | 5.1700e-08 | False |
| 1.0000e-06 | 1.6456e-08 | 9.4100e-08 | False |
| 1.0000e-05 | 9.7012e-09 | 1.1261e-06 | False |
| 1.0000e-04 | 9.7052e-09 | 9.7437e-06 | False |
| 1.0000e-03 | 9.7056e-09 | 1.2588e-04 | False |
| 1.0000e-02 | 9.7056e-09 | 1.1340e-03 | False |

Every algebraic tau analog-passes. A faster servo does not cancel the neural
signal when the TIA is algebraic: Vsum is already ~0 and the integrator has
nothing to track except residual offset.

### Nested loop: behavioral TIA pole fp = 1 kHz

| tau (s) | |Vlin−z| | t after step | max\|Vsum\| | overshoot | osc |
|---:|---:|---:|---:|---:|---|
| 1.0000e-08 | 7.1167e-02 | n/a | 2.0266e-02 | 0.0000e+00 | False |
| 1.0000e-07 | 7.1167e-02 | n/a | 2.0266e-02 | 0.0000e+00 | False |
| 1.0000e-06 | 7.1336e-02 | n/a | 2.0264e-02 | 0.0000e+00 | False |
| 1.0000e-05 | 1.2544e-04 | 9.9526e-05 | 2.0262e-02 | 9.7020e-01 | False |
| 1.0000e-04 | 1.1943e-06 | 5.2709e-04 | 2.0262e-02 | 1.6082e-01 | False |
| 1.0000e-03 | 1.2164e-05 | 3.0353e-03 | 2.0262e-02 | 1.7106e-02 | False |
| 1.0000e-02 | 7.4080e-05 | 2.0259e-05 | 2.0262e-02 | 1.2014e-03 | False |

When the servo is **faster than the TIA pole** (tau ≤ 1 µs) the nested loop
distorts inference: final |Vlin−z| ≈ 7.1e-2, max |Vsum| ≈ 20 mV. That is
signal-path interaction, not a Python artefact. Oscillation_flag stayed false
(no sustained tail ringing under the 5 mV / 4-crossing rule) but analog
equivalence is lost — the servo is tracking the slewing TIA as if it were offset.

Analog-pass nested-loop window: tau ∈ [10 µs, 10 ms] on this sweep.
Selected operating point: **tau = 10 µs**, fp = 1 kHz, A = 1e5, Vos = 214 µV.
At that point isolated o2 |Vlin−z| = 1.25e-4 with ~0.97 V Vlin overshoot and
~100 µs after the step to analog 1e-3. This is a nested feedback loop, not a
true offset-only loop that is infinitely slower than the signal loop.

## 6. Gain × servo dynamics

Algebraic TIA, Vos=214 µV, o2: A ∈ {1e4, 5e4, 1e5} × tau ∈ {10 µs, 1 ms}
all analog-pass (~1e-10 to 1e-8). The servo also removes finite-A loading at
DC/settled TRAN, so A=1e4 is analog-grade **after settling** even though Exp 22
needed A ≳ 5e4 without a VG servo.

With fp=1 kHz (recovery):

| A | tau (s) | |Vlin−z| | t after step | osc |
|---:|---:|---:|---:|---|
| 10000 | 1.0000e-05 | 3.5762e-05 | 9.1926e-05 | False |
| 10000 | 1.0000e-03 | 1.7846e-08 | 7.8034e-04 | False |
| 50000 | 1.0000e-05 | 1.1266e-04 | 9.9126e-05 | False |
| 50000 | 1.0000e-03 | 2.9706e-08 | 2.6640e-03 | False |
| 100000 | 1.0000e-05 | 1.2544e-04 | 9.9526e-05 | False |
| 100000 | 1.0000e-03 | 1.2164e-05 | 3.0353e-03 | False |

## 7. Offset sweep

Algebraic TIA, tau=10 µs, o2 max-|z| step:

| Vos | |Vlin−z| | |Vint| peak |
|---:|---:|---:|
| 0.0000e+00 | 1.0239e-08 | 1.7286e-05 |
| 2.2000e-05 | 8.1897e-09 | 2.1280e-05 |
| 1.0000e-04 | 9.2235e-10 | 9.7847e-05 |
| 2.1402e-04 | 9.7012e-09 | 2.0978e-04 |
| 1.0000e-03 | 8.2931e-08 | 9.8271e-04 |

All listed Vos (0 to 1 mV) analog-pass. |Vint| ≈ Vos as expected. No startup
saturation of the LEVEL 2 B-source. Correction time does not grow with Vos on
this algebraic inner loop (the step delay dominates). A calibration phase is
not required if the integrator is allowed to run; UIC from Vint=0 still works
given several tau. There is no modeled correction-range limit other than the
TIA rail (±15 V behavioral).

## 8. Network A transient inference

First 12 of 100 Exp 24 vectors. tau=10 µs, fp=1 kHz,
Vos=214 µV, Vin PULSE after 40 µs, t_stop=160 µs. No Python repair.

- MAE = 1.6981e-04
- max |error| = 5.5228e-04
- classification = 1.0 (0 class failures)
- oscillating traces = 0

Analog-pass vs frozen software reference. This is a **single step from Vin=0**,
not a stream of changing vectors.

## 9. Network F transient inference

First 12 of 40 Exp 24 vectors. Same servo/pole/Vos.
1342 resistors, 48 TIA+servo cells. Disclosed subset; not a silent full-set swap.

- MAE = 6.3762e-05
- max |error| = 8.5250e-04
- classification = 1.0
- oscillating traces = 0

Analog-pass (MAE 6.38e-5 ≤ 1e-3) and 100% class on this subset. Worst-vector
max error 8.5250e-04 remains under the analog bar.

## 10. Multiple-input behavior

PWL Vin: three Exp 24 vectors in sequence (A indices [0, 3, 31], F [0, 3, 19]).
Sample at 0.92 of each dwell. Nested pole + tau=10 µs:

| net | t_hold (s) | seg0 MAE | seg1 MAE | seg2 MAE | analog all |
|---|---:|---:|---:|---:|---|
| A pole | 8.0000e-05 | 2.4815e-06 | 3.8800e-03 | 3.6905e-01 | False |
| A pole | 2.0000e-04 | 4.0383e-09 | 4.9540e-08 | 5.8802e-06 | True |
| A pole | 5.0000e-04 | 4.0016e-09 | 8.5703e-09 | 6.1614e-09 | True |
| A pole | 1.0000e-03 | 3.9727e-09 | 5.5188e-09 | 6.2044e-09 | True |
| A pole | 2.0000e-03 | 3.5038e-09 | 1.0140e-06 | 2.7161e-07 | True |
| F pole | 8.0000e-05 | 3.9811e-06 | 2.1441e-02 | 2.7996e-01 | False |
| F pole | 2.0000e-04 | 6.6836e-09 | 3.1247e-07 | 1.0995e-05 | True |
| F pole | 2.0000e-03 | 6.7094e-09 | 2.6034e-08 | 8.8359e-09 | True |
| A algebraic | 8.0000e-05 | 2.5198e-06 | 1.1583e-07 | 4.5404e-07 | True |

Segment 0 is cheap: ngspice OP already equals vector 1, so the first sample is
a settled DC point. Segments 1–2 are the scientific test (input **changes**).

At t_hold = 80 µs with the 1 kHz pole, later segments analog-fail (A seg2 MAE
~0.37). The servo is not a continuous 80 µs inference engine on the nested-loop
model. It must re-null Vsum after each loading change; that residue includes
both Vos and the finite-A Vlin/A term, so the integrator **does** move when the
signal changes. That is nested-loop behavior, not a pure offset memory.

Minimum analog-passing dwell (A): 2.0000e-04 s. Network F: 2.0000e-04 s.
Algebraic TIA A at 80 µs analog-all: True.

Architecture class: **sampled / static-calibrated inference** on the finite-TIA
model. It is not shown to meet the Experiment 22 10 µs continuous target.
A reset between vectors is not required if dwell is long enough; a clocked
sample-and-hold of Vin would be compatible.

## 11. Auto-zero comparison

Vref-gated auto-zero (Exp 24 LEVEL 2, Vin=Vref=0 then both on), isolated o2
max-|z| TRAN: |Vlin−z| = 1.4449e-03 at t_stop=80 µs.
That matches the no-servo L Vos=0 finite-A floor (1.44e-3), not the servo's
1e-8 VG restoration. AZ therefore recovers the Vos=0 TIA, including leftover
finite-A loading. The servo, once settled, also removes that loading error.

Timing: AZ needs a clocked sample (~20 µs used here) plus inference; the servo
needs nested-loop dwell (10 µs–ms depending on TIA pole). Both are LEVEL 2.
Neither is a transistor op-amp. For a future physical primitive, AZ has a
clearer clocked contract; the servo has better settled analog MAE if you can
wait and if the inner amplifier is not slower than the integrator.

## 12. Error budget

Settled OP of the same OTA-C netlist after dynamic correction is shown to work
(equivalent to t ≫ tau). Not a substitute for claiming TRAN mismatch.

| mechanism | MAE | acc |
|---|---:|---:|
| ideal R, Vos=214 µV, servo | 7.3755e-09 | 1.0 |
| 0.1% local R | 8.4111e-04 | 1.0 |
| 0.5% local R | 4.2081e-03 | 0.9916666666666666 |
| 13 nA leak, ideal R | 4.1664e-04 | 1.0 |
| combined 214 µV + 13 nA + 0.5% R | 4.6622e-03 | 0.975 |

After the dynamic servo exists, **0.5% resistor mismatch remains the analog
floor** (~4.2e-3), matching Experiment 24 DC. Leak at 13 nA is analog-pass
alone (4.17e-4). Combined is mismatch-dominated (4.66e-3, acc 97.5% on 40
vectors). 0.1% R is analog-pass (8.4e-4) with 100% class.

## 13. Numerical validation

Algebraic o2: delta y_final (tstep/5, reltol=1e-6) = 9.2759e-12.
Pole o2: delta y_final = 9.9932e-08.
Final values are reproducible. Nested-loop analog-fail at tau≤1 µs + 1 kHz pole
is not a coarse-timestep artefact of the passing window; it repeats in the
structured sweep. Do not overclaim digits below simulator agreement (~1e-11
algebraic, pole delta reported above).

## 14. Failure cases

1. Nested loop with servo faster than TIA pole (tau ≤ 1 µs, fp=1 kHz): analog
   fail ~7e-2 on o2. Preserved. Not replaced by a slower tau without comment.
2. Multi-input at 80 µs dwell with fp=1 kHz: later segments analog-fail.
   Preserved; longer dwells are reported separately.
3. Isolated o2 vs z without servo is analog-fail even at Vos=0 (finite A).
   Network MAE can still pass because other neurons are lighter.
4. Uncorrected Network A Vos=214 µV DC: acc 0.99. Not hidden.
5. No unit-cell oscillation_flag trips. Fast-servo analog fail is distortion,
   not a limit-cycle under the coded detector.
6. LEVEL 2 B-source Vplus is unlimited; saturation of a real OTA is not modeled.

## 15. Best operating point

- LEVEL 2 OTA-C servo, gm=1e-3, C=10 nF, Rleak=1e9, **tau=10 µs**
- TIA: XSPICE limit, A=1e5, optional behavioral fp=1 kHz for nested-loop claims
- Vos=214 µV, frozen Exp 9 weights, Architecture A fabric
- Single-step Network F TRAN MAE 6.38e-5, acc 100% (12-vector subset)
- Changing inputs: only after a dwell listed in §10

## 16. Latency / settling requirements

- Selected servo tau: 1.0000e-05 s
- Campaign recommended dwell (8·tau): 8.0000e-05 s
- Measured min analog multi-input dwell A: 2.0000e-04 s
- Measured min analog multi-input dwell F: 2.0000e-04 s
- Experiment 22 10 µs settling proxy: **not met** for changing inputs on the
  nested 1 kHz-pole model
- UIC cold start at tau=1 ms: a few milliseconds

## 17. Physical realism level

LEVEL 2 OTA-C leaky integrator + XSPICE `limit` TIA, with optional behavioral
1 kHz output RC. Not LEVEL 3–6. Not board power, silicon area, transistor count,
or MOS W/L.

## 18. Limitations

TIA is algebraic XSPICE `limit` unless the pole test. Servo is OTA-C LEVEL 2.
UIC cold-start and offset-then-step are both reported. Network F TRAN uses the
first 12 of 40 Exp 24 vectors. Mismatch budget is settled OP (t ≫ tau), plus
TRAN MAE on the vector subset. B-source Vplus = Vos+Vint is unlimited; |Vint|
is reported. Fast algebraic-TIA results overstate inner-loop bandwidth. The
1 kHz pole is a behavioral RC, not transistor fT. Not PCB or silicon.

Plots: `servo_transient_unit_step.png`, `servo_transient_tau_sweep.png`,
`servo_transient_tau_sweep_pole.png`, `servo_transient_stability_map.png`,
`servo_transient_multi_input.png` (200 µs analog-pass),
`servo_transient_multi_input_80us.png` (80 µs analog-fail),
`servo_transient_error_budget.png`. Waveforms: `servo_transient_waveforms.npz`.

## 19. Honest recommendation for Experiment 26

Experiment 26: treat the summing-node servo as sampled/static inference (required dwell ~ 2.0000e-04 s on this LEVEL 2 pole model), or develop Vref-gated auto-zero timing against the Exp 22 10 µs target. Do not invent MOS W/L on Network F. Do not rebuild the resistor fabric.

Do not jump to transistor-level Network F. Do not invent MOS sizing.
Do not retrain. Do not use per-weight calibration.

## FINAL STATUS

DYNAMIC SERVO PARTIALLY VALIDATED

SPICE is the source of truth. Frozen Experiment 9 weights were not edited.
