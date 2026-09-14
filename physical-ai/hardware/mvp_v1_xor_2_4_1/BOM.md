# BOM — Physical AI MVP v1 (hardware revision MVP-H1)

Line items: `BOM.csv` (one row per stuffed part, plus DNP 1 pF).

Electrical values for neural resistors are the **frozen compiled ohms**. Realizations: `resistor_implementation.csv`. Unique kit: `resistor_shopping.csv`.

Do **not** invent cart-line SKUs. Where a standard family is named, verify stock. Mark remaining buys:

`PROCUREMENT VERIFICATION REQUIRED`

Frozen compiler `physical_design/xor_2_4_1/BOM.csv` lists E96 *nearest* values as a compiler dump. **Do not buy those E96 snaps for analog-accurate MVP** (Experiment 67). This hardware BOM supersedes that for purchasing.

## Active / analog

| Ref | Qty | Value / function | Tol | V | P | Package | MPN | Alt | Notes |
| --- | ---: | --- | --- | --- | --- | --- | --- | --- | --- |
| `Xinv1` … `Xo1tia` | 16 (or 4 quads) | OPA189 zero-drift op-amp | — | ±15 V | — | SOIC-8 (D) or OPA4189 SOIC-14 | TI OPA189 / OPA4189 family. **PROCUREMENT VERIFICATION REQUIRED** | OPA2189 duals (8 packages) | Pinout: `opa189_pinout.md` / TI SBOS830. **Not 741 pinout.** Mixed-level host in SPICE, not custom MOS. |
| `U_VREFBUF` | 1 | OPA189 buffer for 1.000 V | — | ±15 V | — | SOIC-8 | same family | — | Extra vs frozen 16. Hardware-only. |
| `U_VREF` | 1 | 1.000 V reference chain | ±0.05% goal | — | — | — | **PROCUREMENT VERIFICATION REQUIRED** | 2.5 V 0.05% ref + 15k/10k 0.05% + buffer | SPICE Vref was ideal. See `reference_voltage.md`. |
| `Xh1d1` … `Xh4d2` | 8 | 1N4148 | — | 75 V class | — | SOD-123 or DO-35 | 1N4148 family. **PROCUREMENT VERIFICATION REQUIRED** | 1N4148WS | Anode→cathode as `schematic_connectivity.md`. |

## Neural resistors — unique 0.1% E192 kit

Minimum stuffed count = 60 physical 0.1% parts (48 compiled functions; 12 are two-element series/parallel). Buy extras as `qty_buy_suggested` in `resistor_shopping.csv`.

| E192 value | Min qty | Used as |
| --- | ---: | --- |
| 10 kΩ | 31 | all invert / TIA Rf / ReLU 10 kΩ |
| 203 Ω | 1 | `Rh2w2_A` |
| 750 Ω | 1 | `Rh4w1_A` |
| 976 Ω | 1 | `Rh1b_A` |
| 6.65 kΩ | 1 | `Rh1w2` |
| 6.73 kΩ | 1 | `Rh3w1_A` |
| 7.68 kΩ | 1 | `Rh3w2` |
| 8.35 kΩ | 1 | `Rh1w1` |
| 9.09 kΩ | 1 | `Rh2w2_B` |
| 9.2 kΩ | 1 | `Ro1w1` |
| 9.53 kΩ | 1 | `Rh2w1_A` |
| 11.8 kΩ | 1 | `Ro1w2_A` |
| 21.5 kΩ | 1 | `Rh3w1_B` |
| 24.9 kΩ | 1 | `Rh4w1_B` |
| 31.6 kΩ | 1 | `Rh4w2` |
| 34 kΩ | 1 | `Rh3b_A` |
| 36.1 kΩ | 1 | `Rh2w1_B` |
| 37 kΩ | 1 | `Rh1b_B` |
| 41.7 kΩ | 1 | `Rh4b_A` |
| 42.7 kΩ | 1 | `Ro1w2_B` |
| 49.9 kΩ | 1 | `Rh4b_B` |
| 54.9 kΩ | 1 | `Ro1w4_A` |
| 57.6 kΩ | 1 | `Ro1w3_A` |
| 105 kΩ | 1 | `Rh2b_A` |
| 109 kΩ | 1 | `Rh3b_B` |
| 160 kΩ | 1 | `Ro1b_A` |
| 180 kΩ | 1 | `Rh2b_B` |
| 835 kΩ | 1 | `Ro1w4_B` |
| 1.3 MΩ | 1 | `Ro1w3_B` |
| 5.9 MΩ | 1 | `Ro1b_B` |

| Spec | Requirement |
| --- | --- |
| Tolerance | 0.1% |
| TCR | ≤ 25 ppm/°C preferred |
| Power | 0.1 W min |
| Voltage | 50 V class 0805/1206 |
| Do not use | coarse E96 snap of weights (Exp67) |

Series pairs (`_A` then `_B`) must be **in series** between the compiled `from`/`to` nodes. Parallel pairs must share those two nodes.

## Hardware capacitors (not in neural netlist)

| Ref | Qty | Value | Rating | Package | Notes |
| --- | ---: | --- | --- | --- | --- |
| `C_VDD_BULK` | 1 | 10 µF | ≥ 35 V | electrolytic or 1210 ceramic | +15 to GND |
| `C_VSS_BULK` | 1 | 10 µF | ≥ 35 V | same | −15 to GND |
| `C_<instance>_VP` / `_VN` | 34 | 100 nF X7R | ≥ 50 V | 0805 | 16 neural OPA189 + `U_VREFBUF`. If using 4× OPA4189: 8 caps (one pair per package) plus VREFBUF. |

**Do not fit** frozen 1 pF caps `Cinv1` … `Co1tia` (qty 0 / DNP in `BOM.csv`). Class C — `capacitor_audit.md`.

## Electromechanical

| Ref | Qty | Function | Notes |
| --- | ---: | --- | --- |
| `J_PWR` | 1 | +15 / GND / −15 | banana or TB |
| `SW_IN1` `SW_IN2` | 2 | 0 V / VREF | omit if using DAC |
| `J_IN` | 1 | IN1 IN2 GND | optional |
| `TP_*` | 27 | see `test_point_map.md` | include **`TP_O1LIN`** |

## Equipment (not stuffed)

Dual ±15 V ≥ 100 mA/rail, DMM (≥ 5.5 digit for analog 1 mV), optional scope, optional DAC.
