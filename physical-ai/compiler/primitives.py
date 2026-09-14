"""SPICE emitters for validated Physical AI primitives.

These emit topology. They do not evaluate the neural network.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OPA189_LIB = PROJECT_ROOT / "models" / "vendor" / "ti" / "opa189" / "OPAx189.LIB"
DIODE_LIB = PROJECT_ROOT / "models" / "vendor" / "ti" / "1n4148" / "1N4148.LIB"

R_INVERT = 10_000.0
R_RELU_LOAD = 10_000.0
C_NODE = 1e-12


def include_models() -> list[str]:
    return [
        f".include \"{OPA189_LIB.as_posix()}\"",
        f".include \"{DIODE_LIB.as_posix()}\"",
    ]


def emit_supplies(vsupply: float) -> list[str]:
    return [
        f"Vdd vdd 0 DC {vsupply:.15g}",
        f"Vss vss 0 DC {-vsupply:.15g}",
    ]


def emit_inverter_opa189(tag: str, src: str, dest: str) -> list[str]:
    inn = f"{tag}inn"
    return [
        f"* Inverter_OPA189 {tag}: {dest} = -{src}",
        f"R{tag}in {src} {inn} {R_INVERT:.15g}",
        f"R{tag}f {dest} {inn} {R_INVERT:.15g}",
        f"X{tag} 0 {inn} vdd vss {dest} OPAx189",
        f"C{tag} {dest} 0 {C_NODE:.15g}",
    ]


def emit_tia_opa189(tag: str, sum_node: str, out_node: str, rf: float) -> list[str]:
    return [
        f"* TIA_OPA189 {tag}: {out_node} = -Rf * I({sum_node})",
        f"R{tag}f {out_node} {sum_node} {rf:.15g}",
        f"X{tag}tia 0 {sum_node} vdd vss {out_node} OPAx189",
        f"C{tag}tia {out_node} 0 {C_NODE:.15g}",
    ]


def emit_relu_opa189_1n4148(tag: str, src: str, dest: str) -> list[str]:
    """Inverting precision rectifier: dest ~= max(-src, 0).

    Experiment 62 single-diode superdiode is valid in isolation. Experiment 63
    OP/TRAN aborted on that diode with four saturated ReLU amps. The clamp
    follower (anode/cathode both ways around y) passed negatives and was
    rejected. This textbook two-diode inverting rectifier keeps the amp
    inside local feedback and uses the same documented 1N4148 card.

    Hidden TIA must emit -z so dest = max(z, 0).
    """
    inn = f"{tag}rinn"
    amp = f"{tag}amp"
    return [
        f"* ReLU_OPA189_1N4148 {tag}: {dest} ~= max(-{src}, 0)",
        f"* Inverting precision rectifier (Exp64). Same 1N4148 card.",
        f"R{tag}r1 {src} {inn} {R_INVERT:.15g}",
        f"X{tag}relu 0 {inn} vdd vss {amp} OPAx189",
        f"X{tag}d1 {inn} {amp} 1N4148",
        f"X{tag}d2 {amp} {dest} 1N4148",
        f"R{tag}rf {dest} {inn} {R_INVERT:.15g}",
        f"R{tag}rl {dest} 0 {R_RELU_LOAD:.15g}",
        f"C{tag}rl {dest} 0 {C_NODE:.15g}",
    ]


def signed_source(
    weight: float,
    pos_node: str,
    neg_node: str,
    tia_inverts: bool = False,
) -> str | None:
    """Architecture A: V_tia = -Σ V_src |w|.

    tia_inverts=False -> V_tia = +w*x (output neuron).
    tia_inverts=True  -> V_tia = -w*x (hidden, so the inverting rectifier
    can recover ReLU without a follower superdiode).
    """
    if weight == 0.0:
        return None
    want_inverted_src = (weight > 0) != tia_inverts
    return neg_node if want_inverted_src else pos_node


def e96_nearest(value: float) -> float:
    seq = [
        1.00, 1.02, 1.05, 1.07, 1.10, 1.13, 1.15, 1.18, 1.21, 1.24, 1.27,
        1.30, 1.33, 1.37, 1.40, 1.43, 1.47, 1.50, 1.54, 1.58, 1.62, 1.65,
        1.69, 1.74, 1.78, 1.82, 1.87, 1.91, 1.96, 2.00, 2.05, 2.10, 2.15,
        2.21, 2.26, 2.32, 2.37, 2.43, 2.49, 2.55, 2.61, 2.67, 2.74, 2.80,
        2.87, 2.94, 3.01, 3.09, 3.16, 3.24, 3.32, 3.40, 3.48, 3.57, 3.65,
        3.74, 3.83, 3.92, 4.02, 4.12, 4.22, 4.32, 4.42, 4.53, 4.64, 4.75,
        4.87, 4.99, 5.11, 5.23, 5.36, 5.49, 5.62, 5.76, 5.90, 6.04, 6.19,
        6.34, 6.49, 6.65, 6.81, 6.98, 7.15, 7.32, 7.50, 7.68, 7.87, 8.06,
        8.25, 8.45, 8.66, 8.87, 9.09, 9.31, 9.53, 9.76,
    ]
    if value <= 0:
        return value
    exp = 0
    mantissa = value
    while mantissa >= 10.0:
        mantissa /= 10.0
        exp += 1
    while mantissa < 1.0:
        mantissa *= 10.0
        exp -= 1
    best = min(seq, key=lambda s: abs(s - mantissa))
    return best * (10.0**exp)
