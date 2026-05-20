"""H11F part-variation sweep on all 4 tubes.

Per Figure 5 of the H11F datasheet, R(I_LED) varies ±30 % across parts
at a given operating point. We model this via the BETA_SCALE parameter
on the internal NJF.

Sweep BETA_SCALE in {0.77, 1.0, 1.43} — corresponds to part R-spread
±30 % (high-R, typical, low-R).

For comparison: the JFET arch's V_p sweep (sweep_vp_4tubes.py on the
jfet-ls844-retrofit branch) showed cold-start overshoot up to +29 K
at V_p=-1 V and a full IV-18 stall at V_p=-3.5 V. The H11F should
have no equivalent failure modes — the loop just shifts V_int_OP to
compensate for R(I_LED) variation.
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

tcl.T_END = 4.0

VARIANTS = [
    # (label, BETA_SCALE) — ±30% per datasheet
    ("low_R",  1.43),
    ("typ",    1.00),
    ("high_R", 0.77),
]

TUBES = ("iv18", "iv6", "ilc11_7", "ilc11_8")


def run(case):
    tube_key, label, beta_scale = case
    spec = tcl.TUBES[tube_key]
    mc = {k: spec[k] for k in ("r_amb","sigma_eps_A","c_th","r_top_ref","r_bot_ref","r_sense")}
    mc["t_rail_ramp"] = 100e-6
    if spec.get("log_gain_K") is not None:
        mc["log_demod"]  = True
        mc["log_gain_K"] = spec["log_gain_K"]
        mc["v_eps_log"]  = 5e-3
        mc["nonlin_type"]= "log"
    for k in ("booster","ce_buf","mos_buf"):
        if spec.get(k): mc[k] = True
    for k in ("buf_fb1","buf_fb_ap","v_buf","c_ap"):
        if spec.get(k) is not None: mc[k] = spec[k]
    mc["h11f_beta_scale"] = beta_scale
    short = f"{tube_key}_{label}"
    cir = tcl.WORK / f"hpv_{short}.cir"
    dat = tcl.WORK / f"hpv_{short}.data"
    raw = tcl.make_netlist(dat, v_preset=0.0, t_ramp=0.0,
                            r_int_scale=spec["r_int_scale"], mc=mc)
    if spec.get("mos_buf"):
        raw = swap_to_level1(raw)
    cir.write_text(raw)
    t0 = time.time()
    res = subprocess.run(["ngspice","-b",cir.name], cwd=tcl.WORK,
                         capture_output=True, text=True, timeout=1800)
    wall = time.time() - t0
    if res.returncode != 0:
        return dict(tube=tube_key, label=label, beta_scale=beta_scale,
                    error=res.stderr[-200:], wall=wall)
    d = np.loadtxt(dat)
    t = d[:,0]; T = d[:,17]; v_int = d[:,15]; v_ap_drive = d[:,3]; v_ctl = d[:,13]
    T_op = spec["T_op"]
    idx_in_band = np.where(np.abs(T - T_op) < 2)[0]
    t_settle = float(t[idx_in_band[0]]) if len(idx_in_band) else float("nan")
    late = t > t[-1] - 0.1
    T_end = float(np.mean(T[late]))
    T_pk = float(np.max(T))
    v_int_op = float(np.mean(v_int[late]))
    v_ctl_op = float(np.mean(v_ctl[late]))
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
    return dict(tube=tube_key, label=label, beta_scale=beta_scale,
                wall=wall, t_settle_2K=t_settle, T_end=T_end, T_pk=T_pk,
                v_int_op=v_int_op, v_ctl_op=v_ctl_op, V1_mV=h1*1e3,
                H2_pct=h2/h1*100 if h1>0 else float("nan"),
                H3_pct=h3/h1*100 if h1>0 else float("nan"))


def main():
    out_path = HERE / "sweep_h11f_part_variation_results.txt"
    out_f = open(out_path, "w")
    def emit(line):
        print(line, flush=True)
        out_f.write(line + "\n"); out_f.flush()
    emit("H11F part-variation sweep (BETA_SCALE = R-spread simulant)")
    emit(f"{'tube':9s} {'part':>6s} {'BETA':>5s} {'wall':>5s} {'t_set2K':>8s} "
         f"{'T_end':>7s} {'T_pk':>7s} {'over':>5s} {'V_int':>7s} {'V_ctl':>7s} "
         f"{'V1mV':>6s} {'H2%':>5s} {'H3%':>5s}")
    jobs = []
    for tube in TUBES:
        for label, scale in VARIANTS:
            jobs.append((tube, label, scale))
    with ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(run, jobs))
    for tube in TUBES:
        for r in [x for x in results if x['tube']==tube]:
            if "error" in r:
                emit(f"{r['tube']:9s} FAIL: {r['error'][:80]}"); continue
            ts = f"{r['t_settle_2K']*1e3:.0f}ms" if not np.isnan(r['t_settle_2K']) else "—"
            T_op = tcl.TUBES[r['tube']]['T_op']
            over = r['T_pk'] - T_op
            emit(f"{r['tube']:9s} {r['label']:>6s} {r['beta_scale']:5.2f} {r['wall']:5.0f} "
                 f"{ts:>8s} {r['T_end']:7.2f} {r['T_pk']:7.2f} {over:+5.1f} "
                 f"{r['v_int_op']:+7.3f} {r['v_ctl_op']:+7.3f} {r['V1_mV']:6.0f} "
                 f"{r['H2_pct']:5.2f} {r['H3_pct']:5.2f}")
    out_f.close()


if __name__ == "__main__":
    main()
