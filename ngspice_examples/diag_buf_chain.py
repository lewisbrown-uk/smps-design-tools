"""Capture the entire Buffer 1 signal path -- v_drv_atten (input),
n_buf_osc_out (op-amp output), v_osc_drive (BJT-pair output) -- over one
settled cycle, plus q_o_bn / q_o_bp (BJT base voltages) so we can see
exactly where the sine becomes a trapezoid.
"""
from __future__ import annotations
import sys
import re
import subprocess
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import test_closed_loop as m

F0 = 1000.0
T_PERIOD = 1.0 / F0
T_END = 4.99
N_PERIODS = 2


def run_capture(tube_key):
    spec = m.TUBES[tube_key]
    if not spec.get("booster"): return None
    mc = {k: spec[k] for k in ("r_amb", "sigma_eps_A", "c_th",
                               "r_top_ref", "r_bot_ref", "r_sense")}
    mc["booster"] = True
    if spec.get("c_ap")    is not None: mc["c_ap"]    = spec["c_ap"]
    if spec.get("buf_fb1") is not None: mc["buf_fb1"] = spec["buf_fb1"]
    if spec.get("buf_fb_ap") is not None: mc["buf_fb_ap"] = spec["buf_fb_ap"]
    if spec.get("v_buf")   is not None: mc["v_buf"]   = spec["v_buf"]
    if spec.get("ce_buf"): mc["ce_buf"] = True

    work = m.WORK; work.mkdir(exist_ok=True)
    cir = work / f"buf_chain_{tube_key}.cir"
    dat = work / f"buf_chain_{tube_key}.data"
    netlist = m.make_netlist(dat, v_preset=0.0, t_ramp=0.0,
                             r_int_scale=spec["r_int_scale"], mc=mc)
    new_control = f""".save @Q_o_npn[ic] @Q_o_pnp[ic] V(v_drv_atten) V(n_buf_osc_out) V(v_osc_drive) V(q_o_bn) V(q_o_bp) V(vcc_buf) V(vee_buf)
.control
run
let v_in    = v(v_drv_atten)
let v_op    = v(n_buf_osc_out)
let v_out   = v(v_osc_drive)
let v_qbn   = v(q_o_bn)
let v_qbp   = v(q_o_bp)
let v_rail_p = v(vcc_buf)
let v_rail_n = v(vee_buf)
let i_npn = @Q_o_npn[ic]
let i_pnp = @Q_o_pnp[ic]
wrdata {dat.as_posix()} v_in v_op v_out v_qbn v_qbp v_rail_p v_rail_n i_npn i_pnp
.endcontrol"""
    netlist = re.sub(r"\.control.*?\.endcontrol", new_control, netlist, flags=re.DOTALL)
    cir.write_text(netlist)
    res = subprocess.run(["ngspice", "-b", cir.name], cwd=work,
                         capture_output=True, text=True, timeout=600)
    if res.returncode != 0:
        print(res.stderr[-2000:]); raise RuntimeError(f"ngspice failed for {tube_key}")
    d = np.loadtxt(dat)
    out = {"t":     d[:, 0],
           "v_in":  d[:, 1],
           "v_op":  d[:, 3],
           "v_out": d[:, 5],
           "v_qbn": d[:, 7],
           "v_qbp": d[:, 9],
           "v_rail_p": d[:, 11],
           "v_rail_n": d[:, 13],
           "i_npn": d[:, 15],
           "i_pnp": d[:, 17]}
    try: dat.unlink()
    except OSError: pass
    return out


def plot_tube(tube, r):
    t = r["t"]
    t_start = T_END - N_PERIODS * T_PERIOD
    mask = (t >= t_start) & (t <= T_END)
    ts = (t[mask] - t_start) * 1000
    # Time-weighted mean for rail labels -- np.mean is biased on
    # ngspice variable-timestep data.
    tw = t[mask]; dur_w = tw[-1] - tw[0]
    rail_p = float(np.trapezoid(r["v_rail_p"][mask], tw) / dur_w)
    rail_n = float(np.trapezoid(r["v_rail_n"][mask], tw) / dur_w)
    spec = m.TUBES[tube]
    fig, axes = plt.subplots(3, 1, figsize=(11, 9), sharex=True)
    # Top: v_in (scaled), v_op, v_out
    k_buf_pos = 1 + spec.get("buf_fb1", 6.2e3) / 1e3
    axes[0].plot(ts, r["v_in"][mask] * k_buf_pos, lw=0.8, label=f"v_drv_atten × k_buf={k_buf_pos:.2g} (commanded)", color="0.6")
    axes[0].plot(ts, r["v_op"][mask], label="n_buf_osc_out (op-amp output)", color="C2")
    axes[0].plot(ts, r["v_out"][mask], label="v_osc_drive (buffer output)", color="C0")
    axes[0].axhline(rail_p, color="C3", ls=":", lw=0.7, label=f"+v_buf = {rail_p:.2f}V")
    axes[0].axhline(rail_n, color="C3", ls=":", lw=0.7, label=f"-v_buf = {rail_n:.2f}V")
    axes[0].axhline(0, color="0.7", lw=0.4)
    axes[0].set_ylabel("V")
    axes[0].set_title(f"{spec['name']} — Buffer 1 signal chain (last 2 cycles, steady state)")
    axes[0].legend(loc="upper right", fontsize=8); axes[0].grid(True, alpha=0.4)
    # Middle: BJT base voltages relative to v_out (V_BE / V_EB)
    v_be_npn = r["v_qbn"][mask] - r["v_out"][mask]
    v_eb_pnp = r["v_out"][mask] - r["v_qbp"][mask]
    axes[1].plot(ts, v_be_npn, label="V_BE NPN = V(q_o_bn) − V(v_osc_drive)", color="C0")
    axes[1].plot(ts, v_eb_pnp, label="V_EB PNP = V(v_osc_drive) − V(q_o_bp)", color="C3")
    axes[1].axhline(0.6, color="0.5", ls=":", lw=0.5, label="≈ V_BE_on")
    axes[1].axhline(0, color="0.7", lw=0.4)
    axes[1].set_ylabel("V")
    axes[1].set_title("BJT base-emitter voltages (each BJT conducts when its V_BE > ~0.6V)")
    axes[1].legend(loc="upper right", fontsize=8); axes[1].grid(True, alpha=0.4)
    # Bottom: BJT collector currents
    axes[2].plot(ts, r["i_npn"][mask] * 1000, label="I_C NPN", color="C0")
    axes[2].plot(ts, -r["i_pnp"][mask] * 1000, label="-I_C PNP (sinks)", color="C3")
    axes[2].axhline(0, color="0.7", lw=0.4)
    axes[2].set_ylabel("I_C [mA]")
    axes[2].set_xlabel("t within window [ms]")
    axes[2].set_title("BJT collector currents")
    axes[2].legend(loc="upper right", fontsize=8); axes[2].grid(True, alpha=0.4)
    fig.tight_layout()
    out = HERE / f"buf_chain_{tube}.png"
    fig.savefig(out, dpi=120); plt.close(fig)
    print(f"Wrote {out}")


def main():
    tubes = sys.argv[1:] or ["iv6", "ilc11_7", "ilc11_8"]
    for tube in tubes:
        r = run_capture(tube)
        if r is not None:
            plot_tube(tube, r)


if __name__ == "__main__":
    main()
