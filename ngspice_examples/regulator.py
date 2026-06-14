"""Canonical VFD-filament regulator: netlist generator + diagnostic harness.

`make_netlist(**TUBES[key])` is the single source of truth for the regulator
design across all four tubes (ilc11_7/iv6/iv18/ilc11_8) — H11F variable-gain
(split-gain Stage 1 + Stage 2) driving a BJT class-AB push-pull buffer, an AC
bridge, synchronous + log demod, and a PID integrator.  `dump_netlists.py` and
`netlist_to_asc.py` import this module to emit the regulator_<tube>.{cir,asc}
artifacts.  (Superseded the older all-pass test_closed_loop.py on 2026-06-02.)

The diagnostic functions below run two simulations:
  A) Cold start (no integrator IC, all caps zero, filament at T_amb).
     Find settling time, peak T (overshoot), V_fil response.
  B) Steady-state with per-device current sensing (V_im=0V sources in
     series with key paths).  Compute per-device dissipation, find hotspots.
"""
import subprocess, numpy as np, sys, re
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

HERE = Path(__file__).resolve().parent
WORK = HERE / "_regulator"; WORK.mkdir(exist_ok=True)
UOPAMP = (HERE / "uopamp.lib").as_posix()
H11F_LIB = (HERE / "spice_models" / "H11F1.spice.txt").as_posix()

QMODELS = """\
* Output class-AB push-pull: Nexperia BCX54 (NPN) / BCX51 (PNP), SOT-89, 1 A,
* VCEO 45 V (~2.5x margin on +-10 V rails; off-device sees ~17 V pk).
* Class-AB bias is a V_BE multiplier (Q_vbm_t/b, also BCX54, thermally coupled),
* tuned for Iq ~20 mA -> ~0.05-0.58 W/device.  Replaced BCX54/869 (VCEO 20 V) +
* the old 4-diode bias string, which over-biased the power devices to Iq=242 mA
* / ~1.9 W/device (verified 2026-06-04, all 4 tubes).
.model BCX54 NPN (IS=7.905E-14 NF=0.9948 ISE=6.507E-15 NE=1.302 BF=143 IKF=0.45 VAF=8 NR=0.9943 ISC=2.266E-14 NC=1.361 BR=35.83 IKR=1.8 VAR=81 RB=10.4 IRB=0.0011 RBM=2.5 RE=0.0864 RC=0.1173 XTB=0 EG=1.11 XTI=3 CJE=1.442E-10 VJE=0.7013 MJE=0.3245 TF=7.8E-10 XTF=7 VTF=5 ITF=2 PTF=0 CJC=2.052E-11 VJC=0.5 MJC=0.4015 XCJC=1 TR=2.3E-8 CJS=0 VJS=0.75 MJS=0.333 FC=0.9)
.model BCX51 PNP (IS=1.01E-13 NF=1.006 ISE=7.054E-15 NE=1.3 BF=157.5 IKF=1 VAF=15.62 NR=1.006 ISC=1.406E-14 NC=1.325 BR=13.46 IKR=0.86 VAR=80 RB=10 IRB=0.001 RBM=2.5 RE=0.1363 RC=0.006969 XTB=1.779 EG=1.11 XTI=5.698 CJE=1.049E-10 VJE=0.7623 MJE=0.3879 TF=1.115E-9 XTF=2.02 VTF=3.118 ITF=0.759 PTF=0 CJC=4.998E-11 VJC=0.9968 MJC=0.4942 XCJC=1 TR=6.5E-8 CJS=0 VJS=0.75 MJS=0.333 FC=0.8944)
"""

# Defaults below are for ILC1-1/7; per-tube values live in TUBES.
R_OP = 25.0; V_OP = 5.0; T_OP = 800.0; T_AMB = 300.0
R_SENSE = 5.0; R_TOP_REF = 5e3; R_BOT_REF = 1e3; F0 = 1000.0; FIL_EXP = 1.2
TAU_TH = 0.42  # fallback only; real per-tube tau_th lives in TUBES (geometry-estimated)

# Per-tube calibration for the unified H11F variable-gain + BJT push-pull
# regulator.  Only five things change per tube: the filament operating point
# (R_op, V_op, T_op → the thermal macromodel), the three bridge-reference
# resistors (set the regulated target R_fil = R_sense·R_top_ref/R_bot_ref =
# R_op), and the oscillator amplitude V_src_rms.  Everything else — the gain
# chain, compensator, clamps, log demod — is shared across all tubes.
# Validated 2026-06-02 (see multitube_unified note).  Keys match the
# regulator_<key>.{cir,asc} artifact filenames.  Each dict is directly
# splattable into make_netlist(**TUBES[key]).
TUBES = {
    # Re-cal 2026-06-07 for the buffered-LED + differencing-in-demod sense topology
    # (removes the standing demod error → gain-invariant setpoint).  Only R_bot trims
    # re-centre T (V_src unchanged from the original constant-V cal).
    # Cold-start (2026-06-09): the integrator senses the PRE-log signal n_demod_dc
    # directly (the ×20 "log" stage was removed and its gain folded into R_int).  This
    # keeps loop feedback un-railed through warm-up, so the loop throttles back exactly
    # as the filament reaches target → temp overshoot +0.2K, tube-independent, with no
    # clamp-ceiling ramp and no per-tube cold-start tuning.  stiff_clamp keeps the
    # anti-windup diode biting during the (still-present, harmless) drive windup slam.
    # tau_th: per-tube filament thermal time constant, geometry-estimated from
    # envelope length + R_op (d~17-54µm -> tau below); replaces the old global 0.1s
    # PLACEHOLDER.  0.1s was conservative for phase margin but wrong for the
    # transient: it hid ilc11_8's cold-start overshoot (+0.2K@0.1s -> +7.4K@0.62s)
    # and over-stated the fault peak (it under-states the dwell).  Bench-measure to
    # refine.  Validated 2026-06-10 (tau_th_study + re-run battery).
    # t_fault_hi: PER-TUBE high-side watchdog qualification (2026-06-13).  The slow
    # botref_short/topref_open faults are caught by this watchdog; the default 3 s let
    # the worst (iv6) sit 922 K for 2.3 s >900 K.  Set per-tube to floor*~1.4, where
    # floor = (cold-start V_int ride >3.7 V)/0.916 = 205/269/867/926 ms for
    # iv18/iv6/ilc11_7/ilc11_8 (vint_ride.py; tracks tau_th).  Result: every tube's
    # worst fault <=871 K, ZERO dwell >900 K, no cold-start false-trip (confirm_pertube).
    # Requires a STABLE C_hiq (C0G/film) so derating doesn't shrink it into the floor.
    "ilc11_7": dict(R_op=25.0,  V_op=5.0, T_op=800.0, R_sense=5.0,  R_top_ref=5.0e3, R_bot_ref=1.0e3, V_src_rms=0.088,  tau_th=0.42, t_fault_hi=1.2, stiff_clamp=True),
    "iv6":     dict(R_op=20.0,  V_op=1.0, T_op=800.0, R_sense=5.0,  R_top_ref=2.0e3, R_bot_ref=500.0, V_src_rms=0.019,  tau_th=0.20, t_fault_hi=0.4, stiff_clamp=True),
    "iv18":    dict(R_op=100.0, V_op=1.0, T_op=800.0, R_sense=10.0, R_top_ref=1.0e3, R_bot_ref=100.0, V_src_rms=0.0115, R_in_s1=28.0, tau_th=0.19, t_fault_hi=0.3, stiff_clamp=True),
    "ilc11_8": dict(R_op=8.0,   V_op=1.2, T_op=800.0, R_sense=2.0,  R_top_ref=800.0, R_bot_ref=200.0, V_src_rms=0.0224, tau_th=0.62, t_fault_hi=1.3, stiff_clamp=True),
}
TUBE_NAMES = {"ilc11_7": "ILC1-1/7", "iv6": "IV-6", "iv18": "IV-18", "ilc11_8": "ILC1-1/8"}


