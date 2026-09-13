# EXPERIMENT 23
# VIRTUAL-GROUND PRIMITIVE VALIDATION

## 1. Objective
Can a documented VG/TIA primitive satisfy Experiment 22 on the frozen o2 unit cell and Network A without Python correction?

## 2. Candidate primitives
| ID | Level | Kind | Source | Inherent Vos | Dynamics |
|---|---:|---|---|---|---|
| O-VF | 2 | xspice_ota_voltage | ngspice built-in analog code model `ota` | False | False |
| O-hiZ | 2 | xspice_ota_hiz | ngspice built-in analog code model `ota` | False | False |
| L | 2 | xspice_limit | ngspice built-in analog code model `limit` | False | False |
| OPA171 | 3 | macro_opa171 | C:\ngspice\examples\p-to-n-examples\OPA171.txt | True | True |
| MCP6041 | 3 | macro_mcp6041 | C:\ngspice\examples\p-to-n-examples\MCP6041.txt | True | True |

O-VF is a voltage-gain equivalent (`A = gm * rout` with rout = 1 ohm), not a high-Z OTA.
O-hiZ is the physical 1-stage OTA (`gm = 1 mS`, `rout = 1e12`); Rf shunts that rout.

## 3. Model realism level
O-VF / O-hiZ / L: LEVEL 2 structured XSPICE primitives.
OPA171 / MCP6041: LEVEL 3 manufacturer macromodels.
Not LEVEL 4 transistor, LEVEL 5 PCB, or LEVEL 6 silicon.

## 4. Exact model sources / locations
- XSPICE `ota` and `limit`: ngspice built-in analog code models (`C:\ngspice\bin\ngspice_con.exe`).
- OPA171: `C:\ngspice\examples\p-to-n-examples\OPA171.txt` exists=True. Included, not copied.
- MCP6041: `C:\ngspice\examples\p-to-n-examples\MCP6041.txt` exists=True. Included, not copied.
- OPA171 requires `ngspice -b -D ngbehavior=ps` because the netlist uses PSpice `IF()`.
- License: TI / Microchip text stays in the ngspice examples tree.

## 5. Worst-neuron configuration
- Frozen Network F output neuron `o2`.
- Compiled `Rf * G_tot` max = 1.4089e+02 (Exp 22: 141 on o2).
- Leakage-worst `h16`; median hidden `h21`.
- Unit cell uses the actual compiled resistor network for that neuron, not a lump R.
- Invert VCVS remain A=1e7. Weights are Experiment 9 frozen `.npz`.

## 6. Unit-cell results
| Circuit | exit | v(lin) | v(sum) |
|---|---:|---:|---:|
| smoke_ota | 0 | -1.0000e+00 | -1.0001e-05 |
| smoke_ota_hiz | 0 | -1.2222e+00 | -1.1111e-01 |
| smoke_limit | 0 | -9.9998e-01 | 9.9998e-06 |
| smoke_opa171 | 0 | -9.9951e-01 | 2.4432e-04 |
| smoke_mcp6041 | 0 | -1.0038e+00 | -1.9133e-03 |

| Candidate | failed | MAE vs z | max |Vsum| | |vlin|max | reason |
|---|---|---:|---:|---:|---|
| O-VF | False | 4.3114e-04 | 1.8168e-05 | 1.8167e+00 |  |
| O-hiZ | False | 8.7333e-01 | 3.6801e-02 | 1.2635e+00 |  |
| L | False | 4.3040e-04 | 1.8137e-05 | 1.8137e+00 |  |
| OPA171 | False | 1.7743e-01 | 1.0633e-02 | 1.8356e+00 |  |
| MCP6041 | False | 1.6010e-01 | 1.9140e-03 | 1.6551e+00 |  |
| OPA171_reset_op | False | 1.7743e-01 | 1.0633e-02 | 1.8356e+00 |  |

