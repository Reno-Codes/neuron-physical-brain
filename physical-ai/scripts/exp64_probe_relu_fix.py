"""Probe: TRAN on Exp63 single-diode XOR, and isolated inverting rectifier."""

from __future__ import annotations

from pathlib import Path

from compile_xor import PROJECT_ROOT, find_ngspice
from exp45_documented_tia import spiceinit_behavior
from exp62_physical_relu import DIODE_LIB, OPA189_LIB
from offset_vg_search import run_ngspice_ex

DEST = PROJECT_ROOT / "circuits" / "exp64_probe"


def invert_rect(vin: float) -> str:
    opa = OPA189_LIB.as_posix()
    dlib = DIODE_LIB.as_posix()
    return f"""* inverting precision rectifier Vout=-max(Vin,0)
.include "{opa}"
.include "{dlib}"
Vin in 0 DC {vin:.15g}
Vdd vdd 0 DC 15
Vss vss 0 DC -15
R1 in inn 10000
Xamp 0 inn vdd vss amp OPAx189
Xd1 inn amp 1N4148
Xd2 amp out 1N4148
Rf out inn 10000
Rload out 0 10000
Cload out 0 1p
.control
set numdgt=15
op
print v(in) v(out) v(amp)
print i(Vdd)
.endc
.end
"""


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    spiceinit_behavior(DEST, "ps")
    ng = find_ngspice()
    src = PROJECT_ROOT / "circuits" / "exp63_xor_mvp" / "xor_0.cir"
    net = src.read_text(encoding="utf-8")
    net = net.replace(
        ".control\nset numdgt=15\nop\n",
        ".control\nset numdgt=15\ntran 2u 400u\n",
    )
    path = DEST / "xor0_tran.cir"
    path.write_text(net, encoding="utf-8")
    print("==== TRAN 400us on Exp63 xor_0 ====", flush=True)
    r = run_ngspice_ex(ng, path, timeout=180.0, pspice=True)
    text = f"{r.stdout or ''}\n{r.stderr or ''}"
    print(text[-2500:], flush=True)
    print("return", r.returncode, flush=True)

    print("==== isolated inverting rectifier ====", flush=True)
    for vin in (-2.0, -0.5, 0.0, 0.5, 0.935, 1.0):
        p = DEST / f"invrect_{vin:+.3f}.cir".replace("+", "p").replace("-", "m")
        p.write_text(invert_rect(vin), encoding="utf-8")
        rr = run_ngspice_ex(ng, p, timeout=60.0, pspice=True)
        tt = f"{rr.stdout or ''}\n{rr.stderr or ''}"
        print(f"--- vin={vin} rc={rr.returncode} ---", flush=True)
        for line in tt.splitlines():
            if "v(" in line.lower() or "error" in line.lower() or "timestep" in line.lower():
                print(line, flush=True)


if __name__ == "__main__":
    main()
