# MVP-H1 hardware readiness audit findings

Audit of `physical_design/xor_2_4_1/` against `hardware/mvp_v1_xor_2_4_1/`.
Frozen files were not modified.

Open BLOCKERS: **0**
WARNINGS: **8**
INFORMATION: **4**

| ID | Severity | Item | Detail |
| --- | --- | --- | --- |
| A001 | INFORMATION | frozen netlist hash | matches required 28dccd8121a1032d69a2b08633737db0b2f10c8996f68ed2271520ec58c3b9cb |
| A002 | INFORMATION | xor_model.npz hash | matches provenance |
| W001 | WARNING | manufacturer SKUs | No verified reel MPNs in project evidence. Electrical specs only. |
| W002 | WARNING | frozen BOM.csv E96 column | physical_design BOM lists nearest E96. Do not buy those snaps (Exp67). |
| W003 | WARNING | VREF ideal in SPICE | Must provide a real 1.000 V source. First demo: lab calibrator + buffer. |
| W004 | WARNING | no native KiCad / PCB | Build from connection table. Layout spec is not a fabricated board. |
| W005 | WARNING | SVG pin numbers | schematics/*.svg are hierarchical drawings. Package pins are opa189_pinout.md. |
| W006 | WARNING | analog 1 mV vs SPICE | DEMONSTRATED IN SPICE only. Hardware Level B is not assumed. |
| W007 | WARNING | hardware settling time | SPICE recorded at 2 ms. Hardware wait >= 10 ms. UNKNOWN if longer needed. |
| W008 | WARNING | Ro1b 6.06 MΩ leakage | Class-0 millivolt floor. Keep flux off this node. |
| I001 | INFORMATION | 1 pF SPICE caps | Class C DNP. Do not place. |
| I002 | INFORMATION | h3/h4 ReLU | On all four XOR states H3_OUT and H4_OUT stay ~0 V. LIN still swings positive. Normal. |

## Closed documentation gaps (this audit)

These were build-path gaps, not neural-design errors. They are closed by new files in this folder:

- No single human procedure → `BUILD_MVP_H1_STEP_BY_STEP.md`
- No pin-to-pin wiring table → `MVP_H1_CONNECTION_TABLE.csv`
- No staged bring-up independent of compiler docs → `MVP_H1_BRINGUP_AND_TEST.md`
- No demo / acceptance split → `MVP_H1_DEMO_PROTOCOL.md`, `MVP_H1_ACCEPTANCE_CRITERIA.md`
- No audited purchase BOM → `MVP_H1_FINAL_BOM_AUDITED.csv`
- No layout specification → `MVP_H1_LAYOUT_SPEC.md`
- No explicit gate → `MVP_H1_HARDWARE_READINESS_GATE.md`

Default first-build package is **16× OPA189 SOIC-8 (D) + 1× VREFBUF**. Quad mapping is optional and documented; do not mix pinouts.
