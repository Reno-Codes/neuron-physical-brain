# Reproducible SPICE / hardware correlation baseline

This is the hardware-package replay of the frozen XOR netlist. It does **not** modify Experiments 1–67.

## Simulation settings

| Item | Value |
| --- | --- |
| Netlist | `physical_design/xor_2_4_1/netlist.cir` |
| SHA-256 `netlist.cir` | `28dccd8121a1032d69a2b08633737db0b2f10c8996f68ed2271520ec58c3b9cb` |
| SHA-256 `xor_model.npz` | `b7448b17347bbf64cce6a72e10ebfb623255a6278917d4349e54e02cc216bb6b` |
| Analysis | `tran 5e-06 0.002 uic` |
| Solver | ngspice `ngbehavior=ps` (PSpice compatibility for OPA189) |
| Temperature | 27 °C implied (no `.temp` card in frozen deck) |
| Supplies | `Vdd=+15 V`, `Vss=−15 V` ideal |
| VREF | ideal `DC 1` |
| Inputs | ideal `Vin1`/`Vin2` 0 V or 1 V |
| Op-amp model | `models/vendor/ti/opa189/OPAx189.LIB` |
| Diode model | `models/vendor/ti/1n4148/1N4148.LIB` |
| Resistors | exact compiled ohms (not E96) |
| 1 pF caps | present in frozen deck; removing them changed yo1 by 0 V |
| Claim level | MIXED-LEVEL (vendor macromodel + discrete R). Not silicon. |

Fill measured columns in `hardware_correlation_template.csv`. Do not substitute a NumPy forward pass for `TP_O1LIN`.

## Node voltages (27 °C UIC TRAN 2 ms)

| Node | 00 | 01 | 10 | 11 |
| --- | ---: | ---: | ---: | ---: |
| IN1 (`in1`) | 0 | 0 | 1 | 1 |
| IN2 (`in2`) | 0 | 1 | 0 | 1 |
| IN1N (`in1n`) | -6.639134e-07 | -6.63913e-07 | -1.000001 | -1.000001 |
| IN2N (`in2n`) | -6.639135e-07 | -1.000001 | -6.639137e-07 | -1.000001 |
| VREF (`vref`) | 1 | 1 | 1 | 1 |
| VREFN (`vrefn`) | -1.000001 | -1.000001 | -1.000001 | -1.000001 |
| H1_LIN (`h1lin`) | 0.2633191 | 1.766247 | -0.9348376 | 0.5680899 |
| H1_OUT (`h1y`) | -3.317805e-06 | -3.318886e-06 | 0.9348269 | -3.318107e-06 |
| H2_LIN (`h2lin`) | 0.1507945 | -0.9253124 | 1.477117 | 0.4010098 |
| H2_OUT (`h2y`) | -3.316831e-06 | 0.9253017 | -3.318868e-06 | -3.317744e-06 |
| H3_LIN (`h3lin`) | 0.3858683 | 1.688048 | 2.336903 | 3.639083 |
| H3_OUT (`h3y`) | -3.125244e-06 | -3.123508e-06 | -3.129787e-06 | -3.128145e-06 |
| H4_LIN (`h4lin`) | 0.4402104 | 0.756453 | 0.8300706 | 1.146313 |
| H4_OUT (`h4y`) | -3.115493e-06 | -3.117495e-06 | -3.117038e-06 | -3.115588e-06 |
| O1_LIN (`o1lin`) | 0.001645123 | 1.002511 | 1.018006 | 0.001645121 |
| H1_SUM (`h1sum`) | 1.601377e-08 | 4.300302e-09 | 2.535328e-08 | 1.363932e-08 |
| H2_SUM (`h2sum`) | 1.689154e-08 | 2.527857e-08 | 6.55197e-09 | 1.495309e-08 |
| H3_SUM (`h3sum`) | 1.506243e-08 | 4.912604e-09 | -1.473464e-10 | -1.029655e-08 |
| H4_SUM (`h4sum`) | 1.463597e-08 | 1.21711e-08 | 1.159769e-08 | 9.132089e-09 |
| O1_SUM (`o1sum`) | 1.804997e-08 | 1.13786e-08 | 1.136829e-08 | 1.804544e-08 |
| i(Vdd) (`i_vdd`) | -0.02104821 | -0.02201999 | -0.02211107 | -0.02195107 |
| i(Vss) (`i_vss`) | 0.02114821 | 0.02223508 | 0.02233741 | 0.0224785 |

Classification from `O1_LIN`: 00→0, 01→1, 10→1, 11→0 using threshold 0.5 V.

Raw JSON: `spice_correlation_raw.json`.
