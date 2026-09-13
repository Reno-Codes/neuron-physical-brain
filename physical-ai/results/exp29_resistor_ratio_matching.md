==================================================
EXPERIMENT 29
RESISTOR-RATIO MATCHING AND NETWORK-SCALE FEASIBILITY
==================================================

Frozen Experiment 9 weights. SPICE is the source of truth.
Experiments 1–28 were not overwritten. No Python correction,
no affine fit, no per-weight calibration, no new encoding.
Network F was not built from transistors. No foundry PCM or
resistor TCR was invented. Matching models are documented
statistical / layout abstractions.

## 1. Objective

Determine whether a physically meaningful resistor-ratio matching
architecture can bring the frozen Network F fabric to analog
MAE ≤ 1e-3 without blind tiling, per-weight calibration, or
retraining. Classification is reported separately.

## 2. Frozen baseline

- Network F Architecture A, A=100000, Vos=0, invert A=1e+07
- Logical resistors: 1342
- By kind: {'invert': 98, 'divider': 124, 'weight': 1024, 'bias': 48, 'feedback': 48}
- Nominal 40-vector MAE=4.8383e-04 acc=1.0000
- Nominal 12-vector MAE=5.1015e-04
- Finite-A floor is already ~4.8383e-04; matching must not spend the rest of the 1e-3 budget.

Experiment 27 isolated-o2 MOS replay (not overwritten):
- o2 logical R=80
- independent 0.5% N=1 MAE ≈ 6.3545e-03
- independent 0.5% N=16 MAE ≈ 2.6156e-03
- common-mode 0.5% MAE ≈ 5.6317e-05
- ratio-matched 0.5% MAE ≈ 8.9247e-04

## 3. Why absolute tolerance is the wrong metric

Architecture A computes Vlin ≈ −Rf · Σ Vin G. A global scale on
every resistor leaves Rf·G invariant. Independent 0.5% does not.
Experiment 27 already showed common-mode 0.5% is invisible on o2.
This experiment asks which *physical grouping* must share that scale
on the full compiled Network F fabric.

## 4. Matching models tested

- **independent**: Unmatched discrete resistors. Independent relative error.
- **common_mode**: Global sheet resistance. One scale on every R.
- **global_plus_local**: Global sheet plus independent local (Pelgrom-like split).
- **ratio_matched_exp27**: Experiment 27 model: one TIA-family scale for all Rf+weights+bias, pair scales for invert/divider, 15% residual.
- **ratio_matched_neuron**: Per-neuron shared unit array on {Rf, weights, bias}; matched invert and divider pairs; 15% residual.
- **rf_g_track**: Per-neuron Rf tracks G_tot; intra-neuron weights still share that scale plus residual.
- **pn_pair**: Interdigitated +/− pairs only. Rf not in the pair.
- **pn_pair_plus_rf**: Interdigitated +/− pairs and a per-neuron Rf draw (Rf not forced to G).
- **pn_systematic**: Chip-wide polarity field: +path +tol, −path −tol.
- **centroid_stat**: Experiment 27 statistical common-centroid: chip + pair + local.
- **unit_array_neuron**: Integer unit conductances from a shared G_unit; sheet + per-neuron array + 1/√N local. Quantizes the compiled map.
- **gradient_paired**: Linear spatial field on paired placement, with neuron ratio groups.
- **gradient_naive**: Linear spatial field on polarity-split placement.
- **gradient_centroid**: Linear spatial field on ring common-centroid placement.

Each model is a documented abstraction (sheet, pair, neuron array,
unit element, linear gradient). None is a foundry extraction.

## 5. Sensitivity decomposition

0.5% independent error on one relationship, others nominal.
Network F, 12 vectors, 8 draws (limited MC, not a yield).

