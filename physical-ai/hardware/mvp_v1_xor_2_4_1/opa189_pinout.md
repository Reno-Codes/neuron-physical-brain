# OPA189 / OPA4189 pinout (hardware)

Source: Texas Instruments **SBOS830** (OPAx189 datasheet Rev I, pin configuration tables). Verify the PDF for the **exact package** you buy.

SPICE subcircuit order in `OPAx189.LIB` is `IN+ IN- VCC VEE OUT`. That is **not** a package pin order.

OPA189 is **not** a 741 pinout.

## OPA189 — 8-pin SOIC (D) and VSSOP (DGK)

| Pin (SOIC D / VSSOP DGK) | Name | SPICE |
| ---: | --- | --- |
| 1 | NC | leave floating |
| 2 | −IN | `IN-` |
| 3 | +IN | `IN+` |
| 4 | V− | `VEE` (`vss`, −15 V) |
| 5 | NC | leave floating |
| 6 | OUT | `OUT` |
| 7 | V+ | `VCC` (`vdd`, +15 V) |
| 8 | NC | leave floating |

SOT-23-5 (DBV) is **different** (OUT=1, V−=2, +IN=3, −IN=4, V+=5). Do not assume SOIC numbers on a SOT-23.

## OPA2189 dual — 8-pin SOIC (if used)

| Pin | Name |
| ---: | --- |
| 1 | OUT A |
| 2 | −IN A |
| 3 | +IN A |
| 4 | V− |
| 5 | +IN B |
| 6 | −IN B |
| 7 | OUT B |
| 8 | V+ |

## OPA4189 quad (if used instead of 16 singles)

| Pin | Name |
| ---: | --- |
| 1 | OUT A |
| 2 | −IN A |
| 3 | +IN A |
| 4 | V+ |
| 5 | +IN B |
| 6 | −IN B |
| 7 | OUT B |
| 8 | OUT C |
| 9 | −IN C |
| 10 | +IN C |
| 11 | V− |
| 12 | +IN D |
| 13 | −IN D |
| 14 | OUT D |

Ground unused channels: +IN to GND, −IN to OUT (unity follower) or follow TI unused-channel guidance. Unused channels still draw Iq.

Electrical limits (SBOS830): supply 4.5 V to 36 V (use ±15 V here). Iq **typical 1.3 mA / max 1.7 mA** per amplifier at 25 °C; max 1.8 mA over −40 °C to 125 °C.
