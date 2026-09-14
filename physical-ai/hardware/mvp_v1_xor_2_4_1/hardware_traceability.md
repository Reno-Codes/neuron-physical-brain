# Hardware traceability

SPICE names are the schematic net names. Do not rename.

| SPICE node | Schematic net | Physical component / origin | Test point | Measurement purpose |
| --- | --- | --- | --- | --- |
| `0` | `GND` | analog ground | `TP_GND` | reference for all measurements |
| `vdd` | `VDD` | +15 V rail, OPA189 V+ | `TP_P15` | supply |
| `vss` | `VSS` | −15 V rail, OPA189 V− | `TP_M15` | supply |
| `vref` | `VREF` | 1.000 V reference (ideal in SPICE) | `TP_VREF` | bias source |
| `vrefn` | `VREFN` | `Xinvref` output | `TP_VREFN` | should be −VREF |
| `in1` | `IN1` | switch/DAC | `TP_IN1` | applied x1 |
| `in2` | `IN2` | switch/DAC | `TP_IN2` | applied x2 |
| `in1n` | `IN1N` | `Xinv1` | `TP_IN1N` | −x1 |
| `in2n` | `IN2N` | `Xinv2` | `TP_IN2N` | −x2 |
| `inv1inn` | `INV1_INN` | `Rinv1in`/`Rinv1f` summing | — | invert virtual ground (~0 V) |
| `inv2inn` | `INV2_INN` | `Rinv2in`/`Rinv2f` | — | invert virtual ground |
| `invrefinn` | `INVREF_INN` | `Rinvrefin`/`Rinvreff` | — | invert virtual ground |
| `h1sum` | `H1_SUM` | `Xh1tia` IN− | `TP_H1_SUM` | TIA virtual ground; \|V\| ≫ 1 mV means TIA broken |
| `h1lin` | `H1_LIN` | `Xh1tia` OUT / `Rh1f` | `TP_H1_LIN` | hidden pre-activation as **−z1** |
| `h1rinn` | `H1_RINN` | rectifier IN− | — | ReLU inverting node |
| `h1amp` | `H1_AMP` | `Xh1relu` OUT | — | diode drive; not the ReLU output |
| `h1y` | `H1_OUT` | rectifier output `Xh1d2` cathode / `Rh1rl` | `TP_H1_OUT` | ReLU(z1) |
| `h1yn` | `H1_YN` | `Xh1inv` OUT | `TP_H1_YN` | −ReLU(z1) |
| `h2sum` … `h4yn` | same pattern h2–h4 | same | `TP_H2_*` … `TP_H4_*` | same |
| `o1sum` | `O1_SUM` | `Xo1tia` IN− | `TP_O1_SUM` | output virtual ground |
| `o1lin` | `O1_LIN` | `Xo1tia` OUT | **`TP_O1LIN`** | **neural analog output** |

## Op-amp instances (16)

| SPICE | Role |
| --- | --- |
| `Xinv1` `Xinv2` `Xinvref` | unity inverters |
| `Xh1tia` `Xh2tia` `Xh3tia` `Xh4tia` | hidden TIAs |
| `Xh1relu` `Xh2relu` `Xh3relu` `Xh4relu` | rectifier op-amps |
| `Xh1inv` `Xh2inv` `Xh3inv` `Xh4inv` | hidden sign inverters |
| `Xo1tia` | output TIA |

## Diodes (8)

| SPICE | From → To | Role |
| --- | --- | --- |
| `Xh1d1` | `h1rinn` → `h1amp` | clamp |
| `Xh1d2` | `h1amp` → `h1y` | forward |
| `Xh2d1` `Xh2d2` | same for h2 | |
| `Xh3d1` `Xh3d2` | same for h3 | |
| `Xh4d1` `Xh4d2` | same for h4 | |

Anode is the first node, cathode the second (1N4148 subckt pins 1, 2).

## Weight/bias resistors (signed routing)

See `resistor_implementation.csv` and frozen `resistor_values.csv`. Node names are SPICE nodes.

Hidden TIA inverts (`H*_LIN = −z`). Positive hidden `w` uses the **original** source; negative hidden `w` uses the **inverted** source.

Output TIA does **not** invert the math (`O1_LIN = +y`). Positive output `w` uses the **inverted** hidden; negative output `w` uses the **original** hidden.

| Ref | Exact Ω | Weight | From | To |
| --- | ---: | ---: | --- | --- |
| `Rh1w1` | 8346.153 | +1.198 | `in1` | `h1sum` |
| `Rh1w2` | 6653.681 | −1.503 | `in2n` | `h1sum` |
| `Rh1b` | 37976.812 | −0.263 | `vrefn` | `h1sum` |
| `Rh2w1` | 7539.646 | −1.326 | `in1n` | `h2sum` |
| `Rh2w2` | 9292.757 | +1.076 | `in2` | `h2sum` |
| `Rh2b` | 66315.561 | −0.151 | `vrefn` | `h2sum` |
| `Rh3w1` | 5125.484 | −1.951 | `in1n` | `h3sum` |
| `Rh3w2` | 7679.433 | −1.302 | `in2n` | `h3sum` |
| `Rh3b` | 25915.697 | −0.386 | `vrefn` | `h3sum` |
| `Rh4w1` | 25650.221 | −0.390 | `in1n` | `h4sum` |
| `Rh4w2` | 31621.294 | −0.316 | `in2n` | `h4sum` |
| `Rh4b` | 22716.415 | −0.440 | `vrefn` | `h4sum` |
| `Ro1w1` | 9197.822 | +1.087 | `h1yn` | `o1sum` |
| `Ro1w2` | 9245.047 | +1.082 | `h2yn` | `o1sum` |
| `Ro1w3` | 55155.970 | −0.181 | `h3y` | `o1sum` |
| `Ro1w4` | 51512.428 | −0.194 | `h4y` | `o1sum` |
| `Ro1b` | 6059355.217 | +0.001650 | `vrefn` | `o1sum` |

Full pin list: `schematic_connectivity.md`.
