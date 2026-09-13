"""Experiment 29: physically documented resistor-ratio matching models.

Frozen Experiment 9 weights. SPICE is never Python-corrected.
These are statistical / layout *abstractions*, not a foundry PCM and not GDS.

Architecture A identity used throughout:

    Vlin ≈ −Rf · Σ Vin_i G_i

A common multiplicative scale on Rf and the G_i cancels to first order.
Independent absolute-R error does not. The models below say *which*
physical grouping that common scale is supposed to come from.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict

import numpy as np

from matching_temperature import classify_item
from mismatch_fabric import path_sign, stamp_signs, tile_netlist


ERROR_LIMIT = 1.0e-3
AMP_A = 1.0e5
AMP_A_HIGH = 1.0e7  # labeled finite-A control only
INVERT_A = 1.0e7
TOL_05 = 0.005
G_WEIGHT = 3.0e-5

# Layout abstraction: chip coords in [0, 1]. Gradient uses x' = 2x-1 ∈ [-1, 1].
# This is not lithography data.
NEURON_SPAN = 0.035


def kind_of(item: dict) -> str:
    return classify_item(item)


def neuron_tag(item: dict) -> str | None:
    name = str(item.get("name") or "")
    m = re.match(r"^R(h\d+|o\d+)", name)
    if m:
        return m.group(1)
    return None


def invert_stem(item: dict) -> str | None:
    name = str(item.get("name") or "")
    m = re.match(r"^R(inv\w+)i[ab]$", name)
    if m:
        return m.group(1)
    mg = str(item.get("match_group") or "")
    if mg.startswith("inv_"):
        return mg[4:]
    return None


def divider_stem(item: dict) -> str | None:
    name = str(item.get("name") or "")
    m = re.match(r"^R(div\w+)[ab]$", name)
    if m:
        return m.group(1)
    mg = str(item.get("match_group") or "")
    if mg.startswith("div_"):
        return mg[4:]
    return None


def pair_key(item: dict) -> str | None:
    """Same-index +/− pair (weight or bias), ignoring polarity letter."""
    name = str(item.get("name") or "")
    if path_sign(item) not in {"p", "n"}:
        return None
    return re.sub(r"[pn]", "x", name, count=1)


def annotate_fabric(catalog: list[dict]) -> list[dict]:
    stamp_signs(catalog)
    for it in catalog:
        it["kind"] = kind_of(it)
        it["neuron"] = neuron_tag(it)
        it["sign"] = path_sign(it)
        it["pair_key"] = pair_key(it)
        it["invert_stem"] = invert_stem(it)
        it["divider_stem"] = divider_stem(it)
    return catalog


def inventory(catalog: list[dict]) -> dict:
    kinds = defaultdict(int)
    layers = defaultdict(int)
    banks = defaultdict(int)
    signs = defaultdict(int)
    neurons = set()
    for it in catalog:
        kinds[kind_of(it)] += 1
        layers[int(it.get("layer") or 0)] += 1
        banks[str(it.get("bank") or "")] += 1
        s = path_sign(it)
        if s:
            signs[s] += 1
        tag = neuron_tag(it)
        if tag:
            neurons.add(tag)
    rs = [float(it["R"]) for it in catalog]
    gs = [1.0 / float(it["R"]) for it in catalog]
    return {
        "n_resistors": len(catalog),
        "n_neurons_with_r": len(neurons),
        "by_kind": dict(kinds),
        "by_layer": {str(k): v for k, v in layers.items()},
        "by_bank": dict(banks),
        "by_sign": dict(signs),
        "r_min": float(min(rs)) if rs else None,
        "r_max": float(max(rs)) if rs else None,
        "g_min": float(min(gs)) if gs else None,
        "g_max": float(max(gs)) if gs else None,
        "note": (
            "Logical compiled resistors on Architecture A. "
            "Not die area. Not a PDK bill of materials."
        ),
    }


def _u(rng, sig: float) -> float:
    if sig <= 0.0:
        return 0.0
    return float(rng.uniform(-sig, sig))


def _scale(r: float, *parts: float) -> float:
    return float(r) * max(0.1, 1.0 + float(sum(parts)))


def nominal_values(catalog: list[dict]) -> dict[str, float]:
    return {str(it["name"]): float(it["R"]) for it in catalog}


def sample_independent(catalog, tol: float, rng) -> dict[str, float]:
    """Unmatched discrete resistors. Each R gets its own draw."""
    return {str(it["name"]): _scale(it["R"], _u(rng, tol)) for it in catalog}


def sample_common_mode(catalog, tol: float, rng) -> dict[str, float]:
    """Global sheet-resistance / process scale. One draw on every R."""
    u = _u(rng, tol)
    return {str(it["name"]): _scale(it["R"], u) for it in catalog}


def sample_global_plus_local(catalog, tol_g: float, tol_l: float, rng) -> dict[str, float]:
    """Wafer-scale sheet + independent local mismatch (Pelgrom-like split)."""
    ug = _u(rng, tol_g)
    return {str(it["name"]): _scale(it["R"], ug, _u(rng, tol_l)) for it in catalog}


def sample_subset(catalog, tol: float, rng, pred) -> dict[str, float]:
    vals = nominal_values(catalog)
    for it in catalog:
        if pred(it):
            vals[str(it["name"])] = _scale(it["R"], _u(rng, tol))
    return vals


def sample_ratio_matched_exp27(catalog, tol: float, rng, local_frac: float = 0.15):
    """Exact Experiment 27 ratio_matched model applied to a whole catalog.

    One shared draw on every feedback+weight+bias resistor (network-wide
    TIA family), one draw on all divider resistors, one on all invert
    resistors, plus local_frac * tol residual. On isolated o2 this is
    one neuron. On Network F it is *not* per-neuron matching — it is a
    single global TIA-family scale.
    """
    u_tia, u_div, u_inv = _u(rng, tol), _u(rng, tol), _u(rng, tol)
    loc = local_frac * tol
    out = {}
    for it in catalog:
        k = kind_of(it)
        r = float(it["R"])
        if k in {"feedback", "weight", "bias"}:
            out[str(it["name"])] = _scale(r, u_tia, _u(rng, loc))
        elif k == "divider":
            out[str(it["name"])] = _scale(r, u_div, _u(rng, loc))
        elif k == "invert":
            out[str(it["name"])] = _scale(r, u_inv, _u(rng, loc))
        else:
            out[str(it["name"])] = _scale(r, _u(rng, tol))
    return out


def sample_ratio_matched_neuron(catalog, tol: float, rng, local_frac: float = 0.15):
    """Per-neuron matched TIA array + matched invert/divider pairs.

    Physical meaning: each neuron's {Rf, weights, bias} are taken from
    one shared unit-resistor array (common process + geometry). Invert
    R1/R2 and divider Ra/Rb are pair-matched. Local residual is the
    unmatched fraction after that grouping.
    """
    loc = local_frac * tol
    u_neu: dict[str, float] = {}
    u_inv: dict[str, float] = {}
    u_div: dict[str, float] = {}
    out = {}
    for it in catalog:
        k = kind_of(it)
        name = str(it["name"])
        r = float(it["R"])
        if k in {"feedback", "weight", "bias"}:
            tag = neuron_tag(it) or "_tia"
            if tag not in u_neu:
                u_neu[tag] = _u(rng, tol)
            out[name] = _scale(r, u_neu[tag], _u(rng, loc))
        elif k == "invert":
            stem = invert_stem(it) or name
            if stem not in u_inv:
                u_inv[stem] = _u(rng, tol)
            out[name] = _scale(r, u_inv[stem], _u(rng, loc))
        elif k == "divider":
            stem = divider_stem(it) or name
            if stem not in u_div:
                u_div[stem] = _u(rng, tol)
            out[name] = _scale(r, u_div[stem], _u(rng, loc))
        else:
            out[name] = _scale(r, _u(rng, tol))
    return out


def sample_rf_g_track(catalog, tol: float, rng, local_frac: float = 0.15):
    """Rf tracks the *sum* of that neuron's weight/bias conductances.

    Weights inside the neuron still have independent local error.
    Invert/divider pairs are matched. Tests H2: Rf-to-G_tot vs full
    intra-neuron weight matching.
    """
    loc = local_frac * tol
    u_g: dict[str, float] = {}
    u_inv: dict[str, float] = {}
    u_div: dict[str, float] = {}
    out = nominal_values(catalog)
    for it in catalog:
        tag = neuron_tag(it)
        if tag and tag not in u_g:
            u_g[tag] = _u(rng, tol)
    for it in catalog:
        k = kind_of(it)
        name = str(it["name"])
        r = float(it["R"])
        tag = neuron_tag(it)
        if k == "feedback" and tag:
            out[name] = _scale(r, u_g[tag], _u(rng, loc))
        elif k in {"weight", "bias"} and tag:
            out[name] = _scale(r, u_g[tag], _u(rng, loc))
        elif k == "invert":
            stem = invert_stem(it) or name
            if stem not in u_inv:
                u_inv[stem] = _u(rng, tol)
            out[name] = _scale(r, u_inv[stem], _u(rng, loc))
        elif k == "divider":
            stem = divider_stem(it) or name
            if stem not in u_div:
                u_div[stem] = _u(rng, tol)
            out[name] = _scale(r, u_div[stem], _u(rng, loc))
    return out


def sample_rf_only_track(catalog, tol: float, rng, local_frac: float = 0.15):
    """Weights independent; Rf of each neuron gets its own draw (no G track)."""
    loc = local_frac * tol
    out = nominal_values(catalog)
    for it in catalog:
        k = kind_of(it)
        name = str(it["name"])
        if k == "feedback":
            out[name] = _scale(it["R"], _u(rng, tol), _u(rng, loc))
        elif k in {"weight", "bias"}:
            out[name] = _scale(it["R"], _u(rng, tol))
    return out


def sample_pn_pair(catalog, tol: float, rng, include_rf: bool = False, local_frac: float = 0.0):
    """Differential pair matching. include_rf also ties that neuron's Rf."""
    shared: dict[str, float] = {}
    u_rf: dict[str, float] = {}
    loc = local_frac * tol
    out = nominal_values(catalog)
    for it in catalog:
        name = str(it["name"])
        sign = path_sign(it)
        if sign in {"p", "n"}:
            key = pair_key(it) or name
            if key not in shared:
                shared[key] = _u(rng, tol)
            out[name] = _scale(it["R"], shared[key], _u(rng, loc))
        elif include_rf and kind_of(it) == "feedback":
            tag = neuron_tag(it) or name
            if tag not in u_rf:
                u_rf[tag] = _u(rng, tol)
            out[name] = _scale(it["R"], u_rf[tag], _u(rng, loc))
    return out


