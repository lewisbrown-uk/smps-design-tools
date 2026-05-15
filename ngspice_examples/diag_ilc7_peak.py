"""Investigate ILC1-1/7's V_ctl_pk = +3.48 V cold-start overshoot at both
V_p variants. Captures diode-clamp currents and integrator internal nodes,
plots the cold-start window.

C_AP=470nF, no soft-start, full T_END=5s but we focus the plot on the first
100 ms where the overshoot occurs.
"""
import sys, csv, time, re, subprocess
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from test_closed_loop import TUBES, make_netlist, metrics, WORK

C_AP_NEW = 470e-9

# Extra signals to capture for clamp-path debugging
EXTRA_SIGNALS = ["i(V_clamp_lo)", "i(V_clamp_hi)", "v(n_int_minus)", "v(n_int_pidp)"]


def patch_extra_signals(netlist_text):
    """Append EXTRA_SIGNALS to the .save and wrdata lines."""
    extras = " " + " ".join(EXTRA_SIGNALS)
    lines = []
    for line in netlist_text.splitlines():
        if line.startswith(".save "):
            line = line + extras
        elif line.startswith("wrdata "):
            line = line + extras
        lines.append(line)
    return "\n".join(lines)


def run_case(vp_label, vp_value):
    spec = TUBES["ilc11_7"]
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

    label = f"diag_ilc7_peak_vp{vp_label}"
    cir = WORK / f"{label}.cir"
    dat = WORK / f"{label}.data"
    raw = make_netlist(dat, v_preset=0.0, t_ramp=0.0,
                      r_int_scale=spec["r_int_scale"], mc=mc)
    cir.write_text(patch_extra_signals(raw))

    t0 = time.time()
    res = subprocess.run(["ngspice", "-b", cir.name],
                         cwd=WORK, capture_output=True, text=True)
    wall = time.time() - t0
    if res.returncode != 0:
        print("STDERR tail:", res.stderr[-2000:])
        raise RuntimeError(f"ngspice failed for {label}")
    d = np.loadtxt(dat)
    # keep dat file for further analysis

    # Column layout: 14 signals (10 original + 4 extra), wrdata writes t,v,t,v...
    # → 28 columns. Even indices = time, odd = value.
    cols = ["v_osc_drive", "v_ap_drive", "node_A", "node_B", "n_diff",
            "n_demout", "v_ctl", "v_int_out", "T_node", "r_fil",
            "i_clamp_lo", "i_clamp_hi", "n_int_minus", "n_int_pidp"]
    r = {"t": d[:, 0]}
    for i, c in enumerate(cols):
        r[c] = d[:, 2*i + 1]
    return vp_label, vp_value, wall, r


