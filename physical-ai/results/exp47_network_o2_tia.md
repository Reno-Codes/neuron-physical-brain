# Experiment 47 — OPA189 catalog o2 TIA in Network F

Experiments 1–46 were not modified. Frozen weights unchanged.
Ideal-R fabric. Only Eo2tia replaced. Not W=10. Not silicon.

**Status: PARTIALLY VALIDATED**
**Decision A — OPA189 o2 TIA HOLDS ANALOG MAE IN NETWORK F**

| Run | MAE | max |acc| analog |
| --- | ---: | ---: | ---: | --- |
| F12 behavioral | 0.000595993397691753 | 0.0023735698772737734 | 1.0 | True |
| F12 OPA189 o2 | 0.0005521029569035677 | 0.0022803692491430994 | 1.0 | True |
| F40 OPA189 o2 | 0.00043840099974446053 | 0.0020041082109008013 | 1.0 | True |

Decision A — OPA189 o2 TIA HOLDS ANALOG MAE IN NETWORK F. This is mixed-level: one vendor macromodel TIA in an otherwise behavioral Network F. Not W=10. Not silicon. Not a PDK MOS TIA.

## Next experiment

Experiment 48: W=10 SKY130 resistor encode on the o2 row inside Network F, or multi-TIA OPA189 copies. Do not claim silicon. Matching remains UNRESOLVED.

