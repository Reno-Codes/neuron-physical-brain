==================================================
EXPERIMENT 34
32-COPY OPA189 RESIDUAL MECHANISM AND FABRIC
LOADING ISOLATION
==================================================

Frozen Experiment 9 weights. SPICE is the source of truth.
Experiments 1-33 were not overwritten. No Python correction,
no invented MOS W/L, no Network F in transistors.
No new amplifier search.

Status: **PHYSICAL HIDDEN INVERTER PARTIALLY VALIDATED**
Decision: **E. NO SINGLE MECHANISM IDENTIFIED; FURTHER PHYSICAL MODEL IS REQUIRED**

The Experiment 33 ~575 uV / N=32 fail is not a physical OPA189
offset that appears at 32 copies. Isolated 32-copy cells stay at
~0.64 uV. In the fabric, 11 of 12 F12 vectors also stay at ~0.73 uV.
One vector lands at ~2.29 mV at default reltol=1e-3 and accounts for
almost the entire 192 uV mean. The same topology at reltol=1e-6
returns residual 0.73 uV and F12 MAE 5.10e-4. That tight-reltol
result is a diagnostic only. It is not a promoted N=32 pass.

## 1. Objective

Determine why an isolated OPA189 invert residual of ~0.66 uV
becomes a large mean residual when 32 copies sit in the Architecture A
hidden-inverter fabric.

## 2. Experiment 33 baseline reproduction

| N | MAE | max | acc | analog | mean invert residual | max invert residual |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 5.1014e-04 | 3.1607e-03 | 1.0000 | True | 7.6723e-07 | 1.0121e-06 |
| 8 | 5.7634e-04 | 3.1605e-03 | 1.0000 | True | n/a | n/a |
| 16 | 7.6206e-04 | 6.5760e-03 | 1.0000 | True | 1.9261e-04 | 2.3305e-03 |
| 32 | 1.0142e-03 | 8.9672e-03 | 1.0000 | False | 1.9183e-04 | 2.3247e-03 |

Unprobed N=1/8/16/32 MAE matches Experiment 33 exactly.
Probed MAE now matches unprobed (the Experiment 33 2.061e-3 probe MAE
was not reproduced and is treated as a prior-script artifact).

Default-reltol N=32 residual_by_vector (mean |Vout+Vin| over 32 stages):

```
11 vectors: 0.71-0.75 uV
1 vector:   2.294 mV
mean:       192 uV
stage-to-stage std: 1.1 uV (shared)
```

The Experiment 33 "575 uV mean" is not a per-vector pedestal. The
2.33 mV max matches. A later o*p-short diagnostic happened to land
at 575 uV; that is a different OP, not the uncorrected fabric mean.

## 3. Isolated-to-fabric hierarchy

| level | residual | note |
| --- | --- | --- |
| L0_noload | 6.3898e-07 | isolated, almost no load |
| L1_4k91 | 6.3731e-07 | isolated representative 4.91 kOhm |
| L2_actualR_far0 | 1.1603e-06 | one stage actual dest R, far=0 V, Vin=2.61 |
| L2_actualR_far500uV | 1.1603e-06 | one stage actual dest R, far=0.0005 V, Vin=2.61 |
| L3_ncopy_actual | 6.5619e-07 | 32 isolated copies, actual hy and Rfab |
| L4_fabric32 | 2.3247e-03 max / 1.9183e-04 mean | all 32 OPA189 in frozen Network F fabric |

The first jump is L4 (coupled fabric), not instance count or Rfab value.

## 4. N-scaling with ideal loads

32 isolated OPA189 cells, independent ideal Vin and 4.91 kOhm (and
actual hy + actual Rfab), shared or independent +/-15 V:

