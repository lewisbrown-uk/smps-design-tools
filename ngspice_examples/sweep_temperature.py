"""Temperature sweep of the biased Wien-bridge + 4th-order LP filter chain.

Circuit configuration is fixed at the THD-minimum / TLV9104 design point:
  - BJT bias ratio alpha = 0.301
  - 2N3904 clamp transistors
  - 4th-order Butterworth Sallen-Key at fc = 1.2 kHz
  - TLV9104-class op-amps (Avol=3.16M, GBW=1MHz, Vrail=100mV), +/-5 V

For each temperature in TEMPS, regenerate the netlist with .option temp=T,
run ngspice, and measure with the lock-in:
  - oscillator output amplitude and THD+N
  - filter output amplitude and THD+N
  - oscillation frequency

The Q2N3904 base-emitter voltage drops by about 2 mV/degC, so the BJT
clamp threshold (which sets V(out) peak via V_clamp = V_BE,on/alpha)
should shift the output amplitude by ~6.6 mV/degC at alpha=0.301.

GOTCHA observed in this sweep: the alpha=0.301 design produces 4.77 V
peak at 25 degC, uncomfortably close to TLV9104's ~4.9 V rail
saturation on +/-5 V supplies. Below 25 degC the BJT clamp wants to
fire at higher V(out), but the rails clip first; above 25 degC the
BJT fires below the rails. So the V(out)-vs-T curve has a knee at
+25 degC where the dominant clamp transitions from "rails" to "BJT".
This isn't a model artefact -- the time-domain peaks pin to ~4.9 V
from -40 to +25 degC and then peel off, exactly the rail-saturation
fingerprint. A side effect: the lock-in fundamental amplitude reads
slightly larger than the time-domain peak in the rail-clipped regime
(the classic 4/pi Fourier enhancement of a partially-clipped sine).

Practical implication: if you wanted clean BJT-only clamping across
temperature with these supplies, pick a higher alpha (~0.5 -> 3.6 V
peak at 25 degC, well clear of the rails) at the cost of ~6 dB more
THD; or replace the 2N3904 BJTs with Schottky diodes (lower V_F and
flatter TC).
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
WORK = HERE / "_temp_sweep"
WORK.mkdir(exist_ok=True)

ALPHA = 0.301
R_TOT = 240e3
RTOP = (1 - ALPHA) * R_TOT
RBOT = ALPHA * R_TOT
R_FILT = 10e3
FC = 1200.0

TEMPS = [-40, -25, -10, 0, 10, 25, 40, 55, 70, 85, 100, 125]


def make_netlist(temp_c: float, data_path: Path) -> str:
    Q1 = 1.0 / (2 * np.cos(np.pi / 8))
    Q2 = 1.0 / (2 * np.cos(3 * np.pi / 8))
    cb1 = 1.0 / (2 * np.pi * R_FILT * FC * (2 * Q1))
    ca1 = (2 * Q1) ** 2 * cb1
    cb2 = 1.0 / (2 * np.pi * R_FILT * FC * (2 * Q2))
    ca2 = (2 * Q2) ** 2 * cb2
    return f"""* Wien bridge (alpha=0.301) + 4th-order SK Butterworth, T = {temp_c} degC

.include {(HERE/'uopamp.lib').as_posix()}

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

Vcc  vcc 0  5
Vee  vee 0 -5

XU1  np nn vcc vee out uopamp_lvl2
+    Avol=3.16meg GBW=1meg Rin=100g Rout=10 Iq=600u Ilimit=1 Vrail=100m Vmax=20

RA1   out  nfa1   {R_FILT:.6g}
RB1   nfa1 nfb1   {R_FILT:.6g}
CB1   nfb1 0      {cb1:.6g}    IC=0
CA1   nfa1 vfilt1 {ca1:.6g}    IC=0
XU2  nfb1 vfilt1 vcc vee vfilt1 uopamp_lvl2
+    Avol=3.16meg GBW=1meg Rin=100g Rout=10 Iq=600u Ilimit=1 Vrail=100m Vmax=20

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

.options TEMP={temp_c} TNOM=27
.tran 1u 100m UIC

.control
run
wrdata {data_path.as_posix()} v(out) v(vfilt)
.endcontrol

