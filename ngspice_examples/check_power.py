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
def power_specs(use_booster: bool):
    specs = [
        # Wien limiter BJTs (2N3904, T0-92, 625 mW abs / ~300 mW derated)
        ("Q1_2N3904",  "(v(vcc) - v(fb))         * @Q1[ic]",        300),
        ("Q2_2N3904",  "(v(vcc) - v(v_osc))      * @Q2[ic]",        300),
        # Anti-windup diodes (1N4148, 500 mW abs)
        ("D_aw_hi_1N4148",  "(v(v_int_out) - v(v_clamp_hi)) * @D_aw_hi[id]",  500),
        ("D_aw_lo_1N4148",  "(v(v_clamp_lo) - v(v_int_out)) * @D_aw_lo[id]",  500),
        # JFET (2N5457, TO-92, 350 mW)
        ("J_var_2N5457",   "(v(v_drv_atten) - v(n_ap_plus)) * @J_var[id]" if use_booster
                           else "(v(v_osc) - v(n_ap_plus)) * @J_var[id]", 350),
    ]
    if use_booster:
        # Buffer 1 BJT pair (BC337/327, T0-92, 625 mW abs / ~300 mW derated).
        # NB: the BJT collectors connect to vcc_buf / vee_buf (the dedicated
        # buffer rail), not vcc / vee. Computing V_CE from v(vcc) instead of
        # v(vcc_buf) inflates dissipation by (V_CC - V_buf) * I_C.
        specs += [
            ("Q_o_npn_BC337", "(v(vcc_buf) - v(v_osc_drive)) * @Q_o_npn[ic]", 300),
            ("Q_o_pnp_BC327", "(v(v_osc_drive) - v(vee_buf)) * (-@Q_o_pnp[ic])", 300),
            # Buffer 2 BJT pair
            ("Q_a_npn_BC337", "(v(vcc_buf) - v(v_ap_drive)) * @Q_a_npn[ic]", 300),
            ("Q_a_pnp_BC327", "(v(v_ap_drive) - v(vee_buf)) * (-@Q_a_pnp[ic])", 300),
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
    if spec.get("v_buf") is not None: mc["v_buf"] = spec["v_buf"]

    work = m.WORK
    work.mkdir(exist_ok=True)
    cir = work / f"power_{tube_key}.cir"
    dat = work / f"power_{tube_key}.data"
    netlist = m.make_netlist(dat, v_preset=0.0, t_ramp=0.0,
                             r_int_scale=spec["r_int_scale"], mc=mc)

    specs = power_specs(use_booster)
    # Build .save and .control blocks: device-internal parameters (@Q1[ic]
    # etc.) are NOT saved as time-domain vectors by default -- without .save
    # they only retain their last-timestep scalar value, and any `let`
    # expression using them collapses to a snapshot.
    save_tokens = set()
    for _name, expr, _ in specs:
        for m_ in re.findall(r"@\w+\[\w+\]", expr):
            save_tokens.add(m_)
        for m_ in re.findall(r"v\(\w+\)", expr):
            save_tokens.add(m_)
    let_lines = "\n".join(f"let p_{name} = {expr}" for name, expr, _rating in specs)
    wrdata_args = " ".join(f"p_{name}" for name, _, _ in specs)
    new_control = f""".save {' '.join(sorted(save_tokens))}
.control
run
{let_lines}
wrdata {dat.as_posix()} {wrdata_args}
.endcontrol"""
    netlist = re.sub(r"\.control.*?\.endcontrol", new_control, netlist, flags=re.DOTALL)
    cir.write_text(netlist)

    res = subprocess.run(["ngspice", "-b", cir.name], cwd=work,
                         capture_output=True, text=True, timeout=600)
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
        out[name] = {
            "p_peak":     float(np.max(p_pos)),
            "p_ss_mean":  float(np.mean(p_pos[ss])),
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
