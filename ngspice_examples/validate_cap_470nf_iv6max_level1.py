"""Re-run IV-6 V_p=-3.0V case with Level 1 placeholder MOSFETs instead of
DMP3098L/DMN3404L manufacturer subcircuits, to calibrate whether Level 1 is
trustworthy for cold-start/settle analysis.

Same C_AP=470nF, same V_p=-3, same loop. Only MOSFET model changes.
"""
import sys, csv, time, re, shutil, subprocess
import numpy as np
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from test_closed_loop import TUBES, make_netlist, metrics, T_OP_TARGET, WORK

C_AP_NEW = 470e-9
CLAMP_LO, CLAMP_HI = -2.5, 2.5

LEVEL1_MODELS = """.model PMOS_LL PMOS(LEVEL=1 VTO=-0.7 KP=100u L=1u W=55600u LAMBDA=0.01)
.model NMOS_LL NMOS(LEVEL=1 VTO=+0.7 KP=100u L=1u W=55600u LAMBDA=0.01)"""


def swap_to_level1(netlist_text):
    """Post-process a netlist string: replace BRIDGE-DRIVER manufacturer MOSFET
    instances with Level 1 .model + M instances for runtime speed. The
    variable-R MOSFETs (M_var1, M_var2) and the V_TO-tracking reference
    (M_ref) are left at manufacturer model: the V_TO-tracking circuit
    relies on Q_ref's V_TO matching Q_var1/Q_var2's V_TO, and the Level-1
    placeholder has V_TO=+0.7 V (vs DMN3404L ~+1.7 V effective) which would
    both break the tracking and stall the loop. .include lines for the
    manufacturer models are retained for that reason."""
    PRESERVE = {"M_var1", "M_var2", "M_ref"}
    lines_out = []
    for line in netlist_text.splitlines():
        # Replace X-instances. Match e.g.
        #   XM_o_pmos v_osc_drive g_o_pmos vcc_buf_o_pmos DMP3098L
        # with
        #   M_o_pmos v_osc_drive g_o_pmos vcc_buf_o_pmos vcc_buf_o_pmos PMOS_LL
        # Skip the variable-R FETs.
        m = re.match(r"^X(M_\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(DMP3098L|DMN3404L)\s*$", line)
        if m and m.group(1) not in PRESERVE:
            instname, d, g, s, mfg = m.groups()
            model_name = "PMOS_LL" if mfg == "DMP3098L" else "NMOS_LL"
            lines_out.append(f"{instname} {d} {g} {s} {s} {model_name}")
            continue
        lines_out.append(line)
    text = "\n".join(lines_out)
    # Inject the Level 1 .model directives right after the comment block
    # describing the (now-removed) manufacturer .include
    text = text.replace(
        "* are 3-pin: drain, gate, source (no external body).",
        "* are 4-pin in Level 1 form (drain, gate, source, body=source).\n"
        + LEVEL1_MODELS,
    )
    return text


