# Experiment 48 — W=10 SKY130 Miller ± servo

Experiments 1–47 were not modified. Frozen weights unchanged.
Exp39/41 Miller sizes, no resize. Official sky130.lib tt.

**Status: CONTRADICTED**
**Decision B — MILLER+SERVO CONVERGED BUT MISSED THE 1 mV BAR**

A first label of Decision T (rail hosting) was **withdrawn**. Servo output
still has **0.402 V** of headroom to +2.5 V, so the miss is incomplete loop
correction, not supply saturation.

| Config | y (V) | |err| (mV) | Vsum (V) | a_eff | headroom to +2.5 V | pass |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Miller no servo | 1.833593776734 | 625.896 | -0.00748097450892 | 245.10 | 0.666 | no |
| Miller + servo | 2.098479338703 | 361.010 | -0.00431771919803 | 486.02 | 0.402 | no |

No-servo repeats Experiment 41 (y≈1.832 V, a_eff≈245). Servo moved y by
**+0.265 V** and doubled a_eff, but Vsum remains −4.32 mV. H4 is not a
dead idea; this existing miller+1 nF servo is not enough.

Physical TIA validated: **NO**. Matching: **UNRESOLVED**. Not silicon.

## Next experiment

Experiment 49: keep OPA189 as the Level-1 TIA host; treat this miller+servo
as an insufficient PDK path (361 mV leftover, Vsum still −4.32 mV). Do not
invent W/L as the first move. Matching remains UNRESOLVED.
