==================================================
EXPERIMENT 24
OFFSET-CORRECTED VIRTUAL-GROUND SEARCH
==================================================

Frozen Experiment 9 weights (`models/scaling/{A,F}.npz`). SPICE is the source of truth. Experiments 1–23 were not overwritten. Analog MAE versus frozen NumPy is reported separately from classification accuracy.

LEVEL 2: XSPICE `limit` TIA, auto-zero S/H, chopper-equivalent Vos modulation, summing-node servo.
LEVEL 3: documented macromodels included from the local ngspice tree (not copied).
Not LEVEL 4–6. Not board power. Not silicon. ngspice simulating a netlist is not a physical board.

Analog bar: MAE <= 1e-3. Classification: Network A `y>=0.5`; Network F `argmax`.

==================================================
1. Baseline reproduction
==================================================

Architecture I (Exp 16 current dump) and Architecture A / XSPICE L (Exp 17/23 TIA, A=1e5, Vos=0) on the same 100 / 40 vectors:

| Net | Arch | analog MAE | class | notes |
|---|---|---:|---:|---|
| A | I | 3.886e-15 | 100% | exact VG dump |
| A | L Vos=0 | 3.442e-04 | 100% | matches Exp 23 ~3.07e-4 (same bar) |
| F | I | 3.607e-15 | 100% | exact VG dump |
| F | L Vos=0 | 4.838e-04 | 100% | matches Exp 23 ~4.91e-4 |

Worst Network F neuron remains output **o2**, Rf*G_tot = **140.89**.

==================================================
2. Candidate / model inventory
==================================================

Local search only (`C:\ngspice\examples\optran\models` and `p-to-n-examples`). No arbitrary internet downloads. No vendor netlists copied into this repo.

| ID | Level | Documented model Vos | Rails used | Flags | Disposition |
|---|---:|---:|---|---|---|
| L | 2 | programmable | none (behavioral) | none | carrier for AZ / servo / chopper / map |
| OPA1656 | 3 | 8.75 µV (`VNEG = -8.75e-6`) | ±15 V | `-D ngbehavior=ps`; 1 pF load C | promoted to o2, A, F |
| OPA1611 | 3 | 97.29 µV; model Ib=60 nA | ±15 V | ps; 1 pF | isolated o2 only; A/F OP failed |
| OPA171 | 3 | 214.023 µV | ±15 V | Exp 23 negative control | not re-promoted |
| MCP6041 | 3 | smoke Vsum ~1.9 mV | 6 V class | Exp 23 | ranked out |
| TLV6001 | 3 | 595 µV | — | ngspice notes OP via optran | ranked out (Vos) |
| TLV9002 | 3 | 396 µV | — | same | ranked out (Vos) |
| TL072 | 3 | typical mV | ±15 V example | dual pinout | ranked out |
| CMOSOpAmp teaching netlist | 4 | n/a | — | default W/L | **not used** (would invent MOS parameters) |

Textbook TIA smoke (Vin=1, Rw=Rf=10 kΩ, IN+=0):

| Model | method | v(lin) | v(sum) |
|---|---|---:|---:|
| OPA1656 | op | -0.99900 | **498.1 µV** |
| OPA1611 | op | -0.99945 | 102.1 µV |

OPA1656 smoke Vsum is ~57× its documented 8.75 µV. Datasheet/model headline Vos is not the loaded-TIA summing-node residual.

==================================================
3. Worst-neuron screening (isolated o2, linear vs z)
==================================================

16 vectors of ReLU(z1) into isolated o2. Isolated MAE vs z is stricter than full-network analog MAE.

| Candidate | failed | MAE vs z | max \|Vsum\| | analog vs 1e-3 |
|---|---|---:|---:|---|
| L Vos=0 | no | 7.884e-04 | 21.7 µV | pass |
| L 8.75 µV | no | 7.454e-04 | 22.8 µV | pass |
| L 214 µV | no | 1.748e-02 | 228 µV | fail |
| OPA1656 | no | 4.167e-02 | **498 µV** | fail |
| OPA1611 | no | 9.280e-03 | 103 µV | fail |

