"""Experiment 34: OPA189 32-copy residual / fabric isolation helpers.

Frozen Experiment 9 weights. SPICE is the source of truth.
Does not overwrite Experiments 1-33. Does not transistorize Network F.
Does not invent MOS W/L. Does not edit the vendor OPAx189.LIB.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import numpy as np

from compile_xor import PROJECT_ROOT, run_ngspice
from documented_precision_primitive import VENDOR_DIR
from inverter_requirement_extraction import patch_invert_amps
from offset_vg_search import run_ngspice_ex
from test_robustness import extract_all


CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp34_opa189_32copy_mechanism"
RESULTS_DIR = PROJECT_ROOT / "results"
ERROR_LIMIT = 1.0e-3
TIER1_RESIDUAL = 100e-6
R_INV = 10_000.0
R_LOAD_W = 4914.013048625536
VIN_SWING = 2.6081758652291698
OPA189 = VENDOR_DIR / "opa189" / "OPAx189.LIB"
OPA189_NAME = "OPAx189"
TIMEOUT_ISO = 90.0
TIMEOUT_NCOPY = 180.0
TIMEOUT_OPA = 360.0

E_INV = re.compile(
    r"^(E)(inv\S+)amp\s+(\S+)\s+0\s+0\s+(\S+)\s+(\S+)\s*$",
    re.IGNORECASE,
)
RELU_B = re.compile(r"^B(h\d+)relu\s+(\S+)\s+0\s+V\s*=", re.IGNORECASE)
X_OPA = re.compile(
    r"^(X)(invh\d+)inv\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$",
    re.IGNORECASE,
)
C_CL = re.compile(r"^(C)(invh\d+)cl\s+(\S+)\s+0\s+(\S+)\s*$", re.IGNORECASE)
R2_LINE = re.compile(
    r"^(R)(invh\d+)ib\s+(\S+)\s+(\S+)\s+(\S+)\s*$",
    re.IGNORECASE,
)


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


def hidden_y(w, x, rail=15.0) -> np.ndarray:
    z = np.atleast_2d(np.asarray(x, dtype=float)) @ w["W1"].T + w["b1"]
    return np.minimum(float(rail), np.maximum(0.0, z))


def fabric_load_ohm(netlist: str, dest_node: str, mid: str) -> float:
    g = 0.0
    for raw in netlist.splitlines():
        parts = raw.split()
        if len(parts) < 4 or parts[0][0] not in "Rr":
            continue
        a, b = parts[1], parts[2]
        if dest_node in (a, b) and mid not in (a, b):
            try:
                g += 1.0 / float(parts[3])
            except ValueError:
                continue
    return 1e12 if g <= 0 else 1.0 / g


def inject_lines(netlist: str, extra: list[str]) -> str:
    if not extra:
        return netlist
    out = []
    inserted = False
    for raw in netlist.splitlines():
        s = raw.strip()
        if (not inserted) and s and not s.startswith("*"):
            out.extend(extra)
            out.append("")
            inserted = True
        out.append(raw)
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(out) + ending


def inject_options(netlist: str, option_line: str | None) -> str:
    if not option_line:
        return netlist
    return inject_lines(netlist, [option_line])


def patch_opa189(netlist: str, stages: list[dict], independent=False) -> str:
    return patch_invert_amps(
        netlist,
        stages,
        "opa_indep" if independent else "opa",
        opa_path=OPA189,
        opa_name=OPA189_NAME,
        independent_supplies=independent,
    )


def replace_relu_with_vsrc(netlist: str, tags: set[str] | None = None) -> str:
    """Replace selected (or all) hidden ReLU B-sources with V sources.

    tags are 'h1'..'h32'. The invert src node stays the same name.
    """
    out = []
    for raw in netlist.splitlines():
        m = RELU_B.match(raw.strip())
        if m and (tags is None or m.group(1).lower() in tags):
            tag, node = m.group(1), m.group(2)
            out.append(f"V{tag}y {node} 0 DC 0")
        else:
            out.append(raw)
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(out) + ending


def force_r1_r2(netlist: str, stages: list[dict], r1=R_INV, r2=R_INV) -> str:
    names = {}
    for s in stages:
        if s.get("r1_name"):
            names[s["r1_name"]] = float(r1)
        if s.get("r2_name"):
            names[s["r2_name"]] = float(r2)
    out = []
    for raw in netlist.splitlines():
        parts = raw.split()
        if len(parts) >= 4 and parts[0] in names:
            out.append(f"{parts[0]} {parts[1]} {parts[2]} {names[parts[0]]:.15g}")
        else:
            out.append(raw)
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(out) + ending


def detach_dest_fabric(netlist: str, stages: list[dict], r_load: float) -> str:
    """Move non-R2 dest resistors off the OPA output; attach a single Rload to 0."""
    dests = {s["dest"]: s for s in stages}
    mids = {s["dest"]: s["mid"] for s in stages}
    out = []
    for raw in netlist.splitlines():
        parts = raw.split()
        if len(parts) >= 4 and parts[0][0] in "Rr":
            a, b = parts[1], parts[2]
            hit = None
            other = None
            if a in dests and b != mids[a]:
                hit, other = a, b
            elif b in dests and a != mids[b]:
                hit, other = b, a
            if hit is not None:
                dump = f"{hit}fab"
                if a == hit:
                    out.append(f"{parts[0]} {dump} {other} {' '.join(parts[3:])}")
                else:
                    out.append(f"{parts[0]} {other} {dump} {' '.join(parts[3:])}")
                continue
        out.append(raw)
    for s in stages:
        out.append(f"R{s['stem']}iso {s['dest']} 0 {float(r_load):.15g}")
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(out) + ending


def set_cl_cap(netlist: str, cap_f: float) -> str:
    out = []
    for raw in netlist.splitlines():
        m = C_CL.match(raw.strip())
        if m:
            out.append(f"C{m.group(2)}cl {m.group(3)} 0 {float(cap_f):.15g}")
        else:
            out.append(raw)
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(out) + ending


def buffer_opa_output(netlist: str, stages: list[dict]) -> str:
    """LEVEL 2 unity VCVS: OPA drives destloc; fabric still sees dest.

    R2 and Ccl move to destloc so the invert loop does not include W2.
    """
    dests = {s["dest"]: s for s in stages}
    out = []
    for raw in netlist.splitlines():
        s = raw.strip()
        m = X_OPA.match(s)
        if m and any(m.group(7) == st["dest"] for st in stages):
            loc = f"{m.group(7)}loc"
            out.append(
                f"X{m.group(2)}inv {m.group(3)} {m.group(4)} {m.group(5)} "
                f"{m.group(6)} {loc} {m.group(8)}"
            )
            out.append(f"E{m.group(2)}buf {m.group(7)} 0 {loc} 0 1")
            continue
        m = R2_LINE.match(s)
        if m:
            stem = m.group(2)
            st = next((x for x in stages if x["stem"] == stem), None)
            if st:
                loc = f"{st['dest']}loc"
                a = loc if m.group(3) == st["dest"] else m.group(3)
                b = loc if m.group(4) == st["dest"] else m.group(4)
                out.append(f"R{stem}ib {a} {b} {m.group(5)}")
                continue
        m = C_CL.match(s)
        if m:
            dest_n = m.group(3)
            if dest_n in dests:
                out.append(f"C{m.group(2)}cl {dest_n}loc 0 {m.group(4)}")
                continue
        out.append(raw)
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(out) + ending


def force_nodes_zero(netlist: str, nodes: list[str], prefix="vfix") -> str:
    extra = [f"V{prefix}{i} {n} 0 DC 0" for i, n in enumerate(nodes, start=1)]
    return inject_lines(netlist, extra)


def output_sum_nodes(n_out: int) -> list[str]:
    return [f"o{k}p" for k in range(1, n_out + 1)]


def hidden_sum_nodes(n_hidden: int) -> list[str]:
    return [f"h{j}p" for j in range(1, n_hidden + 1)]


def isolated_n_copy(
    n: int,
    vin: float,
    r_load: float = R_LOAD_W,
    shared_supply: bool = True,
    cl_f: float = 1e-12,
    vcm: float = 0.0,
    r_src: float = 0.0,
    option_line: str | None = None,
    t_hold: float | None = None,
    vins: list[float] | None = None,
    r_loads: list[float] | None = None,
) -> str:
    """N independent gain=-1 OPA189 cells. No neural fabric."""
    lines = [
        f"* Exp 34 isolated N={n} shared={shared_supply} Vin={vin:g} Rload={r_load:g}",
        f'.include "{OPA189.resolve().as_posix()}"',
    ]
    if option_line:
        lines.append(option_line)
    if shared_supply:
        lines += ["Vdd vdd 0 DC 15", "Vss vss 0 DC -15"]
    for i in range(1, n + 1):
        vi = float(vins[i - 1]) if vins is not None else float(vin)
        rl = float(r_loads[i - 1]) if r_loads is not None else float(r_load)
        inn, mid, out = f"in{i}", f"mid{i}", f"out{i}"
        drv = f"src{i}"
        if r_src > 0:
            lines.append(f"Vin{i} {drv} 0 DC {vi:.15g}")
            lines.append(f"Rsrc{i} {drv} {inn} {float(r_src):.15g}")
        else:
            lines.append(f"Vin{i} {inn} 0 DC {vi:.15g}")
        lines.append(f"Vcm{i} inp{i} 0 DC {float(vcm):.15g}")
        lines += [
            f"R1_{i} {inn} {mid} {R_INV:.15g}",
            f"R2_{i} {out} {mid} {R_INV:.15g}",
            f"Rload{i} {out} 0 {rl:.15g}",
        ]
        if shared_supply:
            vdd, vss = "vdd", "vss"
        else:
            vdd, vss = f"vdd{i}", f"vss{i}"
            lines += [f"Vdd{i} {vdd} 0 DC 15", f"Vss{i} {vss} 0 DC -15"]
        lines += [
            f"Xinv{i} inp{i} {mid} {vdd} {vss} {out} {OPA189_NAME}",
            f"Ccl{i} {out} 0 {float(cl_f):.15g}",
        ]
    extra = []
    for i in range(1, n + 1):
        extra += [
            f"print v(out{i})",
            f"print v(mid{i})",
            f"print v(in{i})",
            f"print v(inp{i})",
            f"print i(Rload{i})",
        ]
    if shared_supply:
        extra.append("print i(Vdd)")
    elif n >= 1:
        extra.append("print i(Vdd1)")
    if t_hold is None:
        ctrl = [".control", "set numdgt=15", "op", *extra, ".endc", ".end", ""]
    else:
        meas = []
        for i in range(1, n + 1):
            meas += [
                f"meas tran vout{i}_end find v(out{i}) at={t_hold:.15g}",
                f"print vout{i}_end",
                f"meas tran vmid{i}_end find v(mid{i}) at={t_hold:.15g}",
                f"print vmid{i}_end",
            ]
        ctrl = [
            ".control",
            "set numdgt=15",
            f"tran {max(t_hold / 200.0, 1e-7):.15g} {t_hold:.15g}",
            *meas,
            ".endc",
            ".end",
            "",
        ]
    return "\n".join(lines + ctrl)


def isolated_one_stage_from_fabric(
    net0: str,
    stage: dict,
    vin: float,
    far_v: float = 0.0,
    cl_f: float = 1e-12,
) -> str:
    """One OPA189 with that stage's actual dest resistors, far side = far_v."""
    dest_n, mid, src = stage["dest"], stage["mid"], stage["src"]
    r1 = float(stage.get("r1") or R_INV)
    r2 = float(stage.get("r2") or R_INV)
    lines = [
        f"* Exp 34 one-stage actual dest R from fabric stem={stage['stem']}",
        f'.include "{OPA189.resolve().as_posix()}"',
        "Vdd vdd 0 DC 15",
        "Vss vss 0 DC -15",
        f"Vin {src} 0 DC {float(vin):.15g}",
        f"R1 {src} {mid} {r1:.15g}",
        f"R2 {dest_n} {mid} {r2:.15g}",
        f"Xinv 0 {mid} vdd vss {dest_n} {OPA189_NAME}",
        f"Ccl {dest_n} 0 {float(cl_f):.15g}",
    ]
    if abs(far_v) > 0:
        lines.append(f"Vfar far 0 DC {float(far_v):.15g}")
        far = "far"
    else:
        far = "0"
    k = 0
    for raw in net0.splitlines():
        parts = raw.split()
        if len(parts) < 4 or parts[0][0] not in "Rr":
            continue
        a, b = parts[1], parts[2]
        if dest_n in (a, b) and mid not in (a, b):
            k += 1
            other = b if a == dest_n else a
            # keep dest, retarget the far node to the common far voltage
            lines.append(f"Rfab{k} {dest_n} {far} {parts[3]}")
            _ = other
    lines += [
        ".control",
        "set numdgt=15",
        "op",
        f"print v({dest_n})",
        f"print v({mid})",
        f"print v({src})",
        "print i(Vdd)",
        ".endc",
        ".end",
        "",
    ]
    return "\n".join(lines)


