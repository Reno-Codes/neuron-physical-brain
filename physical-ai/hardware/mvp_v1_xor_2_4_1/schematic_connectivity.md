# Schematic connectivity (human-readable)

This is the **authoritative wiring list** for MVP-H1 neural topology.
It is a transcription of frozen `physical_design/xor_2_4_1/netlist.cir`.
Hardware net names **are** the SPICE node names (uppercase in silkscreen is allowed; do not rename).

OPA189 SPICE order: `IN+ IN- VCC VEE OUT`. Package pin numbers: `opa189_pinout.md` (TI SBOS830).
1N4148: anode = pin 1, cathode = pin 2.

Do **not** place the 1 pF capacitors (`capacitor_audit.md`).

## Unity inverters and output TIA — op-amp pins

| Instance | IN+ | IN- | V+ | V- | OUT | Role |
| --- | --- | --- | --- | --- | --- | --- |
| `Xinv1` | `0` | `inv1inn` | `vdd` | `vss` | `in1n` | unity invert IN1 -> IN1N |
| `Xinv2` | `0` | `inv2inn` | `vdd` | `vss` | `in2n` | unity invert IN2 -> IN2N |
| `Xinvref` | `0` | `invrefinn` | `vdd` | `vss` | `vrefn` | unity invert VREF -> VREFN |
| `Xh1tia` | `0` | `h1sum` | `vdd` | `vss` | `h1lin` | hidden h1 TIA (inverts; H1_LIN = -z1) |
| `Xh1relu` | `0` | `h1rinn` | `vdd` | `vss` | `h1amp` | hidden h1 rectifier op-amp |
| `Xh1inv` | `0` | `h1invinn` | `vdd` | `vss` | `h1yn` | unity invert H1_OUT -> H1_YN |
| `Xh2tia` | `0` | `h2sum` | `vdd` | `vss` | `h2lin` | hidden h2 TIA |
| `Xh2relu` | `0` | `h2rinn` | `vdd` | `vss` | `h2amp` | hidden h2 rectifier op-amp |
| `Xh2inv` | `0` | `h2invinn` | `vdd` | `vss` | `h2yn` | unity invert H2_OUT -> H2_YN |
| `Xh3tia` | `0` | `h3sum` | `vdd` | `vss` | `h3lin` | hidden h3 TIA |
| `Xh3relu` | `0` | `h3rinn` | `vdd` | `vss` | `h3amp` | hidden h3 rectifier op-amp |
| `Xh3inv` | `0` | `h3invinn` | `vdd` | `vss` | `h3yn` | unity invert H3_OUT -> H3_YN |
| `Xh4tia` | `0` | `h4sum` | `vdd` | `vss` | `h4lin` | hidden h4 TIA |
| `Xh4relu` | `0` | `h4rinn` | `vdd` | `vss` | `h4amp` | hidden h4 rectifier op-amp |
| `Xh4inv` | `0` | `h4invinn` | `vdd` | `vss` | `h4yn` | unity invert H4_OUT -> H4_YN |
| `Xo1tia` | `0` | `o1sum` | `vdd` | `vss` | `o1lin` | output TIA (does not invert math; O1_LIN = +y) |

## Resistors (compiled)

