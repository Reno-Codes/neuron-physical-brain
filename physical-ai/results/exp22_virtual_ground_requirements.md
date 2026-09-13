# Experiment 22 — virtual-ground requirement extraction

## TITLE
What specifications must a physical virtual-ground TIA satisfy?

## QUESTION
Given that this conductance fabric needs a VG I-to-V at each neuron, what open-loop gain, offset, leakage, output resistance, and behavioral bandwidth does that primitive need for MAE <= 1e-3 and for 100% classification on the frozen A/F benchmarks?

## HYPOTHESIS
Finite A is set by the worst-neuron Rf G_tot (Exp 21). Offset maps as Vos*(1+Rf G_tot)*k and is tighter than classification. Leakage maps as ~I_leak*Rf. Bandwidth is a new dynamic requirement and is behavioral (single pole), not transistor GBW. Shared-tap coupling makes full-network offset stricter than the isolated neuron.

## ARCHITECTURE
Experiment 17 Architecture A. Invert A pinned at 1e7 for TIA sweeps. Baselines use invert A = 1e5 to match Experiment 17.

## WHAT CHANGED
Requirement extraction. No new weight encoding. No MOS devices.

## WHAT REMAINED FROZEN
Experiment 9 weights. Fabric. Direct bounded ReLU on full networks.

## TEST CONDITIONS
Networks A (100 vec) and F (40 vec). Isolated worst/median neurons. Analog bar MAE <= 1e-3. Classification = 100% vs frozen software.

## RESULTS

### Baseline verification
- Network A: Arch I MAE=3.2749e-15 acc=1.0; Arch A A=1e5 MAE=2.9627e-04 acc=1.0; max |Vsum|=8.9433e-06
- Network F: Arch I MAE=3.5666e-15 acc=1.0; Arch A A=1e5 MAE=4.8358e-04 acc=1.0; max |Vsum|=1.7381e-05

### Worst-neuron analysis
- worst_finite_gain: o2 RfG=141 VosGain=142 G_phys=4.2268e-03
- worst_offset: o2 RfG=141 VosGain=142 G_phys=4.2268e-03
- worst_leakage: h16 RfG=4.92 VosGain=5.92 G_phys=1.4747e-04
- median_hidden: h21 RfG=39.8 VosGain=40.8 G_phys=1.1936e-03
- highest_signal: o3 RfG=7.8 VosGain=8.8 G_phys=2.3411e-04
- Rf G_tot span: 4.92 .. 141 (ratio 28.7)

### Open-loop gain
- Network A analog A=2.9784e+04 (sampled pass 3.0000e+04, bracketed); class A=3.0000e+03 (sampled pass 3.0000e+03, bracketed)
- Network F analog A=4.8846e+04 (sampled pass 5.4772e+04, bracketed); class A=1.0000e+04 (sampled pass 1.0000e+04, bracketed)

### Offset
- Network A analog |Vos|=3.0215e-05 (bracketed, last pass -3.0000e-05); class |Vos|=1.0000e-04 (bracketed, last pass -1.0000e-04)
- Network F analog |Vos|=2.2436e-05 (bracketed, last pass -1.0000e-05); class |Vos|=1.0000e-04 (bracketed, last pass 1.0000e-04)

### Leakage
- Network A analog |Ileak|=9.1214e-09 (bracketed, last pass 1.0000e-09); class |Ileak|=1.0000e-08 (bracketed, last pass 1.0000e-08)
- Network F analog |Ileak|=1.3098e-08 (bracketed, last pass 1.0000e-08); class |Ileak|=1.0000e-07 (bracketed, last pass 1.0000e-07)

### Output resistance
{'analog': 19295.00165645235, 'classification': 100000.0, 'conservative': None, 'mechanism': 'Rout reduces loop gain', 'raw': {'status': 'bracketed', 'value': 19295.00165645235, 'abs_value': 19295.00165645235, 'lo': 10000.0, 'hi': 100000.0, 'method': 'log_interp'}}

### Bandwidth/settling
{'fp_for_1e3': 120.65107297851415, 'fp_sampled_pass_10us': 1000.0, 'gbw_proxy_for_10us': 12065107.297851415, 'fp_for_100us': 100.0, 'fp_for_1ms': 10.0, 'fp_for_class_note': 'DC classification is independent of f_p once settled', 'fp_conservative': 1000.0, 'window_s': 1e-05, 'note': 'f_p such that |v-vfinal|<1e-3 of the settled value (not of z) within 10 us on the worst-G_tot isolated neuron, A=1e5, unit step. Analog f_p is log-interpolated. Conservative f_p is the first swept pole that met the window. gbw_proxy = A * f_p, not transistor f_T. Finite-A DC error vs z remains after settling.'}

