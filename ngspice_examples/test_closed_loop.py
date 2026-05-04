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

# Per-tube design table: filament + bridge resistors at the recommended
# 10x scaleup of the reference arm. Bridge balance:
#   R_target = R_sen * R_top_ref / R_bot_ref, with a deliberate 1% offset.
def _make_tube(name, R_op, V_op, T_op, R_sen, R_bot_ref,
               r_int_scale=0.3, booster=False,
               wien_alpha=None, c_ap=None, buf_fb1=None, buf_fb_ap=None, v_buf=None):
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
                buf_fb1=buf_fb1, buf_fb_ap=buf_fb_ap, v_buf=v_buf)

# r_int_scale per tube: option-A's 0.3 was tuned for the IV-3 bridge gain.
# Bridge sensitivity ~ V_drive*R_sen/(R_op+R_sen)^2 changes per tube, so
# R_INT must scale inversely with sensitivity to keep loop gain ~constant.
# Numbers below are derived from sensitivity ratios vs IV-3:
#   IV-3:  1.1 mV/Ω  ->  scale 0.30
#   IV-6: 10.6 mV/Ω  ->  scale 0.30 × 9.5 = 2.85
#   ILC1-1/7: 7.3    ->  scale 0.30 × 6.6 = 1.98
#   ILC1-1/8: 26.4   ->  scale 0.30 × 24  = 7.20
TUBES = {
    "iv3":     _make_tube("IV-3",     R_op=100, V_op=1.0, T_op=800, R_sen=10, R_bot_ref=100,  r_int_scale=0.3),
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
    "iv6":     _make_tube("IV-6",     R_op= 20, V_op=1.0, T_op=800, R_sen= 5, R_bot_ref=500,  r_int_scale=0.3, booster=True, buf_fb1=2.0e3, buf_fb_ap=3.0e3, v_buf=2.7),
    "ilc11_7": _make_tube("ILC1-1/7", R_op= 25, V_op=5.0, T_op=800, R_sen= 5, R_bot_ref=1000, r_int_scale=0.3, booster=True, buf_fb1=11.0e3, buf_fb_ap=12.0e3, v_buf=7.5),
    "ilc11_8": _make_tube("ILC1-1/8", R_op=  8, V_op=1.2, T_op=800, R_sen= 2, R_bot_ref=200,  r_int_scale=0.3, booster=True, buf_fb1=2.5e3, buf_fb_ap=3.5e3, v_buf=3.0),
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
C_AP = 100e-9

# Loop integrator (~5 Hz integrator zero frequency at default scale)
# These are baselines; sweep_a scales R_INT and R_PID together (Kp constant)
# to vary loop bandwidth while keeping the same PID shape.
R_INT_BASE = 100e3
C_INT_BASE = 1.0 / (2 * np.pi * 5.0 * R_INT_BASE)
R_PID_BASE = 1e6
C_PID_BASE = 1e-9
C_HF_BASE  = 10e-9   # bumped from 1.6n to push HF pole from 332 Hz to 53 Hz
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
OPAMP = ("uopamp_lvl2 Avol=10meg GBW=4.5meg Rin=100g Rout=10 "
         "Iq=600u Ilimit=1 Vrail=100m Vmax=40 Vos=2.5m")
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
    jfet_vp = mc.get("jfet_vp", -2.5)
    jfet_beta = mc.get("jfet_beta", 1.0e-3)
    # Per-tube buffer rail, defaults to VCC for backward compatibility.
    v_buf = mc.get("v_buf", VCC)
    def _opamp(key, default=None):
        v = mc.get(key, default if default is not None else vos_v)
        return (f"uopamp_lvl2 Avol=10meg GBW=4.5meg Rin=100g Rout=10 "
                f"Iq=600u Ilimit=1 Vrail=100m Vmax=40 Vos={v:.6e}")
    opamp = _opamp("vos_v")          # back-compat default for any unmarked usage
    opamp_osc  = _opamp("vos_osc")
    opamp_ap   = _opamp("vos_ap")
    opamp_diff = _opamp("vos_diff")
    opamp_dem  = _opamp("vos_dem", default=vos_chopper)
    opamp_int  = _opamp("vos_int", default=vos_chopper)
    opamp_cmp  = _opamp("vos_cmp")
    opamp_buf0 = _opamp("vos_buf0")
    opamp_bufo = _opamp("vos_buf_osc")
    opamp_bufa = _opamp("vos_buf_ap")
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
    # Comparator V+/V- swap depends on Buffer 2 polarity:
    #   booster on  -> Buffer 2 inverting -> swap so demod sees -sign(V_osc)
    #   booster off -> Buffer 2 doesn't exist -> keep natural sign(V_osc)
    cmp_inputs = "0 v_osc" if use_booster else "v_osc 0"
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
    booster_lines = ""
    if use_booster:
        booster_lines = f"""
* Buffer 0: passive attenuator on V_osc, then op-amp follower to feed JFET
* with low-Z attenuated drive. R_atten_top:R_atten_bot = 56k:9.1k -> k_atten
* ~ 7.15, so V_drv_atten ~= V_osc / 7.15 (peak ~0.5 V at V_osc 3.6 V_pk),
* keeping V_DS in the JFET's linear region.
R_atten_top  v_osc          v_atten_input 56k
R_atten_bot  v_atten_input  0             9.1k
XU_buf0      v_atten_input  v_drv_atten   vcc vee v_drv_atten {opamp_buf0}

* Buffer 1: V_drv_atten -> V_osc_drive (gain k_buf, class-AB BC337/BC327)
* Feedback divider R_buf1_fb1:R_buf1_fb2 sets per-tube k_buf
XU_buf_osc   v_drv_atten n_buf_osc_fb vcc_buf vee_buf n_buf_osc_out {opamp_bufo}
R_buf1_fb1   v_osc_drive n_buf_osc_fb {buf_fb1:.6g}
R_buf1_fb2   n_buf_osc_fb 0           1k
R_obb_top vcc_buf q_o_bn 680
D_obb_top q_o_bn n_buf_osc_out Dbias
D_obb_bot n_buf_osc_out q_o_bp Dbias
R_obb_bot q_o_bp vee_buf 680
Q_o_npn  vcc_buf q_o_bn v_osc_drive QBC337
Q_o_pnp  vee_buf q_o_bp v_osc_drive QBC327

* Buffer 2: V_ap -> V_ap_drive, INVERTING amp (gain -k_buf_ap).
* Inverting topology so V_top and V_bot are nearly anti-phase, giving
* V_diff = V_top - V_bot = V_drv_atten*k_buf*(1 + H) where H is the
* all-pass response. |1+H| = 2/sqrt(1+(wRC)^2) is large at low wRC
* (JFET in linear region, V_GS far from V_to) -- the OPPOSITE regime
* from the old V_diff = V_drv_atten*k_buf*(1-H) topology, which needed
* high wRC (JFET near pinch-off) for efficient operation. New topology
* reaches good class-AB efficiency without entering the JFET-rectification
* regime.
XU_buf_ap    0           n_buf_ap_minus  vcc_buf vee_buf n_buf_ap_out {opamp_bufa}
R_buf2_in    v_ap        n_buf_ap_minus  1k
R_buf2_fb    v_ap_drive  n_buf_ap_minus  {buf_fb_ap:.6g}
R_abb_top vcc_buf q_a_bn 680
D_abb_top q_a_bn n_buf_ap_out Dbias
D_abb_bot n_buf_ap_out q_a_bp Dbias
R_abb_bot q_a_bp vee_buf 680
Q_a_npn  vcc_buf q_a_bn v_ap_drive QBC337
Q_a_pnp  vee_buf q_a_bp v_ap_drive QBC327
.model Dbias  D(IS=2.52n N=1.752 RS=0.568 BV=80 IBV=0.1m CJO=4p)
.model QBC337 NPN(IS=1e-14 BF=300 BR=10 RB=10 RC=0.5 RE=0.1 IKF=0.8
+ CJC=11p CJE=20p VAF=100)
.model QBC327 PNP(IS=1e-14 BF=300 BR=10 RB=10 RC=0.5 RE=0.1 IKF=0.8
+ CJC=11p CJE=20p VAF=100)
"""
    # Optional pre-heat boost line (added at end of netlist body)
    boost_line = ""
    if p_boost > 0 and t_boost > 0:
        boost_line = (
            f"\n* Option D: pre-heat boost {p_boost*1e3:.1f} mW for {t_boost*1e3:.0f} ms\n"
            f"V_boost_en vboost_en 0 PWL(0 1 {max(t_boost-1e-6,0):.6e} 1 {t_boost:.6e} 0 1 0)\n"
            f"B_boost 0 T_node I = {p_boost:.6e} * (V(vboost_en) > 0.5)\n"
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
* Separate buffer rail for the class-AB BJT collectors. Sized per tube
* to V_op_pk + ~1.5V headroom so the BJTs run with V_CE close to V_BE
* during conduction -- avoids burning P_filament*((VCC/V_op_pk) - 1)
* Watts in the BJT pair, which is the fundamental class-B inefficiency
* when V_CC >> V_pk. Falls back to VCC/VEE if not specified.
Vcc_buf vcc_buf 0  {v_buf:.4g}
Vee_buf vee_buf 0 -{v_buf:.4g}

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
* JFET R_DS in series from V_drv_atten (or V_osc) to V+ (cap-shunted node).
* The gate is driven directly by the inverter op-amp's output (v_ctl), so
* gate-channel forward-conduction current during overshoots is sunk by
* the inverter's output stage with no DC offset on V_GS. The bootstrap AC
* signal is summed into the inverter's non-inverting input -- see the
* inverter section below.
J_var {v_osc_jfet} v_ctl n_ap_plus J2N5457
C_ap n_ap_plus 0 {c_ap_v:.6e}    IC=0
XU_ap n_ap_plus n_ap_minus vcc vee v_ap {opamp_ap}
.model J2N5457 NJF(Vto={jfet_vp:.4f} Beta={jfet_beta:.4e} Lambda=0)

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
B_fil   v_top v_bot I = (V(v_top) - V(v_bot)) / (R_amb * (V(T_node)/T_amb)^fil_exp)
B_pelec 0 T_node    I = (V(v_top)-V(v_bot))*(V(v_top)-V(v_bot)) / (R_amb * (V(T_node)/T_amb)^fil_exp)
B_prad  T_node 0    I = sigma_eps_A * (V(T_node)^4 - T_amb^4)
C_th    T_node 0    {{C_th}} IC={T_AMB}
B_R     r_fil 0     V = R_amb * (V(T_node)/T_amb)^fil_exp
.ends filament

* === AC Wheatstone bridge ===
* Filament arm: V_osc -> filament(thermal) -> node_A -> R_sense -> V_ap
X_filament {v_osc_drive} node_A T_node r_fil filament
R_sen node_A {v_ap_drive} {r_sense_v:.6g}
* Reference arm: V_osc -> R_top_ref -> node_B -> R_bot_ref -> V_ap.
* Bridge balance R_top_ref / R_bot_ref = R_op / R_sen targets R_op exactly.
R_top_ref {v_osc_drive} node_B {r_top_ref:.6g}
R_bot_ref node_B {v_ap_drive}  {r_bot_ref:.6g}

* === Difference amp (1-op-amp subtractor, gain 1) ===
R_a1 node_A n_diff_minus {r_a1:.6g}
R_a2 n_diff_minus n_diff {r_a2:.6g}
R_b1 node_B n_diff_plus {r_b1:.6g}
R_b2 n_diff_plus 0 {r_b2:.6g}
XU_diff n_diff_plus n_diff_minus vcc vee n_diff {opamp_diff}

* === Comparator (behavioural sign of V_osc) ===
* Comparator: open-loop op-amp (one channel of the second TLV9154 quad).
* V+/V- swapped from the natural "sign of V_osc" connection ONLY when the
* booster is on -- the booster's inverting Buffer 2 flips the loop's
* polarity, so we have to flip the demodulator reference to compensate.
* Without the booster (IV-3), Buffer 2 doesn't exist and Buffer-1's
* non-inverting output preserves the old polarity, so the comparator
* must stay unswapped.
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
R_intfb  n_int_pidp v_int_out {r_pid:.6g}
* Realistic startup: cap begins uncharged (no IC). Loop self-starts from
* the intentional 1% bridge mismatch above + Vos drift in the demod and
* integrator op-amps.
C_intfb  n_int_minus n_int_pidp {c_int:.6e}  IC=0
* HF rolloff cap: in parallel with R_PID to limit HF gain and suppress
* the f0 ripple from V_demod that the D term would otherwise pump
* through to V_ctl.
C_hf     n_int_pidp v_int_out {c_hf:.6e}     IC=0
XU_int 0 n_int_minus vcc vee v_int_out {opamp_int}

* Anti-windup: real-circuit clamp on V_int_out using two silicon diodes
* referenced to precision voltage sources. Sized for the 2N5457 V_to=-2.5V
* operating range: V_int_out ~= -V_ctl, so the loop needs V_int_out in
* [0, 2.5] to span the JFET's useful R_DS range. Clamp range chosen as
* [-0.3, +2.5] V (small negative margin keeps the gate reverse-biased).
* The diodes forward-conduct when V_int_out exceeds +2.5 V (Vf ~0.7V over
* the +1.8V reference) or goes below -0.3 V (Vf ~0.7V under the +0.3V
* reference). In production the precision references would be Zeners +
* dividers off the +/-9 V rails, or band-gap parts (TL431, REF03 etc.).
V_clamp_hi v_clamp_hi 0  1.8
V_clamp_lo v_clamp_lo 0  0.3
D_aw_hi    v_int_out  v_clamp_hi Dclamp
D_aw_lo    v_clamp_lo v_int_out  Dclamp
.model Dclamp D(Is=2.52n Rs=0.568 N=1.752 Cjo=4p M=0.4 tt=20n)

* Inverter + JFET-gate bootstrap: V_ctl is the op-amp output that drives
* the JFET gate directly. At DC, n_inv_plus is held to 0 by R_btp, so
* V_ctl = -V_int_out (existing inverter behaviour). At AC the bootstrap
* path R_btd/C_btd and R_bts/C_bts inject (V_drain + V_source) into
* n_inv_plus through R_btp to ground; the op-amp's non-inverting summer
* arrangement gives V_ctl_AC = 2*V(n_inv_plus) = 2*R_btp/(2*R_b + R_btp) *
* (V_d + V_s). With R_b = 100k, R_btp = 18k that's V_ctl_AC = 0.265*(V_d+V_s),
* close to the optimal alpha ~ 0.275 for our topology where the C_ap
* divider gives V_source ~ 0.38*V_drain at f0. Cancels the V_DS-dependent
* term in 1/R_DS = 2*beta*(V_GS - V_to - V_DS/2), reducing JFET-induced
* H2 at v_ap from ~6% to ~3%. The C_b caps block DC so the inverter still
* cleanly tracks V_int_out.
R_inv1 v_int_out  n_inv_minus 100k
R_inv2 n_inv_minus v_ctl       100k
R_btd  {v_osc_jfet} n_btd_mid  100k
C_btd  n_btd_mid   n_inv_plus  10u IC=0
R_bts  n_ap_plus   n_bts_mid   100k
C_bts  n_bts_mid   n_inv_plus  10u IC=0
R_btp  n_inv_plus  0           18k
XU_inv n_inv_plus  n_inv_minus vcc vee v_ctl {opamp}

{booster_lines}{boost_line}
* === 2N3904 ===
.model Q2N3904 NPN(IS=6.734f XTI=3 EG=1.11 VAF=74.03 BF=416.4 NE=1.259
+ ISE=6.734f IKF=66.78m XTB=1.5 BR=.7371 NC=2 ISC=0 IKR=0 RC=1
+ CJC=3.638p MJC=.3085 VJC=.75 FC=.5 CJE=4.493p MJE=.2593 VJE=.75
+ TR=239.5n TF=301.2p ITF=.4 VTF=4 XTF=2 RB=10)

.options reltol=1e-4 abstol=1p chgtol=1f
.tran 10u {T_END} UIC

.control
run
wrdata {data_path.as_posix()} v({v_osc_drive}) v({v_ap_drive}) v(node_A) v(node_B) v(n_diff) v(n_demout) v(v_ctl) v(v_int_out) v(T_node) v(r_fil)
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
            r = run_one(f"tube_{name}", v_preset=v_p, t_ramp=t_r,
                        r_int_scale=spec["r_int_scale"], mc=mc)
            m = metrics(r, target_T=spec["T_op"])
            m["tube"] = spec["name"]
            m["r_int_scale"] = spec["r_int_scale"]
            for k in ("R_op", "V_op", "T_op", "P_op", "r_amb",
                      "r_top_ref", "r_bot_ref", "r_sense"):
                m[k] = spec[k]
            # V_filament RMS over the last 50 ms
            t = r["t"]; v_fil = r["v_osc"] - r["v_A"]
            late = t > (t[-1] - 0.05)
            m["V_fil_rms"] = float(np.sqrt(np.mean(v_fil[late]**2)))
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
