# Experiment 21 — finite TIA gain is per-neuron, not global

## TITLE
Can finite open-loop gain be treated as a ratiometric / common-mode scale?

## QUESTION
If every TIA shares k=A/(A+1), ReLU(k z)=k ReLU(z) and the map is a global scale (F argmax invariant; A threshold is not). Does the physical TIA actually share one k?

## HYPOTHESIS
k_j = A/(A+1+Rf G_tot_j). Fine-bank physical conductances make G_tot span orders of magnitude, so finite A is a per-neuron error.

## ARCHITECTURE
Experiment 17 Architecture A. No new I-to-V.

## WHAT CHANGED
Measurement only. Open-loop A swept. Predictions are physics checks, not SPICE corrections.

## WHAT REMAINED FROZEN
Experiment 9 weights. Fabric. ReLU.

## TEST CONDITIONS
A in {1e2, 1e3, 1e4, 1e5, 1e6} on networks A and F.

## RESULTS

#### Network A
- hidden G_tot span 5.1807e-05 .. 8.2776e-04 (ratio 15.98), max Rf G_tot=27.6
- A=100.0: MAE_sw=2.5539e-01 MAE_global=2.3429e-01 MAE_neuron=6.2138e-02 acc=0.920 k_h=[0.7777,0.9735]
- A=1000.0: MAE_sw=3.1078e-02 MAE_global=2.8940e-02 MAE_neuron=8.8902e-03 acc=1.000 k_h=[0.9722,0.9973]
- A=10000.0: MAE_sw=3.1746e-03 MAE_global=2.9604e-03 MAE_neuron=9.2401e-04 acc=1.000 k_h=[0.9971,0.9997]
- A=100000.0: MAE_sw=3.1814e-04 MAE_global=2.9673e-04 MAE_neuron=9.2761e-05 acc=1.000 k_h=[0.9997,1.0000]
- A=1000000.0: MAE_sw=3.1821e-05 MAE_global=2.9679e-05 MAE_neuron=9.2798e-06 acc=1.000 k_h=[1.0000,1.0000]
#### Network F
- hidden G_tot span 1.4747e-04 .. 2.5454e-03 (ratio 17.26), max Rf G_tot=84.8
- A=100.0: MAE_sw=2.7932e-01 MAE_global=2.6734e-01 MAE_neuron=5.0728e-02 acc=0.725 k_h=[0.5381,0.9441]
- A=1000.0: MAE_sw=4.5342e-02 MAE_global=4.4147e-02 MAE_neuron=1.4726e-02 acc=0.925 k_h=[0.9209,0.9941]
- A=10000.0: MAE_sw=4.8427e-03 MAE_global=4.7232e-03 MAE_neuron=1.7131e-03 acc=1.000 k_h=[0.9915,0.9994]
- A=100000.0: MAE_sw=4.8761e-04 MAE_global=4.7567e-04 MAE_neuron=1.7406e-04 acc=1.000 k_h=[0.9991,0.9999]
- A=1000000.0: MAE_sw=4.8795e-05 MAE_global=4.7600e-05 MAE_neuron=1.7433e-05 acc=1.000 k_h=[0.9999,1.0000]

## COMPARISON WITH PREVIOUS BEST
F G_tot ratio=17.3, max RfG=84.85. At A=100, MAE_sw=2.7932e-01 vs global-k 2.6734e-01 vs per-neuron-k 5.0728e-02. At A=1e5, MAE_sw=4.8761e-04.

## FAILURE MODES
Treating finite A as k=A/(A+1) under-predicts error whenever G_tot varies. Fine-bank physical G is the span.

## DOMINANT ERROR SOURCE
Per-neuron loop load Rf G_tot_j in the TIA closed-loop factor.

## PHYSICAL INTERPRETATION
The leftover TIA error is the same loading identity as Experiment 18, suppressed by A: k_j = A/(A+1+Rf G_tot_j) ≈ 1 - Rf G_tot_j/A. It is not ratiometric across neurons.

## HARDWARE REALISM LEVEL
LEVEL 2 behavioral TIA. A real op-amp would add the same G_tot into the loop equation.

## CONCLUSION
FINITE OPEN-LOOP GAIN IS NOT A GLOBAL SCALE ON THIS FABRIC.

## NEXT RESEARCH QUESTION
The research boundary is now: a virtual-ground I-to-V is required (Exp 18), current-mode W2 is more expensive (Exp 20), replica-null does not beat shared-tap Vos (Exp 19), and finite A is per-neuron (Exp 21). Device-level work should characterize ONE VG primitive, not invent a new encoding to chase MAE.
