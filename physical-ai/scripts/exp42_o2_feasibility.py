"""Experiment 42: o2 1 mV feasibility boundary.

Experiments 39, 40, and 41 are CLOSED and are not modified.
No SPICE. No transistor search. No resistor-geometry change.
No weight or acceptance-bar change. Matching is not claimed.

Uses only the established catalog o2 identity and Experiment 41
additive split. Projections are labeled analytical or
Exp41-anchored. They are not demonstrated circuit results.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from compile_xor import PROJECT_ROOT

RESULTS_DIR = PROJECT_ROOT / "results"
REPORT_JSON = RESULTS_DIR / "exp42_o2_feasibility.json"
REPORT_MD = RESULTS_DIR / "exp42_o2_feasibility.md"

# --- Established facts (Exp40 / Exp41). Do not invent. ---
TAG = "o2"
SIM_TARGET = "o2 / W2[1]"
RFG = 140.89398023224967
Z = 2.459489570880132
EPS = 1.0e-3
A0 = 1.0e5

Y_EXP40 = 2.45254388951
Y_IDEAL = 2.457433737388
Y_W10 = 2.458037812913
Y_MILLER = 1.832237285033

ERR_EXP40 = Y_EXP40 - Z
ERR_IDEAL = Y_IDEAL - Z
ERR_W10 = Y_W10 - Z
ERR_MILLER = Y_MILLER - Z

R_W1 = Y_EXP40 - Y_IDEAL
R_W10 = Y_W10 - Y_IDEAL

# Official SKY130A xhigh_po Pelgrom A from Experiment 39 model card.
# Matching geometry only — not a deterministic-error design.
XHIGH_PELGROM = 0.0347
MATCH_SIGMA = 0.00075
RF_W1_WL_UM2 = 15.72


def k_of(A: float) -> float:
    return A / (A + 1.0 + RFG)


def err_analytical(A: float) -> float:
    """(k·z − z) from the established closed-loop identity."""
    return (k_of(A) - 1.0) * Z


def a_required_analytical() -> float:
    """Minimum A such that |k·z − z| <= EPS."""
    return Z * (1.0 + RFG) / EPS - 1.0 - RFG


def err_ideal_scaled(A: float) -> float:
    """Exp41 ideal-R error scaled as 1/(A+1+RfG). Not new SPICE."""
    return ERR_IDEAL * (A0 + 1.0 + RFG) / (A + 1.0 + RFG)


def a_required_measured_scale() -> float:
    """A where |scaled ideal-R error| = EPS."""
    return abs(ERR_IDEAL) * (A0 + 1.0 + RFG) / EPS - 1.0 - RFG


def meets_bar(err: float) -> bool:
    """|err| <= 1 mV, including float equality at the analytical boundary."""
    return abs(err) <= EPS or math.isclose(abs(err), EPS, rel_tol=0.0, abs_tol=1e-15)


def err_w_scaled(A: float, leftover: float) -> float:
    """Additive: scaled ideal-R amplifier term + constant resistor leftover."""
    return err_ideal_scaled(A) + leftover


def a_for_total_pass(leftover: float) -> float | None:
    """Smallest A>=0 such that |err_ideal_scaled + leftover| <= EPS.

    Binding side is the more negative total (amplifier term is negative).
    Returns None if the A→∞ leftover already exceeds the bar.
    """
    if abs(leftover) > EPS:
        return None
    # err = amp(A) + leftover >= -EPS  (amp < 0, leftover may be + or −)
    # |amp(A)| <= EPS + leftover   if leftover > -EPS
    # amp(A) = ERR_IDEAL * S / (A+1+RfG)
    s = A0 + 1.0 + RFG
    # Need leftover - |ERR_IDEAL|*S/(A+1+RfG) >= -EPS
    # |ERR_IDEAL|*S/(A+1+RfG) <= EPS + leftover
    denom = EPS + leftover
    if denom <= 0:
        return None
    a = abs(ERR_IDEAL) * s / denom - 1.0 - RFG
    return max(a, 0.0)


def compute() -> dict:
    a_req = a_required_analytical()
    a_req_meas = a_required_measured_scale()
    a_w10_pass = a_for_total_pass(R_W10)
    a_w1_pass = a_for_total_pass(R_W1)

    a_points = {
        "1e5": A0,
        "A_required_analytical": a_req,
        "A_required_measured_scale": a_req_meas,
        "1e6": 1.0e6,
        "1e7": 1.0e7,
        "2x_A_required_analytical": 2.0 * a_req,
    }

    ideal_vs_a = {}
    for name, A in a_points.items():
        e_an = err_analytical(A)
        e_ms = err_ideal_scaled(A)
        ideal_vs_a[name] = {
            "A": A,
            "k": k_of(A),
            "err_analytical_V": e_an,
            "err_analytical_mV": e_an * 1e3,
            "abs_analytical_mV": abs(e_an) * 1e3,
            "analytical_pass": meets_bar(e_an),
            "err_measured_scale_V": e_ms,
            "err_measured_scale_mV": e_ms * 1e3,
            "abs_measured_scale_mV": abs(e_ms) * 1e3,
            "measured_scale_pass": meets_bar(e_ms),
            "label": "analytical and Exp41-anchored projection; not a new SPICE result",
        }

    # Interaction (k−1)·z·ε_R at A=1e5. ε_R = leftover / y_ideal.
    eps_w1 = R_W1 / Y_IDEAL
    eps_w10 = R_W10 / Y_IDEAL
    k0 = k_of(A0)
    interact_w1 = (k0 - 1.0) * Z * eps_w1
    interact_w10 = (k0 - 1.0) * Z * eps_w10
    err_w1_inf = Z * eps_w1
    err_w10_inf = Z * eps_w10

    match_wl = (XHIGH_PELGROM / MATCH_SIGMA) ** 2
    used_sigma = XHIGH_PELGROM / math.sqrt(RF_W1_WL_UM2)
    det_rel = EPS / Z
    match_as_mV_on_z = MATCH_SIGMA * Z * 1e3

    rec = {
        "experiment_id": "exp42",
        "kind": "feasibility / boundary",
        "closed_experiments_unmodified": ["exp39", "exp40", "exp41"],
        "spice_run": False,
        "transistor_search": False,
        "geometry_changed": False,
        "weights_changed": False,
        "acceptance_bar_V": EPS,
        "matching": "UNRESOLVED",
        "f40": "NOT TESTED",
        "temperature": "NOT TESTED",
        "network_f_2937_hosting": "NOT DEMONSTRATED",
        "exp40_decision_unchanged": "C",
        "identity": {
            "sim_target": SIM_TARGET,
            "tag": TAG,
            "Rf_G": RFG,
            "z_o2": Z,
        },
        "established": {
            "y_exp40": Y_EXP40,
            "err_exp40_mV": ERR_EXP40 * 1e3,
            "y_ideal_r": Y_IDEAL,
            "err_ideal_r_mV": ERR_IDEAL * 1e3,
            "resistor_w1_mV": R_W1 * 1e3,
            "y_w10": Y_W10,
            "err_w10_mV": ERR_W10 * 1e3,
            "resistor_w10_mV": R_W10 * 1e3,
            "y_miller": Y_MILLER,
            "err_miller_mV": ERR_MILLER * 1e3,
        },
        "question_1_A_required": {
            "A_current": A0,
            "k_at_A_current": k0,
            "predicted_finite_A_error_V": err_analytical(A0),
            "predicted_finite_A_error_mV": err_analytical(A0) * 1e3,
            "A_required": a_req,
            "A_required_formula": "z*(1+RfG)/1e-3 - 1 - RfG",
            "safety_margin": {
                "current_A_over_A_required": A0 / a_req,
                "A_required_over_current_A": a_req / A0,
                "positive_margin_at_current_A": False,
                "deficit": "current A is below A_required",
                "conventional_2x_A_required": 2.0 * a_req,
                "analytical_error_at_2x_mV": err_analytical(2.0 * a_req) * 1e3,
            },
            "physically_achievable": "NOT ASSUMED",
        },
        "question_2_ideal_R": {
            "kind": "analytical first; Exp41-anchored scale is a projection",
            "demonstrated_circuit": False,
            "vs_A": ideal_vs_a,
            "case_B_boundary": (
                "Ideal R + A >= A_required_analytical is analytical PASS "
                "(|k·z−z| <= 1 mV). Ideal R + A=1e5 is FAIL."
            ),
        },
        "question_3_resistor": {
            "A_finite_A_amplifier_error_mV": ERR_IDEAL * 1e3,
            "B_deterministic_resistor_w1_mV": R_W1 * 1e3,
            "B_deterministic_resistor_w10_mV": R_W10 * 1e3,
            "C_interaction_w1_mV": interact_w1 * 1e3,
            "C_interaction_w10_mV": interact_w10 * 1e3,
            "relative_eps_R_w1": eps_w1,
            "relative_eps_R_w10": eps_w10,
            "required_leftover_once_A_solved_mV": EPS * 1e3,
            "required_leftover_with_0p2mV_amp_margin_mV": 0.8,
            "required_deterministic_relative": det_rel,
            "note": (
                "Once |finite-A| is << 1 mV, |y_PDK − y_idealR| must stay "
                "<= 1 mV (tighter if amplifier residual remains). "
                "This is deterministic DC accuracy on this vector, not matching."
            ),
        },
        "question_4_w10": {
            "existing_err_mV": ERR_W10 * 1e3,
            "margin_above_bar_mV": abs(ERR_W10) * 1e3 - EPS * 1e3,
            "consistent_with": {
                "residual_finite_A_mV": ERR_IDEAL * 1e3,
                "residual_resistor_mV": R_W10 * 1e3,
                "sum_mV": (ERR_IDEAL + R_W10) * 1e3,
                "interaction_mV": interact_w10 * 1e3,
            },
            "A_to_infty_err_mV": err_w10_inf * 1e3,
            "A_min_additive_pass": a_w10_pass,
            "theoretically_capable_if_A_large": abs(err_w10_inf) <= EPS,
            "declared_pass": False,
            "reason_not_declared": (
                "No new W=10 + high-A SPICE. Existing W=10 at A=1e5 remains FAIL."
            ),
        },
        "question_5_geometry": {
            "optimization_sweep": False,
            "design_changed": False,
            "w1_leftover_mV": R_W1 * 1e3,
            "w10_leftover_mV": R_W10 * 1e3,
            "w1_infinite_A_pass": abs(err_w1_inf) <= EPS,
            "w10_infinite_A_pass": abs(err_w10_inf) <= EPS,
            "direction": (
                "Increase same-family xhigh_po width from the W=1 encode "
                "toward the established W=10 encode. Leftover changes sign "
                "between those two points; locating a zero is an optimization "
                "and is not performed."
            ),
            "deterministic_error_geometry": {
                "requirement": "|y_PDK − y_idealR| <= 1 mV after A is solved",
                "w1": "does not meet (4.890 mV leftover)",
                "w10": "meets (0.604 mV leftover) as a feasibility bound only",
            },
            "matching_geometry": {
                "status": "UNRESOLVED",
                "pelgrom_A": XHIGH_PELGROM,
                "used_Rf_W1_WL_um2": RF_W1_WL_UM2,
                "used_1sigma": used_sigma,
                "WL_for_0p075pct_um2": match_wl,
                "note": (
                    "Pelgrom area for 0.075% leftover matching is a different "
                    "quantity from deterministic-error geometry. Not conflated."
                ),
            },
            "match_0p075pct_as_mV_on_z_o2": match_as_mV_on_z,
        },
        "question_6_decision_tree": {
            "A_ideal_R_A1e5": {
                "result": "FAIL",
                "analytical_mV": err_analytical(A0) * 1e3,
                "measured_ideal_R_mV": ERR_IDEAL * 1e3,
            },
            "B_ideal_R_high_A": {
                "analytical_boundary": "PASS for A >= A_required",
                "A_required": a_req,
                "demonstrated": False,
            },
            "C_W10_high_A": {
                "theoretical": "capable of PASS",
                "A_to_infty_mV": err_w10_inf * 1e3,
                "A_min_additive": a_w10_pass,
                "demonstrated": False,
            },
            "D_W1_high_A": {
                "theoretical": "FAIL",
                "A_to_infty_mV": err_w1_inf * 1e3,
                "A_min_additive": a_w1_pass,
            },
            "E_miller": {
                "result": "FAIL",
                "err_mV": ERR_MILLER * 1e3,
                "optimized": False,
            },
        },
        "reachable_without_changing_frozen_weights": {
            "at_A1e5_W1": False,
            "theoretically_with_higher_A_and_W10_encode": True,
            "demonstrated": False,
            "statement": (
                "The 1 mV bar is fundamentally missed at the current "
                "A=1e5 / W=1 implementation. It is theoretically reachable "
                "on this frozen o2 vector by raising amplifier gain and using "
                "a resistor implementation whose deterministic leftover is "
                "already at the established W=10 magnitude (0.604 mV). "
                "That is a future experiment, not a result of Experiment 42."
            ),
        },
        "future_experiment_minimum": [
            "Behavioral TIA at A >= A_required (or 1e6) + existing W=10 encode on frozen o2 — first demonstration candidate for Case C.",
            "Behavioral TIA at high A + ideal lumped R — confirm Case B and the analytical vs measured-scale A_required gap.",
            "Only after a high-A behavioral pass: a new experiment for a transistor TIA that actually delivers that A at +2.46 V. Do not treat Exp39 Miller resize as that experiment.",
            "Matching remains a separate campaign. Do not invent a mismatch PDF.",
            "Network-F 2.937 V hosting remains a separate voltage-range test.",
            "Do not change frozen weights, the 1 mV bar, or physical parameters unless a new experiment redefines them.",
        ],
    }
    return rec


def write_md(rec: dict) -> None:
    q1 = rec["question_1_A_required"]
    sm = q1["safety_margin"]
    vs = rec["question_2_ideal_R"]["vs_A"]
    q3 = rec["question_3_resistor"]
    q4 = rec["question_4_w10"]
    q5 = rec["question_5_geometry"]
    tree = rec["question_6_decision_tree"]
    reach = rec["reachable_without_changing_frozen_weights"]

    def row(name: str) -> str:
        r = vs[name]
        return (
            f"| {name} | {r['A']:.6g} | {r['k']:.9f} | "
            f"{r['err_analytical_mV']:+.6f} | "
            f"{'PASS' if r['analytical_pass'] else 'FAIL'} | "
            f"{r['err_measured_scale_mV']:+.6f} | "
            f"{'PASS' if r['measured_scale_pass'] else 'FAIL'} |"
        )

    lines = [
        "# Experiment 42 — o2 1 mV feasibility boundary (CLOSED)",
        "",
        "Experiments 39, 40, and 41 were not modified. No SPICE was run.",
        "No transistor sizes were searched. No resistor geometry was changed.",
        "Frozen weights and the 1 mV bar are unchanged. Matching is not claimed.",
        "Projections are **not** demonstrated circuit results.",
        "",
        "## Central question",
        "",
        "Is the 1 mV requirement fundamentally impossible at the current",
        "A=1e5 / W=1 implementation, or is it reachable with a legitimate",
        "increase in amplifier gain and/or resistor geometry while preserving",
        "the frozen o2 weights?",
        "",
        f"**At A=1e5 / W=1: impossible** (Decision C baseline unchanged).",
        "**Theoretically reachable** with higher A and a resistor leftover",
        "already demonstrated at the existing W=10 encode (0.604 mV).",
        "**Not demonstrated. No design pass.**",
        "",
        "## Established facts (not rerun)",
        "",
        "| Item | Value | Kind |",
        "| --- | ---: | --- |",
        f"| Target | {SIM_TARGET}, Rf·G = {RFG} | Exp40 baseline |",
        f"| z_o2 | {Z:+.15f} V | Exp40 baseline |",
        f"| Exp40 y / \\|err\\| | {Y_EXP40} V / {abs(ERR_EXP40)*1e3:.12f} mV | Exp40 baseline |",
        f"| Ideal-R SPICE error | {ERR_IDEAL*1e3:+.6f} mV | Exp41 diagnostic |",
        f"| W=1 PDK vs ideal R | {R_W1*1e3:+.6f} mV | Exp41 diagnostic |",
        f"| W=10 \\|err\\| | {abs(ERR_W10)*1e3:.6f} mV | Exp41 diagnostic |",
        f"| Existing Miller \\|err\\| | {abs(ERR_MILLER)*1e3:.3f} mV | Exp41 diagnostic |",
        "| Exp40 Decision | **C** | unchanged |",
        "",
        "## Question 1 — required amplifier gain",
        "",
        "Established identity:",
        "",
        "```",
        "k = A / (A + 1 + Rf·G)",
        "|k · z_o2 − z_o2| <= 1e-3",
        "A_required = z_o2 · (1 + Rf·G) / 1e-3 − 1 − Rf·G",
        "```",
        "",
        "| Quantity | Value |",
        "| --- | ---: |",
        f"| Current A | {A0:.0e} |",
        f"| k(A=1e5) | {q1['k_at_A_current']:.15f} |",
        f"| Predicted finite-A error at A=1e5 | {q1['predicted_finite_A_error_mV']:+.12f} mV |",
        f"| A_required for 1 mV | **{q1['A_required']:.10f}** |",
        f"| A_required / A_current | {sm['A_required_over_current_A']:.6f} |",
        f"| A_current / A_required | {sm['current_A_over_A_required']:.6f} |",
        "| Positive safety margin at current A | **no** |",
        f"| Conventional 2× A_required | {sm['conventional_2x_A_required']:.6f} |",
        f"| Analytical error at 2× A_required | {sm['analytical_error_at_2x_mV']:+.6f} mV |",
        "",
        "Current A is **below** A_required by a factor of",
        f"{sm['A_required_over_current_A']:.3f}. There is no safety margin above",
        "A_required at A=1e5. This analytical A_required is **not** assumed",
        "physically achievable in MOS.",
        "",
        "Finite-A error at A=1e5 already exceeds the 1 mV bar under the",
        "established k identity (3.485 mV).",
        "",
        "## Question 2 — perfect-resistor feasibility",
        "",
        "Analytical first. The measured-scale column scales the Experiment 41",
        "ideal-R SPICE error as 1/(A+1+Rf·G). That column is a projection,",
        "not a new simulation.",
        "",
        "| A point | A | k | Analytical err (mV) | k-bar | Measured-scale err (mV) | scale-bar |",
        "| --- | ---: | ---: | ---: | --- | ---: | --- |",
        row("1e5"),
        row("A_required_analytical"),
        row("A_required_measured_scale"),
        row("1e6"),
        row("1e7"),
        row("2x_A_required_analytical"),
        "",
        "Ideal resistors + A=1e5: **FAIL** (analytical 3.485 mV; measured 2.056 mV).",
        "Ideal resistors + A ≥ A_required: **theoretical PASS** on the k identity.",
        "The 1.429 mV gap (ideal-R SPICE vs k·z) means the measured-scale",
        f"A_required is lower (**{a_required_measured_scale():.6f}**).",
        "Neither number is a demonstrated circuit result.",
        "",
        "## Question 3 — resistor requirement",
        "",
        "Experiment 41 additive split, reused (not rerun):",
        "",
        "```",
        "(y_W1 − z) = (y_idealR − z) + (y_W1 − y_idealR)",
        f"{ERR_EXP40*1e3:+.6f} mV = {ERR_IDEAL*1e3:+.6f} mV + {R_W1*1e3:+.6f} mV",
        "```",
        "",
        "| Term | W=1 (mV) | W=10 (mV) |",
        "| --- | ---: | ---: |",
        f"| A. Finite-A / ideal-fabric (measured) | {q3['A_finite_A_amplifier_error_mV']:+.6f} | {q3['A_finite_A_amplifier_error_mV']:+.6f} |",
        f"| B. Deterministic resistor leftover | {q3['B_deterministic_resistor_w1_mV']:+.6f} | {q3['B_deterministic_resistor_w10_mV']:+.6f} |",
        f"| C. Interaction (k−1)·z·ε_R at A=1e5 | {q3['C_interaction_w1_mV']:+.4f} | {q3['C_interaction_w10_mV']:+.4f} |",
        "",
        "Interaction is microvolts and is neglected as a design term.",
        "",
        "Once amplifier error is reduced well below 1 mV, the resistor-side",
        "requirement is:",
        "",
        f"- **|y_PDK − y_idealR| ≤ 1.000 mV** (absolute, this vector)",
        f"- equivalently |ε_R| ≤ {q3['required_deterministic_relative']:.6e} ({q3['required_deterministic_relative']*100:.4f}% of z_o2)",
        "- if ~0.2 mV amplifier residual remains: leftover ≲ 0.8 mV",
        "",
        f"W=1 leftover {abs(R_W1)*1e3:.3f} mV **fails** that resistor budget.",
        f"W=10 leftover {abs(R_W10)*1e3:.3f} mV **meets** that resistor budget.",
        "This is deterministic accuracy, not matching. No mismatch PDF.",
        "",
        "## Question 4 — existing W=10 boundary",
        "",
        f"Existing W=10 signed err = {q4['existing_err_mV']:+.6f} mV, "
        f"|err| = {abs(ERR_W10)*1e3:.6f} mV "
        f"({q4['margin_above_bar_mV']:.6f} mV above the bar).",
        "",
        "That remainder is consistent with residual finite-A (2.056 mV) plus",
        f"resistor leftover ({R_W10*1e3:+.6f} mV):",
        f"{ERR_IDEAL*1e3:+.6f} + {R_W10*1e3:+.6f} = {q4['consistent_with']['sum_mV']:+.6f} mV",
        "(recovers the Experiment 41 W=10 total).",
        "",
        "If A → ∞ and leftover stays at the measured W=10 value:",
        f"|err| → **{abs(q4['A_to_infty_err_mV']):.6f} mV < 1 mV**.",
        "",
        "Under the additive model, W=10 theoretically crosses the bar at",
        f"A ≳ **{q4['A_min_additive_pass']:.6f}**.",
        "",
        "**If amplifier gain were made sufficiently large, the existing W=10",
        "physical resistor implementation is theoretically capable of PASS.**",
        "",
        "It is **not** declared passed. No W=10 + high-A simulation was run.",
        "",
        "## Question 5 — geometry requirement (direction only)",
        "",
        "No sweep. No design change.",
        "",
        "| Encode | Leftover vs ideal R | Infinite-A |err| | Deterministic bar |",
        "| --- | ---: | ---: | --- |",
        f"| W=1 (Exp40) | {R_W1*1e3:+.6f} mV | {abs(Z * (R_W1/Y_IDEAL))*1e3:.6f} mV | FAIL |",
        f"| W=10 (Exp41 diagnostic) | {R_W10*1e3:+.6f} mV | {abs(q4['A_to_infty_err_mV']):.6f} mV | meets bound |",
        "",
        "Direction: increase same-family `xhigh_po` width from W=1 toward the",
        "already-established W=10 encode. Leftover **changes sign** between",
        "those two points, so a leftover zero exists in (1, 10) µm. Locating",
        "it would be an optimization and is **not** performed.",
        "",
        "### Deterministic-error geometry (this experiment)",
        "",
        "Need |y_PDK − y_idealR| ≤ 1 mV after A is solved. Existing W=10",
        "leftover already sits inside that bound. W=1 does not. This is **not**",
        "evidence that matching is satisfied.",
        "",
        "### Pelgrom / matching geometry (separate)",
        "",
        "| Item | Value |",
        "| --- | ---: |",
        f"| Model Pelgrom A | {XHIGH_PELGROM} |",
        f"| Used Rf W=1 WL | {RF_W1_WL_UM2} µm² |",
        f"| Used 1σ body | {q5['matching_geometry']['used_1sigma']*100:.3f}% |",
        f"| WL for 0.075% 1σ | {q5['matching_geometry']['WL_for_0p075pct_um2']:.3f} µm² |",
        f"| 0.075% of z_o2 | {q5['match_0p075pct_as_mV_on_z_o2']:.3f} mV |",
        "",
        "**MATCHING = UNRESOLVED.** 0.075% of this |z| is 1.845 mV, which is",
        "a different quantity from the 1.000 mV analog bar. Do not conflate.",
        "",
        "## Question 6 — decision tree",
        "",
        "| Case | Configuration | Boundary | Demonstrated? |",
        "| --- | --- | --- | --- |",
        f"| A | Ideal R + A=1e5 | **FAIL** (analytical {tree['A_ideal_R_A1e5']['analytical_mV']:+.3f} mV; measured {tree['A_ideal_R_A1e5']['measured_ideal_R_mV']:+.3f} mV) | Exp41 diagnostic |",
        f"| B | Ideal R + A ≥ A_required | **theoretical PASS** (A_required = {q1['A_required']:.3f}) | **no** |",
        f"| C | Existing W=10 + sufficiently high A | **theoretically capable of PASS** (∞-A leftover {tree['C_W10_high_A']['A_to_infty_mV']:+.3f} mV) | **no** |",
        f"| D | Existing W=1 + sufficiently high A | **theoretical FAIL** (∞-A leftover {tree['D_W1_high_A']['A_to_infty_mV']:+.3f} mV) | implied by Exp41 split |",
        f"| E | Existing Exp39 Miller, no resize | **FAIL** ({tree['E_miller']['err_mV']:.1f} mV) | Exp41 diagnostic; not optimized |",
        "",
        "## Conclusion",
        "",
        reach["statement"],
        "",
        "The current implementation fails for two independent reasons:",
        "",
        "1. **Amplifier:** A=1e5 is below A_required. Finite-A alone fails the bar.",
        "2. **Resistor:** W=1 leftover 4.890 mV fails even at infinite A.",
        "",
        "Raising A cannot save W=1. Changing geometry cannot save A=1e5",
        "(ideal R is already 2.056 mV off). Both must move.",
        "The existing Miller implementation is Case E and is not a path",
        "inside this experiment.",
        "",
        "## Minimum legitimate next investigations",
        "",
        "Not started. Not implemented.",
        "",
    ]
    for i, item in enumerate(rec["future_experiment_minimum"], 1):
        lines.append(f"{i}. {item}")
    lines += [
        "",
        "## Status",
        "",
        "- Experiment 40 Decision C: **unchanged**",
        "- Matching: **UNRESOLVED**",
        "- F40 classification: **NOT TESTED**",
        "- Temperature: **NOT TESTED**",
        "- Network-F 2.937183 V hosting: **NOT DEMONSTRATED**",
        "- Experiment 42: feasibility boundary only; **no design pass**",
        "",
        "No Experiment 43. No optimization.",
        "",
    ]
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    rec = compute()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    write_md(rec)

    q1 = rec["question_1_A_required"]
    print("Experiment 42: feasibility boundary (no SPICE)", flush=True)
    print(f"  A_current              = {A0:.0e}", flush=True)
    print(f"  finite-A err A=1e5     = {q1['predicted_finite_A_error_mV']:+.6f} mV", flush=True)
    print(f"  A_required (k identity)= {q1['A_required']:.6f}", flush=True)
    print(f"  A_req / A_current      = {q1['safety_margin']['A_required_over_current_A']:.6f}", flush=True)
    print(f"  A_req measured-scale   = {a_required_measured_scale():.6f}", flush=True)
    print(f"  W=1  infinite-A leftover = {Z * (R_W1/Y_IDEAL)*1e3:+.6f} mV  FAIL", flush=True)
    print(f"  W=10 infinite-A leftover = {Z * (R_W10/Y_IDEAL)*1e3:+.6f} mV  capable", flush=True)
    print("  matching = UNRESOLVED", flush=True)
    print("  Experiment 40 Decision C unchanged", flush=True)
    print("  STOP. No Experiment 43.", flush=True)


if __name__ == "__main__":
    main()
