"""Small-signal closed-loop analysis of the filament regulator, per tube.

Computes the linearized open-loop transfer function L(s) = G_c(s) * G_plant(s)
around the operating point, then extracts:
  - Crossover frequency
  - Phase margin
  - Closed-loop dominant pole(s)
  - Damping ratio if there's a complex pair

Uses the OP values measured from the validation sims and the analytical
small-signal gains.

Plant signal chain (V_ctl small-signal -> V_demand small-signal):
    V_ctl -> R_DS (JFET: dR/dV_ctl = -2*beta*R_DS^2 at OP)
          -> x = omega*R_DS*C_AP
          -> |V_d| = v_osc * 2x/sqrt(1+x^2) and phase arg(V_d) = arctan(1/x)
          -> P_fil = |V_d|^2/2 * R_fil/(R_fil+R_sen)^2
          -> T_node (first-order thermal pole at 1/tau_th)
          -> R_fil = R_amb * (T/T_amb)^fil_exp
          -> bridge_factor = R_top/(R_top+R_bot) - R_fil/(R_fil+R_sen)
          -> V_diff (AC at f0) = bridge_factor * V_d
          -> V_demod_DC = (2/pi) * Re(V_diff * exp(-j*arg(V_osc)))
"""
import numpy as np
import scipy.signal as sig
import sys
sys.path.insert(0, '.')

# Loop constants from test_closed_loop.py
F0 = 1000.0
W0 = 2 * np.pi * F0
K_ATTEN = (56e3 + 9.1e3) / 9.1e3   # 7.15
V_OSC_PK = 3.0
v_drv_atten = V_OSC_PK / K_ATTEN   # 0.42 V_pk
TAU_TH = 0.100
T_AMB = 300.0
T_OP_TARGET = 800.0
FIL_EXP = 1.2
BETA = 2.2e-3
V_P = -1.5

# Compensator
R_INT = 30e3   # r_int_scale=0.3 * R_INT_BASE=100k
C_INT = 1.0 / (2*np.pi*5*100e3)   # 318 nF
R_PID = 1e6
C_PID = 1e-9
C_HF = 10e-9

# Per-tube parameters
TUBES = {
    # V_ctl_OP is read directly from the validation sim instead of computed
    # from tube physics, because the booster-output-stage's actual transfer
    # function is messier than the simple K_buf gain (cap coupling, bias
    # losses, etc.). Using the measured OP gives accurate linearization.
    'IV-3':     dict(R_op=100, V_op=1.0, R_sen=10, R_bot_ref=100,  K_buf=1.0,  C_AP=100e-9, V_ctl_OP_sim=-0.469, r_int_scale=0.30, name_full='IV-3'),
    'IV-6':     dict(R_op=20,  V_op=1.0, R_sen=5,  R_bot_ref=500,  K_buf=3.0,  C_AP=470e-9, V_ctl_OP_sim=-1.140, r_int_scale=2.85, name_full='IV-6'),
    'ILC1-1/7': dict(R_op=25,  V_op=5.0, R_sen=5,  R_bot_ref=1000, K_buf=10.1, C_AP=470e-9, V_ctl_OP_sim=-1.390, r_int_scale=1.98, name_full='ILC1-1/7'),
    'ILC1-1/8': dict(R_op=8,   V_op=1.2, R_sen=2,  R_bot_ref=200,  K_buf=3.5,  C_AP=470e-9, V_ctl_OP_sim=-1.070, r_int_scale=7.20, name_full='ILC1-1/8'),
}


