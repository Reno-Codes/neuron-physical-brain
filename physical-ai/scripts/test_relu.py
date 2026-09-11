"""Physical AI - Experiment 4: characterize physical ReLU-like circuits.

Two topologies are measured in ngspice (not computed in Python):

1. Series silicon diode rectifier (`circuits/relu.cir`)
   Physical response is roughly max(0, Vin - Vf), not ideal ReLU.

2. Precision rectifier / superdiode (`circuits/relu_precision.cir`)
   A diode still rectifies; op-amp feedback cancels most of Vf, so the
   curve is much closer to max(0, Vin).

Python evaluates ideal ReLU only as a reference overlay.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CIRCUITS_DIR = PROJECT_ROOT / "circuits"
RESULTS_DIR = PROJECT_ROOT / "results"
PLOT_PATH = RESULTS_DIR / "relu_curve.png"
NGSPICE_CANDIDATES = (
    Path(r"C:\ngspice\bin\ngspice_con.exe"),
    Path("ngspice_con.exe"),
)

TABLE_INPUTS = (-1.0, -0.5, 0.0, 0.2, 0.5, 1.0, 2.0)
SWEEP_INPUTS = np.linspace(-1.5, 2.5, 81)
DIODE_NEG_TOL = 1e-3
PRECISION_TOL = 1e-3

RLOAD = 10_000.0
DIODE_MODEL = "Dsi D(Is=1e-14 N=1 Rs=1)"
OPAMP_GAIN = 1e5
OPAMP_RAIL = 15.0


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


def extract_all_named_values(text: str, name: str) -> list[float]:
    escaped = re.escape(name)
    pattern = (
        rf"{escaped}\s*=\s*"
        rf"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
    )
    return [float(m.group(1)) for m in re.finditer(pattern, text, flags=re.IGNORECASE)]


def foreach_block(values: np.ndarray | tuple[float, ...]) -> str:
    nums = " ".join(f"{float(v):.8g}" for v in values)
    return (
        ".control\n"
        f"foreach vin_val {nums}\n"
        "  alter Vin DC $vin_val\n"
        "  op\n"
        "  print v(in) v(out)\n"
        "end\n"
        ".endc\n"
    )


def diode_netlist(control: str) -> str:
    return (
        "* Generated diode-rectifier sweep (see circuits/relu.cir)\n"
        "Vin in 0 DC 0\n"
        "D1 in out Dsi\n"
        f"Rload out 0 {RLOAD:.15g}\n"
        f".model {DIODE_MODEL}\n"
        "\n"
        f"{control}"
        "\n.end\n"
    )


def precision_netlist(control: str) -> str:
    return (
        "* Generated precision-rectifier sweep (see circuits/relu_precision.cir)\n"
        "Vin in 0 DC 0\n"
        f"Bop amp 0 V = max(-{OPAMP_RAIL:.15g}, "
        f"min({OPAMP_RAIL:.15g}, {OPAMP_GAIN:.15g} * v(in, out)))\n"
        "D1 amp out Dsi\n"
        f"Rload out 0 {RLOAD:.15g}\n"
        f".model {DIODE_MODEL}\n"
        "\n"
        f"{control}"
        "\n.end\n"
    )


def simulate_curve(
    ngspice: Path,
    path: Path,
    netlist: str,
    inputs: np.ndarray | tuple[float, ...],
) -> tuple[np.ndarray, np.ndarray, str]:
    path.write_text(netlist, encoding="utf-8")
    result = run_ngspice(ngspice, path)
    combined = f"{result.stdout}\n{result.stderr}"
    vin = np.array(extract_all_named_values(combined, "v(in)"), dtype=float)
    vout = np.array(extract_all_named_values(combined, "v(out)"), dtype=float)
    if vin.size != len(inputs) or vout.size != len(inputs):
        raise RuntimeError(
            f"Expected {len(inputs)} (vin, vout) pairs from {path.name}, "
            f"got {vin.size} and {vout.size}.\n{combined}"
        )
    return vin, vout, combined


def print_table(vin: np.ndarray, vout: np.ndarray) -> None:
    print(f"{'Input':>10}  {'Physical Output':>16}  {'Ideal ReLU':>12}")
    for x, y in zip(vin, vout):
        print(f"{x:10.3f}  {y:16.6f}  {max(0.0, float(x)):12.3f}")
    print()


def plot_curves(
    diode_x: np.ndarray,
    diode_y: np.ndarray,
    prec_x: np.ndarray,
    prec_y: np.ndarray,
    table_x: np.ndarray,
    table_diode_y: np.ndarray,
) -> None:
    x_ref = np.linspace(-1.5, 2.5, 400)
    y_ref = np.maximum(0.0, x_ref)

    fig, ax = plt.subplots(figsize=(8.5, 5.2))
    ax.plot(x_ref, y_ref, "k--", lw=2, label="Ideal ReLU  max(0, x)")
    ax.plot(diode_x, diode_y, lw=2, label="Silicon diode rectifier")
    ax.plot(prec_x, prec_y, lw=2, label="Precision rectifier (op-amp + diode)")
    ax.scatter(table_x, table_diode_y, zorder=3, label="Diode test points")
    ax.axhline(0.0, color="0.6", lw=0.8)
    ax.axvline(0.0, color="0.6", lw=0.8)
    ax.set_xlabel("Input voltage (V)")
    ax.set_ylabel("Physical output voltage (V)")
    ax.set_title("Physical AI - Experiment 4: activation curves")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(PLOT_PATH, dpi=150)
    plt.close(fig)


def diode_behavior_ok(vin: np.ndarray, vout: np.ndarray) -> tuple[bool, str]:
    for x, y in zip(vin, vout):
        if x <= 0 and abs(y) > DIODE_NEG_TOL:
            return False, f"negative/zero input {x} V produced {y} V (expected ~0)"
        if x > 0 and y > x + 1e-3:
            return False, f"diode output {y} V exceeded input {x} V"
    y_1 = float(vout[np.argmin(np.abs(vin - 1.0))])
    y_2 = float(vout[np.argmin(np.abs(vin - 2.0))])
    if y_1 < 0.05:
        return False, "1.0 V input did not forward-bias the diode enough"
    if y_2 <= y_1:
        return False, "diode output did not increase from 1.0 V to 2.0 V"
    return True, "diode rectifies: negatives ~0, positives increase with Vin"


def precision_behavior_ok(vin: np.ndarray, vout: np.ndarray) -> tuple[bool, str]:
    ideal = np.maximum(0.0, vin)
    err = np.max(np.abs(vout - ideal))
    if err > PRECISION_TOL:
        return False, f"precision rectifier max error vs ideal ReLU is {err:.3e}"
    return True, f"precision rectifier tracks ideal ReLU (max error {err:.3e})"


def main() -> int:
    print("PHYSICAL AI - EXPERIMENT 4")
    print("Standalone nonlinear activation")
    print()
    print("Ideal ReLU is a Python reference only.")
    print("Physical Output columns come from ngspice.")
    print()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    try:
        ngspice = find_ngspice()
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"ngspice executable: {ngspice}")
    print()

    diode_run = CIRCUITS_DIR / "generated_relu_diode.cir"
    prec_run = CIRCUITS_DIR / "generated_relu_precision.cir"
    diode_sweep = CIRCUITS_DIR / "generated_relu_diode_sweep.cir"
    prec_sweep = CIRCUITS_DIR / "generated_relu_precision_sweep.cir"

    try:
        d_vin, d_vout, d_out = simulate_curve(
            ngspice,
            diode_run,
            diode_netlist(foreach_block(TABLE_INPUTS)),
            TABLE_INPUTS,
        )
        p_vin, p_vout, p_out = simulate_curve(
            ngspice,
            prec_run,
            precision_netlist(foreach_block(TABLE_INPUTS)),
            TABLE_INPUTS,
        )
        ds_vin, ds_vout, _ = simulate_curve(
            ngspice,
            diode_sweep,
            diode_netlist(foreach_block(SWEEP_INPUTS)),
            SWEEP_INPUTS,
        )
        ps_vin, ps_vout, _ = simulate_curve(
            ngspice,
            prec_sweep,
            precision_netlist(foreach_block(SWEEP_INPUTS)),
            SWEEP_INPUTS,
        )
    except (OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("--- Silicon diode rectifier (circuits/relu.cir) ---")
    print_table(d_vin, d_vout)
    print("--- Precision rectifier (circuits/relu_precision.cir) ---")
    print_table(p_vin, p_vout)

    diode_ok, diode_msg = diode_behavior_ok(d_vin, d_vout)
    prec_ok, prec_msg = precision_behavior_ok(p_vin, p_vout)

    print("Diode rectifier: " + diode_msg)
    print("Precision rectifier: " + prec_msg)
    print()
    print("The diode curve is thresholded (Vf ~ 0.5-0.7 V).")
    print("That is physical device behavior, not ideal ReLU.")
    print()

    plot_curves(ds_vin, ds_vout, ps_vin, ps_vout, d_vin, d_vout)
    print(f"Wrote {PLOT_PATH}")
    print()

    if "Error:" in d_out or "Error:" in p_out:
        print("SIMULATION FAILED")
        print("ngspice reported an error while characterizing the circuits.")
        return 1

    if diode_ok and prec_ok:
        print("SIMULATION PASSED")
        return 0

    print("SIMULATION FAILED")
    if not diode_ok:
        print(diode_msg)
    if not prec_ok:
        print(prec_msg)
    return 1


if __name__ == "__main__":
    sys.exit(main())
