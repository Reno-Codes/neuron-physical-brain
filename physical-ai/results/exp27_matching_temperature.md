==================================================
EXPERIMENT 27
MATCHING AND TEMPERATURE OF THE DEVICE-LEVEL NEURON
==================================================

Frozen Experiment 9 weights. SPICE is the source of truth.
Experiments 1–26 were not overwritten. No Python correction,
no affine fit, no per-weight calibration, no new encoding.
IHP SG13G2 is not installed. No foundry resistor TCR or MOS
mismatch PDF was invented.

## 1. Objective

Determine whether the Experiment 26 miller TIA + miller servo on
frozen Network F o2 can be made accurate and temperature-stable
enough to be a credible physical computation primitive.
The two measured floors were 0.5% resistor mismatch and MOS
temperature drift of the 27 °C DW/servo null.
The neuron-level analog target is MAE ≤ 1e-3 without changing
frozen weights and without Python correction.

## 2. Experiment 26 baseline

- o2 miller+servo at 27 °C, ±2.5 V: |Vlin−z| ≈ 5.6283e-05, Vsum ≈ −0.67 µV
- 0.5% independent R: MAE ≈ 1.0203e-02 (tiled-by-R 6.9323e-03)
- −40 / 85 °C: |err| ≈ 4.0447e-03 / 4.8168e-03
- 100 µs–1 ms dwell analog-pass at 27 °C
- transistor-level simulated power ≈ 3.1526e-03 (one neuron)
- Teaching BSIM3v3, not IHP, not silicon

This experiment's nominal 27 °C replay: |err|=5.6283e-05, P=3.1526e-03.

## 3. Resistor mismatch mechanism

Architecture A computes Vlin ≈ −Rf · Σ Vin_i G_i. Independent relative
errors on Rf and the G_i do not cancel. A global (common-mode) scale
on every resistor leaves Rf·G invariant to first order — the neuron
needs ratio accuracy, not absolute R.

Mismatch model: each logical resistor independently uniform in ±tol
or ±tol/√N. Not a foundry PCM. Not extracted layout.

Independent mismatch vs tolerance (N=1, 8 draws, max-|z| vector):
| tol | MAE | max | pass frac |
| --- | --- | --- | --- |
| 1.0000e-03 | 2.2232e-03 | 4.7329e-03 | 0.250 |
| 2.5000e-03 | 3.7490e-03 | 6.7860e-03 | 0.250 |
| 5.0000e-03 | 9.5440e-03 | 2.6314e-02 | 0.000 |
| 1.0000e-02 | 2.2587e-02 | 3.6334e-02 | 0.000 |

Which resistors dominate at 0.5%:
| subset | MAE | max | pass frac |
| --- | --- | --- | --- |
| rf_only | 4.2469e-03 | 7.2851e-03 | 0.250 |
| weights_only | 4.2703e-03 | 7.4417e-03 | 0.125 |
| passive_only | 5.9767e-03 | 1.2949e-02 | 0.125 |

## 4. Tiling results

Fixed N tiles per logical resistor (statistical 1/√N on every R).
Area proxy = n_logical × N. o2 has 80 logical resistors.
This is an area proxy (resistor count), not die area. No documented
resistor geometry is available.

| N | unit-R proxy | MAE | max | pass frac | P (W) |
| --- | --- | --- | --- | --- | --- |
| 1 | 80 | 6.3545e-03 | 1.6987e-02 | 0.125 | 3.1518e-03 |
| 4 | 320 | 3.9737e-03 | 6.3901e-03 | 0.125 | 3.1525e-03 |
| 8 | 640 | 2.6777e-03 | 7.1850e-03 | 0.250 | 3.1524e-03 |
| 16 | 1280 | 2.6156e-03 | 5.0869e-03 | 0.250 | 3.1526e-03 |

1/√N projection from this run's N=1 MAE to |err|≤1e-3: N ≥ 41.
Exp 26's 1.02e-2 N=1 MAE would imply N ≥ 105. Both are area-proxy
numbers, not die area. Measured tiling flattens between N=8 and N=16:
independent tiling of all 80 resistors is an inefficient way to buy
ratio accuracy. MOS Iq does not change with N.

