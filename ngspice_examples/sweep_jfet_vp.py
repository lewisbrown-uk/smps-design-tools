"""JFET sensitivity sweep: vary V_p (V_GS_off) across the 2N5457
datasheet range and measure how the closed loop responds.

The MMBF5457 has notoriously wide V_GS_off spread: -0.5 V to -6 V per
the datasheet (12x). Forum builders won't bin parts, so the design has
to converge across the whole range without trimming. This sweep checks
which tubes survive and which corner cases break.

Sweep strategy:
- 1D over V_p in {-0.5, -1.0, -1.5, -2.0, -2.5, -3.0, -4.0, -6.0} V
- Hold I_DSS at the typical 3 mA by adjusting Beta = I_DSS / V_p^2
- Run 2-second transient (long enough for thermal to be heading toward
  target; short enough that the sweep finishes in reasonable time)
- For each (tube, V_p), report:
    * V_op_RMS measured in last 100 ms (target = spec V_op)
    * v_int settled (target: inside ~[+0.3, +1.8] V clamp range)
    * T settled (target = T_op = 800 K)
    * converged? (no ngspice abort)
    * over-rail? (v_int outside clamp)
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import re, subprocess

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import test_closed_loop as m


VP_GRID = [-0.5, -1.0, -1.5, -2.0, -2.5, -3.0]
I_DSS_TARGET = 5e-3   # MMBFJ113 typical (datasheet I_DSS = 2 to 20 mA, typ ~5)


def build_mc(spec, jfet_vp):
    """Build mc dict for a tube spec, with overridden JFET parameters."""
    mc = {k: spec[k] for k in ("r_amb", "sigma_eps_A", "c_th",
                               "r_top_ref", "r_bot_ref", "r_sense")}
    if spec.get("booster"): mc["booster"] = True
    if spec.get("c_ap")    is not None: mc["c_ap"]    = spec["c_ap"]
    if spec.get("buf_fb1") is not None: mc["buf_fb1"] = spec["buf_fb1"]
    if spec.get("buf_fb_ap") is not None: mc["buf_fb_ap"] = spec["buf_fb_ap"]
    if spec.get("v_buf")   is not None: mc["v_buf"]   = spec["v_buf"]
    if spec.get("ce_buf"): mc["ce_buf"] = True
    if spec.get("mos_buf"): mc["mos_buf"] = True
    if spec.get("bias_zener_v") is not None: mc["bias_zener_v"] = spec["bias_zener_v"]
    if spec.get("buf_comp_pf") is not None: mc["buf_comp_pf"] = spec["buf_comp_pf"]
    if spec.get("t_rail_ramp") is not None: mc["t_rail_ramp"] = spec["t_rail_ramp"]
    # JFET parameters (the sweep variable)
    mc["jfet_vp"] = jfet_vp
    mc["jfet_beta"] = I_DSS_TARGET / (jfet_vp ** 2)
    return mc


def run_short(tube_key, jfet_vp, t_end=5.0):
    """Run a short closed-loop sim with the given JFET V_p. Returns dict
    of trajectories or None on convergence failure. 5 s default matches
    the standard test_closed_loop run length needed for ILC1-1/7's
    1 W filament thermal to fully settle."""
    spec = m.TUBES[tube_key]
    mc = build_mc(spec, jfet_vp)
    work = m.WORK; work.mkdir(exist_ok=True)
    label = f"jfet_{tube_key}_vp{abs(jfet_vp*10):.0f}"
    cir = work / f"{label}.cir"
    dat = work / f"{label}.data"
    netlist = m.make_netlist(dat, v_preset=0.0, t_ramp=0.0,
                             r_int_scale=spec["r_int_scale"], mc=mc)
    # Override .tran to t_end seconds for speed
    netlist = re.sub(r"\.tran\s+\S+\s+\S+(\s+UIC)?",
                     f".tran 10u {t_end:.3f}", netlist, count=1)
    cir.write_text(netlist)
    res = subprocess.run(["ngspice", "-b", cir.name], cwd=work,
                         capture_output=True, text=True, timeout=900)
    if res.returncode != 0:
        return None
    try:
        d = np.loadtxt(dat)
        dat.unlink()
    except (OSError, ValueError):
        return None
    return dict(t=d[:,0], v_osc=d[:,1], v_ap=d[:,3], v_diff=d[:,9],
                v_int=d[:,15], T=d[:,17])


def measure(r, spec):
    """Extract steady-state metrics from the last 100 ms."""
    if r is None:
        return None
    t = r["t"]
    ss = t > t[-1] - 0.1
    if ss.sum() < 10:
        return None
    t_ss = t[ss]; dur = t_ss[-1] - t_ss[0]
    # Bridge differential = V(v_osc_drive) - V(v_ap_drive). Filament
    # voltage = V_diff * R_fil / (R_fil + R_sense). Compute RMS via
    # time-weighted integration of squared waveform.
    v_diff_ss = r["v_osc"][ss] - r["v_ap"][ss]
    v_diff_rms = float(np.sqrt(np.trapezoid(v_diff_ss**2, t_ss) / dur))
    v_fil_rms = v_diff_rms * spec["R_op"] / (spec["R_op"] + spec["r_sense"])
    v_int_ss = float(np.trapezoid(r["v_int"][ss], t_ss) / dur)
    T_ss = float(np.trapezoid(r["T"][ss], t_ss) / dur)
    return {
        "v_op_target": spec["V_op"],
        "v_fil_rms":  v_fil_rms,
        "v_op_err":   100*(v_fil_rms - spec["V_op"]) / spec["V_op"],
        "v_int":      v_int_ss,
        "T":          T_ss,
        "T_err":      T_ss - spec["T_op"],
    }


def sweep_tube(tube_key):
    spec = m.TUBES[tube_key]
    print(f"\n=== {spec['name']} (target V_op={spec['V_op']:.2f} V_RMS, T={spec['T_op']:.0f} K) ===")
    print(f"  {'V_p [V]':>8s} {'V_fil [V]':>10s} {'err [%]':>9s} "
          f"{'v_int [V]':>10s} {'T [K]':>9s} {'T_err':>8s}  status")
    for vp in VP_GRID:
        r = run_short(tube_key, vp, t_end=5.0)
        meas = measure(r, spec)
        if meas is None:
            print(f"  {vp:8.2f}                                                          *** FAILED to converge ***")
            continue
        # Flag concerns
        flags = []
        if abs(meas["v_op_err"]) > 5:
            flags.append("V_op off")
        if meas["v_int"] < 0.2 or meas["v_int"] > 1.9:
            flags.append("v_int near clamp")
        if abs(meas["T_err"]) > 50:
            flags.append("T off (still settling?)")
        status = ", ".join(flags) if flags else "OK"
        print(f"  {vp:8.2f}  {meas['v_fil_rms']:9.3f}  {meas['v_op_err']:+8.1f}  "
              f"{meas['v_int']:+9.3f}  {meas['T']:8.1f}  {meas['T_err']:+7.1f}  {status}")


def main():
    tubes = sys.argv[1:] or ["iv3", "ilc11_7"]
    for tube in tubes:
        if tube not in m.TUBES:
            print(f"Unknown tube {tube}"); continue
        sweep_tube(tube)


if __name__ == "__main__":
    main()