| subset | MAE mean | p95 | worst | analog pass | acc mean |
| --- | --- | --- | --- | --- | --- |
| rf_only | 2.5629e-03 | 2.8215e-03 | 2.8621e-03 | 0.000 | 0.9896 |
| weights_only | 2.6148e-03 | 3.0735e-03 | 3.1945e-03 | 0.000 | 0.9896 |
| bias_only | 5.2543e-04 | 5.5083e-04 | 5.5780e-04 | 1.000 | 1.0000 |
| invert_only | 2.9311e-03 | 3.6454e-03 | 3.9325e-03 | 0.000 | 1.0000 |
| divider_only | 5.2335e-04 | 5.4099e-04 | 5.4145e-04 | 1.000 | 1.0000 |
| layer1_only | 3.3112e-03 | 3.9285e-03 | 4.1578e-03 | 0.000 | 0.9896 |
| layer2_only | 3.3868e-03 | 3.8639e-03 | 3.9768e-03 | 0.000 | 0.9896 |
| fine_bank_only | 5.1779e-04 | 5.3552e-04 | 5.3836e-04 | 1.000 | 1.0000 |
| nom_bank_only | 2.6166e-03 | 2.9913e-03 | 3.0054e-03 | 0.000 | 1.0000 |
| pos_only | 1.8948e-03 | 2.0415e-03 | 2.0456e-03 | 0.000 | 0.9792 |
| neg_only | 1.9414e-03 | 2.1409e-03 | 2.1959e-03 | 0.000 | 0.9896 |
| tia_fabric | 3.7418e-03 | 4.0927e-03 | 4.1158e-03 | 0.000 | 0.9792 |

## 6. Rf-to-weight ratio tracking

Structured models at 0.5% on 12-vector Network F (8 draws):

| model | MAE mean | p95 | worst | analog pass | rms d(Rf G) | acc |
| --- | --- | --- | --- | --- | --- | --- |
| independent | 4.7986e-03 | 5.7004e-03 | 6.1081e-03 | 0.000 | 3.3364e-03 | 0.9896 |
| common_mode | 5.1015e-04 | 5.1015e-04 | 5.1015e-04 | 1.000 | 2.1702e-16 | 1.0000 |
| global_plus_local | 4.3833e-03 | 4.9372e-03 | 5.1331e-03 | 0.000 | 3.3280e-03 | 0.9375 |
| ratio_matched_exp27 | 8.1622e-04 | 9.3742e-04 | 9.6213e-04 | 1.000 | 5.0089e-04 | 1.0000 |
| ratio_matched_neuron | 8.3818e-04 | 9.3899e-04 | 9.7792e-04 | 1.000 | 5.0629e-04 | 1.0000 |
| rf_g_track | 8.1576e-04 | 8.9409e-04 | 8.9493e-04 | 1.000 | 5.0667e-04 | 1.0000 |
| rf_independent | 3.8196e-03 | 4.1060e-03 | 4.1262e-03 | 0.000 | 3.3969e-03 | 0.9688 |
| pn_pair | 2.8153e-03 | 3.2150e-03 | 3.3125e-03 | 0.000 | 1.7284e-03 | 0.9896 |
| pn_pair_plus_rf | 3.7185e-03 | 4.3124e-03 | 4.4523e-03 | 0.000 | 3.3172e-03 | 0.9792 |
| pn_systematic | 1.1040e-02 | 1.1040e-02 | 1.1040e-02 | 0.000 | 3.1064e-03 | 0.9167 |
| centroid_stat | 1.9300e-03 | 2.1659e-03 | 2.2254e-03 | 0.000 | 1.4500e-03 | 0.9896 |

Local residual after per-neuron ratio matching (tol=0.5% shared group):

| local residual | MAE mean | analog pass |
| --- | --- | --- |
| 0.0000e+00 | 5.1120e-04 | 1.000 |
| 2.5000e-04 | 5.4128e-04 | 1.000 |
| 5.0000e-04 | 6.5895e-04 | 1.000 |
| 7.5000e-04 | 8.0574e-04 | 1.000 |
| 1.2500e-03 | 1.1446e-03 | 0.000 |
| 2.5000e-03 | 2.3995e-03 | 0.000 |
| 5.0000e-03 | 4.9630e-03 | 0.000 |

## 7. Positive/negative branch matching

| test | MAE mean | p95 | analog pass | acc |
| --- | --- | --- | --- | --- |
| pn_pair | 2.6501e-03 | 2.8414e-03 | 0.000 | 1.0000 |
| pn_pair_plus_rf | 3.7761e-03 | 4.2090e-03 | 0.000 | 0.9688 |
| pn_systematic | 1.1040e-02 | 1.1040e-02 | 0.000 | 0.9167 |
| pn_corr | 3.7661e-03 | 3.9741e-03 | 0.000 | 0.9896 |

Isolated o2 ρ sweep (mixing weight; 1 = pair-matched, Rf included):

| ρ | MAE mean | analog pass |
| --- | --- | --- |
| 0.00 | 2.8237e-03 | 0.125 |
| 0.50 | 2.5990e-03 | 0.000 |
| 0.80 | 2.2163e-03 | 0.250 |
| 0.90 | 3.0680e-03 | 0.125 |
| 1.00 | 2.7815e-03 | 0.250 |

