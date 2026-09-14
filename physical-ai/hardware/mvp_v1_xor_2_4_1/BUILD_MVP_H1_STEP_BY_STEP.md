# Build MVP-H1 — step by step

This is the **single human build path** for Physical AI MVP v1 (hardware revision MVP-H1).

You are building a physical analog circuit that implements the frozen network:

**2 inputs → 4 ReLU hidden neurons → 1 linear output**

The neural multiply-accumulate and ReLU happen in resistors, OPA189 amplifiers, and 1N4148 diodes. A computer may set input voltages and read the output voltage. It must **not** compute the network equation in place of the circuit.

Do not use `physical_design/xor_2_4_1/BOM.csv` to buy resistors. That file lists nearest E96 values. Experiment 67 showed coarse E96 keeps XOR class but misses analog accuracy (up to ~30 mV). Buy from `MVP_H1_FINAL_BOM_AUDITED.csv` and `resistor_shopping.csv`.

**Ordering from Croatia:** open `MVP_H1_CLICK_TO_BUY.csv` — every row is a product page (Farnell.de + Reichelt.de). How-to: `MVP_H1_CROATIA_BUY_LIST.md`.

Wiring authority: `MVP_H1_CONNECTION_TABLE.csv`.  
Package pins: `opa189_pinout.md` (Texas Instruments SBOS830). The SVG drawings are hierarchy only — **not** pin numbers.

Default first build: **16× OPA189 in SOIC-8 (D)** plus one extra OPA189 as the 1.000 V buffer. If you use OPA4189 quads instead, follow `opa189_pinout.md` and do not mix SOIC-8 numbers onto a quad.

---

## 1. Tools

| Tool | Why |
| --- | --- |
| Dual tracking bench supply, ±15 V, ≥ 100 mA per rail | Analog rails |
| Digital multimeter, ≥ 5.5 digit preferred | Analog checks; 3.5 digit is enough for class |
| Oscilloscope (1× or 10× probe) | Oscillation / settling |
| Soldering iron, fine tip, flux remover | Assembly |
| ESD-safe workstation | CMOS/BiCMOS op-amps |
| Calibrated 1.000 V source **or** a verified 0.05%-class reference chain | VREF (SPICE used an ideal 1 V) |
| Optional: two-channel DAC | Instrumented IN1/IN2 |
| Optional: tweezers, microscope, continuity buzzer | SMT / shorts |

Do **not** use a solderless breadboard for the analog-accurate board (`MVP_H1_LAYOUT_SPEC.md`).

---

## 2. Power supplies

| Rail | Voltage | Current budget | Connector |
| --- | ---: | ---: | --- |
| VDD | **+15.0 V** | ≥ 100 mA | `J_PWR` +15 |
| GND | **0 V** analog | — | `J_PWR` GND |
| VSS | **−15.0 V** | ≥ 100 mA | `J_PWR` −15 |

SPICE current on the frozen netlist at 27 °C is about **21–22 mA per rail**. TI SBOS830 lists OPA189 Iq typical **1.3 mA**, max **1.7 mA** at 25 °C (max 1.8 mA over temperature) **per amplifier**. 17 amplifiers (16 neural + buffer) plus load: plan **≥ 100 mA/rail**.

Do not power this circuit from USB 5 V. Do not run it single-supply.

---

## 3. How ±15 V and ground are connected

1. Connect bench GND to `J_PWR` GND (`TP_GND`). All meter commons use `TP_GND`.
2. Connect +15 V to `J_PWR` +15 (`TP_P15`).
3. Connect −15 V to `J_PWR` −15 (`TP_M15`).
4. Fit `C_VDD_BULK` 10 µF ≥ 35 V from +15 to GND at the connector.
5. Fit `C_VSS_BULK` 10 µF ≥ 35 V from −15 to GND at the connector.
6. Fit **100 nF X7R ≥ 50 V** from each OPA189 pin 7 (V+) to GND and pin 4 (V−) to GND, within 5 mm of the package.

Every OPA189 pin 3 (+IN) in the neural netlist is **ground** except the VREF buffer (pin 3 receives 1.000 V).

---

## 4. How the 1.000 V reference is generated and verified

SPICE used an **ideal** 1 V source. That is a hardware boundary.

