"""Closed-loop VFD-filament regulator: Wien bridge + JFET all-pass + AC bridge
with thermal filament model + synchronous demodulator + integrator,
all running on TLV9154-class op-amps and +/-9 V supplies.

Variable resistance element: a single n-channel JFET (one die of an LS844
monolithic dual). The other die is wired as a SELF-BIASED REFERENCE
producing V_source_ref ≈ -V_p/2 (positive voltage). XU_sum is configured
as a unity-gain subtractor: V_ctl = V_int_out - V_source_ref, so V_GS at
V_int_out=0 is -V_source_ref ≈ V_p/2 — safely negative, well clear of
the gate-channel diode, and AUTO-TRACKING the V_p of the matched pair on
the same die (LS844 within-package match: ΔV_GS ≤ 5 mV).

Why JFET, not MOSFET back-to-back: MOSFETs have an intrinsic body diode
that clamps n_ap_plus to -V_F on the negative half-cycle when R_DS_OP is
in the 80-100 Ω range (which forces sub-threshold operation). The
resulting half-wave rectification killed harmonic purity (V2 up to 175 %
of V1 on ILC1-1/7). JFETs have no body diode → channel handles both
polarities cleanly → harmonics return to the 6-12 % range (or 3 % with
bootstrap re-added).

Why monolithic matched pair, not two singles: across the LS844 V_p spec
(1.0-3.5 V), the V_GS required for R_DS=333 Ω varies by ~1 V. A single
J_var with fixed V_offset would either forward-bias the gate on low-V_p
parts or stall the loop on high-V_p parts. The self-biased Q_ref on the
SAME die has the same V_p as J_var (matched to ±5 mV), so V_offset_ref
tracks V_p automatically — V_int_OP stays roughly constant across the
spec range. Same idea as the diode-degenerated MOSFET ref we previously
used, just adapted to JFET self-biasing.

Earlier architecture history:
- DMN3404L back-to-back NMOS + diode-degenerated NMOS ref + non-inverting
  summer (2026-05-20, commit ae5b517). Body-diode rectification gave H2
  16-175 % — failed the "harmonic purity" design goal.
- DMP3098L back-to-back PMOS + inverter (2026-05-19, commit 431d469).
  +121 K cold-start overshoot on ILC1-1/7 due to V_GS=0 → R_DS=∞ at cold
  start.
- Single J201 JFET + inverter (commit e5017a4 and earlier). Wrong-polarity
  bistability via gate forward conduction with fixed V_offset.

Cold-start transient: V_int_out=0, V_GS=V_offset_ref=-V_source_ref ≈
V_p/2 (matched), R_DS ≈ 4·R_DS_on/3 (modest overdrive), |1-H| modest,
bridge drive moderate. Inverting integrator winds V_int_out negative as
the bridge senses high R_fil, V_GS drops further toward V_p (R_DS grows),
drive grows, filament heats. At balance, V_int_OP varies with V_p (more
negative for higher-|V_p| parts) but stays within the integrator clamps
because the tracking ref keeps V_GS-V_p in a bounded range.
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

# Per-tube design table: filament + bridge resistors at the recommended
# 10x scaleup of the reference arm. Bridge balance:
#   R_target = R_sen * R_top_ref / R_bot_ref, with a deliberate 1% offset.
def _make_tube(name, R_op, V_op, T_op, R_sen, R_bot_ref,
               r_int_scale=0.3, booster=False,
               wien_alpha=None, c_ap=None, buf_fb1=None, buf_fb_ap=None,
               v_buf=None, ce_buf=False, mos_buf=False,
               tank_l=None, tank_c=None, bias_diode="Dbias",
               xfmr_n=None, xfmr_lpri=None, bias_zener_v=None,
               buf_comp_pf=None, t_rail_ramp=None,
               servo_bias=False, servo_iq_target=10e-3,
               servo_r_sense=0.5):
    # Bridge target R = R_op * R_bot_ref / R_sen, set to give R_filament = R_op
    # at the operating temperature T_op. (An earlier version had a 1% offset
    # for "cold-start kick", but that's unnecessary -- the filament starts at
    # R_amb which is far below R_target, so V_diff is large at cold-start
    # regardless. Soft-start preloads the integrator anyway.)
    R_top_ref = R_op * R_bot_ref / R_sen
    P_op = V_op * V_op / R_op
    R_amb = R_op / (T_op / T_AMB) ** 1.2
    sigma_eps_A = P_op / (T_op ** 4 - T_AMB ** 4)
    c_th = TAU_TH * 4 * sigma_eps_A * T_op ** 3
    return dict(name=name, R_op=R_op, V_op=V_op, T_op=T_op, P_op=P_op,
                r_amb=R_amb, sigma_eps_A=sigma_eps_A, c_th=c_th,
                r_top_ref=R_top_ref, r_bot_ref=R_bot_ref, r_sense=R_sen,
                r_int_scale=r_int_scale, booster=booster,
                wien_alpha=wien_alpha, c_ap=c_ap,
                buf_fb1=buf_fb1, buf_fb_ap=buf_fb_ap, v_buf=v_buf,
                ce_buf=ce_buf, mos_buf=mos_buf,
                tank_l=tank_l, tank_c=tank_c,
                bias_diode=bias_diode,
                xfmr_n=xfmr_n, xfmr_lpri=xfmr_lpri,
                bias_zener_v=bias_zener_v,
                buf_comp_pf=buf_comp_pf,
                t_rail_ramp=t_rail_ramp,
                servo_bias=servo_bias,
                servo_iq_target=servo_iq_target,
                servo_r_sense=servo_r_sense)

# r_int_scale per tube: option-A's 0.3 was tuned for the IV-18 bridge gain.
# Bridge sensitivity ~ V_drive*R_sen/(R_op+R_sen)^2 changes per tube, so
# R_INT must scale inversely with sensitivity to keep loop gain ~constant.
# Numbers below are derived from sensitivity ratios vs IV-18:
#   IV-18: 1.1 mV/Ω  ->  scale 0.30
#   IV-6: 10.6 mV/Ω  ->  scale 0.30 × 9.5 = 2.85
#   ILC1-1/7: 7.3    ->  scale 0.30 × 6.6 = 1.98
#   ILC1-1/8: 26.4   ->  scale 0.30 × 24  = 7.20
TUBES = {
    # IV-18 unified onto the booster+mos_buf topology used by IV-6 / ILC1-1/8.
    # K_buf = 2.6 (buf_fb1 = 1.6k) sizes the buffer for V_d_pk = 1.555 V_pk
    # at OP with x_OP ~ 0.7 (just below peak sensitivity).
    # IV-18 (this slot was previously labelled "IV-3" but the real IV-3 has
    # the same nominal R_op/V_op as IV-6; our parameters here are closer to
    # IV-18, so renamed 2026-05-20. Resistances unchanged for continuity --
    # to be re-tuned to true IV-18 spec after settling-speed tuning lands.)
    "iv18":    _make_tube("IV-18",    R_op=100, V_op=1.0, T_op=800, R_sen=10, R_bot_ref=100,  r_int_scale=0.5, booster=True, buf_fb1=1.6e3, buf_fb_ap=1.6e3, v_buf=1.4, ce_buf=True, mos_buf=True),
    # Per-tube buf_fb1 sets buffer gain via R_fb1:R_fb2(=1k):
    #   buf_fb1 = 6.2k -> k_buf = 7.2 (matches k_atten=7.15, unity overall gain)
    #   buf_fb1 = 9.1k -> k_buf = 10.1 (1.41x net gain, for ILC1-1/7)
    # Smaller tubes don't need the extra drive and would limit-cycle if given
    # too much. ILC1-1/7's 5 V_RMS filament drive demands the higher k_buf.
    # k_buf values: with the inverting-Buffer-2 topology and JFET in the
    # linear region (|1+H| ~ 1.5-1.7 at op), V_top_pk = V_drive_diff_pk/|1+H|.
    # k_buf = V_top_pk / V_drv_atten_pk (V_drv_atten_pk ~ 0.5 V from the
    # passive divider).
    #   IV-6:     V_drive_diff_pk = 1.75 V -> V_top_pk = 1.0 V -> k_buf = 2.2
    #   ILC1-1/8: V_drive_diff_pk = 2.13 V -> V_top_pk = 1.3 V -> k_buf = 2.7
    #   ILC1-1/7: V_drive_diff_pk = 8.5 V  -> V_top_pk = 5.0 V -> k_buf = 10
    # Buffer 1 non-inverting (gain = 1 + buf_fb1/1k); buf_fb1 = (k_buf-1)*1k.
    # Buffer 2 inverting (gain = -buf_fb_ap/1k); buf_fb_ap = k_buf*1k.
    # v_buf set just above V_top_pk for ~50-60% class-AB efficiency.
    # Non-inverting Buffer 1 + Buffer 2: V_diff = V_drv_atten*k_buf*(1 - H).
    # Same k_buf in both buffers (buf_fb1 = buf_fb_ap) so V_top and V_bot
    # have matched magnitude. v_buf sized for V_top_pk = k_buf*V_drv_atten_pk
    # plus ~1 V headroom (bootstrap caps on the bias chain let v_buf shrink
    # toward V_top_pk for class-AB efficiency near pi/4).
    # k_buf chosen so the loop settles in the favourable all-pass operating
    # region (|1-H| ~= 1.4 at op, R_DS ~= 1.6 kohm). Lower k_buf forces the
    # loop to settle at higher R_DS to deliver the required V_diff -- pushes
    # the JFET closer to pinch-off where (1-H) is larger and V_top swing is
    # only fractionally bigger than V_diff (efficient class-AB).
    #
    # Per-tube buffer-output topology:
    #   IV-6, ILC1-1/8: MOSFET common-source push-pull (ce_buf+mos_buf),
    #     using DMP3098L+DMN3404L. The low rails (v_buf ~ 1.2-1.4 V, just
    #     above V_pk) put the MOSFETs near triode at peaks, so dissipation
    #     is dominated by I^2*R_DS_on rather than V_DS*I_D linear-region
    #     loss. Forward-diode bias chain works because v_buf ~ V_F + V_GS_th.
    #   ILC1-1/7: BJT common-collector emitter follower (default), using
    #     BC868/BC868PA (SOT-89). Considered the MOSFET path several ways
    #     (CS with Zener bias + comp cap; CC with diode bias; CC with
    #     LM358 servo bias) but none beat BJT CC for this load. Reasons
    #     summarised at the bottom of this comment.
    #
    # Why BJT CC + SOT-89 wins for ILC1-1/7 (V_op=5 V_RMS / 30 ohm = 1 W out):
    #   - BJT V_BE ~ 0.65 V +/- 50 mV across BC868 production: tight
    #     enough that the fixed silicon-diode bias chain gives consistent
    #     class-AB across parts. Trim-free by construction (CLAUDE.md
    #     hard requirement).
    #   - MOSFET V_GS_th = 0.5-1.5 V (3x spread): fixed bias chain can't
    #     handle the variation; needs trimming or a servo to compensate.
    #   - MOSFET CS at any rail oscillates (high-Q resonance at 3-7 MHz
    #     when conducting); compensation costs bandwidth or BOM.
    #   - MOSFET CC with diode bias works but ss_avg ~ 500 mW per FET
    #     (78% of SOT-23 derated rating); BJT CC at SOT-89 gets the same
    #     work done at 100 mW (13% of derated rating) -- 5x more margin.
    #   - LM358 servo bias closes the V_th-variation problem at the cost
    #     of 1 op-amp + 2 sense Rs + filter per buffer arm; works in
    #     simulation but offers ~10% dissipation reduction vs diode bias
    #     at the same rail. Doesn't justify the BOM and complexity.
    #
    # The MOSFET options remain in make_netlist() (set ce_buf, mos_buf,
    # bias_zener_v, buf_comp_pf, servo_bias on a tube spec to enable) for
    # any future tube whose load characteristics tip the trade-off the
    # other way -- e.g., a higher-current tube where I^2*R_DS_on advantage
    # of MOSFETs becomes significant.
    # Per-tube r_int_scale tuned empirically with J112 + 1uF + V_clamp_hi=+6V:
    #   IV-6 / ILC1-1/8: scale=0.7 -- moderate slowdown to kill the cold-start
    #     overshoot at V_p typ
    #   ILC1-1/7: scale=1.5 -- larger slowdown to compensate for the higher
    #     loop gain through its K_buf=14 buffer
    "iv6":     _make_tube("IV-6",     R_op= 20, V_op=1.0, T_op=800, R_sen= 5, R_bot_ref=500,  r_int_scale=0.7, booster=True, buf_fb1=2.0e3, buf_fb_ap=2.0e3, v_buf=1.2, ce_buf=True, mos_buf=True),
    # ILC1-1/7 K_buf raised from 10.1 to 14 (buf_fb1: 9.1k -> 13k E24).
    # The old 10.1 put V_d_max = 8.47 V_pk vs V_d_required = 8.485 V_pk --
    # zero headroom, loop pinned at the asymptote of (1-H_ap), couldn't
    # throttle drive when T crossed T_op -> persistent +15 K overshoot
    # regardless of JFET / C_AP / r_int_scale. New K_buf=14 gives V_d_max
    # = 11.76 V_pk (39% headroom over required), letting the loop operate
    # comfortably below the asymptote with real V_d-vs-x sensitivity.
    # v_buf raised 4.3 -> 6.5 V to cover the larger V_top_pk swing.
    "ilc11_7": _make_tube("ILC1-1/7", R_op= 25, V_op=5.0, T_op=800, R_sen= 5, R_bot_ref=1000, r_int_scale=1.5, booster=True, buf_fb1=13e3, buf_fb_ap=13e3, v_buf=6.5),
    "ilc11_8": _make_tube("ILC1-1/8", R_op=  8, V_op=1.2, T_op=800, R_sen= 2, R_bot_ref=200,  r_int_scale=0.7, booster=True, buf_fb1=2.5e3, buf_fb_ap=2.5e3, v_buf=1.4, ce_buf=True, mos_buf=True),
}
# Higher-current tubes (IV-6, ILC1-1/7, ILC1-1/8) enable the buffer stage:
# two non-inverting unity-gain op-amp + class-AB BC337/BC327 BJT pair buffers
# inserted between v_osc / v_ap (Wien and all-pass internal nodes) and
# v_osc_drive / v_ap_drive (the bridge filament/reference arm inputs).
# Wien and all-pass loops are unloaded, BJT distortion is rejected by the
# buffer op-amp's open-loop gain.
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
# C_AP = 470 nF for the single-JFET LS844 architecture. R_DS_OP must be
# ≥ 333 Ω across the LS844 V_p spec (1.0-3.5 V) to keep V_GS_OP < 0 on
# every part — at f0=1 kHz that requires C_AP ≈ 1/(2π·1k·333) = 478 nF.
# Through-hole PP film (e.g. WIMA MKS2 470n/63V, 9x7 mm, ~$0.45) or 0.47µF
# MLCC X7R for SMT builds.
C_AP = 470e-9

# Loop integrator (~5 Hz integrator zero frequency at default scale)
# These are baselines; sweep_a scales R_INT and R_PID together (Kp constant)
# to vary loop bandwidth while keeping the same PID shape.
R_INT_BASE = 100e3
C_INT_BASE = 1.0 / (2 * np.pi * 5.0 * R_INT_BASE)
R_PID_BASE = 1e6
C_PID_BASE = 1e-9
C_HF_BASE  = 1e-9    # HF rolloff cap in parallel with R_PID. Sets the HF
                     # pole at 1/(2π·R_PID·C_HF). The original code had this
                     # at 1.6 n; it was bumped to 10 n to improve 1 kHz
                     # ripple suppression, but the bump put the pole at
                     # ~10 Hz on ILC1-1/7 (r_int_scale=1.5 ⇒ R_PID=1.5 MΩ)
                     # — right in the loop's working bandwidth, eating PM
                     # and causing a 12-24 Hz cold-start ring (T_peak +7.7K).
                     # 1 nF puts the HF pole at 106 Hz on ILC1-1/7 and
                     # 220-320 Hz on the 1 V tubes; ripple suppression at
                     # 1 kHz drops from ~40 dB to ~20 dB which is still fine
                     # given the integrator's natural attenuation.
                     # (gives 25 dB attenuation at 1 kHz to suppress demod
                     # feedthrough that limit-cycles the boosted-tube loops)
# Module-level "current" values (used in make_netlist when not overridden)
R_INT = R_INT_BASE
C_INT = C_INT_BASE
R_PID = R_PID_BASE
C_PID = C_PID_BASE
C_HF  = C_HF_BASE

T_END = 5.000

# TLV9154 input offset voltage: typ +/-0.5 mV, max +/-2.5 mV (datasheet).
# Higher-voltage successor to TLV9104: 4.5 - 40 V supply range, 4.5 MHz GBW
# vs TLV9104's 1.8 - 5.5 V / 1 MHz. Lets us run the regulator from +/-9 V
# rails so the bridge has comfortable swing headroom for the larger tubes.
OPAMP = ("uopamp_lvl3 Avol=10meg GBW=4.5meg Rin=100g Rout=10 "
         "Iq=600u Ilimit=65m Vrail=100m Vmax=40 Vos=2.5m")
# Supply rails (volts). +/-9 V is comfortable for TLV9154 (range 4.5..40 V
# supply) and gives the buffer class-AB output ~+/-8.4 V swing capability.
VCC = 9.0
VEE = -9.0

# Soft-start: at power-on, hold V_int_out at V_PRESET via a switch that
# opens after T_RAMP. Mimics a real RC + Zener + analog-switch POR network.
# V_PRESET = 0 disables soft-start (the loop integrates from zero).
V_PRESET = 0.0
T_RAMP   = 0.0


def make_netlist(data_path: Path,
                 v_preset: float = None,
                 t_ramp: float = None,
                 r_int_scale: float = 1.0,
                 p_boost: float = 0.0,
                 t_boost: float = 0.0,
                 mc: dict = None) -> str:
    """Generate the closed-loop netlist.
    r_int_scale: scales R_INT and R_PID together (1/scale = bandwidth scale).
    p_boost: extra power [W] injected into thermal node for pre-heat (option D).
    t_boost: duration of the pre-heat boost [s].
    mc: optional dict of multiplicative tolerance factors (defaults to 1.0)
        for Monte Carlo sweep over manufacturing variation.
        Recognised keys (each defaults to 1.0 unless noted):
          k_r1_wien, k_r2_wien, k_c1_wien, k_c2_wien,
          k_r_top_ref, k_r_bot_ref, k_r_sense,
          k_r_amb (filament cold resistance),
          k_r_a1, k_r_a2, k_r_b1, k_r_b2 (diff amp matching),
          k_c_ap, k_c_intin, k_c_hf, k_c_intfb (electrolytic, asym tol),
          k_r_intin, k_r_intfb,
          vos_v (absolute Vos in V, default 1.5e-3),
          jfet_vp (absolute, default -2.5; 2N5457 typ),
          jfet_beta (absolute, default 1.0e-3).
    """
    if v_preset is None: v_preset = V_PRESET
    if t_ramp   is None: t_ramp   = T_RAMP
    if mc is None: mc = {}
    g = lambda k, default=1.0: mc.get(k, default)
    r_int = R_INT_BASE * r_int_scale * g("k_r_intin")
    r_pid = R_PID_BASE * r_int_scale * g("k_r_intfb")
    c_int = C_INT_BASE * g("k_c_intfb")
    c_pid = C_PID_BASE * g("k_c_intin")
    c_hf  = C_HF_BASE  * g("k_c_hf")
    r1_wien = 10e3   * g("k_r1_wien")
    r2_wien = 10e3   * g("k_r2_wien")
    c1_wien = 15.915e-9 * g("k_c1_wien")
    c2_wien = 15.915e-9 * g("k_c2_wien")
    r_top_ref = mc.get("r_top_ref", R_OP * 0.99 * g("k_r_top_ref"))
    r_bot_ref = mc.get("r_bot_ref", R_SENSE * g("k_r_bot_ref"))
    r_sense_v = mc.get("r_sense",   R_SENSE * g("k_r_sense"))
    r_amb_eff = mc.get("r_amb",     R_AMB * g("k_r_amb"))
    sigma_eps_A_eff = mc.get("sigma_eps_A", SIGMA_EPS_A * g("k_sigma_eps_A"))
    c_th_eff  = mc.get("c_th",      C_TH * g("k_c_th"))
    fil_exp = mc.get("fil_exp", 1.2)
    # Diff-amp resistor network: bumped 10k -> 1Meg to eliminate asymmetric
    # loading of node_A vs node_B. Filament arm Thevenin is ~25 ohm; reference
    # arm Thevenin is 400-833 ohm depending on tube. With 10k diff-amp R, the
    # ~3-5% loading shift on node_B vs <0.5% on node_A drives the loop to
    # settle at a non-bridge-balance operating point (off-target T).
    # 1 Meg makes loading <0.1% on both sides; Johnson noise still <5 uV/sqrtHz
    # bandwidth, op-amp input bias current at 10 pA gives <10 uV offset.
    r_a1 = 1e6 * g("k_r_a1"); r_a2 = 1e6 * g("k_r_a2")
    r_b1 = 1e6 * g("k_r_b1"); r_b2 = 1e6 * g("k_r_b2")
    c_ap_v = mc.get("c_ap", C_AP * g("k_c_ap"))
    # HF steady-state mode: f0 bumped to 100 kHz, Wien C and C_AP scaled
    # accordingly, filament replaced with a fixed R_op resistor (no thermal
    # dynamics), and v_int_out forced to the per-tube settled value (so the
    # JFET sits at its OP without the integrator transient). Used to measure
    # AC power dissipation at high carrier frequency without paying for the
    # 100x slower simulation that would happen if we tracked thermal warmup.
    hf_mode = mc.get("hf_mode", False)
    if hf_mode:
        c1_wien *= 0.01
        c2_wien *= 0.01
        c_ap_v *= 0.01
    # Wien BJT amplitude clamp: alpha sets the V_osc clamp threshold (lower
    # alpha -> higher peak amplitude). Default 0.5 keeps clamp at ~3 V_pk on
    # +/-5 V rails.
    wien_alpha_eff = mc.get("wien_alpha") or ALPHA
    rtop_bjt = (1 - wien_alpha_eff) * R_TOT_BJT
    rbot_bjt = wien_alpha_eff * R_TOT_BJT
    vos_v   = mc.get("vos_v", 2.5e-3)  # TLV9154 worst-case Vos
    # Chopper-stabilised Vos for the demodulator and integrator op-amps
    # (e.g. OPA2188 dual chopper: Vos < 5 uV). The Vos sensitivity sweep
    # (PR #16) showed these two op-amps dominate the loop's Vos error
    # budget; with TLV9154-grade 2.5 mV Vos here the residual T error
    # is ~30 K, vs ~5 K with chopper.
    vos_chopper = mc.get("vos_chopper", 5e-6)
    # Legacy JFET parameter shims (kept so old Monte-Carlo / validation
    # scripts that still set jfet_vp / jfet_beta don't break). With the
    # NMOS variable-R + level-shift architecture these have no effect on
    # the netlist; DMN3404L V_GS(th) is fixed by the manufacturer model.
    jfet_vp = mc.get("jfet_vp", -3.0)
    jfet_beta = mc.get("jfet_beta", 3.3e-3)
    # Per-tube buffer rail, defaults to VCC for backward compatibility.
    v_buf = mc.get("v_buf", VCC)
    # Anti-windup clamps. With the NMOS variable-R + level-shift
    # architecture, V_int_out_OP is slightly negative (~-0.4 V for ILC1-1/7).
    # Both clamps are needed because the loop has Kp = R_PID/R_INT = 10:
    # cold-start demod (~0.5 V) drives V_int_out proportionally to -5 V
    # instantly, plus integrated wind on top, which would saturate the
    # integrator at the negative supply rail (~-4.9 V) without a clamp.
    # The 100+ ms recovery from such deep saturation was the residual
    # 68 K overshoot on ILC1-1/7 with NMOS+level-shift and no lower clamp.
    # Set V_clamp_lo = -0.7 V (Schottky V_F = 0.3 V at saturation current
    # gives V_int_out floor ≈ -1.0 V, ~3x V_int_out_OP magnitude); back-calc
    # anti-windup unwinds quickly when the lower diode engages.
    # The upper clamp at +6 V is wind-up safety against transients; it
    # almost never engages because the loop's natural OP is negative.
    v_clamp_hi = mc.get("v_clamp_hi", 6.0)
    # V_clamp_lo widened from -0.7V to -2.5V for the JFET arch. The JFET's
    # V_p variation (LS844 spec: 1.0-3.5 V) maps to a V_int_OP shift of up
    # to ~1.5 V across parts; the lower clamp must accommodate this so the
    # loop never saturates on a high-|V_p| sample. Cold-start anti-windup
    # still works — the back-calc unwinds the integrator the moment the
    # clamp engages.
    v_clamp_lo = mc.get("v_clamp_lo", -2.5)
    # ====== Variable-R: JFET self-biased reference parameters ======
    # The self-biased Q_ref produces V_source_ref via I_ref · R_src_ref.
    # XU_sum is wired as a subtractor: V_ctl = V_int_out - V_source_ref,
    # so V_GS_var at V_int_out=0 = -V_source_ref.
    #
    # We want V_source_ref SMALL (~0.05-0.2 V) so that:
    #   (a) cold-start V_GS_var ≈ 0 → R_DS at the on-resistance minimum →
    #       low all-pass τ → small |1-H| → LOW cold-start bridge drive,
    #   (b) V_int_OP < 0 at OP, so the integrator winds DOWN (negative)
    #       during cold-start heating — correct loop polarity, no
    #       wind-the-wrong-way thermal overshoot.
    # For LS844 with V_p=-2 V, I_DSS=5 mA, R_src_ref=100 Ω gives
    # V_source_ref ≈ 0.34 V. Smaller values force the JFET into triode
    # and V_source_ref → 0 as R_src_ref → 0. Tuning is empirical.
    #
    # Across V_p variation the self-bias still produces a V_source_ref
    # roughly proportional to |V_p| · √(I_DSS·R_src), so the loop's
    # operating point shifts gracefully without saturating the integrator
    # clamps.
    r_d_ref_kohm   = mc.get("r_d_ref_kohm", 10.0)
    r_src_ref_ohm  = mc.get("r_src_ref_ohm", 100.0)
    # LS844 SPICE-model parameters. Default to mid-of-spec V_p, derived
    # I_DSS giving a typical β. mc overrides let us sweep across the
    # 1.0-3.5 V V_p spec range and across I_DSS variation.
    jfet_vp        = mc.get("jfet_vp", -2.0)
    jfet_idss      = mc.get("jfet_idss", 5e-3)
    jfet_beta      = mc.get("jfet_beta", jfet_idss / jfet_vp**2)
    jfet_lambda    = mc.get("jfet_lambda", 0.0)
    # force_v_offset_v: optional override that replaces the self-biased
    # reference with a fixed voltage source. Used for diagnostic sweeps
    # (e.g. V_p-mismatch tolerance studies).
    force_v_offset_v = mc.get("force_v_offset_v", None)
    def _opamp(key, default=None, ilimit="65m"):
        # uopamp_lvl3 fixes two bugs in lvl2: (1) V9/V10 offsets in lvl2 used
        # {Ilimit-545m} which goes negative for Ilimit < 545 mA, breaking the
        # clamp (see uopamp.lib CAVEAT); (2) lvl2's offset is not scaled by
        # Rout, so the actual current limit was Ilimit/Rout instead of Ilimit.
        # lvl3 uses {Ilimit*Rout - 5m} with a low-V_F clip diode (Is=1u).
        # Realistic Isc from datasheets (default per op-amp type):
        #   TLV9154 (standard quad):  ~65 mA typ at 25 C  -> ilimit="65m"
        #   OPA2188 (chopper dual):   ~50 mA typ at 25 C  -> ilimit="50m"
        v = mc.get(key, default if default is not None else vos_v)
        return (f"uopamp_lvl3 Avol=10meg GBW=4.5meg Rin=100g Rout=10 "
                f"Iq=600u Ilimit={ilimit} Vrail=100m Vmax=40 Vos={v:.6e}")
    opamp = _opamp("vos_v")          # back-compat default for any unmarked usage
    opamp_osc  = _opamp("vos_osc")
    opamp_ap   = _opamp("vos_ap")
    opamp_diff = _opamp("vos_diff")
    # Chopper-stabilised op-amps (OPA2188-class), Isc ~50 mA
    opamp_dem  = _opamp("vos_dem", default=vos_chopper, ilimit="50m")
    opamp_int  = _opamp("vos_int", default=vos_chopper, ilimit="50m")
    opamp_aw   = _opamp("vos_aw",  default=vos_chopper, ilimit="50m")
    opamp_cmp  = _opamp("vos_cmp")
    opamp_buf0 = _opamp("vos_buf0")
    opamp_bufo = _opamp("vos_buf_osc")
    opamp_bufa = _opamp("vos_buf_ap")
    # XU_sum (gate-drive level-shifter in the V_TO-tracking arch). Vos
    # here translates 2:1 to V_ctl (non-inverting summer gain of 2) and
    # then into V_GS_var DC. The loop compensates by shifting V_int_OP
    # so the bridge null still holds, so this Vos doesn't directly affect
    # T_op — but a large enough Vos could push V_int_OP into the clamp.
    opamp_sum  = _opamp("vos_sum")
    # Output stages: when use_booster=True, the textbook JFET-VCR architecture is:
    #   Buffer 0  attenuates V_osc to keep JFET in linear region (V_DS << V_GS-Vto).
    #             Passive divider on V_osc gives v_atten_input (high-Z), op-amp
    #             follower presents v_drv_atten (low-Z) so the JFET's asymmetric
    #             current draw doesn't distort the attenuated signal.
    #   All-pass  operates entirely on v_drv_atten (small, linear JFET).
    #   Buffer 1  amplifies v_drv_atten by k_buf, drives v_osc_drive at bridge.
    #   Buffer 2  amplifies v_ap     by k_buf, drives v_ap_drive  at bridge.
    # Net signal gain through the booster chain = k_buf / k_atten.
    # All buffers have op-amp + class-AB BC337/BC327 BJT pair on the output
    # except Buffer 0 (low current to JFET, op-amp output suffices).
    use_booster = mc.get("booster", False)
    v_osc_drive = "v_osc_drive" if use_booster else "v_osc"
    v_ap_drive  = "v_ap_drive"  if use_booster else "v_ap"
    # Optional step-down transformer between buffer outputs and bridge:
    # buffer drives v_osc_drive/v_ap_drive (primary), transformer reflects
    # to v_osc_load/v_ap_load (secondary), bridge sees the secondary. Lets
    # the BJT pair operate at higher V/lower I (better V_pk/V_supply ratio,
    # smaller I_C peak) for class-C efficiency. Only meaningful in hf_mode
    # because at f0=1 kHz the primary X_L is too low to look like a load.
    xfmr_n = mc.get("xfmr_n")  # turns ratio Np:Ns step-down (e.g., 4)
    xfmr_lpri = mc.get("xfmr_lpri", 5e-3)  # primary magnetizing inductance
    use_xfmr = (xfmr_n is not None) and mc.get("hf_mode", False)
    if use_xfmr:
        bridge_v_top = "v_osc_load"
        bridge_v_bot = "v_ap_load"
    else:
        bridge_v_top = v_osc_drive
        bridge_v_bot = v_ap_drive
    # HF steady-state mode: fixed R_op filament (no thermal time constant)
    # so a short sim suffices. T_node and r_fil are still defined (for
    # downstream wrdata/metrics compatibility) via fixed sources.
    if hf_mode:
        R_op_value = mc.get("R_op", 25)
        T_op_value = mc.get("T_op", 800)
        filament_line = (f"R_fil_fixed {bridge_v_top} node_A {R_op_value:.6g}\n"
                         f"V_T_fake T_node 0 {T_op_value:.6g}\n"
                         f"B_R_fake r_fil 0 V = {R_op_value:.6g}")
    else:
        filament_line = f"X_filament {bridge_v_top} node_A T_node r_fil filament"
    # Integrator-cap initial condition for HF mode: with R_fil pinned at
    # R_op, the bridge is always balanced -> no demod error -> integrator
    # has no driving signal and stays at IC=0. We pre-load the cap so the
    # loop starts at its known OP. The op-amp's output equals the
    # difference V(n_int_pidp) - V(n_int_minus) ~ -v_int_out at DC, so
    # IC on C_intfb (n_int_minus -> n_int_pidp) = -v_int_settled.
    v_int_settled = mc.get("v_int_settled", 2.0)
    c_intfb_ic_v = -v_int_settled if hf_mode else 0.0
    # Comparator: natural sign(V_osc) for both booster and non-booster paths
    # (Buffer 2 is non-inverting, so V_bot tracks V_ap with the same sign as
    # V_osc; the demod's reference must be in-phase with V_osc).
    cmp_inputs = "0 v_osc" if mc.get("ce_buf") else "v_osc 0"
    # When booster is on, the all-pass JFET drain (and R_ap1) tap into
    # v_drv_atten (low-Z attenuated signal). Otherwise they tap into v_osc.
    v_osc_jfet  = "v_drv_atten" if use_booster else "v_osc"
    # Per-tube buffer gain via R_buf_fb1 (feedback resistor); R_buf_fb2 = 1k.
    # k_buf = 1 + R_buf_fb1 / R_buf_fb2. Default R_buf_fb1 = 6.2k -> k_buf=7.2,
    # which matches k_atten = 7.15 for unity overall signal gain (small tubes).
    # ILC1-1/7 overrides to R_buf_fb1 = 9.1k -> k_buf = 10.1, giving 1.41x net
    # signal gain to deliver the 8.5 V_pk drive its 5 V_RMS filament needs.
    buf_fb1   = mc.get("buf_fb1",   6.2e3)
    buf_fb_ap = mc.get("buf_fb_ap", 6.2e3)
    # Buffer rail: fixed per-tube v_buf chosen to clip the buffer op-amp
    # at slightly below V_top_pk_demand. Op-amp clipping forces the loop
    # to compensate by pushing the JFET further into pinch-off (raising
    # |1-H| at op), so V_diff is delivered at a lower V_top swing and
    # the BJT runs in saturation at peak (V_CE -> V_CE_sat).
    #
    # Optional rail soft-start: ramp vcc_buf and vee_buf from 0 to v_buf
    # over t_rail_ramp seconds rather than stepping instantaneously. Real
    # PSUs always do this (output cap charges through a finite-current
    # regulator). Without it, ngspice applies the rail step in a single
    # timestep and the MOSFET model sees infinite-dV/dt at startup,
    # producing a multi-hundred-W single-timestep spike that's a sim
    # artifact rather than a real-circuit pulse. PWL is held flat past
    # the ramp via an explicit terminal point so the rails don't drift
    # via end-of-PWL extrapolation.
    t_rail_ramp = mc.get("t_rail_ramp", 0)
    if t_rail_ramp > 0:
        # PWL: 0V at t=0, full v_buf at t=t_rail_ramp, held there to t=100s.
        rail_definition = (
            f"Vcc_buf vcc_buf 0 PWL(0 0 {t_rail_ramp:.6g} {v_buf:.4g} 100 {v_buf:.4g})\n"
            f"Vee_buf vee_buf 0 PWL(0 0 {t_rail_ramp:.6g} -{v_buf:.4g} 100 -{v_buf:.4g})"
        )
    else:
        rail_definition = (f"Vcc_buf vcc_buf 0 {v_buf:.4g}\n"
                           f"Vee_buf vee_buf 0 -{v_buf:.4g}")

    ce_buf = mc.get("ce_buf", False)
    mos_buf = mc.get("mos_buf", False)
    bias_diode = mc.get("bias_diode", "Dbias")
    # MOSFET CE buffer: same topology as ce_buf but with logic-level
    # complementary MOSFETs in place of the BJT pair, and op-amps on
    # +-VCC instead of +-vcc_buf so the gates can be driven hard enough
    # to fully turn on the FET (V_GS >= 2.5 V overdrive needed). Loses
    # the V_BE drop entirely -- V_DS at peak is just I*R_DS_on, ~5 mV
    # for typical low-V/low-I tubes.
    # mos_buf + ce_buf=True  -> MOSFET common-source push-pull (output at drain).
    #                          Saves ~1 V of swing vs source follower but the
    #                          loop has a high-Q resonance at conducting OPs
    #                          (Cgd Miller + bias-chain pole) that's hard to
    #                          stabilise without massive bandwidth loss.
    # mos_buf + ce_buf=False -> MOSFET source follower (output at source).
    #                          Inherently stable (100% local feedback, no
    #                          Miller effect), at the cost of V_GS of swing
    #                          (bootstrap caps lift gate past v_buf to recover).
    buf_op_rails = "vcc vee" if mos_buf else "vcc_buf vee_buf"
    if mos_buf:
        # 0-V current-sense sources in series with each MOSFET source. The
        # manufacturer subcircuit doesn't expose its internal MOSFET to
        # @xname.m1[id] hierarchical accessors in this ngspice build, so we
        # measure I_D externally via i(V_imN) which always works.
        #
        # Gate damping resistors (R_gd_*, 100 ohm) form a low-pass with the
        # MOSFET's own C_GS (320-500 pF). Standard remedy for the buffer's
        # local-loop oscillation that appears when realistic gate caps load
        # the CE output stage -- the gate-node pole gets damped so it can no
        # longer pair with the op-amp's GBW pole to form a high-Q resonance.
        # Pole frequency ~ 1/(2*pi*100*400p) = 4 MHz, well above any signal
        # band, so the resistor contributes only damping, not bandwidth loss.
        bjt_or_fet_top = (
            "V_im_o_pmos vcc_buf vcc_buf_o_pmos 0\n"
            "R_gd_o_pmos q_o_bp_top g_o_pmos 1k\n"
            "XM_o_pmos v_osc_drive g_o_pmos vcc_buf_o_pmos DMP3098L\n"
            "V_im_o_nmos vee_buf_o_nmos vee_buf 0\n"
            "R_gd_o_nmos q_o_bn_bot g_o_nmos 1k\n"
            "XM_o_nmos v_osc_drive g_o_nmos vee_buf_o_nmos DMN3404L"
        )
        bjt_or_fet_bot = (
            "V_im_a_pmos vcc_buf vcc_buf_a_pmos 0\n"
            "R_gd_a_pmos q_a_bp_top g_a_pmos 1k\n"
            "XM_a_pmos v_ap_drive g_a_pmos vcc_buf_a_pmos DMP3098L\n"
            "V_im_a_nmos vee_buf_a_nmos vee_buf 0\n"
            "R_gd_a_nmos q_a_bn_bot g_a_nmos 1k\n"
            "XM_a_nmos v_ap_drive g_a_nmos vee_buf_a_nmos DMN3404L"
        )
    else:
        bjt_or_fet_top = ("Q_o_pnp v_osc_drive q_o_bp_top vcc_buf QBC327\n"
                           "Q_o_npn v_osc_drive q_o_bn_bot vee_buf QBC337")
        bjt_or_fet_bot = ("Q_a_pnp v_ap_drive q_a_bp_top vcc_buf QBC327\n"
                          "Q_a_npn v_ap_drive q_a_bn_bot vee_buf QBC337")
    booster_lines = ""
    if use_booster:
        # Buffer 0 is the same regardless of CC/CE choice (it's a follower)
        buf0_lines = f"""* Buffer 0: passive attenuator on V_osc, then op-amp follower to feed JFET