### Combined maps
Vos=1 mV on F: A=1000->MAE=4.9935e-02 acc=0.925; A=10000->MAE=3.4440e-02 acc=0.95; A=100000->MAE=3.4239e-02 acc=0.95; A=1e+06->MAE=3.4232e-02 acc=0.95. High A does not cancel 1 mV Vos. Ileak=10 nA: A=1000->MAE=4.5101e-02; A=10000->MAE=4.9561e-03; A=100000->MAE=6.8217e-04; A=1e+06->MAE=3.3944e-04. Leakage is only weakly A-dependent once A >> Rf G_tot.

### Design rule (k_j vs SPICE)
{'formula': 'k_j = A / (A + 1 + Rf * G_phys_j)', 'network_F': [{'A': 100.0, 'spice_mae': 0.27692924892416204, 'kj_theory_mae_vs_frozen': 0.3189615902471196, 'spice_minus_kj': -0.04203234132295758, 'k_hidden_min': 0.5380785860694268, 'k_output_min': 0.4134042521603349, 'Rf_Gtot_hidden_max': 84.84645921422579}, {'A': 300.0, 'spice_mae': 0.1288754985088248, 'kj_theory_mae_vs_frozen': 0.15827859375900646, 'spice_minus_kj': -0.02940309525018167, 'k_hidden_min': 0.7775113463810148, 'k_output_min': 0.6788958741694708, 'Rf_Gtot_hidden_max': 84.84645921422579}, {'A': 1000.0, 'spice_mae': 0.04496398934007889, 'kj_theory_mae_vs_frozen': 0.05743496682012892, 'spice_minus_kj': -0.012470977480050029, 'k_hidden_min': 0.9209405174315817, 'k_output_min': 0.875738043383511, 'Rf_Gtot_hidden_max': 84.84645921422579}, {'A': 3000.0, 'spice_mae': 0.015729438432510158, 'kj_theory_mae_vs_frozen': 0.02038066093473681, 'spice_minus_kj': -0.004651222502226653, 'k_hidden_min': 0.9721805798347836, 'k_output_min': 0.9548380750193993, 'Rf_Gtot_hidden_max': 84.84645921422579}, {'A': 10000.0, 'spice_mae': 0.004802627931401415, 'kj_theory_mae_vs_frozen': 0.006256202275658755, 'spice_minus_kj': -0.0014535743442573405, 'k_hidden_min': 0.9914884229537523, 'k_output_min': 0.986009124083843, 'Rf_Gtot_hidden_max': 84.84645921422579}, {'A': 30000.0, 'spice_mae': 0.0016090596857746462, 'kj_theory_mae_vs_frozen': 0.0020993562250994865, 'spice_minus_kj': -0.0004902965393248403, 'k_hidden_min': 0.9971466164553288, 'k_output_min': 0.995292466348488, 'Rf_Gtot_hidden_max': 84.84645921422579}, {'A': 100000.0, 'spice_mae': 0.0004835812064612555, 'kj_theory_mae_vs_frozen': 0.0006312862814164977, 'spice_minus_kj': -0.00014770507495524225, 'k_hidden_min': 0.999142271737201, 'k_output_min': 0.9985830707350086, 'Rf_Gtot_hidden_max': 84.84645921422579}, {'A': 300000.0, 'spice_mae': 0.00016127615597132054, 'kj_theory_mae_vs_frozen': 0.00021057010931446472, 'spice_minus_kj': -4.929395334314418e-05, 'k_hidden_min': 0.9997139269971338, 'k_output_min': 0.9995272436701502, 'Rf_Gtot_hidden_max': 84.84645921422579}, {'A': 1000000.0, 'spice_mae': 4.839150730422915e-05, 'kj_theory_mae_vs_frozen': 6.318588872279563e-05, 'spice_minus_kj': -1.4794381418566484e-05, 'k_hidden_min': 0.9999141609097677, 'k_output_min': 0.9998581261508128, 'Rf_Gtot_hidden_max': 84.84645921422579}, {'A': 3000000.0, 'spice_mae': 1.6131327448385987e-05, 'kj_theory_mae_vs_frozen': 2.1063378212388384e-05, 'spice_minus_kj': -4.9320507640023966e-06, 'k_hidden_min': 0.9999713853324179, 'k_output_min': 0.9999527042435837, 'Rf_Gtot_hidden_max': 84.84645921422579}, {'A': 10000000.0, 'spice_mae': 4.839484867901772e-06, 'kj_theory_mae_vs_frozen': 6.319162085046643e-06, 'spice_minus_kj': -1.4796772171448708e-06, 'k_hidden_min': 0.9999914154277741, 'k_output_min': 0.9999858108033128, 'Rf_Gtot_hidden_max': 84.84645921422579}], 'isolated_vs_theory': {'o2': {'max_mae_vs_theory': 0.08038069382217455, 'mae_vs_z_at_A1e5': 0.0005125493135206242}, 'h16': {'max_mae_vs_theory': 1.8518173106052416e-15, 'mae_vs_z_at_A1e5': 4.769011582260712e-05}, 'h21': {'max_mae_vs_theory': 0.050797991577740356, 'mae_vs_z_at_A1e5': 0.0002562397198678267}}, 'note': 'kj_theory_mae is the frozen-map error of the per-neuron scale model (not a SPICE correction). spice_minus_kj is leftover shared-tap / invert / ReLU discrepancy.'}