.end
"""


def lockin_thd(t_raw, x_raw, t_window=(0.05, 0.085), fs=1_000_000):
    t = np.arange(t_raw[0], t_raw[-1], 1 / fs)
    x = np.interp(t, t_raw, x_raw)
    mask_late = t > 0.07
    zc = np.where(np.diff(np.signbit(x[mask_late])))[0]
    if len(zc) < 4:
        return float("nan"), float("nan"), float("nan")
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
    return A1, thd, f0


def run_one(temp_c: float):
    cir = WORK / f"temp_{temp_c:+.0f}.cir"
    dat = WORK / f"temp_{temp_c:+.0f}.data"
    cir.write_text(make_netlist(temp_c, dat))
    subprocess.run(["ngspice", "-b", cir.name], cwd=WORK,
                   check=True, capture_output=True, text=True)
    d = np.loadtxt(dat)
    return d[:, 0], d[:, 1], d[:, 3]


def main():
    if shutil.which("ngspice") is None:
        raise RuntimeError("ngspice not found")

    rows = []
    for T in TEMPS:
        t, vout, vfilt = run_one(T)
        a_osc, thd_osc, f0 = lockin_thd(t, vout)
        a_flt, thd_flt, _ = lockin_thd(t, vfilt)
        print(f"T={T:+4.0f} degC  f0={f0:7.2f} Hz  "
              f"osc: {a_osc:5.3f} V {20*np.log10(thd_osc):+6.2f} dB  "
              f"filt: {a_flt:5.3f} V {20*np.log10(thd_flt):+6.2f} dB")
        rows.append((T, f0, a_osc, thd_osc, a_flt, thd_flt))

    arr = np.array(rows)
    T = arr[:, 0]
    f0 = arr[:, 1]
    a_osc = arr[:, 2]
    a_flt = arr[:, 4]
    thd_osc_db = 20 * np.log10(arr[:, 3])
    thd_flt_db = 20 * np.log10(arr[:, 5])

    fig, axes = plt.subplots(3, 1, figsize=(9, 9), sharex=True)
    ax_a, ax_f, ax_d = axes

    ax_a.plot(T, a_osc, "o-", color="C0", label="oscillator")
    ax_a.plot(T, a_flt, "s-", color="C2", label="filter output")
    ax_a.set_ylabel("Settled fundamental amplitude [V]")
    ax_a.set_title(
        r"Wien bridge ($\alpha=0.301$) + 4th-order Butterworth SK ($f_c=1.2$ kHz)"
        "\nTemperature sweep, TLV9104-class op-amps, $\\pm5\\,$V supplies"
    )
    ax_a.grid(True, alpha=0.4)
    ax_a.legend()

    ax_f.plot(T, f0, "o-", color="C1")
    ax_f.set_ylabel("Oscillation frequency [Hz]")
    ax_f.grid(True, alpha=0.4)

    ax_d.plot(T, thd_osc_db, "o-", color="C0", label="oscillator")
    ax_d.plot(T, thd_flt_db, "s-", color="C2", label="filter output")
    ax_d.set_xlabel(r"Temperature [$^\circ$C]")
    ax_d.set_ylabel("Settled THD+N [dB]")
    ax_d.grid(True, alpha=0.4)
    ax_d.legend()

    fig.tight_layout()
    out = HERE / "wien_temp_sweep.png"
    fig.savefig(out, dpi=120)
    print(f"\nWrote {out}")

    # Linear coefficients for amplitude vs T
    slope_osc = np.polyfit(T, a_osc, 1)[0] * 1000  # mV/degC
    slope_flt = np.polyfit(T, a_flt, 1)[0] * 1000
    slope_f = np.polyfit(T, f0, 1)[0]              # Hz/degC
    print(f"\nOsc amplitude TC: {slope_osc:+.3f} mV/degC")
    print(f"Filter amplitude TC: {slope_flt:+.3f} mV/degC")
    print(f"Frequency TC: {slope_f:+.4f} Hz/degC ({slope_f/f0.mean()*1e6:+.1f} ppm/degC)")

    csv = HERE / "wien_temp_sweep.csv"
    np.savetxt(csv, arr, delimiter=",",
               header="T_C,f0_Hz,amp_osc_V,thd_osc,amp_filt_V,thd_filt",
               comments="")
    print(f"Wrote {csv}")


if __name__ == "__main__":
    main()