| N | Vin | shared | mean |err| | max |err| | tier1 |
| --- | --- | --- | --- | --- | --- |
| 1 | 0.0 | True | 6.5619e-07 | 6.5619e-07 | True |
| 1 | 2.60818 | True | 6.3731e-07 | 6.3731e-07 | True |
| 32 | 0.0 | True | 6.5619e-07 | 6.5619e-07 | True |
| 32 | 2.60818 | True | 6.3731e-07 | 6.3731e-07 | True |
| 32 | 0.0 | False | 6.5619e-07 | 6.5619e-07 | True |
| 32 | 2.60818 | False | 6.3731e-07 | 6.3731e-07 | True |

Hypothesis B (bare multi-instance GWL) is rejected.
The problem is not "32 OPA189 models."

## 5. Feedback-node analysis

mean |Vout+Vin| = 1.9183e-04
mean |V- - V+| = 9.6394e-05
corr(|err|, |vdiff|) = 0.9997
shared across stages = True

|Vout+Vin| ~ 2 |Vmid| as a closed-loop invert predicts. That is the
shape of a virtual-ground pedestal, but the pedestal is not present
on 11/12 vectors and vanishes at reltol=1e-6. Do not treat the
correlation as a physical Vos.

## 6. Input impedance analysis

| case | residual | note |
| --- | --- | --- |
| ideal_Vsrc_Rs=0 | 6.3731e-07 | isolated; residual vs commanded Vin |
| Rs=100 | 2.5823e-02 | series R before R1; commanded-Vin divider, not Zin |
| Rs=1k | 2.3711e-01 | same; not a fabric condition (ReLU is a B-source) |
| Rs=10k | 1.3041e+00 | same |
| CASE_A_ideal_hy_in_fabric | 1.9240e-04 | fabric, ReLU replaced by V |
| CASE_E_relu_drive | 1.9183e-04 | fabric, actual ReLU B-source |

ReLU vs ideal V in the fabric does not change the residual.
The OPA input is not loading a soft hidden node.

## 7. Common-mode analysis

| Vcm | Vout+Vin | loop err (Vout+Vin-2 Vcm) |
| --- | --- | --- |
| -1.0 | 2.0000e+00 | 1.2797e-06 |
| -0.1 | 2.0000e-01 | 7.0155e-07 |
| 0.0 | 6.3731e-07 | 6.3731e-07 |
| 0.0001 | 1.9936e-04 | 6.3725e-07 |
| 0.0005 | 9.9936e-04 | 6.3699e-07 |
| 0.01 | 1.9999e-02 | 6.3089e-07 |
| 0.1 | 2.0000e-01 | 5.7308e-07 |
| 1.0 | 2.0000e+00 | 5.0239e-09 |

Isolated invert around IN+=Vcm stays at ~uV loop error. The fabric
IN+ is 0. Common-mode of the isolated model does not explain 2.29 mV.

## 8. Output-load analysis

| Rload | |err| | Iout |
| --- | --- | --- |
| 100000.0 | 6.3890e-07 | 2.6082e-05 |
| 10000.0 | 6.3816e-07 | 2.6082e-04 |
| 4914.01 | 6.3731e-07 | 5.3076e-04 |
| 2000.0 | 6.3488e-07 | 1.3041e-03 |
| 1000.0 | 6.3078e-07 | 2.6082e-03 |

Isolated load, including 1 kOhm, stays at ~0.63 uV. The fabric
equivalent R is not the 192 uV source.

## 9. Resistor-fabric coupling

| case | residual | MAE | analog |
| --- | --- | --- | --- |
| A | 1.9240e-04 | 8.2637e-04 | True |
| B | 1.9176e-04 | 1.0142e-03 | False |
| C | 7.2746e-07 | 1.0027e+00 | False |
| D | 7.2749e-07 | 1.0031e+00 | False |
| E | 1.9183e-04 | 1.0142e-03 | False |

CASE C (dest taken off the live TIA resistors) destiffens the OP and
looks like "fabric loading." A LEVEL 2 dest buffer that keeps those
TIA currents failed (MAE 3.48e-3). CASE C is therefore not proof of
a physical dest-drive limit. It is a topology change that also makes
the OP easy.

## 10. Cross-neuron coupling

