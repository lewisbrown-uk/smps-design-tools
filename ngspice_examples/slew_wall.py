"""Focused capture of ILC1-1/7's slew wall (cheaper than slew_sweep's full grid):
short sim, coarser-but-adequate timestep, frequencies bracketing the ~18 kHz
0.8 V/us limit. Reuses the calibrated Islew (127.3 nA -> 0.8 V/us). simhost.
"""
import sys, os, re, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import regulator as r
import overnight_battery as ob
import slew_sweep as ss          # ngrun, FREQ_RE, OPMATCH (import is safe -- __main__ guarded)

ISLEW = 127.3e-9                 # calibrated to 0.8 V/us @ GBW 1 MHz
os.makedirs("/tmp/slewwall", exist_ok=True)

def cell(F, slew):
    try:
        T = 1.5
        cir = r.make_netlist(T_end=T, **r.TUBES["ilc11_7"])
        cir = ss.FREQ_RE.sub(rf"\g<1>{F}\g<2>", cir)
        ms = min(50e-6, 1.0 / (12 * F))
        cir = re.sub(r"\.tran \S+ \S+ 0 uic", f".tran {ms:.4g} {T} 0 uic", cir)
        if slew:
            cir = cir.replace(ss.OPMATCH, f"uopamp_lvl3_slew Islew={ISLEW:.6g} Avol=5meg")
        w = f"/tmp/slewwall/{int(F)}_{'s' if slew else 'n'}"
        cir = re.sub(r"wrdata \S+/run\.data", f"wrdata {w}/x.data", cir)
        d = ss.ngrun(cir, w)
        if d is None: return None
        t, vd, na = d[:, 0], d[:, 1], d[:, 3]
        return ob.thd_db(t, vd - na, 1.0, T, f_seed=float(F))
    except Exception:
        return None

FREQS = [3000, 5000, 8000, 10000, 12000, 15000]
t0 = time.time()
with ThreadPoolExecutor(max_workers=12) as ex:
    fu = {(F, sl): ex.submit(cell, F, sl) for F in FREQS for sl in (False, True)}
    out = {k: v.result() for k, v in fu.items()}

def row(sl):
    return " ".join(f"{(out[(F, sl)] if out[(F, sl)] is not None else float('nan')):6.1f}" for F in FREQS)
lines = ["ilc11_7 slew-wall focus (T=1.5s, window 1.0-1.5s):",
         "F:       " + " ".join(f"{F//1000:>6}k" for F in FREQS),
         "nominal: " + row(False),
         "slew:    " + row(True),
         f"[{time.time()-t0:.0f}s]"]
open(os.path.join(HERE, "slew_wall.txt"), "w").write("\n".join(lines) + "\n")
print("\n".join(lines))
