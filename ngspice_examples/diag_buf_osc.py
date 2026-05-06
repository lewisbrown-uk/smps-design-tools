"""Inspect BJT collector current and v_osc_drive waveforms in xfmr config
to diagnose the 38 W ss_mean dissipation reported by check_power_hf.
Looking for buffer parasitic oscillation through transformer leakage.
"""
from __future__ import annotations
import sys, re, subprocess
from pathlib import Path
import numpy as np

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import test_closed_loop as m


def main():
    tube = "ilc11_7"
    spec = m.TUBES[tube]
    mc = {k: spec[k] for k in ("r_amb", "sigma_eps_A", "c_th",
                               "r_top_ref", "r_bot_ref", "r_sense")}
    mc["booster"] = True
    if spec.get("buf_fb1") is not None: mc["buf_fb1"] = spec["buf_fb1"]
    if spec.get("buf_fb_ap") is not None: mc["buf_fb_ap"] = spec["buf_fb_ap"]
    if spec.get("v_buf") is not None: mc["v_buf"] = spec["v_buf"]
    if spec.get("tank_l") is not None: mc["tank_l"] = spec["tank_l"]
    if spec.get("tank_c") is not None: mc["tank_c"] = spec["tank_c"]
    if spec.get("bias_diode"): mc["bias_diode"] = spec["bias_diode"]
    if spec.get("xfmr_n") is not None: mc["xfmr_n"] = spec["xfmr_n"]
    if spec.get("xfmr_lpri") is not None: mc["xfmr_lpri"] = spec["xfmr_lpri"]
    mc["hf_mode"] = True
    mc["R_op"] = spec["R_op"]
    mc["T_op"] = spec["T_op"]
    mc["v_int_settled"] = 2.10

    work = m.WORK
    cir = work / f"bufosc_{tube}.cir"
    dat = work / f"bufosc_{tube}.data"
    netlist = m.make_netlist(dat, v_preset=0.0, t_ramp=0.0,
                             r_int_scale=spec["r_int_scale"], mc=mc)
    netlist = re.sub(r"\.tran\s+\S+\s+\S+(\s+UIC)?",
                     ".tran 20n 0.100 UIC", netlist)
    new_control = """.save @Q_o_npn[ic] @Q_o_pnp[ic] @Q_a_npn[ic] @Q_a_pnp[ic] V(v_osc_drive) V(v_ap_drive) V(v_osc_load) V(v_ap_load) V(n_buf_osc_out) V(n_buf_ap_out)
.control
run
let i_o_npn = @Q_o_npn[ic]
let i_o_pnp = @Q_o_pnp[ic]
let i_a_npn = @Q_a_npn[ic]
let i_a_pnp = @Q_a_pnp[ic]
let v_o_pri = v(v_osc_drive)
let v_a_pri = v(v_ap_drive)
let v_o_sec = v(v_osc_load)
let v_a_sec = v(v_ap_load)
let v_o_op  = v(n_buf_osc_out)
let v_a_op  = v(n_buf_ap_out)
wrdata """ + str(dat.as_posix()) + """ i_o_npn i_o_pnp i_a_npn i_a_pnp v_o_pri v_a_pri v_o_sec v_a_sec v_o_op v_a_op
.endcontrol"""
    netlist = re.sub(r"\.control.*?\.endcontrol", new_control,
                     netlist, flags=re.DOTALL)
    cir.write_text(netlist)
    res = subprocess.run(["ngspice", "-b", cir.name], cwd=work,
                         capture_output=True, text=True, timeout=900)
    if res.returncode != 0:
        print(res.stderr[-2000:]); raise SystemExit(1)
    d = np.loadtxt(dat)
    t = d[:, 0]
    cols = ["i_o_npn", "i_o_pnp", "i_a_npn", "i_a_pnp",
            "v_o_pri", "v_a_pri", "v_o_sec", "v_a_sec",
            "v_o_op", "v_a_op"]
    arr = {c: d[:, 2*i + 1] for i, c in enumerate(cols)}
    print(f"total samples: {len(t)}, t_end = {t[-1]*1e3:.2f} ms")

    # Steady-state window: last 200 us (20 cycles at 100 kHz)
    ss = t > t[-1] - 200e-6
    t_ss = t[ss]
    print(f"\nSteady-state window: {ss.sum()} samples in last 200 us")
    print(f"\n  Currents (mA):")
    for c in ["i_o_npn", "i_o_pnp", "i_a_npn", "i_a_pnp"]:
        x = arr[c][ss]
        print(f"  {c:>10s}  min={x.min()*1e3:+9.2f}  max={x.max()*1e3:+9.2f}  "
              f"rms={np.sqrt(np.mean(x**2))*1e3:8.2f}  abs_mean={np.mean(np.abs(x))*1e3:7.2f}")
    print(f"\n  Voltages (V):")
    for c in ["v_o_pri", "v_a_pri", "v_o_sec", "v_a_sec", "v_o_op", "v_a_op"]:
        x = arr[c][ss]
        print(f"  {c:>10s}  min={x.min():+8.3f}  max={x.max():+8.3f}  "
              f"rms={np.sqrt(np.mean(x**2)):7.3f}  pp={x.max()-x.min():7.3f}")

    # Look for HF oscillation: zero-crossings on op-amp output
    # If parasitic oscillation, n_buf_osc_out will have many more zero
    # crossings than 100 kHz × duration would predict.
    f0 = 100e3
    expected_xings = 2 * f0 * (t_ss[-1] - t_ss[0])
    for c in ["v_o_op", "v_a_op", "i_o_npn", "i_a_pnp"]:
        x = arr[c][ss] - np.mean(arr[c][ss])
        xings = int(np.sum((x[:-1] * x[1:]) < 0))
        print(f"  zero-crossings({c}) = {xings}  (expected ~{int(expected_xings)} at 100 kHz)")

    # Sample one cycle from the middle of steady state -- look at the
    # detailed waveform shape to spot oscillation directly.
    t_mid = (t[-1] - 100e-6)
    sl = (t > t_mid - 5e-6) & (t < t_mid + 25e-6)
    tt = (t[sl] - t_mid) * 1e6   # us relative
    print(f"\n  Detailed waveform around t={t_mid*1e3:.2f} ms ({sl.sum()} samples in 30 us window):")
    print(f"  {'t [us]':>8s}  {'v_o_pri':>9s}  {'v_o_op':>9s}  {'i_o_npn':>10s}  {'i_o_pnp':>10s}")
    # Subsample for printing
    step = max(1, sl.sum() // 30)
    for i in range(0, sl.sum(), step):
        idx = np.where(sl)[0][i]
        print(f"  {tt[i]:8.3f}  {arr['v_o_pri'][idx]:+9.3f}  "
              f"{arr['v_o_op'][idx]:+9.3f}  {arr['i_o_npn'][idx]*1e3:+10.2f}  "
              f"{arr['i_o_pnp'][idx]*1e3:+10.2f}")
    try: dat.unlink()
    except OSError: pass


if __name__ == "__main__":
    main()
