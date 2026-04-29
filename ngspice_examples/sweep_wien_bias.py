"""Sweep the BJT base-bias ratio alpha = Rbot/(Rtop+Rbot) and measure THD.

For each alpha:
  - Generate a netlist with the symmetric divider biasing Q1 and Q2.
  - Run ngspice in batch mode, capturing v(out).
  - Measure settled fundamental amplitude and lock-in THD+N over the
    last ~30 cycles.

Plots THD+N and steady-state peak amplitude vs alpha.

The total divider impedance Rtot = Rtop + Rbot is held at 240 kohm so the
divider barely shunts the negative-feedback path (Rfb = 12 kohm, two
dividers in parallel give 120 kohm shunt -> ~1% perturbation).
"""
from __future__ import annotations
import argparse
import shutil
import subprocess
from pathlib import Path
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).parent
WORK = HERE / "_bias_sweep"
WORK.mkdir(exist_ok=True)

R_TOT = 240e3                # total divider impedance per transistor

SWEEPS = {
    "broad":  [1.00, 0.90, 0.80, 0.70, 0.60, 0.50,
               0.40, 0.35, 0.30, 0.25, 0.20],
    "fine":   list(np.round(np.arange(0.25, 0.351, 0.01),  3)),
    "finer":  list(np.round(np.arange(0.29, 0.3101, 0.001), 4)),
}

# Default tstep per sweep -- finer sweeps need finer resolution to keep the
# lock-in measurement floor below the THD variation we want to see.
TSTEPS = {"broad": "10u", "fine": "10u", "finer": "1u"}


def make_netlist(alpha: float, data_path: Path, tstep: str = "10u") -> str:
    """Wien bridge with BJT clamps biased by symmetric dividers (ratio alpha)."""
    rtop = (1 - alpha) * R_TOT
    rbot = alpha * R_TOT
    # When alpha == 1.0, Rtop = 0 -> use a wire (avoid zero-ohm element).
    if rtop < 1.0:
        q1 = "Q1   fb   fb   out  Q2N3904"
        q2 = "Q2   out  out  fb   Q2N3904"
        bias = ""
    else:
        q1 = "Q1   fb   b1   out  Q2N3904"
        q2 = "Q2   out  b2   fb   Q2N3904"
        bias = (
            f"Rtop1 fb  b1  {rtop:.6g}\n"
            f"Rbot1 b1  out {rbot:.6g}\n"
            f"Rtop2 out b2  {rtop:.6g}\n"
            f"Rbot2 b2  fb  {rbot:.6g}\n"
        )
    return f"""* Wien bridge oscillator with BJT-divider amplitude clamp (alpha={alpha:.3f})

R1   out  ns   10k
C1   ns   np   15.915n  IC=0
R2   np   0    10k
C2   np   0    15.915n  IC=10m

Rg   nn   0    10k
Rfa  nn   fb   10k
Rfb  fb   out  12k
{q1}
{q2}
{bias}
Bgain oe   0   V = max(-15, min(15, 1e5*(V(np)-V(nn))))
Rop   oe   oa  1k
Cop   oa   0   1.59n     IC=0
Ebuf  out  0   oa  0     1.0

.model Q2N3904 NPN(IS=6.734f XTI=3 EG=1.11 VAF=74.03 BF=416.4 NE=1.259
+ ISE=6.734f IKF=66.78m XTB=1.5 BR=.7371 NC=2 ISC=0 IKR=0 RC=1
+ CJC=3.638p MJC=.3085 VJC=.75 FC=.5 CJE=4.493p MJE=.2593 VJE=.75
+ TR=239.5n TF=301.2p ITF=.4 VTF=4 XTF=2 RB=10)

.tran {tstep} 100m UIC

.control
run
wrdata {data_path.as_posix()} v(out)
.endcontrol

.end
"""


def run_one(alpha: float, tstep: str = "10u") -> tuple[np.ndarray, np.ndarray]:
    tag = f"wien_alpha_{alpha:.4f}_{tstep}"
    cir = WORK / f"{tag}.cir"
    dat = WORK / f"{tag}.data"
    cir.write_text(make_netlist(alpha, dat, tstep=tstep))
    subprocess.run(
        ["ngspice", "-b", cir.name],
        cwd=WORK,
        check=True,
        capture_output=True,
        text=True,
    )
    d = np.loadtxt(dat)
    return d[:, 0], d[:, 1]


