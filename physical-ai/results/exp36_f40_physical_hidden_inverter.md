==================================================
EXPERIMENT 36
FULL NETWORK F40 PHYSICAL HIDDEN-INVERTER INTEGRATION
==================================================

Frozen Experiment 9 weights. SPICE is the source of truth.
Experiments 1-35 were not overwritten. No Python correction,
no invented MOS W/L, no Network F in transistors.
OPA189 remains the official TI Green-Williams-Lis macromodel.
Qualified DC: .option reltol=5e-5. Qualified TRAN: .option method=gear.

Status: **FULL NETWORK PHYSICAL HIDDEN-INVERTER INTEGRATION VALIDATED**
Decision: **F — PHYSICAL INVERTER SUCCESS**
F40 validated: True

## 1. Executive summary

F40 DC MAE=6.3132e-04 acc=1.0000 200us=True repeat=True order_sensitive=False.

## 2. Starting status from Experiment 35

N=32 was qualified. Default DC F12 MAE 1.0142e-3 from vector 6 at
2.29 mV is a Newton branch. Qualified DC reltol=5e-5 MAE 5.1038e-4.
Qualified Gear 200 us F12 MAE 5.1668e-4. Factory-default DC is not
the source of truth for this coupled GWL fabric.

## 3. Frozen baseline and controls

| control | set | MAE | max | acc | analog | note |
| --- | --- | --- | --- | --- | --- | --- |
| A | F40 | 4.8383e-04 | 3.4319e-03 | 1.0000 | True | Architecture A ideal VCVS invert |
| B | F40 | 4.8586e-04 | 3.4885e-03 | 1.0000 | True | XSPICE limit hidden invert, not physical |
| C | F12 | 5.1038e-04 | 3.1576e-03 | 1.0000 | True | Exp 35 qualified DC reltol=5e-5 |
| C | F12 | 5.1668e-04 | 3.1579e-03 | 1.0000 | True | Exp 35 qualified Gear 200 us |

## 4. OPA189 F40 circuit construction

Hidden OPA189 instances: 32.
Model: C:\dev\neuron-physical-brain\physical-ai\models\vendor\ti\opa189\OPAx189.LIB sha256=e7ca1f9b0da954be...
ngspice: ** ngspice-47 : Circuit level simulation program
git: bac4ea77485c Initial commit

All 32 hidden inverts are OPAx189. Input/Vref polarity copies remain
behavioral. TIA and ReLU remain LEVEL 2. No XSPICE limit on hidden stages.

## 5. Qualified DC F40 result

MAE=6.3132e-04 max=9.0728e-03 median_max=1.3611e-03 p95_max=3.1711e-03 acc=1.0000 analog=True worst_vector=18 worst_output=7 analog_mae_fail=[18] spice_s=166.7

## 6. DC repeatability

| run | MAE | max | acc | analog | worst vec | t(s) |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 6.3132e-04 | 9.0728e-03 | 1.0000 | True | 18 | 169.1 |
| 2 | 6.3132e-04 | 9.0728e-03 | 1.0000 | True | 18 | 180.6 |
| 3 | 6.3132e-04 | 9.0728e-03 | 1.0000 | True | 18 | 165.0 |

Repeatable: True

## 7. Solver-band robustness

| reltol | MAE | max | acc | analog | analog-MAE-fail | worst | t(s) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| factory | 9.2880e-04 | 9.0725e-03 | 1.0000 | True | [6, 18, 29] | 18 | 158.8 |
| 0.0001 | 9.2880e-04 | 9.0727e-03 | 1.0000 | True | [6, 18, 29] | 18 | 171.4 |
| 5e-05 | 6.3132e-04 | 9.0728e-03 | 1.0000 | True | [18] | 18 | 165.1 |
| 2e-05 | n/a | n/a | n/a | None | [] | None | 720.0 |
| 1e-05 | n/a | n/a | n/a | None | [] | None | 388.0 |
| 1e-06 | n/a | n/a | n/a | None | [] | None | 469.7 |

## 8. Worst-vector analysis

Qualified DC worst vector is 18 (per-vector MAE 6.6146e-3, max 9.0728e-3, invert residual 2.30 mV).
That is the Experiment 35 coupled-GWL Newton branch on an F40-only
vector. Factory/1e-4 DC analog-MAE-fail vectors are [6, 18, 29];
reltol=5e-5 leaves only vector 18. Gear 100/200/500 us puts vector 18
on the good invert (per-vector MAE ~7.2e-4). The aggregate F40 DC
still analog-passes because 39/40 vectors are at the finite-A floor.
This is inherited GWL-branch behavior, not a new invert-cell failure.

