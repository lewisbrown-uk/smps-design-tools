"""Investigate v_drv_atten DC drift for ILC1-1/7. Captures v_drv_atten,
v_osc, n_ap_plus, v_int_out over the full simulation, then computes
running mean over 100 ms windows to see if there's a low-frequency
drift or oscillation.
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

    work = m.WORK
    cir = work / f"drift_{tube}.cir"
    dat = work / f"drift_{tube}.data"
    netlist = m.make_netlist(dat, v_preset=0.0, t_ramp=0.0,
                             r_int_scale=spec["r_int_scale"], mc=mc)
    new_control = f""".save V(v_drv_atten) V(v_osc) V(n_ap_plus) V(n_ap_minus) V(v_int_out) V(v_ap) V(v_osc_drive) V(v_ap_drive) @J_var[id]
.control
run
let v_da    = v(v_drv_atten)
let v_o     = v(v_osc)
let v_napp  = v(n_ap_plus)
let v_napm  = v(n_ap_minus)
let v_int   = v(v_int_out)
let v_ap_w  = v(v_ap)
let v_od    = v(v_osc_drive)
let v_ad    = v(v_ap_drive)
let i_jfet  = @J_var[id]
wrdata {dat.as_posix()} v_da v_o v_napp v_napm v_int v_ap_w v_od v_ad i_jfet
.endcontrol"""
    netlist = re.sub(r"\.control.*?\.endcontrol", new_control, netlist, flags=re.DOTALL)
    cir.write_text(netlist)
    res = subprocess.run(["ngspice", "-b", cir.name], cwd=work,
                         capture_output=True, text=True, timeout=600)
    if res.returncode != 0:
        print(res.stderr[-2000:]); raise SystemExit(1)
    d = np.loadtxt(dat)
    t       = d[:, 0]
    v_da    = d[:, 1]
    v_o     = d[:, 3]
    v_napp  = d[:, 5]
    v_napm  = d[:, 7]
    v_int   = d[:, 9]
    v_ap    = d[:, 11]
    v_od    = d[:, 13]
    v_ad    = d[:, 15]
    i_jfet  = d[:, 17]
    print(f"Total samples: {len(t)}, t_end = {t[-1]:.3f}s")
    def twm(x, tt):
        if len(tt) < 2: return np.nan
        return np.trapezoid(x, tt) / (tt[-1] - tt[0])
    # Steady-state window: last 50 ms
    mask = t > t[-1] - 0.050
    tm = t[mask]
    print(f"\n=== Steady-state DC means (last 50 ms, time-weighted) ===")
    print(f"  v_drv_atten  = {twm(v_da[mask], tm)*1e3:+8.3f} mV  (Buffer 0 output)")
    print(f"  v_osc_drive  = {twm(v_od[mask], tm)*1e3:+8.3f} mV  (Buffer 1 output, drives bridge top)")
    print(f"  v_osc        = {twm(v_o[mask],  tm)*1e3:+8.3f} mV  (Wien output)")
    print(f"  n_ap_minus   = {twm(v_napm[mask],tm)*1e3:+8.3f} mV  (all-pass minus input, summing junction)")
    print(f"  n_ap_plus    = {twm(v_napp[mask],tm)*1e3:+8.3f} mV  (all-pass plus input, JFET source)")
    print(f"  v_ap         = {twm(v_ap[mask], tm)*1e3:+8.3f} mV  (all-pass output)")
    print(f"  v_ap_drive   = {twm(v_ad[mask], tm)*1e3:+8.3f} mV  (Buffer 2 output, drives bridge bottom)")
    print(f"  v_int_out    = {twm(v_int[mask],tm)*1e3:+8.3f} mV  (PID/integrator output, JFET gate cmd)")
    print(f"  I_JFET (id)  = {twm(i_jfet[mask],tm)*1e6:+8.3f} uA  (DC component through JFET channel)")
    print(f"\n  Bridge differential DC: v_osc_drive - v_ap_drive = "
          f"{(twm(v_od[mask],tm) - twm(v_ad[mask],tm))*1e3:+8.3f} mV")
    print(f"  Buffer 2 inverting-gain check: v_ap_drive predicted = -k_buf*v_ap = "
          f"{-12 * twm(v_ap[mask],tm)*1e3:+8.3f} mV  (vs measured {twm(v_ad[mask],tm)*1e3:+8.3f} mV)")
    try: dat.unlink()
    except OSError: pass


if __name__ == "__main__":
    main()
