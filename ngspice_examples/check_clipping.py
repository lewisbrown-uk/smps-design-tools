"""Check whether the buffer outputs in the booster tubes are clipped sines
(i.e., MOSFETs in triode/clipping mode) or clean sines (linear class-AB).

For each booster tube, runs the standard 1 kHz transient, samples the
last ~10 ms of v_osc_drive, fits a pure sinusoid by FFT-extracting the
fundamental, and reports:
  - Measured V_pk
  - Fundamental amplitude
  - THD (energy in non-fundamental bins)
  - V_pk / v_buf headroom ratio

If THD is low and V_pk < 0.9*v_buf, it's clean linear class-AB.
If THD is high and V_pk ~= v_buf, it's clipping into triode.
"""
from __future__ import annotations
import sys, re, subprocess
from pathlib import Path
import numpy as np

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import test_closed_loop as m


def run_capture(tube_key: str):
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
    if spec.get("ce_buf"): mc["ce_buf"] = True
    if spec.get("mos_buf"): mc["mos_buf"] = True
    if spec.get("bias_zener_v") is not None: mc["bias_zener_v"] = spec["bias_zener_v"]

    work = m.WORK; work.mkdir(exist_ok=True)
    cir = work / f"clip_{tube_key}.cir"
    dat = work / f"clip_{tube_key}.data"
    netlist = m.make_netlist(dat, v_preset=0.55, t_ramp=0.1,
                             r_int_scale=spec["r_int_scale"], mc=mc)
    new_control = f""".control
run
let v_o = v(v_osc_drive)
let v_a = v(v_ap_drive)
wrdata {dat.as_posix()} v_o v_a
.endcontrol"""
    netlist = re.sub(r"\.control.*?\.endcontrol", new_control,
                     netlist, flags=re.DOTALL)
    cir.write_text(netlist)
    res = subprocess.run(["ngspice", "-b", cir.name], cwd=work,
                         capture_output=True, text=True, timeout=900)
    if res.returncode != 0:
        print(res.stderr[-1500:]); raise SystemExit(1)
    d = np.loadtxt(dat)
    t, v_o, v_a = d[:, 0], d[:, 1], d[:, 3]
    try: dat.unlink()
    except OSError: pass
    return spec, t, v_o, v_a


def analyse(tube_key, spec, t, v_o, v_a):
    v_buf = spec.get("v_buf", 4.3)
    # Steady-state window: last 50 ms
    ss = t > t[-1] - 0.05
    t_ss, v_o_ss, v_a_ss = t[ss], v_o[ss], v_a[ss]
    v_diff = v_o_ss - v_a_ss

    # Resample to uniform grid for FFT
    n = 4096
    t_uni = np.linspace(t_ss[0], t_ss[-1], n)
    dt = t_uni[1] - t_uni[0]
    v_o_uni = np.interp(t_uni, t_ss, v_o_ss)
    v_a_uni = np.interp(t_uni, t_ss, v_a_ss)
    v_diff_uni = v_o_uni - v_a_uni

    # FFT
    F_o = np.fft.rfft(v_o_uni)
    F_d = np.fft.rfft(v_diff_uni)
    freqs = np.fft.rfftfreq(n, dt)
    # Find fundamental: largest peak in 800 - 1200 Hz range
    f_mask = (freqs > 800) & (freqs < 1200)
    if not f_mask.any():
        print(f"{tube_key}: no fundamental found"); return
    fund_idx = np.where(f_mask)[0][np.argmax(np.abs(F_o[f_mask]))]
    f0 = freqs[fund_idx]
    fund_amp_o = 2 * np.abs(F_o[fund_idx]) / n
    fund_amp_d = 2 * np.abs(F_d[fund_idx]) / n

    # THD: energy in 2nd-10th harmonic bins (skip DC and fundamental)
    harm_amps = []
    for h in range(2, 11):
        h_freq = f0 * h
        h_idx = int(np.argmin(np.abs(freqs - h_freq)))
        harm_amps.append(2 * np.abs(F_o[h_idx]) / n)
    thd_pct = 100 * np.sqrt(sum(a**2 for a in harm_amps)) / fund_amp_o

    # Peak (raw) of v_osc_drive and v_diff
    v_o_pk = max(np.abs(v_o_ss.max()), np.abs(v_o_ss.min()))
    v_d_pk = max(np.abs(v_diff.max()), np.abs(v_diff.min()))
    v_d_rms = float(np.sqrt(np.mean(v_diff_uni**2)))

    print(f"=== {spec['name']} (v_buf={v_buf:.2f} V, "
          f"buffer={'MOSFET CE' if spec.get('mos_buf') else 'BJT CC'}) ===")
    print(f"  V_pk(v_osc_drive)            = {v_o_pk:.3f} V   "
          f"(headroom v_buf - V_pk = {v_buf - v_o_pk:+.3f} V)")
    print(f"  V_pk/v_buf                   = {v_o_pk/v_buf*100:.1f}%   "
          f"({'CLIPPING' if v_o_pk/v_buf > 0.95 else 'linear'})")
    print(f"  V_diff RMS                   = {v_d_rms:.3f} V   "
          f"(target {spec['V_op']:.3f} V_RMS)")
    print(f"  V_diff peak                  = {v_d_pk:.3f} V")
    print(f"  Fundamental at v_osc_drive   = {fund_amp_o:.3f} V_pk @ {f0:.0f} Hz")
    print(f"  THD on v_osc_drive (2-10th)  = {thd_pct:.2f}%")
    print(f"  Per-harmonic (2,3,5,7):      "
          f"{harm_amps[0]/fund_amp_o*100:.2f}% / "
          f"{harm_amps[1]/fund_amp_o*100:.2f}% / "
          f"{harm_amps[3]/fund_amp_o*100:.2f}% / "
          f"{harm_amps[5]/fund_amp_o*100:.2f}%")
    print()


def main():
    tubes = sys.argv[1:] or ["iv6", "ilc11_7", "ilc11_8"]
    for tube in tubes:
        if tube not in m.TUBES:
            print(f"Unknown tube {tube}"); continue
        result = run_capture(tube)
        if result:
            analyse(tube, *result)


if __name__ == "__main__":
    main()
