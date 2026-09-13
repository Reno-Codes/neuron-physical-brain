# Physical AI

Research prototype: neural-network computation performed by physical electrical circuits, simulated with ngspice.

## Experiment 1 — physical weighted sum

Purpose: demonstrate that a physical electrical network can perform a mathematical operation.

This experiment is a resistor-network **weighted sum**. Two input voltages drive an output node through resistors; a load resistor ties that node to ground. The circuit is simulated with ngspice. No CPU/GPU neural-network kernel computes the result — the voltages and currents themselves do.

## How the mapping works

- **Input voltages** represent neural inputs (`x1`, `x2`).
- **Resistor conductances** (`G = 1/R`) represent weights. A larger conductance injects more current into the output node for a given input voltage.
- **Kirchhoff's current law** causes those currents to combine physically at the output node (the algebraic sum of currents is zero).
- The **resulting voltage** is the unique nodal solution of that network. That voltage is the circuit's output.

The chain is:

```
electrical signals
      ↓
physical circuit
      ↓
Kirchhoff's laws
      ↓
mathematical computation
```

For this topology the nodal equation is:

```
Vout = (V1/R1 + V2/R2) / (1/R1 + 1/R2 + 1/R3)
```

That is the physical result, not a programmed multiply-accumulate.

## What this is not

This is **not** yet a complete artificial neuron or neural network. There is no learned weight programming, no nonlinearity (activation), and no multi-neuron topology. It is the smallest proof-of-concept that physical electrical behavior can perform part of neural computation.

## Run

From `physical-ai/`:

```text
python scripts\simulate.py
```

The script locates `circuits/neuron.cir` relative to the project, calls `ngspice_con.exe` in batch mode, extracts `v(out)`, and compares it to the independent nodal calculation.

## Experiment 2 — neural weights compiled into a circuit

Purpose: show a primitive compiler from numerical weights to physical hardware.

```
neural weights
      ↓
    Python
      ↓
resistor values
      ↓
 SPICE circuit
      ↓
   ngspice
      ↓
physical output
      ↓
compare with math
```

- **Voltage** represents a neural input `x`.
- **Conductance** represents a neural weight: `G = G_SCALE * w`.
- **Ohm's law** produces a current proportional to input × weight: `I = V G`.
- **Kirchhoff's current law** adds those currents at a summing node: `I_total = Σ(V_i G_i)`.
- Dividing by the scale recovers the neural weighted sum: `I_total / G_SCALE = Σ(V_i w_i)`.

The generated circuit uses a 0 V sense source as a virtual ground / ammeter so `I = V G` is exact. That is different from Experiment 1, whose loaded node computed a weighted *average*, not `Σ w_i x_i`.

This is still not a complete neuron: no bias, no activation, no negative weights, and no multi-layer network. It only demonstrates:

```
numerical weights → physical conductances → electrical currents → weighted summation
```

Run:

```text
python scripts\generate_neuron.py
```

The script writes `circuits/generated_neuron.cir` from the weights, simulates it, and compares `I_total / G_SCALE` to `w1*x1 + w2*x2`.

Generated `circuits/generated_*.cir` files are build artifacts: they are overwritten on each run so they can be inspected, but they are not hand-edited.

## Experiment 3 — physical matrix-vector multiplication

Purpose: implement a small neural-network linear layer as parallel physical neurons in one SPICE circuit.

```
X = electrical input voltages
W = physical conductances
W × X = summed electrical currents
Y = normalized physical output currents
```

Three shared input voltages drive two independent current-summing neurons. Each weight in `W` becomes its own resistor (`G = G_SCALE * w`). Each neuron has its own summing node (`sum1`, `sum2`) and 0 V ammeter (`Vam1`, `Vam2`). The neurons run simultaneously: neuron 1's network does not load neuron 2, because each virtual ground clamps its own sum node to 0 V.

This is still a simplified linear layer. It does not yet contain:

- nonlinear activation
- training
- backpropagation
- programmable memory
- large-scale hardware

The purpose is to prove that a neural-network linear layer can be represented as a physical electrical network.

Run:

```text
python scripts\generate_layer.py
```

The script computes `Y_math = W @ X` in NumPy, generates `circuits/generated_layer.cir` from the arrays, reads `I1` and `I2` from ngspice, and compares `Y_physical = [I1, I2] / G_SCALE` to `Y_math`. Changing `W` in the script regenerates the circuit.

## Experiment 4 — physical nonlinear activation

Experiments 1–3 demonstrated physical weighted summation and matrix-vector multiplication. Those circuits are linear. A cascade of linear circuits is still linear, so it cannot represent the nonlinear maps that make neural networks useful. Experiment 4 adds a **physical nonlinear element**.

```
electrical inputs
      ↓
physical weighted sum
      ↓
physical nonlinear circuit
      ↓
neuron output
```

Two rectifier topologies are measured in ngspice:

1. **Silicon diode rectifier** (`circuits/relu.cir`) — a series diode into a load. This is **not** ideal ReLU. The Shockley diode equation gives a forward drop `Vf ≈ 0.5–0.7 V`, so the physical map is roughly `y ≈ max(0, x - Vf)` (plus a soft knee, not a sharp corner).
2. **Precision rectifier / superdiode** (`circuits/relu_precision.cir`) — the same diode provides the rectifying nonlinearity; an ideal op-amp macromodel around it cancels most of `Vf`. The measured curve is close to `max(0, x)`, with finite-gain, rail, and leakage residuals.

`scripts/test_relu.py` sweeps both circuits, prints a table against ideal ReLU (reference only), and writes `results/relu_curve.png`.

`scripts/generate_network.py` attaches the precision rectifier to the Experiment 3 conductance layer. Summed current is converted to a voltage with a transimpedance (H source, analog of an I–V amplifier) so the rectifier operates at the same numerical scale as `Y = W @ X`. Python computes `Y_linear = W @ X` and `Y_expected = ReLU(Y_linear)` only as references; `Y_physical` is `v(y)` from ngspice.

Negative weighted sums are produced with **signed input voltages**, not by assigning a negative value to a positive resistor. Real negative *weights* would need a second path (inverted input or dual-rail conductances). That is not faked here.

This is still not a trained network: no backprop, no programmable memory, no large-scale hardware. It shows that a linear layer plus a physical rectifier can act as a small analog neuron.

Run:

```text
python scripts\test_relu.py
python scripts\generate_network.py
```

## Experiment 5 — signed physical neural network

A conventional resistor is a positive conductance. Real networks need `+w` and `-w`. Experiment 5 splits every signed weight without using a negative resistor:

```
w  = w+ - w-
w+ = max(w, 0)
w- = max(-w, 0)
G+ = G_SCALE * w+
G- = G_SCALE * w-
```

Positive and negative components drive **separate** virtual-ground summing nodes:

```
I+ = Σ(x_i G+_i)
I- = Σ(x_i G-_i)
```

Copies of those currents meet at a third node, where Kirchhoff's current law performs

```
I_diff = I+ - I-
I_diff / G_SCALE = Σ(x_i w_i) + bias
```

inside SPICE. Python does not subtract `I+` and `I-` to invent the result; it only checks that identity as a topology diagnostic.

