==================================================
EXPERIMENT 35
N=32 OPA189 CONVERGENCE AND ROBUSTNESS QUALIFICATION
==================================================

Frozen Experiment 9 weights. SPICE is the source of truth.
Experiments 1-34 were not overwritten. No Python correction,
no invented MOS W/L, no Network F in transistors.
OPA189 remains the official TI Green-Williams-Lis macromodel.

Status: **PHYSICAL HIDDEN INVERTER PARTIALLY VALIDATED**
Decision: **A — ROBUST NUMERICAL QUALIFICATION**
Qualification: **NOT QUALIFIED**
F40 permitted: False

## 1. Executive summary

Default MAE=1.0142e-03 worst_vec=6. Candidate analog=True band=True repeat=True 200us=False. Order-sensitive=False IC-sensitive=True.

The Experiment 34 default-reltol N=32 fail is reproduced: F12 MAE
1.0142e-03, max 8.9672e-03, invert-fail
vector [6]. The same netlist at reltol=1e-6 reproduces MAE
5.1038e-04. The reltol sweep is discontinuous: a bad DC
operating-point plateau from 1e-3 through 1e-4, a good plateau from
5e-5 through 1e-6 except a no-convergence hole at 2e-5. Absolute
tolerances do not move the branch. Vector order does not move it.
Full-F12 DC initial-condition variants do not move it.

The 2.29 mV residual is a DC Newton branch of the coupled GWL fabric.
It is not a stable physical offset: default-reltol TRAN on vector 6
settles to the good invert (MAE ~6e-4) at 100/200/500 us. Isolated
32-copy OPA189 stays at ~0.64 uV at both reltols. Replica-sign analog-
passes at default DC. Independent +/-15 V supplies do not change MAE.

Tighter reltol does not invent a new circuit solution. It selects the
same operating point that default-reltol transient analysis already
finds. The default DC 2.29 mV result is the numerical escape.

## 2. Experiment 34 starting point

Isolated 32-copy residual ~0.66 uV. Default-reltol fabric N=32 MAE
1.014e-3 from one F12 vector at ~2.29 mV. reltol=1e-6 diagnostic
MAE 5.10e-4. Decision E. F40 not earned. Status: PHYSICAL HIDDEN
INVERTER PARTIALLY VALIDATED.

## 3. Exact reproduction

Default (no .option): MAE=1.0142e-03 max=8.9672e-03 acc=1.0000 analog=False worst_vector=6 invert_fail=[6] spice_s=48.5

reltol=1e-6: MAE=5.1038e-04 max=3.1576e-03 acc=1.0000 analog=True worst_vector=10 analog_mae_fail=[] spice_s=45.2

Reproduction: True

Note: `failing_vector_indices` in raw JSON uses per-vector max |err| > 1e-3.
Nominal Architecture A F12 already has several outputs near 1-3 mV, so
that list is almost every vector even on an analog-pass. Invert failure
is identified by per-vector MAE > 1e-3, which is vector 6 only at
default DC. After the good OP is selected, analog MAE-fail is empty
and the worst remaining vector is 10 (max 3.16e-3, the frozen map).

## 4. N=32 failing vector

Original-order index: 6 (Experiment 34 index 6).
per-vector max error: 8.9672e-03
per-vector MAE: 6.6083e-03
mean invert |Vout+Vin|: 2.2940e-03
max invert |Vout+Vin|: 2.3247e-03
worst output neuron: 1
standalone default-reltol analog: False
standalone MAE vs that vector: 6.6083e-03

Vector 6 fails as its own ngspice OP (no prior vector). The error is
a shared invert pedestal on all 32 hidden stages, not one amplifier.
Downstream outputs inherit that common invert offset. Isolated copies
driven by the same hy and Rfab do not show the pedestal.

Per-inverter residuals on the failing vector (worst 8):

