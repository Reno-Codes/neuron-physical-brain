"""Physical AI - Experiment 4: linear layer plus physical ReLU.

Pipeline realized in one SPICE circuit per test vector:

    voltages X
        -> conductance network (W, positive weights only)
        -> currents I = G_SCALE * (W @ X)
        -> transimpedance H: V_lin = I / G_SCALE
        -> precision rectifier (diode + op-amp feedback)
        -> V_y ≈ max(0, W @ X)

Python computes Y_linear = W @ X and Y_expected = ReLU(Y_linear) only
as references. Y_physical is read from ngspice node voltages.

Negative weighted sums are produced with signed *input voltages*, not by
pretending a positive resistor is a negative weight. Dual-rail / inverted
input paths would be required for true negative weights.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CIRCUIT_PATH = PROJECT_ROOT / "circuits" / "generated_network.cir"
NGSPICE_CANDIDATES = (
    Path(r"C:\ngspice\bin\ngspice_con.exe"),
    Path("ngspice_con.exe"),
)

W = np.array(
    [
        [0.1, 0.2, 0.3],
        [0.4, 0.5, 0.6],
    ],
    dtype=float,
)

# Case A: Experiment 3 vector, both linear sums positive.
# Case B: signed inputs so one linear sum is negative and one is positive.
CASES = (
    {
        "name": "all-positive linear sums",
        "x": np.array([1.0, 2.0, 3.0], dtype=float),
    },
    {
        "name": "mixed-sign linear sums",
        "x": np.array([10.0, -5.0, -1.0], dtype=float),
    },
)

G_SCALE = 1e-4
R_IV = 1.0 / G_SCALE  # transimpedance so V_lin has the same units as Y
RLOAD = 10_000.0
OPAMP_GAIN = 1e5
OPAMP_RAIL = 15.0
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
    for v in values:
        fv = float(v)
        if abs(fv - round(fv, 1)) < 1e-9:
            parts.append(f"{round(fv, 1):.1f}" if abs(fv) >= 0.05 or fv == 0.0 else f"{fv:.6g}")
        else:
            parts.append(f"{fv:.6g}")
    return "[" + ", ".join(parts) + "]"


def fmt_matrix(matrix: np.ndarray) -> str:
    rows = []
    for j, row in enumerate(matrix):
        inner = ", ".join(f"{float(v):.1f}" for v in row)
        prefix = "[[" if j == 0 else " ["
        rows.append(f"{prefix}{inner}]")
    return ",\n".join(rows) + "]"


def weights_to_resistances(weights: np.ndarray) -> np.ndarray:
    if np.any(weights <= 0):
        raise ValueError(
            "Positive conductances only. Negative weights need a dual-rail path, "
            "not a negative resistor."
        )
    return 1.0 / (G_SCALE * weights)


def generate_circuit(x: np.ndarray, w: np.ndarray, r: np.ndarray) -> str:
    n_out, n_in = w.shape
    lines: list[str] = [
        "* Physical AI - Experiment 4: linear layer + precision ReLU",
        "*",
        "* I_j = sum_i V_i * G_ji     (virtual-ground current sum)",
        "* V_lin_j = I_j / G_SCALE    (H-source transimpedance)",
        "* V_y_j ≈ max(0, V_lin_j)    (diode precision rectifier)",
        "*",
        "* The H source is an analog of a transimpedance amplifier so the",
        "* rectifier can operate in voltage mode at the same scale as Y.",
        "* The diode is the nonlinear element; op-amp feedback cancels Vf.",
        "*",
        f"* G_SCALE = {G_SCALE:.15g} S per unit weight",
        "",
    ]

    for i, xi in enumerate(x, start=1):
        lines.append(f"V_{i} in{i} 0 DC {xi:.15g}")
    lines.append("")

    for j in range(n_out):
        neuron = j + 1
        lines.append(f"* --- Neuron {neuron} ---")
        for i in range(n_in):
            inp = i + 1
            lines.append(
                f"* W[{neuron},{inp}] = {w[j, i]:.15g} -> R_{neuron}_{inp} = {r[j, i]:.15g} Ohm"
            )
            lines.append(f"R_{neuron}_{inp} in{inp} sum{neuron} {r[j, i]:.15g}")
        lines.append(f"Vam{neuron} sum{neuron} 0 DC 0")
        lines.append(f"Hlin{neuron} lin{neuron} 0 Vam{neuron} {R_IV:.15g}")
        lines.append(
            f"Bop{neuron} amp{neuron} 0 V = max(-{OPAMP_RAIL:.15g}, "
            f"min({OPAMP_RAIL:.15g}, {OPAMP_GAIN:.15g} * v(lin{neuron}, y{neuron})))"
        )
        lines.append(f"Drelu{neuron} amp{neuron} y{neuron} Dsi")
        lines.append(f"Rload{neuron} y{neuron} 0 {RLOAD:.15g}")
        lines.append("")

    lines.append(".model Dsi D(Is=1e-14 N=1 Rs=1)")
    lines.append("")
    lines.append(".control")
    lines.append("op")
    for j in range(1, n_out + 1):
        lines.append(f"print i(Vam{j})")
        lines.append(f"print v(lin{j})")
        lines.append(f"print v(y{j})")
        lines.append(f"print v(sum{j})")
    lines.append(".endc")
    lines.append("")
    lines.append(".end")
    lines.append("")
    return "\n".join(lines)


def simulate_case(
    ngspice: Path,
    x: np.ndarray,
    w: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, str, str, int]:
    r = weights_to_resistances(w)
    CIRCUIT_PATH.write_text(generate_circuit(x, w, r), encoding="utf-8")
    result = run_ngspice(ngspice, CIRCUIT_PATH)
    combined = f"{result.stdout}\n{result.stderr}"
    n_out = w.shape[0]
    currents = []
    v_lin = []
    v_y = []
    for j in range(1, n_out + 1):
        i_j = extract_named_value(combined, f"i(vam{j})")
        lin_j = extract_named_value(combined, f"v(lin{j})")
        y_j = extract_named_value(combined, f"v(y{j})")
        if i_j is None or lin_j is None or y_j is None:
            raise RuntimeError(
                f"Could not parse i(Vam{j}), v(lin{j}), v(y{j}) from ngspice.\n"
                f"{result.stdout}\n{result.stderr}"
            )
        currents.append(i_j)
        v_lin.append(lin_j)
        v_y.append(y_j)
    return (
        np.array(currents, dtype=float),
        np.array(v_lin, dtype=float),
        np.array(v_y, dtype=float),
        result.stdout or "",
        result.stderr or "",
        result.returncode,
    )


def main() -> int:
    print("PHYSICAL AI - EXPERIMENT 4")
    print("Integrated physical neurons (linear layer + activation)")
    print()
    print("Weight matrix (positive conductances only):")
    print(fmt_matrix(W))
    print()
    print("Negative linear sums use signed input voltages.")
    print("Positive resistors are not treated as negative weights.")
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
    worst_relu_error = 0.0

    for idx, case in enumerate(CASES, start=1):
        x = case["x"]
        y_linear = W @ x
        y_expected = np.maximum(0.0, y_linear)

        print(f"--- Test case {idx}: {case['name']} ---")
        print("Input vector:")
        print(fmt_vector(x))
        print()
        print("Mathematical linear result Y = W @ X:")
        print(fmt_vector(y_linear))
        print()
        print("Expected ReLU(Y) (Python reference only):")
        print(fmt_vector(y_expected))
        print()

        try:
            currents, v_lin, v_y, stdout, stderr, code = simulate_case(
                ngspice, x, W
            )
        except (OSError, RuntimeError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

        print("--- ngspice output ---")
        if stdout.strip():
            print(stdout.rstrip())
        if stderr.strip():
            print("--- ngspice stderr ---")
            print(stderr.rstrip())
        print("--- end ngspice output ---")
        print(f"ngspice exit code: {code}")
        print()

        y_from_current = currents / G_SCALE
        linear_err = np.abs(y_from_current - y_linear)
        relu_err = np.abs(v_y - y_expected)
        max_linear = float(np.max(linear_err))
        max_relu = float(np.max(relu_err))
        worst_relu_error = max(worst_relu_error, max_relu)

        for j, current in enumerate(currents, start=1):
            print(f"Neuron {j} physical current: {current:.6e} A")
            print(f"Neuron {j} transimpedance voltage v(lin{j}): {v_lin[j - 1]:.6f} V")
            print(f"Neuron {j} physical output v(y{j}): {v_y[j - 1]:.6f} V")
        print()
        print("Physical linear result (I / G_SCALE):")
        print(fmt_vector(y_from_current))
        print()
        print("Physical result after activation:")
        print(fmt_vector(v_y))
        print()
        print("Absolute error vs ReLU(W @ X):")
        print(fmt_vector(relu_err))
        print()
        print(f"Maximum linear error: {max_linear:.6e}")
        print(f"Maximum ReLU error:   {max_relu:.6e}")
        print()

        case_failed = False
        if code != 0:
            print("CASE FAILED: ngspice returned a non-zero exit code.")
            case_failed = True
        if max_linear > LINEAR_TOL:
            print("CASE FAILED: physical linear stage does not match W @ X.")
            case_failed = True
        if max_relu > RELU_TOL:
            print("CASE FAILED: physical activation does not match ReLU(W @ X).")
            case_failed = True
        if not case_failed:
            print("CASE PASSED")
        print()
        any_failed = any_failed or case_failed

    print(f"Worst ReLU error across cases: {worst_relu_error:.6e}")
    print()
    if any_failed:
        print("SIMULATION FAILED")
        return 1
    print("SIMULATION PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
