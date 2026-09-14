# Output interface

- Linear output: `v(o1lin)` (node `o1lin` after the output TIA).
- Frozen software targets at 27 °C:

  | vec | y_ref (V) | measured SPICE y (V) |
  | ---: | ---: | ---: |
  | 0 | 0.001650 | 0.001645 |
  | 1 | 1.002524 | 1.002511 |
  | 2 | 1.018019 | 1.018006 |
  | 3 | 0.001650 | 0.001645 |

- Classification: class = 1 if y ≥ **0.5 V** else 0. Threshold is from the trainer, not chosen after SPICE.
- A PC + ADC, or a comparator vs 0.5 V, may read the voltage. It must not run the network.
- Analog bar used in validation: |y − y_ref| ≤ 1 mV at −40 °C to 70 °C.
