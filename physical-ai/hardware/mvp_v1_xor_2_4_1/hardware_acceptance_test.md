# Hardware acceptance test

Fill `hardware_correlation_template.csv`. Analog pass and class pass are **separate**.

Analog bar (same as SPICE campaign): **|V − V_SPICE| ≤ 1 mV** on `O1_LIN` at ~27 °C. Hardware may fail analog and still classify. Record both.

Class: **1 if O1_LIN ≥ 0.5 V else 0**.

## Power-off inspection

- Orientation, solder shorts, flux on 6.06 MΩ, datasheet pin 1.

## Power rail verification

| Check | Pass |
| --- | --- |
| TP_P15 | +15.0 V ± 0.2 V |
| TP_M15 | −15.0 V ± 0.2 V |
| Iq | < 50 mA typical; stop if > 80 mA |

## Reference verification

| Check | Pass |
| --- | --- |
| TP_VREF | 1.000 V (record actual) |
| TP_VREFN | ≈ −TP_VREF |

## Static XOR tests

For each of 00, 01, 10, 11 wait for settle, then record:

IN1 IN2  
H1_LIN H1_OUT  
H2_LIN H2_OUT  
H3_LIN H3_OUT  
H4_LIN H4_OUT  
O1_LIN  

Compare to SPICE (not to a live NumPy forward pass used as the circuit output). Software y_ref is listed only as an independent check.

### SPICE expected (27 °C)

| st | H1_LIN | H1_OUT | H2_LIN | H2_OUT | H3_LIN | H3_OUT | H4_LIN | H4_OUT | O1_LIN |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 00 | 0.263319 | ~0 | 0.150795 | ~0 | 0.385868 | ~0 | 0.440210 | ~0 | 0.001645 |
| 01 | 1.766247 | ~0 | −0.925312 | 0.925302 | 1.688048 | ~0 | 0.756453 | ~0 | 1.002511 |
| 10 | −0.934838 | 0.934827 | 1.477117 | ~0 | 2.336903 | ~0 | 0.830071 | ~0 | 1.018006 |
| 11 | 0.568090 | ~0 | 0.401010 | ~0 | 3.639083 | ~0 | 1.146313 | ~0 | 0.001645 |

“~0” on OUT means SPICE leakage ≈ −3 µV.

### Pass / fail

| Check | Pass |
| --- | --- |
| Class 00, 11 | 0 |
| Class 01, 10 | 1 |
| Analog O1_LIN | \|err\| ≤ 1 mV vs SPICE column |
| Hidden LIN sign | matches table (especially 10: H1_LIN negative) |
| H3_OUT, H4_OUT | remain near 0 |

If class passes and analog fails: the circuit still computes XOR coarsely. That is **not** analog MVP success. Document it.
