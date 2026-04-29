"""Chart the ngspice adaptive timestep distribution over the THD measurement
window for each alpha in the finer bias-ratio sweep.

By default, ngspice's `wrdata` writes at the .tran print step (10 us here)
regardless of the internal solver, hiding the adaptive behaviour. To see
the actual solver-native time points we re-run each alpha and emit an
ASCII rawfile via the `write` command, which preserves every accepted
solver step.

For each alpha:
  - Generate the netlist (Wien + biased BJTs + raw output).
  - Run ngspice in batch mode.
  - Parse the rawfile to recover the full time axis.
  - Restrict to the same window used by the lock-in THD readout
    (t in [0.05, 0.085] s) and compute dt[k] = t[k+1] - t[k].
  - Plot the dt distribution as a violin per alpha, with the THD curve
    overlaid below for context.
"""
from pathlib import Path
import re
import shutil
import subprocess
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).parent
WORK = HERE / "_dt_sweep"
WORK.mkdir(exist_ok=True)

ALPHAS = list(np.round(np.arange(0.290, 0.3101, 0.001), 4))
R_TOT = 240e3
T_LO, T_HI = 0.05, 0.085


def make_netlist(alpha: float, raw_path: Path) -> str:
    rtop = (1 - alpha) * R_TOT
    rbot = alpha * R_TOT
    return f"""* Wien bridge with BJT divider clamp, alpha={alpha:.4f}, raw output

R1   out  ns   10k
C1   ns   np   15.915n  IC=0
R2   np   0    10k
C2   np   0    15.915n  IC=10m

Rg   nn   0    10k
Rfa  nn   fb   10k
Rfb  fb   out  12k
Q1   fb   b1   out  Q2N3904
Q2   out  b2   fb   Q2N3904
Rtop1 fb  b1  {rtop:.6g}
Rbot1 b1  out {rbot:.6g}
Rtop2 out b2  {rtop:.6g}
Rbot2 b2  fb  {rbot:.6g}

Bgain oe   0   V = max(-15, min(15, 1e5*(V(np)-V(nn))))
Rop   oe   oa  1k
Cop   oa   0   1.59n     IC=0
Ebuf  out  0   oa  0     1.0

.model Q2N3904 NPN(IS=6.734f XTI=3 EG=1.11 VAF=74.03 BF=416.4 NE=1.259
+ ISE=6.734f IKF=66.78m XTB=1.5 BR=.7371 NC=2 ISC=0 IKR=0 RC=1
+ CJC=3.638p MJC=.3085 VJC=.75 FC=.5 CJE=4.493p MJE=.2593 VJE=.75
+ TR=239.5n TF=301.2p ITF=.4 VTF=4 XTF=2 RB=10)

.tran 1u 100m UIC

.control
set filetype=ascii
run
write {raw_path.as_posix()} v(out)
.endcontrol

.end
"""


def parse_raw_time(path: Path) -> np.ndarray:
    """Extract the time column from an ngspice ASCII raw file."""
    text = path.read_text()
    _, _, body = text.partition("Values:\n")
    times: list[float] = []
    for line in body.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].strip().isdigit():
            times.append(float(parts[1]))
    return np.asarray(times)


def run_one(alpha: float) -> np.ndarray:
    cir = WORK / f"wien_alpha_{alpha:.4f}.cir"
    raw = WORK / f"wien_alpha_{alpha:.4f}.raw"
    cir.write_text(make_netlist(alpha, raw))
    subprocess.run(
        ["ngspice", "-b", cir.name],
        cwd=WORK,
        check=True,
        capture_output=True,
        text=True,
    )
    return parse_raw_time(raw)


