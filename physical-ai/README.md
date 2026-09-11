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
