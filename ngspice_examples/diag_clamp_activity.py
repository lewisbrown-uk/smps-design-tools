"""Integrator-clamp activity diagnostic.

For each tube, runs the standard 5 s closed-loop transient and captures:
- v_int_out (integrator output)
- v_clamp_hi, v_clamp_lo (the clamp reference voltages)
- i(D_aw_hi), i(D_aw_lo) (currents through the anti-windup Schottky
  diodes)

Reports:
- Cold-start behaviour: peak diode currents and how long the clamp is
  significantly conducting
- Steady-state behaviour: is v_int hovering at one of the clamp rails?
  How much continuous current is bleeding through the Schottky?
- Time fraction the clamp is "active" (current > 1 mA threshold)

Useful for deciding whether the clamp is serving a genuine anti-windup
purpose (only active during cold start) or whether it's bottlenecking
steady-state operation (continuously active = limiting the loop's
operating range).
"""
from __future__ import annotations
import sys, re, subprocess
from pathlib import Path
import numpy as np

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import test_closed_loop as m


def run_with_clamp_probe(tube_key: str, t_end: float = 5.0):
    spec = m.TUBES[tube_key]
    mc = {k: spec[k] for k in ("r_amb", "sigma_eps_A", "c_th",
                               "r_top_ref", "r_bot_ref", "r_sense")}
    if spec.get("booster"): mc["booster"] = True
    if spec.get("buf_fb1") is not None: mc["buf_fb1"] = spec["buf_fb1"]
    if spec.get("buf_fb_ap") is not None: mc["buf_fb_ap"] = spec["buf_fb_ap"]
    if spec.get("v_buf")   is not None: mc["v_buf"]   = spec["v_buf"]
    if spec.get("ce_buf"): mc["ce_buf"] = True
    if spec.get("mos_buf"): mc["mos_buf"] = True

    work = m.WORK; work.mkdir(exist_ok=True)
    cir = work / f"clamp_{tube_key}.cir"
    dat = work / f"clamp_{tube_key}.data"
    netlist = m.make_netlist(dat, v_preset=0.0, t_ramp=0.0,
                             r_int_scale=spec["r_int_scale"], mc=mc)
    new_control = f""".save V(v_int_out) V(v_clamp_hi) V(v_clamp_lo) @D_aw_hi[id] @D_aw_lo[id]
.control
run
let v_int = v(v_int_out)
let v_chi = v(v_clamp_hi)
let v_clo = v(v_clamp_lo)
let i_d_hi = @D_aw_hi[id]
let i_d_lo = @D_aw_lo[id]
wrdata {dat.as_posix()} v_int v_chi v_clo i_d_hi i_d_lo
.endcontrol"""
    netlist = re.sub(r"\.control.*?\.endcontrol", new_control,
                     netlist, flags=re.DOTALL)
    netlist = re.sub(r"\.tran\s+\S+\s+\S+",
                     f".tran 10u {t_end:.3f}", netlist, count=1)
    cir.write_text(netlist)
    res = subprocess.run(["ngspice", "-b", cir.name], cwd=work,
                         capture_output=True, text=True, timeout=900)
    if res.returncode != 0:
        print(res.stderr[-1500:]); raise SystemExit(1)
    d = np.loadtxt(dat)
    try: dat.unlink()
    except OSError: pass
    return dict(t=d[:,0], v_int=d[:,1], v_chi=d[:,3], v_clo=d[:,5],
                i_d_hi=d[:,7], i_d_lo=d[:,9])


