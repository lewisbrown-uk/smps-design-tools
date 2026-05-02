"""Quantify JFET-induced THD at the all-pass output and bridge nodes.

Runs a closed-loop sim per tube, captures voltages during steady state, and
uses lock-in detection (same technique as plot_wien_thd.py) to compute THD
at each stage of the signal path:

    v(v_osc)        -- Wien output (clean reference)
    v(v_drv_atten)  -- post-Buffer-0 output that drives the JFET (booster only)
    v(v_ap)         -- post-all-pass (post-JFET); JFET distortion appears here
    v(v_ap_drive)   -- post-Buffer-2 (BJT class-AB pair); BJT distortion adds
    v(node_A/B)     -- bridge arms (what the demodulator integrates)

The delta THD(v_ap) - THD(v_drv_atten) (booster) or THD(v_ap) - THD(v_osc)
(no booster) is the JFET's contribution. Odd harmonics in particular cause
DC error after demodulation by the square-wave-referenced demodulator, so
the script also reports per-harmonic amplitudes.

Usage:
    python3 measure_jfet_thd.py [TUBE]   # default: iv3
"""
from __future__ import annotations
import sys
import subprocess
from pathlib import Path
import numpy as np

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import test_closed_loop as m

F0 = 1000.0


def run_for_thd(tube_key: str, extra_signals: list[str]):
    spec = m.TUBES[tube_key]
    mc = {k: spec[k] for k in ("r_amb", "sigma_eps_A", "c_th",
                               "r_top_ref", "r_bot_ref", "r_sense")}
    if spec.get("booster"): mc["booster"] = True
    if spec.get("c_ap") is not None: mc["c_ap"] = spec["c_ap"]
    if spec.get("buf_fb1") is not None: mc["buf_fb1"] = spec["buf_fb1"]

    work = m.WORK
    work.mkdir(exist_ok=True)
    cir = work / f"thd_{tube_key}.cir"
    dat = work / f"thd_{tube_key}.data"
    netlist = m.make_netlist(dat, v_preset=0.55, t_ramp=0.1,
                             r_int_scale=spec["r_int_scale"], mc=mc)
    sigs = ["v(v_osc)"] + extra_signals + [
        "v(v_ap)", "v(v_ap_drive)",
        "v(node_A)", "v(node_B)", "v(n_diff)"]
    new_wrdata = f"wrdata {dat.as_posix()} " + " ".join(sigs)
    netlist = "\n".join(
        new_wrdata if line.startswith("wrdata ") else line
        for line in netlist.splitlines()
    )
    cir.write_text(netlist)
    res = subprocess.run(["ngspice", "-b", cir.name], cwd=work,
                         capture_output=True, text=True)
    if res.returncode != 0:
        print(res.stderr[-2000:])
        print(res.stdout[-2000:])
        raise RuntimeError(f"ngspice failed for {tube_key}")
    d = np.loadtxt(dat)
    out = {"t": d[:, 0]}
    for i, name in enumerate(sigs):
        out[name] = d[:, 2 * i + 1]
    try:
        dat.unlink()
    except OSError:
        pass
    return out


def lockin_thd(t, x, f0, n_harmonics=10, fs=50_000):
    """Lock-in THD: subtract fitted fundamental, return THD% and per-harmonic
    amplitudes (peak, V) for harmonics 1..n_harmonics.

    Resamples x onto a uniform grid at fs, then mixes with sin/cos at f0
    with a box-car kernel snapped to an integer number of half-periods of f0
    (so the 2*f0 mixer image lands exactly on a kernel null).
    """
    t_uni = np.arange(t[0], t[-1], 1 / fs)
    x_uni = np.interp(t_uni, t, x)
    samples_per_half = fs / (2 * f0)
    N = int(round(round(0.05 * fs / samples_per_half) * samples_per_half))
    kernel = np.ones(N) / N

    def boxcar(s):
        return np.convolve(s, kernel, mode="same")

    sin1 = np.sin(2 * np.pi * f0 * t_uni)
    cos1 = np.cos(2 * np.pi * f0 * t_uni)
    I1 = 2 * boxcar(x_uni * sin1)
    Q1 = 2 * boxcar(x_uni * cos1)
    A1 = np.sqrt(I1 ** 2 + Q1 ** 2)

    fund = I1 * sin1 + Q1 * cos1
    resid = x_uni - fund
    edge = N // 2
    valid = np.zeros_like(t_uni, dtype=bool)
    valid[edge:-edge] = True

    a1 = float(np.nanmean(A1[valid]))

    harmonic_amps = [a1]
    for k in range(2, n_harmonics + 1):
        sk = np.sin(2 * np.pi * k * f0 * t_uni)
        ck = np.cos(2 * np.pi * k * f0 * t_uni)
        Ik = 2 * boxcar(resid * sk)
        Qk = 2 * boxcar(resid * ck)
        Ak = np.sqrt(Ik ** 2 + Qk ** 2)
        harmonic_amps.append(float(np.nanmean(Ak[valid])))

    p_harm = sum(a * a for a in harmonic_amps[1:])
    thd_pct = 100.0 * np.sqrt(p_harm) / a1 if a1 > 0 else float("nan")
    return thd_pct, harmonic_amps


def main():
    tube = sys.argv[1] if len(sys.argv) > 1 else "iv3"
    if tube not in m.TUBES:
        print(f"Unknown tube {tube}; choose from {list(m.TUBES.keys())}")
        sys.exit(1)
    spec = m.TUBES[tube]
    booster = bool(spec.get("booster"))
    extra = ["v(v_drv_atten)"] if booster else []
    print(f"Running closed-loop sim for {tube} (booster={'on' if booster else 'off'})...")
    res = run_for_thd(tube, extra)
    t = res["t"]
    print(f"Captured {len(t)} samples, t = {t[0]:.3f} .. {t[-1]:.3f} s")

    # Steady-state window: last 0.5 s of the 5 s sim
    t_lo, t_hi = t[-1] - 0.5, t[-1]
    mask = (t >= t_lo) & (t <= t_hi)
    print(f"Steady-state window: {t_lo:.3f} .. {t_hi:.3f} s ({mask.sum()} samples)\n")

    signals = ["v(v_osc)"]
    if booster:
        signals.append("v(v_drv_atten)")
    signals += ["v(v_ap)", "v(v_ap_drive)", "v(node_A)", "v(node_B)", "v(n_diff)"]

    print(f"{'Signal':<18s} {'A1 [Vpk]':>9s} {'THD':>8s}  Harmonic ratios (% of A1)")
    print(f"{'':18s} {'':9s} {'':8s}  H2     H3     H4     H5     H6     H7")
    print("-" * 88)
    for name in signals:
        x_ss = res[name][mask]
        t_ss = t[mask]
        thd, amps = lockin_thd(t_ss, x_ss, F0)
        a1 = amps[0]
        ratios = [100.0 * a / a1 if a1 > 0 else 0.0 for a in amps[1:]]
        print(f"{name:<18s} {a1:>9.4f} {thd:>7.3f}%  " +
              "  ".join(f"{r:>5.3f}" for r in ratios[:6]))


if __name__ == "__main__":
    main()
