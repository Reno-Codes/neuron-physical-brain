==================================================
EXPERIMENT 33
DOCUMENTED PRECISION-INVERTER MODEL AND PDK GAP CLOSURE
==================================================

Frozen Experiment 9 weights. SPICE is the source of truth.
Experiments 1-32 were not overwritten. No Python correction,
no invented MOS W/L, no Network F in transistors.

Status: **PHYSICAL HIDDEN INVERTER PARTIALLY VALIDATED**

## 1. Objective

Determine whether a documented precision macromodel or documented
PDK can be introduced that meets the Experiment 31/32 hidden-invert
requirements without behavioral output correction.

## 2. Environment inventory (before any download)

See `results/exp33_model_inventory_before.json`.

- PDK_ROOT=None
- IHP installed=False
- SkyWater installed=False
- OSDI binaries=False
- Already installed precision macros: OPA1656, OPA1611, OPA171,
  TLV6001, TLV9002, MCP6041, TL072, AD22057N.
- Not installed before this experiment: OPA189 / OPA192 / OPA388,
  OP07, chopper/AZ switching models, IHP, SkyWater, r2_cmc OSDI.

## 3. Model acquisition provenance

Official TI PSpice zips were downloaded after the before-inventory.
Model files were not edited. Wrappers were not added.

| part | source | subckt | architecture | model Vos DC | unmodified |
| --- | --- | --- | --- | --- | --- |
| OPA189 | https://www.ti.com/lit/zip/sbomae9 | OPAx189 | Green-Williams-Lis | -1.8684e-06 | True |
| OPA192 | https://www.ti.com/lit/zip/sbom862 | OPAx192 | Green-Williams-Lis | -2.8800e-06 | True |
| OPA388 | https://www.ti.com/lit/zip/sbomab3 | OPAx388 | Green-Williams-Lis | -3.0020e-07 | True |

OPA189/192/388 are Green-Williams-Lis macromodels. Offset is a
static VOS_DRIFT source (DC + linear TEMP), not switching chopper
or auto-zero dynamics. Do not claim physical chopper validation.

PDK track: IHP and SkyWater remain howto-only. No PDK was cloned.
The SkyWater example is a 1.8 V digital CMOS inverter and cannot
meet the 2.61 V hidden swing. IHP examples are device/RO benches
that would still require inventing an analog invert cell.

## 4. Standardized isolated bench

Gain -1, R1=R2=10 kOhm, Rload=4.91 kOhm. error = Vout + Vin.
Tier 1 threshold: max |err| < 1e-04 V.

