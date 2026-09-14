# Debugging guide

Always vs `TP_GND`. Walk **power → VREF → inputs → inverts → H*_SUM → H*_LIN → H*_OUT → O1_LIN**.

## All outputs saturated (~±13–15 V)

- Rails swapped on one package
- IN+ of a TIA not at GND
- Feedback Rf open (`Rh*f` / `Ro1f`)
- Oscillation (scope `TP_O1LIN`)

## All outputs near zero including 01 and 10

- IN1/IN2 stuck at 0
- VREF missing so biases only; still should not zero the 01/10 paths
- Output TIA unstuffed / `Ro1f` shorted
- Measuring the wrong node

## One hidden neuron wrong

- That neuron’s weight `from` node (see frozen CSV) vs schematic
- Sign rule: hidden TIA wants **−z**. If `H*_LIN` has the wrong sign, +/− routing is swapped
- Rf 10 kΩ missing → huge gain/saturation

## Wrong XOR truth table

- 01 uses **h2**; 10 uses **h1**. If 01 fails and 10 works, debug h2 only
- `Ro1w1` comes from **H1_YN** (inverted), `Ro1w3` from **H3_Y** (not inverted)
- Class threshold accidentally 0 V

## Unexpected negative O1_LIN

- Output TIA sign routing (should be +y)
- Measuring AC coupled
- VREFN missing (b2 path)

## Oscillation

- Missing 100 nF at the package
- Long wire on `H*_SUM`
- Scope probe on SUM node
- Do not sprinkle caps on SUM without a recorded experiment

## Power-supply noise on O1_LIN

- Switcher too close; add bulk; star GND
- Measure PSRR qualitatively: 100 mV rail ripple vs output

## Reference drift

- Unbuffered divider; thermal on VREF IC
- Record TP_VREF with every XOR table

## Input loading

- High-Z source; IN drops when connected. Buffer or switch to VREF/GND

## Diode activation error

- `H*_OUT` tracks negative `H*_LIN` → diodes backwards or clamp shorted
- `H*_OUT` stuck 0 when LIN is negative-enough for ReLU (i.e. LIN < 0, should fire) → forward diode open, Rf of rectifier open

## Resistor mapping error

- Coarse E96 used (Exp67: 01/10 analog dies)
- Series pair in parallel by mistake
- 6.06 MΩ `Ro1b` contaminated (class-0 offset)

## Incorrect op-amp orientation

- TI SOIC pin 1 mark. OPA189 is **not** a 741 pinout. **Follow SBOS830.**

## Rail conflict

- Two supplies fighting; USB GND vs bench GND loop
- Disconnect extra grounds until Iq is normal
