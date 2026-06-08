"""Closed-loop check of the hardware commutating-switch demod against the
behavioural B_demod stand-in.

Runs make_netlist(switch_demod=True) (the real CD4053B chopper: comparator +
4 commutating switches + post-chop difference amp with redundant-split R_dda_g)
on iv6 + ilc11_7 and confirms it regulates to ~800 K with matching THD.  The
switch demod is the hardware realization the behavioural source stands in for;
this is the verification that the two are equivalent.

Heavy sim -> run on simhost (ssh -J hv3 debian@192.168.30.60), not locally.
"""
import sys, subprocess, re, os, math
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import regulator as r

WORK = "/tmp/swdemod"; os.makedirs(WORK, exist_ok=True)
T_END, W0, W1 = 10.0, 9.0, 10.0


def thd(t, v, t0, t1, f_seed=1000.0):
    m = (t >= t0) & (t <= t1); ts = t[m]; vs = v[m]
    fs = np.linspace(f_seed*0.95, f_seed*1.05, 201); best = (np.inf, f_seed, 0, 0)
    for f in fs:
        sb = np.sin(2*np.pi*f*ts); cb = np.cos(2*np.pi*f*ts)
        a = np.trapezoid(vs*sb, ts)/np.trapezoid(sb*sb, ts)
        b = np.trapezoid(vs*cb, ts)/np.trapezoid(cb*cb, ts)
        if -math.hypot(a, b) < best[0]: best = (-math.hypot(a, b), f, a, b)
    _, f0, a, b = best
    res = vs - a*np.sin(2*np.pi*f0*ts) - b*np.cos(2*np.pi*f0*ts)
    return math.sqrt(np.trapezoid(res*res, ts)/(ts[-1]-ts[0]))/math.sqrt((a*a+b*b)/2)*100


def run(tube):
    cir = r.make_netlist(switch_demod=True, instrument_power=False,
                         T_end=T_END, **r.TUBES[tube])
    cir = re.sub(r"wrdata \S+/run\.data", f"wrdata {WORK}/{tube}.data", cir)
    open(f"{WORK}/{tube}.cir", "w").write(cir)
    p = subprocess.run(["ngspice", "-b", f"{tube}.cir"], cwd=WORK,
                       capture_output=True, text=True, timeout=900)
    if not os.path.exists(f"{WORK}/{tube}.data"):
        return None, (p.stderr + p.stdout)[-400:]
    d = np.loadtxt(f"{WORK}/{tube}.data"); t = d[:, 0]; m = t > W0
    vfil = d[:, 1] - d[:, 3]
    return dict(T=float(np.mean(d[m, 9])), vint=float(np.mean(d[m, 7])),
                sd=float(np.std(d[m, 7])), thd=20*math.log10(thd(t, vfil, W0, W1)/100)), None


print("Hardware switch demod (make_netlist switch_demod=True) — closed-loop vs behavioural")
print("  (behavioural baseline: iv6 800.0/3.075/-46.1dB  ilc11_7 800.0/3.025/-34.7dB)")
print(f"{'tube':9} {'T':>7} {'V_int':>7} {'V_int_sd':>9} {'THD':>8}")
for tube in ["iv6", "ilc11_7"]:
    x, err = run(tube)
    if x is None:
        print(f"{tube:9} ERR: {err[-200:]}"); continue
    print(f"{tube:9} {x['T']:7.1f} {x['vint']:7.3f} {x['sd']:9.5f} {x['thd']:7.1f}dB")
