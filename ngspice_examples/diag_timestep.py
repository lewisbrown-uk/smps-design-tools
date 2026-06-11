"""Characterise the timestep behaviour at the protection disconnect event.
Runs a short fault sim (protection ON) and reports the dt profile: how small dt
gets, for how long, and whether it RECOVERS (slow) or floors out (pathological).
Writes a summary to diag_timestep_<tube>.txt (poll if the ssh return is empty)."""
import sys, subprocess, re, os, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import regulator as r

TUBE = sys.argv[1] if len(sys.argv) > 1 else "iv18"
T_INJ, T_END = 1.5, 2.2          # settled by ~1s; fault at 1.5; watch 700ms past it
W = f"/tmp/dts_{TUBE}"; os.makedirs(W, exist_ok=True)
SUMM = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"diag_timestep_{TUBE}.txt")

cir = r.make_netlist(overpower_protect=True, T_end=T_END, **r.TUBES[TUBE])
cir = cir.replace(".tran", f"B_xubuf n_buf_o nf_xubuf I = V(n_buf_o,nf_xubuf)"
                  f"/(time < {T_INJ} ? 1e9 : 0.05)\nV_xubuf nf_xubuf 0 9.9\n.tran", 1)
cir = re.sub(r"wrdata \S+/run\.data", f"wrdata {W}/run.data", cir)
open(f"{W}/run.cir", "w").write(cir)

t0 = time.time()
p = subprocess.run(["ngspice", "-b", "run.cir"], cwd=W, capture_output=True, text=True, timeout=900)
wall = time.time() - t0

lines = []
def out(s): lines.append(s); print(s, flush=True)

if not os.path.exists(f"{W}/run.data"):
    out(f"{TUBE}: NO DATA after {wall:.0f}s. tail:\n" + (p.stderr+p.stdout)[-400:])
else:
    d = np.loadtxt(f"{W}/run.data"); t = d[:, 0]
    dt = np.diff(t); ti = t[1:]                      # dt[k] is the step ending at ti[k]
    pre = dt[ti < T_INJ - 0.01]                       # steps before the fault
    post = dt[ti > T_INJ + 0.5]                       # steps well after (recovery region)
    i_min = int(np.argmin(dt))
    tiny = dt < 1e-9                                  # "collapsed" = sub-nanosecond
    collapse_span = float(t[-1])                      # placeholder
    if tiny.any():
        tt = ti[tiny]
        collapse_span = float(tt.max() - tt.min())
    out(f"=== {TUBE}: timestep at the protection disconnect ===")
    out(f"  wall clock        : {wall:.1f} s   ({len(t)} accepted steps, sim to {t[-1]:.3f}s)")
    out(f"  dt before fault   : median {np.median(pre)*1e6:.2f} µs   (the .tran ceiling)")
    out(f"  dt MIN (collapse) : {dt[i_min]*1e15:.3f} fs  @ t-T_INJ = {(ti[i_min]-T_INJ)*1e3:+.3f} ms")
    out(f"  steps with dt<1ns : {int(tiny.sum())} of {len(dt)}  "
        f"(={100*tiny.sum()/len(dt):.1f}% of all steps)")
    out(f"  collapse sim-span : {collapse_span*1e3:.3f} ms of sim-time spent sub-ns")
    out(f"  dt AFTER recovery : median {np.median(post)*1e6:.2f} µs  "
        f"(vs {np.median(pre)*1e6:.2f} µs pre-fault)")
    recovered = len(post) and np.median(post) > 1e-7
    out(f"  RECOVERS to normal dt after the event? {'YES' if recovered else 'NO — stays collapsed'}")
    out(f"  reached sim end ({T_END}s)? {'YES' if t[-1] >= T_END-1e-3 else 'NO — stalled at '+format(t[-1],'.3f')+'s'}")

open(SUMM, "w").write("\n".join(lines) + "\n")
print("WROTE", SUMM, flush=True)