Bias is another conductance from a 1 V reference onto the `+` or `-` path. The hidden layer then goes through the Experiment 4 precision rectifier. The compiled 2→3→2 network is:

```
H = ReLU(W1 X + b1)     (physical)
Y = W2 H + b2           (physical, linear output)
```

This is a small simulation-scale proof of concept, not a practical chip: CCCS current copiers and VCVS buffers are analog-computing macromodels, weights are fixed resistors, and there is no training or programmable memory.

Run:

```text
python scripts\test_signed_weights.py
python scripts\generate_signed_network.py
```

`scripts/generate_network.py` remains the Experiment 4 (unsigned) compiler. Experiment 5 adds `scripts/generate_signed_network.py` and writes `circuits/generated_signed_network.cir`.

## Experiment 6 — Train → compile → physical inference

Experiments 1–5 used **manually chosen** weights. Experiment 6 trains a network, freezes it, and compiles those learned parameters into a SPICE circuit.

```
training data
      ↓
Python neural network (NumPy)
      ↓
learned W1, b1, W2, b2
      ↓
frozen model (models/xor_model.npz)
      ↓
physical compiler
      ↓
conductance network + physical ReLU
      ↓
ngspice inference
```

Task: XOR, architecture **2 → 4 ReLU → 1 linear**. A linear network cannot solve XOR, so a correct physical result requires the compiled hidden rectifier. Output is linear; class is **1 if y ≥ 0.5 else 0**. That threshold is fixed in the trainer, not chosen after seeing SPICE numbers.

```text
python scripts\train_xor.py
python scripts\compile_xor.py
python scripts\verify_xor.py
```

The compiler loads the saved model and does not retrain. Each XOR input is applied as voltages and evaluated in ngspice. `results/xor_comparison.png` is drawn from those measured values.

## Experiment 7 — physical robustness / hardware tolerance

The Experiment 6 XOR model stays **frozen**. This experiment does not retrain, retune weights, or redesign the circuit. It asks how far compiled resistors and input voltages can drift before XOR classification breaks.

Each compiled weight/bias resistor is independently perturbed:

```
R_perturbed = R_nominal * (1 + u),   u ~ Uniform[-tolerance, +tolerance]
```

and XOR input voltages can receive Gaussian analog noise. That is a model of **manufacturing tolerance and analog input error**, not software noise.

```text
python scripts\test_robustness.py
```

Nominal 0% is checked first. Then 100 Monte Carlo trials at 0/1/5/10% resistor tolerance, input noise of 0/1/10 mV, and the combined 5% + 10 mV case. Results go to `results/robustness_report.json`, `results/robustness_accuracy.png`, and `results/robustness_error.png`. Perturbed netlists are written to `circuits/generated_xor_robust.cir` so Experiment 6's `generated_xor.cir` stays nominal.

## Experiment 8 — Matter Compiler v1

Experiments 1–7 used a **fixed** weight→resistor map (`G = G_SCALE * w`). Experiment 8 searches other physical mappings of the **same frozen XOR weights**.

```
frozen neural network
      ↓
matter compiler (G_SCALE, quantization, R range)
      ↓
SPICE-in-the-loop score
      ↓
keep or reject the mapping
```

A conventional compiler emits instructions. This one emits physical structure. The trained parameters are not changed; only compilation targets are.

```text
python scripts\optimize_physical_network.py
```

Grid search is deterministic. Each candidate is generated and scored in ngspice. Classification errors are rejected first; among correct mappings the explicit cost prefers lower analog error and lower total conductance. The Experiment 6 netlist stays at `circuits/generated_xor.cir`. A selected mapping is written to `circuits/generated_xor_optimized.cir`.

This is **not** a production accelerator. Limitations:

- tiny network, 4 training points
- SPICE simulation only — no PCB or silicon
- fixed resistors, not programmable memory
- behavioral analog macromodels (CCCS, VCVS op-amp)
- idealized / approximate components
- limited analog precision (precision-rectifier residual)
- no temperature, process, parasitics, or noise analysis
- training remains digital

## Experiment 9 — physical scaling benchmark

Purpose: measure how the existing SPICE architecture (signed conductances, physical current sum/subtract, physical ReLU and bias) scales as the frozen network grows. No transistor-level redesign.

Deterministic random 2-layer networks (ReLU hidden, linear output) are compiled with Matter Compiler v1 over `G_SCALE ∈ {1e-5, 3e-5, 1e-4, 3e-4, 1e-3}`. Weights stay frozen; only the physical mapping may change.

```text
python scripts\benchmark_scaling.py
```

Networks A–F live under `circuits/scaling/`. Experiment 6/8 XOR netlists are not overwritten. Metrics and log-log fits go to `results/scaling_report.json` and the `results/scaling_*.png` plots.

## Experiment 10 — hardware-constrained Matter Compiler

Purpose: keep Experiment 9's frozen weights unchanged and search for a physical mapping whose compiled resistors fit realistic ranges (`1 kΩ–1 MΩ` and `10 kΩ–10 MΩ`). The compiler may change `G_WEIGHT` / `G_BIAS` (including per layer) and implements bias compensation in SPICE with a separate current path. Resistors are not clipped.

```text
python scripts\test_hardware_constraints.py
```

Circuits go to `circuits/hardware_constrained/`. Previous experiments are not overwritten.

## Experiment 11 — dynamic-range physical encoding

Purpose: represent one frozen weight with multiple in-range conductance branches / banks so a layer whose `max|w|/min|w|` exceeds `R_MAX/R_MIN` can still compile into `1 kΩ–1 MΩ`. Parallel resistors handle large conductances; finer CCCS banks handle small ones. Currents add in SPICE.

```text
python scripts\test_dynamic_range.py
```

Circuits go to `circuits/dynamic_range/`. Previous experiments are not overwritten.

## Experiment 12 — non-ideal building blocks

Purpose: keep Experiment 11's frozen multi-range mapping and measure how inference degrades when ideal CCCS / buffer / ReLU macromodels are replaced with parameterized non-ideal behavioral sources, then when the analog rails shrink.

```text
python scripts\test_nonideal_network.py
```

This is **non-ideal behavioral circuit analysis**, not a transistor-level or PCB study. Circuits go to `circuits/nonideal/`. Previous experiments are not overwritten.

## Experiment 13 — precision-preserving physical architectures

Purpose: keep Experiment 9/11 frozen weights and redesign the physical encoding so dynamic range does not require a highly accurate analog current-copy gain on every weight. Architecture A is the Experiment 11 CCCS-bank baseline. Architecture B uses SPICE voltage-domain references (`I = V_range / R`) with a passive nominal path. Architecture C uses passive resistor dividers plus unity buffers. Direct bounded ReLU is used for low-voltage tests instead of the Experiment 12 precision rectifier.

```text
python scripts\test_precision_architectures.py
```

Circuits go to `circuits/precision_architectures/`. Previous experiments are not overwritten.

## Experiment 14 — ratiometric weight fabric

