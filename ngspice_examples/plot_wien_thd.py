"""Sliding-window THD of the Wien bridge oscillator output via lock-in detection.

Convolutional approach (no FFT):
  1. Multiply x(t) by sin(2 pi f0 t) and cos(2 pi f0 t) -- the mixer step.
  2. Convolve each product with a box-car kernel of length T (= LP filter).
     This yields the slowly-varying in-phase I(t) and quadrature Q(t)
     amplitudes of the fundamental.
  3. Reconstruct the fitted fundamental: x_hat(t) = I(t)*sin + Q(t)*cos.
  4. Residual r(t) = x(t) - x_hat(t) contains everything *but* the fundamental.
  5. THD(t) = sliding RMS(r) / sliding RMS(x_hat), each computed by convolving
     the squared signal with the same box-car kernel.

A box-car length spanning an integer number of cycles of 2*f0 makes the
mixer's image at 2*f0 sit on a null of the kernel's frequency response,
giving clean rejection without an explicit IIR filter.
"""
from pathlib import Path
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).parent
d = np.loadtxt(HERE / "wien_tran.data")
t_raw = d[:, 0]
vout_raw = d[:, 1]

# Resample onto a uniform grid (ngspice uses adaptive timestep).
fs = 50_000
t = np.arange(t_raw[0], t_raw[-1], 1 / fs)
x = np.interp(t, t_raw, vout_raw)

# Measured oscillator frequency (from earlier zero-crossing fit).
f0 = 993.15

# Box-car kernel length: 10 ms => 10 cycles of f0, ~20 cycles of 2*f0.
T_window = 10e-3
N = int(round(T_window * fs))
# Snap to an integer number of half-periods of f0 so the 2*f0 mixer image
# lands exactly on a kernel null.
samples_per_half = fs / (2 * f0)
N = int(round(round(N / samples_per_half) * samples_per_half))
kernel = np.ones(N) / N

# Local oscillators
sin_lo = np.sin(2 * np.pi * f0 * t)
cos_lo = np.cos(2 * np.pi * f0 * t)


def boxcar(sig: np.ndarray) -> np.ndarray:
    """Convolve with the box-car kernel, same length, centred."""
    return np.convolve(sig, kernel, mode="same")


# Step 1+2: lock-in demodulation. Factor of 2 recovers peak amplitude.
I = 2 * boxcar(x * sin_lo)
Q = 2 * boxcar(x * cos_lo)

# Step 3: reconstruct the fitted fundamental.
x_fund = I * sin_lo + Q * cos_lo

# Step 4: residual carries every harmonic and any noise.
resid = x - x_fund

# Step 5: sliding RMS of each via box-car of the squared signal.
fund_rms = np.sqrt(boxcar(x_fund**2))
resid_rms = np.sqrt(boxcar(resid**2))

# Avoid division blow-up before the LP transient settles (first/last N/2 samples).
edge = N // 2
valid = np.zeros_like(t, dtype=bool)
valid[edge:-edge] = True
thd = np.where((fund_rms > 0.01) & valid, resid_rms / fund_rms, np.nan)

A1 = np.where(valid, np.sqrt(I**2 + Q**2), np.nan)  # fundamental peak amplitude

fig, axes = plt.subplots(3, 1, figsize=(9, 8), sharex=True)
ax_t, ax_a, ax_d = axes

ax_t.plot(t * 1e3, x, lw=0.5, color="0.4", label="V(out)")
ax_t.plot(t * 1e3, x_fund, lw=0.7, color="C0", alpha=0.8, label="fitted fundamental")
ax_t.set_ylabel("V(out) [V]")
ax_t.set_title(
    f"Diode-limited Wien bridge — lock-in THD (f0={f0:.1f} Hz, "
    f"box-car {N/fs*1e3:.1f} ms)"
)
ax_t.legend(loc="upper right")
ax_t.grid(True, alpha=0.4)

ax_a.plot(t * 1e3, A1, color="C0")
ax_a.set_ylabel("Fundamental amp [V]")
ax_a.grid(True, alpha=0.4)

ax_d.plot(t * 1e3, thd * 100, color="C3")
ax_d.set_xlabel("Time [ms]")
ax_d.set_ylabel("THD+N [%]")
ax_d.set_yscale("log")
ax_d.set_ylim(0.01, 100)
ax_d.grid(True, which="both", alpha=0.4)

fig.tight_layout()
out = HERE / "wien_bridge_thd.png"
fig.savefig(out, dpi=120)
print(f"Wrote {out}")

ss = (t > 0.05) & valid
print(f"Steady-state amplitude: {np.nanmean(A1[ss]):.3f} V (peak)")
print(f"Steady-state THD+N:     {np.nanmean(thd[ss])*100:.2f} %")
print(f"THD range over run:     {np.nanmin(thd[valid])*100:.3f}% .. "
      f"{np.nanmax(thd[valid])*100:.2f}%")
