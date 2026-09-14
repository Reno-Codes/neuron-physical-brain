"""Probe UIC TRAN and E-source invert substitution on the Exp64 XOR deck."""

from __future__ import annotations

from pathlib import Path

from compile_xor import PROJECT_ROOT, find_ngspice
from exp45_documented_tia import spiceinit_behavior
from offset_vg_search import run_ngspice_ex

SRC = PROJECT_ROOT / "circuits" / "exp64_xor" / "xor_0.cir"
DEST = PROJECT_ROOT / "circuits" / "exp64_probe"


def replace_inverts_with_e(net: str) -> str:
    """Replace OPA189 unity inverters with E-source gain=-1. TIA/ReLU stay."""
    out = []
    skip_block = False
    for raw in net.splitlines():
        s = raw.strip()
        if s.startswith("* Inverter_OPA189"):
            # * Inverter_OPA189 inv1: in1n = -in1
            parts = s.split()
            # tag dest = -src  from "inv1: in1n = -in1"
            skip_block = True
            dest = parts[3]
            src = parts[5].lstrip("-")
            tag = parts[2].rstrip(":")
            out.append(s + "  (E-source probe)")
            out.append(f"E{tag} {dest} 0 {src} 0 -1")
            continue
        if skip_block:
            if s.startswith("C") and "1e-12" in s:
                skip_block = False
            continue
        out.append(raw)
    return "\n".join(out) + "\n"


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    spiceinit_behavior(DEST, "ps")
    ng = find_ngspice()
    net = SRC.read_text(encoding="utf-8")

    uic = net.replace(
        ".control\nset numdgt=15\nop\n",
        ".control\nset numdgt=15\ntran 5u 2m uic\n",
    )
    p1 = DEST / "xor0_uic.cir"
    p1.write_text(uic, encoding="utf-8")
    print("==== UIC TRAN 2ms ====", flush=True)
    r1 = run_ngspice_ex(ng, p1, timeout=180.0, pspice=True)
    t1 = f"{r1.stdout or ''}\n{r1.stderr or ''}"
    for line in t1.splitlines():
        if any(k in line.lower() for k in ("error", "timestep", "o1lin", "abort", "data rows")):
            print(line, flush=True)
    print("rc", r1.returncode, flush=True)

    e_net = replace_inverts_with_e(net)
    p2 = DEST / "xor0_einv.cir"
    p2.write_text(e_net, encoding="utf-8")
    print("==== E-source inverts + OP ====", flush=True)
    r2 = run_ngspice_ex(ng, p2, timeout=180.0, pspice=True)
    t2 = f"{r2.stdout or ''}\n{r2.stderr or ''}"
    for line in t2.splitlines():
        if any(k in line.lower() for k in ("error", "timestep", "v(o1lin)", "v(h1", "abort", "singular")):
            print(line, flush=True)
    print("rc", r2.returncode, flush=True)


if __name__ == "__main__":
    main()
