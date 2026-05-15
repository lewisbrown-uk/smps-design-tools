"""Plot the cold-start behaviour of ILC1-1/7 at C_AP=470nF, both V_p variants
overlaid. Highlights the three distinct phases:
    1. Slew    (0 -> ~12-23 ms): integrator ramps from 0 toward +2.5 V clamp
    2. Pinned  (~12-23 -> ~470-490 ms): V_int_out pinned at +3.34 V by clamp
                                       diode, filament heating at maximum
    3. Release / settle (~470-490 ms onward): diode comes out of conduction,
                                              V_int drifts to OP, bridge balances
Reads the .npz files saved by diag_ilc7_peak.py.
"""
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path
HERE = Path(__file__).resolve().parent

CLAMP_HI = 2.5
CLAMP_LO = 0.3
T_END_ZOOM = 2.000   # cover slew + pinned + release + settle (full cold-start arc)

cases = [("typ", -1.5, "C0"), ("max", -3.0, "C3")]
runs = {}
for lbl, v, _ in cases:
    npz = HERE / f"diag_ilc7_peak_vp{lbl}.npz"
    d = np.load(npz)
    runs[lbl] = {k: d[k] for k in d.files}
    print(f"{lbl} V_p={v}: {len(runs[lbl]['t'])} points")


def find_phases(r):
    """Identify slew-end and release-start times from clamp diode current."""
    t = r["t"]
    i_clamp = r["i_clamp_hi"]
    # Define clamp as "active" when i_clamp_hi > 1 mA
    active = i_clamp > 1e-3
    if not active.any():
        return None, None
    i_first = np.argmax(active)
    # last clamp-active sample before clamp drops back below 1 mA permanently
    # (find last True in active for the cold-start phase)
    # We look for the first False after the first True
    transitions = np.where(np.diff(active.astype(int)) == -1)[0]
    i_last = transitions[0] if len(transitions) else len(t) - 1
    return float(t[i_first]), float(t[i_last])


fig, axes = plt.subplots(4, 1, figsize=(12, 11), sharex=True)
fig.suptitle("ILC1-1/7  cold-start  (C_AP=470 nF, no soft-start)", fontsize=14)

# Shade the 'pinned' window for the V_p=-1.5 case (slowest release, defines envelope)
t_slew_typ, t_release_typ = find_phases(runs["typ"])
t_slew_max, t_release_max = find_phases(runs["max"])
print(f"V_p=-1.5: slew {t_slew_typ*1e3:.1f}->{t_release_typ*1e3:.1f} ms")
print(f"V_p=-3.0: slew {t_slew_max*1e3:.1f}->{t_release_max*1e3:.1f} ms")

for lbl, v, color in cases:
    r = runs[lbl]
    t_ms = r["t"] * 1e3
    mask = r["t"] <= T_END_ZOOM
    label = f"V_p={v:+.1f} V"

    axes[0].plot(t_ms[mask], r["v_ctl"][mask], color=color, lw=0.8, label=label)
    axes[1].plot(t_ms[mask], r["v_int_out"][mask], color=color, lw=0.8, label=label)
    axes[2].plot(t_ms[mask], r["i_clamp_hi"][mask]*1e3, color=color, lw=0.8, label=label)
    axes[3].plot(t_ms[mask], r["r_fil"][mask], color=color, lw=0.8, label=label)

# Annotate the V_p=-1.5 phase boundaries on row 0
for ax in axes:
    ax.axvspan(t_slew_typ*1e3, t_release_typ*1e3, color="0.85", alpha=0.5, zorder=0)
    ax.axvline(t_slew_typ*1e3, color="0.5", lw=0.6, ls="--")
    ax.axvline(t_release_typ*1e3, color="0.5", lw=0.6, ls="--")

# Clamp threshold lines on row 1
axes[1].axhline(CLAMP_HI, color="r", lw=0.7, ls=":", label="clamp_hi = +2.5 V")
axes[1].axhline(CLAMP_LO, color="r", lw=0.7, ls=":", label="clamp_lo = +0.3 V")
axes[1].axhline(3.343, color="r", lw=0.7, ls="-.", alpha=0.5, label="V_int@pinned = +3.34 V (op-amp + Dclamp eq.)")

# Phase labels (on the top panel)
y_top = axes[0].get_ylim()[1]
mid_slew = t_slew_typ * 1e3 / 2
mid_pinned = (t_slew_typ + t_release_typ) * 1e3 / 2
mid_release = (t_release_typ * 1e3 + T_END_ZOOM*1e3) / 2
axes[0].annotate("slew",    xy=(mid_slew,    0.5), ha="center", fontsize=9, color="0.3")
axes[0].annotate("pinned",  xy=(mid_pinned,  0.5), ha="center", fontsize=9, color="0.3")
axes[0].annotate("release / settle", xy=(mid_release, 0.5), ha="center", fontsize=9, color="0.3")

axes[0].set_ylabel("V_ctl (JFET gate) [V]")
axes[1].set_ylabel("V_int_out [V]")
axes[2].set_ylabel("I_clamp_hi [mA]")
axes[3].set_ylabel("R_fil [Ω]")
axes[3].set_xlabel("Time [ms]")

for ax in axes:
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best", fontsize=8)
axes[3].axhline(25, color="0.4", lw=0.6, ls="--", label="R_op = 25 Ω")
axes[3].legend(loc="best", fontsize=8)

fig.tight_layout(rect=[0, 0, 1, 0.97])
out = HERE / "ilc7_coldstart_phases.png"
fig.savefig(out, dpi=130)
print(f"Wrote {out}")