def sample_pn_systematic(catalog, tol: float) -> dict[str, float]:
    """All +path *(1+tol), all −path *(1−tol). Worst signed-path field."""
    out = nominal_values(catalog)
    for it in catalog:
        sign = path_sign(it)
        if sign == "p":
            out[str(it["name"])] = _scale(it["R"], tol)
        elif sign == "n":
            out[str(it["name"])] = _scale(it["R"], -tol)
    return out


def sample_pn_correlated(catalog, tol: float, rng, rho: float, include_rf: bool = True):
    """+/− share rho * common + (1-rho) * independent. rho=1 is pair-matched.

    Uniform draws; rho is a mixing weight, not a Gaussian correlation.
    """
    rho = float(np.clip(rho, 0.0, 1.0))
    shared: dict[str, float] = {}
    out = nominal_values(catalog)
    u_neu: dict[str, float] = {}
    for it in catalog:
        name = str(it["name"])
        sign = path_sign(it)
        if sign in {"p", "n"}:
            key = pair_key(it) or name
            if key not in shared:
                shared[key] = _u(rng, tol)
            out[name] = _scale(it["R"], rho * shared[key], (1.0 - rho) * _u(rng, tol))
        elif include_rf and kind_of(it) == "feedback":
            tag = neuron_tag(it) or name
            if tag not in u_neu:
                u_neu[tag] = _u(rng, tol)
            out[name] = _scale(it["R"], u_neu[tag])
    return out


