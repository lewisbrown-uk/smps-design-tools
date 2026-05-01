"""Sweep the corner of a single-stage active Sallen-Key Butterworth low-pass
filter cascaded after the Wien bridge oscillator (biased BJT clamp at
alpha = 0.301, the THD-minimum operating point), and measure THD+N on the
filtered output.

Topology of the filter (unity-gain SK LP, equal Rs, C_a = 2*C_b):

        out -- R_a --+--- R_b ---+--- vfilt          fc = 1 / (2 pi R sqrt(C_a C_b))
                     |           |
                     C_a         C_b
                     |           |
                   vfilt        GND

with C_a = 2*C_b chosen for a Butterworth (Q = 1/sqrt(2)) response at unity
gain. The op-amp implementing the follower uses the same behavioural model
as the oscillator's op-amp (rail-clamped B-source + single 100 kHz pole +
unity-gain output buffer).

Sweep prints settled fundamental amplitude and lock-in THD+N for each fc.
"""
from __future__ import annotations
import shutil
import subprocess
from pathlib import Path
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).parent
WORK = HERE / "_lp_sweep"
WORK.mkdir(exist_ok=True)

ALPHA = 0.301
R_TOT = 240e3
RTOP = (1 - ALPHA) * R_TOT
RBOT = ALPHA * R_TOT

R_FILT = 10e3                    # Sallen-Key resistors (R1 = R2)
F0_NOMINAL = 1000.0              # Wien bridge fundamental, used for sweep grid
FCS = np.array([
    0.50, 0.60, 0.70, 0.80, 0.90, 1.00, 1.10, 1.20, 1.30, 1.40, 1.50,
    1.65, 1.80, 2.00, 2.50, 3.00, 4.00, 5.00, 7.00, 10.0,
]) * 1000.0  # Hz


