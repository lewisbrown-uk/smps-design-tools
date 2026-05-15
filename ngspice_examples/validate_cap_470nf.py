"""Validate C_AP = 470 nF (Murata GRM31C5C1E474JE01L, 1206 C0G) across the
three tubes and JFET V_p corners.

For each (tube, V_p), runs a 5-second closed-loop transient with:
  - C_AP = 470 nF (10x default 100 nF)
  - No soft-start (v_preset=0, t_ramp=0) -- the lever we're testing is the
    all-pass corner placement, not preset injection
  - Default beta = 2.2 mA/V^2

Reports per run:
  - V_ctl_OP                (last 50 ms mean of v_ctl) -- must lie in [-2.5, +2.5]
  - V_ctl_peak              (worst-case excursion -- check clamp activity)
  - t_settle_5K, t_settle_10K
  - R_fil_peak, R_fil_final, R_fil_target
  - T_peak, T_final, target T
  - V_fil_rms, I_fil_rms over last 50 ms
  - "ok" flag: bridge converged AND V_ctl within clamps

CSV output: cap_470nf_results.csv
"""
from __future__ import annotations
import sys
import csv
import time
import numpy as np
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from test_closed_loop import TUBES, run_one, metrics, T_OP_TARGET

# JFET V_p corners
VP_CORNERS = [
    ("typ", -1.5),
    ("max", -3.0),   # most-negative V_p; widest pinch-off; tightest clamp margin
]

# Cap under test
C_AP_NEW = 470e-9

CLAMP_LO, CLAMP_HI = -2.5, 2.5


def run_case(tube_name, vp_label, vp_value):
    spec = TUBES[tube_name]
    mc = {"r_amb": spec["r_amb"],
          "sigma_eps_A": spec["sigma_eps_A"],
          "c_th": spec["c_th"],
          "r_top_ref": spec["r_top_ref"],
          "r_bot_ref": spec["r_bot_ref"],
          "r_sense":   spec["r_sense"],
          "c_ap": C_AP_NEW,
          "jfet_vp": vp_value}
    if spec.get("booster"):        mc["booster"] = True
    if spec.get("wien_alpha") is not None: mc["wien_alpha"] = spec["wien_alpha"]
    if spec.get("buf_fb1") is not None:    mc["buf_fb1"] = spec["buf_fb1"]
    if spec.get("buf_fb_ap") is not None:  mc["buf_fb_ap"] = spec["buf_fb_ap"]
    if spec.get("v_buf") is not None:      mc["v_buf"] = spec["v_buf"]
    if spec.get("ce_buf"):                 mc["ce_buf"] = True
    if spec.get("mos_buf"):                mc["mos_buf"] = True

    label = f"cap470_{tube_name}_vp{vp_label}"
    t0 = time.time()
    r = run_one(label, v_preset=0.0, t_ramp=0.0,
                r_int_scale=spec["r_int_scale"], mc=mc)
    wall = time.time() - t0
    m = metrics(r, target_T=spec["T_op"])

    t = r["t"]
    late = t > (t[-1] - 0.05)
    t_late = t[late]
    v_ctl_op   = float(np.trapezoid(r["v_ctl"][late], t_late) / (t_late[-1] - t_late[0]))
    v_ctl_peak = float(np.max(np.abs(r["v_ctl"])))
    v_fil      = r["v_osc"] - r["v_A"]
    v_fil_rms  = float(np.sqrt(np.trapezoid(v_fil[late]**2, t_late) / (t_late[-1] - t_late[0])))

    r_fil_peak  = float(np.max(r["R"]))
    r_fil_final = float(r["R"][-1])

    clamp_ok = CLAMP_LO < v_ctl_op < CLAMP_HI
    bridge_ok = abs(r_fil_final - spec["R_op"]) / spec["R_op"] < 0.05  # within 5% of target
    ok = clamp_ok and bridge_ok

    return {
        "tube":         spec["name"],
        "vp_label":     vp_label,
        "vp_value":     vp_value,
        "ok":           ok,
        "clamp_ok":     clamp_ok,
        "bridge_ok":    bridge_ok,
        "v_ctl_OP":     v_ctl_op,
        "v_ctl_peak":   v_ctl_peak,
        "t_settle_5K":  m["t_settle_5K"],
        "t_settle_10K": m["t_settle_10K"],
        "t_target_95":  m["t_95target"],
        "T_peak":       m["T_peak"],
        "T_final":      m["T_final"],
        "T_target":     spec["T_op"],
        "R_fil_peak":   r_fil_peak,
        "R_fil_final":  r_fil_final,
        "R_fil_target": spec["R_op"],
        "V_fil_rms":    v_fil_rms,
        "wall_s":       wall,
    }


def main():
    # ILC1-1/7 done in first run; IV-6 V_p=-1.5 done in serial run; re-run the
    # remaining 3 mos_buf cases in parallel (memory is fine now with .save).
    cases = [("iv6", "max", -3.0), ("ilc11_8", "typ", -1.5), ("ilc11_8", "max", -3.0)]
    print(f"Running {len(cases)} cases in parallel (C_AP=470nF, no soft-start, .save enabled)", flush=True)
    rows = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=len(cases)) as ex:
        futures = {ex.submit(run_case, *c): c for c in cases}
        for fut in as_completed(futures):
            try:
                m = fut.result()
            except Exception as e:
                t_, l_, v_ = futures[fut]
                print(f"  FAIL  {t_} vp={l_}({v_}): {e}", flush=True)
                continue
            rows.append(m)
            tag = "OK " if m["ok"] else "FAIL"
            print(f"  {tag}  {m['tube']:9s} V_p={m['vp_value']:+.1f}V  "
                  f"V_ctl_OP={m['v_ctl_OP']:+.2f}V  V_ctl_pk={m['v_ctl_peak']:+.2f}V  "
                  f"t_settle_5K={m['t_settle_5K']*1e3:.0f}ms  "
                  f"R_final={m['R_fil_final']:.2f}/{m['R_fil_target']:.0f}Ω  "
                  f"T_final={m['T_final']:.0f}/{m['T_target']:.0f}K  "
                  f"R_pk={m['R_fil_peak']:.1f}Ω  ({m['wall_s']/60:.1f} min)",
                  flush=True)

    rows.sort(key=lambda x: (x["tube"], x["vp_value"]))
    keys = ["tube", "vp_label", "vp_value", "ok", "clamp_ok", "bridge_ok",
            "v_ctl_OP", "v_ctl_peak",
            "t_settle_5K", "t_settle_10K", "t_target_95",
            "T_peak", "T_final", "T_target",
            "R_fil_peak", "R_fil_final", "R_fil_target",
            "V_fil_rms", "wall_s"]
    out = HERE / "cap_470nf_results.csv"
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys); w.writeheader()
        for r in rows: w.writerow({k: r[k] for k in keys})

    print(f"\nTotal wall time: {(time.time()-t0)/60:.1f} min")
    print(f"Wrote {out}")
    n_ok = sum(1 for r in rows if r["ok"])
    print(f"Verdict: {n_ok}/{len(rows)} cases OK")
    return 0 if n_ok == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
