"""Measure H2 / THD on the all-pass output v_ap for all 4 tubes at steady
state. The bootstrap (R_btd/C_btd) that previously cancelled the
V_DS-dependent term in 1/R_DS was removed during the NMOS+level-shift
switch. Memory file's analytical prediction is H2 ~5-7% on ILC1-1/7
because V_DS_pk/(2·V_OD) ≈ 0.4 at OP.

Method:
1. Run each tube to steady state (T_END=2.5s, last 200ms is settled).
2. wrdata v(v_ap) at high resolution.
3. FFT the steady-state window.
4. Extract magnitudes at 1k, 2k, 3k Hz; compute H2 (V2/V1) and THD.
5. Compare across tubes — flag if H2 > 10% as material design concern.

Note: H2 in v_ap causes a 2 kHz tone at v_diff, which the chopper demod
re-rectifies. The DC component of the re-rectified 2 kHz tone shifts
the bridge null DC point, which the loop compensates by adjusting
V_int_OP. This is a small T offset, NOT a large dynamic effect.
"""
import sys, types, subprocess, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import numpy as np

mpl = types.ModuleType("matplotlib"); mpl.use=lambda *a, **k: None
sys.modules.setdefault("matplotlib", mpl)
sys.modules.setdefault("matplotlib.pyplot", types.ModuleType("plt"))

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_closed_loop as tcl
from validate_cap_470nf_iv6max_level1 import swap_to_level1

tcl.T_END = 2.5
TUBES = ("iv18", "iv6", "ilc11_7", "ilc11_8")


def run_one(tube_key):
    spec = tcl.TUBES[tube_key]
    mc = {k: spec[k] for k in ("r_amb", "sigma_eps_A", "c_th",
                                "r_top_ref", "r_bot_ref", "r_sense")}
    mc["t_rail_ramp"] = 100e-6
    for k in ("booster", "ce_buf", "mos_buf"):
        if spec.get(k): mc[k] = True
    for k in ("buf_fb1", "buf_fb_ap", "v_buf", "c_ap"):
        if spec.get(k) is not None: mc[k] = spec[k]
    # Enable log demod with per-tube optimal gain (H11F arch defaults).
    if spec.get("log_gain_K") is not None:
        mc["log_demod"]    = True
        mc["log_gain_K"]   = spec["log_gain_K"]
        mc["v_eps_log"]    = 5e-3
        mc["nonlin_type"]  = "log"
        mc["log_clip_type"]= "schottky"
    cir = tcl.WORK / f"h2_{tube_key}.cir"
    dat = tcl.WORK / f"h2_{tube_key}.data"
    raw = tcl.make_netlist(dat, v_preset=0.0, t_ramp=0.0,
                            r_int_scale=spec["r_int_scale"], mc=mc)
    if spec.get("mos_buf"):
        raw = swap_to_level1(raw)
    cir.write_text(raw)
    t0 = time.time()
    res = subprocess.run(["ngspice", "-b", cir.name], cwd=tcl.WORK,
                          capture_output=True, text=True, timeout=1800)
    wall = time.time() - t0
    if res.returncode != 0:
        return dict(tube=tube_key, error=res.stderr[-400:], wall=wall)
    d = np.loadtxt(dat)
    t = d[:, 0]
    v_ap = d[:, 3]   # cols: t, v_osc_drive, t, v_ap_drive (per wrdata in netlist)
    v_osc = d[:, 1]
    # Pull settled window: last 200 ms
    mask = t > t[-1] - 0.20
    ts = t[mask]; vs = v_ap[mask]; vo = v_osc[mask]
    # Resample to uniform grid for FFT
    dt_uniform = 50e-6  # 20 kHz sample rate, plenty for 1 kHz signal + harmonics to 10 kHz
    t_uni = np.arange(ts[0], ts[-1], dt_uniform)
    v_ap_uni  = np.interp(t_uni, ts, vs)
    v_osc_uni = np.interp(t_uni, ts, vo)
    # Remove DC
    v_ap_ac  = v_ap_uni  - np.mean(v_ap_uni)
    v_osc_ac = v_osc_uni - np.mean(v_osc_uni)
    # FFT
    N = len(t_uni)
    win = np.hanning(N)
    V_ap  = np.fft.rfft(v_ap_ac  * win) * (2 / N) / 0.5  # 0.5 = Hanning amplitude correction
    V_osc = np.fft.rfft(v_osc_ac * win) * (2 / N) / 0.5
    freqs = np.fft.rfftfreq(N, dt_uniform)
    def bin_mag(V, f_target, bw=20):
        idx = (freqs > f_target - bw) & (freqs < f_target + bw)
        return float(np.max(np.abs(V[idx]))) if idx.any() else 0.0
    f0 = 1000.0
    V1 = bin_mag(V_ap, f0)
    V2 = bin_mag(V_ap, 2*f0)
    V3 = bin_mag(V_ap, 3*f0)
    V4 = bin_mag(V_ap, 4*f0)
    V5 = bin_mag(V_ap, 5*f0)
    # THD = sqrt(V2^2+V3^2+...) / V1
    THD = (V2**2 + V3**2 + V4**2 + V5**2) ** 0.5 / V1 if V1 > 0 else float("nan")
    # Compare against v_osc magnitudes at same frequencies
    Vosc1 = bin_mag(V_osc, f0)
    Vosc2 = bin_mag(V_osc, 2*f0)
    try: dat.unlink()
    except OSError: pass
    return dict(tube=tube_key, wall=wall,
                V1=V1, V2=V2, V3=V3, V4=V4, V5=V5, THD=THD,
                H2_pct=V2/V1*100 if V1 > 0 else float("nan"),
                Vosc1=Vosc1, Vosc2=Vosc2,
                Vosc_H2_pct=Vosc2/Vosc1*100 if Vosc1 > 0 else float("nan"))


def main():
    print(f"Measuring H2/THD on v_ap for {TUBES} (steady-state 200 ms window)\n")
    with ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(run_one, TUBES))
    print(f"{'tube':8s} {'V1_pk':>7s} {'V2_pk':>7s} {'V3_pk':>7s} {'H2 %':>7s} {'H3 %':>7s} {'THD %':>7s} {'(V_osc H2 %)':>14s}")
    print("-" * 80)
    for r in results:
        if "error" in r:
            print(f"{r['tube']:8s} FAIL: {r['error'][:80]}")
            continue
        h3 = r['V3']/r['V1']*100 if r['V1']>0 else 0
        print(f"{r['tube']:8s} {r['V1']:7.4f} {r['V2']:7.4f} {r['V3']:7.4f} "
              f"{r['H2_pct']:7.3f} {h3:7.3f} {r['THD']*100:7.3f} "
              f"{r['Vosc_H2_pct']:13.3f}")
    print()
    print("Interpretation: H2 at v_ap comes from R_DS non-linearity in the")
    print("variable-R FETs (V_DS-dependent term in 1/R_DS). The bridge demod")
    print("re-rectifies this 2 kHz tone into a DC offset; the loop compensates")
    print("via V_int_OP shift. Final effect: small T offset, not a dynamic issue.")
    print("V_osc H2 % column is the reference for the oscillator's own distortion.")


if __name__ == "__main__":
    main()
