"""SVG hierarchical schematics for Physical AI MVP v1 XOR."""

from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "hardware" / "mvp_v1_xor_2_4_1" / "schematics"


def svg(body: str, w: int, h: int, title: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
  <rect width="100%" height="100%" fill="#fbfbf8"/>
  <text x="24" y="28" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="18" fill="#1a1a1a">{title}</text>
  <text x="24" y="46" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="11" fill="#555">Physical AI MVP v1 · frozen xor_2_4_1 · mixed-level · not silicon</text>
  {body}
</svg>
"""


def box(x, y, w, h, title, lines, fill="#fff"):
    t = [
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="#222" stroke-width="1.2"/>',
        f'<text x="{x + 10}" y="{y + 18}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="12" font-weight="600" fill="#111">{title}</text>',
    ]
    for i, line in enumerate(lines):
        t.append(
            f'<text x="{x + 10}" y="{y + 38 + i * 14}" font-family="Consolas, Menlo, monospace" font-size="11" fill="#333">{line}</text>'
        )
    return "\n".join(t)


def arrow(x1, y1, x2, y2, label=""):
    s = f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#333" stroke-width="1.2" marker-end="url(#arr)"/>'
    if label:
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2 - 6
        s += f'<text x="{mx}" y="{my}" font-family="Consolas, Menlo, monospace" font-size="10" fill="#444">{label}</text>'
    return s


def top() -> str:
    defs = """<defs>
  <marker id="arr" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
    <path d="M0,0 L6,3 L0,6 Z" fill="#333"/>
  </marker>
</defs>"""
    body = defs + "\n".join(
        [
            box(24, 64, 200, 88, "POWER / REF", ["+15 V  GND  -15 V", "VREF = 1.000 V", "VREFN = -VREF"], "#eef6ff"),
            box(248, 64, 200, 88, "INPUT", ["IN1, IN2 = 0 V or 1 V", "switches or DAC", "TP_IN1 TP_IN2"], "#eef8ee"),
            box(472, 64, 210, 88, "SIGNED GEN", ["Xinv1: IN1N = -IN1", "Xinv2: IN2N = -IN2", "Xinvref: VREFN = -VREF"], "#fff6e8"),
            box(24, 180, 165, 120, "HIDDEN h1", ["TIA Xh1tia", "ReLU Xh1relu+diodes", "INV Xh1inv", "TP_H1_LIN / OUT"], "#fff"),
            box(204, 180, 165, 120, "HIDDEN h2", ["TIA Xh2tia", "ReLU Xh2relu+diodes", "INV Xh2inv", "TP_H2_LIN / OUT"], "#fff"),
            box(384, 180, 165, 120, "HIDDEN h3", ["TIA Xh3tia", "ReLU Xh3relu+diodes", "INV Xh3inv", "TP_H3_LIN / OUT"], "#fff"),
            box(564, 180, 165, 120, "HIDDEN h4", ["TIA Xh4tia", "ReLU Xh4relu+diodes", "INV Xh4inv", "TP_H4_LIN / OUT"], "#fff"),
            box(220, 330, 310, 100, "OUTPUT o1 LINEAR TIA", ["Xo1tia  Rf=Ro1f=10k", "TP_O1LIN  class 1 if >= 0.5 V", "PC/ADC may measure; must not compute Wx"], "#fdeeee"),
            arrow(124, 152, 124, 180, ""),
            arrow(348, 152, 286, 180, "IN*"),
            arrow(560, 152, 466, 180, "IN*N"),
            arrow(106, 300, 300, 330, "H1_YN / H1_Y"),
            arrow(286, 300, 340, 330, "H2"),
            arrow(466, 300, 400, 330, "H3_Y"),
            arrow(646, 300, 460, 330, "H4_Y"),
            '<text x="24" y="460" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="11" fill="#444">Neural topology is identical to physical_design/xor_2_4_1/netlist.cir. 1 pF SPICE caps are omitted (class C). Decoupling is hardware-only.</text>',
            '<text x="24" y="478" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="11" fill="#444">Do not implement XOR in firmware. Disconnect NumPy and the analog node TP_O1LIN must still compute XOR.</text>',
        ]
    )
    return svg(body, 760, 500, "TOP — Physical AI MVP v1 XOR 2-4-1")


def neuron() -> str:
    # analog-ish schematic of one hidden neuron
    body = """
  <text x="24" y="70" font-family="Consolas, Menlo, monospace" font-size="12" fill="#222">Instance: replace h1 with h2/h3/h4. SPICE names shown for h1.</text>
  <rect x="24" y="86" width="900" height="430" fill="#fff" stroke="#222"/>
  <text x="40" y="110" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="13" font-weight="600">1) Signed conductance into TIA virtual ground (IN+ = GND)</text>
  <text x="40" y="130" font-family="Consolas, Menlo, monospace" font-size="11">Rh1w1 : src(w) -> H1_SUM    Rh1w2 : src(w) -> H1_SUM    Rh1b : src(b) -> H1_SUM</text>
  <text x="40" y="146" font-family="Consolas, Menlo, monospace" font-size="11">Hidden TIA inverts: V(H1_LIN) = -z. Positive w uses original source; negative w uses inverted source.</text>
  <polygon points="420,200 500,230 420,260" fill="#f7f7f7" stroke="#111"/>
  <text x="428" y="236" font-family="Consolas, Menlo, monospace" font-size="10">Xh1tia</text>
  <text x="360" y="188" font-family="Consolas, Menlo, monospace" font-size="10">H1_SUM (IN-)</text>
  <text x="430" y="278" font-family="Consolas, Menlo, monospace" font-size="10">IN+ = GND</text>
  <text x="510" y="236" font-family="Consolas, Menlo, monospace" font-size="10">H1_LIN  TP_H1_LIN</text>
  <line x1="500" y1="230" x2="560" y2="230" stroke="#111"/>
  <line x1="470" y1="160" x2="470" y2="215" stroke="#111"/>
  <line x1="470" y1="160" x2="560" y2="160" stroke="#111"/>
  <line x1="560" y1="160" x2="560" y2="230" stroke="#111"/>
  <text x="478" y="154" font-family="Consolas, Menlo, monospace" font-size="10">Rh1f = 10k</text>
  <text x="40" y="310" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="13" font-weight="600">2) Inverting precision rectifier  H1_Y = max(-H1_LIN, 0)</text>
  <polygon points="200,360 280,390 200,420" fill="#f7f7f7" stroke="#111"/>
  <text x="206" y="396" font-family="Consolas, Menlo, monospace" font-size="10">Xh1relu</text>
  <text x="40" y="396" font-family="Consolas, Menlo, monospace" font-size="10">H1_LIN --Rh1r1 10k-- H1_RINN (IN-)</text>
  <text x="206" y="436" font-family="Consolas, Menlo, monospace" font-size="10">IN+ = GND</text>
  <text x="300" y="380" font-family="Consolas, Menlo, monospace" font-size="10">H1_AMP</text>
  <text x="300" y="396" font-family="Consolas, Menlo, monospace" font-size="10">Xh1d1 H1_RINN -&gt; H1_AMP</text>
  <text x="300" y="412" font-family="Consolas, Menlo, monospace" font-size="10">Xh1d2 H1_AMP -&gt; H1_Y</text>
  <text x="300" y="428" font-family="Consolas, Menlo, monospace" font-size="10">Rh1rf 10k H1_Y to H1_RINN</text>
  <text x="300" y="444" font-family="Consolas, Menlo, monospace" font-size="10">Rh1rl 10k H1_Y to GND   TP_H1_OUT = H1_Y</text>
  <text x="560" y="360" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="13" font-weight="600">3) Unity invert</text>
  <text x="560" y="384" font-family="Consolas, Menlo, monospace" font-size="11">Xh1inv: H1_YN = -H1_Y</text>
  <text x="560" y="400" font-family="Consolas, Menlo, monospace" font-size="11">Rh1invin = Rh1invf = 10k</text>
  <text x="560" y="416" font-family="Consolas, Menlo, monospace" font-size="11">Used by output signed routing</text>
  <text x="40" y="500" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="11" fill="#444">1N4148 anode-&gt;cathode as written. OPA189: IN+ IN- V+ V- OUT per TI SBOS830. Pin numbers: follow datasheet, not this drawing.</text>