def make_netlist(fc_hz: float, data_path: Path) -> str:
    # 4th-order Butterworth = two cascaded 2nd-order SK stages with same fc
    # but different Q. With unity-gain SK and equal Rs, Q = sqrt(Ca/Cb)/2.
    # 4th-order Butterworth Qs: Q1 = 1/(2 cos(pi/8)) = 0.5412
    #                           Q2 = 1/(2 cos(3pi/8)) = 1.3066
    # Stage 1 (Q=0.5412): Ca/Cb = (2*Q)^2 = 1.171
    # Stage 2 (Q=1.3066): Ca/Cb = (2*Q)^2 = 6.829
    Q1 = 1.0 / (2 * np.cos(np.pi / 8))
    Q2 = 1.0 / (2 * np.cos(3 * np.pi / 8))
    cb1 = 1.0 / (2 * np.pi * R_FILT * fc_hz * (2 * Q1))  # smaller cap of stage 1
    ca1 = (2 * Q1) ** 2 * cb1
    cb2 = 1.0 / (2 * np.pi * R_FILT * fc_hz * (2 * Q2))
    ca2 = (2 * Q2) ** 2 * cb2
    return f"""* Wien bridge oscillator (biased BJT, alpha=0.301) + 4th-order Butterworth SK
* fc = {fc_hz:.1f} Hz
* Stage 1: Q={Q1:.4f}, Ca={ca1*1e9:.4f}n, Cb={cb1*1e9:.4f}n
* Stage 2: Q={Q2:.4f}, Ca={ca2*1e9:.4f}n, Cb={cb2*1e9:.4f}n
* Op-amps modelled as TLV9104 (quad CMOS RRIO, ±5 V supplies).

.include {(HERE/'uopamp.lib').as_posix()}

* --- Wien bridge oscillator ---
R1   out  ns   10k
C1   ns   np   15.915n  IC=0
R2   np   0    10k
C2   np   0    15.915n  IC=10m

Rg   nn   0    10k
Rfa  nn   fb   10k
Rfb  fb   out  12k
Q1   fb   b1   out  Q2N3904
Q2   out  b2   fb   Q2N3904
Rtop1 fb  b1  {RTOP:.6g}
Rbot1 b1  out {RBOT:.6g}
Rtop2 out b2  {RTOP:.6g}
Rbot2 b2  fb  {RBOT:.6g}

* +/-5 V supplies for the whole quad
Vcc  vcc 0  5
Vee  vee 0 -5

* --- Oscillator op-amp: TLV9104-class Level-2 ---
* Avol=130 dB, GBW=1 MHz, Rin=100G (CMOS), Rout=10, Iq=0.6m, Vrail=100m,
* Ilimit=1A (workaround for the lvl2 offset bug; see uopamp.lib)
XU1  np nn vcc vee out uopamp_lvl2
+    Avol=3.16meg GBW=1meg Rin=100g Rout=10 Iq=600u Ilimit=1 Vrail=100m Vmax=20

* --- Stage 1 of 4th-order Butterworth Sallen-Key (Q = 0.5412) ---
RA1   out  nfa1   {R_FILT:.6g}
RB1   nfa1 nfb1   {R_FILT:.6g}
CB1   nfb1 0      {cb1:.6g}    IC=0
CA1   nfa1 vfilt1 {ca1:.6g}    IC=0
XU2  nfb1 vfilt1 vcc vee vfilt1 uopamp_lvl2
+    Avol=3.16meg GBW=1meg Rin=100g Rout=10 Iq=600u Ilimit=1 Vrail=100m Vmax=20

* --- Stage 2 of 4th-order Butterworth Sallen-Key (Q = 1.3066) ---
RA2   vfilt1 nfa2  {R_FILT:.6g}
RB2   nfa2   nfb2  {R_FILT:.6g}
CB2   nfb2   0     {cb2:.6g}   IC=0
CA2   nfa2   vfilt {ca2:.6g}   IC=0
XU3  nfb2 vfilt vcc vee vfilt uopamp_lvl2
+    Avol=3.16meg GBW=1meg Rin=100g Rout=10 Iq=600u Ilimit=1 Vrail=100m Vmax=20

.model Q2N3904 NPN(IS=6.734f XTI=3 EG=1.11 VAF=74.03 BF=416.4 NE=1.259
+ ISE=6.734f IKF=66.78m XTB=1.5 BR=.7371 NC=2 ISC=0 IKR=0 RC=1
+ CJC=3.638p MJC=.3085 VJC=.75 FC=.5 CJE=4.493p MJE=.2593 VJE=.75
+ TR=239.5n TF=301.2p ITF=.4 VTF=4 XTF=2 RB=10)

.tran 1u 100m UIC

.control
run
wrdata {data_path.as_posix()} v(out) v(vfilt1) v(vfilt)
.endcontrol

.end
"""


def lockin_thd(t_raw, x_raw, t_window=(0.05, 0.085), fs=1_000_000):
    t = np.arange(t_raw[0], t_raw[-1], 1 / fs)
    x = np.interp(t, t_raw, x_raw)
    mask_late = t > 0.07
    zc = np.where(np.diff(np.signbit(x[mask_late])))[0]
    if len(zc) < 4:
        return float("nan"), float("nan")
    t_late = t[mask_late]
    f0 = 0.5 / np.mean(np.diff(t_late[zc]))
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


def run_one(fc_hz: float):
    cir = WORK / f"lp_{fc_hz:.0f}.cir"
    dat = WORK / f"lp_{fc_hz:.0f}.data"
    cir.write_text(make_netlist(fc_hz, dat))
    subprocess.run(["ngspice", "-b", cir.name], cwd=WORK,
                   check=True, capture_output=True, text=True)
    d = np.loadtxt(dat)
    # wrdata layout for tran with 3 vars: t, v(out), t, v(vfilt1), t, v(vfilt)
    return d[:, 0], d[:, 1], d[:, 3], d[:, 5]