**First demonstration (recommended):** a calibrated lab 1.000 V source into `U_VREFBUF` pin 3 (+IN). Strap pin 2 (−IN) to pin 6 (OUT). Pin 6 is **VREF**. Measure `TP_VREF`.

**Onboard option (if you do not use a lab source):** a 0.05%-class 2.500 V reference, 15 kΩ / 10 kΩ 0.05% divider, then the same OPA189 buffer. Exact IC SKUs: **PROCUREMENT VERIFICATION REQUIRED**. Do not invent a part number.

**Pass (analog goal):** `TP_VREF` = 1.000 V ± 0.5 mV.  
**Class-only floor:** even ±10 mV still leaves margin to the 0.5 V class threshold — still record the actual value.

`Xinvref` then makes **VREFN ≈ −1.000 V** at `TP_VREFN`. Do not substitute a second DAC as −1 V on the first build; build the inverter.

Do **not** trim neural resistors to chase VREF error. If you calibrate, calibrate VREF.

---

## 5. How IN1 and IN2 are applied

Only two legal input voltages: **0 V** and **1.000 V**.

**Manual:** SPDT `SW_IN1` / `SW_IN2`: common → `TP_IN1` / `TP_IN2`; throws to GND or VREF.

**Instrumented:** two lab outputs or DAC channels, same analog GND, 0.000 V or 1.000 V. A PC may select 00/01/10/11. It must not compute the network output.

The inputs drive several kilohms into virtual grounds. Use a **stiff** source (switch to VREF/GND or a buffered DAC), not a high-Z divider.

---

## 6. Every required component

Buy from `MVP_H1_FINAL_BOM_AUDITED.csv`. From Croatia, click the product pages in `MVP_H1_CLICK_TO_BUY.csv`. Summary:

| What | Qty stuffed | Notes |
| --- | ---: | --- |
| OPA189 SOIC-8 | 17 | 16 neural + `U_VREFBUF` |
| 1N4148 | 8 | two per hidden ReLU |
| 0.1% thin-film resistors | 60 | 48 compiled functions; 12 are two-part series/parallel |
| 10 µF ≥ 35 V | 2 | bulk rails |
| 100 nF X7R ≥ 50 V | 34 | one pair per op-amp package |
| SPDT switches | 2 | omit if DAC |
| Power connector | 1 | +15 / GND / −15 |
| Test points | 27 | include **`TP_O1LIN`** |
| 1.000 V source | 1 | lab or verified reference chain |
| Frozen 1 pF caps | **0** | do not place |

Manufacturer reel numbers are **PROCUREMENT VERIFICATION REQUIRED**.

---

## 7–8. Exact resistor values and tolerance

Tolerance for all neural and invert/TIA 10 kΩ parts: **0.1%** (or a measured/selected part that realizes the compiled ohm within 0.1%). TCR ≤ 25 ppm/°C preferred. Package 0805 or 1206, 50 V, 0.1 W min.

| Compiled ref | Exact target (Ω) | Stuff as | Physical parts |
| --- | ---: | --- | --- |
| All invert / TIA Rf / ReLU 10 kΩ (31 refs) | 10000 | single 10 kΩ 0.1% | 10k |
| Rh1w1 | 8346.153 | single | 8.35k |
| Rh1w2 | 6653.681 | single | 6.65k |
| Rh1b | 37976.812 | series | 976 + 37k |
| Rh2w1 | 7539.646 | parallel | 9.53k \|\| 36.1k |
| Rh2w2 | 9292.757 | series | 203 + 9.09k |
| Rh2b | 66315.561 | parallel | 105k \|\| 180k |
| Rh3w1 | 5125.484 | parallel | 6.73k \|\| 21.5k |
| Rh3w2 | 7679.433 | single | 7.68k |
| Rh3b | 25915.697 | parallel | 34k \|\| 109k |
| Rh4w1 | 25650.221 | series | 750 + 24.9k |
| Rh4w2 | 31621.294 | single | 31.6k |
| Rh4b | 22716.415 | parallel | 41.7k \|\| 49.9k |
| Ro1w1 | 9197.822 | single | 9.2k |
| Ro1w2 | 9245.047 | parallel | 11.8k \|\| 42.7k |
| Ro1w3 | 55155.970 | parallel | 57.6k \|\| 1.3M |
| Ro1w4 | 51512.428 | parallel | 54.9k \|\| 835k |
| Ro1b | 6059355.217 | series | 160k + 5.9M |

