"""Sweep log_gain_K over [5, 7.5, 10, 12.5, 15, 17.5, 20] on all 4 tubes.

Reuses cached results from earlier runs:
  - IV-18  at gain=5 and 10 (from tune_logdem_gain_iv18.py + check_logdem_4tubes.py)
  - IV-6, ILC1-1/7, ILC1-1/8 at gain=10 (from check_logdem_4tubes.py)

Saves all results to a CSV, then plots settling time and overshoot vs
gain for each tube.
"""
import sys, types, subprocess, time, csv, json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_closed_loop as tcl
from validate_cap_470nf_iv6max_level1 import swap_to_level1

tcl.T_END = 6.0

# Cached results from earlier sweeps (T_END=6.0, log_demod=True, eps=5mV, nlin=log)
CACHED = [
    # (tube, gain, t_settle_2K_s, T_end_K, T_pk_K, V_int_op_V, V1_mV, H2_pct, H3_pct)
    # IV-18 from tune_logdem_gain_iv18.py (kb=2.6, log eps=5mV)
    ("iv18",    5.0,  1.753, 799.58, 799.78, -1.507,  767, 0.22, 3.01),
    # IV-18 from check_logdem_4tubes.py (kb=2.6, log eps=5mV)
    ("iv18",   10.0,  0.435, 799.73, 799.94, -1.510,  767, 0.57, 3.01),
    # Others from check_logdem_4tubes.py
    ("iv6",    10.0,  0.244, 799.80, 801.14, -1.221,  957, 0.34, 3.03),
    ("ilc11_7",10.0,  0.119, 800.75, 808.65, -0.490, 6229, 0.47, 7.82),
    ("ilc11_8",10.0,  0.209, 799.87, 804.01, -1.116, 1198, 0.32, 3.02),
]

NEW_CASES = []
for tube in ("iv18","iv6","ilc11_7","ilc11_8"):
    for g in (5.0, 7.5, 10.0, 12.5, 15.0, 17.5, 20.0):
        already = any(c[0]==tube and abs(c[1]-g)<0.01 for c in CACHED)
        if not already:
            NEW_CASES.append((tube, g))

print(f"Cached: {len(CACHED)} cases.  New: {len(NEW_CASES)} cases.", flush=True)


def run(case):
    tk, gain = case
    spec = tcl.TUBES[tk]
    mc = {k: spec[k] for k in ("r_amb","sigma_eps_A","c_th","r_top_ref","r_bot_ref","r_sense")}
    mc["t_rail_ramp"] = 100e-6
    mc["log_demod"]  = True
    mc["log_gain_K"] = gain
    mc["v_eps_log"]  = 5e-3
    mc["nonlin_type"]= "log"
    for k in ("booster","ce_buf","mos_buf"):
        if spec.get(k): mc[k] = True
    for k in ("buf_fb1","buf_fb_ap","v_buf","c_ap"):
        if spec.get(k) is not None: mc[k] = spec[k]
    label = f"{tk}_g{gain:.1f}".replace(".","_")
    cir = tcl.WORK / f"sw4_{label}.cir"
    dat = tcl.WORK / f"sw4_{label}.data"
    raw = tcl.make_netlist(dat, v_preset=0.0, t_ramp=0.0, r_int_scale=spec["r_int_scale"], mc=mc)
    if spec.get("mos_buf"):
        raw = swap_to_level1(raw)
    cir.write_text(raw)
    t0 = time.time()
    res = subprocess.run(["ngspice","-b",cir.name], cwd=tcl.WORK, capture_output=True, text=True, timeout=1800)
    wall = time.time() - t0
    if res.returncode != 0:
        return (tk, gain, float("nan"), float("nan"), float("nan"), float("nan"), 0.0, float("nan"), float("nan"))
    d = np.loadtxt(dat)
    t = d[:,0]; T = d[:,17]; v_int = d[:,15]; v_ap_drive = d[:,3]
    T_op = spec["T_op"]
    idx_in_band = np.where(np.abs(T - T_op) < 2)[0]
    t_settle = float(t[idx_in_band[0]]) if len(idx_in_band) else float("nan")
    late = t > t[-1] - 0.1
    T_end = float(np.mean(T[late]))
    T_pk  = float(np.max(T))
    v_int_op = float(np.mean(v_int[late]))
    end_mask = t > t[-1] - 0.2
    ts2 = t[end_mask]; vs2 = v_ap_drive[end_mask]
    dt = 50e-6
    t_u = np.arange(ts2[0], ts2[-1], dt)
    v_u = np.interp(t_u, ts2, vs2); v_u -= v_u.mean()
    N = len(t_u); win = np.hanning(N)
    V = np.fft.rfft(v_u*win) * (2/N) / 0.5
    f = np.fft.rfftfreq(N, dt)
    def mag(f0, bw=20):
        idx = (f > f0-bw) & (f < f0+bw)
        return float(np.max(np.abs(V[idx])))
    h1, h2, h3 = mag(1000), mag(2000), mag(3000)
    try: dat.unlink()
    except OSError: pass
    print(f"  {tk:9s} g={gain:5.2f}  wall={wall:.0f}s  t_set={t_settle*1e3 if not np.isnan(t_settle) else float('nan'):.0f}ms  T_pk={T_pk:.2f}", flush=True)
    return (tk, gain, t_settle, T_end, T_pk, v_int_op, h1*1e3,
            h2/h1*100 if h1>0 else float("nan"),
            h3/h1*100 if h1>0 else float("nan"))