| stem | Vin | Vout | |Vout+Vin| | |V-| | Rfab |
| --- | --- | --- | --- | --- | --- |
| invh21 | 2.1759e+00 | n/a | 2.3247e-03 | 1.1719e-03 | 3.2748e+04 |
| invh12 | 1.6899e+00 | n/a | 2.3170e-03 | 1.1680e-03 | 8.1024e+04 |
| invh19 | 1.4926e+00 | n/a | 2.3122e-03 | 1.1657e-03 | 1.6469e+04 |
| invh23 | 1.3890e+00 | n/a | 2.3116e-03 | 1.1653e-03 | 5.0620e+04 |
| invh22 | 1.2737e+00 | n/a | 2.3072e-03 | 1.1631e-03 | 9.6619e+03 |
| invh29 | 1.0442e+00 | n/a | 2.3054e-03 | 1.1622e-03 | 7.6623e+04 |
| invh7 | 1.0513e+00 | n/a | 2.3049e-03 | 1.1619e-03 | 2.2295e+04 |
| invh18 | 9.9538e-01 | n/a | 2.3034e-03 | 1.1612e-03 | 1.5216e+04 |

Load correlation (not causation): err vs Rfab r=0.292; err vs Vin r=0.922. Residuals are shared,
so Vin correlation reflects the common pedestal, not a unique loaded stage.

## 5. Solver tolerance sweep

Every other setting held at Experiment 34 / ngspice factory defaults.
Two discrete DC solutions plus a hole. Not a smooth tightening curve.

| reltol | MAE | max | acc | analog | analog-MAE-fail | conv warn | t(s) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0.001 | 1.0142e-03 | 8.9672e-03 | 1.0000 | False | [6] | 0 | 48.0 |
| 0.0005 | 1.0142e-03 | 8.9674e-03 | 1.0000 | False | [6] | 0 | 48.5 |
| 0.0002 | 1.0142e-03 | 8.9674e-03 | 1.0000 | False | [6] | 0 | 49.7 |
| 0.0001 | 1.0142e-03 | 8.9674e-03 | 1.0000 | False | [6] | 0 | 56.9 |
| 5e-05 | 5.1038e-04 | 3.1576e-03 | 1.0000 | True | [] | 0 | 45.1 |
| 2e-05 | n/a | n/a | n/a | None | [] | 0 | 360.0 |
| 1e-05 | 5.1038e-04 | 3.1576e-03 | 1.0000 | True | [] | 0 | 45.7 |
| 5e-06 | 5.1038e-04 | 3.1576e-03 | 1.0000 | True | [] | 0 | 46.0 |
| 2e-06 | 5.1038e-04 | 3.1576e-03 | 1.0000 | True | [] | 0 | 46.4 |
| 1e-06 | 5.1038e-04 | 3.1576e-03 | 1.0000 | True | [] | 0 | 45.0 |

Passing DC reltols: 5e-5, 1e-5, 5e-6, 2e-6, 1e-6 (identical MAE 5.1038e-4).
Hole: reltol=2e-5 failed=True reason=ngspice timeout / possible non-convergence.

## 6. Absolute tolerance analysis

At the bad-branch reltols (1e-3, 1e-4), vntol / abstol / chgtol changes
do not select the good operating point. reltol controls the DC branch.

| reltol | vntol | abstol | chgtol | MAE | max | analog | t(s) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0.001 | 1e-06 | 1e-12 | default | 1.0142e-03 | 8.9672e-03 | False | 48.0 |
| 0.001 | 1e-07 | 1e-12 | default | 1.0142e-03 | 8.9672e-03 | False | 48.1 |
| 0.001 | 1e-05 | 1e-12 | default | 1.0142e-03 | 8.9672e-03 | False | 48.4 |
| 0.001 | 1e-06 | 1e-09 | default | 1.0142e-03 | 8.9674e-03 | False | 47.9 |
| 0.0001 | 1e-06 | 1e-12 | default | 1.0142e-03 | 8.9674e-03 | False | 56.4 |
| 0.0001 | 1e-07 | 1e-12 | default | 1.0142e-03 | 8.9674e-03 | False | 56.9 |
| 0.001 | 1e-06 | 1e-12 | 1e-13 | 1.0142e-03 | 8.9674e-03 | False | 48.0 |
| 5e-05 | 1e-06 | 1e-12 | 1e-13 | 5.1038e-04 | 3.1576e-03 | True | 45.0 |

