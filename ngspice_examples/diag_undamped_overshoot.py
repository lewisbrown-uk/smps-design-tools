"""Investigate the thermal overshoot mechanism on IV-6 and ILC1-1/8 at
V_p=-1.5 V. These cases show large overshoot (+51 K and +65 K) without
significant clamp wind-up, so the mechanism differs from ILC1-1/7.

Hypothesis: integrator response lag. During cold-start the integrator drives
V_int_out high (max heating). When T reaches T_op the bridge balances and
demod_dc crosses zero, but the integrator's "wound-up" value can only
unwind at a rate set by the loop. Meanwhile the filament continues warming
because the integrator's current V_int_out still commands P_in > P_loss(T_op).

This script:
  1. Loads existing .npz for both V_p=-1.5 cases
  2. Computes demod_dc DC content (LP-filter the n_demout signal)
  3. Plots V_int_out, V_int_out time-derivative, demod_dc, T, R_fil
     during the overshoot phase (0-3000 ms)
  4. Fits an exponential to the T-decay tail to extract effective tau
  5. Compares to the integrator and thermal time constants in isolation
"""
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from test_closed_loop import TUBES, TAU_TH


def lowpass_decimate(t, y, npts=4000):
    """Decimate the long sim to a manageable plot resolution. Uses simple
    block-mean (averages within each block) to suppress the 1 kHz bootstrap
    AC content and reveal the DC loop trajectory."""
    n = len(t)
    block = max(1, n // npts)
    nblocks = n // block
    tt = t[:nblocks*block].reshape(nblocks, block).mean(axis=1)
    yy = y[:nblocks*block].reshape(nblocks, block).mean(axis=1)
    return tt, yy


def analyze(tube_key, color):
    spec = TUBES[tube_key]
    npz = HERE / f"diag_{tube_key}_peak_vptyp.npz"
    if not npz.exists():
        print(f"missing {npz.name}", file=sys.stderr); sys.exit(1)
    d = np.load(npz)
    r = {k: d[k] for k in d.files}
    t = r["t"]
    T_op = spec["T_op"]
    name = spec["name"]

    # Decimate / LP-filter
    t_dc, v_int_dc = lowpass_decimate(t, r["v_int_out"])
    _,    n_dem_dc = lowpass_decimate(t, r["n_demout"])
    _,    T_dc     = lowpass_decimate(t, r["T_node"])
    _,    R_dc     = lowpass_decimate(t, r["r_fil"])

    # Find the overshoot peak in T and the t at peak
    i_T_peak = np.argmax(T_dc)
    t_T_peak = t_dc[i_T_peak]
    T_peak = T_dc[i_T_peak]

    # Fit exponential decay to T(t) - T_op after the peak, over the next 2 seconds
    end_t = min(t_dc[-1], t_T_peak + 2.0)
    mask = (t_dc > t_T_peak) & (t_dc < end_t) & (T_dc > T_op + 0.5)
    if mask.sum() > 10:
        # ln(T - T_op) = ln(T_peak - T_op) - (t - t_peak)/tau
        x = t_dc[mask] - t_T_peak
        y = np.log(T_dc[mask] - T_op)
        # least-squares fit
        a, b = np.polyfit(x, y, 1)  # y = a*x + b
        tau_decay = -1.0 / a
    else:
        tau_decay = float("nan")

    # Find time when n_demout DC crosses zero (post cold-start)
    # Restrict to t > 100 ms (skip startup transients)
    late_mask = t_dc > 0.1
    sign = np.sign(n_dem_dc[late_mask])
    crossings = np.where(np.diff(sign) != 0)[0]
    t_zero = t_dc[late_mask][crossings[0]+1] if len(crossings) else float("nan")

    # V_int_out's slope at the zero-crossing of demod — defines how fast
    # the integrator can unwind once the bridge balances
    if not np.isnan(t_zero):
        i_zero = np.argmin(np.abs(t_dc - t_zero))
        i_lo = max(0, i_zero - 5); i_hi = min(len(t_dc)-1, i_zero + 5)
        slope_zero = (v_int_dc[i_hi] - v_int_dc[i_lo]) / (t_dc[i_hi] - t_dc[i_lo])
    else:
        slope_zero = float("nan")

    # Loop integrator constants
    R_INT_BASE = 100e3
    C_INT_BASE = 1.0 / (2 * np.pi * 5.0 * R_INT_BASE)
    r_int_scale = spec["r_int_scale"]
    R_INT = R_INT_BASE * r_int_scale
    C_INT = C_INT_BASE
    Ki = 1.0 / (R_INT * C_INT)

    print(f"\n=== {name}  V_p=-1.5 V ===")
    print(f"  T_peak           = {T_peak:.2f} K  (+{T_peak-T_op:.2f} K) at t={t_T_peak*1e3:.1f} ms")
    print(f"  Thermal time constant TAU_TH = {TAU_TH*1e3:.1f} ms (filament radiative)")
    print(f"  Integrator R_INT = {R_INT/1e3:.1f} kΩ,  C_INT = {C_INT*1e6:.2f} µF,  Ki = {Ki:.2f}/s")
    print(f"  bridge_demod_dc zero-crossing (post-startup): t = {t_zero*1e3:.0f} ms")
    print(f"  V_int_out slope at zero-crossing = {slope_zero:.3f} V/s")
    print(f"  T-decay time constant (fitted exp): tau_decay = {tau_decay*1e3:.0f} ms")
    print(f"    ratio tau_decay / TAU_TH = {tau_decay/TAU_TH:.2f}")
    print(f"    ratio tau_decay / (1/Ki) = {tau_decay*Ki:.2f}")

    return dict(t=t_dc, v_int=v_int_dc, n_dem=n_dem_dc, T=T_dc, R=R_dc,
                t_T_peak=t_T_peak, T_peak=T_peak, tau_decay=tau_decay,
                t_zero=t_zero, name=name, color=color, T_op=T_op, R_op=spec["R_op"])


def main():
    runs = []
    for tk, c in (("iv6", "C0"), ("ilc11_8", "C1")):
        runs.append(analyze(tk, c))

    # Plot 0-3 s window for both tubes
    fig, axes = plt.subplots(4, 1, figsize=(12, 11), sharex=True)
    fig.suptitle("Underdamped thermal overshoot: V_p=-1.5 V\n"
                 "(IV-6 and ILC1-1/8: clamp barely engaged, overshoot is integrator-response lag)",
                 fontsize=12)
    for r in runs:
        t_ms = r["t"] * 1e3
        mask = r["t"] <= 3.0
        axes[0].plot(t_ms[mask], r["T"][mask], color=r["color"], lw=0.9, label=r["name"])
        axes[0].axhline(r["T_op"], color=r["color"], lw=0.5, ls=":", alpha=0.7)
        axes[1].plot(t_ms[mask], r["R"][mask], color=r["color"], lw=0.9, label=r["name"])
        axes[1].axhline(r["R_op"], color=r["color"], lw=0.5, ls=":", alpha=0.7)
        axes[2].plot(t_ms[mask], r["v_int"][mask], color=r["color"], lw=0.9, label=r["name"])
        axes[3].plot(t_ms[mask], r["n_dem"][mask]*1e3, color=r["color"], lw=0.9, label=r["name"])
        # Mark T-peak time and demod zero-crossing
        axes[0].axvline(r["t_T_peak"]*1e3, color=r["color"], lw=0.6, ls="--", alpha=0.5)
        if not np.isnan(r["t_zero"]):
            axes[3].axvline(r["t_zero"]*1e3, color=r["color"], lw=0.6, ls="--", alpha=0.5)
            axes[3].annotate(f"  demod=0  ({r['name']})",
                            xy=(r["t_zero"]*1e3, 0), color=r["color"], fontsize=8, va="bottom")

    axes[3].axhline(0, color="k", lw=0.4)
    axes[0].set_ylabel("T_filament [K]")
    axes[1].set_ylabel("R_fil [Ω]")
    axes[2].set_ylabel("V_int_out [V]")
    axes[3].set_ylabel("demod_dc [mV] (LP-filtered)")
    axes[3].set_xlabel("Time [ms]")
    for ax in axes:
        ax.grid(True, alpha=0.3)
        ax.legend(loc="best", fontsize=9)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    out = HERE / "diag_undamped_overshoot.png"
    fig.savefig(out, dpi=130)
    print(f"\nPlot: {out}")


if __name__ == "__main__":
    main()
