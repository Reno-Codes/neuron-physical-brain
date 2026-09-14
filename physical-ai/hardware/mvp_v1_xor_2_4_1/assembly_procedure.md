# Assembly procedure

Do not apply ±15 V to a fully stuffed untested board as the first act. Staged stuffing on the hierarchical PCB.

Pass voltages are vs `TP_GND`. 27 °C, SPICE column is the analog target.

## Stage 0 — inspect

- Hashes: `FROZEN_PROVENANCE.json` still matches `physical_design/xor_2_4_1/` if you have the original tree.
- Resistors: values from `resistor_implementation.csv`, not coarse E96 snaps.
- Op-amp orientation vs TI datasheet.
- No 1 pF neural caps fitted.

## Stage 1 — power rails

**Connect:** only bulk caps, optionally one unstuffed socket. No inputs required.

**Measure:** `TP_P15`, `TP_M15`, supply current.

**Pass:** +15.0 / −15.0 V ± 0.2 V, Iq of empty board ≈ 0 plus leakage.

**Fail:** short, reversed banana, wrong PSU polarity.

## Stage 2 — reference

**Connect:** VREF circuit + `U_VREFBUF` if used. Still no neural resistors required.

**Measure:** `TP_VREF`.

**Pass:** 1.000 V ± 0.5 mV (analog goal) or record actual value.

**Fail:** divider/buffer. Do not proceed to biases with a wild VREF.

## Stage 3 — input generation

**Connect:** switches or DAC to `IN1` `IN2`.

**Measure:** `TP_IN1` `TP_IN2` for 00, 01, 10, 11.

**Pass:** 0.000 V or 1.000 V as commanded.

## Stage 4 — signed / inverted signals

**Stuff:** `Xinv1` `Xinv2` `Xinvref` and their 10 kΩ pairs. Power + VREF + inputs.

**Measure:** `TP_IN1N` ≈ −IN1, `TP_IN2N` ≈ −IN2, `TP_VREFN` ≈ −1.000 V. Invert summing nodes ~0 V.

**Pass:** invert error ≲ 1 mV at 1 V if 0.1% 10 k matched.

**Fail:** swapped IN+/IN−, missing Rf, rail stuck.

## Stage 5 — one hidden neuron linear (h2 is easiest for a “1” on state 01)

**Stuff:** h2 TIA only (`Xh2tia`, `Rh2f`, `Rh2w1`, `Rh2w2`, `Rh2b`). Leave rectifier unstuffed if you can probe `H2_LIN`.

**Set:** IN = 01 (IN1=0, IN2=1).

**Expect:** `TP_H2_LIN` ≈ **−0.925 V**, `TP_H2_SUM` ≈ 0.

**Pass:** within a few mV of SPICE on first bring-up; investigate if sign is wrong.

**Fail:** wrong signed source (w+ vs w− swapped), Rf open, IN+ not grounded.

## Stage 6 — one activation

**Stuff:** h2 rectifier (`Xh2relu`, `Xh2d1`, `Xh2d2`, `Rh2r1`, `Rh2rf`, `Rh2rl`).

**Set:** 01. **Expect:** `TP_H2_OUT` ≈ **+0.925 V**.
**Set:** 00. **Expect:** `TP_H2_OUT` ≈ **0 V** (few mV leakage).

**Pass:** ReLU polarity correct (positive only).

**Fail:** diodes reversed; output follows `H2_LIN` negative → clamp/forward swapped.

## Stage 7 — all hidden neurons

Stuff h1, h3, h4 the same way. Use `test_point_map.md`. Remember: h3 and h4 **OUT ≈ 0** on all XOR states; their **LIN is positive**.

## Stage 8 — output neuron

**Stuff:** `Xo1tia`, `Ro1f`, `Ro1w1`…`Ro1w4`, `Ro1b`, hidden inverters `Xh*inv`.

**Measure:** `TP_O1_SUM` ≈ 0, `TP_O1LIN` on 00 should already be ~1.6 mV if hiddens are off.

## Stage 9 — XOR inference

All four states. Record analog and class. See `hardware_acceptance_test.md`.