## 8. Unit-element / segmented implementation

Quantization only (no mismatch). Frozen weights unchanged;
compiled G rounded to k·G_unit.

| G_unit / G_W | n_units | unmatched | mean rel G | F MAE | analog |
| --- | --- | --- | --- | --- | --- |
| 1 | 2142 | 844 | 2.4572e-01 | 4.1083e-01 | False |
| 0.25 | 9078 | 298 | 2.1460e-01 | 1.9721e-01 | False |
| 0.0625 | 36447 | 0 | 9.5483e-02 | 5.9675e-02 | False |
| 0.01562 | 145770 | 0 | 2.4595e-02 | 1.4958e-02 | False |
| 0.003906 | 583075 | 0 | 5.8259e-03 | 4.1989e-03 | False |
| 0.0009766 | 2332248 | 0 | 1.4526e-03 | 1.1202e-03 | False |
| 0.0002441 | 9328997 | 0 | 3.7652e-04 | 5.4546e-04 | True |

Unit-array mismatch (quantized + sheet + 1/√N local), 12-vector F:

| G_unit/G_W | MAE mean | analog pass | n_units |
| --- | --- | --- | --- |
| 0.0625 | 5.9634e-02 | 0.000 | 36447 |
| 0.01562 | 1.4994e-02 | 0.000 | 145770 |

Isolated o2 explicit tiles (not statistical 1/√N): {'n_ok': 8, 'mae_mean': 0.0026085263371669384, 'mae_median': 0.0024582132120148457, 'mae_p95': 0.005067219025559049, 'mae_worst': 0.005875810042804751, 'analog_pass_frac': 0.125, 'limited_monte_carlo': True, 'not_a_yield': True, 'tile': {'requested_n': 8, 'n_series': 28, 'n_parallel': 6, 'n_untiled': 0, 'n_partial': 0, 'n_source_resistors': 34, 'n_tiles': 272}, 'note': 'Explicit series/parallel tiles on isolated o2 TIA fabric. Device-level primitive test, not fabrication-ready.'}

## 9. Systematic gradient stress

R ∝ 1 + gx·x' on the documented floorplan. gx is normalized, not ppm/µm.
Matched neuron groups remain unless noted.

| placement | gx | MAE mean | analog pass |
| --- | --- | --- | --- |
| naive | 0 | 8.1101e-04 | 1.000 |
| naive | 0.002 | 8.8806e-04 | 0.875 |
| naive | 0.005 | 9.5554e-04 | 0.500 |
| naive | 0.01 | 1.1301e-03 | 0.125 |
| naive | 0.02 | 1.6591e-03 | 0.000 |
| paired | 0 | 8.2191e-04 | 1.000 |
| paired | 0.002 | 8.9820e-04 | 0.875 |
| paired | 0.005 | 9.4298e-04 | 0.750 |
| paired | 0.01 | 1.1278e-03 | 0.250 |
| paired | 0.02 | 1.5806e-03 | 0.000 |
| centroid | 0 | 8.5525e-04 | 1.000 |
| centroid | 0.002 | 7.7113e-04 | 1.000 |
| centroid | 0.005 | 8.1011e-04 | 0.875 |
| centroid | 0.01 | 7.3283e-04 | 1.000 |
| centroid | 0.02 | 8.1651e-04 | 1.000 |

## 10. Full Network F results

Promoted model: **ratio_matched_neuron**.
Vectors: 40. Draws: 16 (limited Monte Carlo, **not a yield**).

- MAE mean 8.0164e-04
- MAE median 8.1106e-04
- MAE p95 9.0924e-04
- MAE worst 9.3833e-04
- analog pass fraction 1.000
- classification accuracy mean 1.0000
- classification all-correct fraction 1.000

Independent 0.5% on the same 40-vector set: mean MAE 4.1942e-03, analog pass 0.000, acc 0.9938.

Network-wide Experiment 27 ratio model (one TIA-family scale) on F40:
- MAE mean 7.6703e-04 p95 8.9415e-04 worst 9.1908e-04 analog pass 1.000

Finite-A control (A=1e7, ratio_matched_neuron, 12-vec): nominal MAE 5.1053e-06, matched mean MAE 6.5931e-04. The A=1e5 floor is ~4.8e-4; matching residual remains ~6e-4 without it.

## 11. Analog versus classification

Classification can remain high while analog MAE misses 1e-3.
A configuration is not analog-equivalent because argmax is stable.
Nominal F accuracy 1.0000. Independent 0.5% typically keeps classification near 99% while analog-failing.

