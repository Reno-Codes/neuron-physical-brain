# KiCad / CAD import

`kicad-cli` is **not** installed in this environment. A native `.kicad_sch` was **not** generated (unreliable without the tool).

## What you have instead

| File | Use |
| --- | --- |
| `schematics/00_top.svg` | hierarchical top |
| `schematics/01_power_ref_input.svg` | power, VREF, inverts |
| `schematics/02_hidden_neuron.svg` | one hidden neuron (h1 names; clone h2–h4) |
| `schematics/03_output_neuron.svg` | output TIA |
| `schematic_connectivity.md` | **human wiring list** (every pin / resistor) |
| `schematic_nets.json` | machine hierarchy notes |
| `opa189_pinout.md` | TI SBOS830 package pins (not SVG pin numbers) |
| `hardware_traceability.md` | SPICE node → TP |
| `../../physical_design/xor_2_4_1/netlist.cir` | frozen source of the wiring list |

## Manual CAD import (remaining work)

1. Create KiCad project `mvp_v1_xor_2_4_1`.
2. Hierarchical sheets: PWR, IN, H1, H2, H3, H4, OUT.
3. Place OPA189 / OPA4189 from the official TI KiCad library if available; otherwise a 5-pin analog op-amp symbol with pins IN+ IN− V+ V− OUT.
4. Net names **must** equal SPICE nodes (`h1lin`, `o1lin`, …).
5. Annotate resistors with the frozen refs (`Rh1w1`, …).
6. Do not auto-annotate to R1…R99 without a map.

Preferred CAD deliverables would be KiCad + PDF + PNG. This environment has **no `kicad-cli`**, **no Inkscape**, and **no SVG rasterizer**, so the schematic export is **SVG** (`schematics/*.svg`) plus `schematic_connectivity.md`.

Until that CAD exists, **build from**:

1. `schematic_connectivity.md` (every pin and resistor node)
2. `schematics/*.svg` (hierarchy)
3. `hardware_traceability.md`
4. `opa189_pinout.md` (package pins; **not** the SVG)
5. Frozen `physical_design/xor_2_4_1/netlist.cir` only if a line is disputed

Do not start by reconstructing connectivity from the `.cir` file.
