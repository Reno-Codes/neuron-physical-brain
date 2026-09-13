"""Experiment 19: replica-null TIA offset cancellation.

Frozen Experiment 9 networks A and F. Architecture A is the Experiment 17
baseline. N matches replica Vos. U leaves replica Vos = 0.
SPICE outputs are never corrected in Python.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from benchmark_scaling import generate_inputs, make_rng
from compile_xor import PROJECT_ROOT, find_ngspice, run_ngspice
from hardware_constrained_compiler import current_cost_estimate, load_frozen_model
from physical_iv_neuron import IVParams, sample_independent
from precision_architectures import hidden_preact_max, software_reference
from test_hardware_constraints import measure_source_current, spec_by_id
from test_iv_architectures import (
    ERROR_LIMIT,
    INPUT_NOISE,
    N_F_SWEEP,
    N_MC_TRIALS,
    N_TEST,
    evaluate_netlist,
    first_class_fail,
    first_over,
    measure_sum_nodes,
    run_mc,
)
from test_robustness import extract_all
from tia_offset import (
    ARCH_KEYS,
    ARCH_PUBLIC,
    CIRCUIT_DIR,
    accounting,
    compile_offset,
    unit_cell_offset,
)


RESULTS_DIR = PROJECT_ROOT / "results"
REPORT_JSON = RESULTS_DIR / "tia_offset_report.json"
REPORT_MD = RESULTS_DIR / "exp19_tia_offset.md"
TIMEOUT = 40.0
VOS_SWEEP = (0.0, 1e-5, 1e-4, 1e-3, 1e-2)
GAIN_SWEEP = (1e3, 1e4, 1e5)
LOCAL_PCTS = (0.0, 0.1, 0.5, 1.0, 2.0, 5.0)
TEST_IDS = ("A", "F")
UNIT_INPUTS = (
    (0.0, 0.0),
    (1.0, 0.0),
    (0.0, 1.0),
    (1.0, 1.0),
    (0.5, -0.5),
    (-0.7, 0.4),
)


def dest(*parts: str) -> Path:
    name = "_".join(
        str(p).replace("%", "pct").replace(".", "p").replace("+", "p") for p in parts
    )
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    return CIRCUIT_DIR / f"{name}.cir"


def fmt(value, spec=".4e") -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return format(value, spec)
    return str(value)


def software_for(weights, inputs, rail: float = 15.0):
    zmax, hmax = hidden_preact_max(inputs, weights["W1"], weights["b1"])
    clipped = hmax > rail + 1e-12
    y = software_reference(
        inputs, weights["W1"], weights["b1"], weights["W2"], weights["b2"],
        linear=False, hidden_rail=rail if clipped else None,
    )
    return y, {"hidden_preact_max": zmax, "hidden_relu_max": hmax, "clipped": clipped}


def run_unit_cells(ngspice) -> dict:
    wts = load_frozen_model("A")
    w = [float(wts["W1"][0, 0]), float(wts["W1"][0, 1])]
    bias = float(wts["b1"][0])
    out = {"w": w, "bias": bias, "by_vos": {}}
    print(f"  unit neuron w={w} b={bias:g}", flush=True)
    for vos in (0.0, 0.001, 0.01):
        block = {}
        for arch in ARCH_KEYS:
            net = unit_cell_offset(arch, w, bias, vos)
            recs = []
            for x1, x2 in UNIT_INPUTS:
                z = w[0] * x1 + w[1] * x2 + bias
                path = dest("unit", arch, f"vos{vos:g}", f"{x1}_{x2}")
                patched = []
                for line in net.splitlines():
                    if line.startswith("Vin1 "):
                        patched.append(f"Vin1 in1 0 DC {x1:.15g}")
                    elif line.startswith("Vin2 "):
                        patched.append(f"Vin2 in2 0 DC {x2:.15g}")
                    else:
                        patched.append(line)
                path.write_text("\n".join(patched) + "\n", encoding="utf-8")
                result = run_ngspice(ngspice, path, timeout=20.0)
                text = f"{result.stdout or ''}\n{result.stderr or ''}"
                vals = extract_all(text, "v(lin)")
                vlin = float(vals[0]) if vals else None
                failed = result.returncode != 0 or vlin is None
                recs.append(
                    {
                        "x": [x1, x2],
                        "z": z,
                        "v_lin": vlin,
                        "err": None if failed else abs(vlin - z),
                        "failed": failed,
                    }
                )
            ok = [r for r in recs if not r["failed"]]
            mae = float(np.mean([r["err"] for r in ok])) if ok else None
            block[arch] = {"mae_vs_numpy": mae, "n_ok": len(ok)}
            print(f"    vos={vos:g} {arch} MAE={fmt(mae)}", flush=True)
        out["by_vos"][str(vos)] = block
    return out


def evaluate_arch(ngspice, spec, weights, arch, x_all) -> dict:
    print(f"  architecture {arch}: {ARCH_PUBLIC[arch]['title']}", flush=True)
    n_w = spec["n_in"] * spec["n_hidden"] + spec["n_hidden"] * spec["n_out"]
    y_all, meta = software_for(weights, x_all)
    params = IVParams(name=f"{arch}_nom")
    net, cat, reason = compile_offset(arch, spec, weights, params)
    nom = {"failed": True, "failure_reason": reason, **meta}
    if net is not None:
        dest(spec["id"], arch, "nominal").write_text(net, encoding="utf-8")
        nom = evaluate_netlist(
            ngspice, spec, net, x_all, y_all, dest(spec["id"], arch, "nominal")
        )
        nom.update(accounting(net, cat, n_w))
        nom.update(meta)
        source_i = measure_source_current(
            ngspice, net, x_all[0], dest(spec["id"], arch, "nominal_i")
        )
        nom["current_cost"] = current_cost_estimate(cat, source_i)
        nom["summing_node"] = measure_sum_nodes(
            ngspice, spec, net, x_all[0], dest(spec["id"], arch, "vsum"),
            "A",
        )
    print(
        f"    MAE={nom.get('mae')} acc={nom.get('accuracy')} "
        f"nR={nom.get('passive_resistors')} tia={nom.get('n_tia_opamps')} "
        f"null={nom.get('n_null_subtractors')} dmy={nom.get('n_replica_dummy_resistors')} "
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
    }


def sweep_vos(ngspice, spec, weights, arch, x_sw, y_sw) -> list[dict]:
    rows = []
    for vos in VOS_SWEEP:
        params = IVParams(name=f"{arch}_vos_{vos:g}", vos=vos)
        net, _cat, reason = compile_offset(arch, spec, weights, params)
        rec = {"name": params.name, "value": vos, "failed": False, "failure_reason": reason}
        if reason or net is None:
            rec["failed"] = True
            rows.append(rec)
            print(f"    vos={vos:g} compile fail {reason}", flush=True)
            continue
        rec.update(
            evaluate_netlist(
                ngspice, spec, net, x_sw, y_sw, dest(spec["id"], arch, f"vos_{vos:g}")
            )
        )
        print(
            f"    vos={vos:g} MAE={rec.get('mae')} acc={rec.get('accuracy')}",
            flush=True,
        )
        rows.append(rec)
    return rows


def sweep_gain(ngspice, spec, weights, arch, x_sw, y_sw) -> list[dict]:
    rows = []
    for a in GAIN_SWEEP:
        params = IVParams(name=f"{arch}_A{a:g}", amp_gain=a)
        net, _cat, reason = compile_offset(arch, spec, weights, params)
        rec = {"name": params.name, "value": a, "failed": False}
        if reason or net is None:
            rec["failed"] = True
            rec["failure_reason"] = reason
            rows.append(rec)
            continue
        rec.update(
            evaluate_netlist(
                ngspice, spec, net, x_sw, y_sw, dest(spec["id"], arch, f"gain_{a:g}")
            )
        )
        print(f"    A={a:g} MAE={rec.get('mae')} acc={rec.get('accuracy')}", flush=True)
        rows.append(rec)
    return rows


def sweep_local(ngspice, spec, block, x_sw, y_sw) -> list[dict]:
    net, cat = block["net_nominal"], block["catalog"]
    if net is None:
        return []
    rows = []
    for pct in LOCAL_PCTS:
        rng = make_rng("exp19", spec["id"], block["arch"], pct)
        values = sample_independent(cat, pct, rng) if pct else None
        rec = {"name": f"local_{pct:g}", "value": pct}
        rec.update(
            evaluate_netlist(
                ngspice, spec, net, x_sw, y_sw,
                dest(spec["id"], block["arch"], f"local_{pct:g}"),
                r_values=values,
            )
        )
        print(
            f"    local {pct:g}% MAE={rec.get('mae')} acc={rec.get('accuracy')}",
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
        amp_gain_error=0.001,
        clip_amp=False,
    )
    net, cat, reason = compile_offset(arch, spec, weights, params)
    if reason or net is None:
        return {"failed": True, "failure_reason": reason}

    def sampler(catalog, rng, _trial, inputs):
        values = sample_independent(catalog, 0.5, rng)
        noisy = inputs + rng.normal(0.0, INPUT_NOISE, size=inputs.shape)
        return values, noisy

    rec = run_mc(
        ngspice, spec, net, cat, x_mc, y_mc,
        dest(spec["id"], arch, "combined"),
        N_MC_TRIALS, f"e19{spec['id']}{arch}", sampler,
    )
    rec["conditions"] = {
        "independent_resistor_pct": 0.5,
        "amp_gain": 1e5,
        "amp_gain_error": 0.001,
        "vos_V": 0.001,
        "replica": "matched" if arch == "N" else ("unmatched_0" if arch == "U" else "none"),
        "rout_ohm": 100.0,
        "i_leak_A": 1e-8,
        "input_noise_V": INPUT_NOISE,
    }
    print(
        f"    combined MAE={rec.get('mae_mean')} acc={rec.get('accuracy_mean')} "
        f"fail={rec.get('failure_reason')}",
        flush=True,
    )
    return rec


def write_plots(report: dict) -> list[str]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    paths = []
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    for net_id in TEST_IDS:
        for arch, style in (("A", "-"), ("N", "--"), ("U", ":")):
            rows = (
                report["networks"].get(net_id, {}).get("architectures", {})
                .get(arch, {})
                .get("vos")
                or []
            )
            xs = [r["value"] for r in rows if not r.get("failed") and r.get("mae") is not None]
            ys = [r["mae"] for r in rows if not r.get("failed") and r.get("mae") is not None]
            if xs:
                ax.plot(xs, ys, style, marker="o", label=f"{net_id}/{arch}")
    ax.set_xscale("symlog", linthresh=1e-6)
    ax.set_yscale("log")
    ax.set_xlabel("TIA Vos (V)")
    ax.set_ylabel("MAE vs frozen ReLU map")
    ax.set_title("Experiment 19: replica-null vs TIA-A offset")
    ax.axhline(ERROR_LIMIT, color="k", ls="--", lw=0.8)
    ax.legend(fontsize=8)
    fig.tight_layout()
    p1 = RESULTS_DIR / "tia_offset_vos.png"
    fig.savefig(p1, dpi=140)
    plt.close(fig)
    paths.append(str(p1))

    fig, ax = plt.subplots(figsize=(6.8, 4.0))
    labels, vals = [], []
    for net_id in TEST_IDS:
        for arch in ARCH_KEYS:
            rec = (
                report["networks"].get(net_id, {}).get("architectures", {})
                .get(arch, {})
                .get("combined")
                or {}
            )
            if rec.get("mae_mean") is None:
                continue
            labels.append(f"{net_id}/{arch}")
            vals.append(rec["mae_mean"])
    ax.bar(np.arange(len(labels)), vals, color="#d9480f")
    ax.set_yscale("log")
    ax.set_xticks(np.arange(len(labels)))
    ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.set_ylabel("combined MC MAE")
    ax.set_title("Experiment 19 combined non-ideal Monte Carlo")
    ax.axhline(ERROR_LIMIT, color="k", ls="--", lw=0.8)
    fig.tight_layout()
    p2 = RESULTS_DIR / "tia_offset_combined.png"
    fig.savefig(p2, dpi=140)
    plt.close(fig)
    paths.append(str(p2))
    return paths


def write_markdown(report: dict) -> None:
    lines = [
        "# Experiment 19 — replica-null TIA offset cancellation",
        "",
        "## TITLE",
        "Can a matched replica TIA cancel amplifier offset without a current dump?",
        "",
        "## QUESTION",
        "Experiment 17's combined Monte Carlo was dominated by 1 mV TIA Vos. "
        "Can Vsig − Vrep, with a dummy-G_tot replica, make Vos a common-mode error?",
        "",
        "## HYPOTHESIS",
        "Matched Vos and matched G_tot make the I=0 TIA output a common mode. "
        "Subtracting in SPICE cancels it. Unmatched replica Vos does not. "
        "Finite open-loop gain remains (global-ish A/(A+1)). Local resistor "
        "mismatch unbalances the replica and sets the new floor.",
        "",
        "## ARCHITECTURE",
        "- A: Experiment 17 feedback TIA",
        "- N: matched replica TIA + dummy G_tot + unity subtractor",
        "- U: same topology, replica Vos = 0",
        "",
        "## WHAT CHANGED",
        "Added a replica transimpedance path. Did not edit frozen weights. "
        "Did not post-correct SPICE. Added one unity VCVS subtractor per neuron.",
        "",
        "## WHAT REMAINED FROZEN",
        "Experiment 9 weights. Invert fabric. Direct bounded ReLU.",
        "",
        "## TEST CONDITIONS",
        "Vos sweep 0 / 10 µV / 100 µV / 1 mV / 10 mV. Combined MC: A=1e5, "
        "1 mV Vos, 100 Ω Rout, 10 nA leak, 0.5% local R, 1 mV input noise.",
        "",
        "## RESULTS",
        "",
        "### Unit cell",
    ]
    for vos, block in (report.get("unit_cell") or {}).get("by_vos", {}).items():
        bits = [
            f"{arch}={fmt((rec or {}).get('mae_vs_numpy'))}"
            for arch, rec in block.items()
        ]
        lines.append(f"- Vos={vos}: " + ", ".join(bits))
    lines += ["", "### Networks"]
    for net_id in TEST_IDS:
        block = report["networks"].get(net_id, {})
        lines.append(f"#### Network {net_id}")
        for arch in ARCH_KEYS:
            rec = (block.get("architectures") or {}).get(arch, {})
            nom = rec.get("nominal") or {}
            comb = rec.get("combined") or {}
            lines.append(
                f"- {arch} nominal MAE={fmt(nom.get('mae'))} "
                f"acc={fmt(nom.get('accuracy'), '.4f')} "
                f"nR={nom.get('passive_resistors')} "
                f"tia={nom.get('n_tia_opamps')} null={nom.get('n_null_subtractors')} "
                f"dmy={nom.get('n_replica_dummy_resistors')}"
            )
            lines.append(
                f"  combined MAE={fmt(comb.get('mae_mean'))} "
                f"acc={fmt(comb.get('accuracy_mean'), '.4f')}"
            )
            vos_rows = rec.get("vos") or []
            for r in vos_rows:
                lines.append(
                    f"  vos={r.get('value')} MAE={fmt(r.get('mae'))} "
                    f"acc={fmt(r.get('accuracy'), '.4f')}"
                )
            loc = rec.get("local") or []
            if loc:
                lines.append(f"  local first MAE>1e-3: {first_over(loc)}")
                lines.append(f"  local first class<100%: {first_class_fail(loc)}")
    lines += [
        "",
        "## COMPARISON WITH PREVIOUS BEST",
        report.get("comparison") or "",
        "",
        "## FAILURE MODES",
        report.get("failure_modes") or "",
        "",
        "## DOMINANT ERROR SOURCE",
        report.get("dominant_error") or "",
        "",
        "## PHYSICAL INTERPRETATION",
        report.get("physical_interpretation") or "",
        "",
        "## HARDWARE REALISM LEVEL",
        report.get("hardware_level") or "",
        "",
        "## CONCLUSION",
        report.get("conclusion") or "",
        "",
        "## NEXT RESEARCH QUESTION",
        report.get("next_question") or "",
        "",
    ]
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")


def conclude(report: dict) -> None:
    f = (report.get("networks") or {}).get("F", {}).get("architectures") or {}
    a_c = (f.get("A") or {}).get("combined") or {}
    n_c = (f.get("N") or {}).get("combined") or {}
    u_c = (f.get("U") or {}).get("combined") or {}
    a_n = (f.get("A") or {}).get("nominal") or {}
    n_n = (f.get("N") or {}).get("nominal") or {}
    n_vos = (f.get("N") or {}).get("vos") or []
    a_vos = (f.get("A") or {}).get("vos") or []
    a_1m = next((r.get("mae") for r in a_vos if r.get("value") == 0.001), None)
    n_1m = next((r.get("mae") for r in n_vos if r.get("value") == 0.001), None)
    report["comparison"] = (
        f"F A nominal MAE={fmt(a_n.get('mae'))}; "
        f"F N nominal MAE={fmt(n_n.get('mae'))}; "
        f"F A Vos=1mV MAE={fmt(a_1m)}; F N Vos=1mV MAE={fmt(n_1m)}; "
        f"F combined A={fmt(a_c.get('mae_mean'))} N={fmt(n_c.get('mae_mean'))} "
        f"U={fmt(u_c.get('mae_mean'))}. "
        "Exp 17 F A combined was ≈3.50e-2 (Vos-dominated)."
    )
    n_better = (
        n_1m is not None and a_1m is not None and n_1m < 0.3 * a_1m
    )
    report["failure_modes"] = (
        "Unmatched replica Vos (U) does not cancel. Local dummy/Rf mismatch "
        "unbalances a matched replica. The unity subtractor is still an "
        "ideal VCVS. Replica doubles TIA count and adds one dummy R per weight."
    )
    report["dominant_error"] = (
        "After a matched null: finite A and local resistor unbalance. "
        "Before the null: amplifier Vos."
        if n_better
        else "Replica did not clearly beat Vos on F; inspect numbers."
    )
    report["physical_interpretation"] = (
        "At I=0 a TIA outputs ≈Vos. A replica with the same Vos and G_tot "
        "makes that a common mode. Vsig−Vrep leaves I*Rf*A/(A+1). "
        "This is analog common-mode rejection, not a Python correction."
    )
    report["hardware_level"] = (
        "LEVEL 2–3: plausible replica-amp topology, still behavioral "
        "controlled sources. PCB would need two op-amps and a dummy "
        "resistor network per neuron, plus a differential read. Not silicon."
    )
    if n_better:
        report["conclusion"] = (
            "REPLICA-NULL CANCELS MATCHED OFFSET. Architecture N is the new "
            "best no-dump architecture under Vos. Cost: 2× TIA, dummy G_tot, "
            "one unity subtractor per neuron. Unmatched offsets remain fatal."
        )
        report["next_question"] = (
            "Can current-mode cascading avoid some I-to-V stages entirely, "
            "or does an arbitrary frozen W2 require a copy per weight?"
        )
    else:
        report["conclusion"] = (
            "Replica-null did not clearly remove the Vos floor. Preserve the "
            "measurement. TIA-A remains the no-dump baseline."
        )
        report["next_question"] = (
            "Is current-mode cascading able to eliminate hidden I-to-V, or "
            "does frozen W2 force per-weight current copies?"
        )


def main() -> int:
    print("Experiment 19: replica-null TIA offset cancellation", flush=True)
    ngspice = find_ngspice()
    print(f"ngspice: {ngspice}", flush=True)
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "experiment": 19,
        "title": "replica-null TIA offset cancellation",
        "frozen_weights": "Experiment 9 models/scaling/{A,F}.npz",
        "spice_source_of_truth": True,
        "python_does_not_correct_spice": True,
    }
    print("Unit cells", flush=True)
    report["unit_cell"] = run_unit_cells(ngspice)
    report["networks"] = {}
    for net_id in TEST_IDS:
        spec = spec_by_id(net_id)
        weights = load_frozen_model(net_id)
        n_vec = N_TEST if net_id == "A" else N_F_SWEEP
        x_all = generate_inputs(spec["n_in"], n_vec, f"exp19_{net_id}")
        x_sw = generate_inputs(spec["n_in"], min(n_vec, 40), f"exp19_{net_id}_sw")
        x_mc = generate_inputs(spec["n_in"], 8, f"exp19_{net_id}_mc")
        y_sw, _ = software_for(weights, x_sw)
        y_mc, _ = software_for(weights, x_mc)
        print(f"Network {net_id}", flush=True)
        arches = {}
        for arch in ARCH_KEYS:
            block = evaluate_arch(ngspice, spec, weights, arch, x_all)
            print(f"  {arch} Vos sweep", flush=True)
            block["vos"] = sweep_vos(ngspice, spec, weights, arch, x_sw, y_sw)
            if arch in {"A", "N"}:
                print(f"  {arch} gain sweep", flush=True)
                block["gain"] = sweep_gain(ngspice, spec, weights, arch, x_sw, y_sw)
                print(f"  {arch} local mismatch", flush=True)
                block["local"] = sweep_local(ngspice, spec, block, x_sw, y_sw)
            print(f"  {arch} combined MC", flush=True)
            block["combined"] = combined_mc(ngspice, spec, weights, arch, x_mc, y_mc)
            public = {k: block[k] for k in block if k not in {"net_nominal", "catalog"}}
            arches[arch] = public
        report["networks"][net_id] = {"architectures": arches}

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
    print(report.get("conclusion"), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