OPA1656 holds the same ~498 µV Vsum on the Rf*G=141 neuron as on the 10 kΩ smoke cell: the macromodel is not providing the 8.75 µV VG the `VNEG` source suggests.

Loaded o2 (full shared F fabric, 8 vectors, vs software y[:,o2]):

| Candidate | MAE vs y | max \|Vsum\| |
|---|---:|---:|
| L Vos=0 | 8.185e-04 | 10.6 µV |
| L 8.75 µV | 8.881e-04 | 17.5 µV |
| L 214 µV | 1.208e-02 | 223 µV |
| OPA1656 | 2.815e-02 | 498 µV |
| OPA1611 | failed | OP/optran: empty `o2lin` |

==================================================
4. Full-network results
==================================================

| Net | Candidate | analog MAE | max abs | class | converge | rails | Vsum o2 |
|---|---|---:|---:|---:|---|---|---|
| A | L Vos=0 | 3.442e-04 | — | 100% | OP | n/a | — |
| A | OPA1656 | 1.746e-02 | 0.183 | **98%** | baked OP | ±15 V | 498 µV on iso |
| A | OPA1611 | failed | — | — | op/optran fail vec 0 | ±15 V | — |
| A | AZ Vin-only 214 µV | 8.106e-03 | 0.0104 | 100% | TRAN | n/a | ~209 µV mean |
| A | AZ-Vref 214 µV | **3.442e-04** | 8.61e-04 | 100% | TRAN | n/a | — |
| A | chopper 214 µV | 5.781e-03 | 9.32e-03 | 100% | TRAN avg | n/a | — |
| A | servo 214 µV | **5.094e-09** | 8.55e-09 | 100% | OP | n/a | ~0.2 nV iso |
| F | L Vos=0 | 4.838e-04 | — | 100% | OP | n/a | 10.6 µV loaded |
| F | L 214 µV | 7.372e-03 | 0.0228 | 100% | OP | n/a | 223 µV |
| F | OPA1656 | 1.713e-02 | 0.0557 | 100% | baked OP | ±15 V | 498 µV |
| F | OPA1611 | skipped | — | — | A failed | ±15 V | — |
| F | AZ Vin-only 214 µV | skipped | — | — | A not close enough | n/a | — |
| F | AZ-Vref 214 µV | **4.838e-04** | 3.43e-03 | 100% | TRAN | n/a | 223 µV (raw sum) |
| F | servo 214 µV | **7.375e-09** | 2.28e-08 | 100% | OP | n/a | 0.22 nV loaded |

Settling: AZ sample 20 µs, Vin/Vref step 2 µs later, measure at 68 µs of an 80 µs TRAN. Chopper period 20 µs, Vlin averaged over the last 40 µs of 200 µs. Servo reported from DC OP only.

==================================================
5. Offset-correction architecture results
==================================================

All corrections are circuit quantities (S/H, integrator, or square-wave Vos). No Python repair of Vlin. No per-weight calibration. Frozen weights unchanged.

### 5.1 Auto-zero Vin=0 only (LEVEL 2) — preserved failure

Clock: sample actual TIA output onto C while Vin=0, then Eaz = Vraw − Vhold during inference.

This **cancels bias with offset**, because Vref=1 V still drives bias conductance during the sample phase. Isolated o2 MAE vs z = 3.26e-2 (worse than doing nothing at 1.75e-2). Loaded o2 MAE vs y = 3.05e-2. Network A MAE = 8.11e-3 (class 100%). Network F skipped.

This is not a software bug. Vin=0 is not a zero-current phase on a biased neuron.

### 5.2 Auto-zero with Vref gated (LEVEL 2) — analog pass

Same S/H, but Vref is pulsed 0 → 1 V with the Vin step. Sample phase has Vin=Vref=0, so fabric currents are only the residual Vsum·G. Hold stores the offset-amplified Vraw, not k·bias.

| Bench | analog MAE | class |
|---|---:|---:|
| isolated o2 vs z | 7.884e-04 | — |
| loaded o2 vs y (8 vec) | 8.185e-04 | — |
| Network A | 3.442e-04 | 100% |
| Network F | 4.838e-04 | 100% |

