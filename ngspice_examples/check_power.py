"""Power-dissipation diagnostic: scan each tube for hotspots.

For each tube, generates a netlist that computes power waveforms for
the components most likely to overheat:

    BC337/BC327 BJTs in Buffer 1 / Buffer 2 (Q_o_npn/pnp, Q_a_npn/pnp)
    2N3904 BJTs in Wien limiter (Q1, Q2)
    1N4148 anti-windup diodes (D_aw_hi, D_aw_lo)
    2N5457 JFET (J_var)
    Filament + R_sense (intentional dissipation, included for context)

Reports peak instantaneous power and steady-state average per device,
flagged against typical TO-92 derated ratings (~300 mW continuous).
"""
from __future__ import annotations
import sys
import re
import subprocess
from pathlib import Path
import numpy as np

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import test_closed_loop as m


# Components to monitor with (label, ngspice power expression, package rating mW)
def power_specs(use_booster: bool, ce_buf: bool = False, mos_buf: bool = False):
    specs = [
        # Wien limiter BJTs (MMBT3904, SOT-23, 225 mW abs / ~110 mW derated at 70 C)
        ("Q1_MMBT3904",  "(v(vcc) - v(fb))         * @Q1[ic]",        110),
        ("Q2_MMBT3904",  "(v(vcc) - v(v_osc))      * @Q2[ic]",        110),
        # Anti-windup diodes (1N4148W, SOD-123, 200 mW abs / ~100 mW derated)
        ("D_aw_hi_1N4148W",  "(v(v_int_out) - v(v_clamp_hi)) * @D_aw_hi[id]",  100),
        ("D_aw_lo_1N4148W",  "(v(v_clamp_lo) - v(v_int_out)) * @D_aw_lo[id]",  100),
        # JFET (MMBFJ113, SOT-23, 225 mW abs / ~110 mW derated). Picked
        # over MMBF5457 because its tighter V_GS(off) range (-0.5 to -3 V
        # vs -0.5 to -6 V) fits inside the loop's clamp-bounded operating
        # range without trim-time binning.
        ("J_var_MMBFJ113",   "(v(v_drv_atten) - v(n_ap_plus)) * @J_var[id]" if use_booster
                             else "(v(v_osc) - v(n_ap_plus)) * @J_var[id]", 110),
    ]
    if use_booster:
        # Buffer 1/2 class-AB BJT pair (BC817/BC807, SOT-23, ~120 mW derated).
        # CC topology: NPN at top (collector at vcc_buf, V_CE = vcc_buf - v_out),
        #              PNP at bottom (collector at vee_buf, V_EC = v_out - vee_buf).
        # CE topology: PNP at top (collector at v_out, emitter at vcc_buf,
        #                          V_EC = vcc_buf - v_out),
        #              NPN at bottom (collector at v_out, emitter at vee_buf,
        #                             V_CE = v_out - vee_buf).
        # Voltage formulas swap between the two topologies.
        if mos_buf:
            # MOSFET I_D sign convention in ngspice:
            #   NMOS: I_D > 0 when current flows in at drain (D>S)
            #   PMOS: I_D > 0 when current flows in at source (S>D, i.e. conducting)
            # P = V_DS * I_D for NMOS, P = V_SD * I_D for PMOS (both magnitudes positive when conducting).
            # DMN3404L (NMOS) / DMP3098L (PMOS), Diodes Inc., SOT-23.
            # ~1 W abs at TA=25 C, ~640 mW derated at TA=70 C; both confirmed
            # in single-pulse SOA for the 30 W / 1 us startup spike.
            # MOSFET drain currents come from current-sense V sources placed
            # in series with each device's source (the manufacturer subcircuit
            # doesn't expose internal device parameters to @xname.m1[id] in
            # this ngspice build, so we sense externally).
            specs += [
                ("M_o_nmos_DMN3404L",  "(v(v_osc_drive) - v(vee_buf)) * i(V_im_o_nmos)", 640),
                ("M_o_pmos_DMP3098L", "(v(vcc_buf) - v(v_osc_drive)) * i(V_im_o_pmos)", 640),
                ("M_a_nmos_DMN3404L",  "(v(v_ap_drive) - v(vee_buf)) * i(V_im_a_nmos)", 640),
                ("M_a_pmos_DMP3098L", "(v(vcc_buf) - v(v_ap_drive)) * i(V_im_a_pmos)", 640),
            ]
        elif ce_buf:
            specs += [
                ("Q_o_npn_BC817", "(v(v_osc_drive) - v(vee_buf)) * @Q_o_npn[ic]", 120),
                ("Q_o_pnp_BC807", "(v(vcc_buf) - v(v_osc_drive)) * (-@Q_o_pnp[ic])", 120),
                ("Q_a_npn_BC817", "(v(v_ap_drive) - v(vee_buf)) * @Q_a_npn[ic]", 120),
                ("Q_a_pnp_BC807", "(v(vcc_buf) - v(v_ap_drive)) * (-@Q_a_pnp[ic])", 120),
            ]
        else:
            # CC class-AB pair: the only tube using this is ILC1-1/7 (V_op = 5
            # V_RMS / 30 ohm = 1 W out, ss_avg ~ 100 mW per BJT). SOT-23 BC817/
            # BC807 (~120 mW derated) puts ss_avg at ~85% of rating with
            # half-watt sub-millisecond peaks; tight enough that we promote the
            # CC pair to SOT-89 BC868/BC868PA (~750 mW derated).
            specs += [
                ("Q_o_npn_BC868",   "(v(vcc_buf) - v(v_osc_drive)) * @Q_o_npn[ic]", 750),
                ("Q_o_pnp_BC868PA", "(v(v_osc_drive) - v(vee_buf)) * (-@Q_o_pnp[ic])", 750),
                ("Q_a_npn_BC868",   "(v(vcc_buf) - v(v_ap_drive)) * @Q_a_npn[ic]", 750),
                ("Q_a_pnp_BC868PA", "(v(v_ap_drive) - v(vee_buf)) * (-@Q_a_pnp[ic])", 750),
            ]
    return specs


