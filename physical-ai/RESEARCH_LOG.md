# Physical AI — master research log

Frozen Experiment 9 weights (`models/scaling/{A,F}.npz`, seed 9). SPICE is the source of truth. Experiments 1–38 were not overwritten. Experiment 39 is new.

Hardware realism levels: 1 mathematical/ideal behavioral · 2 non-ideal behavioral · 3 plausible analog topology · 4 device-level · 5 PCB · 6 silicon.

Analysis type through Experiment 22: **behavioral circuit analysis**. Experiment 23 adds **LEVEL 2 XSPICE primitives** and **LEVEL 3 manufacturer macromodels**. Experiment 24 adds LEVEL 2 offset-correction loops (servo, Vref-gated auto-zero) on the same fabric. Experiment 25 is **LEVEL 2 nested-loop TRAN** of that servo (OTA-C + optional TIA pole). Experiment 26 is **LEVEL 4 teaching-card MOS** (Berkeley BSIM3v3 miller TIA + miller servo) on isolated o2 — not IHP, not silicon. Experiment 27 is matching + MOS-only temperature on that same cell, with physically implemented capacitive CDS. Experiment 28 is a transistor-level output interface that extracts that CDS state. Experiment 29 is resistor-ratio matching on the frozen Architecture A Network F fabric (behavioral TIA, not MOS Network F). Experiment 30 is the physical invert primitive plus a local PDK/resistor-technology search — still not MOS Network F, still not an invented foundry. Experiment 31 extracts hidden-inverter drive / swing / Rout / Vos requirements and explains the 1-vs-32 OPA1656 anomaly. Experiment 32 searches the local documented model library for a hidden invert that meets those requirements, or shows the library cannot provide one. Experiment 33 acquires official TI precision macromodels and tests them against the quantified N=32 invert bench; no PDK is installed. Experiment 34 isolates the OPA189 N=32 residual: isolated 32-copy stays at ~0.66 µV; the fabric fail at default reltol is one F12 vector (2.29 mV) and is solver-sensitive. Experiment 35 qualifies that residual as a DC Newton branch: gear 200 µs F12 analog-passes and a DC reltol band of 5e-5…1e-6 (except a 2e-5 hole) is repeatable. Experiment 36 integrates the same OPA189 invert across F40 under that policy. Experiment 37 replays the documented Experiment 26 miller TIA + servo against the extracted Network F TIA requirements and stages it into the qualified OPA189 fabric. Experiment 38 maps those extracted requirements onto documented open PDKs without inventing device parameters. Experiment 39 installs official SKY130A and hosts one isolated frozen o2 cell. SPICE current on the MOS cell is transistor-level simulated power, still not board or silicon power.

---

## Architecture map (Experiments 16–17, still the computational core)

Architecture I (Exp 16 dump — best *exact* virtual ground):

```
Vin, Vref
  → passive invert (R2/R1 + high-A VCVS) for negative weights
  → load-compensated dividers for the fine bank (no tap buffers)
  → weight/bias resistors onto one node {tag}p
  → V{tag}p holds {tag}p at exactly 0 V
  → B{tag}iv copies i(V{tag}p) onto {tag}lin
  → R_IV from {tag}lin to 0  ⇒  Vlin = I * R_IV
  → B-source ReLU: y = max(0, min(rail, vlin))
  → layer 2 repeats from hy
```

Signed sum: `w+` from `Vin`, `w-` from inverted `Vin`. KCL at the 0 V node is `I = Vin*(G+ − G−)`.

Architecture A (Exp 17 TIA — best *no current dump*):

```
same fabric, weight polarity flipped for TIA sign
  → no 0 V source
  → E/B tia: Vlin = −A * (v({tag}p) − Vos)
  → Rf from {tag}lin to {tag}p
  → Vlin = −I_into_sum * Rf * A/(A+1+Rf G_tot)   [uncompensated]
  → Vsum ≈ Vos − Vlin/A
```

Remaining controlled sources on A: invert op-amps, TIA op-amps, ReLU B-sources, stimulus `Vin`/`Vref`.

---

## CURRENT BEST ARCHITECTURE

**Experiment 26 miller TIA + miller servo** is the best *device-level (LEVEL 4 teaching-card)* unit cell at 27 °C: isolated frozen o2 analog-passes at ±2.5 V, |Vlin−z| ≈ **5.6e-5**, Vsum ≈ **−0.67 µV**, 214 µV inject corrected, 100–1000 µs dwell analog-stable, P ≈ **3.15 mW**. Not a foundry PDK. Not silicon. Network F was not built from transistors.

**Experiment 27 unbuffered capacitive CDS** is the best *temperature-stable* high-Z state of that cell (MOS-only `.temp`): −40/27/85 °C |Vlin−z| ≈ **1.5e-4 / 2.6e-4 / 4.6e-4**, 200 µs–1 ms and A–B–C–A analog-pass at 85 °C. Output is a **high-Z capacitor plate**. The miller follower misses 85 °C / 200 µs (~1.18e-3, +2 mW).

**Experiment 28 VG charge amp + MOS invert+servo** is the best *driven* extract of that CDS state: −40/27/85 °C |Vout−z| ≈ **2.48e-4 / 2.4e-6 / 2.79e-4**, 200 µs A–B–C–A max |err| **7.1e-4**, drives 100 pF and 100 kΩ at 85 °C. P ≈ **8.80 mW** (one neuron). Invert DW=0.0026 is a 27 °C invert-amp self-balance, not a per-temp trim. Not silicon.

**Experiment 29 per-neuron Rf·G matching** is the best *resistor-fabric* model on frozen Network F: 0.5% grouped scale + 15% local residual, 16-draw 40-vector MAE mean **8.02e-4**, worst **9.38e-4**, analog pass 16/16, acc 1.0. Limited MC, not a yield. Not a foundry PCM.

**Experiment 33/35 OPA189** is the best *uncorrected documented invert cell* now qualified at N=32: isolated |Vout+Vin| **0.64–0.68 µV**; isolated 32-copy **0.66 µV**. Default-reltol DC fabric still fails (**1.014e-3**, vector 6 at 2.29 mV). Qualified policy: DC `reltol=5e-5` MAE **5.1038e-4** (3 identical repeats) and TRAN `.option method=gear` 200 µs F12 MAE **5.1668e-4**, acc 1.0. Not a switching chopper. Still a GWL macromodel, not silicon.

**Experiment 32 OPA1656 + shared replica −mid** is the best *LEVEL 3 amp plus LEVEL 2 sign* hidden invert: F12 MAE **5.101e-4**, F40 MAE **4.838e-4**, acc 1.0, N=1..32 flat, 200 µs TRAN residual ~135 nV. The OPA1656 cell itself still has the **498 µV** GWL mid floor. Do not label the sign flip a physical device.

**Experiment 30 XSPICE `limit` invert** is the best *documented invert replacement* that preserves the frozen F analog map without a replica: all 32 hidden inverts + input/Vref polarity copies, F40 MAE **4.86e-4**, acc 1.0 (LEVEL 2). Isolated teaching miller invert fails the extracted hidden load/swing (|err| 0.20–1.97 V). All 32 hidden OPA1656 analog-fail (F12 MAE **2.64e-3**, acc 1.0). No resistor PDK is installed.

**Experiment 24 summing-node servo** on Experiment 17 Architecture A is the best *no-dump analog* architecture when TIA Vos is nonzero: Network F MAE **7.4e-9** at 214 µV Vos (LEVEL 2 DC OP). Experiment 25 shows that same OTA-C loop is **TRAN-stable** as sampled inference with dwell **≥ 200 µs** on a behavioral 1 kHz TIA pole (F 12-vector TRAN MAE **6.4e-5**). It is **not** a 10 µs continuous nested loop.

**Experiment 24 Vref-gated auto-zero** is the best *clocked* analog architecture: F MAE **4.84e-4** at 214 µV Vos, matching L Vos=0, TRAN-proven (LEVEL 2 ideal switch/C). Isolated o2 vs z remains at the finite-A floor (~1.44e-3).

**Experiment 24 Vref-gated auto-zero** is the best *clocked* analog architecture: F MAE **4.84e-4** at 214 µV Vos, matching L Vos=0, TRAN-proven (LEVEL 2 ideal switch/C).

**Experiment 17 Architecture A** (feedback TIA, Vos=0) remains the uncorrected no-dump baseline (F MAE ~4.8e-4).

Experiment 16 Architecture I remains the best *numerical* architecture if a behavioral current dump is allowed (F MAE ~ 4e-15).

Experiment 19 Architecture N (replica-null TIA) is **not promoted**. Vin-only auto-zero (Exp 24) is also **not promoted** — it stores bias as Vos.

## CURRENT DOMINANT LIMITATION

The resistor fabric plus a circuit VG-offset loop **meets analog MAE at 214 µV Vos** (Exp 24 servo / Vref-gated AZ; Exp 25 servo TRAN; Exp 26 MOS miller servo on isolated o2 at 27 °C). Documented LEVEL 3 macromodels still do not (OPA1656 F MAE 0.017, Vsum ~498 µV).

