import sys, types, subprocess, time
import numpy as np
mpl = types.ModuleType("matplotlib"); mpl.use = lambda *a, **k: None
sys.modules.setdefault("matplotlib", mpl)
sys.modules.setdefault("matplotlib.pyplot", types.ModuleType("plt"))
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_closed_loop as tcl
from validate_cap_470nf_iv6max_level1 import swap_to_level1

tcl.T_END = 6.0   # 6 s — should be plenty for the slow loop
spec = tcl.TUBES["iv18"]
mc = {k: spec[k] for k in ("r_amb", "sigma_eps_A", "c_th", "r_top_ref", "r_bot_ref", "r_sense")}
mc["t_rail_ramp"] = 100e-6
for k in ("booster", "ce_buf", "mos_buf"):
    if spec.get(k): mc[k] = True
for k in ("buf_fb1", "buf_fb_ap", "v_buf", "c_ap"):
    if spec.get(k) is not None: mc[k] = spec[k]
cir = tcl.WORK / "iv3long.cir"
dat = tcl.WORK / "iv3long.data"
raw = tcl.make_netlist(dat, v_preset=0.0, t_ramp=0.0, r_int_scale=spec["r_int_scale"], mc=mc)
if spec.get("mos_buf"):
    raw = swap_to_level1(raw)
cir.write_text(raw)
t0 = time.time()
res = subprocess.run(["ngspice", "-b", cir.name], cwd=tcl.WORK, capture_output=True, text=True, timeout=1800)
print(f"wall={time.time()-t0:.1f}s rc={res.returncode}")
if res.returncode != 0:
    print(res.stderr[-500:])
    sys.exit(1)
d = np.loadtxt(dat)
t = d[:, 0]; T = d[:, 17]; v_int = d[:, 15]
for s, e in [(5.5, 6.0), (5.0, 5.5), (4.0, 4.5), (3.0, 3.5), (2.0, 2.5), (1.0, 1.5)]:
    m = (t > s) & (t < e)
    if not m.any(): continue
    ts = t[m]; Ts = T[m]; vs = v_int[m]
    print(f"t={s:.1f}-{e:.1f}: T_avg={Ts.mean():.2f}  dT/window={(Ts[-1]-Ts[0])*1000:.2f}mK  V_int_avg={vs.mean():.4f}  dV={(vs[-1]-vs[0])*1e6:.1f}uV")
