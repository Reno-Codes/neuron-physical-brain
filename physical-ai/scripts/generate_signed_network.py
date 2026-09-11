"""Physical AI - Experiment 5: compile a signed 2-3-2 network into SPICE.

Architecture:

    X (2) -> differential hidden layer (3) -> physical ReLU -> differential output (2)

Each signed weight is two non-negative conductances. I+ and I- are formed
on separate virtual grounds; CCCS copies meet at a KCL node so

    I_diff = I+ - I-

is computed by the circuit. Bias is a conductance from a 1 V reference
onto the + or - path. Hidden ReLU is the Experiment 4 precision rectifier.
Output neurons are linear.

Python is the compiler and NumPy reference. It does not subtract currents,
apply ReLU, or add biases to produce the reported physical outputs.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CIRCUIT_PATH = PROJECT_ROOT / "circuits" / "generated_signed_network.cir"
NGSPICE_CANDIDATES = (
    Path(r"C:\ngspice\bin\ngspice_con.exe"),
    Path("ngspice_con.exe"),
)

W1 = np.array(
    [
        [0.5, -0.3],
        [-0.2, 0.8],
        [0.7, -0.4],
    ],
    dtype=float,
)
B1 = np.array([0.1, -0.2, 0.05], dtype=float)
W2 = np.array(
    [
        [0.6, -0.5, 0.2],
        [-0.3, 0.4, 0.7],
    ],
    dtype=float,
)
B2 = np.array([0.1, -0.1], dtype=float)

CASES = (
    {"name": "mixed hidden signs, only h2 active", "x": np.array([1.0, 2.0], dtype=float)},
    {"name": "negative-dominant inputs", "x": np.array([-1.0, 0.5], dtype=float)},
    {"name": "different ReLU mask (h1 and h3 active)", "x": np.array([2.0, 0.0], dtype=float)},
)

G_SCALE = 1e-4
R_IV = 1.0 / G_SCALE
RLOAD = 10_000.0
OPAMP_GAIN = 1e5
OPAMP_RAIL = 15.0
KCL_TOL = 1e-12
LINEAR_TOL = 1e-6
RELU_TOL = 1e-3


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


def run_ngspice(ngspice: Path, circuit: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(ngspice), "-b", str(circuit)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(circuit.parent),
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


def fmt_vector(values: np.ndarray) -> str:
    parts = []
    for v in np.atleast_1d(values).astype(float):
        if abs(v) < 1e-9:
            parts.append("0.0")
        elif abs(v - round(v, 1)) < 1e-9:
            parts.append(f"{round(v, 1):.1f}")
        else:
            parts.append(f"{v:.6g}")
    return "[" + ", ".join(parts) + "]"


def fmt_matrix(matrix: np.ndarray) -> str:
    rows = []
    for j, row in enumerate(matrix):
        inner = ", ".join(f"{float(v):+.1f}" for v in row)
        prefix = "[[" if j == 0 else " ["
        rows.append(f"{prefix}{inner}]")
    return ",\n".join(rows) + "]"


def split_weight(weight: float) -> tuple[float, float]:
    return max(weight, 0.0), max(-weight, 0.0)


def numpy_forward(x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    h_linear = W1 @ x + B1
    h = np.maximum(0.0, h_linear)
    y = W2 @ h + B2
    return h_linear, h, y


def emit_path_resistor(
    lines: list[str],
    name: str,
    src: str,
    dest: str,
    weight_comp: float,
    comment: str,
    catalog: list[str],
) -> None:
    if weight_comp <= 0:
        return
    g = G_SCALE * weight_comp
    r = 1.0 / g
    lines.append(f"* {comment}  G = {g:.15g} S  R = {r:.15g} Ohm")
    lines.append(f"{name} {src} {dest} {r:.15g}")
    catalog.append(f"  {name}: {comment}  R = {r:.6f} Ohm")


def emit_diff_neuron(
    lines: list[str],
    tag: str,
    input_nodes: list[str],
    weights: np.ndarray,
    bias: float,
    vref: str,
    apply_relu: bool,
    catalog: list[str],
) -> None:
    """One signed neuron: +/− paths, KCL difference, optional precision ReLU."""
    sump = f"{tag}p"
    sumn = f"{tag}n"
    diff = f"{tag}d"
    lin = f"{tag}lin"
    y = f"{tag}y"
    buf = f"{tag}buf"

    lines.append(f"* --- neuron {tag} ---")
    for i, (node, wi) in enumerate(zip(input_nodes, weights), start=1):
        w_plus, w_minus = split_weight(float(wi))
        emit_path_resistor(
            lines, f"R{tag}p{i}", node, sump, w_plus,
            f"{tag} input {i} w={wi:+.15g} w+", catalog,
        )
        emit_path_resistor(
            lines, f"R{tag}n{i}", node, sumn, w_minus,
            f"{tag} input {i} w={wi:+.15g} w-", catalog,
        )

    b_plus, b_minus = split_weight(float(bias))
    emit_path_resistor(
        lines, f"R{tag}bp", vref, sump, b_plus,
        f"{tag} bias={bias:+.15g} b+", catalog,
    )
    emit_path_resistor(
        lines, f"R{tag}bn", vref, sumn, b_minus,
        f"{tag} bias={bias:+.15g} b-", catalog,
    )

    lines.append(f"V{tag}p {sump} 0 DC 0")
    lines.append(f"V{tag}n {sumn} 0 DC 0")
    lines.append(f"F{tag}p 0 {diff} V{tag}p 1")
    lines.append(f"F{tag}n {diff} 0 V{tag}n 1")
    lines.append(f"V{tag}d {diff} 0 DC 0")
    lines.append(f"H{tag} {lin} 0 V{tag}d {R_IV:.15g}")

    if apply_relu:
        lines.append(
            f"B{tag} {tag}amp 0 V = max(-{OPAMP_RAIL:.15g}, "
            f"min({OPAMP_RAIL:.15g}, {OPAMP_GAIN:.15g} * v({lin}, {y})))"
        )
        lines.append(f"D{tag} {tag}amp {y} Dsi")
        lines.append(f"RL{tag} {y} 0 {RLOAD:.15g}")
        lines.append(f"E{tag} {buf} 0 {y} 0 1")
    lines.append("")


def generate_circuit(x: np.ndarray) -> tuple[str, list[str]]:
    catalog: list[str] = []
    n_in = x.size
    n_hidden = W1.shape[0]
    n_out = W2.shape[0]

    lines = [
        "* Physical AI - Experiment 5: signed 2-3-2 physical network",
        "*",
        "* Hidden:  I_diff/G_SCALE ≈ W1 @ X + b1, then precision ReLU.",
        "* Output:  I_diff/G_SCALE ≈ W2 @ H + b2  (linear).",
        "* Subtraction is KCL at each neuron's diff node, not Python.",
        f"* G_SCALE = {G_SCALE:.15g}",
        "",
    ]
    for i, xi in enumerate(x, start=1):
        lines.append(f"Vin{i} in{i} 0 DC {xi:.15g}")
    lines.append("Vref vref 0 DC 1")
    lines.append("")

    input_nodes = [f"in{i}" for i in range(1, n_in + 1)]
    for j in range(n_hidden):
        emit_diff_neuron(
            lines, f"h{j + 1}", input_nodes, W1[j], float(B1[j]),
            "vref", apply_relu=True, catalog=catalog,
        )

    hidden_nodes = [f"h{j + 1}buf" for j in range(n_hidden)]
    for k in range(n_out):
        emit_diff_neuron(
            lines, f"o{k + 1}", hidden_nodes, W2[k], float(B2[k]),
            "vref", apply_relu=False, catalog=catalog,
        )

    lines.append(".model Dsi D(Is=1e-14 N=1 Rs=1)")
    lines.append("")
    lines.append(".control")
    lines.append("set numdgt=15")
    lines.append("op")
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


def read_neuron_currents(text: str, tag: str) -> tuple[float, float, float]:
    i_plus = extract_named_value(text, f"i(v{tag}p)")
    i_minus = extract_named_value(text, f"i(v{tag}n)")
    i_diff = extract_named_value(text, f"i(v{tag}d)")
    if None in (i_plus, i_minus, i_diff):
        raise RuntimeError(f"Could not parse currents for neuron {tag}")
    return i_plus, i_minus, i_diff


def simulate_case(
    ngspice: Path, x: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, str, str, int, list[str]]:
    netlist, catalog = generate_circuit(x)
    CIRCUIT_PATH.write_text(netlist, encoding="utf-8")
    result = run_ngspice(ngspice, CIRCUIT_PATH)
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    text = f"{stdout}\n{stderr}"

    n_hidden = W1.shape[0]
    n_out = W2.shape[0]
    h_lin = []
    h_y = []
    y_out = []
    kcl_err = []

    for j in range(1, n_hidden + 1):
        tag = f"h{j}"
        i_plus, i_minus, i_diff = read_neuron_currents(text, tag)
        kcl_err.append(abs(i_diff - (i_plus - i_minus)))
        v_lin = extract_named_value(text, f"v({tag}lin)")
        v_y = extract_named_value(text, f"v({tag}y)")
        if v_lin is None or v_y is None:
            raise RuntimeError(f"Could not parse voltages for hidden neuron {tag}\n{text}")
        h_lin.append(v_lin)
        h_y.append(v_y)

    for k in range(1, n_out + 1):
        tag = f"o{k}"
        i_plus, i_minus, i_diff = read_neuron_currents(text, tag)
        kcl_err.append(abs(i_diff - (i_plus - i_minus)))
        v_lin = extract_named_value(text, f"v({tag}lin)")
        if v_lin is None:
            raise RuntimeError(f"Could not parse voltage for output neuron {tag}\n{text}")
        y_out.append(v_lin)

    return (
        np.array(h_lin, dtype=float),
        np.array(h_y, dtype=float),
        np.array(y_out, dtype=float),
        np.array(kcl_err, dtype=float),
        stdout,
        stderr,
        result.returncode,
        catalog,
    )


def main() -> int:
    print("PHYSICAL AI - EXPERIMENT 5")
    print("Signed 2-3-2 physical neural network")
    print()
    print("W1 (input -> hidden):")
    print(fmt_matrix(W1))
    print()
    print(f"b1: {fmt_vector(B1)}")
    print()
    print("W2 (hidden -> output):")
    print(fmt_matrix(W2))
    print()
    print(f"b2: {fmt_vector(B2)}")
    print()
    print("Each signed weight is two non-negative conductances.")
    print("I_diff = I+ - I- is formed by KCL in SPICE.")
    print()

    try:
        ngspice = find_ngspice()
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"ngspice executable: {ngspice}")
    print(f"generated circuit: {CIRCUIT_PATH}")
    print()

    CIRCUIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    any_failed = False
    worst_error = 0.0
    printed_resistors = False

    for idx, case in enumerate(CASES, start=1):
        x = case["x"]
        h_lin_math, h_math, y_math = numpy_forward(x)

        print(f"--- Test case {idx}: {case['name']} ---")
        print("Input:")
        print(fmt_vector(x))
        print()
        print("Mathematical hidden linear:")
        print(fmt_vector(h_lin_math))
        print()
        print("Mathematical hidden ReLU:")
        print(fmt_vector(h_math))
        print()
        print("Mathematical final output:")
        print(fmt_vector(y_math))
        print()

        try:
            h_lin_p, h_y_p, y_p, kcl_err, stdout, stderr, code, catalog = (
                simulate_case(ngspice, x)
            )
        except (OSError, RuntimeError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

        if not printed_resistors:
            print("Generated resistors (from first compiled circuit):")
            print("\n".join(catalog))
            print()
            printed_resistors = True

        print("--- ngspice output ---")
        if stdout.strip():
            print(stdout.rstrip())
        if stderr.strip():
            print("--- ngspice stderr ---")
            print(stderr.rstrip())
        print("--- end ngspice output ---")
        print(f"ngspice exit code: {code}")
        print()

        print("Physical hidden linear (v(*lin) = I_diff / G_SCALE):")
        print(fmt_vector(h_lin_p))
        print()
        print("Physical hidden outputs (precision ReLU voltages):")
        print(fmt_vector(h_y_p))
        print()
        print("Physical final outputs:")
        print(fmt_vector(y_p))
        print()

        err_hidden_lin = np.abs(h_lin_p - h_lin_math)
        err_hidden = np.abs(h_y_p - h_math)
        err_out = np.abs(y_p - y_math)
        max_kcl = float(np.max(kcl_err))
        max_hidden_lin = float(np.max(err_hidden_lin))
        max_hidden = float(np.max(err_hidden))
        max_out = float(np.max(err_out))
        worst_error = max(worst_error, max_out)

        print("Absolute error vs mathematical hidden ReLU:")
        print(fmt_vector(err_hidden))
        print()
        print("Absolute error vs mathematical final output:")
        print(fmt_vector(err_out))
        print()
        print(f"Maximum KCL residual |I_diff-(I+-I-)|: {max_kcl:.6e} A")
        print(f"Maximum hidden-linear error: {max_hidden_lin:.6e}")
        print(f"Maximum hidden-ReLU error:   {max_hidden:.6e}")
        print(f"Maximum output error:        {max_out:.6e}")
        print()

        case_failed = False
        if code != 0:
            print("CASE FAILED: ngspice returned a non-zero exit code.")
            case_failed = True
        if max_kcl > KCL_TOL:
            print("CASE FAILED: a neuron's SPICE topology did not subtract I+ - I-.")
            case_failed = True
        if max_hidden_lin > LINEAR_TOL:
            print("CASE FAILED: physical hidden linear stage does not match W1@X+b1.")
            case_failed = True
        if max_hidden > RELU_TOL:
            print("CASE FAILED: physical hidden ReLU does not match max(0, W1@X+b1).")
            case_failed = True
        if max_out > RELU_TOL:
            print("CASE FAILED: physical outputs do not match W2@H+b2.")
            case_failed = True
        if not case_failed:
            print("CASE PASSED")
        print()
        any_failed = any_failed or case_failed

    print(f"Worst output error across cases: {worst_error:.6e}")
    print()
    if any_failed:
        print("SIMULATION FAILED")
        return 1
    print("SIMULATION PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