def main():
    print(f"Running {len(NEW_CASES)} new cases (T_END={tcl.T_END}s, log_demod, eps=5mV)...", flush=True)
    with ThreadPoolExecutor(max_workers=4) as ex:
        new_results = list(ex.map(run, NEW_CASES))
    # Combine cached + new
    all_results = list(CACHED) + new_results
    # Save CSV
    csv_path = HERE / "sweep_logdem_gain_4tubes_results.csv"
    with open(csv_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["tube","gain","t_settle_2K_s","T_end_K","T_pk_K","V_int_op_V","V1_mV","H2_pct","H3_pct"])
        for r in all_results:
            w.writerow(r)
    print(f"Wrote {csv_path}", flush=True)

    # Plot per tube: 2 subplots × 4 tubes, settling time and overshoot vs gain
    fig, axes = plt.subplots(2, 1, figsize=(10, 9), sharex=True)
    colors = dict(iv18="C0", iv6="C1", ilc11_7="C2", ilc11_8="C3")
    for tube in ("iv18", "iv6", "ilc11_7", "ilc11_8"):
        T_op = tcl.TUBES[tube]["T_op"]
        rows = sorted([r for r in all_results if r[0] == tube], key=lambda r: r[1])
        if not rows: continue
        gains   = [r[1] for r in rows]
        t_set   = [r[2]*1e3 if not np.isnan(r[2]) else None for r in rows]
        # If t_settle is None (didn't reach band), use NaN
        t_set_plot = [v if v is not None else np.nan for v in t_set]
        over    = [r[4] - T_op for r in rows]
        name = tcl.TUBES[tube]["name"]
        axes[0].plot(gains, t_set_plot, "-o", color=colors[tube], label=name, lw=1.5, markersize=6)
        axes[1].plot(gains, over,        "-o", color=colors[tube], label=name, lw=1.5, markersize=6)
    axes[0].set_ylabel("Settling time to ±2 K  (ms)")
    axes[0].set_title("Log demod sweep: gain=5 → 20 (eps=5 mV, signed-log) — IV-18 baseline k_buf=2.6, others at their per-tube k_buf")
    axes[0].set_yscale("log")
    axes[0].grid(True, which="both", alpha=0.4)
    axes[0].legend(loc="upper right", fontsize=9)
    axes[1].set_ylabel("Cold-start overshoot T_pk − T_op  (K)")
    axes[1].set_xlabel("log_gain_K (small-signal gain at V=0)")
    axes[1].axhline(0, color="0.5", lw=0.7)
    axes[1].grid(True, alpha=0.4)
    axes[1].legend(loc="upper left", fontsize=9)
    fig.tight_layout()
    png_path = HERE / "sweep_logdem_gain_4tubes.png"
    fig.savefig(png_path, dpi=110)
    print(f"Wrote {png_path}", flush=True)


if __name__ == "__main__":
    main()