## 7. Timestep / integration analysis

Batched 12-vector TRAN in one ngspice process timed out at 600 s
(default and reltol=5e-5). That timeout is a process-length limit,
not a measured analog fail. Qualification uses independent 200 us
transients (one process per vector).

| mode | method | t_hold | tstep | MAE | analog | n_vec | note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| tran | gear | 0.0002 | 1e-06 | 6.3838e-04 | True | None | failing-vector TRAN gear reltol=0.001 |
| tran | gear | 0.0002 | 1e-06 | 5.6280e-04 | True | None | failing-vector TRAN gear reltol=5e-05 |
| tran | trap | 0.0002 | 2e-07 | 6.3838e-04 | True | 1 | failing-vector TRAN trap tstep=2e-07 |
| tran | trap | 0.0002 | 1e-06 | 6.3838e-04 | True | 1 | failing-vector TRAN trap tstep=1e-06 |
| tran | trap | 0.0002 | 5e-06 | 6.3837e-04 | True | 1 | failing-vector TRAN trap tstep=5e-06 |
| tran | trap | 0.0002 | None | n/a | None | None | F12 TRAN 200 us default |
| tran | trap | 0.0002 | None | n/a | None | None | F12 TRAN 200 us candidate |
| tran | trap | 0.0002 | None | n/a | False | 12 | F12 independent TRAN 0.0002 s default |
| tran | trap | 0.0002 | None | n/a | False | 12 | F12 independent TRAN 0.0002 s cand5e-5 |

## 8. Initial-condition analysis

Full-F12 DC protocols (sequential alter, reset-before-op, independent
per-vector OP) all stay on the bad default-reltol branch (MAE 1.014e-3).
The bad OP is not an inter-vector continuation artifact. UIC / zero
start is reported below where measured. Artificial answer-encoding
ICs were not used.

| case | MAE | max | analog | analog-MAE-fail | note |
| --- | --- | --- | --- | --- | --- |
| sequential_alter_default | 1.0142e-03 | 8.9672e-03 | False | [6] | Experiment 34 protocol |
| reset_before_each_op | 1.0142e-03 | 8.9672e-03 | False | [6] | ngspice reset then alter/op |
| independent_per_vector_OP | 1.0142e-03 | 8.9672e-03 | False | [] | each F12 vector is its own ngspice OP (no previous-vector guess) |
| failing_vector_alone | 6.6083e-03 | 8.9672e-03 | False | [0] | vector 6 only |
| tran_uic_zero_start_vec6 | 6.4231e-04 | 1.6348e-03 | True | [] | UIC transient from zero; does not encode the NumPy answer |

## 9. Vector-order analysis

Default-reltol DC MAE is identical in original, reversed, two shuffled,
and failing-first order. Vector 6 is not created by the preceding vector.

| order | MAE | max | analog | analog-MAE-fail orig |
| --- | --- | --- | --- | --- |
| original | 1.0142e-03 | 8.9672e-03 | False | [0, 1, 2, 3, 5, 6, 7, 8, 9, 10, 11] |
| reversed | 1.0142e-03 | 8.9672e-03 | False | [11, 10, 9, 8, 7, 6, 5, 3, 2, 1, 0] |
| shuffle_seed35 | 1.0142e-03 | 8.9672e-03 | False | [7, 9, 1, 3, 11, 6, 2, 5, 0, 10, 8] |
| shuffle_seed350 | 1.0142e-03 | 8.9672e-03 | False | [7, 5, 6, 11, 10, 3, 1, 9, 2, 8, 0] |
| failing_first | 1.0142e-03 | 8.9672e-03 | False | [6, 7, 8, 9, 10, 11, 0, 1, 2, 3, 5] |