These match L Vos=0 to ~ppm. Offset is removed; the finite-A floor remains. That is Success Type 2, honestly labelled behavioral (ideal `sw` + capacitor, not a physical switched-capacitor IC).

Shared-tap coupling: AZ samples the **actual** signal TIA, unlike Exp 19's dummy replica. On this F benchmark the residual tap-coupling after Vref-gated AZ is negligible next to the 1e-3 bar.

Raw Vsum during inference is still ~223 µV (the TIA loop still has Vos). Downstream uses the subtracted Vlin.

### 5.3 Chopper-equivalent (LEVEL 2)

Vos on IN+ multiplied by a ±1 square wave. Vlin averaged over the last two periods. Inputs are not swapped (that would open the TIA).

Isolated o2 MAE vs z = 6.27e-4 (analog pass on 8 vectors). Network A MAE = 5.78e-3 (analog fail, class 100%). Network F not promoted. Residual ripple / ReLU / shared fabric prevent a full-network analog pass. Not claimed as chopper hardware.

### 5.4 Summing-node servo / integrator (LEVEL 2) — analog pass, best numerical

Slow G-C integrator from Vsum onto IN+. Predicted risk: Vsum mixes Vos with Vlin/A, so nulling Vsum might null the signal. **Loaded inference shows the opposite at DC:** Vsum → 0 is the virtual-ground condition; Vlin is set by Rf and the weight current.

Isolated o2 (4 vec): MAE vs z = 1.79e-8, |Vlin|max = 1.40 V (signal intact), |Vsum|max = 0.23 nV.
Loaded o2 (4 vec): MAE vs y = 1.20e-8, |Vsum|max = 0.22 nV.
Network A: MAE = 5.09e-9, class 100%.
Network F: MAE = 7.38e-9, class 100%.

This also removes finite-A scale error k_j = A/(A+1+Rf G_j), because Vsum is forced to 0 rather than Vos − Vlin/A.

Limitation: DC OP only. Nested-loop TRAN settling is not demonstrated. Integrator is an ideal G + 1 µF + 1e9 Ω, not a device.

==================================================
6. Gain/offset feasibility map (Network F, XSPICE L, 40 vectors)
==================================================

42 SPICE cells. Classification is 100% in every cell. Analog MAE<=1e-3 in **15 / 42**.

High A does **not** cancel offset. At Vos=214 µV, MAE stays ~7.36e-3 from A=3e4 through A=1e6.

At A=1e5 (Exp 22 conservative gain):

| Vos | analog MAE | analog | class |
|---:|---:|---|---|
| 1 µV | 4.806e-04 | pass | 100% |
| 3 µV | 4.801e-04 | pass | 100% |
| 10 µV | 5.440e-04 | pass | 100% |
| 22 µV | 8.427e-04 | pass | 100% |
| 30 µV | 1.093e-03 | fail | 100% |
| 100 µV | 3.463e-03 | fail | 100% |
| 214 µV | 7.371e-03 | fail | 100% |

At A=1e6 the analog |Vos| ceiling is still 22 µV (MAE 7.58e-04); 30 µV is 1.033e-03. Offset floor is independent of open-loop A once A is large, matching Vlin ≈ z·k + Vos·(1+Rf G_tot).

Plots: `results/offset_vg_feasibility_map.png`, `results/offset_vg_network_F.png`.

==================================================
7. Analog versus classification boundary
==================================================

**Target 1 (analog equivalence, MAE<=1e-3) on uncorrected L:**
- needs A ≳ 5e4 **and** |Vos| ≲ 22 µV at A=1e5
- A=3e4 never analog-passes on this map, even at 1 µV
- A=1e4 never analog-passes (finite-A floor ~4.8e-3)

**Target 2 (task preservation) on uncorrected L:**
- 100% classification on all 42 map cells, including A=1e4 and Vos=214 µV

OPA1656 is the exception that drops Network A class to 98%: VG collapse (Vsum 498 µV) plus macromodel error, not a 8.75 µV offset.

