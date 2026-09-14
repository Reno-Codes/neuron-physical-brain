# Reference voltage

SPICE used an **ideal** `Vref vref 0 DC 1`. That is a **hardware validation boundary**.

## What VREF does

Bias conductances (`Rh1b` … `Rh4b`, `Ro1b`) and the inverted reference `VREFN = −VREF` (`Xinvref`).

Load on `VREF`: essentially `Rinvrefin = 10 kΩ` into a virtual ground → **100 µA**.

`VREFN` sources/sinks the bias resistor currents (~0.1 mA). `Xinvref` must be stable with that load.

## Accuracy

A VREF error scales every bias.

Worst hidden |b1| ≈ 0.44, so 0.1% VREF error ≈ **0.44 mV** on that pre-activation, before resistor error. The analog bar is 1 mV on the **output**, which is a weighted sum of ReLUs. Conservative target:

| Spec | Requirement |
| --- | --- |
| DC value | **1.000 V** |
| Initial accuracy | **±0.05%** (±0.5 mV) preferred for analog-accurate MVP |
| Class-only floor | ±10 mV still leaves huge margin to 0.5 V |
| Drift | **UNKNOWN — HARDWARE TEST REQUIRED**; aim ≤ 25 ppm/°C |
| Noise | keep 0.1–10 Hz well below 100 µV if doing analog 1 mV tests |
| Drive | buffered; do not hang the 10 kΩ inverter on a high-Z divider |

## Physical options (electrical spec, not a guaranteed cart line)

1. **Preferred:** precision 2.500 V reference (0.05% class, TI REF50xx family or equivalent) → 15 kΩ/10 kΩ 0.05% divider → **OPA189 buffer** as `VREF`. Buffer is an extra amplifier, not part of the frozen 16. Document it as `U_VREFBUF`.
2. Direct 1.000 V reference IC if a 0.05% (or better) 1.000 V part is **verified in a distributor catalog**. **PROCUREMENT VERIFICATION REQUIRED.**
3. Calibrated lab calibrator into `TP_VREF` for the first bring-up. Allowed. Still not a software neural net.

Do **not** trim neural weight resistors to chase VREF error. If you calibrate, calibrate **VREF** (and record it). That does not change frozen weights.

## `VREFN`

Must come from the compiled inverter (`Rinvrefin`, `Rinvreff`, `Xinvref`), not from a second DAC computing −1. Using a DAC to emit −1 V would still be analog stimulus, not a neural forward pass, but it would **bypass a compiled block**. First MVP: build the inverter.

Expect `TP_VREFN` ≈ −1.000 V. |error| similar to invert matching (10 kΩ 0.1% pair).
