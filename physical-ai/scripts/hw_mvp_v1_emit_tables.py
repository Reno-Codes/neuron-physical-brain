"""Emit hardware CSV tables from frozen design + SPICE correlation + E192 combos."""

from __future__ import annotations

import csv
import json
from pathlib import Path

HW = Path(__file__).resolve().parent.parent / "hardware" / "mvp_v1_xor_2_4_1"
FROZEN = Path(__file__).resolve().parent.parent / "physical_design" / "xor_2_4_1"

STATES = ["00", "01", "10", "11"]
NODES_TP = [
    ("VDD", None, "+15 V rail"),
    ("VSS", None, "-15 V rail"),
    ("GND", None, "analog ground"),
    ("VREF", "vref", "1.000 V bias reference"),
    ("VREFN", "vrefn", "inverted reference = -VREF"),
    ("IN1", "in1", "input 1"),
    ("IN2", "in2", "input 2"),
    ("IN1N", "in1n", "inverted input 1"),
    ("IN2N", "in2n", "inverted input 2"),
    ("H1_LIN", "h1lin", "h1 TIA output = -z1"),
    ("H1_OUT", "h1y", "h1 ReLU = max(-h1lin,0)"),
    ("H1_YN", "h1yn", "h1 inverted ReLU"),
    ("H2_LIN", "h2lin", "h2 TIA output = -z2"),
    ("H2_OUT", "h2y", "h2 ReLU"),
    ("H2_YN", "h2yn", "h2 inverted ReLU"),
    ("H3_LIN", "h3lin", "h3 TIA output = -z3"),
    ("H3_OUT", "h3y", "h3 ReLU"),
    ("H3_YN", "h3yn", "h3 inverted ReLU"),
    ("H4_LIN", "h4lin", "h4 TIA output = -z4"),
    ("H4_OUT", "h4y", "h4 ReLU"),
    ("H4_YN", "h4yn", "h4 inverted ReLU"),
    ("O1_LIN", "o1lin", "network analog output"),
    ("H1_SUM", "h1sum", "h1 TIA summing node (virtual ground)"),
    ("H2_SUM", "h2sum", "h2 TIA summing node (virtual ground)"),
    ("H3_SUM", "h3sum", "h3 TIA summing node (virtual ground)"),
    ("H4_SUM", "h4sum", "h4 TIA summing node (virtual ground)"),
    ("O1_SUM", "o1sum", "output TIA summing node (virtual ground)"),
]


def main() -> None:
    combos = json.loads((HW / "resistor_combos.json").read_text(encoding="utf-8"))
    raw = json.loads((HW / "spice_correlation_raw.json").read_text(encoding="utf-8"))
    rvals = list(csv.DictReader((FROZEN / "resistor_values.csv").open(encoding="utf-8")))
    by_ref = {r["ref"]: r for r in rvals}

    with (HW / "resistor_implementation.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "Reference",
                "Exact_target_ohm",
                "Required_tolerance",
                "Preferred_implementation",
                "E192_0p1pct_combination",
                "Realized_ohm",
                "Expected_rel_error",
                "Within_0p1pct",
                "Alternative",
                "Power_rating",
                "Candidate_purchasable",
                "Risk_notes",
            ]
        )
        for c in combos:
            kind = c["preferred"]["kind"]
            parts = c["preferred"]["parts"]
            if kind == "single":
                impl = f"single 0.1% E192 {c['parts_fmt']}"
                alt = "measure/select 0.1% part to exact if needed"
            elif kind == "series":
                impl = f"series 0.1% E192 {c['parts_fmt']}"
                alt = "single 0.01% / 0.05% if a catalog value exists"
            else:
                impl = f"parallel 0.1% E192 {c['parts_fmt']}"
                alt = "series pair if layout prefers series"
            neural = c["role"] in ("weight", "bias")
            w.writerow(
                [
                    c["ref"],
                    f"{c['exact_ohm']:.15g}",
                    "0.1% (neural paths); 0.1% matched pair for invert/TIA 10k",
                    impl,
                    c["parts_fmt"],
                    f"{c['preferred']['realized']:.15g}",
                    f"{c['preferred']['rel_error']:.6g}",
                    c["preferred"]["within_0p1pct"],
                    alt,
                    "0.1 W min (dissipation << 10 mW)",
                    "PROCUREMENT VERIFICATION REQUIRED — spec: thin-film 0.1% <=25ppm/C 0805/1206 50V",
                    "Do not use coarse E96 snap (Exp67 analog fail). Combination preserves compiled R, not the weight number.",
                ]
            )

    with (HW / "hardware_correlation_template.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "Test_ID",
                "Input_state",
                "IN1_V",
                "IN2_V",
                "Node",
                "SPICE_expected_V",
                "Measured_V",
                "Absolute_error_V",
                "Relative_error",
                "Pass_fail",
                "Notes",
            ]
        )
        analog_nodes = [
            "IN1", "IN2", "IN1N", "IN2N", "VREF", "VREFN",
            "H1_LIN", "H1_OUT", "H2_LIN", "H2_OUT",
            "H3_LIN", "H3_OUT", "H4_LIN", "H4_OUT", "O1_LIN",
        ]
        for row in raw["rows"]:
            st = STATES[row["vector"]]
            tid = f"XOR_{st}"
            for name, spice, _note in NODES_TP:
                if name not in analog_nodes:
                    continue
                exp = row.get(spice) if spice else None
                note = "class uses O1_LIN >= 0.5 V"
                if name == "O1_LIN":
                    note = "primary analog neural output; analog bar 1 mV vs this SPICE column"
                w.writerow(
                    [
                        tid,
                        st,
                        row["x"][0],
                        row["x"][1],
                        name,
                        "" if exp is None else f"{exp:.15g}",
                        "",
                        "",
                        "",
                        "",
                        note,
                    ]
                )

    nets = {
        "revision": "MVP-H1",
        "frozen_netlist": "physical_design/xor_2_4_1/netlist.cir",
        "note": "Hardware nets use the same names as SPICE nodes. Neural topology is unchanged.",
        "blocks": [
            {
                "id": "PWR",
                "title": "Power and references",
                "spice": ["vdd", "vss", "0", "vref"],
                "hardware_additions": [
                    "C_VDD_BULK 10uF",
                    "C_VSS_BULK 10uF",
                    "C_Uxx_decouple 100nF each OPA189 V+/V- to GND",
                    "VREF source+buffer (ideal Vref in SPICE)",
                ],
            },
            {
                "id": "IN",
                "title": "Input interface + signed generation",
                "instances": [
                    "Vin1/Vin2 or switches to IN1/IN2",
                    "Xinv1, Xinv2, Xinvref unity inverters",
                ],
            },
            {
                "id": "H1",
                "title": "Hidden neuron h1",
                "tia": "Xh1tia",
                "relu": "Xh1relu + Xh1d1 + Xh1d2",
                "invert": "Xh1inv",
            },
            {"id": "H2", "title": "Hidden neuron h2"},
            {"id": "H3", "title": "Hidden neuron h3"},
            {"id": "H4", "title": "Hidden neuron h4"},
            {"id": "OUT", "title": "Output neuron o1 linear TIA Xo1tia"},
        ],
        "resistors": by_ref,
        "do_not_place_1pF_spice_caps": True,
    }
    (HW / "schematic_nets.json").write_text(json.dumps(nets, indent=2), encoding="utf-8")
    print("tables written", flush=True)


if __name__ == "__main__":
    main()
