"""Closed-loop VFD-filament regulator: Wien bridge + JFET all-pass + AC bridge
with thermal filament model + synchronous demodulator + integrator,
all running on TLV9104-class op-amps and +/-5 V supplies.

Cold-start transient: V(T_node) starts at 300 K, integrator pre-charged so
V_ctl pinches off the JFET (max all-pass phase shift -> max bridge drive
amplitude). As the filament heats, V_diff falls, V_demod falls, integrator
drifts V_ctl toward 0 (JFET more on, smaller phase shift, less drive),
self-regulating to V_filament_rms ~= 1 V at R(T) = 100 ohm and T = 800 K.
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
WORK = HERE / "_closedloop_test"
WORK.mkdir(exist_ok=True)

# Filament parameters
T_AMB = 300.0
T_OP_TARGET = 800.0
R_OP = 100.0
P_OP = 0.010
R_AMB = R_OP / (T_OP_TARGET / T_AMB) ** 1.2
SIGMA_EPS_A = P_OP / (T_OP_TARGET ** 4 - T_AMB ** 4)
TAU_TH = 0.100
C_TH = TAU_TH * 4 * SIGMA_EPS_A * T_OP_TARGET ** 3

# Bridge / drive
R_SENSE = 10.0
F0 = 1000.0

# Wien bridge (alpha = 0.5 for ~3 V peak, well clear of +/-5 V rails)
ALPHA = 0.5
R_TOT_BJT = 240e3
RTOP_BJT = (1 - ALPHA) * R_TOT_BJT
RBOT_BJT = ALPHA * R_TOT_BJT

# All-pass: corner near f0 mid-bias
R_AP = 1.59e3
C_AP = 100e-9

# Loop integrator (~5 Hz bandwidth)
R_INT = 100e3
C_INT = 1.0 / (2 * np.pi * 5.0 * R_INT)

T_END = 2.500

OPAMP = ("uopamp_lvl2 Avol=3.16meg GBW=1meg Rin=100g Rout=10 "
         "Iq=600u Ilimit=1 Vrail=100m Vmax=20")


def make_netlist(data_path: Path) -> str:
    return f"""* Closed-loop VFD-filament regulator with thermal model

.include {(HERE/'uopamp.lib').as_posix()}

.param T_amb={T_AMB}
.param R_amb={R_AMB:.6g}
.param sigma_eps_A={SIGMA_EPS_A:.6e}
.param C_th={C_TH:.6e}

Vcc  vcc 0  5
Vee  vee 0 -5

* === Wien bridge oscillator (alpha=0.5) ===
R1   v_osc  ns   10k
C1   ns     np   15.915n  IC=0
R2   np     0    10k
C2   np     0    15.915n  IC=10m
Rg   nn     0    10k
Rfa  nn     fb   10k
Rfb  fb     v_osc  12k
Q1   fb     b1    v_osc Q2N3904
Q2   v_osc  b2    fb    Q2N3904
Rtop1 fb    b1    {RTOP_BJT:.6g}
Rbot1 b1    v_osc {RBOT_BJT:.6g}
Rtop2 v_osc b2    {RTOP_BJT:.6g}
Rbot2 b2    fb    {RBOT_BJT:.6g}
XU_osc np nn vcc vee v_osc {OPAMP}

* === JFET-controlled all-pass: V_ap = V_osc * (1 - jwR_DS C)/(1 + jwR_DS C) ===
* Two equal R from V_osc and from V_ap into op-amp's V- (inverting unity gain).
R_ap1 v_osc n_ap_minus {R_AP:.6g}
R_ap2 v_ap  n_ap_minus {R_AP:.6g}
* JFET R_DS in series from V_osc to V+ (the cap-shunted node).
J_var v_osc v_ctl n_ap_plus J201
C_ap n_ap_plus 0 {C_AP:.6g}    IC=0
XU_ap n_ap_plus n_ap_minus vcc vee v_ap {OPAMP}
.model J201 NJF(Vto=-1.5 Beta=1.0e-3 Lambda=0)