## 5. Ratio-matching results

Compared at 0.5%, 8 Monte Carlo draws on the max-|z| vector.
Common-centroid is a statistical/layout abstraction, not a fabricated layout.

| model | N | MAE | max | pass frac |
| --- | --- | --- | --- | --- |
| independent | 1 | 8.4220e-03 | 1.5756e-02 | 0.000 |
| common_mode | 1 | 5.6317e-05 | 5.6444e-05 | 1.000 |
| ratio_matched | 1 | 8.9247e-04 | 2.5531e-03 | 0.625 |
| segmented_N16 | 16 | 1.8407e-03 | 5.4559e-03 | 0.500 |
| centroid_stat | 1 | 2.8445e-03 | 6.0726e-03 | 0.375 |

Common-mode 0.5% is invisible (MAE = nominal). Architecture A is
sensitive to resistor *ratios*, not absolute R. Ratio-matched
(shared fractional error on Rf+weights/bias, paired dividers/inverts,
15% local residual) is the physical matching style that approaches
the 1e-3 bar without huge N.

## 6. Positive/negative path matching

| model | MAE | max | pass frac |
| --- | --- | --- | --- |
| pos_only | 3.8332e-03 | 8.2131e-03 | 0.125 |
| neg_only | 7.4079e-04 | 1.4360e-03 | 0.625 |
| pn_independent | 2.9243e-03 | 7.8156e-03 | 0.500 |
| pn_correlated | 4.3054e-03 | 8.1624e-03 | 0.000 |
| pn_systematic | 1.5976e-02 | 1.5976e-02 | 0.000 |

Positive-path-only mismatch is larger than negative-path-only on o2
(the max-|z| vector weights the positive fabric). Correlated +/−
(same u on a signed pair) does **not** beat independent +/− in this
sample — pair correlation without Rf correlation is not ratio matching.
Systematic polarity (+tol on p, −tol on n) is the worst signed-path
error (same lesson as Experiment 15). Differential pair matching
without TIA-ratio matching is not a substitute for more unit resistors
that include Rf.

## 7. Temperature decomposition

Default ngspice resistors have no TC1/TC2. No foundry TCR was invented.
Therefore `.temp` is a MOS-only experiment (BSIM3 kt1/ute).
R-only temperature was **not simulated** because no documented resistor
TC exists in this installation. Combined T = MOS-only in this netlist.
Do not read these numbers as a thin-film resistor temperature result.

CASE 1 — single stored 27 °C DW + live servo (Exp 26 replay):
| T (°C) | |Vlin−z| | Vsum (V) | Vsrv (V) | P (W) | analog |
| --- | --- | --- | --- | --- | --- |
| -40.0 | 4.0447e-03 | 4.8350e-05 | 6.4774e-04 | 3.1807e-03 | False |
| 27.0 | 5.6283e-05 | -6.6876e-07 | 1.0067e-03 | 3.1526e-03 | True |
| 85.0 | 4.8168e-03 | -5.7572e-05 | 1.4182e-03 | 3.1357e-03 | False |

This reproduces Experiment 26: the servo cannot cancel its own Vos(T).
Vsum and Vsrv move with temperature; the 27 °C geometric DW is a
manual calibration, not a temperature-stable reference.

## 8. Auto-zero / compensation architecture

Rejected after measurement (do not promote):

- Replica on TIA IN+ with servo off: cancels Vos but not finite A
  (A_eff ~ 1.7e3 → |err| ~ 8e-2). Negative control.
- Hold Vsrv after AZ and disconnect the live servo: inference with
  IN+ frozen at the AZ null is no-servo. |err| ~ 8e-2. The live
  servo must stay in the loop.
- Servo-miller replica driving servo IN+ (CASE 2): continuous, no
  clock, extra miller. Buffer Vos(T) ≠ integrator Vos(T). Temperature
  error *increased* versus CASE 1.
