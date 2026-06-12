"""Sweep the high-side watchdog qualification time t_fault_hi vs BOTH the
botref_short over-temperature dwell AND the cold-start false-trip margin.

The worst fault (botref_short) is caught by the SLOW high-side supervisor
(t_fault_hi, default 3 s) -> ~2.76 s to disconnect, ~2.3 s >900 K.  Shortening
t_fault_hi shortens the dwell, but too short false-trips a healthy cold-start
(whose V_int rides high ~1 s).  Find the shortest watchdog that still rides out
startup.

False-trip detector: a cold-start false-trip latches the SUPERVISOR (n_latch,
col 15) and/or fires the disconnect (n_disc_op, col 23) and/or collapses the
filament (T_ss < 600 K).  metrics()'s `disc` alone (col 23) would miss the
supervisor latch, so we read the columns directly.  Cols: 0=t, 9=T_node,
15=n_latch, 23=n_disc_op (wrdata interleaves time,value per saved var).

ngspice on simhost.  Report -> t_fhi_sweep.md
"""
import sys, os, re, json, subprocess, time
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import regulator as r
import overnight_battery as ob

TUBES = ["iv6", "ilc11_8", "iv18", "ilc11_7"]
TFHI = [1.5, 1.0, 0.5, 0.25, 0.125]
SCEN = ["instant_on", "dropout", "brownout"]
ROOT = "/tmp/tfhi"; os.makedirs(ROOT, exist_ok=True)
REPORT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "t_fhi_sweep.md")

def runcir(cir, work):
    os.makedirs(work, exist_ok=True)
    cir = re.sub(r"wrdata \S+/run\.data", f"wrdata {work}/run.data", cir)
    open(f"{work}/run.cir", "w").write(cir)
    subprocess.run(["ngspice", "-b", "run.cir"], cwd=work, capture_output=True, text=True, timeout=1200)
    fp = f"{work}/run.data"
    if not os.path.exists(fp):
        return None
    d = np.loadtxt(fp); os.remove(fp)   # tmpfs is small -- free immediately
    return d

def dwell_cell(tube, tfhi):
    cir = r.make_netlist(overpower_protect=True, t_fault_hi=tfhi, T_end=9.0, **r.TUBES[tube])
    cir = re.sub(r"(R_botref\s+\S+\s+\S+)\s+\S+", r"\1 1e-3", cir, count=1)
    d = runcir(cir, f"{ROOT}/dw_{tube}_{tfhi}")
    if d is None:
        return None
    t, T, nd = d[:, 0], d[:, 9], d[:, 23]
    trip = float(t[np.argmax(nd > 2.5)]) if np.max(nd) > 2.5 else float("nan")
    def dwell(thr):
        m = T > thr
        return float(np.sum(np.diff(t)[m[:-1]])) if m.any() else 0.0
    return dict(peak=float(np.max(T)), d900=dwell(900), d850=dwell(850), d800=dwell(800), trip=trip)

def ftrip_cell(tube, tfhi, sc):
    kw = dict(r.TUBES[tube]); T_END = 10.0
    if sc == "instant_on":
        kw["t_rail_ramp"] = 0.0
        cir = r.make_netlist(overpower_protect=True, t_fault_hi=tfhi, T_end=T_END, **kw)
    elif sc == "dropout":
        cir = ob.osc_dropout(r.make_netlist(overpower_protect=True, t_fault_hi=tfhi, T_end=T_END, **kw), 3.0, 4.5)
    else:
        cir = r.make_netlist(overpower_protect=True, t_fault_hi=tfhi, T_end=T_END, **kw)
        vb = kw.get("v_buf", 10)
        cir = re.sub(r"V_vcc vcc_top 0 DC \S+",
                     f"V_vcc vcc_top 0 PWL(0 {vb} 3 {vb} 3.05 {0.7*vb} 3.5 {0.7*vb} 3.55 {vb} 100 {vb})", cir)
        cir = re.sub(r"V_vee vee_top 0 DC \S+",
                     f"V_vee vee_top 0 PWL(0 {-vb} 3 {-vb} 3.05 {-0.7*vb} 3.5 {-0.7*vb} 3.55 {-vb} 100 {-vb})", cir)
    d = runcir(cir, f"{ROOT}/ft_{tube}_{sc}_{tfhi}")
    if d is None:
        return None
    t, T, nlat, ndisc = d[:, 0], d[:, 9], d[:, 15], d[:, 23]
    Tss = float(np.mean(T[t > T_END - 0.5]))
    tripped = bool(np.max(nlat) > 2.5 or np.max(ndisc) > 2.5 or Tss < 600)
    return dict(trip=tripped, Tss=Tss)

def cell(task):
    kind, tube, tfhi, sc = task
    try:
        return task, (dwell_cell(tube, tfhi) if kind == "dw" else ftrip_cell(tube, tfhi, sc))
    except Exception as e:
        return task, {"err": str(e)}

def main():
    t0 = time.time()
    tasks = ([("dw", tb, k, None) for tb in TUBES for k in TFHI] +
             [("ft", tb, k, sc) for tb in TUBES for k in TFHI for sc in SCEN])
    res = {}
    with ThreadPoolExecutor(max_workers=20) as ex:
        for f in as_completed([ex.submit(cell, t) for t in tasks]):
            task, out = f.result(); res[task] = out
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "t_fhi_raw.json"), "w") as jf:
        json.dump({"|".join(str(x) for x in k): v for k, v in res.items()}, jf)

    L = [f"\n# t_fault_hi sweep -- watchdog speed vs fault dwell vs false-trip  {time.ctime()}\n"]
    L.append("Shorter high-side watchdog -> shorter botref_short over-temp dwell, but")
    L.append("risks false-tripping a healthy cold-start. Baseline as-designed = 3.0 s.\n")
    L.append("## Botref_short over-temperature dwell vs t_fault_hi\n")
    L.append("| tube | t_fhi | peak | >900K | >850K | >800K | disc@ |")
    L.append("|---|---|---|---|---|---|---|")
    for tb in TUBES:
        for k in TFHI:
            o = res.get(("dw", tb, k, None)) or {}
            if "err" in o or not o:
                L.append(f"| {tb} | {k}s | ERR | | | | |"); continue
            L.append(f"| {tb} | {k}s | {o['peak']:.0f}K | {o['d900']*1e3:.0f}m | {o['d850']*1e3:.0f}m | {o['d800']*1e3:.0f}m | {o['trip']*1e3:.0f}m |")
    L.append("\n## Cold-start false-trip vs t_fault_hi (want: ok = rides out startup)\n")
    L.append("| tube | t_fhi | instant_on | dropout | brownout |")
    L.append("|---|---|---|---|---|")
    def fc(tb, k, sc):
        o = res.get(("ft", tb, k, sc)) or {}
        if "err" in o or not o: return "ERR"
        return f"**TRIP**({o['Tss']:.0f}K)" if o["trip"] else "ok"
    for tb in TUBES:
        for k in TFHI:
            L.append(f"| {tb} | {k}s | {fc(tb,k,'instant_on')} | {fc(tb,k,'dropout')} | {fc(tb,k,'brownout')} |")
    L.append(f"\n_{len(tasks)} cells in {time.time()-t0:.0f}s on 20 workers; {time.ctime()}_\n")
    open(REPORT, "w").write("\n".join(L) + "\n")
    print("\n".join(L))

if __name__ == "__main__":
    main()