def main():
    if shutil.which("ngspice") is None:
        raise RuntimeError("ngspice not found")

    rows = []
    for fc in FCS:
        t, vout, vfilt1, vfilt = run_one(fc)
        a_raw, thd_raw = lockin_thd(t, vout)
        a_2nd, thd_2nd = lockin_thd(t, vfilt1)
        a_4th, thd_4th = lockin_thd(t, vfilt)
        print(f"fc={fc:6.0f} Hz  raw: {20*np.log10(thd_raw):+6.2f}dB  "
              f"2nd: amp={a_2nd:.3f}V {20*np.log10(thd_2nd):+6.2f}dB  "
              f"4th: amp={a_4th:.3f}V {20*np.log10(thd_4th):+6.2f}dB")
        rows.append((fc, a_raw, thd_raw, a_2nd, thd_2nd, a_4th, thd_4th))

    arr = np.array(rows)
    fc = arr[:, 0]
    amp_2nd = arr[:, 3]
    amp_4th = arr[:, 5]
    thd_raw_db = 20 * np.log10(arr[:, 2])
    thd_2nd_db = 20 * np.log10(arr[:, 4])
    thd_4th_db = 20 * np.log10(arr[:, 6])

    # Theoretical Butterworth attenuation curves vs fc, for f0 / 3f0 / 5f0:
    fc_dense = np.geomspace(fc.min(), fc.max(), 200)
    def butter_db(f, fc_, order=2):
        return -10 * np.log10(1 + (f / fc_) ** (2 * order))
    raw_h3 = -38.5
    raw_h5 = -52.2
    def predict(order):
        H1 = butter_db(F0_NOMINAL, fc_dense, order)
        H3 = butter_db(3 * F0_NOMINAL, fc_dense, order)
        H5 = butter_db(5 * F0_NOMINAL, fc_dense, order)
        h3 = raw_h3 + (H3 - H1)
        h5 = raw_h5 + (H5 - H1)
        return 10 * np.log10(10 ** (h3 / 10) + 10 ** (h5 / 10))
    pred_2nd = predict(2)
    pred_4th = predict(4)

    fig, axes = plt.subplots(2, 1, figsize=(9, 8), sharex=True)
    ax_a, ax_d = axes

    ax_a.axhline(arr[:, 1].mean(), color="0.5", linestyle="--",
                 label="oscillator output (pre-filter)")
    ax_a.semilogx(fc, amp_2nd, "o-", color="C0", label="after 2nd-order SK")
    ax_a.semilogx(fc, amp_4th, "s-", color="C2", label="after 4th-order SK (cascaded)")
    ax_a.set_ylabel("Settled fundamental amplitude [V]")
    ax_a.set_title(
        "Wien bridge + 2nd vs 4th-order Sallen-Key Butterworth LP\n"
        rf"$\alpha=0.301$, $f_0\approx{F0_NOMINAL:.0f}$ Hz, TLV9104-class quad"
    )
    ax_a.grid(True, which="both", alpha=0.4)
    ax_a.legend()

    ax_d.axhline(20*np.log10(arr[:,2].mean()), color="0.7", linestyle=":",
                 label=f"pre-filter ({20*np.log10(arr[:,2].mean()):.1f} dB)")
    ax_d.semilogx(fc, thd_2nd_db, "o-", color="C0", label="2nd-order (measured)")
    ax_d.semilogx(fc_dense, pred_2nd, "--", color="C0", alpha=0.4,
                  label="2nd-order (predicted)")
    ax_d.semilogx(fc, thd_4th_db, "s-", color="C2", label="4th-order (measured)")
    ax_d.semilogx(fc_dense, pred_4th, "--", color="C2", alpha=0.4,
                  label="4th-order (predicted)")
    ax_d.set_xlabel("Filter corner frequency $f_c$ [Hz]")
    ax_d.set_ylabel("Settled THD+N at filter output [dB]")
    ax_d.grid(True, which="both", alpha=0.4)
    ax_d.legend()

    fig.tight_layout()
    out = HERE / "wien_lp_sweep.png"
    fig.savefig(out, dpi=120)
    print(f"\nWrote {out}")

    csv = HERE / "wien_lp_sweep.csv"
    np.savetxt(csv, arr, delimiter=",",
               header="fc_Hz,amp_raw_V,thd_raw,amp_2nd_V,thd_2nd,amp_4th_V,thd_4th",
               comments="")
    print(f"Wrote {csv}")


if __name__ == "__main__":
    main()