Series: `_A` then `_B` in series between the compiled nodes. Parallel: both parts between the same two nodes. Full pin list: `MVP_H1_CONNECTION_TABLE.csv`.

No potentiometers on weights.

---

## 9. OPA189 orientation and pin mapping (SOIC-8 D)

Pin 1 is the **dot / notch** end (TI SBOS830). This is **not** a 741.

| Pin | Name | Typical neural connection |
| ---: | --- | --- |
| 1 | NC | float |
| 2 | −IN | summing / invert node |
| 3 | +IN | GND (neural amps) |
| 4 | V− | −15 V |
| 5 | NC | float |
| 6 | OUT | labeled node (`IN1N`, `H1_LIN`, …) |
| 7 | V+ | +15 V |
| 8 | NC | float |

`U_VREFBUF` pin 3 = 1.000 V raw, pin 2 tied to pin 6.

SOT-23-5 pin numbers are different. Do not use this table on SOT-23.

---

## 10. 1N4148 orientation

SPICE and hardware: **pin 1 = anode**, **pin 2 = cathode**.

On a physical diode the **band / bar is the cathode**.

Per hidden neuron (example h1):

| Diode | Anode | Cathode |
| --- | --- | --- |
| Xh1d1 | rectifier −IN (`h1rinn`) | rectifier op-amp output (`h1amp`) |
| Xh1d2 | `h1amp` | ReLU output `H1_OUT` (`h1y`) |

Repeat for h2, h3, h4. If `H*_OUT` follows a **negative** `H*_LIN`, the diodes are almost certainly reversed.

---

## 11. Major nodes (what they mean)

| Board name | Meaning |
| --- | --- |
| +15 / GND / −15 | analog supplies |
| VREF | +1.000 V bias |
| VREFN | −VREF |
| IN1, IN2 | physical inputs 0 V or 1.000 V |
| IN1N, IN2N | −IN1, −IN2 |
| H1_SUM … H4_SUM, O1_SUM | TIA virtual grounds; should stay near 0 V |
| H1_LIN … H4_LIN | hidden **linear** voltages = **−z** (sign-flipped pre-activation) |
| H1_OUT … H4_OUT | ReLU outputs; only h1 fires on input 10, only h2 on input 01 |
| H1_YN … H4_YN | −(ReLU) |
| **O1_LIN / TP_O1LIN** | **neural analog output** |

h3 and h4 **do not fire** on this frozen XOR. Their LIN nodes still go **positive**. That is normal.

---

## 12. Where to put the meter or scope

Meter common: **`TP_GND`**.

| What you are checking | Probe |
| --- | --- |
| Rails | `TP_P15`, `TP_M15` |
| Reference | `TP_VREF`, `TP_VREFN` |
| Inputs | `TP_IN1`, `TP_IN2`, `TP_IN1N`, `TP_IN2N` |
| One hidden neuron | `TP_H*_SUM`, `TP_H*_LIN`, `TP_H*_OUT` |
| **XOR result** | **`TP_O1LIN`** |
| Oscillation | scope on `TP_O1LIN` (not on a SUM node unless investigating) |

Do not park a high-C probe on `H*_SUM` during a demo.

---

## 13. What must pass before you proceed

Follow `MVP_H1_BRINGUP_AND_TEST.md`. Do not apply ±15 V to a fully stuffed, untested board as the first act.

Minimum gates:

1. No rail-to-rail shorts (power off).
2. Rails +15.0 / −15.0 V ± 0.2 V, idle current not wild.
3. `TP_VREF` recorded and sane.
4. One invert (`IN1N ≈ −IN1`) before stuffing all hidden neurons.
5. One hidden linear (h2 on input 01) before all ReLUs.
6. One ReLU (h2) before the output TIA.
7. Then four-state XOR on `TP_O1LIN`.

---

## 14. Staged assembly order

Stuff and power in this order (details and numbers in the bring-up file):

