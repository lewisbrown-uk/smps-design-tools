"""STFT spectrogram of the Wien bridge oscillator output.

The ngspice adaptive timestep is non-uniform, so we first resample v(out)
onto a uniform grid before computing the STFT.
"""
from pathlib import Path
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.signal import ShortTimeFFT
from scipy.signal.windows import hann

HERE = Path(__file__).parent
d = np.loadtxt(HERE / "wien_tran.data")
t_raw = d[:, 0]
vout_raw = d[:, 1]

# Resample to uniform grid: 50 kS/s gives ~50 samples/cycle at 1 kHz, plenty
fs = 50_000
t = np.arange(t_raw[0], t_raw[-1], 1 / fs)
x = np.interp(t, t_raw, vout_raw)

# STFT: 50 ms window -> 50 cycles per frame, 25 Hz frequency resolution
nperseg = 2048
hop = 64
win = hann(nperseg, sym=False)
stft = ShortTimeFFT(win, hop=hop, fs=fs, scale_to="magnitude")
# Restrict to fully-valid frames so window straddling the edges doesn't
# show up as a broadband flash from the implicit zero-padding.
p_lo, p_hi = stft.lower_border_end[1], stft.upper_border_begin(len(x))[1]
Sx = stft.stft(x, p0=p_lo, p1=p_hi)
mag_db = 20 * np.log10(np.abs(Sx) + 1e-12)

t_frames = stft.t(len(x), p0=p_lo, p1=p_hi)
freqs = stft.f

f_lim = 5_000  # show up to 5 kHz; harmonics from diode clipping live here
f_mask = freqs <= f_lim

fig, (ax_t, ax_s) = plt.subplots(2, 1, figsize=(9, 7), sharex=True)

ax_t.plot(t * 1e3, x, lw=0.6)
ax_t.set_ylabel("V(out) [V]")
ax_t.set_title("Diode-limited Wien bridge — transient and STFT")
ax_t.grid(True, alpha=0.4)

vmax = mag_db.max()
im = ax_s.pcolormesh(
    t_frames * 1e3,
    freqs[f_mask],
    mag_db[f_mask],
    shading="auto",
    cmap="viridis",
    vmin=vmax - 80,
    vmax=vmax,
)
ax_s.set_xlabel("Time [ms]")
ax_s.set_ylabel("Frequency [Hz]")
ax_s.set_ylim(0, f_lim)
ax_s.set_xlim(0, t[-1] * 1e3)
cbar = fig.colorbar(im, ax=ax_s, pad=0.01)
cbar.set_label("Magnitude [dB]")

fig.tight_layout()
out = HERE / "wien_bridge_spectrogram.png"
fig.savefig(out, dpi=120)
print(f"Wrote {out}")

# Locate the dominant tone in the steady-state region
late = t_frames > 0.05
mean_spec = np.mean(np.abs(Sx[:, late]), axis=1)
f0_idx = int(np.argmax(mean_spec))
print(f"Steady-state fundamental: {freqs[f0_idx]:.2f} Hz")
for k in range(1, 6):
    fk = (k + 1) * freqs[f0_idx]
    if fk < freqs[-1]:
        idx = int(np.argmin(np.abs(freqs - fk)))
        rel_db = 20 * np.log10(mean_spec[idx] / mean_spec[f0_idx])
        print(f"  {k+1}x harmonic ({freqs[idx]:.0f} Hz): {rel_db:+.1f} dBc")