def run_level1():
    spec = TUBES["iv6"]
    mc = {"r_amb": spec["r_amb"],
          "sigma_eps_A": spec["sigma_eps_A"],
          "c_th": spec["c_th"],
          "r_top_ref": spec["r_top_ref"],
          "r_bot_ref": spec["r_bot_ref"],
          "r_sense":   spec["r_sense"],
          "c_ap": C_AP_NEW,
          "jfet_vp": -3.0}
    if spec.get("booster"):        mc["booster"] = True
    if spec.get("buf_fb1") is not None:    mc["buf_fb1"] = spec["buf_fb1"]
    if spec.get("buf_fb_ap") is not None:  mc["buf_fb_ap"] = spec["buf_fb_ap"]
    if spec.get("v_buf") is not None:      mc["v_buf"] = spec["v_buf"]
    if spec.get("ce_buf"):                 mc["ce_buf"] = True
    if spec.get("mos_buf"):                mc["mos_buf"] = True

    label = "cap470_iv6_vpmax_level1"
    cir_path = WORK / f"closedloop_{label}.cir"
    dat_path = WORK / f"closedloop_{label}.data"
    raw_netlist = make_netlist(dat_path,
                               v_preset=0.0, t_ramp=0.0,
                               r_int_scale=spec["r_int_scale"], mc=mc)
    swapped = swap_to_level1(raw_netlist)
    # Sanity check: must contain Level 1 model defs and no DMP3098L/DMN3404L
    assert "PMOS_LL" in swapped and "NMOS_LL" in swapped, "Level 1 model defs missing"
    # Allow refs in comment lines only (starting with *)
    non_comment_refs = [L for L in swapped.splitlines()
                        if ("DMP3098L" in L or "DMN3404L" in L) and not L.lstrip().startswith("*")]
    assert not non_comment_refs, f"manufacturer refs remain on non-comment lines: {non_comment_refs[:3]}"
    cir_path.write_text(swapped)
    print(f"Netlist patched: {cir_path}", flush=True)

    t0 = time.time()
    res = subprocess.run(["ngspice", "-b", cir_path.name],
                         cwd=WORK, capture_output=True, text=True)
    wall = time.time() - t0
    if res.returncode != 0:
        print("STDERR tail:", res.stderr[-2000:])
        print("STDOUT tail:", res.stdout[-2000:])
        raise RuntimeError("ngspice failed")
    print(f"ngspice done in {wall/60:.2f} min", flush=True)

    d = np.loadtxt(dat_path)
    try: dat_path.unlink()
    except OSError: pass
    r = dict(t=d[:,0], v_osc=d[:,1], v_ap=d[:,3], v_A=d[:,5], v_B=d[:,7],
             v_diff=d[:,9], v_dem=d[:,11], v_ctl=d[:,13], v_int=d[:,15],
             T=d[:,17], R=d[:,19])

    m = metrics(r, target_T=spec["T_op"])
    t = r["t"]; late = t > (t[-1] - 0.05)
    t_late = t[late]
    v_ctl_op   = float(np.trapezoid(r["v_ctl"][late], t_late) / (t_late[-1] - t_late[0]))
    v_ctl_peak = float(np.max(np.abs(r["v_ctl"])))
    r_fil_peak  = float(np.max(r["R"]))
    r_fil_final = float(r["R"][-1])
    return dict(
        wall_min=wall/60,
        v_ctl_OP=v_ctl_op, v_ctl_peak=v_ctl_peak,
        t_settle_5K=m["t_settle_5K"], t_settle_10K=m["t_settle_10K"],
        T_peak=m["T_peak"], T_final=m["T_final"], T_target=spec["T_op"],
        R_fil_peak=r_fil_peak, R_fil_final=r_fil_final, R_fil_target=spec["R_op"],
    )


if __name__ == "__main__":
    m = run_level1()
    print(f"\nLevel 1 result (IV-6 V_p=-3.0V, C_AP=470nF):")
    print(f"  V_ctl_OP     = {m['v_ctl_OP']:+.3f} V    (manuf: -2.640 V)")
    print(f"  V_ctl_peak   = {m['v_ctl_peak']:+.3f} V    (manuf: +2.820 V)")
    print(f"  t_settle_5K  = {m['t_settle_5K']*1e3:.0f} ms    (manuf: 1456 ms)")
    print(f"  t_settle_10K = {m['t_settle_10K']*1e3:.0f} ms")
    print(f"  T_final      = {m['T_final']:.1f} K    (manuf: 800.0 K, target {m['T_target']:.0f} K)")
    print(f"  T_peak       = {m['T_peak']:.1f} K")
    print(f"  R_fil_final  = {m['R_fil_final']:.3f} Ω    (manuf: 20.000 Ω, target {m['R_fil_target']:.0f} Ω)")
    print(f"  R_fil_peak   = {m['R_fil_peak']:.3f} Ω    (manuf: 20.0 Ω)")
    print(f"  wall         = {m['wall_min']:.2f} min   (manuf: 321.7 min)")
    out = HERE / "cap_470nf_iv6max_level1_results.csv"
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(m.keys())); w.writeheader(); w.writerow(m)
    print(f"Wrote {out}")
