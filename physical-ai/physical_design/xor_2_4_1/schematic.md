# Schematic (text)

Each hidden neuron:

```
in_i / in_i_n -- R(|w|) --+-- TIA --> (-z)
vref / vref_n -- R(|b|) --+      |
                                 inverting precision rectifier
                                 dest = max(-(-z), 0) = ReLU(z)
```

Hidden TIA is polarity-inverted so the rectifier can be the
textbook two-diode inverting circuit (Experiment 64).
Output TIA keeps V = +y.

Sign rule (Architecture A, inverting TIA):

- Hidden (want -w x): w>0 uses the original source
- Output (want +w x): w>0 uses the inverted source

Output neuron is the same TIA without the superdiode.
CAD schematic is not generated. This file plus `netlist.cir`
and `BOM.csv` are the build description.
