# Power plan

SPICE used ideal `Vdd = +15 V` and `Vss = −15 V`. Hardware must provide real dual rails. Do not redesign the neural circuit for single-supply 5 V.

## Current (measured in this package)

UIC TRAN 2 ms, frozen netlist, 27 °C implied:

| State | i(Vdd) (into source) | \|I+| from +15 V | i(Vss) | \|I−\| into −15 V |
| --- | ---: | ---: | ---: | ---: |
| 00 | −21.05 mA | 21.05 mA | +21.15 mA | 21.15 mA |
| 01 | −22.02 mA | 22.02 mA | +22.24 mA | 22.24 mA |
| 10 | −22.11 mA | 22.11 mA | +22.34 mA | 22.34 mA |
| 11 | −21.95 mA | 21.95 mA | +22.48 mA | 22.48 mA |

About **1.3–1.4 mA per OPA189** in the macromodel (this package’s SPICE current).

TI SBOS830 (Rev I): Iq per amplifier **typical 1.3 mA, max 1.7 mA** at 25 °C; **max 1.8 mA** over −40 °C to 125 °C. 16 × 1.7 mA ≈ **27 mA** plus load (plus `U_VREFBUF`). Real hardware may exceed the macromodel.

## Budget (use this)

| Item | Value |
| --- | --- |
| Recommended supply | Dual tracking ±15 V |
| Current rating | **≥ 100 mA per rail** (first prototype) |
| Power in analog section | ~ 15 V × 25 mA × 2 ≈ 0.75 W typical |
| Connector | 3-pin: +15, GND, −15 (4 mm banana or terminal block) |
| Absolute max (OPA189) | follow SBOS830; do not exceed ±18 V |

**UNKNOWN — HARDWARE VALIDATION REQUIRED:** inrush, short-circuit of an output, and 85 °C Iq.

## Topology

Bench dual supply is acceptable for MVP v1. Do not switch-mode next to summing nodes without LC filtering.

Optional onboard: two linear regulators from ±18 V unregulated. That is support circuitry, not a neural change. If used, verify dropout and noise. **PROCUREMENT VERIFICATION REQUIRED** for regulator MPNs.

## Ground

- Single analog ground plane or a star at the power entry.
- All IN+/TIA grounds (`IN+ = 0` in SPICE) return to that analog ground.
- Do not share that ground with a noisy USB MCU without a star/ferrite.
- Input sources, DMM negative, and VREF ground must be the **same** analog GND.

## Decoupling

- 10 µF ≥ 35 V bulk on +15 and on −15 at the connector (`C_VDD_BULK`, `C_VSS_BULK`).
- 100 nF X7R ≥ 50 V on **each** package V+ and V− pin to GND, < 5 mm.
- Neural 1 pF caps: omit (`capacitor_audit.md`).

## Power-up

1. Confirm no shorts VDD–GND, VSS–GND, VDD–VSS.
2. Enable ±15 V together if the supply allows.
3. Confirm `TP_P15` = +15.0 V ± 0.2 V, `TP_M15` = −15.0 V ± 0.2 V, current < 50 mA with inputs at 0 V (empty-ish).
4. Then apply VREF, then IN1/IN2.

If current > 80 mA at idle: stop. Likely reversed op-amp, rail short, or oscillation.