Purpose: keep Experiment 13 Architecture C as the baseline and test whether representing the layer scale as a physical resistor ratio (`V = I * R_IV`, so `w ~ R_IV / R_w`) is less sensitive to correlated process variation than independent 5% resistor Monte Carlo. Architecture D puts `R_IV` in the SPICE netlist. Architecture E compiles one global or per-layer VCVS constant from dedicated calibration cells. This is a behavioral variation study, not a foundry or PCB model.

```text
python scripts\test_ratiometric_variation.py
```

Circuits go to `circuits/ratiometric/`. Previous experiments are not overwritten.

## Experiment 15 — mismatch-limited ratiometric fabric

Purpose: keep Experiment 14 Architecture D and measure the leftover analog floor: unit-resistor tiling versus independent local mismatch, signed-path (I+ vs I−) offset, and isolated errors on the remaining ideal blocks (unity CCCS, buffers, direct ReLU). Frozen weights. SPICE inference. Behavioral mismatch study, not layout or foundry data.

```text
python scripts\test_mismatch_limits.py
```

Circuits go to `circuits/mismatch/`. Previous experiments are not overwritten.

## Experiment 16 — copy-minimizing fabric

Purpose: keep Experiment 14 Architecture D's frozen weight encoding and remove leftover analog **copy** blocks (the Experiment 15 floor). Architecture D is the dual-CCCS + buffered-divider baseline. Architecture I puts both signs on one 0 V summing node, builds `-Vin` with a passive invert (resistor ratio), load-compensates fine-bank dividers so tap buffers can go, and dumps one current onto physical `R_IV`. Architecture M keeps D's resistors and buffers but subtracts `I+` and `I-` with one matched current source. A finite-A feedback TIA was tried on I and rejected: the summing node sits at `V/A` and breaks unbuffered divider math.

```text
python scripts\test_copy_minimizing.py
```

Circuits go to `circuits/copy_minimizing/`. Previous experiments are not overwritten.

## Experiment 17 — physical current-to-voltage neuron

Purpose: keep Experiment 16 Architecture I's frozen fabric and replace the leftover behavioral current dump with a physical I-to-V stage whose gain is a resistor (or resistor ratio), not a 0.1%-accurate copy. Architecture I is reproduced as the baseline. Architecture A is a feedback TIA that holds the summing node. Architecture B restores TIA polarity with `Rf * (R2/R1)`. Architecture C moves hidden ReLU into the current domain, then still uses a TIA. Finite-A residual is not Python-corrected. `V_sum` is measured in SPICE.

```text
python scripts\test_iv_architectures.py
```

Circuits go to `circuits/physical_iv/`. Previous experiments are not overwritten.

## Experiment 18 — passive current-to-voltage bound

Purpose: test whether `V = I × Rf` at the summing node can replace the Experiment 17 TIA without an active virtual ground. Architecture P places Rf to ground and isolates the next layer with a ReLU B-source. Architecture L attaches layer 2 to the hidden summing nodes (resistor mesh). Charge-domain DC vs transient is measured on a unit capacitor.

```text
python scripts\test_passive_iv.py
```

Circuits go to `circuits/passive_iv/`. Master log: `RESEARCH_LOG.md`.

## Experiment 19 — replica-null TIA offset

Purpose: test whether a matched replica TIA (`Vsig − Vrep`, dummy G_tot) cancels the 1 mV Vos that dominated Experiment 17's combined Monte Carlo. Architecture N matches Vos. Architecture U leaves replica Vos = 0.

```text
python scripts\test_tia_offset.py
```

Circuits go to `circuits/tia_offset/`.

## Experiment 20 — current-mode cascade bound

Purpose: test whether hidden I-to-V can be removed by cascading in current. Architecture J copies hidden I_y with one CCCS per W2 weight. Architecture S uses a resistive current splitter (`I G/G_tot`).

```text
python scripts\test_current_cascade.py
```

Circuits go to `circuits/current_cascade/`.

## Experiment 21 — finite TIA gain is per-neuron

Purpose: test whether finite open-loop A is a global scale `k=A/(A+1)` or a per-neuron factor `A/(A+1+Rf G_tot_j)` on Experiment 17 Architecture A.

```text
python scripts\test_finite_a_scale.py
```

Circuits go to `circuits/finite_a_scale/`.

## Experiment 22 — virtual-ground requirement extraction

Purpose: turn Experiments 17–21 into a specification for the Architecture A TIA (open-loop gain, Vos, leakage, Rout, behavioral pole) on frozen Networks A and F. Analog bar is MAE <= 1e-3; classification is reported separately.

```text
python scripts\test_virtual_ground_requirements.py
```

Circuits go to `circuits/virtual_ground_requirements/`. Report: `results/exp22_virtual_ground_requirements.md`.

## Experiment 23 — virtual-ground primitive validation

Purpose: replace the behavioral TIA with documented XSPICE / manufacturer primitives and test them against Experiment 22 on frozen o2, Network A, then Network F. Analog bar remains MAE <= 1e-3. Manufacturer models are `.include`d from the local ngspice examples tree, not copied.

```text
python scripts\test_virtual_ground_primitive.py
python scripts\test_virtual_ground_primitive_recovery.py
```

Circuits go to `circuits/virtual_ground_primitive/`. Report: `results/exp23_virtual_ground_primitive.md`.

## Experiment 24 — offset-corrected virtual-ground search

Purpose: search documented low-offset macromodels and circuit-level offset correction (auto-zero, chopper-equivalent, summing-node servo) against Experiment 22 analog MAE <= 1e-3, without editing frozen weights or Python-correcting SPICE. Classification is reported separately.

```text
python scripts\test_offset_vg_search.py
python scripts\test_offset_vg_search_recovery.py
python scripts\test_offset_vg_mismatch.py
```

Circuits go to `circuits/offset_vg_search/`. Report: `results/exp24_offset_vg_search.md`.

LEVEL 2 servo (DC) and Vref-gated auto-zero (TRAN) analog-pass Network F at 214 µV Vos. LEVEL 3 OPA1656 does not (F MAE 0.017, Vsum ~498 µV). 0.5% resistor mismatch remains ~4e-3 after offset is solved.

## Experiment 25 — servo transient validation

Purpose: determine whether the Experiment 24 summing-node servo is dynamically stable and useful (nested-loop TRAN, settling, changing inputs) without Python correction or a new resistor encoding.

```text
python scripts\test_servo_transient.py
python scripts\test_servo_transient_recovery.py
```

Circuits go to `circuits/servo_transient/`. Report: `results/exp25_servo_transient.md`.

LEVEL 2 OTA-C servo analog-passes Network F TRAN on a 12-vector subset (MAE 6.4e-5) at Vos=214 µV with a behavioral 1 kHz TIA pole and tau=10 µs. Changing inputs need ≥ 200 µs dwell. Servo faster than the TIA pole distorts inference. This is sampled inference, not the Exp 22 10 µs continuous target. 0.5% R remains the analog floor.

## Experiment 26 — device-level neuron primitive

Purpose: determine whether one transistor-level analog neuron (virtual-ground miller TIA + miller servo) can meet the Experiments 22–25 electrical requirements on frozen Network F o2, using documented BSIM3v3 teaching cards. Not a new encoding. Not Network F in MOS. SPICE is never Python-corrected.