| T (°C) | |Vlin−z| | Vsum (V) | Vsrv (V) | P (W) | analog |
| --- | --- | --- | --- | --- | --- |
| -40.0 | 8.1189e-03 | 9.7051e-05 | 6.9835e-04 | 4.1355e-03 | False |
| 27.0 | 6.1123e-05 | -7.2662e-07 | 1.0067e-03 | 4.1004e-03 | True |
| 85.0 | 9.5560e-03 | -1.1422e-04 | 1.3552e-03 | 4.0789e-03 | False |

- MOS miller wired as a voltage-mode difference amp (Vraw−Vhold):
  closed-loop gain collapsed to ~0.55 (buffers the IN+ divider).
  This teaching miller is a TIA/VG amp, not a proven high-Z subtractor.
| T (°C) | |Vlin−z| | Vsum (V) | Vsrv (V) | P (W) | analog |
| --- | --- | --- | --- | --- | --- |
| -40.0 | 7.8057e-01 | 4.6220e-05 | 7.9465e-04 | 5.2123e-03 | False |
| 27.0 | 7.8171e-01 | -2.9163e-06 | 1.2205e-03 | 5.1678e-03 | False |
| 85.0 | 7.8311e-01 | -6.3359e-05 | 1.7063e-03 | 5.1410e-03 | False |

- Summing-node current injection of Vhold/Rf through a PCH+Rf replica:
  did not move the 85 °C pedestal (servo re-equilibrates to the same
  Vsum target; the stored AZ voltage is not an effective KCL trim here).
| T (°C) | |Vlin−z| | Vsum (V) | Vsrv (V) | P (W) | analog |
| --- | --- | --- | --- | --- | --- |
| -40.0 | 3.9696e-03 | 4.7628e-05 | 6.4793e-04 | 3.1807e-03 | False |
| 27.0 | 8.9070e-05 | -2.3112e-06 | 1.0060e-03 | 3.1526e-03 | True |
| 85.0 | 4.8417e-03 | -6.0961e-05 | 1.4158e-03 | 3.1356e-03 | False |

CASE 3 (promoted for DC/temp accuracy) — unbuffered capacitive CDS:
TIA output is n1raw. Ccds from n1raw to n1lin. During 200 µs AZ
(Vin=Vref=0) an NCH shorts n1lin to analog ground 0. After AZ,
V(n1lin)=Vraw(t)−Vraw(az). Live servo remains. No Python Vos table.
The output is a **high-Z capacitor plate** — a real node voltage,
not a driven pad. A physical next stage would need a buffer.
| T (°C) | |Vlin−z| | Vsum (V) | Vsrv (V) | P (W) | analog |
| --- | --- | --- | --- | --- | --- |
| -40.0 | 1.4921e-04 | 4.9545e-05 | 6.4798e-04 | 3.1807e-03 | True |
| 27.0 | 2.5723e-04 | -5.9062e-07 | 1.0059e-03 | 3.1526e-03 | True |
| 85.0 | 4.5701e-04 | -6.1286e-05 | 1.4153e-03 | 3.1356e-03 | True |

Driven-output attempt — same Ccds plus a miller follower on n1cap:
extra ~2 mW. Follower common-mode offset at |z|≈1.73 V is ~0.6–1.2 mV.
85 °C / 200 µs analog-fails; 500 µs barely passes. Not promoted if
the 200 µs sampled-inference regime must be kept.
| T (°C) | |Vlin−z| | Vsum (V) | Vsrv (V) | P (W) | analog |
| --- | --- | --- | --- | --- | --- |
| -40.0 | 3.0533e-04 | 4.8047e-05 | 6.4798e-04 | 5.1568e-03 | True |
| 27.0 | 6.5820e-04 | -8.1397e-07 | 1.0059e-03 | 5.1064e-03 | True |
| 85.0 | 1.1777e-03 | -5.9770e-05 | 1.4153e-03 | 5.0763e-03 | False |

LEVEL 2 reference — VCVS subtract of Vraw−Vhold (labeled, not the
device-level claim). Confirms the CDS *algorithm* meets MAE ≤ 1e-3
over −40/27/85 °C when the subtractor is ideal.
| T (°C) | |Vlin−z| | Vsum (V) | Vsrv (V) | P (W) | analog |
| --- | --- | --- | --- | --- | --- |
| -40.0 | 9.6639e-05 | 4.9545e-05 | 6.4798e-04 | 3.1807e-03 | True |
| 27.0 | 1.2523e-05 | -5.9062e-07 | 1.0059e-03 | 3.1526e-03 | True |
| 85.0 | 2.0043e-04 | -6.1286e-05 | 1.4153e-03 | 3.1356e-03 | True |

