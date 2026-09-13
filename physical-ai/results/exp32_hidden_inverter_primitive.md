==================================================
EXPERIMENT 32
PHYSICAL LOW-OFFSET HIDDEN-INVERTER PRIMITIVE SEARCH
==================================================

Frozen Experiment 9 weights. SPICE is the source of truth.
Experiments 1-31 were not overwritten. No Python correction,
no new encoding, no Network F in MOS, no invented foundry PDK.

## 1. Objective

Find a documented, repeatable hidden-layer invert cell that meets
the Experiment 31 Architecture A requirements, or establish that
the locally available model library cannot provide it.

Status: **PHYSICAL HIDDEN INVERTER PARTIALLY VALIDATED**

## 2. Frozen baseline

- Network F Architecture A, TIA A=100000, invert A=1e+07
- Nominal 12-vector MAE=5.1015e-04 acc=1.0000
- Experiment 29 leftover unmatched local after Rf.G grouping <= 0.075%
- Experiment 30 invert R1/R2 residual <= 0.075%
- Experiment 31 OPA mid pedestal ~498 uV, |Vout+Vin| ~996 uV

## 3. Experiment 31 baseline reproduction

| case | MAE | max | acc | analog |
| --- | --- | --- | --- | --- |
| F12, 32 hidden XSPICE limit | 5.1165e-04 | 3.2170e-03 | 1.0000 | True |
| 1 OPA1656 hidden inverter | 5.3212e-04 | 3.1607e-03 | 1.0000 | True |
| 8 OPA1656 | 7.1547e-04 | 3.4407e-03 | 1.0000 | True |
| 16 OPA1656 | 1.4462e-03 | 5.8665e-03 | 1.0000 | False |
| 32 OPA1656 | 2.6377e-03 | 7.0360e-03 | 1.0000 | False |
| injected 500 uV hidden inverter offset | 2.6674e-03 | 7.1074e-03 | 1.0000 | False |

Pedestal check (32-OPA): mean |Vmid|=4.9811e-04, mean |Vout+Vin|=9.9618e-04.

Do not reinterpret this fail as missing current drive or missing
finite gain unless a new measurement contradicts Experiment 31.
The injected Vos=500 uV row is the mechanism control. The 32-OPA
mid pedestal is 498.11 uV and |Vout+Vin| is 996.18 uV on every
hidden invert. That is the Experiment 24 / 31 GWL virtual-ground
floor, not datasheet Vos = 8.75 uV.

## 4. Candidate inventory (Gate A)

Only already-installed documented models were considered.
No PDK was installed. No external macromodel was copied in.

| candidate | level | present | doc Vos | note |
| --- | --- | --- | --- | --- |
| XSPICE limit invert | 2 | True | 0.0000e+00 | Exp 30/31 analog-pass at N=32. Behavioral, not a physical device. |
| OPA1656 | 3 | True | 8.7500e-06 | Exp 31: loaded invert mid ≈ 498 uV, N>=16 analog-fail. |
| OPA1611 | 3 | True | 9.7290e-05 | Exp 31 isolated |err|=576 uV. Datasheet-class Vos ≠ loaded residual. |
| OPA171 | 3 | True | 2.1402e-04 | Exp 23/24 TIA analog-fail. Ranked, not a low-offset candidate. |
| MCP6041 | 3 | True | n/a | 6 V CMOS. Rails below 2.61 V hidden swing. Negative control. |
| TLV6001 | 3 | True | 5.9522e-04 | Vos 595 uV and +/-2.5 V. Below hidden swing. Ranked out. |
| TLV9002 | 3 | True | 3.9611e-04 | Vos 396 uV and +/-2.5 V. Ranked out. |
| TL072-dual | 3 | True | n/a | JFET audio dual; typical Vos millivolts. Not a precision VG. |
| teaching miller | 4 | True | n/a | Exp 30/31 isolated invert transfer fail at fabric load/swing. |
| OPA1656 + shared replica mid on IN+ | 3 | True | 8.7500e-06 | Control: IN+ = replica mid. If Vos is input-referred this should add, not cancel. |
| OPA1656 + shared replica -mid on IN+ | 2 | True | 8.7500e-06 | Circuit cancellation. Sign flip is LEVEL 2. Amp still drives dest. |
| OPA1656 + replica output subtract | 2 | True | n/a | DC AZ. B-source also hijacks fabric drive. Mechanism test only. |
| OPA1656 + LEVEL 2 invert servo | 2 | True | n/a | Circuit correction. Not a physical device primitive. |
| OPA1656 invert + OPA1656 follower | 3 | True | 8.7500e-06 | Drive/offset split. Buffer is not assumed transparent. |

