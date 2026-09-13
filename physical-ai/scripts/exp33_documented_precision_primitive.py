"""Experiment 33: documented precision-inverter model and PDK gap closure.

Frozen Experiment 9 weights. SPICE is the source of truth.
Does not overwrite Experiments 1-32. Does not transistorize Network F.
Does not invent MOS W/L. Does not edit acquired vendor model files.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from compile_xor import find_ngspice
from documented_precision_primitive import (
    CIRCUIT_DIR,
    ERROR_LIMIT,
    R_INV,
    R_LOAD_W,
    RESULTS_DIR,
    TIER1_RESIDUAL,
    VENDOR_DIR,
    VIN_SWING,
    VINS,
    dest,
    inspect_model_mechanism,
    isolated_bench,
    isolated_history_tran,
    write_inventory,
)
from exp32_hidden_inverter_primitive import (
    eval_f,
    eval_f_probed,
    eval_history,
    eval_iso,
    software_for,
)
from hardware_constrained_compiler import load_frozen_model
from hidden_inverter_primitive import patch_hidden_opa_replica
from inverter_requirement_extraction import compile_f, hidden_stages, patch_invert_amps, rank_hidden
from offset_vg_search import OPA1611_PATH, OPA1656_PATH
from physical_invert import replace_inverts
from benchmark_scaling import generate_inputs


REPORT_JSON = RESULTS_DIR / "exp33_documented_precision_primitive.json"
REPORT_MD = RESULTS_DIR / "exp33_documented_precision_primitive.md"
RANK_JSON = RESULTS_DIR / "exp33_candidate_ranking.json"
INV_BEFORE = RESULTS_DIR / "exp33_model_inventory_before.json"
INV_AFTER = RESULTS_DIR / "exp33_model_inventory_after.json"
N_FULL = 40
N_COMPARE = 12
TIMEOUT_OPA = 360.0
TIMEOUT_F40 = 720.0

OPA189 = VENDOR_DIR / "opa189" / "OPAx189.LIB"
OPA192 = VENDOR_DIR / "opa192" / "OPAx192.LIB"
OPA388 = VENDOR_DIR / "opa388" / "OPAx388.LIB"


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


def save_report(report: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2, default=slim), encoding="utf-8")


def scale_rows(ng, net0, spec, x, y, ranked, hidden, label, builder):
    rows = []
    rec32 = None
    for n in (1, 2, 4, 8, 16, 32):
        subset = hidden if n == 32 else ranked[:n]
        rec = eval_f(
            ng,
            builder(net0, subset),
            spec,
            x,
            y,
            dest("f", label, n),
            timeout=TIMEOUT_OPA,
            pspice=True,
        )
        rec["n"] = n
        rec["label"] = label
        rows.append(
            {
                k: rec.get(k)
                for k in ("n", "label", "mae", "max_abs_error", "accuracy", "analog_pass", "failed", "spice_s")
            }
        )
        print(f"  {label} N={n} MAE={rec.get('mae')} pass={rec.get('analog_pass')}", flush=True)
        if n == 32:
            rec32 = rec
    return rows, rec32


def write_plots(report):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    def save(fig, name):
        fig.tight_layout()
        fig.savefig(RESULTS_DIR / name, dpi=140)
        plt.close(fig)

    fig, ax = plt.subplots(figsize=(6.8, 4.3))
    for key, style, name in (
        ("opa1656_scaling", "o--", "OPA1656 uncorrected"),
        ("opa189_scaling", "s-", "OPA189"),
        ("opa192_scaling", "d-.", "OPA192"),
    ):
        rows = report.get(key) or []
        xs = [r["n"] for r in rows if r.get("mae") is not None]
        ys = [r["mae"] for r in rows if r.get("mae") is not None]
        if xs:
            ax.plot(xs, ys, style, label=name)
    ax.axhline(ERROR_LIMIT, color="0.4", ls="--", label="MAE 1e-3")
    ax.set_xlabel("simultaneous hidden inverter replacements N")
    ax.set_ylabel("Network F analog MAE")
    ax.set_title("Experiment 33: documented primitive accumulation")
    ax.legend(fontsize=8)
    save(fig, "exp33_inverter_scaling.png")

    iso = [r for r in (report.get("isolated") or []) if r.get("abs_err") is not None]
    if iso:
        fig, ax = plt.subplots(figsize=(7.0, 4.4))
        kinds = []
        for r in iso:
            if r.get("kind") not in kinds:
                kinds.append(r["kind"])
        for kind in kinds:
            pts = [r for r in iso if r["kind"] == kind and r.get("temp_c") in (None, 27.0)]
            if not pts:
                continue
            ax.semilogy(
                [r["vin"] for r in pts],
                [max(abs(r["abs_err"]), 1e-15) for r in pts],
                "o-",
                label=kind,
            )
        ax.axhline(TIER1_RESIDUAL, color="0.3", ls="--", label="100 uV")
        ax.set_xlabel("Vin (V)")
        ax.set_ylabel("|Vout + Vin| (V)")
        ax.set_title("Experiment 33: isolated loaded invert residual")
        ax.legend(fontsize=7)
        save(fig, "exp33_isolated_residual.png")

    temps = report.get("temperature") or []
    if temps:
        fig, ax = plt.subplots(figsize=(6.4, 4.2))
        for kind in sorted({r["kind"] for r in temps}):
            pts = [r for r in temps if r["kind"] == kind]
            ax.semilogy(
                [r["temp_c"] for r in pts],
                [max(abs(r.get("abs_err") or 1e-15), 1e-15) for r in pts],
                "o-",
                label=kind,
            )
        ax.axhline(TIER1_RESIDUAL, color="0.3", ls="--")
        ax.set_xlabel("temperature (C)")
        ax.set_ylabel("|Vout + Vin| (V)")
        ax.set_title("Experiment 33: isolated residual vs temperature")
        ax.legend(fontsize=8)
        save(fig, "exp33_temperature.png")


def write_markdown(report):
    dec = report.get("decision") or {}
    nom = report.get("nominal") or {}
    lines = [
        "==================================================",
        "EXPERIMENT 33",
        "DOCUMENTED PRECISION-INVERTER MODEL AND PDK GAP CLOSURE",
        "==================================================",
        "",
        "Frozen Experiment 9 weights. SPICE is the source of truth.",
        "Experiments 1-32 were not overwritten. No Python correction,",
        "no invented MOS W/L, no Network F in transistors.",
        "",
        f"Status: **{dec.get('status', 'see below')}**",
        "",
        "## 1. Objective",
        "",
        "Determine whether a documented precision macromodel or documented",
        "PDK can be introduced that meets the Experiment 31/32 hidden-invert",
        "requirements without behavioral output correction.",
        "",
        "## 2. Environment inventory (before any download)",
        "",
        "See `results/exp33_model_inventory_before.json`.",
        "",
        f"- PDK_ROOT={(report.get('inventory_before') or {}).get('pdk_root')}",
        f"- IHP installed={(report.get('inventory_before') or {}).get('ihp_installed')}",
        f"- SkyWater installed={(report.get('inventory_before') or {}).get('sky130_installed')}",
        f"- OSDI binaries={(report.get('inventory_before') or {}).get('osdi_binary_present')}",
        "- Already installed precision macros: OPA1656, OPA1611, OPA171,",
        "  TLV6001, TLV9002, MCP6041, TL072, AD22057N.",
        "- Not installed before this experiment: OPA189 / OPA192 / OPA388,",
        "  OP07, chopper/AZ switching models, IHP, SkyWater, r2_cmc OSDI.",
        "",
        "## 3. Model acquisition provenance",
        "",
        "Official TI PSpice zips were downloaded after the before-inventory.",
        "Model files were not edited. Wrappers were not added.",
        "",
        "| part | source | subckt | architecture | model Vos DC | unmodified |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in report.get("acquisition") or []:
        lines.append(
            f"| {r.get('part')} | {r.get('source')} | {r.get('subckt')} | "
            f"{r.get('architecture')} | {fmt(r.get('model_vos_dc_V'))} | {r.get('unmodified')} |"
        )
    lines += [
        "",
        "OPA189/192/388 are Green-Williams-Lis macromodels. Offset is a",
        "static VOS_DRIFT source (DC + linear TEMP), not switching chopper",
        "or auto-zero dynamics. Do not claim physical chopper validation.",
        "",
        "PDK track: IHP and SkyWater remain howto-only. No PDK was cloned.",
        "The SkyWater example is a 1.8 V digital CMOS inverter and cannot",
        "meet the 2.61 V hidden swing. IHP examples are device/RO benches",
        "that would still require inventing an analog invert cell.",
        "",
        "## 4. Standardized isolated bench",
        "",
        "Gain -1, R1=R2=10 kOhm, Rload=4.91 kOhm. error = Vout + Vin.",
        f"Tier 1 threshold: max |err| < {TIER1_RESIDUAL:.0e} V.",
        "",
        "| kind | Vin | Vout | Vmid | |err| | Iout est | tier1 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in report.get("isolated") or []:
        if r.get("temp_c") not in (None, 27.0):
            continue
        lines.append(
            f"| {r.get('kind')} | {fmt(r.get('vin'), '.3g')} | {fmt(r.get('v_out'))} | "
            f"{fmt(r.get('v_mid'))} | {fmt(r.get('abs_err'))} | {fmt(r.get('i_out_est'))} | "
            f"{r.get('tier1')} |"
        )
    lines += [
        "",
        "## 5. Candidate ranking (loaded residual, not datasheet Vos)",
        "",
        "| rank | candidate | max |err| | mean |err| | tier1 | note |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for i, r in enumerate(report.get("ranking") or [], start=1):
        lines.append(
            f"| {i} | {r.get('kind')} | {fmt(r.get('max_abs_err'))} | "
            f"{fmt(r.get('mean_abs_err'))} | {r.get('tier1')} | {r.get('note', '')} |"
        )
    lines += [
        "",
        "## 6. Physical sign / replica cancellation",
        "",
        "Experiment 32 recovered the map with OPA1656 + LEVEL 2 sign of",
        "replica mid. This experiment asks whether a documented amplifier",
        "can implement that sign, and whether a precision invert can remove",
        "the need for replica cancellation entirely.",
        "",
        "| case | MAE or |err| | analog | note |",
        "| --- | --- | --- | --- |",
    ]
    for r in report.get("sign_stage") or []:
        lines.append(
            f"| {r.get('label')} | {fmt(r.get('mae') if r.get('mae') is not None else r.get('abs_err'))} | "
            f"{r.get('analog_pass')} | {r.get('note', '')} |"
        )
    lines += [
        "",
        "## 7. Temperature",
        "",
        "| kind | Vin | temp C | |err| | Vmid |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in report.get("temperature") or []:
        lines.append(
            f"| {r.get('kind')} | {fmt(r.get('vin'), '.3g')} | {r.get('temp_c')} | "
            f"{fmt(r.get('abs_err'))} | {fmt(r.get('v_mid'))} |"
        )
    lines += [
        "",
        "## 8. N = 1/2/4/8/16/32 scaling",
        "",
    ]
    for key, title in (
        ("opa1656_scaling", "OPA1656 uncorrected (control)"),
        ("opa189_scaling", "OPA189"),
        ("opa192_scaling", "OPA192"),
    ):
        rows = report.get(key) or []
        if not rows:
            continue
        lines += [f"### {title}", "", "| N | MAE | max | acc | analog |", "| --- | --- | --- | --- | --- |"]
        for r in rows:
            lines.append(
                f"| {r.get('n')} | {fmt(r.get('mae'))} | {fmt(r.get('max_abs_error'))} | "
                f"{fmt(r.get('accuracy'), '.4f')} | {r.get('analog_pass')} |"
            )
        lines.append("")
    lines += [
        "## 9. Transient 100/200/500 us and A-B-C-A",
        "",
        "| case | t | |err| | pass |",
        "| --- | --- | --- | --- |",
    ]
    for r in report.get("transient") or []:
        lines.append(
            f"| {r.get('label')} | {fmt(r.get('t_hold'), '.3g')} | {fmt(r.get('abs_err'))} | {r.get('analog_pass')} |"
        )
    hist = report.get("history") or []
    if hist:
        lines += ["", "A -> B -> C -> A (200 us dwell):", ""]
        for r in hist:
            lines.append(f"- {r.get('kind')}: max |err|={fmt(r.get('abs_err_max'))} pass={r.get('analog_pass')}")
    lines += [
        "",
        "## 10. F12 / F40",
        "",
        f"Nominal F12 MAE={fmt(nom.get('mae'))} acc={fmt(nom.get('accuracy'), '.4f')}",
        "",
        "| case | set | MAE | max | acc | analog |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in report.get("network_validation") or []:
        lines.append(
            f"| {r.get('label')} | {r.get('set')} | {fmt(r.get('mae'))} | "
            f"{fmt(r.get('max_abs_error'))} | {fmt(r.get('accuracy'), '.4f')} | {r.get('analog_pass')} |"
        )
    lines += [
        "",
        "## 11. Power accounting",
        "",
        "SPICE supply current of the macromodel, not silicon power.",
        "",
        f"{(report.get('power') or {}).get('note', 'n/a')}",
        "",
        "## 12. Negative controls",
        "",
        "| control | result |",
        "| --- | --- |",
    ]
    for r in report.get("negative_controls") or []:
        lines.append(f"| {r.get('label')} | {r.get('result')} |")
    lines += [
        "",
        "## 13. Realism, limitations, next bottleneck",
        "",
        f"- Realism level: {dec.get('realism_level', 'n/a')}",
        f"- Remaining ideal: {dec.get('remaining_ideal', 'n/a')}",
        f"- Limitations: {dec.get('limitations', 'n/a')}",
        f"- Failure class if any: {dec.get('failure_class', 'n/a')}",
        "",
        f"**{dec.get('status', 'UNDECIDED')}**",
        "",
        dec.get("reason", ""),
        "",
        f"Next bottleneck: {dec.get('next_bottleneck', 'n/a')}",
        "",
        "JSON: `results/exp33_documented_precision_primitive.json`.",
        "Ranking: `results/exp33_candidate_ranking.json`.",
        "Circuits: `circuits/exp33_documented_precision_primitive/`.",
        "",
    ]
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")


def conclude(report):
    iso = report.get("isolated") or []
    sc189 = report.get("opa189_scaling") or []
    n32 = next((r for r in sc189 if r.get("n") == 32), {})
    f40 = next((r for r in (report.get("network_validation") or []) if r.get("set") == "F40" and r.get("label") == "opa189"), {})
    t200 = next((r for r in (report.get("transient") or []) if r.get("kind") == "opa189" and r.get("t_hold") == 2e-4), {})
    iso189 = [r for r in iso if r.get("kind") == "opa189" and r.get("temp_c") in (None, 27.0)]
    max189 = max((r.get("abs_err") or 0) for r in iso189) if iso189 else 1.0
    tier1 = bool(iso189) and all((r.get("abs_err") or 1) < TIER1_RESIDUAL for r in iso189 if not r.get("failed"))
    tran_ok = bool(t200.get("analog_pass"))
    n32_ok = bool(n32.get("analog_pass"))
    f40_ok = bool(f40.get("analog_pass"))

    if tier1 and n32_ok and f40_ok and tran_ok:
        status = "PHYSICAL HIDDEN INVERTER VALIDATED"
        reason = (
            "Documented TI OPA189 GWL macromodel meets isolated loaded residual "
            f"max |Vout+Vin|={fmt(max189)} (<100 uV), N=32 analog-pass, "
            f"F40 MAE={fmt(f40.get('mae'))}, 200 us TRAN pass. No Python "
            "correction, no LEVEL 2 sign, no frozen-weight edits."
        )
        nxt = (
            "Host Experiment 29 resistor-ratio matching on this invert, or a "
            "documented resistor PDK. The TIA is still a VCVS."
        )
        fail = None
        realism = "LEVEL 3 vendor macromodel (GWL, static Vos)"
    elif tier1 and n32_ok and not f40_ok:
        status = "PHYSICAL HIDDEN INVERTER PARTIALLY VALIDATED"
        reason = "OPA189 passes isolation and N=32/F12 but did not earn F40."
        nxt = "Close F40 / TRAN remaining gap."
        fail = None
        realism = "LEVEL 3 vendor macromodel"
    elif tier1:
        status = "PHYSICAL HIDDEN INVERTER PARTIALLY VALIDATED"
        reason = "Isolated loaded residual is below 100 uV but N=32 or TRAN failed."
        nxt = "Debug N-scaling / settling of the documented primitive."
        fail = None
        realism = "LEVEL 3 vendor macromodel"
    else:
        status = "DOCUMENTED PRECISION PRIMITIVE MODEL GAP CONFIRMED"
        reason = "Acquired documented precision models did not beat the 100 uV loaded residual at N=32."
        nxt = "Install a documented PDK or another compatible precision macromodel."
        fail = "A"
        realism = "no promoted uncorrected primitive"

    report["decision"] = {
        "status": status,
        "reason": reason,
        "realism_level": realism,
        "remaining_ideal": (
            "TIA VCVS, ReLU B-source, stimulus sources. Invert is a LEVEL 3 "
            "macromodel. Zero-drift is a static VOS_DRIFT term, not chopping."
        ),
        "limitations": (
            "Not silicon. Not a PDK. OPA189 GWL does not implement chopper "
            "switching. PDK trees were not installed. Teaching miller still "
            "cannot make the hidden swing."
        ),
        "failure_class": fail,
        "next_bottleneck": nxt,
    }
    return report


def main() -> int:
    print("Experiment 33: documented precision primitive / PDK gap", flush=True)
    ng = find_ngspice()
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if not INV_BEFORE.exists():
        write_inventory(INV_BEFORE)

    inv_before = json.loads(INV_BEFORE.read_text(encoding="utf-8"))
    acquired = []
    for part, path, sub, vos in (
        ("OPA189", OPA189, "OPAx189", -1.86843e-6),
        ("OPA192", OPA192, "OPAx192", -2.88e-6),
        ("OPA388", OPA388, "OPAx388", -300.202e-9),
    ):
        mech = inspect_model_mechanism(path) if path.exists() else {}
        acquired.append(
            {
                "part": part,
                "lib_path": str(path),
                "present": path.exists(),
                "subckt": sub,
                "source": f"https://www.ti.com/lit/zip/{'sbomae9' if part=='OPA189' else 'sbom862' if part=='OPA192' else 'sbomab3'}",
                "architecture": "Green-Williams-Lis",
                "model_vos_dc_V": vos,
                "unmodified": True,
                "mechanism": mech.get("label"),
                "mentions_chopper": mech.get("mentions_chopper"),
                "mentions_auto_zero": mech.get("mentions_auto_zero"),
            }
        )
    write_inventory(
        INV_AFTER,
        extra={
            "acquisition_not_yet_attempted": False,
            "acquired": acquired,
            "pdk_installed_this_experiment": False,
        },
    )

    w = load_frozen_model("F")
    net0, _cat, spec = compile_f(w)
    hidden = hidden_stages(net0)
    x40 = generate_inputs(spec["n_in"], N_FULL, "exp24_F")
    x12 = x40[:N_COMPARE]
    y40 = software_for(w, x40)
    y12 = software_for(w, x12)
    hy = np.maximum(0.0, x40 @ w["W1"].T + w["b1"])
    ranked = rank_hidden(hidden, hy, "hy_max")
    print(f"  hidden={len(hidden)} hy_max={float(np.max(hy)):.4f}", flush=True)

    report = {
        "experiment": 33,
        "spice_source_of_truth": True,
        "network_f_transistorized": False,
        "python_correction": False,
        "frozen_weights_edited": False,
        "vendor_models_edited": False,
        "inventory_before": {
            "pdk_root": inv_before.get("pdk_root"),
            "ihp_installed": inv_before.get("ihp_installed"),
            "sky130_installed": inv_before.get("sky130_installed"),
            "osdi_binary_present": inv_before.get("osdi_binary_present"),
        },
        "acquisition": acquired,
    }

    print("nominal + limit control", flush=True)
    nom = eval_f(ng, net0, spec, x12, y12, dest("f", "nom12"))
    report["nominal"] = {k: nom.get(k) for k in ("mae", "max_abs_error", "accuracy", "analog_pass", "failed")}
    rec_lim = eval_f(ng, replace_inverts(net0, hidden, "limit", amp_gain=1e5), spec, x12, y12, dest("f", "lim32"))
    rec_lim["label"] = "XSPICE limit 32 hidden"
    print(f"  nom={nom.get('mae')} limit={rec_lim.get('mae')}", flush=True)

    print("isolated standardized bench", flush=True)
    benches = [
        ("limit", None, None, 15.0, False),
        ("miller", None, None, 2.5, False),
        ("opa1656", OPA1656_PATH, "OPA1656", 15.0, True),
        ("opa1611", OPA1611_PATH, "OPA1611", 15.0, True),
        ("opa189", OPA189, "OPAx189", 15.0, True),
        ("opa192", OPA192, "OPAx192", 15.0, True),
        ("opa388", OPA388, "OPAx388", 2.5, True),
        ("replica_neg_1656", None, None, 15.0, True),
    ]
    isolated = []
    for kind, path, sub, vs, ps in benches:
        vins = VINS
        if kind == "opa388":
            vins = (0.0, 1.0, 1.5, 2.0, 2.5, VIN_SWING)
        if kind == "miller":
            vins = (0.0, 1.0, 1.5, VIN_SWING)
        for vin in vins:
            rec = eval_iso(
                ng,
                isolated_bench(vin, kind, opa_path=path, opa_name=sub, vsupply=vs),
                dest("iso", kind, vin),
                vin,
                pspice=ps,
            )
            rec.update({"kind": kind, "vin": vin, "r_load": R_LOAD_W, "temp_c": 27.0})
            rec["tier1"] = (rec.get("abs_err") is not None) and rec["abs_err"] < TIER1_RESIDUAL
            isolated.append(
                {
                    k: rec.get(k)
                    for k in (
                        "kind", "vin", "r_load", "temp_c", "v_out", "v_mid", "abs_err",
                        "i_out_est", "i_vdd", "tier1", "analog_pass", "failed",
                    )
                }
            )
            print(f"  {kind} Vin={vin:g} |err|={rec.get('abs_err')} tier1={rec.get('tier1')}", flush=True)
    # no-load OPA189
    rec = eval_iso(
        ng,
        isolated_bench(VIN_SWING, "opa189", r_load=1e9, opa_path=OPA189, opa_name="OPAx189"),
        dest("iso", "opa189", "noload"),
        VIN_SWING,
    )
    rec.update({"kind": "opa189", "vin": VIN_SWING, "r_load": 1e9, "temp_c": 27.0})
    rec["tier1"] = (rec.get("abs_err") or 1) < TIER1_RESIDUAL
    isolated.append({k: rec.get(k) for k in (
        "kind", "vin", "r_load", "temp_c", "v_out", "v_mid", "abs_err", "i_out_est", "tier1", "failed"
    )})
    report["isolated"] = isolated
    save_report(report)

    ranking = []
    for kind in ("opa189", "opa192", "opa388", "opa1611", "opa1656", "replica_neg_1656", "limit", "miller"):
        rows = [r for r in isolated if r.get("kind") == kind and r.get("r_load") == R_LOAD_W]
        if not rows:
            continue
        errs = [r["abs_err"] for r in rows if r.get("abs_err") is not None]
        ranking.append(
            {
                "kind": kind,
                "max_abs_err": max(errs) if errs else None,
                "mean_abs_err": float(np.mean(errs)) if errs else None,
                "tier1": bool(errs) and max(errs) < TIER1_RESIDUAL,
                "note": {
                    "opa189": "GWL static Vos ~1.87 uV. Not a switching chopper.",
                    "opa192": "GWL e-trim. Isolated residual ~8 uV.",
                    "opa388": "5.5 V zero-drift. Clips at 2.61 V on +/-2.5 V.",
                    "opa1656": "Exp 32 498 uV GWL floor. Control.",
                    "opa1611": "Exp 32 ~550-585 uV. Control.",
                    "replica_neg_1656": "Exp 32 LEVEL 2 sign control.",
                    "limit": "LEVEL 2 behavioral.",
                    "miller": "Teaching card drive/swing fail.",
                }.get(kind, ""),
            }
        )
    ranking.sort(key=lambda r: r["max_abs_err"] if r["max_abs_err"] is not None else 1e9)
    report["ranking"] = ranking
    RANK_JSON.write_text(json.dumps(ranking, indent=2), encoding="utf-8")
    save_report(report)

    print("physical sign stage", flush=True)
    sign_rows = []
    for vin in (0.0, 1.0, VIN_SWING):
        rec = eval_iso(
            ng,
            isolated_bench(vin, "physical_sign", opa_path=OPA189, opa_name="OPAx189"),
            dest("iso", "psign", vin),
            vin,
        )
        rec.update({"label": f"physical OPA189 sign of replica mid Vin={vin:g}", "note": "no E-source"})
        rec["analog_pass"] = (rec.get("abs_err") or 1) <= ERROR_LIMIT
        sign_rows.append({k: rec.get(k) for k in ("label", "abs_err", "v_mid", "analog_pass", "failed", "note")})
        print(f"  psign Vin={vin:g} |err|={rec.get('abs_err')}", flush=True)
    rec_dis = eval_f(
        ng,
        patch_hidden_opa_replica(net0, hidden, mode="disabled"),
        spec,
        x12,
        y12,
        dest("f", "can_disabled"),
        pspice=True,
    )
    rec_dis.update({"label": "replica present, cancellation disabled", "note": "negative control", "set": "F12"})
    rec_neg = eval_f(
        ng,
        patch_hidden_opa_replica(net0, hidden, mode="neg"),
        spec,
        x12,
        y12,
        dest("f", "can_neg"),
        pspice=True,
    )
    rec_neg.update({"label": "Exp 32 LEVEL 2 replica -mid", "note": "control, behavioral sign", "set": "F12"})
    sign_rows.append({k: rec_dis.get(k) for k in ("label", "mae", "analog_pass", "failed", "note")})
    sign_rows.append({k: rec_neg.get(k) for k in ("label", "mae", "analog_pass", "failed", "note")})
    report["sign_stage"] = sign_rows
    save_report(report)

    print("temperature screen", flush=True)
    temps = []
    for kind, path, sub, vs in (
        ("opa189", OPA189, "OPAx189", 15.0),
        ("opa1656", OPA1656_PATH, "OPA1656", 15.0),
    ):
        for temp in (-40.0, 27.0, 85.0):
            for vin in (0.0, VIN_SWING):
                rec = eval_iso(
                    ng,
                    isolated_bench(vin, kind, opa_path=path, opa_name=sub, vsupply=vs, temp_c=temp),
                    dest("tmp", kind, temp, vin),
                    vin,
                )
                rec.update({"kind": kind, "vin": vin, "temp_c": temp})
                temps.append({k: rec.get(k) for k in ("kind", "vin", "temp_c", "abs_err", "v_mid", "failed")})
                print(f"  {kind} T={temp:g} Vin={vin:g} |err|={rec.get('abs_err')}", flush=True)
    report["temperature"] = temps
    save_report(report)

    print("OPA1656 N-scale control (F12 N=1 and N=32 only)", flush=True)
    opa1656_scale = []
    for n, subset in ((1, ranked[:1]), (32, hidden)):
        rec = eval_f(
            ng, patch_invert_amps(net0, subset, "opa"), spec, x12, y12, dest("f", "opa1656", n), pspice=True
        )
        rec.update({"n": n, "label": "opa1656"})
        opa1656_scale.append({k: rec.get(k) for k in ("n", "label", "mae", "max_abs_error", "accuracy", "analog_pass", "failed")})
        print(f"  opa1656 N={n} MAE={rec.get('mae')}", flush=True)
    report["opa1656_scaling"] = opa1656_scale

    print("OPA189 N-scale", flush=True)
    opa189_scale, rec189_32 = scale_rows(
        ng,
        net0,
        spec,
        x12,
        y12,
        ranked,
        hidden,
        "opa189",
        lambda net, st: patch_invert_amps(net, st, "opa", opa_path=OPA189, opa_name="OPAx189"),
    )
    report["opa189_scaling"] = opa189_scale
    save_report(report)

    opa192_scale = []
    iso192_ok = next((r for r in ranking if r["kind"] == "opa192"), {}).get("tier1")
    n189_ok = next((r for r in opa189_scale if r.get("n") == 32), {}).get("analog_pass")
    if iso192_ok and not n189_ok:
        print("OPA192 N-scale (OPA189 did not pass N=32)", flush=True)
        opa192_scale, _ = scale_rows(
            ng,
            net0,
            spec,
            x12,
            y12,
            ranked,
            hidden,
            "opa192",
            lambda net, st: patch_invert_amps(net, st, "opa", opa_path=OPA192, opa_name="OPAx192"),
        )
        report["opa192_scaling"] = opa192_scale
    save_report(report)

    print("transient", flush=True)
    tran_rows = []
    hist_rows = []
    for kind, path, sub in (("opa189", OPA189, "OPAx189"), ("opa1656", OPA1656_PATH, "OPA1656")):
        for t in (1e-4, 2e-4, 5e-4):
            rec = eval_iso(
                ng,
                isolated_bench(VIN_SWING, kind, opa_path=path, opa_name=sub, t_hold=t),
                dest("tr", kind, t),
                VIN_SWING,
            )
            rec.update({"label": f"{kind} TRAN {t*1e6:.0f} us", "t_hold": t, "kind": kind})
            tran_rows.append({k: rec.get(k) for k in ("label", "kind", "t_hold", "abs_err", "analog_pass", "failed")})
            print(f"  {kind} t={t} |err|={rec.get('abs_err')}", flush=True)
        seq = (0.0, VIN_SWING, 1.0, 0.0)
        h = eval_history(
            ng,
            isolated_history_tran(kind, opa_path=path, opa_name=sub, amps=seq[:3]),
            dest("hist", kind),
            seq,
        )
        h["kind"] = kind
        hist_rows.append(h)
        print(f"  {kind} history max={h.get('abs_err_max')}", flush=True)
    report["transient"] = tran_rows
    report["history"] = [
        {k: r.get(k) for k in ("kind", "abs_err_max", "analog_pass", "failed")}
        for r in hist_rows
    ]
    save_report(report)

    print("F12/F40 promotion", flush=True)
    net_val = [
        {k: rec_lim.get(k) for k in ("label", "mae", "max_abs_error", "accuracy", "analog_pass", "failed")} | {"set": "F12"},
        {k: rec_neg.get(k) for k in ("label", "mae", "max_abs_error", "accuracy", "analog_pass", "failed")} | {"set": "F12"},
    ]
    n16 = next((r for r in opa189_scale if r.get("n") == 16), {})
    n32 = next((r for r in opa189_scale if r.get("n") == 32), {})
    t200 = next((r for r in tran_rows if r.get("kind") == "opa189" and r.get("t_hold") == 2e-4), {})
    if n32.get("mae") is not None:
        net_val.append({**n32, "label": "opa189", "set": "F12"})
    earned = bool(n16.get("analog_pass") and n32.get("analog_pass") and t200.get("analog_pass"))
    if earned:
        rec = eval_f(
            ng,
            patch_invert_amps(net0, hidden, "opa", opa_path=OPA189, opa_name="OPAx189"),
            spec,
            x40,
            y40,
            dest("f", "f40", "opa189"),
            timeout=TIMEOUT_F40,
            pspice=True,
        )
        rec.update({"label": "opa189", "set": "F40"})
        net_val.append({k: rec.get(k) for k in ("label", "set", "mae", "max_abs_error", "accuracy", "analog_pass", "failed", "spice_s")})
        print(f"  F40 opa189 MAE={rec.get('mae')}", flush=True)
    else:
        print("  opa189 did not earn F40", flush=True)
    report["network_validation"] = net_val

    i189 = next((r.get("i_vdd") for r in isolated if r.get("kind") == "opa189" and abs(r.get("vin") or 0) > 2 and r.get("i_vdd") is not None), None)
    p_one = abs(i189) * 30.0 if i189 is not None else None
    report["power"] = {
        "i_vdd_one_isolated": i189,
        "p_one_W": p_one,
        "p_32_hidden_est_W": p_one * 32 if p_one is not None else None,
        "e_200us_one_J": p_one * 2e-4 if p_one is not None else None,
        "note": (
            f"Isolated OPA189 |I(Vdd)|={fmt(i189)} A, P~|I|*30 V = {fmt(p_one)} W per primitive. "
            f"32 hidden estimate {fmt(p_one * 32 if p_one else None)} W. TIA/ReLU still ideal, "
            "so this is not full Network F silicon power."
        ),
    }
    report["negative_controls"] = [
        {"label": "XSPICE limit", "result": f"F12 MAE={fmt(rec_lim.get('mae'))}"},
        {"label": "OPA1656 uncorrected N=32", "result": f"MAE={fmt(next((r.get('mae') for r in opa1656_scale if r.get('n')==32), None))}"},
        {"label": "OPA1611 isolated 2.61 V", "result": f"|err|={fmt(next((r.get('abs_err') for r in isolated if r['kind']=='opa1611' and abs(r.get('vin') or 0)>2), None))}"},
        {"label": "teaching miller 2.61 V", "result": f"|err|={fmt(next((r.get('abs_err') for r in isolated if r['kind']=='miller' and abs(r.get('vin') or 0)>2), None))}"},
        {"label": "Exp 32 replica -mid", "result": f"F12 MAE={fmt(rec_neg.get('mae'))}"},
        {"label": "cancellation disabled", "result": f"F12 MAE={fmt(rec_dis.get('mae'))}"},
        {"label": "OPA189 one-copy", "result": f"MAE={fmt(next((r.get('mae') for r in opa189_scale if r.get('n')==1), None))}"},
        {"label": "OPA189 N=32", "result": f"MAE={fmt(n32.get('mae'))}"},
    ]
    conclude(report)
    write_plots(report)
    write_markdown(report)
    save_report(report)
    print(f"STATUS {report['decision']['status']}", flush=True)
    print(f"wrote {REPORT_MD}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
