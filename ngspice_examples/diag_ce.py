"""Focused trace for CE buffer debugging. Captures the loop's internal
signals to diagnose why the loop converges at the wrong V_fil.
"""
from __future__ import annotations
import sys, re, subprocess
from pathlib import Path
import numpy as np

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import test_closed_loop as m


def main():
    tube = sys.argv[1] if len(sys.argv) > 1 else "iv6"
    spec = m.TUBES[tube]
    mc = {k: spec[k] for k in ("r_amb", "sigma_eps_A", "c_th",
                               "r_top_ref", "r_bot_ref", "r_sense")}
    if spec.get("booster"): mc["booster"] = True
    if spec.get("c_ap")    is not None: mc["c_ap"]    = spec["c_ap"]
    if spec.get("buf_fb1") is not None: mc["buf_fb1"] = spec["buf_fb1"]
    if spec.get("buf_fb_ap") is not None: mc["buf_fb_ap"] = spec["buf_fb_ap"]
    if spec.get("v_buf")   is not None: mc["v_buf"]   = spec["v_buf"]
    if spec.get("ce_buf"): mc["ce_buf"] = True

    work = m.WORK
    cir = work / f"ce_{tube}.cir"
    dat = work / f"ce_{tube}.data"
    netlist = m.make_netlist(dat, v_preset=0.0, t_ramp=0.0,
                             r_int_scale=spec["r_int_scale"], mc=mc)
    new_control = f""".save V(v_drv_atten) V(v_osc_drive) V(v_ap) V(v_ap_drive) V(v_int_out) V(n_demout) V(v_osc) V(T_node) V(n_buf_osc_out)
.control
run
let v_da   = v(v_drv_atten)
let v_od   = v(v_osc_drive)
let v_ap_w = v(v_ap)
let v_ad   = v(v_ap_drive)
let v_int  = v(v_int_out)
let v_dem  = v(n_demout)
let v_o    = v(v_osc)
let t_n    = v(T_node)
let v_op   = v(n_buf_osc_out)
wrdata {dat.as_posix()} v_da v_od v_ap_w v_ad v_int v_dem v_o t_n v_op
.endcontrol"""
    netlist = re.sub(r"\.control.*?\.endcontrol", new_control, netlist, flags=re.DOTALL)
    cir.write_text(netlist)
    res = subprocess.run(["ngspice", "-b", cir.name], cwd=work,
                         capture_output=True, text=True, timeout=600)
    if res.returncode != 0:
        print(res.stderr[-2000:]); raise SystemExit(1)
    d = np.loadtxt(dat)
    t = d[:, 0]
    v_da   = d[:, 1]
    v_od   = d[:, 3]
    v_ap_w = d[:, 5]
    v_ad   = d[:, 7]
    v_int  = d[:, 9]
    v_dem  = d[:, 11]
    v_o    = d[:, 13]
    T_n    = d[:, 15]
    v_op   = d[:, 17]
    print(f"=== {spec['name']} CE trace ===\n")
    print(f"  Total samples: {len(t)}, t_end = {t[-1]:.3f}s")
    print(f"\n  Signal swings at various times (peak to peak over ~3 cycles):")
    print(f"  {'t [s]':>6s}  {'v_int':>8s}  {'v_dem':>9s}  {'v_drv_pp':>9s}  "
          f"{'v_o_pp':>8s}  {'v_od_pp':>8s}  {'v_ap_pp':>8s}  {'v_ad_pp':>8s}  {'v_op_pp':>8s}  {'T':>6s}")
    for ts in [0.005, 0.020, 0.050, 0.100, 0.200, 0.500, 1.000, 2.000, 4.99]:
        i = int(np.searchsorted(t, ts))
        if i >= len(t) - 50: continue
        # Look back ~3 ms to get peak-to-peak
        i0 = int(np.searchsorted(t, t[i] - 0.003))
        sl = slice(i0, i)
        def pp(x): return float(np.max(x[sl]) - np.min(x[sl]))
        def avg(x):
            tt = t[sl]; xx = x[sl]
            if len(tt) < 2: return float("nan")
            return float(np.trapezoid(xx, tt) / (tt[-1] - tt[0]))
        print(f"  {t[i]:6.3f}  {avg(v_int):+8.3f}  {avg(v_dem):+9.4f}  "
              f"{pp(v_da):8.3f}  {pp(v_o):7.3f}  {pp(v_od):7.3f}  "
              f"{pp(v_ap_w):7.3f}  {pp(v_ad):7.3f}  {pp(v_op):7.3f}  {avg(T_n):6.0f}")
    try: dat.unlink()
    except OSError: pass


if __name__ == "__main__":
    main()
