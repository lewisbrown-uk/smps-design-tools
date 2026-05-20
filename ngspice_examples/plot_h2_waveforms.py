"""Plot the actual v_ap waveform and FFT for all 4 tubes — see what
the filament really sees vs. what it's supposed to see.

This script exists to PROVE that the variable-R FETs are operating
correctly (or not) at steady state. Output: PNG with rows of (cycle, FFT)
for each tube, showing v_drv_atten (input to all-pass), v_ap (output of
all-pass), and the corresponding bridge inputs v_osc_drive / v_ap_drive
(after the buffers; what the filament actually sees).
"""
import sys, types, subprocess, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_closed_loop as tcl
from validate_cap_470nf_iv6max_level1 import swap_to_level1

tcl.T_END = 2.5
TUBES = ("iv18", "iv6", "ilc11_7", "ilc11_8")


def run_one(tube_key):
    spec = tcl.TUBES[tube_key]
    mc = {k: spec[k] for k in ("r_amb","sigma_eps_A","c_th","r_top_ref","r_bot_ref","r_sense")}
    mc["t_rail_ramp"] = 100e-6
    for k in ("booster","ce_buf","mos_buf"):
        if spec.get(k): mc[k] = True
    for k in ("buf_fb1","buf_fb_ap","v_buf","c_ap"):
        if spec.get(k) is not None: mc[k] = spec[k]
    raw = tcl.make_netlist(tcl.WORK / f"h2plot_{tube_key}.data",
                            v_preset=0.0, t_ramp=0.0,
                            r_int_scale=spec["r_int_scale"], mc=mc)
    if spec.get("mos_buf"):
        raw = swap_to_level1(raw)
    # Add v_ap, v_osc, v_drv_atten, n_ap_plus to wrdata + .save
    extra = '\nwrdata /tmp/h2plot_extra_{tube}.data v(v_ap) v(v_osc) v(v_drv_atten) v(n_ap_plus) v(node_A) v(node_B)\n'.replace("{tube}", tube_key)
    raw = raw.replace('.endcontrol', extra + '.endcontrol', 1)
    raw = raw.replace('.save ', '.save v(v_ap) v(v_osc) v(v_drv_atten) v(n_ap_plus) v(node_A) v(node_B) ', 1)
    cir = tcl.WORK / f"h2plot_{tube_key}.cir"
    cir.write_text(raw)
    t0 = time.time()
    res = subprocess.run(["ngspice","-b",cir.name], cwd=tcl.WORK,
                          capture_output=True, text=True, timeout=1800)
    if res.returncode != 0:
        print(f"{tube_key} FAIL: {res.stderr[-200:]}")
        return tube_key, None
    d = np.loadtxt(f"/tmp/h2plot_extra_{tube_key}.data")
    return tube_key, d


def main():
    print("Running 4 tubes for waveform capture...")
    with ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(run_one, TUBES))

    fig, axes = plt.subplots(4, 3, figsize=(16, 13))
    fig.suptitle("v_ap distortion check — 2 cycles at steady state + FFT\n"
                 "Variable-R FETs should give clean all-pass (1 kHz fundamental); "
                 "instead the negative half-cycle hits body-diode V_F",
                 fontsize=11)

    for row, (tube_key, d) in enumerate(results):
        spec = tcl.TUBES[tube_key]
        if d is None:
            for c in range(3):
                axes[row][c].set_title(f"{tube_key}: FAIL")
            continue
        t = d[:,0]; v_ap=d[:,1]; v_osc=d[:,3]; v_drv_atten=d[:,5]
        n_ap_plus=d[:,7]; node_A=d[:,9]; node_B=d[:,11]
        # Pick a 2 ms window deep in steady state
        t_window_start = t[-1] - 0.005  # 5 ms before end → grab 2 cycles
        mask = t > t_window_start
        ts = t[mask]; v_ap_s = v_ap[mask]; v_drv_s = v_drv_atten[mask]
        nA = node_A[mask]; nB = node_B[mask]

        # Panel 1: v_drv_atten (input to all-pass) overlaid with v_ap (output of all-pass)
        ax = axes[row][0]
        ax.plot((ts - ts[0])*1e3, v_drv_s, "C0", lw=1.0, label="v_drv_atten (input)")
        ax.plot((ts - ts[0])*1e3, v_ap_s, "C3", lw=1.0, label="v_ap (output)")
        ax.axhline(0, color="0.5", lw=0.5)
        ax.axhline(-0.6, color="0.7", lw=0.5, linestyle="--", label="−V_F (body diode)")
        ax.set_xlabel("time [ms]")
        ax.set_ylabel("V")
        ax.set_title(f"{tcl.TUBES[tube_key]['name']}: all-pass in vs out (steady state)")
        ax.legend(loc="lower right", fontsize=8)
        ax.grid(alpha=0.3)

        # Panel 2: filament-side bridge voltages node_A, node_B  ((what the bridge sees))
        ax = axes[row][1]
        ax.plot((ts - ts[0])*1e3, nA, "C0", lw=1.0, label="node_A (filament side)")
        ax.plot((ts - ts[0])*1e3, nB, "C3", lw=1.0, label="node_B (reference side)")
        ax.plot((ts - ts[0])*1e3, nA - nB, "C2", lw=1.0, alpha=0.6, label="A − B (diff)")
        ax.set_xlabel("time [ms]")
        ax.set_ylabel("V")
        ax.set_title("bridge nodes (these drive the filament)")
        ax.legend(loc="lower right", fontsize=8)
        ax.grid(alpha=0.3)

        # Panel 3: FFT of v_ap, normalized to V1 (fundamental)
        # Use a longer window for cleaner FFT
        mask2 = t > t[-1] - 0.2  # 200 ms
        ts2 = t[mask2]; vs2 = v_ap[mask2]
        dt = 50e-6
        t_u = np.arange(ts2[0], ts2[-1], dt)
        v_u = np.interp(t_u, ts2, vs2) - np.mean(np.interp(t_u, ts2, vs2))
        N = len(t_u); win = np.hanning(N)
        V = np.fft.rfft(v_u*win) * (2/N) / 0.5
        f = np.fft.rfftfreq(N, dt)
        def mag(f0, bw=20):
            idx = (f > f0-bw) & (f < f0+bw)
            return float(np.max(np.abs(V[idx])))
        # Show fundamental + 5 harmonics
        harmonics = [mag(k*1000) for k in range(1, 11)]
        V1 = harmonics[0]
        norm = [h/V1*100 if V1>0 else 0 for h in harmonics]
        ax = axes[row][2]
        bars = ax.bar(range(1, 11), norm, color=["C2"]+["C3"]*9)
        bars[0].set_color("C2")  # fundamental green
        ax.set_xlabel("harmonic (×1 kHz)")
        ax.set_ylabel("% of V1")
        ax.set_title(f"FFT of v_ap: V1={V1*1000:.0f} mV, "
                     f"H2={norm[1]:.0f}%, H3={norm[2]:.0f}%, H5={norm[4]:.0f}%")
        ax.set_xticks(range(1, 11))
        ax.grid(alpha=0.3, axis="y")
        # Annotate which harmonics survive chopper demod (1, 3, 5, 7, 9 — odd)
        for k in range(1, 11):
            if k % 2 == 1:
                ax.axvspan(k-0.4, k+0.4, alpha=0.05, color="C1")

    fig.tight_layout(rect=(0, 0, 1, 0.97))
    out = HERE / "h2_waveforms.png"
    fig.savefig(out, dpi=110)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
