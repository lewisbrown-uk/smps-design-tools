"""Per-tube cold-start chart: V_ctl, V_int_out, I_clamp_hi, R_fil, T_filament
for both V_p variants overlaid. Reads .npz from diag_*_peak_vp*.npz.

Usage: python3 plot_tube_coldstart.py <tube>
       (tube ∈ {iv6, ilc11_7, ilc11_8})
"""
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from test_closed_loop import TUBES

CLAMP_HI = 2.5
CLAMP_LO = 0.3
T_END_ZOOM = 2.000

CASES = [("typ", -1.5, "C0"), ("max", -3.0, "C3")]


def find_phases(r, threshold=1e-3):
    """Returns (slew_end, release_start). The 'pinned' window is the period
    of strong (>threshold) clamp conduction. For cases where the clamp barely
    engages (V_p=-3 on small tubes), returns (None, None)."""
    t = r["t"]; i = r["i_clamp_hi"]
    active = i > threshold
    if not active.any(): return None, None
    i_first = np.argmax(active)
    transitions = np.where(np.diff(active.astype(int)) == -1)[0]
    i_last = transitions[0] if len(transitions) else len(t) - 1
    return float(t[i_first]), float(t[i_last])


def main(tube_key):
    spec = TUBES[tube_key]
    T_op = spec["T_op"]
    R_op = spec["R_op"]
    tube_name = spec["name"]

    runs = {}
    for lbl, v, _ in CASES:
        npz = HERE / f"diag_{tube_key}_peak_vp{lbl}.npz"
        if not npz.exists():
            print(f"missing {npz.name}", file=sys.stderr); sys.exit(1)
        d = np.load(npz)
        runs[lbl] = {k: d[k] for k in d.files}

    fig, axes = plt.subplots(5, 1, figsize=(12, 13), sharex=True)
    fig.suptitle(f"{tube_name}  cold-start  (C_AP=470 nF, no soft-start)", fontsize=14)

    t_slew_typ, t_release_typ = find_phases(runs["typ"])
    t_slew_max, t_release_max = find_phases(runs["max"])
    def fmt(t1, t2): return f"{t1*1e3:.1f}->{t2*1e3:.1f} ms" if t1 is not None else "(clamp not strongly engaged)"
    print(f"V_p=-1.5: slew {fmt(t_slew_typ, t_release_typ)}")
    print(f"V_p=-3.0: slew {fmt(t_slew_max, t_release_max)}")

    for lbl, v, color in CASES:
        r = runs[lbl]
        t_ms = r["t"] * 1e3
        mask = r["t"] <= T_END_ZOOM
        label = f"V_p={v:+.1f} V"
        axes[0].plot(t_ms[mask], r["v_ctl"][mask], color=color, lw=0.8, label=label)
        axes[1].plot(t_ms[mask], r["v_int_out"][mask], color=color, lw=0.8, label=label)
        axes[2].plot(t_ms[mask], r["i_clamp_hi"][mask]*1e3, color=color, lw=0.8, label=label)
        axes[3].plot(t_ms[mask], r["r_fil"][mask], color=color, lw=0.8, label=label)
        axes[4].plot(t_ms[mask], r["T_node"][mask], color=color, lw=0.8, label=label)

    # Shade the V_p=-1.5 pinned window if it exists, else V_p=-3.0's
    shade = (t_slew_typ, t_release_typ) if t_slew_typ is not None else (t_slew_max, t_release_max)
    if shade[0] is not None:
        for ax in axes:
            ax.axvspan(shade[0]*1e3, shade[1]*1e3, color="0.85", alpha=0.5, zorder=0)
            ax.axvline(shade[0]*1e3, color="0.5", lw=0.6, ls="--")
            ax.axvline(shade[1]*1e3, color="0.5", lw=0.6, ls="--")

    axes[1].axhline(CLAMP_HI, color="r", lw=0.7, ls=":", label="clamp_hi = +2.5 V")
    axes[1].axhline(CLAMP_LO, color="r", lw=0.7, ls=":", label="clamp_lo = +0.3 V")
    axes[1].axhline(3.343, color="r", lw=0.7, ls="-.", alpha=0.5, label="V_int @ pinned ≈ +3.34 V")

    axes[0].set_ylabel("V_ctl (JFET gate) [V]")
    axes[1].set_ylabel("V_int_out [V]")
    axes[2].set_ylabel("I_clamp_hi [mA]")
    axes[3].set_ylabel("R_fil [Ω]")
    axes[4].set_ylabel("T_filament [K]")
    axes[4].set_xlabel("Time [ms]")
    axes[3].axhline(R_op, color="0.4", lw=0.6, ls="--", label=f"R_op = {R_op} Ω")
    axes[4].axhline(T_op, color="0.4", lw=0.6, ls="--", label=f"T_op = {T_op:.0f} K")
    axes[4].axhline(300, color="0.4", lw=0.6, ls=":", label="T_amb = 300 K")
    for ax in axes:
        ax.grid(True, alpha=0.3)
        ax.legend(loc="best", fontsize=8)

    out = HERE / f"{tube_key}_coldstart_phases.png"
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(out, dpi=130)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "iv6")
