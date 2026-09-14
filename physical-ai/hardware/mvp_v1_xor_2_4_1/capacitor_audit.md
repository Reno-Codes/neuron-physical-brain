# Capacitor audit

Frozen compiler netlist places **1 pF to ground** on every OPA189 output (`Cinv1`, `Cinv2`, `Cinvref`, `Ch*tia`, `Ch*rl`, `Ch*inv`, `Co1tia`).

## SPICE comparison (this package)

UIC TRAN 2 ms, four XOR vectors, `ngbehavior=ps`, 27 °C implied. Same frozen netlist with all `1e-12` capacitors removed.

| Vector | y with 1 pF | y without 1 pF | Δy |
| ---: | ---: | ---: | ---: |
| 00 | 0.001645123 | 0.001645123 | **0** |
| 01 | 1.002511 | 1.002511 | **0** |
| 10 | 1.018006 | 1.018006 | **0** |
| 11 | 0.001645121 | 0.001645121 | **0** |

Raw: `spice_correlation_raw.json`.

## Classification

| Reference | Value | Nodes | Class | Evidence | Physical placement |
| --- | --- | --- | --- | --- | --- |
| `Cinv1` … `Co1tia` (16 caps) | 1 pF | op-amp output to GND | **C — SPICE numerical/stabilization** | Δy = 0 on all XOR states; compiler comment “node” load | **Do not fit a discrete 1 pF.** PCB+probe parasitics already ≥ 1 pF. |
| `C_VDD_BULK` `C_VSS_BULK` | 10 µF | rails to GND | **A — electrically required** (hardware) | Not in neural netlist. Power integrity. | Place at supply entry. |
| `C_Ux_V+` `C_Ux_V−` | 100 nF | each OPA189 V+/V− to GND | **A — electrically required** (hardware) | TI analog practice; not in neural SPICE. | Place at each package. |

Do not treat decoupling capacitors as neural weights. They are not in the frozen MAC topology.

If the board oscillates, that is a **hardware compensation** problem. Measure first. Do not add random caps on summing nodes (`H*_SUM`, `O1_SUM`) — that changes TIA dynamics. **UNKNOWN — HARDWARE VALIDATION REQUIRED** if oscillation appears.

`BOM.csv` lists the 16 frozen 1 pF references with **qty 0 / DNP**.