## 9. Hidden-inverter residual distribution

mean=5.8194e-05 max=2.3285e-03 p95=2.3152e-03 n_stages=32

Compare Experiment 33 isolated ~0.66 uV and Experiment 35 qualified N=32
invert residual ~0.73 uV on the good branch.

## 10. Full-network transient results

| t_hold | method | protocol | MAE | max | acc | analog | note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0.0001 | gear | independent_per_vector | 4.8727e-04 | 3.4286e-03 | 1.0000 | True | F40 independent Gear TRAN 0.0001 s f40_0.0001 |
| 0.0002 | gear | independent_per_vector | 4.8589e-04 | 3.4286e-03 | 1.0000 | True | F40 independent Gear TRAN 0.0002 s f40_0.0002 |
| 0.0005 | gear | independent_per_vector | 4.8440e-04 | 3.4286e-03 | 1.0000 | True | F40 independent Gear TRAN 0.0005 s f40_0.0005 |
| 0.0001 | gear | independent_per_vector | 4.8727e-04 | 3.4286e-03 | 1.0000 | True | F40 independent Gear TRAN 0.0001 s f40_0.0001 |
| 0.0002 | gear | independent_per_vector | 4.8589e-04 | 3.4286e-03 | 1.0000 | True | F40 independent Gear TRAN 0.0002 s f40_0.0002 |
| 0.0005 | gear | independent_per_vector | 4.8440e-04 | 3.4286e-03 | 1.0000 | True | F40 independent Gear TRAN 0.0005 s f40_0.0005 |

## 11. 100/200/500 us dwell analysis

200 us is the required operating point. 500 us is a bound only.

## 12. Vector-order/state analysis

| order | MAE | max | analog | protocol |
| --- | --- | --- | --- | --- |
| original | 4.8589e-04 | 3.4286e-03 | True | independent_per_vector |
| reversed | 4.8589e-04 | 3.4286e-03 | True | independent_per_vector |
| shuffle_seed36 | 4.8589e-04 | 3.4286e-03 | True | independent_per_vector |

## 13. Analog vs classification

DC analog_pass=True class=1.0000 correct=40 incorrect=0.
TRAN 200 us analog_pass=True class=1.0000.
Classification 100% is not analog equivalence.

## 14. Remaining ideal-block accounting

{
  "documented_physical_macromodels": {
    "OPA189_hidden_inverters": 33,
    "model": "OPAx189",
    "path": "C:\\dev\\neuron-physical-brain\\physical-ai\\models\\vendor\\ti\\opa189\\OPAx189.LIB"
  },
  "behavioral_level2": {
    "VCVS_E": 65,
    "XSPICE_limit_or_A": 0,
    "ReLU_B_sources": 32,
    "all_B_sources": 32,
    "note": "Architecture A TIA remains a VCVS / behavioral I-to-V. ReLU is a B-source."
  },
  "ideal_stimuli": {
    "Vin": 16,
    "Vref_like": 1
  },
  "passives": {
    "resistors": 1342,
    "capacitors": 32
  },
  "line_count": 1544
}

## 15. Power scope

{
  "i_vdd_mean_abs_A": 0.04160000307838195,
  "label": "macromodel simulated primitive supply consumption",
  "not": [
    "chip power",
    "board power",
    "Network F physical power"
  ]
}

## 16. Failure mechanism or promotion result

F40 analog-passes and classifies at 100% under the Experiment 35 qualified DC and Gear 200 us policies. All 32 hidden inverts remain OPA189. Qualified DC still leaves F40 vector 18 on the 2.29 mV Newton branch; Gear 200 us recovers that vector. Factory DC analog-passes only by averaging (vectors 6, 18, 29 remain analog-MAE fails).

## 17. Final F40 decision

- DC analog: True
- DC class 100%: True
- DC repeatable: True
- TRAN 200 us analog: True
- TRAN 200 us class 100%: True
- 32 OPA189 hidden: True
- no prohibited repair: True
- qualified: True

## 18. Remaining physical bottleneck

Experiment 37: next physical block in Architecture A (TIA or ReLU), or a PDK. Do not invent MOS. Do not search another invert amp.

## 19. Recommended Experiment 37

Experiment 37: next physical block in Architecture A (TIA or ReLU), or a PDK. Do not invent MOS. Do not search another invert amp.

JSON: `results/exp36_f40_physical_hidden_inverter.json`.
Circuits: `circuits/exp36_f40_physical_hidden_inverter/`.
Scripts: `scripts/exp36_f40_physical_hidden_inverter.py`, `scripts/exp36_f40_transient.py`.