def compensator_tf(r_int_scale=0.3):
    """G_c(s) = -Z_fb/Z_in.
    Z_in = R_intin || (1/sC_intin), Z_fb = 1/sC_intfb + R_intfb || (1/sC_hf).
    R_INT scales per-tube; the rest are common."""
    s = sig.lti
    R_INT = 100e3 * r_int_scale
    # Build numerator/denominator polynomials in s
    # Z_in = R_in/(1 + s R_in C_in)
    # Z_fb = (1 + sR_f(C_f+C_h) + s^2 R_f^2 C_f C_h) / (sC_f(1 + sR_f C_h))   -- careful
    # Better: just multiply out.
    # G_c(s) = -Z_fb/Z_in
    # Numerator(Gc) = -Z_fb * (1 + sR_in C_in)
    # Denominator(Gc) = R_in *  (denominator of Z_fb)
    R_in = R_INT; C_in = C_PID
    R_f = R_PID; C_f = C_INT; C_h = C_HF
    # Z_fb = [s C_h R_f + 1 + s C_f R_f] / [s C_f (1 + s R_f C_h)]
    #      = [1 + s R_f (C_f + C_h)] / [s C_f (1 + s R_f C_h)]
    # Wait I need to redo. 1/sC_f + R_f/(1+sR_f C_h) = ...
    # common denominator s C_f (1 + s R_f C_h):
    #   (1 + s R_f C_h)/(s C_f (1 + s R_f C_h))  +  s C_f R_f /(s C_f (1 + s R_f C_h))
    #   = [1 + s R_f C_h + s C_f R_f] / [s C_f (1 + s R_f C_h)]
    #   = [1 + s R_f (C_h + C_f)] / [s C_f (1 + s R_f C_h)]
    # Hmm but where's the SECOND zero? Let me check.
    # Actually wait, the s^2 term: there's no s^2 in either numerator term, so the
    # numerator is genuinely first-order in s. OK so I had it right: one zero at
    # 1/(R_f(C_f+C_h)).
    # Then with Z_in = R_in/(1+s R_in C_in):
    # G_c(s) = -[1 + sR_f(C_f+C_h)] (1 + sR_in C_in) / [R_in * s C_f (1 + sR_f C_h)]
    # Numerator: -[1 + sR_f(C_f+C_h)] * [1 + sR_in C_in]
    # Denominator: R_in * s * C_f * [1 + sR_f C_h]
    z1 = 1/(R_f*(C_f+C_h))    # zero (R_f, C_f+C_h composite)
    z2 = 1/(R_in*C_in)        # zero (input network)
    p1 = 0                    # integrator pole at origin
    p2 = 1/(R_f*C_h)          # HF pole
    # K_gain: the integrator's own -1 sign cancels with the inverter (V_ctl = -V_int_out)
    # that follows it. So the net compensator-to-V_ctl gain is positive.
    K_gain = +1/(R_in*C_f)
    # tf: K_gain * (s+z1)(s+z2) / (s*(s+p2))   -- factor differently
    num = K_gain * np.polymul([1, z1], [1, z2])
    den = np.polymul([1, 0], [1, p2])
    return sig.TransferFunction(num, den)


def tube_op(tube):
    """Compute the OP from the sim-measured V_ctl_OP."""
    V_ctl_OP = tube['V_ctl_OP_sim']
    R_op = tube['R_op']; V_op = tube['V_op']; R_sen = tube['R_sen']
    K_buf = tube['K_buf']; C_AP = tube['C_AP']
    # Required V_d (from tube physics at OP)
    V_fil_pk = V_op * np.sqrt(2)
    V_d_pk_OP = V_fil_pk * (R_op + R_sen) / R_op
    if K_buf == 1.0:
        V_d_max = 2 * V_OSC_PK
    else:
        V_d_max = 2 * K_buf * v_drv_atten
    # From V_ctl_OP, compute R_DS and x
    overdrive = V_ctl_OP - V_P
    if overdrive <= 0:
        return None
    R_DS_OP = 1 / (2 * BETA * overdrive)
    x_OP = W0 * R_DS_OP * C_AP
    return dict(V_d_pk_OP=V_d_pk_OP, V_d_max=V_d_max, x_OP=x_OP,
                R_DS_OP=R_DS_OP, V_ctl_OP=V_ctl_OP)


