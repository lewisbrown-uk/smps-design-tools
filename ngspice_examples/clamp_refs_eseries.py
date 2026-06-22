"""E24/E96 values for the two clamp-reference generators.

(1) §8b over-power flat clamp: TLV431 shunt sets +V_cl = Vref·(1+Rt/Rb),
    Vref=1.24 V.  Per-tube target V_cl = 1.5·V_op·√2·(R_op+R_sense)/R_op.
    Bias Rb_bias from +15 V suggested separately (analytic, ~1 mA).
(2) §7 anti-windup clamp window, adopted [-3 V, +6 V] (was sim -0.5/+4):
    +6 V from a VCC(+10) divider, -3 V from a VEE(-10) divider, each buffered.
-> clamp_refs_eseries.md
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from utils.eseries_opt import Problem, Resistor

VREF_TLV = 1.24            # TLV431 reference

# (label, V_cl target)  V_cl = 1.5*V_op*sqrt(2)*(R_op+R_sense)/R_op  (§8b-i)
TLV = [
    ("ILC1-1/7 (idle, >rail)", 12.60),
    ("IV-6   (this board)",     2.662),
    ("IV-18",                   2.333),
    ("ILC1-1/8",                3.182),
]

def fmt_r(x):
    if x >= 1e6: return f"{x/1e6:g}M"
    if x >= 1e3: return f"{x/1e3:g}k"
    return f"{x:g}"

def tlv_divider(vcl, eser):
    p = Problem()
    p.add(Resistor("Rt", e_series=eser, range=(1e3, 1e6)))   # K -> ref
    p.add(Resistor("Rb", e_series=eser, range=(1e3, 1e6)))   # ref -> GND
    p.add_target("vcl", lambda Rt, Rb: VREF_TLV*(1+Rt/Rb), target=vcl, metric="abs")
    p.add_constraint("tot", lambda Rt, Rb: Rt+Rb, range=(20e3, 80e3))  # ~33-130uA div
    return p.solve(strategy="brute", n_results=1)[0]

def rail_divider(rail, vout, eser, tot_lo=100e3, tot_hi=1e6):
    # tap = rail * Rb/(Rt+Rb)   (Rb = leg toward 0 V; Rt toward the rail)
    p = Problem()
    p.add(Resistor("Rt", e_series=eser, range=(1e3, 5e6)))
    p.add(Resistor("Rb", e_series=eser, range=(1e3, 5e6)))
    p.add_target("v", lambda Rt, Rb: rail*Rb/(Rt+Rb), target=vout, metric="abs")
    p.add_constraint("tot", lambda Rt, Rb: Rt+Rb, range=(tot_lo, tot_hi))
    return p.solve(strategy="brute", n_results=1)[0]

def main():
    L = ["# Clamp-reference E-series values\n",
         "## (1) §8b over-power flat clamp — TLV431 divider  V_cl = 1.24·(1+Rt/Rb)\n",
         "| tube | V_cl | series | Rt (K→ref) | Rb (ref→GND) | V_cl actual | err | R_bias(+15V,~1mA) |",
         "|---|---|---|---|---|---|---|---|"]
    for label, vcl in TLV:
        rbias = fmt_r(round((15-vcl)/1e-3/100)*100)   # ~1 mA, to nearest 100 Ω
        for eser in (24, 96):
            r = tlv_divider(vcl, eser)
            rt, rb = r.values["Rt"], r.values["Rb"]
            act = VREF_TLV*(1+rt/rb)
            L.append(f"| {label} | {vcl:.3f} | E{eser} | {fmt_r(rt)} | {fmt_r(rb)} "
                     f"| {act:.3f} | {act-vcl:+.3f} | {rbias if eser==24 else ''} |")
        L.append("| | | | | | | | |")

    L.append("\n## (2) §7 anti-windup clamp window [-3 V, +6 V] (buffered rail dividers)\n")
    L.append("| ref | from | target | series | R_top | R_bot | actual | err |")
    L.append("|---|---|---|---|---|---|---|---|")
    for name, rail, vout in [("+6 V (hi)", 10.0, 6.0), ("-3 V (lo)", -10.0, 3.0)]:
        for eser in (24, 96):
            r = rail_divider(abs(rail), vout, eser)
            rt, rb = r.values["Rt"], r.values["Rb"]
            act = rail*rb/(rt+rb)
            L.append(f"| {name} | {fmt_r(abs(rail))}V | {('+' if rail>0 else '-')}{vout:g} "
                     f"| E{eser} | {fmt_r(rt)} | {fmt_r(rb)} | {act:+.3f} | {act-(rail/abs(rail))*vout:+.3f} |")
        L.append("| | | | | | | | |")
    out = "\n".join(L) + "\n"
    open(os.path.join(HERE, "clamp_refs_eseries.md"), "w").write(out)
    print(out)

if __name__ == "__main__":
    main()
