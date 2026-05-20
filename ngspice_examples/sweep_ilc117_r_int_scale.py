"""Sweep r_int_scale on ILC1-1/7 to find a value that brings small-signal
ring damping into the 0.5-0.7 range (PM ~60°). The baseline
r_int_scale=1.5 gives ζ≈0.044 (PM≈5°), a 12.4 Hz lightly-damped ring
visible on the convergence trace. Higher r_int_scale = larger R_INT and
R_PID together, scaling Ki and Kp by 1/r_int_scale (loop bandwidth and
loop gain both drop proportionally).

For each r_int_scale, runs ILC1-1/7 4-s cold-start, extracts the
small-signal ring frequency and ζ from v_int_out peaks in the
0.4-2.0-s window (past the cold-start nonlinear regime).
"""
import sys, types, subprocess, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from scipy.signal import find_peaks

mpl = types.ModuleType("matplotlib"); mpl.use=lambda *a, **k: None
sys.modules.setdefault("matplotlib", mpl)
sys.modules.setdefault("matplotlib.pyplot", types.ModuleType("plt"))

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_closed_loop as tcl

tcl.T_END = 4.0
# (r_int_scale, k_r_intfb, k_c_intin) sweep.
# k_c_intin scales C_PID (input cap parallel with R_INT).
# Compensator's HF zero at 1/(2π·R_INT·C_PID) = 1.06 kHz / k_c_intin
# (at r_int_scale=1.5, k_r_intin=1). Want it near the 24 Hz ring frequency.
# k_c_intin=44 puts the zero at ~24 Hz.
# Sweep R_INT alone (via k_r_intin). C_HF_BASE already lowered to 1n.
# Scales BOTH Kp and Ki by 1/k_r_intin, drops crossover without moving PI
# zero. Goal: ζ ≈ 0.5-0.7. With k_c_hf=1 (the new 1nF baseline).
# Cases: (r_int_scale, k_r_intin, k_r_intfb, k_c_intin, k_c_hf)
CASES = [
    (1.5, 1.0, 1.0, 1.0, 1.0),    # baseline (new C_HF=1n, k_r_intin=1)
    (1.5, 2.0, 1.0, 1.0, 1.0),
    (1.5, 5.0, 1.0, 1.0, 1.0),
    (1.5, 10.0, 1.0, 1.0, 1.0),
    (1.5, 20.0, 1.0, 1.0, 1.0),
    (1.5, 50.0, 1.0, 1.0, 1.0),
]
TUBE = "ilc11_7"


