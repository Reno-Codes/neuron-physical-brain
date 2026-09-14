# MVP-H1 demonstration protocol

## Purpose

Prove that the **physical circuit** computes XOR.

A computer may apply IN1/IN2, wait, measure `TP_O1LIN`, write the voltage to a file, and apply the documented threshold. It must **not** evaluate `W2 · ReLU(W1 x + b1) + b2` and present that as the circuit result.

Disconnect any software neural-network reference used as a live substitute. After that, the voltages must still classify XOR.

---

## Setup

1. Complete Stages 0–5 in `MVP_H1_BRINGUP_AND_TEST.md`.
2. Dual ±15 V on. Record `TP_P15`, `TP_M15`, supply current.
3. Record `TP_VREF` and `TP_VREFN`.
4. Meter common on `TP_GND`.
5. Open `MVP_H1_MEASUREMENT_LOG_TEMPLATE.csv` (repeat 1). After a power cycle, fill repeat 2 (Level C).

---

## Settling

After each input change wait **≥ 10 ms**, then longer if the scope shows ringing. SPICE logged at 2 ms. Hardware settling is **UNKNOWN — HARDWARE TEST REQUIRED**.

---

## Four physical tests

Apply voltages at `TP_IN1` and `TP_IN2`. Confirm the **measured** inputs, not only the switch labels.

| Order | IN1 | IN2 | Expected class | SPICE `TP_O1LIN` (27 °C) |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 0 V | 0 V | 0 | 0.001645123 V |
| 2 | 0 V | 1.000 V | 1 | 1.002511 V |
| 3 | 1.000 V | 0 V | 1 | 1.018006 V |
| 4 | 1.000 V | 1.000 V | 0 | 0.001645121 V |

For each state:

1. Apply the two voltages.
2. Wait the settling time.
3. Measure and record `TP_O1LIN` (raw volts).
4. Also record hidden nodes listed in the log (debug evidence; not a substitute for `O1_LIN`).
5. Derive class **only** as:

```text
class = 1 if O1_LIN_measured >= 0.5 V else 0
```

6. Compare class to the expected class column. Do not “fix” a wrong class by running NumPy.

Optional LED comparator vs 0.5 V is allowed **in parallel** only. `TP_O1LIN` must remain a high-impedance analog node.

---

## Human-readable result table (fill after the run)

| State | IN1 meas (V) | IN2 meas (V) | O1_LIN meas (V) | Class (0.5 V) | Expected class | Class pass | SPICE O1_LIN (V) | \|err\| (V) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 00 |  |  |  |  | 0 |  | 0.001645123 |  |
| 01 |  |  |  |  | 1 |  | 1.002511 |  |
| 10 |  |  |  |  | 1 |  | 1.018006 |  |
| 11 |  |  |  |  | 0 |  | 0.001645121 |  |

Machine-readable twin: `MVP_H1_MEASUREMENT_LOG_TEMPLATE.csv`.

---

## What success is

See `MVP_H1_ACCEPTANCE_CRITERIA.md`.

**First MVP demonstration = Level A:** four classes correct from measured `TP_O1LIN`. Analog 1 mV (Level B) is reported separately and is **not** required to claim Level A.
