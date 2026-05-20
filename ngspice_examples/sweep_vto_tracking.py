"""V_TO part-to-part robustness sweep for the V_TO-tracking reference.

Sweeps the DMN3404L inner model's VTO across the datasheet V_GS(th)=1.0/
1.5/2.0 V min/typ/max range, running ILC1-1/7 cold-start each time. With
the matched-pair tracking architecture (Q_ref = Q_var1 = Q_var2 = same
DMN3404L from the same reel), V_offset_ref auto-shifts so V_OD_var at
cold-start stays at ~+0.31 V independent of V_TO, and V_int_out_OP stays
within the integrator clamp range. This script verifies that.

Implementation: textual substitution on the .SUBCKT DMN3404L model file.
The inner `.MODEL Nmod1 NMOS (LEVEL=3 VTO=2 ...)` is rewritten with the
target VTO, the modified subckt is written to a temp file, and the
netlist's .include line is patched to reference it.

Tube choice: ILC1-1/7 is the slowest-converging tube (largest cold-start
overshoot in the prior fixed-V_offset design), and it runs faster than
the mos_buf tubes under the manufacturer model (~125 s wall for 1.5 s sim
vs 130-180 s for the others), so it's the tightest stress test per minute
of wall time.
"""
import sys, types, re, subprocess, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import numpy as np

mpl = types.ModuleType("matplotlib"); mpl.use=lambda *a, **k: None
sys.modules.setdefault("matplotlib", mpl)
sys.modules.setdefault("matplotlib.pyplot", types.ModuleType("plt"))

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_closed_loop as tcl

tcl.T_END = 2.0

VTO_VALUES = [1.0, 1.5, 2.0]  # datasheet V_GS(th) min/typ/max
TUBE = "ilc11_7"


def make_modified_subckt(vto_target: float) -> Path:
    """Write a modified DMN3404L .subckt file with VTO shifted, return the path."""
    src = HERE / "spice_models" / "DMN3404L.spice.txt"
    text = src.read_text()
    # Match `.MODEL Nmod1 NMOS (LEVEL=3 VTO=2 ...)` and rewrite VTO.
    new_text, n = re.subn(
        r"(\.MODEL\s+Nmod1\s+NMOS\s*\(\s*LEVEL=3\s+VTO=)[\d.eE+-]+",
        rf"\g<1>{vto_target:.4g}",
        text,
        count=1,
    )
    assert n == 1, f"VTO substitution count {n} != 1"
    out = tcl.WORK / f"DMN3404L_vto{vto_target:.2f}.spice.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(new_text)
    return out


def run_one(vto_target: float):
    spec = tcl.TUBES[TUBE]
    mc = {k: spec[k] for k in ("r_amb", "sigma_eps_A", "c_th",
                                "r_top_ref", "r_bot_ref", "r_sense")}
    mc["t_rail_ramp"] = 100e-6
    for k in ("booster", "ce_buf", "mos_buf"):
        if spec.get(k): mc[k] = True
    for k in ("buf_fb1", "buf_fb_ap", "v_buf", "c_ap"):
        if spec.get(k) is not None: mc[k] = spec[k]

    raw = tcl.make_netlist(tcl.WORK / f"vto_{vto_target:.2f}.data",
                            v_preset=0.0, t_ramp=0.0,
                            r_int_scale=spec["r_int_scale"], mc=mc)

    # Patch the .include path to point to our modified subckt.
    new_subckt = make_modified_subckt(vto_target)
    orig_inc = (HERE / "spice_models" / "DMN3404L.spice.txt").as_posix()
    raw = raw.replace(orig_inc, new_subckt.as_posix())
    assert new_subckt.as_posix() in raw, "subckt path patch failed"

    label = f"vto_{vto_target:.2f}"
    cir = tcl.WORK / f"{label}.cir"
    dat = tcl.WORK / f"{label}.data"
    cir.write_text(raw)
    t0 = time.time()
    res = subprocess.run(["ngspice", "-b", cir.name], cwd=tcl.WORK,
                         capture_output=True, text=True, timeout=1800)
    wall = time.time() - t0
    if res.returncode != 0:
        return dict(vto=vto_target, error=res.stderr[-400:], wall=wall)
    d = np.loadtxt(dat)
    t = d[:, 0]
    cols = dict(v_osc_drive=1, v_ap_drive=3, node_A=5, node_B=7, n_diff=9,
                n_demout=11, v_ctl=13, v_int_out=15, T_node=17, r_fil=19,
                v_int_raw=21, e_sat=23)
    r = {k: d[:, c] for k, c in cols.items()}
    r["t"] = t
    late = t > t[-1] - 0.05
    T_end = float(np.mean(r["T_node"][late]))
    T_pk = float(np.max(r["T_node"]))
    v_int_op = float(np.mean(r["v_int_out"][late]))
    v_ctl_op = float(np.mean(r["v_ctl"][late]))
    v_offset = v_ctl_op - v_int_op
    try: dat.unlink()
    except OSError: pass
    return dict(vto=vto_target, wall=wall, T_end=T_end, T_peak=T_pk,
                T_op=spec["T_op"], v_int_op=v_int_op, v_ctl_op=v_ctl_op,
                v_offset=v_offset)


def main():
    print(f"Sweeping VTO over {VTO_VALUES} on {TUBE} (T_op={tcl.TUBES[TUBE]['T_op']} K)...")
    with ThreadPoolExecutor(max_workers=3) as ex:
        results = list(ex.map(run_one, VTO_VALUES))
    print()
    print(f"{'VTO':>5s}  {'T_end':>7s}  {'T_pk':>7s}  {'+over':>6s}  {'V_int_OP':>9s}  {'V_offset':>9s}  {'wall':>6s}")
    for r in results:
        if "error" in r:
            print(f"{r['vto']:5.2f}  FAIL  {r['error'][:80]}")
            continue
        print(f"{r['vto']:5.2f}  {r['T_end']:7.1f}  {r['T_peak']:7.1f}  "
              f"{r['T_peak']-r['T_op']:+6.1f}  {r['v_int_op']:+9.4f}  "
              f"{r['v_offset']:+9.4f}  {r['wall']:6.1f}s")


if __name__ == "__main__":
    main()