### Isolated vs full-network Vos at 1 mV
{'isolated_mae_vs_z': 0.0832853763466143, 'F_mae': 0.03423934518486962, 'note': "Isolated MAE is vs that neuron's software z; F MAE is vs the frozen network outputs. Not a like-for-like tightness ranking."}

### Full-network validation
- A I_ideal: MAE=3.2749e-15 max=1.2434e-14 acc=1.0 A=n/a
- A A_class: MAE=2.9563e-03 max=9.8625e-03 acc=1.0 A=1e+04
- A A_analog: MAE=5.4081e-04 max=1.8036e-03 acc=1.0 A=5.477e+04
- A A_1e5_exp17: MAE=2.9627e-04 max=9.8806e-04 acc=1.0 A=1e+05
- A A_1e6: MAE=2.9634e-05 max=9.8824e-05 acc=1.0 A=1e+06
- F I_ideal: MAE=3.5666e-15 max=1.5543e-14 acc=1.0 A=n/a
- F A_class: MAE=4.8026e-03 max=2.5299e-02 acc=1.0 A=1e+04
- F A_analog: MAE=8.8234e-04 max=4.6640e-03 acc=1.0 A=5.477e+04
- F A_1e5_exp17: MAE=4.8358e-04 max=2.5571e-03 acc=1.0 A=1e+05
- F A_1e6: MAE=4.8392e-05 max=2.5599e-04 acc=1.0 A=1e+06

## Requirement table

| Parameter | Analog threshold | Classification threshold | Conservative point | Dominant failure |
|---|---:|---:|---:|---|
| Open-loop gain A | 4.8846e+04 | 1.0000e+04 | 1.0000e+05 | finite VG loading k=A/(A+1+Rf G_tot), worst neuron |
| Input offset Vos (V) | 2.2436e-05 | 1.0000e-04 | 2.2436e-06 | Vsum displacement + shared-tap coupling on the fabric |
| Input leakage (A) | 1.3098e-08 | 1.0000e-07 | 1.3098e-09 | I_leak * Rf * k_j into Vlin, then ReLU / layer 2 |
| Open-loop pole f_p (Hz) | 1.2065e+02 | DC classification is independent of f_p once settled | 1.0000e+03 | incomplete single-pole settling (behavioral, not GBW) |
| Output resistance (ohm) | 1.9295e+04 | 1.0000e+05 | n/a | Rout reduces loop gain |

Conservative-point notes:
Gain conservative=100000 is the next decade above analog A=4.885e+04 that was actually simulated on F and met MAE<=1e-3 (not an invented factor of 10). Vos conservative=2.244e-06 is analog/10; swept points at or below that still met MAE<=1e-3. Ileak conservative=1.31e-09 is analog/10; swept points at or below that still met MAE<=1e-3.

## COMPARISON WITH PREVIOUS BEST
Exp 17 F A=1e5 MAE~5e-4, class 100% at A>=1e4. This run analog A_min=4.8846e+04 class A_min=1.0000e+04 Vos_analog=2.2436e-05 Ileak_analog=1.3098e-08.

## FAILURE MODES
Classification survives analog failure. Isolated MAE vs a neuron's z is not the same metric as F output MAE; the table uses full-network F. Settling is a behavioral single-pole macromodel, not an op-amp datasheet.

## DOMINANT ERROR SOURCE
DC analog floor: Vos through (1+Rf G_tot) and per-neuron finite A. Classification floor: much larger Vos / much smaller A.

## PHYSICAL INTERPRETATION
The VG primitive must hold Vsum << neural LSB. Fine-bank physical G makes that harder on some neurons (Rf G_tot up to tens). Offset is not a global output shift: ReLU and shared taps make it neuron-wise.

## HARDWARE REALISM LEVEL
LEVEL 2 requirement extraction on a behavioral TIA. Not LEVEL 4-6. A real op-amp/OTA must meet these numbers under this G_tot, not in an unloaded textbook TIA.

## CONCLUSION
REQUIREMENTS EXTRACTED. Analog (MAE<=1e-3 on F) needs A~4.8846e+04 and |Vos|<=2.2436e-05 and |Ileak|<=1.3098e-08. Classification is looser (A~1.0000e+04, larger Vos/Ileak). Conservative analog gain is the next decade that was actually simulated and passed.

## NEXT RESEARCH QUESTION
Experiment 23 should take ONE documented VG primitive (op-amp or OTA macromodel with known A, Vos, Ib, fu) and test it as a unit cell against this table. Do not embed MOS in Network F first. A vendor MCP6041 example exists under ngspice/examples but was not copied into this repo. The built-in XSPICE OTA is the cleanest next macromodel.

## FINAL STATUS
REQUIREMENTS EXTRACTED
