# MVP-H1 purchase gate

Status of the **design** is unchanged:

```text
SIMULATION VALIDATED
→
HARDWARE BUILD READY
→
HARDWARE NOT YET TESTED
```

This file is procurement only. Frozen netlist SHA-256 (re-checked):

`28dccd8121a1032d69a2b08633737db0b2f10c8996f68ed2271520ec58c3b9cb`

Do not buy from `physical_design/xor_2_4_1/BOM.csv` (E96 snaps). Buy electrical values from `MVP_H1_PURCHASE_RESISTORS.csv` and `MVP_H1_PURCHASE_BOM.csv`.

---

## SAFE TO PURCHASE NOW

Identity is documented. **Confirm live stock and packaging** at Texas Instruments or an authorized distributor before checkout.

| Item | Official identity | Qty to buy | Evidence |
| --- | --- | ---: | --- |
| Neural + VREF op-amps | **Texas Instruments `OPA189ID`** (SOIC-8 tube) or **`OPA189IDR`** (SOIC-8 reel) | **20** (17 stuffed + 3 spare) | TI SBOS830 Rev I orderable table: Active / Production / SOIC (D) 8-pin |

Do **not** buy `OPA189IDBVR` / `OPA189IDBVT` (SOT-23-5). That package does not match the SOIC pin map in `opa189_pinout.md` or `MVP_H1_CONNECTION_TABLE.csv`.

Do **not** substitute another amplifier because OPA189 is temporarily out of stock. That is a **procurement blocker**, not a redesign trigger.

Bench equipment you may already own (not stuffed BOM):

| Item | Spec |
| --- | --- |
| Dual tracking supply | +15 V / GND / −15 V, **≥ 100 mA per rail headroom** |
| Calibrated DMM | ≥ 5.5 digit preferred for analog; required for VREF measurement |
| 1.000 V source | Calibrated lab output into `U_VREFBUF` (preferred first demo) |

The 100 mA rating is **headroom** (Iq max, extra buffer, fault, oscillation). SPICE drew ~22 mA/rail. That is **not** a promise of hardware current and is **not** a target the circuit should consume.

---

## VERIFY BEFORE PURCHASE

These have a complete **electrical spec**. A cart-line SKU was **not** live-verified in this repository. Status: `UNVERIFIED — DO NOT PURCHASE YET` until you match the spec at a distributor and write the MPN on your copy of the CSV.

### 0.1% resistors (60 stuffed + ~64 kit spares)

- Thin-film 0.1%, ≤ 25 ppm/°C preferred, 0805 or 1206, 50 V, 0.1 W min
- Values: `resistor_shopping.csv` / `MVP_H1_PURCHASE_RESISTORS.csv`
- All 48 compiled functions realize the frozen ohm within **0.1%** (worst combination error **0.067%** on `Rh4w2` 31.6 kΩ vs 31621 Ω)
- Implementation is single / series / parallel E192 — **not** Experiment 67 coarse E96
- No manufacturer reel codes are claimed here

### 1N4148 (8 stuffed + 8 spare)

- JEDEC **1N4148** switching diode
- Prefer **DO-35** axial for the first board: **body band = cathode**
- Ratings on manufacturer datasheets (Vishay / Nexperia / Diodes Inc.): typically VR 75–100 V, IF hundreds of mA — far above this circuit’s current
- Official manufacturer order examples exist on those datasheets (Vishay lists `1N4148-TAP` / `1N4148TR`; Diodes Inc. lists `1N4148-T`). **Confirm the exact in-stock orderable yourself.**
- SOD-123 `1N4148W` is the same diode family but **package pin 1 is often the cathode**. Our SPICE pin 1 is anode. If you buy SMT, follow the **band**, not the SPICE pin number.

### Hardware-only passives and mechanics

- 2× 10 µF ≥ 35 V bulk (+ 2 spare)
- 34× 100 nF X7R ≥ 50 V 0805 (+ ~6 spare)
- SPDT switches, `J_PWR`, optional `J_IN`, 27 test points

### Onboard 1.000 V IC (only if you refuse a lab calibrator)

- Electrical goal: **1.000 V ± 0.05%**, buffered by `U_VREFBUF`
- No reference IC SKU is verified in project evidence
- Do not treat a cheap uncalibrated “1 V board” as VREF

---

## DO NOT PURCHASE

| Item | Why |
| --- | --- |
| Frozen compiler `BOM.csv` E96 weight/bias values | Experiment 67: class OK, analog error up to ~30 mV |
| E96 **6.04 MΩ** as `Ro1b` | Nearest-E96 of 6.059 MΩ; analog-accurate path uses 160 kΩ + 5.9 MΩ 0.1% |
| Frozen 1 pF `Cinv1`…`Co1tia` | Class C, DNP |
| `OPA189` SOT-23 while using the SOIC connection table | Different pinout |
| A different op-amp “because it is in stock” | No substitution analysis; report blocker instead |
| Uncalibrated USB/module “1 V” as VREF | SPICE VREF was ideal; hardware VREF must be measured |
| Solderless-breadboard “kits” as the analog-accurate build | Rejected in `MVP_H1_LAYOUT_SPEC.md` |

