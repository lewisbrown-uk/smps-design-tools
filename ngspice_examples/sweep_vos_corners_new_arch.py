"""Vos corner sweep for the NMOS+level-shift+V_TO-tracking architecture
with the new C_HF=1n (HF pole >100 Hz on all tubes).

Two studies per tube:
1. 2^4 corners on (vos_ap, vos_diff, vos_dem, vos_int) at ±1.5 mV
   — TLV9154 worst-case on all four, mostly diagnostic.
   This confirms what the dominant Vos contributors are.
2. Realistic: vos_ap, vos_diff at TLV9154 (±1.5 mV corners), vos_dem and
   vos_int held at chopper level (5 µV, current shipping default).
   This is the actual T-error budget the design will deliver.
3. Per-tube marginal sensitivity of the NEW vos_sum (XU_sum DC level
   shifter introduced in the V_TO-tracking arch) — ±1.5 mV.

T_end is the loop's settled temperature; T_target is the per-tube T_op
(800 K nominal). T_error = T_end - T_op.
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

tcl.T_END = 3.0  # enough to settle past cold-start
VOS_MAX = 1.5e-3  # TLV9154 typical worst-case Vos
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
    if extra:
        mc.update(extra)
    return mc, spec


def run_one(tube_key, label, extra_mc):
    mc, spec = build_mc(tube_key, extra=extra_mc)
    cir = tcl.WORK / f"vos_{tube_key}_{label}.cir"
    dat = tcl.WORK / f"vos_{tube_key}_{label}.data"
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
    T_peak = float(np.max(T))
    v_int_op = float(np.mean(v_int[late]))
    try: dat.unlink()
    except OSError: pass
    return dict(tube=tube_key, label=label, wall=wall, T_op=spec["T_op"],
                T_end=T_end, T_peak=T_peak, T_error=T_end-spec["T_op"],
                v_int_op=v_int_op, **extra_mc)


def study1_full_2to4_corners():
    """2^4 corners on (vos_ap, vos_diff, vos_dem, vos_int) at ±1.5 mV.
    16 corners × 4 tubes = 64 runs."""
    print("="*78)
    print("Study 1: 2^4 corners — (vos_ap, vos_diff, vos_dem, vos_int) at ±1.5 mV")
    print("This is the worst-case 'what if EVERYTHING is TLV9154' stress test.")
    print("="*78)
    keys = ["vos_ap", "vos_diff", "vos_dem", "vos_int"]
    jobs = []
    for tube in TUBES:
        for combo in itertools.product([-VOS_MAX, +VOS_MAX], repeat=4):
            mc = dict(zip(keys, combo))
            sign = lambda v: "+" if v > 0 else "-"
            label = "".join(sign(v) for v in combo)
            jobs.append((tube, label, mc))
    print(f"Running {len(jobs)} cases with workers=12...")
    with ThreadPoolExecutor(max_workers=12) as ex:
        results = list(ex.map(lambda j: run_one(*j), jobs))
    # Per-tube summary
    print()
    print(f"{'tube':8s} {'T_op':>5s} {'T_end_mean':>11s} {'T_end_min':>10s} {'T_end_max':>10s} {'T_err_range':>12s}")
    for tube in TUBES:
        r = [x for x in results if x["tube"] == tube and "T_end" in x]
        if not r:
            print(f"{tube:8s} FAIL")
            continue
        T_ends = np.array([x["T_end"] for x in r])
        T_errs = np.array([x["T_error"] for x in r])
        print(f"{tube:8s} {r[0]['T_op']:5.0f} {T_ends.mean():11.2f} {T_ends.min():10.2f} {T_ends.max():10.2f} "
              f"{T_errs.min():+5.1f}…{T_errs.max():+5.1f}")
    # Identify dominant contributor: marginal sensitivity (mean T_err at +Vos vs -Vos for each variable)
    print()
    print("Dominant contributor (marginal sensitivity, K per +1.5 mV step):")
    print(f"{'tube':8s}  {'vos_ap':>8s}  {'vos_diff':>9s}  {'vos_dem':>8s}  {'vos_int':>8s}")
    for tube in TUBES:
        r = [x for x in results if x["tube"] == tube and "T_end" in x]
        if not r: continue
        sens = {}
        for k in keys:
            plus = np.mean([x["T_end"] for x in r if x[k] > 0])
            minus = np.mean([x["T_end"] for x in r if x[k] < 0])
            sens[k] = plus - minus
        print(f"{tube:8s}  {sens['vos_ap']:+8.2f}  {sens['vos_diff']:+9.2f}  "
              f"{sens['vos_dem']:+8.2f}  {sens['vos_int']:+8.2f}")
    return results


def study2_realistic_chopper():
    """Realistic shipping config: vos_ap and vos_diff at TLV9154 (±1.5 mV
    corners — 4 corners), vos_dem and vos_int at chopper (5 µV — uses default).
    4 corners × 4 tubes = 16 runs."""
    print()
    print("="*78)
    print("Study 2: realistic shipping — vos_ap, vos_diff corners (±1.5 mV);")
    print("         vos_dem, vos_int at chopper (5 µV, default)")
    print("="*78)
    keys = ["vos_ap", "vos_diff"]
    jobs = []
    for tube in TUBES:
        for combo in itertools.product([-VOS_MAX, +VOS_MAX], repeat=2):
            mc = dict(zip(keys, combo))
            sign = lambda v: "+" if v > 0 else "-"
            label = "ad" + "".join(sign(v) for v in combo)
            jobs.append((tube, label, mc))
    print(f"Running {len(jobs)} cases with workers=12...")
    with ThreadPoolExecutor(max_workers=12) as ex:
        results = list(ex.map(lambda j: run_one(*j), jobs))
    print()
    print(f"{'tube':8s} {'T_op':>5s} {'T_end_min':>10s} {'T_end_max':>10s} {'T_err_range':>12s}")
    for tube in TUBES:
        r = [x for x in results if x["tube"] == tube and "T_end" in x]
        if not r:
            print(f"{tube:8s} FAIL")
            continue
        T_ends = np.array([x["T_end"] for x in r])
        T_errs = np.array([x["T_error"] for x in r])
        print(f"{tube:8s} {r[0]['T_op']:5.0f} {T_ends.min():10.2f} {T_ends.max():10.2f} "
              f"{T_errs.min():+5.1f}…{T_errs.max():+5.1f}")
    return results


def study3_vos_sum_marginal():
    """Test if the NEW XU_sum stage introduces meaningful Vos sensitivity.
    Sweep vos_sum at ±1.5 mV with all else at default (chopper for dem/int).
    2 cases × 4 tubes = 8 runs."""
    print()
    print("="*78)
    print("Study 3: vos_sum (NEW XU_sum stage) marginal sensitivity, ±1.5 mV")
    print("="*78)
    jobs = []
    for tube in TUBES:
        for v in [-VOS_MAX, +VOS_MAX]:
            jobs.append((tube, f"sum{'+' if v>0 else '-'}", {"vos_sum": v}))
    print(f"Running {len(jobs)} cases with workers=8...")
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda j: run_one(*j), jobs))
    print()
    print(f"{'tube':8s} {'T_op':>5s} {'T_end-':>8s} {'T_end+':>8s} {'ΔT/Vos':>10s}")
    for tube in TUBES:
        rm = [x for x in results if x["tube"] == tube and x.get("vos_sum", 0) < 0]
        rp = [x for x in results if x["tube"] == tube and x.get("vos_sum", 0) > 0]
        if not rm or not rp or "T_end" not in rm[0] or "T_end" not in rp[0]:
            print(f"{tube:8s} FAIL")
            continue
        T_minus = rm[0]["T_end"]; T_plus = rp[0]["T_end"]
        print(f"{tube:8s} {rm[0]['T_op']:5.0f} {T_minus:8.2f} {T_plus:8.2f}  {(T_plus-T_minus):+10.2f}K/3mV")
    return results


def main():
    print(f"Vos sweep on the V_TO-tracking arch (C_HF=1nF, 4 tubes)\n")
    r1 = study1_full_2to4_corners()
    r2 = study2_realistic_chopper()
    r3 = study3_vos_sum_marginal()
    # Compact summary
    print()
    print("="*78)
    print("VERDICT")
    print("="*78)
    for tube in TUBES:
        r1t = [x for x in r1 if x["tube"] == tube and "T_end" in x]
        r2t = [x for x in r2 if x["tube"] == tube and "T_end" in x]
        if not r1t or not r2t: continue
        rng1 = max(x["T_error"] for x in r1t) - min(x["T_error"] for x in r1t)
        rng2 = max(x["T_error"] for x in r2t) - min(x["T_error"] for x in r2t)
        print(f"  {tube:8s}  worst-case (all TLV9154): {rng1:5.1f}K span    "
              f"realistic (chopper dem/int): {rng2:5.1f}K span")


if __name__ == "__main__":
    main()
