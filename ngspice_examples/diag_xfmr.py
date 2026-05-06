"""Trajectory diagnostic for transformer-coupled ILC1-1/7 HF sim.

Runs the HF sim, captures v_int_out plus primary/secondary V_diff over
the full 100 ms, and prints per-decade snapshots so we can tell whether
the integrator is saturated against the anti-windup clamp or just slow.
"""
from __future__ import annotations
import sys, re, subprocess
from pathlib import Path
import numpy as np

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import test_closed_loop as m


def main():
    tube = sys.argv[1] if len(sys.argv) > 1 else "ilc11_7"
    spec = m.TUBES[tube]
    mc = {k: spec[k] for k in ("r_amb", "sigma_eps_A", "c_th",
                               "r_top_ref", "r_bot_ref", "r_sense")}
    if spec.get("booster"): mc["booster"] = True
    if spec.get("c_ap")    is not None: mc["c_ap"]    = spec["c_ap"]
    if spec.get("buf_fb1") is not None: mc["buf_fb1"] = spec["buf_fb1"]
    if spec.get("buf_fb_ap") is not None: mc["buf_fb_ap"] = spec["buf_fb_ap"]
    if spec.get("v_buf")   is not None: mc["v_buf"]   = spec["v_buf"]
    if spec.get("ce_buf"): mc["ce_buf"] = True
    if spec.get("mos_buf"): mc["mos_buf"] = True
    if spec.get("tank_l") is not None: mc["tank_l"] = spec["tank_l"]
    if spec.get("tank_c") is not None: mc["tank_c"] = spec["tank_c"]
    if spec.get("bias_diode"): mc["bias_diode"] = spec["bias_diode"]
    if spec.get("xfmr_n") is not None: mc["xfmr_n"] = spec["xfmr_n"]
    if spec.get("xfmr_lpri") is not None: mc["xfmr_lpri"] = spec["xfmr_lpri"]
    mc["hf_mode"] = True
    mc["R_op"] = spec["R_op"]
    mc["T_op"] = spec["T_op"]
    mc["v_int_settled"] = 2.10
    use_xfmr = spec.get("xfmr_n") is not None

    work = m.WORK; work.mkdir(exist_ok=True)
    cir = work / f"diagxf_{tube}.cir"
    dat = work / f"diagxf_{tube}.data"
    netlist = m.make_netlist(dat, v_preset=0.0, t_ramp=0.0,
                             r_int_scale=spec["r_int_scale"], mc=mc)
    netlist = re.sub(r"\.tran\s+\S+\s+\S+(\s+UIC)?",
                     ".tran 100n 0.100 UIC", netlist)
    sec_pri = "let v_o_sec = v(v_osc_load)\nlet v_a_sec = v(v_ap_load)" \
        if use_xfmr else "let v_o_sec = v(v_osc_drive)\nlet v_a_sec = v(v_ap_drive)"
    new_control = f""".control
run
let v_int = v(v_int_out)
let v_o_pri = v(v_osc_drive)
let v_a_pri = v(v_ap_drive)
{sec_pri}
let v_clip_hi = v(v_clamp_hi)
let v_clip_lo = v(v_clamp_lo)
wrdata {dat.as_posix()} v_int v_o_pri v_a_pri v_o_sec v_a_sec v_clip_hi v_clip_lo
.endcontrol"""
    netlist = re.sub(r"\.control.*?\.endcontrol", new_control,
                     netlist, flags=re.DOTALL)
    cir.write_text(netlist)
    res = subprocess.run(["ngspice", "-b", cir.name], cwd=work,
                         capture_output=True, text=True, timeout=900)
    if res.returncode != 0:
        print(res.stderr[-2000:]); raise SystemExit(1)
    d = np.loadtxt(dat)
    t       = d[:, 0]
    v_int   = d[:, 1]
    v_o_pri = d[:, 3]
    v_a_pri = d[:, 5]
    v_o_sec = d[:, 7]
    v_a_sec = d[:, 9]
    v_clip_hi = d[:, 11]
    v_clip_lo = d[:, 13]

    print(f"=== {spec['name']} HF transformer trajectory ===")
    print(f"  total samples: {len(t)}, t_end = {t[-1]*1e3:.2f} ms")
    print(f"  clamp rails:   v_clamp_lo ~ {np.mean(v_clip_lo):+.3f} V, "
          f"v_clamp_hi ~ {np.mean(v_clip_hi):+.3f} V")
    print()
    print(f"  Per-instant v_int and bridge V_diff (peak-to-peak over a 30 us window):")
    print(f"  {'t [ms]':>8s}  {'v_int':>8s}  "
          f"{'V_pri_pp':>9s}  {'V_pri_avg':>10s}  "
          f"{'V_sec_pp':>9s}  {'V_sec_avg':>10s}")
    times = [0.0001, 0.0005, 0.001, 0.002, 0.005, 0.010, 0.020,
             0.030, 0.050, 0.075, 0.099]
    win_us = 30e-6
    for ts in times:
        i = int(np.searchsorted(t, ts))
        if i >= len(t) - 5: continue
        i0 = int(np.searchsorted(t, max(0.0, t[i] - win_us)))
        sl = slice(i0, i + 1)
        tt = t[sl]
        if len(tt) < 2: continue
        dur = tt[-1] - tt[0]
        def avg(x):
            return float(np.trapezoid(x[sl], tt) / dur) if dur > 0 else float("nan")
        v_diff_pri = v_o_pri - v_a_pri
        v_diff_sec = v_o_sec - v_a_sec
        v_pri_pp = float(v_diff_pri[sl].max() - v_diff_pri[sl].min())
        v_sec_pp = float(v_diff_sec[sl].max() - v_diff_sec[sl].min())
        v_pri_rms = float(np.sqrt(np.trapezoid(v_diff_pri[sl]**2, tt) / dur))
        v_sec_rms = float(np.sqrt(np.trapezoid(v_diff_sec[sl]**2, tt) / dur))
        print(f"  {t[i]*1e3:8.3f}  {avg(v_int):+8.3f}  "
              f"{v_pri_pp:9.3f}  {v_pri_rms:10.3f}  "
              f"{v_sec_pp:9.3f}  {v_sec_rms:10.3f}")
    print()
    # Look at the integrator's *envelope* (slow trend) by removing the AC
    # ripple. Use a 1 ms moving boxcar by re-sampling on a uniform grid.
    t_uni = np.linspace(t[0], t[-1], 5000)
    v_int_uni = np.interp(t_uni, t, v_int)
    win = 50  # ~1 ms at 5000 pts over 100 ms
    kernel = np.ones(win) / win
    v_int_smooth = np.convolve(v_int_uni, kernel, mode="same")
    print(f"  v_int (low-pass) trajectory:")
    print(f"  {'t [ms]':>8s}  {'v_int_lp':>10s}")
    for ms in [0.5, 1, 2, 5, 10, 20, 30, 50, 75, 99]:
        i = int(np.searchsorted(t_uni, ms*1e-3))
        if i >= len(t_uni): continue
        print(f"  {t_uni[i]*1e3:8.2f}  {v_int_smooth[i]:+10.4f}")
    # Final value vs. clamp
    print()
    print(f"  Final v_int  = {v_int[-1]:+.3f} V")
    print(f"  Final clamps = [{v_clip_lo[-1]:+.3f}, {v_clip_hi[-1]:+.3f}] V")
    margin_hi = v_clip_hi[-1] - v_int[-1]
    margin_lo = v_int[-1] - v_clip_lo[-1]
    print(f"  Margin to clamp_hi: {margin_hi*1e3:+.1f} mV")
    print(f"  Margin to clamp_lo: {margin_lo*1e3:+.1f} mV")
    if abs(margin_hi) < 0.05 or abs(margin_lo) < 0.05:
        print("  *** INTEGRATOR PINNED AGAINST CLAMP ***")


if __name__ == "__main__":
    main()
