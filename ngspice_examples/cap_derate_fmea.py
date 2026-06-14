"""Cap DC-bias DERATING sweep on the protection qualifier caps (PARALLEL).

WHY: the validation never modelled DC-bias derating.  The Monte Carlo varied
capacitance by +/-10% (static tolerance); the netlist caps are ideal.  But the
supervisor / over-power RC qualifier caps (C_hiq, C_loq, C_arm, C_lat, C_envop)
set the fault-discrimination TIMES via tau = R*C -- notably C_hiq*R_hiq = 3 s,
the high-side ride-out that stops a cold-start from false-tripping.  If those
are X7R, DC-bias derating can cut C by 30-60 % -> tau shrinks -> the 3 s
ride-out erodes -> risk of false-tripping a legitimate cold start.

WHAT: scale the qualifier caps by a derating factor k and re-check
  - false-trip under disorderly/cold-start (Suite C logic): want NO trip
  - fault still caught + peak bounded (Suite D logic): want caught + bounded
The k at which a false-trip appears (or a fault stops being caught) sets the
required cap spec (high-V X7R, or C0G/film) on those positions.

PARALLEL: ~100 independent ngspice runs over a ThreadPool (ob.run shells out to
ngspice, so threads give real parallelism). Reuses overnight_battery.run /
.metrics / transforms; the only new logic is derate().

RUN (simhost): screen -dmS capderate bash -c 'python3 cap_derate_fmea.py'
     smoke    : python3 cap_derate_fmea.py quick      (1 tube, 2 derates)
Report -> cap_derate_fmea.md
"""
import sys, os, time, re, json
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import regulator as r
import overnight_battery as ob          # run(), metrics(), osc_dropout(), inject_xubuf(), short_element()

QUICK = "quick" in sys.argv
WORKERS = 6 if QUICK else 20
ROOT = "/tmp/cap_derate"; os.makedirs(ROOT, exist_ok=True)
REPORT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cap_derate_fmea.md")

# The real X7R RC-qualifier caps (NOT the relay-lag model cap C_coil_op, which
# represents the physical relay, not a PCB part).
QUAL_CAPS = [("C_hiq", 1e-6), ("C_loq", 1e-6), ("C_arm", 1e-6),
             ("C_lat", 1e-6), ("C_envop", 0.1e-6)]

def derate(cir, k):
    """Scale each qualifier cap's value by k. Anchored to line-start (re.M) so
    it hits the ELEMENT line, not an in-netlist comment naming the cap."""
    for name, nom in QUAL_CAPS:
        cir = re.sub(rf"(?m)^({name}\s+\S+\s+\S+\s+)\S+",
                     lambda m, nom=nom: m.group(1) + f"{k * nom:.4g}", cir, count=1)
    return cir

TUBES   = ["iv6"] if QUICK else list(r.TUBES)
DERATES = [1.0, 0.5] if QUICK else [1.0, 0.8, 0.6, 0.5, 0.4]
SCEN    = ["instant_on", "dropout_restart", "brownout"]
FAULTS  = ["xubuf_hi", "botref_short"]

def build_p1(tb, k, sc):
    kw = dict(r.TUBES[tb]); T_END = 10.0
    if sc == "instant_on":
        kw["t_rail_ramp"] = 0.0
        cir = r.make_netlist(T_end=T_END, overpower_protect=True, **kw)
    elif sc == "dropout_restart":
        cir = ob.osc_dropout(r.make_netlist(T_end=T_END, overpower_protect=True, **kw), 3.0, 4.5)
    else:  # brownout: dip buffer rails to 70% over 3.0-3.5 s
        cir = r.make_netlist(T_end=T_END, overpower_protect=True, **kw)
        vb = kw.get("v_buf", 10)
        cir = re.sub(r"V_vcc vcc_top 0 DC \S+",
                     f"V_vcc vcc_top 0 PWL(0 {vb} 3 {vb} 3.05 {0.7*vb} 3.5 {0.7*vb} 3.55 {vb} 100 {vb})", cir)
        cir = re.sub(r"V_vee vee_top 0 DC \S+",
                     f"V_vee vee_top 0 PWL(0 {-vb} 3 {-vb} 3.05 {-0.7*vb} 3.5 {-0.7*vb} 3.55 {-vb} 100 {-vb})", cir)
    return derate(cir, k), T_END