With Vref-gated AZ or the summing-node servo, analog Target 1 is met **at 214 µV Vos** (LEVEL 2). Classification was already met without them.

==================================================
8. Minimal realistic error budget
==================================================

Network F, 40 vectors. 0.5% independent R, 8 draws. Analog bar 1e-3.

| Condition | MAE mean | MAE max | class mean |
|---|---:|---:|---:|
| L, ideal R, Vos=0 | 4.838e-04 | 4.838e-04 | 100% |
| L, 0.5% R, Vos=0 | 4.154e-03 | 4.546e-03 | 98.75% |
| L, ideal R, Vos=8.75 µV | 5.245e-04 | 5.245e-04 | 100% |
| L, 0.5% R, Vos=8.75 µV | 4.207e-03 | 4.586e-03 | 98.75% |
| L, ideal R, Vos=22 µV | 8.427e-04 | 8.427e-04 | 100% |
| servo 214 µV, ideal R | 7.375e-09 | 2.28e-08 | 100% |
| servo 214 µV, 0.5% R | 4.133e-03 | 4.647e-03 | 98.75% |

Once the VG offset architecture works, **0.5% resistor matching dominates the analog error budget**. An 8.75 µV or even 22 µV amplifier on ideal R is inside 1e-3; 0.5% R is ~4e-3 with or without the servo. Exp 15's mismatch floor was not removed by Exp 24.

==================================================
9. Best architecture
==================================================

**Best analog (this experiment):** LEVEL 2 summing-node servo on Architecture A fabric, A=1e5, Vos=214 µV.

- Network A MAE 5.09e-9, class 100%
- Network F MAE 7.38e-9, class 100%
- o2 Vsum ~0.2 nV on the loaded 4-vector bench
- 48 TIA + 48 integrators, 1342 resistors, no extra weight copies

**Best clocked offset correction:** LEVEL 2 Vref-gated auto-zero (TRAN-proven).

- Network A MAE 3.44e-4, Network F MAE 4.84e-4, both 100% class
- Restores the Vos=0 finite-A floor; does not claim better than Exp 17 L
- 48 TIA + 48 S/H + 1 clock + Vref pulse

**Best documented macromodel:** none analog-pass. OPA1656 is the least-bad LEVEL 3 (F MAE 0.017, class 100%) and is still ~35× the analog bar. Its simulated VG residual is ~498 µV, not 8.75 µV.

==================================================
10. First failure mechanism
==================================================

Uncorrected: **input offset × (1+Rf G_tot)** on neuron-dependent load, plus shared-tap coupling. Raising open-loop A does not remove that floor (map: 214 µV stays ~7.36e-3 from A=3e5 to 1e6).

LEVEL 3: OPA1656/OPA1611/OPA171 do not implement the required VG under Rf*G~141. OPA1656's failure is VG residual ~498 µV, not the 8.75 µV `VNEG` source. OPA1611 isolated o2 is offset-like (103 µV) but full-network OP does not exist in this environment.

Vin-only auto-zero fails by **storing bias as if it were Vos**.

Chopper-equivalent fails the full Network A analog bar by ripple/settling, not by DC math.

After a working LEVEL 2 VG offset loop, the **next** analog failure is 0.5% local resistor mismatch (~4e-3), as in Exp 15.

==================================================
11. Physical realism level
==================================================

| Block | Level | What was actually in the netlist |
|---|---|---|
| Weight fabric | 2 | 1342 resistors, ratiometric encoding from Exp 13–16, unchanged |
| TIA | 2 | XSPICE `limit`, A=1e5, ±15 V rails in the model card |
| Invert | 2 | resistor ratio + VCVS A=1e7 |
| ReLU | 2 | B-source `max(0,min(rail,vlin))` |
| Servo | 2 | G + C + 1e9 Ω + B-source on IN+; DC OP |
| Auto-zero | 2 | `S` switch, 10 nF, Eaz VCVS, PULSE clocks |
| Chopper-eq | 2 | B-source Vos·v(chop) |
| OPA1656/1611 | 3 | included GWL macromodels, ±15 V, 1 pF sim load C |

Physical accounting (Network F):

