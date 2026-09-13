# Experiment 49 — existing Miller+servo in the 200 µs regime

Experiments 1–48 were not modified. Frozen weights unchanged.
Same Exp39/41 Miller sizes and 1 nF servo. No W/L resize.
Official sky130.lib tt. Not silicon.

**Status: CLOSED NEGATIVE PATH**
**Decision D — EXISTING MILLER+SERVO STILL MISSES BY HUNDREDS OF mV AT 200 us**

## Objective

Determine whether the Experiment 48 DC miss (y=2.098479 V, 361 mV)
is only an inappropriate DC operating point for the integrating servo,
or whether the settled 200 µs inference result also fails.

## DC repeat

- y = 2.098479338703  |err| = 361.010232 mV  Δ vs Exp48 = 0.0  repeat_ok = True

## Transient samples

| run | method | t (µs) | y (V) | |err| (mV) | Vsum (V) | Vsrv (V) | Δ vs Exp48 DC | pass |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| servo_tran_500u_trap | trap_default | 100 | 1.993869 | 465.621 | -0.0055571 | 0.00400105 | -0.10461033870300018 | False |
| servo_tran_500u_trap | trap_default | 200 | 2.044546 | 414.944 | -0.0049567 | 0.00579617 | -0.0539333387030001 | False |
| servo_tran_500u_trap | trap_default | 500 | 2.087267 | 372.223 | -0.00445057 | 0.00768364 | -0.011212338702999869 | False |
| servo_tran_200u_repeat | trap_default | 100 | 1.993869 | 465.621 | -0.0055571 | 0.00400105 | -0.10461033870300018 | False |
| servo_tran_200u_repeat | trap_default | 200 | 2.044546 | 414.944 | -0.00495671 | 0.00579867 | -0.0539333387030001 | False |

Decision D — EXISTING MILLER+SERVO STILL MISSES BY HUNDREDS OF mV AT 200 us. Experiment 48 DC was y=2.098479338703 (|err|=361.0 mV). No W/L was changed. Not silicon. PHYSICAL TIA VALIDATED remains no.

- Physical TIA validated: **NO**
- Matching: **UNRESOLVED**
- Experiment 40 Decision C: **unchanged**
- Experiment 48 Decision B: **unchanged** (DC)

## Next experiment

Experiment 50: Track B — inventory documented SKY130/PDK amplifier classes against Experiment 44 budgets. Do not resize this Miller. Do not invent W/L.