### Technology inventory

- PDK_ROOT=None
- IHP SG13G2 installed=False
- SkyWater installed=False
- r2_cmc OSDI binary present=False
- CMC r2_cmc support usable=False
- vendor macromodel dirs: ['C:\\ngspice\\examples\\optran\\models', 'C:\\ngspice\\examples\\p-to-n-examples']
- ngspice opamp examples: ['Models-for-Debian.txt', 'OPA1611.LIB', 'TL072-dual.lib', 'TL072.301', 'TLV6001.LIB', 'TLV9002.lib', 'opa1612c-dual.lib', 'opa1656.lib', 'opa1656c-dual.lib', 'MCP6041.txt', 'OPA171.txt']
- low-offset op-amp examples beyond OPA1656/1611: OPA1656 (model VNEG=8.75 uV) and OPA1611 (model Vos~97 uV) are the only local precision-class macros. No OP07/OPA189/chopper/auto-zero example is installed.

Installed PDK trees: none. PDK_ROOT is unset. SkyWater and IHP
SG13G2 howtos exist under ngspice/examples but the PDK trees are
not installed. No OSDI binaries. No CMC r2_cmc plugin. No
chopper / auto-zero / OP07 / OPA189 example is present.

If a suitable documented model is absent, the missing evidence is
a model/library, not another invented transistor circuit.

## 5. Isolated transfer (Gate B)

Gain -1, R1=R2=10 kOhm, representative load 4.91 kOhm,
Vin covering the hidden range including 0 and 2.61 V.
error = Vout + Vin.

