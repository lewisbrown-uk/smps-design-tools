"""Per-stage distortion diagnostic for the split-gain SE H11F arch.

Captures key nodes along the signal chain:
  v_atten        — Wien × attenuator output (input to Stage 1)
  v_drv1         — Stage 1 (H11F-in-feedback) output (small AC, ~3mV_pk)
  v_drv          — Stage 2 (G2=201) output (~0.6V_pk)
  v_osc_drive    — Buffer + class-AB BJT output (~8.5V_pk)
  V_fil          = v_osc_drive - node_A — what the filament sees

For each node, project the AC waveform onto its fundamental + 2nd + 3rd
harmonics (quadrature) to extract amplitude ratios.  Growth of Hn from
one stage to the next localizes where the distortion is added.
"""
import sys, subprocess, re
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import regulator as s5

WORK = Path("/tmp/stage5_distortion"); WORK.mkdir(exist_ok=True)


def fit_harmonics(t, v, t_start, t_end, f0_seed=1000.0):
    """Project v(t) over [t_start, t_end] onto sin/cos at f0, 2f0, 3f0.
    Returns dict with amplitude of each harmonic and THD."""
    m = (t >= t_start) & (t <= t_end)
    ts = t[m]; vs = v[m]
    # Find f0 precisely by peak-search around seed
    best_amp = 0; f0 = f0_seed
    for f in np.linspace(f0_seed * 0.95, f0_seed * 1.05, 401):
        sb = np.sin(2*np.pi*f*ts); cb = np.cos(2*np.pi*f*ts)
        a = np.trapezoid(vs*sb, ts) / np.trapezoid(sb*sb, ts)
        b = np.trapezoid(vs*cb, ts) / np.trapezoid(cb*cb, ts)
        amp = np.sqrt(a*a + b*b)
        if amp > best_amp:
            best_amp = amp; f0 = f; a1, b1 = a, b
    # Extract H2, H3 at 2f0, 3f0
    harmonics = {1: (a1, b1)}
    for n in [2, 3, 4, 5]:
        f_n = n * f0
        sb = np.sin(2*np.pi*f_n*ts); cb = np.cos(2*np.pi*f_n*ts)
        a = np.trapezoid(vs*sb, ts) / np.trapezoid(sb*sb, ts)
        b = np.trapezoid(vs*cb, ts) / np.trapezoid(cb*cb, ts)
        harmonics[n] = (a, b)
    # DC component
    dc = np.trapezoid(vs, ts) / (ts[-1] - ts[0])
    # Residual after removing all harmonics 1..5
    res = vs.copy() - dc
    for n in [1, 2, 3, 4, 5]:
        a, b = harmonics[n]
        res -= a*np.sin(2*np.pi*n*f0*ts) + b*np.cos(2*np.pi*n*f0*ts)
    fund_pk = np.sqrt(harmonics[1][0]**2 + harmonics[1][1]**2)
    h_pks = {n: np.sqrt(harmonics[n][0]**2 + harmonics[n][1]**2) for n in harmonics}
    res_rms = np.sqrt(np.trapezoid(res*res, ts) / (ts[-1] - ts[0]))
    return dict(f0=f0, dc=dc, fund_pk=fund_pk, h=h_pks, res_rms=res_rms)


def main():
    cir_text = s5.make_netlist(use_split_gain=True, t_src_ramp=0.6, T_end=4.0)
    # Add per-stage traces
    extra = " v(v_atten) v(v_drv1) v(v_drv) v(v_osc_drive) v(node_A)"
    cir_text = cir_text.replace(
        ".save v(v_osc_drive) v(node_A) v(n_demod_dc) v(v_int) v(T_node) v(r_fil) v(n_led_a)",
        ".save v(v_atten) v(v_drv1) v(v_drv) v(v_osc_drive) v(node_A) v(n_demod_dc) v(v_int) v(T_node) v(r_fil) v(n_led_a)"
    )
    cir_text = re.sub(
        r"wrdata \S+/run\.data v\(v_osc_drive\) v\(node_A\) v\(n_demod_dc\) v\(v_int\) v\(T_node\) v\(r_fil\) v\(n_led_a\)",
        f"wrdata {WORK.as_posix()}/run.data v(v_atten) v(v_drv1) v(v_drv) v(v_osc_drive) v(node_A) v(n_demod_dc) v(v_int) v(T_node) v(r_fil) v(n_led_a)",
        cir_text)
    (WORK / "d.cir").write_text(cir_text)
    res = subprocess.run(["ngspice","-b","d.cir"], cwd=WORK, capture_output=True, text=True, timeout=500)
    if res.returncode != 0:
        print("FAIL:", res.stderr[-500:]); return

    d = np.loadtxt(WORK / "run.data")
    # Columns (pairs of t, val): 0:t, 1:v_atten, 3:v_drv1, 5:v_drv, 7:v_osc, 9:node_A,
    # 11:n_demod_dc, 13:v_int, 15:T_node, 17:r_fil, 19:n_led_a
    t        = d[:,0]
    signals = {
        "v_atten     (input)":           d[:,1],
        "v_drv1      (post Stage 1)":    d[:,3],
        "v_drv       (post Stage 2)":    d[:,5],
        "v_osc_drive (post buffer)":     d[:,7],
        "V_fil       (filament V)":      d[:,7] - d[:,9],
    }

    t_start, t_end = 3.5, 4.0
    print(f"=== Per-stage distortion (window {t_start}-{t_end}s, T={d[-1,15]:.1f}K) ===")
    print(f"{'Stage':<32s} {'fund_pk':>10s} {'DC':>9s} "
          f"{'H2/H1':>7s} {'H3/H1':>7s} {'H4/H1':>7s} {'H5/H1':>7s} "
          f"{'res/H1':>8s} {'THD':>6s}")
    print("-" * 100)
    for name, sig in signals.items():
        h = fit_harmonics(t, sig, t_start, t_end)
        fund = h["fund_pk"]
        h2 = h["h"][2]/fund*100
        h3 = h["h"][3]/fund*100
        h4 = h["h"][4]/fund*100
        h5 = h["h"][5]/fund*100
        # THD = sqrt(sum H_n^2)/H_1 for n=2..5
        thd_h = np.sqrt(sum(h["h"][n]**2 for n in [2,3,4,5])) / fund * 100
        # Total residual (THD-N) including non-harmonic content
        res = h["res_rms"] * np.sqrt(2) / fund * 100  # RMS to peak ratio
        # Format fund_pk with auto-unit
        if fund < 0.1:
            fund_str = f"{fund*1000:.3f}mV"
        else:
            fund_str = f"{fund:.3f}V"
        # DC with auto-unit
        dc = h["dc"]
        if abs(dc) < 0.1:
            dc_str = f"{dc*1000:+.2f}mV"
        else:
            dc_str = f"{dc:+.3f}V"
        print(f"{name:<32s} {fund_str:>10s} {dc_str:>9s} "
              f"{h2:>6.3f}% {h3:>6.3f}% {h4:>6.3f}% {h5:>6.3f}% "
              f"{res:>7.3f}% {thd_h:>5.3f}%")


if __name__ == "__main__":
    main()