def build_p2(tb, k, fl):
    kw = dict(r.TUBES[tb]); T_END = 9.0
    cir = r.make_netlist(T_end=T_END, overpower_protect=True, **kw)
    cir = ob.inject_xubuf(cir, 9.9) if fl == "xubuf_hi" else ob.short_element(cir, "R_botref")
    return derate(cir, k), T_END

def cell(task):
    part, tb, k, what = task
    try:
        if part == "p1":
            cir, T_END = build_p1(tb, k, what)
        else:
            cir, T_END = build_p2(tb, k, what)
        d, err = ob.run(cir, f"{ROOT}/{part}_{tb}_{what}_{k}")
        if d is None:
            return task, {"err": err}
        m = ob.metrics(d, T_END, has_protect=True)
        return task, {"disc": bool(m.get("disc")), "T_peak": m.get("T_peak")}
    except Exception as e:
        return task, {"err": f"EXC {e}"}

def main():
    t0 = time.time()
    tasks = ([("p1", tb, k, sc) for tb in TUBES for k in DERATES for sc in SCEN] +
             [("p2", tb, k, fl) for tb in TUBES for k in DERATES for fl in FAULTS])
    res = {}
    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(cell, t) for t in tasks]
        for f in as_completed(futs):
            task, out = f.result()
            res[task] = out
            done += 1
            if done % 10 == 0:
                print(f"{done}/{len(tasks)} cells  ({time.time()-t0:.0f}s)", flush=True)

    # raw-results safety net: persist BEFORE formatting so a format bug can't
    # waste the run (re-format offline from this if ever needed).
    raw_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cap_derate_raw.json")
    with open(raw_path, "w") as jf:
        json.dump({"|".join(map(str, k)): v for k, v in res.items()}, jf, indent=0)

    def p1cell(tb, k, sc):
        o = res.get(("p1", tb, k, sc), {})
        return "ERR" if "err" in o else ("**TRIP**" if o.get("disc") else "ok")
    def p2cell(tb, k, fl):
        o = res.get(("p2", tb, k, fl), {})
        if "err" in o: return "ERR", ""
        return f"{o.get('T_peak', float('nan')):.1f}K", ("YES" if o.get("disc") else "**NO**")

    L = []
    L.append(f"\n# Cap DC-bias derating sweep -- protection qualifier caps  {time.ctime()}\n")
    L.append("Scales C_hiq/C_loq/C_arm/C_lat/C_envop by a derating factor (X7R DC-bias")
    L.append("capacitance loss). k=1.0 is as-designed; k=0.4 ~ a 16 V X7R near rated V.")
    L.append("Want: no false-trip (Part 1), fault still caught + bounded (Part 2).\n")
    L.append("## Part 1 -- false-trip under derating (want: ok on all)\n")
    L.append("| tube | derate | instant_on | dropout | brownout |")
    L.append("|---|---|---|---|---|")
    for tb in TUBES:
        for k in DERATES:
            L.append(f"| {tb} | x{k} | {p1cell(tb,k,'instant_on')} | {p1cell(tb,k,'dropout_restart')} | {p1cell(tb,k,'brownout')} |")
    L.append("\n## Part 2 -- fault catch + peak under derating (want: caught, bounded)\n")
    L.append("| tube | derate | fault | T_peak | disconnect? |")
    L.append("|---|---|---|---|---|")
    for tb in TUBES:
        for k in DERATES:
            for fl in FAULTS:
                pk, disc = p2cell(tb, k, fl)
                L.append(f"| {tb} | x{k} | {fl} | {pk} | {disc} |")
    L.append(f"\n_{len(tasks)} cells in {time.time()-t0:.0f}s on {WORKERS} workers; done {time.ctime()}_\n")

    with open(REPORT, "w") as f:
        f.write("\n".join(L) + "\n")
    print("\n".join(L))

if __name__ == "__main__":
    main()
