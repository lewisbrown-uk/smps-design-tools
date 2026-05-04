"""Test the filament thermal model in open loop.

Filament physics (per the problem statement):
  - R(T) = R_amb * (T / T_amb)^1.2          (resistance scales as T^1.2)
  - P_rad(T) = sigma_eps_A * (T^4 - T_amb^4) (radiation dominates, T^4 law)
  - dT/dt = (P_elec - P_rad) / C_th           (thermal capacitance)
  - P_elec = V_filament^2 / R(T)              (electrical dissipation)

Design point: nominal hot operating R_op = 100 ohm at T_op = 800 K, V_rms = 1 V
gives I = 10 mA, P_op = 10 mW dissipation = P_rad(800 K). Working back:
  R_amb = R_op / (T_op/T_amb)^1.2 = 100 / (800/300)^1.2 = 31.2 ohm
  sigma_eps_A = P_op / (T_op^4 - T_amb^4) = 0.010 / (800^4 - 300^4) = 2.49e-14 W/K^4

Thermal time constant (chosen): tau_th = 100 ms. From linearised radiation
loss near T_op:
  dP_rad/dT = 4 * sigma_eps_A * T_op^3 = 4 * 2.49e-14 * 5.12e8 = 5.10e-5 W/K
  C_th = tau_th * dP_rad/dT = 0.100 * 5.10e-5 = 5.10 uJ/K

Test: drive the filament with V_rms = 1 V (= 1.414 V peak) at 1 kHz; expect
T to rise from 300 K and settle at ~800 K, R(T) settling at ~100 ohm.

The thermal-electrical coupling is implemented via behavioural B-sources:
  - "Filament" is a voltage-controlled current source carrying I = V_fil/R(T)
  - The thermal node carries V = T (Kelvin), with heat-in/heat-out as currents
  - Thermal capacitance smooths the AC ripple in P_elec since tau_th >> 1/f0
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
WORK = HERE / "_filament_test"
WORK.mkdir(exist_ok=True)

# Filament parameters
T_AMB = 300.0
T_OP_TARGET = 800.0
R_OP = 100.0
P_OP = 0.010                # 10 mW at operating point
R_AMB = R_OP / (T_OP_TARGET / T_AMB) ** 1.2
SIGMA_EPS_A = P_OP / (T_OP_TARGET ** 4 - T_AMB ** 4)
TAU_TH = 0.100              # 100 ms thermal time constant
C_TH = TAU_TH * 4 * SIGMA_EPS_A * T_OP_TARGET ** 3

V_DRIVE_PEAK = 1.0 * np.sqrt(2)  # 1 V_rms
F0 = 1000.0
T_END = 0.500               # 5 thermal time constants -- enough to settle

print(f"Filament parameters:")
print(f"  R_amb     = {R_AMB:.3f} ohm  (at T_amb = {T_AMB} K)")
print(f"  R_op      = {R_OP:.3f} ohm  (at T_op = {T_OP_TARGET} K)")
print(f"  sigma*eps*A = {SIGMA_EPS_A:.3e} W/K^4")
print(f"  C_th      = {C_TH*1e6:.3f} uJ/K")
print(f"  tau_th    = {TAU_TH*1e3:.1f} ms")


def make_netlist(data_path: Path) -> str:
    return f"""* Open-loop filament thermal test: 1 V_rms AC drive at {F0:.0f} Hz

.param T_amb={T_AMB}
.param R_amb={R_AMB:.6g}
.param sigma_eps_A={SIGMA_EPS_A:.6e}
.param C_th={C_TH:.6e}

* Drive: ideal voltage source applying 1 V_rms across the filament
V_drive v_drive 0 SIN(0 {V_DRIVE_PEAK:.6g} {F0} 0 0 0)

* "Filament" as a voltage-controlled current source.
* Resistance R(T) = R_amb * (T/T_amb)^1.2; current = V_fil / R(T).
* The thermal-node voltage V(T_node) carries temperature in Kelvin.
B_fil v_drive 0 I = (V(v_drive) - 0) / (R_amb * (V(T_node)/T_amb)^1.2)

* --- Thermal network ---
* V(T_node) holds the filament temperature (in Kelvin). Capacitor with IC=T_amb.
* Power-in current source: P_elec = V_fil^2 / R(T) flows INTO T_node
B_pelec 0 T_node I = V(v_drive)*V(v_drive) / (R_amb * (V(T_node)/T_amb)^1.2)
* Power-out current source: P_rad = sigma_eps_A * (T^4 - T_amb^4) flows OUT
B_prad  T_node 0 I = sigma_eps_A * (V(T_node)^4 - T_amb^4)
C_th T_node 0 {{C_th}} IC={T_AMB}

