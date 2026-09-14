# Input interface

- 2 analog voltages `in1`, `in2` relative to circuit ground.
- Frozen XOR stimulus set (the circuit, not the PC, computes the output):

  | vec | in1 | in2 | expected class |
  | ---: | ---: | ---: | ---: |
  | 0 | 0 V | 0 V | 0 |
  | 1 | 0 V | 1 V | 1 |
  | 2 | 1 V | 0 V | 1 |
  | 3 | 1 V | 1 V | 0 |

- A PC + DAC may drive these voltages. The PC must not compute Wx+b or ReLU.
- Shared precision **1.000 V** bias reference `vref`.
- Predicted |signal| max on this model = 3.64 V (hidden pre-activation).
- Recommended first hardware test: 27 °C, 0/1 V CMOS or DAC levels.
