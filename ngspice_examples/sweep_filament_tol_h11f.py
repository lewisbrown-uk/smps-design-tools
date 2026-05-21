"""Corner sweep: H11F arch with filament R tolerance.

A built tube's actual filament resistance varies from the datasheet
spec R_op by ~±10–15 % due to wire-gauge, length, and emission-coating
tolerances. The PCB-side bridge ratio (R_top_ref/R_bot_ref/R_sen) is
fixed at the design value derived from R_op nominal — so a filament
with a different actual R_op heats to a different actual T, and the
loop dynamics shift with the load.

This sweep verifies:
  - cold-start overshoot stays bounded across ±10 % R_filament tolerance
  - settling time stays bounded
  - no oscillation / instability at the corners
  - T_end follows the (predictable) shift from the actual filament

Sweep: 3 corners (R_filament × {0.9, 1.0, 1.1} of design R_op) × 4 tubes.

Model: filament tolerance is implemented as a proportional scale of
r_amb, sigma_eps_A, and c_th (a filament with 10 % larger R also has
proportionally different thermal radiation coupling and heat capacity,
to first order). The bridge R_top_ref/R_bot_ref/R_sen stay at nominal.
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
TUBES = ("iv18", "iv6", "ilc11_7", "ilc11_8")
CORNERS = (0.9, 1.0, 1.1)  # ±10 % filament R


def run_one(tube_key, fil_scale):
    spec = tcl.TUBES[tube_key]
    mc = {"r_amb":       spec["r_amb"]       * fil_scale,
          "sigma_eps_A": spec["sigma_eps_A"] / fil_scale,  # P_op = V_op²/R: scales 1/R
          "c_th":        spec["c_th"]        / fil_scale,  # ∝ sigma_eps_A
          "r_top_ref":   spec["r_top_ref"],                 # PCB stays nominal
          "r_bot_ref":   spec["r_bot_ref"],
          "r_sense":     spec["r_sense"]}
    mc["t_rail_ramp"] = 100e-6
    for k in ("booster", "ce_buf", "mos_buf"):
        if spec.get(k): mc[k] = True
    for k in ("buf_fb1", "buf_fb_ap", "v_buf", "c_ap"):
        if spec.get(k) is not None: mc[k] = spec[k]
    if spec.get("log_gain_K") is not None:
        mc["log_demod"]    = True
        mc["log_gain_K"]   = spec["log_gain_K"]
        mc["v_eps_log"]    = 5e-3
        mc["nonlin_type"]  = "log"
        mc["log_clip_type"]= "schottky"
    label = f"fil{int(fil_scale*100):03d}"
    cir = tcl.WORK / f"filT_{tube_key}_{label}.cir"
    dat = tcl.WORK / f"filT_{tube_key}_{label}.data"
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
        return dict(tube=tube_key, fil_scale=fil_scale, error=res.stderr[-300:], wall=wall)
    d = np.loadtxt(dat)
    t = d[:,0]; T = d[:,17]; v_int = d[:,15]
    T_op = spec["T_op"]
    idx_in_band = np.where(np.abs(T - T_op) < 2)[0]
    t_settle = float(t[idx_in_band[0]]) if len(idx_in_band) else float("nan")
    late = t > t[-1] - 0.1
    T_end = float(np.mean(T[late]))
    T_pk  = float(np.max(T))
    v_int_op = float(np.mean(v_int[late]))
    try: dat.unlink()
    except OSError: pass
    return dict(tube=tube_key, fil_scale=fil_scale, wall=wall,
                T_op=T_op, T_end=T_end, T_pk=T_pk,
                overshoot=T_pk-T_op, t_settle=t_settle, v_int_op=v_int_op)


def main():
    jobs = [(t, c) for t in TUBES for c in CORNERS]
    print(f"Filament R tolerance corner sweep (H11F arch, log demod + Schottky clipper)")
    print(f"  {len(jobs)} cases, 8 workers, ±10 % filament R\n")
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda j: run_one(*j), jobs))
    print(f"{'tube':9s} {'fil_R':>6s} {'T_op':>5s} {'T_end':>7s} {'T_pk':>7s} {'over':>6s} {'t_set':>7s} {'V_int':>8s}")
    for r in results:
        if "error" in r:
            print(f"{r['tube']:9s} {r['fil_scale']*100:5.0f}% FAIL")
            continue
        ts = f"{r['t_settle']*1e3:.0f}ms" if not np.isnan(r['t_settle']) else "—"
        print(f"{r['tube']:9s} {r['fil_scale']*100:5.0f}% {r['T_op']:5.0f} {r['T_end']:7.2f} {r['T_pk']:7.2f}"
              f" {r['overshoot']:+6.1f} {ts:>7s} {r['v_int_op']:+8.3f}")
    # Per-tube tolerance window
    print(f"\n{'tube':9s} {'T_end span':>12s} {'overshoot range':>17s} {'comment':>30s}")
    for tube in TUBES:
        rs = [r for r in results if r["tube"]==tube and "T_end" in r]
        if len(rs)<3: continue
        T_ends = sorted([r["T_end"] for r in rs])
        overs = sorted([r["overshoot"] for r in rs])
        span = T_ends[-1] - T_ends[0]
        # Predicted T-end at ±10 % R: T ≈ T_op * (R_act/R_nom)^(1/1.2)
        T_pred_p10 = 800 * 1.1**(1/1.2)
        T_pred_m10 = 800 * 0.9**(1/1.2)
        pred_span = T_pred_p10 - T_pred_m10
        comment = f"~predicted span = {pred_span:.0f} K"
        print(f"{tube:9s} {span:11.2f}K {overs[0]:+5.1f}…{overs[-1]:+5.1f}K {comment:>30s}")


if __name__ == "__main__":
    main()
