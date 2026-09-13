==================================================
EXPERIMENT 28
OUTPUT INTERFACE FOR THE CDS-CORRECTED NEURON
==================================================

Frozen Experiment 9 weights. SPICE is the source of truth.
Experiments 1–27 were not overwritten. No Python correction,
no affine fit, no per-weight calibration, no new encoding.
IHP SG13G2 is not installed. No foundry TCR or MOS mismatch PDF
was invented. Network F was not built from transistors.

## 1. Objective

Determine whether a transistor-level output interface can extract
the Experiment 27 CDS-corrected voltage on frozen Network F o2
while preserving MAE ≤ 1e-3 at −40 / 27 / 85 °C and the 200 µs
sampled-inference regime. The question is not how to build another
amplifier. It is how to transfer already-corrected analog state
without creating a new offset-limited stage.

## 2. Experiment 27 baseline

- Unbuffered capacitive CDS: −40 / 27 / 85 °C |err| ≈ 1.49e-4 / 2.57e-4 / 4.57e-4
- Output is a high-Z capacitor plate, not a driven pad
- Miller follower: 85 °C / 200 µs |err| ≈ 1.18e-3, P ≈ 5.11 mW
- Ccds = 2 nF between n1raw (TIA, low-Z) and n1lin (plate)
- AZ: NCH shorts n1lin to analog ground 0 for 200 µs (Vin=Vref=0)
- After AZ: V(n1lin) = Vraw(t) − Vraw(az)
- o2 |z| range on the representative set: ≈ −0.63 V to +1.73 V
- Neuron P ≈ 3.15 mW. Teaching BSIM3v3, not silicon

Unloaded unbuf at 200 µs is the Exp 27 replay (see §7). The §3 table
uses a 1 ms hold so droop can be read; those |err| values are therefore
slightly different from the 200 µs numbers.

## 3. High-Z CDS node characterization

Measured on the actual o2 MOS neuron with Exp 27 unbuffered CDS.
Ccds = 2.000e-09 F (netlist). n1raw is the miller TIA output (driven).
n1lin has no DC path to ground after AZ except the off NCH.
Charge at |z|≈1.73 V: Q ≈ Ccds·z ≈ 3.4571e-09 C.
DC source impedance is open (floating plate). Small-signal Z from the
TIA is 1/(s·Ccds) with n1raw held. Teaching-card Ig = 0; droop is
therefore switch leak / numerical, not a foundry junction model.

Unloaded plate vs temperature (200 µs, max-|z|):
| T (°C) | Vplate | |Vplate−z| | Vraw | Vsum |
| --- | --- | --- | --- | --- |
| -40.0 | 1.7284e+00 | 1.8294e-04 | 1.7326e+00 | 4.9308e-05 |
| 27.0 | 1.7284e+00 | 2.0402e-04 | 1.7285e+00 | 2.0310e-07 |
| 85.0 | 1.7283e+00 | 2.5774e-04 | 1.7238e+00 | -5.6628e-05 |

Unloaded plate motion after the input step (reference = t_az+50 µs;
the 10 µs point is still slewing, not droop):
| T (°C) | 10 µs | 50 µs | 100 µs | 200 µs | 500 µs | 1000 µs |
| --- | --- | --- | --- | --- | --- | --- |
| -40.0 | -6.6826e-03 | 0.0000e+00 | -5.4255e-04 | -8.2047e-04 | -8.6977e-04 | -8.7830e-04 |
| 27.0 | -2.5340e-02 | 0.0000e+00 | 1.7220e-03 | 2.6128e-03 | 2.7546e-03 | 2.7466e-03 |
| 85.0 | -5.0475e-02 | 0.0000e+00 | 5.4021e-03 | 8.0730e-03 | 8.5449e-03 | 8.5250e-03 |