## 9. Dynamic behavior

Unbuffered capacitive CDS at 85 °C (MOS-only .temp), AZ = 200 µs:
| dwell | |Vlin−z| | analog |
| --- | --- | --- |
| 1.0000e-04 | 1.7593e-03 | False |
| 2.0000e-04 | 4.5701e-04 | True |
| 5.0000e-04 | 2.3699e-04 | True |
| 1.0000e-03 | 2.5774e-04 | True |

Multi-input A–B–C–A at 200 µs dwell, 85 °C, one AZ then four inferences:
| step | z | Vlin | |err| | analog |
| --- | --- | --- | --- | --- |
| 0 | 1.7286e+00 | 1.7279e+00 | 7.0572e-04 | True |
| 1 | -6.2892e-01 | -6.2843e-01 | 4.9698e-04 | True |
| 2 | 1.7286e+00 | 1.7277e+00 | 8.5461e-04 | True |
| 3 | 1.7286e+00 | 1.7283e+00 | 2.5977e-04 | True |
all_pass=True; max|err|=8.5461e-04.

100 µs dwell analog-fails at 85 °C (|err|≈1.76e-3). The Experiment 26
100 µs pass was at 27 °C without CDS. With MOS-only temperature and
capacitive CDS, the sampled-inference floor is 200 µs, not 100 µs.
200 µs–1 ms analog-pass, including A–B–C–A with no memory of the
previous input above the analog bar. The miller-follower driven
output fails 85 °C / 200 µs and is not promoted.

## 10. Power / resource cost

| method | P (W) |
| --- | --- |
| CASE1 servo 27C | 3.1526e-03 |
| CASE2 replica 27C | 4.1004e-03 |
| CASE3 unbuf CDS 27C | 3.1526e-03 |
| CASE3 follower 27C | 5.1064e-03 |

Tiling N does not change MOS Iq; it only increases the resistor-count
area proxy (80×N). Do **not** multiply 3.15 mW by neuron count and call
that Network F power — Network F was not built from transistors.
Accuracy vs resource, measured:

- Independent 0.5% → N≈41–105 unit tiles/resistor (area proxy) to chase 1e-3,
  but N=16 already flattened (~2.6e-3). Ratio correlation is cheaper than N.
- Ratio-matched 0.5% (shared Rf·G scale) reached MAE ~1e-3 in this sample
  at N=1, same 3.15 mW.
- Unbuffered CDS: same MOS Iq class as CASE 1, plus one NCH and 2 nF.
- Miller follower CDS: ~5.1 mW and still misses 85 °C / 200 µs.
- CASE 2 replica: extra miller, worse temperature.

Theoretical Network F scaling (NOT a measurement; F was not built):
48 neurons × 3.15 mW would be ~151 mW if every neuron were this o2 cell.
That product is unsupported: hidden neurons have different G_tot, invert
stages are still VCVS, and CDS clocks/buffers are not costed. Do not
cite 151 mW as Network F power.

## 11. Combined Monte Carlo

Physically motivated joint draw: 0.5% independent R at N=16, 214 µV
injected offset (Exp 22/26 ceiling), MOS `.temp` ∈ {−40, 27, 85} °C,
unbuffered capacitive CDS, live servo. Teaching-card MOS has no
Pelgrom mismatch PDF — transistor mismatch was **not invented**.
N_draws = 24 (disclosed). **Not a fabrication yield.**

| mean MAE | median | p95 | worst | pass frac | compensation |
| --- | --- | --- | --- | --- | --- |
| 1.6948e-03 | 1.6577e-03 | 3.7796e-03 | 4.1009e-03 | 0.333 | CASE3_unbuf_cap_CDS |

## 12. Error budget

