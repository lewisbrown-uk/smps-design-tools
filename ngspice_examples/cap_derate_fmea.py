"""Cap DC-bias DERATING sweep on the protection qualifier caps.

WHY: the validation never modelled DC-bias derating.  The Monte Carlo varied
capacitance by +/-10% (static tolerance); the netlist caps are ideal.  But the
supervisor / over-power RC qualifier caps (C_hiq, C_loq, C_arm, C_lat, C_envop)
set the fault-discrimination TIMES via tau = R*C -- notably C_hiq*R_hiq = 3 s,
the high-side ride-out that stops a cold-start from false-tripping.  If those
are X7R, DC-bias derating can cut C by 30-60 % -> tau shrinks -> the 3 s
ride-out erodes -> risk of false-tripping a legitimate cold start (the exact
discrimination the FMEA validated).

WHAT: scale the qualifier caps by a derating factor k and re-check
  - false-trip under disorderly/cold-start (Suite C logic): want NO trip
  - fault still caught + peak bounded (Suite D logic): want caught + bounded
The k at which a false-trip appears (or a fault stops being caught) sets the
required cap spec: a high-voltage-rated X7R (small derating at the 0-5 V working
point), or C0G/film, on those positions.

Reuses the proven harness (overnight_battery.run / .metrics / transforms) so the
only new logic is the derate() transform.  RUN ON THE SIMHOST (needs ngspice):
    screen -dmS capderate bash -c 'cd <repo>/ngspice_examples && python3 cap_derate_fmea.py'
Report -> cap_derate_fmea.md
"""
import sys, os, time, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import regulator as r
import overnight_battery as ob          # run(), metrics(), osc_dropout(), inject_xubuf(), short_element()

ROOT = "/tmp/cap_derate"; os.makedirs(ROOT, exist_ok=True)
REPORT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cap_derate_fmea.md")

def app(s):
    print(s)
    with open(REPORT, "a") as f:
        f.write(s + "\n")

# The real X7R RC-qualifier caps (NOT the relay-lag model cap C_coil_op, which
# represents the physical relay, not a PCB part).
QUAL_CAPS = [("C_hiq", 1e-6), ("C_loq", 1e-6), ("C_arm", 1e-6),
             ("C_lat", 1e-6), ("C_envop", 0.1e-6)]

def derate(cir, k):
    """Scale each qualifier cap's value by k (emulates DC-bias capacitance loss).

    Anchored to line-start (re.M) so it hits the ELEMENT line, not an earlier
    in-netlist comment that mentions the cap name (e.g. '* ...R_hiq/C_hiq...').
    """
    for name, nom in QUAL_CAPS:
        cir = re.sub(rf"(?m)^({name}\s+\S+\s+\S+\s+)\S+",
                     lambda m, nom=nom: m.group(1) + f"{k * nom:.4g}", cir, count=1)
    return cir

DERATES = [1.0, 0.8, 0.6, 0.5, 0.4]
TUBES = list(r.TUBES)

app(f"\n# Cap DC-bias derating sweep -- protection qualifier caps  {time.ctime()}\n")
app("Scales C_hiq/C_loq/C_arm/C_lat/C_envop by a derating factor (X7R DC-bias")
app("capacitance loss). k=1.0 is the as-designed value; k=0.4 ~ a 16 V X7R near")
app("rated voltage. Want: no false-trip (Part 1), fault still caught (Part 2).\n")

# ---- Part 1: false-trip margin (disorderly, protection ON) ----
app("## Part 1 -- false-trip under derating (want: ok on all)\n")
app("| tube | derate | instant_on | dropout | brownout |")
app("|---|---|---|---|---|")
for tb in TUBES:
    for k in DERATES:
        cells = []
        for sc in ["instant_on", "dropout_restart", "brownout"]:
            kw = dict(r.TUBES[tb]); T_END = 10.0
            if sc == "instant_on":
                kw["t_rail_ramp"] = 0.0
                cir = r.make_netlist(T_end=T_END, overpower_protect=True, **kw)
            elif sc == "dropout_restart":
                cir = r.make_netlist(T_end=T_END, overpower_protect=True, **kw)
                cir = ob.osc_dropout(cir, 3.0, 4.5)
            else:  # brownout: dip buffer rails to 70% over 3.0-3.5 s
                cir = r.make_netlist(T_end=T_END, overpower_protect=True, **kw)
                vb = kw.get("v_buf", 10)
                cir = re.sub(r"V_vcc vcc_top 0 DC \S+",
                             f"V_vcc vcc_top 0 PWL(0 {vb} 3 {vb} 3.05 {0.7*vb} 3.5 {0.7*vb} 3.55 {vb} 100 {vb})", cir)
                cir = re.sub(r"V_vee vee_top 0 DC \S+",
                             f"V_vee vee_top 0 PWL(0 {-vb} 3 {-vb} 3.05 {-0.7*vb} 3.5 {-0.7*vb} 3.55 {-vb} 100 {-vb})", cir)
            cir = derate(cir, k)
            d, err = ob.run(cir, f"{ROOT}/C_{tb}_{sc}_{k}")
            if d is None:
                cells.append(f"ERR")
            else:
                cells.append("**TRIP**" if ob.metrics(d, T_END, has_protect=True).get("disc") else "ok")
        app(f"| {tb} | x{k} | {cells[0]} | {cells[1]} | {cells[2]} |")

# ---- Part 2: fault still caught + bounded under derating ----
app("\n## Part 2 -- fault catch + peak under derating (want: caught, bounded)\n")
app("| tube | derate | fault | T_peak | disconnect? |")
app("|---|---|---|---|---|")
for tb in TUBES:
    for k in DERATES:
        for fl in ["xubuf_hi", "botref_short"]:
            kw = dict(r.TUBES[tb]); T_END = 9.0
            cir = r.make_netlist(T_end=T_END, overpower_protect=True, **kw)
            cir = ob.inject_xubuf(cir, 9.9) if fl == "xubuf_hi" else ob.short_element(cir, "R_botref")
            cir = derate(cir, k)
            d, err = ob.run(cir, f"{ROOT}/D_{tb}_{fl}_{k}")
            if d is None:
                app(f"| {tb} | x{k} | {fl} | ERR | |"); continue
            m = ob.metrics(d, T_END, has_protect=True)
            app(f"| {tb} | x{k} | {fl} | {m['T_peak']:.1f}K | {'YES' if m.get('disc') else '**NO**'} |")

app(f"\n_done {time.ctime()}_\n")
