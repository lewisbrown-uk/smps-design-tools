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

# Loop integrator (~5 Hz integrator zero frequency at default scale)
# These are baselines; sweep_a scales R_INT and R_PID together (Kp constant)
# to vary loop bandwidth while keeping the same PID shape.
R_INT_BASE = 100e3
C_INT_BASE = 1.0 / (2 * np.pi * 5.0 * R_INT_BASE)
R_PID_BASE = 1e6
C_PID_BASE = 1e-9
C_HF_BASE  = 1.6e-9
# Module-level "current" values (used in make_netlist when not overridden)
R_INT = R_INT_BASE
C_INT = C_INT_BASE
R_PID = R_PID_BASE
C_PID = C_PID_BASE
C_HF  = C_HF_BASE

T_END = 5.000

# TLV9104 input offset voltage: typ +/-0.3 mV, max +/-1.5 mV (datasheet).
# Use worst case to expose integrator-windup-from-offset.
OPAMP = ("uopamp_lvl2 Avol=3.16meg GBW=1meg Rin=100g Rout=10 "
         "Iq=600u Ilimit=1 Vrail=100m Vmax=20 Vos=1.5m")

# Soft-start: at power-on, hold V_int_out at V_PRESET via a switch that
# opens after T_RAMP. Mimics a real RC + Zener + analog-switch POR network.
# V_PRESET = 0 disables soft-start (the loop integrates from zero).
V_PRESET = 0.0
T_RAMP   = 0.0


def make_netlist(data_path: Path,
                 v_preset: float = None,
                 t_ramp: float = None,
                 r_int_scale: float = 1.0) -> str:
    """Generate the closed-loop netlist.
    r_int_scale: scales R_INT and R_PID together (1/scale = bandwidth scale).
    """
    if v_preset is None: v_preset = V_PRESET
    if t_ramp   is None: t_ramp   = T_RAMP
    r_int = R_INT_BASE * r_int_scale
    r_pid = R_PID_BASE * r_int_scale
    c_int = C_INT_BASE
    c_pid = C_PID_BASE
    c_hf  = C_HF_BASE
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
* R_top_ref deliberately set 1% off-nominal to mimic real resistor tolerance
* and ensure the bridge has a non-zero error signal at zero drive (otherwise
* the regulator has a chicken-and-egg cold-start trap with no IC on integrator).
R_top_ref v_osc node_B {R_OP * 0.99:.6g}
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
* PID compensator (single-op-amp form):
*   Input: R_INT || C_PID  (the parallel cap adds derivative action)
*   Feedback: R_PID in series with C_INT (the series R adds proportional)
* Transfer function: H(s) = -(R_PID + 1/sC_INT)(1 + sR_INT*C_PID) / R_INT
*   Ki = 1/(R_INT * C_INT)         integrator (DC dominates)
*   Kp = R_PID/R_INT + C_PID/C_INT proportional (mid-band)
*   Kd = R_PID * C_PID             derivative (HF, fights overshoot)
R_intin  n_demout n_int_minus {r_int:.6g}
C_intin  n_demout n_int_minus {c_pid:.6e}
R_intfb  n_int_pidp v_int_out {r_pid:.6g}
* Realistic startup: cap begins uncharged (no IC). Loop self-starts from
* the intentional 1% bridge mismatch above + Vos drift in the demod and
* integrator op-amps.
C_intfb  n_int_minus n_int_pidp {c_int:.6e}  IC=0
* HF rolloff cap: in parallel with R_PID to limit HF gain and suppress
* the f0 ripple from V_demod that the D term would otherwise pump
* through to V_ctl.
C_hf     n_int_pidp v_int_out {c_hf:.6e}     IC=0
XU_int 0 n_int_minus vcc vee v_int_out {OPAMP}

* Anti-windup: clamp v_int_out at [0, +1.0] V to match the V_ctl range.
B_aw v_int_out 0 I = (V(v_int_out) > 1.0) * (V(v_int_out) - 1.0) * 1e3
+                  + (V(v_int_out) < 0) * V(v_int_out) * 1e3

* Map integrator output to JFET range [-1.0, 0]: invert.
B_ctl v_ctl 0 V = max(-1.0, min(0, -V(v_int_out)))

* === Soft-start network (V_PRESET = {v_preset}, T_RAMP = {t_ramp} s) ===
* During the first T_RAMP seconds, a switch ties v_int_out to V_PRESET
* via a low-Z path, forcing the integrator output into the neighbourhood
* of its expected steady state. After T_RAMP the switch opens and the
* loop takes over. T_RAMP=0 disables (loop starts from zero).
.model swSS SW(VT=0 VH=0.1 RON=0.01 ROFF=1G)
V_preset_src v_preset_node 0 {v_preset:.4f}
V_ss vss 0 PWL(0 1 {max(t_ramp - 1e-6, 0):.6e} 1 {t_ramp:.6e} 0 1 0)
S_ss v_int_out v_preset_node vss 0 swSS

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