```text
python scripts\test_device_neuron.py
```

Circuits go to `circuits/device_neuron/`. Report: `results/exp26_device_neuron.md`. JSON: `results/device_neuron_report.json`.

LEVEL 4 teaching-card miller+servo analog-passes isolated o2 at 27 °C, ±2.5 V (|Vlin−z| ≈ 5.6e-5, Vsum ≈ −0.67 µV, 214 µV inject corrected, 100–1000 µs dwell). IHP SG13G2 is not installed. Not silicon. 0.5% R and −40/85 °C still analog-fail. Invert VCVS remains ideal.

## Experiment 27 — matching and temperature

Purpose: determine whether the Experiment 26 transistor neuron can be made accurate and temperature-stable enough to be a credible physical primitive. Frozen weights unchanged. SPICE is never Python-corrected. No new encoding. Not Network F in MOS.

```text
python scripts\exp27_matching_temperature.py
```

Circuits go to `circuits/exp27_matching_temperature/`. Report: `results/exp27_matching_temperature.md`. JSON: `results/exp27_matching_temperature.json`.

Architecture A is ratiometric (common-mode 0.5% is invisible; ratio-matched 0.5% MAE ≈ 8.9e-4). Independent 0.5% tiling flattens by N=16 (MAE ≈ 2.6e-3). MOS-only `.temp` CASE 1 replays Exp 26 (~4e-3 at −40/85 °C). Unbuffered capacitive CDS analog-passes −40/27/85 °C (MAE ≤ 4.6e-4) and preserves 200 µs A–B–C–A at 85 °C; the output is a high-Z capacitor plate. A miller follower misses 85 °C / 200 µs. IHP / resistor TCR / MOS mismatch PDFs were not invented.

## Experiment 28 — CDS output interface

Purpose: determine whether a transistor-level interface can extract the Experiment 27 CDS-corrected voltage without Python correction, weight edits, or a new encoding. Not Network F in MOS.

```text
python scripts\exp28_output_interface.py
```

Circuits go to `circuits/exp28_output_interface/`. Report: `results/exp28_output_interface.md`. JSON: `results/exp28_output_interface.json`.

The raw plate cannot drive 1 pF or 100 MΩ. The Exp 27 miller follower fails because it adds ~0.71 mV at 85 °C (CM-dependent Vos at |z|≈1.73 V) while the plate stays analog-good. A virtual-ground charge amp plus MOS invert+servo analog-passes −40/27/85 °C (|err| ≤ 2.8e-4), preserves 200 µs A–B–C–A, and drives 100 pF / 100 kΩ. Invert DW=0.0026 is a 27 °C invert-amp null, not a per-temperature trim. P ≈ 8.80 mW for one neuron. Independent 0.5% R mismatch is unchanged.

## Experiment 29 — resistor-ratio matching

Purpose: determine whether a physically interpretable resistor-ratio matching structure can bring frozen Network F to analog MAE ≤ 1e-3 without blind tiling, per-weight calibration, or a new encoding. Not Network F in MOS. SPICE is never Python-corrected.

```text
python scripts\exp29_resistor_ratio_matching.py
```

Circuits go to `circuits/exp29_resistor_ratio_matching/`. Report: `results/exp29_resistor_ratio_matching.md`. JSON: `results/exp29_resistor_ratio_matching.json`.

Architecture A is ratiometric on the full 1342-resistor fabric: common-mode 0.5% equals the nominal finite-A floor (MAE ≈ 4.8e-4). Independent 0.5% stays at MAE ≈ 4.2e-3 (classification ~99%). Per-neuron Rf·G matching at 0.5% with a 15% local residual analog-passes a 16-draw 40-vector Network F set (mean MAE **8.02e-4**, worst **9.38e-4**, limited MC, not a yield). Leftover unmatched local error after that grouping must stay ≲ 0.075%. Integer unit-element reconstruction of the frozen continuous map needs ~9e6 units before quantization alone analog-passes. No foundry PCM was invented.

## Experiment 30 — physical invert and matching-technology search

Purpose: test whether the remaining Architecture A invert VCVS can be replaced by a documented physical primitive without destroying the frozen Network F analog map, and whether a local resistor PDK can host Experiment 29's ratio-matching requirement. Not Network F in MOS. No invented foundry. SPICE is never Python-corrected.

```text
python scripts\exp30_physical_invert_matching.py
```

Circuits go to `circuits/exp30_physical_invert_matching/`. Report: `results/exp30_physical_invert_matching.md`. JSON: `results/exp30_physical_invert_matching.json`. Inventory: `results/exp30_tech_inventory.json`.

The compiled fabric has 49 invert stages (16 input, 1 Vref, 32 hidden). Only the hidden stages copy a computed ReLU; input/Vref may be polarity copies. A grounded resistor tap cannot invert about 0. XSPICE `limit` on all 32 hidden inverts plus polarity copies preserves F40 analog MAE (**4.86e-4**). The teaching miller invert fails isolated transfer at the extracted load/swing (|err| 0.20–1.97 V at 4.9 kΩ / up to 2.61 V). All 32 hidden OPA1656 analog-fail (MAE **2.64e-3**) while classification stays 1.0. Invert R1/R2 must stay pair-matched; systematic ratio ≲ 0.075%. IHP / SkyWater / r2_cmc are not installed. Status: physical invert primitive partially validated. Next direction: the physical invert remains the dominant bottleneck.

## Experiment 31 — hidden-inverter drive and output-stage search

Purpose: extract the actual hidden-inverter current / swing / Rout / Vos requirements and explain why one OPA1656 insertion analog-passes while 32 fail. Not Network F in MOS. No invented W/L or foundry. SPICE is never Python-corrected.

```text
python scripts\exp31_hidden_inverter_drive.py
```

Circuits go to `circuits/exp31_hidden_inverter_drive/`. Report: `results/exp31_hidden_inverter_drive.md`. JSON: `results/exp31_hidden_inverter_drive.json`.

OPA1656 scaling is gradual: N=8 still analog-passes (MAE 7.16e-4); N=16 fails (1.45e-3); N=32 fails (2.64e-3). Every OPA invert mid sits at **~498 µV** (the Experiment 24 TIA Vsum). Behavioral Vos=500 µV reproduces the 32-OPA MAE. Independent supplies do not. Required hidden invert: ≳ 0.40 mA (peak 0.63 mA), |Vout| ≳ 2.5 V plus headroom, Vos ≲ 100 µV at 32 instances. Linear Rout inside a high-A loop is not the miller failure. Teaching miller and miller+follower fail isolated. Status: physical hidden inverter not yet validated. Next direction: documented device models are insufficient to implement those requirements.

## Experiment 32 — physical low-offset hidden-inverter primitive search

Purpose: find a documented hidden-layer invert cell that meets the Experiment 31 requirements (gain ≈ −1, ~2.61 V, ~4.91 kΩ, ≳ 0.40 mA, Vos-scale residual ≲ 100 µV, N=32 analog-pass, 200 µs), or show that the local model library cannot provide one. Not Network F in MOS. No invented W/L or foundry. SPICE is never Python-corrected.

