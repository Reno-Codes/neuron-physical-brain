"""Experiment 15: mismatch-limited inference on the ratiometric fabric.

Architecture D from Experiment 14 is the baseline. This module does not
retrain weights and does not correct SPICE outputs in Python.

Three physical questions
------------------------
1. Unit-resistor tiling
   Split each weight / bias / R_IV resistor into N series or parallel
   segments that stay in [1 kOhm, 1 MOhm]. Independent relative mismatch
   on each tile should average as ~1/sqrt(N) if the error is local.

2. Signed-path offset
   Perturb +path and -path resistors in opposite directions. That creates
   an analog offset, not a common scale. Layer gain calibration cannot
   cancel it.

3. Remaining active blocks
   Unity CCCS conveyors, VCVS buffers, and the direct ReLU B-source are
   still ideal in Architecture D. Inject isolated behavioral errors and
   find the first block that exceeds MAE 1e-3.

This is a behavioral mismatch study, not a layout or foundry PCM model.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from compile_xor import PROJECT_ROOT
from dynamic_range_compiler import R_MAX, R_MIN, range_violation
from ratiometric_compiler import annotate_catalog, compile_ratiometric


CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "mismatch"
TILE_ROLES = frozenset({"weight", "bias", "reference", "divider"})


@dataclass(frozen=True)
class ActiveParams:
    name: str
    cccs_common: float = 0.0
    cccs_polarity: float = 0.0
    i_leak: float = 0.0
    buf_gain: float = 0.0
    buf_vos: float = 0.0
    relu_vos: float = 0.0

    def public(self) -> dict:
        row = asdict(self)
        row["note"] = (
            "cccs_common multiplies both polarity conveyors. "
            "cccs_polarity raises +path and lowers -path. "
            "buf_* apply to VCVS copies. relu_vos adds to the ReLU argument. "
            "These are behavioral sources, not transistors."
        )
        return row


def path_sign(item: dict) -> str | None:
    if item.get("path_sign") in {"p", "n"}:
        return str(item["path_sign"])
    comment = str(item.get("comment", ""))
    if comment.endswith("w+") or comment.endswith("b+"):
        return "p"
    if comment.endswith("w-") or comment.endswith("b-"):
        return "n"
    return None


def stamp_signs(catalog: list[dict]) -> list[dict]:
    for item in catalog:
        item["path_sign"] = path_sign(item)
    return catalog


def tile_plan(resistance: float, n: int, r_min: float = R_MIN, r_max: float = R_MAX) -> tuple[str, int, float]:
    """Choose series or parallel tiles that stay in range."""
    if n <= 1:
        return "none", 1, float(resistance)
    r = float(resistance)
    if r / n >= r_min:
        return "series", n, r / n
    if n * r <= r_max:
        return "parallel", n, n * r
    n_series = int(r / r_min)
    n_para = int(r_max / r) if r > 0 else 1
    n_fit = max(1, min(n, max(n_series, n_para)))
    if n_fit > 1 and r / n_fit >= r_min:
        return "series", n_fit, r / n_fit
    if n_fit > 1 and n_fit * r <= r_max:
        return "parallel", n_fit, n_fit * r
    return "none", 1, r


def _replace_resistor_line(
    lines: list[str], name: str, new_lines: list[str]
) -> bool:
    for i, raw in enumerate(lines):
        parts = raw.split()
        if parts and parts[0] == name:
            lines[i : i + 1] = new_lines
            return True
    return False


def tile_netlist(
    netlist: str,
    catalog: list[dict],
    n: int,
    roles: frozenset[str] = TILE_ROLES,
) -> tuple[str, list[dict], dict]:
    """Expand selected resistors into N in-range tiles."""
    lines = netlist.splitlines()
    new_catalog: list[dict] = []
    stats = {
        "requested_n": n,
        "n_series": 0,
        "n_parallel": 0,
        "n_untiled": 0,
        "n_partial": 0,
        "n_source_resistors": 0,
        "n_tiles": 0,
    }
    for item in catalog:
        role = str(item.get("role", ""))
        if role not in roles or n <= 1:
            new_catalog.append(dict(item))
            if role in roles:
                stats["n_untiled"] += 1
                stats["n_source_resistors"] += 1
                stats["n_tiles"] += 1
            continue
        stats["n_source_resistors"] += 1
        mode, n_fit, r_tile = tile_plan(float(item["R"]), n)
        name = str(item["name"])
        if mode == "none":
            new_catalog.append(dict(item))
            stats["n_untiled"] += 1
            stats["n_tiles"] += 1
            continue
        if n_fit < n:
            stats["n_partial"] += 1
        # Find original nodes.
        src = dest = None
        for raw in lines:
            parts = raw.split()
            if len(parts) >= 4 and parts[0] == name:
                src, dest = parts[1], parts[2]
                break
        if src is None:
            new_catalog.append(dict(item))
            stats["n_untiled"] += 1
            stats["n_tiles"] += 1
            continue
        emitted: list[str] = [f"* tiled {name} {mode} x{n_fit}  each={r_tile:.15g}"]
        for k in range(1, n_fit + 1):
            tname = f"{name}t{k}"
            if mode == "series":
                a = src if k == 1 else f"{name}n{k - 1}"
                b = dest if k == n_fit else f"{name}n{k}"
            else:
                a, b = src, dest
            emitted.append(f"{tname} {a} {b} {r_tile:.15g}")
            child = dict(item)
            child["name"] = tname
            child["R"] = r_tile
            child["G"] = 1.0 / r_tile
            child["tile_parent"] = name
            child["tile_mode"] = mode
            child["tile_n"] = n_fit
            child["path_sign"] = path_sign(item)
            new_catalog.append(child)
            stats["n_tiles"] += 1
        if not _replace_resistor_line(lines, name, emitted):
            return netlist, catalog, {**stats, "error": f"missing {name}"}
        if mode == "series":
            stats["n_series"] += 1
        else:
            stats["n_parallel"] += 1
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(lines) + ending, annotate_catalog(new_catalog), stats


def apply_active_params(netlist: str, params: ActiveParams) -> str:
    """Rewrite F / E / B macromodels. Topology and resistor values stay."""
    out: list[str] = []
    for raw in netlist.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("*") or stripped.startswith("."):
            out.append(raw)
            continue
        parts = raw.split()
        kind = parts[0][0].upper()
        if kind == "F" and len(parts) >= 5:
            name = parts[0]
            gain = (1.0 + params.cccs_common)
            if name.endswith("p"):
                gain *= 1.0 + params.cccs_polarity
            elif name.endswith("n"):
                gain *= 1.0 - params.cccs_polarity
            out.append(f"{parts[0]} {parts[1]} {parts[2]} {parts[3]} {gain:.15g}")
            continue
        if kind == "E" and len(parts) >= 6 and params.buf_gain == 0.0 and params.buf_vos == 0.0:
            out.append(raw)
            continue
        if kind == "E" and len(parts) >= 6:
            gain = float(parts[5]) * (1.0 + params.buf_gain)
            if params.buf_vos == 0.0:
                out.append(
                    f"{parts[0]} {parts[1]} {parts[2]} {parts[3]} {parts[4]} {gain:.15g}"
                )
            else:
                # V = gain * v(nc+, nc-) + Vos
                out.append(
                    f"B{parts[0][1:]} {parts[1]} {parts[2]} V = "
                    f"{gain:.15g} * v({parts[3]}, {parts[4]}) + ({params.buf_vos:.15g})"
                )
            continue
        if kind == "B" and "relu" in parts[0].lower() and params.relu_vos != 0.0:
            # Bhre1relu h1y 0 V = max(0, min(rail, v(h1lin)))
            joined = " ".join(parts)
            vos = params.relu_vos
            if "v(" in joined and params.relu_vos != 0.0:
                out.append(
                    joined.replace(
                        "v(", f"({vos:.15g}) + v(", 1
                    )
                )
            else:
                out.append(raw)
            continue
        out.append(raw)
    # Leakage: inject on every neuron diff node if requested and not present.
    if params.i_leak:
        extra = []
        seen = set()
        for raw in out:
            parts = raw.split()
            if parts and parts[0].startswith("F") and parts[0].endswith("p") and len(parts) >= 3:
                diff = parts[2]
                tag = parts[0][1:-1]
                if tag not in seen and "cal" not in tag:
                    seen.add(tag)
                    extra.append(f"B{tag}leak 0 {diff} I = {params.i_leak:.15g}")
        # Insert before .control
        merged = []
        inserted = False
        for raw in out:
            if raw.strip().startswith(".control") and not inserted:
                merged.extend(extra)
                merged.append("")
                inserted = True
            merged.append(raw)
        out = merged
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(out) + ending


def sample_independent(catalog: list[dict], percent: float, rng) -> dict[str, float]:
    p = percent / 100.0
    values = {}
    for item in catalog:
        u = float(rng.uniform(-p, p)) if p else 0.0
        values[str(item["name"])] = float(item["R"]) * max(0.1, 1.0 + u)
    return values


def sample_signed_offset(
    catalog: list[dict],
    percent: float,
    rng,
    mode: str,
) -> dict[str, float]:
    """Opposite perturbations on + and - paths.

    systematic:
        all +path R *= (1+d), all -path R *= (1-d), d = percent/100

    random:
        each resistor with a sign gets u ~ U(-d, d)
        +path *= (1+u), -path *= (1-u) independently
        (unmatched local polarity error)

    R_IV and dividers are left at nominal: they are not a polarity pair.
    """
    d = percent / 100.0
    values = {str(item["name"]): float(item["R"]) for item in catalog}
    for item in catalog:
        sign = path_sign(item)
        if sign not in {"p", "n"}:
            continue
        if mode == "systematic":
            delta = d if sign == "p" else -d
        else:
            u = float(rng.uniform(-d, d)) if d else 0.0
            delta = u if sign == "p" else -u
        values[str(item["name"])] = float(item["R"]) * max(0.1, 1.0 + delta)
    return values


def compile_d(
    spec: dict,
    weights: dict[str, np.ndarray],
    tile_n: int = 1,
    active: ActiveParams | None = None,
    i_leak: float = 0.0,
    scale_error: float = 0.0,
) -> tuple[str | None, list[dict], dict]:
    leak = i_leak
    if active is not None and active.i_leak:
        leak = active.i_leak
    netlist, catalog, reason = compile_ratiometric(
        "D", spec, weights, scale_error=scale_error, i_leak=leak
    )
    meta = {"compile_reason": reason, "tile": None}
    if reason or netlist is None:
        return None, catalog, meta
    stamp_signs(catalog)
    if tile_n > 1:
        netlist, catalog, tile_stats = tile_netlist(netlist, catalog, tile_n)
        meta["tile"] = tile_stats
        if tile_stats.get("error"):
            return None, catalog, meta
        violation = range_violation(catalog, R_MIN, R_MAX)
        if violation:
            meta["compile_reason"] = violation
            return None, catalog, meta
    stamp_signs(catalog)
    if active is not None:
        # Leak is already in the deck from compile_ratiometric.
        active_apply = ActiveParams(
            name=active.name,
            cccs_common=active.cccs_common,
            cccs_polarity=active.cccs_polarity,
            i_leak=0.0,
            buf_gain=active.buf_gain,
            buf_vos=active.buf_vos,
            relu_vos=active.relu_vos,
        )
        netlist = apply_active_params(netlist, active_apply)
    return netlist, catalog, meta