def run_one(label, v_preset=0.0, t_ramp=0.0, r_int_scale=1.0):
    """Run one closed-loop sim with the given soft-start params, return dict of arrays."""
    if shutil.which("ngspice") is None:
        raise RuntimeError("ngspice not found")
    cir = WORK / f"closedloop_{label}.cir"
    dat = WORK / f"closedloop_{label}.data"
    cir.write_text(make_netlist(dat, v_preset=v_preset, t_ramp=t_ramp,
                                r_int_scale=r_int_scale))
    result = subprocess.run(["ngspice", "-b", cir.name], cwd=WORK,
                            capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr[-2000:]); print(result.stdout[-2000:])
        raise RuntimeError(f"ngspice failed for {label}")
    d = np.loadtxt(dat)
    return dict(
        t      = d[:, 0],
        v_osc  = d[:, 1],
        v_ap   = d[:, 3],
        v_A    = d[:, 5],
        v_B    = d[:, 7],
        v_diff = d[:, 9],
        v_dem  = d[:, 11],
        v_ctl  = d[:, 13],
        v_int  = d[:, 15],
        T      = d[:, 17],
        R      = d[:, 19],
    )


def metrics(run, target_T=T_OP_TARGET):
    """Extract settling/overshoot metrics from a run.

    Settling time is defined three ways:
      - t_target_95: time to reach 95% of target rise (T_amb -> target)
      - t_settle_5K: first time after which |T - T_final| < 5 K and stays
      - t_settle_10K: same with 10 K tolerance
    """
    t, T, R = run["t"], run["T"], run["R"]
    T_peak = T.max()
    t_peak = t[T.argmax()]
    T_final = T[-1]

    def time_to_reach(thresh):
        idx = np.where(T >= thresh)[0]
        return t[idx[0]] if len(idx) else float("nan")

    def time_settled_within(tol):
        # First time after which |T - T_final| < tol for the rest of sim
        bad = np.abs(T - T_final) > tol
        # Find last 'bad' point; settling time is just after it
        idx = np.where(bad)[0]
        if len(idx) == 0:
            return float(t[0])
        return float(t[idx[-1] + 1]) if idx[-1] + 1 < len(t) else float("nan")

    return dict(
        T_final = float(T_final),
        R_final = float(R[-1]),
        T_peak  = float(T_peak),
        t_peak  = float(t_peak),
        T_overshoot = float(T_peak - target_T),
        t_95target  = time_to_reach(T_AMB + 0.95 * (target_T - T_AMB)),
        t_settle_5K  = time_settled_within(5.0),
        t_settle_10K = time_settled_within(10.0),
        v_ctl_final = float(run["v_ctl"][-1]),
    )


