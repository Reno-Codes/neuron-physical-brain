"""Find 0.1% E192 series/parallel combinations for compiled XOR resistors."""

from __future__ import annotations

import csv
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CSV_IN = PROJECT_ROOT / "physical_design" / "xor_2_4_1" / "resistor_values.csv"
HW = PROJECT_ROOT / "hardware" / "mvp_v1_xor_2_4_1"

E192 = [
    100, 101, 102, 104, 105, 106, 107, 109, 110, 111, 113, 114, 115, 117, 118, 120,
    121, 123, 124, 126, 127, 129, 130, 132, 133, 135, 137, 138, 140, 142, 143, 145,
    147, 149, 150, 152, 154, 156, 158, 160, 162, 164, 165, 167, 169, 172, 174, 176,
    178, 180, 182, 184, 187, 189, 191, 193, 196, 198, 200, 203, 205, 208, 210, 213,
    215, 218, 221, 223, 226, 229, 232, 234, 237, 240, 243, 246, 249, 252, 255, 258,
    261, 264, 267, 271, 274, 277, 280, 284, 287, 291, 294, 298, 301, 305, 309, 312,
    316, 320, 324, 328, 332, 336, 340, 344, 348, 352, 357, 361, 365, 370, 374, 379,
    383, 388, 392, 397, 402, 407, 412, 417, 422, 427, 432, 437, 442, 448, 453, 459,
    464, 470, 475, 481, 487, 493, 499, 505, 511, 517, 523, 530, 536, 542, 549, 556,
    562, 569, 576, 583, 590, 597, 604, 612, 619, 626, 634, 642, 649, 657, 665, 673,
    681, 690, 698, 706, 715, 723, 732, 741, 750, 759, 768, 777, 787, 796, 806, 816,
    825, 835, 845, 856, 866, 876, 887, 898, 909, 920, 931, 942, 953, 965, 976, 988,
]


def e192_values(r_min: float = 10.0, r_max: float = 1.0e7) -> list[float]:
    out: list[float] = []
    decade = 0.1
    while decade <= r_max:
        for m in E192:
            v = m * decade / 100.0
            if r_min <= v <= r_max:
                out.append(v)
        decade *= 10.0
    return sorted(set(round(v, 10) for v in out))


def fmt_r(v: float) -> str:
    if v >= 1e6:
        return f"{v/1e6:.6g}M"
    if v >= 1e3:
        return f"{v/1e3:.6g}k"
    return f"{v:.6g}"


def best_combo(target: float, catalog: list[float], rel_budget: float = 0.001) -> dict:
    nearest = min(catalog, key=lambda v: abs(v - target))
    single_rel = abs(nearest - target) / target
    best = {
        "kind": "single",
        "parts": [nearest],
        "realized": nearest,
        "rel_error": single_rel,
        "within_0p1pct": single_rel <= rel_budget,
    }
    if single_rel <= rel_budget:
        return best
    # series of two, search near target
    # limit inner loop: values between target*0.05 and target*0.95
    lo, hi = target * 0.02, target * 0.98
    cands = [v for v in catalog if lo <= v <= hi]
    # also include small adders
    adders = [v for v in catalog if v < target * 0.2]
    pool_a = cands if len(cands) < 400 else [v for v in catalog if abs(v - target / 2) / target < 0.6]
    for a in pool_a:
        b_target = target - a
        b = min(catalog, key=lambda v: abs(v - b_target))
        realized = a + b
        rel = abs(realized - target) / target
        if rel < best["rel_error"]:
            parts = sorted([a, b])
            best = {
                "kind": "series",
                "parts": parts,
                "realized": realized,
                "rel_error": rel,
                "within_0p1pct": rel <= rel_budget,
            }
            if rel <= rel_budget * 0.2:
                break
    # parallel of two: 1/R = 1/a + 1/b => b = a*R/(a-R), a > R
    for a in [v for v in catalog if v > target * 1.02 and v < target * 8]:
        b_t = a * target / (a - target)
        if b_t <= 0:
            continue
        b = min(catalog, key=lambda v: abs(v - b_t))
        realized = 1.0 / (1.0 / a + 1.0 / b)
        rel = abs(realized - target) / target
        if rel < best["rel_error"]:
            best = {
                "kind": "parallel",
                "parts": sorted([a, b]),
                "realized": realized,
                "rel_error": rel,
                "within_0p1pct": rel <= rel_budget,
            }
    return best


def main() -> None:
    catalog = e192_values()
    HW.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader(CSV_IN.open(encoding="utf-8")))
    out = []
    for row in rows:
        target = float(row["R_exact_ohm"])
        combo = best_combo(target, catalog)
        rec = {
            "ref": row["ref"],
            "role": row["role"],
            "layer": row.get("layer", ""),
            "from": row.get("from", ""),
            "to": row.get("to", ""),
            "weight": row.get("weight", ""),
            "exact_ohm": target,
            "e96_ohm": float(row["R_e96_ohm"]) if row["R_e96_ohm"] else None,
            "preferred": combo,
            "parts_fmt": "+".join(fmt_r(p) for p in combo["parts"])
            if combo["kind"] == "series"
            else "||".join(fmt_r(p) for p in combo["parts"])
            if combo["kind"] == "parallel"
            else fmt_r(combo["parts"][0]),
        }
        out.append(rec)
        print(
            f"{row['ref']:10} {target:12.6g}  {rec['parts_fmt']:20}  "
            f"{combo['kind']:8}  {combo['rel_error']*100:.4f}%  "
            f"{'OK' if combo['within_0p1pct'] else 'MISS'}",
            flush=True,
        )
    (HW / "resistor_combos.json").write_text(json.dumps(out, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
