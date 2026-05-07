"""Chart the MOSFET startup pulse: V_DS, I_D, instantaneous P.

Runs the standard 1 kHz transient for ilc11_7 (MOSFET CE config) with
a tight ngspice timestep, captures the first 5 ms of v_osc_drive,
@M_o_nmos[id], @M_o_pmos[id], and the rail voltages, then plots each
MOSFET's V_DS, I_D, and P=V_DS*I_D over the first few microseconds
(where the startup peak lives) and over a wider 1 ms window for
context.
"""
from __future__ import annotations
import sys, re, subprocess
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import test_closed_loop as m


def main():
    tube = "ilc11_7"
    spec = m.TUBES[tube]
    if not (spec.get("mos_buf") and spec.get("ce_buf")):
        print(f"{tube} is not configured for MOSFET CE; aborting"); return
    mc = {k: spec[k] for k in ("r_amb", "sigma_eps_A", "c_th",
                               "r_top_ref", "r_bot_ref", "r_sense")}
    mc["booster"] = True
    if spec.get("buf_fb1") is not None: mc["buf_fb1"] = spec["buf_fb1"]
    if spec.get("buf_fb_ap") is not None: mc["buf_fb_ap"] = spec["buf_fb_ap"]
    if spec.get("v_buf") is not None: mc["v_buf"] = spec["v_buf"]
    mc["ce_buf"] = True
    mc["mos_buf"] = True
    if spec.get("bias_zener_v") is not None: mc["bias_zener_v"] = spec["bias_zener_v"]
    if spec.get("buf_comp_pf") is not None: mc["buf_comp_pf"] = spec["buf_comp_pf"]

    work = m.WORK; work.mkdir(exist_ok=True)
    cir = work / f"startup_{tube}.cir"
    dat = work / f"startup_{tube}.data"
    netlist = m.make_netlist(dat, v_preset=0.55, t_ramp=0.1,
                             r_int_scale=spec["r_int_scale"], mc=mc)
    # Override .tran for tight resolution at startup. 5 ns timestep, run for
    # 5 ms total (covers startup + a few ms of settled operation).
    netlist = re.sub(r"\.tran\s+\S+\s+\S+",
                     ".tran 5n 5m", netlist, count=1)
    new_control = """.save @M_o_nmos[id] @M_o_pmos[id] @M_a_nmos[id] @M_a_pmos[id] V(v_osc_drive) V(v_ap_drive) V(vcc_buf) V(vee_buf) V(n_buf_osc_out)
.control
run
let i_o_n   = @M_o_nmos[id]
let i_o_p   = @M_o_pmos[id]
let i_a_n   = @M_a_nmos[id]
let i_a_p   = @M_a_pmos[id]
let v_o_drv = v(v_osc_drive)
let v_a_drv = v(v_ap_drive)
let v_cc    = v(vcc_buf)
let v_ee    = v(vee_buf)
let v_op    = v(n_buf_osc_out)
wrdata """ + str(dat.as_posix()) + """ i_o_n i_o_p i_a_n i_a_p v_o_drv v_a_drv v_cc v_ee v_op
.endcontrol"""
    netlist = re.sub(r"\.control.*?\.endcontrol", new_control,
                     netlist, flags=re.DOTALL)
    cir.write_text(netlist)
    print("Running startup capture (5 ms with 5 ns timestep, may take a few minutes)...")
    res = subprocess.run(["ngspice", "-b", cir.name], cwd=work,
                         capture_output=True, text=True, timeout=1200)
    if res.returncode != 0:
        print(res.stderr[-1500:]); raise SystemExit(1)
    d = np.loadtxt(dat)
    t       = d[:, 0]
    i_o_n   = d[:, 1]
    i_o_p   = d[:, 3]
    i_a_n   = d[:, 5]
    i_a_p   = d[:, 7]
    v_o_drv = d[:, 9]
    v_a_drv = d[:, 11]
    v_cc    = d[:, 13]
    v_ee    = d[:, 15]
    v_op    = d[:, 17]

    # PMOS top: source=vcc_buf, drain=v_osc_drive.
    # V_DS = drain - source = v_osc_drive - v_cc (negative when conducting)
    # P = V_DS * I_D (both negative -> positive when conducting)
    v_ds_o_p = v_o_drv - v_cc
    p_o_p = v_ds_o_p * i_o_p
    # NMOS bottom: source=vee_buf, drain=v_osc_drive.
    # V_DS = drain - source = v_osc_drive - v_ee (positive when conducting)
    v_ds_o_n = v_o_drv - v_ee
    p_o_n = v_ds_o_n * i_o_n
    # Same for buffer 2
    v_ds_a_p = v_a_drv - v_cc
    p_a_p = v_ds_a_p * i_a_p
    v_ds_a_n = v_a_drv - v_ee
    p_a_n = v_ds_a_n * i_a_n

    print(f"\nTotal samples: {len(t)}, t_end = {t[-1]*1e3:.3f} ms")
    print(f"Peak instantaneous power per MOSFET in first 100 us:")
    early = t < 100e-6
    for name, p in [("M_o_pmos", p_o_p), ("M_o_nmos", p_o_n),
                    ("M_a_pmos", p_a_p), ("M_a_nmos", p_a_n)]:
        idx = int(np.argmax(p[early]))
        t_pk = t[early][idx]
        print(f"  {name}: P_peak = {p[early][idx]:.2f} W at t = {t_pk*1e6:.2f} us  "
              f"(V_DS={[v_ds_o_p, v_ds_o_n, v_ds_a_p, v_ds_a_n][['M_o_pmos','M_o_nmos','M_a_pmos','M_a_nmos'].index(name)][early][idx]:+.2f} V, "
              f"I_D={[i_o_p, i_o_n, i_a_p, i_a_n][['M_o_pmos','M_o_nmos','M_a_pmos','M_a_nmos'].index(name)][early][idx]*1e3:+.0f} mA)")

    # Plot: 3 columns (V, I, P), 2 rows (Buffer 1 NMOS+PMOS, Buffer 2 NMOS+PMOS)
    # First panel: zoomed to first ~20 us (where peak lives)
    # Second panel: 0 to 1 ms (settling)
    fig, axes = plt.subplots(3, 2, figsize=(14, 9), sharex='col')
    t_us = t * 1e6
    t_ms = t * 1e3

    # Column 1: zoom on first 20 us
    zoom = t < 30e-6
    ax_v0, ax_i0, ax_p0 = axes[0, 0], axes[1, 0], axes[2, 0]
    ax_v0.plot(t_us[zoom], v_ds_o_p[zoom], label="V_DS PMOS_o", color="C0")
    ax_v0.plot(t_us[zoom], v_ds_o_n[zoom], label="V_DS NMOS_o", color="C1")
    ax_v0.set_ylabel("V_DS [V]")
    ax_v0.legend(loc="upper right", fontsize=8)
    ax_v0.set_title("Buffer 1 startup (first 30 us)")
    ax_v0.grid(True, alpha=0.4)

    ax_i0.plot(t_us[zoom], i_o_p[zoom]*1e3, label="I_D PMOS_o", color="C0")
    ax_i0.plot(t_us[zoom], i_o_n[zoom]*1e3, label="I_D NMOS_o", color="C1")
    ax_i0.set_ylabel("I_D [mA]")
    ax_i0.legend(loc="upper right", fontsize=8)
    ax_i0.grid(True, alpha=0.4)

    ax_p0.plot(t_us[zoom], p_o_p[zoom], label="P PMOS_o", color="C0")
    ax_p0.plot(t_us[zoom], p_o_n[zoom], label="P NMOS_o", color="C1")
    ax_p0.set_ylabel("P [W]")
    ax_p0.set_xlabel("t [us]")
    ax_p0.legend(loc="upper right", fontsize=8)
    ax_p0.grid(True, alpha=0.4)

    # Column 2: out to 1 ms for settling context
    settle = t < 1e-3
    ax_v1, ax_i1, ax_p1 = axes[0, 1], axes[1, 1], axes[2, 1]
    ax_v1.plot(t_ms[settle], v_ds_o_p[settle], label="V_DS PMOS_o", color="C0")
    ax_v1.plot(t_ms[settle], v_ds_o_n[settle], label="V_DS NMOS_o", color="C1")
    ax_v1.set_ylabel("V_DS [V]")
    ax_v1.legend(loc="upper right", fontsize=8)
    ax_v1.set_title("Buffer 1 settling (first 1 ms)")
    ax_v1.grid(True, alpha=0.4)

    ax_i1.plot(t_ms[settle], i_o_p[settle]*1e3, label="I_D PMOS_o", color="C0")
    ax_i1.plot(t_ms[settle], i_o_n[settle]*1e3, label="I_D NMOS_o", color="C1")
    ax_i1.set_ylabel("I_D [mA]")
    ax_i1.legend(loc="upper right", fontsize=8)
    ax_i1.grid(True, alpha=0.4)

    ax_p1.plot(t_ms[settle], p_o_p[settle], label="P PMOS_o", color="C0")
    ax_p1.plot(t_ms[settle], p_o_n[settle], label="P NMOS_o", color="C1")
    ax_p1.set_ylabel("P [W]")
    ax_p1.set_xlabel("t [ms]")
    ax_p1.legend(loc="upper right", fontsize=8)
    ax_p1.grid(True, alpha=0.4)

    fig.suptitle(f"{spec['name']} MOSFET startup pulse  "
                 f"(v_buf={spec.get('v_buf'):.1f} V, "
                 f"V_Z={spec.get('bias_zener_v', 0):.1f} V, "
                 f"C_comp={spec.get('buf_comp_pf', 0):.0f} pF)")
    fig.tight_layout()
    out = HERE / f"startup_pulse_{tube}.png"
    fig.savefig(out, dpi=130); plt.close(fig)
    print(f"\nWrote {out}")
    try: dat.unlink()
    except OSError: pass


if __name__ == "__main__":
    main()