def plot_run(run, out_path, title):
    t = run["t"]
    v_fil = run["v_osc"] - run["v_A"]
    fig, axes = plt.subplots(5, 1, figsize=(10, 11), sharex=True)
    ax_vfil, ax_T, ax_R, ax_dem, ax_ctl = axes
    ax_vfil.plot(t*1e3, v_fil, lw=0.3, color="C0"); ax_vfil.set_ylabel("V_filament [V]")
    ax_T.plot(t*1e3, run["T"], color="C3"); ax_T.axhline(T_OP_TARGET, color="0.5", linestyle="--", label=f"target = {T_OP_TARGET:.0f} K")
    ax_T.set_ylabel("T [K]"); ax_T.legend(loc="lower right"); ax_T.grid(True, alpha=0.4)
    ax_R.plot(t*1e3, run["R"], color="C0"); ax_R.axhline(R_OP, color="0.5", linestyle="--", label=f"target = {R_OP:.0f} $\\Omega$")
    ax_R.set_ylabel("R(T) [$\\Omega$]"); ax_R.legend(loc="lower right"); ax_R.grid(True, alpha=0.4)
    ax_dem.plot(t*1e3, run["v_dem"], lw=0.3, color="C2"); ax_dem.set_ylabel("V_demod [V]"); ax_dem.grid(True, alpha=0.4)
    ax_ctl.plot(t*1e3, run["v_ctl"], lw=0.3, color="C4"); ax_ctl.set_ylabel("V_ctl (JFET gate) [V]")
    ax_ctl.set_xlabel("Time [ms]"); ax_ctl.grid(True, alpha=0.4)
    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120); plt.close(fig)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["single", "sweep_b", "sweep_a"], default="single")
    parser.add_argument("--v_preset", type=float, default=0.0)
    parser.add_argument("--t_ramp", type=float, default=0.0)
    parser.add_argument("--r_int_scale", type=float, default=1.0)
    args = parser.parse_args()
    if args.mode == "single":
        print(f"Running closed-loop transient (T_END={T_END*1e3:.0f} ms, "
              f"V_PRESET={args.v_preset}, T_RAMP={args.t_ramp}, "
              f"R_INT_SCALE={args.r_int_scale})...")
        run = run_one("single", v_preset=args.v_preset, t_ramp=args.t_ramp,
                      r_int_scale=args.r_int_scale)
        m = metrics(run)
        for k, v in m.items():
            print(f"  {k:14s} = {v:.4g}")
        plot_run(run, HERE / "closed_loop_coldstart.png",
                 f"V_preset={args.v_preset:.2f} V, T_ramp={args.t_ramp*1e3:.0f} ms, "
                 f"R_INT scale={args.r_int_scale}")
        return

    if args.mode == "sweep_b":
        # Sweep V_preset x T_ramp; for each, run sim and collect metrics.
        v_presets = [0.30, 0.45, 0.55, 0.65, 0.75]
        t_ramps   = [0.050, 0.150, 0.300]
        rows = []
        runs_for_plot = {}   # store full traces for selected combos for overlay plot
        for v_p in v_presets:
            for t_r in t_ramps:
                label = f"vp{int(v_p*100):03d}_tr{int(t_r*1e3):03d}"
                print(f"Running {label}: V_preset={v_p:.2f} V, T_ramp={t_r*1e3:.0f} ms")
                r = run_one(label, v_preset=v_p, t_ramp=t_r)
                m = metrics(r)
                m["v_preset"], m["t_ramp"] = v_p, t_r
                rows.append(m)
                print(f"  T_peak={m['T_peak']:.1f}K  T_final={m['T_final']:.1f}K  "
                      f"t_95tar={m['t_95target']*1e3:.0f}ms  t_set5K={m['t_settle_5K']*1e3:.0f}ms  "
                      f"overshoot={m['T_overshoot']:.1f}K")
                # Keep traces for v_preset = 0.55 (a likely sweet spot) for overlay
                if abs(v_p - 0.55) < 0.01:
                    runs_for_plot[t_r] = r
        # Add baseline (no soft-start) for comparison
        r0 = run_one("baseline", v_preset=0.0, t_ramp=0.0)
        m0 = metrics(r0); m0["v_preset"], m0["t_ramp"] = 0.0, 0.0
        rows.insert(0, m0)
        runs_for_plot[0.0] = r0
        print(f"baseline (no soft-start): T_peak={m0['T_peak']:.1f}K T_final={m0['T_final']:.1f}K t_95tar={m0['t_95target']*1e3:.0f}ms")

        # Save sweep results
        import csv
        keys = ["v_preset", "t_ramp", "T_peak", "T_final", "T_overshoot",
                "t_95target", "t_settle_5K", "t_settle_10K", "v_ctl_final", "R_final"]
        with open(HERE / "soft_start_sweep.csv", "w") as fh:
            w = csv.DictWriter(fh, fieldnames=keys); w.writeheader()
            for r in rows: w.writerow({k: r[k] for k in keys})

        # Overlay plot: T vs t for several t_ramps at v_preset=0.55, plus baseline
        fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
        ax_T, ax_ctl = axes
        for t_r, r in sorted(runs_for_plot.items()):
            label = "no soft-start" if t_r == 0.0 else f"V_preset=0.55 V, T_ramp={t_r*1e3:.0f} ms"
            ax_T.plot(r["t"]*1e3, r["T"], lw=1.0, label=label)
            ax_ctl.plot(r["t"]*1e3, r["v_ctl"], lw=0.4)
        ax_T.axhline(T_OP_TARGET, color="0.5", linestyle="--", label=f"target = {T_OP_TARGET:.0f} K")
        ax_T.set_ylabel("T [K]"); ax_T.grid(True, alpha=0.4); ax_T.legend(loc="lower right")
        ax_T.set_title("Soft-start sweep: T(t) vs T_ramp at V_preset = 0.55 V")
        ax_ctl.set_ylabel("V_ctl [V]"); ax_ctl.grid(True, alpha=0.4)
        ax_ctl.set_xlabel("Time [ms]")
        fig.tight_layout()
        fig.savefig(HERE / "soft_start_sweep_traces.png", dpi=120); plt.close(fig)

        # 2D heatmap: t_95target vs (V_preset, T_ramp), and overshoot
        fig, axes = plt.subplots(1, 2, figsize=(12, 5))
        ax_t95, ax_ovr = axes
        arr_t95 = np.full((len(v_presets), len(t_ramps)), np.nan)
        arr_ovr = np.full_like(arr_t95, np.nan)
        for r in rows[1:]:  # skip baseline
            i = v_presets.index(r["v_preset"]); j = t_ramps.index(r["t_ramp"])
            arr_t95[i, j] = r["t_95target"] * 1e3
            arr_ovr[i, j] = r["T_overshoot"]
        for ax, arr, title, units in [(ax_t95, arr_t95, "t to 95% of target [ms]", " ms"),
                                       (ax_ovr, arr_ovr, "T overshoot [K]", " K")]:
            im = ax.imshow(arr, aspect="auto", origin="lower",
                           extent=(t_ramps[0]*1e3-25, t_ramps[-1]*1e3+25,
                                   v_presets[0]-0.05, v_presets[-1]+0.05))
            for i, vp in enumerate(v_presets):
                for j, tr in enumerate(t_ramps):
                    val = arr[i, j]
                    txt = f"{val:.0f}" if "ms" in units else f"{val:.0f}"
                    ax.text(tr*1e3, vp, txt, ha="center", va="center", color="white" if val < np.nanmean(arr) else "black", fontsize=9)
            ax.set_xlabel("T_ramp [ms]"); ax.set_ylabel("V_preset [V]")
            ax.set_title(title); fig.colorbar(im, ax=ax)
        fig.suptitle("Soft-start sweep: settling time and overshoot")
        fig.tight_layout()
        fig.savefig(HERE / "soft_start_sweep_heatmap.png", dpi=120); plt.close(fig)
        print(f"Wrote {HERE/'soft_start_sweep_traces.png'}")
        print(f"Wrote {HERE/'soft_start_sweep_heatmap.png'}")
        print(f"Wrote {HERE/'soft_start_sweep.csv'}")


    if args.mode == "sweep_a":
        # Loop bandwidth sweep. Scale R_INT (and R_PID together to keep Kp).
        # Use the V_preset = 0.55 V, T_ramp = 100 ms soft-start so warm-up
        # isn't dominated by the integrator-from-zero phase.
        v_p = 0.55
        t_r = 0.100
        scales = [3.0, 1.0, 0.3, 0.1, 0.03]   # R_INT scale; smaller = faster loop
        rows = []
        runs_for_plot = {}
        for s in scales:
            label = f"a_scale{int(s*1000):04d}"
            f_int_zero = 5.0 / s   # ~Hz; 5 Hz at scale=1
            print(f"Running {label}: R_INT_scale={s} (f_int_zero ~ {f_int_zero:.1f} Hz)")
            r = run_one(label, v_preset=v_p, t_ramp=t_r, r_int_scale=s)
            m = metrics(r)
            m["r_int_scale"] = s
            m["f_int_zero"]  = f_int_zero
            rows.append(m)
            runs_for_plot[s] = r
            print(f"  T_peak={m['T_peak']:.1f}K  T_final={m['T_final']:.1f}K  "
                  f"t_95tar={m['t_95target']*1e3:.0f}ms  t_set5K={m['t_settle_5K']*1e3:.0f}ms  "
                  f"overshoot={m['T_overshoot']:.1f}K")

        import csv
        keys = ["r_int_scale", "f_int_zero", "T_peak", "T_final", "T_overshoot",
                "t_95target", "t_settle_5K", "t_settle_10K", "v_ctl_final", "R_final"]
        with open(HERE / "loop_bw_sweep.csv", "w") as fh:
            w = csv.DictWriter(fh, fieldnames=keys); w.writeheader()
            for r in rows: w.writerow({k: r[k] for k in keys})

        fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
        ax_T, ax_ctl = axes
        for s in sorted(runs_for_plot.keys(), reverse=True):
            r = runs_for_plot[s]
            f_z = 5.0 / s
            ax_T.plot(r["t"]*1e3, r["T"], lw=1.0,
                      label=f"R_INT scale={s} (f_int_zero={f_z:.1f} Hz)")
            ax_ctl.plot(r["t"]*1e3, r["v_ctl"], lw=0.4)
        ax_T.axhline(T_OP_TARGET, color="0.5", linestyle="--", label=f"target = {T_OP_TARGET:.0f} K")
        ax_T.set_ylabel("T [K]"); ax_T.grid(True, alpha=0.4); ax_T.legend(loc="lower right")
        ax_T.set_title(f"Loop-bandwidth sweep: T(t), V_preset={v_p:.2f} V, T_ramp={t_r*1e3:.0f} ms")
        ax_ctl.set_ylabel("V_ctl [V]"); ax_ctl.grid(True, alpha=0.4); ax_ctl.set_xlabel("Time [ms]")
        fig.tight_layout()
        fig.savefig(HERE / "loop_bw_sweep_traces.png", dpi=120); plt.close(fig)
        print(f"Wrote {HERE/'loop_bw_sweep_traces.png'}")
        print(f"Wrote {HERE/'loop_bw_sweep.csv'}")


if __name__ == "__main__":
    main()