Load / leak sensitivity of the raw plate at 85 °C / 200 µs:
| stimulus | |Vplate−z| | analog |
| --- | --- | --- |
| C=1e-12 | 1.3266e-03 | False |
| C=1e-11 | 9.0649e-03 | False |
| C=1e-10 | 8.2713e-02 | False |
| R=1e+08 | 2.4849e-03 | False |
| R=1e+06 | 1.9179e-01 | False |
| R=1e+05 | 1.1913e+00 | False |
| I=0e+00 | 4.5701e-04 | True |
| I=1e-09 | 5.7801e-04 | True |
| I=1e-08 | 1.6670e-03 | False |
| I=1e-07 | 1.2556e-02 | False |

Dominant raw-node mechanisms (from these sweeps): capacitive loading
and DC leakage, not finite TIA gain (the plate already carries the
CDS-corrected voltage). A 1 mV droop in 200 µs on 2 nF implies
Ileak ≈ 10 nA. Attaching Cload to the plate forms a divider with Ccds.

## 4. Why the Miller follower failed

The Exp 27 miller is a unity-gain buffer of n1cap. DW=0.00185 nulls
that buffer at Vin=0. During inference the plate sits at |z|≈1.73 V,
so the pair runs at a different common-mode than the null.

| T (°C) | Vplate | Vout | |Vout−Vplate| | |Vout−z| | |Vplate−z| |
| --- | --- | --- | --- | --- | --- |
| -40.0 | 1.7284e+00 | 1.7283e+00 | 1.4840e-04 | 3.0533e-04 | 1.5693e-04 |
| 27.0 | 1.7283e+00 | 1.7279e+00 | 3.9310e-04 | 6.5820e-04 | 2.6510e-04 |
| 85.0 | 1.7281e+00 | 1.7274e+00 | 7.1272e-04 | 1.1777e-03 | 4.6498e-04 |

At 85 °C the plate is still analog-good (|Vplate−z|=4.6498e-04) while the follower output is not (|Vout−z|=1.1777e-03). The buffer introduces |Vout−Vplate|=7.1272e-04. That is common-mode / temperature-dependent input offset of the teaching miller at Vin≈1.73 V, plus any incomplete 200 µs settle — not destruction of the CDS plate itself.

## 5. Output-interface requirements

Extracted from the raw-plate sensitivity sweeps. Not invented.

| quantity | limit | how extracted |
| --- | --- | --- |
| max |Vos| at signal CM | 7.4226e-04 | 1e-3 bar minus raw CDS residual |
| max |Ileak| onto plate | I=1e-08 | I such that |err| crosses 1e-3 |
| max Cload on plate | C=1e-12 | C such that |err| crosses 1e-3 |
| min Rload on plate | R=1e+08 | R such that |err| crosses 1e-3 |
| min dwell | 2.0000e-04 | Exp 27/28 85 °C dwell sweep |
| output swing | ≥ |z|≈1.73 V | o2 max-|z| vector |
| Q available | 3.4571e-09 | Ccds·z |

An interface that presents Cgg≪Ccds and Ig≪10 nA does not destroy
the plate by loading. An interface that reintroduces Vos(CM=z) will
fail even if it does not load the plate (the miller lesson).

## 6. Candidate ranking

Ranked before the device-level campaign, by whether the active
element can operate at the DW-nulled CM~0 or otherwise cancel the
same pedestal the CDS already removed.

1. VG charge amp (Ccouple from plate into miller IN-): TIA supplies
   the charge through Ccds; the new miller sits at virtual ground.
2. NMOS SF, body=source, nested CDS: gate C much less than Ccds;
   nested CDS cancels Vgs(0); leftover is dVgs(Vin).
3. LEVEL 2 VCVS buffer: control; proves the plate is readable.
4. Exp 27 miller follower: already failed; diagnosis only.
5. Plain NMOS SF: Vgs ~ 0.8 V, rejected a priori, measured anyway.
6. Charge-amp dump that resets the plate: destroys A-B-C-A tracking.
   Not promoted; the coupled (non-resetting) charge amp is used instead.

