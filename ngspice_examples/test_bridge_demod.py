"""Test the AC Wheatstone bridge + difference amp + synchronous demodulator.

Sweeps a fixed (non-thermal) "filament" resistance across the target value
and verifies that the demodulator's DC output:
  - crosses zero at R_fil = R_target
  - has the correct sign for cold (R_fil < R_target) vs hot (R_fil > R_target)
  - is monotonic across a useful range

Bridge topology:
              V_osc o-----+--R_top_ref--+--R_bot_ref--o V_ap (= -V_osc)
                          |             |
                          R_fil      tap = node B
                          |             |
                       tap = node A
                          |
                          R_sense
                          |
                          +-------- (other end of bridge)

For symmetry, both midpoints sit at the geometric mean of the rail voltages
when the resistance ratios match. We pick R_top_ref / R_bot_ref =
R_target / R_sense so that node A = node B at balance (for any V_osc, V_ap).

Difference amp: 3-op-amp instrumentation isn't cost-effective at this stage,
so use a unity-gain difference subtractor (one op-amp, four matched 10k Rs).
Then feed V(diff) into the polarity-switching demodulator from test 1.

Drive: V_osc and V_ap = -V_osc as ideal V sources at 1 V peak (skips the
all-pass and avoids stressing TLV9104 current limits while we're proving the
principle).
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
WORK = HERE / "_bridge_test"
WORK.mkdir(exist_ok=True)

R_TARGET = 100.0    # nominal "hot" filament resistance
R_SENSE  = 10.0     # series sense resistor (also sets bridge ratio)
F0       = 1000.0   # drive frequency
V_DRIVE  = 1.0      # drive amplitude (per side; differential is 2x)

# Sweep R_fil from 0.2x to 5x R_TARGET
R_FILS = np.geomspace(0.2 * R_TARGET, 5.0 * R_TARGET, 25)

T_END = 200e-3
T_LP  = 50e-3
R_LP  = 100e3
C_LP  = T_LP / R_LP


def make_netlist(r_fil: float, data_path: Path) -> str:
    return f"""* AC Wheatstone bridge + diff amp + demodulator, R_fil = {r_fil:.2f} ohm

.include {(HERE/'uopamp.lib').as_posix()}

Vcc  vcc 0  5
Vee  vee 0 -5

* Differential drive: V_osc and its inverse
V_osc v_osc 0 SIN(0 {V_DRIVE} {F0} 0 0 0)
E_neg v_neg 0  v_osc 0 -1.0      ; V_neg = -V_osc, ideal inverter

* --- Bridge: filament arm and reference arm ---
R_fil  v_osc node_A {r_fil:.6g}
R_sen  node_A v_neg {R_SENSE:.6g}
R_top  v_osc node_B {R_TARGET:.6g}
R_bot  node_B v_neg {R_SENSE:.6g}

* --- Difference amp: classical 1-op-amp subtractor, gain 1 ---
* Inputs node_A (- input) and node_B (+ input), 10k matched
R_a1 node_A n_minus 10k
R_a2 n_minus n_diff 10k
R_b1 node_B n_plus  10k
R_b2 n_plus  0      10k
XU_diff n_plus n_minus vcc vee n_diff uopamp_lvl2
+    Avol=3.16meg GBW=1meg Rin=100g Rout=10 Iq=600u Ilimit=1 Vrail=100m Vmax=20

* --- Polarity-switching demodulator (from test 1) ---
* Comparator on V_osc -> n_cmp
XU_cmp v_osc 0 vcc vee n_cmp uopamp_lvl2
+    Avol=3.16meg GBW=1meg Rin=100g Rout=10 Iq=600u Ilimit=1 Vrail=100m Vmax=20

.model swMod SW(VT=0 VH=0.1 RON=10 ROFF=1G)
S1 n_diff vplus n_cmp 0     swMod
S2 0      vplus 0     n_cmp swMod
R_bias vplus 0 1Meg

R_din n_diff n_minus2 10k
R_dfb n_demout n_minus2 10k
XU_dem vplus n_minus2 vcc vee n_demout uopamp_lvl2
+    Avol=3.16meg GBW=1meg Rin=100g Rout=10 Iq=600u Ilimit=1 Vrail=100m Vmax=20

R_lp n_demout n_dc {R_LP:.6g}
C_lp n_dc 0 {C_LP:.6g}    IC=0

.tran 1u {T_END}