def run_for_power(tube_key: str):
    spec = m.TUBES[tube_key]
    use_booster = bool(spec.get("booster", False))
    mc = {k: spec[k] for k in ("r_amb", "sigma_eps_A", "c_th",
                               "r_top_ref", "r_bot_ref", "r_sense")}
    if spec.get("booster"): mc["booster"] = True
    if spec.get("c_ap") is not None: mc["c_ap"] = spec["c_ap"]
    if spec.get("buf_fb1") is not None: mc["buf_fb1"] = spec["buf_fb1"]
    if spec.get("buf_fb_ap") is not None: mc["buf_fb_ap"] = spec["buf_fb_ap"]
    if spec.get("v_buf") is not None: mc["v_buf"] = spec["v_buf"]
    if spec.get("ce_buf"): mc["ce_buf"] = True
    if spec.get("mos_buf"): mc["mos_buf"] = True
    if spec.get("tank_l") is not None: mc["tank_l"] = spec["tank_l"]
    if spec.get("tank_c") is not None: mc["tank_c"] = spec["tank_c"]
    if spec.get("bias_diode"): mc["bias_diode"] = spec["bias_diode"]
    if spec.get("bias_zener_v") is not None: mc["bias_zener_v"] = spec["bias_zener_v"]
    if spec.get("buf_comp_pf") is not None: mc["buf_comp_pf"] = spec["buf_comp_pf"]
    if spec.get("t_rail_ramp") is not None: mc["t_rail_ramp"] = spec["t_rail_ramp"]
    if spec.get("servo_bias"): mc["servo_bias"] = True
    if spec.get("servo_iq_target") is not None: mc["servo_iq_target"] = spec["servo_iq_target"]
    if spec.get("servo_r_sense") is not None: mc["servo_r_sense"] = spec["servo_r_sense"]
    # R_op / V_op needed by servo bias to compute V_ref (signal-dependent).
    mc["R_op"] = spec["R_op"]
    mc["V_op"] = spec["V_op"]

    work = m.WORK
    work.mkdir(exist_ok=True)
    cir = work / f"power_{tube_key}.cir"
    dat = work / f"power_{tube_key}.data"
    netlist = m.make_netlist(dat, v_preset=0.0, t_ramp=0.0,
                             r_int_scale=spec["r_int_scale"], mc=mc)

    specs = power_specs(use_booster, ce_buf=spec.get("ce_buf", False),
                        mos_buf=spec.get("mos_buf", False))
    # Build .save and .control blocks. Two subtleties:
    # (1) device-internal parameters (@Q1[ic] etc.) are NOT saved as time-
    #     domain vectors by default -- need explicit .save.
    # (2) Even WITH .save, an @-param used inline in a vector arithmetic
    #     `let` (e.g. `let p = v(x) * @Q1[ic]`) collapses to its last-
    #     timestep scalar value. Workaround: bind each @-param to its own
    #     let first (`let ic_q1 = @Q1[ic]`) and reference that let in the
    #     power expression.
    save_tokens = set()
    at_token_to_let = {}   # @Q1[ic] -> ic_q1, also i(Vname) -> i_vname
    for _name, expr, _ in specs:
        for tok in re.findall(r"@\w+\[\w+\]", expr):
            save_tokens.add(tok)
            # Build a safe let-name from the @-token (strip @, [], make underscore)
            let_name = "x_" + tok.replace("@", "").replace("[", "_").replace("]", "")
            at_token_to_let[tok] = let_name
        for tok in re.findall(r"i\(\w+\)", expr):
            # Current through a V source: must be explicitly .saved AND bound
            # to a let to avoid scalar collapse in arithmetic. Without .save,
            # ngspice in batch mode reports the vector has zero length.
            save_tokens.add(tok)
            let_name = "x_" + tok.replace("i(", "i_").replace(")", "")
            at_token_to_let[tok] = let_name
        for tok in re.findall(r"v\(\w+\)", expr):
            save_tokens.add(tok)
    bind_lines = "\n".join(f"let {let_name} = {tok}"
                           for tok, let_name in sorted(at_token_to_let.items()))
    let_lines_list = []
    for name, expr, _rating in specs:
        # Substitute each @-token / i(...) with its bound let-name
        e = expr
        for tok, let_name in at_token_to_let.items():
            e = e.replace(tok, let_name)
        let_lines_list.append(f"let p_{name} = {e}")
    let_lines = "\n".join(let_lines_list)
    wrdata_args = " ".join(f"p_{name}" for name, _, _ in specs)
    new_control = f""".save {' '.join(sorted(save_tokens))}
.control
run
{bind_lines}
{let_lines}
wrdata {dat.as_posix()} {wrdata_args}
.endcontrol"""
    netlist = re.sub(r"\.control.*?\.endcontrol", new_control, netlist, flags=re.DOTALL)
    cir.write_text(netlist)

    res = subprocess.run(["ngspice", "-b", cir.name], cwd=work,
                         capture_output=True, text=True, timeout=2400)
    if res.returncode != 0:
        print(res.stderr[-2000:])
        raise RuntimeError(f"ngspice failed for {tube_key}")
    d = np.loadtxt(dat)
    t = d[:, 0]
    out = {}
    for i, (name, _expr, rating) in enumerate(specs):
        p = d[:, 2*i + 1]
        # Take only positive power (BJT can be reverse-biased briefly with neg P)
        p_pos = np.where(p > 0, p, 0.0)
        # Steady-state window: last 100 ms
        ss = t > t[-1] - 0.1
        # Time-weighted mean -- np.mean is biased on ngspice variable-timestep
        # data because samples cluster at high-dV/dt regions. Trapezoidal
        # integration weights each sample by its dt and gives the true average.
        t_ss = t[ss]
        ss_dur = t_ss[-1] - t_ss[0]
        out[name] = {
            "p_peak":     float(np.max(p_pos)),
            "p_ss_mean":  float(np.trapezoid(p_pos[ss], t_ss) / ss_dur),
            "p_ss_max":   float(np.max(p_pos[ss])),
            "rating":     rating,
        }
    try:
        dat.unlink()
    except OSError:
        pass
    return out