| kind | Vin | Rload | Vout | Vmid | |err| | Iout est | pass |
| --- | --- | --- | --- | --- | --- | --- | --- |
| passive | 0 | 4914 | 0.0000e+00 | 0.0000e+00 | 0.0000e+00 | 0.0000e+00 | True |
| passive | 1 | 4914 | 1.9724e-01 | 5.9862e-01 | 1.1972e+00 | 8.0276e-05 | False |
| passive | 2.61 | 4914 | 5.1443e-01 | 1.5613e+00 | 3.1226e+00 | 2.0937e-04 | False |
| limit | 0 | 4914 | 0.0000e+00 | 0.0000e+00 | 0.0000e+00 | 0.0000e+00 | True |
| limit | 1 | 4914 | -9.9998e-01 | 9.9998e-06 | 2.0000e-05 | 3.0349e-04 | True |
| limit | 2.61 | 4914 | -2.6081e+00 | 2.6081e-05 | 5.2162e-05 | 7.9157e-04 | True |
| miller | 0 | 4914 | 7.6400e-04 | 3.8200e-04 | 7.6400e-04 | 1.9367e-07 | True |
| miller | 1 | 4914 | -9.4069e-01 | 2.9655e-02 | 5.9310e-02 | 2.8846e-04 | False |
| miller | 2.61 | 4914 | -6.3349e-01 | 9.8734e-01 | 1.9747e+00 | 2.9100e-04 | False |
| opa1656 | 0 | 4914 | 9.9624e-04 | 4.9811e-04 | 9.9624e-04 | 2.5255e-07 | True |
| opa1656 | 1 | 4914 | -9.9900e-01 | 4.9813e-04 | 9.9628e-04 | 3.0325e-04 | True |
| opa1656 | 2.61 | 4914 | -2.6072e+00 | 4.9816e-04 | 9.9635e-04 | 7.9133e-04 | True |
| opa1611 | 0 | 4914 | 5.5004e-04 | 1.0002e-04 | 5.5004e-04 | 1.5694e-07 | True |
| opa1611 | 1 | 4914 | -9.9992e-01 | -1.2344e-05 | 7.9513e-05 | 3.0347e-04 | True |
| opa1611 | 2.61 | 4914 | -2.6076e+00 | 9.7999e-05 | 5.8482e-04 | 7.9141e-04 | True |
| replica | 0 | 4914 | 1.9925e-03 | 9.9621e-04 | 1.9925e-03 | 5.0509e-07 | False |
| replica | 1 | 4914 | -9.9801e-01 | 9.9623e-04 | 1.9925e-03 | 3.0299e-04 | False |
| replica | 2.61 | 4914 | -2.6062e+00 | 9.9627e-04 | 1.9926e-03 | 7.9108e-04 | False |
| replica_neg | 0 | 4914 | 2.9062e-08 | -4.7903e-10 | 2.9062e-08 | 8.8682e-12 | True |
| replica_neg | 1 | 4914 | -1.0000e+00 | 1.9571e-08 | 6.9156e-08 | 3.0350e-04 | True |
| replica_neg | 2.61 | 4914 | -2.6082e+00 | 5.1814e-08 | 1.3364e-07 | 7.9158e-04 | True |
| replica_sub | 0 | 4914 | 2.2987e-12 | 4.9811e-04 | 2.2987e-12 | 4.9811e-08 | True |
| replica_sub | 1 | 4914 | -1.0000e+00 | 4.9813e-04 | 3.7794e-08 | 3.0355e-04 | True |
| replica_sub | 2.61 | 4914 | -2.6082e+00 | 4.9816e-04 | 9.8570e-08 | 7.9163e-04 | True |
| replica_disabled | 0 | 4914 | 9.9624e-04 | 4.9811e-04 | 9.9624e-04 | 2.5255e-07 | True |
| replica_disabled | 1 | 4914 | -9.9900e-01 | 4.9813e-04 | 9.9628e-04 | 3.0325e-04 | True |
| replica_disabled | 2.61 | 4914 | -2.6072e+00 | 4.9816e-04 | 9.9635e-04 | 7.9133e-04 | True |
| servo | 0 | 4914 | -2.2487e-08 | -2.6253e-08 | 2.2487e-08 | 4.9527e-12 | True |
| servo | 1 | 4914 | -1.0000e+00 | -2.6253e-08 | 2.2487e-08 | 3.0350e-04 | True |
| servo | 2.61 | 4914 | -2.6082e+00 | -2.6253e-08 | 2.2487e-08 | 7.9158e-04 | True |
| opa_follow_in | 0 | 4914 | 9.9624e-04 | 4.9811e-04 | 9.9624e-04 | 2.5255e-07 | True |
| opa_follow_in | 1 | 4914 | -1.6660e+00 | -5.5204e-01 | 6.6603e-01 | 4.5043e-04 | False |
| opa_follow_in | 2.61 | 4914 | -2.6072e+00 | 4.9815e-04 | 9.9634e-04 | 7.9133e-04 | True |
| opa_follow_out | 0 | 4914 | 1.4944e-03 | 4.9811e-04 | 1.4944e-03 | 4.0372e-07 | False |
| opa_follow_out | 1 | 4914 | -9.9858e-01 | 4.9323e-04 | 1.4223e-03 | 3.0312e-04 | False |
| opa_follow_out | 2.61 | 4914 | -2.6067e+00 | 4.9816e-04 | 1.4919e-03 | 7.9118e-04 | False |
| opa1656 | 2.61 | 1e+09 | -2.6072e+00 | 4.9816e-04 | 9.9634e-04 | 7.9133e-04 | True |
| replica_neg | 2.61 | 1e+09 | -2.6082e+00 | 4.8804e-08 | 1.2763e-07 | 7.9158e-04 | True |

