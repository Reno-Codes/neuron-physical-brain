# Experiment 19 — replica-null TIA offset cancellation

## TITLE
Can a matched replica TIA cancel amplifier offset without a current dump?

## QUESTION
Experiment 17's combined Monte Carlo was dominated by 1 mV TIA Vos. Can Vsig − Vrep, with a dummy-G_tot replica, make Vos a common-mode error?

## HYPOTHESIS
Matched Vos and matched G_tot make the I=0 TIA output a common mode. Subtracting in SPICE cancels it. Unmatched replica Vos does not. Finite open-loop gain remains (global-ish A/(A+1)). Local resistor mismatch unbalances the replica and sets the new floor.

## ARCHITECTURE
- A: Experiment 17 feedback TIA
- N: matched replica TIA + dummy G_tot + unity subtractor
- U: same topology, replica Vos = 0

## WHAT CHANGED
Added a replica transimpedance path. Did not edit frozen weights. Did not post-correct SPICE. Added one unity VCVS subtractor per neuron.

## WHAT REMAINED FROZEN
Experiment 9 weights. Invert fabric. Direct bounded ReLU.

## TEST CONDITIONS
Vos sweep 0 / 10 µV / 100 µV / 1 mV / 10 mV. Combined MC: A=1e5, 1 mV Vos, 100 Ω Rout, 10 nA leak, 0.5% local R, 1 mV input noise.

## RESULTS

### Unit cell
- Vos=0.0: A=8.3317e-06, N=8.3317e-06, U=8.3317e-06
- Vos=0.001: A=2.0253e-03, N=8.3317e-06, U=2.0253e-03
- Vos=0.01: A=2.0202e-02, N=8.3317e-06, U=2.0202e-02

### Networks
#### Network A
- A nominal MAE=3.0915e-04 acc=1.0000 nR=40 tia=5 null=0 dmy=0
  combined MAE=2.1348e-02 acc=1.0000
  vos=0.0 MAE=2.7843e-04 acc=1.0000
  vos=1e-05 MAE=1.4685e-04 acc=1.0000
  vos=0.0001 MAE=2.0798e-03 acc=1.0000
  vos=0.001 MAE=2.3368e-02 acc=1.0000
  vos=0.01 MAE=2.4642e-01 acc=0.9500
  local first MAE>1e-3: {'name': 'local_0.5', 'value': 0.5, 'mae': 0.0023946942917925877, 'accuracy': 1.0}
  local first class<100%: None
- N nominal MAE=3.0915e-04 acc=1.0000 nR=62 tia=10 null=5 dmy=17
  combined MAE=1.4844e-02 acc=1.0000
  vos=0.0 MAE=2.7843e-04 acc=1.0000
  vos=1e-05 MAE=4.4301e-04 acc=1.0000
  vos=0.0001 MAE=1.9243e-03 acc=1.0000
  vos=0.001 MAE=1.6569e-02 acc=1.0000
  vos=0.01 MAE=1.5505e-01 acc=0.9750
  local first MAE>1e-3: {'name': 'local_0.1', 'value': 0.1, 'mae': 0.0013363609522092817, 'accuracy': 1.0}
  local first class<100%: None
- U nominal MAE=3.0915e-04 acc=1.0000 nR=62 tia=10 null=5 dmy=17
  combined MAE=2.0733e-02 acc=1.0000
  vos=0.0 MAE=2.7843e-04 acc=1.0000
  vos=1e-05 MAE=1.4685e-04 acc=1.0000
  vos=0.0001 MAE=2.0798e-03 acc=1.0000
  vos=0.001 MAE=2.3368e-02 acc=1.0000
  vos=0.01 MAE=2.4642e-01 acc=0.9500
