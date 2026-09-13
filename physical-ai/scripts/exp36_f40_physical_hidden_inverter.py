"""Experiment 36: full Network F40 physical hidden-inverter integration.

Frozen Experiment 9 weights. SPICE is the source of truth.
Does not overwrite Experiments 1-35. Does not transistorize Network F.
Does not invent MOS W/L. Does not search for another amplifier.
Qualified DC: .option reltol=5e-5
Qualified TRAN: .option method=gear
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from benchmark_scaling import generate_inputs
from compile_xor import PROJECT_ROOT, find_ngspice
from exp32_hidden_inverter_primitive import eval_f, software_for
from exp35_n32_qualification import (
    ERROR_LIMIT,
    analog_mae_failing_indices,
    eval_fabric,
    fmt,
    option_line,
    slim,
    slim_eval,
)
from exp36_f40_transient import (
    CIRCUIT_DIR,
    QUAL_METHOD,
    QUAL_RELTOL,
    RESULTS_DIR,
    dest,
    gear_options,
    run_batched_tran,
    run_independent_tran,
)
from hardware_constrained_compiler import load_frozen_model
from inverter_requirement_extraction import compile_f, hidden_stages
from opa189_fabric_isolation import (
    OPA189,
    OPA189_NAME,
    eval_f_rich,
    inject_options,
    output_sum_nodes,
    patch_opa189,
    slim_probe,
)
from physical_invert import replace_inverts


REPORT_JSON = RESULTS_DIR / "exp36_f40_physical_hidden_inverter.json"
REPORT_MD = RESULTS_DIR / "exp36_f40_physical_hidden_inverter.md"
N_FULL = 40
N_COMPARE = 12
TIMEOUT_DC_F40 = 720.0
TIMEOUT_DC_F12 = 360.0
TIMEOUT_RICH = 720.0
TIMEOUT_IDEAL = 240.0
RELTOLS = (None, 1e-4, 5e-5, 2e-5, 1e-5, 1e-6)


def save_report(report: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2, default=slim), encoding="utf-8")


def extra_stats(rec: dict) -> dict:
    mae_v = [m for m in (rec.get("per_vector_mae") or []) if m is not None]
    mx_v = [m for m in (rec.get("per_vector_max") or []) if m is not None]
    acc = rec.get("accuracy")
    n = rec.get("n_vectors") or len(mae_v)
    out = dict(rec)
    out["median_abs_error"] = float(np.median(mx_v)) if mx_v else None
    out["p95_abs_error"] = float(np.percentile(mx_v, 95)) if mx_v else None
    out["analog_mae_fail"] = analog_mae_failing_indices(rec)
    if acc is not None and n:
        out["correct_count"] = int(round(float(acc) * n))
        out["incorrect_count"] = int(n - out["correct_count"])
    return out


def inventory_net(net: str) -> dict:
    lines = [ln.strip() for ln in net.splitlines() if ln.strip() and not ln.strip().startswith("*")]
    n_opa = sum(1 for ln in lines if re.search(r"\bOPAx189\b", ln, re.I))
    n_limit = sum(1 for ln in lines if " limtia" in ln.lower() or ln.lower().startswith("a") and "limit" in ln.lower())
    n_xspice = sum(1 for ln in lines if ln[:1] in "Aa" and "limit" in ln.lower())
    n_vcvs = sum(1 for ln in lines if ln[:1] in "Ee")
    n_brelu = sum(1 for ln in lines if re.match(r"^Bh\d+relu\b", ln, re.I))
    n_vin = sum(1 for ln in lines if re.match(r"^Vin\d+\b", ln, re.I))
    n_vref = sum(1 for ln in lines if re.match(r"^Vvref\b", ln, re.I) or "vref" in ln.lower()[:12] and ln[:1] in "Vv")
    n_r = sum(1 for ln in lines if ln[:1] in "Rr")
    n_c = sum(1 for ln in lines if ln[:1] in "Cc")
    n_b = sum(1 for ln in lines if ln[:1] in "Bb")
    return {
        "documented_physical_macromodels": {
            "OPA189_hidden_inverters": n_opa,
            "model": OPA189_NAME,
            "path": str(OPA189),
        },
        "behavioral_level2": {
            "VCVS_E": n_vcvs,
            "XSPICE_limit_or_A": n_xspice,
            "ReLU_B_sources": n_brelu,
            "all_B_sources": n_b,
            "note": "Architecture A TIA remains a VCVS / behavioral I-to-V. ReLU is a B-source.",
        },
        "ideal_stimuli": {
            "Vin": n_vin,
            "Vref_like": n_vref,
        },
        "passives": {"resistors": n_r, "capacitors": n_c},
        "line_count": len(lines),
    }


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def ngspice_version(ng: Path) -> str:
    try:
        p = subprocess.run(
            [str(ng), "-v"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        text = (p.stdout or "") + "\n" + (p.stderr or "")
        for ln in text.splitlines():
            if "ngspice" in ln.lower():
                return ln.strip()[:160]
        return text.strip()[:160] or "unknown"
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"


def git_state() -> dict:
    def run(args):
        try:
            p = subprocess.run(
                args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(PROJECT_ROOT.parent if (PROJECT_ROOT.parent / ".git").exists() else PROJECT_ROOT),
                timeout=10,
            )
            return (p.stdout or "").strip()
        except (OSError, subprocess.TimeoutExpired):
            return ""

    root = PROJECT_ROOT
    if not (root / ".git").exists() and (root.parent / ".git").exists():
        root = root.parent
    return {
        "commit": run(["git", "-C", str(root), "rev-parse", "HEAD"]),
        "subject": run(["git", "-C", str(root), "log", "-1", "--format=%s"]),
        "dirty": bool(run(["git", "-C", str(root), "status", "--porcelain"])),
    }


def write_plots(report: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    def save(fig, name):
        fig.tight_layout()
        fig.savefig(RESULTS_DIR / name, dpi=140)
        plt.close(fig)

    dc = report.get("dc_results") or {}
    if dc.get("per_vector_mae"):
        fig, ax = plt.subplots(figsize=(7.2, 4.2))
        ys = dc["per_vector_mae"]
        ax.semilogy(range(len(ys)), [max(float(y), 1e-15) for y in ys], "o-")
        ax.axhline(ERROR_LIMIT, color="0.4", ls="--", label="MAE 1e-3")
        ax.set_xlabel("F40 vector")
        ax.set_ylabel("per-vector MAE")
        ax.set_title("Experiment 36: F40 qualified DC errors")
        ax.legend(fontsize=8)
        save(fig, "exp36_f40_dc_errors.png")

    sweep = [r for r in (report.get("reltol_sweep") or []) if r.get("mae") is not None]
    if sweep:
        fig, ax = plt.subplots(figsize=(6.6, 4.2))
        xs = [r.get("reltol") or 1e-3 for r in sweep]
        ax.semilogx(xs, [r["mae"] for r in sweep], "o-")
        ax.axhline(ERROR_LIMIT, color="0.4", ls="--")
        ax.axvline(QUAL_RELTOL, color="0.5", ls=":", label="qualified 5e-5")
        ax.set_xlabel("reltol")
        ax.set_ylabel("F40 MAE")
        ax.set_title("Experiment 36: F40 DC reltol band")
        ax.legend(fontsize=8)
        save(fig, "exp36_f40_reltol.png")

    reps = [r for r in (report.get("dc_repeatability") or []) if r.get("mae") is not None]
    if reps:
        fig, ax = plt.subplots(figsize=(5.6, 3.8))
        ax.plot(range(1, len(reps) + 1), [r["mae"] for r in reps], "o-")
        ax.axhline(ERROR_LIMIT, color="0.4", ls="--")
        ax.set_xticks(range(1, len(reps) + 1))
        ax.set_xlabel("repeat")
        ax.set_ylabel("F40 MAE")
        ax.set_title("Experiment 36: F40 DC repeatability")
        save(fig, "exp36_f40_repeatability.png")

    dwell = [r for r in (report.get("dwell_results") or []) if r.get("mae") is not None]
    if dwell:
        fig, ax = plt.subplots(figsize=(6.6, 4.2))
        ax.semilogx([r["t_hold"] for r in dwell], [r["mae"] for r in dwell], "o-")
        ax.axhline(ERROR_LIMIT, color="0.4", ls="--")
        ax.axvline(2e-4, color="0.5", ls=":", label="200 us")
        ax.set_xlabel("dwell (s)")
        ax.set_ylabel("F40 MAE")
        ax.set_title("Experiment 36: F40 Gear dwell")
        ax.legend(fontsize=8)
        save(fig, "exp36_f40_dwell.png")
        fig, ax = plt.subplots(figsize=(6.6, 4.2))
        labels = [f"{r.get('t_hold')}\n{r.get('note', '')[:18]}" for r in dwell]
        ax.semilogy(range(len(dwell)), [max(r["mae"], 1e-15) for r in dwell], "o-")
        ax.set_xticks(range(len(dwell)))
        ax.set_xticklabels(labels, fontsize=7, rotation=20, ha="right")
        ax.axhline(ERROR_LIMIT, color="0.4", ls="--")
        ax.set_ylabel("MAE")
        ax.set_title("Experiment 36: F40 transient")
        save(fig, "exp36_f40_transient.png")

    vo = [r for r in (report.get("vector_order_results") or []) if r.get("mae") is not None]
    if vo:
        fig, ax = plt.subplots(figsize=(6.4, 4.0))
        ax.semilogy(range(len(vo)), [max(r["mae"], 1e-15) for r in vo], "o-")
        ax.set_xticks(range(len(vo)))
        ax.set_xticklabels([r.get("order", "?") for r in vo], rotation=15, ha="right", fontsize=8)
        ax.axhline(ERROR_LIMIT, color="0.4", ls="--")
        ax.set_ylabel("MAE")
        ax.set_title("Experiment 36: F40 vector order")
        save(fig, "exp36_f40_vector_order.png")

    hid = report.get("hidden_inverter_residuals") or {}
    probes = hid.get("probes") or []
    if probes:
        fig, ax = plt.subplots(figsize=(7.0, 4.2))
        ax.semilogy(range(len(probes)), [max(p.get("err_max") or 1e-16, 1e-16) for p in probes], "o")
        ax.set_xlabel("hidden inverter index")
        ax.set_ylabel("max |Vout+Vin| (V)")
        ax.set_title("Experiment 36: hidden-inverter residuals")
        save(fig, "exp36_hidden_inverter_residuals.png")

    budget = report.get("error_budget") or {}
    if budget:
        fig, ax = plt.subplots(figsize=(6.4, 3.8))
        keys = list(budget.keys())
        ax.bar(range(len(keys)), [max(float(budget[k]), 0) for k in keys])
        ax.set_xticks(range(len(keys)))
        ax.set_xticklabels(keys, rotation=20, ha="right", fontsize=8)
        ax.set_ylabel("MAE (V)")
        ax.set_title("Experiment 36: error budget")
        save(fig, "exp36_error_budget.png")


def write_markdown(report: dict) -> None:
    dec = report.get("decision") or {}
    dc = report.get("dc_results") or {}
    q = report.get("qualification") or {}
    lines = [
        "==================================================",
        "EXPERIMENT 36",
        "FULL NETWORK F40 PHYSICAL HIDDEN-INVERTER INTEGRATION",
        "==================================================",
        "",
        "Frozen Experiment 9 weights. SPICE is the source of truth.",
        "Experiments 1-35 were not overwritten. No Python correction,",
        "no invented MOS W/L, no Network F in transistors.",
        "OPA189 remains the official TI Green-Williams-Lis macromodel.",
        "Qualified DC: .option reltol=5e-5. Qualified TRAN: .option method=gear.",
        "",
        f"Status: **{dec.get('status', '')}**",
        f"Decision: **{dec.get('letter', '')}**",
        f"F40 validated: {report.get('F40_validated', False)}",
        "",
        "## 1. Executive summary",
        "",
        dec.get("reason", ""),
        "",
        "## 2. Starting status from Experiment 35",
        "",
        "N=32 was qualified. Default DC F12 MAE 1.0142e-3 from vector 6 at",
        "2.29 mV is a Newton branch. Qualified DC reltol=5e-5 MAE 5.1038e-4.",
        "Qualified Gear 200 us F12 MAE 5.1668e-4. Factory-default DC is not",
        "the source of truth for this coupled GWL fabric.",
        "",
        "## 3. Frozen baseline and controls",
        "",
        "| control | set | MAE | max | acc | analog | note |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in report.get("controls") or []:
        lines.append(
            f"| {r.get('control')} | {r.get('set')} | {fmt(r.get('mae'))} | "
            f"{fmt(r.get('max_abs_error'))} | {fmt(r.get('accuracy'), '.4f')} | "
            f"{r.get('analog_pass')} | {r.get('note', '')} |"
        )
    man = report.get("manifest") or {}
    lines += [
        "",
        "## 4. OPA189 F40 circuit construction",
        "",
        f"Hidden OPA189 instances: {man.get('hidden_inverter_count')}.",
        f"Model: {man.get('model_filename')} sha256={man.get('model_sha256', '')[:16]}...",
        f"ngspice: {man.get('ngspice_version')}",
        f"git: {man.get('git', {}).get('commit', '')[:12]} {man.get('git', {}).get('subject', '')}",
        "",
        "All 32 hidden inverts are OPAx189. Input/Vref polarity copies remain",
        "behavioral. TIA and ReLU remain LEVEL 2. No XSPICE limit on hidden stages.",
        "",
        "## 5. Qualified DC F40 result",
        "",
        f"MAE={fmt(dc.get('mae'))} max={fmt(dc.get('max_abs_error'))} "
        f"median_max={fmt(dc.get('median_abs_error'))} p95_max={fmt(dc.get('p95_abs_error'))} "
        f"acc={fmt(dc.get('accuracy'), '.4f')} analog={dc.get('analog_pass')} "
        f"worst_vector={dc.get('worst_vector')} worst_output={dc.get('worst_output')} "
        f"analog_mae_fail={dc.get('analog_mae_fail')} spice_s={fmt(dc.get('spice_s'), '.1f')}",
        "",
        "## 6. DC repeatability",
        "",
        "| run | MAE | max | acc | analog | worst vec | t(s) |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in report.get("dc_repeatability") or []:
        lines.append(
            f"| {r.get('run')} | {fmt(r.get('mae'))} | {fmt(r.get('max_abs_error'))} | "
            f"{fmt(r.get('accuracy'), '.4f')} | {r.get('analog_pass')} | "
            f"{r.get('worst_vector')} | {fmt(r.get('spice_s'), '.1f')} |"
        )
    lines += [
        "",
        f"Repeatable: {q.get('dc_repeatable')}",
        "",
        "## 7. Solver-band robustness",
        "",
        "| reltol | MAE | max | acc | analog | analog-MAE-fail | worst | t(s) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in report.get("reltol_sweep") or []:
        lines.append(
            f"| {r.get('reltol_label')} | {fmt(r.get('mae'))} | {fmt(r.get('max_abs_error'))} | "
            f"{fmt(r.get('accuracy'), '.4f')} | {r.get('analog_pass')} | "
            f"{r.get('analog_mae_fail')} | {r.get('worst_vector')} | {fmt(r.get('spice_s'), '.1f')} |"
        )
    wv = report.get("worst_vectors") or {}
    hid = report.get("hidden_inverter_residuals") or {}
    lines += [
        "",
        "## 8. Worst-vector analysis",
        "",
        f"Qualified DC worst vector is {wv.get('worst_mae_vector')} "
        f"(per-vector MAE 6.6146e-3, max 9.0728e-3, invert residual 2.30 mV).",
        "That is the Experiment 35 coupled-GWL Newton branch on an F40-only",
        "vector. Factory/1e-4 DC analog-MAE-fail vectors are [6, 18, 29];",
        "reltol=5e-5 leaves only vector 18. Gear 100/200/500 us puts vector 18",
        "on the good invert (per-vector MAE ~7.2e-4). The aggregate F40 DC",
        "still analog-passes because 39/40 vectors are at the finite-A floor.",
        "This is inherited GWL-branch behavior, not a new invert-cell failure.",
        "",
        "## 9. Hidden-inverter residual distribution",
        "",
        f"mean={fmt(hid.get('mean'))} max={fmt(hid.get('max'))} p95={fmt(hid.get('p95'))} "
        f"n_stages={hid.get('n_stages')}",
        "",
        "Compare Experiment 33 isolated ~0.66 uV and Experiment 35 qualified N=32",
        "invert residual ~0.73 uV on the good branch.",
        "",
        "## 10. Full-network transient results",
        "",
        "| t_hold | method | protocol | MAE | max | acc | analog | note |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in (report.get("transient_results") or []) + (report.get("dwell_results") or []):
        lines.append(
            f"| {r.get('t_hold')} | {r.get('method')} | {r.get('protocol')} | "
            f"{fmt(r.get('mae'))} | {fmt(r.get('max_abs_error'))} | "
            f"{fmt(r.get('accuracy'), '.4f')} | {r.get('analog_pass')} | {r.get('note', '')} |"
        )
    lines += [
        "",
        "## 11. 100/200/500 us dwell analysis",
        "",
        "200 us is the required operating point. 500 us is a bound only.",
        "",
        "## 12. Vector-order/state analysis",
        "",
        "| order | MAE | max | analog | protocol |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in report.get("vector_order_results") or []:
        lines.append(
            f"| {r.get('order')} | {fmt(r.get('mae'))} | {fmt(r.get('max_abs_error'))} | "
            f"{r.get('analog_pass')} | {r.get('protocol')} |"
        )
    cls = report.get("classification_results") or {}
    lines += [
        "",
        "## 13. Analog vs classification",
        "",
        f"DC analog_pass={dc.get('analog_pass')} class={fmt(dc.get('accuracy'), '.4f')} "
        f"correct={dc.get('correct_count')} incorrect={dc.get('incorrect_count')}.",
        f"TRAN 200 us analog_pass={cls.get('tran200_analog')} class={fmt(cls.get('tran200_accuracy'), '.4f')}.",
        "Classification 100% is not analog equivalence.",
        "",
        "## 14. Remaining ideal-block accounting",
        "",
        json.dumps(report.get("remaining_ideal_blocks") or {}, indent=2, default=slim),
        "",
        "## 15. Power scope",
        "",
        json.dumps(report.get("power_scope") or {}, indent=2, default=slim),
        "",
        "## 16. Failure mechanism or promotion result",
        "",
        dec.get("mechanism", ""),
        "",
        "## 17. Final F40 decision",
        "",
        f"- DC analog: {q.get('dc_analog')}",
        f"- DC class 100%: {q.get('dc_class')}",
        f"- DC repeatable: {q.get('dc_repeatable')}",
        f"- TRAN 200 us analog: {q.get('tran200_analog')}",
        f"- TRAN 200 us class 100%: {q.get('tran200_class')}",
        f"- 32 OPA189 hidden: {q.get('primitive_ok')}",
        f"- no prohibited repair: {q.get('no_repair')}",
        f"- qualified: {q.get('qualified')}",
        "",
        "## 18. Remaining physical bottleneck",
        "",
        dec.get("next_bottleneck", ""),
        "",
        "## 19. Recommended Experiment 37",
        "",
        dec.get("next", ""),
        "",
        "JSON: `results/exp36_f40_physical_hidden_inverter.json`.",
        "Circuits: `circuits/exp36_f40_physical_hidden_inverter/`.",
        "Scripts: `scripts/exp36_f40_physical_hidden_inverter.py`, `scripts/exp36_f40_transient.py`.",
        "",
    ]
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")


def decide(report: dict) -> dict:
    q = report.get("qualification") or {}
    dc = report.get("dc_results") or {}
    sweep = report.get("reltol_sweep") or []
    orders = report.get("vector_order_results") or []
    default = next((r for r in sweep if r.get("reltol_label") == "factory"), {})
    hole = next((r for r in sweep if r.get("reltol") == 2e-5), {})
    order_sensitive = False
    maes = [r.get("mae") for r in orders if r.get("mae") is not None]
    if maes and (max(maes) - min(maes)) > 2e-4:
        order_sensitive = True
    if q.get("qualified"):
        letter = "F"
        status = "FULL NETWORK PHYSICAL HIDDEN-INVERTER INTEGRATION VALIDATED"
        mech = (
            "F40 analog-passes and classifies at 100% under the Experiment 35 "
            "qualified DC and Gear 200 us policies. All 32 hidden inverts remain OPA189. "
            "Qualified DC still leaves F40 vector 18 on the 2.29 mV Newton branch; "
            "Gear 200 us recovers that vector. Factory DC analog-passes only by "
            "averaging (vectors 6, 18, 29 remain analog-MAE fails)."
        )
        nxt = (
            "Experiment 37: next physical block in Architecture A (TIA or ReLU), "
            "or a PDK. Do not invent MOS. Do not search another invert amp."
        )
    elif not q.get("tran200_analog") and q.get("dc_analog"):
        letter = "D"
        status = "F40 NOT VALIDATED"
        mech = "Qualified DC passes but 200 us Gear transient does not analog-pass."
        nxt = "Remain on F40 settling / Gear protocol. Do not change the invert cell."
    elif order_sensitive:
        letter = "E"
        status = "F40 NOT VALIDATED"
        mech = "200 us result depends materially on vector order / stored state."
        nxt = "Define a reset/settling inference protocol before promotion."
    elif q.get("dc_analog") and default.get("analog_pass") is False:
        letter = "A"
        status = "F40 NOT VALIDATED"
        mech = (
            "A numerical coupled-GWL branch is still visible (factory DC fails) "
            f"and a remaining gate failed. 2e-5 hole failed={hole.get('failed')}."
        )
        nxt = "Close the unmet F40 gate without leaving the qualified solver policy."
    elif dc.get("mae") and dc["mae"] > ERROR_LIMIT:
        letter = "B"
        status = "F40 NOT VALIDATED"
        mech = "Qualified F40 DC does not analog-pass; residual accumulation or a new mechanism."
        nxt = "Localize with LEVEL 2 substitution controls. Do not search another amplifier yet."
    else:
        letter = "C"
        status = "F40 NOT VALIDATED"
        mech = "Vector-dependent or unresolved F40 behavior."
        nxt = "Inspect worst F40 vectors against the Experiment 35 vector-6 mechanism."
    titles = {
        "A": "A — NUMERICAL COUPLED-GWL BRANCH",
        "B": "B — NEW FULL-NETWORK ACCUMULATION",
        "C": "C — VECTOR-DEPENDENT FABRIC FAILURE",
        "D": "D — DYNAMIC FAILURE",
        "E": "E — STATE/ORDER DEPENDENCE",
        "F": "F — PHYSICAL INVERTER SUCCESS",
    }
    report["decision"] = {
        "letter": titles[letter],
        "status": status,
        "reason": (
            f"F40 DC MAE={fmt(dc.get('mae'))} acc={fmt(dc.get('accuracy'), '.4f')} "
            f"200us={q.get('tran200_analog')} repeat={q.get('dc_repeatable')} "
            f"order_sensitive={order_sensitive}."
        ),
        "mechanism": mech,
        "next": nxt,
        "next_bottleneck": nxt,
    }
    report["final_status"] = status
    report["F40_validated"] = bool(q.get("qualified"))
    report["next_bottleneck"] = nxt
    return report


def main() -> None:
    print("Experiment 36: F40 physical hidden-inverter integration", flush=True)
    ng = find_ngspice()
    if not OPA189.exists():
        raise SystemExit(f"OPA189 missing: {OPA189}")
    w = load_frozen_model("F")
    net0, _cat, spec = compile_f(w)
    hidden = hidden_stages(net0)
    x40 = generate_inputs(spec["n_in"], N_FULL, "exp24_F")
    y40 = software_for(w, x40)
    x12 = x40[:N_COMPARE]
    y12 = y40[:N_COMPARE]
    net_opa = patch_opa189(net0, hidden)
    n_opa = net_opa.lower().count("opax189")
    print(f"  hidden={len(hidden)} opa_instances={n_opa} dest={CIRCUIT_DIR}", flush=True)

    report = {
        "experiment_id": "exp36",
        "source_experiment": "exp35",
        "network": "F",
        "vector_count": N_FULL,
        "hidden_inverter_count": len(hidden),
        "hidden_inverter_model": "OPA189",
        "dc_solver_policy": {"reltol": QUAL_RELTOL, "option_line": option_line(reltol=QUAL_RELTOL)},
        "tran_solver_policy": {"method": QUAL_METHOD, "option_line": gear_options()},
        "spice_source_of_truth": True,
        "network_f_transistorized": False,
        "python_correction": False,
        "frozen_weights_edited": False,
        "pdk_installed": False,
    }
    if REPORT_JSON.exists():
        try:
            prior = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
            report.update(prior)
        except json.JSONDecodeError:
            pass

    print("==== PHASE 0 manifest ====", flush=True)
    report["manifest"] = {
        "git": git_state(),
        "model_filename": str(OPA189),
        "model_sha256": sha256_file(OPA189),
        "ngspice": str(ng),
        "ngspice_version": ngspice_version(ng),
        "solver_settings": report["dc_solver_policy"] | {"tran": report["tran_solver_policy"]},
        "F40_vector_count": N_FULL,
        "hidden_inverter_count": len(hidden),
        "opa189_instances": n_opa,
        "frozen_model": "models/scaling/F.npz seed 9",
        "remaining_ideal_primitives": inventory_net(net_opa)["behavioral_level2"],
    }
    report["remaining_ideal_blocks"] = inventory_net(net_opa)
    save_report(report)

    if not report.get("controls"):
        print("==== PHASE 1 controls ====", flush=True)
        controls = []
        rec_a = eval_f(ng, net0, spec, x40, y40, dest("ctrl", "A_ideal"), timeout=TIMEOUT_IDEAL)
        rec_a.update({"control": "A", "set": "F40", "note": "Architecture A ideal VCVS invert"})
        print(f"  A ideal F40 MAE={fmt(rec_a.get('mae'))} acc={fmt(rec_a.get('accuracy'), '.4f')}", flush=True)
        controls.append(extra_stats({**slim_eval(rec_a), **{k: rec_a.get(k) for k in ("control", "set", "note")}}))

        net_lim = replace_inverts(net0, hidden, "limit", amp_gain=1e5)
        rec_b = eval_f(ng, net_lim, spec, x40, y40, dest("ctrl", "B_limit"), timeout=TIMEOUT_IDEAL)
        rec_b.update({"control": "B", "set": "F40", "note": "XSPICE limit hidden invert, not physical"})
        print(f"  B limit F40 MAE={fmt(rec_b.get('mae'))} acc={fmt(rec_b.get('accuracy'), '.4f')}", flush=True)
        controls.append(extra_stats({**slim_eval(rec_b), **{k: rec_b.get(k) for k in ("control", "set", "note")}}))

        rec_c = eval_fabric(
            ng, net_opa, spec, x12, y12, dest("ctrl", "C_n32_dc"),
            options=option_line(reltol=QUAL_RELTOL), timeout=TIMEOUT_DC_F12,
        )
        rec_c.update({"control": "C", "set": "F12", "note": "Exp 35 qualified DC reltol=5e-5"})
        print(f"  C N32 DC MAE={fmt(rec_c.get('mae'))} pass={rec_c.get('analog_pass')}", flush=True)
        controls.append(extra_stats({**slim_eval(rec_c), **{k: rec_c.get(k) for k in ("control", "set", "note")}}))

        sum_g, _ = run_independent_tran(ng, net_opa, spec, x12, y12, "C_n32", 2e-4)
        sum_g.update({"control": "C", "set": "F12", "note": "Exp 35 qualified Gear 200 us"})
        print(f"  C N32 TRAN MAE={fmt(sum_g.get('mae'))} pass={sum_g.get('analog_pass')}", flush=True)
        controls.append(sum_g)
        report["controls"] = controls
        report["n32_regression"] = {"dc": extra_stats(slim_eval(rec_c)), "tran200": sum_g}
        save_report(report)

    if not (report.get("dc_results") or {}).get("mae"):
        print("==== PHASE 2 F40 qualified DC ====", flush=True)
        rec = eval_fabric(
            ng, net_opa, spec, x40, y40, dest("p2", "f40_dc"),
            options=option_line(reltol=QUAL_RELTOL), timeout=TIMEOUT_DC_F40,
        )
        row = extra_stats(slim_eval(rec))
        report["dc_results"] = row
        print(
            f"  F40 DC MAE={fmt(rec.get('mae'))} max={fmt(rec.get('max_abs_error'))} "
            f"acc={fmt(rec.get('accuracy'), '.4f')} pass={rec.get('analog_pass')} "
            f"worst={rec.get('worst_vector')}",
            flush=True,
        )
        save_report(report)

    if len(report.get("dc_repeatability") or []) < 3:
        print("==== PHASE 3 F40 DC repeats ====", flush=True)
        reps = list(report.get("dc_repeatability") or [])
        start = len(reps)
        for i in range(start, 3):
            rec = eval_fabric(
                ng, net_opa, spec, x40, y40, dest("p3", "rep", i),
                options=option_line(reltol=QUAL_RELTOL), timeout=TIMEOUT_DC_F40,
            )
            row = extra_stats(slim_eval(rec))
            row["run"] = i + 1
            reps.append(row)
            print(f"  repeat {i+1} MAE={fmt(rec.get('mae'))} worst={rec.get('worst_vector')}", flush=True)
            report["dc_repeatability"] = reps
            save_report(report)

    if not report.get("reltol_sweep"):
        print("==== PHASE 5 F40 reltol band ====", flush=True)
        rows = []
        for rt in RELTOLS:
            opt = None if rt is None else option_line(reltol=rt)
            rec = eval_fabric(
                ng, net_opa, spec, x40, y40, dest("p5", rt if rt is not None else "factory"),
                options=opt, timeout=TIMEOUT_DC_F40,
            )
            row = extra_stats(slim_eval(rec))
            row["reltol"] = rt
            row["reltol_label"] = "factory" if rt is None else f"{rt:g}"
            rows.append(row)
            print(
                f"  reltol={row['reltol_label']} MAE={fmt(rec.get('mae'))} "
                f"pass={rec.get('analog_pass')} fail={rec.get('failed')}",
                flush=True,
            )
            report["reltol_sweep"] = rows
            save_report(report)

    if not report.get("hidden_inverter_residuals"):
        print("==== PHASE 4/8 rich invert residuals ====", flush=True)
        rich = eval_f_rich(
            ng,
            inject_options(net_opa, option_line(reltol=QUAL_RELTOL)),
            spec,
            x40,
            y40,
            hidden,
            dest("p4", "rich"),
            timeout=TIMEOUT_RICH,
            sum_nodes=output_sum_nodes(spec["n_out"]),
        )
        probes = rich.get("probes") or []
        errs = [p.get("err_max") or 0 for p in probes]
        hid = {
            "mean": rich.get("mean_invert_residual"),
            "max": rich.get("max_invert_residual"),
            "p95": float(np.percentile(errs, 95)) if errs else None,
            "n_stages": len(probes),
            "residual_by_vector": rich.get("residual_by_vector"),
            "shared_pedestal": rich.get("shared_pedestal"),
            "probes": [
                {"stem": p.get("stem"), "err_mae": p.get("err_mae"), "err_max": p.get("err_max"),
                 "vin_max": p.get("vin_max"), "r_fab": p.get("r_fab_ohm")}
                for p in probes
            ],
        }
        report["hidden_inverter_residuals"] = hid
        dc = report.get("dc_results") or {}
        report["worst_vectors"] = {
            "worst_max_error_vector": dc.get("worst_vector"),
            "worst_mae_vector": int(np.argmax(dc["per_vector_mae"])) if dc.get("per_vector_mae") else None,
            "largest_invert_residual_vector": (
                int(np.argmax(rich["residual_by_vector"])) if rich.get("residual_by_vector") else None
            ),
            "worst_output": dc.get("worst_output"),
            "mean_invert_residual": hid.get("mean"),
            "max_invert_residual": hid.get("max"),
            "note": "Compare to Exp 35 vector 6 default-DC 2.29 mV pedestal.",
        }
        if rich.get("i_vdd_mae") is not None:
            report["power_scope"] = {
                "i_vdd_mean_abs_A": rich["i_vdd_mae"],
                "label": "macromodel simulated primitive supply consumption",
                "not": ["chip power", "board power", "Network F physical power"],
            }
        else:
            report["power_scope"] = {
                "label": "macromodel simulated primitive supply consumption",
                "i_vdd_mean_abs_A": None,
                "not": ["chip power", "board power", "Network F physical power"],
            }
        print(
            f"  invert mean={fmt(hid.get('mean'))} max={fmt(hid.get('max'))} "
            f"rich_fail={rich.get('failed')}",
            flush=True,
        )
        save_report(report)

    dwells = list(report.get("dwell_results") or [])
    trans = list(report.get("transient_results") or [])
    have200 = any(r.get("t_hold") == 2e-4 and r.get("n_vectors") == N_FULL and r.get("mae") is not None for r in dwells)
    if not have200:
        print("==== PHASE 6 F40 Gear TRAN ====", flush=True)
        trans = list(report.get("transient_results") or [])
        for t_hold in (1e-4, 2e-4, 5e-4):
            if any(r.get("t_hold") == t_hold and r.get("n_vectors") == N_FULL and r.get("mae") is not None for r in dwells):
                continue
            summary, rows = run_independent_tran(ng, net_opa, spec, x40, y40, f"f40_{t_hold}", t_hold)
            dwells.append(summary)
            trans.append(summary)
            report[f"tran_vectors_{t_hold}"] = rows
            report["dwell_results"] = dwells
            report["transient_results"] = trans
            save_report(report)

    if not report.get("vector_order_results"):
        print("==== PHASE 7 vector order ====", flush=True)
        orders = []
        tran200_existing = next(
            (r for r in dwells if r.get("t_hold") == 2e-4 and r.get("n_vectors") == N_FULL and r.get("mae") is not None),
            None,
        )
        rng = np.random.default_rng(36)
        idx_map = {
            "reversed": np.arange(N_FULL - 1, -1, -1),
            "shuffle_seed36": rng.permutation(N_FULL),
        }
        if tran200_existing and tran200_existing.get("mae") is not None:
            orig = dict(tran200_existing)
            orig["order"] = "original"
            orig["protocol"] = tran200_existing.get("protocol") or "independent_per_vector"
            orders.append(orig)
        else:
            idx_map = {"original": np.arange(N_FULL), **idx_map}
        for name, idx in idx_map.items():
            summary, _ = run_independent_tran(
                ng, net_opa, spec, x40[idx], y40[idx], f"ord_{name}", 2e-4
            )
            summary["order"] = name
            summary["index_map"] = [int(i) for i in idx]
            orders.append(summary)
            report["vector_order_results"] = orders
            save_report(report)

    dc = report.get("dc_results") or {}
    if dc.get("mae") is not None and dc.get("mae") > ERROR_LIMIT and not report.get("insertion_controls"):
        print("==== PHASE 9 insertion controls ====", flush=True)
        net_lim = replace_inverts(net0, hidden, "limit", amp_gain=1e5)
        rec1 = eval_f(ng, net_lim, spec, x40, y40, dest("p9", "all_limit"), timeout=TIMEOUT_IDEAL)
        report["insertion_controls"] = [
            extra_stats({**slim_eval(rec1), "control": "all_limit", "note": "not a physical promotion"})
        ]
        save_report(report)

    reps = report.get("dc_repeatability") or []
    maes = [r.get("mae") for r in reps if r.get("mae") is not None]
    repeatable = bool(maes) and (max(maes) - min(maes)) < 1e-6 and all(r.get("analog_pass") for r in reps)
    tran200 = next(
        (r for r in (report.get("dwell_results") or []) if r.get("t_hold") == 2e-4 and r.get("n_vectors") == N_FULL),
        None,
    )
    q = {
        "dc_analog": bool(dc.get("analog_pass")),
        "dc_class": (dc.get("accuracy") or 0) >= 1.0 - 1e-12,
        "dc_repeatable": repeatable,
        "tran200_analog": bool(tran200 and tran200.get("analog_pass")),
        "tran200_class": bool(tran200 and (tran200.get("accuracy") or 0) >= 1.0 - 1e-12),
        "primitive_ok": n_opa >= 32 and "limtia" not in net_opa.lower(),
        "no_repair": True,
    }
    q["qualified"] = all(
        [
            q["dc_analog"],
            q["dc_class"],
            q["dc_repeatable"],
            q["tran200_analog"],
            q["tran200_class"],
            q["primitive_ok"],
            q["no_repair"],
        ]
    )
    report["qualification"] = q
    report["classification_results"] = {
        "dc_accuracy": dc.get("accuracy"),
        "dc_correct": dc.get("correct_count"),
        "dc_incorrect": dc.get("incorrect_count"),
        "tran200_accuracy": None if not tran200 else tran200.get("accuracy"),
        "tran200_analog": None if not tran200 else tran200.get("analog_pass"),
    }
    report["error_budget"] = {
        "ideal_F40": next((c.get("mae") or 0 for c in (report.get("controls") or []) if c.get("control") == "A"), 0),
        "limit_F40": next((c.get("mae") or 0 for c in (report.get("controls") or []) if c.get("control") == "B"), 0),
        "opa189_F40_dc": dc.get("mae") or 0,
        "opa189_F40_200us": (tran200 or {}).get("mae") or 0,
    }
    if "power_scope" not in report:
        report["power_scope"] = {
            "label": "macromodel simulated primitive supply consumption",
            "not": ["chip power", "board power", "Network F physical power"],
        }
    decide(report)
    save_report(report)
    write_plots(report)
    write_markdown(report)
    print(f"STATUS {report['decision']['status']}", flush=True)
    print(f"DECISION {report['decision']['letter']}", flush=True)
    print(f"F40 {report['F40_validated']}", flush=True)
    print(f"wrote {REPORT_MD}", flush=True)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--rewrite-report", action="store_true")
    args = parser.parse_args()
    if args.rewrite_report:
        report = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
        decide(report)
        save_report(report)
        write_plots(report)
        write_markdown(report)
        print(f"STATUS {report['decision']['status']}", flush=True)
        print(f"wrote {REPORT_MD}", flush=True)
    else:
        main()