* === AC Wheatstone bridge ===
* Filament arm: V_osc -> R_filament(thermal) -> node_A -> R_sense -> V_ap
B_fil v_osc node_A I = (V(v_osc) - V(node_A)) / (R_amb * (V(T_node)/T_amb)^1.2)
R_sen node_A v_ap {R_SENSE:.6g}
* Reference arm: V_osc -> R_top_ref -> node_B -> R_sense_ref -> V_ap
R_top_ref v_osc node_B {R_OP:.6g}
R_bot_ref node_B v_ap  {R_SENSE:.6g}

* === Filament thermal subnet ===
B_pelec 0 T_node I = (V(v_osc)-V(node_A))*(V(v_osc)-V(node_A)) / (R_amb * (V(T_node)/T_amb)^1.2)
B_prad  T_node 0 I = sigma_eps_A * (V(T_node)^4 - T_amb^4)
C_th T_node 0 {{C_th}} IC={T_AMB}
B_R r_fil 0 V = R_amb * (V(T_node)/T_amb)^1.2

* === Difference amp (1-op-amp subtractor, gain 1) ===
R_a1 node_A n_diff_minus 10k
R_a2 n_diff_minus n_diff 10k
R_b1 node_B n_diff_plus 10k
R_b2 n_diff_plus 0 10k
XU_diff n_diff_plus n_diff_minus vcc vee n_diff {OPAMP}

* === Comparator (behavioural sign of V_osc) ===
B_cmp n_cmp 0 V = 5 * tanh(V(v_osc) * 1000)

* === Polarity-switching demodulator ===
.model swMod SW(VT=0 VH=0.1 RON=10 ROFF=1G)
S1 n_diff vplus n_cmp 0 swMod
S2 0      vplus 0     n_cmp swMod
R_bias vplus 0 1Meg
R_din n_diff n_dem_minus 10k
R_dfb n_demout n_dem_minus 10k
XU_dem vplus n_dem_minus vcc vee n_demout {OPAMP}

* === Integrator -> V_ctl (loop amp) ===
* V_ctl_raw = -1/(R*C) * integral(V_demout). Cold filament: V_demout < 0,
* so V_ctl_raw integrates positive. We want V_ctl negative when cold so
* the JFET stays pinched off. Wire B_invert to flip sign.
R_intin n_demout n_int_minus {R_INT:.6g}
* IC and anti-windup limit chosen to bound max filament drive. At
* V_ctl = -1.0 V the JFET R_DS ~= 1 kohm (using J201 Vto=-1.5,
* Beta=1e-3 in the linear region), giving an all-pass corner near
* 1.6 kHz and ~55% of the maximum bridge differential. That delivers
* roughly 1.5x the steady-state filament power -- enough for fast
* warm-up but with bounded overshoot instead of running at full rail.
* IC on the cap = V(n_int_minus) - V(v_int_out) = 0 - (+1.0) = -1.0
* sets V(v_int_out) = +1.0 at t=0 -> V_ctl = -1.0.
C_intfb n_int_minus v_int_out {C_INT:.6e}  IC=-1.0
XU_int 0 n_int_minus vcc vee v_int_out {OPAMP}

* Anti-windup: clamp v_int_out at [0, +1.0] V to match the V_ctl range.
B_aw v_int_out 0 I = (V(v_int_out) > 1.0) * (V(v_int_out) - 1.0) * 1e3
+                  + (V(v_int_out) < 0) * V(v_int_out) * 1e3

* Map integrator output to JFET range [-1.0, 0]: invert.
B_ctl v_ctl 0 V = max(-1.0, min(0, -V(v_int_out)))

* === 2N3904 ===
.model Q2N3904 NPN(IS=6.734f XTI=3 EG=1.11 VAF=74.03 BF=416.4 NE=1.259
+ ISE=6.734f IKF=66.78m XTB=1.5 BR=.7371 NC=2 ISC=0 IKR=0 RC=1
+ CJC=3.638p MJC=.3085 VJC=.75 FC=.5 CJE=4.493p MJE=.2593 VJE=.75
+ TR=239.5n TF=301.2p ITF=.4 VTF=4 XTF=2 RB=10)