Baselines: A I MAE=3.6459e-15, A Exp17 A=1e5 MAE=3.0673e-04; F I MAE=3.6817e-15, F Exp17 A=1e5 MAE=4.9108e-04.

## 7. Gain / virtual-ground requirement results
L analog A_min vs z (iso o2): {'status': 'bracketed', 'value': 44125.18805127807, 'metric': 0.001, 'lo': {'A': 30000.0, 'mae_vs_z': 0.0014318865897068448}, 'hi': {'A': 50000.0, 'mae_vs_z': 0.0008600886602585813}, 'method': 'log_interp', 'sampled_pass': 50000.0}
O-VF analog A_min vs z (iso o2): {'status': 'bracketed', 'value': 44288.29633420516, 'metric': 0.001, 'lo': {'A': 30000.0, 'mae_vs_z': 0.0014399381310818142}, 'hi': {'A': 50000.0, 'mae_vs_z': 0.0008629975391308197}, 'method': 'log_interp', 'sampled_pass': 50000.0}

### L gain sweep (iso o2)
| A | MAE vs z | max |Vsum| | failed |
|---:|---:|---:|---|
| 1.0000e+03 | 3.9751e-02 | 1.6751e-03 | False |
| 1.0000e+04 | 4.2719e-03 | 1.8001e-04 | False |
| 3.0000e+04 | 1.4319e-03 | 6.0339e-05 | False |
| 5.0000e+04 | 8.6009e-04 | 3.6243e-05 | False |
| 1.0000e+05 | 4.3040e-04 | 1.8137e-05 | False |
| 1.0000e+06 | 4.3073e-05 | 1.8151e-06 | False |

### O-VF gain sweep (iso o2)
| A | MAE vs z | max |Vsum| | failed |
|---:|---:|---:|---|
| 1.0000e+03 | 4.7011e-02 | 1.9810e-03 | False |
| 1.0000e+04 | 4.3441e-03 | 1.8306e-04 | False |
| 3.0000e+04 | 1.4399e-03 | 6.0678e-05 | False |
| 5.0000e+04 | 8.6300e-04 | 3.6366e-05 | False |
| 1.0000e+05 | 4.3114e-04 | 1.8168e-05 | False |
| 1.0000e+06 | 4.3081e-05 | 1.8154e-06 | False |

O-hiZ cannot expose a usable open-loop A under Rf: loaded gain is ~gm*Rf.
OPA171 does not expose a programmable A; smoke Vsum ~244 uV is the VG residual.

## 8. Offset sensitivity
L iso o2 |Vos| analog: {'status': 'bracketed', 'value': 1.4330812498106366e-05, 'abs_value': 1.4330812498106366e-05, 'lo': 1e-05, 'hi': 2.2e-05, 'method': 'log_interp'}
O-VF iso o2 |Vos| analog: {'status': 'bracketed', 'value': 6.602623335824435e-06, 'abs_value': 6.602623335824435e-06, 'lo': 3e-06, 'hi': 1e-05, 'method': 'log_interp'}

### L offset sweep (iso o2, IN+ Vos)
| Vos (V) | MAE vs z | max |Vsum| | failed |
|---:|---:|---:|---|
| 1.0000e-06 | 3.9536e-04 | 1.7138e-05 | False |
| 3.0000e-06 | 3.6906e-04 | 1.5139e-05 | False |
| 1.0000e-05 | 5.9749e-04 | 1.4298e-05 | False |
| 2.2000e-05 | 1.4795e-03 | 2.6288e-05 | False |
| 3.0000e-05 | 2.1482e-03 | 3.4281e-05 | False |
| 1.0000e-04 | 7.9993e-03 | 1.0422e-04 | False |
| 1.0000e-03 | 8.3228e-02 | 1.0035e-03 | False |

OPA171 inherent `V_OS = 214.023 uV` in the macromodel. Smoke Vsum = 244 uV.
That is ~10x the Experiment 22 full-network analog bound of 22 uV, and is
multiplied by ~(1+Rf G_tot) ~142 on o2.