## 6. Zero-input residual (Gate C)

Vin=0, feedback connected, 4.91 kOhm load, OP.

| kind | Vout | Vmid | other | |Vout+Vin| | mechanism |
| --- | --- | --- | --- | --- | --- |
| passive | 0.0000e+00 | 0.0000e+00 |  | 0.0000e+00 | no inversion; grounded divider |
| limit | 0.0000e+00 | 0.0000e+00 |  | 0.0000e+00 | see report |
| miller | 7.6400e-04 | 3.8200e-04 |  | 7.6400e-04 | output stage saturation / drive |
| opa1656 | 9.9624e-04 | 4.9811e-04 |  | 9.9624e-04 | virtual-ground / GWL floor ~498 uV, not datasheet Vos |
| opa1611 | 5.5004e-04 | 1.0002e-04 |  | 5.5004e-04 | see report |
| replica | 1.9925e-03 | 9.9621e-04 | rmid=4.9811e-04 | 1.9925e-03 | IN+=+Vos; input-referred pedestal should add |
| replica_neg | 2.9062e-08 | -4.7903e-10 | rmid=4.9811e-04, inp=-4.9811e-04 | 2.9062e-08 | IN+=-Vos; input-referred pedestal should cancel |
| replica_sub | 2.2987e-12 | 4.9811e-04 | rmid=4.9811e-04 | 2.2987e-12 | LEVEL 2 dest subtract; B-source drives load |
| replica_disabled | 9.9624e-04 | 4.9811e-04 | rmid=4.9811e-04 | 9.9624e-04 | see report |
| servo | -2.2487e-08 | -2.6253e-08 | inp=-4.9813e-04 | 2.2487e-08 | LEVEL 2 integrator on IN+ |
| opa_follow_in | 9.9624e-04 | 4.9811e-04 |  | 9.9624e-04 | see report |
| opa_follow_out | 1.4944e-03 | 4.9811e-04 |  | 1.4944e-03 | see report |

## 7. Output current and swing

| kind | Vin | |Vout| | Iout est | headroom to +/-15 V | failed |
| --- | --- | --- | --- | --- | --- |
| passive | 2.61 | 5.1443e-01 | 2.0937e-04 | 1.4486e+01 | False |
| limit | 2.61 | 2.6081e+00 | 7.9157e-04 | 1.2392e+01 | False |
| miller | 2.61 | 6.3349e-01 | 2.9100e-04 | 1.4367e+01 | False |
| opa1656 | 2.61 | 2.6072e+00 | 7.9133e-04 | 1.2393e+01 | False |
| opa1611 | 2.61 | 2.6076e+00 | 7.9141e-04 | 1.2392e+01 | False |
| replica | 2.61 | 2.6062e+00 | 7.9108e-04 | 1.2394e+01 | False |
| replica_neg | 2.61 | 2.6082e+00 | 7.9158e-04 | 1.2392e+01 | False |
| replica_sub | 2.61 | 2.6082e+00 | 7.9163e-04 | 1.2392e+01 | False |
| replica_disabled | 2.61 | 2.6072e+00 | 7.9133e-04 | 1.2393e+01 | False |
| servo | 2.61 | 2.6082e+00 | 7.9158e-04 | 1.2392e+01 | False |
| opa_follow_in | 2.61 | 2.6072e+00 | 7.9133e-04 | 1.2393e+01 | False |
| opa_follow_out | 2.61 | 2.6067e+00 | 7.9118e-04 | 1.2393e+01 | False |
| opa1656 | 2.61 | 2.6072e+00 | 7.9133e-04 | 1.2393e+01 | False |
| replica_neg | 2.61 | 2.6082e+00 | 7.9158e-04 | 1.2392e+01 | False |

## 8. N = 1/2/4/8/16/32 scaling

Primary promotion criterion: analog-pass at N=32.
One-copy network MAE is not invert validation.

### OPA1656 uncorrected

