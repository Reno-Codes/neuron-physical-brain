# MVP-H1 acceptance criteria

Classification and analog error are **always reported separately**. Correct class does not hide analog error.

Threshold is the frozen trainer threshold **0.5 V**, not chosen after seeing hardware:

```text
class = 1 if measured TP_O1LIN >= 0.5 V else 0
```

Software must not compute the network in place of `TP_O1LIN`.

---

## Level A — Physical XOR demonstration (minimum MVP)

| Requirement | Pass |
| --- | --- |
| Inputs are physical 0 V / 1 V on IN1 and IN2 | measured, not only commanded |
| All four states applied | 00, 01, 10, 11 |
| Class from `TP_O1LIN` vs 0.5 V | 0, 1, 1, 0 |
| Analog path is the circuit | no NumPy/firmware XOR substitute |

**Level A does not require** |V − V_SPICE| ≤ 1 mV.

If Level A passes and Level B fails: the board still **demonstrates physical XOR**. Record that honestly.

---

## Level B — Analog correlation (stretch)

Compare measured `TP_O1LIN` to SPICE 27 °C UIC 2 ms:

| State | SPICE (V) |
| --- | ---: |
| 00 | 0.001645123 |
| 01 | 1.002511 |
| 10 | 1.018006 |
| 11 | 0.001645121 |

Compute:

```text
err_i = |O1_LIN_meas_i - O1_LIN_SPICE_i|
MAE   = mean(err_i)
max   = max(err_i)
```

**Level B pass (same bar as the SPICE campaign):** every `err_i` ≤ 1 mV at ~27 °C with 0.1% / exact resistors.

If this fails, report MAE and max anyway. Do not retune frozen weights to force Level B.

Hidden-node comparison to `simulation_baseline.md` is diagnostic, not a Level B requirement.

---

## Level C — Repeatability

1. Power down per `BUILD_MVP_H1_STEP_BY_STEP.md`.
2. Power up.
3. Repeat the four states (log repeat = 2).

**Level C pass:** Level A still 4/4 after the cycle.

Optional note: class flicker or large analog walk after warmup is **UNKNOWN — HARDWARE TEST REQUIRED**.

---

## What this does not accept as success

- A microcontroller that XORs the two bits.
- A Python forward pass written into the “measured” column.
- Classification from a hidden node instead of `TP_O1LIN`.
- Buying E96 snaps from the frozen compiler BOM and calling Level B a pass.