Not tested: bootstrapped-switch layout (no layout), ping-pong dual
neuron (complexity), current-mode readout into a later TIA (second
computation, not an extract).

## 7. Device-level candidate results

All on the actual o2 CDS neuron, 200 µs dwell, max-|z| vector.
| candidate | T | |Vout−z| | |Vout−Vplate| | P (W) | analog | level |
| --- | --- | --- | --- | --- | --- | --- |
| unbuf | -40.0 | 1.4921e-04 | 0.0000e+00 | 3.1807e-03 | True | L4 |
| unbuf | 27.0 | 2.5723e-04 | 0.0000e+00 | 3.1526e-03 | True | L4 |
| unbuf | 85.0 | 4.5701e-04 | 0.0000e+00 | 3.1356e-03 | True | L4 |
| vcvs | -40.0 | 1.4915e-04 | 0.0000e+00 | 3.1807e-03 | True | L2 |
| vcvs | 27.0 | 2.5724e-04 | 0.0000e+00 | 3.1526e-03 | True | L2 |
| vcvs | 85.0 | 4.5698e-04 | 0.0000e+00 | 3.1356e-03 | True | L2 |
| miller | -40.0 | 3.0533e-04 | 1.4840e-04 | 5.1568e-03 | True | L4 |
| miller | 27.0 | 6.5820e-04 | 3.9310e-04 | 5.1064e-03 | True | L4 |
| miller | 85.0 | 1.1777e-03 | 7.1272e-04 | 5.0763e-03 | False | L4 |
| sf_plain | -40.0 | 7.3395e-01 | 7.3375e-01 | 3.5969e-03 | False | L4 |
| sf_plain | 27.0 | 7.3593e-01 | 7.3562e-01 | 3.5662e-03 | False | L4 |
| sf_plain | 85.0 | 7.3818e-01 | 7.3768e-01 | 3.5478e-03 | False | L4 |
| sf_nested | -40.0 | 9.1126e-03 | 8.9198e-03 | 3.5969e-03 | False | L4 |
| sf_nested | 27.0 | 9.2076e-03 | 8.9068e-03 | 3.5662e-03 | False | L4 |
| sf_nested | 85.0 | 9.5494e-03 | 9.0489e-03 | 3.5478e-03 | False | L4 |
| qamp | -40.0 | 1.6562e-03 | 8.6271e-01 | 7.9055e-03 | False | L4 |
| qamp | 27.0 | 2.6945e-03 | 8.6161e-01 | 7.8498e-03 | False | L4 |
| qamp | 85.0 | 3.8147e-03 | 8.6046e-01 | 7.8158e-03 | False | L4 |
| qamp_invservo | -40.0 | 2.4820e-04 | 8.6462e-01 | 8.8597e-03 | True | L4 |
| qamp_invservo | 27.0 | 2.4443e-06 | 8.6430e-01 | 8.7977e-03 | True | L4 |
| qamp_invservo | 85.0 | 2.7878e-04 | 8.6399e-01 | 8.7600e-03 | True | L4 |
| qamp_l2inv | -40.0 | 1.2348e-04 | 8.6424e-01 | 5.9390e-03 | True | L2 |
| qamp_l2inv | 27.0 | 2.5559e-04 | 8.6404e-01 | 5.9043e-03 | True | L2 |
| qamp_l2inv | 85.0 | 3.6631e-04 | 8.6391e-01 | 5.8828e-03 | True | L2 |
| qamp_idealrst | -40.0 | 1.5010e-03 | 8.6288e-01 | 7.9055e-03 | False | L2 |
| qamp_idealrst | 27.0 | 2.5365e-03 | 8.6178e-01 | 7.8498e-03 | False | L2 |
| qamp_idealrst | 85.0 | 3.6416e-03 | 8.6064e-01 | 7.8158e-03 | False | L2 |