def run_one(case):
    r_int_scale, k_r_intin, k_r_intfb, k_c_intin, k_c_hf = case
    spec = tcl.TUBES[TUBE]
    mc = {k: spec[k] for k in ("r_amb", "sigma_eps_A", "c_th",
                                "r_top_ref", "r_bot_ref", "r_sense")}
    mc["t_rail_ramp"] = 100e-6
    mc["k_r_intin"] = k_r_intin
    mc["k_r_intfb"] = k_r_intfb
    mc["k_c_intin"] = k_c_intin
    mc["k_c_hf"]    = k_c_hf
    for k in ("booster", "ce_buf", "mos_buf"):
        if spec.get(k): mc[k] = True
    for k in ("buf_fb1", "buf_fb_ap", "v_buf", "c_ap"):
        if spec.get(k) is not None: mc[k] = spec[k]

    label = f"rintinsweep_{r_int_scale:.1f}_{k_r_intin:.2f}"
    cir = tcl.WORK / f"{label}.cir"
    dat = tcl.WORK / f"{label}.data"
    raw = tcl.make_netlist(dat, v_preset=0.0, t_ramp=0.0,
                            r_int_scale=r_int_scale, mc=mc)
    cir.write_text(raw)
    t0 = time.time()
    res = subprocess.run(["ngspice", "-b", cir.name], cwd=tcl.WORK,
                          capture_output=True, text=True, timeout=3600)
    wall = time.time() - t0
    if res.returncode != 0:
        return dict(scale=r_int_scale, kin=k_r_intin, kp=k_r_intfb, kc=k_c_intin, khf=k_c_hf, error=res.stderr[-300:], wall=wall)
    d = np.loadtxt(dat)
    t = d[:, 0]
    v_int = d[:, 15]
    T = d[:, 17]
    T_op = spec["T_op"]
    T_peak = float(np.max(T))
    late = t > (t[-1] - 0.05)
    T_end = float(np.mean(T[late]))
    # Small-signal ring on v_int_out in 0.4-2.0 s window
    mask = (t > 0.4) & (t < 2.0)
    ts = t[mask]
    v_op = float(np.mean(v_int[(t > 1.5) & (t < 2.0)]))
    v_osc = v_int[mask] - v_op
    avg_dt = float(np.mean(np.diff(ts)))
    min_dist = max(int(0.020 / avg_dt), 5)  # 20 ms minimum peak separation
    peaks, _ = find_peaks(np.abs(v_osc), distance=min_dist)
    if len(peaks) < 6:
        return dict(scale=r_int_scale, kin=k_r_intin, kp=k_r_intfb, kc=k_c_intin, khf=k_c_hf, wall=wall, T_peak=T_peak, T_end=T_end,
                    n_peaks=len(peaks), zeta=None, freq=None, v_op=v_op,
                    note=f"too few peaks ({len(peaks)})")
    pk_v = np.abs(v_osc)[peaks]
    pk_t = ts[peaks]
    # Use peaks past the initial transient (skip first 4)
    use = pk_v[4:]; use_t = pk_t[4:]
    if len(use) < 4:
        use = pk_v; use_t = pk_t
    # Same-sign ratio per full period
    ratios = []
    for i in range(len(use) - 2):
        r = use[i+2] / use[i]
        if 0 < r < 1.5:
            ratios.append(r)
    if not ratios:
        # Probably overdamped — no ringing
        # Estimate decay via single-exp fit
        return dict(scale=r_int_scale, kin=k_r_intin, kp=k_r_intfb, kc=k_c_intin, khf=k_c_hf, wall=wall, T_peak=T_peak, T_end=T_end,
                    v_op=v_op, zeta=None, freq=None, n_peaks=len(peaks),
                    note="no ring (overdamped?)")
    ratio = float(np.median(ratios))
    half_period = float(np.mean(np.diff(use_t[:8])))
    period = 2 * half_period
    freq = 1 / period if period > 0 else float("nan")
    if ratio >= 1.0:
        zeta = float("nan")
        note = f"ratio >= 1 (diverging? ratios={[f'{r:.2f}' for r in ratios[:4]]})"
    else:
        delta = np.log(1 / ratio)
        zeta = float(delta / np.sqrt(4 * np.pi**2 + delta**2))
        note = ""
    try: dat.unlink()
    except OSError: pass
    return dict(scale=r_int_scale, kin=k_r_intin, kp=k_r_intfb, kc=k_c_intin, khf=k_c_hf, wall=wall, T_peak=T_peak, T_end=T_end,
                v_op=v_op, freq=freq, zeta=zeta, n_peaks=len(peaks),
                ratio=ratio, note=note)


def main():
    print(f"Sweeping (r_int_scale, k_r_intfb) on {TUBE}")
    print(f"(baseline (1.5, 1.0) gives Kp=10, ζ≈0.044, f_ring=12.4 Hz, PM≈5°)\n")
    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(run_one, CASES))
    print(f"\n{'kin':>5s} {'Rint':>6s} {'T_pk':>6s} {'T_end':>6s} "
          f"{'V_int_OP':>9s} {'f_ring':>7s} {'ratio':>6s} {'zeta':>6s} {'PM≈':>5s} {'note':s}")
    for r in results:
        if "error" in r:
            print(f"{r.get('kin',0):5.2f} FAIL  {r['error'][:80]}")
            continue
        Rint_eff = 100 * r['scale'] * r['kin']  # in kΩ
        z = r.get("zeta")
        pm = f"{z*100:.0f}°" if z is not None and z == z else "—"
        zs = f"{z:.3f}" if z is not None and z == z else "—"
        rs = f"{r.get('ratio', float('nan')):.3f}" if r.get("ratio") is not None else "—"
        fs = f"{r['freq']:5.2f}" if r.get("freq") else "—"
        print(f"{r['kin']:5.1f} {Rint_eff:5.0f}k {r['T_peak']:6.1f} {r['T_end']:6.1f} "
              f"{r['v_op']:+9.4f} {fs:>7s} {rs:>6s} {zs:>6s} {pm:>5s} {r.get('note','')}")


if __name__ == "__main__":
    main()
