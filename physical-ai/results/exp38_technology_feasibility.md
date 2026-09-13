# Experiment 38 - semiconductor technology feasibility

Frozen Experiment 9 weights. SPICE is the source of truth. Experiments 1-37 were not overwritten.
No PDK, W/L, TCR, mismatch PDF, or silicon performance was invented.

## Decision: B - TECHNOLOGY PLAUSIBLE BUT KEY DATA MISSING

- Open PDKs document analog MOSFET, poly resistors, MIM, and enough voltage on 5-6 V nodes.
- No installed PDK, so no legitimate transistor-level Network F simulation was possible.
- Public docs do not quantify resistor-ratio leftover at 0.075%, TCR leftover, or 85 C leak.
- Fully integrated 2 nF CDS is area-impractical (~120 mm2 at 2 fF/um2 for 48 neurons).

Best candidate: SkyWater SKY130 (voltage headroom) and IHP SG13G2 (analog documentation); GF180MCU is the 6 V alternative
Strongest evidence: Official SKY130 MIM 2 fF/um2 e-test; official 5 V FETs; official IHP 3.3 V HV CMOS + rhigh; official GF180 6 V resistors/MIM. Local Exp 22/29/36/37 requirement numbers.
Biggest unknown: documented resistor matching / TCR sufficient to judge residual leftover 0.075%
Hardest requirement: per-neuron Rf*G leftover <= 0.075% AND fully-integrated 1-2 nF CDS
Real PDK used: False
Legitimate transistor-level PDK simulation: False

No invented PDK/device/process parameters were used.

## 1. Executive summary

The frozen Architecture A Network F map has quantified electrical requirements. 
Three open PDKs (IHP SG13G2, SKY130, GF180MCU) document analog MOS, poly resistors, 
and MIM capacitors. None is installed here. Public documentation does not prove 
the Experiment 29 leftover matching target. Fully integrated 1-2 nF CDS capacitors 
are area-impractical at documented MIM densities. The architecture is not blocked 
by a single documented voltage/current contradiction on 5-6 V nodes, but it is 
blocked from a responsible silicon claim until a real PDK is installed and the 
resistor-matching / leakage / TCR numbers are read from that PDK.

## 2. Exact objective

Is there a documented, realistically accessible semiconductor technology/PDK that 
could implement the demonstrated Physical AI architecture without invented device parameters?

## 3. Repository baseline

- Frozen model: models/scaling/F.npz seed 9
- Shape: [16, 32, 16]
- Logical resistors (recalculated): 1342 kind={'invert': 98, 'divider': 124, 'weight': 1024, 'bias': 48, 'feedback': 48}
- Hidden invert stages: 32 / total invert stages 49
- Worst Rf*G: o2 = 1.4089e+02
- Worst G: o2 = 4.2268e-03 S
- Largest hidden G: h5 = 2.5454e-03 S
- Rf: 3.3333e+04 Ohm
- |z|max: h25 = 2.9372e+00 V; hy_max=2.6082e+00 V
- Worst-neuron I_max: 2.3411e-04 A (this is the 234 uA number)
- Sum of per-neuron I_max: 7.2995e-03 A (not previously labeled network current)
- I_max_est = G_WEIGHT * L1 mass per neuron. 234 uA in Exp 37 is the worst-neuron estimate, not network total current.
- Local PDK_ROOT set: False; foundry PDK installed: False
- Teaching BSIM3 present: True; OPA189 present: True

Discrepancy vs the prompt: 234 uA is worst-neuron G_WEIGHT*L1, not total Network F current.
Resistor counts match Experiment 29 (1342 = 1024 weight + 48 bias + 48 Rf + 98 invert + 124 divider).

## 4-5. Technology inventory and candidate table

See JSON candidates[]. Local scan: PDK_ROOT unset, IHP/SkyWater howtos present, foundry model trees absent. Compact-model .osdi plugins exist locally but are not a PDK.

- IHP SG13G2 Open PDK (130 nm SiGe BiCMOS): local=False runnable=False Vmax=3.3 overall=YELLOW access=REFERENCE ONLY until PDK_ROOT+OpenVAF installed
  Best analog-process documentation among open PDKs. 2.94 V swing on 3.3 V HV CMOS has little TIA headroom unless analog ground is mid-rail. Dual +/-2.5 V exceeds 3.3 V devices.
- SkyWater SKY130 (180/130 nm hybrid): local=False runnable=False Vmax=5.0 overall=YELLOW access=REFERENCE ONLY; ngspice howto present, example lib path absent
  5 V devices can host +/-2.5 V miller rails. Precision resistor matching numbers are not in the public PDK pages.
