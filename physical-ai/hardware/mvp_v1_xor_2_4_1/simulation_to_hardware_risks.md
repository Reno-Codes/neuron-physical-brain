# Simulation to hardware risks

Labels: **DEMONSTRATED IN SPICE** · **EXPECTED IN HARDWARE** · **UNKNOWN — HARDWARE TEST REQUIRED**

| Topic | Label | Notes |
| --- | --- | --- |
| Frozen XOR electrical inference, exact R, 27 °C | DEMONSTRATED IN SPICE | Exp64; MAE 9.3 µV; this package repeats yo1 |
| UIC TRAN vs OP | DEMONSTRATED IN SPICE | Full-netlist OP is stiff; hardware will have its own startup |
| 1 pF SPICE caps unnecessary for DC XOR | DEMONSTRATED IN SPICE | Δy = 0 with caps removed |
| Coarse E96 weights | DEMONSTRATED IN SPICE | Exp67 class OK, analog up to 30 mV — do not use |
| Analog 1 mV −40…70 °C | DEMONSTRATED IN SPICE | Ideal R, macromodel T only (Exp65/66) |
| 85 °C analog 1 mV | DEMONSTRATED IN SPICE as **fail** (~1.08 mV) | Class still 4/4 |
| OPA189 vendor macromodel vs real OPA189 | UNKNOWN — HARDWARE TEST REQUIRED | Mixed-level; Vos, Ib, Iq, settling |
| 1N4148 compact model vs parts | UNKNOWN — HARDWARE TEST REQUIRED | Extracted TI TLC555 card, not a measured diode |
| 0.1% resistor realization | EXPECTED IN HARDWARE | Combinations keep compiled R within 0.1%; still not the SPICE exact float |
| Resistor TCR | UNKNOWN — HARDWARE TEST REQUIRED | SPICE discrete R had no TCR card |
| VREF ideal 1 V | UNKNOWN — HARDWARE TEST REQUIRED | Must build/calibrate |
| Input source error | UNKNOWN — HARDWARE TEST REQUIRED | |
| PCB leakage on 6.06 MΩ | UNKNOWN — HARDWARE TEST REQUIRED | Affects class-0 millivolt floor |
| Parasitic C on TIA −input | UNKNOWN — HARDWARE TEST REQUIRED | May oscillate; not in frozen netlist |
| Power-supply noise | UNKNOWN — HARDWARE TEST REQUIRED | Ideal Vdc in SPICE |
| Startup / UIC | UNKNOWN — HARDWARE TEST REQUIRED | SPICE UIC is not a power switch |
| Ground loops | UNKNOWN — HARDWARE TEST REQUIRED | |
| Thermal drift after warmup | UNKNOWN — HARDWARE TEST REQUIRED | |
| Real settling time | UNKNOWN — HARDWARE TEST REQUIRED | SPICE recorded at 2 ms |
| Silicon / PDK MOS TIA | not claimed | Miller family closed; this MVP is discrete analog |
| Yield | not claimed | |

**EXPECTED IN HARDWARE:** with 0.1% resistors, a 1.000 V reference, ±15 V, and no oscillation, **classification 4/4** is the likely first-board outcome. Analog 1 mV vs SPICE is **not** guaranteed.