```text
python scripts\exp32_hidden_inverter_primitive.py
```

Circuits go to `circuits/exp32_hidden_inverter_primitive/`. Report: `results/exp32_hidden_inverter_primitive.md`. JSON: `results/exp32_hidden_inverter_primitive.json`. Inventory: `results/exp32_inverter_candidate_inventory.json`.

Experiment 31 baseline reproduces (limit-32 MAE 5.12e-4; OPA N=1/8/16/32 = 5.32e-4 / 7.16e-4 / 1.45e-3 / 2.64e-3; Vos=500 µV MAE 2.667e-3; mid pedestal 498 µV). No uncorrected local macromodel meets the 100 µV loaded floor. Shared replica with IN+ = −replica mid analog-passes N=32 and F40 (MAE **4.838e-4**, acc 1.0, 200 µs residual ~135 nV) using a LEVEL 2 sign of that pedestal. IN+ = +replica mid explodes. A follower is not transparent. Status: physical hidden inverter partially validated. Next bottleneck: a macromodel whose loaded invert mid stays ≲ 100 µV without a behavioral sign, or a real PDK. Do not invent MOS.

## Experiment 33 — documented precision-inverter model and PDK gap closure

Purpose: acquire a documented precision macromodel or PDK, if the environment allows, and test it against the Experiment 31/32 hidden-invert requirements. Inventory first. Do not invent MOS. Do not transistorize Network F. SPICE is never Python-corrected.

```text
python scripts\exp33_documented_precision_primitive.py
```

Circuits go to `circuits/exp33_documented_precision_primitive/`. Report: `results/exp33_documented_precision_primitive.md`. Before/after inventory: `results/exp33_model_inventory_before.json`, `results/exp33_model_inventory_after.json`. Official TI OPA189/192/388 PSpice models: `models/vendor/ti/` (unmodified).

After a before-inventory (no PDK, no OSDI, no chopper models), official TI zips were installed. Isolated OPA189 |Vout+Vin| is **0.64–0.68 µV** at 2.61 V / 4.91 kΩ (Tier 1), with 200 µs TRAN and −40/27/85 °C <2 µV. Zero-drift in the model is a static VOS_DRIFT term, not chopping. N=16 analog-passes (7.62e-4); N=32 fails (**1.014e-3**). That fail is a 32-copy residual (~575 µV mean), not 32× the isolated 0.66 µV. OPA192 isolated-passes and fabric-timeouts. No PDK was cloned. Status: physical hidden inverter partially validated. Next bottleneck: the N=32 multi-instance residual, or accept LEVEL 2 invert / replica-sign.

## Experiment 34 — 32-copy OPA189 residual mechanism and fabric loading isolation

Purpose: determine why isolated OPA189 residual ~0.66 µV becomes a large residual at N=32 in the frozen Architecture A fabric. Do not search for another amplifier. Do not invent MOS. Do not transistorize Network F. SPICE is never Python-corrected.

```text
python scripts\exp34_opa189_32copy_mechanism.py
```

Circuits go to `circuits/exp34_opa189_32copy_mechanism/`. Report: `results/exp34_opa189_32copy_mechanism.md`.

Experiment 33 N-scaling reproduces. Isolated 32-copy OPA189, including actual hidden voltages and dest Rfab, stays at **0.66 µV** (shared or independent supplies). The fabric default-reltol mean invert residual **192 µV** is **one F12 vector at 2.29 mV**; the other 11 vectors stay at ~0.73 µV and all 32 stages agree. The same netlist at `reltol=1e-6` analog-passes (MAE **5.10e-4**, residual 0.73 µV) and is **not promoted**. A LEVEL 2 dest buffer failed. Independent supplies do not change MAE. Decision **E**: further physical/model evidence is required. F40 was not earned. Next bottleneck: a documented coupled-GWL solver/model policy or a PDK — not another op-amp.

## Experiment 35 — N=32 OPA189 convergence and robustness qualification

Purpose: determine whether the Experiment 34 `reltol=1e-6` N=32 pass is robust numerical behavior or a solver-dependent escape. Do not edit frozen weights. Do not invent MOS. Do not transistorize Network F. Do not jump to F40 until N=32 is qualified.

```text
python scripts\exp35_opa189_convergence.py
python scripts\exp35_opa189_convergence.py --complete-gates
```

Circuits go to `circuits/exp35_opa189_convergence/`. Report: `results/exp35_opa189_convergence.md`.

Experiment 34 is reproduced: default DC MAE **1.0142e-3** (invert-fail vector 6, 2.29 mV); `reltol=1e-6` MAE **5.1038e-4**. The reltol sweep is a discontinuous two-OP map with a hole at `2e-5`. Absolute tolerances, vector order, and full-F12 DC initial conditions do not move the bad branch. Isolated 32-copy stays at **0.64 µV**. Trapezoidal independent F12 TRAN hangs on 8/12 vectors. Gear independent F12 TRAN at 200 µs analog-passes (MAE **5.1668e-4**, max **3.16e-3**, acc 1.0) at factory reltol and at `5e-5`. Three DC repeats at `reltol=5e-5` are identical (MAE **5.1038e-4**). Decision **F**: PHYSICAL HIDDEN INVERTER VALIDATED AT N=32. F40 is now permitted on the documented solver policy (DC `reltol=5e-5`, TRAN `method=gear`). OPA189 remains a vendor macromodel, not silicon.

## Experiment 36 — full Network F40 physical hidden-inverter integration

Purpose: integrate the Experiment 35 qualified OPA189 hidden invert across frozen F40. Do not edit weights. Do not invent MOS. Do not transistorize Network F. Do not replace OPA189.

```text
python scripts\exp36_f40_physical_hidden_inverter.py
```

Circuits go to `circuits/exp36_f40_physical_hidden_inverter/`. Report: `results/exp36_f40_physical_hidden_inverter.md`.

Controls reproduce: ideal F40 MAE **4.838e-4**; XSPICE limit F40 MAE **4.859e-4**; N=32 DC **5.1038e-4**; N=32 Gear 200 µs **5.1668e-4**. Qualified F40 DC (`reltol=5e-5`) MAE **6.313e-4**, max **9.073e-3**, acc 1.0, three identical repeats. Vector 18 remains the 2.29 mV Newton branch at that DC; factory DC analog-MAE-fails [6, 18, 29]. reltol 2e-5 / 1e-5 / 1e-6 do not converge on F40. Independent Gear F40 200 µs MAE **4.859e-4**, max **3.429e-3**, acc 1.0; 100/500 µs also analog-pass; order does not matter. Decision **F**: FULL NETWORK PHYSICAL HIDDEN-INVERTER INTEGRATION VALIDATED, inside a mixed-level Architecture A fabric (TIA/ReLU still behavioral). Not silicon.

## Experiment 37 — physical TIA integration and technology requirements

Purpose: test whether the documented Experiment 26 miller TIA + miller servo survives the extracted electrical requirements of the now-qualified Network F map. Do not edit weights. Do not invent MOS W/L or a PDK. Do not transistorize all of Network F. Do not reopen the invert search.

```text
python scripts\exp37_physical_tia_integration.py
```