* with low-Z attenuated drive. R_atten_top:R_atten_bot = 56k:9.1k -> k_atten
* ~ 7.15, so V_drv_atten ~= V_osc / 7.15 (peak ~0.5 V at V_osc 3.6 V_pk),
* keeping V_DS in the JFET's linear region.
R_atten_top  v_osc          v_atten_input 56k
R_atten_bot  v_atten_input  0             9.1k
XU_buf0      v_atten_input  v_drv_atten   vcc vee v_drv_atten {opamp_buf0}"""
        if ce_buf:
            # Common-emitter complementary push-pull. PNP top + NPN bottom with
            # collectors as the output. V_out swings to within V_CE_sat (~0.2V)
            # of each rail -- saves V_BE = 0.6V vs CC emitter follower. Inverting
            # op-amp config + inverting CE BJT stage gives non-inverting overall
            # with closed-loop gain = R_fb / R_in.
            #
            # Two bias-chain options:
            #   forward diode (bias_zener_v=None): R + Dbias forward + Dbias
            #     forward + R. Total chain V drop = 2*v_buf, of which 2*V_F is
            #     in the diodes. Works only when v_buf ~ V_F + V_GS_th (1.0-
            #     1.5 V), the regime IV-6 and ILC1-1/8 use. At higher v_buf
            #     the chain forces V_R = v_buf - V_F, shoving V_GS far past
            #     threshold and causing shoot-through.
            #   Zener (bias_zener_v=value): R + Zener_reverse + Zener_reverse +
            #     R. Each Zener clamps at V_Z, soaking up the rail headroom so
            #     V_R can be small. Sized so V_GS_q sits just below or near
            #     V_th for class-B / shallow-class-AB push-pull. Used by
            #     ILC1-1/7 at v_buf=8 V (V_op=5 V_RMS / 30 ohm = 1 W out).
            # Optional Miller-style frequency compensation across the buffer's
            # feedback resistor. Real CE class-AB amps need this when the
            # output stage is operating near the rail / saturation-triode
            # boundary -- the BJT/MOSFET small-signal gain shifts dramatically
            # in that region, eroding the local loop's phase margin and
            # causing oscillation. A small cap (~100 pF) across R_fb rolls
            # off the loop gain at HF (>= 1 MHz) so the gain crosses unity
            # before the output-stage phase shift accumulates.
            buf_comp_pf = mc.get("buf_comp_pf")
            if buf_comp_pf is not None:
                buf_comp_top = f"C_buf1_comp v_osc_drive n_buf_osc_sum {buf_comp_pf:.4g}p\n"
                buf_comp_ap  = f"C_buf2_comp v_ap_drive  n_buf_ap_sum  {buf_comp_pf:.4g}p\n"
            else:
                buf_comp_top = ""
                buf_comp_ap  = ""
            bias_zener_v = mc.get("bias_zener_v")
            if bias_zener_v is not None:
                v_buf_v = mc.get("v_buf", 4.3)
                # Symmetric bias chain: 2*v_buf = 2*V_R + 2*V_Z, so V_R is
                # forced to (v_buf - V_Z). Pick R for ~5 mA chain current --
                # small enough to be negligible thermally (~50 mW total chain
                # dissipation), but low enough that the bias chain's output
                # impedance (~R_obb) doesn't pair with the MOSFET's Miller-
                # multiplied gate cap (~80 nF effective at the gate at peak
                # conduction) to form a sub-kHz pole that destabilises the
                # buffer's local loop. At 5 mA, R_obb = 130 ohm for v_buf=5V,
                # giving a gate-node pole at ~15 kHz, which the comp cap can
                # cleanly roll the loop gain past.
                v_r = max(0.05, v_buf_v - bias_zener_v)
                r_obb = max(100.0, v_r / 5e-4)
                bias_top_top = f"R_obb_top   vcc_buf       q_o_bp_top    {r_obb:.6g}"
                bias_top_mid = f"D_obb_top   n_buf_osc_out q_o_bp_top    Dzen_obb"
                bias_top_lower = f"D_obb_bot   q_o_bn_bot    n_buf_osc_out Dzen_obb"
                bias_top_bot = f"R_obb_bot   q_o_bn_bot    vee_buf       {r_obb:.6g}"
                bias_ap_top = f"R_abb_top   vcc_buf       q_a_bp_top    {r_obb:.6g}"
                bias_ap_mid = f"D_abb_top   n_buf_ap_out  q_a_bp_top    Dzen_obb"
                bias_ap_lower = f"D_abb_bot   q_a_bn_bot    n_buf_ap_out  Dzen_obb"
                bias_ap_bot = f"R_abb_bot   q_a_bn_bot    vee_buf       {r_obb:.6g}"
            else:
                bias_top_top = "R_obb_top   vcc_buf       q_o_bp_top    200"
                bias_top_mid = f"D_obb_top   q_o_bp_top    n_buf_osc_out {bias_diode}"
                bias_top_lower = f"D_obb_bot   n_buf_osc_out q_o_bn_bot   {bias_diode}"
                bias_top_bot = "R_obb_bot   q_o_bn_bot    vee_buf       200"
                bias_ap_top = "R_abb_top   vcc_buf       q_a_bp_top    200"
                bias_ap_mid = f"D_abb_top   q_a_bp_top    n_buf_ap_out  {bias_diode}"
                bias_ap_lower = f"D_abb_bot   n_buf_ap_out q_a_bn_bot    {bias_diode}"
                bias_ap_bot = "R_abb_bot   q_a_bn_bot    vee_buf       200"
            buf12_lines = f"""
