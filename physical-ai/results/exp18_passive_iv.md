# Experiment 18 — passive current-to-voltage bound

## TITLE
Can a passive resistor replace the TIA for frozen-network I-to-V?

## QUESTION
Can V = I × Rf at the summing node implement the frozen neuron while preserving next-layer loading, without an active virtual ground?

## HYPOTHESIS
Passive Rf makes Vsum = I_loaded × Rf. Then I_k = (Vin_k − Vsum)/R_k, so V = Rf Σ Vin G / (1 + Rf G_tot). The denominator is a per-neuron attenuation. Because G_tot differs across neurons, this is not a global scale and cannot be absorbed without editing frozen weights. A mesh cascade (Architecture L) couples layers and is a different physical computation.

## ARCHITECTURE
- I: Experiment 16 dump (exact 0 V + current copy)
- A: Experiment 17 feedback TIA
- P: passive Rf, ReLU B-source isolates layer 2
- L: passive Rf, layer 2 attaches to hidden summing nodes

## WHAT CHANGED
Removed the TIA / dump. Placed Rf from the summing node to ground.

## WHAT REMAINED FROZEN
Experiment 9 weights. No Python output correction. Invert op-amps and ReLU B-sources remain on P. L removes hidden ReLU isolation.

## TEST CONDITIONS
Unit cell = network A hidden neuron 1. Networks A and F. Error bar MAE ≤ 0.001. Classification reported separately.

## RESULTS

### Unit cell
- weights w=[0.6837607953488155, 0.30936678304579385] b=-0.026598796257646187
- I: MAE vs numpy=1.5374e-15 MAE vs k*z=2.4745e-01 k=0.495117 max|Vsum|=0.0000e+00
- A: MAE vs numpy=9.8987e-06 MAE vs k*z=2.4744e-01 k=0.495117 max|Vsum|=1.0197e-05
- P: MAE vs numpy=2.4745e-01 MAE vs k*z=3.6559e-16 k=0.495117 max|Vsum|=5.0488e-01
- Q: MAE vs numpy=3.2781e-01 MAE vs k*z=2.8081e-16 k=0.331156 max|Vsum|=3.3769e-01

### Networks
#### Network A
- I: MAE=3.7659e-15 max=1.1990e-14 acc=1.0000 nR=30 dumps=5 tia=0 Vsum=0.0000e+00 k_h=0.1236 theory_MAE=1.1369e+00
- A: MAE=3.3615e-04 max=8.3773e-04 acc=1.0000 nR=40 dumps=0 tia=5 Vsum=1.6051e-05 k_h=0.1236 theory_MAE=1.1366e+00
- P: MAE=1.1350e+00 max=3.2557e+00 acc=0.3300 nR=30 dumps=0 tia=0 Vsum=2.1410e-01 k_h=0.1236 theory_MAE=1.6998e-02
- L: MAE=1.1433e+00 max=3.2579e+00 acc=0.3300 nR=30 dumps=0 tia=0 Vsum=1.8983e-01 k_h=0.1236 theory_MAE=2.1009e-02
- P local-mismatch first MAE>1e-3: {'name': 'local_0', 'value': 0.0, 'mae': 1.1519209319513397, 'accuracy': 0.4}
- P local-mismatch first class<100%: {'name': 'local_0', 'value': 0.0, 'accuracy': 0.4, 'mae': 1.1519209319513397}
#### Network F
- I: MAE=3.8744e-15 max=1.9540e-14 acc=1.0000 nR=1342 dumps=48 tia=0 Vsum=0.0000e+00 k_h=0.0487 theory_MAE=6.2616e-01
- A: MAE=5.2098e-04 max=3.5032e-03 acc=1.0000 nR=1342 dumps=0 tia=48 Vsum=1.3229e-05 k_h=0.0487 theory_MAE=6.2566e-01
- P: MAE=6.2587e-01 max=3.0098e+00 acc=0.1000 nR=1342 dumps=0 tia=0 Vsum=2.2364e-01 k_h=0.0487 theory_MAE=1.0483e-03
- L: MAE=6.2635e-01 max=3.0107e+00 acc=0.0250 nR=1342 dumps=0 tia=0 Vsum=1.2035e-01 k_h=0.0487 theory_MAE=1.4483e-03
- P local-mismatch first MAE>1e-3: {'name': 'local_0', 'value': 0.0, 'mae': 0.5540169605006369, 'accuracy': 0.09999999999999998}
- P local-mismatch first class<100%: {'name': 'local_0', 'value': 0.0, 'accuracy': 0.09999999999999998, 'mae': 0.5540169605006369}

### Charge domain
- DC: v=3.0000e-01 exit=0
- TRAN: v=3.0000e-02 expected=3.0000e-02

## COMPARISON WITH PREVIOUS BEST
F I MAE=3.8744e-15 acc=1.0000; F TIA-A MAE=5.2098e-04 acc=1.0000; F P MAE=6.2587e-01 acc=0.1000; F L MAE=6.2635e-01 acc=0.0250. P/L are worse than I and TIA-A on analog fidelity because the summing node is no longer a virtual ground.

## FAILURE MODES
Passive Rf sets Vsum to the neuron voltage. Weight currents become (Vin-Vsum)/R, so the frozen identity I=Vin*G is lost. Per-neuron G_tot makes attenuation non-global. Mesh L also loads hidden nodes and drops ReLU isolation. Divider compensation assumes dest≈0 V and is therefore inconsistent on P/L.

## DOMINANT ERROR SOURCE
Summing-node loading: V = Rf ΣVinG / (1+Rf G_tot). Secondary: VG-designed divider compensation on a floating dest; layer-2 resistive loading on L.

## PHYSICAL INTERPRETATION
Unit-cell P matches k*z (k=0.495117) and does not match z. F P vs isolated theory MAE=1.0483e-03. Charge on a capacitor is not a DC replacement for I-to-V: DC is an open circuit; transient voltage is (I/C)*t and needs a clock.

## HARDWARE REALISM LEVEL
LEVEL 2 non-ideal behavioral (P/L are passive at the I-to-V, but still use invert VCVS and ReLU B-sources). Not LEVEL 4–6.

## CONCLUSION
PASSIVE I-TO-V CANNOT IMPLEMENT THE FROZEN MAP. A virtual-ground (TIA or 0 V dump) is a minimum active primitive for this conductance encoding. Next: make the unavoidable TIA errors ratiometric / offset-immune.

## NEXT RESEARCH QUESTION
Can TIA input offset be cancelled by a matched replica so the Experiment 17 combined-MC floor (Vos-dominated) falls without reintroducing a current dump?