After that loop works, analog error is dominated by **unmatched resistor ratios**, not absolute R. Architecture A is ratiometric: common-mode 0.5% is invisible on F (MAE = nominal 5.10e-4). Experiment 29: independent 0.5% F40 MAE ≈ **4.19e-3**; per-neuron Rf·G matching at 0.5% + 15% residual, 16-draw F40 MAE mean **8.02e-4** (worst 9.38e-4, analog pass 16/16, limited MC). Leftover unmatched local after that grouping must stay ≲ **0.075%** (0.125% mean-fails). Isolated o2 ratio-matched 0.5% remains Exp 27: MAE ≈ **8.9e-4** (8 draws, 62.5% pass, max 2.6e-3). Independent 0.5% tiling follows ~1/√N until N=8 then flattens (N=16 MAE ≈ **2.6e-3**). Blind N≥41 tiling is the 1/√N projection, not a measured recovery. Integer unit-G reconstruction of the frozen map needs ~**9.3e6** units before quantization alone analog-passes. Nested-loop dynamics are bounded: LEVEL 2 servo faster than a 1 kHz TIA pole **distorts** inference (~7e-2 on o2); changing inputs need **≥ 200 µs** dwell. The MOS miller analog-passes 100–1000 µs at 27 °C; with Exp 27 CDS at 85 °C the floor is **200 µs** (100 µs analog-fails). The Exp 22 10 µs continuous proxy is **not met**. Stored 27 °C DW/servo null is **temperature-fragile** (−40/85 °C |err|≈4e-3); capacitive CDS removes that MOS pedestal if the output may be high-Z. BSIM3 gate current is 0; the 13 nA leakage spec is not device-validated. Resistor TCR was not simulated (none documented; not invented). Experiment 30: LEVEL 2 XSPICE `limit` can replace the invert VCVS on F (F40 MAE 4.86e-4); the teaching miller invert cannot meet hidden y ≈ 2.61 V into ≈ 4.91 kΩ (isolated |err| up to 1.97 V); all 32 hidden OPA1656 analog-fail (MAE 2.64e-3) while acc stays 1.0. Experiment 31: that 32-OPA fail is a **498 µV invert-mid pedestal × N** (reproduced by Vos=500 µV; independent supplies unchanged). Hidden invert needs ≳ 0.40 mA (peak 0.63 mA), |Vout| ≳ 2.5 V plus headroom, and Vos ≲ 100 µV at 32 instances. Experiment 32: no uncorrected local macromodel meets that. Shared replica with IN+ = −replica mid analog-passes F40 (MAE **4.838e-4**) because a LEVEL 2 sign cancels the systematic 498 µV floor; IN+ = +replica mid explodes (F12 MAE 2.41). Per-invert LEVEL 2 servo works isolated and fails at 32 copies (MAE 0.424). A follower is not transparent. Experiment 33 acquired official TI OPA189/192/388 PSpice models after a before-inventory. Isolated OPA189 |Vout+Vin| is **0.64–0.68 µV** (Tier 1) with 0.79 mA and 2.61 V; TRAN 200 µs and −40/27/85 °C stay <2 µV. N=16 analog-passes (7.62e-4); N=32 fails (**1.014e-3**). That fail is not 32×0.66 µV. Experiment 34: isolated 32-copy OPA189 (shared or independent supplies, actual hy+Rfab) stays at **0.66 µV**. Fabric default-reltol mean invert residual **192 µV** is one F12 vector at **2.29 mV** (11/12 vectors ~0.73 µV, shared across 32 stages). Same topology `reltol=1e-6` → **0.73 µV** / MAE **5.10e-4** (diagnostic only, not promoted). A LEVEL 2 dest buffer failed (MAE 3.48e-3). Independent supplies unchanged (MAE 1.014e-3). OPA192 isolated-passes and fabric-timeouts. Zero-drift in these models is a static VOS_DRIFT term, not chopping. No IHP / SkyWater / r2_cmc tree is installed.

Leftover errors are still **not** removable by:

* passive `V = I R` (per-neuron loading)
* replica-null (shared taps sit outside the replica)
* Vin-only auto-zero (bias current is stored as offset)
* current-mode W2 (splitter is the wrong math; CCCS explodes copies)
* treating finite A as a global scale (G_tot varies ~17×)
* zero-input IN+ trim of an identical macromodel (Exp 23; same Exp 19 lesson)
* a high-Z 1-stage OTA (O-hiZ: Rf shunts rout)
* raising open-loop A to cancel Vos (Exp 24 map: 214 µV stays ~7.36e-3 from A=3e5 to 1e6)
* a servo integrator faster than the TIA pole (Exp 25: tau ≤ 1 µs with fp=1 kHz → o2 |Vlin−z| ≈ 7e-2)
* a 5T OTA as the summing-node servo (Exp 26: output CM rails)
* a telescopic-cascode miller at ±2.5 V (Exp 26: collapsed)
* a servo-miller replica as a temperature reference (Exp 27: worse than stored DW)
* holding Vsrv after AZ and opening the live servo (Exp 27: no-servo, |err|~8e-2)
* a teaching miller as a voltage-mode difference amp (Exp 27: gain ~0.55)
* summing-node injection of the AZ voltage (Exp 27: does not move the T pedestal)
* independent tiling of all 80 resistors past N=8 (Exp 27: flattening; pair matching without Rf is not ratio matching)
* a miller follower of the CDS plate at |z|≈1.73 V (Exp 28: adds ~0.71 mV at 85 °C)
* a plain NMOS source follower of that plate (Exp 28: Vgs≈0.74 V)
* nested CDS on that SF (Exp 28: leftover ΔVgs≈9 mV)
* loading the CDS plate with ≥1 pF or ≤100 MΩ (Exp 28)
* independent 0.5% resistors on Network F (Exp 29: 40-vector MAE ≈ 4.19e-3, analog pass 0)
* pairing +/− weights without Rf·G tracking (Exp 29: MAE ≈ 2.8e-3)
* a chip-wide polarity field at 0.5% (Exp 29: MAE ≈ 1.10e-2)
* integer unit-G quantization of the frozen map coarser than G_W/4096 (Exp 29: G_W/1024 still 1.12e-3)
* global sheet plus unmatched 0.5% local (Exp 29: MAE ≈ 4.38e-3)
* naive polarity-split placement under a normalized gx=0.01 gradient (Exp 29)
* a grounded resistor tap as an invert (Exp 30: isolated Vout=+0.51 vs −2.61; all-hidden F MAE 1.52, acc 0)
* the teaching miller as a Network F hidden invert at fabric load/swing (Exp 30: isolated |err| 0.20–1.97 V; 200 µs TRAN and miller servo do not recover 1.5 V into 4.91 kΩ)
* all 32 hidden OPA1656 macromodel inverts (Exp 30/31: F12 MAE 2.64e-3, analog fail, acc 1.0; mechanism is 498 µV VG pedestal × N, not supply interaction)
* 16 simultaneous OPA1656 hidden inverts (Exp 31: MAE 1.45e-3)
* a miller invert + miller follower at ±2.5 V into 4.9 kΩ (Exp 31: isolated |err| 0.655–1.77 V)
* F MAE of a single miller insertion as invert-transfer validation (Exp 30: F analog-pass while isolated |Vout+Vin| is hundreds of mV)
* invert Vos = 214 µV without correction (Exp 30: F12 MAE 1.50e-3)
* systematic invert R2/R1 error of 0.15% (Exp 30) or signed −0.075% (MAE 1.10e-3)
* an isolated-pass OPA189 invert as N=32 proof (Exp 33: isolated |err| 0.66 µV; 32-copy MAE 1.014e-3, mean invert residual ~575 µV)
* independent ±15 V supplies on 32 OPA189 copies (Exp 33: MAE 2.061e-3)
* treating TI “zero-drift” GWL as a switching chopper (Exp 33: static VOS_DRIFT only)
* OPA192 in the Network F fabric (Exp 33: isolated pass, fabric timeout)
* OPA388 at 2.61 V on ±2.5 V (Exp 33: clips, |err| 90.5 mV)
* treating the Exp 33 ~575 µV 32-copy OPA189 residual as a physical Vos (Exp 34: isolated 32-copy 0.66 µV; fabric mean 192 µV is one 2.29 mV vector at default reltol)
* 32 OPA189 instances without live dest–TIA coupling (Exp 34: 32 OPA, one live hidden, residual 0.66 µV)
* independent ±15 V supplies on fabric OPA189 (Exp 34: MAE 1.014e-3, same as shared)
* a LEVEL 2 dest VCVS buffer as dest-loading proof (Exp 34: MAE 3.48e-3)
* promoting `reltol=1e-6` as N=32 physical validation (Exp 34: diagnostic analog-pass 5.10e-4 only)

## CURRENT BEST NUMERICAL RESULT

* Isolated o2 MOS miller+servo |Vlin−z| ≈ **5.6e-5** (Exp 26, 27 °C, ±2.5 V, teaching BSIM3)
* Isolated o2 MOS miller no-servo |Vlin−z| ≈ **8.0e-2** (A_eff ≈ 1.7e3)
* Isolated o2 MOS 0.5% R MAE ≈ **1.02e-2** lumped / **6.93e-3** tiled (Exp 26)
* Isolated o2 Exp 27 ratio-matched 0.5% MAE ≈ **8.9e-4**; independent N=16 MAE ≈ **2.6e-3**
* Isolated o2 Exp 27 unbuf CDS −40/27/85 °C |err| ≈ **1.5e-4 / 2.6e-4 / 4.6e-4** (MOS-only T)
* Isolated o2 Exp 28 VG charge-amp + MOS invert −40/27/85 °C |err| ≈ **2.5e-4 / 2e-6 / 2.8e-4** (driven; P≈8.80 mW)
* F Architecture I nominal MAE ≈ **3.8e-15**
* F servo + 214 µV (Exp 24, LEVEL 2 DC) MAE ≈ **7.4e-9**
* F servo TRAN + 1 kHz pole, 12-vector subset (Exp 25) MAE ≈ **6.4e-5**
* F AZ-Vref + 214 µV (Exp 24, LEVEL 2 TRAN) MAE ≈ **4.84e-4**
* F Architecture A / L (A=1e5, Vos=0) MAE ≈ **4.8e-4**
* F L + 214 µV uncorrected MAE ≈ **7.4e-3**
* F OPA1656 macromodel MAE ≈ **0.017** (acc 100%)
* F OPA171 macromodel MAE ≈ **0.149** (acc 75%)
* F 0.5% R (L or servo) MAE ≈ **4.2e-3** (acc ~99%)
* F Exp 29 independent 0.5% 40-vector MAE ≈ **4.19e-3** (acc 99.4%, analog pass 0)
* F Exp 29 per-neuron ratio-matched 0.5% (15% residual) 16-draw 40-vector MAE mean **8.02e-4**, worst **9.38e-4**, analog pass 1.0, acc 1.0 (limited MC, not a yield)
* F Exp 30 polarity + XSPICE limit invert F40 MAE **4.86e-4**, acc 1.0
* F Exp 30 all-hidden OPA1656 F12 MAE **2.64e-3**, acc 1.0
* F Exp 31 OPA invert scaling N=1/8/16/32 MAE **5.32e-4 / 7.16e-4 / 1.45e-3 / 2.64e-3**
* F Exp 31 behavioral hidden Vos=500 µV MAE **2.667e-3** (matches 32-OPA)
* F Exp 32 replica −mid invert F12 MAE **5.101e-4**, F40 MAE **4.838e-4**, acc 1.0 (LEVEL 3+2)
* F Exp 32 replica +mid invert F12 MAE **2.41** (common-mode IN+ is not a cancel)
* Isolated Exp 30 miller invert |Vout+Vin| **0.655 V** at 1.5 V / 4.91 kΩ; **1.97 V** at 2.61 V / 4.91 kΩ
* Isolated Exp 30 OPA1656 invert |Vout+Vin| **9.96e-4** at 2.61 V / 4.91 kΩ
* Isolated Exp 32 replica −mid |Vout+Vin| **1.3e-7** at 2.61 V / 4.91 kΩ
* Isolated Exp 33 OPA189 |Vout+Vin| **0.64–0.68 µV** at 2.61 V / 4.91 kΩ (−40/27/85 °C <2 µV)
* F Exp 33 OPA189 N=16/32 MAE **7.62e-4 / 1.014e-3** (N=32 analog-fail; acc 1.0)
* Isolated Exp 34 32-copy OPA189, actual hy+Rfab, |err| **0.66 µV**
* F Exp 34 OPA189 N=32 default-reltol MAE **1.014e-3**; reltol=1e-6 diagnostic MAE **5.10e-4** (not promoted)
* F Exp 35 OPA189 N=32 qualified: DC reltol=5e-5 MAE **5.1038e-4** (3 repeats); TRAN gear 200 µs MAE **5.1668e-4**
* F Exp 36 OPA189 F40 qualified DC MAE **6.313e-4** (vector 18 still 2.30 mV invert); Gear 200 µs MAE **4.859e-4**, acc 1.0

