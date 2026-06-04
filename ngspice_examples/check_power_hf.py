"""HF-mode power probe: measure per-device dissipation at f0=100 kHz with
fixed-R filament and the transformer in circuit (reflecting reality of
the design once xfmr_n is set on a tube).

This is the HF analogue of check_power.py: same BJT/MOSFET/diode/JFET
specs, but the netlist is generated in hf_mode so the transformer + tank
actually do their job. Without this, check_power.py's 1 kHz run sees
the transformer shorted by magnetising reactance and reports misleading
dissipation numbers.
"""
from __future__ import annotations
import sys, re, subprocess
from pathlib import Path
import numpy as np

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import test_closed_loop as m
from check_power import power_specs


T_END_HF = 0.100
SS_WIN   = 0.005   # last 5 ms = 500 cycles at 100 kHz

V_INT_SETTLED = {"iv6": 2.13, "ilc11_7": 2.10, "ilc11_8": 2.10, "iv18": 0.50}


def run(tube_key: str):
    spec = m.TUBES[tube_key]
    mc = {k: spec[k] for k in ("r_amb", "sigma_eps_A", "c_th",
                               "r_top_ref", "r_bot_ref", "r_sense")}
    if spec.get("booster"): mc["booster"] = True
    if spec.get("c_ap")    is not None: mc["c_ap"]    = spec["c_ap"]
    if spec.get("buf_fb1") is not None: mc["buf_fb1"] = spec["buf_fb1"]
    if spec.get("buf_fb_ap") is not None: mc["buf_fb_ap"] = spec["buf_fb_ap"]
    if spec.get("v_buf")   is not None: mc["v_buf"]   = spec["v_buf"]
    if spec.get("ce_buf"): mc["ce_buf"] = True
    if spec.get("mos_buf"): mc["mos_buf"] = True
    if spec.get("tank_l") is not None: mc["tank_l"] = spec["tank_l"]
    if spec.get("tank_c") is not None: mc["tank_c"] = spec["tank_c"]
    if spec.get("bias_diode"): mc["bias_diode"] = spec["bias_diode"]
    if spec.get("xfmr_n") is not None: mc["xfmr_n"] = spec["xfmr_n"]
    if spec.get("xfmr_lpri") is not None: mc["xfmr_lpri"] = spec["xfmr_lpri"]
    mc["hf_mode"] = True
    mc["R_op"] = spec["R_op"]
    mc["T_op"] = spec["T_op"]
    mc["v_int_settled"] = V_INT_SETTLED.get(tube_key, 2.0)

    use_booster = bool(spec.get("booster"))
    work = m.WORK; work.mkdir(exist_ok=True)
    cir = work / f"powerhf_{tube_key}.cir"
    dat = work / f"powerhf_{tube_key}.data"
    netlist = m.make_netlist(dat, v_preset=0.0, t_ramp=0.0,
                             r_int_scale=spec["r_int_scale"], mc=mc)
    netlist = re.sub(r"\.tran\s+\S+\s+\S+(\s+UIC)?",
                     f".tran 50n {T_END_HF:.3f} UIC", netlist)

    specs = power_specs(use_booster, ce_buf=spec.get("ce_buf", False),
                        mos_buf=spec.get("mos_buf", False))
    save_tokens, at_to_let = set(), {}
    for _n, e, _r in specs:
        for tok in re.findall(r"@\w+\[\w+\]", e):
            save_tokens.add(tok)
            at_to_let[tok] = "x_" + tok.replace("@", "").replace("[", "_").replace("]", "")
        for tok in re.findall(r"v\(\w+\)", e):
            save_tokens.add(tok)
    binds = "\n".join(f"let {ln} = {tk}" for tk, ln in sorted(at_to_let.items()))
    lets = []
    for n, e, _r in specs:
        ee = e
        for tk, ln in at_to_let.items():
            ee = ee.replace(tk, ln)
        lets.append(f"let p_{n} = {ee}")
    let_lines = "\n".join(lets)
    wrdata_args = " ".join(f"p_{n}" for n, _, _ in specs)
    new_control = f""".save {' '.join(sorted(save_tokens))}
.control
run
{binds}
{let_lines}
wrdata {dat.as_posix()} {wrdata_args}
.endcontrol"""
    netlist = re.sub(r"\.control.*?\.endcontrol", new_control, netlist, flags=re.DOTALL)
    cir.write_text(netlist)
    res = subprocess.run(["ngspice", "-b", cir.name], cwd=work,
                         capture_output=True, text=True, timeout=900)
    if res.returncode != 0:
        print(res.stderr[-2000:]); raise SystemExit(1)
    d = np.loadtxt(dat)
    t = d[:, 0]
    ss = t > t[-1] - SS_WIN
    t_ss = t[ss]; dur = t_ss[-1] - t_ss[0]
    out = {}
    for i, (name, _e, rating) in enumerate(specs):
        p = d[:, 2*i + 1]
        p_pos = np.where(p > 0, p, 0.0)
        p_neg = np.where(p < 0, -p, 0.0)
        out[name] = {
            "p_peak":    float(np.max(p_pos)),
            "p_ss_mean": float(np.trapezoid(p_pos[ss], t_ss) / dur),
            "p_ss_max":  float(np.max(p_pos[ss])),
            "rating":    rating,
        }
    try: dat.unlink()
    except OSError: pass
    return out


def main():
    tubes = sys.argv[1:] or ["ilc11_7"]
    for tube in tubes:
        if tube not in m.TUBES:
            print(f"Unknown tube {tube}"); continue
        spec = m.TUBES[tube]
        print(f"\n=== {spec['name']} HF (booster={'on' if spec.get('booster') else 'off'}, "
              f"xfmr_n={spec.get('xfmr_n', 'none')}, v_buf={spec.get('v_buf', 'default')}) ===")
        results = run(tube)
        print(f"{'Device':<22s} {'P_peak':>10s} {'P_ss_max':>10s} {'P_ss_avg':>10s}  Rating  Status")
        print("-" * 80)
        for name, r in results.items():
            peak_pct = 100 * r["p_peak"] / (r["rating"] * 1e-3)
            ss_pct   = 100 * r["p_ss_mean"] / (r["rating"] * 1e-3)
            status = ""
            if ss_pct > 100:    status = " *** SS over rating ***"
            elif peak_pct > 100: status = " *** PEAK over rating ***"
            elif ss_pct > 50:    status = " (steady-state >50% rating)"
            print(f"{name:<22s} {r['p_peak']*1e3:>8.1f}mW {r['p_ss_max']*1e3:>8.1f}mW "
                  f"{r['p_ss_mean']*1e3:>8.1f}mW  {r['rating']:>4d}mW{status}")


if __name__ == "__main__":
    main()
