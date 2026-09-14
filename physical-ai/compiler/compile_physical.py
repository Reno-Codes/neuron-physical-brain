"""Compile a frozen 2-layer MLP into PCB-oriented analog artifacts.

The neural weights are not edited. If a mapping is unsafe or unknown the
compiler raises PhysicalMappingFailed instead of emitting a fake design.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from compiler.parser import PhysicalMappingFailed, load_npz, range_analysis, software_forward
from compiler.primitives import (
    C_NODE,
    DIODE_LIB,
    OPA189_LIB,
    R_INVERT,
    R_RELU_LOAD,
    e96_nearest,
    emit_inverter_opa189,
    emit_relu_opa189_1n4148,
    emit_supplies,
    emit_tia_opa189,
    include_models,
    signed_source,
)

G_SCALE = 1.0e-4
VSUPPLY = 15.0
ABS_SIGNAL_MAX = 12.0
R_MIN = 100.0
R_MAX = 2.0e7
TRAN_STEP = 5.0e-6
TRAN_STOP = 2.0e-3
REG_PATH = Path(__file__).resolve().parent / "primitives_registry.json"


def _r_from_weight(abs_w: float) -> float:
    return 1.0 / (G_SCALE * abs_w)


def compile_mlp(
    model_path: Path,
    dest: Path,
    inputs: np.ndarray,
    title: str | None = None,
) -> dict:
    model = load_npz(Path(model_path))
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    if not OPA189_LIB.is_file() or not DIODE_LIB.is_file():
        raise PhysicalMappingFailed(
            "MISSING DOCUMENTED MODELS: OPA189 and/or 1N4148 library files"
        )

    ranges = range_analysis(model, inputs)
    if ranges["abs_signal_max"] > ABS_SIGNAL_MAX:
        raise PhysicalMappingFailed(
            "PHYSICAL MAPPING FAILED: predicted |signal| "
            f"{ranges['abs_signal_max']:.6g} V exceeds {ABS_SIGNAL_MAX} V "
            f"headroom on +/-{VSUPPLY} V supplies"
        )

    w1, b1, w2, b2 = model["W1"], model["b1"], model["W2"], model["b2"]
    n_in, n_hid, n_out = model["n_in"], model["n_hidden"], model["n_out"]
    rf = 1.0 / G_SCALE

    resistors: list[dict] = []
    capacitors: list[dict] = []
    devices: list[dict] = []
    mapping_notes: list[str] = []
    lines: list[str] = [
        title
        or (
            f"* Physical AI compiler: {n_in}->{n_hid}->{n_out} "
            f"{model['hidden_activation']}/{model['output_activation']}"
        ),
        f"* Frozen model: {model['path']}",
        "* Weights are compiled, not edited.",
        f"* G_SCALE={G_SCALE:.15g} Rf={rf:.15g}",
        "* Architecture A signed routing + OPA189 TIA + OPA189/1N4148 ReLU.",
        "* MIXED-LEVEL: vendor macromodel TIA/ReLU + discrete R. Not silicon.",
        "",
        *include_models(),
        *emit_supplies(VSUPPLY),
        "Vref vref 0 DC 1",
        "",
    ]

    for i in range(1, n_in + 1):
        lines.append(f"Vin{i} in{i} 0 DC 0")
    lines.append("")

    for i in range(1, n_in + 1):
        lines += emit_inverter_opa189(f"inv{i}", f"in{i}", f"in{i}n")
        devices.append(
            {
                "ref": f"Xinv{i}",
                "part": "OPA189",
                "role": "input_invert",
                "node": f"in{i}n",
            }
        )
        resistors.append({"ref": f"Rinv{i}in", "ohm": R_INVERT, "role": "invert"})
        resistors.append({"ref": f"Rinv{i}f", "ohm": R_INVERT, "role": "invert"})
        capacitors.append({"ref": f"Cinv{i}", "farad": C_NODE, "role": "node"})
    lines += emit_inverter_opa189("invref", "vref", "vrefn")
    devices.append(
        {"ref": "Xinvref", "part": "OPA189", "role": "vref_invert", "node": "vrefn"}
    )
    resistors += [
        {"ref": "Rinvrefin", "ohm": R_INVERT, "role": "invert"},
        {"ref": "Rinvreff", "ohm": R_INVERT, "role": "invert"},
    ]
    capacitors.append({"ref": "Cinvref", "farad": C_NODE, "role": "node"})
    lines.append("")

    def add_weight_resistor(
        ref: str,
        src: str,
        dest_node: str,
        weight: float,
        role: str,
        layer: int,
    ) -> None:
        if abs(weight) == 0.0:
            mapping_notes.append(f"{ref}: zero weight omitted")
            return
        r = _r_from_weight(abs(weight))
        if r < R_MIN or r > R_MAX:
            raise PhysicalMappingFailed(
                f"PHYSICAL MAPPING FAILED: {ref} R={r:.6g} ohm "
                f"outside [{R_MIN}, {R_MAX}] for |w|={abs(weight):.6g}"
            )
        lines.append(f"{ref} {src} {dest_node} {r:.15g}")
        resistors.append(
            {
                "ref": ref,
                "ohm": r,
                "e96": e96_nearest(r),
                "weight": float(weight),
                "role": role,
                "layer": layer,
                "from": src,
                "to": dest_node,
            }
        )

    hidden_y: list[str] = []
    for j in range(n_hid):
        tag = f"h{j + 1}"
        sumn = f"{tag}sum"
        lin = f"{tag}lin"
        y = f"{tag}y"
        hidden_y.append(y)
        lines.append(f"* Hidden neuron {tag}")
        for i in range(n_in):
            w = float(w1[j, i])
            src = signed_source(w, f"in{i + 1}", f"in{i + 1}n", tia_inverts=True)
            if src is None:
                continue
            add_weight_resistor(f"R{tag}w{i + 1}", src, sumn, w, "weight", 1)
        b = float(b1[j])
        bsrc = signed_source(b, "vref", "vrefn", tia_inverts=True)
        if bsrc is not None:
            add_weight_resistor(f"R{tag}b", bsrc, sumn, b, "bias", 1)
        lines += emit_tia_opa189(tag, sumn, lin, rf)
        lines += emit_relu_opa189_1n4148(tag, lin, y)
        lines += emit_inverter_opa189(f"{tag}inv", y, f"{tag}yn")
        devices += [
            {"ref": f"X{tag}tia", "part": "OPA189", "role": "hidden_tia", "node": lin},
            {"ref": f"X{tag}relu", "part": "OPA189", "role": "hidden_relu", "node": y},
            {"ref": f"X{tag}d1", "part": "1N4148", "role": "hidden_relu_dclamp", "node": y},
            {"ref": f"X{tag}d2", "part": "1N4148", "role": "hidden_relu_dfwd", "node": y},
            {
                "ref": f"X{tag}inv",
                "part": "OPA189",
                "role": "hidden_invert",
                "node": f"{tag}yn",
            },
        ]
        resistors.append({"ref": f"R{tag}f", "ohm": rf, "role": "tia_rf", "layer": 1})
        resistors += [
            {"ref": f"R{tag}r1", "ohm": R_INVERT, "role": "relu_r1", "layer": 1},
            {"ref": f"R{tag}rf", "ohm": R_INVERT, "role": "relu_rf", "layer": 1},
            {"ref": f"R{tag}rl", "ohm": R_RELU_LOAD, "role": "relu_load", "layer": 1},
        ]
        resistors += [
            {"ref": f"R{tag}invin", "ohm": R_INVERT, "role": "invert"},
            {"ref": f"R{tag}invf", "ohm": R_INVERT, "role": "invert"},
        ]
        capacitors += [
            {"ref": f"C{tag}tia", "farad": C_NODE, "role": "node"},
            {"ref": f"C{tag}rl", "farad": C_NODE, "role": "node"},
            {"ref": f"C{tag}inv", "farad": C_NODE, "role": "node"},
        ]
        lines.append("")

    for k in range(n_out):
        tag = f"o{k + 1}"
        sumn = f"{tag}sum"
        lin = f"{tag}lin"
        lines.append(f"* Output neuron {tag} (linear)")
        for j, hy in enumerate(hidden_y):
            w = float(w2[k, j])
            src = signed_source(w, hy, f"h{j + 1}yn", tia_inverts=False)
            if src is None:
                continue
            add_weight_resistor(f"R{tag}w{j + 1}", src, sumn, w, "weight", 2)
        b = float(b2[k])
        bsrc = signed_source(b, "vref", "vrefn", tia_inverts=False)
        if bsrc is not None:
            add_weight_resistor(f"R{tag}b", bsrc, sumn, b, "bias", 2)
        lines += emit_tia_opa189(tag, sumn, lin, rf)
        devices.append(
            {"ref": f"X{tag}tia", "part": "OPA189", "role": "output_tia", "node": lin}
        )
        resistors.append({"ref": f"R{tag}f", "ohm": rf, "role": "tia_rf", "layer": 2})
        capacitors.append({"ref": f"C{tag}tia", "farad": C_NODE, "role": "node"})
        lines.append("")

    lines += [
        "* Validation analysis is UIC TRAN. OP of this 16x OPA189 + diode",
        "* netlist is stiff (Exp63/64 timestep too small on the ReLU diode).",
        "* UIC TRAN is the power-on settle, not a Python correction.",
        ".control",
        "set numdgt=15",
        f"tran {TRAN_STEP:.15g} {TRAN_STOP:.15g} uic",
        *[
            f"meas tran yo{k} FIND v(o{k}lin) AT={TRAN_STOP:.15g}"
            for k in range(1, n_out + 1)
        ],
        *[
            f"meas tran yh{j} FIND v(h{j}y) AT={TRAN_STOP:.15g}"
            for j in range(1, n_hid + 1)
        ],
        *[
            f"meas tran zh{j} FIND v(h{j}lin) AT={TRAN_STOP:.15g}"
            for j in range(1, n_hid + 1)
        ],
        *[f"print yo{k}" for k in range(1, n_out + 1)],
        *[f"print yh{j} zh{j}" for j in range(1, n_hid + 1)],
        ".endc",
        "",
        ".end",
        "",
    ]
    netlist = "\n".join(lines)
    (dest / "netlist.cir").write_text(netlist, encoding="utf-8")

    z1, h, y_ref = software_forward(model, inputs)
    architecture = {
        "kind": "MIXED-LEVEL PCB analog MLP",
        "silicon": False,
        "physical_tia_validated": False,
        "model": {
            "path": model["path"],
            "shape": [n_in, n_hid, n_out],
            "hidden_activation": model["hidden_activation"],
            "output_activation": model["output_activation"],
            "class_threshold": model["class_threshold"],
            "weights_frozen": True,
        },
        "g_scale": G_SCALE,
        "rf_ohm": rf,
        "vsupply": VSUPPLY,
        "primitives": [
            "SignedDense_A",
            "TIA_OPA189",
            "Inverter_OPA189",
            "ReLU_OPA189_1N4148",
            "Bias_Vref",
        ],
        "range_analysis": ranges,
        "mapping_notes": mapping_notes,
        "opa189_count": sum(1 for d in devices if d["part"] == "OPA189"),
        "diode_count": sum(1 for d in devices if d["part"] == "1N4148"),
        "resistor_count": len(resistors),
        "validation_analysis": {
            "type": "tran_uic",
            "tstep_s": TRAN_STEP,
            "tstop_s": TRAN_STOP,
            "note": "OP of the full OPA189+diode netlist is stiff. UIC TRAN is the power-on settle.",
        },
    }
    (dest / "architecture.json").write_text(
        json.dumps(architecture, indent=2), encoding="utf-8"
    )
    (dest / "component_map.json").write_text(
        json.dumps(
            {"devices": devices, "resistors": resistors, "capacitors": capacitors},
            indent=2,
        ),
        encoding="utf-8",
    )
    (dest / "device_requirements.json").write_text(
        json.dumps(
            {
                "amplifier": {
                    "part": "OPA189 or OPA4189 (quad)",
                    "model": "TI OPAx189 Green-Williams-Lis macromodel",
                    "supplies_V": [-VSUPPLY, VSUPPLY],
                    "count_single": architecture["opa189_count"],
                    "physical_tia_validated": False,
                    "note": "Level-1 macromodel host. Not custom MOS. Not silicon.",
                },
                "diode": {
                    "part": "1N4148",
                    "count": architecture["diode_count"],
                    "spice": str(DIODE_LIB),
                    "note": "Extracted unmodified from TI TLC555.LIB in the ngspice tree.",
                },
                "reference": {"vref_V": 1.0, "note": "precision 1 V for bias conductances"},
                "resistor_policy": {
                    "spice": "exact compiled R = 1/(G_SCALE*|w|); weights not snapped",
                    "bom": "nearest E96 listed for procurement only",
                    "r_limits_ohm": [R_MIN, R_MAX],
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    with (dest / "BOM.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["ref", "part", "value", "role"])
        w.writerow(["U_amp", "OPA189", f"x{architecture['opa189_count']}", "TIA/invert/ReLU"])
        w.writerow(["D_relu", "1N4148", f"x{architecture['diode_count']}", "ReLU inverting rectifier"])
        w.writerow(["Vref", "precision reference", "1 V", "bias"])
        w.writerow(["Vdd", "supply", f"+{VSUPPLY} V", "rails"])
        w.writerow(["Vss", "supply", f"-{VSUPPLY} V", "rails"])
        for r in resistors:
            w.writerow(
                [
                    r["ref"],
                    "resistor",
                    f"{r['ohm']:.9g} ohm (E96 {e96_nearest(r['ohm']):.6g})",
                    r.get("role", ""),
                ]
            )
        for c in capacitors:
            w.writerow([c["ref"], "capacitor", f"{c['farad']:.3g} F", c.get("role", "")])

    with (dest / "resistor_values.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["ref", "R_exact_ohm", "R_e96_ohm", "weight", "role", "layer", "from", "to"])
        for r in resistors:
            w.writerow(
                [
                    r["ref"],
                    f"{r['ohm']:.15g}",
                    f"{e96_nearest(r['ohm']):.15g}",
                    r.get("weight", ""),
                    r.get("role", ""),
                    r.get("layer", ""),
                    r.get("from", ""),
                    r.get("to", ""),
                ]
            )
    with (dest / "capacitor_values.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["ref", "C_F", "role"])
        for c in capacitors:
            w.writerow([c["ref"], f"{c['farad']:.15g}", c.get("role", "")])

    (dest / "schematic.md").write_text(
        "\n".join(
            [
                "# Schematic (text)",
                "",
                "Each hidden neuron:",
                "",
                "```",
                "in_i / in_i_n -- R(|w|) --+-- TIA --> (-z)",
                "vref / vref_n -- R(|b|) --+      |",
                "                                 inverting precision rectifier",
                "                                 dest = max(-(-z), 0) = ReLU(z)",
                "```",
                "",
                "Hidden TIA is polarity-inverted so the rectifier can be the",
                "textbook two-diode inverting circuit (Experiment 64).",
                "Output TIA keeps V = +y.",
                "",
                "Sign rule (Architecture A, inverting TIA):",
                "",
                "- Hidden (want -w x): w>0 uses the original source",
                "- Output (want +w x): w>0 uses the inverted source",
                "",
                "Output neuron is the same TIA without the superdiode.",
                "CAD schematic is not generated. This file plus `netlist.cir`",
                "and `BOM.csv` are the build description.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (dest / "input_interface.md").write_text(
        "\n".join(
            [
                "# Input interface",
                "",
                f"- {n_in} analog voltages `in1..in{n_in}` relative to circuit ground.",
                "- First MVP stimulus: a PC + DAC may drive these voltages.",
                "- The PC must not compute Wx+b or ReLU.",
                f"- Validated software input set used for range analysis: {ranges['n_vectors']} vectors.",
                f"- Predicted |signal| max = {ranges['abs_signal_max']:.6g} V.",
                "- Shared 1.000 V bias reference `vref`.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (dest / "output_interface.md").write_text(
        "\n".join(
            [
                "# Output interface",
                "",
                f"- Linear outputs: `v(o1lin)` .. `v(o{n_out}lin)`.",
                f"- Classification (if used): class = 1 if y >= {model['class_threshold']} else 0.",
                "- A PC + ADC/comparator may read the voltage. It must not run the network.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (dest / "build_notes.md").write_text(
        "\n".join(
            [
                "# Build notes",
                "",
                "This is a hybrid PCB/discrete analog prototype, not an ASIC.",
                "",
                "- Use the exact `R_exact_ohm` values in SPICE.",
                "- For a first board, nearest E96 is listed; E96 substitution is a",
                "  robustness experiment, not this compile.",
                "- Do not replace the analog MAC or ReLU with firmware.",
                "- Unre-sized SKY130 Miller TIA family is closed; this compile uses OPA189.",
                "- Do not call this silicon.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (dest / "validation_report.md").write_text(
        "\n".join(
            [
                "# Validation report",
                "",
                "Compile succeeded. SPICE comparison is written by the validation script.",
                "",
                f"- Range |signal|max = {ranges['abs_signal_max']:.6g} V",
                f"- z1 in [{ranges['z1_min']:.6g}, {ranges['z1_max']:.6g}] V",
                f"- y in [{ranges['y_min']:.6g}, {ranges['y_max']:.6g}] V",
                "",
            ]
        ),
        encoding="utf-8",
    )
    registry = json.loads(REG_PATH.read_text(encoding="utf-8"))
    (dest / "primitives_used.json").write_text(
        json.dumps(registry, indent=2), encoding="utf-8"
    )

    ref = {
        "inputs": np.atleast_2d(np.asarray(inputs, dtype=float)).tolist(),
        "z1": np.atleast_2d(z1).tolist(),
        "h": np.atleast_2d(h).tolist(),
        "y": np.atleast_2d(y_ref).tolist(),
    }
    (dest / "software_reference.json").write_text(
        json.dumps(ref, indent=2), encoding="utf-8"
    )
    return {
        "dest": str(dest),
        "architecture": architecture,
        "netlist": str(dest / "netlist.cir"),
        "model": model,
        "ranges": ranges,
    }
