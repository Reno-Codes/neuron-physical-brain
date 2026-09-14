# MVP-H1 staged bring-up and test

Do **not** first test a fully stuffed board as a black box.

Voltages below that quote SPICE (frozen netlist, 27 °C, UIC transient 2 ms) are labeled **SPICE**. Hardware is expected to match **sign and rough magnitude**. Do not treat 1 mV agreement as a bring-up gate.

Meter common: `TP_GND`. After every input change wait **≥ 10 ms** (hardware settle: UNKNOWN — HARDWARE TEST REQUIRED).

---

## Stage 0 — continuity and shorts (power off)

**Connected:** nothing powered. Board or module as stuffed for Stage 1 only is ideal.

**Measure:** resistance `J_PWR` +15–GND, −15–GND, +15–(−15).

**Pass:** not a dead short. Op-amp ESD diodes can read a few kΩ on a diode-check; a milliohm beep is a fail.

**Fail:** solder bridge, reversed electrolytic, pin 7 shorted to pin 4.

**Likely causes:** solder, backwards bulk cap, clipped lead.

**Do not proceed** if +15 is shorted to −15 or GND.

---

## Stage 1 — power rails and reference

**Connected:** `J_PWR`, bulk 10 µF, local 100 nF on any stuffed amplifiers, `U_VREFBUF`, 1.000 V source into buffer pin 3. Neural weight resistors may be absent.

**Inputs:** none required. Keep IN1/IN2 at 0 V if already wired.

**Measure:** `TP_P15`, `TP_M15`, supply current, `TP_VREF`.

**Expected (documented hardware targets, not SPICE neural nodes):**

| Node | Expected |
| --- | --- |
| `TP_P15` | +15.0 V ± 0.2 V |
| `TP_M15` | −15.0 V ± 0.2 V |
| Current | typically well under 50 mA at this stage |
| `TP_VREF` | 1.000 V (record actual). Analog goal ± 0.5 mV |

**Pass:** rails in band; current **< 80 mA**; VREF recorded.

**Fail:** rail missing, current ≥ 80 mA, VREF wildly off (e.g. 0 V or 2.5 V unbuffered).

**Likely causes:** polarity, missing GND, buffer not in unity-gain, source not sharing analog GND.

---

## Stage 2 — one OPA189 invert / TIA check (`Xinv1`)

`Xinv1` is a unity inverting amplifier (Rin = Rf = 10 kΩ). It is the safest first neural-path amplifier.

**Connected:** Stage 1 + `Xinv1`, `Rinv1in`, `Rinv1f`, IN1 source.

**Inputs:** IN1 = 0 V, then IN1 = 1.000 V (from VREF or lab). IN2 unused.

**Measure:** `TP_IN1`, `TP_IN1N`, `Xinv1` pin 2 (should be ~0 V).

**Expected (SPICE at 1 V input: IN1N ≈ −1.000 V):**

| IN1 | `TP_IN1N` |
| ---: | --- |
| 0 V | ≈ 0 V |
| 1.000 V | ≈ −1.000 V |

**Pass:** invert error ≲ a few millivolts at 1 V if 0.1% 10 kΩ pair is fitted. Sign must be negative.

**Fail:** output stuck at a rail; output equals +IN1; pin 2 not near 0 V.

**Likely causes:** pin 3 not grounded, Rf open, SOIC rotated 180°, using SOT-23 pin numbers on SOIC.

Optional: repeat with `Xinv2` and `Xinvref` (`TP_VREFN` ≈ −`TP_VREF`).

---

## Stage 3 — hidden linear stage (h2 TIA)

h2 is the neuron that fires on input **01**.

**Connected:** Stage 2 inverters recommended (need `IN1N` for `Rh2w1`) + `Xh2tia`, `Rh2f` 10 kΩ, `Rh2w1` (9.53k\|\|36.1k), `Rh2w2` (203+9.09k), `Rh2b` (105k\|\|180k). Leave h2 ReLU **unstuffed**.

