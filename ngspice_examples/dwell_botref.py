"""Over-temperature dwell for the WORST fault (botref_short, peaks 922 K).

Unlike dwell_analysis.py (which injects XU_buf-stuck at t=3 s, the ~899 K IV-18
case), botref_short shorts R_botref from t=0 -> the filament overshoots during
warm-up, the authority-gated disconnect trips, then it cools.  Reports how long
T stays above 800/850/900 K, the disconnect time, and the cool-down.  Parallel
over the tubes that cross 900 K (+ ILC1-1/7 for contrast).  ngspice on simhost.
"""
import sys, os, re, subprocess, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import regulator as r

TUBES = ["iv6", "ilc11_8", "iv18", "ilc11_7"]
T_END = 9.0

def run_dwell(tube):
    WORK = f"/tmp/dwellb_{tube}"; os.makedirs(WORK, exist_ok=True)
    cir = r.make_netlist(overpower_protect=True, T_end=T_END, **r.TUBES[tube])
    cir = re.sub(r"(R_botref\s+\S+\s+\S+)\s+\S+", r"\1 1e-3", cir, count=1)   # short, as Suite D
    cir = re.sub(r"\.tran 50u (\S+) 0 uic", r".tran 20u \1 0 uic", cir)        # resolve the ms event
    cir = re.sub(r"wrdata \S+/run\.data", f"wrdata {WORK}/run.data", cir)
    open(f"{WORK}/run.cir", "w").write(cir)
    subprocess.run(["ngspice", "-b", "run.cir"], cwd=WORK, capture_output=True, text=True, timeout=1200)
    if not os.path.exists(f"{WORK}/run.data"):
        return tube, None
    d = np.loadtxt(f"{WORK}/run.data")
    t, T, n_disc = d[:, 0], d[:, 9], d[:, 23]
    i_pk = int(np.argmax(T)); t_pk, T_pk = t[i_pk], T[i_pk]
    t_trip = t[np.argmax(n_disc > 2.5)] if np.max(n_disc) > 2.5 else float("nan")
    def dwell(thr):
        m = T > thr
        return float(np.sum(np.diff(t)[m[:-1]])) if m.any() else 0.0
    def cool_to(tg):
        post, Tp = t[i_pk:], T[i_pk:]; b = np.where(Tp <= tg)[0]
        return float(post[b[0]] - t_pk) if len(b) else float("nan")
    return tube, dict(peak=T_pk, t_pk=t_pk, trip=t_trip,
                      d800=dwell(800), d850=dwell(850), d900=dwell(900),
                      c850=cool_to(850), c500=cool_to(500))

t0 = time.time()
with ThreadPoolExecutor(max_workers=4) as ex:
    res = dict(ex.map(run_dwell, TUBES))
print(f"botref_short over-temperature dwell (protection ON)  [{time.time()-t0:.0f}s]\n")
hdr = f"{'tube':9} {'peak':>6} {'>900K':>7} {'>850K':>7} {'>800K':>7} {'disc@':>7} {'pk->850':>8} {'pk->500':>8}"
print(hdr)
for tb in TUBES:
    o = res.get(tb)
    if not o:
        print(f"{tb:9} NODATA"); continue
    print(f"{tb:9} {o['peak']:5.0f}K {o['d900']*1e3:6.0f}m {o['d850']*1e3:6.0f}m {o['d800']*1e3:6.0f}m "
          f"{o['trip']*1e3:6.0f}m {o['c850']*1e3:7.0f}m {o['c500']*1e3:7.0f}m")
print("\n(>900K/>850K/>800K = total ms above; disc@ = disconnect time; pk->X = ms from peak down to X)")