| N | MAE | max | acc | analog |
| --- | --- | --- | --- | --- |
| 1 | 5.3212e-04 | 3.1607e-03 | 1.0000 | True |
| 2 | 5.5439e-04 | 3.2850e-03 | 1.0000 | True |
| 4 | 6.1568e-04 | 3.3346e-03 | 1.0000 | True |
| 8 | 7.1547e-04 | 3.4407e-03 | 1.0000 | True |
| 16 | 1.4462e-03 | 5.8665e-03 | 1.0000 | False |
| 32 | 2.6377e-03 | 7.0360e-03 | 1.0000 | False |

### replica mid on IN+

| N | MAE | max | acc | analog |
| --- | --- | --- | --- | --- |
| 32 | 2.4105e+00 | 5.8246e+00 | 0.4167 | False |

### replica -mid on IN+

| N | MAE | max | acc | analog |
| --- | --- | --- | --- | --- |
| 1 | 5.1015e-04 | 3.1607e-03 | 1.0000 | True |
| 2 | 5.1015e-04 | 3.1607e-03 | 1.0000 | True |
| 4 | 5.1015e-04 | 3.1607e-03 | 1.0000 | True |
| 8 | 5.1014e-04 | 3.1607e-03 | 1.0000 | True |
| 16 | 5.1013e-04 | 3.1603e-03 | 1.0000 | True |
| 32 | 5.1013e-04 | 3.1603e-03 | 1.0000 | True |

### LEVEL 2 invert servo

| N | MAE | max | acc | analog |
| --- | --- | --- | --- | --- |
| 32 | 4.2441e-01 | 1.7889e+00 | 0.9167 | False |

Predicted vs measured: 32-OPA mean invert residual 9.9618e-04 produced F12 MAE 2.6377e-03. A cancelled residual should track that same scale.

OPA1656 isolated |err| is 996 uV at Vin=0, 1 V, and 2.61 V, loaded
and unloaded. That is a constant input-referred pedestal, not
signal-dependent finite-A error. OPA1611 is better (550-585 uV)
but still far above the 100 uV network-scale budget. Teaching
miller analog-passes only at Vin=0 and collapses to 1.97 V at
2.61 V / 4.91 kOhm (drive/swing, unchanged from Experiment 31).

A candidate must sit comfortably below 1e-3 V isolated because
32 copies accumulate. Only limit, replica_neg, replica_sub, and
the isolated servo meet that. Uncorrected OPA1656 is exactly on
the 1e-3 isolated line and fails N=16.

## 9. Correction / cancellation

The Experiment 31 residual is systematic (~996 uV, Vin-independent).
Vin=0 is the correct zero-signal state for this invert: src=0 means
zero invert input current. That is not the Experiment 24 Vin-only TIA mistake.

For an R1=R2 invert, Vout = -Vin + 2*Vmid and Vmid ~ Vos_eff.
IN+ = +replica_mid therefore sets Vmid ~ 2*Vos and doubles the
isolated residual (1.99 mV). On Network F that common-mode shift
is not merely 2x: F12 MAE becomes 2.41 with residual ~0.87 V.
IN+ = -replica_mid (LEVEL 2 sign of the LEVEL 3 mid) sets Vmid ~ 0
and leaves |Vout+Vin| ~ 30-130 nV isolated, 80 nV mean on F12.

The disabled-replica control is identical to uncorrected 32-OPA
(MAE 2.6377e-3). The improvement is the sign, not the extra amp.

| case | MAE | analog | note |
| --- | --- | --- | --- |
| replica present, cancellation disabled | 2.6377e-03 | False | negative control |
| shared replica mid -> IN+ | 2.4105e+00 | False | LEVEL 3 wiring; expected to add if Vos is input-referred |
| shared replica -mid -> IN+ | 5.1013e-04 | True | LEVEL 2 sign of LEVEL 3 pedestal; amp still drives dest |
| replica output subtract (B-source) | 2.6162e-03 | False | LEVEL 2 AZ; B-source hijacks drive |
| LEVEL 2 invert servo, 32 hidden | 4.2441e-01 | False | behavioral G-C on IN+; not a physical primitive |