def plant_tf(tube, op):
    """Plant transfer function from V_ctl to V_demod (negative of the
    inverter is absorbed). One pole at thermal time constant; DC gain set
    by all the linearized factors.

    Returns (gain_DC, pole_frequency_Hz, transfer function)
    """
    R_op = tube['R_op']; V_op = tube['V_op']; R_sen = tube['R_sen']
    K_buf = tube['K_buf']
    C_AP = tube['C_AP']
    x = op['x_OP']
    R_DS = op['R_DS_OP']
    V_d_pk = op['V_d_pk_OP']
    if K_buf == 1.0:
        v_drive = V_OSC_PK
    else:
        v_drive = K_buf * v_drv_atten

    # Sensitivity at OP:
    # d|V_d|/dx = 2*v_drive/(1+x^2)^1.5  (V_pk per unit x)
    dVd_dx = 2 * v_drive / (1 + x**2)**1.5

    # dx/dV_ctl: x = w0*R_DS*C_AP; dR_DS/dV_ctl = -2*beta*R_DS^2 (V_ctl = V_GS)
    dx_dVctl = W0 * C_AP * (-2 * BETA * R_DS**2)

    # dP_fil/d|V_d| at OP: P_fil = |V_d|^2/2 * R_fil/(R_fil+R_sen)^2
    # dP/d|V_d| = |V_d| * R_op/(R_op+R_sen)^2  at R_fil=R_op (small-signal AC mag)
    dP_dVd = V_d_pk * R_op / (R_op + R_sen)**2

    # K_actuator = dP_fil/dV_ctl  (W per V)
    K_actuator = dP_dVd * dVd_dx * dx_dVctl

    # Thermal: R_th_eff = 1/(4*sigma_eps_A*T_op^3); plant T(s) = R_th_eff/(1 + s*tau_th)
    # By construction tau_th = 100 ms and dT/dP_DC = R_th_eff
    P_op = V_op**2 / R_op
    sigma_eps_A = P_op / (T_OP_TARGET**4 - T_AMB**4)
    R_th_eff = 1 / (4 * sigma_eps_A * T_OP_TARGET**3)

    # dR_fil/dT at T_op: R_fil = R_op*(T/T_op)^1.2 -> dR/dT = R_op*1.2/T_op
    dRfil_dT = R_op * FIL_EXP / T_OP_TARGET

    # Bridge: dBridge_factor / dR_fil = -R_sen/(R_op+R_sen)^2
    dBridge_dRfil = -R_sen / (R_op + R_sen)**2

    # Demod sensitivity at OP: V_demod_DC_change per Bridge_factor_change
    # V_demod = (2/pi) * bridge_factor * v_drive * 2x^2/(1+x^2)
    # ... where the 2x^2/(1+x^2) comes from |V_d|*cos(arg(V_d)) = v_drive * 2x^2/(1+x^2)
    K_demod = (2/np.pi) * v_drive * 2 * x**2 / (1 + x**2)

    # Sign of inverter: V_ctl = -V_int_out, so when we close the loop the inverter
    # gives an additional -1 multiplication. Including that here.
    INVERTER_GAIN = -1.0

    # DC gain of plant (V_demod / V_ctl):
    K_plant_DC = INVERTER_GAIN * K_actuator * R_th_eff * dRfil_dT * dBridge_dRfil * K_demod / INVERTER_GAIN
    # Hmm wait, the inverter is BEFORE V_ctl in our chain. Reconsider.
    # Loop: V_demod -> G_c -> V_int_out -> -1 -> V_ctl -> plant -> V_demod_back
    # So forward path is G_c * (-1) * (V_ctl_to_demod plant).
    # Closed loop: V_demod_out / V_demand_in = G_c * (-1) * P / (1 - G_c * (-1) * P_)
    # For negative-feedback, we typically want G_c * P > 0 around the loop... messy.
    # Let me just compute |L(0)| and the dominant dynamics.

    # The plant from V_ctl to V_demod (small-signal AC mag):
    K_plant_DC = K_actuator * R_th_eff * dRfil_dT * dBridge_dRfil * K_demod
    # Signs: K_actuator negative (V_ctl_up -> P_down); R_th>0; dRfil_dT>0;
    #        dBridge_dRfil<0; K_demod>0.
    # Product: (-)*(+)*(+)*(-)*(+) = + => K_plant_DC > 0. Good.

    # Thermal pole only (all other dynamics are above the loop's BW):
    plant_pole = 1 / TAU_TH   # rad/s
    num = [K_plant_DC]
    den = [1/plant_pole, 1]
    return K_plant_DC, plant_pole/(2*np.pi), sig.TransferFunction(num, den), dict(
        K_actuator=K_actuator, R_th_eff=R_th_eff, dRfil_dT=dRfil_dT,
        dBridge_dRfil=dBridge_dRfil, K_demod=K_demod, V_d_pk_OP=V_d_pk,
        sigma_eps_A=sigma_eps_A)


