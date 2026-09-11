"""Physical AI - Experiment 5: signed weights as differential conductances.

A resistor cannot be negative. Each signed weight is split in Python into
non-negative parts, then realized as two physical paths:

    w  = w+ - w-
    G+ = G_SCALE * max(w, 0)
    G- = G_SCALE * max(-w, 0)

ngspice computes I+ and I- on separate virtual grounds. CCCS copies of
those currents meet at node `diff`, where KCL performs I_diff = I+ - I-.

The reported physical result is I(Vdiff)/G_SCALE from SPICE, not a
Python subtraction of I+ and I-. The script only checks that KCL identity
as a topology diagnostic.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CIRCUIT_PATH = PROJECT_ROOT / "circuits" / "signed_weight.cir"
NGSPICE_CANDIDATES = (
    Path(r"C:\ngspice\bin\ngspice_con.exe"),
    Path("ngspice_con.exe"),
)

X = np.array([1.0, 2.0, 3.0], dtype=float)
W = np.array([0.5, -0.2, 0.3], dtype=float)
G_SCALE = 1e-4
R_IV = 1.0 / G_SCALE
TOLERANCE = 1e-6
KCL_TOL = 1e-12


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


def split_weight(weight: float) -> tuple[float, float]:
    return max(weight, 0.0), max(-weight, 0.0)


def generate_circuit(x: np.ndarray, w: np.ndarray) -> str:
    lines = [
        "* Physical AI - Experiment 5: signed-weight differential current sum",
        "*",
        "* w = w+ - w-  with separate G+ / G- paths and KCL subtraction.",
        "* No negative resistors. Python does not compute I+ - I-.",
        f"* G_SCALE = {G_SCALE:.15g} S per unit weight",
        "",
    ]
    for i, xi in enumerate(x, start=1):
        lines.append(f"V{i} in{i} 0 DC {xi:.15g}")
    lines.append("")

    plus_lines = ["* Positive conductance path -> sump"]
    minus_lines = ["* Negative conductance path -> sumn"]
    for i, wi in enumerate(w, start=1):
        w_plus, w_minus = split_weight(float(wi))
        if w_plus > 0:
            g = G_SCALE * w_plus
            r = 1.0 / g
            plus_lines.append(f"* w{i} = {wi:.15g}  w+ = {w_plus:.15g}  G+ = {g:.15g} S  R = {r:.15g} Ohm")
            plus_lines.append(f"Rp{i} in{i} sump {r:.15g}")
        if w_minus > 0:
            g = G_SCALE * w_minus
            r = 1.0 / g
            minus_lines.append(f"* w{i} = {wi:.15g}  w- = {w_minus:.15g}  G- = {g:.15g} S  R = {r:.15g} Ohm")
            minus_lines.append(f"Rn{i} in{i} sumn {r:.15g}")

    lines.extend(plus_lines)
    lines.append("Vamp sump 0 DC 0")
    lines.append("")
    lines.extend(minus_lines)
    lines.append("Vamn sumn 0 DC 0")
    lines.append("")
    lines.append("* Current copiers + KCL subtractor: I(Vdiff) = I+ - I-")
    lines.append("Fplus 0 diff Vamp 1")
    lines.append("Fminus diff 0 Vamn 1")
    lines.append("Vdiff diff 0 DC 0")
    lines.append("")
    lines.append(f"Hlin y 0 Vdiff {R_IV:.15g}")
    lines.append("")
    lines.append(".control")
    lines.append("set numdgt=15")
    lines.append("op")
    lines.append("print i(Vamp)")
    lines.append("print i(Vamn)")
    lines.append("print i(Vdiff)")
    lines.append("print v(y)")
    lines.append(".endc")
    lines.append("")
    lines.append(".end")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    y_math = float(W @ X)
    print("PHYSICAL AI - EXPERIMENT 5")
    print("Signed-weight isolation test")
    print()
    print(f"Input: {np.array2string(X, separator=', ')}")
    print(f"Weights: {np.array2string(W, separator=', ')}")
    print()
    print("Decomposition w = w+ - w-:")
    for i, wi in enumerate(W, start=1):
        w_plus, w_minus = split_weight(float(wi))
        print(f"  w{i} = {wi:+.1f}  w+ = {w_plus:.1f}  w- = {w_minus:.1f}")
        if w_plus > 0:
            print(f"       G+ = {G_SCALE * w_plus:.6e} S  R+ = {1.0 / (G_SCALE * w_plus):.6f} Ohm")
        if w_minus > 0:
            print(f"       G- = {G_SCALE * w_minus:.6e} S  R- = {1.0 / (G_SCALE * w_minus):.6f} Ohm")
    print()
    print("Mathematical y = W dot X:")
    print(f"{y_math:.6f}")
    print()

    CIRCUIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CIRCUIT_PATH.write_text(generate_circuit(X, W), encoding="utf-8")
    print(f"circuit: {CIRCUIT_PATH}")

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
    i_plus = extract_named_value(combined, "i(vamp)")
    i_minus = extract_named_value(combined, "i(vamn)")
    i_diff = extract_named_value(combined, "i(vdiff)")
    v_y = extract_named_value(combined, "v(y)")

    if None in (i_plus, i_minus, i_diff, v_y) or result.returncode != 0:
        print()
        print("SIMULATION FAILED")
        print("Could not parse I+, I-, I_diff, and v(y) from ngspice.")
        return 1

    kcl_error = abs(i_diff - (i_plus - i_minus))
    y_physical = i_diff / G_SCALE
    error = abs(y_physical - y_math)

    print()
    print(f"Physical I+  (Vamp):  {i_plus:.6e} A")
    print(f"Physical I-  (Vamn):  {i_minus:.6e} A")
    print(f"Physical I_diff (Vdiff, from KCL in SPICE): {i_diff:.6e} A")
    print(f"KCL residual |I_diff - (I+ - I-)|: {kcl_error:.6e} A")
    print(f"Transimpedance voltage v(y): {v_y:.6f} V")
    print()
    print("Physical differential result (I_diff / G_SCALE):")
    print(f"{y_physical:.6f}")
    print()
    print("Error vs mathematical y:")
    print(f"{error:.6e}")
    print()

    if kcl_error > KCL_TOL:
        print("SIMULATION FAILED")
        print("Differential topology did not perform I_diff = I+ - I- in SPICE.")
        return 1

    if error > TOLERANCE:
        print("SIMULATION FAILED")
        print("Physical differential result does not match W · X.")
        return 1

    print("SIMULATION PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
