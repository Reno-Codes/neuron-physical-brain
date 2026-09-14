# MVP-H1 hardware readiness gate

Frozen netlist SHA-256 (verified this audit):

`28dccd8121a1032d69a2b08633737db0b2f10c8996f68ed2271520ec58c3b9cb`

Open documentation BLOCKERS: **0** (`MVP_H1_AUDIT_FINDINGS.md`).  
WARNINGS: **8** (SKUs, E96 frozen BOM, ideal VREF, no KiCad PCB, SVG pinout, analog 1 mV, settle time, 6.06 MΩ leakage).

---

## READY TO ORDER?

**YES** — electrical kit.

**Evidence**

- `MVP_H1_FINAL_BOM_AUDITED.csv` lists every stuffed reference, value, tolerance, voltage/power, package, and spare policy
- `resistor_shopping.csv` is the 0.1% E192 kit (not frozen E96)
- OPA189 / 1N4148 families and SOIC-8 default pinout are documented from TI SBOS830 and the 1N4148 subcircuit pins

**At checkout you must still** verify manufacturer reel SKUs. Project evidence does **not** contain verified cart-line MPNs. Status on those fields remains `PROCUREMENT VERIFICATION REQUIRED`.

---

## READY TO ASSEMBLE?

**YES** — after parts are in hand, on a hierarchical PCB (or soldered proto that follows `MVP_H1_LAYOUT_SPEC.md`).

**Evidence**

- `BUILD_MVP_H1_STEP_BY_STEP.md` is a single human path
- `MVP_H1_CONNECTION_TABLE.csv` is pin-level (312 connections)
- `opa189_pinout.md` + 1N4148 anode/cathode
- Staged order in `MVP_H1_BRINGUP_AND_TEST.md`

**Not ready on:** a solderless breadboard (rejected).  
**Not ready as:** “drop in a finished KiCad board from this repo” — no `.kicad_pcb` exists.

---

## READY TO POWER?

**NO**

**Missing**

- No physical MVP-H1 board has been assembled or Stage 0 continuity-checked in this repository
- Power is allowed only after Stage 0 pass, then Stage 1, per `BUILD_MVP_H1_STEP_BY_STEP.md`

Do not apply ±15 V to an untested fully stuffed assembly.

When a board exists and Stage 0 passes, Stage 1 is the first powered test.

---

## READY TO DEMONSTRATE?

**NO**

**Missing**

- No filled `MVP_H1_MEASUREMENT_LOG_TEMPLATE.csv` with hardware voltages
- Level A (4/4 class from `TP_O1LIN`) has not been measured on a physical circuit

**Ready as documentation:** `MVP_H1_DEMO_PROTOCOL.md` and `MVP_H1_ACCEPTANCE_CRITERIA.md` define the demo. They do not replace a measured board.

---

## First physical action (now)

1. Re-confirm the frozen `netlist.cir` hash if you keep a local tree.
2. Order the electrical kit in `MVP_H1_FINAL_BOM_AUDITED.csv` / `resistor_shopping.csv`, verifying SKUs at the distributor.
3. Layout or send out a hierarchical PCB from `MVP_H1_LAYOUT_SPEC.md` (or solder proto to the same partition).
4. Assemble and power only through the staged bring-up.

---

## Definition of first MVP success

**Level A:** four physical input states produce classes **0, 1, 1, 0** from measured `TP_O1LIN` using threshold 0.5 V, with the multiply-accumulate and ReLU performed in the circuit.

Level B (≤ 1 mV vs SPICE) and Level C (repeat after power cycle) are reported separately.
