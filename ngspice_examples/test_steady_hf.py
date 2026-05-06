"""High-frequency steady-state simulation: f0 = 100 kHz with fixed-R
filament so the loop's integrator settles in ~50 ms (not the 1+ s
thermal time constant). Used to evaluate AC behaviour (BJT/MOSFET
power, harmonic content, eventually class-C tank performance) at
high carrier frequency without paying for a 5 s simulation that
runs at 1/100th real-time per sim.

The matched closed-loop transient sim runs at f0=1 kHz via
test_closed_loop.py --mode sweep_tubes (existing). The two together
verify both slow thermal dynamics (1 kHz) and fast AC behaviour
(100 kHz) for the same circuit topology.

Usage:  python3 test_steady_hf.py [tube ...]
        defaults to ilc11_7 if no args given.
"""
from __future__ import annotations
import sys, re, subprocess
from pathlib import Path
import numpy as np

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import test_closed_loop as m


T_END_HF = 0.100   # 100 ms is plenty: integrator settles in ~50 ms with
                   # fixed R_fil; we measure steady-state in last 5 ms.


def run_hf(tube_key: str):
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
    # HF mode: f0 = 100 kHz, fixed R_fil = R_op
    mc["hf_mode"] = True
    mc["R_op"] = spec["R_op"]
    mc["T_op"] = spec["T_op"]
    # Settled v_int_out per tube (from prior 1 kHz sweeps); used as IC on
    # the integrator's feedback cap so the loop starts at its OP without
    # needing to traverse the slow electrical settling.
    v_int_settled_map = {
        "iv6":     2.13,
        "ilc11_7": 2.10,
        "ilc11_8": 2.10,
        "iv3":     0.50,   # IV-3 has different scale, smaller v_int
    }
    mc["v_int_settled"] = v_int_settled_map.get(tube_key, 2.0)

    work = m.WORK; work.mkdir(exist_ok=True)
    cir = work / f"hf_{tube_key}.cir"
    dat = work / f"hf_{tube_key}.data"
    netlist = m.make_netlist(dat, v_preset=0.0, t_ramp=0.0,
                             r_int_scale=spec["r_int_scale"], mc=mc)
    # Override the .tran for short HF run
    netlist = re.sub(r"\.tran\s+\S+\s+\S+(\s+UIC)?",
                     f".tran 100n {T_END_HF:.3f} UIC", netlist)
    new_control = f""".control
run
let v_o   = v({mc.get('v_osc_drive', 'v_osc_drive')})
let v_a   = v(v_ap_drive)
let v_int = v(v_int_out)
let v_drv = v(v_drv_atten)
let v_osc_w = v(v_osc)
wrdata {dat.as_posix()} v_o v_a v_int v_drv v_osc_w
.endcontrol"""
    if not spec.get("booster"):
        new_control = new_control.replace("v(v_ap_drive)", "v(v_ap)")
        new_control = new_control.replace("v(v_drv_atten)", "v(v_osc)")
    netlist = re.sub(r"\.control.*?\.endcontrol", new_control,
                     netlist, flags=re.DOTALL)
    cir.write_text(netlist)
    res = subprocess.run(["ngspice", "-b", cir.name], cwd=work,
                         capture_output=True, text=True, timeout=900)
    if res.returncode != 0:
        print(res.stderr[-2000:])
        raise RuntimeError(f"ngspice failed for {tube_key}")
    d = np.loadtxt(dat)
    t = d[:, 0]
    v_o   = d[:, 1]
    v_a   = d[:, 3]
    v_int = d[:, 5]
    v_drv = d[:, 7]
    v_osc_w = d[:, 9]
    # Steady-state window: last 5 ms (500 cycles at 100 kHz)
    ss = t > t[-1] - 0.005
    tt = t[ss]; dur = tt[-1] - tt[0]
    def twm(x): return float(np.trapezoid(x[ss], tt) / dur)
    def rms(x): return float(np.sqrt(np.trapezoid(x[ss]**2, tt) / dur))
    v_diff = v_o - v_a
    print(f"=== {spec['name']} HF steady state (last 5 ms, n={ss.sum()}) ===")
    print(f"  v_osc       rms={rms(v_osc_w):8.3f} V  twm={twm(v_osc_w)*1e3:+8.2f} mV")
    print(f"  v_drv_atten rms={rms(v_drv):8.3f} V  twm={twm(v_drv)*1e3:+8.2f} mV")
    print(f"  v_osc_drive rms={rms(v_o):8.3f} V  twm={twm(v_o)*1e3:+8.2f} mV")
    print(f"  v_ap_drive  rms={rms(v_a):8.3f} V  twm={twm(v_a)*1e3:+8.2f} mV")
    print(f"  v_int_out   twm={twm(v_int):+.3f} V")
    print(f"  V_diff      rms={rms(v_diff):8.3f} V  (target {spec['V_op']:.3f} V_RMS)")
    try: dat.unlink()
    except OSError: pass


def main():
    tubes = sys.argv[1:] or ["ilc11_7"]
    for tube in tubes:
        if tube not in m.TUBES:
            print(f"Unknown tube {tube}"); continue
        run_hf(tube)


if __name__ == "__main__":
    main()