## CURRENT BEST CLASSIFICATION RESULT

100% on A and F for I, TIA-A, L, servo, and Vref-gated AZ. Uncorrected L map: 100% class in all 42 (A, Vos) cells including A=1e4 and Vos=214 µV. 0.5% R on F drops to ~98.75%. LEVEL 3 OPA1656 Network A dropped to **98%**; OPA171 on F remains **75%** from Exp 23.

## CURRENT MOST PROMISING NEXT DIRECTION

**Enlarge the SKY130 o2 resistor area to the model-Pelgrom 0.075% WL, or move analog ground to mid-rail for 2.94 V.** Experiment 39 ran official SKY130A. Isolated o2 works as a LEVEL 1 model cell but misses the analog bar. Do not tape out. Do not transistorize Network F. Do not invent a mismatch PDF.

SKY130A `1689ac3f…`. o2 Rf*G **140.894**. W=1 |err| **5.924e-3** (tt=ll=hh). W=10 **2.274e-3**. Miller 200 us **1.667e-3**. tt_mm n=20 MAE **0.0196**. Decision **B**.

---

## Experiment table

| Exp | Arch | Net | MAE | Acc | nR | Active / copies | R range | Modeled current | Main limitation | vs prev | Level |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 16 I | invert+dump | F | 3.8e-15 | 1.00 | 1342 | 48 dumps, 0 CCCS | 1k–1M | ΣG·1 V (relative) | dump gain 0.1% → 1.25e-3 | best copies | 2 |
| 17 A | feedback TIA | F | 5.2e-4 | 1.00 | 1342 | 48 TIA, 0 dumps | 1k–1M | relative | Vos / finite A / Rf | copy gone; comb worse | 2 |
| 17 A comb | TIA + 1 mV Vos MC | F | 3.50e-2 | ~1.00 | 1342 | 48 TIA | 1k–1M | relative | Vos dominates | — | 2 |
| 18 P | passive Rf, isolated ReLU | F | 0.626 | 0.10 | 1342 | 0 TIA, 0 dumps | 1k–1M | relative | V = I R / (1+Rf G_tot) | **worse** (bound) | 2 |
| 18 L | passive mesh cascade | F | 0.626 | 0.025 | 1342 | 0 TIA | 1k–1M | relative | coupled mesh ≠ MLP | **worse** (bound) | 2 |
| 19 N | replica-null TIA | F | 4.7e-4 nom / 3.21e-2 @ 1 mV Vos | 1.00 / 1.00 | 2462 | 96 TIA + 48 subtractors | 1k–1M | relative | shared-tap Vos | not promoted | 2–3 |
| 20 J | current ReLU + per-w CCCS | F | 4.5e-13 | 1.00 | 640 | **512 CCCS** + 16 dumps | 1k–1M | relative | copy explosion | worse on copies | 2 |
| 20 S | current splitter | A | 0.347 | 0.98 | 26 | 0 CCCS | 1k–1M | relative | I G/G_tot ≠ w I | **worse** (bound) | 2 |
| 20 S | current splitter | F | compile fail | — | — | — | R>1M | — | range + wrong math | bound | 2 |
| 21 A | TIA A=100 | F | 0.279 | 0.725 | 1342 | 48 TIA | 1k–1M | relative | per-neuron k_j | explains A sweep | 2 |
| 22 A | TIA req. extract | F | 8.82e-4 @ A=5.48e4 | 1.00 @ A>=1e4 | 1342 | 48 TIA | 1k–1M | relative | Vos ~22 µV analog | specs, not a new arch | 2 |
| 23 L | XSPICE limit TIA | F | 4.91e-4 | 1.00 | 1342 | 48 limit TIA | 1k–1M | relative | still Vos=0 | = Exp 17 A | 2 |
| 23 OPA171 | TI GWL macromodel | A | 1.30e-2 | 1.00 | ~A | 5 OPA171 + 1 pF | 1k–1M | relative | Vos + VG collapse | analog fail | 3 |
| 23 OPA171 | TI GWL macromodel | F | 1.49e-1 | 0.75 | 1342 | 48 OPA171 + 1 pF | 1k–1M | relative | o2 Vsum ~10 mV | analog+class fail | 3 |
| 23 L+214µV | documented Vos on L | F | 7.55e-3 | 1.00 | 1342 | 48 limit TIA | 1k–1M | relative | 214 µV > 22 µV | offset-limited | 2 |
| 24 L map | A×Vos feasibility | F | analog pass 15/42 | 1.00 all 42 | 1342 | 48 limit TIA | 1k–1M | relative | Vos floor ≠ f(A) | bound | 2 |
| 24 OPA1656 | TI GWL 8.75 µV model | F | 1.71e-2 | 1.00 | 1342 | 48 OPA1656 + 1 pF | 1k–1M | relative | Vsum ~498 µV | analog fail | 3 |
| 24 AZ Vin-only | S/H at Vin=0 | A | 8.11e-3 | 1.00 | 40 | 5 TIA + 5 S/H | 1k–1M | relative | stores bias as Vos | fail | 2 |
| 24 AZ-Vref | S/H Vin=Vref=0 | F | 4.84e-4 | 1.00 | 1342 | 48 TIA + 48 S/H | 1k–1M | relative | TRAN; finite-A floor | **pass analog** | 2 |
| 24 servo | Vsum integrator on IN+ | F | 7.4e-9 | 1.00 | 1342 | 48 TIA + 48 G-C | 1k–1M | relative | DC OP; VG forced | **pass analog** | 2 |
| 24 servo 0.5%R | servo + mismatch | F | 4.13e-3 | 0.9875 | 1342 | 48 TIA + 48 G-C | 1k–1M | relative | R matching dominates | mismatch floor | 2 |
| 25 servo TRAN | OTA-C + 1 kHz pole | F | 6.4e-5 (12 vec) | 1.00 | 1342 | 48 TIA + 48 OTA-C | 1k–1M | relative | dwell ≥200 µs; not 10 µs | DC servo now TRAN | 2 |
| 25 servo 0.5%R | settled OP mismatch | F | 4.21e-3 | 0.992 | 1342 | 48 TIA + 48 OTA-C | 1k–1M | relative | R matching dominates | same floor | 2 |
| 26 miller+servo | BSIM3 teaching MOS | o2 iso | 5.6e-5 vs z | n/a (linear iso) | 80 | miller TIA + miller servo | frozen A | ~3.15 mW sim | teaching card; 0.5% R; temp | LEVEL 4 unit cell | 4 |
| 30 limit inv | XSPICE limit invert | F | 4.86e-4 | 1.00 | 1342 | 32 limit + 17 polarity | 1k–1M | relative | still LEVEL 2 invert | map preserved | 2 |
| 30 miller inv | teaching miller invert | iso | \|err\| 0.20–1.97 | n/a | 2 R | miller invert | frozen A | ~0.40 mW | drive/swing at 4.9 kΩ / 2.61 V | invert transfer fail | 4 |
| 30 OPA inv | 32× OPA1656 invert | F12 | 2.64e-3 | 1.00 | 1342 | 32 OPA1656 | 1k–1M | ~120 mW/amp Iq | offset stacking | analog fail | 3 |
| 31 OPA N | 1–32 OPA1656 invert | F12 | 5.3e-4 → 2.64e-3 | 1.00 | 1342 | N hidden OPA | 1k–1M | macromodel Iq | 498 µV VG pedestal × N | 16 copies fail | 3 |
| 32 replica −mid | OPA1656 + LEVEL 2 sign | F40 | 4.84e-4 | 1.00 | 1342 | 32 OPA + 1 replica | 1k–1M | macromodel Iq | sign is LEVEL 2; cell still 498 µV | analog-pass composite | 3+2 |
| 33 OPA189 | TI GWL zero-drift (static) | F12 | 7.62e-4 @N=16 / 1.014e-3 @N=32 | 1.00 | 1342 | N hidden OPA189 | 1k–1M | ~39 mW/amp Iq | isolated 0.66 µV; 32-copy ~575 µV | N=32 fail | 3 |
| 34 OPA189 fabric | 32-copy residual isolation | F12 | 1.014e-3 dflt / 5.10e-4 reltol=1e-6 | 1.00 | 1342 | 32 OPA189 | 1k–1M | ~39 mW/amp Iq | one-vector GWL OP at default reltol | N=32 not promoted | 3 |
| 35 OPA189 qual. | N=32 convergence / robustness | F12 | 5.10e-4 DC @reltol=5e-5 / 5.17e-4 TRAN gear 200 us | 1.00 | 1342 | 32 OPA189 | 1k–1M | macromodel Iq | default DC 2.29 mV Newton branch; trap TRAN hang | N=32 qualified; F40 permitted | 3 |
| 36 OPA189 F40 | full-network hidden invert | F40 | 6.31e-4 DC @5e-5 / 4.86e-4 Gear 200 us | 1.00 | 1342 | 32 OPA189 | 1k–1M | macromodel Iq ~42 mA | DC vec18 2.30 mV branch; TIA/ReLU still LEVEL 2 | F40 hidden invert validated | 3 |
| 37 miller TIA | Exp26 miller+servo in F12 | F12/iso | iso 5.63e-5; F12 Gear o2 7.95e-4 / h25 5.51e-4 | 1.00 | 1342 | 1 miller TIA + 32 OPA189 | 1k–1M | teaching-card Iq | DC insert branchy; no F40 MOS TIA; no PDK | TIA partially validated | 4+3 |
| 38 tech audit | open-PDK feasibility | F | n/a (audit) | n/a | 1342 | no PDK installed | 1k–1M | n/a | matching 0.075% + 2 nF CDS undocumented/impractical | B key data missing | docs |
| 39 SKY130 o2 | official sky130A o2 cell | o2 | 5.92e-3 W=1 / 1.67e-3 miller | n/a | iso o2 | 5V miller + xhigh_po | 1k–1M | 329 uA TIA Iq | leftover + Pelgrom area + 2.94 V | first real PDK | 4 |
| 32 OPA uncorr. | 32× OPA1656 invert | F12 | 2.64e-3 | 1.00 | 1342 | 32 OPA1656 | 1k–1M | macromodel Iq | library has no ≤100 µV loaded Vos | same as Exp 31 | 3 |