* Buffer 1 (CE complementary push-pull): v_drv_atten -> v_osc_drive
* Op-amp + and - inputs SWAPPED relative to standard inverting amp because
* the CE BJT stage is itself inverting -- if we used standard inverting amp
* (signals into V-), the loop would have positive feedback and latch up.
* With signals into V+, the BJT inversion provides the second sign flip
* needed for negative feedback overall.
XU_buf_osc n_buf_osc_sum 0 {buf_op_rails} n_buf_osc_out {opamp_bufo}
R_buf1_in   v_drv_atten n_buf_osc_sum 1k
R_buf1_fb   v_osc_drive n_buf_osc_sum {buf_fb1:.6g}
{buf_comp_top}{bias_top_top}
{bias_top_mid}
{bias_top_lower}
{bias_top_bot}
{bjt_or_fet_top}

* Buffer 2 (CE complementary push-pull): v_ap -> v_ap_drive
* DC-block cap on v_ap to kill the JFET-rectification offset before the
* gain stage. C must be sized so the HPF corner against R_buf2_in (1k,
* the AC load at n_buf2_ac since op-amp summing junction is virtual GND)
* is well below f0 = 1 kHz. C = 10 uF gives fc = 16 Hz; smaller caps
* attenuate the carrier (100 nF would have fc = 1.6 kHz, killing 60% of
* the signal at f0).
C_buf2_dcblock v_ap         n_buf2_ac    10u IC=0
R_buf2_dcref   n_buf2_ac    0            100k
* Inverting amp summing junction takes both v_drv_atten (via cap-coupled v_ap)
* and v_ap_drive feedback. R_buf2_in is from n_buf2_ac (AC-coupled v_ap).
XU_buf_ap   n_buf_ap_sum 0 {buf_op_rails} n_buf_ap_out {opamp_bufa}
R_buf2_in   n_buf2_ac   n_buf_ap_sum  1k
R_buf2_fb   v_ap_drive  n_buf_ap_sum  {buf_fb_ap:.6g}
{buf_comp_ap}{bias_ap_top}
{bias_ap_mid}
{bias_ap_lower}
{bias_ap_bot}
{bjt_or_fet_bot}"""
        else:
            # CC topology: BJT emitter follower or MOSFET source follower.
            # Default bias chain is the static R-D-D-R + bootstrap caps. With
            # MOSFETs, V_GS_th (~1 V for DMN3404L/DMP3098L) is higher than the
            # silicon V_F (0.65 V) the diodes drop, so quiescent V_GS sits
            # below threshold => sub-threshold class-B with op-amp loop
            # closing the crossover. 0-V V_im_* sources sense MOSFET drain
            # current for check_power.
            #
            # Optional servo bias (servo_bias=True, MOSFET CC only): replaces
            # the diode chain with a B-source-driven floating bias controlled
            # by an LM358 integrator that senses I_NMOS+I_PMOS via small
            # source resistors and adjusts to maintain target quiescent
            # current regardless of V_th variation. The B-sources are SPICE
            # idealisations of the real-circuit V_BE multiplier with
            # servo-modulated divider; the discrete implementation uses
            # 1 BJT + 1 JFET + 3 R per buffer arm.
            servo_bias = mc.get("servo_bias", False) and mos_buf
            servo_iq = mc.get("servo_iq_target", 10e-3)
            servo_r = mc.get("servo_r_sense", 0.5)
            if mos_buf:
                if servo_bias:
                    # Insert R_sense_n / R_sense_p in the source path between
                    # MOSFET source and v_osc_drive (output to bridge load).
                    cc_dev_o_top = (
                        "V_im_o_nmos vcc_buf vcc_buf_o_nmos 0\n"
                        "XM_o_nmos vcc_buf_o_nmos q_o_bn n_o_nmos_src DMN3404L\n"
                        f"R_sense_o_n n_o_nmos_src v_osc_drive {servo_r:.4g}"
                    )
                    cc_dev_o_bot = (
                        "V_im_o_pmos vee_buf_o_pmos vee_buf 0\n"
                        "XM_o_pmos vee_buf_o_pmos q_o_bp n_o_pmos_src DMP3098L\n"
                        f"R_sense_o_p v_osc_drive n_o_pmos_src {servo_r:.4g}"
                    )
                    cc_dev_a_top = (
                        "V_im_a_nmos vcc_buf vcc_buf_a_nmos 0\n"
                        "XM_a_nmos vcc_buf_a_nmos q_a_bn n_a_nmos_src DMN3404L\n"
                        f"R_sense_a_n n_a_nmos_src v_ap_drive {servo_r:.4g}"
                    )
                    cc_dev_a_bot = (
                        "V_im_a_pmos vee_buf_a_pmos vee_buf 0\n"
                        "XM_a_pmos vee_buf_a_pmos q_a_bp n_a_pmos_src DMP3098L\n"
                        f"R_sense_a_p v_ap_drive n_a_pmos_src {servo_r:.4g}"
                    )
                else:
                    cc_dev_o_top = (
                        "V_im_o_nmos vcc_buf vcc_buf_o_nmos 0\n"
                        "XM_o_nmos vcc_buf_o_nmos q_o_bn v_osc_drive DMN3404L"
                    )
                    cc_dev_o_bot = (
                        "V_im_o_pmos vee_buf_o_pmos vee_buf 0\n"
                        "XM_o_pmos vee_buf_o_pmos q_o_bp v_osc_drive DMP3098L"
                    )
                    cc_dev_a_top = (
                        "V_im_a_nmos vcc_buf vcc_buf_a_nmos 0\n"
                        "XM_a_nmos vcc_buf_a_nmos q_a_bn v_ap_drive DMN3404L"
                    )
                    cc_dev_a_bot = (
                        "V_im_a_pmos vee_buf_a_pmos vee_buf 0\n"
                        "XM_a_pmos vee_buf_a_pmos q_a_bp v_ap_drive DMP3098L"
                    )
            else:
                cc_dev_o_top = "Q_o_npn  vcc_buf q_o_bn v_osc_drive QBC337"
                cc_dev_o_bot = "Q_o_pnp  vee_buf q_o_bp v_osc_drive QBC327"
                cc_dev_a_top = "Q_a_npn  vcc_buf q_a_bn v_ap_drive QBC337"
                cc_dev_a_bot = "Q_a_pnp  vee_buf q_a_bp v_ap_drive QBC327"
            # Bias block: either the static R-D-D-R + bootstrap caps OR the
            # servo-controlled B-source chain. When servo_bias=True, the
            # bootstrap caps and bias diodes are replaced with an op-amp
            # integrator that holds the bias current at servo_iq_target.
            if servo_bias:
                # Sense V_ref: target = (2*Iq + (2/pi)*Ipk) * R_sense.
                # Ipk is signal-dependent (varies with V_op and bridge load).
                # For ILC1-1/7: Ipk ~ 235 mA at V_op = 5 V_RMS, so
                # V_ref = (2*0.01 + 0.637*0.235) * 0.5 = 0.085 V at Iq=10 mA.
                # If Ipk changes (different tube), recompute V_ref.
                # For other tubes, this would need recalibration.
                # Approximate I_pk from V_op and bridge total R = R_op+R_sen:
                v_op_v = mc.get("V_op", 5.0)  # default if not in mc
                r_load = mc.get("r_top_ref", 5e3) / mc.get("r_bot_ref", 1e3) * mc.get("r_sense", 5)
                # Actually use V_op from spec via passthrough; r_load is filament + sense
                r_total = mc.get("R_op", 25.0) + mc.get("r_sense", 5)
                i_pk_est = v_op_v * 1.414 / r_total  # peak load current estimate
                v_ref = (2 * servo_iq + (2/3.14159) * i_pk_est) * servo_r
                bias_block_o = f"""* Servo bias for buffer 1 (osc).  R_sense already in source path.
