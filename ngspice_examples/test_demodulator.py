"""Test the single-op-amp polarity-switching synchronous demodulator.

Topology:
  - V_osc  : reference, sin(omega*t)
  - V_in   : test signal, sin(omega*t + phi), with phi swept
  - Comparator (one TLV9104 section running open-loop) generates sign(V_osc)
  - Two voltage-controlled switches (S-element) toggle the op-amp's V+ input
    between V_in and GND based on sign(V_osc):
       sign(V_osc) > 0 -> V+ = V_in       -> gain +1, V_out = +V_in
       sign(V_osc) < 0 -> V+ = 0          -> gain -1, V_out = -V_in
    Inverting unity gain stage with R_fb = R_in.
  - First-order RC LP on V_out extracts the DC component.

Theory: V_out(t) = V_in(t) * sign(V_osc(t)). The DC component of the product
of a 1 kHz cosine V_in = A cos(omega*t + phi) and a 1 kHz square-wave (sign
of cosine) is (2/pi) * A * cos(phi) -- amplitude-independent of V_osc.

Sweeps phi from 0 to 360 deg in 15 deg steps and plots the DC output vs the
theoretical (2/pi) * cos(phi).
"""
from __future__ import annotations
import shutil
import subprocess
from pathlib import Path
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).parent
WORK = HERE / "_demod_test"
WORK.mkdir(exist_ok=True)

PHIS_DEG = list(range(0, 361, 15))
F0 = 1000.0
A_REF = 1.0
A_IN = 1.0
T_END = 200e-3   # transient duration (10x LP time constant)
T_LP = 50e-3     # LP filter time constant
R_LP = 100e3
C_LP = T_LP / R_LP


def make_netlist(phi_deg: float, data_path: Path) -> str:
    phi_rad = phi_deg * np.pi / 180
    return f"""* Single-op-amp polarity-switching synchronous demodulator
* phi = {phi_deg} deg between V_in and V_osc

.include {(HERE/'uopamp.lib').as_posix()}

* References
Vcc  vcc 0  5
Vee  vee 0 -5

* Reference and test signals at f0={F0:.0f} Hz
V_osc v_osc 0 SIN(0 {A_REF} {F0} 0 0 0)
V_in  v_in  0 SIN(0 {A_IN}  {F0} 0 0 {phi_deg})

* --- Comparator: open-loop op-amp section ---
* Output saturates to ~ +/- 4.9 V immediately
XU_cmp v_osc 0 vcc vee n_cmp uopamp_lvl2
+    Avol=3.16meg GBW=1meg Rin=100g Rout=10 Iq=600u Ilimit=1 Vrail=100m Vmax=20

* --- Polarity-switching gain stage (the "multiplier" op-amp) ---
* Inverting unity gain with V+ toggled by switches
.model swMod SW(VT=0 VH=0.1 RON=10 ROFF=1G)
S1 v_in  vplus n_cmp 0     swMod   ; V_in -> vplus when n_cmp > 0
S2 0     vplus 0     n_cmp swMod   ; GND  -> vplus when n_cmp < 0
R_bias vplus 0 1Meg                ; keep vplus defined during switch dead-zone

R_in  v_in  n_minus 10k
R_fb  n_out n_minus 10k
XU_amp vplus n_minus vcc vee n_out uopamp_lvl2
+    Avol=3.16meg GBW=1meg Rin=100g Rout=10 Iq=600u Ilimit=1 Vrail=100m Vmax=20

* --- Low-pass filter on output, tau = R*C = {T_LP*1e3:.0f} ms ---
R_lp n_out n_dc {R_LP:.6g}
C_lp n_dc  0   {C_LP:.6g}    IC=0

.tran 1u {T_END}

.control
run
wrdata {data_path.as_posix()} v(n_dc) v(n_out)
.endcontrol

.end
"""


def run_one(phi_deg: float):
    cir = WORK / f"demod_phi{phi_deg:03d}.cir"
    dat = WORK / f"demod_phi{phi_deg:03d}.data"
    cir.write_text(make_netlist(phi_deg, dat))
    subprocess.run(["ngspice", "-b", cir.name], cwd=WORK,
                   check=True, capture_output=True, text=True)
    d = np.loadtxt(dat)
    # wrdata: t, v(n_dc), t, v(n_out)
    return d[:, 0], d[:, 1], d[:, 3]


def main():
    if shutil.which("ngspice") is None:
        raise RuntimeError("ngspice not found")

    rows = []
    for phi in PHIS_DEG:
        t, v_dc, v_out = run_one(phi)
        # Average over the last 50 ms (well after the LP transient settles).
        # Time-weighted mean -- np.mean is biased on ngspice variable-timestep data.
        sel = t > T_END - 0.050
        ts_sel = t[sel]; dur_sel = ts_sel[-1] - ts_sel[0]
        v_dc_settled = float(np.trapezoid(v_dc[sel], ts_sel) / dur_sel)
        v_dc_ripple = float(np.sqrt(np.trapezoid((v_dc[sel] - v_dc_settled)**2, ts_sel) / dur_sel))
        rows.append((phi, v_dc_settled, v_dc_ripple))
        print(f"phi = {phi:3d} deg   V_DC = {v_dc_settled:+.4f} V   "
              f"ripple_std = {v_dc_ripple*1e3:.2f} mV   "
              f"theory (2/pi)cos(phi) = {2/np.pi * np.cos(np.radians(phi)):+.4f}")

    arr = np.array(rows)
    phi = arr[:, 0]
    measured = arr[:, 1]
    ripple = arr[:, 2]

    phi_dense = np.linspace(0, 360, 200)
    theory = (2 / np.pi) * np.cos(np.radians(phi_dense))

    fig, axes = plt.subplots(2, 1, figsize=(9, 7), sharex=True,
                             gridspec_kw=dict(height_ratios=[3, 1]))
    ax_v, ax_e = axes

    ax_v.plot(phi_dense, theory, "-", color="0.5", linewidth=2,
              label=r"theory: $(2/\pi)\cos\varphi$")
    ax_v.errorbar(phi, measured, yerr=ripple, fmt="o", color="C0",
                  capsize=4, label="simulation (last 50 ms mean ± 1$\\sigma$)")
    ax_v.set_ylabel(r"$V_\mathrm{DC}$ at demodulator output [V]")
    ax_v.set_title(
        "Single-op-amp polarity-switching demodulator: phase response\n"
        rf"$V_\mathrm{{ref}} = {A_REF}\cos\omega t$, "
        rf"$V_\mathrm{{in}} = {A_IN}\cos(\omega t+\varphi)$, "
        rf"$f_0={F0:.0f}\,$Hz"
    )
    ax_v.grid(True, alpha=0.4)
    ax_v.legend()

    err = measured - (2/np.pi) * np.cos(np.radians(phi))
    ax_e.plot(phi, err * 1e3, "o-", color="C3")
    ax_e.set_xlabel(r"phase $\varphi$ [deg]")
    ax_e.set_ylabel("error [mV]")
    ax_e.grid(True, alpha=0.4)
    ax_e.set_xticks(range(0, 361, 30))

    fig.tight_layout()
    out = HERE / "demodulator_phase_response.png"
    fig.savefig(out, dpi=120)
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
