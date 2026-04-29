"""STFT spectrogram of the Wien bridge oscillator at the THD-minimum operating
point (alpha = 0.301, found by sweep_wien_bias.py --sweep finer).

Uses the cached high-resolution (tstep = 1 us) simulation data so the
harmonic content is sampled cleanly.
"""
from pathlib import Path
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.signal import ShortTimeFFT
from scipy.signal.windows import hann

HERE = Path(__file__).parent
DATA = HERE / "_bias_sweep" / "wien_alpha_0.3010_1u.data"
ALPHA = 0.301

d = np.loadtxt(DATA)
t_raw, vout_raw = d[:, 0], d[:, 1]

# Resample to 200 kS/s -- comfortably above the highest harmonic of interest.
fs = 200_000
t = np.arange(t_raw[0], t_raw[-1], 1 / fs)
x = np.interp(t, t_raw, vout_raw)

# STFT: 50 ms window -> 25 Hz frequency resolution
nperseg = 8192
hop = 256
win = hann(nperseg, sym=False)
stft = ShortTimeFFT(win, hop=hop, fs=fs, scale_to="magnitude")
Sx = stft.stft(x)
mag_db = 20 * np.log10(np.abs(Sx) + 1e-12)

t_frames = stft.t(len(x))
freqs = stft.f
f_lim = 5_000
f_mask = freqs <= f_lim

fig, (ax_t, ax_s) = plt.subplots(2, 1, figsize=(9, 7), sharex=True)

ax_t.plot(t * 1e3, x, lw=0.5)
ax_t.set_ylabel("V(out) [V]")
ax_t.set_title(
    rf"Wien bridge with biased BJT clamp at $\alpha={ALPHA:.3f}$ "
    "(THD minimum, settled THD+N $=-38.09$ dB)"
)
ax_t.grid(True, alpha=0.4)
ax_t.set_xlim(0, t[-1] * 1e3)

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
out = HERE / "wien_bridge_biased_spectrogram.png"
fig.savefig(out, dpi=120)
print(f"Wrote {out}")

# Steady-state harmonic levels
late = t_frames > 0.05
mean_spec = np.mean(np.abs(Sx[:, late]), axis=1)
f0_idx = int(np.argmax(mean_spec[(freqs > 500) & (freqs < 1500)]
                       )) + int(np.searchsorted(freqs, 500))
f0 = freqs[f0_idx]
print(f"Steady-state fundamental: {f0:.2f} Hz")
for k in range(2, 7):
    fk = k * f0
    if fk < freqs[-1]:
        idx = int(np.argmin(np.abs(freqs - fk)))
        rel_db = 20 * np.log10(mean_spec[idx] / mean_spec[f0_idx])
        print(f"  {k}x harmonic ({freqs[idx]:.0f} Hz): {rel_db:+.1f} dBc")
