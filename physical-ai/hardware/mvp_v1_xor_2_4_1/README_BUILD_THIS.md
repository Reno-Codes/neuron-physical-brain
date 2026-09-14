# README — BUILD THIS

## 1. What is this?

**Physical AI MVP v1** is a buildable analog circuit that implements the frozen XOR network:

`2 inputs → 4 ReLU hidden neurons → 1 linear output`

compiled from `physical-ai/models/xor_model.npz`. The neural multiply-accumulate and ReLU are electrical (resistors, OPA189, 1N4148). This folder is hardware revision **MVP-H1**. The validated SPICE design is frozen in `physical-ai/physical_design/xor_2_4_1/`.

## 2. What does it demonstrate?

Four analog input states must produce XOR classification **from `TP_O1LIN`**, not from software:

| IN1 | IN2 | class (`TP_O1LIN` ≥ 0.5 V → 1) | SPICE analog (27 °C) |
| --: | --: | ---: | ---: |
| 0 V | 0 V | 0 | 1.645 mV |
| 0 V | 1 V | 1 | 1.002511 V |
| 1 V | 0 V | 1 | 1.018006 V |
| 1 V | 1 V | 0 | 1.645 mV |

> The computer may stimulate and measure the circuit, but the neural-network multiply-accumulate and activation computation must occur in the physical electrical circuit.

Disconnect NumPy / the frozen-model forward pass. The voltages must still compute XOR.

## 3. What parts do I need?

**Buy from Croatia:** `MVP_H1_CLICK_TO_BUY.csv` — one product-page URL per part (Farnell.de + Reichelt.de). Readme: `MVP_H1_CROATIA_BUY_LIST.md`.

See `BOM.md` / `BOM.csv`. Minimum:

- 16× OPA189 **or** 4× OPA4189 (quad of the same family). Pinout: TI datasheet SBOS830 / SBOS873.
- 8× 1N4148 (two per hidden ReLU).
- 48 neural/support resistors as `resistor_implementation.csv` (0.1% thin film; series/parallel where a single E192 is not close enough; **60** physical parts, kit in `resistor_shopping.csv`). **Do not coarse-E96 snap weights** (Experiment 67: class OK, analog error up to 30 mV).
- Dual ±15 V supply, 1.000 V buffered reference, decoupling, test points, input switches or a DAC.

Exact manufacturer reels: **PROCUREMENT VERIFICATION REQUIRED**. Electrical specs are in the BOM.

## 4. What equipment do I need?

- Dual tracking ±15 V bench supply, ≥ 100 mA per rail (SPICE draw ~22 mA/rail; budget headroom).
- DMM (≥ 5.5 digit preferred for analog 1 mV checks) and/or oscilloscope.
- Optional: 0.5 V comparator / ADC after `TP_O1LIN`.
- Optional: precision 1 V calibrator for IN1/IN2 and VREF.

## 5. How do I power it?

`+15 V`, analog `GND`, `−15 V`. See `power_plan.md`. Power **GND first if your supply requires it**; otherwise bring up ±15 V together. Do not power the analog section from a single-ended 5 V USB rail.

## 6. How do I provide inputs?

**Manual:** two SPDT switches, 0 V / 1.000 V from the buffered reference.
**Instrumented:** two DAC channels or two lab sources, common ground, 0.000 V or 1.000 V.

The source may generate voltages. It must not compute `W2 ReLU(W1 x + b1) + b2`.

## 7. Where do I measure outputs?

Primary analog result: **`TP_O1LIN`** (SPICE node `o1lin`).

Hidden debug: `TP_H1_LIN` … `TP_H4_LIN` and `TP_H1_OUT` … `TP_H4_OUT`. Map: `test_point_map.md`.

## 8. How do I assemble it?

Not a solderless breadboard. Recommended: **one 2-layer (or 4-layer) PCB with hierarchical stuffing**, or soldered proto modules. Procedure: `assembly_procedure.md`.

## 9. How do I test it?

`hardware_acceptance_test.md`. Fill `hardware_correlation_template.csv`. Analog pass and class pass are **separate**.

## 10. What does success look like?

For all four states:

- Classification from `TP_O1LIN` vs 0.5 V matches the XOR table.
- Analog: |V_measured − V_SPICE| ≤ 1 mV on `O1_LIN` at ~27 °C with exact/0.1% resistors (the SPICE bar). Hardware may miss 1 mV; **do not hide that behind correct class**.

## 11. What does this NOT prove?