## 12. Physical implementation requirements

Promoted grouping is `ratio_matched_neuron`. It requires 48 matched TIA arrays (one per neuron) in which Rf shares the same resistor family as that neuron's weights and bias. Invert R1/R2 and divider Ra/Rb must be pair-matched. Polarity pairs should be co-located; a chip-wide +/− field is destructive. Common-centroid / interdigitated placement is the abstraction that reduces linear-gradient residual. This is a matching *relationship*, not a claimed die area.

## 13. Component-count tradeoffs

Current compiled fabric: 1342 logical resistors (1024 weight, 48 bias, 48 Rf, 98 invert, 124 divider). Blind N-tiling of all of them was already rejected by Experiment 27 (N=16 still ~2.6e-3 on o2). Ratio matching does not require multiplying every resistor; it requires grouping the TIA arrays. At G_unit=G_W/16 the TIA fabric becomes 36447 unit elements vs 1342 logical resistors (27.16×) and still quantization-fails (MAE 5.967e-02). Quantization-only analog-pass first occurs at G_unit=7.324e-09 (9328997 units, ~6952×). Area proxy = element count, not mm².

## 14. What failed and why

Failed or insufficient: independent mean MAE 4.799e-03; global_plus_local mean MAE 4.383e-03; rf_independent mean MAE 3.820e-03; pn_pair mean MAE 2.815e-03; pn_pair_plus_rf mean MAE 3.718e-03; pn_systematic mean MAE 1.104e-02; centroid_stat mean MAE 1.930e-03. Independent absolute 0.5% fails. +/− pairing without Rf·G tracking fails or is weak (Experiment 27 lesson, confirmed). Naive polarity-split placement makes a linear gradient look like systematic polarity mismatch. Blind tiling is not promoted.

## 15. Quantified matching requirement

- Analog bar: MAE ≤ 0.001
- Independent 0.5% on F does **not** meet it (mean 4.4950e-03).
- Required local residual after per-neuron Rf·G matching: 7.5000e-04
- Required +/− mixing weight ρ (isolated o2, analog mean-pass): n/a
- Required unit G (quantization-only analog-pass): 7.3242e-09
- Gradient gx that breaks centroid+ratio (mean): n/a

Hypothesis verdicts (this fabric, this limited MC):
H1 shared unit/sheet scale cancels — supported (common-mode = nominal).
H2 Rf-to-G tracking matters more than global absolute R — supported
(rf_g_track analog-passes; rf_independent fails).
H3 +/− pairing is required but not sufficient — supported
(systematic polarity is worst; pairs without Rf·G still fail).
H4 integer/segmented units beat independent absolute R — not supported
as a replacement for ratio grouping; quantization of the frozen map
is a separate error source.
H5 a quantization / unmatched-residual floor exists — supported
(G_W/1024 still analog-fails; local residual 0.125% mean-fails).
H6 systematic spatial fields can beat equal-RMS independent error —
supported on naive polarity-split placement; centroid+ratio survives
gx≤0.02 in this abstraction.
H7 structured ratio matching can meet Network F MAE ≤ 1e-3 at a
nominal 0.5% group scale — supported in this limited MC, provided
unmatched local residual stays ≲ 0.075%. Not a foundry yield.

These are measured SPICE thresholds on this frozen fabric and these
abstractions. They are not foundry ppm specifications.

## 16. Physical realism level

LEVEL 2/3 behavioral Architecture A fabric (E-source TIA, Vos=0).
Resistor values are physical. Matching is a statistical layout
abstraction. Not LEVEL 4 Network F. Not LEVEL 5/6.

## 17. Limitations

- Limited Monte Carlo; not a yield.
- No documented PDK resistor mismatch or TCR.
- Floorplan positions are an abstraction, not GDS.
- Unit-array 1/√N is statistical except where isolated tiles were emitted.
- Invert stages remain VCVS.
- Finite A=1e5 is included in the primary numbers.
- Experiment 28 interface and Experiment 26 MOS cell were not rebuilt.

## 18. Experiment 30 recommendation

Experiment 30 should not rebuild the encoding and should not transistorize Network F. The remaining physical gaps are a documented PDK (resistor TCR, MOS/resistor mismatch PDF, real unit-array geometry) and replacing the Architecture A invert VCVS. Independent 0.5% remains unacceptable. Do not invent foundry coefficients. Do not retrain.

## 19. Final status

RESISTOR-RATIO MATCHING PARTIALLY VALIDATED

SPICE is the source of truth. Frozen Experiment 9 weights were not edited.