| kind | Vin | Vout | Vmid | |err| | Iout est | tier1 |
| --- | --- | --- | --- | --- | --- | --- |
| limit | 0 | 0.0000e+00 | 0.0000e+00 | 0.0000e+00 | 0.0000e+00 | True |
| limit | -1 | 9.9998e-01 | -9.9998e-06 | 2.0000e-05 | 3.0349e-04 | True |
| limit | 1 | -9.9998e-01 | 9.9998e-06 | 2.0000e-05 | 3.0349e-04 | True |
| limit | 1.5 | -1.5000e+00 | 1.5000e-05 | 2.9999e-05 | 4.5524e-04 | True |
| limit | 2 | -2.0000e+00 | 2.0000e-05 | 3.9999e-05 | 6.0699e-04 | True |
| limit | 2.5 | -2.5000e+00 | 2.5000e-05 | 4.9999e-05 | 7.5874e-04 | True |
| limit | 2.61 | -2.6081e+00 | 2.6081e-05 | 5.2162e-05 | 7.9157e-04 | True |
| limit | -2.61 | 2.6081e+00 | -2.6081e-05 | 5.2162e-05 | 7.9157e-04 | True |
| miller | 0 | 7.6400e-04 | 3.8200e-04 | 7.6400e-04 | 1.9367e-07 | False |
| miller | 1 | -9.4069e-01 | 2.9655e-02 | 5.9310e-02 | 2.8846e-04 | False |
| miller | 1.5 | -8.4523e-01 | 3.2738e-01 | 6.5477e-01 | 2.8927e-04 | False |
| miller | 2.61 | -6.3349e-01 | 9.8734e-01 | 1.9747e+00 | 2.9100e-04 | False |
| opa1656 | 0 | 9.9624e-04 | 4.9811e-04 | 9.9624e-04 | 2.5255e-07 | False |
| opa1656 | -1 | 1.0010e+00 | 4.9809e-04 | 9.9620e-04 | 3.0375e-04 | False |
| opa1656 | 1 | -9.9900e-01 | 4.9813e-04 | 9.9628e-04 | 3.0325e-04 | False |
| opa1656 | 1.5 | -1.4990e+00 | 4.9814e-04 | 9.9630e-04 | 4.5500e-04 | False |
| opa1656 | 2 | -1.9990e+00 | 4.9815e-04 | 9.9632e-04 | 6.0675e-04 | False |
| opa1656 | 2.5 | -2.4990e+00 | 4.9816e-04 | 9.9634e-04 | 7.5850e-04 | False |
| opa1656 | 2.61 | -2.6072e+00 | 4.9816e-04 | 9.9635e-04 | 7.9133e-04 | False |
| opa1656 | -2.61 | 2.6092e+00 | 4.9805e-04 | 9.9614e-04 | 7.9183e-04 | False |
| opa1611 | 0 | 5.5004e-04 | 1.0002e-04 | 5.5004e-04 | 1.5694e-07 | False |
| opa1611 | -1 | 1.0011e+00 | 3.3138e-05 | 1.1064e-03 | 3.0383e-04 | False |
| opa1611 | 1 | -9.9992e-01 | -1.2344e-05 | 7.9513e-05 | 3.0347e-04 | True |
| opa1611 | 1.5 | -1.4995e+00 | 1.0701e-04 | 5.0392e-04 | 4.5511e-04 | False |
| opa1611 | 2 | -1.9995e+00 | 9.4743e-05 | 5.3175e-04 | 6.0685e-04 | False |
| opa1611 | 2.5 | -2.4995e+00 | 1.1039e-04 | 5.1435e-04 | 7.5860e-04 | False |
| opa1611 | 2.61 | -2.6076e+00 | 9.7999e-05 | 5.8482e-04 | 7.9141e-04 | False |
| opa1611 | -2.61 | 2.6084e+00 | 1.8934e-04 | 2.7050e-04 | 7.9164e-04 | False |
| opa189 | 0 | -6.5619e-07 | 2.1930e-08 | 6.5619e-07 | 2.0135e-10 | True |
| opa189 | -1 | 1.0000e+00 | 1.8313e-08 | 6.6342e-07 | 3.0350e-04 | True |
| opa189 | 1 | -1.0000e+00 | 2.5548e-08 | 6.4895e-07 | 3.0350e-04 | True |
| opa189 | 1.5 | -1.5000e+00 | 2.7357e-08 | 6.4533e-07 | 4.5525e-04 | True |
| opa189 | 2 | -2.0000e+00 | 2.9166e-08 | 6.4172e-07 | 6.0700e-04 | True |
| opa189 | 2.5 | -2.5000e+00 | 3.0975e-08 | 6.3810e-07 | 7.5875e-04 | True |
| opa189 | 2.61 | -2.6082e+00 | 3.1366e-08 | 6.3731e-07 | 7.9158e-04 | True |
| opa189 | -2.61 | 2.6082e+00 | 1.2495e-08 | 6.7506e-07 | 7.9158e-04 | True |
| opa192 | 0 | 7.4022e-06 | 3.6862e-06 | 7.4022e-06 | 1.8779e-09 | True |
| opa192 | -1 | 1.0000e+00 | 3.3900e-06 | 6.8099e-06 | 3.0350e-04 | True |
| opa192 | 1 | -9.9999e-01 | 3.9823e-06 | 7.9945e-06 | 3.0350e-04 | True |
| opa192 | 1.5 | -1.5000e+00 | 4.2245e-06 | 8.7354e-06 | 4.5525e-04 | True |
| opa192 | 2 | -2.0000e+00 | 4.4069e-06 | 9.4722e-06 | 6.0700e-04 | True |
| opa192 | 2.5 | -2.5000e+00 | 4.5808e-06 | 9.3548e-06 | 7.5875e-04 | True |
| opa192 | 2.61 | -2.6082e+00 | 4.6121e-06 | 8.6785e-06 | 7.9158e-04 | True |
| opa192 | -2.61 | 2.6082e+00 | 2.7630e-06 | 6.4088e-06 | 7.9158e-04 | True |
| opa388 | 0 | 9.9984e-08 | 1.9998e-07 | 9.9984e-08 | 3.0347e-11 | True |
| opa388 | 1 | -1.0000e+00 | 2.3980e-07 | 1.7963e-07 | 3.0350e-04 | True |
| opa388 | 1.5 | -1.5000e+00 | 2.5972e-07 | 2.1946e-07 | 4.5525e-04 | True |
| opa388 | 2 | -2.0000e+00 | 2.7963e-07 | 2.5928e-07 | 6.0700e-04 | True |
| opa388 | 2.5 | -2.5000e+00 | 1.8261e-06 | 3.3523e-06 | 7.5875e-04 | True |
| opa388 | 2.61 | -2.5176e+00 | 4.5271e-02 | 9.0546e-02 | 7.6863e-04 | False |
| replica_neg_1656 | 0 | 2.9062e-08 | -4.7903e-10 | 2.9062e-08 | 8.8682e-12 | True |
| replica_neg_1656 | -1 | 1.0000e+00 | -2.0529e-08 | 1.1038e-08 | 3.0350e-04 | True |
| replica_neg_1656 | 1 | -1.0000e+00 | 1.9571e-08 | 6.9156e-08 | 3.0350e-04 | True |
| replica_neg_1656 | 1.5 | -1.5000e+00 | 2.9595e-08 | 8.9205e-08 | 4.5525e-04 | True |
| replica_neg_1656 | 2 | -2.0000e+00 | 3.9621e-08 | 1.0927e-07 | 6.0700e-04 | True |
| replica_neg_1656 | 2.5 | -2.5000e+00 | 4.9645e-08 | 1.2930e-07 | 7.5875e-04 | True |
| replica_neg_1656 | 2.61 | -2.6082e+00 | 5.1814e-08 | 1.3364e-07 | 7.9158e-04 | True |
| replica_neg_1656 | -2.61 | 2.6082e+00 | -5.2772e-08 | 7.5524e-08 | 7.9158e-04 | True |
| opa189 | 2.61 | -2.6082e+00 | 3.0532e-08 | 6.3898e-07 | 7.9158e-04 | True |