## 9. Leakage sensitivity
L iso o2 |Ileak| analog: {'status': 'bracketed', 'value': 1.2634576686319264e-08, 'abs_value': 1.2634576686319264e-08, 'lo': 1e-08, 'hi': 1e-07, 'method': 'log_interp'}

| Ileak (A) | MAE vs z | max |Vsum| | failed |
|---:|---:|---:|---|
| 1.0000e-12 | 4.3042e-04 | 1.8137e-05 | False |
| 1.0000e-11 | 4.3061e-04 | 1.8137e-05 | False |
| 1.0000e-10 | 4.3249e-04 | 1.8137e-05 | False |
| 1.0000e-09 | 4.5122e-04 | 1.8137e-05 | False |
| 1.0000e-08 | 6.9592e-04 | 1.8134e-05 | False |
| 1.0000e-07 | 3.6900e-03 | 1.8104e-05 | False |
| 1.0000e-06 | 3.3665e-02 | 1.7804e-05 | False |

## 10. Bandwidth and settling
- O-VF and L have no dynamics; they are DC primitives.
- OPA171 macromodel ones-step on o2: failed=False t(|v-vfinal|<1e-3)=2.3208e-05 s, v_final=1.1120e+00, overshoot=0.0000e+00.
- This is measured macromodel settling, not datasheet GBW and not transistor f_T.
- UIC TRAN was not used for DC: the GWL model contains 1 F capacitors.

## 11. Stability
L/O-VF: no ringing (no poles). OPA171 ones-step overshoot recorded above.
OPA171 DC OP on alter-continuation hit singular GWL `cl_clamp` / `n053`.
Working DC method: bake Vin into a fresh netlist per vector and run a bare `op`.
A 1 pF capacitor was added on each OPA171 output so that OP exists on the loaded TIA.
That is a simulation load C, not a datasheet CL, not Python correction, and not silicon.
Control-section rshunt/gmin aborted some OPs; those options were removed.
Recovery note: OPA171 alter-continuation hit GWL cl_clamp singularities. Recovery bakes Vin DC into one netlist per vector. Control-section rshunt/gmin also aborted some OPs; the working DC analysis is a bare op. UIC was not used (GWL 1 F capacitors). Vlin is still the SPICE solution.

## 12. Supply behavior
| rail (V) | MAE vs z | |vlin|max | failed |
|---:|---:|---:|---|
| 1.5000e+01 | 4.3040e-04 | 1.8137e+00 | False |
| 5.0000e+00 | 4.3040e-04 | 1.8137e+00 | False |
| 3.3000e+00 | 4.3040e-04 | 1.8137e+00 | False |

L rails are XSPICE `limit` bounds. Isolated o2 |z|max ~1.82 V, so ±5 V and ±3.3 V did not clip.
MCP6041 is a 6 V part, simulated at ±2.2 V. That is observed, not a datasheet claim.
OPA171 smoke used ±15 V. Network A OPA171 uses the same supplies when it converges.

## 13. Network A integration
| A candidate | failed | MAE | max abs | class | reason |
|---|---|---:|---:|---:|---|
| L | False | 3.0673e-04 | 9.2294e-04 | 1.0000e+00 |  |
| O-VF | False | 3.0688e-04 | 9.2335e-04 | 1.0000e+00 |  |
| OPA171 | False | 1.2974e-02 | 3.1973e-02 | 1.0000e+00 |  |
| OPA171_trim | True | n/a | n/a | n/a | ngspice convergence failure |
| MCP6041 | False | 1.4605e-01 | 1.4684e+00 | 1.0000e+00 |  |
| OPA171_reset_op | False | 1.2974e-02 | 3.1973e-02 | 1.0000e+00 |  |
| OPA171_trim_reset | False | 7.0311e-03 | 2.3980e-02 | 1.0000e+00 |  |

