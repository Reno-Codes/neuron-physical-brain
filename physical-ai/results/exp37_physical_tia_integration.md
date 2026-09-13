# Experiment 37 - physical TIA integration and technology requirements

Frozen Experiment 9 weights. SPICE is the source of truth. Experiments 1-36 were not overwritten.
The documented Experiment 26 miller TIA + miller servo was not redesigned.
Network F was not fully transistorized. No MOS W/L, PDK, TCR, or mismatch PDF was invented.
OPA189 remains a vendor macromodel. The miller is a Berkeley BSIM3v3 teaching card, not silicon.

## Decision: B - PHYSICAL TIA PARTIALLY VALIDATED

- 200 us Gear insertion analog-passes; DC insertion remains solver-branchy and is not promoted as a DC OP result
- full Network F was not transistorized; remaining TIA copies stay behavioral
- MOS offset/temperature still requires the documented CDS path; not a new architecture

Dominant remaining bottleneck: resistor technology / foundry PDK (TCR, mismatch PDF, layout parasitics, switch nonidealities). The teaching-card miller is not silicon. OPA189 remains a vendor macromodel.

## 1. Qualified baseline reproduction

- F40 DC MAE = 6.3132e-04 (Exp 36 6.3132e-04, matched=True)
- F40 DC max = 9.0728e-03, acc = 1.0000
- F40 Gear 200 us MAE = 4.8589e-04 (Exp 36 4.8589e-04, matched=True)
- F40 Gear 200 us max = 3.4286e-03, acc = 1.0000
- Analog MAE and classification are reported separately. Solver: DC reltol=5e-5, TRAN method=gear.

## 2. Extracted TIA electrical requirements

- Worst Rf·G_tot: o2 = 1.4089e+02
- Worst conductance: o2 = 4.2268e-03 S
- Rf range: 3.3333e+04 .. 3.3333e+04 Ohm
- Input current (est): 2.3411e-04 A
- Required output swing (max |z|): 2.9372e+00 V on h25
- o2: Rf·G_tot=1.4089e+02, G=4.2268e-03 S, |z|=2.4595e+00 V, is_worst_RfG=True
- Summing-node / Vos ceiling from Exp 22: 2.2000e-05 V; representative raw offset 214 uV
- Behavioral loop gain A=1e5; isolated miller no-servo A_eff ~ 1.7e3 on o2 (Exp 26)
- 200 us sampled inference; temperatures already exercised: -40, 27, 85 C
- Servo must hold Vsum so |Vlin-z|<=1e-3. Exp 26 o2 servo Vsum ~0.67 uV. Uncorrected Vos ceiling ~22 uV (Exp 22). 214 uV is the representative raw offset.
- Architecture A hidden ReLU is a B-source: it isolates h*lin from the OPA189 invert and layer-2 fabric. Output-neuron TIA load is Rf plus that neuron's summing fabric. Shared-fabric coupling is through the input taps / hidden voltages, not TIA output current into invert.
- Isolated o2 does not automatically bound every other neuron.

## 3. Isolated primitive replay

- no-servo |err|=7.9704e-02 analog_pass=False
- servo |err|=5.6283e-05 Vsum=-6.6876e-07 analog_pass=True
- 214 uV inject |err|=4.5354e-05 analog_pass=True
- 200 us |err|=2.2578e-04 analog_pass=True
- isolated dwells: 100 us fail (1.27e-3), 200 us pass, 1 ms pass
- solver branch: documented isolated reltol=1e-6 vs qualified 5e-5: doc 1e-6 |err|=5.6283e-05; reltol=5e-5 |err|=5.6283e-05; default-options |err|=5.6283e-05
- Isolated miller no-servo still analog-fails. Servo is required at 27 C.

## 4. Representative loaded-neuron results

- o2 RfG=1.4089e+02 |err|=5.6283e-05 Vsum=-6.6876e-07 pass=True fail=False
- h5 RfG=8.4846e+01 |err|=3.5631e-05 Vsum=-6.7780e-07 pass=True fail=False
- h21 RfG=3.9788e+01 |err|=1.6593e-05 Vsum=5.4326e-07 pass=True fail=False
- h16 RfG=4.9158e+00 |err|=2.4414e-06 Vsum=3.7270e-07 pass=True fail=False
- h25 RfG=3.3342e+01 |err|=1.4517e-05 Vsum=6.5356e-07 pass=True fail=False
- h3 RfG=6.6152e+00 |err|=5.6167e-06 Vsum=6.9120e-07 pass=True fail=False
- h13 RfG=2.5781e+01 |err|=1.0441e-05 Vsum=-5.4901e-07 pass=True fail=False

## 5. Physical TIA + OPA189 interaction