def main():
    tubes = sys.argv[1:] or ["iv3", "iv6", "ilc11_7", "ilc11_8"]
    for tube in tubes:
        if tube not in m.TUBES:
            print(f"Unknown tube {tube}"); continue
        print(f"\n=== {m.TUBES[tube]['name']} (booster={'on' if m.TUBES[tube].get('booster') else 'off'}) ===")
        results = run_for_power(tube)
        print(f"{'Device':<22s} {'P_peak':>10s} {'P_ss_max':>10s} {'P_ss_avg':>10s}  Rating  Status")
        print("-" * 80)
        for name, r in results.items():
            peak_pct = 100 * r["p_peak"] / (r["rating"] * 1e-3)
            ss_pct   = 100 * r["p_ss_mean"] / (r["rating"] * 1e-3)
            status = ""
            if peak_pct > 100:
                status = " *** PEAK over rating ***"
            elif ss_pct > 100:
                status = " *** SS over rating ***"
            elif ss_pct > 50:
                status = " (steady-state >50% rating)"
            elif peak_pct > 100:
                status = " (peak >100% rating)"
            print(f"{name:<22s} {r['p_peak']*1e3:>8.1f}mW {r['p_ss_max']*1e3:>8.1f}mW "
                  f"{r['p_ss_mean']*1e3:>8.1f}mW  {r['rating']:>4d}mW{status}")


if __name__ == "__main__":
    main()
