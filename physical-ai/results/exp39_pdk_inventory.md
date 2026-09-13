# Experiment 39 PDK inventory

- Family: sky130 variant sky130A
- open_pdks / ciel version: 1689ac3f2dc763876eaf967227c7dfe831b031ae
- Source: https://github.com/fossi-foundation/ciel-releases/releases/download/sky130-1689ac3f2dc763876eaf967227c7dfe831b031ae/
- Installer: ciel 2.6.1 + official common + sky130_fd_pr tarballs (Windows-safe extract)
- PDK_ROOT: C:\dev\pdk
- ngspice lib: C:\dev\pdk\sky130A\libs.tech\ngspice\sky130.lib.spice
- Runnable: True
- Resistor card: C:\dev\pdk\sky130A\libs.ref\sky130_fd_pr\spice\sky130_fd_pr__res_xhigh_po.model.spice
- 5V NFET card: C:\dev\pdk\sky130A\libs.ref\sky130_fd_pr\spice\sky130_fd_pr__nfet_g5v0d10v5__tt.pm3.spice
- Corners used: tt, ll, hh, tt_mm
- ngspice: C:\ngspice\bin\ngspice_con.exe (v47)
- xschem / magic / netgen / OpenLane: not installed
- PDK_ROOT env var: unset at start; files used by absolute path

Teaching BSIM3 was not used. ASAP7 was not used. IHP was not installed (SKY130 succeeded).