## 14. Representative Network F integration
### h16
- L: mae_vs_z=3.6896e-05; max_vsum=1.3029e-05; failed=False
- OPA171: failed=True; failure_reason=expected 16 v(n1lin), got 8
- OPA171_reset_op: mae_vs_z=1.5969e-03; max_vsum=3.4739e-04; failed=False

### h21
- L: mae_vs_z=2.4876e-04; max_vsum=2.2133e-05; failed=False
- OPA171: failed=True; failure_reason=expected 16 v(n1lin), got 12
- OPA171_reset_op: mae_vs_z=1.2099e-02; max_vsum=9.7349e-04; failed=False

### o2
- L: mae_vs_z=4.3040e-04; max_vsum=1.8137e-05; failed=False
- OPA171: failed=True; failure_reason=expected 16 v(n1lin), got 13
- OPA171_reset_op: mae_vs_z=1.7743e-01; max_vsum=1.0633e-02; failed=False

## 15. Full Network F results
| F candidate | failed | MAE | max abs | class | reason |
|---|---|---:|---:|---:|---|
| L | False | 4.9108e-04 | 3.8130e-03 | 1.0000e+00 |  |
| O-VF | False | 4.9186e-04 | 3.8229e-03 | 1.0000e+00 |  |
| OPA171 | True | n/a | n/a | n/a | skipped: Network A OPA171 failed |
| OPA171_reset_op | False | 1.4932e-01 | 1.6854e+00 | 7.5000e-01 |  |

## 16. Monte Carlo / documented-Vos injection
This is not an OPA171 result. It asks whether the documented macromodel offset, applied to the converging XSPICE limit TIA, meets Exp 22 analog MAE. SPICE is uncorrected.

| L + 214 uV Vos | failed | MAE | max abs | class | reason |
|---|---|---:|---:|---:|---|
| A | False | 4.8809e-03 | 8.5396e-03 | 1.0000e+00 |  |
| F | False | 7.5467e-03 | 2.2668e-02 | 1.0000e+00 |  |

| F L MC | failed | MAE | max abs | class | reason |
|---|---|---:|---:|---:|---|
| nominal_L | False | 4.9108e-04 | 3.8130e-03 | 1.0000e+00 |  |
| offset_214uV | False | 7.5467e-03 | 2.2668e-02 | 1.0000e+00 |  |
| leakage_13nA | False | 7.6292e-04 | 7.6292e-04 | 1.0000e+00 |  |
| mismatch_0p5pct | False | 4.1030e-03 | 4.4759e-03 | 1.0000e+00 |  |
| combined_214uV_13nA_0p5pct | False | 8.2077e-03 | 9.0295e-03 | 1.0000e+00 |  |

## 17. Failure analysis
- O-hiZ: expected VG failure. Rf shunts high rout. Isolated o2 MAE vs z ~0.87.
- MCP6041: converges; analog MAE fails (Vsum ~1.9 mV, 6 V rails, Network A MAE 0.146, class 100%).
- OPA171 smoke Vsum=244 uV (model Vos=214 uV) already exceeds Exp 22 analog 22 uV.
- OPA171 alter+op and rshunt in .control: GWL clamp singularities. Reported, not hidden.
- After baked-Vin OP + 1 pF load C: Network A MAE=1.30e-2 acc=100%; F MAE=0.149 acc=75%.
- Isolated o2 OPA171 max |Vsum|=10.6 mV, MAE vs z=0.177: VG is not held under Rf G=141.
- L+214 uV on the converging XSPICE TIA: A MAE=4.88e-3, F MAE=7.55e-3, both 100% class.
  OPA171 F is worse than that injection, so offset is not the only LEVEL 3 error.
- IN+ trim from zero-input Vsum: A MAE 1.30e-2 -> 7.03e-3 (still fail); isolated o2 got worse.
  Same lesson as Exp 19: zero-input cancellation does not restore the loaded fabric.
