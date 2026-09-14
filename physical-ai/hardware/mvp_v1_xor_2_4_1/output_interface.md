# Output interface

## Analog evidence (required)

The neural result **is** the voltage on SPICE node `o1lin`.

Hardware name: **`TP_O1LIN`**.

| State | IN1 | IN2 | SPICE `o1lin` (27 °C, UIC TRAN 2 ms) | Software y_ref |
| --- | ---: | ---: | ---: | ---: |
| 00 | 0 | 0 | 0.001645123 V | 0.001650341 V |
| 01 | 0 | 1 | 1.002511 V | 1.002524 V |
| 10 | 1 | 0 | 1.018006 V | 1.018019 V |
| 11 | 1 | 1 | 0.001645121 V | 0.001650341 V |

Measure with DMM (DC) after settling. SPICE used 2 ms UIC TRAN; hardware settling is **UNKNOWN — HARDWARE TEST REQUIRED**. Wait ≥ 10 ms after changing inputs before recording; if the scope shows ringing, wait until it dies.

Range: about **0 V to +1.02 V** for this frozen XOR. Do not expect negative class-0; class-0 sits near +1.6 mV.

Instrument: DMM ≥ 5.5 digit for 1 mV analog checks; 3.5 digit is enough for class.

## Classification (optional, parallel)

```
class = 1 if TP_O1LIN ≥ 0.5 V else 0
```

Threshold is from the frozen trainer (`class_threshold = 0.5`), not chosen after seeing hardware.

A comparator (e.g. extra OPA189 as comparator vs a 0.5 V divider from VREF, or a documented comparator IC) may drive an LED. **`TP_O1LIN` must remain a high-impedance analog test point.** The comparator must not replace the analog TIA.

## Do not

- Buffer `TP_O1LIN` with a digital GPIO read without documenting the analog voltage.
- Filter the analog output in firmware with a learned correction.
- Compute XOR in logic and OR it with the analog bit.
