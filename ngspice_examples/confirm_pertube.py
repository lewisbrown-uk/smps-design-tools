"""Confirm the proposed per-tube t_fault_hi: no cold-start false-trip AND the
resulting botref_short fault peak/dwell.  Reuses t_fhi_sweep's validated cell
logic (correct n_latch false-trip detector)."""
import sys, os
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import t_fhi_sweep as ts

TFHI = {"iv18": 0.3, "iv6": 0.4, "ilc11_7": 1.2, "ilc11_8": 1.3}
SCEN = ["instant_on", "dropout", "brownout"]

tasks = []
for tb, k in TFHI.items():
    tasks.append(("dw", tb, k, None))
    for sc in SCEN:
        tasks.append(("ft", tb, k, sc))

with ThreadPoolExecutor(max_workers=16) as ex:
    res = dict(ex.map(ts.cell, tasks))

print("per-tube t_fault_hi confirmation\n")
print(f"{'tube':9} {'tfhi':>5} {'instant':>8} {'dropout':>8} {'brown':>8} | {'botref_pk':>9} {'>900K':>6} {'>850K':>6}")
for tb, k in TFHI.items():
    def ft(sc):
        o = res.get(("ft", tb, k, sc)) or {}
        if "err" in o or not o: return "ERR"
        return "**TRIP**" if o.get("trip") else "ok"
    dw = res.get(("dw", tb, k, None)) or {}
    pk = dw.get("peak", float("nan")); d9 = dw.get("d900", 0) * 1e3; d8 = dw.get("d850", 0) * 1e3
    print(f"{tb:9} {k:>4}s {ft('instant_on'):>8} {ft('dropout'):>8} {ft('brownout'):>8} | "
          f"{pk:8.0f}K {d9:5.0f}m {d8:5.0f}m")
