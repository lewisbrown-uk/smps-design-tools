"""Capture Q_o_npn and Q_o_pnp collector currents over a few cycles in
steady state to localise the asymmetric conduction behaviour.

Reports per-BJT for each tube:
  - Mean of |I_C| (DC component magnitude)
  - Peak of |I_C| during conduction
  - Fraction of cycle each BJT conducts (|I_C| > 1 mA)
  - Mean v_osc_drive WHEN each BJT is conducting
"""
from __future__ import annotations
import sys
import re
import subprocess
from pathlib import Path
import numpy as np

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import test_closed_loop as m


def run_capture(tube_key):
    spec = m.TUBES[tube_key]
    if not spec.get("booster"): return None
    mc = {k: spec[k] for k in ("r_amb", "sigma_eps_A", "c_th",
                               "r_top_ref", "r_bot_ref", "r_sense")}
    mc["booster"] = True
    if spec.get("c_ap") is not None: mc["c_ap"] = spec["c_ap"]
    if spec.get("buf_fb1") is not None: mc["buf_fb1"] = spec["buf_fb1"]
    if spec.get("buf_fb_ap") is not None: mc["buf_fb_ap"] = spec["buf_fb_ap"]

    work = m.WORK; work.mkdir(exist_ok=True)
    cir = work / f"bjt_ic_{tube_key}.cir"
    dat = work / f"bjt_ic_{tube_key}.data"
    netlist = m.make_netlist(dat, v_preset=0.0, t_ramp=0.0,
                             r_int_scale=spec["r_int_scale"], mc=mc)
    new_control = f""".save @Q_o_npn[ic] @Q_o_pnp[ic] V(v_osc_drive) V(v_ap_drive) V(n_buf_osc_out)
.control
run
let ic_q_o_npn = @Q_o_npn[ic]
let ic_q_o_pnp = @Q_o_pnp[ic]
let v_osc_d = v(v_osc_drive)
let v_ap_d = v(v_ap_drive)
let n_buf_o = v(n_buf_osc_out)
wrdata {dat.as_posix()} ic_q_o_npn ic_q_o_pnp v_osc_d v_ap_d n_buf_o
.endcontrol"""
    netlist = re.sub(r"\.control.*?\.endcontrol", new_control, netlist, flags=re.DOTALL)
    cir.write_text(netlist)
    res = subprocess.run(["ngspice", "-b", cir.name], cwd=work,
                         capture_output=True, text=True, timeout=600)
    if res.returncode != 0:
        print(res.stderr[-2000:]); raise RuntimeError(f"ngspice failed for {tube_key}")
    d = np.loadtxt(dat)
    t = d[:, 0]
    out = {"t": t, "ic_npn": d[:, 1], "ic_pnp": d[:, 3],
           "v_osc_d": d[:, 5], "v_ap_d": d[:, 7], "n_buf_o": d[:, 9]}
    try: dat.unlink()
    except OSError: pass
    return out


def report(tube, r):
    t = r["t"]
    # Steady-state, last 10 ms (10 cycles at 1 kHz)
    ss = (t > t[-1] - 0.010) & (t < t[-1] - 0.001)
    ic_npn = r["ic_npn"][ss]
    ic_pnp = r["ic_pnp"][ss]
    v_osc_d = r["v_osc_d"][ss]
    n_buf_o = r["n_buf_o"][ss]
    # PNP convention: ic is negative when conducting (current out of collector)
    pnp_cond_current = -ic_pnp  # positive when PNP sinks current
    npn_cond_current = ic_npn   # positive when NPN sources current
    print(f"\n=== {m.TUBES[tube]['name']} ===")
    print(f"  Q_o_npn ic:  mean={np.mean(npn_cond_current)*1e3:+8.3f}mA  "
          f"max={np.max(npn_cond_current)*1e3:+8.3f}mA  min={np.min(npn_cond_current)*1e3:+8.3f}mA")
    print(f"  Q_o_pnp -ic: mean={np.mean(pnp_cond_current)*1e3:+8.3f}mA  "
          f"max={np.max(pnp_cond_current)*1e3:+8.3f}mA  min={np.min(pnp_cond_current)*1e3:+8.3f}mA")
    # Conduction fraction (ic > 1 mA)
    npn_frac = np.mean(npn_cond_current > 1e-3)
    pnp_frac = np.mean(pnp_cond_current > 1e-3)
    print(f"  NPN conducts (>1mA): {npn_frac*100:.1f}% of cycle")
    print(f"  PNP conducts (>1mA): {pnp_frac*100:.1f}% of cycle")
    # Mean v_osc_drive during NPN vs PNP conduction
    if npn_frac > 0.01:
        print(f"  <v_osc_drive> | NPN conducting = {np.mean(v_osc_d[npn_cond_current > 1e-3]):+.3f} V")
    if pnp_frac > 0.01:
        print(f"  <v_osc_drive> | PNP conducting = {np.mean(v_osc_d[pnp_cond_current > 1e-3]):+.3f} V")
    # Op-amp output stats
    print(f"  n_buf_osc_out: mean={np.mean(n_buf_o):+.3f}V  pp={np.max(n_buf_o)-np.min(n_buf_o):.3f}V")


def main():
    tubes = sys.argv[1:] or ["iv6", "ilc11_7", "ilc11_8"]
    for tube in tubes:
        r = run_capture(tube)
        if r is not None:
            report(tube, r)


if __name__ == "__main__":
    main()