- Not silicon. Not a SKY130 / custom MOS TIA.
- OPA189 is a **vendor macromodel** in SPICE (mixed-level). Real silicon op-amps will differ (offset, Ib, temp).
- Not Network F, not a language model, not yield.
- Experiment 65/66: analog 1 mV in SPICE held −40 °C to 70 °C with **ideal** discrete R; 85 °C was class-only. Hardware TCR is **UNKNOWN — HARDWARE TEST REQUIRED**.
- Coarse E96 is not analog-accurate.

## Open this package in order

1. **`BUILD_MVP_H1_STEP_BY_STEP.md`** (human build path)
2. `MVP_H1_HARDWARE_READINESS_GATE.md` and `MVP_H1_AUDIT_FINDINGS.md`
3. `MVP_H1_CONNECTION_TABLE.csv` while wiring
4. `MVP_H1_BRINGUP_AND_TEST.md` then `MVP_H1_DEMO_PROTOCOL.md`
5. This file and `schematics/00_top.svg` for hierarchy only

## Package index

| File | Deliverable |
| --- | --- |
| `BUILD_MVP_H1_STEP_BY_STEP.md` | **Authoritative human build path** |
| `MVP_H1_CONNECTION_TABLE.csv` | Pin-level wiring |
| `MVP_H1_BRINGUP_AND_TEST.md` | Stages 0–6 |
| `MVP_H1_DEMO_PROTOCOL.md` | Four-state XOR demo |
| `MVP_H1_MEASUREMENT_LOG_TEMPLATE.csv` | Machine-readable log |
| `MVP_H1_ACCEPTANCE_CRITERIA.md` | Levels A / B / C |
| `MVP_H1_FINAL_BOM_AUDITED.csv` | Electrical BOM |
| `MVP_H1_PURCHASE_BOM.csv` | Consolidated purchase lines |
| `MVP_H1_PURCHASE_RESISTORS.csv` | 60 physical 0.1% realizations |
| `MVP_H1_PURCHASE_GATE.md` | What is safe / verify / do-not-buy |
| `MVP_H1_CLICK_TO_BUY.csv` | **One product-page URL per part (buy this)** |
| `MVP_H1_CROATIA_BUY_LIST.md` | How to check out from Croatia |
| `MVP_H1_PURCHASE_CHECKLIST.md` | Human checkout list |
| `MVP_H1_LAYOUT_SPEC.md` | PCB / proto layout (no fabricated board) |
| `MVP_H1_HARDWARE_READINESS_GATE.md` | Order / assemble / power / demo |
| `MVP_H1_AUDIT_FINDINGS.md` | Blockers / warnings |
| `README_BUILD_THIS.md` | Package overview |
| `FROZEN_PROVENANCE.md` / `.json` | Frozen hashes (do not edit `physical_design/xor_2_4_1/`) |
| `schematics/*.svg` | Hierarchical schematic drawings |
| `schematic_connectivity.md` | Every neural connection, transcribed from the frozen netlist |
| `schematic_nets.json` | Machine hierarchy notes |
| `kicad_import_notes.md` | KiCad was not generated (`kicad-cli` missing) |
| `opa189_pinout.md` | TI SBOS830 package pins |
| `hardware_traceability.md` | SPICE node → schematic → test point |
| `BOM.csv` / `BOM.md` | Line-item bill of materials |
| `resistor_implementation.csv` / `.md` | 0.1% E192 realizations of compiled ohms |
| `resistor_shopping.csv` | Unique E192 kit quantities |
| `resistor_combos.json` | Combo search dump |
| `power_plan.md` | ±15 V, current, grounding, decoupling |
| `capacitor_audit.md` | 1 pF = class C, DNP |
| `input_interface.md` | Switches / DAC |
| `reference_voltage.md` | 1.000 V (ideal in SPICE) |
| `output_interface.md` | `TP_O1LIN` analog + optional class |
| `test_point_map.md` | Expected voltages |
| `assembly_strategy.md` | No solderless breadboard; one hierarchical PCB |
| `assembly_procedure.md` | Stages 0–9 |
| `hardware_acceptance_test.md` | Analog vs class, separately |
| `debugging_guide.md` | Failure paths |
| `simulation_to_hardware_risks.md` | SPICE vs hardware labels |
| `simulation_baseline.md` | Settings + four-state node table |
| `hardware_correlation_template.csv` | Lab fill-in sheet |
| `spice_correlation_raw.json` | Raw replay numbers |
