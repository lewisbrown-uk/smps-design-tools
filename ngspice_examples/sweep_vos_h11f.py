"""Vos corner sweep for the H11F arch (replaces sweep_vos_corners_new_arch.py).

The XU_sum stage was removed during the H11F retrofit (committed 61737a6) —
the JFET arch's vos_sum no longer exists. The new XU_vi op-amp in the V→I
converter (drives the H11F LED) gets a vos parameter in test_closed_loop
under its default opamp_v (TLV9154 grade); test that here too.

Two studies per tube:
  1. 2^4 corners on (vos_ap, vos_diff, vos_dem, vos_int) at ±1.5 mV
  2. Realistic shipping: vos_ap, vos_diff at TLV9154 (±1.5 mV);
     vos_dem, vos_int at chopper (5 µV). 4 corners × 4 tubes.

Log demod with per-tube log_gain_K is enabled to match production.
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

tcl.T_END = 3.0
VOS_MAX = 1.5e-3
TUBES = ("iv18", "iv6", "ilc11_7", "ilc11_8")


def build_mc(tube_key, extra=None):
    spec = tcl.TUBES[tube_key]
    mc = {k: spec[k] for k in ("r_amb", "sigma_eps_A", "c_th",
                                "r_top_ref", "r_bot_ref", "r_sense")}
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
    if extra:
        mc.update(extra)
    return mc, spec


def run_one(tube_key, label, extra_mc):
    mc, spec = build_mc(tube_key, extra=extra_mc)
    cir = tcl.WORK / f"vosH_{tube_key}_{label}.cir"
    dat = tcl.WORK / f"vosH_{tube_key}_{label}.data"
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
        return dict(tube=tube_key, label=label, error=res.stderr[-300:], wall=wall)
    d = np.loadtxt(dat)
    t = d[:, 0]
    T = d[:, 17]
    v_int = d[:, 15]
    late = t > (t[-1] - 0.1)
    T_end = float(np.mean(T[late]))
    v_int_op = float(np.mean(v_int[late]))
    try: dat.unlink()
    except OSError: pass
    return dict(tube=tube_key, label=label, wall=wall, T_op=spec["T_op"],
                T_end=T_end, T_error=T_end-spec["T_op"],
                v_int_op=v_int_op, **extra_mc)


def study1():
    keys = ["vos_ap", "vos_diff", "vos_dem", "vos_int"]
    jobs = []
    for tube in TUBES:
        for combo in itertools.product([-VOS_MAX, +VOS_MAX], repeat=4):
            mc = dict(zip(keys, combo))
            label = "".join("p" if v>0 else "m" for v in combo)
            jobs.append((tube, label, mc))
    print(f"Study 1: 2^4 corners (all 4 op-amps at ±1.5 mV TLV9154)")
    print(f"  {len(jobs)} cases, 12 workers")
    with ThreadPoolExecutor(max_workers=12) as ex:
        results = list(ex.map(lambda j: run_one(*j), jobs))
    print(f"{'tube':8s} {'T_op':>5s} {'T_end_min':>10s} {'T_end_max':>10s} {'T_err_range':>15s}")
    for tube in TUBES:
        r = [x for x in results if x["tube"] == tube and "T_end" in x]
        if not r: print(f"{tube:8s} FAIL"); continue
        Te = np.array([x["T_end"] for x in r])
        Terr = np.array([x["T_error"] for x in r])
        print(f"{tube:8s} {r[0]['T_op']:5.0f} {Te.min():10.2f} {Te.max():10.2f} "
              f"{Terr.min():+6.2f}…{Terr.max():+6.2f}")
    print("\nDominant contributor (Δ T_end per +1.5 mV step, K):")
    print(f"{'tube':8s}  {'vos_ap':>8s}  {'vos_diff':>9s}  {'vos_dem':>8s}  {'vos_int':>8s}")
    for tube in TUBES:
        r = [x for x in results if x["tube"] == tube and "T_end" in x]
        if not r: continue
        sens = {}
        for k in keys:
            plus = np.mean([x["T_end"] for x in r if x[k] > 0])
            minus = np.mean([x["T_end"] for x in r if x[k] < 0])
            sens[k] = plus - minus
        print(f"{tube:8s}  {sens['vos_ap']:+8.3f}  {sens['vos_diff']:+9.3f}  "
              f"{sens['vos_dem']:+8.3f}  {sens['vos_int']:+8.3f}")
    return results


def study2():
    """Realistic: vos_ap, vos_diff at TLV9154 (±1.5 mV); vos_dem, vos_int chopper (5 µV default)."""
    keys = ["vos_ap", "vos_diff"]
    jobs = []
    for tube in TUBES:
        for combo in itertools.product([-VOS_MAX, +VOS_MAX], repeat=2):
            mc = dict(zip(keys, combo))
            label = "ad" + "".join("p" if v>0 else "m" for v in combo)
            jobs.append((tube, label, mc))
    print(f"\nStudy 2: realistic — vos_ap/vos_diff ±1.5 mV, dem/int chopper (5 µV)")
    print(f"  {len(jobs)} cases, 8 workers")
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda j: run_one(*j), jobs))
    print(f"{'tube':8s} {'T_op':>5s} {'T_end_min':>10s} {'T_end_max':>10s} {'T_err_range':>15s}")
    for tube in TUBES:
        r = [x for x in results if x["tube"] == tube and "T_end" in x]
        if not r: print(f"{tube:8s} FAIL"); continue
        Te = np.array([x["T_end"] for x in r])
        Terr = np.array([x["T_error"] for x in r])
        print(f"{tube:8s} {r[0]['T_op']:5.0f} {Te.min():10.2f} {Te.max():10.2f} "
              f"{Terr.min():+6.2f}…{Terr.max():+6.2f}")
    return results


def main():
    print(f"Vos corner sweep on H11F arch (log demod + Schottky clipper)\n")
    r1 = study1()
    r2 = study2()
    print("\n" + "="*72 + "\nVERDICT\n" + "="*72)
    for tube in TUBES:
        r1t = [x for x in r1 if x["tube"] == tube and "T_end" in x]
        r2t = [x for x in r2 if x["tube"] == tube and "T_end" in x]
        if not r1t or not r2t: continue
        rng1 = max(x["T_error"] for x in r1t) - min(x["T_error"] for x in r1t)
        rng2 = max(x["T_error"] for x in r2t) - min(x["T_error"] for x in r2t)
        print(f"  {tube:8s}  all-TLV9154 span: {rng1:5.2f} K   "
              f"shipping (chopper dem/int): {rng2:5.2f} K")


if __name__ == "__main__":
    main()
