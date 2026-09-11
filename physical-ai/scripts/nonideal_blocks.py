"""Experiment 12: parameterized non-ideal behavioral building blocks.

This is non-ideal behavioral circuit analysis. It is not a transistor-level
netlist, not a PCB model, and not a claim of silicon feasibility.

Ideal Experiment 11 mapping is preserved. Device-level F/E/B macromodels
can be replaced with parameterized sources that include gain error, leakage,
finite buffer gain, offset, swing, and a more realistic diode.

CCCS finite output resistance is accepted as a parameter but is electrically
idle in this topology: the difference node is a 0 V ammeter, so Rout to
ground drops no voltage.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from compile_xor import PROJECT_ROOT, RLOAD
from dynamic_range_compiler import (
    RangeConfig,
    _emit_resistor,
    encode_parameters,
    generate_banked_circuit,
)


CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "nonideal"

EXP11_A = RangeConfig(
    g_weight_1=3e-6,
    g_weight_2=3e-6,
    banks=(("f", 1e-4), ("m", 1e-2), ("n", 1.0)),
)
EXP11_F = RangeConfig(
    g_weight_1=3e-5,
    g_weight_2=3e-5,
    banks=(("f", 1e-4), ("m", 1e-2), ("n", 1.0)),
)
WINNERS = {"A": EXP11_A, "F": EXP11_F}


@dataclass(frozen=True)
class NonidealParams:
    name: str
    level: int = 0
    gain_error: float = 0.0
    i_leak: float = 0.0
    i_max: float | None = None
    r_sense: float = 0.0
    r_out_cccs: float = 0.0
    buf_open_loop: float = 1.0e12
    buf_vos: float = 0.0
    buf_rout: float = 0.0
    relu_aol: float = 1.0e5
    relu_vos: float = 0.0
    diode_is: float = 1.0e-14
    diode_n: float = 1.0
    diode_rs: float = 1.0
    rail: float = 15.0
    temp_c: float | None = None
    resistor_tc1: float = 0.0

    def is_ideal(self) -> bool:
        return (
            self.gain_error == 0.0
            and self.i_leak == 0.0
            and self.i_max is None
            and self.r_sense == 0.0
            and self.buf_open_loop >= 1.0e11
            and self.buf_vos == 0.0
            and self.buf_rout == 0.0
            and self.relu_aol == 1.0e5
            and self.relu_vos == 0.0
            and self.diode_is == 1.0e-14
            and self.diode_n == 1.0
            and self.diode_rs == 1.0
            and self.rail == 15.0
            and self.temp_c is None
            and self.resistor_tc1 == 0.0
        )

    def analysis_label(self) -> str:
        return "non-ideal behavioral circuit analysis"


def level_params(level: int, rail: float | None = None) -> NonidealParams:
    """Progressive degradation. Level 0 is the Experiment 11 ideal mapping."""
    vrail = 15.0 if rail is None else float(rail)
    if level <= 0:
        return NonidealParams(name="L0_ideal", level=0, rail=vrail)
    # L1: current-copy imperfections only.
    p = dict(
        gain_error=0.01,
        i_leak=1.0e-8,
        i_max=1.0e-2,
        r_sense=1.0,
        r_out_cccs=1.0e6,
    )
    if level == 1:
        return NonidealParams(name="L1_cccs", level=1, rail=vrail, **p)
    # L2: + finite-gain buffered hidden outputs.
    p.update(buf_open_loop=1.0e3, buf_vos=1.0e-3, buf_rout=50.0)
    if level == 2:
        return NonidealParams(name="L2_cccs_buffer", level=2, rail=vrail, **p)
    # L3: + finite-gain ReLU and a more realistic diode.
    p.update(
        relu_aol=1.0e4,
        relu_vos=1.0e-3,
        diode_is=2.0e-9,
        diode_n=1.75,
        diode_rs=0.6,
    )
    if level == 3:
        return NonidealParams(name="L3_relu", level=3, rail=vrail, **p)
    return NonidealParams(name=f"L4_supply_{vrail:g}V", level=4, rail=vrail, **p)


def _clip_current(expr: str, i_max: float | None) -> str:
    if i_max is None:
        return expr
    return f"max(-{i_max:.15g}, min({i_max:.15g}, {expr}))"


def emit_nonideal_neuron(
    lines: list[str],
    tag: str,
    input_nodes: list[str],
    weights: np.ndarray,
    bias: float,
    vref: str,
    apply_relu: bool,
    catalog: list[dict],
    g_weight: float,
    banks: tuple[tuple[str, float], ...],
    r_min: float,
    r_max: float,
    layer: int,
    params: NonidealParams,
) -> str | None:
    encoded, reason = encode_parameters(
        weights, bias, g_weight, banks, r_min, r_max
    )
    if reason is not None or encoded is None:
        return reason or "encode failed"

    diff = f"{tag}d"
    lin = f"{tag}lin"
    y = f"{tag}y"
    buf = f"{tag}buf"
    lines.append(f"* --- neuron {tag} non-ideal behavioral ---")
    used_banks: set[tuple[str, str, float]] = set()
    tc = params.resistor_tc1
    for item in encoded:
        sign = item["sign"]
        bank = item["bank"]
        dest = f"{tag}{sign}{bank}"
        used_banks.add((sign, bank, float(item["alpha"])))
        if item["kind"] == "weight":
            src = input_nodes[int(item["source_index"]) - 1]
            name = f"R{tag}{sign}{item['source_index']}{bank}{item['branch']}"
            comment = (
                f"{tag} input {item['source_index']} "
                f"w={float(weights[item['source_index'] - 1]):+.15g} "
                f"w{'+' if sign == 'p' else '-'}"
            )
        else:
            src = vref
            name = f"R{tag}b{sign}{bank}{item['branch']}"
            comment = f"{tag} bias={bias:+.15g} b{'+' if sign == 'p' else '-'}"
        _emit_resistor(
            lines, catalog, name, src, dest, item, comment, g_weight, layer
        )
        if tc != 0.0:
            # Rewrite last resistor line with a first-order tempco.
            last = lines[-1]
            if last.startswith(name + " "):
                lines[-1] = last + f" tc1={tc:.15g}"

    err = 1.0 + params.gain_error
    leak = params.i_leak
    for sign, bank, alpha in sorted(used_banks):
        node = f"{tag}{sign}{bank}"
        vs = f"V{tag}{sign}{bank}"
        if params.r_sense > 0.0:
            sense = f"{tag}{sign}{bank}s"
            lines.append(f"{vs} {node} {sense} DC 0")
            lines.append(f"R{tag}{sign}{bank}s {sense} 0 {params.r_sense:.15g}")
        else:
            lines.append(f"{vs} {node} 0 DC 0")
        expr = f"{alpha * err:.15g} * i({vs}) + {leak:.15g}"
        expr = _clip_current(expr, params.i_max)
        bname = f"B{tag}{sign}{bank}"
        if sign == "p":
            lines.append(f"{bname} 0 {diff} I = {expr}")
        else:
            lines.append(f"{bname} {diff} 0 I = {expr}")
        if params.r_out_cccs > 0.0:
            lines.append(
                f"* CCCS Rout={params.r_out_cccs:.15g} is idle: {diff} is 0 V"
            )

    lines.append(f"V{tag}d {diff} 0 DC 0")
    lines.append(f"H{tag} {lin} 0 V{tag}d {1.0 / g_weight:.15g}")
    rail = params.rail
    if apply_relu:
        lines.append(
            f"B{tag} {tag}amp 0 V = max(-{rail:.15g}, min({rail:.15g}, "
            f"{params.relu_aol:.15g} * (v({lin}) - v({y}) + {params.relu_vos:.15g})))"
        )
        lines.append(f"D{tag} {tag}amp {y} Dsi")
        lines.append(f"RL{tag} {y} 0 {RLOAD:.15g}")
        closed = params.buf_open_loop / (params.buf_open_loop + 1.0)
        swing = rail
        buf_expr = (
            f"max(-{swing:.15g}, min({swing:.15g}, "
            f"{closed:.15g} * (v({y}) + {params.buf_vos:.15g})))"
        )
        if params.buf_rout > 0.0:
            lines.append(f"B{tag}be {tag}bint 0 V = {buf_expr}")
            lines.append(f"R{tag}bo {buf} {tag}bint {params.buf_rout:.15g}")
        else:
            lines.append(f"B{tag}be {buf} 0 V = {buf_expr}")
    lines.append("")
    return None


def generate_nonideal_circuit(
    x: np.ndarray,
    w1: np.ndarray,
    b1: np.ndarray,
    w2: np.ndarray,
    b2: np.ndarray,
    config: RangeConfig,
    params: NonidealParams,
    title: str | None = None,
) -> tuple[str | None, list[dict], str | None]:
    if params.is_ideal():
        netlist, catalog, reason = generate_banked_circuit(
            x, w1, b1, w2, b2, config, title=title
        )
        return netlist, catalog, reason

    catalog: list[dict] = []
    n_in = int(w1.shape[1])
    n_hidden = int(w1.shape[0])
    n_out = int(w2.shape[0])
    header = title or (
        f"* Physical AI - Experiment 12: {params.name}\n"
        f"* {params.analysis_label()}\n"
        f"* Frozen Experiment 11 mapping: {config.label()}"
    )
    lines = [
        header,
        "* Not transistor-level. Not a PCB or silicon power model.",
        f"* rail=+/-{params.rail:g} V  gain_err={params.gain_error:g} "
        f"Ileak={params.i_leak:g} Rsense={params.r_sense:g}",
        f"* buf A={params.buf_open_loop:g} Vos={params.buf_vos:g} "
        f"Rout={params.buf_rout:g}",
        f"* ReLU Aol={params.relu_aol:g} Vos={params.relu_vos:g} "
        f"diode Is={params.diode_is:g} N={params.diode_n:g}",
        f"* {config.label()}",
        f"* shape: {n_in} -> {n_hidden} -> {n_out}",
        "",
    ]
    if params.temp_c is not None:
        lines.append(f".options TEMP={params.temp_c:.15g}")
        lines.append(f".temp {params.temp_c:.15g}")
        lines.append("")
    x = np.atleast_1d(np.asarray(x, dtype=float))
    for i in range(1, n_in + 1):
        xi = float(x[i - 1]) if i - 1 < x.size else 0.0
        lines.append(f"Vin{i} in{i} 0 DC {xi:.15g}")
    lines.append("Vref vref 0 DC 1")
    lines.append("")

    input_nodes = [f"in{i}" for i in range(1, n_in + 1)]
    for j in range(n_hidden):
        reason = emit_nonideal_neuron(
            lines, f"h{j + 1}", input_nodes, w1[j], float(b1[j]),
            "vref", True, catalog, config.g_weight_1, config.banks,
            config.r_min, config.r_max, 1, params,
        )
        if reason:
            return None, catalog, f"hidden {j + 1}: {reason}"
    hidden_nodes = [f"h{j + 1}buf" for j in range(n_hidden)]
    for k in range(n_out):
        reason = emit_nonideal_neuron(
            lines, f"o{k + 1}", hidden_nodes, w2[k], float(b2[k]),
            "vref", False, catalog, config.g_weight_2, config.banks,
            config.r_min, config.r_max, 2, params,
        )
        if reason:
            return None, catalog, f"output {k + 1}: {reason}"

    lines.append(
        f".model Dsi D(Is={params.diode_is:.15g} N={params.diode_n:.15g} "
        f"Rs={params.diode_rs:.15g} Eg=1.11 Xti=3)"
    )
    lines.append("")
    lines.append(".control")
    lines.append("set numdgt=15")
    lines.append("op")
    for k in range(1, n_out + 1):
        lines.append(f"print v(o{k}lin)")
    lines.append(".endc")
    lines.append("")
    lines.append(".end")
    lines.append("")
    return "\n".join(lines), catalog, None


def compile_nonideal(
    spec: dict,
    weights: dict[str, np.ndarray],
    params: NonidealParams,
) -> tuple[str | None, list[dict], str | None]:
    config = WINNERS[spec["id"]]
    dummy = np.zeros(spec["n_in"], dtype=float)
    title = (
        f"* Physical AI - Experiment 12: {spec['id']} {params.name}\n"
        f"* {params.analysis_label()}\n"
        f"* Frozen Experiment 9/11 weights. Mapping not retrained."
    )
    return generate_nonideal_circuit(
        dummy,
        weights["W1"],
        weights["b1"],
        weights["W2"],
        weights["b2"],
        config,
        params,
        title=title,
    )


def params_public(params: NonidealParams) -> dict:
    row = asdict(params)
    row["analysis"] = params.analysis_label()
    row["ideal"] = params.is_ideal()
    return row
