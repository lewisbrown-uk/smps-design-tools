"""Capture vcc_buf, n_env_lpf, and v_osc_drive over time to verify the
rail servo's behavior."""
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
    cir = work / f"servo_{tube}.cir"
    dat = work / f"servo_{tube}.data"
    netlist = m.make_netlist(dat, v_preset=0.0, t_ramp=0.0,
                             r_int_scale=spec["r_int_scale"], mc=mc)
    new_control = f""".save V(vcc_buf) V(vee_buf) V(n_env_lpf) V(n_envin) V(v_osc_drive) V(v_ap_drive) V(T_node)
.control
run
let v_cc   = v(vcc_buf)
let v_ee   = v(vee_buf)
let v_pk   = v(n_env_lpf)
let v_env  = v(n_envin)
let v_o    = v(v_osc_drive)
let v_a    = v(v_ap_drive)
let t_n    = v(T_node)
wrdata {dat.as_posix()} v_cc v_ee v_pk v_env v_o v_a t_n
.endcontrol"""
    netlist = re.sub(r"\.control.*?\.endcontrol", new_control, netlist, flags=re.DOTALL)
    cir.write_text(netlist)
    res = subprocess.run(["ngspice", "-b", cir.name], cwd=work,
                         capture_output=True, text=True, timeout=900)
    if res.returncode != 0:
        print(res.stderr[-2000:]); raise SystemExit(1)
    d = np.loadtxt(dat)
    t = d[:, 0]
    v_cc = d[:, 1]
    v_ee = d[:, 3]
    v_pk = d[:, 5]
    v_env = d[:, 7]
    v_o = d[:, 9]
    v_a = d[:, 11]
    T_n = d[:, 13]
    print(f"=== {spec['name']} rail servo trace ===\n")
    print(f"  Total samples: {len(t)}, t_end = {t[-1]:.3f}s")
    print(f"\n  Snapshot at various times:")
    print(f"  {'t [s]':>8s}  {'vcc_buf':>9s}  {'n_env_lpf':>9s}  {'n_envin':>9s}  "
          f"{'|v_o|':>8s}  {'|v_a|':>8s}  {'T':>8s}")
    for ts in [0.0, 0.005, 0.020, 0.050, 0.1, 0.2, 0.5, 1.0, 2.0, 4.99]:
        i = int(np.searchsorted(t, ts))
        if i >= len(t): continue
        print(f"  {t[i]:8.3f}  {v_cc[i]:+9.3f}  {v_pk[i]:+9.3f}  {v_env[i]:+9.3f}  "
              f"{abs(v_o[i]):8.3f}  {abs(v_a[i]):8.3f}  {T_n[i]:8.1f}")
    try: dat.unlink()
    except OSError: pass


if __name__ == "__main__":
    main()
