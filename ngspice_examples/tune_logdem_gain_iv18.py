"""Follow-up to tune_logdem_iv18.py: sweep small-signal gain (log_gain_K).

The previous sweep used K=v_eps in V_out = K · sign · ln(1+|V|/v_eps),
giving unit small-signal gain. That preserves OP small-signal dynamics
but doesn't speed up the slow IV-18 settling near OP.

This sweep parametrizes log_gain_K > 1: slope at V_in=0 is log_gain_K.
At V_in >> v_eps, slope drops to log_gain_K · v_eps / |V|. So at OP
(small signal), the loop has MORE gain than linear — fast settle. At
cold-start (large signal), gain is MUCH LESS than linear — bounded
overshoot.

Target: fast OP settle (< 1 s) AND zero/small cold-start overshoot.
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

tcl.T_END = 6.0  # enough to see if settling completes
TUBE = "iv18"

CASES = [
    # (label, log_demod, v_eps_log, nonlin_type, log_gain_K, buf_fb1)
    # Reference: linear baseline (committed config)
    ("linear_kb_2_6_g1",          False, 5e-3, "log",   1,  1.6e3),
    # Log with progressively higher small-signal gain, k_buf=2.6 (small bridge signal)
    ("log_eps5mV_g5_kb_2_6",      True,  5e-3, "log",   5,  1.6e3),
    ("log_eps5mV_g10_kb_2_6",     True,  5e-3, "log",  10,  1.6e3),
    ("log_eps5mV_g30_kb_2_6",     True,  5e-3, "log",  30,  1.6e3),
    ("log_eps2mV_g30_kb_2_6",     True,  2e-3, "log",  30,  1.6e3),
    # Log with high gain + bigger v_eps for harder cold-start clamp
    ("log_eps20mV_g30_kb_2_6",    True, 20e-3, "log",  30,  1.6e3),
    # tanh at high gain (bounded output absolutely)
    ("tanh_V5mV_g10_kb_2_6",      True,  5e-3, "tanh", 10,  1.6e3),
    ("tanh_V5mV_g30_kb_2_6",      True,  5e-3, "tanh", 30,  1.6e3),
]


def run_one(label, log_demod, v_eps_log, nonlin_type, log_gain_K, buf_fb1):
    spec = tcl.TUBES[TUBE]
    mc = {k: spec[k] for k in ("r_amb","sigma_eps_A","c_th","r_top_ref","r_bot_ref","r_sense")}
    mc["t_rail_ramp"]   = 100e-6
    mc["log_demod"]     = log_demod
    mc["v_eps_log"]     = v_eps_log
    mc["nonlin_type"]   = nonlin_type
    mc["log_gain_K"]    = log_gain_K
    mc["buf_fb1"]       = buf_fb1
    mc["buf_fb_ap"]     = buf_fb1
    for k in ("booster","ce_buf","mos_buf"):
        if spec.get(k): mc[k] = True
    for k in ("v_buf","c_ap"):
        if spec.get(k) is not None: mc[k] = spec[k]
    cir = tcl.WORK / f"logdg_{label}.cir"
    dat = tcl.WORK / f"logdg_{label}.data"
    raw = tcl.make_netlist(dat, v_preset=0.0, t_ramp=0.0, r_int_scale=spec["r_int_scale"], mc=mc)
    if spec.get("mos_buf"):
        raw = swap_to_level1(raw)
    cir.write_text(raw)
    t0 = time.time()
    res = subprocess.run(["ngspice","-b",cir.name], cwd=tcl.WORK, capture_output=True, text=True, timeout=1800)
    wall = time.time() - t0
    if res.returncode != 0:
        return dict(label=label, error=res.stderr[-200:], wall=wall)
    d = np.loadtxt(dat)
    t = d[:,0]; T = d[:,17]; v_int = d[:,15]; v_ap_drive = d[:,3]
    T_op = spec["T_op"]
    idx_in_band = np.where(np.abs(T - T_op) < 2)[0]
    t_settle = float(t[idx_in_band[0]]) if len(idx_in_band) else float("nan")
    late = t > t[-1] - 0.1
    T_end = float(np.mean(T[late]))
    T_pk = float(np.max(T))
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
    return dict(label=label, wall=wall, log_demod=log_demod, v_eps_log=v_eps_log,
                nonlin_type=nonlin_type, log_gain_K=log_gain_K, buf_fb1=buf_fb1,
                t_settle_2K=t_settle, T_end=T_end, T_pk=T_pk,
                v_int_op=v_int_op, V1_mV=h1*1e3,
                H2_pct=h2/h1*100 if h1>0 else float("nan"),
                H3_pct=h3/h1*100 if h1>0 else float("nan"))


def main():
    out_path = HERE / "tune_logdem_gain_iv18_results.txt"
    out_f = open(out_path, "w")
    def emit(line):
        print(line, flush=True)
        out_f.write(line + "\n"); out_f.flush()
    emit("Log demod with variable small-signal gain, on IV-18 (kb=2.6)")
    emit(f"{'label':28s}  {'gain':>4s}  {'nlin':>5s}  {'eps_mV':>7s}  {'wall':>5s}  "
         f"{'t_set2K':>8s}  {'T_end':>7s}  {'T_pk':>7s}  {'over':>5s}  {'V_int':>7s}  "
         f"{'V1mV':>6s}  {'H2%':>5s}  {'H3%':>5s}")
    with ThreadPoolExecutor(max_workers=4) as ex:
        for r in ex.map(lambda c: run_one(*c), CASES):
            if "error" in r:
                emit(f"{r['label']:28s}  FAIL: {r['error'][:80]}"); continue
            nlin_tag = (r['nonlin_type'] if r['log_demod'] else "—")[:5]
            ts = f"{r['t_settle_2K']*1e3:.0f}ms" if not np.isnan(r['t_settle_2K']) else "—"
            over = r['T_pk'] - 800
            emit(f"{r['label']:28s}  {r['log_gain_K']:4.1f}  {nlin_tag:>5s}  "
                 f"{r['v_eps_log']*1e3:7.2f}  {r['wall']:5.0f}  "
                 f"{ts:>8s}  {r['T_end']:7.2f}  {r['T_pk']:7.2f}  {over:+5.1f}  "
                 f"{r['v_int_op']:+7.3f}  {r['V1_mV']:6.0f}  {r['H2_pct']:5.2f}  {r['H3_pct']:5.2f}")
    out_f.close()


if __name__ == "__main__":
    main()