**Inputs:** IN1 = 0 V, IN2 = 1.000 V.

**Measure:** `TP_H2_SUM`, `TP_H2_LIN`.

**Expected (SPICE 01):**

| Node | SPICE |
| --- | ---: |
| `TP_H2_SUM` | ~0 V (tens of nV in SPICE) |
| `TP_H2_LIN` | **−0.925 V** |

**Pass:** `H2_SUM` near 0 V (millivolts, not volts). `H2_LIN` **negative**, order of 1 V.

**Fail:** `H2_LIN` positive on 01; `H2_LIN` at a rail; `H2_SUM` at hundreds of millivolts.

**Likely causes:** `Rh2w2` not on `IN2`; `Rh2w1` not on `IN1N`; Rf open; +IN not GND.

Cross-check input **00**: SPICE `H2_LIN` ≈ **+0.151 V** (positive; ReLU will be off).

---

## Stage 4 — ReLU / rectifier (h2)

**Connected:** Stage 3 + `Xh2relu`, `Xh2d1`, `Xh2d2`, `Rh2r1`, `Rh2rf`, `Rh2rl` (all 10 kΩ). Band = cathode.

**Inputs:** 01, then 00.

**Measure:** `TP_H2_LIN`, `TP_H2_OUT`.

**Expected (SPICE):**

| State | H2_LIN | H2_OUT |
| --- | ---: | ---: |
| 01 | −0.925 V | **+0.925 V** |
| 00 | +0.151 V | ~0 V (SPICE ≈ −3 µV) |

**Pass:** on 01, OUT is **positive** and similar magnitude to |LIN|. On 00, OUT stays near 0 V (not a large negative).

**Fail:** OUT tracks negative LIN; OUT stuck at 0 V on 01; OUT at a rail.

**Likely causes:** diodes reversed; Rf of rectifier open; rectifier op-amp rotated.

---

## Stage 5 — output stage

**Connected:** all hidden neurons through ReLU and hidden inverters (`Xh*inv`), plus `Xo1tia`, `Ro1f` 10 kΩ, `Ro1w1` 9.2k, `Ro1w2` (11.8k\|\|42.7k), `Ro1w3` (57.6k\|\|1.3M), `Ro1w4` (54.9k\|\|835k), `Ro1b` (160k+5.9M). Keep `Ro1b` clean of flux.

**Inputs:** 00 first (both ReLUs off).

**Measure:** `TP_O1_SUM`, `TP_O1LIN`.

**Expected (SPICE 00):**

| Node | SPICE |
| --- | ---: |
| `TP_O1_SUM` | ~0 V |
| `TP_O1LIN` | **1.645 mV** |

**Pass:** SUM near 0 V. `O1_LIN` near 0 V (millivolts), **not** ~1 V and **not** a rail.

**Fail:** `O1_LIN` ≈ 1 V on 00; `O1_LIN` negative several hundred mV; SUM not regulating.

**Likely causes:** a hidden OUT stuck high; `Ro1w1` taken from `H1_OUT` instead of `H1_YN`; VREFN missing.

Then apply 01 without yet calling this the official demo: SPICE `O1_LIN` ≈ **1.002511 V**.

---

## Stage 6 — complete four-input XOR

**Connected:** full neural circuit.

**Inputs:** 00, 01, 10, 11 as physical voltages.

**Measure:** at least IN1, IN2, all H*_LIN, H*_OUT, `TP_O1LIN`. Fill `MVP_H1_MEASUREMENT_LOG_TEMPLATE.csv`.

**Class rule (only this):** `class = 1 if TP_O1LIN ≥ 0.5 V else 0`.

**Pass Level A:** classes 0, 1, 1, 0.

**Pass Level B (stretch):** |O1_LIN − SPICE| ≤ 1 mV on all four. Report MAE/max even if this fails.

**Fail Level A:** any class wrong.

**Likely causes:** see `debugging_guide.md`. 01 depends on h2; 10 depends on h1.

Official procedure: `MVP_H1_DEMO_PROTOCOL.md`.