## 10. Dwell-time analysis

Project target is 200 us. 1 ms is reported only as a bound, not as a substitute.

| dwell | MAE | max | analog | n_vec | note |
| --- | --- | --- | --- | --- | --- |
| 0.0001 | 6.9344e-04 | 1.7538e-03 | True | None | failing vector 6 only |
| 0.0002 | 6.3838e-04 | 1.6248e-03 | True | None | failing vector 6 only |
| 0.0005 | 5.7855e-04 | 1.4708e-03 | True | None | failing vector 6 only |
| 0.0002 | n/a | n/a | None | None | F12 TRAN 200 us default |
| 0.0002 | n/a | n/a | None | None | F12 TRAN 200 us candidate |
| 0.0002 | n/a | n/a | False | 12 | F12 independent TRAN 0.0002 s default |
| 0.0002 | n/a | n/a | False | 12 | F12 independent TRAN 0.0002 s cand5e-5 |
| 0.00015 | 6.6024e-04 | 1.6808e-03 | True | 1 | failing vector 6 only |
| 0.0003 | 6.0807e-04 | 1.5468e-03 | True | 1 | failing vector 6 only |
| 0.001 | 5.6388e-04 | 1.4308e-03 | True | 1 | failing vector 6 only |

## 11. Model-vs-fabric hierarchy

Sensitivity appears only when the vendor macromodel is embedded in the
full hidden-neuron resistor fabric. Isolated A/B/C stay at ~0.64 uV
at default reltol. Control D dumps W2 (MAE ~1, expected). Control E
is the coupled N=32 fabric and is the first place the 2.29 mV DC
branch appears.

| control | reltol | residual/MAE | analog | note |
| --- | --- | --- | --- | --- |
| A | 0.001 | 6.3731e-07 | True | 32 isolated OPA189, ideal Vin, 4.91 kOhm |
| B | 0.001 | 6.3731e-07 | True | isolated 4.91 kOhm |
| A | 1e-06 | 6.3731e-07 | True | 32 isolated OPA189, ideal Vin, 4.91 kOhm |
| B | 1e-06 | 6.3731e-07 | True | isolated 4.91 kOhm |
| C | 0.001 | 6.5619e-07 | True | 32 isolated, failing-vector hy and actual Rfab |
| D | 0.001 | 1.0027e+00 | False | full OPA189, dest isolated to 4.91 kOhm (W2 dumped) |
| E | 0.001 | 1.0142e-03 | False | full N=32 fabric |
| D | 1e-06 | 1.0027e+00 | False | full OPA189, dest isolated to 4.91 kOhm (W2 dumped) |
| E | 1e-06 | 5.1038e-04 | True | full N=32 fabric |

## 12. Supply / replica controls

Independent vs shared +/-15 V rails are numerically identical at both
reltols. Supply-network interaction is not the branch. Replica present
with IN+=0 matches the uncorrected fabric. LEVEL 2 replica-sign analog-
passes at default reltol (MAE 5.084e-4), i.e. the composite already
finds the good solution without tightening reltol. That is a control,
not a promotion of replica-sign as the N=32 invert itself.

| case | reltol | MAE | analog | note |
| --- | --- | --- | --- | --- |
| independent_+/-15V | 0.001 | 1.0142e-03 | False | per-amp supplies |
| shared_+/-15V | 0.001 | 1.0142e-03 | False | Experiment 34 rails |
| independent_+/-15V | 1e-06 | 5.1038e-04 | True | per-amp supplies |
| shared_+/-15V | 1e-06 | 5.1038e-04 | True | Experiment 34 rails |
| replica_present_IN+0 | 0.001 | 1.0142e-03 | False | disabled |
| replica_present_IN+0 | 1e-06 | 5.1038e-04 | True | disabled |
| replica_LEVEL2_sign | 0.001 | 5.0844e-04 | True | neg |
| replica_LEVEL2_sign | 1e-06 | 5.1040e-04 | True | neg |

