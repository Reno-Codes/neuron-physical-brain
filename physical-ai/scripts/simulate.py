"""Physical AI — Experiment 1: simulate a resistor-network weighted sum."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CIRCUIT_PATH = PROJECT_ROOT / "circuits" / "neuron.cir"
NGSPICE_CANDIDATES = (
    Path(r"C:\ngspice\bin\ngspice_con.exe"),
    Path("ngspice_con.exe"),
)

# Circuit parameters (must match circuits/neuron.cir)
V1 = 1.0
V2 = 2.0
R1 = 10_000.0
R2 = 20_000.0
R3 = 10_000.0
TOLERANCE = 1e-4


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


def expected_vout() -> float:
    """KCL nodal voltage at the output node of the resistor network."""
    return (V1 / R1 + V2 / R2) / (1.0 / R1 + 1.0 / R2 + 1.0 / R3)


def run_ngspice(ngspice: Path, circuit: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(ngspice), "-b", str(circuit)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(circuit.parent),
    )


def extract_vout(text: str) -> float | None:
    """Parse v(out) from ngspice batch / .op output."""
    patterns = (
        r"v\(\s*out\s*\)\s*=\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)",
        r"^\s*out\s+([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            return float(match.group(1))
    return None


def simulation_succeeded(result: subprocess.CompletedProcess[str]) -> bool:
    combined = f"{result.stdout}\n{result.stderr}"
    fatal = (
        "Error:",
        "fatal error",
        "can't open",
        "Circuit not loaded",
        "Simulation interrupted",
    )
    if any(token.lower() in combined.lower() for token in fatal):
        # ngspice often prints "Error on line..." even when it continues;
        # treat as failure only if we also have a non-zero exit or no v(out).
        if result.returncode != 0:
            return False
    if result.returncode != 0:
        return False
    return extract_vout(combined) is not None or "Initial Transient Solution" in combined or "Node" in combined


def main() -> int:
    print("PHYSICAL AI - EXPERIMENT 1")
    print()
    print(f"Input 1: {V1:.1f} V")
    print(f"Input 2: {V2:.1f} V")
    print()
    print(f"R1: {R1 / 1000:.0f} kOhm")
    print(f"R2: {R2 / 1000:.0f} kOhm")
    print(f"R3: {R3 / 1000:.0f} kOhm")
    print()

    expected = expected_vout()
    print(f"Expected Vout: {expected:.6f} V")

    if not CIRCUIT_PATH.is_file():
        print(f"ERROR: circuit file not found: {CIRCUIT_PATH}", file=sys.stderr)
        return 1

    try:
        ngspice = find_ngspice()
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"ngspice executable: {ngspice}")
    print(f"circuit: {CIRCUIT_PATH}")
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
    simulated = extract_vout(combined)

    if simulated is None:
        print("Simulated Vout: (could not extract)")
        print("Error: n/a")
        print()
        print("SIMULATION FAILED")
        print("Could not parse the output-node voltage from ngspice.")
        return 1

    error = abs(simulated - expected)
    print(f"Simulated Vout: {simulated:.6f} V")
    print(f"Error: {error:.6e} V")
    print()

    if not simulation_succeeded(result) and result.returncode != 0:
        print("SIMULATION FAILED")
        return 1

    if error <= TOLERANCE:
        print("SIMULATION PASSED")
        return 0

    print("SIMULATION FAILED")
    print(f"Expected and simulated voltages differ by more than {TOLERANCE} V.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