Circuits go to `circuits/exp37_physical_tia_integration/`. Report: `results/exp37_physical_tia_integration.md`.

Experiment 36 F40 DC MAE **6.3132e-4** and Gear 200 µs MAE **4.8589e-4** reproduce before any TIA change. Worst TIA load is still o2 (Rf·G_tot **140.9**); highest F40 |z| is h25 at **2.94 V**. Isolated miller replay matches Experiment 26 (no-servo fail, servo **5.63e-5**). Representative isolated fabrics analog-pass at 27 °C. Batched F12 DC insertion times out; independent DC is solver-branchy and is not promoted. Independent Gear 200 µs insertion analog-passes (o2 MAE **7.95e-4** repeatable; h25 **5.51e-4**; h21 **5.78e-4**; acc 1.0). Raw −40/85 °C fail; CDS still analog-passes. Independent 0.5% R fails; Rf·G tracking still holds. Decision **B**: PHYSICAL TIA PARTIALLY VALIDATED. F40 physical TIA was not simulated. Not silicon.

## Experiment 38 — semiconductor technology feasibility

Purpose: map the extracted Physical AI requirements onto documented open PDKs. Do not invent a PDK, W/L, TCR, or mismatch PDF. Do not transistorize Network F.

```text
python scripts\exp38_technology_audit.py
```

Report: `results/exp38_technology_feasibility.md`. Sources: `docs/exp38_sources/sources.json`.

Recalculated fabric matches Experiment 29 (1342 R). Worst-neuron 234 µA is not network total current (sum of per-neuron I_max is 7.30 mA). SKY130 / IHP SG13G2 / GF180MCU document analog MOS, poly R, and MIM; none is installed. Public docs do not prove leftover matching 0.075%. Fully integrated 2 nF CDS is area-impractical at documented MIM density. Decision **B**: TECHNOLOGY PLAUSIBLE BUT KEY DATA MISSING. No invented process parameters.

## Experiment 39 — first real SKY130 PDK isolated cell (o3)

Purpose: install one official open PDK and host one frozen Network F cell. Do not transistorize Network F. Do not invent process parameters.

```text
python scripts\exp39_install_sky130.py
python scripts\exp39_pdk_o2_cell.py
python scripts\exp39_followup.py
```

Reports: `results/exp39_pdk_o2_cell.md`, `results/exp39_pdk_inventory.md`, `results/exp39_pdk_requirements.md`, `results/exp39_identity_correction.md`.

Official SKY130A `1689ac3f2dc763876eaf967227c7dfe831b031ae` ran in ngspice-47. Simulated cell = **o3 / W2[2]**, Rf·G = **7.803810**, z_ref = **−2.162419 V**. Catalog o2 / W2[1] Rf·G = **140.893980** was **not** transistorized (withdrawn). W=1 xhigh_po + behavioral TIA |err| **5.924e-3** (tt=ll=hh). W=10 **2.274e-3**. 5V miller no-servo DC/200 µs |err| **1.663e-3 / 1.667e-3**. tt_mm n=20 MAE **0.0196**. Analog bar not met. Matching UNRESOLVED. Automated `decide()` = **C**. Published **B** withdrawn. Decision **C**.

## Experiment 40 — catalog o2 on official SKY130A (CLOSED)

Purpose: instantiate the actual frozen o2 cell (`W2[1]`, Rf·G = 140.893980) in official SKY130A and measure analog error. Do not modify Experiment 39. Do not edit weights. Do not optimize.

```text
python scripts\exp40_pdk_o2_cell.py
```

Reports: `results/exp40_pdk_o2_cell.md`, `results/exp40_pdk_o2_cell.json`, `results/exp40_pdk_requirements.md`, `results/exp40_closure.md`.

**Closed.** Identity-gated **W2[1]** only. Deck Rf·G = **140.893980**. y = **2.45254388951**, |err| = **6.945681370132295 mV** vs 1.0 mV bar (**FAIL**, ≈6.95×). tt=ll=hh identical leftover (not matching). Matching **UNRESOLVED**. W=10 / Miller / MC / temperature **NOT TESTED**. Automated `decide()` = **C**. No override.

**Experiment 39: C — identity-corrected o3 experiment; critical o2 not simulated.**  
**Experiment 40: C — critical o2 correctly simulated; analog bar fails at 6.946 mV.**

## Experiment 41 — o2 residual decomposition (CLOSED)

Purpose: split the Experiment 40 6.946 mV residual into amplifier versus PDK-resistor contributions. Do not change weights or the 1 mV bar. Diagnostics are not a design solution.

```text
python scripts\exp41_o2_residual.py
```

Reports: `results/exp41_o2_residual.md`, `results/exp41_o2_residual.json`.

Finite-A identity predicts −3.485 mV and cannot explain 6.946 mV. Ideal lumped R + A=1e5: |err| = **2.056 mV**. W=1 PDK leftover versus that bench: **4.890 mV**. Sum = Exp40 residual. W=10 diagnostic |err| = **1.452 mV** (still FAIL). Exp39 Miller unre-sized: |err| = **627 mV**. Matching **UNRESOLVED**. Network-F 2.937 V **NOT DEMONSTRATED**. Experiment 40 Decision **C** unchanged.

## Experiment 42 — o2 1 mV feasibility boundary (CLOSED)

Purpose: establish whether the 1 mV bar is fundamentally impossible at A=1e5 / W=1, or theoretically reachable with higher amplifier gain and/or existing resistor geometry, without changing frozen o2 weights. Do not optimize. Do not search transistors. Do not modify Experiments 39–41.

```text
python scripts\exp42_o2_feasibility.py
```

Reports: `results/exp42_o2_feasibility.md`, `results/exp42_o2_feasibility.json`.

No SPICE. Analytical A_required = **348844.87** (k identity; current A is 3.488× too small; no safety margin). Ideal R + A=1e5: **FAIL**. Ideal R + A ≥ A_required: theoretical **PASS** (not demonstrated). W=1 + infinite A: leftover **4.894 mV FAIL**. W=10 + sufficiently high A: leftover **0.605 mV**, theoretically capable of **PASS** (not demonstrated; W=10 at A=1e5 remains 1.452 mV FAIL). Existing Miller: **627 mV FAIL**, not optimized. Matching **UNRESOLVED**. Experiment 40 Decision **C** unchanged.

## Experiment 43 — high-gain behavioral TIA + existing W=10 (CLOSED)

Purpose: demonstrate Experiment 42 Case C in SPICE. Existing W=10 encode, frozen o2 weights, behavioral TIA A above the finite-gain boundary. No resistor fitting, no Python correction, no MOS search.

```text
python scripts\exp43_highgain_w10.py
```

Reports: `results/exp43_highgain_w10.md`, `results/exp43_highgain_w10.json`. Circuits: `circuits/exp43_o2/`.