* Diagnostic: also output instantaneous resistance via behavioural source
B_R r_value 0 V = R_amb * (V(T_node)/T_amb)^1.2

* Tighter solver tolerance is required for accurate AC averaging into the
* slow thermal node. With the defaults (reltol=1e-3, large tstep) the
* integrator drops ~5% of the AC power and the filament equilibrates well
* below the analytic operating point.
.options reltol=1e-6 abstol=1p chgtol=1f
.tran 10u {T_END} UIC

.control
run
wrdata {data_path.as_posix()} v(T_node) v(r_value) v(v_drive)
.endcontrol

.end
"""


def main():
    if shutil.which("ngspice") is None:
        raise RuntimeError("ngspice not found")

    cir = WORK / "filament_open_loop.cir"
    dat = WORK / "filament_open_loop.data"
    cir.write_text(make_netlist(dat))
    subprocess.run(["ngspice", "-b", cir.name], cwd=WORK,
                   check=True, capture_output=True, text=True)
    d = np.loadtxt(dat)
    t = d[:, 0]
    T = d[:, 1]
    R = d[:, 3]
    Vd = d[:, 5]

    # Power and current diagnostics from the time-domain data
    I = Vd / R
    P_inst = Vd * I
    # Smooth ripple via interpolation onto a uniform grid then box-car
    # average over one f0 period (avoids ngspice adaptive-tstep edge
    # artefacts that corrupted the convolve in the previous version).
    fs = 1e5
    t_uni = np.arange(t[0], t[-1], 1 / fs)
    P_uni = np.interp(t_uni, t, P_inst)
    win_n = int(round(fs / F0))
    P_smooth_uni = np.convolve(P_uni, np.ones(win_n)/win_n, mode="same")
    P_smooth = np.interp(t, t_uni, P_smooth_uni)

    # True power average over the last 10 cycles (avoids boxcar edge bias).
    # Time-weighted mean -- np.mean is biased on ngspice variable-timestep data.
    sel_late = t > T_END - 10 / F0
    ts_late = t[sel_late]; dur_late = ts_late[-1] - ts_late[0]
    P_avg_settled = float(np.trapezoid(P_inst[sel_late], ts_late) / dur_late)

    print(f"\nSettled values at t={t[-1]*1e3:.0f} ms:")
    print(f"  T   = {T[-1]:.2f} K   (target {T_OP_TARGET:.0f} K)")
    print(f"  R   = {R[-1]:.3f} ohm (target {R_OP:.2f} ohm)")
    print(f"  P   = {P_avg_settled*1e3:.4f} mW (target {P_OP*1e3:.2f} mW)")

    fig, axes = plt.subplots(3, 1, figsize=(9, 8), sharex=True)
    ax_T, ax_R, ax_P = axes

    ax_T.plot(t * 1e3, T, color="C3", lw=1.0)
    ax_T.axhline(T_OP_TARGET, color="0.5", linestyle="--",
                 label=f"target = {T_OP_TARGET:.0f} K")
    ax_T.axhline(T_AMB, color="0.7", linestyle=":",
                 label=f"ambient = {T_AMB:.0f} K")
    ax_T.set_ylabel("Filament T [K]")
    ax_T.set_title(
        f"Filament thermal model, open loop: {V_DRIVE_PEAK/np.sqrt(2):.2f} V"
        rf"$_\mathrm{{rms}}$ at {F0:.0f} Hz, $\tau_\mathrm{{th}}={TAU_TH*1e3:.0f}$ ms"
    )
    ax_T.grid(True, alpha=0.4)
    ax_T.legend(loc="lower right")

    ax_R.plot(t * 1e3, R, color="C0", lw=1.0)
    ax_R.axhline(R_OP, color="0.5", linestyle="--",
                 label=f"target = {R_OP:.0f} $\\Omega$")
    ax_R.axhline(R_AMB, color="0.7", linestyle=":",
                 label=f"R_amb = {R_AMB:.1f} $\\Omega$")
    ax_R.set_ylabel("R(T) [$\\Omega$]")
    ax_R.grid(True, alpha=0.4)
    ax_R.legend(loc="lower right")

    ax_P.plot(t * 1e3, P_smooth * 1e3, color="C2", lw=1.0,
              label="P (1 ms boxcar mean)")
    ax_P.axhline(P_OP * 1e3, color="0.5", linestyle="--",
                 label=f"target = {P_OP*1e3:.1f} mW")
    ax_P.set_xlabel("Time [ms]")
    ax_P.set_ylabel("Filament power [mW]")
    ax_P.grid(True, alpha=0.4)
    ax_P.legend(loc="lower right")

    fig.tight_layout()
    out = HERE / "filament_open_loop.png"
    fig.savefig(out, dpi=120)
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