def lockin_thd(t_raw: np.ndarray, x_raw: np.ndarray, t_window=(0.05, 0.085),
               fs: float = 50_000) -> tuple[float, float]:
    """Return (peak_amplitude, THD+N) over the steady-state window via lock-in."""
    t = np.arange(t_raw[0], t_raw[-1], 1 / fs)
    x = np.interp(t, t_raw, x_raw)

    # Estimate f0 from late-time zero crossings.
    mask_late = t > 0.07
    sgn = np.signbit(x[mask_late])
    zc = np.where(np.diff(sgn))[0]
    if len(zc) < 4:
        return float("nan"), float("nan")
    t_late = t[mask_late]
    f0 = 0.5 / np.mean(np.diff(t_late[zc]))

    # Box-car length: integer number of half-periods to null the 2*f0 image.
    half_period_samples = fs / (2 * f0)
    N = int(round(round(0.010 * fs / half_period_samples) * half_period_samples))
    kernel = np.ones(N) / N

    sin_lo = np.sin(2 * np.pi * f0 * t)
    cos_lo = np.cos(2 * np.pi * f0 * t)
    I = 2 * np.convolve(x * sin_lo, kernel, mode="same")
    Q = 2 * np.convolve(x * cos_lo, kernel, mode="same")
    x_fund = I * sin_lo + Q * cos_lo
    resid = x - x_fund

    fund_rms_sq = np.convolve(x_fund**2, kernel, mode="same")
    resid_rms_sq = np.convolve(resid**2, kernel, mode="same")

    sel = (t >= t_window[0]) & (t <= t_window[1])
    A1 = float(np.mean(np.sqrt(I[sel] ** 2 + Q[sel] ** 2)))
    thd = float(np.mean(np.sqrt(resid_rms_sq[sel] / fund_rms_sq[sel])))
    return A1, thd


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sweep", choices=SWEEPS.keys(), default="broad",
                        help="which alpha set to sweep")
    args = parser.parse_args()
    alphas = SWEEPS[args.sweep]
    suffix = "" if args.sweep == "broad" else f"_{args.sweep}"
    tstep = TSTEPS[args.sweep]
    # Match lock-in fs to the simulation print rate so we don't downsample.
    suffix_lookup = {"10u": 100_000, "1u": 1_000_000, "100n": 10_000_000}
    fs = suffix_lookup.get(tstep, 100_000)

    if shutil.which("ngspice") is None:
        raise RuntimeError("ngspice not found in PATH")

    print(f"Sweep '{args.sweep}': {len(alphas)} points, "
          f"tstep={tstep}, lock-in fs={fs/1e3:.0f} kS/s")

    results = []
    for a in alphas:
        try:
            t, x = run_one(a, tstep=tstep)
            amp, thd = lockin_thd(t, x, fs=fs)
            print(f"alpha={a:.4f}  peak={amp:.3f} V   THD+N={thd*100:.4f} %  "
                  f"({20*np.log10(thd):+.3f} dB)")
            results.append((a, amp, thd))
        except subprocess.CalledProcessError as e:
            print(f"alpha={a:.4f}  FAILED: {e.stderr[-200:]}")
            results.append((a, float("nan"), float("nan")))

    arr = np.array(results)
    alpha = arr[:, 0]
    amp = arr[:, 1]
    thd_db = 20 * np.log10(arr[:, 2])

    fig, axes = plt.subplots(2, 1, figsize=(8, 7), sharex=True)
    ax_a, ax_d = axes

    ax_a.plot(alpha, amp, "o-", color="C0")
    # Theoretical V(out)_peak = 3 * V_BE,on / alpha (V_BE,on ~ 0.62 V here)
    a_dense = np.linspace(alpha.min(), alpha.max(), 100)
    ax_a.plot(a_dense, 3 * 0.62 / a_dense, "--", color="0.5",
              label=r"$3\,V_{BE,\mathrm{on}}/\alpha$")
    ax_a.set_ylabel("Settled peak V(out) [V]")
    ax_a.set_title(
        f"Wien bridge with BJT clamp + bias divider ({args.sweep} sweep)\n"
        r"$\alpha = R_\mathrm{bot}/(R_\mathrm{top}+R_\mathrm{bot})$, "
        f"$R_\\mathrm{{tot}}={R_TOT/1e3:.0f}\\,$k$\\Omega$"
    )
    ax_a.grid(True, alpha=0.4)
    ax_a.legend()

    ax_d.plot(alpha, thd_db, "o-", color="C3")
    ax_d.set_xlabel(r"Bias ratio $\alpha = R_\mathrm{bot}/R_\mathrm{tot}$")
    ax_d.set_ylabel("Settled THD+N [dB]")
    ax_d.grid(True, which="both", alpha=0.4)
    ax_d.invert_xaxis()  # higher alpha (diode-connected end) on the left

    fig.tight_layout()
    out = HERE / f"wien_bias_sweep{suffix}.png"
    fig.savefig(out, dpi=120)
    print(f"\nWrote {out}")

    table = HERE / f"wien_bias_sweep{suffix}.csv"
    np.savetxt(table, arr, delimiter=",",
               header="alpha,peak_V,thd_fraction", comments="")
    print(f"Wrote {table}")


if __name__ == "__main__":
    main()
