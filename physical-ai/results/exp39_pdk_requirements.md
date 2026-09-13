# Experiment 39 updated minimum technology specification

Only numbers supported by Experiments 1-39. No invented PDK parameters.
Identity classes: **A** = o3 SPICE, **B** = catalog o2, **C** = network software.
Controlling identity: `results/exp39_identity_correction.md`.
Decision **C**. Published **B** is withdrawn.

- Analog bar `|y−z| <= 1e-3` on the simulated cell. F40 classification 100%:
  **NOT TESTED** in Experiment 39 (full network still mixed-level / not run).
- **B / catalog o2 (NOT simulated):** Rf·G = 140.893980. Rf = 33333.333 ohm.
  Gtot = 4.226819e-3 S. |z|max = 2.459490 V. Imax = 202.805 uA.
- **A / simulated o3:** Rf·G = 7.803810. z_ref = −2.162419 V. Imax = 234.114 uA.
  o2 was **NOT** transistorized or hosted.
- **C / network software:** |z|max = 2.937183 V (h25). This is not a measured
  SKY130 transistor output. Dual +/-2.5 V hosts this o3 vector (|z| = 2.162419 V).
  2.937183 V does not fit that span as a **network-level** requirement.
- Sampled dwell 200 us. On SKY130, the isolated **o3** fabric was settled by
  100 us (behavioral TIA). Miller temperature sweep: **NOT TESTED**.
- TIA A >= 4.88e4 analog (1e5 conservative). SKY130 miller closed-loop ran on
  o3; analog bar FAIL. OL sat. OL gain extraction: **NOT TESTED**.
- Uncorrected MOS offset is large in this miller (OL near a rail). Servo/CDS
  still required if raw fails. Servo DC is not the inference OP.
- Invert |Vos| <= 100 uV at N=32 remains a vendor-macromodel requirement, not
  a PDK invert.
- Summing-node |Ileak| <= 13 nA analog. SKY130 miller input current at 27 C
  was ~0. 85 C FET leakage: **NOT TESTED**.
- Same-family resistors: SKY130 xhigh_po rsheet 2000 ohm/sq, body tc1 = -1.47e-3
  (card parameter). Circuit-level TCR: **NOT TESTED**.
- Leftover after common-mode on **o3**: W=1 left 5.924e-3 V; W=10 left
  2.274e-3 V. These do not characterize catalog o2.
- Model Pelgrom A = 0.0347. For leftover sigma 0.075%, WL >= 2141 um2
  (2140.604 um2). Used Rf WL = 15.7 um2 is insufficient.
  **MATCHING FEASIBILITY UNRESOLVED.** MOS mismatch: **NOT TESTED**.
  MC n>=100: **NOT TESTED**.
- MIM camimc typical = 2.00 fF/um2. 2 nF => 1.0 mm2 is a **density/area
  estimate**, not a layout. In-circuit miller Cc and servo C are **lumped**.
  Fully integrated 1-2 nF CDS remains impractical.
- Temperature exercised on the PDK R fabric and o3 behavioral-TIA |err|:
  -40, 27, 85 C.
- ReLU remains a behavioral B-source.
- Layout parasitics: not extracted.

Do not invent a numeric TCR beyond the official card, a new Pelgrom A, or a MOS mismatch sigma beyond tt_mm.