- Resistors: 1342 (catalog). Servo/AZ do not add weight resistors.
- TIA/VG primitives: 48
- Servo extras: 48 integrators
- AZ extras: 48 switches, 48 hold caps, 1 clock; Vref gated in the passing variant
- Macro extras: 48×1 pF (simulation OP aid, not datasheet CL)
- Supplies: none on L; ±15 V on LEVEL 3
- Settling: AZ 20 µs sample / 80 µs stop; chopper 20 µs; servo **not transient-tested**
- Relative modeled current: not converted to board watts

Not claimed: transistor count, PCB power, silicon area, chip Iq, hardware GBW of a real chopper IC.

==================================================
12. Limitations
==================================================

- Servo success is a DC operating-point result. Nested TIA+integrator dynamics, saturation, and wind-up are unknown.
- Auto-zero uses an ideal switch (ron=10 Ω, roff=1e12) and an ideal capacitor. Charge injection, kT/C, and dielectric absorption are not modeled.
- Chopper-equivalent is not input-swap demodulation.
- Inverts remain high-A VCVS. ReLU remains a B-source.
- GWL macromodels contain 1 F capacitors: UIC is not a DC method. 1 pF output C is a simulation crutch from Exp 23.
- Isolated MAE vs z is not full-network MAE.
- 0.5% R mismatch still breaks analog MAE even when Vos is solved.
- OPA1656 headline 8.75 µV is not the simulated TIA Vsum.
- Classification 100% on F is easier than analog MAE<=1e-3; they must stay separate.

==================================================
13. Honest recommendation for Experiment 25
==================================================

Do **not** rebuild resistor encoding. Do **not** invent MOS W/L on Network F yet.

The fabric plus a circuit-level VG offset loop is analog-viable at LEVEL 2. The remaining unknowns are the **dynamics and physical implementation of that VG primitive**, and the **resistor matching floor**.

Recommended Experiment 25, in order:

1. TRAN nested-loop test of the summing-node servo (step Vin, report overshoot, settling to 0.1% of z, stability). If it rings or slews past the 10 µs / 100 µs Exp 22 targets, that is the next hard bound.
2. Keep Vref-gated AZ as the clocked backup; quantify hold droop vs t_az and shared-tap residual on a larger vector set.
3. Treat 0.5% R as the analog error budget unless a tighter matching model is introduced. Classification-only products can ignore analog 1e-3.
4. Device-level unit-cell of **one** VG+servo (or VG+AZ) only after (1) shows the LEVEL 2 loop is dynamically usable. A full Network F transistor netlist is not justified while inverts and ReLU are still B/E-sources.

==================================================
FINAL STATUS
==================================================

**BEHAVIORAL SERVO VALIDATED** (and Vref-gated auto-zero also analog-passes).

What was solved: a circuit-generated offset correction on the existing Architecture A fabric meets Network F analog MAE<=1e-3 and 100% classification at 214 µV Vos, without editing weights, retraining, Python output repair, or per-weight digital calibration.

What failed: documented LEVEL 3 macromodels (OPA1656 analog MAE 0.017; OPA1611 OP failure; OPA171 already failed in Exp 23); Vin-only auto-zero (cancels bias); chopper-equivalent on Network A analog; uncorrected finite-A+Vos map above ~22 µV.

Why: uncorrected finite A is neuron-dependent (k_j); uncorrected Vos is multiplied by ~1+Rf G_tot; LEVEL 3 GWL models do not hold this VG; Vin=0 is not a zero-current AZ phase; a Vsum servo at DC *is* a VG.

What remains ideal: invert VCVS, ReLU B-source, XSPICE limit amp, ideal integrator and switch, DC-only servo, no kT/C.

Whether the project is closer to a physically buildable system: **closer**. The resistor fabric is no longer waiting on a 22 µV op-amp headline. It is waiting on a VG primitive whose loop (servo or AZ) can be given dynamics and then, if that holds, a device-level unit cell — while analog products still need ~0.1% class resistor matching, and classification-only products already work at 214 µV without correction.

SPICE is the source of truth. Frozen Experiment 9 weights were not edited.
Classification accuracy and analog MAE are reported separately.