## 5. Candidate ranking (loaded residual, not datasheet Vos)

| rank | candidate | max |err| | mean |err| | tier1 | note |
| --- | --- | --- | --- | --- | --- |
| 1 | replica_neg_1656 | 1.3364e-07 | 8.0775e-08 | True | Exp 32 LEVEL 2 sign control. |
| 2 | opa189 | 6.7506e-07 | 6.5076e-07 | True | GWL static Vos ~1.87 uV. Not a switching chopper. |
| 3 | opa192 | 9.4722e-06 | 8.1070e-06 | True | GWL e-trim. Isolated residual ~8 uV. |
| 4 | limit | 5.2162e-05 | 3.3040e-05 | True | LEVEL 2 behavioral. |
| 5 | opa1656 | 9.9635e-04 | 9.9627e-04 | False | Exp 32 498 uV GWL floor. Control. |
| 6 | opa1611 | 1.1064e-03 | 5.1767e-04 | False | Exp 32 ~550-585 uV. Control. |
| 7 | opa388 | 9.0546e-02 | 1.5092e-02 | False | 5.5 V zero-drift. Clips at 2.61 V on +/-2.5 V. |
| 8 | miller | 1.9747e+00 | 6.7238e-01 | False | Teaching card drive/swing fail. |

## 6. Physical sign / replica cancellation

Experiment 32 recovered the map with OPA1656 + LEVEL 2 sign of
replica mid. This experiment asks whether a documented amplifier
can implement that sign, and whether a precision invert can remove
the need for replica cancellation entirely.

