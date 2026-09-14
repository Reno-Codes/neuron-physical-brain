# Resistor implementation

Frozen compiled ohms are **not** replaced by coarse E96 (Experiment 67: analog error up to 29.9 mV, class still 4/4).

This plan **realizes the same ohms** with 0.1% E192 thin-film parts (single, series, or parallel). It does not edit `W1/b1/W2/b2`.

Full table: `resistor_implementation.csv`. Unique kit quantities: `resistor_shopping.csv`. Search details: `resistor_combos.json`.

## Policy

- Invert / TIA Rf / rectifier 10 kΩ: **single 10 kΩ 0.1%**, match pairs that form a unity invert (`Rin`/`Rf`).
- Neural weight/bias: 0.1% E192 combination with |R/R_exact − 1| ≤ 0.1%.
- No potentiometer on a weight unless a future revision adds a documented calibration DAC. MVP-H1: **no trimmers on weights**.
- Power: all dissipations ≪ 10 mW; **0.1 W** is enough.
- Package: 0805 or 1206 50 V thin film, ≤ 25 ppm/°C preferred.
- MPNs: **PROCUREMENT VERIFICATION REQUIRED**. Buy to the ohm combination, not to a guessed stock number.

## Combinations (0.1% E192)

| Ref | Exact Ω | Implementation | Rel. error |
| --- | ---: | --- | ---: |
| All 10 kΩ invert/TIA/ReLU (31 pcs) | 10000 | single 10k | 0 |
| Rh1w1 | 8346.153 | single 8.35k | 0.046% |
| Rh1w2 | 6653.681 | single 6.65k | 0.055% |
| Rh1b | 37976.812 | series 976+37k | 0.002% |
| Rh2w1 | 7539.646 | parallel 9.53k\|\|36.1k | 0.0003% |
| Rh2w2 | 9292.757 | series 203+9.09k | 0.003% |
| Rh2b | 66315.561 | parallel 105k\|\|180k | 0.0003% |
| Rh3w1 | 5125.484 | parallel 6.73k\|\|21.5k | 0.002% |
| Rh3w2 | 7679.433 | single 7.68k | 0.007% |
| Rh3b | 25915.697 | parallel 34k\|\|109k | 0.002% |
| Rh4w1 | 25650.221 | series 750+24.9k | 0.001% |
| Rh4w2 | 31621.294 | single 31.6k | 0.067% |
| Rh4b | 22716.415 | parallel 41.7k\|\|49.9k | 0.0003% |
| Ro1w1 | 9197.822 | single 9.2k | 0.024% |
| Ro1w2 | 9245.047 | parallel 11.8k\|\|42.7k | 0.001% |
| Ro1w3 | 55155.970 | parallel 57.6k\|\|1.3M | 0.0003% |
| Ro1w4 | 51512.428 | parallel 54.9k\|\|835k | 0.001% |
| Ro1b | 6059355.217 | series 160k+5.9M | 0.011% |

Prefer **series** over parallel if a layout is easier, as long as the realized R stays within 0.1%.

`Ro1b` (6.06 MΩ) sets the ~1.65 mV class-0 floor. Keep it clean of flux. A 1% error on this resistor is only ~16 µV on y — much less sensitive than `Ro1w1` on state 10.

## Alternative

0.01% / 0.05% catalog singles if a distributor has the exact E192 value. Still verify the ohm, not the marketing name.