def make_netlist(*, instrument_power=False, T_end=15.0,
                  v_buf=10, V_led=5.0, t_rail_ramp=0.0,
                  R_bias=2200, k_buf=14, V_src_rms=0.1, t_src_ramp=0.017,
                  R_cs=0.01, I_limit_enable=False,
                  R_series=0.01,
                  R_op=R_OP, V_op=V_OP, T_op=T_OP, tau_th=TAU_TH,
                  R_sense=R_SENSE, R_top_ref=R_TOP_REF, R_bot_ref=R_BOT_REF,
                  R_fb_vgain=100000, R_atten_top=12000, R_atten_bot=1000,
                  use_split_gain=True,
                  R_in_s1=40, R_max_s1=140,
                  C_couple_s1s2=22e-6, R_fb_s2=2.4e3, R_gnd_s2=100,
                  K_diff=30, R_lp=100e3, C_lp=0.22e-6,
                  switch_demod=False, R_dda_in=1e3,
                  use_notch_filter=False,
                  R_tt=8e3, C_tt=10e-9,
                  R_lp_post=100e3, C_lp_post=50e-9,
                  R_int=5e4, C_int=318e-9, R_pid=1e6, C_pid=1e-9, C_hf=1e-9,
                  V_clamp_hi=4.0, V_clamp_lo=-0.5,
                  stiff_clamp=False,
                  R_led_set=270,
                  fault_supervisor=False, v_fault_arm=1.5, v_fault_trip=0.5,
                  v_fault_trip_hi=3.7, t_fault_hi=3.0, t_fault_lo=0.001,
                  overpower_protect=False, k_overpower=1.3, k_clamp=1.5, t_relay=0.007,
                  polarity_swap=False):
    """Cold-start netlist for the SE Darlington + H11F variable-gain regulator.

    polarity_swap=True (default, hardware-realistic cold start):
      LED biased between fixed V_LED supply and v_int (op-amp output sinks
      LED current).  V_int=0 → I_F=max → R_h11f=min → MAX drive.  V_int
      rises as the loop throttles back, settling at V_int_OP > 0 where the
      H11F delivers operating-point gain.  Diff-amp inputs swapped so loop
      polarity is consistent.  No IC preload — V_int starts at 0V like
      every other op-amp output in real hardware.

    polarity_swap=False (legacy):  V_int=0 → I_F=0 → no drive; loop has to
      wind V_int UP to deliver drive.  See se_h11f_overshoot_thd_tradeoff
      memory note for why this gives bigger overshoot.
    """
    V_src_pk = V_src_rms * np.sqrt(2)
    # The over-power disconnect reuses the supervisor's V_int-rail signals
    # (n_lo_int / n_hi_int / n_armed) for fault/warm-up discrimination, so it
    # requires the supervisor to be present.
    if overpower_protect:
        fault_supervisor = True

    # Per-tube filament thermal macromodel, derived from the operating point.
    # Calibrated so driving the filament at V_op (RMS) holds it at T_op.
    P_op = V_op ** 2 / R_op
    sigma_eps_A = P_op / (T_op ** 4 - T_AMB ** 4)
    C_th = tau_th * 4 * sigma_eps_A * T_op ** 3
    R_amb = R_op / (T_op / T_AMB) ** FIL_EXP
    fil_subckt = f"""\
.param T_amb={T_AMB}
.param R_amb={R_amb:.6e}
.param sigma_eps_A={sigma_eps_A:.6e}
.param C_th={C_th:.6e}
.param fil_exp={FIL_EXP}

.subckt filament v_top v_bot T_node r_fil
B_fil   v_top v_bot I = (V(v_top) - V(v_bot)) / (R_amb * (max(V(T_node),T_amb)/T_amb)^fil_exp)
B_pelec 0 T_node    I = (V(v_top)-V(v_bot))*(V(v_top)-V(v_bot)) / (R_amb * (max(V(T_node),T_amb)/T_amb)^fil_exp)
B_prad  T_node 0    I = sigma_eps_A * (max(V(T_node),T_amb)^4 - T_amb^4)
C_th    T_node 0    {{C_th}} IC={T_AMB}
B_R     r_fil 0     V = R_amb * (max(V(T_node),T_amb)/T_amb)^fil_exp
.ends
"""
    R_fb_buf = (k_buf - 1) * 1e3
    Rb_half = R_bias / 2.0
    # Models the OPA4277 (quad precision, OP07-class, all 10 positions):
    # A_OL 134 dB (~5e6), GBW 1 MHz, Vos ~10 µV typ / ~50 µV max (quad),
    # BJT class-AB output, ~0.8 mA/ch Iq.  The load-bearing op-amp requirement
    # is LOW Vos, not GBW: Suite G1 (pre-log) swept 0.5-10 MHz with zero hunting
    # and THD flat-to-improving, so faster parts are safe (the earlier "≥3 MHz
    # degrades THD + hunts" was the pre-pre-log architecture).  1 MHz chosen for
    # low Vos + cost.  Quad packaging is safe here (channel sep ±1 µV/V;
    # coupling sim showed ≤0.14 dB penalty).
    op = ("uopamp_lvl3 Avol=5meg GBW=1meg Rin=100g Rout=10 "
          "Iq=800u Ilimit=25m Vos=50u Vmax=30 Vrail=0.1")
    # Power instrumentation: insert 0-V current-sense sources in series with
    # key devices.  When instrument_power=False we omit them to keep the
    # cold-start simulation fast/small.
    if instrument_power:
        # Top NPN Darlington collectors (driver + output)
        bjt_o_drv_n_C = "vcc_buf_drv_n"
        bjt_o_out_n_C = "vcc_buf_out_n"
        bjt_o_drv_p_C = "vee_buf_drv_p"
        bjt_o_out_p_C = "vee_buf_out_p"
        instr = f"""V_im_o_drv_n vcc_buf vcc_buf_drv_n 0
V_im_o_out_n vcc_buf vcc_buf_out_n 0
V_im_o_drv_p vee_buf_drv_p vee_buf 0
V_im_o_out_p vee_buf_out_p vee_buf 0
* Also sense the bias-chain current path
V_im_chain  vcc_buf vcc_buf_chain 0"""
        # Modify chain top R to feed from vcc_buf_chain
        bbo_ta_top = "vcc_buf_chain"
    else:
        bjt_o_drv_n_C = "vcc_buf"; bjt_o_out_n_C = "vcc_buf"
        bjt_o_drv_p_C = "vee_buf"; bjt_o_out_p_C = "vee_buf"
        instr = ""
        bbo_ta_top = "vcc_buf"

    # Save list and wrdata list depend on instrumentation level
    if instrument_power:
        save_extra = (" i(V_im_o_drv_n) i(V_im_o_out_n) i(V_im_o_drv_p) i(V_im_o_out_p)"
                      " i(V_im_chain) v(vcc_top) v(vcc_buf) v(vee_top) v(vee_buf)"
                      " v(q_o_bn) v(q_o_bp) v(n_o_pair_n) v(n_o_pair_p)")
    else:
        save_extra = ""

    # ---- Optional DUAL-SIDED V_int fault supervisor (over-temp protection) ----
    # With the buffered-LED + differencing-in-demod sense topology, EVERY single
    # passive fault that overheats the filament rails V_int to a clamp (FMEA:
    # silent-hot = 0 on all 4 tubes).  So watching V_int both ways catches them all:
    #   LOW side  (V_int < v_fault_trip):  catastrophic forward-gain faults (atten/
    #     buffer) that bypass the H11F authority → loop fights to the low rail.
    #     Trips fast (~ms) — a healthy loop never sits this low.
    #   HIGH side (V_int > v_fault_trip_hi sustained): sense/setpoint/bridge-ref
    #     faults that wind the loop up to max drive.  TIME-QUALIFIED (must stay high
    #     for ~t_fault_hi) because a healthy cold-start / oscillator restart
    #     transiently rides V_int up too — a real fault holds it forever, a startup
    #     ride clears in ~1 s.  RC integrator (R_hiq·C_hiq = t_fault_hi) discriminates.
    # Both arm only after capture (V_int first > v_fault_arm) and latch (diode-cap)
    # → gate the oscillator off → filament cools to a safe state + drive a fault LED.
    # Real hw: a dual window comparator + reference + RC + diode-cap latch + LED;
    # cutoff = a transistor disabling the Wien oscillator.
    if fault_supervisor:
        R_hiq = t_fault_hi / 1e-6  # with C_hiq = 1µF → τ = t_fault_hi
        R_loq = t_fault_lo / 1e-6  # with C_loq = 1µF → τ = t_fault_lo
        supervisor_block = (
            "* ---- Dual-sided V_int fault supervisor (arm, latch, drive cutoff) ----\n"
            ".model Dlatch D(IS=1e-12 N=1)\n"
            "* arm once the loop captures (V_int first exceeds v_fault_arm)\n"
            f"B_arm n_arm_drv 0 V = (V(v_int) > {v_fault_arm:.4g}) ? 5 : 0\n"
            "D_arm n_arm_drv n_armed Dlatch\n"
            "C_arm n_armed 0 1u IC=0\n"
            "R_arm n_armed 0 1e9\n"
            "* LOW-side trip: V_int below v_fault_trip (forward-gain / loss-of-authority).\n"
            "* Threshold is set WELL BELOW any startup undershoot: a cold-start / restart\n"
            "* transiently swings V_int down (to ~0.9V at the fastest physical Wien AGC\n"
            "* ramp), but the dangerous forward-gain faults rail V_int hard to ~-0.85V, so\n"
            "* v_fault_trip=0.5 cleanly separates them. Detection is kept FAST (t_fault_lo\n"
            "* ~1ms qual, for glitch immunity only) because these faults bypass the loop\n"
            "* authority and over-drive ~50x -> the filament heats far faster than the\n"
            "* thermal time constant (50ms delay -> 1679K; 1ms -> ~940K).\n"
            f"B_lo n_lo_drv 0 V = (V(v_int) < {v_fault_trip:.4g}) ? 1 : 0\n"
            f"R_loq n_lo_drv n_lo_int {R_loq:.6g}\n"
            "C_loq n_lo_int 0 1u IC=0\n"
            "B_tr n_tr_drv 0 V = (V(n_armed) > 2.5)*(V(n_lo_int) > 0.6)*5\n"
            "D_tr n_tr_drv n_latch Dlatch\n"
            "* HIGH-side trip: V_int above v_fault_trip_hi SUSTAINED (time-qualified\n"
            "* via the R_hiq/C_hiq integrator so cold-start / restart rides don't trip)\n"
            f"B_hi n_hi_drv 0 V = (V(v_int) > {v_fault_trip_hi:.4g}) ? 1 : 0\n"
            f"R_hiq n_hi_drv n_hi_int {R_hiq:.6g}\n"
            "C_hiq n_hi_int 0 1u IC=0\n"
            "B_tr_hi n_tr_hi_drv 0 V = (V(n_armed) > 2.5)*(V(n_hi_int) > 0.6)*5\n"
            "D_tr_hi n_tr_hi_drv n_latch Dlatch\n"
            "* shared set-dominant latch (either trip latches it)\n"
            "C_lat n_latch 0 1u IC=0\n"
            "R_lat n_latch 0 1e9"
        )
        src_gate = " * (V(n_latch) < 2.5 ? 1 : 0)"
        supervisor_save = " v(n_latch) v(n_armed) v(n_hi_int) v(n_lo_int)"
    else:
        supervisor_block = "* fault supervisor disabled"
        src_gate = ""
        supervisor_save = ""

    # ---- Optional over-power protection: flat-clamp + authority-gated disconnect ----
    # Discriminator (vs the old 2s duration integrator): legitimate filament
    # over-power is loop-COMMANDED (V_int high); a loss-of-authority fault (e.g.
    # XU_buf stuck at rail) is over-power the loop is FIGHTING (V_int railed low).
    # So DISCONNECT = independent_over_power AND (V_int low [fast] OR high [slow])
    # AND armed -- reusing the supervisor's n_lo_int/n_hi_int/n_armed rail signals.
    # The flat-clamp bounds the INSTANTANEOUS drive so the peak is independent of
    # the relay's actuation lag (t_relay); the series relay disconnect then gives
    # cold-safe isolation (the actuation the supervisor lacks -- its own cutoff hits
    # the oscillator UPSTREAM of a stuck output buffer).  Validated 4 tubes: fault
    # bounded <=937K (clamp+disconnect compound: clamp caps rate, disconnect caps
    # time), zero false trips on cold-start / restart.
    # Real hw: bidirectional flat-clamp (TLV431 active shunt, per-tube ref) on
    # v_osc_drive + precision FWR + window comparators + SR latch + latching relay.
    if overpower_protect:
        V_cl = k_clamp * V_op * np.sqrt(2) * (R_op + R_sense) / R_op  # drive-node ref
        V_thop = k_overpower * V_op
        R_coil = t_relay / 1e-6  # with C_coil=1µF -> contact opens ~0.69*t_relay after latch
        overpower_block = (
            "* flat drive clamp (TLV431 active shunt / flat-clamp TVS), +/- V_cl\n"
            ".model Dcl_op D(Is=1e-7 N=0.08 RS=0.02 BV=60)\n"
            f"V_clp_op n_clp_op 0 {V_cl:.4g}\nV_cln_op n_cln_op 0 {-V_cl:.4g}\n"
            "D_clp_op v_osc_drive n_clp_op Dcl_op\nD_cln_op n_cln_op v_osc_drive Dcl_op\n"
            "* independent over-power sense: precision FWR on the filament-side drive\n"
            ".model DSch_op D(IS=1e-8 N=1.0 RS=2 BV=30 CJO=10p)\n"
            "R1op v_bridge_top nAop 10k\nR2op nAop nBop 10k\n"
            "D1op nO1op nBop DSch_op\nD2op nAop nO1op DSch_op\n"
            f"XA1op 0 nAop vcc_buf vee_buf nO1op {op}\n"
            "R3op v_bridge_top nCop 10k\nR4op nBop nCop 5k\nR5op nCop nAbsop 10k\n"
            f"XA2op 0 nCop vcc_buf vee_buf nAbsop {op}\n"
            "R_envop nAbsop n_envop 100k\nC_envop n_envop 0 0.1u IC=0\n"
            f"B_opf n_opf 0 V = (-V(n_envop) > {V_thop:.4g}) ? 1 : 0\n"
            "* authority-gated disconnect latch (over-power AND V_int railed AND armed)\n"
            ".model Dlat_op D(IS=1e-12 N=1)\n"
            ".model SWdisc_op SW(Ron=0.05 Roff=1e12 Vt=2.5 Vh=0.5)\n"
            "B_discset_op n_discset_op 0 V = (V(n_armed)>2.5)*(V(n_opf)>0.5)"
            "*(((V(n_lo_int)>0.6)+(V(n_hi_int)>0.6))>0.5 ? 1:0)*5\n"
            "D_disc_op n_discset_op n_disc_op Dlat_op\n"
            "C_disc_op n_disc_op 0 1u IC=0\nR_disc_op n_disc_op 0 1e9\n"
            "* relay contact drive: RC models actuation lag; cap starts closed (5V)\n"
            "B_coil_op n_coil_op 0 V = (V(n_disc_op) > 2.5) ? 0 : 5\n"
            f"R_coil_op n_coil_op n_discctl_op {R_coil:.6g}\n"
            "C_coil_op n_discctl_op 0 1u IC=5"
        )
        series_element = "S_disc_op v_osc_drive v_bridge_top n_discctl_op 0 SWdisc_op"
        overpower_save = " v(n_disc_op) v(n_opf) v(v_bridge_top)"
    else:
        overpower_block = "* over-power protection disabled"
        series_element = f"R_series v_osc_drive v_bridge_top {R_series}"
        overpower_save = ""

    # ---- PSU rail definitions ----
    # Ramp from 0V at t=0 to full rail at t_rail_ramp, then hold flat.
    # Held to t=100s past the ramp so end-of-PWL extrapolation doesn't drift.
    if t_rail_ramp > 0:
        rail_definitions = (
            f"V_vcc vcc_top 0 PWL(0 0 {t_rail_ramp:.6g} {v_buf:.4g} 100 {v_buf:.4g})\n"
            f"V_vee vee_top 0 PWL(0 0 {t_rail_ramp:.6g} -{v_buf:.4g} 100 -{v_buf:.4g})\n"
            f"V_led_supply n_v_led 0 PWL(0 0 {t_rail_ramp:.6g} {V_led:.4g} 100 {V_led:.4g})"
        )
    else:
        rail_definitions = (
            f"V_vcc vcc_top 0 DC {v_buf}\n"
            f"V_vee vee_top 0 DC -{v_buf}\n"
            f"V_led_supply n_v_led 0 DC {V_led}"
        )

    # ---- Active current limit at buffer output ----
    # Two small-signal BJTs sense the V across R_cs.  When |V_R_cs| > V_BE,on,
    # the corresponding limit BJT steals base drive from the output pair,
    # capping I_load.
    #   Q_cl_n (NPN): C=n_o_pair_n (steals from Q_o_out_n base),
    #                 B=n_buf_emi, E=v_osc_drive.
    #     V_BE = V(n_buf_emi)−V(v_osc_drive) = +I_load·R_cs (top sourcing).
    #     Conducts at I_load > 0.6/R_cs → throttles top NPN.
    #   Q_cl_p (PNP): C=n_o_pair_p (injects into Q_o_out_p base, raising
    #                 it and reducing PNP drive),
    #                 B=n_buf_emi, E=v_osc_drive.
    #     V_EB = V(v_osc_drive)−V(n_buf_emi) = +|I_load|·R_cs (bot sinking).
    #     Conducts at |I_load| > 0.6/R_cs → throttles bot PNP.
    # With R_cs=1.8Ω, I_limit ≈ 333 mA_pk, well above the 283 mA_pk
    # steady-state requirement so the limit doesn't engage at OP.
    if I_limit_enable:
        current_limit_block = (
            "Q_cl_n n_o_pair_n n_buf_emi v_osc_drive BCX54\n"
            "Q_cl_p n_o_pair_p n_buf_emi v_osc_drive BCX51"
        )
    else:
        current_limit_block = "* current limit disabled"

    # ---- Synchronous demodulator ----
    # switch_demod=False (default, fast): behavioural sign-multiply stand-in.
    #   B_demod = K_diff·(node_B_buf - node_A_buf)·sign(v_osc).  This is the
    #   abstraction used for routine sweeps — it's a clean B-source so it sims
    #   fast and is numerically robust.
    # switch_demod=True (hardware-faithful, slower): the real commutating
    #   analog-switch chopper that the behavioural source stands in for.  A
    #   comparator squares v_osc into the switch gate; a complementary SPDT pair
    #   (CD4053B) swaps the two buffered bridge nodes onto the +/- lines of a
    #   post-chop difference amp (so the switch BOTH differences and chops, with
    #   the gain after the chop).  Validated to regulate identically to the
    #   behavioural source (iv6 799.8/-47.5dB, ilc11_7 799.9/-34.7dB).
    #   R_dda_g is split into two series halves (R_dda_g1/g2): a single-resistor
    #   SHORT then leaves R_dda_in_g/2 to ground instead of 0, so the diff-amp
    #   keeps differential rejection instead of going single-ended.  This closes
    #   the one residual demod-component fault the FMEA found (a full R_dda_g
    #   short = +22.7K silent on iv6 / hunting on ilc11_7); split = benign on
    #   both.  Gain = R_dda_fb/R_dda_in = K_diff (balanced diff amp, R_dda_g =
    #   R_dda_fb for CM rejection).  Hardware switch = CD4053B (±5V bipolar, the
    #   ±1.45V worst-case bridge-tap signal fits with margin); NOT 74HC4053
    #   (6V-class, marginal).  Comparator = LM393/TLV3201.
    if switch_demod:
        R_dda_fb = K_diff * R_dda_in
        R_dda_g_half = R_dda_fb / 2.0
        demod_block = (
            "* Hardware commutating-switch synchronous demodulator (CD4053B chopper).\n"
            f"XU_demod_comp v_osc_drive 0 vcc_buf vee_buf n_demod_ref {op}\n"
            "B_demod_refn n_demod_refn 0 V = -V(n_demod_ref)\n"
            ".model SW_demod SW(Ron=60 Roff=1e9 Vt=0 Vh=0.5)\n"
            "S_dp1 n_demod_plus  n_node_B_buf n_demod_ref  0 SW_demod\n"
            "S_dp2 n_demod_plus  n_node_A_buf n_demod_refn 0 SW_demod\n"
            "S_dm1 n_demod_minus n_node_A_buf n_demod_ref  0 SW_demod\n"
            "S_dm2 n_demod_minus n_node_B_buf n_demod_refn 0 SW_demod\n"
            "R_dp_gnd n_demod_plus 0 1Meg\n"
            "R_dm_gnd n_demod_minus 0 1Meg\n"
            f"R_dda_inp n_demod_plus  n_dda_p {R_dda_in}\n"
            f"R_dda_g1  n_dda_p n_dda_gmid {R_dda_g_half}\n"
            f"R_dda_g2  n_dda_gmid 0 {R_dda_g_half}\n"
            f"R_dda_inm n_demod_minus n_dda_m {R_dda_in}\n"
            f"R_dda_fb  n_demod n_dda_m {R_dda_fb}\n"
            f"XU_demod_da n_dda_p n_dda_m vcc_buf vee_buf n_demod {op}"
        )
    else:
        demod_block = (
            f"B_demod n_demod 0 V = {K_diff}*(V(n_node_B_buf) - V(n_node_A_buf))"
            " * (V(v_osc_drive) >= 0 ? 1 : -1)"
        )

    # ---- Demod output filter ----
    # use_notch_filter=True: twin-T notch at 2 kHz (= 2× carrier, the chopper
    # output's primary ripple component) + buffer + 1st-order LP at ~30 Hz.
    # The notch kills the 2 kHz ripple with minimal phase lag at 1-10 Hz where
    # the loop crossover lives.  Compared to the legacy single 100 ms LP, this
    # gives both faster loop response (smaller startup overshoot) AND better
    # ripple rejection (lower THD).
    # use_notch_filter=False: legacy single 1st-order LP at R_lp · C_lp.
    if use_notch_filter:
        f_notch = 1.0 / (2 * 3.141592653589793 * R_tt * C_tt)
        f_lp_post = 1.0 / (2 * 3.141592653589793 * R_lp_post * C_lp_post)
        demod_filter_block = (
            f"* Twin-T notch at {f_notch:.0f} Hz + buffered LP at {f_lp_post:.0f} Hz\n"
            f"R_tt_1   n_demod  n_tt_a       {R_tt}\n"
            f"R_tt_2   n_tt_a   n_tt_out     {R_tt}\n"
            f"C_tt_a   n_tt_a   0            {2*C_tt} IC=0\n"
            f"C_tt_1   n_demod  n_tt_b       {C_tt} IC=0\n"
            f"C_tt_2   n_tt_b   n_tt_out     {C_tt} IC=0\n"
            f"R_tt_b   n_tt_b   0            {R_tt/2}\n"
            f"* Unity-gain buffer (high Z input loads the twin-T's output minimally)\n"
            f"XU_tt_buf n_tt_out n_tt_buffered vcc_buf vee_buf n_tt_buffered {op}\n"
            f"R_lp_demod n_tt_buffered n_demod_dc {R_lp_post}\n"
            f"C_lp_demod n_demod_dc 0 {C_lp_post} IC=0"
        )
    else:
        demod_filter_block = (
            f"R_lp_demod n_demod n_demod_dc {R_lp}\n"
            f"C_lp_demod n_demod_dc 0 {C_lp}"
        )

    # ---- H11F LED bias ----
    # polarity_swap=True: LED biased between V_LED supply and v_int (op-amp
    # sinks current).  V_int=0 → I_F=max → max H11F gain → max drive at
    # cold start.  When use_split_gain=True, inverted LED bias is mandatory
    # (cold-start low drive comes from max I_F at V_int=0).
    if use_split_gain:
        invert_led_bias = True
    else:
        invert_led_bias = polarity_swap

    if invert_led_bias:
        # R_led_set in series between V_LED supply and H11F LED anode.
        # H11F LED cathode connects to v_int (the integrator output) so
        # current sinks into the op-amp.
        h11f_line   = "X_h11f n_led_a v_int v_atten n_h11f_out H11F1"
        r_led_line  = f"R_led_set n_v_led n_led_a {R_led_set}"
    else:
        h11f_line   = "X_h11f n_led_a 0 v_atten n_h11f_out H11F1"
        r_led_line  = f"R_led_set v_int n_led_a {R_led_set}"

    # ---- Variable-gain stage topology ----
    # use_split_gain=False (legacy): H11F as input-R of single inverting amp,
    #   gain = R_fb_vgain / R_h11f.  Gain monotonic, unbounded → buffer
    #   rail-clip during cold start.
    # use_split_gain=True (new): H11F as feedback-R with R_max in parallel,
    #   R_in input, then fixed-gain Stage 2 (G2 ≈ 200) after AC coupling.
    #   H11F V_DS stays small (~3mV at OP) → linear region.  Stage 1's gain
    #   is bounded by R_max so buffer stays linear across V_int range.
    if use_split_gain:
        vgain_stage_block = (
            "* Split-gain Stage 1: H11F in feedback || R_max, R_in_s1 input\n"
            "* H11F channel between n_h11f_inv (= virtual ground) and v_drv1\n"
            "* LED bias inverted: V_LED supply → R_LED → LED anode, cathode → v_int_buf.\n"
            "* The LED is driven from a UNITY BUFFER of v_int (not v_int directly) so\n"
            "* the LED current does NOT flow through the anti-windup R_aw_out.  That\n"
            "* removes the standing demod error (e_sat = I_LED·R_aw_out) that otherwise\n"
            "* makes the setpoint depend on forward gain (the 'T tracks V_src' effect\n"
            "* and the Set-B gain-fault sensitivity).  Clamp still acts on v_int.\n"
            f"R_in_vgain v_atten n_h11f_inv {R_in_s1}\n"
            f"R_max_s1   n_h11f_inv v_drv1 {R_max_s1}\n"
            f"X_h11f     n_led_a v_int_buf n_h11f_inv v_drv1 H11F1\n"
            f"XU_led_buf v_int v_int_buf vcc_buf vee_buf v_int_buf {op}\n"
            f"XU_vgain   0 n_h11f_inv vcc_buf vee_buf v_drv1 {op}\n"
            "* DC coupling between Stage 1 and Stage 2.  AC coupling caused\n"
            "* slow settling artifacts during cold-start; Stage 1's Vos (10µV)\n"
            "* through G2=201 gives only ~2mV at v_drv, negligible.\n"
            f"R_dc_couple v_drv1 n_s2_in 0\n"
            "* Stage 2: fixed-gain non-inverting amp, G2 = 1 + R_fb/R_gnd\n"
            f"R_gnd_s2   n_minus_s2 0 {R_gnd_s2}\n"
            f"R_fb_s2    v_drv n_minus_s2 {R_fb_s2}\n"
            f"XU_s2      n_s2_in n_minus_s2 vcc_buf vee_buf v_drv {op}"
        )
    else:
        # Legacy single-stage with H11F as input-R (h11f_line from polarity_swap block)
        vgain_stage_block = (
            f"{h11f_line}\n"
            f"R_fb_vgain v_drv n_h11f_out {R_fb_vgain}\n"
            f"XU_vgain 0 n_h11f_out vcc_buf vee_buf v_drv {op}"
        )

    # ---- Anti-windup high clamp: optional cold-start trajectory shaping ----
    # stiff_clamp: sharp-knee, low-Rs clamp diode so it holds V_int hard during a
    #   fast windup slam (the soft default diode's V_F balloons under the slam and
    #   lets V_int overshoot the reference).
    dclamp_model = (".model Dclamp D(Is=1e-7 N=0.05 RS=0.01 BV=40)" if stiff_clamp
                    else ".model Dclamp D(Is=10n N=1.0 RS=0.1 BV=40 IBV=0.1m CJO=10p)")

    return f"""* Regulator netlist: polarity_swap={polarity_swap}, instrument_power={instrument_power}, use_split_gain={use_split_gain}
.include {UOPAMP}
.include {H11F_LIB}
{QMODELS}
{fil_subckt}

* Power supplies with optional ramp.  Real PSUs charge their output cap
* over ~ms; with t_rail_ramp=0 the rails step instantly (sim-only case).
* All rails ramp together so the relative timing matches hardware.
{rail_definitions}
R_sense_vcc vcc_top vcc_buf 0.1
R_sense_vee vee_top vee_buf 0.1

{instr}

* V_src models the Wien oscillator output.  We use a 2-NPN/diode CLAMP Wien
* (NOT an integrator-driven JFET AGC), which limits amplitude by clipping the
* loop gain and settles in a FEW CYCLES.  Its amplitude GROWS exponentially
* (loop gain >1) from the power-on kick to the clamp level over t_src_ramp
* (~17ms / ~17 cycles, measured from wien_oscillator.py) -- a concave-UP
* build-up, NOT the old concave-down 1-exp (which described a slow JFET AGC we
* don't use).  The integrator still winds to the V_int clamp during this fast
* rise (the harmless drive slam), but with PRE-log sensing the loop has un-railed
* feedback and throttles back exactly as the filament reaches target -> no temp
* overshoot, so no clamp-ceiling ramp is needed.
* env(t) = exp((t - t_src_ramp)*g/t_src_ramp), g=3.4 so env(0) ~ 3% (the kick),
* env(t_src_ramp) = 1, clamped at 1 thereafter.
B_src v_src 0 V = {V_src_pk:.6g} * (time < {t_src_ramp} ? exp((time-{t_src_ramp})*{3.4/t_src_ramp:.6g}) : 1) * sin(2*3.141592653589793*{F0}*time){src_gate}

R_atten_top v_src n_atten_raw {R_atten_top}
R_atten_bot n_atten_raw 0 {R_atten_bot}
XU_atten_buf n_atten_raw v_atten vcc_buf vee_buf v_atten {op}

{vgain_stage_block}

* AC-couple between Stage 2 output (v_drv) and the buffer input.
* Blocks DC propagated through the Stage 1/Stage 2 gain chain (the dominant
* DC source is Stage 2's Vos × G2=201 ≈ 1V worst-case for non-chopper op-amps).
* C × R = 16ms gives 10 Hz corner; 0.57° phase shift at the 1 kHz carrier.
* The HP filter sits in the SIGNAL (carrier) chain only — the loop's DC
* sensing path runs through the chopper+integrator and is unaffected.
C_couple_buf v_drv     v_buf_in  1u  IC=0
R_bias_buf   v_buf_in  0         16k
XU_buf       v_buf_in  n_fb_buf vcc_buf vee_buf n_buf_o {op}
R_fb_buf v_osc_drive n_fb_buf {R_fb_buf:.6g}
R_in_buf n_fb_buf 0 1k
R_bbo_ta {bbo_ta_top}     mid_bbo_t   {Rb_half:.6g}
R_bbo_tb mid_bbo_t    q_o_bn      {Rb_half:.6g}
* Bootstrap caps tie bias chain to the BJT emitter node (n_buf_emi), NOT
* the post-R_cs load (v_osc_drive).  If they bootstrap to v_osc_drive,
* the I·R_cs drop reduces V_BE on the output BJTs and they collapse at
* peak current — destroys THD and defeats the current limit.
C_bbo_t  mid_bbo_t    n_buf_emi   4.7u IC=0
* V_BE-multiplier class-AB spreader (replaces the old 4-diode string): one
* multiplier per half, op-amp still drives the n_buf_o midpoint.  Each sets
* ~2 V_BE via R_vbm1/R_vbm2 (ratio 1.68 -> Iq ~20 mA).  Q_vbm are BCX54
* thermally coupled to the output pair (tracks V_BE over temperature, sets Iq).
Q_vbm_t  q_o_bn  vbm_t_b  n_buf_o  BCX54
R_vbm_t1 q_o_bn  vbm_t_b  680
R_vbm_t2 vbm_t_b n_buf_o  1000
Q_vbm_b  n_buf_o vbm_b_b  q_o_bp   BCX54
R_vbm_b1 n_buf_o vbm_b_b  680
R_vbm_b2 vbm_b_b q_o_bp   1000
R_bbo_bb q_o_bp       mid_bbo_b   {Rb_half:.6g}
R_bbo_ba mid_bbo_b    vee_buf     {Rb_half:.6g}
C_bbo_b  mid_bbo_b    n_buf_emi   4.7u IC=0
Q_o_drv_n   {bjt_o_drv_n_C} q_o_bn      n_o_pair_n   BCX54
Q_o_out_n   {bjt_o_out_n_C} n_o_pair_n  n_buf_emi    BCX54
R_o_bleed_n n_o_pair_n n_buf_emi 5k
Q_o_drv_p   {bjt_o_drv_p_C} q_o_bp      n_o_pair_p   BCX51
Q_o_out_p   {bjt_o_out_p_C} n_o_pair_p  n_buf_emi    BCX51
R_o_bleed_p n_o_pair_p n_buf_emi 5k
* Current-sense resistor between output BJT emitters and the load.
* Current limit threshold = V_BE_on / R_cs ≈ 0.6V / R_cs.
R_cs        n_buf_emi   v_osc_drive   {R_cs}
{current_limit_block}

* Series R between buffer output and the bridge top.  Limits cold-start
* current (since R_fil is small when cold and dominates the bridge
* impedance).  Bridge balance is unchanged because both arms tap the
* same v_bridge_top node — the R_series voltage drop is common-mode.
* With overpower_protect this R is replaced by the latching-relay disconnect.
{series_element}
X_filament v_bridge_top node_A T_node r_fil filament
R_sense  node_A      v_ap_drive {R_sense}
R_topref v_bridge_top node_B    {R_top_ref}
R_botref node_B      v_ap_drive {R_bot_ref}
R_ap_gnd v_ap_drive  0          0.01

XU_buf_A  node_A n_node_A_buf vcc_buf vee_buf n_node_A_buf {op}
XU_buf_B  node_B n_node_B_buf vcc_buf vee_buf n_node_B_buf {op}

* Differencing-in-demod (replaces the old 1-op-amp difference amplifier).
* The bridge differential (node_B_buf - node_A_buf) is chopped by the drive
* sign directly, with gain K_diff.  Removing the pre-demod high-gain op-amp
* removes its single-fault failure modes: at balance it sat at ~0 output, so a
* feedback-open / input-short sent it open-loop and RAILED, forcing the loop to
* regulate to a ~5% bridge imbalance (the Set-B diff-amp overheat faults).  With
* the gain now POST-demod (gain-invariant setpoint from the buffered LED), those
* faults no longer exist.  Hardware: an analog-switch synchronous detector across
* the two buffered bridge nodes + a post-demod gain stage.  See the switch_demod
* flag above: False = this behavioural B-source (default, fast); True = the real
* commutating CD4053B chopper with split-R_dda_g (hardware-faithful, slower).
{demod_block}
{demod_filter_block}

* ===== PRE-log sensing (no separate gain stage) =====
* The integrator senses the demod output n_demod_dc DIRECTLY; the loop gain
* the old ×20 "log demod" op-amp provided is folded into R_int (=5e4 vs the
* 1e6 it had behind the ×20 — identical small-signal loop transfer).  Removing
* that stage removes the cold-start RAILING it caused: at warm-up the ×20 pinned
* its output at the −9.9V op-amp rail from ~15ms (filament still 300K) right up
* to target (×20 turns even the small near-target imbalance into >9.9V), so the
* loop was BLIND through warm-up and overshot before it could throttle back.
* n_demod_dc stays graded/un-railed, so the loop sees the filament arriving and
* backs off precisely → +0.2K temp overshoot, tube-independent (2026-06-09).
V_set n_setpoint 0 DC 0
R_int_p n_setpoint n_int_plus {R_int}
R_int_pg n_int_plus 0 1G
* PID compensator with HF rolloff (matches the tuned compensator from the
* old test_closed_loop.py architecture).
*   Input branch (parallel):  R_int || C_pid (adds Kd through input)
*   Feedback branch (series): (R_pid || C_hf) + C_int
*   H(s) = -((R_pid || 1/sC_hf) + 1/sC_int) · (1 + sR_int·C_pid) / R_int
*   Integrator zero: f_zi = 1/(2π·R_pid·C_int) ≈ 5 Hz
*   HF rolloff: f_hf = 1/(2π·R_pid·C_hf) ≈ 160 Hz
* Damping (2026-06-05): demod LP sped up (C_lp 1u->0.22u, 1.6->7.2 Hz, out of
* the crossover region) raises phase margin ~42->58 deg, collapsing the
* cold-start clamp-release ring to one bump. C_int/R_pid don't affect PM
* (crossover sits in the proportional region). R_int also scales R_bc ->
* softer anti-windup release.  Input is the PRE-log demod node (see above).
R_intin  n_demod_dc n_int_minus {R_int}
C_intin  n_demod_dc n_int_minus {C_pid}
R_pid    n_int_pidp v_int_raw {R_pid}
C_intfb  n_int_minus n_int_pidp {C_int} IC=0
C_hf     n_int_pidp v_int_raw {C_hf} IC=0
XU_int n_int_plus n_int_minus vcc_buf vee_buf v_int_raw {op}

* ===== Passive saturator + back-calc anti-windup =====
* v_int_raw is the integrator's free-swinging output.  v_int (the
* "clamped" version that drives the LED) is bounded between V_clamp_lo
* and V_clamp_hi by Schottky diodes through R_aw_out.  e_sat measures
* how far v_int_raw has wound past the clamp, and R_bc feeds that error
* back into the integrator summing junction to unwind it quickly.
{dclamp_model}
* Clamp range bounds the loop's wind-up.  In the polarity-swapped arch
* V_int=0 is "max drive" (cold-start state) and V_int_OP > 0; V_clamp_lo
* is the safety bound that prevents wind-down past the H11F's max-I_F.
* V_clamp_hi is wind-up safety past the operating point.
V_clamp_hi v_clamp_hi 0 {V_clamp_hi}
V_clamp_lo v_clamp_lo 0 {V_clamp_lo}
R_aw_out  v_int_raw v_int 10
D_aw_hi   v_int     v_clamp_hi Dclamp
D_aw_lo   v_clamp_lo v_int     Dclamp
* Back-calc diff amp: e_sat = v_int_raw - v_int (unity-gain difference)
R_diff1 v_int n_aw_diff_minus 100k
R_diff2 v_int_raw n_aw_diff_plus 100k
R_diff3 n_aw_diff_minus e_sat 100k
R_diff4 n_aw_diff_plus 0 100k
XU_aw_diff n_aw_diff_plus n_aw_diff_minus vcc_buf vee_buf e_sat {op}
* Back-calc resistor: R_bc < R_int gives FASTER unwinding than wind-up,
* so once the integrator saturates the clamp, anti-windup can pull it
* back down quickly.  R_bc = R_int / 20 → 20× faster than wind-up.
R_bc e_sat n_int_minus {R_int / 20}

{r_led_line}

{supervisor_block}

{overpower_block}

.tran 50u {T_end} 0 uic
.options reltol=1e-4 abstol=1n vntol=1u

.save v(v_osc_drive) v(node_A) v(n_demod_dc) v(v_int) v(T_node) v(r_fil) v(n_led_a){save_extra}{supervisor_save}{overpower_save}
.control
run
wrdata {WORK.as_posix()}/run.data v(v_osc_drive) v(node_A) v(n_demod_dc) v(v_int) v(T_node) v(r_fil) v(n_led_a){save_extra}{supervisor_save}{overpower_save}
.endc
.end
"""


