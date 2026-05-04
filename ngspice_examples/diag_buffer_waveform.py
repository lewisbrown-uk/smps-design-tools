"""Capture v_osc_drive and v_ap_drive waveforms during steady state to
look for asymmetry that explains the BJT hotspot pattern.

Outputs a few statistics on the buffer outputs over the last 100 ms:
    - mean (DC component)
    - max, min
    - asymmetry of swing relative to ground
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


def run_capture(tube_key: str):
    spec = m.TUBES[tube_key]
    use_booster = bool(spec.get("booster"))
    if not use_booster:
        return None
    mc = {k: spec[k] for k in ("r_amb", "sigma_eps_A", "c_th",
                               "r_top_ref", "r_bot_ref", "r_sense")}
    mc["booster"] = True
    if spec.get("c_ap") is not None: mc["c_ap"] = spec["c_ap"]
    if spec.get("buf_fb1") is not None: mc["buf_fb1"] = spec["buf_fb1"]
    if spec.get("buf_fb_ap") is not None: mc["buf_fb_ap"] = spec["buf_fb_ap"]

    work = m.WORK; work.mkdir(exist_ok=True)
    cir = work / f"buf_wave_{tube_key}.cir"
    dat = work / f"buf_wave_{tube_key}.data"
    netlist = m.make_netlist(dat, v_preset=0.0, t_ramp=0.0,
                             r_int_scale=spec["r_int_scale"], mc=mc)
    sigs = ["v(v_osc)", "v(v_drv_atten)", "v(v_ap)",
            "v(v_osc_drive)", "v(v_ap_drive)",
            "v(n_buf_osc_out)", "v(n_buf_ap_out)",
            "v(n_ap_plus)", "v(v_int_out)", "v(v_ctl)"]
    new_wrdata = "wrdata " + dat.as_posix() + " " + " ".join(sigs)
    netlist = "\n".join(new_wrdata if line.startswith("wrdata ") else line
                        for line in netlist.splitlines())
    cir.write_text(netlist)
    res = subprocess.run(["ngspice", "-b", cir.name], cwd=work,
                         capture_output=True, text=True, timeout=300)
    if res.returncode != 0:
        print(res.stderr[-2000:])
        raise RuntimeError(f"ngspice failed for {tube_key}")
    d = np.loadtxt(dat)
    t = d[:, 0]
    out = {"t": t}
    for i, name in enumerate(sigs):
        out[name] = d[:, 2*i + 1]
    try: dat.unlink()
    except OSError: pass
    return out


def report(tube, res):
    print(f"\n=== {m.TUBES[tube]['name']} (last 100 ms steady-state) ===")
    t = res["t"]
    ss = t > t[-1] - 0.1
    for name in ["v(v_osc)", "v(v_drv_atten)", "v(v_ap)",
                 "v(v_osc_drive)", "v(v_ap_drive)",
                 "v(n_buf_osc_out)", "v(n_buf_ap_out)",
                 "v(n_ap_plus)", "v(v_int_out)", "v(v_ctl)"]:
        s = res[name][ss]
        print(f"  {name:<22s} mean={np.mean(s):+.4f}  max={np.max(s):+.4f}  min={np.min(s):+.4f}  pp={(np.max(s)-np.min(s)):.4f}")


def main():
    tubes = sys.argv[1:] or ["ilc11_8"]
    for tube in tubes:
        res = run_capture(tube)
        if res is not None:
            report(tube, res)


if __name__ == "__main__":
    main()