| case | MAE or |err| | analog | note |
| --- | --- | --- | --- |
| physical OPA189 sign of replica mid Vin=0 | 1.2833e-06 | True | no E-source |
| physical OPA189 sign of replica mid Vin=1 | 1.2432e-06 | True | no E-source |
| physical OPA189 sign of replica mid Vin=2.60818 | 1.1787e-06 | True | no E-source |
| replica present, cancellation disabled | 2.6377e-03 | False | negative control |
| Exp 32 LEVEL 2 replica -mid | 5.1013e-04 | True | control, behavioral sign |

A documented OPA189 invert of the OPA1656 replica mid implements
the Experiment 32 sign **without an E-source** at ~1.2 uV isolated.
That answers the physical-sign question on the isolated bench.
It was not inserted at N=32: the simpler uncorrected OPA189 invert
already fails the 32-copy accumulation test, so a 32+32+replica
composite would not be a smaller claim.

## 7. Temperature

| kind | Vin | temp C | |err| | Vmid |
| --- | --- | --- | --- | --- |
| opa189 | 0 | -40.0 | 1.3262e-06 | -3.1307e-07 |
| opa189 | 2.61 | -40.0 | 1.3073e-06 | -3.0363e-07 |
| opa189 | 0 | 27.0 | 6.5619e-07 | 2.1930e-08 |
| opa189 | 2.61 | 27.0 | 6.3731e-07 | 3.1366e-08 |
| opa189 | 0 | 85.0 | 7.6158e-08 | 3.1193e-07 |
| opa189 | 2.61 | 85.0 | 5.7286e-08 | 3.2137e-07 |
| opa1656 | 0 | -40.0 | 9.2924e-04 | 4.6461e-04 |
| opa1656 | 2.61 | -40.0 | 9.2935e-04 | 4.6466e-04 |
| opa1656 | 0 | 27.0 | 9.9624e-04 | 4.9811e-04 |
| opa1656 | 2.61 | 27.0 | 9.9635e-04 | 4.9816e-04 |
| opa1656 | 0 | 85.0 | 1.0542e-03 | 5.2711e-04 |
| opa1656 | 2.61 | 85.0 | 1.0543e-03 | 5.2716e-04 |

## 8. N = 1/2/4/8/16/32 scaling

### OPA1656 uncorrected (control)

| N | MAE | max | acc | analog |
| --- | --- | --- | --- | --- |
| 1 | 5.3212e-04 | 3.1607e-03 | 1.0000 | True |
| 32 | 2.6377e-03 | 7.0360e-03 | 1.0000 | False |

### OPA189

| N | MAE | max | acc | analog |
| --- | --- | --- | --- | --- |
| 1 | 5.1014e-04 | 3.1607e-03 | 1.0000 | True |
| 2 | 5.3937e-04 | 2.8727e-03 | 1.0000 | True |
| 4 | 5.8823e-04 | 2.7598e-03 | 1.0000 | True |
| 8 | 5.7634e-04 | 3.1605e-03 | 1.0000 | True |
| 16 | 7.6206e-04 | 6.5760e-03 | 1.0000 | True |
| 32 | 1.0142e-03 | 8.9672e-03 | 1.0000 | False |

N=32 fails analog by 1.4% of the 1e-3 bar (MAE 1.014e-3). That is
**not** 32 x isolated 0.66 uV. A probed 32-copy netlist shows mean
invert |Vout+Vin| = 575 uV and max 2.33 mV (mean |Vmid| 290 uV).
Independent +/-15 V supplies on all 32 instances still analog-fail
(MAE 2.061e-3). The isolated uV-scale residual does not survive
32 simultaneous GWL instances. Do not relax the N=32 rule.

### OPA192

OPA192 isolated analog-passes. Every fabric insertion timed out or
failed to emit outputs (N=1 used the full 360 s budget). That is
ngspice/GWL incompatibility in the resistor fabric, not a datasheet
swing problem.

| N | MAE | max | acc | analog |
| --- | --- | --- | --- | --- |
| 1 | n/a | n/a | n/a | timeout |
| 2 | n/a | n/a | n/a | fail |
| 4 | n/a | n/a | n/a | fail |
| 8 | n/a | n/a | n/a | fail |
| 16 | n/a | n/a | n/a | fail |
| 32 | n/a | n/a | n/a | fail |

## 9. Transient 100/200/500 us and A-B-C-A

