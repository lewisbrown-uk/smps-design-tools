"""Numerical analysis of the Buffer-1 signal chain for ILC1-1/7. Captures
v_drv_atten, n_buf_osc_out, v_osc_drive, q_o_bn, q_o_bp, vcc_buf, vee_buf
and reports:
  - Per-signal statistics (DC mean, peak excursions, time of peak)
  - Computed V_BE NPN, V_EB PNP with extreme values and the time index
    at which they occur, plus surrounding data for context
  - Whether the op-amp output reaches the supply rail
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
    cir = work / f"buf_data_{tube}.cir"
    dat = work / f"buf_data_{tube}.data"
    netlist = m.make_netlist(dat, v_preset=0.0, t_ramp=0.0,
                             r_int_scale=spec["r_int_scale"], mc=mc)
    new_control = f""".save V(v_drv_atten) V(n_buf_osc_out) V(v_osc_drive) V(q_o_bn) V(q_o_bp) V(vcc_buf) V(vee_buf)
.control
run
let v_in   = v(v_drv_atten)
let v_op   = v(n_buf_osc_out)
let v_out  = v(v_osc_drive)
let v_qbn  = v(q_o_bn)
let v_qbp  = v(q_o_bp)
let v_pos  = v(vcc_buf)
let v_neg  = v(vee_buf)
wrdata {dat.as_posix()} v_in v_op v_out v_qbn v_qbp v_pos v_neg
.endcontrol"""
    netlist = re.sub(r"\.control.*?\.endcontrol", new_control, netlist, flags=re.DOTALL)
    cir.write_text(netlist)
    res = subprocess.run(["ngspice", "-b", cir.name], cwd=work,
                         capture_output=True, text=True, timeout=600)
    if res.returncode != 0:
        print(res.stderr[-2000:]); raise SystemExit(1)
    d = np.loadtxt(dat)
    t      = d[:, 0]
    v_in   = d[:, 1]
    v_op   = d[:, 3]
    v_out  = d[:, 5]
    v_qbn  = d[:, 7]
    v_qbp  = d[:, 9]
    v_pos  = d[:, 11]
    v_neg  = d[:, 13]
    # Steady-state window: last 5 ms
    mask = t > t[-1] - 0.005
    ts   = t[mask]
    vin  = v_in[mask]
    vop  = v_op[mask]
    vout = v_out[mask]
    qbn  = v_qbn[mask]
    qbp  = v_qbp[mask]
    vp   = v_pos[mask]
    vn   = v_neg[mask]
    vbe_npn = qbn - vout    # NPN V_BE
    veb_pnp = vout - qbp    # PNP V_EB
    print(f"=== {spec['name']} (last 5 ms steady-state, n={len(ts)} samples) ===\n")
    print(f"Supply rails: v_buf = {np.mean(vp):+.3f}V, -v_buf = {np.mean(vn):+.3f}V\n")
    for label, x in [
        ("v_drv_atten",       vin),
        ("n_buf_osc_out",     vop),
        ("v_osc_drive",       vout),
        ("q_o_bn (NPN base)", qbn),
        ("q_o_bp (PNP base)", qbp),
        ("V_BE NPN  (q_o_bn - v_osc_drive)", vbe_npn),
        ("V_EB PNP  (v_osc_drive - q_o_bp)", veb_pnp),
    ]:
        i_max = int(np.argmax(x))
        i_min = int(np.argmin(x))
        print(f"  {label:35s}  mean={np.mean(x):+.4f}  max={np.max(x):+.4f} @ t-rel={ts[i_max]-ts[0]:.5f}s   min={np.min(x):+.4f} @ t-rel={ts[i_min]-ts[0]:.5f}s")

    # Op-amp rail saturation: how often does v_op come within 0.1V of either rail?
    v_pos_mean = np.mean(vp)
    v_neg_mean = np.mean(vn)
    near_pos = np.mean(vop > v_pos_mean - 0.1)
    near_neg = np.mean(vop < v_neg_mean + 0.1)
    print(f"\n  Op-amp output near +v_buf rail (within 0.1V): {near_pos*100:.2f}% of cycle")
    print(f"  Op-amp output near -v_buf rail (within 0.1V): {near_neg*100:.2f}% of cycle")

    # V_BE NPN reverse bias episodes
    rev_npn = np.mean(vbe_npn < 0)
    rev_pnp = np.mean(veb_pnp < 0)
    print(f"\n  V_BE NPN reverse-biased (V_BE < 0): {rev_npn*100:.2f}% of cycle")
    print(f"  V_EB PNP reverse-biased (V_EB < 0): {rev_pnp*100:.2f}% of cycle")
    if rev_npn > 0:
        i = int(np.argmin(vbe_npn))
        print(f"\n  Most negative V_BE NPN: {np.min(vbe_npn):+.4f} V at t-rel={ts[i]-ts[0]:.5f}s")
        # Show context: 10 samples before and after
        lo = max(0, i - 10); hi = min(len(ts), i + 10)
        print(f"    ctx idx t-rel(ms)  v_in    v_op    v_out   q_o_bn  V_BE_NPN")
        for j in range(lo, hi):
            mark = " <--" if j == i else ""
            print(f"    {j:5d}  {(ts[j]-ts[0])*1e3:8.4f}  {vin[j]:+.3f}  {vop[j]:+.3f}  {vout[j]:+.3f}  {qbn[j]:+.3f}  {vbe_npn[j]:+.4f}{mark}")
    try: dat.unlink()
    except OSError: pass


if __name__ == "__main__":
    main()
