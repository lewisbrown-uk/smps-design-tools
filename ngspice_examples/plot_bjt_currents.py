"""Capture driver BJT collector currents over one settled AC cycle for each
booster tube and plot them.

For each of IV-6, ILC1-1/7, ILC1-1/8 (booster=on tubes; IV-3 has no Buffer 1/2):
  - Run the closed-loop sim
  - Capture @Q_o_npn[ic], @Q_o_pnp[ic], @Q_a_npn[ic], @Q_a_pnp[ic] in steady state
  - Plot one period centred ~10 ms before the end of the run

Output: bjt_currents_<tube>.png alongside this script.
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

F0 = 1000.0           # Hz
T_PERIOD = 1.0 / F0   # 1 ms
T_WINDOW_END = 4.99   # capture window relative to start of sim
N_PERIODS = 2         # show two cycles for context


def run_capture(tube_key):
    spec = m.TUBES[tube_key]
    if not spec.get("booster"):
        return None
    mc = {k: spec[k] for k in ("r_amb", "sigma_eps_A", "c_th",
                               "r_top_ref", "r_bot_ref", "r_sense")}
    mc["booster"] = True
    if spec.get("c_ap")    is not None: mc["c_ap"]    = spec["c_ap"]
    if spec.get("buf_fb1") is not None: mc["buf_fb1"] = spec["buf_fb1"]
    if spec.get("buf_fb_ap") is not None: mc["buf_fb_ap"] = spec["buf_fb_ap"]
    if spec.get("v_buf")   is not None: mc["v_buf"]   = spec["v_buf"]

    work = m.WORK; work.mkdir(exist_ok=True)
    cir = work / f"bjt_trace_{tube_key}.cir"
    dat = work / f"bjt_trace_{tube_key}.data"
    netlist = m.make_netlist(dat, v_preset=0.0, t_ramp=0.0,
                             r_int_scale=spec["r_int_scale"], mc=mc)
    new_control = f""".save @Q_o_npn[ic] @Q_o_pnp[ic] @Q_a_npn[ic] @Q_a_pnp[ic] V(v_osc_drive) V(v_ap_drive) V(v_osc)
.control
run
let ic_o_npn = @Q_o_npn[ic]
let ic_o_pnp = @Q_o_pnp[ic]
let ic_a_npn = @Q_a_npn[ic]
let ic_a_pnp = @Q_a_pnp[ic]
let v_top    = v(v_osc_drive)
let v_bot    = v(v_ap_drive)
let v_osc_w  = v(v_osc)
wrdata {dat.as_posix()} ic_o_npn ic_o_pnp ic_a_npn ic_a_pnp v_top v_bot v_osc_w
.endcontrol"""
    netlist = re.sub(r"\.control.*?\.endcontrol", new_control, netlist, flags=re.DOTALL)
    cir.write_text(netlist)
    res = subprocess.run(["ngspice", "-b", cir.name], cwd=work,
                         capture_output=True, text=True, timeout=600)
    if res.returncode != 0:
        print(res.stderr[-2000:]); raise RuntimeError(f"ngspice failed for {tube_key}")
    d = np.loadtxt(dat)
    out = {
        "t":         d[:, 0],
        "ic_o_npn":  d[:, 1],
        "ic_o_pnp":  d[:, 3],
        "ic_a_npn":  d[:, 5],
        "ic_a_pnp":  d[:, 7],
        "v_top":     d[:, 9],
        "v_bot":     d[:, 11],
        "v_osc":     d[:, 13],
    }
    try: dat.unlink()
    except OSError: pass
    return out


def plot_tube(tube, r):
    t = r["t"]
    # Steady-state window: last N_PERIODS cycles, ending at T_WINDOW_END
    t_end = T_WINDOW_END
    t_start = t_end - N_PERIODS * T_PERIOD
    mask = (t >= t_start) & (t <= t_end)
    ts = (t[mask] - t_start) * 1000  # ms within window
    fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
    # Top: V_top, V_bot, V_osc reference for phase
    axes[0].plot(ts, r["v_top"][mask], label="v_osc_drive (V_top)", color="C0")
    axes[0].plot(ts, r["v_bot"][mask], label="v_ap_drive (V_bot)", color="C3")
    axes[0].plot(ts, r["v_osc"][mask] * 0.3, label="v_osc (Wien, 0.3x)", color="0.7", lw=0.8)
    axes[0].axhline(0, color="0.7", lw=0.5)
    axes[0].set_ylabel("V")
    axes[0].set_title(f"{m.TUBES[tube]['name']} — buffer outputs and Wien reference (steady state, 2 cycles)")
    axes[0].legend(loc="upper right", fontsize=9); axes[0].grid(True, alpha=0.4)
    # Middle: Buffer 1 BJT currents
    axes[1].plot(ts, r["ic_o_npn"][mask] * 1000, label="Q_o_npn (NPN, sources)", color="C0")
    axes[1].plot(ts, -r["ic_o_pnp"][mask] * 1000, label="Q_o_pnp (PNP, sinks; -I_C)", color="C3")
    axes[1].axhline(0, color="0.7", lw=0.5)
    axes[1].set_ylabel("I_C [mA]")
    axes[1].set_title("Buffer 1 (drives v_osc_drive)")
    axes[1].legend(loc="upper right", fontsize=9); axes[1].grid(True, alpha=0.4)
    # Bottom: Buffer 2 BJT currents
    axes[2].plot(ts, r["ic_a_npn"][mask] * 1000, label="Q_a_npn (NPN, sources)", color="C0")
    axes[2].plot(ts, -r["ic_a_pnp"][mask] * 1000, label="Q_a_pnp (PNP, sinks; -I_C)", color="C3")
    axes[2].axhline(0, color="0.7", lw=0.5)
    axes[2].set_ylabel("I_C [mA]")
    axes[2].set_xlabel("t within window [ms]")
    axes[2].set_title("Buffer 2 (drives v_ap_drive)")
    axes[2].legend(loc="upper right", fontsize=9); axes[2].grid(True, alpha=0.4)
    fig.tight_layout()
    out = HERE / f"bjt_currents_{tube}.png"
    fig.savefig(out, dpi=120); plt.close(fig)
    print(f"Wrote {out}")
    # Also print per-BJT mean and peak
    print(f"  Q_o_npn:   mean={np.mean(r['ic_o_npn'][mask])*1e3:+.2f} mA   peak={np.max(r['ic_o_npn'][mask])*1e3:+.2f} mA")
    print(f"  Q_o_pnp:  -mean={np.mean(-r['ic_o_pnp'][mask])*1e3:+.2f} mA  -peak={np.max(-r['ic_o_pnp'][mask])*1e3:+.2f} mA")
    print(f"  Q_a_npn:   mean={np.mean(r['ic_a_npn'][mask])*1e3:+.2f} mA   peak={np.max(r['ic_a_npn'][mask])*1e3:+.2f} mA")
    print(f"  Q_a_pnp:  -mean={np.mean(-r['ic_a_pnp'][mask])*1e3:+.2f} mA  -peak={np.max(-r['ic_a_pnp'][mask])*1e3:+.2f} mA")


def main():
    tubes = sys.argv[1:] or ["iv6", "ilc11_7", "ilc11_8"]
    for tube in tubes:
        r = run_capture(tube)
        if r is not None:
            print(f"\n=== {m.TUBES[tube]['name']} ===")
            plot_tube(tube, r)


if __name__ == "__main__":
    main()
