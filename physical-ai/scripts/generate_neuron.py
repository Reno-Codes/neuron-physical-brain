"""Physical AI - Experiment 2: compile neural weights into a SPICE circuit.

Experiment 1 used a manually designed resistor network.
Experiment 2 starts a primitive compiler:

    numerical neural weights
            ->
    automatic circuit generation
            ->
    physical computation (Ohm + Kirchhoff)

This is still not a complete artificial neuron: no bias, no activation,
no negative weights, and no multi-neuron topology. It only shows that
weights can become conductances and that currents then perform the sum.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CIRCUIT_PATH = PROJECT_ROOT / "circuits" / "generated_neuron.cir"
NGSPICE_CANDIDATES = (
    Path(r"C:\ngspice\bin\ngspice_con.exe"),
    Path("ngspice_con.exe"),
)

# Neural parameters
X1 = 1.0
X2 = 2.0
W1 = 0.2
W2 = 0.4

# G = G_SCALE * w  so  I / G_SCALE = sum(w_i * x_i)
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


def weight_to_conductance(weight: float) -> float:
    if weight <= 0:
        raise ValueError("This experiment supports positive weights only.")
    return G_SCALE * weight


def conductance_to_resistance(conductance: float) -> float:
    return 1.0 / conductance


def generate_circuit(
    x1: float,
    x2: float,
    w1: float,
    w2: float,
    g1: float,
    g2: float,
    r1: float,
    r2: float,
) -> str:
    """Current-summing neuron with an exact virtual ground.

    Each input voltage drives a conductance toward node `sum`.
    Vam1/Vam2 are 0 V series ammeters (ngspice does not expose i(R)).
    Vsense is a 0 V source from `sum` to ground: it clamps the summing
    node to 0 V (so Ohm's law is I = V*G exactly) and measures I_total.
    This is not the Experiment 1 voltage divider.
    """
    return f"""* Physical AI - Experiment 2: neural weights compiled to a circuit
*
* Compiler pipeline:
*     numerical weights -> conductances G = G_SCALE * w
*     voltages x represent neural inputs
*     Ohm's law: I_i = x_i * G_i = G_SCALE * w_i * x_i
*     KCL at the summing node: I_total = I1 + I2
*     Normalize: I_total / G_SCALE = w1*x1 + w2*x2
*
* Vsense (0 V) holds node `sum` at ground so the current-sum is exact,
* not a loaded weighted average as in Experiment 1.
* Vam1 and Vam2 are 0 V ammeters in series with each weight resistor.
*
* G_SCALE = {G_SCALE:.15g} S per unit weight

V1 in1 0 DC {x1:.15g}
V2 in2 0 DC {x2:.15g}

* weight {w1:.15g}
* conductance {g1:.15g} S
* resistance {r1:.15g} Ohm
R1 in1 n1 {r1:.15g}
Vam1 n1 sum DC 0

* weight {w2:.15g}
* conductance {g2:.15g} S
* resistance {r2:.15g} Ohm
R2 in2 n2 {r2:.15g}
Vam2 n2 sum DC 0

* 0 V ammeter / virtual ground: V(sum) = 0, i(Vsense) = I1 + I2
Vsense sum 0 DC 0

.control
op
print i(Vam1)
print i(Vam2)
print i(Vsense)
print v(sum)
.endc

.end
"""


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
    """Parse ngspice `print` lines such as `i(r1) = 2.000000e-05`."""
    escaped = re.escape(name)
    pattern = (
        rf"{escaped}\s*=\s*"
        rf"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
    )
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if match:
        return float(match.group(1))
    return None


def main() -> int:
    print("PHYSICAL AI - EXPERIMENT 2")
    print()
    print(f"Input 1: {X1:.1f}")
    print(f"Input 2: {X2:.1f}")
    print()
    print(f"Weight 1: {W1}")
    print(f"Weight 2: {W2}")
    print()

    g1 = weight_to_conductance(W1)
    g2 = weight_to_conductance(W2)
    r1 = conductance_to_resistance(g1)
    r2 = conductance_to_resistance(g2)

    print(f"G_SCALE: {G_SCALE:.6e} S")
    print()
    print(f"Weight 1: {W1}")
    print(f"Conductance 1: {g1:.6e} S")
    print(f"Resistance 1: {r1:.6f} Ohm")
    print()
    print(f"Weight 2: {W2}")
    print(f"Conductance 2: {g2:.6e} S")
    print(f"Resistance 2: {r2:.6f} Ohm")
    print()

    mathematical_result = W1 * X1 + W2 * X2
    print("Mathematical weighted sum:")
    print(f"{mathematical_result:.6f}")
    print()

    CIRCUIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CIRCUIT_PATH.write_text(
        generate_circuit(X1, X2, W1, W2, g1, g2, r1, r2),
        encoding="utf-8",
    )
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
    i1 = extract_named_value(combined, "i(vam1)")
    i2 = extract_named_value(combined, "i(vam2)")
    i_total = extract_named_value(combined, "i(vsense)")

    if i1 is None or i2 is None or i_total is None:
        print("Physical current result: (could not extract currents)")
        print()
        print("SIMULATION FAILED")
        print("Could not parse i(Vam1), i(Vam2), and i(Vsense) from ngspice.")
        return 1

    if result.returncode != 0:
        print("SIMULATION FAILED")
        print("ngspice returned a non-zero exit code.")
        return 1

    # i(Vam1)/i(Vam2) are branch currents into the summing node.
    physical_i_total = i1 + i2
    normalized = i_total / G_SCALE
    error = abs(normalized - mathematical_result)

    print()
    print(f"Simulated I1: {i1:.6e} A")
    print(f"Simulated I2: {i2:.6e} A")
    print(f"Simulated I_total (Vsense): {i_total:.6e} A")
    print(f"I1 + I2: {physical_i_total:.6e} A")
    print()
    print("Physical current result:")
    print(f"{i_total:.6e} A")
    print()
    print("Normalized physical result:")
    print(f"{normalized:.6f}")
    print()
    print("Error:")
    print(f"{error:.6e}")
    print()

    current_mismatch = abs(i_total - physical_i_total)
    if current_mismatch > 1e-12:
        print("SIMULATION FAILED")
        print("i(Vsense) does not equal i(Vam1) + i(Vam2); KCL check failed.")
        return 1

    if error <= TOLERANCE:
        print("SIMULATION PASSED")
        return 0

    print("SIMULATION FAILED")
    print(f"Normalized physical result differs by more than {TOLERANCE}.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