## 13. Mechanism evidence

Default sequential OP fails invert-vector 6 (per-vector MAE 6.6083e-03, invert residual 2.2940e-03). Standalone DC analog_pass=False. Full-F12 reset/independent DC stay on the same bad branch (reset MAE=1.0142e-03, indep MAE=1.0142e-03). Passing DC reltols=[5e-05, 1e-05, 5e-06, 2e-06, 1e-06]. Hole at reltol=2e-5. Default-reltol TRAN on vector 6 analog-passes at 100/200/500 us. Isolated 32-copy remains uV-scale at default reltol (hierarchy A/B/C). The 2.29 mV result is a DC Newton branch, not the settled invert.

Interpretation of the central distinction: default DC 2.29 mV vs
reltol=1e-6 MAE 5.10e-4 is not 'tighter tolerance fixes the circuit.'
Default-reltol TRAN and tight-reltol DC converge to the same good
operating point. Default-reltol DC Newton can stop on a different
coupled-GWL solution. The isolated macromodel does not show that
second solution. The fabric creates the bad Newton basin; the
intended settled invert remains the microvolt-class OP.

## 14. Repeatability

| run | MAE | max | analog | worst vec |
| --- | --- | --- | --- | --- |
| 1 | 5.1038e-04 | 3.1576e-03 | True | 10 |
| 2 | 5.1038e-04 | 3.1576e-03 | True | 10 |
| 3 | 5.1038e-04 | 3.1576e-03 | True | 10 |

Repeatable: True

## 15. N=32 qualification decision

- default DC analog: False
- candidate analog: True
- candidate max-err <= 1e-2: True
- classification 100%: True
- 200 us: False
- repeatable: True
- reltol band (not a single point): True
- qualified: False

Candidate solver: {'reltol': 5e-05, 'abstol': 1e-12, 'vntol': 1e-06, 'chgtol': 1e-14, 'method': 'trap (ngspice default)', 'itl1': 100, 'note': 'Experiment 34 default: no .option line; ngspice factory defaults.', 'option_line': '.option reltol=5e-05'}

Important solver configurations (complete list in JSON):

| config | settings | MAE | analog |
| --- | --- | --- | --- |
| Exp 34 default DC | no .option; reltol=1e-3 factory | 1.0142e-03 | False |
| Diagnostic tight DC | .option reltol=1e-6 | 5.1038e-04 | True |
| Loosest passing DC | .option reltol=5e-05 | 5.1038e-04 | True |
| Hole | .option reltol=2e-05 | n/a | None |

## 16. Whether F40 is permitted

False

DC solver band is robust but 200 us sampled-inference gate was not satisfied.

## 17. Remaining physical limitations

OPA189 remains a GWL macromodel, not silicon. TIA/ReLU remain ideal. No PDK. Solver settings are recorded; a single tight-reltol run is not a pass. Macromodel Iq is not board or silicon power.

Additional remaining limits: TIA and ReLU are still ideal behavioral
blocks. The invert cell is a vendor macromodel, not transistor-level
silicon. reltol=2e-5 is a documented DC non-convergence hole. Default
DC OP remains the wrong branch and must not be used as the N=32
source of truth. Macromodel supply current is not board or silicon power.

## 18. Exact next experiment

Remain on N=32: close the unmet gate (200 us=False, band=True, repeat=True). Do not invent MOS. Do not search another amp.

JSON: `results/exp35_opa189_convergence.json`.
Circuits: `circuits/exp35_opa189_convergence/`.
Scripts: `scripts/exp35_opa189_convergence.py`, `scripts/exp35_n32_qualification.py`.
Plots: `results/exp35_reltol_sweep.png`, `results/exp35_abstol_sweep.png`,
`results/exp35_timestep.png`, `results/exp35_dwell.png`,
`results/exp35_vector_order.png`, `results/exp35_hierarchy.png`,
`results/exp35_feedback_residual.png`, `results/exp35_solver_matrix.png`,
`results/exp35_qualification.png`.