- GlobalFoundries GF180MCU Open PDK (180 nm MCU): local=False runnable=False Vmax=6.0 overall=YELLOW access=REFERENCE ONLY; no local tree
  Best documented voltage headroom (6 V resistors/MIM). High-R poly local mismatch flag is N, so the compact Rf family is not proven for 0.075% leftover.
- Berkeley BSIM3v3 teaching cards (CMOSOpAmp) (teaching 0.35 um-class): local=True runnable=True Vmax=2.5 overall=RED access=locally runnable MOS only
  Already used. Not a foundry. Cannot host the resistor fabric.
- TI OPA189 GWL macromodel (vendor IC, not a process): local=False runnable=True Vmax=36.0 overall=YELLOW access=LEVEL 3 invert primitive only
  Validates invert requirements as a vendor part, not as custom silicon in a PDK.
- ASAP7 (7 nm academic predictive): local=False runnable=False Vmax=0.7 overall=RED access=REFERENCE ONLY
  Predictive digital node. 2.94 V swing is a documented contradiction.
- CMC r2_cmc compact resistor example (compact-model example): local=False runnable=False Vmax=None overall=RED access=REFERENCE ONLY
  r2_cmc.osdi is now present locally, but the example TC1 is not a foundry TCR and must not be used as the fabric TCR.

## 6-14. Requirement extraction and feasibility

| Requirement | Required | Prior evidence | Technology evidence | Status | Class |
|---|---:|---|---|---|---|
| analog MAE | 0.001 | Exp 17/29/36/37 SPICE vs NumPy | independent of PDK; already demonstrated mixed-level | GREEN | demonstrated_in_spice |
| classification | 1.0 | F40 Exp 36/37 acc 1.0 | independent | GREEN | demonstrated_in_spice |
| output swing |z|max | 2.9371827051901307 | Exp 37 F40 software z, h25 | IHP 3.3 V YELLOW; SKY130 5 V / GF180 6 V GREEN; ASAP7 RED | YELLOW | supported_by_published_docs |
| worst-neuron current | 0.00023411431370398122 | G_WEIGHT * L1; Exp 37 called this 234 uA | any analog CMOS; not a process limiter | GREEN | inferred_estimated |
| sum of per-neuron I_max | 0.007299530602891502 | not previously labeled as network current | still modest for analog CMOS; supply design unknown | YELLOW | inferred_estimated |
| 200 us dwell | 0.0002 | Exp 25/28/36/37; isolated 100 us fail | audio-speed analog; GREEN on all real processes | GREEN | demonstrated_in_spice |
| residual local Rf*G leftover | 0.00075 | Exp 29 local residual 0.075% pass / 0.125% fail | INSUFFICIENT DATA in public open-PDK matching tables | UNKNOWN | completely_unknown |
| uncorrected TIA |Vos| | 2.2e-05 | Exp 22 analog ceiling | raw MOS offset typically larger; servo/CDS required (Exp 26/27) | YELLOW | demonstrated_in_spice |
| effective post-CDS offset | 0.001 | Exp 27/37 CDS analog-pass -40/27/85 C on isolated o2 | needs PDK switch/C/leakage models; not silicon | YELLOW | demonstrated_in_spice |
| summing-node leakage | 1.3098e-08 | Exp 22 analog |Ileak| | 85 C junction leak UNKNOWN without PDK | UNKNOWN | completely_unknown |
| TIA open-loop A | 48846.0 | Exp 22 analog A_min; conservative 1e5 simulated | two-stage miller in analog CMOS is plausible; not demonstrated on a PDK | YELLOW | demonstrated_in_spice |
| hidden invert Vos (32 copies) | 0.0001 | Exp 30/31; OPA189 Exp 36 macromodel | custom invert on PDK UNKNOWN; OPA189 is vendor model | YELLOW | demonstrated_using_vendor_model |
| CDS capacitors 1-2 nF | 2e-09 | Exp 28 teaching lumped C | at 2 fF/um2, 48-neuron CDS stack ~120.0 mm2 (inferred area) | RED | inferred_estimated |
| resistor TCR | common-mode cancel if same family; differential TCR unknown | Exp 27 .temp is MOS-only; no fabric TCR | IHP/SKY/GF document TCR sections; numeric leftover vs 1e-3 UNKNOWN | UNKNOWN | completely_unknown |
| MOS mismatch PDF | servo/CDS must absorb raw Vos | teaching DW null is not a PCM | PDK statistical models exist (GF/IHP) but unused locally | UNKNOWN | completely_unknown |
| layout parasitics | must not destroy analog map | not demonstrated | unknown until extraction | UNKNOWN | completely_unknown |
| ReLU | bounded max(0,z) | behavioral B-source only | not a documented physical primitive | YELLOW | demonstrated_in_spice |