def sample_centroid_stat(catalog, tol: float, rng) -> dict[str, float]:
    """Experiment 27 centroid_stat: chip + pair + local. Not a layout."""
    u_chip = _u(rng, tol)
    pairs: dict[str, float] = {}
    out = {}
    for it in catalog:
        name = str(it["name"])
        key = re.sub(r"[pn]", "x", name, count=1)
        if key not in pairs:
            pairs[key] = _u(rng, tol)
        out[name] = _scale(it["R"], u_chip, 0.35 * pairs[key], 0.25 * _u(rng, tol))
    return out


def quantize_values(catalog, g_unit: float, roles=None) -> tuple[dict[str, float], dict]:
    """Round selected conductances to integer multiples of g_unit.

    Frozen weights are not edited. This is an implementation of the same
    compiled map with a shared unit element. k=0 keeps the original R
    and marks it unmatched residual.
    """
    roles = roles or {"feedback", "weight", "bias"}
    vals = nominal_values(catalog)
    n_q = n_keep = 0
    n_units = 0
    max_rel = 0.0
    abs_dg = []
    for it in catalog:
        if kind_of(it) not in roles:
            continue
        g = 1.0 / float(it["R"])
        k = int(round(g / g_unit))
        if k < 1:
            n_keep += 1
            continue
        gq = k * g_unit
        vals[str(it["name"])] = 1.0 / gq
        n_q += 1
        n_units += k
        rel = abs(gq - g) / g
        max_rel = max(max_rel, rel)
        abs_dg.append(rel)
    return vals, {
        "g_unit_S": float(g_unit),
        "n_quantized": n_q,
        "n_unmatched_residual": n_keep,
        "n_unit_elements": n_units,
        "mean_rel_g": float(np.mean(abs_dg)) if abs_dg else 0.0,
        "max_rel_g": float(max_rel),
        "roles": sorted(roles),
    }