def run_spice(ng, path: Path, timeout: float, pspice=True):
    t0 = time.perf_counter()
    result = (
        run_ngspice_ex(ng, path, timeout=timeout, pspice=pspice)
        if pspice
        else run_ngspice(ng, path, timeout=timeout)
    )
    text = f"{result.stdout or ''}\n{result.stderr or ''}"
    from benchmark_scaling import detect_spice_failure

    fail = detect_spice_failure(result)
    rec = {
        "failed": bool(fail),
        "failure_reason": fail,
        "spice_s": time.perf_counter() - t0,
        "n_conv_warn": text.lower().count("without convergence"),
    }
    if fail:
        rec["log_tail"] = text[-400:]
    return rec, text


def eval_isolated_ncopy(ng, netlist: str, path: Path, n: int, vins, timeout=TIMEOUT_NCOPY):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(netlist, encoding="utf-8")
    rec, text = run_spice(ng, path, timeout)
    if rec["failed"]:
        return rec
    if isinstance(vins, (int, float)):
        vins = [float(vins)] * n
    copies = []
    for i in range(1, n + 1):
        vo = extract_all(text, f"v(out{i})")
        vm = extract_all(text, f"v(mid{i})")
        vin_n = extract_all(text, f"v(in{i})")
        vp = extract_all(text, f"v(inp{i})")
        if not vo:
            vo = extract_all(text, f"vout{i}_end")
            vm = extract_all(text, f"vmid{i}_end")
        if not vo:
            rec.update({"failed": True, "failure_reason": f"missing v(out{i})"})
            rec["log_tail"] = text[-300:]
            return rec
        vout = float(vo[-1])
        vmid = float(vm[-1]) if vm else None
        vin = float(vin_n[-1]) if vin_n else float(vins[i - 1])
        vplus = float(vp[-1]) if vp else 0.0
        err = vout + vin
        copies.append(
            {
                "i": i,
                "vin": vin,
                "v_out": vout,
                "v_mid": vmid,
                "v_plus": vplus,
                "v_minus": vmid,
                "abs_err": abs(err),
                "vdiff": None if vmid is None else abs(vmid - vplus),
            }
        )
    rec["copies"] = copies
    rec["mean_residual"] = float(np.mean([c["abs_err"] for c in copies]))
    rec["max_residual"] = float(np.max([c["abs_err"] for c in copies]))
    rec["mean_vmid"] = float(np.nanmean([abs(c["v_mid"]) for c in copies if c["v_mid"] is not None]))
    rec["mean_vdiff"] = float(np.nanmean([c["vdiff"] for c in copies if c["vdiff"] is not None]))
    rec["tier1"] = rec["max_residual"] < TIER1_RESIDUAL
    idd = extract_all(text, "i(vdd)") or extract_all(text, "i(vdd1)")
    rec["i_vdd"] = float(idd[-1]) if idd else None
    return rec