Baselines at A=1e5 match Experiments 40/41 exactly. W=10 crosses 1 mV at measured **A_cross = 128203** (last fail 128092.83 at 1.000528 mV; Exp42 prediction 128203.10, Δ = +0.098). Ideal R first passes at A = 348845. W=1 at A=1e7 remains **4.927 mV FAIL**. W=10 leftover vs ideal R stays **+0.604 to +0.607 mV** across A. Repeat at A=1e6: Δy = 0. Sensitivity at A=1e6 on frozen F40 vectors 19 / 20 / 38 / 6: all **PASS**. **Decision A — BEHAVIORAL HIGH-GAIN + W=10 FEASIBILITY DEMONSTRATED.** Physical TIA **NOT** validated. Matching **UNRESOLVED**. Experiment 40 Decision **C** unchanged.

## Experiment 44 — physical high-gain TIA requirement extraction (CLOSED)

Purpose: translate the Experiment 43 W=10 behavioral feasibility point into electrical budgets. Do not invent MOS W/L. Do not claim a physical TIA.

```text
python scripts\exp44_tia_requirements.py
```

Reports: `results/exp44_tia_requirements.md`, `results/exp44_tia_requirements.json`.

Behavioral A is **open-loop VCVS gain**, not loop gain. T = A/(1+Rf·G); A_cross=128203 ⇒ **T≥903.5 (59.12 dB)**. Measured OP: Vout=2.458490 V, |Vsum|=19.18 µV, |Iout|=73.71 µA. At A=2e5: Vos pass +10 µV / fail +22 µV; Ileak pass 13 nA / fail 30 nA; Rout pass 10 kΩ / fail 20 kΩ. 200 µs TRAN with behavioral poles 10 Hz–10 kHz **PASS**. Existing SKY130 Miller a_eff≈245 is **523× below** A_ol. **Decision R — REQUIREMENTS EXTRACTED; PHYSICAL TIA NOT VALIDATED.** Matching **UNRESOLVED**. Experiment 45: documented macromodel vs these budgets.

## Experiment 45 — documented macromodel TIA on W=10 o2 (CLOSED)

Purpose: test whether a documented Level-1 macromodel can meet the Experiment 44 budgets on the same frozen W=10 o2 cell. No MOS W/L. No resistor fitting. No Python correction. Not silicon.

```text
python scripts\exp45_documented_tia.py --phase3
```

Reports: `results/exp45_documented_tia.md`, `results/exp45_documented_tia.json`. Circuits: `circuits/exp45_o2/`.

Phase 1: `ngbehavior=hsa` blocked TI `PARAMS:` parse. Phase 2: `ngbehavior=ps` parsed OPA189, but `.lib sky130.lib.spice tt` was read as include-file `tt`. Phase 3: official tt resistor `.include` cards (same files the `tt` section uses for `xhigh_po`). Behavioral A=1e5 control matched Experiment 41 exactly (Δy = 0).

| Candidate | ±V | |err| (mV) | Vsum | pass |
| --- | ---: | ---: | ---: | --- |
| OPA189 | 15 | **0.606** | 14.1 nV | yes |
| OPA192 | 15 | **0.882** | 3.28 µV | yes |
| OPA388 | 2.5 | **0.615** | 102 nV | yes |
| OPA1656 | 15 | 42.32 | 498.06 µV | no |
| OPA171 | 15 | 1164 | −13.95 mV | no |

OPA1656 Vsum reproduces the Experiment 23/24 498 µV floor. OPA189 error matches the W=10 high-A leftover (~0.605 mV). **Decision A — DOCUMENTED MACROMODEL MEETS 1 mV ON W=10 o2.** Physical TIA **NOT** validated (macromodel ≠ PDK MOS ≠ silicon). Matching **UNRESOLVED**. Isolated DC only.

## Experiment 46 — OPA189 TIA promotion on isolated W=10 o2 (CLOSED)

Purpose: promote the Experiment 45 OPA189 pass through extra frozen vectors, 200 µs transient, and temperature. Still isolated. Still a macromodel.

```text
python scripts\exp46_tia_promotion.py
```

Reports: `results/exp46_tia_promotion.md`, `results/exp46_tia_promotion.json`.

DC repeat matches Experiment 45 exactly (Δy = 0). Frozen F40 vectors 19 / 20 / 38 / 6 all **PASS** (0.606 / 0.431 / 0.022 / 0.041 mV). 200 µs TRAN **PASS** (0.605 mV). Temperature −40 / 27 / 85 °C all **PASS** (0.410 / 0.606 / 0.637 mV). OPA189 ±5 V **PASS** (0.500 mV). OPA388 ±2.5 V **PASS** (0.615 mV). **Decision A — OPA189 TIA PROMOTED ON ISOLATED W=10 o2 (DC/TRAN/TEMP).** Physical TIA **NOT** validated. Network F **NOT TESTED**. Matching **UNRESOLVED**.

## Experiment 47 — OPA189 catalog o2 TIA in Network F (CLOSED)

Purpose: insert the Experiment 45/46 OPA189 TIA as **only** `Eo2tia` in frozen Network F. Ideal-R fabric. Behavioral hidden inverts and all other TIAs. Not W=10. Not silicon.

```text
python scripts\exp47_network_o2_tia.py
```

Reports: `results/exp47_network_o2_tia.md`, `results/exp47_network_o2_tia.json`.

F12 behavioral control MAE **0.596 mV** analog-pass. F12 OPA189-o2 MAE **0.552 mV**. F40 OPA189-o2 MAE **0.438 mV**, acc 1.0. **Decision A — OPA189 o2 TIA HOLDS ANALOG MAE IN NETWORK F.** Mixed-level only. Physical TIA **NOT** validated. Matching **UNRESOLVED**.

## Experiment 48 — W=10 SKY130 Miller ± servo (CLOSED)

Purpose: test H4 — whether the existing Experiment 39/41 SKY130 Miller plus the documented 1 nF servo can realize the Experiment 43 W=10 point. No W/L resize.

```text
python scripts\exp48_w10_miller_servo.py
```

Reports: `results/exp48_w10_miller_servo.md`, `results/exp48_w10_miller_servo.json`.

No-servo y = **1.834 V**, a_eff = **245**, |err| = 626 mV (Exp41 repeat). Servo y = **2.098 V**, a_eff = **486**, |err| = **361 mV**, Vsum = −4.32 mV, headroom to +2.5 V = **0.402 V**. A first rail-limit label was withdrawn. **Decision B — MILLER+SERVO CONVERGED BUT MISSED THE 1 mV BAR.** Physical TIA **NOT** validated. OPA189 remains the Level-1 host.

## Experiment 49 — existing Miller+servo 200 µs TRAN (CLOSED)

Purpose: decide whether the Experiment 48 DC miss is only an integrator DC artifact, or whether the sampled 200 µs result also fails. Same circuit. No W/L resize.

```text
python scripts\exp49_miller_servo_tran.py
```

Reports: `results/exp49_miller_servo_tran.md`, `results/exp49_miller_servo_tran.json`.

DC repeat matches Experiment 48 exactly (y = 2.098479 V, Δ = 0). Transient trajectory: 100 µs y = 1.994 V (466 mV); 200 µs y = 2.045 V (415 mV); 500 µs y = 2.087 V (372 mV). Independent 200 µs repeat matches. The servo integrates **toward the DC miss**, not toward z. **Decision D — EXISTING MILLER+SERVO IS A CLOSED NEGATIVE PATH.** Physical TIA **NOT** validated.

