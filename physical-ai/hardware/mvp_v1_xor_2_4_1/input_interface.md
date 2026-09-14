# Input interface

Frozen XOR uses **0 V** and **1.000 V** only.

## Source impedance

Driving `IN1` (example): `Rinv1in = 10 kΩ` plus `Rh1w1 ≈ 8.35 kΩ` to a virtual ground. Effective load is a few kΩ. Use a **stiff source** (op-amp / DAC / switch to VREF/GND), not a 10 kΩ divider without a buffer.

`IN1N` is generated on-board. Do not also drive `IN1N` unless you are substituting the inverter (not recommended for v1).

## Allowable voltage error

| Goal | IN1/IN2 tolerance |
| --- | --- |
| Analog 1 mV vs SPICE | **±0.5 mV** on 1.000 V (0.05%) plus common ground error |
| Classification only | ±20 mV still far from the 0.5 V class threshold |

Common ground with analog GND is mandatory.

## Method A — manual MVP

- SPDT (or DPDT) switch per input: **GND** or **VREF**.
- If VREF is 1.000 V, the 1-state is exactly the bias reference (good).
- Debounce is irrelevant (DC).
- Connector: two switches on the board; test points `TP_IN1` `TP_IN2`.

## Method B — instrumented

- Two lab outputs or DAC channels, 0.000 V / 1.000 V, shared analog GND.
- A PC may set the DAC codes for 00/01/10/11. It must **not** compute the network output and force `TP_O1LIN`.

## Connectors

| Pin | Net |
| --- | --- |
| 1 | IN1 |
| 2 | IN2 |
| 3 | GND |

Optional: IN1N, IN2N as **sense-only** test points.

## What the microcontroller may do

- Close analog switches to GND/VREF.
- Clock a test sequence.
- Read `TP_O1LIN` with an ADC.

It may **not** run `y = W2 · ReLU(W1x+b1)+b2` as a substitute for the analog path.