| case | t | |err| | pass |
| --- | --- | --- | --- |
| opa189 TRAN 100 us | 0.0001 | 1.1348e-06 | True |
| opa189 TRAN 200 us | 0.0002 | 1.1348e-06 | True |
| opa189 TRAN 500 us | 0.0005 | 1.1348e-06 | True |
| opa1656 TRAN 100 us | 0.0001 | 9.9587e-04 | True |
| opa1656 TRAN 200 us | 0.0002 | 9.9587e-04 | True |
| opa1656 TRAN 500 us | 0.0005 | 9.9587e-04 | True |

A -> B -> C -> A (200 us dwell):

- opa189: max |err|=1.0000e-06 pass=True
- opa1656: max |err|=1.0049e-03 pass=False

## 10. F12 / F40

Nominal F12 MAE=5.1015e-04 acc=1.0000

| case | set | MAE | max | acc | analog |
| --- | --- | --- | --- | --- | --- |
| XSPICE limit 32 hidden | F12 | 5.1165e-04 | 3.2170e-03 | 1.0000 | True |
| Exp 32 LEVEL 2 replica -mid | F12 | 5.1013e-04 | 3.1603e-03 | 1.0000 | True |
| opa189 | F12 | 1.0142e-03 | 8.9672e-03 | 1.0000 | False |

## 11. Power accounting

SPICE supply current of the macromodel, not silicon power.

Isolated OPA189 |I(Vdd)|=-1.3000e-03 A, P~|I|*30 V = 3.9000e-02 W per primitive. 32 hidden estimate 1.2480e+00 W. TIA/ReLU still ideal, so this is not full Network F silicon power.

## 12. Negative controls

| control | result |
| --- | --- |
| XSPICE limit | F12 MAE=5.1165e-04 |
| OPA1656 uncorrected N=32 | MAE=2.6377e-03 |
| OPA1611 isolated 2.61 V | |err|=5.8482e-04 |
| teaching miller 2.61 V | |err|=1.9747e+00 |
| Exp 32 replica -mid | F12 MAE=5.1013e-04 |
| cancellation disabled | F12 MAE=2.6377e-03 |
| OPA189 one-copy | MAE=5.1014e-04 |
| OPA189 N=32 | MAE=1.0142e-03 |

## 13. Realism, limitations, next bottleneck

- Realism level: LEVEL 3 vendor macromodel (GWL, static Vos)
- Remaining ideal: TIA VCVS, ReLU B-source, stimulus sources. Invert is a LEVEL 3 macromodel. Zero-drift is a static VOS_DRIFT term, not chopping.
- Limitations: Not silicon. Not a PDK. OPA189 does not implement chopper switching. Isolated uV residual does not survive N=32. OPA192 does not converge in the fabric. PDK trees were not installed.
- Failure classes:
  A. Precision macromodel library: closed for acquisition (official TI zips installed).
  B. PDK: still missing.
  C. ngspice incompatibility: OPA192 in the fabric.
  D. Shared virtual-ground artifact: still true for OPA1656 (498 uV). Not the isolated OPA189 floor.
  E. Required N=32 performance: not achieved with tested uncorrected primitives.

The architecture can still recover the map (XSPICE limit; Exp 32 replica -mid). Do not read N=32 OPA189 as "the encoding cannot work."

**PHYSICAL HIDDEN INVERTER PARTIALLY VALIDATED**

OPA189 is a documented uncorrected primitive that passes the isolated
extracted bench (max |err| 0.68 uV), isolated 100/200/500 us TRAN,
A-B-C-A, and temperature -40/27/85 C, plus N<=16. It fails N=32
(F12 MAE 1.014e-3) and therefore did not earn F40. The N=32 error
is a multi-instance residual (~575 uV mean invert error on a probed
copy), not 32 x the isolated 0.66 uV, and independent supplies do
not remove it.

Next bottleneck: a documented invert whose **32-copy** loaded residual
stays at the isolated uV scale, or accept a LEVEL 2 invert / replica
sign and host Experiment 29 on a resistor PDK. Do not invent MOS.

JSON: `results/exp33_documented_precision_primitive.json`.
Ranking: `results/exp33_candidate_ranking.json`.
Circuits: `circuits/exp33_documented_precision_primitive/`.
