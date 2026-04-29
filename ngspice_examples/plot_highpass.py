"""Plot the AC response of the RC high-pass filter from highpass_ac.data."""
from pathlib import Path
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).parent
data = np.loadtxt(HERE / "highpass_ac.data")
freq, re, im = data[:, 0], data[:, 1], data[:, 2]

vout = re + 1j * im
mag_db = 20 * np.log10(np.abs(vout))
phase_deg = np.degrees(np.angle(vout))

R, C = 1e3, 159.15e-9
fc = 1 / (2 * np.pi * R * C)

fig, (ax_mag, ax_ph) = plt.subplots(2, 1, sharex=True, figsize=(8, 6))

ax_mag.semilogx(freq, mag_db, label="|V(out)/V(in)|")
ax_mag.axvline(fc, color="0.5", linestyle="--", label=f"fc = {fc:.1f} Hz")
ax_mag.axhline(-3, color="0.7", linestyle=":")
ax_mag.set_ylabel("Magnitude [dB]")
ax_mag.set_title("RC high-pass filter (R=1k, C=159.15n) — AC response")
ax_mag.grid(True, which="both", alpha=0.4)
ax_mag.legend(loc="lower right")

ax_ph.semilogx(freq, phase_deg)
ax_ph.axvline(fc, color="0.5", linestyle="--")
ax_ph.axhline(45, color="0.7", linestyle=":")
ax_ph.set_ylabel("Phase [deg]")
ax_ph.set_xlabel("Frequency [Hz]")
ax_ph.grid(True, which="both", alpha=0.4)

fig.tight_layout()
out = HERE / "highpass_ac.png"
fig.savefig(out, dpi=120)
print(f"Wrote {out}")

# Quick sanity numbers near the corner
idx = int(np.argmin(np.abs(freq - fc)))
print(f"At f={freq[idx]:.2f} Hz: mag={mag_db[idx]:.2f} dB, phase={phase_deg[idx]:.1f} deg")
