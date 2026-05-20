"""Corner sweep for the V_TO-tracking + C_HF=1n architecture, per tube.

Sweeps the three filament parameters at their lo/hi extrema:
  - k_r_amb       (R at ambient: cold-resistance variation per tube spec)
  - k_sigma_eps_A (radiative cooling coefficient)
  - k_c_th        (thermal capacity)

2^3 = 8 corners × 4 tubes = 32 runs. Verifies T_peak overshoot and
T_end accuracy across realistic part-to-part variation.

Bands are ±15-20% on each, matching the existing sweep_corners ranges
in test_closed_loop.py.
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

tcl.T_END = 2.5
TUBES = ("iv18", "iv6", "ilc11_7", "ilc11_8")
BANDS = {
    "k_r_amb":       (0.85, 1.15),
    "k_sigma_eps_A": (0.80, 1.20),
    "k_c_th":        (0.85, 1.15),
}


def run_one(tube_key, corner_label, corner_mc):
    spec = tcl.TUBES[tube_key]
    mc = {k: spec[k] for k in ("r_amb", "sigma_eps_A", "c_th",
                                "r_top_ref", "r_bot_ref", "r_sense")}
    mc["t_rail_ramp"] = 100e-6
    for k in ("booster", "ce_buf", "mos_buf"):
        if spec.get(k): mc[k] = True
    for k in ("buf_fb1", "buf_fb_ap", "v_buf", "c_ap"):
        if spec.get(k) is not None: mc[k] = spec[k]
    mc.update(corner_mc)
    cir = tcl.WORK / f"corner_{tube_key}_{corner_label}.cir"
    dat = tcl.WORK / f"corner_{tube_key}_{corner_label}.data"
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
        return dict(tube=tube_key, label=corner_label, error=res.stderr[-300:], wall=wall)
    d = np.loadtxt(dat)
    t = d[:, 0]; T = d[:, 17]; v_int = d[:, 15]
    late = t > t[-1] - 0.1
    T_end  = float(np.mean(T[late]))
    T_peak = float(np.max(T))
    v_int_op = float(np.mean(v_int[late]))
    # Target T scales as ((R_op·0.99)/(R_amb·k_r_amb))^(1/1.2)·T_amb
    # Per-tube R_op_ref calc: R_op_eff = R_amb · (T_op/T_amb)^fil_exp
    T_target_perturbed = 300.0 * (spec["R_op"] * 0.99 / (spec["r_amb"] * corner_mc["k_r_amb"])) ** (1.0/1.2)
    try: dat.unlink()
    except OSError: pass
    return dict(tube=tube_key, label=corner_label, wall=wall,
                T_op_nominal=spec["T_op"],
                T_target_perturbed=T_target_perturbed,
                T_end=T_end, T_peak=T_peak,
                T_err_from_nominal=T_end - spec["T_op"],
                T_err_from_perturbed=T_end - T_target_perturbed,
                v_int_op=v_int_op,
                **corner_mc)


def main():
    print(f"Per-tube 2^3 corner sweep (V_TO-tracking + C_HF=1n arch)")
    print(f"  Bands: k_r_amb {BANDS['k_r_amb']}, k_sigma {BANDS['k_sigma_eps_A']}, k_cth {BANDS['k_c_th']}\n")
    keys = list(BANDS.keys())
    jobs = []
    for tube in TUBES:
        for combo in itertools.product(*[BANDS[k] for k in keys]):
            mc = dict(zip(keys, combo))
            label = "".join(("L" if mc[k]==BANDS[k][0] else "H") for k in keys)
            jobs.append((tube, label, mc))
    print(f"Running {len(jobs)} cases with workers=12...")
    with ThreadPoolExecutor(max_workers=12) as ex:
        results = list(ex.map(lambda j: run_one(*j), jobs))

    # Per-tube summary
    print()
    print(f"{'tube':8s}  {'T_op':>5s}  {'T_end_min':>9s}  {'T_end_max':>9s}  "
          f"{'T_pk_max':>8s}  {'overshoot_max':>13s}  {'T_err_perturbed_range':>22s}")
    for tube in TUBES:
        r = [x for x in results if x["tube"] == tube and "T_end" in x]
        if not r:
            print(f"{tube:8s}  FAIL")
            continue
        T_ends = np.array([x["T_end"] for x in r])
        T_peaks = np.array([x["T_peak"] for x in r])
        overshoots = T_peaks - r[0]["T_op_nominal"]
        T_err_perturbed = np.array([x["T_err_from_perturbed"] for x in r])
        print(f"{tube:8s}  {r[0]['T_op_nominal']:5.0f}  {T_ends.min():9.2f}  {T_ends.max():9.2f}  "
              f"{T_peaks.max():8.2f}  {overshoots.max():+12.1f}  "
              f"{T_err_perturbed.min():+7.1f}…{T_err_perturbed.max():+5.1f}")

    # Detailed table: rows per corner per tube
    print()
    print("Detailed (LLL/LLH/.../HHH — k_r_amb, k_sigma, k_cth letters):")
    print(f"{'tube':8s}  {'corner':6s}  {'T_end':>7s}  {'T_pk':>7s}  {'overshoot':>9s}  {'T_err_pert':>10s}")
    for tube in TUBES:
        r = sorted([x for x in results if x["tube"] == tube and "T_end" in x],
                   key=lambda x: x["label"])
        for x in r:
            print(f"{x['tube']:8s}  {x['label']:6s}  {x['T_end']:7.2f}  {x['T_peak']:7.2f}  "
                  f"{x['T_peak']-x['T_op_nominal']:+9.2f}  {x['T_err_from_perturbed']:+10.2f}")


if __name__ == "__main__":
    main()