* Sum sense voltages via B-source: V(n_o_sense_inst) = V(NMOS_src) - V(PMOS_src).
B_sense_o n_o_sense_inst 0 V = V(n_o_nmos_src) - V(n_o_pmos_src)
* Low-pass filter: corner ~ 16 Hz (1.6 ms time constant).
R_lp_o n_o_sense_inst n_o_sense_avg 100k
C_lp_o n_o_sense_avg 0 100n IC=0
* V_ref source: target average sense voltage at design operating point.
V_ref_o n_o_vref 0 {v_ref:.4g}
* LM358 servo (modeled with uopamp_lvl3): inverting integrator.
* + input = V_ref, - input via R_in from sense; C_int from output to - input.
XU_servo_o n_o_vref n_o_servo_minus vcc vee n_o_servo_out uopamp_lvl3 Avol=10meg GBW=1meg Rin=100g Rout=10 Iq=70u Ilimit=20m Vrail=100m Vmax=12 Vos=2.5e-3
R_servo_o_in n_o_sense_avg n_o_servo_minus 100k
C_servo_o_int n_o_servo_out n_o_servo_minus 100n IC=0
* Initial servo output: pre-load to give ~1.5 V V_GS bias at t=0.
.ic V(n_o_servo_out)=1.5
* B-sources: q_top - n_buf_osc_out = V_servo, n_buf_osc_out - q_bot = V_servo.
B_bias_o_top q_o_bn n_buf_osc_out V = V(n_o_servo_out)
B_bias_o_bot n_buf_osc_out q_o_bp V = V(n_o_servo_out)"""
                bias_block_a = f"""* Servo bias for buffer 2 (ap).
B_sense_a n_a_sense_inst 0 V = V(n_a_nmos_src) - V(n_a_pmos_src)
R_lp_a n_a_sense_inst n_a_sense_avg 100k
C_lp_a n_a_sense_avg 0 100n IC=0
V_ref_a n_a_vref 0 {v_ref:.4g}
XU_servo_a n_a_vref n_a_servo_minus vcc vee n_a_servo_out uopamp_lvl3 Avol=10meg GBW=1meg Rin=100g Rout=10 Iq=70u Ilimit=20m Vrail=100m Vmax=12 Vos=2.5e-3
R_servo_a_in n_a_sense_avg n_a_servo_minus 100k
C_servo_a_int n_a_servo_out n_a_servo_minus 100n IC=0
.ic V(n_a_servo_out)=1.5
B_bias_a_top q_a_bn n_buf_ap_out V = V(n_a_servo_out)
B_bias_a_bot n_buf_ap_out q_a_bp V = V(n_a_servo_out)"""
            else:
                bias_block_o = f"""R_obb_top_a  vcc_buf      mid_obb_top  680
R_obb_top_b  mid_obb_top  q_o_bn       680
C_obb_top    mid_obb_top  v_osc_drive  4.7u IC=0
D_obb_top    q_o_bn       n_buf_osc_out {bias_diode}
D_obb_bot    n_buf_osc_out q_o_bp      {bias_diode}
R_obb_bot_b  q_o_bp       mid_obb_bot  680
R_obb_bot_a  mid_obb_bot  vee_buf      680
C_obb_bot    mid_obb_bot  v_osc_drive  4.7u IC=0"""
                bias_block_a = f"""R_abb_top_a  vcc_buf      mid_abb_top  680
R_abb_top_b  mid_abb_top  q_a_bn       680
C_abb_top    mid_abb_top  v_ap_drive   4.7u IC=0
D_abb_top    q_a_bn       n_buf_ap_out {bias_diode}
D_abb_bot    n_buf_ap_out q_a_bp       {bias_diode}
R_abb_bot_b  q_a_bp       mid_abb_bot  680
R_abb_bot_a  mid_abb_bot  vee_buf      680
C_abb_bot    mid_abb_bot  v_ap_drive   4.7u IC=0"""
            buf12_lines = f"""
* Buffer 1 (CC emitter follower): V_drv_atten -> V_osc_drive (gain k_buf,
* class-AB BC337/BC327). Bootstrap caps from output to bias-chain midpoints
* lift the bias rail with the signal so the BJT base can drive past vcc_buf
* / vee_buf at peak swing. Feedback divider R_buf1_fb1:R_buf1_fb2 sets k_buf.
XU_buf_osc   v_drv_atten n_buf_osc_fb vcc_buf vee_buf n_buf_osc_out {opamp_bufo}
R_buf1_fb1   v_osc_drive n_buf_osc_fb {buf_fb1:.6g}
R_buf1_fb2   n_buf_osc_fb 0           1k
{bias_block_o}
{cc_dev_o_top}
{cc_dev_o_bot}

* Buffer 2 (CC emitter follower): V_ap -> V_ap_drive (gain k_buf_ap).
C_buf2_dcblock v_ap         n_buf2_ac    100n IC=0
R_buf2_dcref   n_buf2_ac    0            100k
XU_buf_ap    n_buf2_ac   n_buf_ap_fb     vcc_buf vee_buf n_buf_ap_out {opamp_bufa}
R_buf2_fb1   v_ap_drive  n_buf_ap_fb     {buf_fb_ap:.6g}
R_buf2_fb2   n_buf_ap_fb 0               1k
{bias_block_a}
{cc_dev_a_top}
{cc_dev_a_bot}"""
        # Optional step-down transformer + class-C tank: at hf_mode only.
        # Buffer outputs (v_osc_drive, v_ap_drive) drive the primary, which
        # is parallel-LC tuned to f0 (impedance transformation up). The
        # secondary (v_osc_load, v_ap_load) drives the bridge at lower V /
        # higher I. Lets the BJT pair sit at high V_supply / low I_pk for
        # class-C operation, with the tank providing impedance transformation
        # so V_pk on the primary can exceed v_buf via the LC ringing.
        tank_l = mc.get("tank_l")
        tank_c = mc.get("tank_c")
        tank_lines = ""
        # When the transformer is in use, both L_tank and L_pri attach to the
        # DC-blocked node n_pri_top (set up below in xfmr_lines). When there's
        # no transformer, the tank attaches directly to v_osc_drive.
        tank_top = "n_pri_top" if use_xfmr else "v_osc_drive"
        if hf_mode and tank_l is not None and tank_c is not None:
            if use_xfmr:
                tank_lines = (f"\n* Class-C / harmonic-rejection LC tank on transformer primary\n"
                              f"L_tank {tank_top} v_ap_drive {tank_l:.6g} IC=0\n"
                              f"C_tank {tank_top} v_ap_drive {tank_c:.6e} IC=0")
            else:
                tank_lines = (f"\n* Harmonic-rejection LC tank across bridge differential\n"
                              f"L_tank {tank_top} v_ap_drive {tank_l:.6g} IC=0\n"
                              f"C_tank {tank_top} v_ap_drive {tank_c:.6e} IC=0")
        # Step-down transformer (when use_xfmr): primary on v_osc_drive,v_ap_drive
        # (high V/low I), secondary on v_osc_load,v_ap_load (low V/high I = filament).
        # K=0.99 gives ~1% leakage; for ideal coupling K=1.0 but ngspice may
        # be unhappy. Magnetizing inductance L_pri set per-tube so primary
        # impedance at f0 is dominated by reflected load, not magnetizing.
        xfmr_lines = ""
        if use_xfmr:
            l_sec = xfmr_lpri / (xfmr_n ** 2)
            # C_block_pri (1 uF) breaks the DC path through L_pri. Without it,
            # any small DC offset between the two buffer outputs (Vos mismatch,
            # JFET-rectification residual, BJT bias asymmetry) drives unbounded
            # DC current through the ideal-inductor L_pri until BJT-saturation
            # current limits it -- ~1.7 A at 24 V rails = 40 W of DC dissipation
            # per BJT. With C_block, the cap charges to whatever DC offset the
            # buffers settle at and L_pri sees no DC. X_C(1uF) at 100 kHz = 1.6
            # ohm, negligible vs the ~480 ohm reflected load.
            xfmr_lines = (f"\n* Step-down transformer Np:Ns = {xfmr_n}:1 (DC-blocked primary)\n"
                          f"* L_pri = {xfmr_lpri:.4g} H, L_sec = {l_sec:.4g} H, k = 0.99\n"
                          f"* Both L_pri and L_tank attach to n_pri_top so a single C_block_pri\n"
                          f"* breaks the DC path through either inductor. Without this, any\n"
                          f"* tiny DC offset between buffer outputs drives unbounded current\n"
                          f"* through whichever inductor is connected (~1.7 A measured = 40 W\n"
                          f"* per BJT). X_C(1uF) at 100 kHz = 1.6 ohm, negligible vs reflected\n"
                          f"* load (~480 ohm at N=4).\n"
                          f"C_block_pri v_osc_drive n_pri_top 1u IC=0\n"
                          f"L_pri n_pri_top v_ap_drive {xfmr_lpri:.6g} IC=0\n"
                          f"L_sec v_osc_load v_ap_load {l_sec:.6g} IC=0\n"
                          f"K_xfmr L_pri L_sec 0.99")
        bias_zener_v = mc.get("bias_zener_v")
        if bias_zener_v is not None:
            # Zener (BZX84-class) wired in reverse breakdown to absorb v_buf
            # rail headroom in the CE-MOSFET bias chain. Used by ILC1-1/7 at
            # v_buf=8 V; pick BZX84-C7V5 for V_Z = 7.5 V, leaving V_R = 0.5 V
            # per side -> V_GS_q = 0.5 V (sub-threshold class-B; op-amp loop
            # corrects the crossover at f0=1-100 kHz easily).
            zener_model = (f"\n.model Dzen_obb D(IS=10n N=1.0 RS=1 "
                           f"BV={bias_zener_v} IBV=100m CJO=80p TT=10n)")
        else:
            zener_model = ""
        # Absolute paths to the manufacturer MOSFET subcircuit models. Need
        # absolute paths because ngspice runs from the WORK subdirectory, so
        # any relative include path would resolve from there.
        pmos_path = (HERE / "spice_models" / "DMP3098L.spice.txt").as_posix()
        nmos_path = (HERE / "spice_models" / "DMN3404L.spice.txt").as_posix()
        models = f""".model Dbias  D(IS=2.52n N=1.752 RS=0.568 BV=80 IBV=0.1m CJO=4p){zener_model}
