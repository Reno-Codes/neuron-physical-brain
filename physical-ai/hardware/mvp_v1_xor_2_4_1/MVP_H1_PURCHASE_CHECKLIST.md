# MVP-H1 purchase checklist

Print this. Do not buy the frozen compiler E96 BOM.

## Before any cart

- [ ] Frozen `netlist.cir` hash is still `28dccd8121a1032d69a2b08633737db0b2f10c8996f68ed2271520ec58c3b9cb`
- [ ] Purchasing from `MVP_H1_PURCHASE_BOM.csv` / `MVP_H1_PURCHASE_RESISTORS.csv`, not `physical_design/xor_2_4_1/BOM.csv`
- [ ] Dual ±15 V supply already available, **≥ 100 mA/rail capability** (headroom, not a 100 mA load target)
- [ ] Calibrated DMM available to measure `TP_VREF` and `TP_O1LIN`
- [ ] 1.000 V plan: lab calibrator **or** a later-verified reference IC — not a random module

## Op-amps (only identity-verified line)

- [ ] Search authorized distributor / TI for **`OPA189ID`** or **`OPA189IDR`**
- [ ] Package is **SOIC-8 (D)**, not SOT-23
- [ ] Qty **20**
- [ ] Did **not** add `OPA189IDBVR`
- [ ] Did **not** substitute another op-amp
- [ ] Write the exact orderable and date on this sheet: _______________

## Diodes

- [ ] Type **1N4148**, prefer **DO-35**, band = cathode
- [ ] Qty **16** (8 + 8 spare)
- [ ] Exact MPN confirmed on the distributor page: _______________
- [ ] If SOD-123: I will assemble by **band**, not by SPICE pin 1

## Resistors 0.1% (do this as one kit)

For each line in `resistor_shopping.csv`, confirm value / 0.1% / thin film / 0805 or 1206 / 50 V / 0.1 W:

- [ ] 10 kΩ × **37** (31 stuffed + 6 spare)
- [ ] 203 Ω × 3
- [ ] 750 Ω × 3
- [ ] 976 Ω × 3
- [ ] 6.65 kΩ × 3
- [ ] 6.73 kΩ × 3
- [ ] 7.68 kΩ × 3
- [ ] 8.35 kΩ × 3
- [ ] 9.09 kΩ × 3
- [ ] 9.2 kΩ × 3
- [ ] 9.53 kΩ × 3
- [ ] 11.8 kΩ × 3
- [ ] 21.5 kΩ × 3
- [ ] 24.9 kΩ × 3
- [ ] 31.6 kΩ × 3
- [ ] 34 kΩ × 3
- [ ] 36.1 kΩ × 3
- [ ] 37 kΩ × 3
- [ ] 41.7 kΩ × 3
- [ ] 42.7 kΩ × 3
- [ ] 49.9 kΩ × 3
- [ ] 54.9 kΩ × 3
- [ ] 57.6 kΩ × 3
- [ ] 105 kΩ × 3
- [ ] 109 kΩ × 3
- [ ] 160 kΩ × 3
- [ ] 180 kΩ × 3
- [ ] 835 kΩ × 3
- [ ] 1.3 MΩ × 3
- [ ] **5.9 MΩ × 3** (`Ro1b_B` — do not substitute 6.04 MΩ E96)
- [ ] No line is a coarse E96 snap of a weight/bias from the frozen BOM

Write distributor resistor series (e.g. a 0.1% thin-film family you actually clicked): _______________

## Capacitors and hardware

- [ ] 10 µF ≥ 35 V × 4
- [ ] 100 nF X7R ≥ 50 V 0805 × 40
- [ ] **Zero** 1 pF “neural” capacitors
- [ ] `J_PWR` +15 / GND / −15
- [ ] 2× SPDT (or skip if DAC)
- [ ] Test points including **`TP_O1LIN`**

## After the boxes arrive

- [ ] Count OPA189: SOIC-8 marking matches TI
- [ ] Measure a sample of 10 kΩ and the 5.9 MΩ parts on the DMM
- [ ] First assembly: **Stage 0 continuity only** (`MVP_H1_BRINGUP_AND_TEST.md`) — do not apply ±15 V to a fully stuffed untested board
