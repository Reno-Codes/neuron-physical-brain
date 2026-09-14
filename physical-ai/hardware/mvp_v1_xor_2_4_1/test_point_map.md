# Test point map

All voltages vs `TP_GND`. SPICE numbers: 27 °C UIC TRAN 2 ms (`spice_correlation_raw.json`).

| Test point | SPICE | Expected range / 27 °C XOR | Failure interpretation |
| --- | --- | --- | --- |
| `TP_P15` | `vdd` | +15.0 V ± 0.2 V | Supply/connector |
| `TP_M15` | `vss` | −15.0 V ± 0.2 V | Supply/connector |
| `TP_GND` | `0` | 0 (meter common) | — |
| `TP_VREF` | `vref` | 1.000 V (hardware source) | Reference circuit |
| `TP_VREFN` | `vrefn` | ≈ −1.000 V | `Xinvref` or 10 k pair |
| `TP_IN1` | `in1` | 0 or 1.000 V as set | Switch/DAC |
| `TP_IN2` | `in2` | 0 or 1.000 V as set | Switch/DAC |
| `TP_IN1N` | `in1n` | ≈ −IN1 | `Xinv1` |
| `TP_IN2N` | `in2n` | ≈ −IN2 | `Xinv2` |
| `TP_H1_SUM` | `h1sum` | ~0 V (tens of µV in SPICE) | TIA not regulating |
| `TP_H1_LIN` | `h1lin` | **−z1**: 00: +0.263 V; 01: +1.766 V; 10: −0.935 V; 11: +0.568 V | Weights or TIA |
| `TP_H1_OUT` | `h1y` | ReLU: 00/01/11 ~0; 10: +0.935 V | Rectifier diodes/op-amp |
| `TP_H1_YN` | `h1yn` | −H1_OUT | Hidden invert |
| `TP_H2_SUM` | `h2sum` | ~0 V | TIA |
| `TP_H2_LIN` | `h2lin` | 00: +0.151 V; 01: −0.925 V; 10: +1.477 V; 11: +0.401 V | |
| `TP_H2_OUT` | `h2y` | 01: +0.925 V; else ~0 | |
| `TP_H2_YN` | `h2yn` | −H2_OUT | |
| `TP_H3_SUM` | `h3sum` | ~0 V | |
| `TP_H3_LIN` | `h3lin` | 00: +0.386 V; 01: +1.688 V; 10: +2.337 V; 11: +3.639 V (all −z3 ≥ 0 so ReLU 0) | If H3_OUT not ~0, rectifier failed |
| `TP_H3_OUT` | `h3y` | ~0 all four XOR states | |
| `TP_H3_YN` | `h3yn` | ~0 | |
| `TP_H4_SUM` | `h4sum` | ~0 V | |
| `TP_H4_LIN` | `h4lin` | 00: +0.440 V; 01: +0.756 V; 10: +0.830 V; 11: +1.146 V | |
| `TP_H4_OUT` | `h4y` | ~0 all four XOR states | |
| `TP_H4_YN` | `h4yn` | ~0 | |
| `TP_O1_SUM` | `o1sum` | ~0 V | Output TIA |
| **`TP_O1LIN`** | **`o1lin`** | **1.645 mV / 1.002511 V / 1.018006 V / 1.645 mV** | **Primary neural output** |

H3 and H4 ReLU outputs are ~0 on this frozen XOR (those neurons never fire). Their TIAs still swing **positive** `H*_LIN` (because hidden TIA = −z and z is negative). That is normal.

Optional: `TP_H1_AMP` … for diode debugging only.
