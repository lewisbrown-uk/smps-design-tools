"""Optimal E24 / E96 resistor-divider values for the safety reference voltages,
derived from an LM4040-4.096 (Vref = 4.096 V).

Divider:  Vref ─[Rtop]─ node ─[Rbot]─ 0 ,  Vout = Vref·Rbot/(Rtop+Rbot).
For each threshold we brute-force the closest (Rtop, Rbot) E-series pair,
constraining the total to a sane window (keeps LM4040 load + node impedance
reasonable for the LM339 comparator inputs).  -> safety_refs_eseries.md
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))            # repo root for utils.*
from utils.eseries_opt import Problem, Resistor

VREF = 4.096

# (label, target V, note).  Only thresholds <= Vref are divider-realisable.
TARGETS = [
    ("v_ref_lo   (supervisor LOW, all tubes)",      0.50, "loop railed-low fault"),
    ("v_ref_arm  (supervisor ARM, all tubes)",      1.50, "loop-capture arm"),
    ("v_ref_hi   (supervisor HIGH, all tubes)",     3.70, "sustained over-drive"),
    ("v_ref_op   (over-power, IV-6 / IV-18)",       1.30, "1.3*V_op, V_op=1.0"),
    ("v_ref_op   (over-power, ILC1-1/8)",           1.56, "1.3*V_op, V_op=1.2"),
    ("v_ref_op/2 (over-power, ILC1-1/7)",           3.25, "1.3*V_op=6.50>Vref -> halve envelope, ref=3.25"),
]

TOTAL_LO, TOTAL_HI = 40e3, 100e3      # divider total -> 41..102 uA from the ref
RNG = (1e3, 1e6)

def solve_one(vout, eser):
    p = Problem()
    p.add(Resistor("Rtop", e_series=eser, range=RNG))
    p.add(Resistor("Rbot", e_series=eser, range=RNG))
    p.add_target("vout", lambda Rtop, Rbot: VREF * Rbot / (Rtop + Rbot),
                 target=vout, metric="abs")
    p.add_constraint("total", lambda Rtop, Rbot: Rtop + Rbot,
                     range=(TOTAL_LO, TOTAL_HI))
    return p.solve(strategy="brute", n_results=1)[0]

def fmt_r(x):
    if x >= 1e6: return f"{x/1e6:g}M"
    if x >= 1e3: return f"{x/1e3:g}k"
    return f"{x:g}"

def main():
    L = ["# Safety-reference divider values from LM4040-4.096 (Vref = 4.096 V)\n",
         f"Divider `Vref─[Rtop]─node─[Rbot]─0`, `Vout = 4.096·Rbot/(Rtop+Rbot)`. "
         f"Total constrained to {fmt_r(TOTAL_LO)}–{fmt_r(TOTAL_HI)} "
         f"(≈{VREF/TOTAL_HI*1e6:.0f}–{VREF/TOTAL_LO*1e6:.0f} µA ref load).\n",
         "| threshold | target | series | Rtop | Rbot | Vout | err (mV) | err (%) | Rth |",
         "|---|---|---|---|---|---|---|---|---|"]
    for label, vt, note in TARGETS:
        for eser in (24, 96):
            r = solve_one(vt, eser)
            rt, rb = r.values["Rtop"], r.values["Rbot"]
            vo = VREF * rb / (rt + rb)
            rth = rt * rb / (rt + rb)
            err = vo - vt
            L.append(f"| {label} | {vt:.3f} | E{eser} | {fmt_r(rt)} | {fmt_r(rb)} "
                     f"| {vo:.4f} | {err*1e3:+.2f} | {err/vt*100:+.3f} | {fmt_r(rth)} |")
        L.append("|  |  |  |  |  |  |  |  |  |")
    out = "\n".join(L) + "\n"
    open(os.path.join(HERE, "safety_refs_eseries.md"), "w").write(out)
    print(out)

if __name__ == "__main__":
    main()