| Ref | Node A | Node B | Exact ohm |
| --- | --- | --- | ---: |
| `Rinv1in` | `in1` | `inv1inn` | 10000 |
| `Rinv1f` | `in1n` | `inv1inn` | 10000 |
| `Rinv2in` | `in2` | `inv2inn` | 10000 |
| `Rinv2f` | `in2n` | `inv2inn` | 10000 |
| `Rinvrefin` | `vref` | `invrefinn` | 10000 |
| `Rinvreff` | `vrefn` | `invrefinn` | 10000 |
| `Rh1w1` | `in1` | `h1sum` | 8346.15342020291 |
| `Rh1w2` | `in2n` | `h1sum` | 6653.68052854338 |
| `Rh1b` | `vrefn` | `h1sum` | 37976.8116137404 |
| `Rh1f` | `h1lin` | `h1sum` | 10000 |
| `Rh1r1` | `h1lin` | `h1rinn` | 10000 |
| `Rh1rf` | `h1y` | `h1rinn` | 10000 |
| `Rh1rl` | `h1y` | `0` | 10000 |
| `Rh1invin` | `h1y` | `h1invinn` | 10000 |
| `Rh1invf` | `h1yn` | `h1invinn` | 10000 |
| `Rh2w1` | `in1n` | `h2sum` | 7539.64567142449 |
| `Rh2w2` | `in2` | `h2sum` | 9292.75696435857 |
| `Rh2b` | `vrefn` | `h2sum` | 66315.5606469353 |
| `Rh2f` | `h2lin` | `h2sum` | 10000 |
| `Rh2r1` | `h2lin` | `h2rinn` | 10000 |
| `Rh2rf` | `h2y` | `h2rinn` | 10000 |
| `Rh2rl` | `h2y` | `0` | 10000 |
| `Rh2invin` | `h2y` | `h2invinn` | 10000 |
| `Rh2invf` | `h2yn` | `h2invinn` | 10000 |
| `Rh3w1` | `in1n` | `h3sum` | 5125.48418304015 |
| `Rh3w2` | `in2n` | `h3sum` | 7679.43278733945 |
| `Rh3b` | `vrefn` | `h3sum` | 25915.6966255384 |
| `Rh3f` | `h3lin` | `h3sum` | 10000 |
| `Rh3r1` | `h3lin` | `h3rinn` | 10000 |
| `Rh3rf` | `h3y` | `h3rinn` | 10000 |
| `Rh3rl` | `h3y` | `0` | 10000 |
| `Rh3invin` | `h3y` | `h3invinn` | 10000 |
| `Rh3invf` | `h3yn` | `h3invinn` | 10000 |
| `Rh4w1` | `in1n` | `h4sum` | 25650.2210777918 |
| `Rh4w2` | `in2n` | `h4sum` | 31621.2940385193 |
| `Rh4b` | `vrefn` | `h4sum` | 22716.4148046838 |
| `Rh4f` | `h4lin` | `h4sum` | 10000 |
| `Rh4r1` | `h4lin` | `h4rinn` | 10000 |
| `Rh4rf` | `h4y` | `h4rinn` | 10000 |
| `Rh4rl` | `h4y` | `0` | 10000 |
| `Rh4invin` | `h4y` | `h4invinn` | 10000 |
| `Rh4invf` | `h4yn` | `h4invinn` | 10000 |
| `Ro1w1` | `h1yn` | `o1sum` | 9197.82154480464 |
| `Ro1w2` | `h2yn` | `o1sum` | 9245.04749840197 |
| `Ro1w3` | `h3y` | `o1sum` | 55155.9696790035 |
| `Ro1w4` | `h4y` | `o1sum` | 51512.4284437413 |
| `Ro1b` | `vrefn` | `o1sum` | 6059355.21666454 |
| `Ro1f` | `o1lin` | `o1sum` | 10000 |

## Diodes

| Ref | Anode | Cathode |
| --- | --- | --- |
| `Xh1d1` | `h1rinn` | `h1amp` |
| `Xh1d2` | `h1amp` | `h1y` |
| `Xh2d1` | `h2rinn` | `h2amp` |
| `Xh2d2` | `h2amp` | `h2y` |
| `Xh3d1` | `h3rinn` | `h3amp` |
| `Xh3d2` | `h3amp` | `h3y` |
| `Xh4d1` | `h4rinn` | `h4amp` |
| `Xh4d2` | `h4amp` | `h4y` |

## SPICE capacitors (do not fit)

| Ref | Node A | Node B | Value | Placement |
| --- | --- | --- | --- | --- |
| `Cinv1` | `in1n` | `0` | 1e-12 F | **DNP** class C |
| `Cinv2` | `in2n` | `0` | 1e-12 F | **DNP** class C |
| `Cinvref` | `vrefn` | `0` | 1e-12 F | **DNP** class C |
| `Ch1tia` | `h1lin` | `0` | 1e-12 F | **DNP** class C |
| `Ch1rl` | `h1y` | `0` | 1e-12 F | **DNP** class C |
| `Ch1inv` | `h1yn` | `0` | 1e-12 F | **DNP** class C |
| `Ch2tia` | `h2lin` | `0` | 1e-12 F | **DNP** class C |
| `Ch2rl` | `h2y` | `0` | 1e-12 F | **DNP** class C |
| `Ch2inv` | `h2yn` | `0` | 1e-12 F | **DNP** class C |
| `Ch3tia` | `h3lin` | `0` | 1e-12 F | **DNP** class C |
| `Ch3rl` | `h3y` | `0` | 1e-12 F | **DNP** class C |
| `Ch3inv` | `h3yn` | `0` | 1e-12 F | **DNP** class C |
| `Ch4tia` | `h4lin` | `0` | 1e-12 F | **DNP** class C |
| `Ch4rl` | `h4y` | `0` | 1e-12 F | **DNP** class C |
| `Ch4inv` | `h4yn` | `0` | 1e-12 F | **DNP** class C |
| `Co1tia` | `o1lin` | `0` | 1e-12 F | **DNP** class C |

## Hardware-only (not in frozen netlist)

| Item | Connection |
| --- | --- |
| `J_PWR` | `vdd`=+15 V, `0`=GND, `vss`=−15 V |
| `C_VDD_BULK` | `vdd` to `0` |
| `C_VSS_BULK` | `vss` to `0` |
| 100 nF per package | each OPA189 V+ and V− to `0` |
| `U_VREF` + `U_VREFBUF` | drive `vref`; SPICE used ideal 1 V |
| `SW_IN1` / DAC | `in1` to `0` or `vref` |
| `SW_IN2` / DAC | `in2` to `0` or `vref` |
| `TP_O1LIN` | `o1lin` |

Block diagrams: `schematics/*.svg`. CAD import: `kicad_import_notes.md`.
