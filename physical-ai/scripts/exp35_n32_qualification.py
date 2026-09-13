"""Experiment 35: N=32 OPA189 convergence / robustness qualification helpers.

Frozen Experiment 9 weights. SPICE is the source of truth.
Does not overwrite Experiments 1-34. Does not transistorize Network F.
Does not invent MOS W/L. Does not edit OPAx189.LIB.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from benchmark_scaling import (
    classification_labels,
    detect_spice_failure,
    error_stats,
    parse_physical_outputs,
)
from compile_xor import PROJECT_ROOT
from exp32_hidden_inverter_primitive import software_for
from offset_vg_search import run_ngspice_ex
from opa189_fabric_isolation import inject_options
from test_robustness import extract_all


CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp35_opa189_convergence"
RESULTS_DIR = PROJECT_ROOT / "results"
ERROR_LIMIT = 1.0e-3
MAX_ABS_LIMIT = 1.0e-2
TIMEOUT_DC = 360.0
TIMEOUT_TRAN = 600.0
TIMEOUT_ISO = 90.0

DEFAULT_SOLVER = {
    "reltol": 1e-3,
    "abstol": 1e-12,
    "vntol": 1e-6,
    "chgtol": 1e-14,
    "method": "trap (ngspice default)",
    "itl1": 100,
    "note": "Experiment 34 default: no .option line; ngspice factory defaults.",
}


def dest(*parts) -> Path:
    raw = "_".join(str(p) for p in parts)
    slug = []
    for ch in raw:
        if ch.isalnum() or ch in "._":
            slug.append(ch)
        elif ch in "-+":
            slug.append("m" if ch == "-" else "p")
        elif ch in " .":
            slug.append("_")
        else:
            slug.append("")
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    return CIRCUIT_DIR / f"{''.join(slug).replace('.', 'p')[:90]}.cir"


def option_line(
    reltol: float | None = None,
    abstol: float | None = None,
    vntol: float | None = None,
    chgtol: float | None = None,
    method: str | None = None,
    itl1: int | None = None,
    maxstep: float | None = None,
) -> str | None:
    parts = []
    if reltol is not None:
        parts.append(f"reltol={float(reltol):.15g}")
    if abstol is not None:
        parts.append(f"abstol={float(abstol):.15g}")
    if vntol is not None:
        parts.append(f"vntol={float(vntol):.15g}")
    if chgtol is not None:
        parts.append(f"chgtol={float(chgtol):.15g}")
    if method is not None:
        parts.append(f"method={method}")
    if itl1 is not None:
        parts.append(f"itl1={int(itl1)}")
    if maxstep is not None:
        parts.append(f"maxstep={float(maxstep):.15g}")
    if not parts:
        return None
    return ".option " + " ".join(parts)


def solver_record(**kwargs) -> dict:
    rec = dict(DEFAULT_SOLVER)
    rec.update({k: v for k, v in kwargs.items() if v is not None})
    rec["option_line"] = option_line(
        reltol=kwargs.get("reltol"),
        abstol=kwargs.get("abstol"),
        vntol=kwargs.get("vntol"),
        chgtol=kwargs.get("chgtol"),
        method=kwargs.get("method") if kwargs.get("method") not in (None, "trap (ngspice default)") else None,
        itl1=kwargs.get("itl1") if kwargs.get("itl1") not in (None, 100) else None,
        maxstep=kwargs.get("maxstep"),
    )
    return rec


def _control_dc(inputs, n_out: int, reset: bool = False) -> str:
    lines = [".control", "set numdgt=15"]
    for x in inputs:
        if reset:
            lines.append("reset")
        for i, xi in enumerate(np.atleast_1d(x), start=1):
            lines.append(f"alter Vin{i} DC {float(xi):.15g}")
        lines.append("op")
        for k in range(1, n_out + 1):
            lines.append(f"print v(o{k}lin)")
    lines.extend([".endc", "", ".end", ""])
    return "\n".join(lines)


def _control_tran(inputs, n_out: int, t_hold: float, tstep: float | None = None, uic=False) -> str:
    if tstep is None:
        tstep = max(t_hold / 200.0, 1e-7)
    lines = [".control", "set numdgt=15"]
    for vi, x in enumerate(inputs):
        for i, xi in enumerate(np.atleast_1d(x), start=1):
            lines.append(f"alter Vin{i} DC {float(xi):.15g}")
        uic_s = " uic" if uic else ""
        lines.append(f"tran {tstep:.15g} {t_hold:.15g}{uic_s}")
        for k in range(1, n_out + 1):
            name = f"v{vi}o{k}end"
            lines.append(f"meas tran {name} find v(o{k}lin) at={t_hold:.15g}")
            lines.append(f"print {name}")
    lines.extend([".endc", "", ".end", ""])
    return "\n".join(lines)


def parse_tran_outputs(text: str, n_vectors: int, n_out: int) -> np.ndarray:
    columns = []
    for k in range(1, n_out + 1):
        vals = []
        for vi in range(n_vectors):
            found = extract_all(text, f"v{vi}o{k}end")
            if not found:
                raise RuntimeError(f"missing meas v{vi}o{k}end")
            vals.append(found[-1])
        columns.append(vals)
    return np.column_stack(columns)


def diagnostics(text: str) -> dict:
    low = text.lower()
    return {
        "n_conv_warn": low.count("without convergence"),
        "n_singular": low.count("singular"),
        "n_timestep_small": low.count("timestep too small"),
        "n_fatal": low.count("fatal"),
        "n_doanalyses_fail": low.count("doanalyses"),
        "n_iteration_limit": low.count("iteration limit"),
        "n_gmin": low.count("gmin"),
        "n_source_step": low.count("source stepping"),
    }


def eval_fabric(
    ng,
    net: str,
    spec: dict,
    x,
    y,
    path: Path,
    options: str | None = None,
    reset: bool = False,
    timeout: float = TIMEOUT_DC,
    mode: str = "op",
    t_hold: float | None = None,
    tstep: float | None = None,
    uic: bool = False,
) -> dict:
    head, sep, _ = net.partition(".control")
    if not sep:
        return {"failed": True, "failure_reason": "no .control"}
    body = inject_options(head, options) if options else head
    if mode == "tran":
        ctrl = _control_tran(x, spec["n_out"], float(t_hold), tstep=tstep, uic=uic)
    else:
        ctrl = _control_dc(x, spec["n_out"], reset=reset)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.rstrip() + "\n" + ctrl, encoding="utf-8")
    t0 = time.perf_counter()
    result = run_ngspice_ex(ng, path, timeout=timeout, pspice=True)
    runtime = time.perf_counter() - t0
    text = f"{result.stdout or ''}\n{result.stderr or ''}"
    fail = detect_spice_failure(result)
    rec = {
        "failed": bool(fail),
        "failure_reason": fail,
        "spice_s": runtime,
        "option_line": options,
        "reset_before_op": reset,
        "mode": mode,
        "t_hold": t_hold,
        **diagnostics(text),
    }
    if fail:
        rec["log_tail"] = text[-500:]
        return rec
    try:
        physical = (
            parse_tran_outputs(text, len(x), spec["n_out"])
            if mode == "tran"
            else parse_physical_outputs(text, len(x), spec["n_out"])
        )
    except RuntimeError as exc:
        rec.update({"failed": True, "failure_reason": str(exc), "log_tail": text[-400:]})
        return rec
    y = np.atleast_2d(np.asarray(y, dtype=float))
    st = error_stats(physical, y)
    rec.update(st)
    rec["accuracy"] = float(np.mean(classification_labels(physical) == classification_labels(y)))
    rec["analog_pass"] = st["mae"] <= ERROR_LIMIT
    rec["max_pass"] = st["max_abs_error"] <= MAX_ABS_LIMIT
    rec["per_vector_mae"] = np.mean(np.abs(physical - y), axis=1).tolist()
    rec["per_vector_max"] = np.max(np.abs(physical - y), axis=1).tolist()
    rec["failing_vector_indices"] = [
        int(i) for i, m in enumerate(rec["per_vector_max"]) if m > ERROR_LIMIT
    ]
    rec["worst_vector"] = int(np.argmax(rec["per_vector_max"]))
    rec["worst_output"] = int(np.argmax(np.max(np.abs(physical - y), axis=0)))
    rec["n_vectors"] = len(x)
    return rec


def slim_eval(rec: dict) -> dict:
    keys = (
        "mae",
        "max_abs_error",
        "accuracy",
        "analog_pass",
        "max_pass",
        "failed",
        "failure_reason",
        "spice_s",
        "option_line",
        "reset_before_op",
        "mode",
        "t_hold",
        "per_vector_mae",
        "per_vector_max",
        "failing_vector_indices",
        "worst_vector",
        "worst_output",
        "n_conv_warn",
        "n_singular",
        "n_timestep_small",
        "n_fatal",
        "n_doanalyses_fail",
        "n_iteration_limit",
        "n_gmin",
        "n_source_step",
        "n_vectors",
        "mean_invert_residual",
        "max_invert_residual",
        "residual_by_vector",
    )
    return {k: rec.get(k) for k in keys if k in rec or k in (
        "mae", "failed", "option_line"
    )}


def analog_mae_failing_indices(rec: dict) -> list[int]:
    """Vectors whose per-vector MAE exceeds the analog bar (not max |err|)."""
    return [
        int(i)
        for i, m in enumerate(rec.get("per_vector_mae") or [])
        if m is not None and m > ERROR_LIMIT
    ]


def fmt(v, spec=".4e"):
    if v is None:
        return "n/a"
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        return format(v, spec)
    return str(v)


def slim(x):
    if isinstance(x, (np.floating, np.integer)):
        return x.item()
    return x
