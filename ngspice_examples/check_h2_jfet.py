"""H2 check across all 4 tubes for the JFET+bootstrap arch (6s data already on disk)."""
import numpy as np
TUBES = ("iv18", "iv6", "ilc11_7", "ilc11_8")
print(f"{'tube':9s} {'V1 (mV)':>9s} {'H2 %':>7s} {'H3 %':>7s} {'H5 %':>7s} {'THD %':>7s}")
for tk in TUBES:
    d = np.loadtxt(f"/home/lewisbrown/claude-code/smps-design-tools/ngspice_examples/_closedloop_test/jl_{tk}.data")
    t = d[:, 0]; v_ap_drive = d[:, 3]
    mask = t > t[-1] - 0.2
    ts = t[mask]; vs = v_ap_drive[mask]
    dt = 50e-6
    t_u = np.arange(ts[0], ts[-1], dt)
    v_u = np.interp(t_u, ts, vs); v_u -= v_u.mean()
    N = len(t_u); win = np.hanning(N)
    V = np.fft.rfft(v_u * win) * (2/N) / 0.5
    f = np.fft.rfftfreq(N, dt)
    def mag(f0, bw=20):
        idx = (f > f0-bw) & (f < f0+bw)
        return float(np.max(np.abs(V[idx])))
    h = [mag(k*1000) for k in range(1, 6)]
    THD = float(np.sqrt(sum(x*x for x in h[1:])) / h[0]) if h[0] > 0 else 0.0
    print(f"{tk:9s} {h[0]*1000:>9.0f} {h[1]/h[0]*100:>7.2f} {h[2]/h[0]*100:>7.2f} {h[4]/h[0]*100:>7.2f} {THD*100:>7.2f}")