def main() -> None:
    if shutil.which("ngspice") is None:
        raise RuntimeError("ngspice not found in PATH")

    dt_thd: list[np.ndarray] = []
    dt_startup: list[np.ndarray] = []
    n_total: list[int] = []
    for a in ALPHAS:
        t = run_one(a)
        sel_thd = (t >= T_LO) & (t <= T_HI)
        sel_start = t < 0.015
        dts_thd = np.diff(t[sel_thd])
        dts_start = np.diff(t[sel_start])
        dt_thd.append(dts_thd)
        dt_startup.append(dts_start)
        n_total.append(len(t))
        print(f"alpha={a:.4f}  total_pts={len(t):5d}  "
              f"THD-window unique-dt={len(np.unique(np.round(dts_thd,12))):2d}  "
              f"startup dt: min={dts_start.min()*1e6:7.4f}us  "
              f"median={np.median(dts_start)*1e6:6.3f}us  "
              f"max={dts_start.max()*1e6:6.3f}us")

    csv = np.loadtxt(HERE / "wien_bias_sweep_finer.csv", delimiter=",", skiprows=1)
    thd_db = 20 * np.log10(csv[:, 2])

    fig, axes = plt.subplots(
        3, 1, figsize=(11, 9), sharex=True,
        gridspec_kw=dict(height_ratios=[2, 3, 1])
    )
    ax_thd_dt, ax_start_dt, ax_thd_curve = axes
    positions = np.arange(len(ALPHAS))

    # Top: per-alpha [min, max] dt in the THD window. Will be a flat line at
    # 10 us because every step is bit-for-bit identical across alpha.
    medians = np.array([np.median(d) for d in dt_thd]) * 1e6
    mins = np.array([d.min() for d in dt_thd]) * 1e6
    maxs = np.array([d.max() for d in dt_thd]) * 1e6
    ax_thd_dt.fill_between(positions, mins, maxs, color="C0", alpha=0.3,
                           label="[min, max] across window")
    ax_thd_dt.plot(positions, medians, "o-", color="C0", label="median")
    ax_thd_dt.set_ylabel(r"$\Delta t$ [$\mu$s]")
    ax_thd_dt.set_title(
        rf"THD measurement window  $t\in[{T_LO*1e3:.0f},\,{T_HI*1e3:.0f}]$ ms"
        rf" — bit-for-bit identical {medians[0]:.1f} us steps for all $\alpha$"
    )
    ax_thd_dt.set_ylim(medians[0] * 0.95, medians[0] * 1.05)
    ax_thd_dt.grid(True, which="both", alpha=0.4)
    ax_thd_dt.legend(loc="lower right")

    # Bottom violin: actual adaptive behaviour during startup
    parts = ax_start_dt.violinplot(
        [d * 1e6 for d in dt_startup],
        positions=positions,
        showmeans=False,
        showmedians=True,
        showextrema=True,
        widths=0.85,
    )
    for body in parts["bodies"]:
        body.set_facecolor("C2")
        body.set_edgecolor("0.3")
        body.set_alpha(0.55)
    for key in ("cbars", "cmaxes", "cmins"):
        parts[key].set_color("0.25")
    parts["cmedians"].set_color("C3")
    parts["cmedians"].set_linewidth(2)
    ax_start_dt.set_yscale("log")
    ax_start_dt.set_ylabel(r"$\Delta t$ [$\mu$s]")
    ax_start_dt.set_title(
        r"Startup window  $t<15$ ms — real adaptive behaviour, "
        "tail to nanosecond steps when clamp first engages"
    )
    ax_start_dt.grid(True, which="both", alpha=0.4)

    ax_thd_curve.plot(positions, thd_db, "o-", color="C3")
    ax_thd_curve.set_ylabel("THD+N [dB]")
    ax_thd_curve.grid(True, which="both", alpha=0.4)
    ax_thd_curve.set_xticks(positions)
    ax_thd_curve.set_xticklabels([f"{a:.3f}" for a in ALPHAS], rotation=45)
    ax_thd_curve.set_xlabel(r"Bias ratio $\alpha$")

    fig.tight_layout()
    out = HERE / "wien_bias_dt_distribution.png"
    fig.savefig(out, dpi=120)
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