| source | nominal | worst | independent? | physical cancellation |
| --- | --- | --- | --- | --- |
| resistor mismatch 0.5% N=1 | 6.3545e-03 | 1.6987e-02 | True | tiling / ratio correlation; not by servo |
| resistor mismatch 0.5% N=16 | 2.6156e-03 | 5.0869e-03 | True | further N or better process matching |
| MOS temperature CASE1 | 5.6283e-05 | 4.8168e-03 | False | replica or periodic AZ (not a stored 27C DW) |
| MOS temperature CASE3 unbuf CDS | 2.5723e-04 | 4.5701e-04 | False | already the compensation under test (high-Z output) |
| MOS follower residual at 85C/200us | 6.5820e-04 | 1.1777e-03 | False | not at 200 µs; teaching miller CM offset |
| transistor mismatch PDF | n/a | n/a | True | unvalidated: teaching card has no Pelgrom draw; not invented |
| resistor TCR | n/a | n/a | True | unvalidated: no documented TCR; not invented |
| servo residual 27C | 5.6283e-05 | 5.6283e-05 | False | already below 1e-3 |
| finite loop gain (no-servo Exp26) | 7.9700e-02 | 7.9700e-02 | False | servo / AZ restores VG; not by raising A alone |
| bias current | 0.0000e+00 | 0.0000e+00 | True | unvalidated: teaching card Ig=0 |
| dynamic settling CASE3 85C | 4.5701e-04 | 1.7593e-03 | False | longer dwell or larger Caz if droop appears |
| output swing ±1.65V (Exp26) | 1.9400e-01 | 1.9400e-01 | False | keep ±2.5 V for o2 |z|≈1.73 |

## 13. What is physically corrected

- Common-mode / ratio-correlated R error (Architecture A is ratiometric)
- Independent R error, partially, by tiling (1/√N until it flattens)
- MOS temperature pedestal on Vlin, by capacitive CDS (charge stored
  during Vin=Vref=0; no Python table)
- Injected 214 µV at 27 °C, still by the miller servo (Exp 26)

## 14. What remains ideal

- Vin / Vref sources
- Architecture A invert VCVS
- Ideal Ibias into MOS diodes
- Lumped Ccds / servo C (not MIM layout)
- Geometric DW null at 27 °C (CASE 1 only)
- Analog ground node 0 as the AZ short reference
- High-Z CDS output (no MOS output buffer in the promoted CASE 3)

## 15. What remains unvalidated

- IHP / foundry PDK, resistor TCR, MOS mismatch PDF
- R-only temperature (no documented TCR; not invented)
- Physical common-centroid layout (statistical abstraction only)
- A driven MOS subtractor/buffer that keeps MAE ≤ 1e-3 at 85 °C / 200 µs
- Network F at transistor level (forbidden)
- Silicon / board power
- Classification yield (isolated linear o2; F not built)

## 16. Distance to MAE ≤ 1e-3

Independent 0.5% N=1 MAE=6.3545e-03; N=16 MAE=2.6156e-03 (still 2.62× the 1e-3 bar; 1/√N from N=1 implies N≥41, but N=8–16 flattened). Ratio-matched 0.5% MAE=8.9247e-04 (pass_frac=0.625, max=2.5531e-03). CASE 1 85 °C |err|=4.8168e-03. CASE 3 unbuf CDS −40/27/85 |err|=1.4921e-04/2.5723e-04/4.5701e-04; temp_ok=True. 200 µs multi-input all_pass=True. High-Z CDS output and teaching-card MOS keep the primitive partial.

## 17. Recommended Experiment 28

Experiment 28 should not rebuild the encoding and should not transistorize Network F. The remaining device gaps are: (1) a driven MOS buffer/subtractor that does not re-introduce ~1 mV at 85 °C / 200 µs; (2) a documented PDK with resistor TCR and MOS mismatch PDFs — do not invent IHP parameters; (3) Architecture A invert in MOS; (4) process matching that makes Rf·G a ratio (this sample: ratio-matched 0.5% MAE=8.9247e-04), not blind N≥41 tiling of all 80 resistors. Do not retrain.

## FINAL STATUS

DEVICE-LEVEL PRIMITIVE PARTIALLY VALIDATED

SPICE is the source of truth. Frozen Experiment 9 weights were not edited.
