# MVP-H1 physical layout specification

This is a **layout specification**, not a fabricated PCB and not a KiCad project. No `.kicad_pcb` exists in this package (`kicad_import_notes.md`).

Neural topology is unchanged. Do not move weight resistors to different nodes to shorten a trace.

---

## A / B / C — first prototype medium

| Option | Verdict |
| --- | --- |
| A. Solderless breadboard | **Reject** for analog-accurate MVP-H1 |
| B. Perfboard / soldered proto | Acceptable only if ground is a plane or a tight star and SUM nodes stay short |
| C. Hierarchical PCB (2-layer minimum, 4-layer preferred) | **Recommended** |

### Why breadboard is still wrong

- 17 precision op-amps, ±15 V, 60 thin-film resistors, 6.06 MΩ `Ro1b`
- TIA summing nodes sit at microvolts in SPICE
- Contact resistance, leakage, and stray C already exceed Experiment 67-class analog error
- 16-channel analog on jumper wire is not a 1 mV experiment and is a poor even for Level A

### Why a hierarchical PCB remains correct

- 156-line audited BOM, 312 documented connections
- Need a single analog GND, local 100 nF at every package, and labeled test points
- Staged stuffing is possible if silkscreen boxes match H1/H2/H3/H4/OUT
- Debugging access without analog patch cables between boards

Soldered modules (one hidden neuron per small PCB) are a fallback if you must bring up h2 alone. Keep GND in every interconnect.

---

## Board partition (recommended silkscreen)

```text
+---------+-----------+--------+--------+--------+--------+--------+
|  PWR    | INPUT+    |  H1    |  H2    |  H3    |  H4    |  OUT   |
|  VREF   | SIGNED    |        |        |        |        |        |
+---------+-----------+--------+--------+--------+--------+--------+
```

- **PWR / VREF:** `J_PWR`, bulk caps, `U_VREFBUF`, VREF source connector
- **INPUT + SIGNED:** `SW_IN*`, `Xinv1`, `Xinv2`, `Xinvref`, 10 kΩ pairs
- **H1…H4:** TIA + rectifier + hidden invert of that neuron
- **OUT:** `Xo1tia` and `Ro1w1…Ro1b`

Place h2 nearest the inputs if you stuff h2 first (Stage 3–4).

---

## Grounding

- One analog ground plane (4-layer: dedicated GND) or a star at `J_PWR` GND on 2-layer
- All neural OPA189 pin 3 (+IN) to that GND with a short
- VREF source GND, DMM common, and DAC GND join **only** at analog GND
- Do not share that plane with a switching USB MCU without a ferrite/star
- Guard or GND-pour around `H*_SUM` and `O1_SUM`; do not run ±15 V across those pins

---

## Supplies

- +15 and −15 as short, wide traces from `J_PWR`
- Bulk 10 µF at the connector
- 100 nF from pin 7 to GND and pin 4 to GND at **each** SOIC, < 5 mm
- Keep switching regulators off this board for v1

---

## Analog inputs and output

- IN1/IN2 as short traces from switch/DAC to the weight resistors that use them (`Rh1w1` on IN1, `Rh2w2` on IN2, …)
- IN1N/IN2N/VREFN stay in the signed block; do not daisy-chain through long cables
- `TP_O1LIN` at the output TIA pin 6; no digital GPIO on that node
- Optional comparator after a high-Z tap, never replacing the analog node

---

## High-impedance / summing nodes

Treat as sensitive:

- `inv1inn`, `inv2inn`, `invrefinn`
- `h1sum`…`h4sum`, `o1sum`
- `h*rinn`, `h*invinn`
- `Ro1b` (6.06 MΩ) and its midpoint

Rules:

- Keep Rf (`Rh*f`, `Ro1f`) immediately next to the op-amp
- Keep 1N4148 next to the rectifier op-amp
- No flux on `Ro1b`
- No extra capacitor on SUM nodes unless a later recorded experiment says so
- Do not place the frozen 1 pF SPICE caps

---

## Test points

Place 1.0 mm loops or 1.27 mm headers, labeled with the names in `test_point_map.md`, along the bottom or top edge — not buried under ICs. Required: `TP_O1LIN`, rails, VREF, IN1, IN2, each H*_LIN and H*_OUT.

---

## Component grouping

- 10 kΩ invert pairs matched and adjacent
- Series `_A`/`_B` in a straight line
- Parallel pairs sharing pads/vias of the two compiled nodes
- Decoupling on the supply pins, not on the summing pin

---

## KiCad user checklist

1. Hierarchical sheets: PWR, IN, H1, H2, H3, H4, OUT
2. Net names = SPICE names (`h1lin`, `o1lin`, …)
3. Reference designators = compiled names (`Rh1w1`, `Xh1tia`, …)
4. Import connectivity from `MVP_H1_CONNECTION_TABLE.csv` / `schematic_connectivity.md`
5. Footprints: SOIC-8 D for OPA189; SOD-123 or DO-35 for 1N4148; 0805/1206 for 0.1% R
6. ERC: every OPA189 pin 7/4 powered; pin 3 of neural amps on GND
7. Do not auto-annotate to R1…R99 without a map

There is still **no** generated PCB in this repository.
