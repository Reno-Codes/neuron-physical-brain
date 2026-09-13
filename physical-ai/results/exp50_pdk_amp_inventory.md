# Experiment 50 — Track B inventory and existing miller A_ol

Experiments 1–49 were not modified. No W/L resize. Not silicon.

**Status: NUMERICAL ISSUE**
**Decision E — OPEN-LOOP A_ol WAS NOT EXTRACTED; OUTPUT WAS RAIL-SATURATED**

The first pick A_ol ≈ −240000 is **withdrawn**. For Vid ≤ 1 mV the
isolated miller sits near VSS (−2.31 to −2.40 V). That ratio is
Vrail/Vid, not linear gain. The in-TIA a_eff ≈ 245 (Exp41/48) remains
the only defensible closed-circuit gain number.

## Inventory

SKY130A fd_pr has 5V MOS and xhigh_po. A filename scan of the ngspice tech tree found no opamp/OTA IP cells. The existing sky_miller is a campaign-constructed two-stage using documented 5V FETs and Experiment 39 sizes, not a foundry analog library cell.

- Documented opamp/OTA filenames in tech tree: none
- IHP / GF180 installed: no

## Isolated sky_miller open-loop (Exp39 sizes)

| load | Vid | Vout (V) | A_ol | headroom (V) |
| --- | ---: | ---: | ---: | ---: |
| none | 1e-05 | -2.3095655776 | -230956.55775999997 | 4.8095655776 |
| none | 0.0001 | -2.30490332914 | -23049.0332914 | 4.80490332914 |
| none | 0.001 | -2.25114101109 | -2251.14101109 | 4.7511410110900005 |
| none | 0.01 | 2.108035564014 | 210.8035564014 | 0.39196443598599995 |
| 73.71 uA | 1e-05 | -2.40187810585 | -240187.81058499997 | 4.90187810585 |
| 73.71 uA | 0.0001 | -2.39825217954 | -23982.5217954 | 4.89825217954 |
| 73.71 uA | 0.001 | -2.35789614823 | -2357.89614823 | 4.85789614823 |
| 73.71 uA | 0.01 | 1.992591792496 | 199.25917924959998 | 0.5074082075040001 |

A required (Exp43/44) = 128203. The loaded A_ol pick of −240188 is a
saturation artifact and is not used. In-TIA a_eff ≈ 245 would need
three identical copies (245² = 60025 < 128203; 245³ ≈ 1.47e7) if that
number is the true stage gain — that remains a hypothesis until
offset-nulled incremental A is measured.

Decision E — OPEN-LOOP A_ol WAS NOT EXTRACTED. Inventory stands: no
foundry opamp cell in the SKY130A tech tree. Not silicon. No W/L invented.

## Next experiment

Experiment 51: offset-null the existing miller, then measure incremental
A_ol (dVout/dVid) in the linear region. Still no W/L resize.