.control
run
wrdata {data_path.as_posix()} v(n_dc) v(n_diff) v(node_A) v(node_B)
.endcontrol

.end
"""


def run_one(r_fil: float):
    cir = WORK / f"bridge_{r_fil:09.4f}.cir"
    dat = WORK / f"bridge_{r_fil:09.4f}.data"
    cir.write_text(make_netlist(r_fil, dat))
    subprocess.run(["ngspice", "-b", cir.name], cwd=WORK,
                   check=True, capture_output=True, text=True)
    d = np.loadtxt(dat)
    # cols: t, v(n_dc), t, v(n_diff), t, v(node_A), t, v(node_B)
    t = d[:, 0]
    v_dc    = d[:, 1]
    v_diff  = d[:, 3]
    v_A     = d[:, 5]
    v_B     = d[:, 7]
    return t, v_dc, v_diff, v_A, v_B


def main():
    if shutil.which("ngspice") is None:
        raise RuntimeError("ngspice not found")

    rows = []
    for r in R_FILS:
        t, v_dc, v_diff, v_A, v_B = run_one(r)
        sel = t > T_END - 0.050
        v_dc_settled = float(np.mean(v_dc[sel]))
        v_diff_amp = float(np.std(v_diff[sel]) * np.sqrt(2))   # peak from RMS
        # Predicted: bridge midpoint difference at balance is 0; off balance,
        # V_diff_peak = V_drive_diff * (R_sense/(R+R_sense) - R_sense/(R_T+R_sense))
        # where V_drive_diff = 2 * V_DRIVE (differential)
        V_diff_predicted = 2 * V_DRIVE * (
            R_SENSE / (r + R_SENSE) - R_SENSE / (R_TARGET + R_SENSE)
        )
        rows.append((r, v_dc_settled, v_diff_amp, V_diff_predicted))
        print(f"R_fil = {r:7.2f}  V_diff_pk(meas) = {v_diff_amp:+.4f} V  "
              f"V_diff_pk(theory) = {V_diff_predicted:+.4f} V  "
              f"V_DC(demod) = {v_dc_settled:+.5f} V")

    arr = np.array(rows)
    r_fil = arr[:, 0]
    v_dc = arr[:, 1]
    v_diff_meas = arr[:, 2] * np.sign(arr[:, 3])  # restore sign
    v_diff_th = arr[:, 3]

    fig, axes = plt.subplots(2, 1, figsize=(9, 7), sharex=True)
    ax_b, ax_d = axes

    ax_b.semilogx(r_fil, v_diff_th * 1000, "-", color="0.5",
                  label="theory: bridge $\\Delta V$")
    ax_b.semilogx(r_fil, v_diff_meas * 1000, "o", color="C0",
                  label=r"simulation: peak $V_\mathrm{diff}$ (signed)")
    ax_b.axvline(R_TARGET, color="r", linestyle=":",
                 label=f"$R_\\mathrm{{target}}$ = {R_TARGET:.0f} Ω")
    ax_b.axhline(0, color="0.6", linewidth=0.5)
    ax_b.set_ylabel("Bridge midpoint $\\Delta V$ peak [mV]")
    ax_b.set_title(
        "AC Wheatstone bridge + 1-op-amp synchronous demodulator: error sweep\n"
        rf"$R_\mathrm{{target}}={R_TARGET:.0f}\,\Omega$, "
        rf"$R_\mathrm{{sense}}={R_SENSE:.0f}\,\Omega$, "
        rf"$V_\mathrm{{drive}}=\pm{V_DRIVE:.0f}\,$V at {F0:.0f} Hz"
    )
    ax_b.grid(True, which="both", alpha=0.4)
    ax_b.legend()

    ax_d.semilogx(r_fil, v_dc * 1000, "o-", color="C2",
                  label=r"$V_\mathrm{DC}$ at demodulator output")
    ax_d.axvline(R_TARGET, color="r", linestyle=":")
    ax_d.axhline(0, color="0.6", linewidth=0.5)
    ax_d.set_xlabel(r"$R_\mathrm{filament}$ [$\Omega$]")
    ax_d.set_ylabel(r"Demodulator $V_\mathrm{DC}$ [mV]")
    ax_d.grid(True, which="both", alpha=0.4)
    ax_d.legend()

    fig.tight_layout()
    out = HERE / "bridge_demod_sweep.png"
    fig.savefig(out, dpi=120)
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