Promoted device-level candidate: **qamp_invservo**.

|Vout−Vplate| ≈ 0.86 V on the charge-amp rows is the intended
Ccds||Ccouple divider (Vplate ≈ 0.5·(Vraw−Vraw_az)), not an output error.
The driven output reconstructs +z.

qamp (MOS invert, no invert servo) misses the bar: the invert miller
at |V|≈1.73 V reintroduces millivolts. qamp_l2inv (LEVEL 2 invert)
analog-passes all T — the VG stage is not the limiter.
qamp_invservo adds a MOS invert servo and a 27 °C invert-amp DW null
(0.0026) of the same class as Exp 26
servo_dw. That DW was chosen at 27 °C only and then frozen; it was
not re-fit at −40/85 °C and is not per-input.
sf_plain is Vgs≈0.74 V. sf_nested leaves ΔVgs(Vin)≈9 mV.
qamp_idealrst still has the un-servoed MOS invert, so it fails like qamp:
the MOS reset switch is not the limiter.

## 8. Temperature behavior

Raw plate already analog-passes −40/27/85 °C. The interface must not
reintroduce MOS Vos(T) at the signal common-mode.
| candidate | −40 | 27 | 85 |
| --- | --- | --- | --- |
| unbuf | 1.4921e-04 | 2.5723e-04 | 4.5701e-04 |
| miller | 3.0533e-04 | 6.5820e-04 | 1.1777e-03 |
| sf_nested | 9.1126e-03 | 9.2076e-03 | 9.5494e-03 |
| qamp | 1.6562e-03 | 2.6945e-03 | 3.8147e-03 |
| qamp_invservo | 2.4820e-04 | 2.4443e-06 | 2.7878e-04 |
| qamp_l2inv | 1.2348e-04 | 2.5559e-04 | 3.6631e-04 |
| vcvs | 1.4915e-04 | 2.5724e-04 | 4.5698e-04 |

## 9. Dynamic sampled inference

Best candidate `qamp_invservo` at 85 °C:
| dwell | |Vout−z| | analog |
| --- | --- | --- |
| 1.0000e-04 | 1.5409e-03 | False |
| 2.0000e-04 | 2.7878e-04 | True |
| 5.0000e-04 | 6.1153e-04 | True |
| 1.0000e-03 | 6.7162e-04 | True |

A→B→C→A at 200 µs, 85 °C, one AZ then four inferences:
| step | z | Vout | |err| | analog |
| --- | --- | --- | --- | --- |
| 0 | 1.7286e+00 | 1.7286e+00 | 6.4456e-05 | True |
| 1 | -6.2892e-01 | -6.2959e-01 | 6.6737e-04 | True |
| 2 | 1.7286e+00 | 1.7293e+00 | 7.1004e-04 | True |
| 3 | 1.7286e+00 | 1.7279e+00 | 6.3069e-04 | True |
all_pass=True; max|err|=7.1004e-04.

## 10. Output loading

Loads are abstractions of a next-stage input. Not a Network F layer.
| load | |Vout−z| | analog | P (W) |
| --- | --- | --- | --- |
| hiZ | 2.7878e-04 | True | 8.7600e-03 |
| 1pF | 2.7877e-04 | True | 8.7600e-03 |
| 10pF | 2.7863e-04 | True | 8.7600e-03 |
| 100pF | 2.7729e-04 | True | 8.7600e-03 |
| 1M | 2.7956e-04 | True | 8.7687e-03 |
| 100k | 2.8653e-04 | True | 8.8464e-03 |

## 11. Power

