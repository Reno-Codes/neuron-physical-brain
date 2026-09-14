"""Emit purchase CSVs. Does not modify frozen xor_2_4_1 files."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HW = ROOT / "hardware" / "mvp_v1_xor_2_4_1"
FROZEN = ROOT / "physical_design" / "xor_2_4_1"
UNVERIFIED = "UNVERIFIED — DO NOT PURCHASE YET"
OPA_STATUS = "IDENTITY VERIFIED — CONFIRM DISTRIBUTOR STOCK"
E96_REJECT = "Not coarse E96 (Exp67 rejected for analog). Frozen E96 listed only to prove we did not buy it."


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fmt(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        value = float(round(value))
    if value >= 1e6:
        return f"{value / 1e6:g}M"
    if value >= 1000:
        return f"{value / 1000:g}k"
    return f"{value:g}"


def main() -> None:
    got = sha256(FROZEN / "netlist.cir")
    need = "28dccd8121a1032d69a2b08633737db0b2f10c8996f68ed2271520ec58c3b9cb"
    if got != need:
        raise SystemExit(f"frozen hash mismatch {got}")

    combos = json.loads((HW / "resistor_combos.json").read_text(encoding="utf-8"))
    shop = list(csv.DictReader((HW / "resistor_shopping.csv").open(encoding="utf-8")))
    spare_by_val = {}
    for s in shop:
        stuffed = int(s["qty_minimum"])
        buy = int(s["qty_buy_suggested"])
        spare_by_val[s["e192_value"]] = max(0, buy - stuffed)

    r_rows = []
    for c in combos:
        kind = c["preferred"]["kind"]
        parts = c["preferred"]["parts"]
        realized = c["preferred"]["realized"]
        err_pct = 100.0 * c["preferred"]["rel_error"]
        e96 = c["e96_ohm"]
        used_e96 = abs(e96 - realized) < 1e-6 and abs(c["exact_ohm"] - e96) > 1e-3 and kind == "single"
        if kind == "single":
            phys = [(c["ref"], parts[0])]
        else:
            phys = [(f"{c['ref']}_A", parts[0]), (f"{c['ref']}_B", parts[1])]
        for ref, part in phys:
            val = fmt(part)
            r_rows.append(
                {
                    "Reference": ref,
                    "Frozen_target_ohm": f"{c['exact_ohm']:.15g}",
                    "Implementation": kind,
                    "Part_values": c["parts_fmt"],
                    "This_part_ohm": f"{part:.15g}",
                    "Effective_ohm": f"{realized:.15g}",
                    "Error_pct": f"{err_pct:.6g}",
                    "Tolerance": "0.1%",
                    "Quantity": 1,
                    "Spare_quantity": spare_by_val.get(val, 2),
                    "Manufacturer": "",
                    "MPN": "",
                    "Distributor": "",
                    "Verification_status": UNVERIFIED,
                    "Notes": (
                        f"compiled {c['ref']}; "
                        f"frozen E96 nearest was {e96:g} (DO NOT BUY that snap). "
                        f"{E96_REJECT} "
                        f"{'WARNING: this single equals E96 by coincidence' if used_e96 else ''}"
                    ),
                }
            )

    fields = [
        "Reference",
        "Frozen_target_ohm",
        "Implementation",
        "Part_values",
        "This_part_ohm",
        "Effective_ohm",
        "Error_pct",
        "Tolerance",
        "Quantity",
        "Spare_quantity",
        "Manufacturer",
        "MPN",
        "Distributor",
        "Verification_status",
        "Notes",
    ]
    with (HW / "MVP_H1_PURCHASE_RESISTORS.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(r_rows)

    # consolidated unique resistor buy list
    uniq: Counter[str] = Counter()
    for row in r_rows:
        uniq[fmt(float(row["This_part_ohm"]))] += 1

    bom_fields = [
        "reference_designator",
        "required_quantity",
        "exact_electrical_value",
        "tolerance",
        "voltage_rating",
        "power_rating",
        "package",
        "recommended_quantity_including_spares",
        "manufacturer",
        "manufacturer_part_number",
        "distributor",
        "procurement_status",
        "notes",
    ]
    bom = []

    def add(**kw):
        bom.append({k: kw.get(k, "") for k in bom_fields})

    add(
        reference_designator="Xinv1…Xo1tia + U_VREFBUF (17 channels)",
        required_quantity=17,
        exact_electrical_value="OPA189 zero-drift op-amp",
        tolerance="",
        voltage_rating="±15 V used; TI SBOS830 supply 4.5 V to 36 V; do not exceed ±18 V",
        power_rating="Iq typ 1.3 mA / max 1.7 mA per amp at 25 C (SBOS830)",
        package="SOIC-8 (D) 4.90 mm × 3.90 mm",
        recommended_quantity_including_spares=20,
        manufacturer="Texas Instruments",
        manufacturer_part_number="OPA189ID (tube) or OPA189IDR (reel)",
        distributor="TI or authorized distributor — live stock not checked in this audit",
        procurement_status=OPA_STATUS,
        notes=(
            "Official orderables from TI SBOS830 Rev I packaging table. "
            "Do not buy OPA189IDBVR (SOT-23-5): pinout differs from the SOIC connection table. "
            "Do not substitute another op-amp. Confirm stock before checkout."
        ),
    )
    add(
        reference_designator="Xh1d1…Xh4d2",
        required_quantity=8,
        exact_electrical_value="1N4148 silicon switching diode",
        tolerance="",
        voltage_rating="VR typically 75–100 V class (Vishay/Nexperia/Diodes datasheets); SPICE BV=75",
        power_rating="signal diode; circuit current is << IF rating",
        package="DO-35 axial preferred for first build (band = cathode)",
        recommended_quantity_including_spares=16,
        manufacturer="JEDEC type 1N4148 (multi-source)",
        manufacturer_part_number="",
        distributor="",
        procurement_status=UNVERIFIED,
        notes=(
            "Type is specified. A cart SKU was not live-verified. "
            "Official manufacturer examples exist (e.g. Vishay DS lists 1N4148-TAP / 1N4148TR; "
            "Diodes Inc DS lists 1N4148-T) — confirm the exact orderable at an authorized distributor. "
            "SOD-123 1N4148W is electrically the same family but pin-1 is often the cathode; "
            "follow the body band, not SPICE pin 1. Prefer DO-35 for MVP-H1."
        ),
    )
    add(
        reference_designator="R_NEURAL_0p1pct_kit",
        required_quantity=60,
        exact_electrical_value="see MVP_H1_PURCHASE_RESISTORS.csv",
        tolerance="0.1%",
        voltage_rating="50 V",
        power_rating="0.1 W min",
        package="0805 or 1206 thin film; TCR <=25 ppm/C preferred",
        recommended_quantity_including_spares=60 + sum(spare_by_val.get(v, 2) for v in uniq),
        manufacturer="",
        manufacturer_part_number="",
        distributor="",
        procurement_status=UNVERIFIED,
        notes="Do not buy physical_design/xor_2_4_1/BOM.csv E96 snaps. Buy to the E192 values listed.",
    )
    add(
        reference_designator="C_VDD_BULK + C_VSS_BULK",
        required_quantity=2,
        exact_electrical_value="10 uF",
        tolerance="20%",
        voltage_rating=">=35 V",
        power_rating="",
        package="electrolytic or 1210 ceramic",
        recommended_quantity_including_spares=4,
        manufacturer="",
        manufacturer_part_number="",
        distributor="",
        procurement_status=UNVERIFIED,
        notes="Hardware decouple only. Not a neural weight.",
    )
    add(
        reference_designator="C_*_VP / C_*_VN",
        required_quantity=34,
        exact_electrical_value="100 nF X7R",
        tolerance="10%",
        voltage_rating=">=50 V",
        power_rating="",
        package="0805",
        recommended_quantity_including_spares=40,
        manufacturer="",
        manufacturer_part_number="",
        distributor="",
        procurement_status=UNVERIFIED,
        notes="One pair per OPA189 package. Not the frozen 1 pF caps.",
    )
    add(
        reference_designator="C_1PF_SPICE",
        required_quantity=0,
        exact_electrical_value="1 pF",
        tolerance="",
        voltage_rating="",
        power_rating="",
        package="DNP",
        recommended_quantity_including_spares=0,
        manufacturer="",
        manufacturer_part_number="DNP",
        distributor="",
        procurement_status="DO NOT PURCHASE",
        notes="Class C SPICE-only.",
    )
    add(
        reference_designator="VREF_SRC",
        required_quantity=1,
        exact_electrical_value="1.000 V buffered",
        tolerance="0.05% analog goal",
        voltage_rating="",
        power_rating="",
        package="calibrated lab source into U_VREFBUF (preferred first demo)",
        recommended_quantity_including_spares=1,
        manufacturer="",
        manufacturer_part_number="",
        distributor="",
        procurement_status=UNVERIFIED,
        notes="Do not buy an uncalibrated '1 V module'. Measure TP_VREF with a calibrated DMM.",
    )
    add(
        reference_designator="SW_IN1 SW_IN2 J_PWR J_IN TP_*",
        required_quantity=32,
        exact_electrical_value="electromechanical / test",
        tolerance="",
        voltage_rating=">=15 V where applicable",
        power_rating="",
        package="see audited BOM",
        recommended_quantity_including_spares=32,
        manufacturer="",
        manufacturer_part_number="",
        distributor="",
        procurement_status=UNVERIFIED,
        notes="2 switches + 2 connectors + 27 test points + optional extras. Any equivalent hardware is fine.",
    )
    add(
        reference_designator="PSU_DUAL",
        required_quantity=1,
        exact_electrical_value="±15 V dual tracking",
        tolerance="±0.2 V on rails is the Stage 1 band",
        voltage_rating=">=15 V",
        power_rating=">=100 mA per rail HEADROOM (expected draw ~tens of mA)",
        package="bench supply",
        recommended_quantity_including_spares=1,
        manufacturer="",
        manufacturer_part_number="",
        distributor="",
        procurement_status="EQUIPMENT — CAPABILITY SPEC ONLY",
        notes="Not a stuffed BOM part. 100 mA is headroom, not expected Iq.",
    )

    with (HW / "MVP_H1_PURCHASE_BOM.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=bom_fields)
        w.writeheader()
        w.writerows(bom)

    (HW / "MVP_H1_PURCHASE_COUNTS.json").write_text(
        json.dumps(
            {
                "frozen_netlist_sha256": got,
                "physical_resistors_stuffed": len(r_rows),
                "unique_resistor_values": len(uniq),
                "resistor_spares_suggested": sum(spare_by_val.get(v, 2) for v in uniq),
                "opa189_stuffed": 17,
                "opa189_buy": 20,
                "diodes_stuffed": 8,
                "diodes_buy": 16,
                "max_resistor_error_pct": max(float(r["Error_pct"]) for r in r_rows),
                "all_resistors_within_0p1pct": all(float(r["Error_pct"]) <= 0.1 for r in r_rows),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print("purchase files written", len(r_rows), "resistors")


if __name__ == "__main__":
    main()
