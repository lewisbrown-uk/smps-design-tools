"""Measure V_filament THD in the steady state of regulator.

Quadrature THD: project v_fil onto (sin, cos) at the actual carrier
frequency (peak-search), compute residual RMS / fundamental RMS.

Compare τ=30ms (current) and other demod LP options.
"""
from pathlib import Path
import subprocess, numpy as np, re, sys, importlib

sys.path.insert(0, str(Path(__file__).parent))
import regulator as s5

WORK = Path("/tmp/stage5_thd"); WORK.mkdir(exist_ok=True)


def run_cfg(label, C_lp_val, T_end=3.0):
    cir_text = s5.make_netlist(cold_start=False, instrument_power=False,
                               T_end=T_end, C_lp=C_lp_val)
    # Redirect wrdata to our work dir
    cir_text = re.sub(
        r"wrdata \S+/run\.data",
        f"wrdata {WORK.as_posix()}/{label}.data",
        cir_text)
    cir = WORK / f"{label}.cir"
    cir.write_text(cir_text)
    res = subprocess.run(["ngspice", "-b", cir.name], cwd=WORK,
                         capture_output=True, text=True, timeout=900)
    if res.returncode != 0:
        print(f"FAIL {label}: {res.stderr[-300:]}"); return None
    return np.loadtxt(WORK / f"{label}.data")


def thd(t, v_fil, t_start=2.5, t_end=3.0, f_seed=1000.0):
    """Quadrature THD: peak-search for actual carrier f, fit sin/cos,
    return residual_RMS / fundamental_RMS in percent."""
    m = (t >= t_start) & (t <= t_end)
    ts = t[m]; vs = v_fil[m]
    # Search ±5% around seed
    fs = np.linspace(f_seed * 0.95, f_seed * 1.05, 201)
    best = (np.inf, f_seed, 0.0, 0.0)
    for f in fs:
        sin_b = np.sin(2*np.pi*f*ts)
        cos_b = np.cos(2*np.pi*f*ts)
        # Trapezoidal integration for inner products (handles non-uniform t)
        N = np.trapezoid(sin_b*sin_b, ts)
        M = np.trapezoid(cos_b*cos_b, ts)
        a = np.trapezoid(vs*sin_b, ts) / N
        b = np.trapezoid(vs*cos_b, ts) / M
        amp = np.sqrt(a*a + b*b)
        if amp > best[0] if False else -amp < best[0]:
            best = (-amp, f, a, b)
    _, f0, a, b = best
    # Project out the fundamental
    res = vs - a*np.sin(2*np.pi*f0*ts) - b*np.cos(2*np.pi*f0*ts)
    fund_rms = np.sqrt((a*a + b*b)/2)
    res_rms = np.sqrt(np.trapezoid(res*res, ts) / (ts[-1] - ts[0]))
    return res_rms / fund_rms * 100, f0, fund_rms


for label, c_lp in [("lp_100ms", 1e-6), ("lp_30ms", 300e-9), ("lp_10ms", 100e-9)]:
    d = run_cfg(label, c_lp)
    if d is None: continue
    t = d[:, 0]; v_osc = d[:, 1]; node_A = d[:, 3]; v_int = d[:, 7]; T_node = d[:, 9]
    v_fil = v_osc - node_A
    thd_pct, f0, fund_rms = thd(t, v_fil)
    print(f"{label} (C_lp = {c_lp*1e9:.0f}nF): "
          f"T_ss = {T_node[-1]:.1f} K, V_int_ss = {v_int[-1]:.3f} V, "
          f"V_fil_RMS = {fund_rms:.3f} V, "
          f"f0 = {f0:.1f} Hz, "
          f"THD = {thd_pct:.2f}%")
