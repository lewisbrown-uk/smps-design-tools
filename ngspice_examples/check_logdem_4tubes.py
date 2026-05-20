"""Validate log demod (gain_K=10, eps=5mV, signed-log) on all 4 tubes.
Each tube uses its existing per-tube baseline (buf_fb1, r_int_scale, c_ap).
T_END=6s to confirm settling.
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

tcl.T_END = 6.0

CASES = [
    # (tube, log_demod, log_gain_K)
    ("iv18",    True, 10),
    ("iv6",     True, 10),
    ("ilc11_7", True, 10),
    ("ilc11_8", True, 10),
    # Linear references at baseline (for direct comparison)
    ("iv18",    False, 1),
    ("iv6",     False, 1),
    ("ilc11_7", False, 1),
    ("ilc11_8", False, 1),
]


def run(case):
    tk, log_demod, log_gain_K = case
    spec = tcl.TUBES[tk]
    mc = {k: spec[k] for k in ("r_amb","sigma_eps_A","c_th","r_top_ref","r_bot_ref","r_sense")}
    mc["t_rail_ramp"] = 100e-6
    if log_demod:
        mc["log_demod"]  = True
        mc["log_gain_K"] = log_gain_K
        mc["v_eps_log"]  = 5e-3
        mc["nonlin_type"]= "log"
    for k in ("booster","ce_buf","mos_buf"):
        if spec.get(k): mc[k] = True
    for k in ("buf_fb1","buf_fb_ap","v_buf","c_ap"):
        if spec.get(k) is not None: mc[k] = spec[k]
    label = f"{tk}_{'log' if log_demod else 'lin'}_g{log_gain_K}"
    cir = tcl.WORK / f"v4_{label}.cir"
    dat = tcl.WORK / f"v4_{label}.data"
    raw = tcl.make_netlist(dat, v_preset=0.0, t_ramp=0.0, r_int_scale=spec["r_int_scale"], mc=mc)
    if spec.get("mos_buf"):
        raw = swap_to_level1(raw)
    cir.write_text(raw)
    t0 = time.time()
    res = subprocess.run(["ngspice","-b",cir.name], cwd=tcl.WORK, capture_output=True, text=True, timeout=1800)
    wall = time.time() - t0
    if res.returncode != 0:
        return dict(label=label, tube=tk, error=res.stderr[-200:], wall=wall)
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
    return dict(label=label, tube=tk, log_demod=log_demod, log_gain_K=log_gain_K,
                wall=wall, t_settle_2K=t_settle, T_end=T_end, T_pk=T_pk,
                v_int_op=v_int_op, V1_mV=h1*1e3,
                H2_pct=h2/h1*100 if h1>0 else float("nan"),
                H3_pct=h3/h1*100 if h1>0 else float("nan"))


def main():
    out_path = HERE / "check_logdem_4tubes_results.txt"
    out_f = open(out_path, "w")
    def emit(line):
        print(line, flush=True)
        out_f.write(line + "\n"); out_f.flush()
    emit("Log demod validation on 4 tubes (T_END=6s)")
    emit(f"{'tube':9s}  {'log':>4s}  {'gain':>5s}  {'wall':>5s}  {'t_set2K':>8s}  "
         f"{'T_end':>7s}  {'T_pk':>7s}  {'over':>5s}  {'V_int':>7s}  "
         f"{'V1mV':>6s}  {'H2%':>5s}  {'H3%':>5s}")
    with ThreadPoolExecutor(max_workers=4) as ex:
        for r in ex.map(run, CASES):
            if "error" in r:
                emit(f"{r['tube']:9s}  FAIL: {r['error'][:80]}"); continue
            ts = f"{r['t_settle_2K']*1e3:.0f}ms" if not np.isnan(r['t_settle_2K']) else "—"
            T_op = tcl.TUBES[r['tube']]['T_op']
            over = r['T_pk'] - T_op
            log_tag = "Y" if r['log_demod'] else "—"
            emit(f"{r['tube']:9s}  {log_tag:>4s}  {r['log_gain_K']:5.0f}  {r['wall']:5.0f}  "
                 f"{ts:>8s}  {r['T_end']:7.2f}  {r['T_pk']:7.2f}  {over:+5.1f}  "
                 f"{r['v_int_op']:+7.3f}  {r['V1_mV']:6.0f}  {r['H2_pct']:5.2f}  {r['H3_pct']:5.2f}")
    out_f.close()


if __name__ == "__main__":
    main()