## 10. Transient 100/200/500 us

DC correctness is not sampled-inference correctness.

| case | t | |Vout+Vin| | pass |
| --- | --- | --- | --- |
| opa1656 TRAN 100 us | 0.0001 | 9.9587e-04 | True |
| opa1656 TRAN 200 us | 0.0002 | 9.9587e-04 | True |
| opa1656 TRAN 500 us | 0.0005 | 9.9587e-04 | True |
| replica_neg TRAN 100 us | 0.0001 | 1.3477e-07 | True |
| replica_neg TRAN 200 us | 0.0002 | 1.3477e-07 | True |
| replica_neg TRAN 500 us | 0.0005 | 1.3477e-07 | True |
| servo TRAN 100 us | 0.0001 | 1.3477e-07 | True |
| servo TRAN 200 us | 0.0002 | 1.3477e-07 | True |
| servo TRAN 500 us | 0.0005 | 1.3477e-07 | True |
| isolated AZ 200+200 us | 0.0004 | n/a | meas failed (TRAN out of interval) |

The two-phase switch AZ TRAN did not emit a valid sample
(meas out of interval). That is a switch/TRAN artifact, not a
new offset mechanism. The DC equivalent of AZ on this invert is
the shared replica: Vin=0 on the replica is a true zero-signal
state, and replica_neg TRAN at 100/200/500 us matches the DC
residual (~135 nV). History A=0 -> B=2.61 -> C=1.0 -> A=0 at
200 us dwell stays <= 10 uV for replica_neg. Previous input
history does not restore the 996 uV pedestal.

100 us passes. 200 us passes. 500 us passes. Isolated servo TRAN
also nulls, but 32 network servos do not (F12 MAE 0.424).

A -> B -> C -> A isolated history (200 us dwell):

| kind | max |s| | samples |
| --- | --- | --- |
| opa1656 | 1.0049e-03 | [{'i': 0, 'vin': 0.0, 'v_out': 0.0009962431, 'abs_err': 0.0009962431}, {'i': 1, 'vin': 2.6081758652291698, 'v_out': -2.607171, 'abs_err': 0.0010048652291696492}, {'i': 2, 'vin': 1.0, 'v_out': -0.9990137, 'abs_err': 0.0009862999999999955}, {'i': 3, 'vin': 0.0, 'v_out': 0.0009958365000000001, 'abs_err': 0.0009958365000000001}] |
| replica_neg | 1.0000e-05 | [{'i': 0, 'vin': 0.0, 'v_out': 2.905788e-08, 'abs_err': 2.905788e-08}, {'i': 1, 'vin': 2.6081758652291698, 'v_out': -2.608167, 'abs_err': 8.865229169874311e-06}, {'i': 2, 'vin': 1.0, 'v_out': -0.99999, 'abs_err': 9.99999999995449e-06}, {'i': 3, 'vin': 0.0, 'v_out': 7.37891e-08, 'abs_err': 7.37891e-08}] |
| servo | 1.3800e-05 | [{'i': 0, 'vin': 0.0, 'v_out': -2.248803e-08, 'abs_err': 2.248803e-08}, {'i': 1, 'vin': 2.6081758652291698, 'v_out': -2.608177, 'abs_err': 1.1347708301912007e-06}, {'i': 2, 'vin': 1.0, 'v_out': -0.9999862, 'abs_err': 1.3799999999952739e-05}, {'i': 3, 'vin': 0.0, 'v_out': 2.32134e-06, 'abs_err': 2.32134e-06}] |

## 11. F12 / F40

F40 is run only if a candidate passed isolated + N=16 + N=32 + 200 us TRAN.

| case | set | MAE | max | acc | analog |
| --- | --- | --- | --- | --- | --- |
| replica_neg | F12 | 5.1013e-04 | 3.1603e-03 | 1.0000 | True |
| servo | F12 | 4.2441e-01 | 1.7889e+00 | 0.9167 | False |
| replica_neg | F40 | 4.8384e-04 | 3.4315e-03 | 1.0000 | True |