"""
    return svg(body, 950, 530, "HIDDEN NEURON — TIA + inverting rectifier ReLU + invert")


def output_page() -> str:
    body = """
  <rect x="24" y="70" width="900" height="360" fill="#fff" stroke="#222"/>
  <text x="40" y="96" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="13" font-weight="600">Linear output TIA (no ReLU)</text>
  <text x="40" y="120" font-family="Consolas, Menlo, monospace" font-size="11">Ro1w1 H1_YN -&gt; O1_SUM   (W2[0]&gt;0 uses inverted hidden)</text>
  <text x="40" y="136" font-family="Consolas, Menlo, monospace" font-size="11">Ro1w2 H2_YN -&gt; O1_SUM</text>
  <text x="40" y="152" font-family="Consolas, Menlo, monospace" font-size="11">Ro1w3 H3_Y  -&gt; O1_SUM   (W2[2]&lt;0 uses original hidden)</text>
  <text x="40" y="168" font-family="Consolas, Menlo, monospace" font-size="11">Ro1w4 H4_Y  -&gt; O1_SUM</text>
  <text x="40" y="184" font-family="Consolas, Menlo, monospace" font-size="11">Ro1b  VREFN -&gt; O1_SUM   (b2&gt;0, output TIA does not invert the math)</text>
  <polygon points="420,230 500,260 420,290" fill="#f7f7f7" stroke="#111"/>
  <text x="428" y="266" font-family="Consolas, Menlo, monospace" font-size="10">Xo1tia</text>
  <text x="508" y="266" font-family="Consolas, Menlo, monospace" font-size="12">O1_LIN  = TP_O1LIN</text>
  <text x="508" y="284" font-family="Consolas, Menlo, monospace" font-size="11">Ro1f = 10k  (Rf)</text>
  <text x="40" y="330" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="13" font-weight="600">Classification (optional, must not replace analog)</text>
  <text x="40" y="350" font-family="Consolas, Menlo, monospace" font-size="11">class = 1 if V(O1_LIN) &gt;= 0.5 V else 0</text>
  <text x="40" y="366" font-family="Consolas, Menlo, monospace" font-size="11">Comparator vs 0.5 V is allowed only in parallel with TP_O1LIN.</text>
  <text x="40" y="400" font-family="Consolas, Menlo, monospace" font-size="11">SPICE 27 C UIC TRAN 2 ms:  00 -&gt; 1.645 mV    01 -&gt; 1.002511 V    10 -&gt; 1.018006 V    11 -&gt; 1.645 mV</text>
