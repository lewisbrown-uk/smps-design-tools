"""Generalized cold-start diagnostic: any tube, both V_p variants, with
Level 1 MOSFET swap auto-applied for mos_buf tubes (calibrated to 1%
against manufacturer subcircuits on IV-6 V_p=-3 V).

Captures clamp-diode currents and integrator internal nodes, saves
per-(tube, V_p) .npz for downstream charting.
"""
import sys, time, subprocess
import numpy as np
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from test_closed_loop import TUBES, make_netlist, WORK
from validate_cap_470nf_iv6max_level1 import swap_to_level1
from diag_ilc7_peak import patch_extra_signals

C_AP_NEW = 470e-9


def run_case(tube_name, vp_label, vp_value):
    spec = TUBES[tube_name]
    mc = {"r_amb": spec["r_amb"], "sigma_eps_A": spec["sigma_eps_A"],
          "c_th": spec["c_th"], "r_top_ref": spec["r_top_ref"],
          "r_bot_ref": spec["r_bot_ref"], "r_sense": spec["r_sense"],
          "c_ap": C_AP_NEW, "jfet_vp": vp_value}
    if spec.get("booster"):                mc["booster"] = True
    if spec.get("buf_fb1") is not None:    mc["buf_fb1"] = spec["buf_fb1"]
    if spec.get("buf_fb_ap") is not None:  mc["buf_fb_ap"] = spec["buf_fb_ap"]
    if spec.get("v_buf") is not None:      mc["v_buf"] = spec["v_buf"]
    if spec.get("ce_buf"):                 mc["ce_buf"] = True
    if spec.get("mos_buf"):                mc["mos_buf"] = True

    label = f"diag_{tube_name}_peak_vp{vp_label}"
    cir = WORK / f"{label}.cir"
    dat = WORK / f"{label}.data"
    raw = make_netlist(dat, v_preset=0.0, t_ramp=0.0,
                       r_int_scale=spec["r_int_scale"], mc=mc)
    patched = patch_extra_signals(raw)
    if spec.get("mos_buf"):
        patched = swap_to_level1(patched)
    cir.write_text(patched)

    t0 = time.time()
    res = subprocess.run(["ngspice", "-b", cir.name],
                         cwd=WORK, capture_output=True, text=True)
    wall = time.time() - t0
    if res.returncode != 0:
        print("STDERR tail:", res.stderr[-2000:])
        raise RuntimeError(f"ngspice failed for {label}")

    d = np.loadtxt(dat)
    try: dat.unlink()
    except OSError: pass
    cols = ["v_osc_drive", "v_ap_drive", "node_A", "node_B", "n_diff",
            "n_demout", "v_ctl", "v_int_out", "T_node", "r_fil",
            "i_clamp_lo", "i_clamp_hi", "n_int_minus", "n_int_pidp"]
    r = {"t": d[:, 0]}
    for i, c in enumerate(cols):
        r[c] = d[:, 2*i + 1]
    npz = HERE / f"diag_{tube_name}_peak_vp{vp_label}.npz"
    np.savez(npz, **r)

    # Peak summary
    i_min = np.argmin(r["v_ctl"])
    late = r["t"] > (r["t"][-1] - 0.05)
    v_ctl_op = float(np.trapezoid(r["v_ctl"][late], r["t"][late]) / (r["t"][late][-1] - r["t"][late][0]))
    T_peak = float(r["T_node"].max())
    above = r["T_node"] > spec["T_op"]
    if above.any():
        idx = np.where(above)[0]
        t_enter = r["t"][idx[0]]; t_exit = r["t"][idx[-1]+1] if idx[-1]+1 < len(r["t"]) else r["t"][-1]
        dur_above = t_exit - t_enter
    else:
        dur_above = 0
    print(f"  {tube_name:9s} V_p={vp_value:+.1f}V  wall={wall/60:.1f} min  "
          f"V_ctl_min={r['v_ctl'][i_min]:+.3f}V at t={r['t'][i_min]*1e3:.1f}ms  "
          f"V_ctl_OP={v_ctl_op:+.3f}V  "
          f"T_peak={T_peak:.1f}K (+{T_peak-spec['T_op']:.1f}K)  "
          f"t_above_T_op={dur_above*1e3:.0f}ms  "
          f"saved {npz.name}", flush=True)
    return tube_name, vp_label


def main():
    cases = [(tube, lbl, v) for tube in ("iv6", "ilc11_8")
             for lbl, v in (("typ", -1.5), ("max", -3.0))]
    print(f"Running {len(cases)} cases in parallel (C_AP=470nF, Level 1 MOSFETs)", flush=True)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=len(cases)) as ex:
        futs = {ex.submit(run_case, t, l, v): (t, l, v) for t, l, v in cases}
        for fut in as_completed(futs):
            try:
                fut.result()
            except Exception as e:
                t, l, v = futs[fut]
                print(f"  FAIL {t} V_p={v}: {e}", flush=True)
    print(f"\nTotal wall: {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
