# Experiment 39 identity correction (controlling record)

This addendum repairs labels only. Frozen weights, SPICE decks, wrdata,
and analog numbers were not rerun or edited.

**Automated decision (first run):** C  
**Published decision (follow-up):** B — withdrawn  
**Correct decision under `decide()` and prompt §26:** C

The simulated cell is **o3 = W2[2]**, Rf·G = 7.803810456799374.  
Catalog **o2 = W2[1]**, Rf·G = 140.89398023224967, was not compiled.

Analog errors are `y_SPICE − z_o3` with `z_o3 = −2.1624190680719453 V`
(F40 vector 18). They do not characterize o2.

Matching remains **UNRESOLVED**. Analog bar **FAIL** on all promoted
inference paths. Network software `|z|max = 2.937183 V` (h25) is not a
SKY130 output. Miller Cc and servo C remain **lumped**. 2 nF ≈ 1.0 mm²
is density arithmetic.

The main report, requirements, and results canvas were aligned to this
table after identity closure. Historical filenames under
`circuits/exp39_o2/` are unchanged.
