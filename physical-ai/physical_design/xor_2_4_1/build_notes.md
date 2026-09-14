# Build notes

This is a hybrid PCB/discrete analog prototype, not an ASIC.

- Use the exact `R_exact_ohm` values in SPICE.
- Experiment 67: nearest-E96 weight/bias snap keeps XOR **class** but
  misses the 1 mV analog bar (worst 29.9 mV). First analog-accurate board:
  0.1% or selected exact R, not coarse E96.
- Do not replace the analog MAC or ReLU with firmware.
- Unre-sized SKY130 Miller TIA family is closed; this compile uses OPA189.
- Do not call this silicon.

## Validated mixed-level range (Experiments 64-66)

- Analog |y − y_ref| ≤ 1 mV on frozen XOR: **−40 °C to 70 °C** (27 °C MAE 9 µV).
- 85 °C: classification still 4/4; analog misses ~1.08 mV on the high outputs.
- Discrete resistors in SPICE have **no TCR card** (not invented). Temperature
  enters through the OPA189 and 1N4148 macromodels only.
- Full-netlist **OP is stiff**. Validation used UIC TRAN 2 ms (power-on settle).

## Assembly

- 16× OPA189 (or 4× OPA4189) on ±15 V.
- 8× 1N4148 (two per hidden ReLU).
- Precision 1.000 V bias reference.
- Ground the unused OPA189 inputs if using quads.

## What the microcontroller / PC may do

- Drive `in1`, `in2` as 0 V or 1 V.
- Read `v(o1lin)` with an ADC or compare to 0.5 V.
- It must not compute `y = W2 ReLU(W1x+b1)+b2`.
