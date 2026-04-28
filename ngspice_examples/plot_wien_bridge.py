"""Plot the diode-limited Wien bridge oscillator transient from wien_tran.data.

Top panel: full 100 ms run showing the exponential startup envelope.
Bottom panel: 5-cycle zoom in steady state showing the slight diode distortion.
"""
from pathlib import Path
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).parent
d = np.loadtxt(HERE / "wien_tran.data")
# wrdata layout for tran with 3 vars: t, v(out), t, v(np), t, v(fb)
t = d[:, 0]
vout = d[:, 1]

# Late-time zero crossings -> measured frequency
mask_late = t > 0.07
zc_late = np.where(np.diff(np.signbit(vout[mask_late])))[0]
t_late = t[mask_late]
freq = 0.5 / np.mean(np.diff(t_late[zc_late]))

# Pick a 5-cycle window late in the run
period = 1 / freq
t_zoom_start = 0.08
t_zoom_end = t_zoom_start + 5 * period
zoom = (t >= t_zoom_start) & (t <= t_zoom_end)

fig, (ax_full, ax_zoom) = plt.subplots(2, 1, figsize=(9, 6))

ax_full.plot(t * 1e3, vout, lw=0.6)
ax_full.set_xlabel("Time [ms]")
ax_full.set_ylabel("V(out) [V]")
ax_full.set_title(
    f"Diode-limited Wien bridge oscillator — startup ({freq:.1f} Hz, "
    f"{(t[-1] * freq):.0f} cycles)"
)
ax_full.grid(True, alpha=0.4)

ax_zoom.plot(t[zoom] * 1e3, vout[zoom], lw=1.0)
ax_zoom.set_xlabel("Time [ms]")
ax_zoom.set_ylabel("V(out) [V]")
ax_zoom.set_title("Steady-state zoom (5 cycles)")
ax_zoom.grid(True, alpha=0.4)

fig.tight_layout()
out = HERE / "wien_bridge_tran.png"
fig.savefig(out, dpi=120)
print(f"Wrote {out}")
print(f"Measured oscillation frequency: {freq:.2f} Hz")
print(f"Steady-state peak: {np.max(np.abs(vout[mask_late])):.3f} V")