def main():
    cases = [("typ", -1.5), ("max", -3.0)]
    print(f"Running ILC1-1/7 V_p sweep with extra clamp signals", flush=True)
    runs = {}
    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = {ex.submit(run_case, lbl, v): (lbl, v) for lbl, v in cases}
        for fut in as_completed(futs):
            lbl, v, wall, r = fut.result()
            runs[lbl] = (v, wall, r)
            v_ctl_pk = np.max(r["v_ctl"])
            t_pk = r["t"][np.argmax(r["v_ctl"])]
            print(f"  V_p={v:+.1f}V  wall={wall/60:.1f} min  "
                  f"V_ctl_pk={v_ctl_pk:+.3f}V at t={t_pk*1e3:.2f}ms",
                  flush=True)

    # Plot cold-start window (0-100 ms) for both V_p side by side
    fig, axes = plt.subplots(4, 2, figsize=(13, 9), sharex='col')
    for col, lbl in enumerate(("typ", "max")):
        v, wall, r = runs[lbl]
        t_ms = r["t"] * 1e3
        # zoom to first 100 ms
        m = t_ms <= 100
        axes[0, col].set_title(f"ILC1-1/7  V_p={v:+.1f}V  C_AP=470nF  (cold-start window)")
        axes[0, col].plot(t_ms[m], r["v_ctl"][m], color="C4", lw=0.6, label="V_ctl")
        axes[0, col].plot(t_ms[m], -r["v_int_out"][m], color="C5", lw=0.6, ls="--", label="-V_int_out (expect = V_ctl)")
        axes[0, col].axhline(2.5, color="r", lw=0.5, ls=":", label="±clamp 2.5V")
        axes[0, col].axhline(-0.3, color="r", lw=0.5, ls=":")
        axes[0, col].set_ylabel("V [V]"); axes[0, col].grid(True, alpha=0.3); axes[0, col].legend(loc="best", fontsize=8)
        axes[1, col].plot(t_ms[m], r["v_int_out"][m], color="C0", lw=0.6, label="V_int_out")
        axes[1, col].axhline(2.5, color="r", lw=0.5, ls=":")
        axes[1, col].axhline(0.3, color="r", lw=0.5, ls=":", label="clamp_lo 0.3V")
        axes[1, col].set_ylabel("V_int_out [V]"); axes[1, col].grid(True, alpha=0.3); axes[1, col].legend(loc="best", fontsize=8)
        axes[2, col].plot(t_ms[m], r["i_clamp_lo"][m]*1e3, color="C1", lw=0.6, label="I(clamp_lo)")
        axes[2, col].plot(t_ms[m], r["i_clamp_hi"][m]*1e3, color="C2", lw=0.6, label="I(clamp_hi)")
        axes[2, col].set_ylabel("I_clamp [mA]"); axes[2, col].grid(True, alpha=0.3); axes[2, col].legend(loc="best", fontsize=8)
        axes[3, col].plot(t_ms[m], r["n_demout"][m]*1e3, color="C3", lw=0.6, label="n_demout (mV)")
        axes[3, col].set_ylabel("demod DC [mV]"); axes[3, col].set_xlabel("t [ms]"); axes[3, col].grid(True, alpha=0.3); axes[3, col].legend(loc="best", fontsize=8)
    fig.tight_layout()
    out_png = HERE / "diag_ilc7_peak.png"
    fig.savefig(out_png, dpi=110)
    print(f"\nPlot: {out_png}")

    # Peak summary: report V_ctl_min (deepest cold-start swing), the time it
    # occurs, V_int_out at that moment, and the clamp diode peak current.
    print("\n=== Peak analysis ===")
    for lbl, (v, wall, r) in runs.items():
        i_min = np.argmin(r["v_ctl"])
        i_max_hi = np.argmax(r["i_clamp_hi"])
        i_min_lo = np.argmin(r["i_clamp_lo"])
        # OP value (last 50 ms mean)
        late = r["t"] > (r["t"][-1] - 0.05)
        v_ctl_op   = float(np.trapezoid(r["v_ctl"][late], r["t"][late]) / (r["t"][late][-1] - r["t"][late][0]))
        v_int_op   = float(np.trapezoid(r["v_int_out"][late], r["t"][late]) / (r["t"][late][-1] - r["t"][late][0]))
        i_clamp_hi_op = float(np.trapezoid(r["i_clamp_hi"][late], r["t"][late]) / (r["t"][late][-1] - r["t"][late][0]))
        print(f"\n  V_p={v:+.1f} V:")
        print(f"    Cold-start kick (V_ctl most negative):")
        print(f"      V_ctl_min = {r['v_ctl'][i_min]:+.3f} V  at t={r['t'][i_min]*1e3:.2f} ms")
        print(f"      V_int_out @ that t = {r['v_int_out'][i_min]:+.3f} V  (clamp_hi=+2.5V)")
        print(f"      I_clamp_hi @ that t = {r['i_clamp_hi'][i_min]*1e3:+.3f} mA")
        print(f"    Peak clamp_hi current:")
        print(f"      I_clamp_hi_max = {r['i_clamp_hi'][i_max_hi]*1e3:+.3f} mA  at t={r['t'][i_max_hi]*1e3:.2f} ms")
        print(f"      V_int_out @ peak = {r['v_int_out'][i_max_hi]:+.3f} V")
        print(f"    Steady-state (last 50 ms mean):")
        print(f"      V_ctl_OP = {v_ctl_op:+.3f} V,  V_int_out_OP = {v_int_op:+.3f} V")
        print(f"      I_clamp_hi_OP = {i_clamp_hi_op*1e3:+.4f} mA  (>0 = diode conducting in steady state)")
        # Save run as npz for any further analysis
        npz = HERE / f"diag_ilc7_peak_vp{lbl}.npz"
        np.savez(npz, **{k: v_ for k, v_ in r.items()})
        print(f"    Saved {npz.name}")


if __name__ == "__main__":
    main()
