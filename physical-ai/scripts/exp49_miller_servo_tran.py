"""Experiment 49: existing SKY130 Miller+servo in the 200 us regime.

Same Experiment 48 circuit. No W/L resize. No Python correction.
Does not modify Experiments 1-48. Not silicon.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from compile_xor import PROJECT_ROOT, find_ngspice
from exp39_pdk_o2_cell import (
    ERROR_LIMIT,
    PDK_VERSION,
    TAG,
    bake_vin_step,
    discover_pdk,
    insert_miller,
    last,
    prepend_pdk,
    run_cir,
    write_op_net,
)
from exp40_pdk_o2_cell import compile_o2_w2_1, prove_identity
from exp41_o2_residual import MILLER_SIZES, replace_resistors_w
from exp45_documented_tia import spiceinit_hsa
from exp48_w10_miller_servo import VSUPPLY, Z_O2
from test_robustness import extract_all

CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp49_o2"
RESULTS_DIR = PROJECT_ROOT / "results"
Y_EXP48_SERVO = 2.098479338703
ERR_EXP48_SERVO = 0.361010232177132
TIMES = (100e-6, 200e-6, 500e-6)
REPEAT_ATOL_V = 1e-6


def tag49(net: str) -> str:
    return net.replace(
        "* Experiment 39 SKY130 isolated frozen o2 cell",
        "* Experiment 49 Miller+servo TRAN · no W/L resize · not silicon",
    )


def write_tran(path: Path, net: str, hy, tstop: float, method: str | None) -> None:
    head, _, _ = net.partition(".control")
    baked = bake_vin_step(tag49(head), hy)
    opt = f"option method={method}\n" if method else ""
    meas = []
    stamps = [t for t in TIMES if t <= tstop + 1e-12]
    if tstop not in stamps:
        stamps.append(tstop)
    for t in stamps:
        us = int(round(t * 1e6))
        meas.append(f"meas tran y{us} FIND v({TAG}lin) AT={t:.15g}")
        meas.append(f"meas tran s{us} FIND v({TAG}p) AT={t:.15g}")
        meas.append(f"meas tran srv{us} FIND v({TAG}srv) AT={t:.15g}")
    ctrl = (
        "\n.control\nset numdgt=12\n"
        f"{opt}tran 1u {tstop:.15g}\n"
        + "\n".join(meas)
        + "\n"
        + "\n".join(f"print y{int(round(t*1e6))}" for t in stamps)
        + "\n.endc\n.end\n"
    )
    path.write_text(baked.rstrip() + "\n" + ctrl, encoding="utf-8")


def run_tran(ng, net, hy, z_ref, name, tstop, method=None, timeout=420.0) -> dict:
    path = CIRCUIT_DIR / f"{name}.cir"
    write_tran(path, net, hy, tstop, method)
    _r, text, fail = run_cir(ng, path, timeout=timeout)
    rec = {
        "name": name,
        "path": str(path),
        "failed": bool(fail),
        "failure_reason": fail,
        "z_ref": float(z_ref),
        "tstop_s": tstop,
        "method": method or "trap_default",
        "python_corrected": False,
        "resized": False,
    }
    if fail:
        rec["log_tail"] = text[-700:]
        print(f"  {name} FAIL {fail}", flush=True)
        return rec
    samples = []
    stamps = [t for t in TIMES if t <= tstop + 1e-12]
    if tstop not in stamps:
        stamps.append(tstop)
    for t in stamps:
        us = int(round(t * 1e6))
        y = last(extract_all(text, f"y{us}"))
        vsum = last(extract_all(text, f"s{us}"))
        vsrv = last(extract_all(text, f"srv{us}"))
        if y is None:
            continue
        row = {
            "t_s": t,
            "y": y,
            "vsum": vsum,
            "vsrv": vsrv,
            "err": y - float(z_ref),
            "abs_err": abs(y - float(z_ref)),
            "analog_pass": abs(y - float(z_ref)) <= ERROR_LIMIT,
            "headroom_V": VSUPPLY - y,
            "delta_vs_exp48_dc": y - Y_EXP48_SERVO,
        }
        samples.append(row)
    rec["samples"] = samples
    if not samples:
        rec.update({"failed": True, "failure_reason": "missing ylin samples", "log_tail": text[-700:]})
        print(f"  {name} missing samples", flush=True)
        return rec
    end = samples[-1]
    rec.update({k: end[k] for k in ("y", "vsum", "err", "abs_err", "analog_pass", "headroom_V")})
    rec["vsrv"] = end.get("vsrv")
    print(
        f"  {name} t={tstop*1e6:.0f}us y={end['y']} |err|={end['abs_err']} "
        f"pass={end['analog_pass']} vsum={end['vsum']} vsrv={end.get('vsrv')} "
        f"dDC={end['delta_vs_exp48_dc']}",
        flush=True,
    )
    return rec


def run_dc(ng, net, hy, z_ref, name) -> dict:
    path = CIRCUIT_DIR / f"{name}.cir"
    write_op_net(path, tag49(net), hy, extra_prints=[f"v({TAG}srv)"])
    from exp39_pdk_o2_cell import eval_cell

    rec = eval_cell(ng, path, z_ref, extra_names=[f"v({TAG}srv)"], timeout=240.0)
    rec.update({"name": name, "python_corrected": False, "resized": False})
    if rec.get("y") is not None:
        rec["delta_vs_exp48"] = rec["y"] - Y_EXP48_SERVO
        rec["repeat_ok"] = abs(rec["y"] - Y_EXP48_SERVO) <= REPEAT_ATOL_V
        rec["headroom_V"] = VSUPPLY - rec["y"]
    print(
        f"  {name} y={rec.get('y')} |err|={rec.get('abs_err')} "
        f"d48={rec.get('delta_vs_exp48')} vsrv={rec.get(f'v({TAG}srv)')}",
        flush=True,
    )
    return rec


def classify(dc: dict, rows: list[dict]) -> tuple[str, str, str, str]:
    usable = [r for r in rows if not r.get("failed") and r.get("samples")]
    at200 = []
    for r in usable:
        at200.extend(s for s in r["samples"] if abs(s["t_s"] - 200e-6) < 1e-12)
    at500 = []
    for r in usable:
        at500.extend(s for s in r["samples"] if abs(s["t_s"] - 500e-6) < 1e-12)
    pass200 = any(s.get("analog_pass") for s in at200)
    if pass200:
        return (
            "A",
            "EXISTING MILLER+SERVO MEETS 1 mV AT 200 us",
            "PARTIALLY VALIDATED",
            "Isolated transient pass only. Promote temperature / vectors next. "
            "Not a full physical TIA claim.",
        )
    if not usable:
        return (
            "E",
            "MILLER+SERVO TRAN DID NOT YIELD A USABLE WAVEFORM",
            "NUMERICAL ISSUE",
            "Retry Gear or inspect the hang before closing the topology.",
        )
    last_y = (at500 or at200 or usable[-1]["samples"])[-1]["y"]
    dy = abs(last_y - Y_EXP48_SERVO)
    moving_to_z = abs(last_y - Z_O2) + 20e-3 < ERR_EXP48_SERVO
    if dy < 5e-3 and not moving_to_z:
        return (
            "D",
            "EXISTING MILLER+SERVO TRAN SETTLES TO THE SAME 361 mV DC MISS",
            "CLOSED NEGATIVE PATH",
            "This exact unre-sized Miller+1 nF servo is closed. Move to Track B. "
            "Do not cosmetic-tweak it.",
        )
    if at200 and at200[0]["abs_err"] > 0.05:
        return (
            "D",
            "EXISTING MILLER+SERVO STILL MISSES BY HUNDREDS OF mV AT 200 us",
            "CLOSED NEGATIVE PATH",
            "Settled transient is still far outside 1 mV. Close this configuration. "
            "Move to Track B.",
        )
    return (
        "B",
        "TRANSIENT DIFFERS FROM DC BUT DOES NOT MEET 1 mV",
        "PARTIALLY VALIDATED",
        "Inspect the trajectory before any W/L search.",
    )


def write_reports(report: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "exp49_miller_servo_tran.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    lines = [
        "# Experiment 49 — existing Miller+servo in the 200 µs regime",
        "",
        "Experiments 1–48 were not modified. Frozen weights unchanged.",
        "Same Exp39/41 Miller sizes and 1 nF servo. No W/L resize.",
        "Official sky130.lib tt. Not silicon.",
        "",
        f"**Status: {report['status']}**",
        f"**Decision {report['decision']} — {report['decision_label']}**",
        "",
        "## Objective",
        "",
        "Determine whether the Experiment 48 DC miss (y=2.098479 V, 361 mV)",
        "is only an inappropriate DC operating point for the integrating servo,",
        "or whether the settled 200 µs inference result also fails.",
        "",
        "## DC repeat",
        "",
    ]
    d = report.get("dc") or {}
    lines.append(
        f"- y = {d.get('y')}  |err| = {None if d.get('abs_err') is None else d['abs_err']*1e3:.6f} mV  "
        f"Δ vs Exp48 = {d.get('delta_vs_exp48')}  repeat_ok = {d.get('repeat_ok')}"
    )
    lines += [
        "",
        "## Transient samples",
        "",
        "| run | method | t (µs) | y (V) | |err| (mV) | Vsum (V) | Vsrv (V) | Δ vs Exp48 DC | pass |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for r in report.get("transients") or []:
        if r.get("failed") and not r.get("samples"):
            lines.append(
                f"| {r.get('name')} | {r.get('method')} | {r.get('tstop_s')} | "
                f"FAIL {r.get('failure_reason')} | — | — | — | — | no |"
            )
            continue
        for s in r.get("samples") or []:
            ae = s.get("abs_err")
            lines.append(
                f"| {r.get('name')} | {r.get('method')} | {s['t_s']*1e6:.0f} | "
                f"{s.get('y')} | {None if ae is None else ae*1e3:.3f} | "
                f"{s.get('vsum')} | {s.get('vsrv')} | {s.get('delta_vs_exp48_dc')} | "
                f"{s.get('analog_pass')} |"
            )
    lines += [
        "",
        report["conclusion"],
        "",
        "- Physical TIA validated: **NO**",
        "- Matching: **UNRESOLVED**",
        "- Experiment 40 Decision C: **unchanged**",
        "- Experiment 48 Decision B: **unchanged** (DC)",
        "",
        "## Next experiment",
        "",
        report["next_experiment"],
        "",
    ]
    (RESULTS_DIR / "exp49_miller_servo_tran.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ident = prove_identity()
    w = ident.pop("weights")
    pdk = discover_pdk()
    if pdk.get("ciel_current") != PDK_VERSION:
        raise SystemExit("BLOCKED PDK")
    net0, cat, _ = compile_o2_w2_1(w)
    z0 = float(ident["z_at_imax"])
    if not math.isclose(z0, Z_O2, rel_tol=0, abs_tol=1e-12):
        raise SystemExit("BLOCKED z")
    w10, _ = replace_resistors_w(net0, cat, 10.0)
    net = insert_miller(prepend_pdk(w10, "tt", 27.0), MILLER_SIZES, servo=True, vsupply=VSUPPLY)
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    spiceinit_hsa(CIRCUIT_DIR)
    ng = find_ngspice()
    hy = ident["hy_at_imax"]

    print("DC repeat Experiment 48 servo", flush=True)
    dc = run_dc(ng, net, hy, z0, "dc_servo_repeat")

    trans = []
    print("TRAN 500 us trap (samples at 100/200/500 us)", flush=True)
    t500 = run_tran(ng, net, hy, z0, "servo_tran_500u_trap", 500e-6, method=None)
    trans.append(t500)
    if t500.get("failed"):
        print("trap failed; retry Gear 500 us", flush=True)
        t500g = run_tran(ng, net, hy, z0, "servo_tran_500u_gear", 500e-6, method="gear")
        trans.append(t500g)

    print("Independent 200 us repeat", flush=True)
    t200 = run_tran(ng, net, hy, z0, "servo_tran_200u_repeat", 200e-6, method=t500.get("method") if not t500.get("failed") else "gear")
    trans.append(t200)

    decision, label, status, nxt = classify(dc, trans)
    if decision == "D":
        nxt = (
            "Experiment 50: Track B — inventory documented SKY130/PDK amplifier "
            "classes against Experiment 44 budgets. Do not resize this Miller. "
            "Do not invent W/L."
        )
    elif decision == "A":
        nxt = (
            "Experiment 50: temperature and extra frozen vectors on this same "
            "Miller+servo TRAN. Still not silicon."
        )
    report = {
        "experiment_id": "exp49",
        "kind": "Existing Miller+servo 200 us transient discrimination",
        "objective": "DC miss vs settled sampled inference",
        "frozen_baseline": "Exp9 F / catalog o2 W2[1] / Exp41 W=10 / Exp39 Miller sizes",
        "hypothesis": (
            "The integrating servo may reach a different equilibrium in TRAN "
            "than the Experiment 48 DC operating point."
        ),
        "pass_fail": "|y-z|<=1e-3 at 200 us",
        "allowed": ["transient time", "trap vs gear"],
        "forbidden": ["W/L resize", "weight edit", "Python correction"],
        "status": status,
        "decision": decision,
        "decision_label": label,
        "physical_tia_validated": False,
        "silicon": False,
        "resized": False,
        "dc": dc,
        "transients": trans,
        "exp48_dc_y": Y_EXP48_SERVO,
        "exp48_dc_abs_err": ERR_EXP48_SERVO,
        "matching": "UNRESOLVED",
        "solver": {
            "ngspice": str(ng),
            "primary": "tran 1u; default trap, gear fallback",
            "spiceinit": "ngbehavior=hsa skywaterpdk ng_nomodcheck klu",
        },
        "next_experiment": nxt,
        "conclusion": (
            f"Decision {decision} — {label}. "
            f"Experiment 48 DC was y={Y_EXP48_SERVO} (|err|=361.0 mV). "
            "No W/L was changed. Not silicon. PHYSICAL TIA VALIDATED remains no."
        ),
    }
    write_reports(report)
    print(f"Experiment 49 Decision {decision} — {label}", flush=True)


if __name__ == "__main__":
    main()