def run(label, **kw):
    cir = WORK / f"{label}.cir"
    dat = WORK / "run.data"
    cir.write_text(make_netlist(**kw))
    res = subprocess.run(["ngspice", "-b", cir.name], cwd=WORK,
                         capture_output=True, text=True, timeout=900)
    if res.returncode != 0:
        return None, res.stderr[-400:]
    return np.loadtxt(dat), None


def cold_start_analysis():
    print("=== Cold-start analysis (realistic IC: V_int=0V, T_fil=300K, V_src ramps τ=3s) ===")
    # No preload.  V_int starts at 0V (op-amp output at power-up).  V_src
    # has an exponential 3-second envelope, modeling the Wien oscillator's
    # AGC startup transient.  With τ_src >> τ_thermal=100ms, the filament
    # tracks the drive quasi-statically and cold-start overshoot is bounded
    # to a few K — safe for the rare tubes even with real-world component
    # variation that could 2-3× the sim's overshoot.
    d, err = run("cold_start", T_end=6.0)
    if d is None: print(f"FAIL: {err}"); return None
    t = d[:, 0]
    v_osc = d[:, 1]; node_A = d[:, 3]; demod_dc = d[:, 5]
    v_int = d[:, 7]; T_node = d[:, 9]; r_fil = d[:, 11]; n_led_a = d[:, 13]

    # Find settling time: T within 1% of final
    T_final = float(T_node[-1])
    T_target = 800.0
    print(f"  T_final  = {T_final:.2f} K (target 800 K)")
    T_max = float(np.max(T_node))
    T_min_after_peak = T_max  # placeholder
    t_T_max = float(t[int(np.argmax(T_node))])
    print(f"  T_max    = {T_max:.2f} K at t={t_T_max*1000:.0f} ms")
    overshoot_pct = (T_max - T_target) / T_target * 100
    print(f"  Overshoot = {overshoot_pct:+.2f}% relative to target")

    # Settling time: time to reach within 1% of T_target and stay there
    band_lo = T_target * 0.99; band_hi = T_target * 1.01
    in_band = (T_node > band_lo) & (T_node < band_hi)
    if in_band.any():
        # last excursion out of band
        out_of_band = ~in_band
        if out_of_band.any():
            last_out = int(np.where(out_of_band)[0][-1])
            if last_out < len(t) - 1:
                t_settle = float(t[last_out+1])
                print(f"  Settling time (±1%)     = {t_settle*1000:.0f} ms")
            else:
                print(f"  Settling time (±1%)     = not yet within band")
        else:
            print(f"  Settling time (±1%)     = within band immediately")
    else:
        print(f"  Settling time (±1%)     = never within band; T_final={T_final}")

    # Also ±0.1%
    band_lo = T_target * 0.999; band_hi = T_target * 1.001
    out_of_band = ~((T_node > band_lo) & (T_node < band_hi))
    if out_of_band.any():
        last_out = int(np.where(out_of_band)[0][-1])
        if last_out < len(t) - 1:
            t_settle_strict = float(t[last_out+1])
            print(f"  Settling time (±0.1%)   = {t_settle_strict*1000:.0f} ms")
        else:
            print(f"  Settling time (±0.1%)   = not yet within band")

    print(f"  V_int final = {v_int[-1]:.3f} V")
    print(f"  r_fil final = {r_fil[-1]:.3f} Ω")

    # Save trace for plot
    return dict(t=t, T_node=T_node, r_fil=r_fil, v_int=v_int,
                v_osc=v_osc, node_A=node_A, demod_dc=demod_dc)


