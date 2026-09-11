"""Physical AI - Experiment 3: compile a linear layer into a SPICE circuit.

A weight matrix W becomes a physical conductance network. Shared input
voltages X drive two independent current-summing neurons in one circuit:

    Y = W @ X

is realized as

    I_j = sum_i (V_i * G_ji)
    Y_j = I_j / G_SCALE

This is still only a simplified linear layer: no activation, training,
backprop, programmable memory, or large-scale hardware.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CIRCUIT_PATH = PROJECT_ROOT / "circuits" / "generated_layer.cir"
NGSPICE_CANDIDATES = (
    Path(r"C:\ngspice\bin\ngspice_con.exe"),
    Path("ngspice_con.exe"),
)

X = np.array([1.0, 2.0, 3.0], dtype=float)
W = np.array(
    [
        [0.1, 0.2, 0.3],
        [0.4, 0.5, 0.6],
    ],
    dtype=float,
)

G_SCALE = 1e-4  # siemens per unit weight
TOLERANCE = 1e-6


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


def weights_to_resistances(weights: np.ndarray) -> np.ndarray:
    if np.any(weights <= 0):
        raise ValueError("This experiment supports positive weights only.")
    return 1.0 / (G_SCALE * weights)


def generate_circuit(x: np.ndarray, w: np.ndarray, r: np.ndarray) -> str:
    """Shared-input current-summing layer with one virtual ground per neuron."""
    n_out, n_in = w.shape
    lines: list[str] = [
        "* Physical AI - Experiment 3: linear layer compiled to a circuit",
        "*",
        "* Python weight matrix W -> conductances G = G_SCALE * W",
        "* Shared voltages X drive every neuron.",
        "* Each neuron j has its own summing node sum{j} and 0 V ammeter Vam{j}.",
        "* Ohm: I_ji = V_i * G_ji",
        "* KCL: I_j = sum_i I_ji",
        "* Normalize: Y_j = I_j / G_SCALE = (W @ X)_j",
        "*",
        f"* G_SCALE = {G_SCALE:.15g} S per unit weight",
        f"* n_in = {n_in}, n_out = {n_out}",
        "",
    ]

    for i, xi in enumerate(x, start=1):
        lines.append(f"V_{i} in{i} 0 DC {xi:.15g}")
    lines.append("")

    for j in range(n_out):
        neuron = j + 1
        lines.append(f"* Neuron {neuron}: row {neuron} of W")
        for i in range(n_in):
            inp = i + 1
            wij = w[j, i]
            gji = G_SCALE * wij
            rji = r[j, i]
            lines.append(f"* weight {wij:.15g}")
            lines.append(f"* conductance {gji:.15g} S")
            lines.append(f"* resistance {rji:.15g} Ohm")
            lines.append(f"R_{neuron}_{inp} in{inp} sum{neuron} {rji:.15g}")
        lines.append(
            f"* 0 V ammeter / virtual ground for neuron {neuron}"
        )
        lines.append(f"Vam{neuron} sum{neuron} 0 DC 0")
        lines.append("")

    lines.append(".control")
    lines.append("op")
    for j in range(1, n_out + 1):
        lines.append(f"print i(Vam{j})")
        lines.append(f"print v(sum{j})")
    lines.append(".endc")
    lines.append("")
    lines.append(".end")
    lines.append("")
    return "\n".join(lines)


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
    return "[" + ", ".join(f"{float(v):.6g}" if float(v) != int(float(v)) else f"{float(v):.1f}" for v in values) + "]"


def fmt_matrix(matrix: np.ndarray) -> str:
    rows = []
    for j, row in enumerate(matrix):
        inner = ", ".join(f"{float(v):.1f}" for v in row)
        prefix = "[[" if j == 0 else " ["
        rows.append(f"{prefix}{inner}]")
    return ",\n".join(rows) + "]"


def main() -> int:
    x = X
    w = W
    y_math = w @ x
    r = weights_to_resistances(w)
    g = G_SCALE * w
    n_out, n_in = w.shape

    print("PHYSICAL AI - EXPERIMENT 3")
    print()
    print("Input vector:")
    print(fmt_vector(x))
    print()
    print("Weight matrix:")
    print(fmt_matrix(w))
    print()
    print("Mathematical result:")
    print(fmt_vector(y_math))
    print()
    print(f"G_SCALE: {G_SCALE:.6e} S")
    print()
    print("Generated resistors (R = 1 / (G_SCALE * W)):")
    for j in range(n_out):
        for i in range(n_in):
            print(
                f"  R_{j + 1}_{i + 1}: W={w[j, i]:.1f}  "
                f"G={g[j, i]:.6e} S  R={r[j, i]:.6f} Ohm"
            )
    print()

    CIRCUIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CIRCUIT_PATH.write_text(generate_circuit(x, w, r), encoding="utf-8")
    print(f"generated circuit: {CIRCUIT_PATH}")

    try:
        ngspice = find_ngspice()
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"ngspice executable: {ngspice}")
    print()
    print("--- ngspice output ---")

    try:
        result = run_ngspice(ngspice, CIRCUIT_PATH)
    except OSError as exc:
        print(f"ERROR: failed to launch ngspice: {exc}", file=sys.stderr)
        return 1

    stdout = result.stdout or ""
    stderr = result.stderr or ""
    if stdout.strip():
        print(stdout.rstrip())
    if stderr.strip():
        print("--- ngspice stderr ---")
        print(stderr.rstrip())
    print("--- end ngspice output ---")
    print()
    print(f"ngspice exit code: {result.returncode}")

    combined = f"{stdout}\n{stderr}"
    currents: list[float] = []
    for j in range(1, n_out + 1):
        current = extract_named_value(combined, f"i(vam{j})")
        if current is None:
            print()
            print("SIMULATION FAILED")
            print(f"Could not parse i(Vam{j}) from ngspice.")
            return 1
        currents.append(current)

    if result.returncode != 0:
        print()
        print("SIMULATION FAILED")
        print("ngspice returned a non-zero exit code.")
        return 1

    i_physical = np.array(currents, dtype=float)
    y_physical = i_physical / G_SCALE
    abs_error = np.abs(y_physical - y_math)
    max_error = float(np.max(abs_error))

    print()
    for j, current in enumerate(i_physical, start=1):
        print(f"Neuron {j} physical current: {current:.6e} A")
    print()
    print("Normalized physical result:")
    print(fmt_vector(y_physical))
    print()
    print("Absolute error:")
    print(fmt_vector(abs_error))
    print()
    print("Maximum error:")
    print(f"{max_error:.6e}")
    print()

    if max_error <= TOLERANCE:
        print("SIMULATION PASSED")
        return 0

    print("SIMULATION FAILED")
    print(f"Physical Y differs from W @ X by more than {TOLERANCE}.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
