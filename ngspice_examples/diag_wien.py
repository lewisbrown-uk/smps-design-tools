"""Capture Wien-bridge internal nodes to localise the DC offset on v_osc.

Wien topology (from netlist):
  R1, C1, R2, C2: bridge feedback to op-amp + input (np)
  Rg, Rfa, Rfb:   feedback divider to op-amp - input (nn) and node fb
  Q1: collector=fb, emitter=v_osc (limits when fb-v_osc rises)
  Q2: collector=v_osc, emitter=fb (limits when v_osc-fb rises)
  Rtop1/Rbot1, Rtop2/Rbot2: limiter base bias dividers

If the limiter is symmetric, b1 and b2 should have equal DC means. If
not, one BJT clips harder, biasing v_osc.
"""
from __future__ import annotations
import sys, re, subprocess
from pathlib import Path
import numpy as np

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import test_closed_loop as m


def main():
    tube = sys.argv[1] if len(sys.argv) > 1 else "ilc11_7"
    spec = m.TUBES[tube]
    mc = {k: spec[k] for k in ("r_amb", "sigma_eps_A", "c_th",
                               "r_top_ref", "r_bot_ref", "r_sense")}
    if spec.get("booster"): mc["booster"] = True
    if spec.get("c_ap")    is not None: mc["c_ap"]    = spec["c_ap"]
    if spec.get("buf_fb1") is not None: mc["buf_fb1"] = spec["buf_fb1"]
    if spec.get("buf_fb_ap") is not None: mc["buf_fb_ap"] = spec["buf_fb_ap"]
    if spec.get("v_buf")   is not None: mc["v_buf"]   = spec["v_buf"]
    if spec.get("ce_buf"): mc["ce_buf"] = True
    # Optional second arg: 'vos0' to zero the Wien op-amp Vos for diagnostic
    zero_vos = (len(sys.argv) > 2 and sys.argv[2] == "vos0")
    if zero_vos:
        mc["vos_osc"] = 0.0

    work = m.WORK
    cir = work / f"wien_{tube}.cir"
    dat = work / f"wien_{tube}.data"
    netlist = m.make_netlist(dat, v_preset=0.0, t_ramp=0.0,
                             r_int_scale=spec["r_int_scale"], mc=mc)
    new_control = f""".save V(v_osc) V(fb) V(np) V(nn) V(b1) V(b2) V(ns) @Q1[ic] @Q2[ic] @Q1[ie] @Q2[ie]
.control
run
let v_o   = v(v_osc)
let v_fb  = v(fb)
let v_np  = v(np)
let v_nn  = v(nn)
let v_b1  = v(b1)
let v_b2  = v(b2)
let v_ns  = v(ns)
let i_q1c = @Q1[ic]
let i_q2c = @Q2[ic]
let i_q1e = @Q1[ie]
let i_q2e = @Q2[ie]
wrdata {dat.as_posix()} v_o v_fb v_np v_nn v_b1 v_b2 v_ns i_q1c i_q2c i_q1e i_q2e
.endcontrol"""
    netlist = re.sub(r"\.control.*?\.endcontrol", new_control, netlist, flags=re.DOTALL)
    cir.write_text(netlist)
    res = subprocess.run(["ngspice", "-b", cir.name], cwd=work,
                         capture_output=True, text=True, timeout=600)
    if res.returncode != 0:
        print(res.stderr[-2000:]); raise SystemExit(1)
    d = np.loadtxt(dat)
    t = d[:, 0]
    cols = ["v_o", "v_fb", "v_np", "v_nn", "v_b1", "v_b2", "v_ns",
            "i_q1c", "i_q2c", "i_q1e", "i_q2e"]
    sigs = {name: d[:, 2*i+1] for i, name in enumerate(cols)}
    # Last 100 ms steady state
    mask = t > t[-1] - 0.1
    print(f"=== {spec['name']}, last 100 ms ({mask.sum()} samples) ===\n")
    tt = t[mask]
    dur = tt[-1] - tt[0]
    for name in cols:
        x = sigs[name][mask]
        unit = "A" if name.startswith("i_") else "V"
        scale = 1e3 if unit == "V" else 1e6
        unit2 = "mV" if unit == "V" else "uA"
        # Time-weighted mean (trapezoidal integration), correct for variable timestep
        twm = np.trapezoid(x, tt) / dur
        print(f"  {name:6s}  twm={twm*scale:+9.3f}{unit2}  "
              f"mean={np.mean(x)*scale:+9.3f}{unit2}  "
              f"rms={np.std(x)*scale:9.3f}{unit2}  "
              f"max={np.max(x)*scale:+9.3f}{unit2}  "
              f"min={np.min(x)*scale:+9.3f}{unit2}")
    print(f"\n  v_osc - v_fb mean: {(np.mean(sigs['v_o'][mask]) - np.mean(sigs['v_fb'][mask]))*1e3:+.3f}mV")
    print(f"  b1   - b2   mean (limiter base symmetry): {(np.mean(sigs['v_b1'][mask]) - np.mean(sigs['v_b2'][mask]))*1e3:+.3f}mV")
    print(f"  Q1 vs Q2 collector current means: Q1={np.mean(sigs['i_q1c'][mask])*1e6:+.3f}uA  Q2={np.mean(sigs['i_q2c'][mask])*1e6:+.3f}uA")
    # Mean per 500ms window to see whether V(np)/V(v_osc) drift over time
    print("\n  Window-mean evolution (testing for slow drift):")
    print(f"  {'window':12s}  {'v_o':>10s}  {'v_np':>10s}  {'v_nn':>10s}  {'v_fb':>10s}")
    for w_start in np.arange(0.5, t[-1] - 0.5 + 1e-9, 0.5):
        wmask = (t >= w_start) & (t < w_start + 0.5)
        if wmask.sum() == 0: continue
        print(f"  [{w_start:.2f}-{w_start+0.5:.2f}]   "
              f"{np.mean(sigs['v_o'][wmask])*1e3:+8.2f}mV  "
              f"{np.mean(sigs['v_np'][wmask])*1e3:+8.2f}mV  "
              f"{np.mean(sigs['v_nn'][wmask])*1e3:+8.2f}mV  "
              f"{np.mean(sigs['v_fb'][wmask])*1e3:+8.2f}mV")
    try: dat.unlink()
    except OSError: pass


if __name__ == "__main__":
    main()