## Experiment 50 — Track B inventory and miller A_ol attempt (CLOSED)

Purpose: inventory documented SKY130 amplifier IP and measure open-loop gain of the existing miller. No W/L resize.

```text
python scripts\exp50_pdk_amp_inventory.py
```

Reports: `results/exp50_pdk_amp_inventory.md`, `results/exp50_pdk_amp_inventory.json`.

No opamp/OTA cell filenames in the SKY130A tech tree. IHP/GF180 not installed. Isolated miller DC at Vid ≤ 1 mV sits on the negative rail; Vrail/Vid ≈ 2e5 is **not** linear A_ol and is withdrawn. **Decision E — OPEN-LOOP A_ol WAS NOT EXTRACTED.** In-TIA a_eff ≈ 245 remains the only defensible pre-null gain.

## Experiment 51 — offset-nulled miller A_ol (CLOSED)

Purpose: find the Vid that centers the existing miller, then measure incremental A_ol. No W/L resize.

```text
python scripts\exp51_miller_aol_null.py
```

Reports: `results/exp51_miller_aol_null.md`, `results/exp51_miller_aol_null.json`.

Null Vid = **4.30 mV** (no load) / **5.74 mV** (73.71 µA). Incremental A_ol = **2714** / **2507**. Two identical stages would meet A≥128203 **if offset were removed**. The 5.74 mV loaded offset is ~260× the Experiment 44 Vos budget. **Decision B — OFFSET-NULLED A_ol = 2507; CASCADE NEEDS ~2 STAGES (VOS UNRESOLVED).**

## Experiment 52 — two-copy miller TIA (CLOSED)

Purpose: close the TIA loop around two copies of the existing sky_miller. No new W/L.

```text
python scripts\exp52_cascade_miller.py
```

Reports: `results/exp52_cascade_miller.md`, `results/exp52_cascade_miller.json`.

y = **2.09887 V**, |err| = **361 mV**, Vmid = 12.6 mV, a_eff = 487 — the same miss as Experiment 48 servo. First-stage offset saturates the cascade. **Decision D — TWO-COPY MILLER TIA CLOSED.** Unre-sized miller family (single / servo / cascade) is a closed negative path. OPA189 remains the Level-1 host.

## Experiment 53 — W=10 tt_mm mismatch at A=1e6 (CLOSED)

Purpose: apply the official SKY130 `tt_mm` AGAUSS mismatch model to the Experiment 43 W=10 + A=1e6 cell. Not a foundry yield.

```text
python scripts\exp53_w10_ttmm.py
```

Reports: `results/exp53_w10_ttmm.md`, `results/exp53_w10_ttmm.json`.

Nominal tt |err| = **0.401 mV** (matches Exp43). Eight `tt_mm` draws: **1/8 PASS**. Mean |err| = **3.23 mV**, max = **8.51 mV**. **Decision C — MATCHING UNRESOLVED AT THIS AREA.** Deterministic W=10 success is not a Pelgrom pass.

## Research direction

## Research direction

Later experiments can grow this into:

1. Fixed resistor weighted sum *(Experiment 1)*
2. Python generation of resistor values from weights *(Experiment 2)*
3. Multiple physical neurons / linear layer *(Experiment 3)*
4. Nonlinear activation *(Experiment 4)*
5. Signed multi-layer physical network *(Experiment 5)*
6. Train → compile → physical inference *(Experiment 6)*
7. Hardware-tolerance robustness of the compiled circuit *(Experiment 7)*
8. Matter Compiler v1 — optimize the physical mapping *(Experiment 8)*
9. Scaling benchmark of the same physical architecture *(Experiment 9)*
10. Hardware-constrained Matter Compiler *(Experiment 10)*
11. Dynamic-range multi-branch weight encoding *(Experiment 11)*
12. Non-ideal behavioral building blocks *(Experiment 12)*
13. Precision-preserving physical encodings *(Experiment 13)*
14. Ratiometric weight fabric and variation models *(Experiment 14)*
15. Mismatch-limited ratiometric fabric *(Experiment 15)*
16. Copy-minimizing fabric *(Experiment 16)*
17. Physical current-to-voltage neuron *(Experiment 17)*
18. Passive current-to-voltage bound *(Experiment 18)*
19. Replica-null TIA offset *(Experiment 19)*
20. Current-mode cascade bound *(Experiment 20)*
21. Finite TIA gain is per-neuron *(Experiment 21)*
22. Virtual-ground requirement extraction *(Experiment 22)*
23. Virtual-ground primitive validation *(Experiment 23)*
24. Offset-corrected virtual-ground search *(Experiment 24)*
25. Transient validation of the virtual-ground servo *(Experiment 25)*
26. Device-level MOS neuron primitive on frozen o2 *(Experiment 26)*
27. Matching and temperature of the device-level neuron *(Experiment 27)*
28. Output interface for the CDS-corrected neuron *(Experiment 28)*
29. Resistor-ratio matching and network-scale feasibility *(Experiment 29)*
30. Physical invert primitive and matching-technology search *(Experiment 30)*
31. Hidden-inverter drive requirement and physical output-stage search *(Experiment 31)*
32. Physical low-offset hidden-inverter primitive search *(Experiment 32)*
33. Documented precision-inverter model and PDK gap closure *(Experiment 33)*
34. 32-copy OPA189 residual mechanism and fabric loading isolation *(Experiment 34)*
35. N=32 OPA189 convergence and robustness qualification *(Experiment 35)*
36. Full Network F40 physical hidden-inverter integration *(Experiment 36)*
37. Physical TIA integration and technology-requirement extraction *(Experiment 37)*
38. Semiconductor technology feasibility *(Experiment 38)*
39. First real SKY130 PDK isolated cell (o3; catalog o2 not simulated) *(Experiment 39)*
40. Catalog o2 (W2[1]) on official SKY130A *(Experiment 40)*
41. o2 residual decomposition (finite-A vs PDK R) *(Experiment 41)*
42. o2 1 mV feasibility boundary (gain vs geometry) *(Experiment 42)*
43. Behavioral high-gain + W=10 feasibility demonstration *(Experiment 43)*
44. Physical high-gain TIA requirement extraction *(Experiment 44)*
45. Documented macromodel TIA on W=10 o2 *(Experiment 45)*
46. OPA189 TIA promotion on isolated W=10 o2 *(Experiment 46)*
47. OPA189 catalog o2 TIA in Network F *(Experiment 47)*
48. W=10 SKY130 Miller ± servo *(Experiment 48)*
49. Existing Miller+servo 200 µs transient *(Experiment 49)*
50. Track B inventory and miller A_ol attempt *(Experiment 50)*
51. Offset-nulled miller incremental A_ol *(Experiment 51)*
52. Two-copy miller composite TIA *(Experiment 52)*
53. W=10 tt_mm mismatch at A=1e6 *(Experiment 53)*

Longer-term:

```
trained neural network
        ↓
   "matter compiler"
        ↓
physical circuit topology
        ↓
   electrical signals
        ↓
   physical computation
        ↓
      output
```
