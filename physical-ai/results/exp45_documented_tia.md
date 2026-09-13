# Experiment 45 — documented macromodel TIA on W=10 o2

Experiments 1–44 were not modified. Frozen weights unchanged.
No MOS W/L. No Python correction. Not silicon. Not a PDK MOS TIA.

**Status: PARTIALLY VALIDATED**
**Decision A — DOCUMENTED MACROMODEL MEETS 1 mV ON W=10 o2**

## Phase 1 — parser conflict (preserved)

First attempt wrote `set ngbehavior=hsa` into `circuits/exp45_o2/.spiceinit`.
That overrode `ngspice -D ngbehavior=ps`. TI GWL `PARAMS:` lines were
parsed as unknown subcircuit names. No operating point was obtained.
This is a numerical/parser issue, not a measured analog error.

| Candidate | ±V | pspice | result |
| --- | ---: | --- | --- |
| OPA189 | 5.0 | True | FAIL ngspice exit 1 |
| OPA189 | 5.0 | False | FAIL ngspice exit 1 |
| OPA189 | 15.0 | True | FAIL ngspice exit 1 |
| OPA189 | 15.0 | False | FAIL ngspice exit 1 |
| OPA388 | 5.0 | True | FAIL ngspice exit 1 |
| OPA388 | 5.0 | False | FAIL ngspice exit 1 |
| OPA388 | 15.0 | True | FAIL ngspice exit 1 |
| OPA388 | 15.0 | False | FAIL ngspice exit 1 |

## Phase 2 — `ngbehavior=ps` + `skywaterpdk`

Working directory: `circuits/exp45_o2/phase2`. Home `.spiceinit` was not edited.

### Phase 2 smoke (open-loop, not a follower)

First smoke grounded IN+ and drove IN− to 1 V, so the output is not
required to track 1 V. It only proved `ngbehavior=ps` can parse OPAx189.

| Smoke | ±V | PDK .lib | v(out) | |vout−1| | ok |
| --- | ---: | --- | ---: | ---: | --- |
| OPA189 | 15.0 | False | -707.206740175 | 708206.740175 mV | False |

### Loaded W=10 catalog o2 (vec 19, z = +2.459489570880132 V)

| Candidate | ±V | y (V) | |err| (mV) | Vsum (V) | a_eff | pass |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| OPA189 | 15.0 | FAIL ngspice exit 1 | — | — | — | no |
| OPA189 | 5.0 | FAIL ngspice exit 1 | — | — | — | no |
| OPA192 | 15.0 | FAIL ngspice exit 1 | — | — | — | no |
| OPA388 | 2.5 | FAIL ngspice exit 1 | — | — | — | no |
| OPA1656 | 15.0 | FAIL ngspice exit 1 | — | — | — | no |
| OPA171 | 15.0 | FAIL ngspice exit 1 | — | — | — | no |

Decision A — DOCUMENTED MACROMODEL MEETS 1 mV ON W=10 o2. Phase 1: hsa blocked PARAMS. Phase 2: ps parsed OPA189 but .lib tt was read as include-file 'tt'. Phase 3 tested official_r_include_ps. PHYSICAL TIA VALIDATED remains no unless a loaded W=10 o2 cell analog-passed. Not silicon.

- Physical TIA validated: **NO** (macromodel ≠ PDK MOS ≠ silicon)
- Matching: **UNRESOLVED**
- Experiment 40 Decision C: **unchanged**
- Experiment 43 Decision A: **unchanged** (behavioral feasibility)
- Experiment 44 Decision R: **unchanged** (requirements)


## Phase 3 — mixed parser / official R include

Include mode: `official_r_include_ps`.

### Behavioral W=10 control (A=1e5 vs Experiment 41 y)

- y = 2.458037812913
- Δ vs Exp41 = 0.0
- fabric_match (≤1 µV) = True

### Phase 3 loaded cells

| Candidate | ±V | include | y (V) | |err| (mV) | Vsum (V) | pass |
| --- | ---: | --- | ---: | ---: | ---: | --- |
| OPA189 | 15.0 | official_r_include_ps | 2.460095443162 | 0.605872 | 1.408843641134e-08 | True |
| OPA192 | 15.0 | official_r_include_ps | 2.46037146906 | 0.881898 | 3.280548816355e-06 | True |
| OPA388 | 2.5 | official_r_include_ps | 2.460104142955 | 0.614572 | 1.0201750799e-07 | True |
| OPA1656 | 15.0 | official_r_include_ps | 2.501813278651 | 42.323708 | 0.0004980602438697 | False |
| OPA171 | 15.0 | official_r_include_ps | 1.295745838476 | 1163.743732 | -0.0139465216111 | False |

## Next experiment

Experiment 46: promote the passing macromodel on this W=10 cell (200 us / temp / extra frozen vectors). Still not silicon.