#### Network F
- A nominal MAE=4.7272e-04 acc=1.0000 nR=1342 tia=48 null=0 dmy=0
  combined MAE=3.4944e-02 acc=1.0000
  vos=0.0 MAE=5.3862e-04 acc=1.0000
  vos=1e-05 MAE=5.6779e-04 acc=1.0000
  vos=0.0001 MAE=3.5232e-03 acc=1.0000
  vos=0.001 MAE=3.4960e-02 acc=0.9750
  vos=0.01 MAE=3.4534e-01 acc=0.7750
  local first MAE>1e-3: {'name': 'local_0.1', 'value': 0.1, 'mae': 0.0010571355651309016, 'accuracy': 1.0}
  local first class<100%: {'name': 'local_1', 'value': 1.0, 'accuracy': 0.95, 'mae': 0.008817049787096756}
- N nominal MAE=4.7272e-04 acc=1.0000 nR=2462 tia=96 null=48 dmy=1072
  combined MAE=3.1224e-02 acc=1.0000
  vos=0.0 MAE=5.3862e-04 acc=1.0000
  vos=1e-05 MAE=7.1830e-04 acc=1.0000
  vos=0.0001 MAE=3.3378e-03 acc=1.0000
  vos=0.001 MAE=3.2055e-02 acc=1.0000
  vos=0.01 MAE=3.1873e-01 acc=0.6750
  local first MAE>1e-3: {'name': 'local_0.1', 'value': 0.1, 'mae': 0.0010525005571238948, 'accuracy': 1.0}
  local first class<100%: {'name': 'local_2', 'value': 2.0, 'accuracy': 0.975, 'mae': 0.02148417949879277}
- U nominal MAE=4.7272e-04 acc=1.0000 nR=2462 tia=96 null=48 dmy=1072
  combined MAE=3.5161e-02 acc=1.0000
  vos=0.0 MAE=5.3862e-04 acc=1.0000
  vos=1e-05 MAE=5.6779e-04 acc=1.0000
  vos=0.0001 MAE=3.5232e-03 acc=1.0000
  vos=0.001 MAE=3.4960e-02 acc=0.9750
  vos=0.01 MAE=3.4534e-01 acc=0.7750

## COMPARISON WITH PREVIOUS BEST
F A nominal MAE=4.7272e-04; F N nominal MAE=4.7272e-04; F A Vos=1mV MAE=3.4960e-02; F N Vos=1mV MAE=3.2055e-02; F combined A=3.4944e-02 N=3.1224e-02 U=3.5161e-02. Exp 17 F A combined was ≈3.50e-2 (Vos-dominated).

## FAILURE MODES
Unmatched replica Vos (U) does not cancel. Local dummy/Rf mismatch unbalances a matched replica. The unity subtractor is still an ideal VCVS. Replica doubles TIA count and adds one dummy R per weight.

## DOMINANT ERROR SOURCE
Shared load-compensated fine-bank taps. A local dummy-G_tot replica cancels the private I=0 TIA term (unit cell: N stays at 8.3e-6 from Vos=0 to 10 mV). It does not sit on the shared tapref/htap nodes, so Vos-induced Vsum shifts the divider and the replica cannot see that error. Fine-bank physical G is large (e.g. 1253 Ω onto the sum), so dest-at-Vos vs dest-at-0 is a first-order tap error.

## PHYSICAL INTERPRETATION
Algebra on one isolated TIA: Vsig−Vrep = −I_src Rf A/(A+1+Rf G_tot). Vos cancels locally. The Experiment 16/17 fabric shares divider taps across neurons. Dummy resistors go to 0 V, not to those taps, so tap voltage is a signal-path error outside the replica loop. Doubling TIA count (F: 48→96) and adding 1072 dummy R therefore does not buy analog offset immunity on this encoding.

## HARDWARE REALISM LEVEL
LEVEL 2–3: plausible replica-amp topology, still behavioral controlled sources. PCB would need two op-amps and a dummy resistor network per neuron, plus a differential read. Not silicon.

## CONCLUSION
Replica-null did not clearly remove the Vos floor. Preserve the measurement. TIA-A remains the no-dump baseline.

## NEXT RESEARCH QUESTION
Is current-mode cascading able to eliminate hidden I-to-V, or does frozen W2 force per-weight current copies?