Staged insertion only. Not all 48 TIAs. F40 with a physical TIA was not simulated.
Batched 12-vector DC OP of miller+OPA189 timed out (720 s) and is not a circuit fail.
Independent per-vector DC is solver-branchy, the same class as Experiment 35/36 invert DC.
Do not promote those DC OP numbers as dynamic validation.

- F12_OPA189_baseline: MAE=5.1038e-04 completed_MAE=5.1038e-04 max=3.1576e-03 acc=1.0000 pass=True Vsum_max=n/a Vlin_err=n/a swing=n/a invert_res=n/a fail=False reason=None
- F12_o2: MAE=n/a completed_MAE=n/a max=n/a acc=n/a pass=None Vsum_max=n/a Vlin_err=n/a swing=n/a invert_res=n/a fail=True reason=ngspice timeout / possible non-convergence
- F12_o2_indep: MAE=n/a completed_MAE=6.0829e-03 max=n/a acc=n/a pass=False Vsum_max=n/a Vlin_err=n/a swing=n/a invert_res=n/a fail=True reason=one or more independent DC vectors failed
- F12_h5_indep: MAE=n/a completed_MAE=1.8946e-03 max=n/a acc=n/a pass=False Vsum_max=5.3651e-05 Vlin_err=3.7020e-03 swing=1.4320e+00 invert_res=6.5619e-07 fail=True reason=one or more independent DC vectors failed
- F12_h25_indep: MAE=1.0483e-03 completed_MAE=1.0483e-03 max=8.8042e-03 acc=1.0000 pass=False Vsum_max=5.4451e-05 Vlin_err=1.1770e-03 swing=3.6085e-01 invert_res=7.2594e-07 fail=False reason=None
- F12_h21_indep: MAE=n/a completed_MAE=5.6531e-04 max=n/a acc=n/a pass=False Vsum_max=5.4867e-05 Vlin_err=1.7123e-03 swing=1.3429e+00 invert_res=9.1579e-07 fail=True reason=one or more independent DC vectors failed
- F12_o2_indep_default: MAE=6.2027e-03 completed_MAE=6.2027e-03 max=7.8075e-02 acc=1.0000 pass=False Vsum_max=n/a Vlin_err=n/a swing=n/a invert_res=n/a fail=False reason=None

## 6. 200 us dynamic results

- F12_o2_gear200: MAE=7.9538e-04 max=7.3959e-03 acc=1.0000 analog_mae_fail=[10] pass=True fail=False
- F12_o2_gear200_repeat: MAE=7.9538e-04 max=7.3959e-03 acc=1.0000 analog_mae_fail=[10] pass=True fail=False
- F12_h25_gear200: MAE=5.5071e-04 max=3.1579e-03 acc=1.0000 analog_mae_fail=[] pass=True fail=False
- F12_h21_gear200: MAE=5.7771e-04 max=3.1729e-03 acc=1.0000 analog_mae_fail=[] pass=True fail=False
- F12 Gear is the inference result. o2 repeat matched. h25/h21 recover the DC branch vectors.
- F40 with a physical TIA was not simulated, so this is not a full-network TIA claim.

## 7. Temperature / offset

- raw_servo o2 T=-40.0 |err|=4.0447e-03 Vsum=4.8350e-05 pass=False
- raw_servo o2 T=27.0 |err|=5.6283e-05 Vsum=-6.6876e-07 pass=True
- raw_servo o2 T=85.0 |err|=4.8168e-03 Vsum=-5.7572e-05 pass=False
- offset_214uV o2 T=27.0 |err|=4.5354e-05 Vsum=-5.3898e-07 pass=True
- cds_unbuf o2 T=-40.0 |err|=1.4921e-04 Vsum=4.9545e-05 pass=True
- cds_unbuf o2 T=27.0 |err|=2.5723e-04 Vsum=-5.9062e-07 pass=True
- cds_unbuf o2 T=85.0 |err|=4.5701e-04 Vsum=-6.1286e-05 pass=True
- cds_qamp_invservo o2 T=27.0 |err|=2.4443e-06 Vsum=1.5158e-06 pass=True iface_vs_plate=8.6430e-01 plate_err=8.6430e-01

## 8. Resistor-ratio interaction

- nominal |err|=5.6283e-05 pass=True
- common_mode |err|=5.6117e-05 pass=True
- ratio_matched |err|=5.3387e-04 pass=True
- independent |err|=2.2725e-03 pass=False
- Rf·G matching model still dominates: True
- Common-mode 0.5% and ratio-matched 0.5% analog-pass. Independent 0.5% analog-fails.
- The miller+servo does not replace Experiment 29's Rf·G tracking requirement with a new dominant mismatch.

Correction-path status (existing paths, not a new architecture):