def startup_hotspot_analysis():
    print("\n=== Dissipation hotspots (cold start, peak transient) ===")
    d, err = run("cold_instrumented", instrument_power=True, T_end=6.0)
    if d is None: print(f"FAIL: {err}"); return
    t = d[:, 0]
    cols = {
        'v_osc': d[:, 1], 'node_A': d[:, 3], 'demod_dc': d[:, 5],
        'v_int': d[:, 7], 'T_node': d[:, 9], 'r_fil': d[:, 11],
        'n_led_a': d[:, 13],
        'i_drv_n': d[:, 15], 'i_out_n': d[:, 17],
        'i_drv_p': d[:, 19], 'i_out_p': d[:, 21],
        'i_chain': d[:, 23],
        'vcc_top': d[:, 25], 'vcc_buf': d[:, 27],
        'vee_top': d[:, 29], 'vee_buf': d[:, 31],
        'q_o_bn': d[:, 33], 'q_o_bp': d[:, 35],
        'n_o_pair_n': d[:, 37], 'n_o_pair_p': d[:, 39],
    }
    # Compute instantaneous power for each output BJT, then find peak over time
    # Use a sliding window to average over one signal cycle (1 ms)
    def smooth_power_envelope(t_arr, p_arr, window=2e-3):
        """Find the peak of a 2 ms moving-average of |p| — captures the worst
        single-cycle dissipation."""
        # Resample to uniform 50 us for moving average
        dt_u = 5e-5
        t_u = np.arange(t_arr[0], t_arr[-1], dt_u)
        p_u = np.interp(t_u, t_arr, p_arr)
        # Moving average over 'window'
        n_win = int(window/dt_u)
        if n_win < 1: n_win = 1
        # Use a simple boxcar via convolve
        kernel = np.ones(n_win) / n_win
        p_avg = np.convolve(np.abs(p_u), kernel, mode='same')
        return t_u, p_avg
    P_inst_out_n = (cols['vcc_buf'] - cols['v_osc']) * cols['i_out_n']
    P_inst_out_p = (cols['v_osc'] - cols['vee_buf']) * cols['i_out_p']
    P_inst_drv_n = (cols['vcc_buf'] - cols['n_o_pair_n']) * cols['i_drv_n']
    P_inst_drv_p = (cols['n_o_pair_p'] - cols['vee_buf']) * cols['i_drv_p']

    for name, P in [("Q_o_out_n (top NPN)", P_inst_out_n),
                     ("Q_o_out_p (bot PNP)", P_inst_out_p),
                     ("Q_o_drv_n (top NPN drv)", P_inst_drv_n),
                     ("Q_o_drv_p (bot PNP drv)", P_inst_drv_p)]:
        t_u, p_avg = smooth_power_envelope(t, P, window=2e-3)
        p_peak = float(np.max(p_avg))
        t_peak = float(t_u[int(np.argmax(p_avg))])
        # Steady state value (last 100 ms)
        smask_ss = t > t[-1] - 0.1
        p_ss = float(np.trapezoid(np.abs(P)[smask_ss], t[smask_ss]) / (t[smask_ss][-1]-t[smask_ss][0]))
        print(f"  {name:30s}: peak {p_peak*1e3:5.0f} mW @ t={t_peak*1000:5.0f} ms,  ss {p_ss*1e3:5.0f} mW,  peak/ss = {p_peak/max(p_ss,1e-9):.2f}x")

    # Also overall peak T during this sim
    print(f"  T_max during this 4s run: {np.max(cols['T_node']):.1f} K")


