"""Dump the raw netlist (as the test_closed_loop.py make_netlist function
generates it) for each tube to a .cir file. Useful for comparing the
LTspice-generated netlist against the original ngspice netlist when
diagnosing why a converted .asc doesn't simulate quite the same way.
"""
from pathlib import Path
import sys

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import test_closed_loop as m


def main():
    for tube_key, spec in m.TUBES.items():
        mc = {k: spec[k] for k in ("r_amb", "sigma_eps_A", "c_th",
                                   "r_top_ref", "r_bot_ref", "r_sense")}
        if spec.get("booster"): mc["booster"] = True
        if spec.get("c_ap") is not None: mc["c_ap"] = spec["c_ap"]
        if spec.get("buf_fb1") is not None: mc["buf_fb1"] = spec["buf_fb1"]
        if spec.get("buf_fb_ap") is not None: mc["buf_fb_ap"] = spec["buf_fb_ap"]
        if spec.get("v_buf") is not None: mc["v_buf"] = spec["v_buf"]
        if spec.get("ce_buf"): mc["ce_buf"] = True
        if spec.get("mos_buf"): mc["mos_buf"] = True
        if spec.get("wien_alpha") is not None: mc["wien_alpha"] = spec["wien_alpha"]
        if spec.get("bias_diode"): mc["bias_diode"] = spec["bias_diode"]
        if spec.get("bias_zener_v") is not None: mc["bias_zener_v"] = spec["bias_zener_v"]
        # Dummy data path; not actually used since we won't run the sim
        netlist = m.make_netlist(HERE / f"_{tube_key}_unused.data",
                                 v_preset=0.55, t_ramp=0.1,
                                 r_int_scale=spec["r_int_scale"], mc=mc)
        out = HERE / f"regulator_{tube_key}.cir"
        # Add a header comment so the file describes itself
        header = (
            f"* VFD-filament regulator netlist for {spec['name']} (tube={tube_key})\n"
            f"* Generated from test_closed_loop.py make_netlist; matches the\n"
            f"* netlist that the corresponding regulator_{tube_key}.asc was\n"
            f"* converted from. Use to cross-check LTspice's generated netlist.\n\n"
        )
        out.write_text(header + netlist)
        print(f"Wrote {out}")


if __name__ == "__main__":
    main()
