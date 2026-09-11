"""Physical AI - Experiment 6: compile a frozen XOR model into SPICE.

This script does not train. It loads models/xor_model.npz and emits a
2-4-1 differential conductance network (Experiment 5 topology):

    w = w+ - w-   (positive resistors only)
    I_diff = I+ - I-   (KCL in SPICE, not Python)
    bias = conductance from a 1 V reference onto the + or - path
    hidden = precision-rectifier ReLU
    output = linear  y = W2 h + b2

Classification (fixed before physical comparison):
    class = 1 if y >= 0.5 else 0
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = PROJECT_ROOT / "models" / "xor_model.npz"
CIRCUIT_PATH = PROJECT_ROOT / "circuits" / "generated_xor.cir"
NGSPICE_CANDIDATES = (
    Path(r"C:\ngspice\bin\ngspice_con.exe"),
    Path("ngspice_con.exe"),
)

G_SCALE = 1e-4
R_IV = 1.0 / G_SCALE
RLOAD = 10_000.0
OPAMP_GAIN = 1e5
OPAMP_RAIL = 15.0
KCL_TOL = 1e-12
CLASS_THRESHOLD = 0.5
XOR_X = np.array(
    [
        [0.0, 0.0],
        [0.0, 1.0],
        [1.0, 0.0],
        [1.0, 1.0],
    ]
)
XOR_Y = np.array([0, 1, 1, 0], dtype=int)


def find_ngspice() -> Path:
    for candidate in NGSPICE_CANDIDATES:
        if candidate.is_file():
            return candidate
    which = shutil.which("ngspice_con.exe") or shutil.which("ngspice_con")
    if which:
        return Path(which)
    raise FileNotFoundError(
        "Could not find ngspice_con.exe. Expected at "
        r"C:\ngspice\bin\ngspice_con.exe or on PATH."
    )


def run_ngspice(
    ngspice: Path,
    circuit: Path,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [str(ngspice), "-b", str(circuit)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(circuit.parent),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            args=exc.args or [str(ngspice), "-b", str(circuit)],
            returncode=124,
            stdout=exc.stdout or "",
            stderr=(exc.stderr or "") + "\nngspice timed out",
        )


def extract_named_value(text: str, name: str) -> float | None:
    escaped = re.escape(name)
    pattern = (
        rf"{escaped}\s*=\s*"
        rf"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
    )
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if match:
        return float(match.group(1))
    return None


def split_weight(weight: float) -> tuple[float, float]:
    return max(weight, 0.0), max(-weight, 0.0)


def classify(output: float) -> int:
    return 1 if output >= CLASS_THRESHOLD else 0


def load_model(path: Path = MODEL_PATH) -> dict[str, np.ndarray]:
    if not path.is_file():
        raise FileNotFoundError(
            f"Frozen model not found: {path}. Run scripts/train_xor.py first."
        )
    data = np.load(path, allow_pickle=True)
    w1 = np.asarray(data["W1"], dtype=float)
    b1 = np.asarray(data["b1"], dtype=float).reshape(-1)
    w2 = np.asarray(data["W2"], dtype=float)
    b2 = np.asarray(data["b2"], dtype=float).reshape(-1)
    if w1.shape != (4, 2):
        raise ValueError(f"W1 shape {w1.shape} != (4, 2)")
    if b1.shape != (4,):
        raise ValueError(f"b1 shape {b1.shape} != (4,)")
    if w2.shape != (1, 4):
        raise ValueError(f"W2 shape {w2.shape} != (1, 4)")
    if b2.shape != (1,):
        raise ValueError(f"b2 shape {b2.shape} != (1,)")
    return {"W1": w1, "b1": b1, "W2": w2, "b2": b2, "raw": data}


def software_forward(
    x: np.ndarray, w1: np.ndarray, b1: np.ndarray, w2: np.ndarray, b2: np.ndarray
) -> float:
    h = np.maximum(0.0, w1 @ x + b1)
    y = float((w2 @ h + b2).reshape(-1)[0])
    return y


def emit_path_resistor(
    lines: list[str],
    name: str,
    src: str,
    dest: str,
    weight_comp: float,
    comment: str,
    catalog: list[dict[str, float | str]],
    g_scale: float = G_SCALE,
    role: str = "weight",
    layer: int = 0,
) -> None:
    if weight_comp <= 0:
        return
    g = g_scale * weight_comp
    r = 1.0 / g
    lines.append(f"* {comment}  G = {g:.15g} S  R = {r:.15g} Ohm")
    lines.append(f"{name} {src} {dest} {r:.15g}")
    catalog.append(
        {
            "name": name,
            "comment": comment,
            "weight_comp": weight_comp,
            "G": g,
            "R": r,
            "g_scale": g_scale,
            "role": role,
            "layer": layer,
        }
    )


def emit_diff_neuron(
    lines: list[str],
    tag: str,
    input_nodes: list[str],
    weights: np.ndarray,
    bias: float,
    vref: str,
    apply_relu: bool,
    catalog: list[dict[str, float | str]],
    g_scale: float = G_SCALE,
    g_bias_scale: float | None = None,
    layer: int = 0,
) -> None:
    sump = f"{tag}p"
    sumn = f"{tag}n"
    diff = f"{tag}d"
    lin = f"{tag}lin"
    y = f"{tag}y"
    buf = f"{tag}buf"
    bias_scale = g_scale if g_bias_scale is None else float(g_bias_scale)
    separate_bias = abs(bias_scale - g_scale) > 0.0

    lines.append(f"* --- neuron {tag} ---")
    if separate_bias:
        k = g_scale / bias_scale
        lines.append(
            f"* separate bias path: I_b_injected = k * Vref * G_B * |b|, "
            f"k=G_W/G_B={k:.15g}"
        )
        lines.append(
            "* so V_b = I_b_injected / G_W = |b|  (math bias unchanged)"
        )
    for i, (node, wi) in enumerate(zip(input_nodes, weights), start=1):
        w_plus, w_minus = split_weight(float(wi))
        emit_path_resistor(
            lines, f"R{tag}p{i}", node, sump, w_plus,
            f"{tag} input {i} w={wi:+.15g} w+", catalog,
            g_scale=g_scale, role="weight", layer=layer,
        )
        emit_path_resistor(
            lines, f"R{tag}n{i}", node, sumn, w_minus,
            f"{tag} input {i} w={wi:+.15g} w-", catalog,
            g_scale=g_scale, role="weight", layer=layer,
        )
    b_plus, b_minus = split_weight(float(bias))
    if separate_bias:
        k = g_scale / bias_scale
        emit_path_resistor(
            lines, f"R{tag}bp", vref, f"{tag}biasp", b_plus,
            f"{tag} bias={bias:+.15g} b+", catalog,
            g_scale=bias_scale, role="bias", layer=layer,
        )
        emit_path_resistor(
            lines, f"R{tag}bn", vref, f"{tag}biasn", b_minus,
            f"{tag} bias={bias:+.15g} b-", catalog,
            g_scale=bias_scale, role="bias", layer=layer,
        )
        if b_plus > 0:
            lines.append(f"V{tag}bbp {tag}biasp 0 DC 0")
            lines.append(f"F{tag}bbp 0 {diff} V{tag}bbp {k:.15g}")
        if b_minus > 0:
            lines.append(f"V{tag}bbn {tag}biasn 0 DC 0")
            lines.append(f"F{tag}bbn {diff} 0 V{tag}bbn {k:.15g}")
    else:
        emit_path_resistor(
            lines, f"R{tag}bp", vref, sump, b_plus,
            f"{tag} bias={bias:+.15g} b+", catalog,
            g_scale=g_scale, role="bias", layer=layer,
        )
        emit_path_resistor(
            lines, f"R{tag}bn", vref, sumn, b_minus,
            f"{tag} bias={bias:+.15g} b-", catalog,
            g_scale=g_scale, role="bias", layer=layer,
        )
    lines.append(f"V{tag}p {sump} 0 DC 0")
    lines.append(f"V{tag}n {sumn} 0 DC 0")
    lines.append(f"F{tag}p 0 {diff} V{tag}p 1")
    lines.append(f"F{tag}n {diff} 0 V{tag}n 1")
    lines.append(f"V{tag}d {diff} 0 DC 0")
    r_iv = 1.0 / g_scale
    lines.append(f"H{tag} {lin} 0 V{tag}d {r_iv:.15g}")
    if apply_relu:
        lines.append(
            f"B{tag} {tag}amp 0 V = max(-{OPAMP_RAIL:.15g}, "
            f"min({OPAMP_RAIL:.15g}, {OPAMP_GAIN:.15g} * v({lin}, {y})))"
        )
        lines.append(f"D{tag} {tag}amp {y} Dsi")
        lines.append(f"RL{tag} {y} 0 {RLOAD:.15g}")
        lines.append(f"E{tag} {buf} 0 {y} 0 1")
    lines.append("")


def generate_circuit(
    x: np.ndarray,
    w1: np.ndarray,
    b1: np.ndarray,
    w2: np.ndarray,
    b2: np.ndarray,
    g_scale: float | None = None,
    control: str = "full",
    title: str | None = None,
    g_weight_1: float | None = None,
    g_bias_1: float | None = None,
    g_weight_2: float | None = None,
    g_bias_2: float | None = None,
) -> tuple[str, list[dict[str, float | str]]]:
    scale = G_SCALE if g_scale is None else float(g_scale)
    gw1 = scale if g_weight_1 is None else float(g_weight_1)
    gb1 = gw1 if g_bias_1 is None else float(g_bias_1)
    gw2 = gw1 if g_weight_2 is None else float(g_weight_2)
    gb2 = gw2 if g_bias_2 is None else float(g_bias_2)
    catalog: list[dict[str, float | str]] = []
    n_in = int(w1.shape[1])
    n_hidden = int(w1.shape[0])
    n_out = int(w2.shape[0])
    header = title or (
        "* Physical AI - Experiment 6: compiled trained XOR network\n"
        "* Source: models/xor_model.npz  (frozen; this file does not retrain)"
    )
    separate_bias = (gb1 != gw1) or (gb2 != gw2)
    lines = [
        header,
        "* Hidden: precision ReLU. Output: linear.",
        "* Signed weights: G+/G- paths, I_diff = I+ - I- by KCL in SPICE.",
        (
            "* Bias: separate ammeter path + CCCS gain k=G_WEIGHT/G_BIAS so "
            "V_b = b. Vref remains 1 V."
            if separate_bias
            else "* Bias: 1 V reference through G_WEIGHT*|b| onto the + or - path."
        ),
        f"* G_WEIGHT_1={gw1:.15g} G_BIAS_1={gb1:.15g} k1={gw1 / gb1:.15g}",
        f"* G_WEIGHT_2={gw2:.15g} G_BIAS_2={gb2:.15g} k2={gw2 / gb2:.15g}",
        f"* R_IV_1={1.0 / gw1:.15g} R_IV_2={1.0 / gw2:.15g}",
        "* Layer voltages stay in neural units (no inter-layer Python rescale).",
        f"* shape: {n_in} -> {n_hidden} -> {n_out}",
        "",
    ]
    x = np.atleast_1d(np.asarray(x, dtype=float))
    for i in range(1, n_in + 1):
        xi = float(x[i - 1]) if i - 1 < x.size else 0.0
        lines.append(f"Vin{i} in{i} 0 DC {xi:.15g}")
    lines.append("Vref vref 0 DC 1")
    lines.append("")

    input_nodes = [f"in{i}" for i in range(1, n_in + 1)]
    for j in range(n_hidden):
        emit_diff_neuron(
            lines, f"h{j + 1}", input_nodes, w1[j], float(b1[j]),
            "vref", True, catalog, g_scale=gw1, g_bias_scale=gb1, layer=1,
        )
    hidden_nodes = [f"h{j + 1}buf" for j in range(n_hidden)]
    for k in range(n_out):
        emit_diff_neuron(
            lines, f"o{k + 1}", hidden_nodes, w2[k], float(b2[k]),
            "vref", False, catalog, g_scale=gw2, g_bias_scale=gb2, layer=2,
        )

    lines.append(".model Dsi D(Is=1e-14 N=1 Rs=1)")
    lines.append("")
    lines.append(".control")
    lines.append("set numdgt=15")
    lines.append("op")
    if control in ("outputs", "outputs+currents"):
        for k in range(1, n_out + 1):
            lines.append(f"print v(o{k}lin)")
        if control == "outputs+currents":
            for i in range(1, n_in + 1):
                lines.append(f"print i(Vin{i})")
            lines.append("print i(Vref)")
    else:
        for j in range(1, n_hidden + 1):
            tag = f"h{j}"
            lines.append(f"print i(V{tag}p)")
            lines.append(f"print i(V{tag}n)")
            lines.append(f"print i(V{tag}d)")
            lines.append(f"print v({tag}lin)")
            lines.append(f"print v({tag}y)")
        for k in range(1, n_out + 1):
            tag = f"o{k}"
            lines.append(f"print i(V{tag}p)")
            lines.append(f"print i(V{tag}n)")
            lines.append(f"print i(V{tag}d)")
            lines.append(f"print v({tag}lin)")
    lines.append(".endc")
    lines.append("")
    lines.append(".end")
    lines.append("")
    return "\n".join(lines), catalog


def apply_resistor_values(netlist: str, values: dict[str, float]) -> str:
    """Replace compiled weight/bias resistor values. Topology is unchanged.

    Used by Experiment 7 to model manufacturing tolerance. Experiment 6
    still calls generate_circuit with nominal R = 1/(G_SCALE*|w|).
    """
    if not values:
        return netlist
    out: list[str] = []
    for line in netlist.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("*") or not stripped:
            out.append(line)
            continue
        parts = line.split()
        if len(parts) >= 4 and parts[0] in values:
            r = values[parts[0]]
            out.append(f"{parts[0]} {parts[1]} {parts[2]} {r:.15g}")
        else:
            out.append(line)
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(out) + ending


def simulate_physical(
    ngspice: Path,
    x: np.ndarray,
    w1: np.ndarray,
    b1: np.ndarray,
    w2: np.ndarray,
    b2: np.ndarray,
) -> tuple[float, float, list[dict[str, float | str]], str, int]:
    netlist, catalog = generate_circuit(x, w1, b1, w2, b2)
    CIRCUIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CIRCUIT_PATH.write_text(netlist, encoding="utf-8")
    result = run_ngspice(ngspice, CIRCUIT_PATH)
    text = f"{result.stdout or ''}\n{result.stderr or ''}"
    if result.returncode != 0:
        raise RuntimeError(f"ngspice failed:\n{text}")

    max_kcl = 0.0
    for tag in [f"h{j}" for j in range(1, w1.shape[0] + 1)] + ["o1"]:
        i_plus = extract_named_value(text, f"i(v{tag}p)")
        i_minus = extract_named_value(text, f"i(v{tag}n)")
        i_diff = extract_named_value(text, f"i(v{tag}d)")
        if None in (i_plus, i_minus, i_diff):
            raise RuntimeError(f"Could not parse currents for {tag}\n{text}")
        max_kcl = max(max_kcl, abs(i_diff - (i_plus - i_minus)))
    if max_kcl > KCL_TOL:
        raise RuntimeError(
            f"Differential topology did not perform I_diff = I+ - I- "
            f"(KCL residual {max_kcl:.3e} A)"
        )

    y = extract_named_value(text, "v(o1lin)")
    if y is None:
        raise RuntimeError(f"Could not parse v(o1lin)\n{text}")
    return y, max_kcl, catalog, text, result.returncode


def fmt_array(arr: np.ndarray) -> str:
    return np.array2string(arr, precision=6, separator=", ")


def print_compilation_report(
    w1: np.ndarray,
    b1: np.ndarray,
    w2: np.ndarray,
    b2: np.ndarray,
    catalog: list[dict[str, float | str]],
) -> None:
    n_weight = sum(1 for item in catalog if "bias=" not in str(item["comment"]))
    n_bias = sum(1 for item in catalog if "bias=" in str(item["comment"]))
    print("PHYSICAL AI - EXPERIMENT 6")
    print()
    print("Source model:")
    print(f"    {MODEL_PATH}")
    print()
    print("Architecture:")
    print("    2 -> 4 -> 1")
    print()
    print("G_SCALE:")
    print(f"    {G_SCALE} S")
    print()
    print("Parameters compiled:")
    print(f"    W1: {fmt_array(w1)}")
    print(f"    b1: {fmt_array(b1)}")
    print(f"    W2: {fmt_array(w2)}")
    print(f"    b2: {fmt_array(b2)}")
    print()
    print("Number of physical weight conductances:")
    print(f"    {n_weight}")
    print("Number of physical bias conductances:")
    print(f"    {n_bias}")
    print("Number of physical resistors (weights + biases):")
    print(f"    {len(catalog)}")
    print()
    print("Number of physical neurons:")
    print("    5  (4 hidden + 1 output)")
    print()
    print("Generated circuit:")
    print(f"    {CIRCUIT_PATH}")
    print()
    print("Bias representation: 1 V reference -> G = G_SCALE*|b| onto + or - path.")
    print("Output activation: linear. Class 1 if y >= 0.5 else class 0.")
    print()
    print("COMPILATION COMPLETE")


def main() -> int:
    try:
        model = load_model()
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    w1, b1, w2, b2 = model["W1"], model["b1"], model["W2"], model["b2"]
    netlist, catalog = generate_circuit(XOR_X[0], w1, b1, w2, b2)
    CIRCUIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CIRCUIT_PATH.write_text(netlist, encoding="utf-8")
    print_compilation_report(w1, b1, w2, b2, catalog)
    print()

    try:
        ngspice = find_ngspice()
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"ngspice executable: {ngspice}")
    print("Running physical inference for all four XOR inputs...")
    print()
    print(f"{'Input':<10} {'Software':>10} {'Physical':>10} {'Error':>10}")
    max_err = 0.0
    try:
        for x in XOR_X:
            y_sw = software_forward(x, w1, b1, w2, b2)
            y_ph, _, _, _, _ = simulate_physical(ngspice, x, w1, b1, w2, b2)
            err = abs(y_ph - y_sw)
            max_err = max(max_err, err)
            print(
                f"{np.array2string(x, separator=', '):<10} "
                f"{y_sw:10.6f} {y_ph:10.6f} {err:10.3e}"
            )
    except (OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print()
    print(f"Maximum software-vs-physical error: {max_err:.6e}")
    print("Full classification table: python scripts\\verify_xor.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