def analyse_loop(G_c, G_p):
    """Open-loop L = G_c * G_p (with the inverter sign absorbed into the sign
    convention: we have negative feedback, so L(s) = -G_c(s)*G_p(s) for the
    purposes of stability). G_c already has the negative sign baked in (it
    outputs -Z_fb/Z_in i.e. inverting integrator)."""
    # Multiply transfer functions
    L_num = np.polymul(G_c.num, G_p.num)
    L_den = np.polymul(G_c.den, G_p.den)
    L = sig.TransferFunction(L_num, L_den)
    # Bode
    w = np.logspace(-2, 7, 5000)
    w, mag, phase = sig.bode(L, w)
    mag_lin = 10**(mag/20)
    # Crossover: where |L| = 1 (0 dB)
    idx = np.where(mag_lin >= 1)[0]
    if len(idx):
        i_cross = idx[-1]  # last index where mag>=1
        f_cross = w[i_cross] / (2*np.pi)
        phase_at_cross = phase[i_cross]
        # Phase margin
        pm = 180 + phase_at_cross   # negative-feedback convention
        # gain margin: find -180 deg crossing
        idx_180 = np.where(phase <= -180)[0]
        if len(idx_180):
            i_gm = idx_180[0]
            f_gm = w[i_gm] / (2*np.pi)
            gain_at_180 = mag[i_gm]
            gm = -gain_at_180  # dB
        else:
            f_gm = float('inf'); gm = float('inf')
    else:
        f_cross = float('nan'); pm = float('nan'); f_gm = float('nan'); gm = float('nan')
    # Closed-loop poles
    cl_den = np.polyadd(L_num, L_den)
    cl_poles = np.roots(cl_den)
    return dict(L=L, f_cross=f_cross, phase_margin_deg=pm, f_gm=f_gm, gain_margin_dB=gm,
                cl_poles=cl_poles, w=w, mag_dB=mag, phase_deg=phase)


def main():
    for name, tube in TUBES.items():
        r_int_scale = tube['r_int_scale']
        R_INT = 100e3 * r_int_scale
        G_c = compensator_tf(r_int_scale)
        print(f"=== {name} (V_p = -1.5 V, typical), r_int_scale = {r_int_scale} ===")
        print(f"  Compensator (R_INT = {R_INT/1e3:.0f} kΩ):")
        print(f"    Poles: 0, {1/(2*np.pi*R_PID*C_HF):.2f} Hz")
        print(f"    Zeros: {1/(2*np.pi*R_PID*(C_INT+C_HF)):.2f} Hz, {1/(2*np.pi*R_INT*C_PID):.0f} Hz")
        op = tube_op(tube)
        if op is None:
            print(f"  *** No valid OP"); continue
        K_DC, f_pole, G_p, details = plant_tf(tube, op)
        print(f"  Operating point:")
        print(f"    V_d_pk_OP = {op['V_d_pk_OP']:.3f} V (of max {op['V_d_max']:.2f} V)")
        print(f"    x_OP = {op['x_OP']:.3f},  R_DS_OP = {op['R_DS_OP']:.0f} Ω,  V_ctl_OP = {op['V_ctl_OP']:+.3f} V")
        print(f"    All-pass corner at OP = {1/(2*np.pi*op['R_DS_OP']*tube['C_AP']):.0f} Hz")
        print(f"  Plant gain factors:")
        print(f"    K_actuator = dP_fil/dV_ctl  = {details['K_actuator']*1e3:.3f} mW/V")
        print(f"    R_th_eff                    = {details['R_th_eff']:.0f} K/W")
        print(f"    dR_fil/dT                   = {details['dRfil_dT']:.4f} Ω/K")
        print(f"    dBridge/dR_fil              = {details['dBridge_dRfil']*1e3:.4f} m/Ω")
        print(f"    K_demod                     = {details['K_demod']:.3f} V/Bridge-factor")
        print(f"  Plant DC gain K_plant(0) = {K_DC:.4e} V_demod / V_ctl")
        print(f"  Plant pole = {f_pole:.2f} Hz (thermal)")
        res = analyse_loop(G_c, G_p)
        print(f"  Loop crossover frequency = {res['f_cross']:.3f} Hz")
        print(f"  Phase margin             = {res['phase_margin_deg']:.1f}°")
        print(f"  Gain margin              = {res['gain_margin_dB']:.1f} dB at {res['f_gm']:.0f} Hz")
        print(f"  Closed-loop poles:")
        for p in res['cl_poles']:
            f = abs(p) / (2*np.pi)
            if np.iscomplex(p) and abs(p.imag) > 1e-6:
                wn = abs(p); zeta = -p.real/wn
                print(f"    {p.real:+.3e} ± j{abs(p.imag):.3e} rad/s  |  f={f:.2f} Hz, zeta={zeta:.3f}")
            else:
                print(f"    {p.real:+.3e} rad/s  |  f={f:.2f} Hz")
        print()


if __name__ == "__main__":
    main()