- Chopper/auto-zero clocking was not implemented. Differential replica was bounded in Exp 19.
- No MOS W/L invented. No vendor netlist copied into this repo.

## 18. Comparison against Experiment 22 requirements
| Item | Exp 22 need | Candidate result |
|---|---:|---|
| A >= 4.88e4 (analog) | 4.8800e+04 | L iso o2 A_min~4.41e4; O-VF ~4.43e4; O-hiZ cannot; OPA171 A not exposed |
| |Vos| <= 22 uV analog | 2.2400e-05 | L iso o2 analog ~14 uV. OPA171 model Vos=214 uV, smoke Vsum~244 uV. L+214uV F MAE=7.5467e-03 A MAE=4.8809e-03. OPA171 Network A MAE=1.2974e-02 unit MAE_z=1.7743e-01 |
| Network A analog MAE<=1e-3 | 1.0000e-03 | L MAE=3.0673e-04 O-VF MAE=3.0688e-04 OPA171 MAE=1.2974e-02 trim MAE=7.0311e-03 MCP6041 MAE=1.4605e-01 |
| Network F analog if run | 1.0000e-03 | L MAE=4.9108e-04 acc=1.0 O-VF MAE=4.9186e-04 OPA171=1.4932e-01 |

## 19. What requirement fails first
Input offset of documented op-amp macromodels. OPA171 V_OS=214 uV is about 10x the Exp 22 analog bound. High open-loop gain does not remove the ~142x (1+Rf G_tot) multiplier on o2. GWL DC OP singularity is a model-convergence failure on the same loaded TIA, reported separately.

## 20. What requirement is easiest
Programmable open-loop A on XSPICE limit / O-VF, and leakage at nA-class on the isolated cell. Isolated o2 |z|<2 V also fit inside ±3.3 V L rails.

## 21. What remains ideal
Inverts stay high-A VCVS. ReLU stays a B-source. Fine-bank dest=0 compensation is unchanged. O-VF/L have no transistor dynamics. Architecture I dump remains the numerical exact VG.

## 22. Hardware realism level
LEVEL 2 structured (O-VF, L) and LEVEL 3 macromodel (OPA171, MCP6041). Not LEVEL 4-6. Not board power. Not silicon. O-VF is not a high-Z OTA.

## 23. Limitations
OPA171 needs ngspice PSpice IF() compatibility. MCP6041 is a 6 V part. O-VF sets rout=1 ohm so A=gm*rout survives Rf; that is a voltage op-amp equivalent. IN+ trim is a known-model voltage, not a replica, and would not cancel uncorrelated per-chip Vos. Isolated MAE vs z is not full-network MAE. GWL 1 F capacitors forbid UIC as a DC method.

## 24. Honest conclusion
OFFSET-LIMITED VG PRIMITIVE. XSPICE L/O-VF meet analog MAE on Network A (and F) at Vos=0, matching Exp 17 behavioral TIA. Documented LEVEL 3 OPA171/MCP6041 do not meet the 22 uV analog offset spec. IN+ trim on Network A changed MAE from 1.2974e-02 to 7.0311e-03, still above 1e-3. Isolated o2 trim MAE_z=2.6247e-01 (worse than untrimmed). Calibration of one zero-input Vsum does not restore the loaded worst neuron (Exp 19 lesson). Injecting 214 uV into L on F gives analog MAE=7.5467e-03 (above 1e-3). Full Network F OPA171 MAE=1.4932e-01 acc=7.5000e-01: analog fails and classification drops. That is worse than L+214 uV because Vsum on o2 reaches ~10 mV, so the macromodel is not holding virtual ground under Rf G_tot=141.

## FINAL STATUS
OFFSET-LIMITED VG PRIMITIVE

SPICE is the source of truth. Frozen Experiment 9 weights were not edited.
Classification accuracy and analog MAE are reported separately.
