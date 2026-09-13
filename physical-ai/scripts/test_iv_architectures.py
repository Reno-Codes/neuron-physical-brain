"""Experiment 17: physical current-to-voltage neuron.

Frozen Experiment 9 networks A and F. Architecture I is the Experiment 16
baseline. A/B/C replace the leftover current dump. Weights are never
edited. SPICE outputs are never corrected in Python.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from benchmark_scaling import (
    N_ROBUST_INPUTS,
    N_TEST,
    classification_labels,
    error_stats,
    generate_inputs,
    make_rng,
    simulate_batch,
)
from compile_xor import PROJECT_ROOT, find_ngspice, run_ngspice
from hardware_constrained_compiler import current_cost_estimate, load_frozen_model
from physical_iv_neuron import (
    ARCH_KEYS,
    ARCH_PUBLIC,
    CIRCUIT_DIR,
    DEFAULT_GAIN,
    IVParams,
    accounting,
    compile_iv,
    neuron_tags,
    sample_feedback_absolute,
    sample_feedback_ratiometric,
    sample_global_fixed,
    sample_independent,
)
from precision_architectures import hidden_preact_max, software_reference
from test_hardware_constraints import measure_source_current, spec_by_id
from test_nonideal_network import class_margins


RESULTS_DIR = PROJECT_ROOT / "results"
REPORT_PATH = RESULTS_DIR / "physical_iv_report.json"
ERROR_LIMIT = 1.0e-3
TIMEOUT = 40.0
INPUT_NOISE = 0.001
N_F_SWEEP = 40
N_MC_TRIALS = 100
GAIN_SWEEP = (1e2, 1e3, 1e4, 1e5, 1e6)
FB_PCTS = (0.0, 0.1, 0.5, 1.0, 5.0)
GLOBAL_DELTAS = (-0.10, -0.05, -0.01, 0.01, 0.05, 0.10)
LOCAL_PCTS = (0.0, 0.1, 0.5, 1.0, 2.0, 5.0)
RAILS = (15.0, 5.0, 3.3)
COPY_PCTS = (0.0, 0.1, 1.0)
TEST_IDS = ("A", "F")
TIA_ARCHES = ("A", "B", "C")


def dest(*parts: str) -> Path:
    name = "_".join(str(p).replace("%", "pct").replace(".", "p").replace("+", "p") for p in parts)
    return CIRCUIT_DIR / f"{name}.cir"


def fmt(value, spec=".4e") -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return format(value, spec)
    return str(value)


def software_for(spec, weights, inputs, rail: float, linear: bool = False):
    zmax, hmax = hidden_preact_max(inputs, weights["W1"], weights["b1"])
    clipped = (not linear) and hmax > rail + 1e-12
    y = software_reference(
        inputs, weights["W1"], weights["b1"], weights["W2"], weights["b2"],
        linear=linear, hidden_rail=rail if clipped else None,
    )
    return y, {"hidden_preact_max": zmax, "hidden_relu_max": hmax, "clipped": clipped}


def evaluate_netlist(
    ngspice: Path,
    spec: dict,
    netlist: str,
    inputs: np.ndarray,
    software: np.ndarray,
    path: Path,
    r_values: dict[str, float] | None = None,
) -> dict:
    physical, runtime, spice_err, log = simulate_batch(
        ngspice, netlist, inputs, spec["n_out"], path,
        r_values=r_values, timeout=TIMEOUT,
    )
    rec = {"failed": False, "failure_reason": None, "spice_runtime_s": runtime}
    if spice_err or physical is None:
        rec["failed"] = True
        rec["failure_reason"] = spice_err or "no physical outputs"
        rec["spice_log_tail"] = (log or "")[-400:]
        rec["convergence_failure"] = "convergence" in (spice_err or "").lower()
        return rec
    err = error_stats(physical, software)
    pred = classification_labels(physical)
    expected = classification_labels(software)
    n_fail = int(np.sum(pred != expected))
    margins = class_margins(physical, software)
    rec.update(
        {
            "mae": err["mae"],
            "rms": err["rms"],
            "max_abs_error": err["max_abs_error"],
            "accuracy": float(1.0 - n_fail / max(len(expected), 1)),
            "n_class_failures": n_fail,
            "min_margin": float(np.min(margins)),
            "classification_ok": n_fail == 0,
            "exceeds_error_limit": err["mae"] > ERROR_LIMIT,
            "convergence_failure": False,
        }
    )
    return rec


def measure_sum_nodes(
    ngspice: Path,
    spec: dict,
    netlist: str,
    x: np.ndarray,
    path: Path,
    arch: str,
) -> dict:
    """One operating point. Report |V_sum| on every neuron summing node."""
    tags = neuron_tags(spec)
    nodes = []
    for tag in tags:
        if arch == "C" and tag.startswith("h"):
            nodes.append(f"{tag}ir")
        else:
            nodes.append(f"{tag}p")
    head, sep, _tail = netlist.partition(".control")
    if not sep:
        return {"failed": True, "reason": "no .control"}
    lines = [".control", "set numdgt=15"]
    for i, xi in enumerate(np.atleast_1d(x), start=1):
        lines.append(f"alter Vin{i} DC {float(xi):.15g}")
    lines.append("op")
    for node in nodes:
        lines.append(f"print v({node})")
    lines.extend([".endc", "", ".end", ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(head.rstrip() + "\n" + "\n".join(lines), encoding="utf-8")
    result = run_ngspice(ngspice, path, timeout=TIMEOUT)
    text = f"{result.stdout or ''}\n{result.stderr or ''}"
    if result.returncode != 0:
        return {"failed": True, "reason": f"ngspice exit {result.returncode}"}
    from test_robustness import extract_all

    absvals = []
    by_node = {}
    for node in nodes:
        vals = extract_all(text, f"v({node})")
        if not vals:
            by_node[node] = None
            continue
        by_node[node] = float(vals[0])
        absvals.append(abs(float(vals[0])))
    if not absvals:
        return {"failed": True, "reason": "no summing-node voltages"}
    return {
        "failed": False,
        "n_nodes": len(nodes),
        "max_abs_V": float(np.max(absvals)),
        "mean_abs_V": float(np.mean(absvals)),
        "nodes": {k: by_node[k] for k in list(by_node)[:8]},
    }


def run_mc(
    ngspice, spec, netlist, catalog, inputs, software, path, n_trials, seed_tag, sampler
) -> dict:
    rng = make_rng("exp17", spec["id"], seed_tag)
    maes, accs, mx, margins = [], [], [], []
    failures = 0
    expected = classification_labels(software)
    for trial in range(n_trials):
        values, extra_x = sampler(catalog, rng, trial, inputs)
        physical, _rt, spice_err, _log = simulate_batch(
            ngspice, netlist, extra_x, spec["n_out"], path,
            r_values=values, timeout=TIMEOUT,
        )
        if spice_err or physical is None:
            failures += 1
            continue
        stats = error_stats(physical, software)
        pred = classification_labels(physical)
        maes.append(stats["mae"])
        mx.append(stats["max_abs_error"])
        accs.append(float(np.mean(pred == expected)))
        margins.append(float(np.min(class_margins(physical, software))))
        if trial == 0 or (trial + 1) % 25 == 0:
            print(
                f"      {seed_tag} {trial + 1}/{n_trials} MAE={stats['mae']:.4e}",
                flush=True,
            )
    if not maes:
        return {"failed": True, "n_spice_failures": failures, "n_trials": n_trials}
    return {
        "failed": False,
        "n_trials": n_trials,
        "n_ok": len(maes),
        "n_spice_failures": failures,
        "mae_mean": float(np.mean(maes)),
        "mae_std": float(np.std(maes)),
        "mae_max": float(np.max(maes)),
        "max_abs_error_mean": float(np.mean(mx)),
        "accuracy_mean": float(np.mean(accs)),
        "accuracy_min": float(np.min(accs)),
        "min_margin_min": float(np.min(margins)),
        "exceeds_error_limit": float(np.mean(maes)) > ERROR_LIMIT,
    }


def first_over(rows: list[dict], key="mae") -> dict | None:
    for rec in rows:
        mae = rec.get(key, rec.get("mae_mean"))
        if rec.get("failed") or mae is None:
            continue
        if mae > ERROR_LIMIT:
            return {
                "name": rec.get("name"),
                "value": rec.get("value"),
                "mae": mae,
                "accuracy": rec.get("accuracy", rec.get("accuracy_mean")),
            }
    return None


def first_class_fail(rows: list[dict]) -> dict | None:
    for rec in rows:
        acc = rec.get("accuracy", rec.get("accuracy_mean"))
        if rec.get("failed") or acc is None:
            continue
        if acc < 1.0:
            return {
                "name": rec.get("name"),
                "value": rec.get("value"),
                "accuracy": acc,
                "mae": rec.get("mae", rec.get("mae_mean")),
            }
    return None


def first_over_1e2(rows: list[dict]) -> dict | None:
    for rec in rows:
        mae = rec.get("mae", rec.get("mae_mean"))
        if rec.get("failed") or mae is None:
            continue
        if mae > 1e-2:
            return {"name": rec.get("name"), "value": rec.get("value"), "mae": mae}
    return None


def evaluate_arch(
    ngspice, spec, weights, arch, x_all, x_sw, x_mc, rail_nom=15.0
) -> dict:
    print(f"  architecture {arch}: {ARCH_PUBLIC[arch]['title']}", flush=True)
    n_w = spec["n_in"] * spec["n_hidden"] + spec["n_hidden"] * spec["n_out"]
    y_all, meta_all = software_for(spec, weights, x_all, rail_nom)
    y_sw, _ = software_for(spec, weights, x_sw, rail_nom)
    y_mc, _ = software_for(spec, weights, x_mc, rail_nom)
    params = IVParams(name=f"{arch}_nom", rail=rail_nom)
    net, cat, reason = compile_iv(arch, spec, weights, params)
    nom = {"failed": True, "failure_reason": reason, **meta_all}
    if net is not None:
        dest(spec["id"], arch, "nominal").write_text(net, encoding="utf-8")
        nom = evaluate_netlist(
            ngspice, spec, net, x_all, y_all, dest(spec["id"], arch, "nominal")
        )
        nom.update(accounting(net, cat, n_w))
        nom.update(meta_all)
        source_i = measure_source_current(
            ngspice, net, x_all[0], dest(spec["id"], arch, "nominal_i")
        )
        nom["current_cost"] = current_cost_estimate(cat, source_i)
        nom["spice_source_current_A"] = source_i
        vsum = measure_sum_nodes(
            ngspice, spec, net, x_all[0], dest(spec["id"], arch, "vsum"), arch
        )
        nom["summing_node"] = vsum
    print(
        f"    nominal MAE={nom.get('mae')} nR={nom.get('passive_resistors')} "
        f"dumps={nom.get('n_current_dumps')} tia={nom.get('n_tia_opamps')} "
        f"Vsum={((nom.get('summing_node') or {}).get('max_abs_V'))} "
        f"fail={nom.get('failure_reason')}",
        flush=True,
    )
    return {
        "arch": arch,
        "title": ARCH_PUBLIC[arch]["title"],
        "iv_topology": ARCH_PUBLIC[arch]["iv_topology"],
        "nominal": nom,
        "net_nominal": net,
        "catalog": cat,
        "y_sw": y_sw,
        "y_mc": y_mc,
        "x_sw": x_sw,
        "x_mc": x_mc,
    }


def sweep_gain(ngspice, spec, weights, arch, x_sw, y_sw) -> list[dict]:
    rows = []
    for a in GAIN_SWEEP:
        params = IVParams(name=f"{arch}_A{a:g}", amp_gain=a)
        net, cat, reason = compile_iv(arch, spec, weights, params)
        rec = {"name": params.name, "value": a, "failed": False, "failure_reason": reason}
        if reason or net is None:
            rec["failed"] = True
            rows.append(rec)
            print(f"    A={a:g} compile fail {reason}", flush=True)
            continue
        dest(spec["id"], arch, f"gain_{a:g}").write_text(net, encoding="utf-8")
        rec.update(
            evaluate_netlist(
                ngspice, spec, net, x_sw, y_sw, dest(spec["id"], arch, f"gain_{a:g}")
            )
        )
        vsum = measure_sum_nodes(
            ngspice, spec, net, x_sw[0], dest(spec["id"], arch, f"gain_{a:g}_v"), arch
        )
        rec["summing_node"] = vsum
        print(
            f"    A={a:g} MAE={rec.get('mae')} acc={rec.get('accuracy')} "
            f"Vsum={vsum.get('max_abs_V')}",
            flush=True,
        )
        rows.append(rec)
    return rows


def sweep_copy_like(ngspice, spec, weights, arch, x_sw, y_sw) -> list[dict]:
    """0.1% leftover-copy analogue: dump gain on I, open-loop A on TIA."""
    rows = []
    for pct in COPY_PCTS:
        e = pct / 100.0
        if arch == "I":
            params = IVParams(name=f"{arch}_dump_{pct:g}", dump_gain_error=e)
        else:
            params = IVParams(name=f"{arch}_Aerr_{pct:g}", amp_gain_error=e)
        net, cat, reason = compile_iv(arch, spec, weights, params)
        rec = {"name": params.name, "value": pct, "failed": False, "failure_reason": reason}
        if reason or net is None:
            rec["failed"] = True
            rows.append(rec)
            continue
        rec.update(
            evaluate_netlist(
                ngspice, spec, net, x_sw, y_sw, dest(spec["id"], arch, params.name)
            )
        )
        print(f"    copy-like {pct:g}% MAE={rec.get('mae')}", flush=True)
        rows.append(rec)
    return rows


def sweep_tolerance(ngspice, spec, block, kind: str, x_sw, y_sw) -> list[dict]:
    arch = block["arch"]
    net, cat = block["net_nominal"], block["catalog"]
    rows = []
    sampler = sample_feedback_absolute if kind == "absolute" else sample_feedback_ratiometric
    for pct in FB_PCTS:
        rng = make_rng("fb", spec["id"], arch, kind, pct)
        if pct == 0.0:
            values = {str(i["name"]): float(i["R"]) for i in cat}
        else:
            values = sampler(cat, pct, rng)
        rec = evaluate_netlist(
            ngspice, spec, net, x_sw, y_sw,
            dest(spec["id"], arch, f"fb_{kind}_{pct:g}"),
            r_values=values,
        )
        rec["name"] = f"{arch}_{kind}_{pct:g}"
        rec["value"] = pct
        rec["kind"] = kind
        print(f"    {kind} {pct:g}% MAE={rec.get('mae')}", flush=True)
        rows.append(rec)
    return rows


def sweep_global(ngspice, spec, block, x_sw, y_sw) -> list[dict]:
    arch = block["arch"]
    net, cat = block["net_nominal"], block["catalog"]
    rows = []
    for delta in GLOBAL_DELTAS:
        values = sample_global_fixed(cat, delta)
        rec = evaluate_netlist(
            ngspice, spec, net, x_sw, y_sw,
            dest(spec["id"], arch, f"global_{delta:+.4g}"),
            r_values=values,
        )
        rec["name"] = f"{arch}_global_{delta:+.4g}"
        rec["value"] = delta * 100.0
        rec["delta"] = delta
        print(f"    global {delta:+.0%} MAE={rec.get('mae')}", flush=True)
        rows.append(rec)
    return rows


def sweep_local(ngspice, spec, block, x_sw, y_sw) -> list[dict]:
    arch = block["arch"]
    net, cat = block["net_nominal"], block["catalog"]
    rows = []
    for pct in LOCAL_PCTS:
        rng = make_rng("loc", spec["id"], arch, pct)
        values = sample_independent(cat, pct, rng) if pct else None
        rec = evaluate_netlist(
            ngspice, spec, net, x_sw, y_sw,
            dest(spec["id"], arch, f"local_{pct:g}"),
            r_values=values,
        )
        rec["name"] = f"{arch}_local_{pct:g}"
        rec["value"] = pct
        print(f"    local {pct:g}% MAE={rec.get('mae')} acc={rec.get('accuracy')}", flush=True)
        rows.append(rec)
    return rows


def sweep_rail(ngspice, spec, weights, arch, x_sw) -> list[dict]:
    rows = []
    for rail in RAILS:
        y, meta = software_for(spec, weights, x_sw, rail)
        params = IVParams(name=f"{arch}_rail_{rail:g}", rail=rail, clip_amp=True)
        net, cat, reason = compile_iv(arch, spec, weights, params)
        rec = {
            "name": params.name, "value": rail, "failed": False,
            "failure_reason": reason, **meta,
        }
        if reason or net is None:
            rec["failed"] = True
            rows.append(rec)
            print(f"    rail +/-{rail:g} compile fail {reason}", flush=True)
            continue
        rec.update(
            evaluate_netlist(
                ngspice, spec, net, x_sw, y, dest(spec["id"], arch, f"rail_{rail:g}")
            )
        )
        rec.update(meta)
        print(
            f"    rail +/-{rail:g} MAE={rec.get('mae')} acc={rec.get('accuracy')} "
            f"clip={meta['clipped']} fail={rec.get('failure_reason')}",
            flush=True,
        )
        rows.append(rec)
    return rows


def combined_mc(ngspice, spec, weights, arch, x_mc, y_mc) -> dict:
    params = IVParams(
        name="combined",
        amp_gain=1e5,
        vos=0.001,
        rout=100.0,
        i_leak=1e-8,
        amp_gain_error=0.001 if arch != "I" else 0.0,
        dump_gain_error=0.001 if arch == "I" else 0.0,
        clip_amp=False,
    )
    net, cat, reason = compile_iv(arch, spec, weights, params)
    if reason or net is None:
        return {"failed": True, "failure_reason": reason}

    def sampler(catalog, rng, _trial, inputs):
        values = sample_independent(catalog, 0.5, rng)
        noisy = inputs + rng.normal(0.0, INPUT_NOISE, size=inputs.shape)
        return values, noisy

    rec = run_mc(
        ngspice, spec, net, cat, x_mc, y_mc,
        dest(spec["id"], arch, "combined"),
        N_MC_TRIALS, f"{spec['id']}{arch}comb", sampler,
    )
    rec["conditions"] = {
        "independent_resistor_pct": 0.5,
        "amp_gain": 1e5,
        "amp_gain_error": params.amp_gain_error,
        "dump_gain_error": params.dump_gain_error,
        "vos_V": 0.001,
        "rout_ohm": 100.0,
        "i_leak_A": 1e-8,
        "input_noise_V": INPUT_NOISE,
    }
    return rec


def min_gain_for(rows: list[dict], pred) -> dict | None:
    ok = [r for r in rows if not r.get("failed") and pred(r)]
    if not ok:
        return None
    best = min(ok, key=lambda r: r["value"])
    return {"A": best["value"], "mae": best.get("mae"), "accuracy": best.get("accuracy")}


def analyze(rows: list[dict]) -> dict:
    f = next(r for r in rows if r["id"] == "F")
    table = {}
    for net in rows:
        table[net["id"]] = {}
        for arch, block in net["architectures"].items():
            nom = block["nominal"]
            copy = block.get("copy_like") or []
            fb_abs = block.get("fb_absolute") or []
            glob = block.get("global") or []
            loc = block.get("local") or []
            rail = block.get("rails") or []
            gain = block.get("gain") or []
            g10 = next((r.get("mae") for r in glob if r.get("delta") == 0.10), None)
            g10n = next((r.get("mae") for r in glob if r.get("delta") == -0.10), None)
            c01 = next((r.get("mae") for r in copy if r.get("value") == 0.1), None)
            c1 = next((r.get("mae") for r in copy if r.get("value") == 1.0), None)
            a01 = next((r.get("mae") for r in fb_abs if r.get("value") == 0.1), None)
            a1 = next((r.get("mae") for r in fb_abs if r.get("value") == 1.0), None)
            a5 = next((r.get("mae") for r in fb_abs if r.get("value") == 5.0), None)
            working_rail = None
            for rec in sorted(rail, key=lambda r: r.get("value") or 99, reverse=False):
                if rec.get("failed") or rec.get("convergence_failure"):
                    continue
                if rec.get("classification_ok"):
                    working_rail = rec.get("value")
                    break
            table[net["id"]][arch] = {
                "nominal_mae": nom.get("mae"),
                "max_abs_error": nom.get("max_abs_error"),
                "accuracy": nom.get("accuracy"),
                "n_resistors": nom.get("passive_resistors"),
                "n_current_dumps": nom.get("n_current_dumps"),
                "n_tia_opamps": nom.get("n_tia_opamps"),
                "n_iv_stages": nom.get("n_iv_stages"),
                "leftover_current_copies": nom.get("leftover_current_copies"),
                "closed_loop_opamps": nom.get("closed_loop_opamps"),
                "active_functional_blocks": nom.get("active_functional_blocks"),
                "vsum_max": (nom.get("summing_node") or {}).get("max_abs_V"),
                "copy_0.1": c01,
                "copy_1.0": c1,
                "fb_abs_0.1": a01,
                "fb_abs_1.0": a1,
                "fb_abs_5.0": a5,
                "global_p10": g10,
                "global_m10": g10n,
                "local_first_1e3": first_over(loc),
                "local_first_1e2": first_over_1e2(loc),
                "local_first_class": first_class_fail(loc),
                "min_A_mae": min_gain_for(gain, lambda r: (r.get("mae") or 9) <= ERROR_LIMIT),
                "min_A_class": min_gain_for(gain, lambda r: r.get("accuracy") == 1.0),
                "lowest_working_supply": working_rail,
                "combined_mae": (block.get("combined") or {}).get("mae_mean"),
                "combined_acc": (block.get("combined") or {}).get("accuracy_mean"),
                "combined_acc_min": (block.get("combined") or {}).get("accuracy_min"),
                "spice_runtime_s": nom.get("spice_runtime_s"),
            }

    def floor(arch: str) -> float:
        rec = table["F"][arch]
        vals = [v for v in (rec.get("copy_0.1"), rec.get("combined_mae")) if v is not None]
        return max(vals) if vals else 9.0

    def copy_score(arch: str) -> tuple:
        rec = table["F"][arch]
        leftover = rec.get("leftover_current_copies")
        leftover = 999 if leftover is None else leftover
        return (leftover, floor(arch))

    # Prefer zero leftover current copies (the Experiment 16 bottleneck).
    winner = min(ARCH_KEYS, key=copy_score)
    i_floor = floor("I")
    w_floor = floor(winner)
    leftover = table["F"][winner].get("leftover_current_copies")
    copy01 = table["F"][winner].get("copy_0.1")
    comb = table["F"][winner].get("combined_mae")
    improved = (
        winner != "I"
        and leftover == 0
        and copy01 is not None
        and copy01 < ERROR_LIMIT
        and comb is not None
        and (comb <= ERROR_LIMIT or comb < i_floor * 0.7)
    )
    analog_pass = (table["F"][winner].get("combined_mae") or 9) <= ERROR_LIMIT
    remaining = (
        "Architecture I current dump (B-source I = i(Vsum))"
        if winner == "I"
        else (
            "TIA open-loop VCVS/B-source (resistor Rf sets the gain; "
            "the amplifier is still a controlled source enforcing virtual ground)"
            if winner in {"A", "B"}
            else "current-mode ReLU B-source plus TIA amplifier"
        )
    )
    return {
        "by_network": table,
        "winner": winner,
        "F_I_floor": i_floor,
        "F_winner_floor": w_floor,
        "analog_pass_1e3": analog_pass,
        "copy_minimizing_style_improved": bool(improved),
        "remaining_ideal_block": remaining,
        "device_preview": {
            "status": "DEVICE-LEVEL TEST DEFERRED",
            "reason": (
                "ngspice example MOS / CMOS cards exist under "
                "C:\\\\ngspice\\\\examples but they are not a characterized "
                "drop-in summing-node TIA. Wiring them into Network A would "
                "invent bias and device sizing. No project device library."
            ),
        },
        "verdict": (
            "CURRENT-TO-VOLTAGE ARCHITECTURE IMPROVED"
            if improved
            else "CURRENT-TO-VOLTAGE LIMIT FOUND"
        ),
    }


def make_plots(rows: list[dict]) -> dict[str, str]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    colors = {"I": "#1f4e79", "A": "#b85c38", "B": "#2e7d4f", "C": "#6a3d9a"}
    styles = {"A": "-", "F": "--"}

    fig, ax = plt.subplots(figsize=(7.6, 4.4))
    for row in rows:
        for arch, block in row["architectures"].items():
            recs = [r for r in (block.get("gain") or []) if not r.get("failed") and r.get("mae") is not None]
            if not recs:
                continue
            ax.plot(
                [r["value"] for r in recs],
                [max(r["mae"], 1e-16) for r in recs],
                styles[row["id"]], color=colors[arch], marker="o",
                label=f"{row['id']}-{arch}", linewidth=1.8,
            )
    ax.axhline(ERROR_LIMIT, color="#a33", linestyle=":")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("TIA open-loop gain A")
    ax.set_ylabel("MAE")
    ax.set_title("Experiment 17 finite-gain TIA")
    ax.legend(fontsize=7, ncol=2)
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    p1 = RESULTS_DIR / "physical_iv_gain_sweep.png"
    fig.savefig(p1, dpi=140)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(9.2, 4.2))
    for ax, field, title in (
        (axes[0], "fb_absolute", "absolute feedback R"),
        (axes[1], "fb_ratiometric", "ratiometric Rf with R_w"),
    ):
        for row in rows:
            for arch, block in row["architectures"].items():
                recs = [r for r in (block.get(field) or []) if not r.get("failed") and r.get("mae") is not None]
                if not recs:
                    continue
                ax.plot(
                    [r["value"] for r in recs],
                    [max(r["mae"], 1e-16) for r in recs],
                    styles[row["id"]], color=colors[arch], marker="o",
                    label=f"{row['id']}-{arch}", linewidth=1.7,
                )
        ax.axhline(ERROR_LIMIT, color="#a33", linestyle=":")
        ax.set_yscale("log")
        ax.set_xlabel("tolerance (%)")
        ax.set_ylabel("MAE")
        ax.set_title(title)
        ax.grid(True, which="both", alpha=0.3)
    axes[1].legend(fontsize=7, ncol=2)
    fig.suptitle("Experiment 17 feedback tolerance")
    fig.tight_layout()
    p2 = RESULTS_DIR / "physical_iv_tolerance.png"
    fig.savefig(p2, dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.6, 4.3))
    for row in rows:
        for arch, block in row["architectures"].items():
            recs = [r for r in (block.get("rails") or []) if not r.get("failed") and r.get("mae") is not None]
            if not recs:
                continue
            ax.plot(
                [r["value"] for r in recs],
                [max(r["mae"], 1e-16) for r in recs],
                styles[row["id"]], color=colors[arch], marker="o",
                label=f"{row['id']}-{arch}", linewidth=1.8,
            )
    ax.axhline(ERROR_LIMIT, color="#a33", linestyle=":")
    ax.set_yscale("log")
    ax.set_xlabel("supply half-rail (V)")
    ax.set_ylabel("MAE")
    ax.set_title("Experiment 17 supply")
    ax.legend(fontsize=7, ncol=2)
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    p3 = RESULTS_DIR / "physical_iv_supply.png"
    fig.savefig(p3, dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8.6, 4.5))
    labels = ["nom", "copy 0.1%", "Rf 0.1%", "global +10%", "local 1%", "comb"]
    x = np.arange(len(labels))
    w = 0.10
    idx = 0
    for row in rows:
        for arch, block in row["architectures"].items():
            nom = block["nominal"].get("mae")
            c = next((r.get("mae") for r in (block.get("copy_like") or []) if r.get("value") == 0.1), None)
            fb = next((r.get("mae") for r in (block.get("fb_absolute") or []) if r.get("value") == 0.1), None)
            g = next((r.get("mae") for r in (block.get("global") or []) if r.get("delta") == 0.10), None)
            loc = next((r.get("mae") for r in (block.get("local") or []) if r.get("value") == 1.0), None)
            comb = (block.get("combined") or {}).get("mae_mean")
            ys = [nom, c, fb, g, loc, comb]
            ax.bar(
                x + (idx - 3.5) * w,
                [v if v is not None else np.nan for v in ys],
                w, label=f"{row['id']}-{arch}", color=colors[arch],
                alpha=0.55 if row["id"] == "A" else 0.95,
            )
            idx += 1
    ax.set_yscale("log")
    ax.set_xticks(x, labels, rotation=15, ha="right")
    ax.axhline(ERROR_LIMIT, color="#333", linestyle="--")
    ax.set_ylabel("MAE")
    ax.set_title("Experiment 17 comparison")
    ax.legend(fontsize=6, ncol=4)
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    p4 = RESULTS_DIR / "physical_iv_comparison.png"
    fig.savefig(p4, dpi=140)
    plt.close(fig)

    return {
        "gain": str(p1.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "tolerance": str(p2.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "supply": str(p3.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "comparison": str(p4.relative_to(PROJECT_ROOT)).replace("\\", "/"),
    }


def public_arch(block: dict) -> dict:
    return {
        k: v
        for k, v in block.items()
        if k not in {"net_nominal", "catalog", "y_sw", "y_mc", "x_sw", "x_mc"}
    }


def print_final(rows: list[dict], summary: dict, plots: dict) -> None:
    print("\n==================================================")
    print("EXPERIMENT 17")
    print("PHYSICAL CURRENT-TO-VOLTAGE NEURON")
    print("==================================================")
    t = summary["by_network"]
    for net_id in TEST_IDS:
        print(f"\nNETWORK {net_id}")
        for arch in ARCH_KEYS:
            rec = t[net_id][arch]
            print(
                f"  {arch}: MAE={fmt(rec.get('nominal_mae'))} "
                f"acc={fmt(rec.get('accuracy'), '.4f')} "
                f"nR={rec.get('n_resistors')} dumps={rec.get('n_current_dumps')} "
                f"TIA={rec.get('n_tia_opamps')} copies={rec.get('leftover_current_copies')} "
                f"Vsum={fmt(rec.get('vsum_max'))}"
            )
            print(
                f"      copy0.1={fmt(rec.get('copy_0.1'))} "
                f"Rf0.1={fmt(rec.get('fb_abs_0.1'))} "
                f"+10%={fmt(rec.get('global_p10'))} "
                f"comb={fmt(rec.get('combined_mae'))}"
            )
    print("\nBASELINE ARCHITECTURE I:")
    print(f"  F copy 0.1% MAE={fmt(t['F']['I'].get('copy_0.1'))} dumps={t['F']['I'].get('n_current_dumps')}")
    print("\nTIA:")
    print(f"  F-A copy 0.1% (open-loop) MAE={fmt(t['F']['A'].get('copy_0.1'))} Vsum={fmt(t['F']['A'].get('vsum_max'))}")
    print(f"  min A for MAE<=1e-3: {t['F']['A'].get('min_A_mae')}")
    print("\nRATIOMETRIC TIA:")
    print(f"  F-B +10% MAE={fmt(t['F']['B'].get('global_p10'))} -10% MAE={fmt(t['F']['B'].get('global_m10'))}")
    print("\nCURRENT-MODE:")
    print(f"  F-C leftover copies={t['F']['C'].get('leftover_current_copies')} comb={fmt(t['F']['C'].get('combined_mae'))}")
    print(f"\nBEST ARCHITECTURE: {summary['winner']}")
    print(f"MINIMUM REQUIRED AMPLIFIER GAIN: {t['F'][summary['winner']].get('min_A_mae')}")
    print(f"FIRST MAE > 1e-3: {t['F'][summary['winner']].get('local_first_1e3')}")
    print(f"LOCAL MISMATCH LIMIT: {t['F'][summary['winner']].get('local_first_1e3')}")
    print(
        f"GLOBAL SHIFT CANCELLATION: +10% MAE={fmt(t['F'][summary['winner']].get('global_p10'))} "
        f"-10% MAE={fmt(t['F'][summary['winner']].get('global_m10'))}"
    )
    print(f"LOWEST WORKING SUPPLY: +/- {t['F'][summary['winner']].get('lowest_working_supply')} V")
    print(f"CLASSIFICATION LIMIT: {t['F'][summary['winner']].get('local_first_class')}")
    print(f"REMAINING IDEAL BLOCK: {summary['remaining_ideal_block']}")
    print(f"DEVICE-LEVEL PREVIEW: {summary['device_preview']['status']}")
    print(f"  {summary['device_preview']['reason']}")
    print("\nFINAL STATUS:")
    print(summary["verdict"])
    print(f"\nWrote {REPORT_PATH}")
    for path in plots.values():
        print(f"Wrote {path}")


def evaluate_network(ngspice, spec) -> dict:
    weights = load_frozen_model(spec["id"])
    n_full = N_TEST
    n_sw = N_TEST if spec["id"] == "A" else N_F_SWEEP
    x_all = generate_inputs(spec["n_in"], n_full, spec["id"])
    x_sw, x_mc = x_all[:n_sw], x_all[:N_ROBUST_INPUTS]
    print(
        f"\n=== Network {spec['id']} {spec['n_in']}->{spec['n_hidden']}->"
        f"{spec['n_out']}  full={n_full} sweep={n_sw} ===",
        flush=True,
    )
    arches = {}
    for arch in ARCH_KEYS:
        block = evaluate_arch(ngspice, spec, weights, arch, x_all, x_sw, x_mc)
        y_sw, y_mc = block["y_sw"], block["y_mc"]
        if arch in TIA_ARCHES:
            print("    finite-gain sweep", flush=True)
            block["gain"] = sweep_gain(ngspice, spec, weights, arch, x_sw, y_sw)
        else:
            block["gain"] = []
        print("    copy-like sweep", flush=True)
        block["copy_like"] = sweep_copy_like(ngspice, spec, weights, arch, x_sw, y_sw)
        print("    feedback absolute", flush=True)
        block["fb_absolute"] = sweep_tolerance(ngspice, spec, block, "absolute", x_sw, y_sw)
        print("    feedback ratiometric", flush=True)
        block["fb_ratiometric"] = sweep_tolerance(ngspice, spec, block, "ratiometric", x_sw, y_sw)
        print("    global shift", flush=True)
        block["global"] = sweep_global(ngspice, spec, block, x_sw, y_sw)
        print("    local mismatch", flush=True)
        block["local"] = sweep_local(ngspice, spec, block, x_sw, y_sw)
        print("    supply", flush=True)
        block["rails"] = sweep_rail(ngspice, spec, weights, arch, x_sw)
        print("    combined MC", flush=True)
        block["combined"] = combined_mc(ngspice, spec, weights, arch, x_mc, y_mc)
        print(
            f"    combined MAE_mean={block['combined'].get('mae_mean')} "
            f"acc={block['combined'].get('accuracy_mean')}",
            flush=True,
        )
        arches[arch] = block
    return {
        "id": spec["id"],
        "label": f"{spec['id']} {spec['n_in']}->{spec['n_hidden']}->{spec['n_out']}",
        "architectures": arches,
        "n_full": n_full,
        "n_sweep": n_sw,
        "n_mc": N_ROBUST_INPUTS,
        "n_trials": N_MC_TRIALS,
    }


def main() -> int:
    ngspice = find_ngspice()
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    print("Physical AI - Experiment 17")
    print("PHYSICAL CURRENT-TO-VOLTAGE NEURON")
    print("Behavioral circuit analysis. Not transistor-level or PCB.")
    print(f"ngspice: {ngspice}")

    rows = [evaluate_network(ngspice, spec_by_id(net_id)) for net_id in TEST_IDS]
    plots = make_plots(rows)
    summary = analyze(rows)
    report = {
        "experiment": 17,
        "analysis": "physical I-to-V on Experiment 16 Architecture I fabric",
        "error_limit": ERROR_LIMIT,
        "fairness": (
            "Frozen Experiment 9 weights. No Python output correction. "
            "TIA closed-loop A/(A+1) is left uncompensated. "
            "Architecture I is reproduced from Experiment 16, not overwritten. "
            "V_sum is measured in SPICE. Not layout. Not foundry PCM."
        ),
        "architectures": ARCH_PUBLIC,
        "networks": [
            {
                **{k: v for k, v in row.items() if k != "architectures"},
                "architectures": {a: public_arch(b) for a, b in row["architectures"].items()},
            }
            for row in rows
        ],
        "plots": plots,
        "summary": summary,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print_final(rows, summary, plots)
    return 0


if __name__ == "__main__":
    sys.exit(main())
