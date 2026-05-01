"""Post-process filament_mc_sweep.csv into histograms + scatter plot.

Decoupled from test_closed_loop.py so that plot tweaks don't require
rerunning the 24-trial MC sweep.

Trace overlays are produced only by sweep_mc / sweep_corners themselves
(they need the full per-trial T(t) arrays).
"""
from pathlib import Path
import csv
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).parent
T_OP_TARGET = 800.0
R_OP = 100.0


def read_csv(p):
    with open(p) as fh:
        return list(csv.DictReader(fh))


def col(rows, key, cast=float):
    return np.array([cast(r[key]) for r in rows])


def make_plots(csv_path, png_hist, png_scatter, label):
    rows = read_csv(csv_path)
    N = len(rows)
    T_finals = col(rows, "T_final")
    T_peaks  = col(rows, "T_peak")
    R_finals = col(rows, "R_final")
    t_set    = col(rows, "t_settle_5K") * 1e3
    overshoots = col(rows, "T_overshoot")
    kr = col(rows, "k_r_amb")

    # Histograms
    fig, axes = plt.subplots(2, 2, figsize=(11, 8))
    for ax, arr, title, unit, ref in [
        (axes[0, 0], T_finals, "T_final",     "K",  T_OP_TARGET),
        (axes[0, 1], T_peaks,  "T_peak",      "K",  T_OP_TARGET),
        (axes[1, 0], R_finals, "R_final",     r"$\Omega$", R_OP),
        (axes[1, 1], t_set,    "t_settle_5K", "ms", None),
    ]:
        ax.hist(arr, bins=12, color="C0", edgecolor="0.2")
        ax.set_xlabel(f"{title} [{unit}]")
        ax.set_ylabel("count")
        ax.set_title(f"{title}: mean {arr.mean():.1f}, sigma {arr.std():.1f} {unit}")
        if ref is not None:
            ax.axvline(ref, color="C3", linestyle="--", lw=1.0,
                       label=f"target = {ref:g}")
            ax.legend(loc="upper right")
        ax.grid(True, alpha=0.3, axis="y")
    fig.suptitle(f"Filament {label} histograms (N={N})")
    fig.tight_layout()
    fig.savefig(png_hist, dpi=120)
    plt.close(fig)
    print(f"Wrote {png_hist}")

    # Scatter T_final vs k_r_amb (dominant operating-point lever)
    fig, axes = plt.subplots(1, 2, figsize=(11, 5))
    ax_t, ax_r = axes
    ax_t.scatter(kr, T_finals, c="C0", label="T_final")
    ax_t.set_xlabel("k_r_amb (R_amb tolerance factor)")
    ax_t.set_ylabel("T [K]")
    ax_t.set_title("Steady-state T vs filament cold-resistance variation")
    ax_t.grid(True, alpha=0.4)
    ax_t.axhline(T_OP_TARGET, color="0.5", lw=0.7, ls="--", label=f"target = {T_OP_TARGET:.0f} K")
    ax_t.legend(loc="best")
    ax_r.scatter(kr, t_set, c="C2")
    ax_r.set_xlabel("k_r_amb (R_amb tolerance factor)")
    ax_r.set_ylabel("t_settle_5K [ms]")
    ax_r.set_title("Settling time vs filament cold-R variation")
    ax_r.grid(True, alpha=0.4)
    fig.suptitle(f"Filament {label} scatter (N={N})")
    fig.tight_layout()
    fig.savefig(png_scatter, dpi=120)
    plt.close(fig)
    print(f"Wrote {png_scatter}")


if __name__ == "__main__":
    mc = HERE / "filament_mc_sweep.csv"
    if mc.exists():
        make_plots(mc, HERE / "filament_mc_histograms.png",
                       HERE / "filament_mc_scatter.png", "MC")
    corners = HERE / "filament_corners_sweep.csv"
    if corners.exists():
        make_plots(corners, HERE / "filament_corners_histograms.png",
                            HERE / "filament_corners_scatter.png", "corners")