| n_active | residual | MAE | note |
| --- | --- | --- | --- |
| 1 | 7.6723e-07 | 5.1014e-04 | OPA on N worst; others remain VCVS |
| 8 | 1.9148e-04 | 5.7634e-04 | OPA on N worst; others remain VCVS |
| 16 | 1.9261e-04 | 7.6206e-04 | OPA on N worst; others remain VCVS |
| 32 | 1.9183e-04 | 1.0142e-03 | OPA on N worst; others remain VCVS |
| 1 | 6.5966e-07 | 6.4062e-01 | 32 OPA present; only worst ReLU live, others hy=0 |

32 OPA189 instances with only one live hidden signal stay at uV.
The bad OP appears once several hidden dest nodes carry signal
into the shared output fabric (already at N=8).

## 11. Shared reference/bias analysis

| node | residual | MAE |
| --- | --- | --- |
| baseline_shared_vdd | 1.9183e-04 | 1.0142e-03 |
| independent_+/-15V | n/a | 1.0142e-03 |
| output_summing_nodes_forced_0 | 5.7505e-04 | 6.5144e-01 |
| hidden_summing_nodes_forced_0 | 6.5619e-07 | 6.5457e-01 |

Independent supplies reproduce MAE 1.014e-3 (Experiment 33's 2.061e-3
independent-supply MAE is not reproduced). Shared rails are not the
cause. Shorting hidden VG collapses invert residual (and wrecks MAE)
by changing the OP, not by revealing a hidden reference voltage.

## 12. Replica interaction

| case | residual | MAE | analog |
| --- | --- | --- | --- |
| A | 1.9183e-04 | 1.0142e-03 | False |
| B | n/a | 1.0142e-03 | False |
| C | n/a | 5.0844e-04 | True |
| D | n/a | n/a | None |

A replica that is present but unused does not change N=32 MAE.
LEVEL 2 replica-sign still analog-passes (Experiment 32 control).
Physical OPA189 sign was not inserted at N=32.

## 13. Capacitive effects

| Ccl | DC |err| | 200 us |err| |
| --- | --- | --- |
| 0.0 | 6.3731e-07 | 1.1348e-06 |
| 1e-13 | 6.3731e-07 | 1.1348e-06 |
| 1e-12 | 6.3731e-07 | 1.1348e-06 |
| 1e-11 | 6.3731e-07 | 1.1348e-06 |

Isolated DC and 200 us TRAN stay at uV. Ccl is not the fabric residual.
Fabric Ccl~0 MAE 1.013e-3 (still fail) — the 1 pF GWL helper cap is
not the N=32 mechanism.

## 14. Numerical/model diagnostics

| where | reltol | residual | MAE | analog |
| --- | --- | --- | --- | --- |
| isolated_n32 | 0.001 | 6.3731e-07 | n/a | True |
| isolated_n32 | 0.0001 | 6.3731e-07 | n/a | True |
| isolated_n32 | 1e-06 | 6.3731e-07 | n/a | True |
| fabric_n32 | 0.001 | 1.9183e-04 | 1.0142e-03 | False |
| fabric_n32 | 1e-06 | 7.2742e-07 | 5.1038e-04 | True |

Same netlist, same weights, same OPA189. Only the solver tolerance
changes. Isolated 32-copy is insensitive. Coupled fabric is highly
sensitive. This is the controlling experiment.

Do not promote reltol=1e-6 as PHYSICAL N=32 VALIDATED.

## 15. Mechanism attribution

| mechanism | residual contribution | verdict |
| --- | --- | --- |
| isolated OPA189 | 6.3731e-07 | not the fail |
| multi-instance GWL (ideal load) | 6.5619e-07 | rejected |
| actual hy+Rfab isolated | 6.5619e-07 | rejected |
| resistor values / R1/R2 | 1.9176e-04 at default reltol | not causal |
| ReLU vs V drive | same as full fabric | rejected |
| isolated common-mode | ~uV loop err | rejected |
| isolated output load | ~uV to 1 kOhm | rejected |
| replica present | MAE unchanged | rejected |
| Ccl / 200 us isolated | ~uV | rejected |
| dest connected to live TIA (CASE C vs E) | appears to matter | destiffens OP; buffer fails |
| default-reltol one-vector OP | 2.29 mV on 1/12 vectors | **dominant** |
| fabric reltol=1e-6 | 7.2742e-07 | diagnostic only |

