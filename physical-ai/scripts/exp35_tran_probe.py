"""Probe TRAN settings on Experiment 35 vectors that timed out at 90 s."""

from __future__ import annotations

from benchmark_scaling import generate_inputs
from compile_xor import find_ngspice
from exp32_hidden_inverter_primitive import software_for
from exp35_n32_qualification import dest, eval_fabric, fmt, option_line
from hardware_constrained_compiler import load_frozen_model
from inverter_requirement_extraction import compile_f, hidden_stages
from opa189_fabric_isolation import patch_opa189


def main() -> None:
    ng = find_ngspice()
    w = load_frozen_model("F")
    net0, _c, spec = compile_f(w)
    hidden = hidden_stages(net0)
    x = generate_inputs(spec["n_in"], 40, "exp24_F")[:12]
    y = software_for(w, x)
    net = patch_opa189(net0, hidden)
    i = 0
    combos = [
        ("gear", option_line(method="gear"), None, False),
        ("gear_rt5e-5", option_line(method="gear", reltol=5e-5), None, False),
        ("trap_rt1e-6", option_line(reltol=1e-6), None, False),
        ("gear_tstep5e-6", option_line(method="gear", reltol=5e-5), 5e-6, False),
        ("uic_gear", option_line(method="gear", reltol=5e-5), None, True),
        ("gear_maxstep", option_line(method="gear", reltol=5e-5, maxstep=1e-6), None, False),
    ]
    for name, opt, tstep, uic in combos:
        rec = eval_fabric(
            ng,
            net,
            spec,
            x[i : i + 1],
            y[i : i + 1],
            dest("p4", "probe", name),
            options=opt,
            mode="tran",
            t_hold=2e-4,
            tstep=tstep,
            uic=uic,
            timeout=45.0,
        )
        print(
            f"{name} MAE={fmt(rec.get('mae'))} fail={rec.get('failed')} "
            f"reason={rec.get('failure_reason')} t={fmt(rec.get('spice_s'), '.1f')}",
            flush=True,
        )


if __name__ == "__main__":
    main()