0. Inspect parts and orientation. Confirm you did **not** buy E96 snaps of the weight resistors.
1. Power connector, bulk caps, one empty op-amp footprint if you want a socket check.
2. VREF buffer and 1.000 V source.
3. Input switches or DAC.
4. `Xinv1`, `Xinv2`, `Xinvref` and their 10 kΩ pairs.
5. Hidden h2 TIA only (`Xh2tia`, `Rh2f`, `Rh2w1` pair, `Rh2w2` pair, `Rh2b` pair).
6. Hidden h2 ReLU diodes and resistors.
7. Remaining hidden neurons the same way.
8. Hidden inverters + output TIA (`Xo1tia`, `Ro1f`, `Ro1w*`, `Ro1b` series).
9. Four-state demonstration (`MVP_H1_DEMO_PROTOCOL.md`).

---

## 15. Expected voltage ranges (from SPICE, 27 °C)

These are **SPICE** numbers from the frozen netlist (UIC transient 2 ms). Hardware will differ. Use them as sign/magnitude guides, not as a promise of 1 mV.

| State | IN1 | IN2 | H2_LIN | H2_OUT | H1_LIN | H1_OUT | O1_LIN | Class if O1_LIN ≥ 0.5 V |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 00 | 0 | 0 | +0.151 V | ~0 | +0.263 V | ~0 | 1.645 mV | 0 |
| 01 | 0 | 1 | **−0.925 V** | **+0.925 V** | +1.766 V | ~0 | 1.002511 V | 1 |
| 10 | 1 | 0 | +1.477 V | ~0 | **−0.935 V** | **+0.935 V** | 1.018006 V | 1 |
| 11 | 1 | 1 | +0.401 V | ~0 | +0.568 V | ~0 | 1.645 mV | 0 |

H3_OUT and H4_OUT stay ~0 V on all four states. Full table: `simulation_baseline.md`.

Wait **≥ 10 ms** after changing inputs (SPICE used 2 ms; hardware settle is not guaranteed).

---

## 16. Safe power-up

1. Inputs at 0 V (or disconnected). VREF source off or at 0 V.
2. Confirm `J_PWR` polarity with a meter **before** enabling the supply.
3. Enable GND connection.
4. Enable +15 V and −15 V **together** if the supply can track.
5. Confirm `TP_P15` / `TP_M15` and current **< 50 mA** typical at this stage; **stop if > 80 mA**.
6. Enable VREF. Confirm `TP_VREF`.
7. Apply IN1/IN2 only after the stage you are testing is stuffed.

---

## 17. Safe shutdown

1. Set IN1 and IN2 to 0 V.
2. Disable the 1.000 V source (if separate).
3. Disable +15 V and −15 V together.
4. Then disconnect cables. Do not leave one rail on.

---

## 18. Troubleshooting from voltages

Walk **rails → VREF → inputs → inverts → H*_SUM → H*_LIN → H*_OUT → O1_LIN**.

| Symptom | Likely cause |
| --- | --- |
| Current > 80 mA immediately | Rail short, reversed package, missing Rf, oscillation |
| All outputs near ±13–15 V | +IN not grounded, Rf open, rails swapped on one chip |
| `IN1N` not ≈ −IN1 | Xinv1 backwards, 10 k pair mismatch, missing Rf |
| H2_LIN positive on input 01 | Signed resistor on the wrong source (`in2` vs `in2n`) |
| H2_OUT negative | Diodes reversed |
| 01 wrong, 10 correct | Debug **h2 only** |
| 10 wrong, 01 correct | Debug **h1 only** |
| Class 00/11 not near 0 V | Output TIA or `Ro1b` leakage / wrong VREFN |
| Oscillation on O1_LIN | Missing 100 nF, long SUM wire, probe on SUM |
| Analog far from SPICE, class still XOR | Possible E96 snap or 0.1% not fitted — still Level A if class is 4/4 |

More paths: `debugging_guide.md`.

---

## What you must not do

- Compute `y = W2 · ReLU(W1 x + b1) + b2` and call that the circuit result.
- Implement XOR in firmware/logic and OR it with the analog bit.
- Place the 16 frozen 1 pF capacitors.
- Change compiled resistor mappings to “make layout easier.”
- Edit `physical_design/xor_2_4_1/`.