---

## Experiments 18–21 (this run)

### Experiment 18 — passive I-to-V bound

**Question.** Can `V = I × Rf` at the summing node replace the TIA?

**Result.** No. Unit cell: P matches `k z` with `k = 1/(1+Rf G_tot) = 0.495` to 4e-16 and mismatches `z` by 0.247 V. Next-layer load (Q) makes `k = 0.331`. Network F: P MAE 0.626 vs frozen map, 10% classification; isolated-loading theory MAE 1.05e-3. Local mismatch does not matter — loading already destroys analog fidelity.

Charge domain: transient `V = (I/C) t` matched (30 mV). DC is not a neuron output. Charge needs a clock; it is not a drop-in DC TIA.

**Bound.** A virtual ground (dump or TIA) is a minimum active primitive for this encoding. Changing `Rf` per neuron to force `k=1` requires `Σ|w| < 1` and is forbidden as a weight edit.

Reports: `results/exp18_passive_iv.md`, `results/passive_iv_report.json`.

### Experiment 19 — replica-null TIA

**Question.** Can `Vsig − Vrep` cancel matched Vos?

**Result.** Unit cell: yes (N MAE stays 8.3e-6 from Vos=0 to 10 mV; A goes to 2.0e-2). Full network: no meaningful win. F Vos=1 mV: A 3.50e-2, N 3.21e-2, U 3.50e-2. Combined MC: A 3.49e-2, N 3.12e-2. Cost on F: 1342 → 2462 R, 48 → 96 TIA, +1072 dummy R, +48 unity subtractors.

**Why.** Algebra on one isolated TIA cancels Vos. The fabric shares load-compensated fine taps. Dummy `G_tot` goes to 0 V, not onto those taps. Vos moves `Vsum`, which moves `Vtap`, which the replica cannot see. Fine-bank physical R can be ~1 kΩ onto the sum (`Rf G_tot` up to ~85).

**Bound.** Offset is not a local common-mode on this encoding. N is not the new best.

Reports: `results/exp19_tia_offset.md`, `results/tia_offset_report.json`.

### Experiment 20 — current-mode cascade

**Question.** Can hidden I-to-V be removed by staying in current?

**Result.** Splitter unit cell matches `I G/G_tot` (error ~1e-20) and mismatches `w I`. Network A S MAE 0.347, 98% class — classification can look fine while the analog map is wrong. F S does not compile (`R = 16.7 MΩ > 1 MΩ`). J implements frozen W2 (F MAE 4.5e-13) with **512 CCCS + 32 current ReLU + 16 dumps** versus I’s 48 dumps or A’s 48 TIA.

**Bound.** Kirchhoff current division is ratiometric and the wrong multiply. Arbitrary frozen W2 in current mode needs a copy per weight. That reverses Experiments 16–17.

Reports: `results/exp20_current_cascade.md`, `results/current_cascade_report.json`.

### Experiment 21 — finite A is per-neuron

**Question.** Is `k = A/(A+1)` a global scale?

**Result.** No. Hidden `G_tot` spans 17× on F (`Rf G_tot` up to 85). At A=100, `k_j ∈ [0.538, 0.944]`. MAE vs frozen 0.279; vs global-k 0.267; vs per-neuron-k 0.051. Classification: F 72.5% at A=100, 100% at A=1e4. The leftover TIA error is Experiment 18’s loading identity suppressed by A: `k_j ≈ 1 − Rf G_tot_j / A`.

**Bound.** Finite open-loop gain is not ratiometric across neurons on this fabric.

Reports: `results/exp21_finite_a_scale.md`, `results/finite_a_scale_report.json`.

### Experiment 22 — virtual-ground requirement extraction

**Question.** What specs must the Architecture A TIA satisfy for MAE <= 1e-3 versus 100% classification on frozen A/F?

**Baselines.** Architecture I still matches the frozen map at numerical precision (F MAE 3.57e-15). Architecture A at A=1e5, invert A=1e5: F MAE 4.84e-4, acc 100%, max |Vsum| 17 µV — same trend as Experiment 17.

**Worst neurons on F.** Ranked by compiled `Rf G_phys`, not by hand. Worst finite-A / Vos: **o2** (`Rf G_tot = 141`, Vos gain 142). Worst leakage (largest |dV/dI|): **h16** (`Rf G_tot = 4.92`). Median hidden: **h21** (`Rf G_tot = 39.8`). Span is **29×** across all 48 neurons (hidden-only span remains ~17× as in Exp 21). Output neurons can be harder than hidden.

**Gain.** F analog A_min **4.88e4** (log-interp; sampled pass 5.48e4, MAE 8.82e-4). F class A_min **1e4** (sampled; A=3e3 is 97.5%). A=1e5 (next decade actually simulated) is the conservative analog point (MAE 4.84e-4). Isolated h16 matches `k_j z` to ~1e-15. Isolated o2/h21 retain a leftover vs `k_j` because fine-tap dest=0 compensation is inexact at finite Vsum.

**Offset (A=1e5).** F analog |Vos| **22 µV** (tighter sign; 10 µV passes MAE, 30 µV is 1.10e-3). F class |Vos| **100 µV** (1 mV drops F to 95%). High A does **not** cancel 1 mV Vos: MAE stays ~3.42e-2 from A=1e4 to 1e6.

**Leakage (A=1e5).** F analog |Ileak| **13 nA** (+10 nA MAE 6.82e-4; +100 nA 3.39e-3). F class **100 nA**. First-order `I Rf` is ~0.43 mV at 13 nA; the network crossing is that plus the finite-A floor. Sign is asymmetric (positive leakage is worse on F).

**Rout.** Analog **19 kΩ** at A=1e5 (10 kΩ still MAE 6.3e-4; 100 kΩ MAE 1.93e-3). Class still 100% at 100 kΩ. Not the first limiter if Rout is tens of ohms.

**Bandwidth.** Behavioral RC single-pole (C open at DC), **not** transistor GBW. Worst neuron o2, A=1e5, |v-vfinal|<1e-3: **fp ≈ 121 Hz** interpolated for a 10 µs window (100 Hz → 12.2 µs, 1 kHz → 1.03 µs). Conservative measured pass: **1 kHz**. GBW proxy `A fp` ≈ **12 MHz** for 10 µs; a 1 MHz proxy (fp=10 Hz) settles in **115 µs**. DC error vs z remains ~9e-4 after settling. Classification is a DC statement.

**Design rule.** `k_j = A/(A+1+Rf G_phys,j)` over-predicts F MAE slightly (A=1e5: theory 6.31e-4 vs SPICE 4.84e-4). It is a usable sizing rule, not a SPICE correction. Worst-neuron `1-k ≈ Rf G_tot / A` still sets the analog A floor.

**Status.** REQUIREMENTS EXTRACTED. Classification is not analog equivalence.

Reports: `results/exp22_virtual_ground_requirements.md`, `results/virtual_ground_requirements_report.json`, `results/virtual_ground_worst_neurons.json`.

### Experiment 23 — virtual-ground primitive validation

**Question.** Can a documented VG/TIA primitive satisfy Experiment 22 on frozen o2 and Network A without Python correction?