| candidate | P (W) | ΔP vs unbuf | E per 200 µs (J) |
| --- | --- | --- | --- |
| unbuf | 3.1526e-03 | 0.0000e+00 | 6.3052e-07 |
| vcvs | 3.1526e-03 | -3.0010e-09 | 6.3052e-07 |
| miller | 5.1064e-03 | 1.9538e-03 | 1.0213e-06 |
| sf_plain | 3.5662e-03 | 4.1362e-04 | 7.1325e-07 |
| sf_nested | 3.5662e-03 | 4.1362e-04 | 7.1325e-07 |
| qamp | 7.8498e-03 | 4.6972e-03 | 1.5700e-06 |
| qamp_invservo | 8.7977e-03 | 5.6451e-03 | 1.7595e-06 |
| qamp_l2inv | 5.9043e-03 | 2.7517e-03 | 1.1809e-06 |
| qamp_idealrst | 7.8498e-03 | 4.6972e-03 | 1.5700e-06 |

One isolated neuron. Do not multiply by neuron count for Network F.

## 12. Combined test

Best device-level interface + 214 µV inject + MOS `.temp` + CDS +
10 pF load + 200 µs dwell. Resistor mismatch was **not** included
(independent 0.5% remains the network-scale floor from Exp 27;
this experiment isolates the output interface).
| T (°C) | |Vout−z| | analog | P (W) |
| --- | --- | --- | --- |
| -40.0 | 2.5852e-04 | True | 8.8596e-03 |
| 27.0 | 1.0757e-05 | True | 8.7977e-03 |
| 85.0 | 2.6298e-04 | True | 8.7600e-03 |

## 13. Error budget

| source | nominal | worst | cancellable? |
| --- | --- | --- | --- |
| raw CDS plate 85C | 2.0402e-04 | 2.5774e-04 | already the Exp 27 primitive |
| miller follower added (85C) | 3.9310e-04 | 7.1272e-04 | not at CM=z; do not follow at high CM |
| qamp_invservo vs z (85C) | 2.4443e-06 | 2.7878e-04 | the interface under test |
| plate Cload 100pF | 1.3266e-03 | 8.2713e-02 | do not load the plate; drive from the interface |
| plate Ileak 10nA | 4.5701e-04 | 1.6670e-03 | Ig=0 on this card; 10nA is a sensitivity, not a PDK leak |
| independent 0.5% R (Exp 27 N=16) | 2.6200e-03 | 5.0900e-03 | not this experiment; ratio matching |

## 14. What remains ideal

- Vin / Vref sources
- Architecture A invert VCVS on the neuron fabric
- Ideal Ibias into MOS diodes (neuron and interface)
- Lumped Ccds / Ccouple / Cf / servo C (not MIM layout)
- Analog ground 0 as the AZ short
- LEVEL 2 blocks used only as labeled controls (VCVS buffer, optional
  ideal reset / invert)

## 15. What remains unvalidated

- IHP / foundry PDK, resistor TCR, MOS mismatch PDF, switch charge
  injection as a fabrication model
- A driven pad into a real next MOS neuron (Network F forbidden)
- Silicon / board power and area
- Classification yield

## 16. Relationship to resistor matching

A working output interface does **not** solve independent 0.5% resistor
mismatch (Exp 27 N=16 MAE ≈ 2.6e-3). Architecture A still needs
resistor-ratio matching. This experiment only asks whether the
already-corrected CDS state can leave the neuron.

## 17. Recommended Experiment 29

Experiment 29 should not rebuild the encoding and should not transistorize Network F. The CDS state can leave the neuron through a VG charge amp plus a MOS invert (27C invert DW frozen). Remaining gaps: Architecture A invert VCVS on the neuron fabric, a documented PDK (resistor TCR, MOS mismatch, switch charge), and resistor-ratio matching (Exp 27 independent 0.5% N=16 MAE still ~2.6e-3). Do not invent IHP parameters. Do not retrain.

## FINAL STATUS

OUTPUT INTERFACE PRIMITIVE PARTIALLY VALIDATED

SPICE is the source of truth. Frozen Experiment 9 weights were not edited.