* Schottky (BAT54-class): V_F ~0.3V at 1mA. Used as bias-chain diode for
* sub-threshold class-C operation: 2*V_d_schottky = 0.6V offset between
* BJT bases puts V_BE_quiescent ~0.3V (below 0.6V on threshold), so the
* BJTs only pulse-conduct at AC peaks.
.model Dschottky D(IS=10n N=1.0 RS=0.1 BV=20 IBV=0.1m CJO=10p)
.model QBC337 NPN(IS=1e-14 BF=300 BR=10 RB=10 RC=0.5 RE=0.1 IKF=0.8
+ CJC=11p CJE=20p VAF=100)
.model QBC327 PNP(IS=1e-14 BF=300 BR=10 RB=10 RC=0.5 RE=0.1 IKF=0.8
+ CJC=11p CJE=20p VAF=100)
* Logic-level complementary MOSFET pair: DMP3098L (PMOS) / DMN3404L (NMOS),
* Diodes Inc., SOT-23. Manufacturer subcircuit models (LEVEL=3 internal,
* with junction caps + body diodes) loaded from spice_models/. Terminals
* are 3-pin: drain, gate, source (no external body).
.include {pmos_path}
.include {nmos_path}"""
        booster_lines = "\n" + buf0_lines + "\n\n" + buf12_lines.lstrip() + tank_lines + xfmr_lines + "\n" + models + "\n"
    # Optional pre-heat boost line (added at end of netlist body)
    boost_line = ""
    if p_boost > 0 and t_boost > 0:
        boost_line = (
            f"\n* Option D: pre-heat boost {p_boost*1e3:.1f} mW for {t_boost*1e3:.0f} ms\n"
            f"V_boost_en vboost_en 0 PWL(0 1 {max(t_boost-1e-6,0):.6e} 1 {t_boost:.6e} 0 1 0)\n"
            f"B_boost 0 T_node I = {p_boost:.6e} * (V(vboost_en) > 0.5)\n"
        )
    # V_offset reference: self-biased JFET (LS844 second die) that tracks
    # V_p of the matched J_var on the same die. Produces V_source_ref =
    # I_ref·R_src_ref ≈ |V_p|/2 (positive). XU_sum subtracts this from
    # V_int_out: V_ctl = V_int_out - V_source_ref. So V_GS_var at
    # V_int_out=0 is -V_source_ref ≈ V_p/2 (negative, safely below
    # the gate-channel diode threshold) and matched to V_p across builds.
    if force_v_offset_v is not None:
        # Diagnostic override: replace Q_ref with a fixed source on
        # n_ref_src equal to -force_v_offset_v, preserving the
        # V_ctl = V_int_out + force_v_offset_v back-compat convention.
        v_offset_block = (
            f"* Fixed V_offset (diagnostic / sweep override): V_ctl_OP = V_int_out + {float(force_v_offset_v):.4g}\n"
            f"V_offset_ref n_ref_src 0 {-float(force_v_offset_v):.4g}"
        )
    else:
        v_offset_block = (
            f"* V_p-tracking V_offset reference: LS844 die 2 wired self-biased.\n"
            f"* I_ref = (VCC - V_drain)/(R_d_ref); V_GS_ref = -I_ref·R_src_ref.\n"
            f"* V_source_ref (at n_ref_src) ≈ |V_p|/2 ≈ 1 V at typical LS844.\n"
            f"* On the same die as J_var → ΔV_GS ≤ 5 mV (LS844 grade match).\n"
            f"R_d_ref    vcc          n_ref_drain   {r_d_ref_kohm:.4g}k\n"
            f"J_ref      n_ref_drain  0             n_ref_src  J_LS844\n"
            f"R_src_ref  n_ref_src    0             {r_src_ref_ohm:.4g}"
        )
    return f"""* Closed-loop VFD-filament regulator with thermal model

.include {(HERE/'uopamp.lib').as_posix()}

.param T_amb={T_AMB}
.param R_amb={r_amb_eff:.6g}
.param sigma_eps_A={sigma_eps_A_eff:.6e}
.param C_th={c_th_eff:.6e}
.param fil_exp={fil_exp:.4f}

Vcc  vcc 0  {VCC}
Vee  vee 0 {VEE}
* Buffer rails for the class-AB BJT collectors. Class-H envelope-tracking
* servo in booster mode (auto-tunes vcc_buf/vee_buf to V_top_pk + 0.3 V),
* fixed at VCC/VEE in non-booster mode (no buffers to power).
{rail_definition}

* === Wien bridge oscillator (alpha=0.5) ===
R1   v_osc  ns   {r1_wien:.6g}
C1   ns     np   {c1_wien:.6e}  IC=0
R2   np     0    {r2_wien:.6g}
C2   np     0    {c2_wien:.6e}  IC=10m
Rg   nn     0    10k
Rfa  nn     fb   10k
Rfb  fb     v_osc  12k
Q1   fb     b1    v_osc Q2N3904
Q2   v_osc  b2    fb    Q2N3904
Rtop1 fb    b1    {rtop_bjt:.6g}
Rbot1 b1    v_osc {rbot_bjt:.6g}
Rtop2 v_osc b2    {rtop_bjt:.6g}
Rbot2 b2    fb    {rbot_bjt:.6g}
XU_osc np nn vcc vee v_osc {opamp_osc}

* === JFET-controlled all-pass: V_ap = V_osc * (1 - jwR_DS C)/(1 + jwR_DS C) ===
* All-pass input is taken from {v_osc_jfet}: when a buffer chain is in use,
* this is v_drv_atten (low-Z attenuated signal from Buffer 0); otherwise it
* is v_osc directly. Attenuation keeps V_DS << V_GS-Vto so the JFET stays
* in its linear region, eliminating the asymmetric V_GS shift caused by the
* model's drain/source swap when V_DS reverses polarity.
R_ap1 {v_osc_jfet} n_ap_minus {R_AP:.6g}
R_ap2 v_ap  n_ap_minus {R_AP:.6g}
* JFET variable resistor: single LS844 die. JFETs have no body diode, so
* the back-to-back MOSFET arrangement (needed to keep body diodes reverse-
* biased on both half-cycles) is unnecessary. The channel handles both
* V_DS polarities cleanly via its symmetric drain/source structure. R_DS
* in triode is 1/(2·β·(V_GS-V_p)); at LS844 typical (β=1.25 mS/V) and
* R_DS_target = 333 Ω, V_GS-V_p ≈ 1.2 V — moderate-overdrive triode,
* clean linear behaviour, low harmonic content (predicted 6-12 % H2 in
* this topology without bootstrap, down to 3 % with the bootstrap of
* commit e5017a4 adapted to the new summer topology).
*
* J_var uses the J_LS844 model (defined below). The matched die in the
* same LS844 package serves as Q_ref for the V_p-tracking V_offset
* reference, also using the same .model statement (so V_p and β are
* identical between J_var and Q_ref in simulation; in hardware the LS844
* on-die match guarantees ±5 mV V_GS, 5 % I_DSS).
*
* Drain = v_drv_atten (or v_osc on no-booster tubes), source = n_ap_plus.
* JFET is symmetric so either side could be drain — by convention we put
* the higher-voltage-swing side as drain.
J_var {v_osc_jfet} v_ctl n_ap_plus J_LS844
.model J_LS844 NJF(Vto={jfet_vp:.4f} Beta={jfet_beta:.4e} Lambda={jfet_lambda:.4f})
C_ap n_ap_plus 0 {c_ap_v:.6e}    IC=0
XU_ap n_ap_plus n_ap_minus vcc vee v_ap {opamp_ap}

* === Tube filament thermal-electrical macromodel ===
* The filament behaves as a non-linear resistor R(T) = R_amb*(T/T_amb)^fil_exp
* with thermal capacity C_th and radiative cooling sigma*eps*A*(T^4-T_amb^4).
* Encapsulated as a subcircuit so the controller netlist doesn't carry
* behavioural sources directly -- this is a model of the tube itself.
*   Terminals: v_top, v_bot   (filament endpoints, AC drive across these)
*              T_node          (internal thermal node, exposed for monitoring)
*              r_fil           (instantaneous R(T) as voltage, for monitoring)
* All physical parameters are global .params (R_amb, sigma_eps_A, C_th,
* T_amb, fil_exp) so a single instantiation is enough.
.subckt filament v_top v_bot T_node r_fil
* T_node is clamped via max(T, T_amb) in every formula. Physically the
* filament can't sit below ambient (no negative-temperature regime), so
* this clamp doesn't alter behaviour in the operating regime (T >= T_amb
* always). It exists purely as a numerical safety: without it, the
* adaptive solver can occasionally take a bad step where T_node dips
* below 0, at which point the T^4 cooling term explodes in sign and
* drives T_node to -inf in a few rejected timesteps. With the clamp,
* the worst case T_node briefly equals T_amb and the model just sits.
B_fil   v_top v_bot I = (V(v_top) - V(v_bot)) / (R_amb * (max(V(T_node),T_amb)/T_amb)^fil_exp)
B_pelec 0 T_node    I = (V(v_top)-V(v_bot))*(V(v_top)-V(v_bot)) / (R_amb * (max(V(T_node),T_amb)/T_amb)^fil_exp)
B_prad  T_node 0    I = sigma_eps_A * (max(V(T_node),T_amb)^4 - T_amb^4)
C_th    T_node 0    {{C_th}} IC={T_AMB}
B_R     r_fil 0     V = R_amb * (max(V(T_node),T_amb)/T_amb)^fil_exp
.ends filament

* === AC Wheatstone bridge ===
* Filament arm: V_osc -> filament(thermal) -> node_A -> R_sense -> V_ap
{filament_line}
R_sen node_A {bridge_v_bot} {r_sense_v:.6g}
* Reference arm: V_osc -> R_top_ref -> node_B -> R_bot_ref -> V_ap.
* Bridge balance R_top_ref / R_bot_ref = R_op / R_sen targets R_op exactly.
R_top_ref {bridge_v_top} node_B {r_top_ref:.6g}
R_bot_ref node_B {bridge_v_bot}  {r_bot_ref:.6g}

* === Difference amp (1-op-amp subtractor, gain 1) ===
* Loop polarity bookkeeping:
*   JFET-era: V_int_out + → V_ctl - (inverter) → V_GS_JFET - → pinched
*             → R_DS bigger → drive bigger. Cold filament needs more drive
*             → V_int_out +. Diff-amp natural wiring (n_diff = node_B -
*             node_A) gave cold → demod < 0 → inverting integrator winds
*             V_int_out +. Correct.
*   NMOS+level-shift (current): V_ctl = V_int_out + V_offset (non-inverting
*             summer). V_int_out + → V_ctl + → V_GS + → NMOS more on
*             → R_DS smaller → drive smaller. Cold filament needs more
*             drive → V_int_out -. Diff-amp SWAPPED (n_diff = node_A -
*             node_B) gives cold → demod > 0 → inverting integrator winds
*             V_int_out -. Correct.
* So the swap done for the PMOS era is also right for NMOS+level-shift,
* by coincidence of sign-flipping the (gate-drive polarity) twice
* (PMOS inversion AND inverter removal) — net result: opposite polarity
* from JFET, swapped diff-amp matches.
R_a1 node_A n_diff_plus  {r_a1:.6g}
R_a2 n_diff_plus  0      {r_a2:.6g}
R_b1 node_B n_diff_minus {r_b1:.6g}
R_b2 n_diff_minus n_diff {r_b2:.6g}
XU_diff n_diff_plus n_diff_minus vcc vee n_diff {opamp_diff}

* === Comparator (behavioural sign of V_osc) ===
* Comparator: open-loop op-amp (one channel of the second TLV9154 quad).
* V+/V- swapped from the natural "sign of V_osc" connection ONLY when the
* CE booster is on (mc["ce_buf"]=True): in that topology Buffer 2 is an
* inverting summer (sign-flipped). The CC booster (default for non-mos_buf
* tubes like ILC1-1/7) uses non-inverting Buffers 1 and 2, no sign flip,
* so the comparator stays unswapped.
XU_cmp {cmp_inputs} vcc vee n_cmp {opamp_cmp}

* === Polarity-switching demodulator ===
.model swMod SW(VT=0 VH=0.1 RON=10 ROFF=1G)
S1 n_diff vplus n_cmp 0 swMod
S2 0      vplus 0     n_cmp swMod
R_bias vplus 0 1Meg
R_din n_diff n_dem_minus 10k
R_dfb n_demout n_dem_minus 10k
XU_dem vplus n_dem_minus vcc vee n_demout {opamp_dem}

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
R_intfb  n_int_pidp v_int_raw {r_pid:.6g}
* Realistic startup: cap begins uncharged (no IC). Loop self-starts from
* the intentional 1% bridge mismatch above + Vos drift in the demod and
* integrator op-amps.
C_intfb  n_int_minus n_int_pidp {c_int:.6e}  IC={c_intfb_ic_v:.4g}
* HF rolloff cap: in parallel with R_PID to limit HF gain and suppress
* the f0 ripple from V_demod that the D term would otherwise pump
* through to V_ctl.
C_hf     n_int_pidp v_int_raw {c_hf:.6e}     IC=0
* Integrator op-amp output is v_int_raw (free-swinging, no clamp diodes
* on this node). The downstream-visible v_int_out is the upper-clamped
* version produced by the saturator (R_aw_out + D_aw_hi below). The
* back-calc path (R_bc + diff amp) feeds e_sat = v_int_raw - v_int_out
* into n_int_minus, unwinding the integrator only when v_int_raw is past
* the upper clamp -- zero effect when in range.
* DUAL-SUPPLY for the integrator. V_int_out_OP is slightly negative (~-0.4 V
* for ILC1-1/7) with the NMOS variable-R + level-shift architecture
* (V_ctl = V_int_out + V_offset). Cold-start: V_int_out winds from 0 toward
* OP through negative values; the NMOS pair is strongly on at cold start
* (V_GS ≈ V_offset = +2.5 V), so |1-H| ≈ 0 and the filament heats gently.
* No wrong-polarity basin (MOSFET gate is insulated; there's no equivalent
* of the JFET gate-source forward-conduction trap regardless of V_int_out
* sign).
XU_int 0 n_int_minus vcc vee v_int_raw {opamp_int}

