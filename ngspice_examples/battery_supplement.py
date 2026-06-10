"""Supplement to the overnight battery:
  E  over-driving forward-gain faults (protection ON) -- the dangerous class
  F  realistic R_op +/-5% cold-start corner (protection OFF; +/-10% was pessimistic)
Run: python3 battery_supplement.py
"""
import sys, subprocess, re, os, math, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import regulator as r

TUBES = ["ilc11_7", "iv6", "iv18", "ilc11_8"]
ROOT = "/tmp/battery_sup"; os.makedirs(ROOT, exist_ok=True)
REPORT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "overnight_battery_EF.md")


def run(cir, work, timeout=600):
    work = re.sub(r"\s+", "_", work)  # no spaces in dir names (the Suite-A WORST bug)
    os.makedirs(work, exist_ok=True)
    cir = re.sub(r"wrdata \S+/run\.data", f"wrdata {work}/run.data", cir)
    open(f"{work}/run.cir", "w").write(cir)
    try:
        p = subprocess.run(["ngspice", "-b", "run.cir"], cwd=work,
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "TIMEOUT"
    fp = f"{work}/run.data"
    if not os.path.exists(fp): return None, (p.stderr+p.stdout)[-150:].replace("\n", " ")
    try:
        d = np.loadtxt(fp); os.remove(fp); return d, None
    except Exception as e:
        return None, f"loadtxt:{e}"


def thd_db(t, v, t0, t1, f=1000.0):
    m = (t >= t0) & (t <= t1); ts, vs = t[m], v[m]
    if len(ts) < 50: return float("nan")
    fs = np.linspace(f*0.95, f*1.05, 41); best = (np.inf, 0, 0)
    for ff in fs:
        sb, cb = np.sin(2*np.pi*ff*ts), np.cos(2*np.pi*ff*ts)
        a = np.trapezoid(vs*sb, ts)/np.trapezoid(sb*sb, ts)
        b = np.trapezoid(vs*cb, ts)/np.trapezoid(cb*cb, ts)
        if -math.hypot(a, b) < best[0]: best = (-math.hypot(a, b), a, b)
    _, a, b = best
    res = vs - a*np.sin(2*np.pi*1000*ts) - b*np.cos(2*np.pi*1000*ts)
    dn = math.sqrt((a*a+b*b)/2)
    return 20*math.log10(math.sqrt(np.trapezoid(res*res, ts)/(ts[-1]-ts[0]))/dn) if dn > 0 else float("nan")


def app(s):
    open(REPORT, "a").write(s+"\n"); print(s, flush=True)


def short(cir, name): return re.sub(rf"({name}\s+\S+\s+\S+)\s+\S+", r"\1 1e-3", cir, count=1)
def opn(cir, name):   return re.sub(rf"({name}\s+\S+\s+\S+)\s+\S+", r"\1 1e12", cir, count=1)

# ---- Suite E: over-driving forward-gain faults (protection ON) ----
app(f"\n## Suite E — over-driving forward-gain faults (protection ON)  {time.ctime()}\n")
app("| tube | fault | T_peak | T_final | disconnect? |")
app("|---|---|---|---|---|")
efaults = ["atten_top_short", "atten_bot_open", "topref_open", "fb_vgain_short"]
for tb in TUBES:
    for fl in efaults:
        cir = r.make_netlist(T_end=9.0, overpower_protect=True, **r.TUBES[tb])
        if fl == "atten_top_short": cir = short(cir, "R_atten_top")
        elif fl == "atten_bot_open": cir = opn(cir, "R_atten_bot")
        elif fl == "topref_open": cir = opn(cir, "R_topref")
        elif fl == "fb_vgain_short": cir = short(cir, "R_fb_vgain")
        d, err = run(cir, f"{ROOT}/E_{tb}_{fl}")
        if d is None: app(f"| {tb} | {fl} | FAIL: {err} | | |"); continue
        t = d[:, 0]; T = d[:, 9]
        disc = bool(d.shape[1] > 23 and np.max(d[:, 23]) > 2.5)
        app(f"| {tb} | {fl} | {np.max(T):.1f}K | {np.mean(T[t>5.7]):.1f}K | {'YES' if disc else 'no'} |")

# ---- Suite F: realistic R_op +/-5% cold-start ----
app(f"\n## Suite F — realistic R_op +/-5% cold-start (protection OFF)  {time.ctime()}\n")
app("| tube | R_op | T_overshoot | T_ss | THD |")
app("|---|---|---|---|---|")
for tb in TUBES:
    for tag, sc in [("R_op+5%", 1.05), ("R_op-5%", 0.95)]:
        kw = dict(r.TUBES[tb]); kw["R_op"] *= sc
        cir = r.make_netlist(T_end=8.0, **kw)
        d, err = run(cir, f"{ROOT}/F_{tb}_{tag}")
        if d is None: app(f"| {tb} | {tag} | FAIL: {err} | | |"); continue
        t = d[:, 0]; T = d[:, 9]; vfil = d[:, 1]-d[:, 3]; ss = t > 7.5
        app(f"| {tb} | {tag} | +{np.max(T)-np.mean(T[ss]):.1f}K | {np.mean(T[ss]):.1f}K "
            f"| {thd_db(t, vfil, 7.0, 8.0):.1f}dB |")

open("/tmp/supplement_DONE", "w").write("done")
print("SUPPLEMENT DONE", flush=True)
