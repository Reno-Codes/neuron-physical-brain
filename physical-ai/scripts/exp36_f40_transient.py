"""Experiment 36: F40 Gear transient helpers.

Frozen Experiment 9 weights. SPICE is the source of truth.
Does not overwrite Experiments 1-35. Does not transistorize Network F.
Qualified transient policy: .option method=gear
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from compile_xor import PROJECT_ROOT
from exp35_n32_qualification import (
    ERROR_LIMIT,
    MAX_ABS_LIMIT,
    analog_mae_failing_indices,
    eval_fabric,
    fmt,
    option_line,
    slim_eval,
)


CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp36_f40_physical_hidden_inverter"
RESULTS_DIR = PROJECT_ROOT / "results"
TIMEOUT_VEC = 45.0
TIMEOUT_BATCH = 900.0
QUAL_RELTOL = 5e-5
QUAL_METHOD = "gear"


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
    return CIRCUIT_DIR / f"{''.join(slug).replace('.', 'p')[:100]}.cir"


def gear_options(reltol: float | None = None) -> str:
    return option_line(method=QUAL_METHOD, reltol=reltol)


def run_independent_tran(
    ng,
    net,
    spec,
    x,
    y,
    tag: str,
    t_hold: float = 2e-4,
    reltol: float | None = None,
    timeout: float = TIMEOUT_VEC,
):
    """One ngspice process per vector. Qualified sampled-inference protocol."""
    options = gear_options(reltol)
    per_mae = []
    per_max = []
    per_acc = []
    rows = []
    ok = True
    t_sum = 0.0
    x = np.atleast_2d(np.asarray(x, dtype=float))
    y = np.atleast_2d(np.asarray(y, dtype=float))
    for i in range(len(x)):
        rec = eval_fabric(
            ng,
            net,
            spec,
            x[i : i + 1],
            y[i : i + 1],
            dest("tran", tag, t_hold, i),
            options=options,
            mode="tran",
            t_hold=t_hold,
            timeout=timeout,
        )
        row = slim_eval(rec)
        row.update({"vector": i, "t_hold": t_hold, "method": QUAL_METHOD, "reltol": reltol})
        rows.append(row)
        t_sum += float(rec.get("spice_s") or 0)
        print(
            f"  TRAN {tag} vec{i} {t_hold:g}s MAE={fmt(rec.get('mae'))} "
            f"fail={rec.get('failed')} t={fmt(rec.get('spice_s'), '.1f')}",
            flush=True,
        )
        if rec.get("failed") or rec.get("mae") is None:
            ok = False
            per_mae.append(None)
            per_max.append(None)
            per_acc.append(None)
        else:
            per_mae.append(rec["mae"])
            per_max.append(rec["max_abs_error"])
            per_acc.append(rec["accuracy"])
    summary = {
        "mae": None if not ok else float(np.mean(per_mae)),
        "max_abs_error": None if not ok else float(np.max(per_max)),
        "accuracy": None if not ok else float(np.mean(per_acc)),
        "analog_pass": bool(ok and float(np.mean(per_mae)) <= ERROR_LIMIT),
        "max_pass": bool(ok and float(np.max(per_max)) <= MAX_ABS_LIMIT),
        "failed": not ok,
        "failure_reason": None if ok else "one or more independent TRAN vectors failed",
        "spice_s": t_sum,
        "option_line": options,
        "mode": "tran",
        "t_hold": t_hold,
        "per_vector_mae": per_mae,
        "per_vector_max": per_max,
        "failing_vector_indices": [i for i, m in enumerate(per_max) if m is not None and m > ERROR_LIMIT],
        "analog_mae_fail": [i for i, m in enumerate(per_mae) if m is not None and m > ERROR_LIMIT],
        "n_vectors": int(len(x)),
        "method": QUAL_METHOD,
        "protocol": "independent_per_vector",
        "note": f"F{len(x)} independent Gear TRAN {t_hold} s {tag}",
        "worst_vector": None if not ok else int(np.argmax(per_max)),
        "correct_count": None if not ok else int(round(float(np.mean(per_acc)) * len(x))),
        "incorrect_count": None if not ok else int(len(x) - round(float(np.mean(per_acc)) * len(x))),
    }
    return summary, rows


def run_batched_tran(
    ng,
    net,
    spec,
    x,
    y,
    tag: str,
    t_hold: float = 2e-4,
    reltol: float | None = None,
    timeout: float = TIMEOUT_BATCH,
    method: str = QUAL_METHOD,
):
    """Sequential TRAN in one ngspice process. Tests inter-vector state."""
    options = option_line(method=method, reltol=reltol)
    rec = eval_fabric(
        ng,
        net,
        spec,
        x,
        y,
        dest("tranbat", tag, t_hold),
        options=options,
        mode="tran",
        t_hold=t_hold,
        timeout=timeout,
    )
    row = slim_eval(rec)
    row.update(
        {
            "t_hold": t_hold,
            "method": method,
            "reltol": reltol,
            "protocol": "batched_sequential",
            "note": f"F{len(x)} batched {method} TRAN {t_hold} s {tag}",
            "analog_mae_fail": analog_mae_failing_indices(rec),
            "n_vectors": len(x),
        }
    )
    print(
        f"  TRAN batched {tag} {method} {t_hold:g}s MAE={fmt(rec.get('mae'))} "
        f"fail={rec.get('failed')} t={fmt(rec.get('spice_s'), '.1f')}",
        flush=True,
    )
    return row
