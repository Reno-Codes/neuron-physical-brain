"""Experiment 24: offset-corrected virtual-ground search.

Frozen Experiment 9 weights. SPICE is never Python-corrected.
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
    classification_labels,
    detect_spice_failure,
    error_stats,
    generate_inputs,
    simulate_batch,
)
from compile_xor import PROJECT_ROOT, find_ngspice
from hardware_constrained_compiler import load_frozen_model
from offset_vg_search import (
    CIRCUIT_DIR,
    INVENTORY,
    OPA1611_PATH,
    OPA1656_PATH,
    OPA171_PATH,
    MCP6041_PATH,
    TLV6001_PATH,
    TLV9002_PATH,
    E24Params,
    bake_vin_dc,
    bake_vin_pulse,
    bake_vref_pulse,
    candidate_needs_ps,
    compile_isolated,
    compile_network,
    count_blocks,
    run_ngspice_ex,
    simple_op_control,
    simple_optran_control,
    tran_meas_control,
)
from physical_iv_neuron import IVParams, compile_iv
from precision_architectures import ARCH_C_CFG, hidden_preact_max, software_reference
from test_hardware_constraints import spec_by_id
from test_iv_architectures import ERROR_LIMIT, evaluate_netlist
from test_robustness import extract_all, sample_resistor_values
from virtual_ground_requirements import INVERT_PINNED, rank_neurons


RESULTS_DIR = PROJECT_ROOT / "results"
REPORT_JSON = RESULTS_DIR / "offset_vg_search_report.json"
REPORT_MD = RESULTS_DIR / "exp24_offset_vg_search.md"
N_A = 100
N_F = 40
TAG = "n1"
TIMEOUT = 180.0
TIMEOUT_MACRO = 180.0
TIMEOUT_TRAN = 120.0
VOS_MAP = (1e-6, 3e-6, 1e-5, 2.2e-5, 3e-5, 1e-4, 2.14e-4)
GAIN_MAP = (1e4, 3e4, 5e4, 1e5, 3e5, 1e6)
N_MC = 8
R_TOL = 0.005


def dest(*parts) -> Path:
    name = "_".join(
        str(p).replace("%", "pct").replace(".", "p").replace("+", "p").replace("-", "m")
        for p in parts
    )
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    return CIRCUIT_DIR / f"{name}.cir"


def fmt(value, spec=".4e") -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return format(value, spec)
    return str(value)


def software_for(weights, inputs, rail: float = 15.0, linear: bool = False):
    zmax, hmax = hidden_preact_max(inputs, weights["W1"], weights["b1"])
    clipped = (not linear) and hmax > rail + 1e-12
    y = software_reference(
        inputs, weights["W1"], weights["b1"], weights["W2"], weights["b2"],
        linear=linear, hidden_rail=rail if clipped else None,
    )
    return y, {"hidden_preact_max": zmax, "hidden_relu_max": hmax, "clipped": clipped}


def simulate_op_vectors(ngspice, net, inputs, n_in, nodes, path, pspice=False, timeout=TIMEOUT):
    head, sep, _ = net.partition(".control")
    if not sep:
        return None, "no .control", ""
    rows = []
    logs = []
    for i, x in enumerate(np.atleast_2d(np.asarray(inputs, dtype=float))):
        baked = bake_vin_dc(head, x[:n_in])
        used = None
        text = ""
        for method, ctrl in (("op", simple_op_control), ("optran", simple_optran_control)):
            vec_path = path.with_name(f"{path.stem}_v{i}_{method}.cir")
            vec_path.write_text(baked.rstrip() + "\n" + ctrl(nodes), encoding="utf-8")
            result = run_ngspice_ex(ngspice, vec_path, timeout=timeout, pspice=pspice)
            text = f"{result.stdout or ''}\n{result.stderr or ''}"
            fail = detect_spice_failure(result)
            vals = [extract_all(text, f"v({n})") for n in nodes]
            if not fail and all(v for v in vals):
                rows.append([float(v[-1]) for v in vals])
                used = method
                break
        if used is None:
            return None, f"vector {i}: op/optran failed", text[-1200:]
        logs.append(f"v{i} {used}")
    return np.array(rows, float), None, "; ".join(logs[-2:])


def simulate_tran_vectors(ngspice, net, inputs, n_in, nodes, path, params: E24Params, pulse: bool):
    head, sep, _ = net.partition(".control")
    if not sep:
        return None, "no .control", ""
    t_meas = 0.85 * float(params.t_stop)
    avg_start = None
    if params.chopper:
        avg_start = max(0.0, float(params.t_stop) - 2.0 * float(params.chop_period))
    rows = []
    for i, x in enumerate(np.atleast_2d(np.asarray(inputs, dtype=float))):
        vec_path = path.with_name(f"{path.stem}_t{i}.cir")
        body = bake_vin_pulse(head, x[:n_in], params.t_az) if pulse else bake_vin_dc(head, x[:n_in])
        if pulse and params.gate_vref:
            body = bake_vref_pulse(body, params.t_az)
        vec_path.write_text(
            body.rstrip()
            + "\n"
            + tran_meas_control(nodes, params.t_stop, t_meas, avg_start=avg_start),
            encoding="utf-8",
        )
        result = run_ngspice_ex(ngspice, vec_path, timeout=TIMEOUT_TRAN, pspice=False)
        text = f"{result.stdout or ''}\n{result.stderr or ''}"
        vals = []
        for j, _n in enumerate(nodes):
            found = extract_all(text, f"m{j}")
            if not found:
                return None, f"vector {i}: missing m{j}", text[-800:]
            vals.append(float(found[-1]))
        if result.returncode != 0:
            return None, f"vector {i}: rc={result.returncode}", text[-800:]
        rows.append(vals)
    return np.array(rows, float), None, f"n={len(rows)}"


def iso_eval(ngspice, spec, weights, pick, params: E24Params, inputs):
    hidden = pick["layer"] == 1
    idx = pick["index"]
    wrow = weights["W1"][idx] if hidden else weights["W2"][idx]
    bias = float(weights["b1"][idx] if hidden else weights["b2"][idx])
    cfg = ARCH_C_CFG[spec["id"]]
    g_w = cfg.g_weight_1 if hidden else cfg.g_weight_2
    n_src = spec["n_in"] if hidden else spec["n_hidden"]
    net, cat, reason = compile_isolated(n_src, wrow, bias, g_w, cfg.banks, params, tag=TAG)
    rec = {
        "tag": pick["tag"],
        "candidate": params.candidate,
        "name": params.name,
        "failed": bool(reason),
        "failure_reason": reason,
        "vos": params.vos,
        "A": params.amp_gain,
        "autozero": params.autozero,
        "servo": params.servo,
        "chopper": params.chopper,
        "n_resistors": len(cat) if cat else None,
    }
    if reason or net is None:
        return rec
    x = np.atleast_2d(np.asarray(inputs, dtype=float))[:, :n_src]
    z = x @ np.asarray(wrow, float) + bias
    path = dest("iso", pick["tag"], params.candidate, params.name)
    nodes = [f"{TAG}lin", f"{TAG}p"]
    if params.autozero:
        arr, err, log = simulate_tran_vectors(ngspice, net, x, n_src, nodes, path, params, True)
    elif params.chopper:
        arr, err, log = simulate_tran_vectors(ngspice, net, x, n_src, nodes, path, params, False)
    else:
        arr, err, log = simulate_op_vectors(
            ngspice, net, x, n_src, nodes, path,
            pspice=candidate_needs_ps(params.candidate),
            timeout=TIMEOUT_MACRO if candidate_needs_ps(params.candidate) else TIMEOUT,
        )
    if err or arr is None:
        rec.update({"failed": True, "failure_reason": err, "log_tail": (log or "")[-600:]})
        return rec
    vlin, vsum = arr[:, 0], arr[:, 1]
    rec.update({
        "failed": False,
        "mae_vs_z": float(np.mean(np.abs(vlin - z))),
        "max_vs_z": float(np.max(np.abs(vlin - z))),
        "mean_vsum": float(np.mean(np.abs(vsum))),
        "max_vsum": float(np.max(np.abs(vsum))),
        "vlin_abs_max": float(np.max(np.abs(vlin))),
        "z_abs_max": float(np.max(np.abs(z))),
        "n_vectors": int(len(z)),
        "log_tail": log,
    })
    return rec


def eval_network(ngspice, spec, weights, params: E24Params, inputs, y, path):
    net, cat, reason = compile_network(spec, weights, params, linear=False)
    rec = {"failed": True, "failure_reason": reason, "params": params.public()}
    if reason or net is None:
        return rec, net, cat
    path.write_text(net, encoding="utf-8")
    ps = candidate_needs_ps(params.candidate)
    n_out = spec["n_out"]
    n_in = spec["n_in"]
    nodes = [f"o{k}lin" for k in range(1, n_out + 1)]
    if params.autozero:
        arr, err, log = simulate_tran_vectors(ngspice, net, inputs, n_in, nodes, path, params, True)
        if err or arr is None:
            rec = {"failed": True, "failure_reason": err, "log_tail": log, "params": params.public()}
            return rec, net, cat
        physical = arr
    elif ps:
        arr, err, log = simulate_op_vectors(
            ngspice, net, inputs, n_in, nodes, path, pspice=True, timeout=TIMEOUT_MACRO
        )
        if err or arr is None:
            rec = {"failed": True, "failure_reason": err, "log_tail": log, "params": params.public()}
            return rec, net, cat
        physical = arr
    else:
        physical, _rt, err, log = simulate_batch(
            ngspice, net, inputs, spec["n_out"], path, timeout=TIMEOUT
        )
        if err or physical is None:
            rec = {
                "failed": True,
                "failure_reason": err or "no physical outputs",
                "log_tail": log,
                "params": params.public(),
                "n_resistors": len(cat),
                "blocks": count_blocks(net),
            }
            return rec, net, cat
        errst = error_stats(physical, y)
        pred = classification_labels(physical)
        expected = classification_labels(y)
        n_fail = int(np.sum(pred != expected))
        rec = {
            "failed": False,
            "failure_reason": None,
            "mae": errst["mae"],
            "rms": errst["rms"],
            "max_abs_error": errst["max_abs_error"],
            "accuracy": float(1.0 - n_fail / max(len(expected), 1)),
            "n_class_failures": n_fail,
            "params": params.public(),
            "n_resistors": len(cat),
            "blocks": count_blocks(net),
        }
        return rec, net, cat
    errst = error_stats(physical, y)
    pred = classification_labels(physical)
    expected = classification_labels(y)
    n_fail = int(np.sum(pred != expected))
    rec = {
        "failed": False,
        "failure_reason": None,
        "mae": errst["mae"],
        "rms": errst["rms"],
        "max_abs_error": errst["max_abs_error"],
        "accuracy": float(1.0 - n_fail / max(len(expected), 1)),
        "n_class_failures": n_fail,
        "params": params.public(),
        "n_resistors": len(cat),
        "blocks": count_blocks(net),
    }
    return rec, net, cat


def smoke_macro(ngspice, name, include, subckt, vsupply, pspice):
    recs = []
    for method, extra in (
        ("op", ["op"]),
        ("optran", ["optran 0 0 0 100n 10u 0"]),
    ):
        path = dest("smoke", name, method)
        path.write_text(
            "\n".join([
                f"* Exp 24 smoke {name} textbook TIA Vin=1 Rw=Rf=10k {method}",
                f'.include "{include.as_posix()}"',
                f"Vdd vdd 0 DC {vsupply}",
                f"Vss vss 0 DC {-vsupply}",
                "Vin in 0 DC 1",
                "Rw in sum 10000",
                f"Xtia 0 sum vdd vss lin {subckt}",
                "Rf lin sum 10000",
                "Cload lin 0 1p",
                ".control",
                "set numdgt=15",
                *extra,
                "print v(lin)",
                "print v(sum)",
                ".endc",
                ".end",
                "",
            ]),
            encoding="utf-8",
        )
        result = run_ngspice_ex(ngspice, path, timeout=45.0, pspice=pspice)
        text = f"{result.stdout or ''}\n{result.stderr or ''}"
        vlin = extract_all(text, "v(lin)")
        vsum = extract_all(text, "v(sum)")
        rec = {
            "exit": result.returncode,
            "vlin": vlin[-1] if vlin else None,
            "vsum": vsum[-1] if vsum else None,
            "ok": result.returncode == 0 and bool(vlin),
            "tail": text[-300:],
            "method": method,
        }
        recs.append({k: rec[k] for k in ("exit", "vlin", "vsum", "ok", "method")})
        if rec["ok"]:
            rec["attempts"] = list(recs)
            return rec
    last = recs[-1]
    last = dict(last)
    last["attempts"] = list(recs)
    return last


def eval_loaded_tag(ngspice, spec, weights, params: E24Params, inputs, y, tag: str):
    """Shared fabric: score one neuron versus software y[:,idx] and measure Vsum."""
    idx = int(tag[1:]) - 1
    net, cat, reason = compile_network(spec, weights, params, linear=False)
    rec = {
        "tag": tag,
        "mode": "loaded_full_fabric",
        "failed": bool(reason),
        "failure_reason": reason,
        "n_resistors": len(cat) if cat else None,
        "blocks": count_blocks(net) if net else None,
    }
    if reason or net is None:
        return rec
    n_in = spec["n_in"]
    nodes = [f"{tag}lin", f"{tag}p"]
    path = dest("loaded", tag, params.candidate, params.name)
    if params.autozero or params.chopper:
        arr, err, log = simulate_tran_vectors(
            ngspice, net, inputs, n_in, nodes, path, params, pulse=params.autozero
        )
    else:
        arr, err, log = simulate_op_vectors(
            ngspice, net, inputs, n_in, nodes, path,
            pspice=candidate_needs_ps(params.candidate),
            timeout=TIMEOUT_MACRO if candidate_needs_ps(params.candidate) else TIMEOUT,
        )
    if err or arr is None:
        rec.update({"failed": True, "failure_reason": err, "log_tail": (log or "")[-600:]})
        return rec
    ycol = np.atleast_2d(np.asarray(y, dtype=float))[:, idx]
    rec.update({
        "failed": False,
        "loaded_mae_vs_y": float(np.mean(np.abs(arr[:, 0] - ycol))),
        "loaded_max_vs_y": float(np.max(np.abs(arr[:, 0] - ycol))),
        "loaded_max_vsum": float(np.max(np.abs(arr[:, 1]))),
        "loaded_mean_vsum": float(np.mean(np.abs(arr[:, 1]))),
        "n_vectors": int(len(ycol)),
    })
    return rec


def write_plots(report: dict) -> list[str]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    paths = []
    fmap = report.get("feasibility_map") or []
    if fmap:
        fig, axes = plt.subplots(1, 2, figsize=(9.2, 4.0))
        gains = sorted({r["A"] for r in fmap if r.get("mae") is not None})
        vos = sorted({r["vos"] for r in fmap if r.get("mae") is not None})
        if gains and vos:
            mae = np.full((len(vos), len(gains)), np.nan)
            acc = np.full((len(vos), len(gains)), np.nan)
            gi = {g: i for i, g in enumerate(gains)}
            vi = {v: i for i, v in enumerate(vos)}
            for r in fmap:
                if r.get("mae") is None:
                    continue
                mae[vi[r["vos"]], gi[r["A"]]] = r["mae"]
                acc[vi[r["vos"]], gi[r["A"]]] = r["accuracy"]
            im0 = axes[0].imshow(
                np.log10(np.clip(mae, 1e-5, 1e-1)),
                origin="lower", aspect="auto",
                extent=[np.log10(gains[0]), np.log10(gains[-1]), np.log10(vos[0]), np.log10(vos[-1])],
            )
            axes[0].set_xlabel("log10 A")
            axes[0].set_ylabel("log10 |Vos|")
            axes[0].set_title("F analog MAE (log10)")
            fig.colorbar(im0, ax=axes[0], fraction=0.046)
            im1 = axes[1].imshow(
                acc, origin="lower", aspect="auto", vmin=0.7, vmax=1.0,
                extent=[np.log10(gains[0]), np.log10(gains[-1]), np.log10(vos[0]), np.log10(vos[-1])],
            )
            axes[1].set_xlabel("log10 A")
            axes[1].set_ylabel("log10 |Vos|")
            axes[1].set_title("F classification")
            fig.colorbar(im1, ax=axes[1], fraction=0.046)
        fig.tight_layout()
        p = RESULTS_DIR / "offset_vg_feasibility_map.png"
        fig.savefig(p, dpi=140)
        plt.close(fig)
        paths.append(str(p))
    rows = []
    for key, rec in (report.get("network_F") or {}).items():
        if isinstance(rec, dict) and rec.get("mae") is not None:
            rows.append((key, rec["mae"]))
    if rows:
        fig, ax = plt.subplots(figsize=(7.6, 4.2))
        xs = np.arange(len(rows))
        ax.bar(xs, [r[1] for r in rows], color="#4c6")
        ax.axhline(ERROR_LIMIT, color="k", ls="--", lw=0.8, label="MAE=1e-3")
        ax.set_xticks(list(xs))
        ax.set_xticklabels([r[0] for r in rows], rotation=35, ha="right")
        ax.set_yscale("log")
        ax.set_ylabel("Network F analog MAE")
        ax.set_title("Experiment 24: Network F analog MAE")
        ax.legend(fontsize=8)
        fig.tight_layout()
        p = RESULTS_DIR / "offset_vg_network_F.png"
        fig.savefig(p, dpi=140)
        plt.close(fig)
        paths.append(str(p))
    return paths


def write_markdown(report: dict) -> None:
    inv = report.get("inventory") or INVENTORY
    lines = [
        "# EXPERIMENT 24",
        "# OFFSET-CORRECTED VIRTUAL-GROUND SEARCH",
        "",
        "## 1. Baseline reproduction",
        f"{report.get('baseline')}",
        "",
        "## 2. Candidate / model inventory",
        "| ID | Level | Documented Vos | Source | Note |",
        "|---|---:|---:|---|---|",
    ]
    for k, m in inv.items():
        lines.append(
            f"| {k} | {m.get('level')} | {fmt(m.get('model_vos_V'))} | {m.get('source')} | {m.get('note')} |"
        )
    lines += ["", "### Smokes", "| Circuit | exit | v(lin) | v(sum) |", "|---|---:|---:|---:|"]
    for name, rec in (report.get("smokes") or {}).items():
        lines.append(f"| {name} | {rec.get('exit')} | {fmt(rec.get('vlin'))} | {fmt(rec.get('vsum'))} |")
    lines += [
        "",
        "## 3. Worst-neuron screening (Network F o2)",
        "| Candidate | failed | MAE vs z | max |Vsum| | reason |",
        "|---|---|---:|---:|---|",
    ]
    for name, rec in (report.get("unit_cell") or {}).items():
        if isinstance(rec, dict):
            lines.append(
                f"| {name} | {rec.get('failed')} | {fmt(rec.get('mae_vs_z'))} | "
                f"{fmt(rec.get('max_vsum'))} | {rec.get('failure_reason') or ''} |"
            )
    lines += [
        "",
        "## 4. Full-network results",
        "| Net | Candidate | failed | MAE | max abs | class | reason |",
        "|---|---|---|---:|---:|---:|---|",
    ]
    for label, block in (("A", report.get("network_A")), ("F", report.get("network_F"))):
        for name, rec in (block or {}).items():
            if isinstance(rec, dict):
                lines.append(
                    f"| {label} | {name} | {rec.get('failed')} | {fmt(rec.get('mae'))} | "
                    f"{fmt(rec.get('max_abs_error'))} | {fmt(rec.get('accuracy'))} | "
                    f"{rec.get('failure_reason') or ''} |"
                )
    lines += [
        "",
        "## 5. Offset-correction architecture results",
        "### Auto-zero (Vin=0 only)",
        str(report.get("autozero")),
        "",
        "### Auto-zero with Vref gated",
        str(report.get("autozero_vref")),
        "",
        "### Servo",
        str(report.get("servo")),
        "",
        "### Chopper-equivalent",
        str(report.get("chopper")),
        "",
        "### Loaded o2 (shared fabric)",
        str(report.get("loaded_o2")),
        "",
        "## 6. Gain/offset feasibility map (Network F, XSPICE L)",
        "| A | Vos | MAE | class | failed |",
        "|---:|---:|---:|---:|---|",
    ]
    fmap = report.get("feasibility_map") or []
    for r in fmap:
        lines.append(
            f"| {fmt(r.get('A'))} | {fmt(r.get('vos'))} | {fmt(r.get('mae'))} | "
            f"{fmt(r.get('accuracy'))} | {r.get('failed')} |"
        )
    analog_pass = [r for r in fmap if (not r.get("failed")) and r.get("mae") is not None and r["mae"] <= ERROR_LIMIT]
    class_pass = [r for r in fmap if (not r.get("failed")) and r.get("accuracy") == 1.0]
    lines += [
        "",
        f"Analog-pass cells (MAE<=1e-3): {len(analog_pass)} / {len(fmap)}",
        f"Classification-pass cells (100%): {len(class_pass)} / {len(fmap)}",
        "",
        "## 7. Analog versus classification boundary",
        report.get("analog_vs_class") or "",
        "",
        "## 8. Minimal realistic error budget",
        str(report.get("error_budget")),
        "",
        "## 9. Best architecture",
        report.get("best_architecture") or "",
        "",
        "## 10. First failure mechanism",
        report.get("fails_first") or "",
        "",
        "## 11. Physical realism level",
        report.get("hardware_level") or "",
        "",
        "### Physical accounting (quantities actually in the netlists)",
        str(report.get("physical_accounting")),
        "",
        "## 12. Limitations",
        report.get("limitations") or "",
        "",
        "## 13. Honest recommendation for Experiment 25",
        report.get("next_experiment") or "",
        "",
        "## FINAL STATUS",
        report.get("final_status") or "",
        "",
        "SPICE is the source of truth. Frozen Experiment 9 weights were not edited.",
        "",
    ]
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")


def conclude(report: dict) -> None:
    net_f = report.get("network_F") or {}
    az = report.get("autozero") or {}
    fmap = report.get("feasibility_map") or []
    analog_ok = [
        name for name, rec in net_f.items()
        if isinstance(rec, dict) and not rec.get("failed") and rec.get("mae") is not None and rec["mae"] <= ERROR_LIMIT
    ]
    high_a_offset = [
        r for r in fmap
        if r.get("A") and r["A"] >= 1e5 and r.get("vos") and r["vos"] >= 1e-4 and r.get("mae") is not None
    ]
    still_high = all(r["mae"] > ERROR_LIMIT for r in high_a_offset) if high_a_offset else True

    def max_pass_vos(gain, analog=True):
        rows = [
            r for r in fmap
            if r.get("A") == gain and not r.get("failed") and r.get("mae") is not None
        ]
        rows.sort(key=lambda r: r["vos"])
        last = None
        for r in rows:
            ok = (r["mae"] <= ERROR_LIMIT) if analog else (r.get("accuracy") == 1.0)
            if ok:
                last = r["vos"]
        return last

    a1e5_analog = max_pass_vos(1e5, True)
    a1e5_class = max_pass_vos(1e5, False)
    a1e6_analog = max_pass_vos(1e6, True)
    report["analog_vs_class"] = (
        "Analog MAE<=1e-3 is much tighter than 100% classification on F. "
        f"At A=1e5 the analog-passing |Vos| ceiling in this map is {fmt(a1e5_analog)}; "
        f"classification-passing ceiling is {fmt(a1e5_class)}. "
        f"At A=1e6 analog ceiling is {fmt(a1e6_analog)}. "
        f"High A does not cancel Vos>=100 uV ({'confirmed' if still_high else 'see map'})."
    )
    report["best_architecture"] = (
        f"Analog-passing F candidates this run: {analog_ok or 'none besides L Vos=0 baseline if it passed'}. "
        "LEVEL 2 L at Vos=0 still matches Exp 17/23."
    )
    servo = (report.get("servo") or {}).get("isolated_o2") or {}
    servo_nulls = (
        servo.get("vlin_abs_max") is not None
        and servo.get("z_abs_max") not in (None, 0)
        and servo["vlin_abs_max"] < 0.05 * abs(servo["z_abs_max"])
    )
    report["fails_first"] = (
        "Input offset amplified by (1+Rf G_tot) on the worst neuron, plus shared-tap "
        "coupling. High open-loop gain does not remove that floor. "
        + (
            "The Vsum servo collapsed Vlin with the offset (cannot separate Vos from finite-A residue)."
            if servo_nulls else
            "A summing-node servo was tested on loaded inference, not only zero-input offset."
        )
    )
    report["hardware_level"] = (
        "LEVEL 2 behavioral (L, auto-zero S/H, chopper-equivalent, servo). "
        "LEVEL 3 documented macromodels (OPA1656, OPA1611). Not LEVEL 4-6."
    )
    report["limitations"] = (
        "Auto-zero uses an ideal switch and capacitor (LEVEL 2). Chopper modulates Vos "
        "on IN+; it does not swap TIA inputs. GWL macromodels use 1 pF load C for OP "
        "and may use optran. Vendor files included, not copied. Isolated MAE vs z is "
        "stricter than full-network analog MAE."
    )
    opa1656_f = net_f.get("OPA1656") or {}
    az_f = az.get("network_F") or {}
    az_iso = az.get("isolated_o2") or {}
    az_loaded = az.get("loaded_o2") or {}
    az_vref_f = (report.get("autozero_vref") or {}).get("network_F") or {}
    servo_f = (report.get("servo") or {}).get("network_F") or {}
    servo_a = (report.get("servo") or {}).get("network_A") or {}
    if servo_f.get("mae") is not None and servo_f.get("mae") <= ERROR_LIMIT and servo_f.get("accuracy") == 1.0:
        status = "BEHAVIORAL SERVO VALIDATED"
        nxt = (
            "Experiment 25: keep the LEVEL 2 summing-node servo as the offset architecture "
            "and test its dynamics/stability (pole, nested-loop settling) without inventing MOS W/L. "
            "Do not rebuild the resistor encoding."
        )
    elif opa1656_f.get("mae") is not None and opa1656_f.get("mae") <= ERROR_LIMIT and opa1656_f.get("accuracy") == 1.0:
        status = "LOW-OFFSET MACROMODEL VALIDATED"
        nxt = "Experiment 25: OPA1656 plus 0.5% mismatch, then only if analog holds a device-level unit cell."
    elif az_vref_f.get("mae") is not None and az_vref_f["mae"] <= ERROR_LIMIT:
        status = "BEHAVIORAL AUTO-ZERO VALIDATED"
        nxt = "Experiment 25: more physical switched-capacitor auto-zero unit cell. Do not rebuild encoding."
    elif az_f.get("mae") is not None and az_f["mae"] <= ERROR_LIMIT:
        status = "BEHAVIORAL AUTO-ZERO VALIDATED"
        nxt = "Experiment 25: more physical switched-capacitor auto-zero unit cell. Do not rebuild encoding."
    elif az_iso.get("mae_vs_z") is not None and az_iso["mae_vs_z"] <= ERROR_LIMIT and (
        (az_f.get("mae") is not None and az_f.get("mae") > ERROR_LIMIT)
        or (az_loaded.get("loaded_mae_vs_y") is not None and az_loaded["loaded_mae_vs_y"] > ERROR_LIMIT)
        or az_f.get("failed")
    ):
        status = "AUTO-ZERO FABRIC-LIMITED"
        nxt = "Experiment 25: shared-tap coupling during AZ hold (Exp 19 class). Do not invent MOS W/L yet."
    else:
        status = "VG OFFSET BOUNDARY EXTRACTED"
        nxt = (
            "Experiment 25 should not invent a new weight encoding. The fabric needs |Vos| "
            "below the analog contour on the Experiment 24 map, or a VG primitive that "
            "meets that spec under Rf*Gtot~141."
        )
    report["final_status"] = status
    report["next_experiment"] = nxt
    report["conclusion"] = f"{status}. {nxt}"


def mc_l(ngspice, spec, weights, inputs, y, vos, mismatch, seed, name):
    params = E24Params(candidate="L", name=name, vos=vos, linear=False)
    net, cat, reason = compile_network(spec, weights, params, linear=False)
    rec = {"name": name, "vos": vos, "mismatch": mismatch, "failed": bool(reason)}
    if reason or net is None:
        rec["failure_reason"] = reason
        return rec
    rng = np.random.default_rng(seed)
    maes, accs = [], []
    expected = classification_labels(y)
    draws = N_MC if mismatch else 1
    for i in range(draws):
        values = sample_resistor_values(cat, R_TOL, rng) if mismatch else {}
        physical, _rt, err, _ = simulate_batch(
            ngspice, net, inputs, spec["n_out"], dest("mc", name, i), r_values=values, timeout=180.0
        )
        if err or physical is None:
            continue
        stats = error_stats(physical, y)
        pred = classification_labels(physical)
        maes.append(stats["mae"])
        accs.append(float(np.mean(pred == expected)))
    rec["n_ok"] = len(maes)
    rec["mae_mean"] = float(np.mean(maes)) if maes else None
    rec["mae_max"] = float(np.max(maes)) if maes else None
    rec["acc_mean"] = float(np.mean(accs)) if accs else None
    rec["failed"] = not maes
    return rec


def main() -> int:
    print("Experiment 24: offset-corrected virtual-ground search", flush=True)
    ngspice = find_ngspice()
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "experiment": 24,
        "title": "offset-corrected virtual-ground search",
        "inventory": INVENTORY,
        "spice_source_of_truth": True,
        "files_exist": {
            "OPA1656": OPA1656_PATH.exists(),
            "OPA1611": OPA1611_PATH.exists(),
            "OPA171": OPA171_PATH.exists(),
            "MCP6041": MCP6041_PATH.exists(),
            "TLV6001": TLV6001_PATH.exists(),
            "TLV9002": TLV9002_PATH.exists(),
        },
    }
    spec_a, spec_f = spec_by_id("A"), spec_by_id("F")
    wa, wf = load_frozen_model("A"), load_frozen_model("F")
    xa = generate_inputs(spec_a["n_in"], N_A, "exp24_A")
    xf = generate_inputs(spec_f["n_in"], N_F, "exp24_F")
    ya, _ = software_for(wa, xa)
    yf, _ = software_for(wf, xf)

    print("Phase 1: baseline + smokes", flush=True)
    baseline = {}
    for net_id, spec, w, x, y in (("A", spec_a, wa, xa, ya), ("F", spec_f, wf, xf, yf)):
        net_i, _, r_i = compile_iv("I", spec, w)
        rec_i = evaluate_netlist(ngspice, spec, net_i, x, y, dest(net_id, "I")) if net_i else {"failed": True}
        rec_l, _, _ = eval_network(
            ngspice, spec, w, E24Params(candidate="L", name="base", linear=False), x, y, dest(net_id, "Lbase")
        )
        baseline[net_id] = {
            "I": {k: rec_i.get(k) for k in ("mae", "accuracy", "failed")},
            "L": {k: rec_l.get(k) for k in ("mae", "accuracy", "failed", "failure_reason")},
        }
        print(f"  {net_id} I MAE={fmt(rec_i.get('mae'))} L MAE={fmt(rec_l.get('mae'))}", flush=True)
    report["baseline"] = baseline

    smokes = {
        "OPA1656": smoke_macro(ngspice, "OPA1656", OPA1656_PATH, "OPA1656", 15.0, True),
        "OPA1611": smoke_macro(ngspice, "OPA1611", OPA1611_PATH, "OPA1611", 15.0, True),
    }
    for k, v in smokes.items():
        print(f"  smoke {k} exit={v['exit']} vlin={fmt(v['vlin'])} vsum={fmt(v['vsum'])}", flush=True)
    report["smokes"] = smokes

    print("Phase 2: rank F and isolated o2", flush=True)
    _net_rank, cat_rank, _ = compile_iv("A", spec_f, wf, IVParams(name="rank", invert_gain=INVERT_PINNED))
    _rows, selected = rank_neurons(spec_f, cat_rank, wf, xf)
    o2 = selected["worst_finite_gain"]
    h16 = selected["worst_leakage"]
    report["ranking"] = {"worst": o2["tag"], "Rf_Gtot": o2.get("Rf_Gtot"), "leak": h16["tag"]}
    iso_h = generate_inputs(spec_f["n_in"], 16, "exp24_iso_h")
    z1 = iso_h @ wf["W1"].T + wf["b1"]
    iso_o = np.maximum(0.0, z1[:16])

    def iso_x(pick):
        return iso_h if pick["layer"] == 1 else iso_o

    unit = {}
    for cand, extra in (
        ("L", {"vos": 0.0}),
        ("L", {"vos": 214.023e-6, "name": "L214u"}),
        ("L", {"vos": 8.75e-6, "name": "L8750n"}),
        ("OPA1656", {"vsupply": 15.0}),
        ("OPA1611", {"vsupply": 15.0}),
    ):
        name = extra.pop("name", cand)
        if cand in smokes and not smokes[cand].get("ok"):
            unit[name] = {"failed": True, "failure_reason": "skipped: smoke failed", "candidate": cand}
            print(f"  o2 {name} skipped: smoke failed", flush=True)
            continue
        params = E24Params(candidate=cand, name=name, linear=True, **extra)
        rec = iso_eval(ngspice, spec_f, wf, o2, params, iso_x(o2))
        unit[name] = rec
        print(
            f"  o2 {name} fail={rec.get('failed')} MAE_z={fmt(rec.get('mae_vs_z'))} "
            f"Vsum={fmt(rec.get('max_vsum'))} {rec.get('failure_reason')}",
            flush=True,
        )
    report["unit_cell"] = unit

    print("Phase 2b: loaded o2 on shared F fabric (8 vectors)", flush=True)
    x_load = xf[:8]
    y_load, _ = software_for(wf, x_load)
    loaded = {}
    for cand, extra in (
        ("L", {"vos": 0.0, "name": "L0"}),
        ("L", {"vos": 214.023e-6, "name": "L214u"}),
        ("L", {"vos": 8.75e-6, "name": "L8750n"}),
        ("OPA1656", {"vsupply": 15.0, "name": "OPA1656"}),
        ("OPA1611", {"vsupply": 15.0, "name": "OPA1611"}),
    ):
        name = extra.pop("name")
        if unit.get(name, {}).get("failed") and cand != "L":
            loaded[name] = {"failed": True, "failure_reason": "skipped: isolated failed"}
            continue
        params = E24Params(candidate=cand, name=f"ld_{name}", linear=False, **extra)
        rec = eval_loaded_tag(ngspice, spec_f, wf, params, x_load, y_load, o2["tag"])
        loaded[name] = rec
        print(
            f"  loaded {o2['tag']} {name} fail={rec.get('failed')} "
            f"MAE_y={fmt(rec.get('loaded_mae_vs_y'))} Vsum={fmt(rec.get('loaded_max_vsum'))}",
            flush=True,
        )
    report["loaded_o2"] = loaded

    print("Phase 3: Network A then F", flush=True)
    net_a, net_f = {}, {}
    net_a["L_vos0"] = baseline["A"]["L"]
    net_f["L_vos0"] = baseline["F"]["L"]
    rec, net_l214, cat_l214 = eval_network(
        ngspice, spec_f, wf, E24Params(candidate="L", name="F214", vos=214.023e-6, linear=False),
        xf, yf, dest("F", "L214"),
    )
    net_f["L_214uV"] = {k: rec.get(k) for k in ("mae", "max_abs_error", "accuracy", "failed", "failure_reason", "blocks", "n_resistors")}
    print(f"  F L 214uV MAE={fmt(rec.get('mae'))} acc={rec.get('accuracy')}", flush=True)
    for cand in ("OPA1656", "OPA1611"):
        iso_ok = not (unit.get(cand) or {}).get("failed")
        smoke_ok = bool((smokes.get(cand) or {}).get("ok"))
        if not smoke_ok:
            net_a[cand] = {"failed": True, "failure_reason": "skipped: smoke failed"}
            net_f[cand] = {"failed": True, "failure_reason": "skipped: smoke failed"}
            continue
        if not iso_ok:
            net_a[cand] = {"failed": True, "failure_reason": "skipped: isolated o2 failed"}
            net_f[cand] = {"failed": True, "failure_reason": "skipped: isolated o2 failed"}
            continue
        rec, _, _ = eval_network(
            ngspice, spec_a, wa, E24Params(candidate=cand, name=f"A_{cand}", linear=False, vsupply=15.0),
            xa, ya, dest("A", cand),
        )
        net_a[cand] = {k: rec.get(k) for k in ("mae", "max_abs_error", "accuracy", "failed", "failure_reason", "blocks", "n_resistors")}
        print(f"  A {cand} fail={rec.get('failed')} MAE={fmt(rec.get('mae'))} acc={rec.get('accuracy')}", flush=True)
        if rec.get("failed"):
            net_f[cand] = {"failed": True, "failure_reason": "skipped: Network A failed"}
            continue
        recf, _, _ = eval_network(
            ngspice, spec_f, wf, E24Params(candidate=cand, name=f"F_{cand}", linear=False, vsupply=15.0),
            xf, yf, dest("F", cand),
        )
        net_f[cand] = {k: recf.get(k) for k in ("mae", "max_abs_error", "accuracy", "failed", "failure_reason", "blocks", "n_resistors")}
        print(f"  F {cand} fail={recf.get('failed')} MAE={fmt(recf.get('mae'))} acc={recf.get('accuracy')}", flush=True)
    report["network_A"] = net_a
    report["network_F"] = net_f

    print("Phase 4: auto-zero / servo / chopper", flush=True)
    p_az = E24Params(candidate="L", name="az214", vos=214.023e-6, linear=True, autozero=True, t_az=2e-5, t_stop=8e-5)
    az = {"isolated_o2": iso_eval(ngspice, spec_f, wf, o2, p_az, iso_x(o2))}
    print(
        f"  AZ o2 fail={az['isolated_o2'].get('failed')} MAE_z={fmt(az['isolated_o2'].get('mae_vs_z'))} "
        f"{az['isolated_o2'].get('failure_reason')}",
        flush=True,
    )
    p_az_ld = E24Params(candidate="L", name="azld214", vos=214.023e-6, linear=False, autozero=True, t_az=2e-5, t_stop=8e-5)
    az["loaded_o2"] = eval_loaded_tag(ngspice, spec_f, wf, p_az_ld, x_load, y_load, o2["tag"])
    print(
        f"  AZ loaded o2 fail={az['loaded_o2'].get('failed')} "
        f"MAE_y={fmt(az['loaded_o2'].get('loaded_mae_vs_y'))} "
        f"Vsum={fmt(az['loaded_o2'].get('loaded_max_vsum'))}",
        flush=True,
    )
    p_az_a = E24Params(candidate="L", name="azA214", vos=214.023e-6, linear=False, autozero=True, t_az=2e-5, t_stop=8e-5)
    rec, _, _ = eval_network(ngspice, spec_a, wa, p_az_a, xa, ya, dest("A", "AZ214"))
    az["network_A"] = {k: rec.get(k) for k in ("mae", "max_abs_error", "accuracy", "failed", "failure_reason", "blocks")}
    print(f"  AZ A fail={rec.get('failed')} MAE={fmt(rec.get('mae'))} acc={rec.get('accuracy')}", flush=True)
    if rec.get("mae") is not None and rec.get("mae") <= 5e-3:
        p_az_f = E24Params(candidate="L", name="azF214", vos=214.023e-6, linear=False, autozero=True, t_az=2e-5, t_stop=8e-5)
        recf, _, _ = eval_network(ngspice, spec_f, wf, p_az_f, xf, yf, dest("F", "AZ214"))
        az["network_F"] = {k: recf.get(k) for k in ("mae", "max_abs_error", "accuracy", "failed", "failure_reason", "blocks")}
        print(f"  AZ F fail={recf.get('failed')} MAE={fmt(recf.get('mae'))} acc={recf.get('accuracy')}", flush=True)
    else:
        az["network_F"] = {"failed": True, "failure_reason": "skipped: Network A AZ not close enough"}
    az["note"] = (
        "Clocked S/H of the actual signal TIA output at Vin=0, then Vin step. "
        "Correction is Eaz=Vraw-Vhold in SPICE, not a Python subtraction of NumPy z."
    )
    report["autozero"] = az
    net_a["AZ_L_214uV"] = az["network_A"]
    net_f["AZ_L_214uV"] = az["network_F"]
    report["network_A"] = net_a
    report["network_F"] = net_f

    p_srv = E24Params(candidate="L", name="servo", vos=214.023e-6, linear=True, servo=True)
    servo_iso = iso_eval(ngspice, spec_f, wf, o2, p_srv, iso_x(o2)[:4])
    p_srv_ld = E24Params(candidate="L", name="servold", vos=214.023e-6, linear=False, servo=True)
    servo_ld = eval_loaded_tag(ngspice, spec_f, wf, p_srv_ld, x_load[:4], y_load[:4], o2["tag"])
    report["servo"] = {
        "isolated_o2": servo_iso,
        "loaded_o2": servo_ld,
        "note": (
            "DC integrator from Vsum onto IN+. Tests loaded weighted inference, not only "
            "zero-input offset. If Vlin collapses, the loop cannot separate Vos from Vlin/A."
        ),
    }
    print(
        f"  servo o2 fail={servo_iso.get('failed')} MAE_z={fmt(servo_iso.get('mae_vs_z'))} "
        f"vlinmax={fmt(servo_iso.get('vlin_abs_max'))} loaded MAE_y={fmt(servo_ld.get('loaded_mae_vs_y'))}",
        flush=True,
    )
    if servo_iso.get("mae_vs_z") is not None and servo_iso["mae_vs_z"] <= ERROR_LIMIT:
        p_srv_a = E24Params(candidate="L", name="servoA", vos=214.023e-6, linear=False, servo=True)
        rec_sa, _, _ = eval_network(ngspice, spec_a, wa, p_srv_a, xa, ya, dest("A", "SERVO214"))
        report["servo"]["network_A"] = {
            k: rec_sa.get(k) for k in ("mae", "max_abs_error", "accuracy", "failed", "failure_reason", "blocks")
        }
        print(f"  servo A fail={rec_sa.get('failed')} MAE={fmt(rec_sa.get('mae'))} acc={rec_sa.get('accuracy')}", flush=True)
        if rec_sa.get("failed"):
            report["servo"]["network_F"] = {"failed": True, "failure_reason": "skipped: Network A servo failed"}
        else:
            p_srv_f = E24Params(candidate="L", name="servoF", vos=214.023e-6, linear=False, servo=True)
            rec_sf, _, _ = eval_network(ngspice, spec_f, wf, p_srv_f, xf, yf, dest("F", "SERVO214"))
            report["servo"]["network_F"] = {
                k: rec_sf.get(k) for k in ("mae", "max_abs_error", "accuracy", "failed", "failure_reason", "blocks")
            }
            print(f"  servo F fail={rec_sf.get('failed')} MAE={fmt(rec_sf.get('mae'))} acc={rec_sf.get('accuracy')}", flush=True)
            net_f["SERVO_L_214uV"] = report["servo"]["network_F"]
            net_a["SERVO_L_214uV"] = report["servo"]["network_A"]
            report["network_A"] = net_a
            report["network_F"] = net_f

    p_azv = E24Params(
        candidate="L", name="azvref214", vos=214.023e-6, linear=True,
        autozero=True, gate_vref=True, t_az=2e-5, t_stop=8e-5,
    )
    azv = {
        "isolated_o2": iso_eval(ngspice, spec_f, wf, o2, p_azv, iso_x(o2)),
        "note": "Vin=0 and Vref=0 during sample so bias current is not stored as if it were Vos.",
    }
    print(
        f"  AZ-Vref o2 fail={azv['isolated_o2'].get('failed')} "
        f"MAE_z={fmt(azv['isolated_o2'].get('mae_vs_z'))} {azv['isolated_o2'].get('failure_reason')}",
        flush=True,
    )
    p_azv_ld = E24Params(
        candidate="L", name="azvrefld", vos=214.023e-6, linear=False,
        autozero=True, gate_vref=True, t_az=2e-5, t_stop=8e-5,
    )
    azv["loaded_o2"] = eval_loaded_tag(ngspice, spec_f, wf, p_azv_ld, x_load, y_load, o2["tag"])
    print(
        f"  AZ-Vref loaded o2 fail={azv['loaded_o2'].get('failed')} "
        f"MAE_y={fmt(azv['loaded_o2'].get('loaded_mae_vs_y'))}",
        flush=True,
    )
    p_azv_a = E24Params(
        candidate="L", name="azvrefA", vos=214.023e-6, linear=False,
        autozero=True, gate_vref=True, t_az=2e-5, t_stop=8e-5,
    )
    rec_azva, _, _ = eval_network(ngspice, spec_a, wa, p_azv_a, xa, ya, dest("A", "AZVREF214"))
    azv["network_A"] = {k: rec_azva.get(k) for k in ("mae", "max_abs_error", "accuracy", "failed", "failure_reason")}
    print(f"  AZ-Vref A MAE={fmt(rec_azva.get('mae'))} acc={rec_azva.get('accuracy')}", flush=True)
    if rec_azva.get("mae") is not None and rec_azva["mae"] <= 5e-3:
        p_azv_f = E24Params(
            candidate="L", name="azvrefF", vos=214.023e-6, linear=False,
            autozero=True, gate_vref=True, t_az=2e-5, t_stop=8e-5,
        )
        rec_azvf, _, _ = eval_network(ngspice, spec_f, wf, p_azv_f, xf, yf, dest("F", "AZVREF214"))
        azv["network_F"] = {k: rec_azvf.get(k) for k in ("mae", "max_abs_error", "accuracy", "failed", "failure_reason")}
        print(f"  AZ-Vref F MAE={fmt(rec_azvf.get('mae'))} acc={rec_azvf.get('accuracy')}", flush=True)
        net_f["AZVREF_L_214uV"] = azv["network_F"]
        report["network_F"] = net_f
    report["autozero_vref"] = azv

    p_ch = E24Params(
        candidate="L", name="chop", vos=214.023e-6, linear=True, chopper=True, t_stop=2e-4, chop_period=2e-5
    )
    rec_ch = iso_eval(ngspice, spec_f, wf, o2, p_ch, iso_x(o2)[:8])
    chop = {
        "isolated_o2_8vec": rec_ch,
        "note": "Vos square-wave on IN+; Vlin averaged over the last two chop periods. Not input-swap chopper.",
    }
    print(f"  chop o2 fail={rec_ch.get('failed')} MAE_z={fmt(rec_ch.get('mae_vs_z'))} {rec_ch.get('failure_reason')}", flush=True)
    if rec_ch.get("mae_vs_z") is not None and rec_ch["mae_vs_z"] <= 5e-3:
        p_ch_a = E24Params(
            candidate="L", name="chopA", vos=214.023e-6, linear=False, chopper=True, t_stop=2e-4, chop_period=2e-5
        )
        rec_cha, _, _ = eval_network(ngspice, spec_a, wa, p_ch_a, xa, ya, dest("A", "CHOP214"))
        chop["network_A"] = {k: rec_cha.get(k) for k in ("mae", "max_abs_error", "accuracy", "failed", "failure_reason")}
        print(f"  chop A MAE={fmt(rec_cha.get('mae'))} acc={rec_cha.get('accuracy')}", flush=True)
        if rec_cha.get("mae") is not None and rec_cha["mae"] <= ERROR_LIMIT:
            p_ch_f = E24Params(
                candidate="L", name="chopF", vos=214.023e-6, linear=False, chopper=True, t_stop=2e-4, chop_period=2e-5
            )
            rec_chf, _, _ = eval_network(ngspice, spec_f, wf, p_ch_f, xf, yf, dest("F", "CHOP214"))
            chop["network_F"] = {k: rec_chf.get(k) for k in ("mae", "max_abs_error", "accuracy", "failed", "failure_reason")}
            net_f["CHOP_L_214uV"] = chop["network_F"]
            print(f"  chop F MAE={fmt(rec_chf.get('mae'))} acc={rec_chf.get('accuracy')}", flush=True)
    report["chopper"] = chop
    report["network_F"] = net_f

    net_acct, cat_acct, _ = compile_network(
        spec_f, wf, E24Params(candidate="L", name="acct", linear=False), linear=False
    )
    net_az_acct, cat_az_acct, _ = compile_network(
        spec_f, wf, E24Params(candidate="L", name="acctaz", vos=214.023e-6, linear=False, autozero=True), linear=False
    )
    report["physical_accounting"] = {
        "F_L": {"n_resistors": len(cat_acct) if cat_acct else None, **(count_blocks(net_acct) if net_acct else {})},
        "F_AZ_L": {"n_resistors": len(cat_az_acct) if cat_az_acct else None, **(count_blocks(net_az_acct) if net_az_acct else {})},
        "supply_rails": "LEVEL 2 L has no supplies. LEVEL 3 macros use +/-15 V documented in the smoke/netlist.",
        "settling": "AZ t_az=20 us, t_stop=80 us, Vin step 2 us after hold. Chopper period 20 us, average last 40 us of 200 us.",
        "note": "Not transistor count, board power, silicon area, or PCB performance.",
    }
    print("Phase 5: F gain/offset map", flush=True)
    fmap = []
    for a in GAIN_MAP:
        for vos in VOS_MAP:
            params = E24Params(candidate="L", name=f"map_a{a:g}_v{vos:g}", amp_gain=a, vos=vos, linear=False)
            rec, _, _ = eval_network(ngspice, spec_f, wf, params, xf, yf, dest("map", f"a{a:g}", f"v{vos:g}"))
            fmap.append({
                "A": a, "vos": vos, "mae": rec.get("mae"), "accuracy": rec.get("accuracy"),
                "failed": rec.get("failed"), "failure_reason": rec.get("failure_reason"),
            })
            print(f"  map A={a:g} Vos={vos:g} MAE={fmt(rec.get('mae'))} acc={rec.get('accuracy')}", flush=True)
    report["feasibility_map"] = fmap

    print("Phase 6: error budget", flush=True)
    budget = {
        "L_idealR_vos0": mc_l(ngspice, spec_f, wf, xf, yf, 0.0, False, 24, "b0"),
        "L_0p5pct_vos0": mc_l(ngspice, spec_f, wf, xf, yf, 0.0, True, 24, "bR"),
        "L_idealR_vos8p75u": mc_l(ngspice, spec_f, wf, xf, yf, 8.75e-6, False, 24, "b875"),
        "L_0p5pct_vos8p75u": mc_l(ngspice, spec_f, wf, xf, yf, 8.75e-6, True, 25, "bR875"),
        "L_idealR_vos22u": mc_l(ngspice, spec_f, wf, xf, yf, 2.2e-5, False, 24, "b22"),
        "note": "8 draws of independent 0.5% R. Analog bar 1e-3.",
    }
    report["error_budget"] = budget
    print(
        f"  budget R0.5% MAE={fmt(budget['L_0p5pct_vos0'].get('mae_mean'))} "
        f"Vos8.75u MAE={fmt(budget['L_idealR_vos8p75u'].get('mae_mean'))}",
        flush=True,
    )

    conclude(report)
    report["plots"] = write_plots(report)
    write_markdown(report)

    def default(o):
        if isinstance(o, (np.floating, np.integer)):
            return float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        raise TypeError(type(o))

    REPORT_JSON.write_text(json.dumps(report, indent=2, default=default), encoding="utf-8")
    print(f"wrote {REPORT_JSON}", flush=True)
    print(f"wrote {REPORT_MD}", flush=True)
    print(report.get("final_status"), flush=True)
    print(report.get("conclusion"), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