def sample_unit_array(
    catalog,
    rng,
    g_unit: float,
    tol_sheet: float,
    tol_unit: float,
    per_neuron: bool = True,
    quantize: bool = True,
):
    """Shared unit-resistor array.

    Each TIA-fabric resistor is treated as N = round(G/G_unit) parallel
    (or series-equivalent) units. Sheet variation is common. Local unit
    mismatch averages as 1/√N. If per_neuron, each neuron array also
    has its own group scale (same physical family, different array).

    Logical netlist is *not* exploded; 1/√N is the statistical tile model
    used in Experiment 27. Isolated o2 can also emit explicit tiles.
    """
    qvals, qstat = quantize_values(catalog, g_unit) if quantize else (
        nominal_values(catalog),
        {"g_unit_S": g_unit, "n_quantized": 0, "n_unit_elements": 0},
    )
    us = _u(rng, tol_sheet)
    u_neu: dict[str, float] = {}
    out = dict(qvals)
    n_used = 0
    for it in catalog:
        k = kind_of(it)
        name = str(it["name"])
        r0 = float(qvals[name])
        if k not in {"feedback", "weight", "bias"}:
            if k == "invert":
                # pair-match invert
                continue
            if k == "divider":
                continue
            out[name] = _scale(r0, us, _u(rng, tol_unit))
            continue
        g = 1.0 / r0
        n = max(1, int(round(g / g_unit))) if g_unit > 0 else 1
        n_used += n
        tag = neuron_tag(it) or "_tia"
        if per_neuron and tag not in u_neu:
            u_neu[tag] = _u(rng, tol_sheet)
        un = u_neu.get(tag, 0.0) if per_neuron else 0.0
        loc = _u(rng, tol_unit) / math.sqrt(n)
        out[name] = _scale(r0, us, un, loc)
    # invert / divider pairs share one draw
    u_inv: dict[str, float] = {}
    u_div: dict[str, float] = {}
    for it in catalog:
        k = kind_of(it)
        name = str(it["name"])
        r0 = float(qvals[name])
        if k == "invert":
            stem = invert_stem(it) or name
            if stem not in u_inv:
                u_inv[stem] = _u(rng, tol_sheet)
            out[name] = _scale(r0, us, u_inv[stem], _u(rng, tol_unit) * 0.15)
        elif k == "divider":
            stem = divider_stem(it) or name
            if stem not in u_div:
                u_div[stem] = _u(rng, tol_sheet)
            out[name] = _scale(r0, us, u_div[stem], _u(rng, tol_unit) * 0.15)
    qstat = dict(qstat)
    qstat["n_unit_elements_applied"] = n_used
    return out, qstat


