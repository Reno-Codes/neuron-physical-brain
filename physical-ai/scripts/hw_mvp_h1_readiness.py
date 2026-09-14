"""MVP-H1 readiness tables. Does not modify frozen xor_2_4_1 files."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HW = ROOT / "hardware" / "mvp_v1_xor_2_4_1"
FROZEN = ROOT / "physical_design" / "xor_2_4_1"
MODEL = ROOT / "models" / "xor_model.npz"
PROC = "PROCUREMENT VERIFICATION REQUIRED"

OPA_ROLE = {
    "Xinv1": ("SIGNED_INV", "unity invert IN1 -> IN1N"),
    "Xinv2": ("SIGNED_INV", "unity invert IN2 -> IN2N"),
    "Xinvref": ("SIGNED_INV", "unity invert VREF -> VREFN"),
    "Xh1tia": ("H1", "hidden h1 TIA; H1_LIN = -z1"),
    "Xh1relu": ("H1", "hidden h1 rectifier op-amp"),
    "Xh1inv": ("H1", "unity invert H1_OUT -> H1_YN"),
    "Xh2tia": ("H2", "hidden h2 TIA"),
    "Xh2relu": ("H2", "hidden h2 rectifier op-amp"),
    "Xh2inv": ("H2", "unity invert H2_OUT -> H2_YN"),
    "Xh3tia": ("H3", "hidden h3 TIA"),
    "Xh3relu": ("H3", "hidden h3 rectifier op-amp"),
    "Xh3inv": ("H3", "unity invert H3_OUT -> H3_YN"),
    "Xh4tia": ("H4", "hidden h4 TIA"),
    "Xh4relu": ("H4", "hidden h4 rectifier op-amp"),
    "Xh4inv": ("H4", "unity invert H4_OUT -> H4_YN"),
    "Xo1tia": ("OUT", "output TIA; O1_LIN = +y"),
}

TP = {
    "vdd": "TP_P15",
    "vss": "TP_M15",
    "0": "TP_GND",
    "vref": "TP_VREF",
    "vrefn": "TP_VREFN",
    "in1": "TP_IN1",
    "in2": "TP_IN2",
    "in1n": "TP_IN1N",
    "in2n": "TP_IN2N",
    "h1sum": "TP_H1_SUM",
    "h1lin": "TP_H1_LIN",
    "h1y": "TP_H1_OUT",
    "h1yn": "TP_H1_YN",
    "h2sum": "TP_H2_SUM",
    "h2lin": "TP_H2_LIN",
    "h2y": "TP_H2_OUT",
    "h2yn": "TP_H2_YN",
    "h3sum": "TP_H3_SUM",
    "h3lin": "TP_H3_LIN",
    "h3y": "TP_H3_OUT",
    "h3yn": "TP_H3_YN",
    "h4sum": "TP_H4_SUM",
    "h4lin": "TP_H4_LIN",
    "h4y": "TP_H4_OUT",
    "h4yn": "TP_H4_YN",
    "o1sum": "TP_O1_SUM",
    "o1lin": "TP_O1LIN",
}

HUB = {
    "0": ("J_PWR", "GND"),
    "vdd": ("J_PWR", "+15"),
    "vss": ("J_PWR", "-15"),
    "vref": ("U_VREFBUF", "6"),
    "in1": ("SW_IN1", "COM"),
    "in2": ("SW_IN2", "COM"),
    "in1n": ("Xinv1", "6"),
    "in2n": ("Xinv2", "6"),
    "vrefn": ("Xinvref", "6"),
    "inv1inn": ("Rinv1in", "2"),
    "inv2inn": ("Rinv2in", "2"),
    "invrefinn": ("Rinvrefin", "2"),
    "h1sum": ("Xh1tia", "2"),
    "h1lin": ("Xh1tia", "6"),
    "h1rinn": ("Rh1r1", "2"),
    "h1amp": ("Xh1d1", "2"),
    "h1y": ("TP_H1_OUT", "1"),
    "h1invinn": ("Rh1invin", "2"),
    "h1yn": ("Xh1inv", "6"),
    "h2sum": ("Xh2tia", "2"),
    "h2lin": ("Xh2tia", "6"),
    "h2rinn": ("Rh2r1", "2"),
    "h2amp": ("Xh2d1", "2"),
    "h2y": ("TP_H2_OUT", "1"),
    "h2invinn": ("Rh2invin", "2"),
    "h2yn": ("Xh2inv", "6"),
    "h3sum": ("Xh3tia", "2"),
    "h3lin": ("Xh3tia", "6"),
    "h3rinn": ("Rh3r1", "2"),
    "h3amp": ("Xh3d1", "2"),
    "h3y": ("TP_H3_OUT", "1"),
    "h3invinn": ("Rh3invin", "2"),
    "h3yn": ("Xh3inv", "6"),
    "h4sum": ("Xh4tia", "2"),
    "h4lin": ("Xh4tia", "6"),
    "h4rinn": ("Rh4r1", "2"),
    "h4amp": ("Xh4d1", "2"),
    "h4y": ("TP_H4_OUT", "1"),
    "h4invinn": ("Rh4invin", "2"),
    "h4yn": ("Xh4inv", "6"),
    "o1sum": ("Xo1tia", "2"),
    "o1lin": ("Xo1tia", "6"),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fmt_ohm(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        value = float(round(value))
    if value >= 1e6:
        return f"{value / 1e6:g}M"
    if value >= 1000:
        return f"{value / 1000:g}k"
    return f"{value:g}"


def parse_netlist(path: Path):
    resistors, amps, diodes = [], [], []
    in_control = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("*"):
            continue
        low = line.lower()
        if low.startswith(".control"):
            in_control = True
            continue
        if low.startswith(".endc"):
            in_control = False
            continue
        if in_control or line.startswith("."):
            continue
        p = line.split()
        name = p[0]
        if name.startswith("R"):
            resistors.append({"ref": name, "n1": p[1], "n2": p[2], "ohm": float(p[3])})
        elif name.startswith("X") and p[-1] == "OPAx189":
            amps.append({"ref": name, "inp": p[1], "inn": p[2], "vcc": p[3], "vee": p[4], "out": p[5]})
        elif name.startswith("X") and p[-1] == "1N4148":
            diodes.append({"ref": name, "anode": p[1], "cathode": p[2]})
    return resistors, amps, diodes


def subsystem_for_ref(ref: str) -> str:
    if ref.startswith(("Rinv1", "Rinv2", "Xinv1", "Xinv2")):
        return "SIGNED_INV"
    if ref.startswith(("Rinvref", "Xinvref")):
        return "SIGNED_INV"
    if ref.startswith(("Rh1", "Xh1")):
        return "H1"
    if ref.startswith(("Rh2", "Xh2")):
        return "H2"
    if ref.startswith(("Rh3", "Xh3")):
        return "H3"
    if ref.startswith(("Rh4", "Xh4")):
        return "H4"
    if ref.startswith(("Ro1", "Xo1")):
        return "OUT"
    return "MISC"


class ConnWriter:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.n = 0

    def add(
        self,
        src: str,
        src_pin: str,
        dst: str,
        dst_pin: str,
        net: str,
        value: str,
        subsystem: str,
        purpose: str,
    ) -> None:
        self.n += 1
        self.rows.append(
            {
                "connection_id": f"C{self.n:04d}",
                "source_component": src,
                "source_pin": src_pin,
                "destination_component": dst,
                "destination_pin": dst_pin,
                "net_name": net,
                "component_value": value,
                "subsystem": subsystem,
                "purpose": purpose,
                "test_point": TP.get(net, ""),
            }
        )


def expand_resistors(resistors: list[dict], combos: list[dict]) -> list[dict]:
    by_ref = {c["ref"]: c for c in combos}
    out = []
    for r in resistors:
        c = by_ref[r["ref"]]
        kind = c["preferred"]["kind"]
        parts = c["preferred"]["parts"]
        sub = subsystem_for_ref(r["ref"])
        if kind == "single":
            out.append(
                {
                    "ref": r["ref"],
                    "n1": r["n1"],
                    "n2": r["n2"],
                    "value": fmt_ohm(parts[0]),
                    "compiled": r["ref"],
                    "exact": r["ohm"],
                    "network": "single",
                    "subsystem": sub,
                }
            )
        elif kind == "series":
            mid = f"{r['ref']}_MID"
            HUB[mid] = (f"{r['ref']}_A", "2")
            out.append(
                {
                    "ref": f"{r['ref']}_A",
                    "n1": r["n1"],
                    "n2": mid,
                    "value": fmt_ohm(parts[0]),
                    "compiled": r["ref"],
                    "exact": r["ohm"],
                    "network": "series",
                    "subsystem": sub,
                }
            )
            out.append(
                {
                    "ref": f"{r['ref']}_B",
                    "n1": mid,
                    "n2": r["n2"],
                    "value": fmt_ohm(parts[1]),
                    "compiled": r["ref"],
                    "exact": r["ohm"],
                    "network": "series",
                    "subsystem": sub,
                }
            )
        elif kind == "parallel":
            for i, p in enumerate(parts):
                suf = "_A" if i == 0 else "_B"
                out.append(
                    {
                        "ref": f"{r['ref']}{suf}",
                        "n1": r["n1"],
                        "n2": r["n2"],
                        "value": fmt_ohm(p),
                        "compiled": r["ref"],
                        "exact": r["ohm"],
                        "network": "parallel",
                        "subsystem": sub,
                    }
                )
        else:
            raise SystemExit(kind)
    return out


def write_connections(resistors, amps, diodes, phys) -> None:
    w = ConnWriter()

    w.add("J_PWR", "+15", "TP_P15", "1", "vdd", "connector", "PWR", "positive analog rail")
    w.add("J_PWR", "GND", "TP_GND", "1", "0", "connector", "PWR", "analog ground")
    w.add("J_PWR", "-15", "TP_M15", "1", "vss", "connector", "PWR", "negative analog rail")
    w.add("C_VDD_BULK", "1", "J_PWR", "+15", "vdd", "10uF >=35V", "PWR", "bulk decouple +15")
    w.add("C_VDD_BULK", "2", "J_PWR", "GND", "0", "10uF >=35V", "PWR", "bulk decouple +15 return")
    w.add("C_VSS_BULK", "1", "J_PWR", "-15", "vss", "10uF >=35V", "PWR", "bulk decouple -15")
    w.add("C_VSS_BULK", "2", "J_PWR", "GND", "0", "10uF >=35V", "PWR", "bulk decouple -15 return")

    w.add("VREF_SRC", "OUT", "U_VREFBUF", "3", "vref_raw", "1.000 V source", "VREF", "unbuffered 1 V into buffer +IN")
    w.add("VREF_SRC", "GND", "J_PWR", "GND", "0", "1.000 V source return", "VREF", "VREF source shares analog GND")
    w.add("U_VREFBUF", "2", "U_VREFBUF", "6", "vref", "OPA189 unity follower", "VREF", "buffer feedback")
    w.add("U_VREFBUF", "6", "TP_VREF", "1", "vref", "OPA189", "VREF", "buffered VREF = 1.000 V")
    w.add("U_VREFBUF", "7", "J_PWR", "+15", "vdd", "OPA189", "VREF", "buffer V+")
    w.add("U_VREFBUF", "4", "J_PWR", "-15", "vss", "OPA189", "VREF", "buffer V-")
    w.add("C_U_VREFBUF_VP", "1", "U_VREFBUF", "7", "vdd", "100nF X7R", "PWR", "local V+ decouple")
    w.add("C_U_VREFBUF_VP", "2", "J_PWR", "GND", "0", "100nF X7R", "PWR", "local V+ decouple return")
    w.add("C_U_VREFBUF_VN", "1", "U_VREFBUF", "4", "vss", "100nF X7R", "PWR", "local V- decouple")
    w.add("C_U_VREFBUF_VN", "2", "J_PWR", "GND", "0", "100nF X7R", "PWR", "local V- decouple return")

    w.add("SW_IN1", "0V", "J_PWR", "GND", "0", "SPDT", "INPUT", "IN1 = 0 V position")
    w.add("SW_IN1", "1V", "U_VREFBUF", "6", "vref", "SPDT", "INPUT", "IN1 = 1.000 V position")
    w.add("SW_IN1", "COM", "TP_IN1", "1", "in1", "SPDT", "INPUT", "IN1 common")
    w.add("SW_IN2", "0V", "J_PWR", "GND", "0", "SPDT", "INPUT", "IN2 = 0 V position")
    w.add("SW_IN2", "1V", "U_VREFBUF", "6", "vref", "SPDT", "INPUT", "IN2 = 1.000 V position")
    w.add("SW_IN2", "COM", "TP_IN2", "1", "in2", "SPDT", "INPUT", "IN2 common")

    for a in amps:
        ref = a["ref"]
        sub, purpose = OPA_ROLE[ref]
        val = "OPA189 SOIC-8 D"
        w.add(ref, "3", *HUB[a["inp"]], a["inp"], val, sub, f"{purpose}; +IN")
        inn_dst = (TP[a["inn"]], "1") if a["inn"] in TP else HUB[a["inn"]]
        if inn_dst != (ref, "2"):
            w.add(ref, "2", inn_dst[0], inn_dst[1], a["inn"], val, sub, f"{purpose}; -IN")
        out_dst = (TP[a["out"]], "1") if a["out"] in TP else HUB[a["out"]]
        if out_dst != (ref, "6"):
            w.add(ref, "6", out_dst[0], out_dst[1], a["out"], val, sub, f"{purpose}; OUT")
        w.add(ref, "7", "J_PWR", "+15", a["vcc"], val, sub, f"{purpose}; V+")
        w.add(ref, "4", "J_PWR", "-15", a["vee"], val, sub, f"{purpose}; V-")
        w.add(f"C_{ref}_VP", "1", ref, "7", "vdd", "100nF X7R", "PWR", f"local V+ decouple {ref}")
        w.add(f"C_{ref}_VP", "2", "J_PWR", "GND", "0", "100nF X7R", "PWR", f"local V+ return {ref}")
        w.add(f"C_{ref}_VN", "1", ref, "4", "vss", "100nF X7R", "PWR", f"local V- decouple {ref}")
        w.add(f"C_{ref}_VN", "2", "J_PWR", "GND", "0", "100nF X7R", "PWR", f"local V- return {ref}")

    for r in phys:
        d1, p1 = HUB[r["n1"]]
        d2, p2 = HUB[r["n2"]]
        if r["ref"].endswith("_A") and r["n2"].endswith("_MID"):
            d2, p2 = r["ref"][:-2] + "_B", "1"
        purpose = f"compiled {r['compiled']} {r['network']} target {r['exact']:.9g} ohm"
        w.add(r["ref"], "1", d1, p1, r["n1"], r["value"], r["subsystem"], purpose)
        w.add(r["ref"], "2", d2, p2, r["n2"], r["value"], r["subsystem"], purpose)

    for d in diodes:
        sub = subsystem_for_ref(d["ref"])
        w.add(d["ref"], "1", *HUB[d["anode"]], d["anode"], "1N4148 anode", sub, "rectifier anode")
        w.add(d["ref"], "2", *HUB[d["cathode"]], d["cathode"], "1N4148 cathode", sub, "rectifier cathode")

    for net, tp in TP.items():
        if net in ("vdd", "vss", "0", "vref", "in1", "in2"):
            continue
        if net not in HUB:
            continue
        w.add(tp, "1", *HUB[net], net, "test point", "TEST", f"probe {net}")

    path = HW / "MVP_H1_CONNECTION_TABLE.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        fields = list(w.rows[0].keys())
        wr = csv.DictWriter(fh, fieldnames=fields)
        wr.writeheader()
        wr.writerows(w.rows)
    print(f"connections {len(w.rows)} -> {path.name}")


def write_audited_bom(phys: list[dict]) -> None:
    rows = []

    def add(**kw):
        rows.append(kw)

    for ref, (_sub, role) in OPA_ROLE.items():
        add(
            reference_designator=ref,
            value="OPA189",
            tolerance="",
            voltage_rating="+/-15 V (abs max follow SBOS830, do not exceed +/-18 V)",
            power_rating="",
            package_footprint="SOIC-8 D (default first build)",
            required_quantity=1,
            recommended_quantity_with_spares=1,
            verified_manufacturer_part_number="",
            procurement_status=PROC,
            notes=f"{role}. Family OPA189. Alt 4x OPA4189 covering same 16 channels. Pinout opa189_pinout.md / SBOS830. Not 741.",
        )
    add(
        reference_designator="U_VREFBUF",
        value="OPA189",
        tolerance="",
        voltage_rating="+/-15 V",
        power_rating="",
        package_footprint="SOIC-8 D",
        required_quantity=1,
        recommended_quantity_with_spares=2,
        verified_manufacturer_part_number="",
        procurement_status=PROC,
        notes="Hardware-only VREF buffer. Not a neural MAC stage. Buy +1 spare amp.",
    )
    add(
        reference_designator="VREF_SRC / U_VREF",
        value="1.000 V",
        tolerance="0.05% analog goal; class-only may be looser",
        voltage_rating="",
        power_rating="",
        package_footprint="lab calibrator OR 0.05% 2.5 V ref + 15k/10k 0.05% + buffer",
        required_quantity=1,
        recommended_quantity_with_spares=1,
        verified_manufacturer_part_number="",
        procurement_status=PROC,
        notes="SPICE Vref was ideal. First demo may use a calibrated lab 1.000 V into U_VREFBUF pin 3. Do not invent an IC SKU.",
    )
    for ref in (
        "Xh1d1",
        "Xh1d2",
        "Xh2d1",
        "Xh2d2",
        "Xh3d1",
        "Xh3d2",
        "Xh4d1",
        "Xh4d2",
    ):
        add(
            reference_designator=ref,
            value="1N4148",
            tolerance="",
            voltage_rating="75 V class (SPICE BV=75)",
            power_rating="",
            package_footprint="SOD-123 or DO-35; band/bar = cathode",
            required_quantity=1,
            recommended_quantity_with_spares=1,
            verified_manufacturer_part_number="",
            procurement_status=PROC,
            notes="Anode pin 1, cathode pin 2. Buy extras: see kit row DIODE_SPARE.",
        )
    add(
        reference_designator="DIODE_SPARE",
        value="1N4148",
        tolerance="",
        voltage_rating="75 V class",
        power_rating="",
        package_footprint="same as stuffed diodes",
        required_quantity=0,
        recommended_quantity_with_spares=8,
        verified_manufacturer_part_number="",
        procurement_status=PROC,
        notes="Spares only.",
    )
    shop: Counter[str] = Counter()
    for p in phys:
        shop[p["value"]] += 1
        add(
            reference_designator=p["ref"],
            value=p["value"],
            tolerance="0.1%",
            voltage_rating="50 V",
            power_rating="0.1 W min",
            package_footprint="0805 or 1206 thin film",
            required_quantity=1,
            recommended_quantity_with_spares=1,
            verified_manufacturer_part_number="",
            procurement_status=PROC,
            notes=(
                f"compiled {p['compiled']} {p['network']}; exact target {p['exact']:.15g} ohm; "
                f"{p['n1']} -> {p['n2']}; TCR <=25 ppm/C preferred; do not coarse-E96 snap"
            ),
        )
    add(
        reference_designator="R_KIT_SPARES",
        value="see resistor_shopping.csv qty_buy_suggested",
        tolerance="0.1%",
        voltage_rating="50 V",
        power_rating="0.1 W min",
        package_footprint="0805 or 1206 thin film",
        required_quantity=0,
        recommended_quantity_with_spares=sum(max(2, q // 5) for q in shop.values()),
        verified_manufacturer_part_number="",
        procurement_status=PROC,
        notes="Extra 0.1% E192 of each unique value. 10k especially (31 stuffed).",
    )
    add(
        reference_designator="C_VDD_BULK",
        value="10uF",
        tolerance="20%",
        voltage_rating=">=35 V",
        power_rating="",
        package_footprint="electrolytic or 1210 ceramic",
        required_quantity=1,
        recommended_quantity_with_spares=2,
        verified_manufacturer_part_number="",
        procurement_status=PROC,
        notes="Hardware-only. +15 to GND.",
    )
    add(
        reference_designator="C_VSS_BULK",
        value="10uF",
        tolerance="20%",
        voltage_rating=">=35 V",
        power_rating="",
        package_footprint="electrolytic or 1210 ceramic",
        required_quantity=1,
        recommended_quantity_with_spares=2,
        verified_manufacturer_part_number="",
        procurement_status=PROC,
        notes="Hardware-only. -15 to GND.",
    )
    for ref in list(OPA_ROLE) + ["U_VREFBUF"]:
        add(
            reference_designator=f"C_{ref}_VP",
            value="100nF X7R",
            tolerance="10%",
            voltage_rating=">=50 V",
            power_rating="",
            package_footprint="0805",
            required_quantity=1,
            recommended_quantity_with_spares=1,
            verified_manufacturer_part_number="",
            procurement_status=PROC,
            notes="Hardware-only. Package V+ to GND <5 mm. If using OPA4189 quads, one pair per IC package.",
        )
        add(
            reference_designator=f"C_{ref}_VN",
            value="100nF X7R",
            tolerance="10%",
            voltage_rating=">=50 V",
            power_rating="",
            package_footprint="0805",
            required_quantity=1,
            recommended_quantity_with_spares=1,
            verified_manufacturer_part_number="",
            procurement_status=PROC,
            notes="Hardware-only. Package V- to GND <5 mm.",
        )
    add(
        reference_designator="C_1PF_SPICE_DNP",
        value="1pF",
        tolerance="",
        voltage_rating="",
        power_rating="",
        package_footprint="DNP",
        required_quantity=0,
        recommended_quantity_with_spares=0,
        verified_manufacturer_part_number="DNP",
        procurement_status="DO NOT BUY / DO NOT PLACE",
        notes="Frozen Cinv1..Co1tia class C. capacitor_audit.md: yo1 unchanged with all 16 removed.",
    )
    for ref, note in (
        ("SW_IN1", "SPDT IN1 to GND or VREF. Omit if DAC drives IN1."),
        ("SW_IN2", "SPDT IN2 to GND or VREF. Omit if DAC drives IN2."),
        ("J_PWR", "3-pin +15 / GND / -15. Banana or terminal block."),
        ("J_IN", "Optional IN1 IN2 GND."),
    ):
        add(
            reference_designator=ref,
            value="",
            tolerance="",
            voltage_rating=">=15 V where applicable",
            power_rating="",
            package_footprint="",
            required_quantity=1,
            recommended_quantity_with_spares=1,
            verified_manufacturer_part_number="",
            procurement_status=PROC,
            notes=note,
        )
    for tp in sorted(set(TP.values())):
        add(
            reference_designator=tp,
            value="test point",
            tolerance="",
            voltage_rating="",
            power_rating="",
            package_footprint="1.0 mm loop or 1.27 mm header",
            required_quantity=1,
            recommended_quantity_with_spares=1,
            verified_manufacturer_part_number="",
            procurement_status=PROC,
            notes="Primary analog neural output is TP_O1LIN.",
        )

    fields = [
        "reference_designator",
        "value",
        "tolerance",
        "voltage_rating",
        "power_rating",
        "package_footprint",
        "required_quantity",
        "recommended_quantity_with_spares",
        "verified_manufacturer_part_number",
        "procurement_status",
        "notes",
    ]
    path = HW / "MVP_H1_FINAL_BOM_AUDITED.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=fields)
        wr.writeheader()
        wr.writerows(rows)
    print(f"bom {len(rows)} -> {path.name}")


def write_measurement_log() -> None:
    spice = {
        "00": {
            "in1": 0.0,
            "in2": 0.0,
            "class": 0,
            "o1": 0.001645123,
            "h1lin": 0.2633191,
            "h1y": -3.317805e-06,
            "h2lin": 0.1507945,
            "h2y": -3.316831e-06,
            "h3lin": 0.3858683,
            "h3y": -3.125244e-06,
            "h4lin": 0.4402104,
            "h4y": -3.115493e-06,
        },
        "01": {
            "in1": 0.0,
            "in2": 1.0,
            "class": 1,
            "o1": 1.002511,
            "h1lin": 1.766247,
            "h1y": -3.318886e-06,
            "h2lin": -0.9253124,
            "h2y": 0.9253017,
            "h3lin": 1.688048,
            "h3y": -3.123508e-06,
            "h4lin": 0.756453,
            "h4y": -3.117495e-06,
        },
        "10": {
            "in1": 1.0,
            "in2": 0.0,
            "class": 1,
            "o1": 1.018006,
            "h1lin": -0.9348376,
            "h1y": 0.9348269,
            "h2lin": 1.477117,
            "h2y": -3.318868e-06,
            "h3lin": 2.336903,
            "h3y": -3.129787e-06,
            "h4lin": 0.8300706,
            "h4y": -3.117038e-06,
        },
        "11": {
            "in1": 1.0,
            "in2": 1.0,
            "class": 0,
            "o1": 0.001645121,
            "h1lin": 0.5680899,
            "h1y": -3.318107e-06,
            "h2lin": 0.4010098,
            "h2y": -3.317744e-06,
            "h3lin": 3.639083,
            "h3y": -3.128145e-06,
            "h4lin": 1.146313,
            "h4y": -3.115588e-06,
        },
    }
    fields = [
        "test_id",
        "repeat",
        "input_state",
        "IN1_command_V",
        "IN2_command_V",
        "IN1_measured_V",
        "IN2_measured_V",
        "TP_P15_V",
        "TP_M15_V",
        "TP_VREF_V",
        "TP_VREFN_V",
        "H1_LIN_V",
        "H1_OUT_V",
        "H2_LIN_V",
        "H2_OUT_V",
        "H3_LIN_V",
        "H3_OUT_V",
        "H4_LIN_V",
        "H4_OUT_V",
        "O1_LIN_V",
        "class_from_threshold",
        "expected_class",
        "class_pass",
        "SPICE_O1_LIN_V",
        "analog_abs_error_V",
        "analog_1mV_pass",
        "settle_wait_s",
        "notes",
    ]
    rows = []
    for repeat in (1, 2):
        for st, s in spice.items():
            rows.append(
                {
                    "test_id": f"XOR_{st}_R{repeat}",
                    "repeat": repeat,
                    "input_state": st,
                    "IN1_command_V": s["in1"],
                    "IN2_command_V": s["in2"],
                    "IN1_measured_V": "",
                    "IN2_measured_V": "",
                    "TP_P15_V": "",
                    "TP_M15_V": "",
                    "TP_VREF_V": "",
                    "TP_VREFN_V": "",
                    "H1_LIN_V": "",
                    "H1_OUT_V": "",
                    "H2_LIN_V": "",
                    "H2_OUT_V": "",
                    "H3_LIN_V": "",
                    "H3_OUT_V": "",
                    "H4_LIN_V": "",
                    "H4_OUT_V": "",
                    "O1_LIN_V": "",
                    "class_from_threshold": "",
                    "expected_class": s["class"],
                    "class_pass": "",
                    "SPICE_O1_LIN_V": s["o1"],
                    "analog_abs_error_V": "",
                    "analog_1mV_pass": "",
                    "settle_wait_s": 0.01,
                    "notes": (
                        "class = 1 if O1_LIN_V >= 0.5 else 0. "
                        "Do not compute W2*ReLU(W1x+b1)+b2. "
                        f"SPICE H*_LIN/OUT 27C: "
                        f"H1 {s['h1lin']}/{s['h1y']}; "
                        f"H2 {s['h2lin']}/{s['h2y']}; "
                        f"H3 {s['h3lin']}/{s['h3y']}; "
                        f"H4 {s['h4lin']}/{s['h4y']}"
                    ),
                }
            )
    path = HW / "MVP_H1_MEASUREMENT_LOG_TEMPLATE.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=fields)
        wr.writeheader()
        wr.writerows(rows)
    print(f"log template {len(rows)} -> {path.name}")


def verify_and_audit(resistors, amps, diodes, combos) -> list[dict]:
    findings = []
    prov = json.loads((HW / "FROZEN_PROVENANCE.json").read_text(encoding="utf-8"))
    got_nl = sha256(FROZEN / "netlist.cir")
    if got_nl != "28dccd8121a1032d69a2b08633737db0b2f10c8996f68ed2271520ec58c3b9cb":
        findings.append(
            {
                "id": "A001",
                "severity": "BLOCKER",
                "item": "frozen netlist hash",
                "detail": f"got {got_nl}",
            }
        )
    else:
        findings.append(
            {
                "id": "A001",
                "severity": "INFORMATION",
                "item": "frozen netlist hash",
                "detail": "matches required 28dccd8121a1032d69a2b08633737db0b2f10c8996f68ed2271520ec58c3b9cb",
            }
        )
    if sha256(MODEL) != prov["xor_model.npz"]:
        findings.append(
            {
                "id": "A002",
                "severity": "BLOCKER",
                "item": "xor_model.npz hash",
                "detail": "mismatch",
            }
        )
    else:
        findings.append(
            {
                "id": "A002",
                "severity": "INFORMATION",
                "item": "xor_model.npz hash",
                "detail": "matches provenance",
            }
        )
    for name, expected in prov["files"].items():
        got = sha256(FROZEN / name)
        if got != expected:
            findings.append(
                {
                    "id": f"A-{name}",
                    "severity": "BLOCKER",
                    "item": f"frozen {name}",
                    "detail": "hash mismatch",
                }
            )
    if not (len(amps) == 16 and len(diodes) == 8 and len(resistors) == 48):
        findings.append(
            {
                "id": "A003",
                "severity": "BLOCKER",
                "item": "device counts",
                "detail": f"R={len(resistors)} opa={len(amps)} d={len(diodes)}",
            }
        )
    by_combo = {c["ref"]: c for c in combos}
    for r in resistors:
        c = by_combo[r["ref"]]
        if abs(c["exact_ohm"] - r["ohm"]) > 1e-6:
            findings.append(
                {
                    "id": f"R-{r['ref']}",
                    "severity": "BLOCKER",
                    "item": "resistor exact mismatch",
                    "detail": f"{r['ref']} netlist {r['ohm']} combo {c['exact_ohm']}",
                }
            )
        if not c["preferred"]["within_0p1pct"]:
            findings.append(
                {
                    "id": f"T-{r['ref']}",
                    "severity": "BLOCKER",
                    "item": "E192 combo outside 0.1%",
                    "detail": r["ref"],
                }
            )
    findings.append(
        {
            "id": "W001",
            "severity": "WARNING",
            "item": "manufacturer SKUs",
            "detail": "No verified reel MPNs in project evidence. Electrical specs only.",
        }
    )
    findings.append(
        {
            "id": "W002",
            "severity": "WARNING",
            "item": "frozen BOM.csv E96 column",
            "detail": "physical_design BOM lists nearest E96. Do not buy those snaps (Exp67).",
        }
    )
    findings.append(
        {
            "id": "W003",
            "severity": "WARNING",
            "item": "VREF ideal in SPICE",
            "detail": "Must provide a real 1.000 V source. First demo: lab calibrator + buffer.",
        }
    )
    findings.append(
        {
            "id": "W004",
            "severity": "WARNING",
            "item": "no native KiCad / PCB",
            "detail": "Build from connection table. Layout spec is not a fabricated board.",
        }
    )
    findings.append(
        {
            "id": "W005",
            "severity": "WARNING",
            "item": "SVG pin numbers",
            "detail": "schematics/*.svg are hierarchical drawings. Package pins are opa189_pinout.md.",
        }
    )
    findings.append(
        {
            "id": "W006",
            "severity": "WARNING",
            "item": "analog 1 mV vs SPICE",
            "detail": "DEMONSTRATED IN SPICE only. Hardware Level B is not assumed.",
        }
    )
    findings.append(
        {
            "id": "W007",
            "severity": "WARNING",
            "item": "hardware settling time",
            "detail": "SPICE recorded at 2 ms. Hardware wait >= 10 ms. UNKNOWN if longer needed.",
        }
    )
    findings.append(
        {
            "id": "W008",
            "severity": "WARNING",
            "item": "Ro1b 6.06 MΩ leakage",
            "detail": "Class-0 millivolt floor. Keep flux off this node.",
        }
    )
    findings.append(
        {
            "id": "I001",
            "severity": "INFORMATION",
            "item": "1 pF SPICE caps",
            "detail": "Class C DNP. Do not place.",
        }
    )
    findings.append(
        {
            "id": "I002",
            "severity": "INFORMATION",
            "item": "h3/h4 ReLU",
            "detail": "On all four XOR states H3_OUT and H4_OUT stay ~0 V. LIN still swings positive. Normal.",
        }
    )
    return findings


def write_findings(findings: list[dict]) -> None:
    n_b = sum(1 for f in findings if f["severity"] == "BLOCKER")
    n_w = sum(1 for f in findings if f["severity"] == "WARNING")
    n_i = sum(1 for f in findings if f["severity"] == "INFORMATION")
    lines = [
        "# MVP-H1 hardware readiness audit findings",
        "",
        "Audit of `physical_design/xor_2_4_1/` against `hardware/mvp_v1_xor_2_4_1/`.",
        "Frozen files were not modified.",
        "",
        f"Open BLOCKERS: **{n_b}**",
        f"WARNINGS: **{n_w}**",
        f"INFORMATION: **{n_i}**",
        "",
        "| ID | Severity | Item | Detail |",
        "| --- | --- | --- | --- |",
    ]
    for f in findings:
        lines.append(f"| {f['id']} | {f['severity']} | {f['item']} | {f['detail']} |")
    lines += [
        "",
        "## Closed documentation gaps (this audit)",
        "",
        "These were build-path gaps, not neural-design errors. They are closed by new files in this folder:",
        "",
        "- No single human procedure → `BUILD_MVP_H1_STEP_BY_STEP.md`",
        "- No pin-to-pin wiring table → `MVP_H1_CONNECTION_TABLE.csv`",
        "- No staged bring-up independent of compiler docs → `MVP_H1_BRINGUP_AND_TEST.md`",
        "- No demo / acceptance split → `MVP_H1_DEMO_PROTOCOL.md`, `MVP_H1_ACCEPTANCE_CRITERIA.md`",
        "- No audited purchase BOM → `MVP_H1_FINAL_BOM_AUDITED.csv`",
        "- No layout specification → `MVP_H1_LAYOUT_SPEC.md`",
        "- No explicit gate → `MVP_H1_HARDWARE_READINESS_GATE.md`",
        "",
        "Default first-build package is **16× OPA189 SOIC-8 (D) + 1× VREFBUF**. Quad mapping is optional and documented; do not mix pinouts.",
        "",
    ]
    (HW / "MVP_H1_AUDIT_FINDINGS.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"findings B={n_b} W={n_w} I={n_i}")


def main() -> None:
    resistors, amps, diodes = parse_netlist(FROZEN / "netlist.cir")
    combos = json.loads((HW / "resistor_combos.json").read_text(encoding="utf-8"))
    findings = verify_and_audit(resistors, amps, diodes, combos)
    if any(f["severity"] == "BLOCKER" for f in findings):
        write_findings(findings)
        raise SystemExit("audit blockers remain")
    phys = expand_resistors(resistors, combos)
    write_connections(resistors, amps, diodes, phys)
    write_audited_bom(phys)
    write_measurement_log()
    write_findings(findings)
    print("readiness tables written")


if __name__ == "__main__":
    main()