CDS C per neuron = 5.000e-09 F. At 2 fF/um2, 48 neurons ~ 120.0 mm2.

## 15. Minimum Physical AI process specification

Minimum Physical AI Process Specification (only numbers the experiments support):
- Analog bar MAE <= 1e-3; classification 100% on frozen F40.
- Output swing >= 2.937 V with TIA headroom. Dual +/-2.5 V needs >=5 V devices, or the analog ground must move to mid-supply on a 3.3 V HV process.
- Worst-neuron current estimate 2.341e-04 A; do not call this chip power.
- Sampled inference dwell 200 us (100 us failed on the documented physical path).
- TIA A >= 4.88e4 analog (1e5 conservative, already simulated).
- Uncorrected |Vos| <= 22 uV or a physical servo/CDS that reduces effective offset below the analog bar.
- Invert |Vos| <= 100 uV at N=32, or a documented zero-drift / AZ invert.
- Summing-node |Ileak| <= 13 nA analog (Exp 22); 85 C value UNKNOWN until PDK.
- Per-neuron Rf must share the resistor family of that neuron's weights/bias. Unmatched leftover after grouping <= 7.50e-04 (0.075%). Not a foundry yield.
- Invert R1/R2 and divider pairs must be ratio-matched.
- TCR: common-mode same-family scale cancels (Exp 29). Differential TCR UNKNOWN.
- Temperature range already exercised: -40, 27, 85 C (MOS teaching card; fabric TCR not present).
- CDS capacitors in the demonstrated path are 2 nF / 2 nF / 1 nF. Fully integrated area is impractical at 1-2 fF/um2. Hybrid/external C, or a new physically justified smaller-C path, is required.
- ReLU remains a behavioral B-source. A physical ReLU is still missing.
- Layout parasitics: no experiment has extracted them.
Do not invent a numeric TCR, Pelgrom A_R, or MOS mismatch sigma.

## 16. Demonstrated vs required vs unknown

| Property | Experiment evidence | Required for silicon | Technology evidence |
|---|---|---|---|
| Frozen weights | demonstrated (Exp 9) | yes | independent |
| Physical weighted sum | demonstrated (Exp 1-17 SPICE) | yes | resistor implementation required |
| ReLU | behavioral B-source only | yes | still incomplete |
| TIA | partial teaching MOS + F12 Gear (Exp 26/37) | yes | PDK miller not simulated |
| Hidden inverter | OPA189 vendor macromodel (Exp 36) | yes | custom transistor invert incomplete |
| Rf/G matching | behavioral/statistical (Exp 29) | yes | PDK matching data required |
| TCR | not demonstrated on fabric | required | unknown until PDK |
| MOS mismatch | teaching DW null only | required | PDK/model required |
| Layout parasitics | not demonstrated | required | unknown |
| Full silicon F40 | not demonstrated | final target | unknown |
| CDS capacitors 1-2 nF | lumped teaching C (Exp 28) | if CDS path kept | on-die area impractical at documented MIM density |

## 17. Unknowns

- Public open-PDK resistor matching vs leftover 0.075%
- Fabric resistor TCR leftover after same-family tracking
- 85 C summing-node leakage on a real device
- Custom invert offset at N=32 in a PDK (OPA189 is not that)
- Layout parasitics and routing drop
- Physical ReLU
- Switch charge injection at the documented AZ device beyond teaching NCH

## 18. Risks

- Treating OPA189 macromodel as custom-silicon invert feasibility.
- Treating 0.5% discrete-resistor language as 0.075% on-chip leftover.
- Dual +/-2.5 V miller rails on 3.3 V-only IHP devices.
- Integrating 2 nF CDS capacitors on-die.
- Using example compact-model TC1 as a foundry TCR.

## 19. Candidate ranking

1. SKY130 - voltage GREEN, analog YELLOW, matching UNKNOWN, not installed.
2. IHP SG13G2 - analog GREEN, voltage YELLOW for 2.94 V, matching UNKNOWN, not installed.
3. GF180MCU - voltage GREEN, high-R local-mismatch flag N, not installed.
4. OPA189 macromodel - invert only.
5. Teaching BSIM3 - MOS only, resistor RED.
6. ASAP7 / r2_cmc - not suitable.

## 20. Final decision

**B - TECHNOLOGY PLAUSIBLE BUT KEY DATA MISSING**

## 21. Next experiment

Do not tape out. Next is install one real open PDK and host a single o2 Rf*G cell, or accept hybrid/external capacitors and mid-rail analog ground.

Recommended Experiment 39: install one documented open PDK (SKY130 or IHP SG13G2), 
host a single frozen o2 Rf*G cell plus one invert, and read matching/TCR/leakage from that PDK. 
Do not invent parameters if the PDK omits them. Do not transistorize all of Network F.
