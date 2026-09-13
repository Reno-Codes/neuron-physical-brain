# Experiment 40 closed technology note

Does not overwrite Experiment 39. No invented PDK parameters.
Experiment 40 is **CLOSED** at the first identity-correct o2 DC.

- SIM_TARGET = o2 / W2[1]. Rf·G = 140.89398023224967. Gtot = 4.22681940696749e-3 S.
- Official SKY130A implementation of this o2 cell: |y−z| = 6.945681370132295 mV.
  Analog bar 1.0 mV: **FAIL** (≈6.95×). Decision **C**. No override.
- Matching: **UNRESOLVED**.
- Network software |z|max = 2.937183 V is not a SKY130 node.
- NOT TESTED: W=10, Miller, MC, MOS mismatch, F40 classification, temperature.

**Experiment 39: C — identity-corrected o3 experiment; critical o2 not simulated.**  
**Experiment 40: C — critical o2 correctly simulated; analog bar fails at 6.946 mV.**