.options reltol=1e-6 abstol=1p chgtol=1f
.tran 10u {T_END} UIC

.control
run
wrdata {data_path.as_posix()} v(v_osc) v(v_ap) v(node_A) v(node_B) v(n_diff) v(n_demout) v(v_ctl) v(v_int_out) v(T_node) v(r_fil)
.endcontrol

.end
"""


def main():
    if shutil.which("ngspice") is None:
        raise RuntimeError("ngspice not found")

    cir = WORK / "closedloop.cir"
    dat = WORK / "closedloop.data"
    cir.write_text(make_netlist(dat))
    print(f"Running closed-loop transient (T_END = {T_END*1e3:.0f} ms)...")
    result = subprocess.run(["ngspice", "-b", cir.name], cwd=WORK,
                            capture_output=True, text=True)
    if result.returncode != 0:
        print("STDERR:")
        print(result.stderr[-3000:])
        print("STDOUT tail:")
        print(result.stdout[-3000:])
        raise RuntimeError("ngspice failed")
    print("done. Loading data...")

    d = np.loadtxt(dat)
    # wrdata layout: t, vosc, t, vap, t, vA, t, vB, t, vdiff, t, vdem, t, vctl, t, vint, t, T, t, R
    t = d[:, 0]
    v_osc, v_ap = d[:, 1], d[:, 3]
    v_A, v_B = d[:, 5], d[:, 7]
    v_diff = d[:, 9]
    v_dem = d[:, 11]
    v_ctl = d[:, 13]
    v_int = d[:, 15]
    T = d[:, 17]
    R = d[:, 19]

    # V across filament (= V_osc - V_node_A)
    v_fil = v_osc - v_A

    print(f"\nFinal state at t={t[-1]*1e3:.0f} ms:")
    print(f"  T  = {T[-1]:.1f} K")
    print(f"  R  = {R[-1]:.2f} ohm")
    print(f"  V_ctl = {v_ctl[-1]:.3f} V")

    fig, axes = plt.subplots(5, 1, figsize=(10, 11), sharex=True)
    ax_vfil, ax_T, ax_R, ax_dem, ax_ctl = axes

    ax_vfil.plot(t * 1e3, v_fil, color="C0", lw=0.5)
    ax_vfil.set_ylabel("V_filament [V]")
    ax_vfil.set_title("Closed-loop VFD filament regulator: cold-start transient")
    ax_vfil.grid(True, alpha=0.4)

    ax_T.plot(t * 1e3, T, color="C3")
    ax_T.axhline(T_OP_TARGET, color="0.5", linestyle="--",
                 label=f"target = {T_OP_TARGET:.0f} K")
    ax_T.set_ylabel("T [K]")
    ax_T.grid(True, alpha=0.4); ax_T.legend()

    ax_R.plot(t * 1e3, R, color="C0")
    ax_R.axhline(R_OP, color="0.5", linestyle="--",
                 label=f"target = {R_OP:.0f} $\\Omega$")
    ax_R.set_ylabel("R(T) [$\\Omega$]")
    ax_R.grid(True, alpha=0.4); ax_R.legend()

    ax_dem.plot(t * 1e3, v_dem, color="C2", lw=0.5)
    ax_dem.set_ylabel("V_demod [V]")
    ax_dem.grid(True, alpha=0.4)

    ax_ctl.plot(t * 1e3, v_ctl, color="C4")
    ax_ctl.set_xlabel("Time [ms]")
    ax_ctl.set_ylabel("V_ctl (JFET gate) [V]")
    ax_ctl.grid(True, alpha=0.4)

    fig.tight_layout()
    out = HERE / "closed_loop_coldstart.png"
    fig.savefig(out, dpi=120)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
