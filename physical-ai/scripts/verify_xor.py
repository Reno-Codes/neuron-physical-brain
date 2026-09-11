"""Physical AI - Experiment 6: software reference vs physical XOR inference.

Loads the frozen model. Does not retrain.
Software predictions are an independent NumPy reference.
Physical predictions are v(o1lin) from ngspice for each XOR input.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from compile_xor import (
    CIRCUIT_PATH,
    CLASS_THRESHOLD,
    G_SCALE,
    MODEL_PATH,
    PROJECT_ROOT,
    XOR_X,
    XOR_Y,
    classify,
    find_ngspice,
    generate_circuit,
    load_model,
    simulate_physical,
    software_forward,
    split_weight,
)


RESULTS_DIR = PROJECT_ROOT / "results"
PLOT_PATH = RESULTS_DIR / "xor_comparison.png"
OUTPUT_TOL = 1e-3
PROVENANCE_SAMPLES = 6


def fmt_input(x: np.ndarray) -> str:
    return "[" + ",".join(str(int(v)) for v in x) + "]"


def verify_provenance(
    netlist: str,
    w1: np.ndarray,
    b1: np.ndarray,
    w2: np.ndarray,
    b2: np.ndarray,
) -> tuple[bool, list[str]]:
    """Check that selected trained weights appear as R = 1/(G_SCALE*|w|) in SPICE."""
    rng = np.random.default_rng(42)
    candidates: list[tuple[str, float, str]] = []
    for j in range(w1.shape[0]):
        for i in range(w1.shape[1]):
            candidates.append((f"W1[{j},{i}]", float(w1[j, i]), f"h{j + 1}"))
        candidates.append((f"b1[{j}]", float(b1[j]), f"h{j + 1}"))
    for i in range(w2.shape[1]):
        candidates.append((f"W2[0,{i}]", float(w2[0, i]), "o1"))
    candidates.append(("b2[0]", float(b2[0]), "o1"))

    picks = rng.choice(len(candidates), size=min(PROVENANCE_SAMPLES, len(candidates)), replace=False)
    lines: list[str] = []
    ok = True
    for idx in picks:
        label, weight, _tag = candidates[idx]
        w_plus, w_minus = split_weight(weight)
        if w_plus <= 0 and w_minus <= 0:
            lines.append(f"  {label} = {weight:+.6g}: zero weight, no resistor expected")
            continue
        comp = w_plus if w_plus > 0 else w_minus
        path = "G+" if w_plus > 0 else "G-"
        expected_r = 1.0 / (G_SCALE * comp)
        token = f"{expected_r:.15g}"
        found = token in netlist
        # also accept slightly different .15g formatting by scanning resistor values
        if not found:
            found = any(
                abs(float(m) - expected_r) / expected_r < 1e-9
                for m in __import__("re").findall(
                    r"R[A-Za-z0-9]+ \S+ \S+ ([0-9.eE+-]+)", netlist
                )
            )
        status = "OK" if found else "MISSING"
        if not found:
            ok = False
        lines.append(
            f"  {label} = {weight:+.6g} -> {path} = {G_SCALE * comp:.6e} S "
            f"-> R = {expected_r:.6f} Ohm  [{status}]"
        )
    return ok, lines


def plot_comparison(software: list[float], physical: list[float]) -> None:
    labels = [fmt_input(x) for x in XOR_X]
    idx = np.arange(len(labels))
    width = 0.35
    fig, ax = plt.subplots(figsize=(8.0, 4.8))
    ax.bar(idx - width / 2, software, width, label="Software (NumPy)")
    ax.bar(idx + width / 2, physical, width, label="Physical (ngspice)")
    ax.axhline(CLASS_THRESHOLD, color="0.4", ls="--", lw=1, label="class threshold 0.5")
    ax.set_xticks(idx)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Network output")
    ax.set_xlabel("XOR input")
    ax.set_title("Physical AI - Experiment 6: trained XOR, software vs physical")
    ax.legend()
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(PLOT_PATH, dpi=150)
    plt.close(fig)


def main() -> int:
    print("PHYSICAL AI - EXPERIMENT 6")
    print("Software reference vs physical inference")
    print()
    print(f"Frozen model: {MODEL_PATH}")
    print(f"Classification: output >= {CLASS_THRESHOLD} -> class 1, else 0")
    print()

    try:
        model = load_model()
        ngspice = find_ngspice()
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    w1, b1, w2, b2 = model["W1"], model["b1"], model["W2"], model["b2"]

    print("Software predictions (NumPy, frozen weights):")
    print(f"{'Input':<10} {'Target':>6} {'Software':>10} {'Class':>6}")
    sw_out: list[float] = []
    sw_cls: list[int] = []
    for x, target in zip(XOR_X, XOR_Y):
        y = software_forward(x, w1, b1, w2, b2)
        c = classify(y)
        sw_out.append(y)
        sw_cls.append(c)
        print(f"{fmt_input(x):<10} {target:6d} {y:10.6f} {c:6d}")
    print()

    print("Physical predictions (ngspice, one circuit evaluation per input):")
    print(f"{'Input':<10} {'Target':>6} {'Physical':>10} {'Class':>6}")
    ph_out: list[float] = []
    ph_cls: list[int] = []
    last_catalog: list = []
    try:
        for x, target in zip(XOR_X, XOR_Y):
            y, _kcl, catalog, _text, _code = simulate_physical(
                ngspice, x, w1, b1, w2, b2
            )
            c = classify(y)
            ph_out.append(y)
            ph_cls.append(c)
            last_catalog = catalog
            print(f"{fmt_input(x):<10} {target:6d} {y:10.6f} {c:6d}")
    except (OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print()

    errors = [abs(p - s) for p, s in zip(ph_out, sw_out)]
    max_err = max(errors)
    sw_acc = float(np.mean(np.array(sw_cls) == XOR_Y))
    ph_acc = float(np.mean(np.array(ph_cls) == XOR_Y))

    print("PHYSICAL AI - EXPERIMENT 6")
    print()
    print(
        f"{'Input':<8} {'Target':>6} {'Software':>10} {'Physical':>10} "
        f"{'Error':>10} {'Scls':>5} {'Pcls':>5}"
    )
    print("-" * 63)
    for x, t, s, p, e, sc, pc in zip(
        XOR_X, XOR_Y, sw_out, ph_out, errors, sw_cls, ph_cls
    ):
        print(
            f"{fmt_input(x):<8} {t:6d} {s:10.6f} {p:10.6f} {e:10.3e} {sc:5d} {pc:5d}"
        )
    print()
    print("Software accuracy:")
    print(f"{sw_acc * 100:.0f}%")
    print()
    print("Physical accuracy:")
    print(f"{ph_acc * 100:.0f}%")
    print()
    print("Maximum output error:")
    print(f"{max_err:.6e}")
    print()

    netlist, _ = generate_circuit(XOR_X[0], w1, b1, w2, b2)
    # Restore an inspectable netlist after the last [1,1] simulate overwrite.
    CIRCUIT_PATH.write_text(netlist, encoding="utf-8")
    prov_ok, prov_lines = verify_provenance(netlist, w1, b1, w2, b2)
    print("Parameter provenance (trained weight -> conductance -> resistor):")
    print("\n".join(prov_lines))
    print(f"Provenance check: {'PASSED' if prov_ok else 'FAILED'}")
    print(f"Compiled resistors in this netlist: {len(last_catalog)}")
    print()

    plot_comparison(sw_out, ph_out)
    print(f"Wrote {PLOT_PATH}")
    print()

    if sw_acc < 1.0:
        print("SIMULATION FAILED")
        print("Frozen software model does not classify all XOR inputs.")
        return 1
    if ph_acc < 1.0:
        print("SIMULATION FAILED")
        print("Physical circuit did not classify all XOR inputs correctly.")
        print("Weights were not edited to force a pass.")
        return 1
    if max_err > OUTPUT_TOL:
        print("SIMULATION FAILED")
        print(f"Physical outputs differ from software by more than {OUTPUT_TOL}.")
        return 1
    if not prov_ok:
        print("SIMULATION FAILED")
        print("Generated resistors do not match the frozen trained weights.")
        return 1

    print("SIMULATION PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