---

## OPA189 (Task 4)

| Check | Result |
| --- | --- |
| Required package for this wiring table | **SOIC-8 (D)** |
| Official MPN | `OPA189ID` / `OPA189IDR` (SBOS830 Rev I) |
| Pinout | pin 2 −IN, 3 +IN, 4 V−, 6 OUT, 7 V+; NC 1/5/8. **Not 741.** |
| Supply | 4.5 V to 36 V; this design uses ±15 V (30 V). Abs max: do not exceed ±18 V |
| Input | Includes the **negative** rail; virtual grounds at 0 V are legal |
| Output | Rail-to-rail; XOR nodes stay near 0–1 V |
| Iq | typ 1.3 mA, max 1.7 mA at 25 °C; max 1.8 mA over −40 to 125 °C |
| Live distributor qty | **Not checked** — confirm before paying |
| Substitute | **Do not.** Unavailability is a purchase blocker |

---

## 1N4148 (Task 5)

| Check | Result |
| --- | --- |
| Type | JEDEC 1N4148 |
| Polarity | Band / bar = **cathode** = SPICE pin 2 |
| Voltage/current | 75–100 V / hundreds of mA class — adequate |
| Preferred package | DO-35 |
| SMT alternative | 1N4148W SOD-123 only if you obey the band |
| Cart SKU | `UNVERIFIED — DO NOT PURCHASE YET` until you pick an in-stock official 1N4148 |

---

## Power (Task 6)

SPICE |i(Vdd)| / |i(Vss)| ≈ **21–22 mA** at 27 °C on the frozen netlist. That is a macromodel number, **not** guaranteed hardware current.

**≥ 100 mA per rail** is specified so that:

- 17 × 1.7 mA max Iq ≈ 29 mA, plus load and a fault
- a shorted output or oscillation does not fold the bench supply into an undervoltage mess on first power-up
- you have margin if real Iq exceeds the macromodel

The circuit is **not** designed to draw 100 mA. Stage 1 **fail** if idle current **> 80 mA**.

---

## Reference (Task 7)

SPICE: ideal `Vref = 1 V`.

| Item | Requirement |
| --- | --- |
| DC | 1.000 V |
| Analog goal | ±0.05% (±0.5 mV) |
| Drive | **Buffered** (`U_VREFBUF` unity follower). Do not hang 10 kΩ invert + bias network on a high-Z divider |
| Measure | Calibrated DMM on `TP_VREF` vs `TP_GND`; record the number |
| Calibrate | Adjust the **source**, not the neural resistors |
| First demo | Lab calibrator → buffer pin 3 → `TP_VREF` |

An unverified generic “1 V source” must not silently become VREF.

---

## Ro1b ≈ 6.06 MΩ (Task 3)

| Item | Value |
| --- | --- |
| Frozen target | **6 059 355.216 664 54 Ω** (`vrefn` → `o1sum`, b2 ≈ +0.001650) |
| Implementation | **Series** 160 kΩ + 5.9 MΩ, both 0.1% thin film |
| Resistor count | **2** (`Ro1b_A`, `Ro1b_B`) |
| Effective | **6 060 000 Ω** |
| Combination error | **0.0106%** (inside 0.1%) |
| Rejected E96 | 6.04 MΩ — do not buy |
| Role | Sets the ~1.65 mV class-0 floor. 1% of Ro1b ≈ 16 µV on `O1_LIN` |
| Technology | Thin film 0.1% is appropriate; carbon/thick-film leaky parts are not |
| Leakage | **Material for analog millivolts, not for Level A class.** 10 MΩ of flux/PCB leakage across Ro1b would pull the combination down by tens of percent and move the floor by ~0.6 mV. 1 MΩ leakage is a real analog error |
| Layout | Keep pads clean; wash flux; soldermask between pads; no breadboard; optional GND guard ring around `o1sum` / `Ro1b`; do not run ±15 V across those pads |

Do **not** replace this series pair with a pot or a different topology. If 5.9 MΩ 0.1% is unobtainable, that is a **purchase blocker** for analog-accurate stuffing — not a license to E96-snap or trim a weight.

---

## Remaining procurement blockers

1. Live stock of `OPA189ID` / `OPA189IDR` not confirmed in this audit.
2. Every 0.1% resistor reel MPN is unverified.
3. 1N4148 cart SKU unverified (type is specified).
4. Decoupling / bulk capacitor SKUs unverified.
5. Onboard 1.000 V IC SKU unverified (lab source avoids this).

None of these is a neural-design blocker. They are **checkout** blockers until you match the spec on a distributor page.