Dominant: numerical / GWL operating-point of the coupled fabric.

## 16. Mitigation experiment

| mitigation | residual | N=32 MAE | analog | note |
| --- | --- | --- | --- | --- |
| LEVEL2 dest VCVS buffer | 1.1492e-03 | 3.4825e-03 | False | keeps TIA currents; not a physical primitive |
| force R1=R2=10k | n/a | 1.0142e-03 | False | topology-preserving ratio |
| reltol=1e-6 (diagnostic) | 7.2742e-07 | 5.1038e-04 | True | NOT promoted |

No physical architectural mitigation analog-passed. Tight reltol is
not an intervention that may be promoted.

## 17. N=32 validation

Default solver: MAE=1.0142e-03 analog=False mean residual=1.9183e-04
(max 2.325e-03, one vector). Uncorrected documented primitive does
not pass the Experiment 33 promotion gate.

## 18. F12 result

Default: MAE=1.0142e-03 acc=1.0000 analog=False
reltol=1e-6 diagnostic: MAE=5.1038e-04 analog=True (not promoted)

## 19. F40 gate status

F40 not earned. N=32 F12 did not analog-pass under the same solver
policy used for Experiments 31-33.

## 20. Power

one primitive ~ 3.9000e-02 W (macromodel Iq, +/-15 V).
32 hidden estimate ~ 1.2480e+00 W. I(Vdd) on N=32 ~ 41.6 mA = 32 x 1.3 mA.
Not full-F silicon. TIA/ReLU still ideal.

## 21. Realism level

LEVEL 3 vendor macromodel (Green-Williams-Lis, static VOS_DRIFT).
Not a switching chopper. Not a PDK.

## 22. Remaining ideal blocks

TIA VCVS, ReLU B-source, stimulus sources. Invert is OPAx189.

## 23. Limitations

Not silicon. Not a PDK. Default ngspice reltol=1e-3 is the
Experiments 31-33 policy; changing it is diagnostic only.
A LEVEL 2 dest buffer is not a physical primitive and did not help.
PDK_ROOT remains unset. No IHP / SkyWater analog tree.

## 24. Experiment 35 recommendation

Do not search for another amplifier. The isolated OPA189 already
meets the extracted invert bench.

The next experiment should either:

1. adopt a documented, frozen solver/model policy that makes the
   coupled 32-copy GWL OP trustworthy, then re-run N=32/F40 without
   calling that a physical offset fix, or
2. install a documented PDK / resistor+device model whose
   multi-instance DC solution is the intended physical evidence,

or accept LEVEL 2 invert / replica-sign and host Experiment 29 on a
resistor PDK.

Do not invent MOS. Do not rebuild the encoding. Do not promote reltol.

## 25. Final status

**E. NO SINGLE MECHANISM IDENTIFIED; FURTHER PHYSICAL MODEL IS REQUIRED**

**PHYSICAL HIDDEN INVERTER PARTIALLY VALIDATED**

Isolated OPA189, including 32 copies with actual hy and Rfab, remains
~0.64-0.66 uV. The Architecture A fabric at default reltol fails N=32
because one F12 vector is not solved (2.29 mV shared invert residual).
The same topology at reltol=1e-6 analog-passes. That is a numerical /
GWL-in-fabric result, not a 575 uV physical primitive failure, and it
is not a promoted validation.

JSON: `results/exp34_opa189_32copy_mechanism.json`.
Circuits: `circuits/exp34_opa189_32copy_mechanism/`.
Scripts: `scripts/exp34_opa189_32copy_mechanism.py`,
`scripts/opa189_fabric_isolation.py`.