* === Passive saturator + back-calculation anti-windup ===
* The integrator op-amp output v_int_raw drives v_int_out through a series
* resistor R_aw_out. A single upper clamp diode D_aw_hi clips v_int_out to
* V_clamp_hi + Vf. When v_int_raw exceeds the clamp, the clamp diode
* conducts, with current bounded by R_aw_out. The lower bound on v_int_out
* is the integrator op-amp's own VEE rail (no diode clamp needed; the
* NMOS+level-shift architecture has V_int_out_OP negative).
*
* R_aw_out = 10 ohm sizes for the loads on v_int_out (R_sum_a = 100k draws
* ~13 uA at OP; the diff amp's R_diff1 draws another ~5 uA): the load drop
* across R_aw_out is ~0.18 mV at OP, which through the back-calc resistor
* would give a ~1 nA bias current at the integrator input -- equivalent to
* ~0.3 K of steady-state T error. Cold-start clamp peak current is
* ~50 mA on ILC1-1/7 (only ~13 mA on IV-18) for ~40 ms during cold-start
* before the loop settles; this is at the OPA2188 chopper's typical Isc
* of 50 mA. OPA2188 datasheet rates 35 mA min / 65 mA typ; a min-spec
* part would current-limit at 35 mA during cold-start, slowing the
* integrator wind but the loop still converges. Verified by
* verify_opamp_currents.py + plot_convergence.py 2026-05-20. The diode
* itself sees the same current; BAS70 / 1N5819 Schottky rated 1 A
* continuous, plenty of margin.
* Clamp widened from +2.5 V to +6.0 V to give the loop room for the
* JMMBFJ112's V_p range (-1 to -5 V). With the +6 V upper clamp, V_ctl
* can swing to -6 V, comfortably accommodating worst-case V_p = -5 parts
* without engaging the clamp at OP. Cold-start kick still hits the clamp
* (which is the intended anti-windup behaviour during slew). The +/-9 V
* op-amp supplies easily accommodate +6 V on V_int_out.
V_clamp_hi v_clamp_hi 0  {v_clamp_hi:.4g}
V_clamp_lo v_clamp_lo 0  {v_clamp_lo:.4g}
R_aw_out   v_int_raw  v_int_out  10
D_aw_hi    v_int_out  v_clamp_hi Dclamp
D_aw_lo    v_clamp_lo v_int_out  Dclamp
* Lower clamp at V_clamp_lo = -0.7 V → V_int_out floor ≈ -1.0 V (Schottky
* V_F ≈ 0.3 V at saturation current). Without it, the loop's proportional
* gain (Kp=10) sends V_int_out to the integrator's negative rail (~-5 V)
* in milliseconds at cold start, and the 100+ ms recovery from saturation
* drives a +68 K overshoot. With the clamp + back-calc anti-windup
* (R_bc), V_int_out is bounded at ~-1 V, anti-windup unwinds the
* integrator quickly when the loop transitions out of the cold-start
* high-error regime.
* Dclamp: switched 2026-05 from 1N4148-class to Schottky (BAT54 / 1N5819).
* Reason: at the worst-case clamp current (op-amp Isc ~50 mA chopper),
* the 1N4148's V_F was ~0.76 V; that meant the effective V_int_out floor
* sat at V_clamp_lo - 0.76 = -0.46 V even with V_clamp_lo = +0.3 V. V_ctl
* (via inverter, +1*V_int_out) crossed the JFET gate-source forward
* threshold (~0.6 V) on AC peaks, latching the loop in a "wrong-polarity"
* steady state where the JFET gate diode forward-conducts. With Schottky
* V_F ~0.3 V at 50 mA, the effective floor is V_clamp_lo - 0.3 ≈ 0 V,
* so V_ctl stays comfortably below the gate-conduction threshold. The
* lvl3 op-amp current verification (verify_opamp_currents.py) exposed
* the bistability when Ilimit was tightened from 1 A to 50/65 mA.
* Schottky (BAT54 / 1N5819 class). Higher SOA than 1N4148 for the
* worst-case clamp engagement current (~ Ilimit at full op-amp saturation).
.model Dclamp D(Is=10n N=1.0 RS=0.1 BV=40 IBV=0.1m CJO=10p)

* Difference op-amp: e_sat = v_int_raw - v_int_out (the "saturation error").
* Zero when v_int_out follows v_int_raw (no clamp current), positive when
* upper clamp diode conducts (v_int_raw > v_int_out), negative when lower
* clamp diode conducts. Standard 4-resistor difference topology, unity
* gain. Sign convention: v_int_raw is on the +IN side, v_int_out on the -IN
* side so e_sat = v_int_raw - v_int_out (so R_bc opposes integrator
* wind-up, not reinforces it).
R_diff1 v_int_out n_aw_diff_minus 100k
R_diff2 v_int_raw n_aw_diff_plus  100k
R_diff3 n_aw_diff_minus e_sat     100k
R_diff4 n_aw_diff_plus  0         100k
* Chopper-stabilized op-amp (Vos ~ 5 uV vs 2.5 mV for standard) for the
* back-calc diff amp. Tight Vos is essential here: e_sat's DC value is
* multiplied by 1/R_bc to become an integrator bias current, which the
* closed loop has to compensate with a corresponding steady-state demod
* error. With R_bc=R_INT (set below), the bias from a 2.5 mV Vos creates
* a ~33 K T error; chopper-class Vos cuts that to <0.1 K.
XU_aw_diff n_aw_diff_plus n_aw_diff_minus vcc vee e_sat {opamp_aw}

* Back-calc resistor: routes e_sat to n_int_minus (integrator's summing
* junction). When v_int_raw > clamp_hi, e_sat > 0 -> injects positive current
* into n_int_minus, which the integrator counter-integrates -> v_int_raw is
* pulled back toward v_int_out at rate ~1/(R_bc * C_INT). Symmetric on the
* low side.
*
* Sizing: R_bc = R_INT sets the back-calc tracking time constant to
* R_INT*C_INT = ~9.5 ms, much faster than the thermal pole (100 ms) so
* anti-windup acts well within the regulator's response window. The DC
* leakage (chopper-class Vos -> e_sat offset -> bias current at
* n_int_minus) is negligible: 5 uV * 1 = 5 uV demand error, < 0.1 K.
R_bc e_sat n_int_minus {r_int:.6g}

* === Variable-R gate drive: unity-gain SUBTRACTOR with V_p-tracking shift ===
* V_ctl = V_int_out - V_source_ref, with V_source_ref produced by the
* self-biased J_ref above. At cold start V_int_out=0, V_ctl = -V_source_ref
* ≈ V_p/2 (negative), placing J_var at moderate-overdrive triode (R_DS
* a few hundred Ω, |1-H| moderate, bridge drive moderate). As V_int_out
* winds negative, V_ctl drops more negative, V_GS drops toward V_p,
* R_DS grows, drive grows.
*
* Why subtractor (not summer with -V_offset source): the self-biased
* Q_ref naturally produces a POSITIVE V_source_ref (current through R_src
* lifts the source above ground). Using V_source_ref directly via a
* subtractor (V_ctl = V_int_out - V_source_ref) gets the correct negative
* V_offset_effective without an extra inverter stage.
*
* The two LS844 dies are matched: V_GS_ref ≈ V_GS_var when both carry
* the same I, so V_GS_var_OP = V_int_out_OP - V_source_ref_OP is the same
* gate voltage referenced to V_p of both dies. Across the LS844 V_p spec
* (1.0-3.5 V), V_int_OP shifts to compensate; the loop converges on
* whatever value gives R_DS_OP ≈ 333 Ω for the bridge null.
*
* Standard 4-resistor diff-amp topology:
*   V_+IN  = V_int_out · R_gnd/(R_a + R_gnd)
*   V_-IN  = V(+IN)   (virtual short)
*   KCL at -IN: (V_source_ref - V_-IN)/R_b = (V_-IN - V_ctl)/R_fb
*   ⇒ V_ctl = V_+IN · (1 + R_fb/R_b) - V_source_ref · R_fb/R_b
*           = (R_fb/R_a) · V_int_out - (R_fb/R_b) · V_source_ref     (when R_a=R_gnd, R_b=R_fb)
*           = V_int_out - V_source_ref                                (all four R = 100k)
{v_offset_block}
R_sum_a    v_int_out  n_sum_plus  100k
R_sum_gnd  n_sum_plus 0           100k
R_sum_b    n_ref_src  n_sum_minus 100k
R_sum_fb   v_ctl      n_sum_minus 100k
* AC bootstrap: inject v_drv_atten and n_ap_plus into +IN through 100k
* each via AC-coupling caps. With R_a=R_gnd=R_btd=R_bts=100k all to n_sum_plus,
* +IN AC voltage = (V_int_out + V_drv + V_ap) / 4. Op-amp gain of 2 from +IN
* gives V_ctl_AC = (V_int_out + V_drv + V_ap)/2 - V_source_ref_AC.
* For slow V_int (≈ DC) and slow V_source_ref (≈ DC), the AC term at f0
* is (V_drv + V_ap)/2 = V_avg_DS = V_S_AC + V_DS/2 → V_GS_AC = V_DS/2 →
* the V_DS-dependent term in R_DS cancels (see Lipshitz-Vanderkooy
* "JFETs as Voltage-Controlled Resistors" AES Journal). Brings H2 down
* from ~7-11% to ~3% target.
*
* C_btd = C_bts = 100 nF: at f0=1 kHz, |Z_C| = 1.6 kΩ << R_btd=100 kΩ → cap
* is effectively short at f0. HP cut-off = 1/(2π·100k·100n) ≈ 16 Hz, well
* below f0 so bootstrap is full strength at the operating frequency, and
* well above the loop bandwidth (~few Hz) so DC operation is unaffected.
* Through-hole ceramic / MLCC 100 nF X7R, ~$0.02 each.
C_btd      v_drv_atten n_btd_mid  100n IC=0
R_btd      n_btd_mid   n_sum_plus 100k
C_bts      n_ap_plus   n_bts_mid  100n IC=0
R_bts      n_bts_mid   n_sum_plus 100k
XU_sum     n_sum_plus n_sum_minus vcc vee v_ctl {opamp_sum}

{booster_lines}{boost_line}
* === 2N3904 ===
.model Q2N3904 NPN(IS=6.734f XTI=3 EG=1.11 VAF=74.03 BF=416.4 NE=1.259
+ ISE=6.734f IKF=66.78m XTB=1.5 BR=.7371 NC=2 ISC=0 IKR=0 RC=1
+ CJC=3.638p MJC=.3085 VJC=.75 FC=.5 CJE=4.493p MJE=.2593 VJE=.75
+ TR=239.5n TF=301.2p ITF=.4 VTF=4 XTF=2 RB=10)

.options reltol=1e-4 abstol=1p chgtol=1f
* Limit stored vectors to just the ones we wrdata -- without this,
* ngspice keeps every external + internal subcircuit node in RAM for the
* full transient. With manufacturer MOSFET subcircuits (DMP3098L/DMN3404L)
* this exhausts host memory at ~1.5 s of sim time.
.save v({v_osc_drive}) v({v_ap_drive}) v(node_A) v(node_B) v(n_diff) v(n_demout) v(v_ctl) v(v_int_out) v(T_node) v(r_fil) v(v_int_raw) v(e_sat)
.tran 10u {T_END} UIC

.control
run
wrdata {data_path.as_posix()} v({v_osc_drive}) v({v_ap_drive}) v(node_A) v(node_B) v(n_diff) v(n_demout) v(v_ctl) v(v_int_out) v(T_node) v(r_fil) v(v_int_raw) v(e_sat)
.endcontrol

.end
"""


def draw_filament_sample(rng):
    """Draw one Soviet-era VFD filament tolerance sample.
    Variation captured (uniform within band):
      - R_amb (cold resistance): +/-15% (manufacturing tungsten draw spread)
      - sigma_eps_A (radiative coupling): +/-20% (oxide layer / surface area)
      - C_th (thermal mass): +/-15% (filament length / diameter spread)
    The temperature exponent (1.2) is left fixed -- it is a tungsten material
    constant, not a manufacturing variable.
    """
    return {
        "k_r_amb":       float(rng.uniform(0.85, 1.15)),
        "k_sigma_eps_A": float(rng.uniform(0.80, 1.20)),
        "k_c_th":        float(rng.uniform(0.85, 1.15)),
    }


def run_one(label, v_preset=0.0, t_ramp=0.0, r_int_scale=1.0,
            p_boost=0.0, t_boost=0.0, mc=None):
    """Run one closed-loop sim with the given soft-start params, return dict of arrays."""
    if shutil.which("ngspice") is None:
        raise RuntimeError("ngspice not found")
    cir = WORK / f"closedloop_{label}.cir"
    dat = WORK / f"closedloop_{label}.data"
    cir.write_text(make_netlist(dat, v_preset=v_preset, t_ramp=t_ramp,
                                r_int_scale=r_int_scale,
                                p_boost=p_boost, t_boost=t_boost,
                                mc=mc))
    result = subprocess.run(["ngspice", "-b", cir.name], cwd=WORK,
                            capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr[-2000:]); print(result.stdout[-2000:])
        raise RuntimeError(f"ngspice failed for {label}")
    d = np.loadtxt(dat)
    # Free disk: remove the 800-MB .data file as soon as we have the array
    try:
        dat.unlink()
    except OSError:
        pass
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


def decimate_run(run, npts=2000):
    """Return a new run dict with each array linearly decimated to ~npts.
    Time axis is preserved exactly at the chosen indices (no interpolation,
    no smoothing). Trace overlays at 11" / 120 dpi can resolve at most
    ~1320 pixels horizontally, so 2000 samples is already supersampled."""
    n = len(run["t"])
    if n <= npts:
        return run
    idx = np.linspace(0, n - 1, npts).astype(np.int64)
    return {k: v[idx] for k, v in run.items()}


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
    parser.add_argument("--mode", choices=["single", "sweep_b", "sweep_a", "sweep_c", "sweep_d", "sweep_mc", "sweep_corners", "sweep_vos_corners", "sweep_tubes"], default="single")
    parser.add_argument("--v_preset", type=float, default=0.0)
    parser.add_argument("--t_ramp", type=float, default=0.0)
    parser.add_argument("--r_int_scale", type=float, default=1.0)
    parser.add_argument("--mc_n", type=int, default=24, help="MC trial count (sweep_mc)")
    parser.add_argument("--mc_workers", type=int, default=4, help="Parallel ngspice workers (sweep_mc)")
    parser.add_argument("--mc_seed", type=int, default=42, help="RNG seed (sweep_mc)")
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


    if args.mode == "sweep_c":
        # Bang-bang regime: V_preset close to 1.0 V (V_ctl pinned at -1.0 V
        # = max bridge drive during the ramp), sweep T_ramp.
        v_presets = [0.85, 0.95, 1.00]
        t_ramps   = [0.030, 0.060, 0.100, 0.150]
        rows = []
        runs_for_plot = {}
        for v_p in v_presets:
            for t_r in t_ramps:
                label = f"c_vp{int(v_p*100):03d}_tr{int(t_r*1e3):03d}"
                print(f"Running {label}: V_preset={v_p:.2f} V, T_ramp={t_r*1e3:.0f} ms", flush=True)
                r = run_one(label, v_preset=v_p, t_ramp=t_r)
                m = metrics(r)
                m["v_preset"], m["t_ramp"] = v_p, t_r
                rows.append(m)
                runs_for_plot[(v_p, t_r)] = r
                print(f"  T_peak={m['T_peak']:.1f}K  T_final={m['T_final']:.1f}K  "
                      f"t_95tar={m['t_95target']*1e3:.0f}ms  t_set5K={m['t_settle_5K']*1e3:.0f}ms  "
                      f"overshoot={m['T_overshoot']:.1f}K", flush=True)
        import csv
        keys = ["v_preset", "t_ramp", "T_peak", "T_final", "T_overshoot",
                "t_95target", "t_settle_5K", "t_settle_10K", "v_ctl_final", "R_final"]
        with open(HERE / "bang_bang_sweep.csv", "w") as fh:
            w = csv.DictWriter(fh, fieldnames=keys); w.writeheader()
            for r in rows: w.writerow({k: r[k] for k in keys})

        # Overlay plot: T(t) for V_preset=1.0 across all t_ramps
        fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
        ax_T, ax_ctl = axes
        for (v_p, t_r), r in sorted(runs_for_plot.items()):
            if abs(v_p - 1.0) < 0.01:
                ax_T.plot(r["t"]*1e3, r["T"], lw=1.0, label=f"V_preset=1.0 V, T_ramp={t_r*1e3:.0f} ms")
                ax_ctl.plot(r["t"]*1e3, r["v_ctl"], lw=0.4)
        ax_T.axhline(T_OP_TARGET, color="0.5", linestyle="--", label=f"target = {T_OP_TARGET:.0f} K")
        ax_T.set_ylabel("T [K]"); ax_T.grid(True, alpha=0.4); ax_T.legend(loc="lower right")
        ax_T.set_title("Bang-bang regime: T(t) vs T_ramp at V_preset = 1.0 V (full pinch-off)")
        ax_ctl.set_ylabel("V_ctl [V]"); ax_ctl.grid(True, alpha=0.4); ax_ctl.set_xlabel("Time [ms]")
        fig.tight_layout()
        fig.savefig(HERE / "bang_bang_sweep_traces.png", dpi=120); plt.close(fig)
        print(f"Wrote {HERE/'bang_bang_sweep_traces.png'}", flush=True)
        print(f"Wrote {HERE/'bang_bang_sweep.csv'}", flush=True)

    if args.mode == "sweep_d":
        # Pre-heat boost (option D): inject extra power into the thermal node
        # for the first t_boost seconds, on top of the standard loop drive.
        # Sweep P_boost. Use the soft-start sweet spot from sweep_b.
        v_p, t_r = 0.55, 0.100
        configs = [(0.0, 0.0),  # baseline
                   (0.020, 0.050),
                   (0.050, 0.050),
                   (0.020, 0.100),
                   (0.050, 0.100)]
        rows = []; runs_for_plot = {}
        for p_b, t_b in configs:
            label = f"d_pb{int(p_b*1000):03d}_tb{int(t_b*1e3):03d}" if p_b > 0 else "d_baseline"
            print(f"Running {label}: P_boost={p_b*1e3:.0f} mW, t_boost={t_b*1e3:.0f} ms", flush=True)
            r = run_one(label, v_preset=v_p, t_ramp=t_r, p_boost=p_b, t_boost=t_b)
            m = metrics(r)
            m["p_boost"], m["t_boost"] = p_b, t_b
            rows.append(m); runs_for_plot[(p_b, t_b)] = r
            print(f"  T_peak={m['T_peak']:.1f}K  T_final={m['T_final']:.1f}K  "
                  f"t_95tar={m['t_95target']*1e3:.0f}ms  t_set5K={m['t_settle_5K']*1e3:.0f}ms  "
                  f"overshoot={m['T_overshoot']:.1f}K", flush=True)
        import csv
        keys = ["p_boost", "t_boost", "T_peak", "T_final", "T_overshoot",
                "t_95target", "t_settle_5K", "t_settle_10K", "v_ctl_final", "R_final"]
        with open(HERE / "preheat_sweep.csv", "w") as fh:
            w = csv.DictWriter(fh, fieldnames=keys); w.writeheader()
            for r in rows: w.writerow({k: r[k] for k in keys})

        fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
        ax_T, ax_ctl = axes
        for (p_b, t_b), r in sorted(runs_for_plot.items()):
            label = "no pre-heat" if p_b == 0 else f"P_boost={p_b*1e3:.0f} mW, t_boost={t_b*1e3:.0f} ms"
            ax_T.plot(r["t"]*1e3, r["T"], lw=1.0, label=label)
            ax_ctl.plot(r["t"]*1e3, r["v_ctl"], lw=0.4)
        ax_T.axhline(T_OP_TARGET, color="0.5", linestyle="--", label=f"target = {T_OP_TARGET:.0f} K")
        ax_T.set_ylabel("T [K]"); ax_T.grid(True, alpha=0.4); ax_T.legend(loc="lower right")
        ax_T.set_title(f"Pre-heat boost: T(t) (V_preset={v_p:.2f} V, T_ramp={t_r*1e3:.0f} ms baseline)")
        ax_ctl.set_ylabel("V_ctl [V]"); ax_ctl.grid(True, alpha=0.4); ax_ctl.set_xlabel("Time [ms]")
        fig.tight_layout()
        fig.savefig(HERE / "preheat_sweep_traces.png", dpi=120); plt.close(fig)
        print(f"Wrote {HERE/'preheat_sweep_traces.png'}", flush=True)
        print(f"Wrote {HERE/'preheat_sweep.csv'}", flush=True)


    if args.mode == "sweep_mc":
        # Monte Carlo over Soviet-era VFD filament manufacturing variation,
        # using the option-A production config (R_INT scale=0.3 = 16.7 Hz
        # integrator zero) plus the soft-start (V_p=0.55 V, T_r=100 ms).
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import csv as _csv
        rng = np.random.default_rng(args.mc_seed)
        v_p, t_r, r_int_scale = 0.55, 0.100, 0.3
        N = args.mc_n
        samples = [draw_filament_sample(rng) for _ in range(N)]

        def one(i):
            s = samples[i]
            label = f"mc{i:03d}"
            r = run_one(label, v_preset=v_p, t_ramp=t_r,
                        r_int_scale=r_int_scale, mc=s)
            m = metrics(r)
            m.update({"trial": i, **s,
                      "T_target": T_AMB * (R_OP * 0.99 / (R_AMB * s["k_r_amb"])) ** (1.0 / 1.2)})
            # Decimate before returning so the full-res arrays are freed
            # in the worker thread instead of accumulating in the main loop.
            return m, decimate_run(r, npts=2000)

        rows = [None] * N
        runs = [None] * N
        print(f"Running MC: N={N}, workers={args.mc_workers}, seed={args.mc_seed}",
              flush=True)
        with ThreadPoolExecutor(max_workers=args.mc_workers) as ex:
            futures = {ex.submit(one, i): i for i in range(N)}
            for fut in as_completed(futures):
                i = futures[fut]
                m, r = fut.result()
                rows[i] = m; runs[i] = r
                print(f"  trial {i:03d}: k_r_amb={m['k_r_amb']:.3f} "
                      f"k_sigma={m['k_sigma_eps_A']:.3f} k_cth={m['k_c_th']:.3f}  "
                      f"-> T_final={m['T_final']:.0f}K  R_final={m['R_final']:.1f}ohm  "
                      f"T_peak={m['T_peak']:.0f}K  t_set5K={m['t_settle_5K']*1e3:.0f}ms  "
                      f"overshoot={m['T_overshoot']:+.0f}K", flush=True)

        # Save CSV
        keys = ["trial", "k_r_amb", "k_sigma_eps_A", "k_c_th", "T_target",
                "T_peak", "T_final", "T_overshoot",
                "t_95target", "t_settle_5K", "t_settle_10K",
                "v_ctl_final", "R_final"]
        with open(HERE / "filament_mc_sweep.csv", "w") as fh:
            w = _csv.DictWriter(fh, fieldnames=keys); w.writeheader()
            for r in rows: w.writerow({k: r[k] for k in keys})
        print(f"Wrote {HERE/'filament_mc_sweep.csv'}", flush=True)

        # Summary stats
        T_finals = np.array([r["T_final"] for r in rows])
        T_peaks  = np.array([r["T_peak"]  for r in rows])
        R_finals = np.array([r["R_final"] for r in rows])
        t_set    = np.array([r["t_settle_5K"] for r in rows]) * 1e3
        overshoots = np.array([r["T_overshoot"] for r in rows])
        print("\n=== MC summary ({} trials) ===".format(N))
        for name, arr, unit in [
            ("T_final",     T_finals,   "K"),
            ("T_peak",      T_peaks,    "K"),
            ("R_final",     R_finals,   "ohm"),
            ("t_settle_5K", t_set,      "ms"),
            ("overshoot",   overshoots, "K"),
        ]:
            print(f"  {name:14s}: mean={arr.mean():8.2f}  std={arr.std():6.2f}  "
                  f"min={arr.min():8.2f}  max={arr.max():8.2f}  [{unit}]")

        # Overlay traces
        fig, axes = plt.subplots(3, 1, figsize=(11, 10), sharex=True)
        ax_T, ax_R, ax_ctl = axes
        for r in runs:
            ax_T.plot(r["t"]*1e3, r["T"], lw=0.6, alpha=0.6)
            ax_R.plot(r["t"]*1e3, r["R"], lw=0.6, alpha=0.6)
            ax_ctl.plot(r["t"]*1e3, r["v_ctl"], lw=0.4, alpha=0.6)
        ax_T.axhline(T_OP_TARGET, color="0.3", linestyle="--", lw=0.8, label=f"target = {T_OP_TARGET:.0f} K")
        ax_T.set_ylabel("T [K]"); ax_T.grid(True, alpha=0.4); ax_T.legend(loc="lower right")
        ax_T.set_title(f"Filament Monte Carlo (N={N}): T(t) across +/-15% R_amb, +/-20% sigma*eps*A, +/-15% C_th")
        ax_R.axhline(R_OP, color="0.3", linestyle="--", lw=0.8, label=f"target = {R_OP:.0f} ohm")
        ax_R.set_ylabel("R [ohm]"); ax_R.grid(True, alpha=0.4); ax_R.legend(loc="lower right")
        ax_ctl.set_ylabel("V_ctl [V]"); ax_ctl.grid(True, alpha=0.4); ax_ctl.set_xlabel("Time [ms]")
        fig.tight_layout()
        fig.savefig(HERE / "filament_mc_traces.png", dpi=120); plt.close(fig)
        print(f"Wrote {HERE/'filament_mc_traces.png'}", flush=True)

        # Histograms
        fig, axes = plt.subplots(2, 2, figsize=(11, 8))
        for ax, arr, title, unit, ref in [
            (axes[0,0], T_finals,   "T_final",     "K",  T_OP_TARGET),
            (axes[0,1], T_peaks,    "T_peak",      "K",  T_OP_TARGET),
            (axes[1,0], R_finals,   "R_final",     "$\\Omega$", R_OP),
            (axes[1,1], t_set,      "t_settle_5K", "ms", None),
        ]:
            ax.hist(arr, bins=12, color="C0", edgecolor="0.2")
            ax.set_xlabel(f"{title} [{unit}]"); ax.set_ylabel("count")
            ax.set_title(f"{title}: mean {arr.mean():.1f}, sigma {arr.std():.1f} {unit}")
            if ref is not None:
                ax.axvline(ref, color="C3", linestyle="--", lw=1.0, label=f"target = {ref:g}")
                ax.legend(loc="upper right")
            ax.grid(True, alpha=0.3, axis="y")
        fig.suptitle(f"Filament MC histograms (N={N})")
        fig.tight_layout()
        fig.savefig(HERE / "filament_mc_histograms.png", dpi=120); plt.close(fig)
        print(f"Wrote {HERE/'filament_mc_histograms.png'}", flush=True)

        # Scatter of T_final vs k_r_amb (the dominant operating-point lever)
        fig, axes = plt.subplots(1, 2, figsize=(11, 5))
        ax_t, ax_r = axes
        kr = np.array([r["k_r_amb"] for r in rows])
        Tt = np.array([r["T_target"] for r in rows])
        ax_t.scatter(kr, T_finals, c="C0", label="T_final"); ax_t.scatter(kr, Tt, c="C3", marker="x", label="T_target (computed)")
        ax_t.set_xlabel("k_r_amb (R_amb tolerance factor)"); ax_t.set_ylabel("T [K]")
        ax_t.set_title("Steady-state T vs filament cold-resistance variation")
        ax_t.legend(); ax_t.grid(True, alpha=0.4); ax_t.axhline(T_OP_TARGET, color="0.5", lw=0.5, ls="--")
        ax_r.scatter(kr, t_set, c="C2"); ax_r.set_xlabel("k_r_amb")
        ax_r.set_ylabel("t_settle_5K [ms]")
        ax_r.set_title("Settling time vs filament cold-R variation")
        ax_r.grid(True, alpha=0.4)
        fig.tight_layout()
        fig.savefig(HERE / "filament_mc_scatter.png", dpi=120); plt.close(fig)
        print(f"Wrote {HERE/'filament_mc_scatter.png'}", flush=True)


    if args.mode == "sweep_corners":
        # Deterministic 2^3 corner sweep over the same three filament knobs
        # used by sweep_mc. Each parameter at its lo / hi extremum.
        # Guarantees coverage of the simultaneous-extreme cases that random
        # MC sampling can miss. 8 trials total.
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import csv as _csv
        import itertools
        v_p, t_r, r_int_scale = 0.55, 0.100, 0.3
        bands = {
            "k_r_amb":       (0.85, 1.15),
            "k_sigma_eps_A": (0.80, 1.20),
            "k_c_th":        (0.85, 1.15),
        }
        keys_in_order = list(bands.keys())
        corners = []
        for combo in itertools.product(*[bands[k] for k in keys_in_order]):
            corners.append({k: v for k, v in zip(keys_in_order, combo)})

        def label_for(s):
            return ("c"
                    + ("L" if s["k_r_amb"]       == bands["k_r_amb"][0]       else "H")
                    + ("L" if s["k_sigma_eps_A"] == bands["k_sigma_eps_A"][0] else "H")
                    + ("L" if s["k_c_th"]        == bands["k_c_th"][0]        else "H"))

        def one(i):
            s = corners[i]
            r = run_one(label_for(s), v_preset=v_p, t_ramp=t_r,
                        r_int_scale=r_int_scale, mc=s)
            m = metrics(r)
            m.update({"trial": i, "label": label_for(s), **s,
                      "T_target": T_AMB * (R_OP * 0.99 / (R_AMB * s["k_r_amb"])) ** (1.0 / 1.2)})
            # Decimate before returning to keep memory bounded.
            return m, decimate_run(r, npts=2000)

        rows = [None] * len(corners)
        runs = [None] * len(corners)
        print(f"Running 2^3 corner sweep: 8 trials, workers={args.mc_workers}",
              flush=True)
        with ThreadPoolExecutor(max_workers=args.mc_workers) as ex:
            futures = {ex.submit(one, i): i for i in range(len(corners))}
            for fut in as_completed(futures):
                i = futures[fut]
                m, r = fut.result()
                rows[i] = m; runs[i] = r
                print(f"  {m['label']}  k_r_amb={m['k_r_amb']:.2f}  "
                      f"k_sigma={m['k_sigma_eps_A']:.2f}  k_cth={m['k_c_th']:.2f}  "
                      f"-> T_final={m['T_final']:.0f}K  R_final={m['R_final']:.1f}ohm  "
                      f"T_peak={m['T_peak']:.0f}K  t_set5K={m['t_settle_5K']*1e3:.0f}ms  "
                      f"overshoot={m['T_overshoot']:+.0f}K", flush=True)

        # CSV
        keys = ["trial", "label", "k_r_amb", "k_sigma_eps_A", "k_c_th", "T_target",
                "T_peak", "T_final", "T_overshoot",
                "t_95target", "t_settle_5K", "t_settle_10K",
                "v_ctl_final", "R_final"]
        with open(HERE / "filament_corners_sweep.csv", "w") as fh:
            w = _csv.DictWriter(fh, fieldnames=keys); w.writeheader()
            for r in rows: w.writerow({k: r[k] for k in keys})
        print(f"Wrote {HERE/'filament_corners_sweep.csv'}", flush=True)

        # Overlay traces
        fig, axes = plt.subplots(3, 1, figsize=(11, 10), sharex=True)
        ax_T, ax_R, ax_ctl = axes
        for r, m in zip(runs, rows):
            ax_T.plot(r["t"]*1e3, r["T"], lw=0.9, label=m["label"])
            ax_R.plot(r["t"]*1e3, r["R"], lw=0.9)
            ax_ctl.plot(r["t"]*1e3, r["v_ctl"], lw=0.5)
        ax_T.axhline(T_OP_TARGET, color="0.3", linestyle="--", lw=0.8, label=f"target = {T_OP_TARGET:.0f} K")
        ax_T.set_ylabel("T [K]"); ax_T.grid(True, alpha=0.4); ax_T.legend(loc="lower right", ncol=3, fontsize=8)
        ax_T.set_title("2^3 corner sweep: T(t).  Label = (R_amb, sigma*eps*A, C_th), L=lo, H=hi")
        ax_R.axhline(R_OP, color="0.3", linestyle="--", lw=0.8, label=f"target = {R_OP:.0f} ohm")
        ax_R.set_ylabel("R [ohm]"); ax_R.grid(True, alpha=0.4)
        ax_ctl.set_ylabel("V_ctl [V]"); ax_ctl.grid(True, alpha=0.4); ax_ctl.set_xlabel("Time [ms]")
        fig.tight_layout()
        fig.savefig(HERE / "filament_corners_traces.png", dpi=120); plt.close(fig)
        print(f"Wrote {HERE/'filament_corners_traces.png'}", flush=True)


    if args.mode == "sweep_vos_corners":
        # 2^4 corner sweep over Vos of the four DC-path op-amps:
        # XU_ap (all-pass), XU_diff (subtractor), XU_dem (demodulator),
        # XU_int (integrator). XU_osc is held at nominal because its Vos
        # is AC-coupled out by the bridge. Each Vos at +/-1.5 mV
        # (TLV9104 datasheet worst case). Filament held at nominal.
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import csv as _csv
        import itertools
        v_p, t_r, r_int_scale = 0.55, 0.100, 0.3
        VOS_MAX = 1.5e-3
        keys_in_order = ["vos_ap", "vos_diff", "vos_dem", "vos_int"]
        corners = []
        for combo in itertools.product([-VOS_MAX, +VOS_MAX], repeat=4):
            corners.append({k: v for k, v in zip(keys_in_order, combo)})

        def label_for(s):
            sign = lambda v: "P" if v > 0 else "N"
            return ("v"
                    + sign(s["vos_ap"])
                    + sign(s["vos_diff"])
                    + sign(s["vos_dem"])
                    + sign(s["vos_int"]))

        def one(i):
            s = corners[i]
            r = run_one(label_for(s), v_preset=v_p, t_ramp=t_r,
                        r_int_scale=r_int_scale, mc=s)
            m = metrics(r)
            m.update({"trial": i, "label": label_for(s), **s})
            return m, decimate_run(r, npts=2000)

        rows = [None] * len(corners)
        runs = [None] * len(corners)
        print(f"Running 2^4 Vos corner sweep: 16 trials, workers={args.mc_workers}",
              flush=True)
        with ThreadPoolExecutor(max_workers=args.mc_workers) as ex:
            futures = {ex.submit(one, i): i for i in range(len(corners))}
            for fut in as_completed(futures):
                i = futures[fut]
                m, r = fut.result()
                rows[i] = m; runs[i] = r
                print(f"  {m['label']}  vos_ap={m['vos_ap']*1e3:+.2f}mV "
                      f"vos_diff={m['vos_diff']*1e3:+.2f}mV "
                      f"vos_dem={m['vos_dem']*1e3:+.2f}mV "
                      f"vos_int={m['vos_int']*1e3:+.2f}mV  "
                      f"-> T_final={m['T_final']:.0f}K  R_final={m['R_final']:.2f}ohm  "
                      f"t_set5K={m['t_settle_5K']*1e3:.0f}ms", flush=True)

        keys = ["trial", "label", "vos_ap", "vos_diff", "vos_dem", "vos_int",
                "T_peak", "T_final", "T_overshoot",
                "t_95target", "t_settle_5K", "t_settle_10K",
                "v_ctl_final", "R_final"]
        with open(HERE / "vos_corners_sweep.csv", "w") as fh:
            w = _csv.DictWriter(fh, fieldnames=keys); w.writeheader()
            for r in rows: w.writerow({k: r[k] for k in keys})
        print(f"Wrote {HERE/'vos_corners_sweep.csv'}", flush=True)

        # Overlay traces
        fig, axes = plt.subplots(3, 1, figsize=(11, 10), sharex=True)
        ax_T, ax_R, ax_ctl = axes
        for r, m in zip(runs, rows):
            ax_T.plot(r["t"]*1e3, r["T"], lw=0.7, label=m["label"], alpha=0.8)
            ax_R.plot(r["t"]*1e3, r["R"], lw=0.7, alpha=0.8)
            ax_ctl.plot(r["t"]*1e3, r["v_ctl"], lw=0.4, alpha=0.6)
        ax_T.axhline(T_OP_TARGET, color="0.3", linestyle="--", lw=0.8, label=f"target = {T_OP_TARGET:.0f} K")
        ax_T.set_ylabel("T [K]"); ax_T.grid(True, alpha=0.4); ax_T.legend(loc="lower right", ncol=4, fontsize=7)
        ax_T.set_title("Vos corner sweep (2^4): standard filament. Label = sign(vos_ap, diff, dem, int) at +/-1.5 mV")
        ax_R.axhline(R_OP, color="0.3", linestyle="--", lw=0.8, label=f"target = {R_OP:.0f} ohm")
        ax_R.set_ylabel("R [ohm]"); ax_R.grid(True, alpha=0.4)
        ax_ctl.set_ylabel("V_ctl [V]"); ax_ctl.grid(True, alpha=0.4); ax_ctl.set_xlabel("Time [ms]")
        fig.tight_layout()
        fig.savefig(HERE / "vos_corners_traces.png", dpi=120); plt.close(fig)
        print(f"Wrote {HERE/'vos_corners_traces.png'}", flush=True)

        # Summary
        T_finals = np.array([r["T_final"] for r in rows])
        R_finals = np.array([r["R_final"] for r in rows])
        t_set    = np.array([r["t_settle_5K"] for r in rows]) * 1e3
        print("\n=== Vos corner summary (16 trials, standard filament) ===")
        for name, arr, unit in [("T_final", T_finals, "K"),
                                ("R_final", R_finals, "ohm"),
                                ("t_settle_5K", t_set, "ms")]:
            print(f"  {name:14s}: mean={arr.mean():8.3f}  std={arr.std():6.3f}  "
                  f"min={arr.min():8.3f}  max={arr.max():8.3f}  [{unit}]")


    if args.mode == "sweep_tubes":
        # Run nominal closed-loop transient for each tube in TUBES.
        # Same loop config (option-A: r_int_scale=0.3, soft-start v_p=0.55,
        # t_r=100ms). Per-tube parameters set the filament thermal model and
        # bridge resistors; everything else (op-amps, Wien, JFET, PID) is
        # unchanged.
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import csv as _csv
        v_p, t_r = 0.55, 0.100
        names = list(TUBES.keys())

        def one(name):
            spec = TUBES[name]
            mc = {"r_amb": spec["r_amb"],
                  "sigma_eps_A": spec["sigma_eps_A"],
                  "c_th": spec["c_th"],
                  "r_top_ref": spec["r_top_ref"],
                  "r_bot_ref": spec["r_bot_ref"],
                  "r_sense":   spec["r_sense"]}
            if spec.get("booster"):
                mc["booster"] = True
            if spec.get("wien_alpha") is not None:
                mc["wien_alpha"] = spec["wien_alpha"]
            if spec.get("buf_fb1") is not None:
                mc["buf_fb1"] = spec["buf_fb1"]
            if spec.get("buf_fb_ap") is not None:
                mc["buf_fb_ap"] = spec["buf_fb_ap"]
            if spec.get("c_ap") is not None:
                mc["c_ap"] = spec["c_ap"]
            if spec.get("v_buf") is not None:
                mc["v_buf"] = spec["v_buf"]
            if spec.get("ce_buf"):
                mc["ce_buf"] = True
            if spec.get("mos_buf"):
                mc["mos_buf"] = True
            r = run_one(f"tube_{name}", v_preset=v_p, t_ramp=t_r,
                        r_int_scale=spec["r_int_scale"], mc=mc)
            m = metrics(r, target_T=spec["T_op"])
            m["tube"] = spec["name"]
            m["r_int_scale"] = spec["r_int_scale"]
            for k in ("R_op", "V_op", "T_op", "P_op", "r_amb",
                      "r_top_ref", "r_bot_ref", "r_sense"):
                m[k] = spec[k]
            # V_filament RMS over the last 50 ms (time-weighted -- ngspice
            # variable-timestep clusters samples non-uniformly, so a plain
            # np.mean is biased; trapezoidal integration is correct).
            t = r["t"]; v_fil = r["v_osc"] - r["v_A"]
            late = t > (t[-1] - 0.05)
            t_late = t[late]; v_late = v_fil[late]
            dur_late = t_late[-1] - t_late[0]
            m["V_fil_rms"] = float(np.sqrt(np.trapezoid(v_late**2, t_late) / dur_late))
            m["I_fil_rms"] = m["V_fil_rms"] / m["R_final"] if m["R_final"] else float("nan")
            return name, m, decimate_run(r, npts=2000)

        rows = {}
        runs = {}
        print(f"Running 4-tube nominal sim, workers={args.mc_workers}",
              flush=True)
        with ThreadPoolExecutor(max_workers=min(args.mc_workers, len(names))) as ex:
            futures = {ex.submit(one, n): n for n in names}
            for fut in as_completed(futures):
                name, m, r = fut.result()
                rows[name] = m; runs[name] = r
                print(f"  {m['tube']:9s}  R_target={m['R_op']:6.1f} target T={m['T_op']:.0f}K  "
                      f"r_int_scale={m['r_int_scale']:.2f}  "
                      f"-> T_final={m['T_final']:.0f}K  R_final={m['R_final']:.2f}ohm  "
                      f"V_fil={m['V_fil_rms']:.3f}V_RMS  I_fil={m['I_fil_rms']*1000:.1f}mA  "
                      f"t_set5K={m['t_settle_5K']*1e3:.0f}ms  overshoot={m['T_overshoot']:+.0f}K",
                      flush=True)

        keys = ["tube", "R_op", "V_op", "T_op", "P_op",
                "r_top_ref", "r_bot_ref", "r_sense", "r_amb", "r_int_scale",
                "T_peak", "T_final", "T_overshoot",
                "t_95target", "t_settle_5K", "t_settle_10K",
                "v_ctl_final", "R_final", "V_fil_rms", "I_fil_rms"]
        with open(HERE / "tubes_sweep.csv", "w") as fh:
            w = _csv.DictWriter(fh, fieldnames=keys); w.writeheader()
            for n in names: w.writerow({k: rows[n][k] for k in keys})
        print(f"Wrote {HERE/'tubes_sweep.csv'}", flush=True)

        # Overlay traces, one column per tube to avoid Y-axis crowding
        fig, axes = plt.subplots(4, len(names), figsize=(4*len(names), 11), sharex=True)
        for i, n in enumerate(names):
            r = runs[n]; m = rows[n]
            t_ms = r["t"] * 1e3
            v_fil = r["v_osc"] - r["v_A"]
            axes[0, i].plot(t_ms, r["T"], color="C3")
            axes[0, i].axhline(m["T_op"], color="0.4", ls="--", lw=0.8, label=f"target {m['T_op']:.0f} K")
            axes[0, i].set_title(f"{m['tube']}  ({m['R_op']:.0f} Ω, {m['V_op']:.1f} V_RMS)")
            axes[0, i].set_ylabel("T [K]" if i == 0 else "")
            axes[0, i].grid(True, alpha=0.3); axes[0, i].legend(loc="lower right", fontsize=8)
            axes[1, i].plot(t_ms, r["R"], color="C0")
            axes[1, i].axhline(m["R_op"], color="0.4", ls="--", lw=0.8, label=f"target {m['R_op']:.0f} Ω")
            axes[1, i].set_ylabel(r"R [$\Omega$]" if i == 0 else "")
            axes[1, i].grid(True, alpha=0.3); axes[1, i].legend(loc="lower right", fontsize=8)
            axes[2, i].plot(t_ms, v_fil, color="C2", lw=0.4)
            axes[2, i].set_ylabel("V_fil [V]" if i == 0 else "")
            axes[2, i].grid(True, alpha=0.3)
            axes[3, i].plot(t_ms, r["v_ctl"], color="C4", lw=0.5)
            axes[3, i].set_ylabel("V_ctl [V]" if i == 0 else "")
            axes[3, i].set_xlabel("Time [ms]")
            axes[3, i].grid(True, alpha=0.3)
        fig.suptitle("Four-tube nominal sweep (option-A loop, 10x ref-arm scaleup)")
        fig.tight_layout()
        fig.savefig(HERE / "tubes_sweep_traces.png", dpi=120); plt.close(fig)
        print(f"Wrote {HERE/'tubes_sweep_traces.png'}", flush=True)


if __name__ == "__main__":
    main()
