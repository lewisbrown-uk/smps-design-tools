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
    new_control = f""".save V(v_drv_atten) V(v_osc) V(n_ap_plus) V(v_int_out) V(v_ap)
.control
run
let v_da    = v(v_drv_atten)
let v_o     = v(v_osc)
let v_napp  = v(n_ap_plus)
let v_int   = v(v_int_out)
let v_ap_w  = v(v_ap)
wrdata {dat.as_posix()} v_da v_o v_napp v_int v_ap_w
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
    v_int   = d[:, 7]
    v_ap    = d[:, 9]
    print(f"Total samples: {len(t)}, t_end = {t[-1]:.3f}s")
    # Time-weighted (trapezoidal) mean -- correct for ngspice variable timestep.
    # Plain np.mean weights samples equally, but ngspice clusters samples at
    # high-dV/dt regions, biasing the result for non-sinusoidal waveforms.
    def twm(x, tt):
        if len(tt) < 2: return np.nan
        return np.trapezoid(x, tt) / (tt[-1] - tt[0])
    # Compute running mean over 500 ms windows
    print("\nWindow [s]      v_drv_atten      v_osc          n_ap_plus       v_int_out       v_ap")
    print("-" * 100)
    for w_start in np.arange(0.5, 5.0, 0.5):
        w_end = w_start + 0.5
        mask = (t >= w_start) & (t < w_end)
        if mask.sum() < 100: continue
        tm = t[mask]
        print(f"  [{w_start:.2f}-{w_end:.2f}]   {twm(v_da[mask], tm)*1e3:+8.2f}mV       "
              f"{twm(v_o[mask], tm)*1e3:+8.2f}mV    "
              f"{twm(v_napp[mask], tm)*1e3:+8.2f}mV     "
              f"{twm(v_int[mask], tm)*1e3:+8.2f}mV    "
              f"{twm(v_ap[mask], tm)*1e3:+8.2f}mV")
    # Final 5 ms detail
    mask = t > t[-1] - 0.005
    tm = t[mask]
    print(f"\n  Final 5 ms:   {twm(v_da[mask], tm)*1e3:+8.2f}mV       "
          f"{twm(v_o[mask], tm)*1e3:+8.2f}mV    "
          f"{twm(v_napp[mask], tm)*1e3:+8.2f}mV     "
          f"{twm(v_int[mask], tm)*1e3:+8.2f}mV    "
          f"{twm(v_ap[mask], tm)*1e3:+8.2f}mV")
    try: dat.unlink()
    except OSError: pass


if __name__ == "__main__":
    main()
