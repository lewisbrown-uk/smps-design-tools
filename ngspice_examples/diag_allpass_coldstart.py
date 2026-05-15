"""Analytical study of the loop-gain attenuation at cold start, due to the
JFET-VCR all-pass topology.

Topology (matches the .cir generation in test_closed_loop.py):

    v_drv_atten = V_osc / k_atten       (passive divider, k_atten ~ 7.15)

    All-pass:  v_ap = v_drv_atten * (1 - j*x) / (1 + j*x),
               x = w0 * R_DS * C_AP

    Buffer 1 (inverting via CE BJT trick):  v_osc_drive = -K_buf * v_drv_atten
    Buffer 2 (inverting via CE BJT trick):  v_ap_drive  = -K_buf * v_ap

    Bridge differential drive:
        V_d = v_osc_drive - v_ap_drive
            = -K_buf * v_drv_atten * (1 - H_ap)
            = -K_buf * v_drv_atten * 2*j*x / (1 + j*x)

At cold start V_ctl ~ 0, JFET fully on, R_DS small, x << 1, so V_d ~ -2*j*x*K*v_drv_atten:
    -- SMALL magnitude (linear in x)
    -- ~90 deg shifted from V_osc (rejected by sync demod whose ref is sign(V_osc))

The synchronous demodulator's reference is in phase with V_osc.
DC out = (2/pi) * Re(n_diff_phasor)
where n_diff_phasor = bridge_factor(cold) * V_d.

Result: cold-start demod DC is doubly attenuated -- |V_d| is small AND the
quadrature component dominates.

Sweep V_ctl from 0 to V_p and report demod DC, |V_d|, phase, x.
Plain stdlib only (no numpy).
"""
import math
import cmath
import csv

# ---- Constants from test_closed_loop.py ----
F0 = 1000.0
W0 = 2 * math.pi * F0
R_AP = 1.59e3
C_AP = 100e-9
K_ATTEN = (56e3 + 9.1e3) / 9.1e3
V_OSC_PK = 3.0

# JFET MMBFJ113 typical
V_P  = -1.5
BETA = 2.2e-3

# Per-tube
TUBES = {
    "IV-6":     dict(R_op=20, R_sen=5, R_bot_ref=500,  K_buf=2.0),
    "ILC1-1/7": dict(R_op=25, R_sen=5, R_bot_ref=1000, K_buf=9.1),
    "ILC1-1/8": dict(R_op=8,  R_sen=2, R_bot_ref=200,  K_buf=2.5),
}

T_AMB = 300.0
T_OP  = 800.0
FIL_EXP = 1.2


def r_ds(V_gs):
    overdrive = V_gs - V_P
    if overdrive <= 0:
        return 1e9
    return 1.0 / (2 * BETA * overdrive)


def H_ap(R_DS, w=W0):
    x = w * R_DS * C_AP
    return (1 - 1j * x) / (1 + 1j * x)


def differential_drive(R_DS, K_buf, w=W0):
    v_drv_atten = V_OSC_PK / K_ATTEN
    return -K_buf * v_drv_atten * (1 - H_ap(R_DS, w))


def r_fil_cold(R_op, T=T_AMB):
    return R_op * (T / T_OP) ** FIL_EXP


def bridge_factor(R_fil, R_sen, R_top, R_bot):
    return R_top / (R_top + R_bot) - R_fil / (R_fil + R_sen)


def demod_dc(n_diff_phasor):
    return (2.0 / math.pi) * n_diff_phasor.real


def scan_tube(name, tube):
    R_op  = tube["R_op"]
    R_sen = tube["R_sen"]
    R_top = R_op * tube["R_bot_ref"] / R_sen
    R_bot = tube["R_bot_ref"]
    K_buf = tube["K_buf"]
    R_fil_at_cold = r_fil_cold(R_op)
    bf = bridge_factor(R_fil_at_cold, R_sen, R_top, R_bot)

    rows = []
    N = 401
    for i in range(N):
        V_ctl = i * V_P / (N - 1)
        R = r_ds(V_ctl)
        x = W0 * R * C_AP
        Vd = differential_drive(R, K_buf)
        nd = bf * Vd
        dc = demod_dc(nd)
        rows.append(dict(
            V_ctl=V_ctl, R_DS=R, x=x,
            absVd=abs(Vd), phase_Vd_deg=math.degrees(cmath.phase(Vd)),
            abs_n_diff=abs(nd), phase_n_diff_deg=math.degrees(cmath.phase(nd)),
            demod_dc=dc,
        ))
    return dict(name=name, R_fil_cold=R_fil_at_cold, bf=bf, K_buf=K_buf, R_top=R_top, rows=rows)


def print_summary(scan):
    print(f"\n=== {scan['name']} ===")
    print(f"  R_top_ref / R_bot_ref balance ratio = {scan['R_top'] / (scan['R_top'] + scan['rows'][0]['x']*0 + scan['rows'][0]['absVd']*0):.0f} : ...")  # just R_top
    print(f"  R_fil cold = {scan['R_fil_cold']:.2f} ohm,  bridge factor (cold) = {scan['bf']:.3f}")
    print(f"  K_buf = {scan['K_buf']}")
    print()
    print(f"  V_ctl    R_DS      x      |V_d|   phase(V_d)   |n_diff|     demod_DC (sync)")
    print(f"  ------  ------   -----   ------   ----------   ---------    ----------------")
    targets = [0.0, -0.1, -0.25, -0.5, -0.75, -1.0, -1.25, -1.4]
    for V_ctl in targets:
        R = r_ds(V_ctl)
        x = W0 * R * C_AP
        Vd = differential_drive(R, scan["K_buf"])
        nd = scan["bf"] * Vd
        dc = demod_dc(nd)
        print(f"  {V_ctl:+.2f}    {R:6.1f}   {x:5.3f}   "
              f"{abs(Vd):6.3f}   {math.degrees(cmath.phase(Vd)):+8.1f}     "
              f"{abs(nd)*1000:7.2f}m    {dc*1000:+7.2f} mV")