def _neuron_centers(spec: dict) -> dict[str, tuple[float, float]]:
    def grid(n, cols, x0, x1, y0, y1):
        rows = max(1, math.ceil(n / cols))
        pts = []
        for i in range(n):
            r, c = divmod(i, cols)
            x = x0 + (c + 0.5) / cols * (x1 - x0)
            y = y0 + (r + 0.5) / rows * (y1 - y0)
            pts.append((x, y))
        return pts

    n_h, n_o = int(spec["n_hidden"]), int(spec["n_out"])
    h = grid(n_h, 8, 0.05, 0.95, 0.05, 0.52)
    o = grid(n_o, 4, 0.10, 0.90, 0.62, 0.95)
    out = {f"h{i + 1}": h[i] for i in range(n_h)}
    out.update({f"o{i + 1}": o[i] for i in range(n_o)})
    return out


def assign_positions(catalog, spec: dict, placement: str = "paired") -> dict[str, tuple[float, float]]:
    """Documented floorplan abstraction. Not extracted layout.

    placements
    ----------
    naive:
        all +path shifted +y, all −path shifted −y (polarity gradient).
    paired:
        +/− of the same index sit on opposite sides of the neuron
        center; Rf at the center.
    centroid:
        each neuron TIA group (Rf+weights+bias) has centroid = neuron
        center (common-centroid / interdigitated stand-in).
    """
    centers = _neuron_centers(spec)
    pos: dict[str, tuple[float, float]] = {}
    grouped: dict[str, list[dict]] = defaultdict(list)
    extras: list[dict] = []
    for it in catalog:
        tag = neuron_tag(it)
        if tag and kind_of(it) in {"feedback", "weight", "bias"}:
            grouped[tag].append(it)
        else:
            extras.append(it)

    for tag, items in grouped.items():
        cx, cy = centers.get(tag, (0.5, 0.5))
        if placement == "centroid":
            # Place items on a ring so the mean is (cx, cy).
            n = max(len(items), 1)
            for i, it in enumerate(items):
                ang = 2.0 * math.pi * i / n
                pos[str(it["name"])] = (
                    cx + NEURON_SPAN * 0.35 * math.cos(ang),
                    cy + NEURON_SPAN * 0.35 * math.sin(ang),
                )
            continue
        for it in items:
            k = kind_of(it)
            sign = path_sign(it)
            src = 0
            m = re.search(r"[pn](\d+)", str(it["name"]))
            if m:
                src = int(m.group(1))
            dx = NEURON_SPAN * ((src % 8) - 3.5) / 8.0
            if placement == "naive":
                dy = 0.04 if sign == "p" else (-0.04 if sign == "n" else 0.0)
                if k == "feedback":
                    dy = 0.0
            else:
                dy = 0.012 if sign == "p" else (-0.012 if sign == "n" else 0.0)
            pos[str(it["name"])] = (cx + dx, cy + dy)

    for it in extras:
        name = str(it["name"])
        k = kind_of(it)
        stem = invert_stem(it) or divider_stem(it) or ""
        hm = re.search(r"h(\d+)", stem)
        im = re.search(r"(\d+)", stem)
        if hm and f"h{hm.group(1)}" in centers:
            cx, cy = centers[f"h{hm.group(1)}"]
            pos[name] = (cx - 0.02, cy + (0.01 if name.endswith("a") else -0.01))
        elif stem.startswith("inv") and im:
            col = int(im.group(1))
            pos[name] = (0.05 + 0.05 * (col % 16), 0.02 if k == "invert" else 0.00)
        else:
            pos[name] = (0.5, 0.55)
    return pos


def sample_gradient(
    catalog,
    spec,
    rng,
    gx: float,
    gy: float = 0.0,
    tol_local: float = 0.0,
    placement: str = "paired",
    matched_groups: bool = True,
    local_frac_on_groups: float = 0.15,
    group_tol: float = 0.005,
):
    """R_i = R_nom · (1 + gx x' + gy y' + local [+ matched-group scale]).

    x', y' ∈ [-1, 1] from the documented floorplan. gx is a *normalized*
    coefficient, not a foundry ppm/µm number.

    If matched_groups, each neuron TIA array and each invert/divider pair
    still share a group scale (ratio matching) *and* see the gradient at
    their individual positions. A linear gradient then leaves a residual
    equal to gx times the intra-group span — common-centroid placement
    is the case where that span averages toward zero.
    """
    pos = assign_positions(catalog, spec, placement)
    u_neu: dict[str, float] = {}
    u_inv: dict[str, float] = {}
    u_div: dict[str, float] = {}
    out = {}
    for it in catalog:
        name = str(it["name"])
        x, y = pos.get(name, (0.5, 0.5))
        xn, yn = 2.0 * x - 1.0, 2.0 * y - 1.0
        field = gx * xn + gy * yn
        extra = _u(rng, tol_local)
        if matched_groups:
            k = kind_of(it)
            loc = local_frac_on_groups * group_tol
            if k in {"feedback", "weight", "bias"}:
                tag = neuron_tag(it) or "_tia"
                if tag not in u_neu:
                    u_neu[tag] = _u(rng, group_tol)
                extra += u_neu[tag] + _u(rng, loc)
            elif k == "invert":
                stem = invert_stem(it) or name
                if stem not in u_inv:
                    u_inv[stem] = _u(rng, group_tol)
                extra += u_inv[stem] + _u(rng, loc)
            elif k == "divider":
                stem = divider_stem(it) or name
                if stem not in u_div:
                    u_div[stem] = _u(rng, group_tol)
                extra += u_div[stem] + _u(rng, loc)
        out[name] = _scale(it["R"], field, extra)
    return out


