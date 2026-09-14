# Assembly strategy

## Decision

**Do not use a solderless breadboard** for the first analog-accurate XOR.

Reasons: 16 precision op-amps, 6.06 MΩ bias, ±15 V, 0.1% resistors, TIA virtual grounds at microvolts, contact resistance and leakage that Experiment 67-level analog error already cannot afford.

## Recommended first prototype — **MVP-H1-PCB**

**One 2-layer PCB (4-layer preferred if ground noise appears), hierarchical layout, staged stuffing.**

- Silkscreen boxes: PWR | IN+INV | H1 | H2 | H3 | H4 | OUT
- Stuff in the same order as `assembly_procedure.md`
- Keep summing nodes (`H*_SUM`, `O1_SUM`) short, guard with GND
- Test points on 1.0 mm or 1.27 mm headers, labeled with SPICE names
- 100 mil grid is fine; this is not a dense digital board

This is still “modular” for debug (you can leave H3/H4 unstuffed) without analog cables between boards.

## Acceptable alternative — soldered modules

Four identical hidden-neuron PCBs + power/input PCB + output PCB, **soldered** 0.1" headers, GND in every interconnect. Higher parasitic risk. Use only if you want to bring up a single neuron on the bench first.

## Rejected for analog-accurate v1

| Approach | Why not |
| --- | --- |
| Solderless breadboard | Leakage, thermals, contact R, stray C on TIA −input |
| Dead-bug over a ground plane | Possible for one invert; miserable for 16 amps |
| MCU-only “XOR” | Violates the MVP rule |

## Layout notes (not a neural change)

- OPA189 IN+ at GND: short to plane
- Keep 1N4148 at the rectifier op-amp
- 6.06 MΩ `Ro1b`: keep leakage paths clean (no flux, no breadboard)
- ±15 V traces away from `H*_SUM`