**Candidates (local only).** LEVEL 2: XSPICE `limit` (L), voltage-gain OTA (O-VF, `A=gm*rout`, rout=1 ohm), high-Z OTA (O-hiZ). LEVEL 3: TI OPA171 and Microchip MCP6041 macromodels from `C:\ngspice\examples\p-to-n-examples\`, **included not copied**. OPA171 needs `ngspice -D ngbehavior=ps`.

**LEVEL 2 result.** L and O-VF at Vos=0 match Experiment 17 Architecture A: Network A MAE 3.07e-4 / 3.07e-4, Network F MAE 4.91e-4 / 4.92e-4, both 100% class. Isolated o2 analog A_min ~4.41e4 (L) / 4.43e4 (O-VF). Isolated o2 |Vos| analog ~14 µV (L). Leakage analog ~13 nA on o2. O-hiZ fails as expected (o2 MAE vs z 0.87; Rf shunts rout).

**LEVEL 3 result.** OPA171 smoke Vsum=244 µV (model `V_OS=214.023 µV`). MCP6041 smoke Vsum=-1.91 mV. Alter-continuation OP hit GWL `cl_clamp` singularities; those failures were kept. Working DC: one baked-Vin netlist per vector, bare `op`, plus **1 pF** on each OPA171 output so OP exists (simulation load C, not datasheet CL, not silicon).

After that recovery:

* Isolated o2 OPA171: MAE vs z **0.177**, max |Vsum| **10.6 mV** (VG not held under Rf G_tot=141).
* h16 / h21 / o2: MAE vs z 1.60e-3 / 1.21e-2 / 0.177.
* Network A OPA171: MAE **1.30e-2**, acc **100%**.
* Network A IN+ trim (−244 µV): MAE **7.03e-3**, still analog-fail; isolated o2 trim got **worse**.
* Network F OPA171: MAE **0.149**, acc **75%**.
* MCP6041 Network A: MAE **0.146**, acc **100%**.

**Documented-Vos injection (not an OPA171 result).** 214 µV on L IN+: A MAE 4.88e-3, F MAE 7.55e-3, both 100% class. OPA171 F is worse than this, so offset is not the only LEVEL 3 error.

**F L Monte Carlo (8 draws where mismatch).** Nominal 4.91e-4; 13 nA leak 7.63e-4 (still analog); 0.5% R 4.10e-3; 214 µV+13 nA+0.5% R **8.21e-3**. Classification stayed 100% on these L draws.

**Settling.** OPA171 ones-step on o2: |v−vfinal|<1e-3 at **23 µs**, overshoot 0. Macromodel transient, not datasheet GBW. UIC was not used for DC (GWL 1 F capacitors).

**Status.** OFFSET-LIMITED VG PRIMITIVE. L/O-VF validate the Exp 17 TIA identity at LEVEL 2. Documented LEVEL 3 op-amp macromodels do not meet analog MAE on this fabric.

Reports: `results/exp23_virtual_ground_primitive.md`, `results/virtual_ground_primitive_report.json`. Circuits: `circuits/virtual_ground_primitive/`.

---

## Answers to the standing research questions

1. **Neuron without explicit I-to-V?** Not for this frozen conductance encoding. Passive `V=IR` is a different map (Exp 18).
2. **Same passive element for accumulate + signal?** Only if you accept `V = I R / (1+R G_tot)` and per-neuron k. That is not the frozen net.
3. **Cascade in current?** Splitter ≠ W2. Per-weight CCCS works and is more expensive (Exp 20).
4. **Physical ReLU device?** Not revisited. B-source ReLU remains. Diode/precision-rectifier limits from Exp 4/12 still stand. Device-level rectifier deferred with the TIA.
5. **Ratiometric amplifier gain?** TIA gain is `Rf` (already a resistor). Open-loop A residual is per-neuron, not a ratio across the layer (Exp 21).
6. **Offset irrelevant by topology?** Isolated replica-null yes; this fabric no (Exp 19).
7. **Finite A → common-mode?** No (Exp 21).
8. **Average mismatch without exploding parts?** Unchanged since Exp 15: tiling ~1/√N; systematic signed-path / Vos / G_tot do not average away.
9. **Minimum active circuitry, one neuron:** virtual-ground I-to-V (1 TIA or 1 dump) + ReLU + invert if any `w−`. That is the floor found here.
10. **Minimum for a layer:** one VG per neuron, plus shared inverts/dividers. Not one VG per layer — each summing node needs its own VG.
11–13. **What scales with size?** VG count and invert count scale with neurons / signed sources. J’s CCCS count scales with weights (512 on F). G_tot (hence finite-A and passive-k) scale with fan-in and fine-bank physical G, not just neuron count.
14. **Averageable errors:** independent resistor mismatch (tiling).
15. **Systematic:** Vos through shared taps; per-neuron G_tot; dump/CCCS gain; signed-path mismatch.
16. **When does physical implementation stop being practical?** When the encoding requires a precision VG on every neuron *and* a fine-bank of large physical G on shared taps. Experiment 22 puts numbers on that VG: analog (F MAE<=1e-3) wants A ≳ 5e4, |Vos| ≲ 22 µV, |Ib| ≲ 13 nA, and ~12 MHz GBW proxy for 10 µs steps (or ~1 MHz for ~100 µs). A 1 mV op-amp is a classification part, not an analog part, on this fabric.
17. **Current / voltage / charge / hybrid?** Hybrid current-sum + voltage neuron state, with a VG I-to-V, is the only architecture that matched the frozen map without a copy explosion. Charge needs timing. Pure current W2 is more active, not less.

---

## Minimum neuron (Architecture A)

For one signed neuron on this encoding, a PCB would actually have to contain:

* input resistors (weights) and a bias path to Vref
* a passive invert (2 resistors + 1 op-amp) if any weight is negative
* a fine-bank divider if any |w| needs the 1e-3 domain
* **one op-amp + Rf** as a TIA (the minimum VG)
* a ReLU (behavioral now; a diode or comparator later)
* supplies, analog ground, measurement node

Ideal voltage/current sources in the netlist today: `Vin*`, `Vref`, invert/TIA VCVS or B-sources, ReLU B-source. The 0 V dump of Architecture I is an extra ideal ammeter + current copy.

LEVEL: 2–4 teaching-card MOS TIA/servo on one isolated neuron (Exp 26). Invert/ReLU/Vin still behavioral. Not LEVEL 5–6. Not silicon.

---

## Device-level status

**DEVICE-LEVEL PRIMITIVE PARTIALLY VALIDATED** on a Berkeley BSIM3v3 teaching card (ngspice CMOSOpAmp), not IHP SG13G2, not silicon.

Isolated frozen o2 miller TIA + miller servo analog-passes at 27 °C, ±2.5 V: |Vlin−z| ≈ 5.6e-5, Vsum ≈ −0.67 µV, 214 µV inject corrected, dwell 100–1000 µs analog-stable, transistor-level simulated power ≈ 3.15 mW. h16 / h21 / h31 analog-pass. 0.5% R, −40/85 °C, ±1.65 V headroom, and ±15 V overvoltage fail. Invert VCVS, Vin, and Ibias remain ideal. Network F was not transistorized.

Next justified step: a **documented PDK** (IHP SG13G2 is in the ngspice howto but not installed) for leakage/mismatch/temperature that are not teaching-card artefacts; and/or MOS auto-zero for temperature-stable offset; resistor matching remains the analog floor. Do not invent MOS parameters. Do not rebuild encoding. Do not transistorize Network F yet.

---

## Experiment 24 — offset-corrected virtual-ground search

**Question.** Can a physically meaningful offset-correction or low-offset VG meet Exp 22 analog requirements without editing weights, retraining, Python output repair, per-weight calibration, or invented MOS parameters?

**Part A.** Local macromodels: OPA1656 (8.75 µV in-file) smoke Vsum 498 µV; F MAE 0.017 acc 100%. OPA1611 isolated o2 MAE vs z 9.3e-3; Network A OP failed. LEVEL 3 does not pass analog.

**Part B.** Vin-only AZ fails (stores bias). Vref-gated AZ passes F analog MAE 4.84e-4. Chopper-eq isolated pass, Network A analog fail 5.78e-3. Summing-node servo passes F MAE 7.4e-9 at 214 µV (DC OP; Vsum ~0.2 nV). Predicted "servo nulls Vlin" is false at DC: nulling Vsum *is* VG.

**Part C.** 42-cell F map, L TIA: analog pass 15/42; class pass 42/42. At A=1e5 analog |Vos| ceiling 22 µV; A=1e6 does not raise that ceiling. High A does not cancel offset.

**Part D.** 0.5% R: L Vos=0 MAE 4.15e-3; servo 214 µV MAE 4.13e-3. After offset is solved, resistor matching dominates analog MAE.

**Status.** BEHAVIORAL SERVO VALIDATED (Vref-gated AZ also analog-passes). LEVEL 2. Closer to buildable; not a board.

Report: `results/exp24_offset_vg_search.md`. Circuits: `circuits/offset_vg_search/`.

---

## Experiment 25 — transient validation of the virtual-ground servo

**Question.** Can the Experiment 24 summing-node servo function dynamically (stability, settling, changing inputs) without Python correction or fabric redesign?

**DC reproduction.** Intact. F servo 7.38e-9; A servo 5.09e-9; F L+214 µV 7.37e-3.

**Circuit.** LEVEL 2 OTA-C: I = gm·Vsum onto C, leak 1e9, Vplus = Vos+Vint, tau = C/gm. Finite C. Optional behavioral TIA pole on XSPICE `limit` outputs (not fT).

**Unit cell.** o2 / h16 / h21 at tau=1 ms algebraic: analog-pass ~1e-8, including UIC cold start. Servo does not null Vlin.

**Stability.** Algebraic TIA: all tau 10 ns–10 ms analog-pass. Nested 1 kHz pole: tau ≤ 1 µs analog-fail (~7e-2, signal tracking). Window tau ∈ [10 µs, 10 ms]. Selected tau=10 µs.

**Networks.** A 12-vec TRAN MAE 1.70e-4; F 12-vec TRAN MAE 6.38e-5; both acc 100%, Vos=214 µV, fp=1 kHz. Disclosed subset.

**Changing inputs.** 80 µs dwell analog-fails (A seg2 MAE ~0.37). **200 µs analog-passes** A and F. Algebraic TIA A passes at 80 µs. Sampled inference, not 10 µs continuous. No reset required if dwell is long enough.

**AZ.** Isolated o2 Vref-gated AZ |Vlin−z| = 1.44e-3 = L Vos=0 finite-A floor, not servo 1e-8.

**Error budget.** 0.5% R MAE 4.21e-3; 13 nA leak 4.17e-4; combined 4.66e-3. Mismatch remains the analog floor.

**Numerical.** Algebraic Δy 9e-12; pole Δy 1e-7.

**Status.** DYNAMIC SERVO PARTIALLY VALIDATED. LEVEL 2 sampled/static inference. Not LEVEL 3–6.

Report: `results/exp25_servo_transient.md`. Circuits: `circuits/servo_transient/`.

---

## Experiment 26 — device-level physical neuron primitive

**Question.** Can one realistic transistor-level analog neuron primitive meet the Exp 22–25 electrical requirements on frozen Network F o2, without a new encoding, retraining, or Python correction?

**Model.** Berkeley BSIM3v3 v3.3.0 teaching cards from ngspice CMOSOpAmp (include, not copied). L=1.4 µm from CMOS-OP1. IHP SG13G2 is documented but not installed — not invented as a substitute. LEVEL 4 teaching-card simulation, not silicon.

**Topology.** Two-stage miller TIA + miller leaky-integrator servo on the real Architecture A o2 fabric. 5T OTA servo rejected (CM rails). Cascode miller rejected (collapsed at ±2.5 V, |err|≈4.18).

**Failure then fix.** Shared TIA/servo DW=0.00185 left Vsum stuck at the servo miller's ~100 µV Vos → ~10 mV Vlin error on o2, independent of input. Separate inverting-amp DW null (0.001487) is one-time amplifier self-balance, not per-weight calibration.

**o2 DC (27 °C, ±2.5 V).** No-servo |Vlin−z|≈8.0e-2, A_eff≈1.73e3, P≈2.19 mW. Servo |Vlin−z|≈5.6e-5 analog-pass, Vsum≈−0.67 µV, P≈3.15 mW. All five representative vectors analog-pass. 214 µV and 1 mV inject analog-pass.

**G_tot.** h16 (RfG≈4.92), h21 (≈39.8), h31 (≈4.95) analog-pass.

**Dynamics.** C=1 nF, tau≈50 µs. Step TRAN and dwells 100/200/500/1000 µs analog-pass. Multi-input 200 µs max |err|≈2.5e-4, all_pass. C=5 nF needed ≥500 µs (not promoted).

**Mismatch.** 0.1% lumped analog-pass (MAE 6.9e-4). 0.25% and 0.5% fail (0.5% MAE 1.02e-2; tiled 6.93e-3). TIA DW ±1% still analog-pass with servo on.

**Supply / temp / leakage.** ±2.5 V operating point; ±3.3 V analog-pass (overvoltage caution); ±1.65 V clips o2; ±5/±15 V overvoltage and analog-fail. −40/85 °C analog-fail (DW null is 27 °C). Gate current 0 on this card — 13 nA spec not device-validated.

**Still ideal.** Invert VCVS, Vin/Vref, Ibias, lumped C.

**Status.** DEVICE-LEVEL PRIMITIVE PARTIALLY VALIDATED.

Report: `results/exp26_device_neuron.md`. Circuits: `circuits/device_neuron/`. JSON: `results/device_neuron_report.json`.

---

## Experiment 27 — matching and temperature of the device-level neuron

**Question.** Can the Exp 26 miller TIA + miller servo be made accurate and temperature-stable enough to be a credible physical computation primitive, without editing frozen weights or Python-correcting SPICE?

**Mismatch.** Architecture A needs **ratio** accuracy, not absolute R. Common-mode 0.5% MAE = nominal (5.63e-5). Independent 0.5% N=1 MAE 6.35e-3 (this seed; Exp 26 was 1.02e-2). Tiling N=4/8/16: 3.97e-3 / 2.68e-3 / 2.62e-3 — ~1/√N then flatten. Area proxy 80×N, not die area. 1/√N projection N≥41 does not match the measured floor. Rf-only, weights-only, and invert/divider-only 0.5% are each ~4–6e-3. Ratio-matched 0.5% MAE **8.92e-4** (pass 0.625, max 2.55e-3). Centroid-stat (layout abstraction, not fabricated) 2.84e-3. Systematic +/− polarity 1.60e-2 (worst). Pair-correlated +/− without Rf matching does not beat independent +/−.

**Temperature.** Default R has no TCR; `.temp` is MOS-only (kt1/ute). R-only T was not simulated and not invented. CASE 1 replays Exp 26: −40/85 °C |err| 4.04e-3 / 4.82e-3.

**Compensation (all physical, all measured).** CASE 2 servo-miller replica: worse (8.1e-3 / 9.6e-3). Vsrv-hold AZ and replica-without-servo: no-servo, ~8e-2. MOS difference amp: gain ~0.55. Summing-node Vhold/Rf injection: no T improvement. Unbuffered capacitive CDS: −40/27/85 °C **1.49e-4 / 2.57e-4 / 4.57e-4** analog-pass, P≈3.15 mW. Miller follower of that node: 85 °C / 200 µs **1.18e-3** fail, P≈5.11 mW. LEVEL 2 VCVS CDS (labeled): all T analog-pass — algorithm works; the device gap is a driven MOS subtractor.

**Dynamics.** Unbuffered CDS at 85 °C: 100 µs fail (1.76e-3); 200/500/1000 µs pass; A–B–C–A max |err| 8.55e-4, all_pass.

**Combined MC.** N=16 independent 0.5% + 214 µV inject + MOS T∈{−40,27,85} + unbuf CDS. 24 draws, **not a yield**. Mean MAE 1.69e-3, p95 3.78e-3, worst 4.10e-3, pass 0.333. Mismatch, not temperature, is the joint floor.

**Still ideal / unvalidated.** Invert VCVS, Vin/Vref, Ibias, lumped C, high-Z CDS output, no PDK, no resistor TCR, no MOS mismatch PDF.

**Status.** DEVICE-LEVEL PRIMITIVE PARTIALLY VALIDATED.

Report: `results/exp27_matching_temperature.md`. Circuits: `circuits/exp27_matching_temperature/`. JSON: `results/exp27_matching_temperature.json`. Scripts: `scripts/exp27_matching_temperature.py`, `scripts/matching_temperature.py`.

---

## Experiment 28 — output interface for the CDS-corrected neuron

**Question.** Can a transistor-level interface extract the Exp 27 CDS plate without destroying MAE ≤ 1e-3 at −40/27/85 °C and 200 µs sampled inference?

**Plate.** Ccds=2 nF, Q≈3.46 nC at |z|≈1.73 V. DC Z is open. 1 pF or 100 MΩ on the plate analog-fails. 10 nA leak analog-fails. Teaching-card Ig=0.

**Miller diagnosis.** At 85 °C the plate is still analog-good (|Vplate−z|≈4.65e-4). The follower adds |Vout−Vplate|≈7.13e-4 (CM-dependent Vos at Vin≈1.73 V). The CDS state was not destroyed.

**Failed extracts.** Plain NMOS SF: Vgs≈0.74 V. SF+nested CDS: leftover ΔVgs≈9 mV. MOS invert without invert-servo: 1.7–3.8e-3. Ideal reset SW does not fix that invert.

**Promoted.** VG charge amp (Ccouple=2 nF, Cf=1 nF) + MOS invert+servo. Invert DW=0.0026 chosen at 27 °C only (invert-amp self-balance). −40/27/85 °C |Vout−z| **2.48e-4 / 2.4e-6 / 2.79e-4**. 100 µs fail; 200 µs–1 ms pass. A–B–C–A max |err| **7.10e-4**. Drives 100 pF and 100 kΩ at 85 °C. P≈**8.80 mW** (ΔP≈5.65 mW vs unbuf). LEVEL 2 invert control also analog-passes (isolates the VG stage). Combined 214 µV + 10 pF + MOS T: all three temps analog-pass. No R mismatch in this test.

**Does not solve** independent 0.5% resistor mismatch.

**Status.** OUTPUT INTERFACE PRIMITIVE PARTIALLY VALIDATED.

Report: `results/exp28_output_interface.md`. Circuits: `circuits/exp28_output_interface/`. JSON: `results/exp28_output_interface.json`. Scripts: `scripts/exp28_output_interface.py`, `scripts/output_interface.py`.

---

## Experiment 29 — resistor-ratio matching and Network F feasibility

**Question.** Can the frozen Network F conductance fabric meet analog MAE ≤ 1e-3 through a physically interpretable ratio-matching structure, without blind tiling, per-weight calibration, or a new encoding?

**Vehicle.** Architecture A, A=1e5, Vos=0, invert A=1e7. 1342 logical resistors (1024 weight, 48 bias, 48 Rf, 98 invert, 124 divider). Not transistorized. Limited Monte Carlo, not a yield.

**29A baseline.** Nominal F40 MAE **4.84e-4**, acc 1.0. Common-mode 0.5% = nominal. Independent 0.5% F12 mean **4.50e-3**; F40 mean **4.19e-3**, analog pass 0, acc 0.994. Experiment 27 o2 MOS numbers replayed, not overwritten.

**Sensitivity.** Rf-only and weights-only each ~2.6e-3. Invert-only ~2.93e-3. Layer 1 and layer 2 each ~3.3e-3. Fine-bank and divider and bias are analog-safe at 0.5%. The critical relationship is Rf·G on the nominal bank, plus invert ratios.

**Promoted model.** Per-neuron shared scale on {Rf, weights, bias} + pair-matched invert/divider + 15% of 0.5% local residual. F12: mean **8.38e-4**, worst 9.78e-4, analog pass 8/8. F40 16 draws: mean **8.02e-4**, p95 **9.09e-4**, worst **9.38e-4**, analog pass 16/16, acc 1.0. Network-wide Exp 27 TIA-family scale also analog-passes F40 (mean 7.67e-4).

**Failed.** Independent; global+0.5% local; Rf not tracking G; +/− pairs without Rf·G; systematic polarity (1.10e-2); centroid_stat (1.93e-3); isolated +/− ρ sweep (never mean-passes — pair matching is not TIA-ratio matching).

**Unit elements.** Quantizing frozen compiled G to k·G_unit fails analog until G_unit = G_W/4096 (~9.3e6 units, MAE 5.45e-4). G_W/1024 (~2.3e6 units) is still 1.12e-3. Explicit 8-tile isolated o2 TIA fabric still independent-fails (mean 2.61e-3). Segmentation of the frozen continuous map is not a cheap substitute for ratio grouping.

**Gradient.** Documented floorplan, not GDS. Naive / paired placement mean-fails by gx=0.01. Common-centroid + neuron-ratio still analog-passes at gx=0.02 (mean 8.17e-4).

**Requirement.** After per-neuron Rf·G grouping, unmatched local relative error must stay ≲ **0.075%** (0.125% mean-fails). This is a SPICE threshold on these abstractions, not a foundry ppm spec.

**Status.** RESISTOR-RATIO MATCHING PARTIALLY VALIDATED.

Report: `results/exp29_resistor_ratio_matching.md`. JSON: `results/exp29_resistor_ratio_matching.json`. Circuits: `circuits/exp29_resistor_ratio_matching/`. Scripts: `scripts/exp29_resistor_ratio_matching.py`, `scripts/resistor_ratio_matching.py`.

---

## Experiment 30 — physical invert primitive and matching-technology search

**Question.** Can the remaining Architecture A invert VCVS be replaced by a documented physical primitive without destroying the frozen Network F analog map, and is a local resistor technology available to host Experiment 29's Rf·G matching requirement?

**Vehicle.** Frozen Experiment 9 Network F. Architecture A TIA left as VCVS. Invert stages extracted from the compiled fabric: 49 amplifiers (16 input, 1 Vref, 32 hidden), R1=10 kΩ, target gain −1. Worst hidden load invh22 ≈ 4.91 kΩ. Worst hidden swing invh20 hy=2.608 V. Not transistorized Network F. No invented PDK.

**Requirements.** Uncompensated invert A ≥ 1e4 analog-passes F12. Invert Vos ≲ 100 µV analog-passes; 214 µV fails (MAE 1.50e-3). Input/Vref inverts copy stimulus and may be polarity copies. Hidden inverts copy a computed ReLU and are the real primitive. 200 µs isolated TRAN settles to the same DC as OP.

**Passive.** Grounded divider cannot invert about 0. Isolated Vout=+0.514 V vs −2.608 V. All-hidden F12 MAE 1.52, acc 0.

**LEVEL 2.** XSPICE `limit` on all 32 hidden inverts + input/Vref polarity: F12 MAE 5.12e-4, F40 MAE **4.86e-4**, acc 1.0. Isolated |err|=5.22e-5 at Vin=2.608 V.

**LEVEL 3.** Isolated OPA1656 just analog-passes (|err|=9.96e-4, P≈120 mW macromodel Iq). One hidden insertion analog-passes (MAE 5.32e-4). All 32 hidden OPA1656 analog-fail (MAE **2.64e-3**, acc 1.0). Offset stacking.

**LEVEL 4.** Teaching miller invert fails isolated transfer at fabric load/swing: |err|=0.655 V at 1.5 V / 4.91 kΩ, 0.205 V at 1.5 V / 8.9 kΩ, 1.97 V at 2.61 V / 4.91 kΩ. Servo recovers only Vin=0.5 V. 200 µs TRAN matches failed DC. MOS `.temp` −40/27/85 °C does not repair drive. One miller on F analog-passes MAE while the invert itself is broken — F MAE is the wrong invert metric.

**Matching.** Invert pair-matched and common-mode scale are invisible (MAE=nominal). Systematic R2/R1 of 0.075% is at the analog bar (−0.075% MAE 1.10e-3 fails). Independent invert 0.075% mean-passes; 0.5% mean-fails (2.59e-3). Same 0.075% ceiling as Experiment 29 leftover local.

**PDK.** IHP and SkyWater howtos exist; trees are absent; PDK_ROOT unset. r2_cmc example card present; OSDI plugin missing. No resistor TCR/geometry/mismatch model. Experiment 29 remains a behavioral matching specification.

**Status.** PHYSICAL INVERT PRIMITIVE PARTIALLY VALIDATED.

**Next direction.** B. Physical invert primitive is the next dominant bottleneck.

Report: `results/exp30_physical_invert_matching.md`. JSON: `results/exp30_physical_invert_matching.json`. Inventory: `results/exp30_tech_inventory.json`. Circuits: `circuits/exp30_physical_invert_matching/`. Scripts: `scripts/exp30_physical_invert_matching.py`, `scripts/physical_invert.py`, `scripts/resistor_technology_inventory.py`.

---

## Experiment 31 — hidden-inverter drive requirement and output-stage search

**Question.** Why does one hidden OPA1656 analog-pass on frozen Network F while 32 fail, and what output current / swing / Rout / Vos does the hidden invert actually require?

**Vehicle.** Frozen Experiment 9 Network F. 32 hidden Architecture A inverts. TIA left as VCVS. Not transistorized. No invented W/L or PDK.

**Reproduction.** Limit-32 MAE 5.12e-4 pass. 1× OPA1656 (invh20) MAE 5.32e-4 pass. 32× OPA1656 MAE **2.64e-3** fail, acc 1.0.

**Scaling.** N=1/2/4/8 pass (5.32e-4 … 7.16e-4). N=16 fail (1.45e-3). N=32 fail (2.64e-3). Gradual. Not a step at 32.

**Mechanism.** Every OPA invert mid sits at **~498 µV** (|Vout+Vin| ≈ 996 µV), independent of Vin and load. That is the Experiment 24 OPA1656 TIA Vsum, not drive. Behavioral Vos=500 µV on 32 hidden inverts MAE **2.667e-3**. Independent ±15 V supplies MAE identical to shared (2.637665658e-3). Model Vos=8.75 µV is harmless. Finite-A=5e3 does **not** reproduce the fail.

**Requirements.** Isolated peak |I| = **0.626 mA**. Behavioral Imax ≳ **0.40 mA** analog-passes F12; 0.20 mA collapses. Absolute |Vout| ≳ **2.5 V**; ±2.0 V fails. Linear closed-loop Rout of 4.9 kΩ still analog-passes at A=1e5 — miller failure is saturation, not Thevenin Rout. Hidden Vos ≲ **100 µV** (214 µV fails). Hidden A ≳ 3e3 analog-passes when input/Vref stay ideal.

**Physical stages.** Teaching miller isolated |err|=1.77 V. Miller+follower (documented composition) isolated |err|=0.655 V at 1.5 V / 4.91 kΩ and 1.77 V at 2.61 V. OPA1611 isolated |err|=576 µV (better than 1656, still a large residual). No candidate promoted (needs isolated pass and 16 simultaneous physical inverts).

**Status.** PHYSICAL HIDDEN INVERTER NOT YET VALIDATED.

**Next direction.** D. Documented device models are insufficient to implement the extracted requirements. The 1-vs-32 question is answered.

Report: `results/exp31_hidden_inverter_drive.md`. JSON: `results/exp31_hidden_inverter_drive.json`. Circuits: `circuits/exp31_hidden_inverter_drive/`. Scripts: `scripts/exp31_hidden_inverter_drive.py`, `scripts/inverter_requirement_extraction.py`.

---

## Experiment 32 — physical low-offset hidden-inverter primitive search

**Question.** Can a documented, repeatable physical invert primitive deliver unity inversion with ≤100 µV-scale accumulated offset, ≥0.4 mA drive, ≈2.61 V swing, and stable N=32 accumulation at 200 µs — without inventing transistors or Python-correcting SPICE?

**Vehicle.** Frozen Experiment 9 Network F. Local ngspice / vendor tree only. TIA left as VCVS. Not transistorized.

**Reproduction.** Limit-32 MAE 5.12e-4 pass. OPA N=1/8/16/32 = 5.32e-4 / 7.16e-4 / 1.45e-3 / 2.64e-3. Vos=500 µV MAE 2.667e-3. 32-OPA mid 498.11 µV, |Vout+Vin| 996.18 µV. Experiment 31 stands.

**Library.** No PDK_ROOT, no IHP, no SkyWater, no r2_cmc OSDI, no chopper/auto-zero/OP07/OPA189. Usable precision macros: OPA1656, OPA1611. Teaching miller still drive-fails at 2.61 V / 4.91 kΩ (|err| 1.97 V).

**Isolated.** Uncorrected OPA1656 |err| = 996 µV at Vin=0, 1, 2.61 V (Vin-independent). OPA1611 550–585 µV. replica mid on IN+ doubles to 1.99 mV. replica −mid: 29–134 nV. Isolated servo: 22 nV. Follower-in-loop unstable at Vin=1 V (0.666 V). Follower-out adds ~498 µV.

**Cancellation.** Disabled replica = uncorrected 32-OPA. +mid on IN+ explodes (F12 MAE 2.41). −mid on IN+ F12 MAE 5.101e-4, residual 80 nV. B-source subtract does not transfer to the fabric (F12 MAE 2.62e-3). 32-copy invert servo fails (MAE 0.424).

**Scaling / TRAN / F40.** replica −mid N=1..32 flat at nominal MAE. Isolated 100/200/500 µs |err| ~135 nV. A→B→C→A ≤10 µV. F40 MAE **4.838e-4**, acc 1.0. Switch AZ TRAN did not meas (out of interval); DC equivalent is the replica.

**Matching.** Replica-to-signal mid identity is a new relationship beyond R1/R2. R1/R2 residual ≤0.075% still applies. No foundry MC.

**Status.** PHYSICAL HIDDEN INVERTER PARTIALLY VALIDATED. The composite analog-passes. The uncorrected documented primitive does not. Missing evidence is a model/library.

**Next direction.** Accept LEVEL 2 invert (`limit` or replica-sign) and host Experiment 29 on a documented resistor PDK, or obtain a macromodel whose loaded invert mid stays ≲ 100 µV. Do not invent W/L.

Report: `results/exp32_hidden_inverter_primitive.md`. JSON: `results/exp32_hidden_inverter_primitive.json`. Inventory: `results/exp32_inverter_candidate_inventory.json`. Circuits: `circuits/exp32_hidden_inverter_primitive/`. Scripts: `scripts/exp32_hidden_inverter_primitive.py`, `scripts/hidden_inverter_primitive.py`.

---

## Experiment 33 — documented precision-inverter model and PDK gap closure

**Question.** Can a documented precision macromodel or PDK primitive meet the extracted N=32 hidden-invert requirements without behavioral output correction, or is the blocker still the absence of such a library?

**Inventory first.** `results/exp33_model_inventory_before.json`: PDK_ROOT unset, no IHP/SkyWater/r2_cmc OSDI, no chopper/OP07/OPA189 locally.

**Acquisition.** Official TI PSpice zips after that inventory, unmodified: OPA189 (`sbomae9`), OPA192 (`sbom862`), OPA388 (`sbomab3`). All Green-Williams-Lis. Offset is static `VOS_DRIFT` (DC + linear TEMP), not chopping. No PDK cloned.

**Isolated ranking (4.91 kΩ, actual hidden range).** OPA189 max |err| **0.68 µV** (Tier 1). OPA192 **9.5 µV** (Tier 1). OPA388 clips at 2.61 V on ±2.5 V. OPA1656 996 µV. Miller 1.97 V. Physical OPA189 sign of replica mid ~1.2 µV, no E-source.

**Temperature / TRAN.** OPA189 −40/27/85 °C <2 µV. 100/200/500 µs and A→B→C→A ≤1 µV.

**Scaling.** OPA189 N=1..16 analog-pass (5.10e-4 … 7.62e-4). N=32 MAE **1.014e-3** fail, acc 1.0. Not 32×0.66 µV: 32-copy probe mean invert residual **575 µV**. Independent supplies MAE 2.061e-3. OPA192 fabric timeout. F40 not earned.

**Power.** Isolated OPA189 |I(Vdd)| = 1.30 mA → ~39 mW at ±15 V; 32-hidden estimate ~1.25 W. Not full-F silicon power (TIA still VCVS).

**Status.** PHYSICAL HIDDEN INVERTER PARTIALLY VALIDATED. Isolated documented primitive exists. N=32 uncorrected does not.

**Next direction.** Close the 32-copy residual, or accept LEVEL 2 invert / replica-sign. Do not invent W/L.

Report: `results/exp33_documented_precision_primitive.md`. JSON: `results/exp33_documented_precision_primitive.json`. Ranking: `results/exp33_candidate_ranking.json`. Circuits: `circuits/exp33_documented_precision_primitive/`. Scripts: `scripts/exp33_documented_precision_primitive.py`, `scripts/documented_precision_primitive.py`. Models: `models/vendor/ti/` plus `provenance.json`.

---

## Experiment 34 — 32-copy OPA189 residual mechanism and fabric loading isolation

**Question.** Why does isolated OPA189 residual ~0.66 µV become a large mean residual at N=32 in the Architecture A fabric?

**Reproduction.** N=1/8/16/32 MAE **5.101e-4 / 5.76e-4 / 7.62e-4 / 1.014e-3**. Matches Experiment 33.

**Isolated N-copy.** N=32 shared or independent ±15 V, including actual hy+Rfab: **0.64–0.66 µV**. Hypothesis B (bare multi-instance GWL) is rejected.

**Fabric residual structure.** Default-reltol mean **192 µV** is one F12 vector at **2.29 mV**; 11/12 vectors ~0.73 µV; stage-to-stage std **1.1 µV** (shared). Not a 575 µV per-vector pedestal.

**Controls.** Isolated load to 1 kΩ, CM loop, Ccl, ReLU vs V, R1=R2: not causal. Independent supplies MAE 1.014e-3. Unused replica unchanged. LEVEL 2 replica-sign still analog-passes (5.08e-4). 32 OPA with one live hidden: **0.66 µV**. LEVEL 2 dest buffer **fails** (MAE 3.48e-3).

**Numerical.** Same fabric topology: reltol=1e-3 → 192 µV / 1.014e-3; reltol=1e-6 → **0.73 µV / 5.10e-4**. Isolated 32-copy is reltol-insensitive. Tight reltol is diagnostic only.

**Status.** PHYSICAL HIDDEN INVERTER PARTIALLY VALIDATED. Decision **E**. F40 not earned.

**Next direction.** Document a trustworthy coupled-GWL OP policy or install a PDK. Do not search another amplifier. Do not promote reltol. Do not invent W/L.

Report: `results/exp34_opa189_32copy_mechanism.md`. JSON: `results/exp34_opa189_32copy_mechanism.json`. Circuits: `circuits/exp34_opa189_32copy_mechanism/`. Scripts: `scripts/exp34_opa189_32copy_mechanism.py`, `scripts/opa189_fabric_isolation.py`.

---

## Experiment 35 — N=32 OPA189 convergence and robustness qualification

**Question.** Is the Experiment 34 `reltol=1e-6` N=32 analog-pass a robust numerical recovery of the intended operating point, or a solver-dependent escape?

**Reproduction.** Default DC MAE **1.0142e-3**, max **8.9672e-3**, invert-fail vector **6**, invert residual **2.294 mV**. `reltol=1e-6` MAE **5.1038e-4**, max **3.1576e-3**. Matches Experiment 34.

**DC map.** reltol 1e-3…1e-4 stay on the bad plateau. reltol 5e-5 and 1e-5…1e-6 stay on the good plateau (identical MAE **5.1038e-4**). reltol=2e-5 does not converge. vntol/abstol/chgtol do not move the bad branch. Vector order and full-F12 DC ICs do not move it.

**TRAN.** Independent trapezoidal F12 200 µs times out on 8/12 vectors (including at reltol=1e-6). Gear independent F12 200 µs analog-passes at factory reltol (MAE **5.1668e-4**) and at reltol=5e-5 (MAE **5.1038e-4**). Vector 6 trap TRAN already analog-passes at 100/200/500 µs. 100 µs and 1 ms gear F12 also analog-pass; 200 µs is the qualified dwell.

**Hierarchy / controls.** Isolated A/B/C remain **~0.64 µV**. Supplies do not change MAE. Replica-sign analog-passes at default DC. The 2.29 mV result exists only in the coupled fabric DC Newton.

**Repeatability.** Three DC repeats at reltol=5e-5: MAE **5.1038e-4**, worst vector 10, identical.

**Status.** PHYSICAL HIDDEN INVERTER VALIDATED AT N=32. Decision **F**. F40 permitted.

**Qualified solver policy.** DC: `.option reltol=5e-5`. TRAN inference: `.option method=gear`. Do not use default-reltol DC.

**Next direction.** F40 integration on that policy. Do not invent W/L. Do not search another amplifier.

Report: `results/exp35_opa189_convergence.md`. JSON: `results/exp35_opa189_convergence.json`. Circuits: `circuits/exp35_opa189_convergence/`. Scripts: `scripts/exp35_opa189_convergence.py`, `scripts/exp35_n32_qualification.py`.

---

## Experiment 36 — full Network F40 physical hidden-inverter integration

**Question.** Does frozen Network F analog-pass and classify 100% on F40 with all 32 hidden inverts as documented OPA189, under the Experiment 35 solver policy?

**Controls.** Ideal F40 MAE **4.838e-4**. XSPICE limit F40 MAE **4.859e-4**. N=32 DC **5.1038e-4**. N=32 Gear 200 µs **5.1668e-4**. Matches Experiments 30/35.

**Qualified DC.** `.option reltol=5e-5` F40 MAE **6.313e-4**, max **9.073e-3**, acc **1.0**. Three identical repeats. Analog-MAE-fail: vector **18** only (per-vector MAE 6.61e-3, invert residual **2.30 mV**). Factory/1e-4 pass by averaging (analog-MAE-fail [6, 18, 29]). reltol 2e-5 / 1e-5 / 1e-6 do not converge.

**TRAN.** Independent Gear 100/200/500 µs MAE **4.873e-4 / 4.859e-4 / 4.844e-4**, acc 1.0, analog-MAE-fail empty. Vector 18 recovers. Original/reversed/shuffle 200 µs MAE identical.

**Residuals.** 39/40 vectors ~0.73 µV invert; vector 18 is the known GWL branch at DC. Isolated Exp 33 remains 0.66 µV.

**Status.** FULL NETWORK PHYSICAL HIDDEN-INVERTER INTEGRATION VALIDATED. Decision **F**. Mixed-level fabric: TIA VCVS and ReLU B-source remain behavioral.

**Next direction.** Physical TIA integration against the qualified F40 map (Experiment 37). Do not invent W/L. Do not search another invert amp.

Report: `results/exp36_f40_physical_hidden_inverter.md`. JSON: `results/exp36_f40_physical_hidden_inverter.json`. Circuits: `circuits/exp36_f40_physical_hidden_inverter/`. Scripts: `scripts/exp36_f40_physical_hidden_inverter.py`, `scripts/exp36_f40_transient.py`.

---

## Experiment 37 — physical TIA integration and technology-requirement extraction

**Question.** Can the remaining Architecture A TIA be expressed as the documented Experiment 26 miller+servo primitive and tested against the actual electrical requirements of the now-qualified Network F map, without destroying that map?

**Baseline.** Experiment 36 F40 DC MAE **6.3132e-4** and Gear 200 µs MAE **4.8589e-4** reproduced exactly before any TIA change.

**Extracted requirements.** Worst neuron is still **o2** (Rf·G_tot **140.9**, G **4.23 mS**). Rf is **33.333 kOhm** on every neuron. Highest F40 |z| is **h25 at 2.94 V** (o2 2.46 V). Isolated o2 does not bound swing. Hidden ReLU B-sources isolate `h*lin` from OPA189 load.

**Isolated replay.** No-servo |err| **7.97e-2** fail. Servo **5.63e-5**, Vsum **−0.67 µV**, 214 µV inject **4.54e-5**, 200 µs **2.26e-4**. 100 µs **1.27e-3** fail. Isolated reltol 1e-6 / 5e-5 / factory-options agree.

**Loaded isolated fabrics.** o2, h5, h21, h16, h25, h3, h13 analog-pass at 27 °C.

**Insertion.** Batched F12 DC timed out (720 s). Independent DC is Newton-branchy (o2 default-DC MAE **6.20e-3**). Not promoted. Independent Gear 200 µs: o2 **7.95e-4** (repeat identical), h25 **5.51e-4**, h21 **5.78e-4**, acc 1.0. F40 physical TIA was not simulated.

**Temp / ratio.** Raw −40/85 °C fail. CDS unbuf analog-passes all three temps. Path D charge-amp 200 µs analog-passes vs z. Common-mode and ratio-matched 0.5% pass; independent 0.5% fails. Experiment 29 Rf·G model still dominates.

**Status.** PHYSICAL TIA PARTIALLY VALIDATED. Decision **B**. Mixed-level: one documented miller TIA at a time inside the OPA189 invert fabric. Not silicon. Not a PDK.

**Next direction.** Technology feasibility audit of documented open PDKs (Experiment 38). Do not invent TCR, mismatch PDFs, or W/L.

Report: `results/exp37_physical_tia_integration.md`. JSON: `results/exp37_physical_tia_integration.json`. Circuits: `circuits/exp37_physical_tia_integration/`. Scripts: `scripts/exp37_physical_tia_integration.py`, `scripts/exp37_tia_requirement_extraction.py`.

---

## Experiment 38 — semiconductor technology feasibility

**Question.** Is there a documented, realistically accessible PDK that can host the extracted Physical AI requirements without invented device parameters?

**Recalculated fabric.** 1342 logical R (1024/48/48/98/124). Worst Rf*G **o2 = 140.9**. |z|max **h25 = 2.94 V**. Worst-neuron I_max **234 uA**. Sum of per-neuron I_max **7.30 mA** (not previously labeled network current).

**Local inventory.** PDK_ROOT unset. IHP and SkyWater ngspice howtos present. Model trees absent. Teaching BSIM3 and OPA189 macromodel present. No .osdi binaries.

**Candidates.** IHP SG13G2 (3.3 V HV, rhigh, MIM 1.5 fF/um2) REFERENCE ONLY. SKY130 (5 V FETs, precision poly, MIM 2 fF/um2 e-test) REFERENCE ONLY. GF180MCU (6 V resistors/MIM) REFERENCE ONLY. Teaching BSIM3 is MOS-only. ASAP7 voltage-contradicts 2.94 V.

**Hardest gaps.** Public docs do not prove leftover matching 0.075%. Fully integrated 2 nF CDS is ~120 mm2 at 2 fF/um2 for 48 neurons (inferred area). Fabric TCR and 85 C leak UNKNOWN.

**Status.** TECHNOLOGY PLAUSIBLE BUT KEY DATA MISSING. Decision **B**. No invented PDK parameters. No transistor-level PDK simulation.

**Next direction.** Experiment 39: install official SKY130 and host one frozen o2 cell.

Report: `results/exp38_technology_feasibility.md`. JSON: `results/exp38_technology_feasibility.json`. Scripts: `scripts/exp38_technology_audit.py`. Sources: `docs/exp38_sources/sources.json`.

---

## Experiment 39 — first real SKY130 PDK o2 cell

**Question.** Can official SKY130A reproduce the frozen o2 Rf*G cell, including resistor ratio, miller TIA, leakage, temperature, and 200 us operation, without invented device parameters?

**PDK.** ciel-releases sky130A `1689ac3f2dc763876eaf967227c7dfe831b031ae` at `C:\dev\pdk`. ngspice-47. Teaching BSIM3 not used.

**o2.** Rf*G **140.894**. I_max **234.11 uA**. z_ref **-2.162 V**. Network |z|max still 2.94 V.

**Resistors.** xhigh_po rsheet 2000, tc1=-1.47e-3, Pelgrom A=0.0347. W=1 + behavioral TIA |err| **5.924e-3**; tt=ll=hh. W=10 **2.274e-3**. Settled by 100 us.

**TIA.** 5V miller, L=1.0 um from 2*Lmin, W from measured Id 132 uA @ W=5. No-servo DC/200 us |err| **1.66e-3**. Servo DC not an inference OP. OL sat at -2.31 V. Iq 329 uA.

**MC.** tt_mm n=20 MAE **0.0196**. Used Rf WL 15.7 um2 vs 2141 um2 for 0.075%. MATCHING UNRESOLVED.

**Status.** Decision **B**. LEVEL 1 model demonstration. Not silicon. Not F40.

**Next direction.** Unit/wide resistor area to the model Pelgrom target, or mid-rail 5 V for 2.94 V. Still one cell.

Report: `results/exp39_pdk_o2_cell.md`. Inventory: `results/exp39_pdk_inventory.md`. Spec: `results/exp39_pdk_requirements.md`. Scripts: `scripts/exp39_pdk_o2_cell.py`, `scripts/exp39_install_sky130.py`, `scripts/exp39_followup.py`.
