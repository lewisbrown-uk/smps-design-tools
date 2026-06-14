"""Characterise the healthy cold-start V_int ride per tube -- the overshoot the
high-side watchdog integrates and (if too long for t_fault_hi) false-trips on.

V_int rides up to its +4 V clamp on power-on (cold = max drive), stays above the
3.7 V high-side threshold while the loop warms up, then settles to V_int_OP.
The watchdog (RC tau = t_fault_hi) trips if the ride above 3.7 V lasts longer
than ~0.92*t_fault_hi.  So min safe t_fault_hi ~ T_ride/0.92; we report T_ride,
peak, and the implied floor, per tube.  Run with a long t_fault_hi (no trip) so
the natural ride is captured.  ngspice on simhost.
"""
import sys, os, re, subprocess, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import regulator as r

TUBES = ["iv18", "iv6", "ilc11_7", "ilc11_8"]
VHI = 3.7   # v_fault_trip_hi
ROOT = "/tmp/vintride"; os.makedirs(ROOT, exist_ok=True)

def measure(tube):
    WORK = f"{ROOT}/{tube}"; os.makedirs(WORK, exist_ok=True)
    cir = r.make_netlist(overpower_protect=True, t_fault_hi=10.0, T_end=10.0,
                         t_rail_ramp=0.0, **r.TUBES[tube])   # instant-on, watchdog never trips
    cir = re.sub(r"wrdata \S+/run\.data", f"wrdata {WORK}/run.data", cir)
    open(f"{WORK}/run.cir", "w").write(cir)
    subprocess.run(["ngspice", "-b", "run.cir"], cwd=WORK, capture_output=True, text=True, timeout=900)
    if not os.path.exists(f"{WORK}/run.data"):
        return tube, None
    d = np.loadtxt(f"{WORK}/run.data"); t, vint, T = d[:, 0], d[:, 7], d[:, 9]
    above = vint > VHI
    dt = np.diff(t)
    t_ride = float(np.sum(dt[above[:-1]]))                       # total time V_int > 3.7
    t_last = float(t[np.where(above)[0][-1]]) if above.any() else 0.0  # when it finally settles below
    vint_pk = float(np.max(vint))
    vint_ss = float(np.mean(vint[t > 9.5]))
    T_over = float(np.max(T) - np.mean(T[t > 9.5]))
    return tube, dict(t_ride=t_ride, t_last=t_last, vint_pk=vint_pk, vint_ss=vint_ss, T_over=T_over)

t0 = time.time()
with ThreadPoolExecutor(max_workers=4) as ex:
    res = dict(ex.map(measure, TUBES))
print(f"cold-start V_int ride (instant-on, healthy)  [{time.time()-t0:.0f}s]\n")
print(f"{'tube':9} {'Vint_pk':>8} {'ride>3.7V':>10} {'settle@':>8} {'Vint_ss':>8} {'minTfhi':>8} {'T_over':>7}")
for tb in TUBES:
    o = res.get(tb)
    if not o:
        print(f"{tb:9} NODATA"); continue
    min_tfhi = o['t_ride'] / 0.916
    print(f"{tb:9} {o['vint_pk']:7.2f}V {o['t_ride']*1e3:8.0f}ms {o['t_last']*1e3:6.0f}ms "
          f"{o['vint_ss']:6.2f}V {min_tfhi*1e3:6.0f}ms {o['T_over']:6.1f}K")
print("\nride>3.7V = total ms V_int above the 3.7V high-side threshold;")
print("minTfhi = ride/0.916 (watchdog trips above this); set t_fault_hi above it w/ margin.")