def neuron_ratio_errors(catalog, values: dict[str, float]) -> dict:
    """Per-neuron d(Rf · G_weights)/ (Rf · G) — the ratiometric residual."""
    g0: dict[str, float] = defaultdict(float)
    g1: dict[str, float] = defaultdict(float)
    rf0: dict[str, float] = {}
    rf1: dict[str, float] = {}
    for it in catalog:
        tag = neuron_tag(it)
        if not tag:
            continue
        k = kind_of(it)
        r0 = float(it["R"])
        r1 = float(values.get(str(it["name"]), r0))
        if k == "feedback":
            rf0[tag] = r0
            rf1[tag] = r1
        elif k in {"weight", "bias"}:
            g0[tag] += 1.0 / r0
            g1[tag] += 1.0 / r1
    rel = []
    for tag, rfn in rf0.items():
        if tag not in g0 or g0[tag] == 0:
            continue
        p0 = rfn * g0[tag]
        p1 = rf1[tag] * g1[tag]
        rel.append((p1 - p0) / p0)
    arr = np.asarray(rel, dtype=float) if rel else np.zeros(0)
    return {
        "n_neurons": int(arr.size),
        "rms_d_rfG": float(np.sqrt(np.mean(arr**2))) if arr.size else None,
        "mae_d_rfG": float(np.mean(np.abs(arr))) if arr.size else None,
        "max_abs_d_rfG": float(np.max(np.abs(arr))) if arr.size else None,
    }


def apply_values(netlist: str, values: dict[str, float]) -> str:
    from compile_xor import apply_resistor_values

    return apply_resistor_values(netlist, values)


def model_catalog() -> list[dict]:
    return [
        {
            "name": "independent",
            "physical": "Unmatched discrete resistors. Independent relative error.",
        },
        {
            "name": "common_mode",
            "physical": "Global sheet resistance. One scale on every R.",
        },
        {
            "name": "global_plus_local",
            "physical": "Global sheet plus independent local (Pelgrom-like split).",
        },
        {
            "name": "ratio_matched_exp27",
            "physical": (
                "Experiment 27 model: one TIA-family scale for all "
                "Rf+weights+bias, pair scales for invert/divider, 15% residual."
            ),
        },
        {
            "name": "ratio_matched_neuron",
            "physical": (
                "Per-neuron shared unit array on {Rf, weights, bias}; "
                "matched invert and divider pairs; 15% residual."
            ),
        },
        {
            "name": "rf_g_track",
            "physical": "Per-neuron Rf tracks G_tot; intra-neuron weights still share that scale plus residual.",
        },
        {
            "name": "pn_pair",
            "physical": "Interdigitated +/− pairs only. Rf not in the pair.",
        },
        {
            "name": "pn_pair_plus_rf",
            "physical": "Interdigitated +/− pairs and a per-neuron Rf draw (Rf not forced to G).",
        },
        {
            "name": "pn_systematic",
            "physical": "Chip-wide polarity field: +path +tol, −path −tol.",
        },
        {
            "name": "centroid_stat",
            "physical": "Experiment 27 statistical common-centroid: chip + pair + local.",
        },
        {
            "name": "unit_array_neuron",
            "physical": (
                "Integer unit conductances from a shared G_unit; sheet + "
                "per-neuron array + 1/√N local. Quantizes the compiled map."
            ),
        },
        {
            "name": "gradient_paired",
            "physical": "Linear spatial field on paired placement, with neuron ratio groups.",
        },
        {
            "name": "gradient_naive",
            "physical": "Linear spatial field on polarity-split placement.",
        },
        {
            "name": "gradient_centroid",
            "physical": "Linear spatial field on ring common-centroid placement.",
        },
    ]


