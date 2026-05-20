"""Sweep buf_fb1 and r_int_scale on IV-18 (formerly IV-3) to speed up
settling under the JFET+bootstrap architecture.

Baseline:
  buf_fb1 = 1.6 kΩ → k_buf = 2.6 (smallest of all tubes)
  r_int_scale = 0.5 (smallest of all tubes)
  Settling: ~15 s to within 5 K of T_op (vs ~2 s on MOSFET arch)

Hypotheses to test:
  - Larger k_buf → bigger V_drive_diff → bigger bridge ΔV_diff per ΔR_fil
    → larger demod signal → faster integrator wind.
  - Smaller r_int_scale → smaller R_INT → larger Ki → faster wind.

Settling metric: time for T_node to reach within 2 K of T_op (and stay).
T_END = 4.0 s; cases that don't settle in 4 s are flagged.
"""
import sys, types, subprocess, time, itertools
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

tcl.T_END = 4.0
TUBE = "iv18"

CASES = [
    # (label, buf_fb1, r_int_scale, t_rail_ramp)
    # Soft-start sweep at k_buf=4.3, exploring rail ramp time
    ("kb_4_3_ramp_0",   3.3e3, 0.5, 100e-6),  # instant ramp (was previous test)
    ("kb_4_3_ramp_50",  3.3e3, 0.5,  50e-3),
    ("kb_4_3_ramp_100", 3.3e3, 0.5, 100e-3),
    ("kb_4_3_ramp_200", 3.3e3, 0.5, 200e-3),
    ("kb_4_3_ramp_500", 3.3e3, 0.5, 500e-3),
    # Same range at k_buf=2.6 for comparison
    ("kb_2_6_ramp_0",   1.6e3, 0.5, 100e-6),
    ("kb_2_6_ramp_100", 1.6e3, 0.5, 100e-3),
]


def run_one(label, buf_fb1, r_int_scale, t_rail_ramp):
    spec = tcl.TUBES[TUBE]
    mc = {k: spec[k] for k in ("r_amb", "sigma_eps_A", "c_th", "r_top_ref", "r_bot_ref", "r_sense")}
    mc["t_rail_ramp"] = t_rail_ramp
    mc["buf_fb1"] = buf_fb1
    mc["buf_fb_ap"] = buf_fb1  # keep matched
    for k in ("booster", "ce_buf", "mos_buf"):
        if spec.get(k): mc[k] = True
    for k in ("v_buf", "c_ap"):
        if spec.get(k) is not None: mc[k] = spec[k]
    cir = tcl.WORK / f"tune_{label}.cir"
    dat = tcl.WORK / f"tune_{label}.data"
    raw = tcl.make_netlist(dat, v_preset=0.0, t_ramp=0.0, r_int_scale=r_int_scale, mc=mc)
    if spec.get("mos_buf"):
        raw = swap_to_level1(raw)
    cir.write_text(raw)
    t0 = time.time()
    res = subprocess.run(["ngspice", "-b", cir.name], cwd=tcl.WORK, capture_output=True, text=True, timeout=1800)
    wall = time.time() - t0
    if res.returncode != 0:
        return dict(label=label, error=res.stderr[-200:], wall=wall)
    d = np.loadtxt(dat)
    t = d[:, 0]; T = d[:, 17]; v_int = d[:, 15]; v_ap_drive = d[:, 3]
    T_op = spec["T_op"]
    # Time to settle within 2 K
    idx_in_band = np.where(np.abs(T - T_op) < 2)[0]
    t_settle = float(t[idx_in_band[0]]) if len(idx_in_band) else float("nan")
    # Final T
    late = t > t[-1] - 0.1
    T_end = float(np.mean(T[late]))
    T_pk  = float(np.max(T))
    v_int_op = float(np.mean(v_int[late]))
    # H2 via FFT of v_ap_drive in last 200 ms
    end_mask = t > t[-1] - 0.2
    ts2 = t[end_mask]; vs2 = v_ap_drive[end_mask]
    dt = 50e-6
    t_u = np.arange(ts2[0], ts2[-1], dt)
    v_u = np.interp(t_u, ts2, vs2); v_u -= v_u.mean()
    N = len(t_u); win = np.hanning(N)
    V = np.fft.rfft(v_u * win) * (2 / N) / 0.5
    f = np.fft.rfftfreq(N, dt)
    def mag(f0, bw=20):
        idx = (f > f0 - bw) & (f < f0 + bw)
        return float(np.max(np.abs(V[idx])))
    h1, h2, h3 = mag(1000), mag(2000), mag(3000)
    H2_pct = h2 / h1 * 100 if h1 > 0 else float("nan")
    H3_pct = h3 / h1 * 100 if h1 > 0 else float("nan")
    try: dat.unlink()
    except OSError: pass
    return dict(label=label, wall=wall, buf_fb1=buf_fb1, r_int_scale=r_int_scale,
                t_rail_ramp=t_rail_ramp,
                t_settle_2K=t_settle, T_end=T_end, T_pk=T_pk, v_int_op=v_int_op,
                V1_mV=h1*1e3, H2_pct=H2_pct, H3_pct=H3_pct)


def main():
    out_path = HERE / "tune_iv18_results.txt"
    out_f = open(out_path, "w")
    def emit(line):
        print(line, flush=True)
        out_f.write(line + "\n"); out_f.flush()
    emit(f"Tuning IV-18 settling — JFET+bootstrap arch")
    emit(f"{'label':22s}  {'k_buf':>5s}  {'rint':>5s}  {'ramp_ms':>7s}  {'wall':>5s}  {'t_set2K':>8s}  "
         f"{'T_end':>7s}  {'T_pk':>7s}  {'over':>5s}  {'V1mV':>6s}  {'H3%':>5s}")
    with ThreadPoolExecutor(max_workers=4) as ex:
        for r in ex.map(lambda c: run_one(*c), CASES):
            if "error" in r:
                emit(f"{r['label']:22s}  FAIL: {r['error'][:80]}"); continue
            kbuf = 1 + r["buf_fb1"] / 1e3
            ts = f"{r['t_settle_2K']*1e3:.0f}ms" if not np.isnan(r['t_settle_2K']) else "—"
            over = r['T_pk'] - 800
            emit(f"{r['label']:22s}  {kbuf:5.2f}  {r['r_int_scale']:5.2f}  {r['t_rail_ramp']*1e3:7.1f}  {r['wall']:5.0f}  "
                 f"{ts:>8s}  {r['T_end']:7.2f}  {r['T_pk']:7.2f}  {over:+5.1f}  {r['V1_mV']:6.0f}  {r['H3_pct']:5.2f}")
    out_f.close()


if __name__ == "__main__":
    main()