def eval_named_nodes(ng, netlist: str, path: Path, vin: float, dest_n: str, mid: str, src: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(netlist, encoding="utf-8")
    rec, text = run_spice(ng, path, TIMEOUT_ISO)
    if rec["failed"]:
        return rec
    vo = extract_all(text, f"v({dest_n})")
    vm = extract_all(text, f"v({mid})")
    vi = extract_all(text, f"v({src})")
    if not vo:
        rec.update({"failed": True, "failure_reason": f"missing v({dest_n})", "log_tail": text[-300:]})
        return rec
    rec["v_out"] = float(vo[-1])
    rec["v_mid"] = float(vm[-1]) if vm else None
    rec["v_in"] = float(vi[-1]) if vi else float(vin)
    rec["abs_err"] = abs(rec["v_out"] + rec["v_in"])
    rec["tier1"] = rec["abs_err"] < TIER1_RESIDUAL
    idd = extract_all(text, "i(vdd)")
    rec["i_vdd"] = float(idd[-1]) if idd else None
    return rec


def rich_probe_control(inputs, n_out: int, stages: list[dict], sum_nodes=None) -> str:
    lines = [".control", "set numdgt=15"]
    for x in inputs:
        for i, xi in enumerate(np.atleast_1d(x), start=1):
            lines.append(f"alter Vin{i} DC {float(xi):.15g}")
        lines.append("op")
        for k in range(1, n_out + 1):
            lines.append(f"print v(o{k}lin)")
        for s in stages:
            lines.append(f"print v({s['src']})")
            lines.append(f"print v({s['dest']})")
            lines.append(f"print v({s['mid']})")
            if s.get("r1_name"):
                lines.append(f"print i({s['r1_name']})")
            if s.get("r2_name"):
                lines.append(f"print i({s['r2_name']})")
        if sum_nodes:
            for n in sum_nodes:
                lines.append(f"print v({n})")
        lines.append("print i(Vdd)")
    lines.extend([".endc", "", ".end", ""])
    return "\n".join(lines)


def eval_f_rich(ng, net, spec, x, y, stages, path, timeout=TIMEOUT_OPA, sum_nodes=None):
    from benchmark_scaling import (
        classification_labels,
        detect_spice_failure,
        error_stats,
        parse_physical_outputs,
    )

    head, sep, _ = net.partition(".control")
    if not sep:
        return {"failed": True, "failure_reason": "no .control"}
    ctrl = rich_probe_control(x, spec["n_out"], stages, sum_nodes=sum_nodes)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(head.rstrip() + "\n" + ctrl, encoding="utf-8")
    t0 = time.perf_counter()
    result = run_ngspice_ex(ng, path, timeout=timeout, pspice=True)
    text = f"{result.stdout or ''}\n{result.stderr or ''}"
    fail = detect_spice_failure(result)
    rec = {"failed": bool(fail), "failure_reason": fail, "spice_s": time.perf_counter() - t0}
    if fail:
        rec["log_tail"] = text[-500:]
        return rec
    try:
        physical = parse_physical_outputs(text, len(x), spec["n_out"])
    except RuntimeError as exc:
        rec.update({"failed": True, "failure_reason": str(exc), "log_tail": text[-400:]})
        return rec
    st = error_stats(physical, y)
    rec.update(st)
    rec["accuracy"] = float(np.mean(classification_labels(physical) == classification_labels(y)))
    rec["analog_pass"] = st["mae"] <= ERROR_LIMIT
    rec["n_conv_warn"] = text.lower().count("without convergence")
    residual_matrix = []
    vmid_matrix = []
    vin_matrix = []
    probes = []
    for s in stages:
        vin = np.asarray(extract_all(text, f"v({s['src']})"), dtype=float)
        vout = np.asarray(extract_all(text, f"v({s['dest']})"), dtype=float)
        vmid = np.asarray(extract_all(text, f"v({s['mid']})"), dtype=float)
        if len(vin) != len(x) or len(vout) != len(x):
            continue
        if len(vmid) != len(x):
            vmid = np.full(len(x), np.nan)
        err = vout + vin
        residual_matrix.append(err.tolist())
        vmid_matrix.append(vmid.tolist())
        vin_matrix.append(vin.tolist())
        ir1 = extract_all(text, f"i({s['r1_name']})") if s.get("r1_name") else []
        ir2 = extract_all(text, f"i({s['r2_name']})") if s.get("r2_name") else []
        probes.append(
            {
                "stem": s["stem"],
                "r_load_ohm": s.get("r_load_ohm"),
                "r_fab_ohm": fabric_load_ohm(net, s["dest"], s["mid"]),
                "err_mae": float(np.mean(np.abs(err))),
                "err_max": float(np.max(np.abs(err))),
                "err_mean": float(np.mean(err)),
                "vin_max": float(np.max(np.abs(vin))),
                "vmid_mae": float(np.nanmean(np.abs(vmid))),
                "vdiff_mae": float(np.nanmean(np.abs(vmid))),
                "i_r1_mae": float(np.mean(np.abs(ir1))) if len(ir1) == len(x) else None,
                "i_r2_mae": float(np.mean(np.abs(ir2))) if len(ir2) == len(x) else None,
            }
        )
    rec["probes"] = probes
    if probes:
        rec["mean_invert_residual"] = float(np.mean([p["err_mae"] for p in probes]))
        rec["max_invert_residual"] = float(np.max([p["err_max"] for p in probes]))
        rec["mean_vmid"] = float(np.mean([p["vmid_mae"] for p in probes]))
        rec["residual_by_vector"] = np.mean(np.abs(np.asarray(residual_matrix)), axis=0).tolist()
        rec["residual_std_across_stages"] = float(
            np.mean(np.std(np.asarray(residual_matrix), axis=0))
        )
        rec["shared_pedestal"] = rec["residual_std_across_stages"] < 0.2 * rec["mean_invert_residual"]
    rec["sum_nodes"] = {}
    if sum_nodes:
        for n in sum_nodes:
            vals = extract_all(text, f"v({n})")
            if vals:
                rec["sum_nodes"][n] = {
                    "mae": float(np.mean(np.abs(vals))),
                    "max": float(np.max(np.abs(vals))),
                }
    idd = extract_all(text, "i(vdd)")
    if idd:
        rec["i_vdd_mae"] = float(np.mean(np.abs(idd)))
    rec["n_probe_stages"] = len(probes)
    return rec


def ideal_hy_control(inputs, hy, n_out: int, stages: list[dict]) -> str:
    lines = [".control", "set numdgt=15"]
    for vi, x in enumerate(inputs):
        for i, xi in enumerate(np.atleast_1d(x), start=1):
            lines.append(f"alter Vin{i} DC {float(xi):.15g}")
        for j in range(hy.shape[1]):
            lines.append(f"alter Vh{j + 1}y DC {float(hy[vi, j]):.15g}")
        lines.append("op")
        for k in range(1, n_out + 1):
            lines.append(f"print v(o{k}lin)")
        for s in stages:
            lines.append(f"print v({s['src']})")
            lines.append(f"print v({s['dest']})")
            lines.append(f"print v({s['mid']})")
    lines.extend([".endc", "", ".end", ""])
    return "\n".join(lines)


def eval_f_ideal_hy(ng, net, spec, x, y, hy, stages, path, timeout=TIMEOUT_OPA):
    from benchmark_scaling import (
        classification_labels,
        detect_spice_failure,
        error_stats,
        parse_physical_outputs,
    )

    head, sep, _ = net.partition(".control")
    if not sep:
        return {"failed": True, "failure_reason": "no .control"}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(head.rstrip() + "\n" + ideal_hy_control(x, hy, spec["n_out"], stages), encoding="utf-8")
    t0 = time.perf_counter()
    result = run_ngspice_ex(ng, path, timeout=timeout, pspice=True)
    text = f"{result.stdout or ''}\n{result.stderr or ''}"
    fail = detect_spice_failure(result)
    rec = {"failed": bool(fail), "failure_reason": fail, "spice_s": time.perf_counter() - t0}
    if fail:
        rec["log_tail"] = text[-500:]
        return rec
    try:
        physical = parse_physical_outputs(text, len(x), spec["n_out"])
        st = error_stats(physical, y)
        rec.update(st)
        rec["accuracy"] = float(np.mean(classification_labels(physical) == classification_labels(y)))
        rec["analog_pass"] = st["mae"] <= ERROR_LIMIT
    except RuntimeError as exc:
        rec.update({"mae": None, "analog_pass": False, "parse_error": str(exc)})
    probes = []
    for s in stages:
        vin = extract_all(text, f"v({s['src']})")
        vout = extract_all(text, f"v({s['dest']})")
        vmid = extract_all(text, f"v({s['mid']})")
        if len(vin) != len(x) or len(vout) != len(x):
            continue
        err = np.asarray(vout, float) + np.asarray(vin, float)
        probes.append(
            {
                "stem": s["stem"],
                "err_mae": float(np.mean(np.abs(err))),
                "err_max": float(np.max(np.abs(err))),
                "vmid_mae": float(np.mean(np.abs(vmid))) if len(vmid) == len(x) else None,
            }
        )
    rec["probes"] = probes
    if probes:
        rec["mean_invert_residual"] = float(np.mean([p["err_mae"] for p in probes]))
        rec["max_invert_residual"] = float(np.max([p["err_max"] for p in probes]))
        rec["mean_vmid"] = float(np.mean([p["vmid_mae"] or 0.0 for p in probes]))
    return rec


def slim_probe(rec: dict, keep_worst=8) -> dict:
    out = {
        k: rec.get(k)
        for k in (
            "mae",
            "max_abs_error",
            "accuracy",
            "analog_pass",
            "failed",
            "failure_reason",
            "spice_s",
            "mean_invert_residual",
            "max_invert_residual",
            "mean_vmid",
            "residual_by_vector",
            "residual_std_across_stages",
            "shared_pedestal",
            "i_vdd_mae",
            "n_conv_warn",
            "n_probe_stages",
            "sum_nodes",
        )
        if k in rec
    }
    probes = rec.get("probes") or []
    probes_s = sorted(probes, key=lambda p: p.get("err_max") or 0.0, reverse=True)
    out["worst_probes"] = probes_s[:keep_worst]
    out["n_probes"] = len(probes)
    return out