"""
    return svg(body, 950, 460, "OUTPUT NEURON — linear TIA")


def power_page() -> str:
    body = """
  <rect x="24" y="70" width="430" height="280" fill="#fff" stroke="#222"/>
  <text x="40" y="96" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="13" font-weight="600">Power</text>
  <text x="40" y="120" font-family="Consolas, Menlo, monospace" font-size="11">J_PWR: +15 V, GND, -15 V</text>
  <text x="40" y="136" font-family="Consolas, Menlo, monospace" font-size="11">C_VDD_BULK 10uF &gt;=35 V +15 to GND</text>
  <text x="40" y="152" font-family="Consolas, Menlo, monospace" font-size="11">C_VSS_BULK 10uF &gt;=35 V -15 to GND</text>
  <text x="40" y="168" font-family="Consolas, Menlo, monospace" font-size="11">Each OPA189: 100 nF X7R 50 V on V+ and V- to GND</text>
  <text x="40" y="184" font-family="Consolas, Menlo, monospace" font-size="11">Star/return GND under analog section</text>
  <text x="40" y="216" font-family="Consolas, Menlo, monospace" font-size="11">SPICE |i(Vdd)| ~ 21-22 mA at 27 C</text>
  <text x="40" y="232" font-family="Consolas, Menlo, monospace" font-size="11">Hardware budget: &gt;= 100 mA/rail dual supply</text>
  <text x="40" y="248" font-family="Consolas, Menlo, monospace" font-size="11">TI OPA189 Iq typ 1.7 mA (SBOS830) x16 ~ 27 mA</text>
  <rect x="470" y="70" width="450" height="280" fill="#fff" stroke="#222"/>
  <text x="486" y="96" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="13" font-weight="600">VREF 1.000 V</text>
  <text x="486" y="120" font-family="Consolas, Menlo, monospace" font-size="11">SPICE used ideal Vref. HARDWARE VALIDATION REQUIRED.</text>
  <text x="486" y="144" font-family="Consolas, Menlo, monospace" font-size="11">Target: 1.000 V +/- 0.05%, buffered</text>
  <text x="486" y="160" font-family="Consolas, Menlo, monospace" font-size="11">Load: ~100 uA into Rinvrefin</text>
  <text x="486" y="176" font-family="Consolas, Menlo, monospace" font-size="11">Do not feed an unbuffered divider into VREFN invert.</text>
  <text x="486" y="208" font-family="Consolas, Menlo, monospace" font-size="11">Unity inverters:</text>
  <text x="486" y="224" font-family="Consolas, Menlo, monospace" font-size="11">Rin = Rf = 10k 0.1% matched</text>
  <text x="486" y="240" font-family="Consolas, Menlo, monospace" font-size="11">IN+ = GND, output = -input</text>
"""
    return svg(body, 950, 380, "POWER, REFERENCE, SIGNED INPUTS")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "00_top.svg").write_text(top(), encoding="utf-8")
    (OUT / "01_power_ref_input.svg").write_text(power_page(), encoding="utf-8")
    (OUT / "02_hidden_neuron.svg").write_text(neuron(), encoding="utf-8")
    (OUT / "03_output_neuron.svg").write_text(output_page(), encoding="utf-8")
    print("svg written", OUT)


if __name__ == "__main__":
    main()