# Integrator gain. Current code: r_int_scale=0.3 -> R_INT=30k, C_INT=318n.
# Ki = 1/(R_INT*C_INT) = 1/9.55ms = 104.7/s.
KI_INTEGRATOR = 1.0 / (30e3 * (1.0 / (2 * math.pi * 5.0 * 100e3)))


def cold_slew_time(tube, V_ctl_target, V_int_out_initial=0.0, dt=1e-3, t_max=10.0):
    """Numerically integrate V_int_out from V_int_out_initial until V_ctl reaches
    V_ctl_target, holding the FILAMENT AT COLD R_amb (i.e., model the pre-thermal
    phase only). Returns the slew time in seconds.

    The integrator gain Ki = 1/(R*C) maps demod input mV -> V_int_out V/s.
    Cold filament drives demod NEGATIVE, integrator RAMPS POSITIVE, V_ctl goes NEGATIVE
    (V_ctl ~ -V_int_out via the inverter B_invert).
    """
    R_op  = tube["R_op"]
    R_sen = tube["R_sen"]
    R_top = R_op * tube["R_bot_ref"] / R_sen
    R_bot = tube["R_bot_ref"]
    K_buf = tube["K_buf"]
    R_fil = r_fil_cold(R_op)
    bf = bridge_factor(R_fil, R_sen, R_top, R_bot)

    V_int_out = V_int_out_initial
    t = 0.0
    history = []
    while t < t_max:
        V_ctl = -V_int_out                           # inverter
        if V_ctl <= V_ctl_target:                    # reached target
            return t, history
        R = r_ds(V_ctl)
        Vd = differential_drive(R, K_buf)
        nd_pk = bf * Vd
        n_demout_dc = demod_dc(nd_pk)
        # integrator: dV_int_out/dt = -1/(RC) * n_demout = -Ki * n_demout
        V_int_out += -KI_INTEGRATOR * n_demout_dc * dt
        # apply clamp [-0.4, +3.2] V
        if V_int_out < -0.4: V_int_out = -0.4
        if V_int_out >  3.2: V_int_out =  3.2
        t += dt
        if int(t / dt) % 50 == 0:
            history.append((t, V_int_out, V_ctl, n_demout_dc))
    return t, history


if __name__ == "__main__":
    scans = {}
    for name, tube in TUBES.items():
        scans[name] = scan_tube(name, tube)
        print_summary(scans[name])

    # CSV dump
    with open("allpass_coldstart_scan.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["tube", "V_ctl", "R_DS", "x", "absVd", "phase_Vd_deg",
                    "abs_n_diff", "phase_n_diff_deg", "demod_dc_mV"])
        for name, scan in scans.items():
            for r in scan["rows"]:
                w.writerow([name, f"{r['V_ctl']:.4f}", f"{r['R_DS']:.2f}",
                            f"{r['x']:.5f}", f"{r['absVd']:.5f}",
                            f"{r['phase_Vd_deg']:.2f}", f"{r['abs_n_diff']:.6f}",
                            f"{r['phase_n_diff_deg']:.2f}",
                            f"{r['demod_dc']*1000:.4f}"])
    print("\nSaved: allpass_coldstart_scan.csv")

    # Open-loop gain attenuation factor: |H(V_ctl)| / |H(V_ctl=V_p)|
    print("\n=== Open-loop gain ratio: cold-start (V_ctl=0) vs operating (x=1) ===")
    for name, scan in scans.items():
        rows = scan["rows"]
        # find row where x is closest to 1
        idx_op = min(range(len(rows)), key=lambda i: abs(rows[i]["x"] - 1.0))
        cold = rows[0]
        op   = rows[idx_op]
        ratio_dc = abs(cold["demod_dc"]) / max(1e-12, abs(op["demod_dc"]))
        ratio_Vd = cold["absVd"] / op["absVd"]
        print(f"  {name:9s}: at V_ctl=0  demod_DC={cold['demod_dc']*1000:+.2f} mV;  "
              f"at OP (x=1, V_ctl={op['V_ctl']:.2f}V)  demod_DC={op['demod_dc']*1000:+.2f} mV;  "
              f"ratio (cold/OP) demod_DC = {ratio_dc:.3f}  |V_d| = {ratio_Vd:.3f}")

    # Cold-start slew time: integrator running open-loop on cold filament, time
    # for V_ctl to traverse from initial preset to a "loop wake-up" target.
    # Wake-up target: x = 0.5 (loop gain ~ 80% of OP)
    V_CTL_WAKEUP = -0.92  # gives x ~= 0.5 with V_p=-1.5, beta=2.2e-3
    print(f"\n=== Cold-start integrator slew time (filament held at R_amb) ===")
    print(f"  Ki = {KI_INTEGRATOR:.1f}/s,  wake-up target V_ctl = {V_CTL_WAKEUP} V")
    print(f"\n  {'Tube':9s}  {'V_int_preset':>12s}  {'slew_to_target_ms':>17s}")
    for name, tube in TUBES.items():
        for V_init in [0.0, 0.3, 0.6, 1.0, 1.2]:
            t_slew, _ = cold_slew_time(tube, V_CTL_WAKEUP,
                                        V_int_out_initial=V_init, dt=1e-4, t_max=20.0)
            tag = "(none)" if V_init == 0.0 else ""
            print(f"  {name:9s}  {V_init:>9.2f} V {tag:>3s}  {t_slew*1000:>14.1f}")
