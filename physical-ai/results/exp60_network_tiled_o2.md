# Experiment 60 — OPA189 + tiled o2 row in Network F

Experiments 1–59 were not modified. Frozen Experiment 9 weights.
Software prepares the netlist and compares measured outputs to frozen
targets. It does not substitute a NumPy forward pass for the circuit.

**Status: DEMONSTRATED**
**Decision A — OPA189 + TILED o2 ROW HOLDS NETWORK F ANALOG MAE**
**Claim: MIXED-LEVEL PHYSICAL COMPUTATION DEMONSTRATION**
**Realism: Level 1 o2 TIA + Level 4 o2 resistors; all other neurons Level 0.**

## 1. Objective

Does inserting the leftover-limited W=10 8s×8p `Ro2*` row plus OPA189
`Eo2tia` into frozen Network F preserve analog MAE ≤ 1 mV, as
Experiment 47 did with ideal-R o2 weights?

## 2. Baseline

F12 behavioral (this run) MAE = 0.595993 mV, max = 2.374 mV, acc = 1.0 —
exact Experiment 47 behavioral control.

Experiment 47 F12/F40 OPA189 + ideal-R o2: MAE 0.552 / 0.438 mV.

## 3. Hypothesis

H1: tiled o2 leftover raises o2 error by ~0.6 mV on vec 19 but network
MAE still passes (other outputs dominate the max ~2 mV finite-A floor).
H2: F12 behavioral control matches Experiment 47 exactly.
H3: classification accuracy stays 1.0.

## 4. Method

`compile_f` Network F. Replace only the 34 catalog names `Ro2*` with
W=10 `xhigh_po`, then 8s×8p (2176 instances). Official R `.include` +
`ngbehavior=ps`. `Eo2tia` → OPA189 ±15 V. All other resistors remain
ideal; hidden inverts and other TIAs remain behavioral.

## 5. Controls

F12 behavioral netlist (no PDK, no OPA189).

## 6. Results

| Run | MAE (mV) | max (mV) | acc | analog MAE pass |
| --- | ---: | ---: | ---: | --- |
| F12 behavioral | 0.596 | 2.374 | 1.0 | True |
| F12 OPA189 + tiled o2 | 0.574 | 2.280 | 1.0 | True |
| F40 OPA189 + tiled o2 | 0.470 | 2.004 | 1.0 | True |

F12 behavioral matches Experiment 47 to all reported digits.
Tiled F12/F40 MAE is 0.022 / 0.032 mV above Experiment 47's ideal-R
OPA189 insertion — leftover, not a new break. Max ~2 mV is the same
other-output finite-A floor as Experiment 47.

## 7. Mechanism

The o2 row now computes with PDK currents through tiled `xhigh_po` and
an OPA189 TIA. Network MAE is an average over all outputs; o2 leftover
does not move the MAE bar. Classification uses measured voltages.

## 8. Failure analysis

No SPICE failure. This is not a full-network PDK fabric. Matching was
not repeated at network scale.

## 9. Promotion decision

**A — DEMONSTRATED** as mixed-level Network F insertion of the isolated
tiled o2 cell. Not FULL NETWORK PHYSICAL NEURAL COMPUTATION. Not silicon.
Physical MOS TIA **NO**. Miller family **CLOSED**. Matching **not yield**.

## 10. Claim map

- **Demonstrated:** F12 behavioral Exp47 repeat; F12/F40 analog MAE pass
  with tiled PDK o2 row + OPA189; acc = 1.0.
- **Supported:** isolated leftover does not break network MAE.
- **Projected:** temperature will move leftover via documented TCR/voltco.
- **Unknown:** tiled fabric on every neuron; `tt_mm` inside Network F;
  silicon.
- **Contradicted:** unre-sized miller TIA; W=10 single as a matching
  solution; leftover is mismatch.

## 11. Next dominant bottleneck

**Primary:** leftover / voltco on worst-case o2 swing, and the remaining
behavioral / ideal-R neurons.

**Secondary:** `tt_mm` tails; Track B MOS TIA; scaling tiled R to the
whole network.

## 12. Next experiment

Experiment 61: temperature on isolated OPA189 + 8s8p (cheap, documented
TCR) or Network F `tt_mm` on the 34-row o2 tile. Do not invent W/L.
Do not reopen the miller family.

Decision A — OPA189 + TILED o2 ROW HOLDS NETWORK F ANALOG MAE.
Mixed-level. Not silicon. Miller family remains closed.
