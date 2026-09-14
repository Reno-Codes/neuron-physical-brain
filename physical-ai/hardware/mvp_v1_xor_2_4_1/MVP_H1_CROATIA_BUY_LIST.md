# MVP-H1 — click-to-buy (Croatia / EU)

**Spreadsheet with one product page per line:** [`MVP_H1_CLICK_TO_BUY.csv`](MVP_H1_CLICK_TO_BUY.csv)

Every URL is a **product page**, not a search. Open the CSV, click the link, add the quantity. Two shops: **Farnell.de** (amps + every 0.1% resistor) and **Reichelt.de** (diodes, caps, terminal, switches). Both ship in the EU, including Croatia.

Farnell prices are **net EUR**. Reichelt prices include **19% German VAT**; checkout to HR may switch to 25% PDV.

---

## Cart 1 — Farnell.de (neural parts)

Create an account, set country **Croatia**, add every `Farnell` row from the CSV.

| What | Qty | Exact page |
| --- | ---: | --- |
| OPA189ID SOIC-8 | 20 | https://de.farnell.com/texas-instruments/opa189id/op-amp-8mhz-20v-us-soic-8/dp/3004835 |
| 10 kΩ 0.1% TNPW0805 | 40 | https://de.farnell.com/vishay/tnpw080510k0beea/d-nnsch-widerstand-10k-0-1-0-125w/dp/1653329 |
| 29 other 0.1% values | 5 each | see CSV |
| **4.99 MΩ + 909 kΩ** (instead of 5.9 MΩ) | 5 + 5 | CSV lines `Ro1b_B1` / `Ro1b_B2` |

**5.9 MΩ ±0.1% thin film is not sold** on Farnell or LCSC (only 1% thick film).  
Do **not** buy 6.04 MΩ or 1% CRCW 5.9 MΩ.

Wire `Ro1b` as **three parts in series**:

`160 kΩ + 4.99 MΩ + 909 kΩ = 6.059 MΩ`

Frozen compiled `Ro1b` is 6 059 355.22 Ω. This combo is **0.006%** off. The 4.99 MΩ MCU part is on **factory lead time from 11 Nov 2026** — order it anyway; the rest of the kit can arrive first.

A few odd E192 values are **0603 or 0402** (still 0.1% thin film). The CSV `package` column says which.

---

## Cart 2 — Reichelt.de (everything else)

| Qty | What | Exact page | Price |
| ---: | --- | --- | ---: |
| 16 | 1N4148 DO-35 Diotec | https://www.reichelt.de/de/de/shop/produkt/schalt-diode_100_v_150_ma_do-35-219454 | €0.02 |
| 40 | 100 nF 50 V X7R 0805 | https://www.reichelt.de/de/de/shop/produkt/smd-kerko_0805_100_nf_50v_10_x7r_mlcc-346808 | €0.03 |
| 4 | 10 µF 50 V Panasonic EEUEB1H100S | https://www.reichelt.de/de/de/shop/produkt/elko_radial_10_f_50v_rm2_105_c_5000h_20_-376151 | €0.30 |
| 2 | WAGO 250-503 3-pole | https://www.reichelt.de/de/de/shop/produkt/klemmleiste_mit_betaetigungsdrueckern_rm_5_0_mm_17_5a_3-pol-100846 | €1.15 |
| 2 | Marquardt SPDT ON–ON | https://www.reichelt.de/de/de/shop/produkt/wippschalter_umschalter_spdt_-_ein_-_ein-334358 | €1.99 |

---

## Optional (Amazon.de / Reichelt product pages)

| What | Page |
| --- | --- |
| 30× test hooks | https://www.amazon.de/dp/B0BFX31M63 |
| Dual ±15 V PSU (skip if you have one) | https://www.reichelt.de/de/de/shop/produkt/labornetzgeraet_0_-_30_v_0_-_5_a_150_w_2_kanaele_linear-369452 |

---

## Do not buy

- `OPA189IDBVR` (SOT-23)
- Frozen E96 BOM / 6.04 MΩ
- Any 1 pF “neural” cap
- 1% thick-film 5.9 MΩ

After the boxes arrive: confirm SOIC-8 on the amps, DMM the 10 kΩ and the 4.99 MΩ+909 kΩ series, Stage 0 continuity, no ±15 V on an untested stuffed board.
