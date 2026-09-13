# Experiment 20 — current-mode cascade bound

## TITLE
Can hidden current-to-voltage conversion be removed by cascading in current?

## QUESTION
After Experiment 18 showed passive V=IR cannot implement the frozen map, can weighted current → physical ReLU → next weighted current avoid a voltage conversion at every neuron?

## HYPOTHESIS
A resistive current splitter implements I_k = I_y * G_k/G_tot, not I_k = w_k * I_y, unless each row of W2 is normalized (it is not). Arbitrary frozen W2 in current mode requires a current copy/gain per weight. That explodes the copy count the project has been removing.

## ARCHITECTURE
- I: Experiment 16 dump (voltage after every neuron)
- J: hidden current ReLU + one CCCS per W2 weight + output dump
- S: hidden current ReLU + resistive current splitter + output dump

## WHAT CHANGED
Hidden I-to-V / voltage ReLU removed on J and S. Layer 2 is current-mode.

## WHAT REMAINED FROZEN
Experiment 9 weights. No Python correction. Output still needs I-to-V to compare against the voltage-domain software map.

## TEST CONDITIONS
Unit current cell plus networks A and F vs the frozen ReLU map.

## RESULTS

### Unit cell
- I_y=3e-05 w=[0.3, 0.5]
- wanted frozen I=(9e-06, 1.5e-05)
- wanted split I=(1.1249999999999999e-05, 1.875e-05)
- split measured I1=1.1250e-05 I2=1.8750e-05 err_vs_frozen=6.0000e-06 err_vs_partition=1.6941e-20
- CCCS measured I1=9.0000e-06 I2=1.5000e-05 err_vs_frozen=1.6941e-21

### Networks
#### Network A
- I: MAE=3.6503e-15 acc=1.0000 CCCS=0 crelu=0 dumps=5 nR=30 fail=None
- J: MAE=6.2074e-15 acc=1.0000 CCCS=4 crelu=4 dumps=1 nR=21 fail=None
- S: MAE=3.4744e-01 acc=0.9800 CCCS=0 crelu=4 dumps=0 nR=26 fail=None
#### Network F
- I: MAE=3.8056e-15 acc=1.0000 CCCS=0 crelu=0 dumps=48 nR=1342 fail=None
- J: MAE=4.5373e-13 acc=1.0000 CCCS=512 crelu=32 dumps=16 nR=640 fail=None
- S: MAE=n/a acc=n/a CCCS=None crelu=None dumps=None nR=None fail=Rh1s13 R=1.6666e+07 > r_max=1e+06

## COMPARISON WITH PREVIOUS BEST
F I MAE=3.8056e-15 CCCS=0; F J MAE=4.5373e-13 CCCS=512; F S MAE=n/a CCCS=None. Exp 16 I has 0 CCCS and 48 dumps. Exp 17 A has 0 dumps and 48 TIA.

## FAILURE MODES
S computes a normalized current partition, not W2. J implements W2 but needs one current-copy gain per hidden-to-output weight (F: 512 CCCS). 0.1% copy error would return the Experiment 12/16 bottleneck at much larger count.

## DOMINANT ERROR SOURCE
S: current-division identity I*G/G_tot. J: leftover CCCS copy gain plus output dump. I: leftover dump only.

## PHYSICAL INTERPRETATION
Unit split matches G/G_tot (err=1.6941e-20) and mismatches w*I (err=6.0000e-06). Unit CCCS matches w*I (err=1.6941e-21). Kirchhoff current division is ratiometric and physically elegant, but it is not an unnormalized matrix multiply.

## HARDWARE REALISM LEVEL
LEVEL 2 behavioral. J's CCCS would become MOS current mirrors with per-weight gain — not justified as a path that *reduces* active blocks.

## CONCLUSION
CURRENT-MODE CASCADE CANNOT REMOVE COPIES FOR FROZEN W2. A splitter is the wrong math. A CCCS fabric restores the copy explosion (512 on F). Hidden voltage conversion remains the cheaper way to apply an arbitrary next-layer weight matrix. J analog MAE=4.5373e-13 is fine and irrelevant: it loses on active-block count.

## NEXT RESEARCH QUESTION
Given VG is required (Exp 18) and current cascade is not cheaper (Exp 20), what is the minimum active primitive of one neuron, and can finite TIA A be treated as a common-mode scale?