SENSITIVITY_PREDS = {
    "rf_only": lambda it: kind_of(it) == "feedback",
    "weights_only": lambda it: kind_of(it) == "weight",
    "bias_only": lambda it: kind_of(it) == "bias",
    "invert_only": lambda it: kind_of(it) == "invert",
    "divider_only": lambda it: kind_of(it) == "divider",
    "layer1_only": lambda it: int(it.get("layer") or 0) == 1,
    "layer2_only": lambda it: int(it.get("layer") or 0) == 2,
    "fine_bank_only": lambda it: str(it.get("bank")) == "f",
    "nom_bank_only": lambda it: str(it.get("bank")) == "n",
    "pos_only": lambda it: path_sign(it) == "p",
    "neg_only": lambda it: path_sign(it) == "n",
    "tia_fabric": lambda it: kind_of(it) in {"feedback", "weight", "bias"},
}


def sample_named(catalog, name: str, rng, spec=None, **kw):
    """Dispatch a documented model. Unknown names raise."""
    tol = float(kw.get("tol", TOL_05))
    loc = float(kw.get("local_frac", 0.15))
    if name == "independent":
        return sample_independent(catalog, tol, rng)
    if name == "common_mode":
        return sample_common_mode(catalog, tol, rng)
    if name == "global_plus_local":
        return sample_global_plus_local(
            catalog, float(kw.get("tol_g", tol)), float(kw.get("tol_l", tol)), rng
        )
    if name == "ratio_matched_exp27":
        return sample_ratio_matched_exp27(catalog, tol, rng, loc)
    if name == "ratio_matched_neuron":
        return sample_ratio_matched_neuron(catalog, tol, rng, loc)
    if name == "rf_g_track":
        return sample_rf_g_track(catalog, tol, rng, loc)
    if name == "rf_independent":
        return sample_rf_only_track(catalog, tol, rng, loc)
    if name == "pn_pair":
        return sample_pn_pair(catalog, tol, rng, False, loc)
    if name == "pn_pair_plus_rf":
        return sample_pn_pair(catalog, tol, rng, True, loc)
    if name == "pn_systematic":
        return sample_pn_systematic(catalog, tol)
    if name == "centroid_stat":
        return sample_centroid_stat(catalog, tol, rng)
    if name == "pn_corr":
        return sample_pn_correlated(
            catalog, tol, rng, float(kw.get("rho", 1.0)), bool(kw.get("include_rf", True))
        )
    if name.startswith("sens_"):
        pred = SENSITIVITY_PREDS[name[5:]]
        return sample_subset(catalog, tol, rng, pred)
    if name == "unit_array_neuron":
        vals, _st = sample_unit_array(
            catalog,
            rng,
            g_unit=float(kw.get("g_unit", G_WEIGHT / 16.0)),
            tol_sheet=float(kw.get("tol_sheet", tol)),
            tol_unit=float(kw.get("tol_unit", tol)),
            per_neuron=True,
            quantize=bool(kw.get("quantize", True)),
        )
        return vals
    if name.startswith("gradient_"):
        if spec is None:
            raise ValueError("gradient models need spec")
        placement = name.split("_", 1)[1]
        return sample_gradient(
            catalog,
            spec,
            rng,
            gx=float(kw.get("gx", 0.0)),
            gy=float(kw.get("gy", 0.0)),
            tol_local=float(kw.get("tol_local", 0.0)),
            placement=placement,
            matched_groups=bool(kw.get("matched_groups", True)),
            local_frac_on_groups=loc,
            group_tol=tol,
        )
    raise ValueError(f"unknown matching model {name}")


def tile_tia_fabric(netlist: str, catalog: list[dict], n: int):
    """Explicit series/parallel tiles on TIA fabric only (isolated benches)."""
    roles = frozenset({"weight", "bias", "feedback"})
    return tile_netlist(netlist, catalog, n, roles=roles)