- A_miller_alone: {'isolated': 'fail', 'representative_load': 'not_claimed', 'us200': 'not_claimed', 'temperature': 'not_claimed', 'driven_next_stage': 'voltage_node_exists_but_error_unbounded'}
- B_miller_servo: {'isolated': 'pass', 'representative_load': 'pass', 'us200': 'pass', 'temperature': 'fail_without_CDS', 'driven_next_stage': 'yes_voltage_at_TIA_output_27C'}
- C_temperature_stable_CDS: {'isolated': 'pass', 'representative_load': 'isolated_fabric_only', 'us200': 'AZ_plus_hold_documented', 'temperature': 'pass', 'driven_next_stage': 'no_highZ_plate'}
- D_CDS_plus_VG_charge_output: {'isolated': 'pass', 'representative_load': 'isolated_o2_only', 'us200': 'pass', 'temperature': 'previously_Exp28_not_remerged', 'driven_next_stage': 'yes_if_iface_pass'}
- minimally_required_for_extracted_spec: B for 27 C analog voltage; C if temperature must hold; D if a driven pad/next-stage must read the CDS result. Do not merge B+C+D into a new architecture.

## 9. Technology requirement table

### Already demonstrated in simulation

- Hidden inverter precision / drive: OPA189 F40 DC MAE 6.3132e-4, Gear 200 us MAE 4.8589e-4, classification 100% (Exp 36).
- Isolated miller TIA + servo at 27 C on o2 (Exp 26) and the isolated replay in this experiment.
- Isolated unbuffered capacitive CDS over -40/27/85 C (Exp 27) and the CDS replay here.
- CDS + VG charge-amp output interface, 200 us pass / 100 us fail (Exp 28).
- Sampled-inference timing: 200 us Gear is the qualified Network F protocol.
- F12 representative miller TIA + OPA189 Gear 200 us: o2 MAE 7.95e-4 (repeat identical), h25 5.51e-4, h21 5.78e-4, classification 100%.

### Behavioral / teaching-model only

- Resistor technology, TCR, foundry mismatch PDF.
- MOS mismatch distribution (teaching-card DW null is not a PCM).
- Switch nonidealities beyond the documented NCH AZ device.
- Layout parasitics, wells, routing, MIM capacitor extraction.
- OPA189 is a vendor macromodel, not silicon.
- Teaching-card miller W/L is CMOS-OP1 / BSIM3v3, not IHP SG13G2.

### Quantified technology requirements (experiment-supported)

- Residual local resistor-ratio leftover: Exp 29 15% of the 0.5% draw, leftover ~0.075%.
- Rf·G tracking: required for analog pass at 0.5% (Exp 29 mean MAE 8.02e-4).
- Invert R1/R2: documented ratio-restore at invert A=1e7.
- TIA summing-node residual: servo target ~1 uV class on o2 (Exp 26 Vsum ~0.67 uV).
- Effective offset: raw teaching miller ~214 uV; uncorrected ceiling ~22 uV (Exp 22).
- Output swing: at least max |z| = 2.9372e+00 V on the highest-signal neuron.
- Output current / I_max est: 2.3411e-04 A (G_WEIGHT * L1 mass).
- Dwell: isolated miller+servo 100 us analog-fails (1.27e-3); 200 us and 1 ms analog-pass. Exp 28 charge-amp 100 us also failed.
- Inserted-fabric Vsum probe ~55 uV (h5/h21/h25 vec0); isolated o2 servo Vsum ~0.67 uV.
- Acceptable leakage: Exp 22 ceiling ~13 nA into the summing node.
- Capacitor/interface: Exp 28 Ccds=Ccouple=2 nF, Cf=1 nF on the teaching card; not a foundry MIM.
- Miller supplies for the documented primitive are ±2.5 V. ±15 V overvoltage analog-failed in Exp 26.

## 10. Dominant remaining bottleneck

resistor technology / foundry PDK (TCR, mismatch PDF, layout parasitics, switch nonidealities). The teaching-card miller is not silicon. OPA189 remains a vendor macromodel.

## 11. Explicit decision

**B - PHYSICAL TIA PARTIALLY VALIDATED**

Feasibility split:

A. Isolated physical TIA primitive: yes at 27 C with miller+servo (no-servo fails).
B. Shared-fabric / loaded-neuron isolated fabrics: yes at 27 C on o2, h5, h21, h16, h25, h3, h13.
C. Full-network integration: F12 representative physical TIA + OPA189 Gear 200 us analog-passes; F40 physical TIA was not simulated; DC OP is not promoted.
D. Missing technology evidence: resistor TCR/mismatch PDF, MOS mismatch PDF, layout parasitics, foundry PDK, silicon OPA189.

This is not a fully transistorized Network F and not a silicon power/area claim.