Comparisons: Experiment 29 nominal ~5.10e-4; Experiment 30 XSPICE limit
F40 ~4.86e-4; Experiment 31 OPA1656 N=1/8/16/32 = 5.32e-4 / 7.16e-4 /
1.45e-3 / 2.64e-3.

## 12. Negative controls

| control | result |
| --- | --- |
| passive grounded divider | isolated |err|=0.0000e+00 |
| teaching miller at worst load/swing | isolated |err|=1.9747e+00 |
| OPA1656 uncorrected | N=32 MAE=2.6377e-03 |
| one-copy network insertion | MAE=5.3212e-04 analog-pass |
| all-32 insertion uncorrected | MAE=2.6377e-03 analog-fail expected |
| cancellation disabled | MAE=2.6377e-03 |

## 13. Matching interaction

- Extra matching beyond R1/R2: replica identity: the shared replica must produce the same mid pedestal as every signal invert (same model, R, load, temp)
- Behavioral requirement: If replica cancellation is used, replica-to-signal mid matching must stay well below ~100 uV. That is a new relationship beyond R1/R2. R1/R2 residual <= 0.075% still applies.

No fake foundry Monte Carlo was run.

## 14. Realism, remaining ideal elements, limitations

- Realism level of the best candidate: LEVEL 3 OPA1656 + LEVEL 2 replica-sign cancellation
- Remaining ideal elements: TIA VCVS, ReLU B-source, stimulus sources, and any LEVEL 2 sign/servo/B-source used for cancellation. Frozen weights untouched.
- Explicit limitations: Local vendor tree has no chopper/auto-zero/precision <=50 uV op-amp whose loaded invert residual was measured below the 498 uV GWL floor. No PDK. No r2_cmc OSDI. Teaching miller cannot make the hidden swing/load.

## 15. Decision and next bottleneck

**PHYSICAL HIDDEN INVERTER PARTIALLY VALIDATED**

Shared replica with IN+ = -replica mid analog-passes isolated,
N=1..32, 100/200/500 us TRAN, F12 (MAE 5.101e-4), and F40
(MAE 4.838e-4, acc 1.0). That meets the analog map. It does
**not** meet SUCCESS as an uncorrected physical primitive:

* the OPA1656 cell still has a 498 uV loaded virtual-ground floor
* datasheet Vos (8.75 uV) is not that floor
* cancellation uses a LEVEL 2 VCVS sign of the replica mid
* replica-to-signal mid matching is a new relationship beyond R1/R2

A buffer is not transparent: follower-inside-loop is unstable at
Vin=1 V (|err|=0.666 V); follower-outside-loop adds ~498 uV.
Drive and offset do not separate for free. Teaching miller still
fails swing/current. Per-invert LEVEL 2 servo works isolated and
fails at 32 copies.

No locally documented uncorrected primitive meets ~100 uV
offset-scale residual + ~0.4-0.63 mA drive + ~2.61 V swing
at N=32. That missing evidence is a model/library (chopper /
auto-zero / precision VG macromodel, or a real PDK), not another
invented transistor circuit.

XSPICE `limit` remains the LEVEL 2 invert that already analog-
passes F40 without a replica. replica_neg is the best LEVEL 3
amp plus LEVEL 2 sign. Do not label the sign flip a physical
device.

Next bottleneck: a documented macromodel whose loaded invert mid
stays <=100 uV without a behavioral sign/servo, or a foundry PDK
that can implement that cell. Do not invent MOS W/L.

Plots: `results/exp32_inverter_scaling.png`,
`results/exp32_isolated_transfer.png`,
`results/exp32_zero_input_residual.png`,
`results/exp32_cancellation.png`.

JSON: `results/exp32_hidden_inverter_primitive.json`.
Inventory: `results/exp32_inverter_candidate_inventory.json`.
Circuits: `circuits/exp32_hidden_inverter_primitive/`.