def hotspot_analysis():
    print("\n=== Dissipation hotspots (steady state) ===")
    d, err = run("instrumented", instrument_power=True, T_end=6.0)
    if d is None: print(f"FAIL: {err}"); return
    t = d[:, 0]
    # Columns (pairs of t, value):
    # 0: t, 1: v_osc_drive, 3: node_A, 5: n_demod_dc, 7: v_int, 9: T_node,
    # 11: r_fil, 13: n_led_a, 15: i_drv_n, 17: i_out_n, 19: i_drv_p, 21: i_out_p,
    # 23: i_chain, 25: vcc_top, 27: vcc_buf, 29: vee_top, 31: vee_buf,
    # 33: q_o_bn, 35: q_o_bp, 37: n_o_pair_n, 39: n_o_pair_p
    cols = {
        'v_osc': d[:, 1], 'node_A': d[:, 3], 'demod_dc': d[:, 5],
        'v_int': d[:, 7], 'T_node': d[:, 9], 'r_fil': d[:, 11],
        'n_led_a': d[:, 13],
        'i_drv_n': d[:, 15], 'i_out_n': d[:, 17],
        'i_drv_p': d[:, 19], 'i_out_p': d[:, 21],
        'i_chain': d[:, 23],
        'vcc_top': d[:, 25], 'vcc_buf': d[:, 27],
        'vee_top': d[:, 29], 'vee_buf': d[:, 31],
        'q_o_bn': d[:, 33], 'q_o_bp': d[:, 35],
        'n_o_pair_n': d[:, 37], 'n_o_pair_p': d[:, 39],
    }
    # Steady-state window: last 100 ms
    smask = t > t[-1] - 0.1
    ts = t[smask]
    def tavg(x): return float(np.trapezoid(x, ts)/(ts[-1]-ts[0]))
    # Total supply input (= rail current × supply V, sign-corrected)
    i_vcc_rail = abs(tavg(cols['vcc_top'][smask] - cols['vcc_buf'][smask]) / 0.1)
    i_vee_rail = abs(tavg(cols['vee_buf'][smask] - cols['vee_top'][smask]) / 0.1)
    P_sup_vcc = i_vcc_rail * 10.0
    P_sup_vee = i_vee_rail * 10.0
    print(f"  Rail current: |I_vcc| = {i_vcc_rail*1e3:.1f} mA, |I_vee| = {i_vee_rail*1e3:.1f} mA")
    print(f"  Supply power: P_vcc = {P_sup_vcc*1e3:.0f} mW, P_vee = {P_sup_vee*1e3:.0f} mW, total = {(P_sup_vcc+P_sup_vee)*1e3:.0f} mW")
    # Filament power
    v_fil_inst = cols['v_osc'][smask] - cols['node_A'][smask]
    P_fil = float(np.trapezoid(v_fil_inst**2, ts)/(ts[-1]-ts[0])) / 25.0
    print(f"  P_filament: {P_fil*1e3:.0f} mW")
    P_sense = float(np.trapezoid((cols['node_A'][smask])**2, ts)/(ts[-1]-ts[0])) / R_SENSE
    # That's V(node_A)²/R_sense, but R_sense connects node_A to v_ap≈0
    print(f"  P_R_sense:  {P_sense*1e3:.0f} mW")
    # Bias chain power: V drop × I_chain
    P_chain = float(tavg(cols['vcc_buf'][smask] - cols['vee_buf'][smask]) * tavg(cols['i_chain'][smask]))
    print(f"  P_chain (top half ≈ same for bottom): {P_chain*1e3:.0f} mW")

    # Per-BJT dissipation: V_CE × I_C, instantaneous, then averaged
    # Top NPN driver Q_o_drv_n: collector at vcc_buf, emitter at n_o_pair_n
    P_drv_n = float(np.trapezoid(
        (cols['vcc_buf'][smask] - cols['n_o_pair_n'][smask]) * cols['i_drv_n'][smask],
        ts) / (ts[-1]-ts[0]))
    # Top NPN output Q_o_out_n: C=vcc_buf, E=v_osc_drive
    P_out_n = float(np.trapezoid(
        (cols['vcc_buf'][smask] - cols['v_osc'][smask]) * cols['i_out_n'][smask],
        ts) / (ts[-1]-ts[0]))
    # Bottom PNP driver Q_o_drv_p: C=vee_buf, E=n_o_pair_p
    P_drv_p = float(np.trapezoid(
        (cols['n_o_pair_p'][smask] - cols['vee_buf'][smask]) * cols['i_drv_p'][smask],
        ts) / (ts[-1]-ts[0]))
    # Bottom PNP output Q_o_out_p: C=vee_buf, E=v_osc_drive
    P_out_p = float(np.trapezoid(
        (cols['v_osc'][smask] - cols['vee_buf'][smask]) * cols['i_out_p'][smask],
        ts) / (ts[-1]-ts[0]))
    print(f"  P_BJT[Q_o_drv_n (top NPN driver)]:   {abs(P_drv_n)*1e3:6.1f} mW")
    print(f"  P_BJT[Q_o_out_n (top NPN output)]:   {abs(P_out_n)*1e3:6.1f} mW")
    print(f"  P_BJT[Q_o_drv_p (bot PNP driver)]:   {abs(P_drv_p)*1e3:6.1f} mW")
    print(f"  P_BJT[Q_o_out_p (bot PNP output)]:   {abs(P_out_p)*1e3:6.1f} mW")
    P_BJT_total = abs(P_drv_n) + abs(P_out_n) + abs(P_drv_p) + abs(P_out_p)
    print(f"  P_BJT (4 total):                     {P_BJT_total*1e3:6.1f} mW")

    P_rsense = i_vcc_rail**2 * 0.1 + i_vee_rail**2 * 0.1
    print(f"  P_R_sense_supply (instr. resistors): {P_rsense*1e3:6.3f} mW")
    return cols, ts


def main():
    cold = cold_start_analysis()
    startup_hotspot_analysis()
    hotspot_analysis()


if __name__ == "__main__":
    main()