def analyse(tube_key, r):
    spec = m.TUBES[tube_key]
    t = r["t"]
    v_int = r["v_int"]
    i_hi = r["i_d_hi"]   # forward current of D_aw_hi (positive when conducting)
    i_lo = r["i_d_lo"]
    # The diodes are forward-biased when v_int exceeds v_chi or falls
    # below v_clo. ngspice diode current is positive in forward direction
    # (anode-to-cathode).

    # Time-segment analysis: cold-start (first 100 ms) vs settled (last 1 s)
    cold = t < 0.1
    settled = t > t[-1] - 1.0

    def stats(mask):
        if mask.sum() < 5:
            return dict(active_frac=float("nan"), i_max=0.0, i_avg=0.0,
                        v_int_min=float("nan"), v_int_max=float("nan"))
        # Active if either diode current > 1 mA forward
        i_max_inst = np.maximum(np.abs(i_hi[mask]), np.abs(i_lo[mask]))
        active = i_max_inst > 1e-3
        t_seg = t[mask]
        seg_dur = t_seg[-1] - t_seg[0]
        active_frac = float(np.trapezoid(active.astype(float), t_seg) / seg_dur)
        i_avg_hi = float(np.trapezoid(np.maximum(i_hi[mask], 0), t_seg) / seg_dur)
        i_avg_lo = float(np.trapezoid(np.maximum(i_lo[mask], 0), t_seg) / seg_dur)
        return dict(
            active_frac=active_frac,
            i_hi_max=float(np.max(np.abs(i_hi[mask]))),
            i_lo_max=float(np.max(np.abs(i_lo[mask]))),
            i_hi_avg=i_avg_hi,
            i_lo_avg=i_avg_lo,
            v_int_min=float(np.min(v_int[mask])),
            v_int_max=float(np.max(v_int[mask])),
            v_int_avg=float(np.trapezoid(v_int[mask], t_seg) / seg_dur),
        )

    cold_s = stats(cold)
    settled_s = stats(settled)

    print(f"\n=== {spec['name']} integrator-clamp activity ===")
    print(f"  Clamp rails: v_clamp_lo = {np.mean(r['v_clo']):+.3f} V, "
          f"v_clamp_hi = {np.mean(r['v_chi']):+.3f} V")
    print(f"  (Schottky V_F ~ 0.3 V, so soft-clamp range is "
          f"~{np.mean(r['v_clo'])-0.3:+.2f} V to {np.mean(r['v_chi'])+0.3:+.2f} V)")
    print()
    print(f"  Cold-start window (t < 100 ms):")
    print(f"    v_int range:  {cold_s['v_int_min']:+.3f} to {cold_s['v_int_max']:+.3f} V")
    print(f"    D_aw_hi peak: {cold_s['i_hi_max']*1e3:.2f} mA   D_aw_lo peak: {cold_s['i_lo_max']*1e3:.2f} mA")
    print(f"    D_aw_hi avg:  {cold_s['i_hi_avg']*1e3:.2f} mA   D_aw_lo avg:  {cold_s['i_lo_avg']*1e3:.2f} mA")
    print(f"    Clamp active: {cold_s['active_frac']*100:.1f}% of cold-start window")
    print()
    print(f"  Settled window (last 1 s):")
    print(f"    v_int avg:    {settled_s['v_int_avg']:+.3f} V (range {settled_s['v_int_min']:+.3f} to {settled_s['v_int_max']:+.3f} V)")
    print(f"    D_aw_hi peak: {settled_s['i_hi_max']*1e3:.2f} mA   D_aw_lo peak: {settled_s['i_lo_max']*1e3:.2f} mA")
    print(f"    D_aw_hi avg:  {settled_s['i_hi_avg']*1e3:.2f} mA   D_aw_lo avg:  {settled_s['i_lo_avg']*1e3:.2f} mA")
    print(f"    Clamp active: {settled_s['active_frac']*100:.1f}% of settled window")
    # Verdict
    if settled_s["active_frac"] < 0.05:
        print(f"  Verdict: clamp is mostly inactive in steady state -- serving its anti-windup purpose only at cold-start.")
    elif settled_s["active_frac"] < 0.5:
        print(f"  Verdict: clamp is intermittently active in steady state.")
    else:
        print(f"  Verdict: clamp is continuously bleeding current in steady state -- bottlenecking the loop's operating point.")


def main():
    tubes = sys.argv[1:] or ["iv3", "iv6", "ilc11_7", "ilc11_8"]
    for tube in tubes:
        if tube not in m.TUBES:
            print(f"Unknown tube {tube}"); continue
        r = run_with_clamp_probe(tube, t_end=5.0)
        analyse(tube, r)


if __name__ == "__main__":
    main()
