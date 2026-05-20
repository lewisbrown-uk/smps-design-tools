"""6-second convergence on all 4 tubes with the JFET+bootstrap arch.
Reports T_end and rate of approach at multiple time windows."""
import sys, types, subprocess, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import numpy as np

mpl = types.ModuleType("matplotlib"); mpl.use=lambda *a, **k: None
sys.modules.setdefault("matplotlib", mpl)
sys.modules.setdefault("matplotlib.pyplot", types.ModuleType("plt"))
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_closed_loop as tcl
from validate_cap_470nf_iv6max_level1 import swap_to_level1

tcl.T_END = 6.0
TUBES = ("iv18", "iv6", "ilc11_7", "ilc11_8")


def run(tk):
    spec = tcl.TUBES[tk]
    mc = {k: spec[k] for k in ("r_amb", "sigma_eps_A", "c_th", "r_top_ref", "r_bot_ref", "r_sense")}
    mc["t_rail_ramp"] = 100e-6
    for k in ("booster", "ce_buf", "mos_buf"):
        if spec.get(k): mc[k] = True
    for k in ("buf_fb1", "buf_fb_ap", "v_buf", "c_ap"):
        if spec.get(k) is not None: mc[k] = spec[k]
    cir = tcl.WORK / f"jl_{tk}.cir"
    dat = tcl.WORK / f"jl_{tk}.data"
    raw = tcl.make_netlist(dat, v_preset=0.0, t_ramp=0.0, r_int_scale=spec["r_int_scale"], mc=mc)
    if spec.get("mos_buf"):
        raw = swap_to_level1(raw)
    cir.write_text(raw)
    t0 = time.time()
    res = subprocess.run(["ngspice", "-b", cir.name], cwd=tcl.WORK, capture_output=True, text=True, timeout=1800)
    wall = time.time() - t0
    if res.returncode != 0:
        return tk, None, spec, res.stderr[-300:], wall
    return tk, np.loadtxt(dat), spec, None, wall


with ThreadPoolExecutor(max_workers=4) as ex:
    results = list(ex.map(run, TUBES))

print(f"{'tube':9s} {'wall':>5s} {'T_op':>5s} {'T@2.5':>7s} {'T@4':>6s} {'T@6':>6s} {'dT@5-6':>7s} {'V_int@6':>8s} {'status':s}")
for tk, d, spec, err, wall in results:
    if d is None:
        print(f"{tk:9s} FAIL: {err[:100]}")
        continue
    t = d[:, 0]; T = d[:, 17]; v_int = d[:, 15]
    def T_at(t_pt):
        idx = np.argmin(np.abs(t - t_pt))
        return float(T[idx])
    def V_at(t_pt):
        idx = np.argmin(np.abs(t - t_pt))
        return float(v_int[idx])
    T_25 = T_at(2.5); T_4 = T_at(4.0); T_6 = T_at(6.0)
    # rate over last 1s
    mask = (t > 5.0) & (t < 6.0)
    dT_last = (T[mask][-1] - T[mask][0]) if mask.any() else 0.0
    status = "OK" if abs(T_6 - spec["T_op"]) < 3 else ("approaching" if abs(dT_last) > 0.5 else "stuck")
    print(f"{tk:9s} {wall:5.0f} {spec['T_op']:5.0f} {T_25:7.2f} {T_4:6.2f} {T_6:6.2f} {dT_last:+7.2f} {V_at(6.0):+8.4f} {status}")
