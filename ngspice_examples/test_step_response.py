"""Closed-loop step response: inject a thermal power step into T_node
after the loop has settled, then watch T recover.

For each tube, runs the standard closed-loop netlist with an additional
B-source feeding +P_step into T_node from t=t_step to t=t_step+t_step_dur.
This is a thermal disturbance comparable to a sudden draught or a
light perturbation in the real environment. The disturbance lets us
characterise the loop's transient response: undershoot/overshoot
magnitude after the step ends, and time to settle back within +/-5 K
of the pre-step temperature.

Usage:  python3 test_step_response.py [tube ...]
        defaults to ilc11_7 if no tubes given.
"""
from __future__ import annotations
import sys, re, subprocess
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import test_closed_loop as m

T_END    = 6.000     # extend the standard 5 s by 1 s for the step
T_STEP   = 3.000     # inject the step well after the soft-start has settled
T_DUR    = 0.200     # 200 ms perturbation
STEP_PCT = 0.10      # step magnitude as a fraction of each tube's P_op
                     # so loop dynamics are compared like-for-like across tubes


def run_step(tube_key: str):
    spec = m.TUBES[tube_key]
    p_step = STEP_PCT * spec["P_op"]
    mc = {k: spec[k] for k in ("r_amb", "sigma_eps_A", "c_th",
                               "r_top_ref", "r_bot_ref", "r_sense")}
    if spec.get("booster"): mc["booster"] = True
    if spec.get("c_ap")    is not None: mc["c_ap"]    = spec["c_ap"]
    if spec.get("buf_fb1") is not None: mc["buf_fb1"] = spec["buf_fb1"]
    if spec.get("buf_fb_ap") is not None: mc["buf_fb_ap"] = spec["buf_fb_ap"]
    if spec.get("v_buf")   is not None: mc["v_buf"]   = spec["v_buf"]

    work = m.WORK; work.mkdir(exist_ok=True)
    cir = work / f"step_{tube_key}.cir"
    dat = work / f"step_{tube_key}.data"
    netlist = m.make_netlist(dat, v_preset=0.55, t_ramp=0.100,
                             r_int_scale=spec["r_int_scale"], mc=mc)
    # Extend simulation length to T_END
    netlist = re.sub(r"\.tran\s+\S+\s+\S+", f".tran 10u {T_END:.3f}", netlist)
    # Insert the step disturbance just before .end. PWL high during
    # [T_STEP, T_STEP+T_DUR], zero elsewhere; B-source converts that to a
    # current injected into T_node (1 A at this thermal node = 1 W
    # because the filament subcircuit uses I directly as power).
    step_lines = (
        f"\n* Step disturbance: +{p_step*1e3:.2f} mW ({STEP_PCT*100:.0f}% of P_op={spec['P_op']*1e3:.1f} mW)\n"
        f"V_step_en vstepen 0 PWL("
        f"0 0 {T_STEP-1e-6:.6e} 0 {T_STEP:.6e} 1 "
        f"{T_STEP+T_DUR-1e-6:.6e} 1 {T_STEP+T_DUR:.6e} 0 {T_END:.3f} 0)\n"
        f"B_step 0 T_node I = {p_step:.6e} * (V(vstepen) > 0.5)\n"
    )
    netlist = netlist.replace("\n.end\n", step_lines + "\n.end\n")
    # Replace .control wrdata to capture the signals we need.
    # In non-booster mode, v_osc_drive == v_osc and v_ap_drive == v_ap; pick
    # the right pair so a single-arm tube also works.
    use_booster = bool(spec.get("booster"))
    v_top_name = "v_osc_drive" if use_booster else "v_osc"
    v_bot_name = "v_ap_drive"  if use_booster else "v_ap"
    v_drv_atten_let = "let v_da  = v(v_drv_atten)" if use_booster else "let v_da  = v(v_osc)"
    new_control = f""".control
run
let v_o   = v({v_top_name})
let v_a   = v({v_bot_name})
let v_i   = v(v_int_out)
let t_n   = v(T_node)
let r_f   = v(r_fil)
{v_drv_atten_let}
wrdata {dat.as_posix()} v_o v_a v_i t_n r_f v_da
.endcontrol"""
    netlist = re.sub(r"\.control.*?\.endcontrol", new_control,
                     netlist, flags=re.DOTALL)
    cir.write_text(netlist)
    res = subprocess.run(["ngspice", "-b", cir.name], cwd=work,
                         capture_output=True, text=True, timeout=900)
    if res.returncode != 0:
        print(res.stderr[-2000:])
        raise RuntimeError(f"ngspice failed for {tube_key}")
    d = np.loadtxt(dat)
    out = {"t":   d[:, 0],
           "v_o": d[:, 1],  "v_a": d[:, 3],  "v_i": d[:, 5],
           "T":   d[:, 7],  "r_f": d[:, 9],  "v_da": d[:, 11]}
    try: dat.unlink()
    except OSError: pass
    return out


def analyse(tube_key, r):
    spec = m.TUBES[tube_key]
    p_step = STEP_PCT * spec["P_op"]
    t = r["t"]
    T = r["T"]
    # Pre-step settled value: time-weighted mean over [T_STEP-0.1, T_STEP]
    pre_mask = (t > T_STEP - 0.1) & (t < T_STEP)
    T_pre = float(np.trapezoid(T[pre_mask], t[pre_mask]) /
                  (t[pre_mask][-1] - t[pre_mask][0]))
    # Peak excursion during/after step
    post_mask = t >= T_STEP
    T_post = T[post_mask]; t_post = t[post_mask]
    T_max = float(np.max(T_post))
    T_max_t = float(t_post[int(np.argmax(T_post))])
    T_min = float(np.min(T_post))
    T_min_t = float(t_post[int(np.argmin(T_post))])
    # Settling: first time after T_STEP+T_DUR after which |T-T_pre| stays < 5 K
    end_mask = t >= T_STEP + T_DUR
    end_t = t[end_mask]; end_T = T[end_mask]
    abs_err = np.abs(end_T - T_pre)
    bad = abs_err > 5.0
    if bad.any():
        idx_last_bad = int(np.where(bad)[0][-1])
        if idx_last_bad < len(end_t) - 1:
            t_settle = float(end_t[idx_last_bad + 1])
        else:
            t_settle = float("nan")
    else:
        t_settle = float(end_t[0])
    settle_after_step = t_settle - (T_STEP + T_DUR) if not np.isnan(t_settle) else float("nan")
    print(f"\n=== {m.TUBES[tube_key]['name']} step response ===")
    print(f"  Pre-step T (settled):  {T_pre:.2f} K")
    print(f"  Step:  +{p_step*1e3:.2f} mW ({STEP_PCT*100:.0f}% of P_op={spec['P_op']*1e3:.1f} mW) "
          f"for {T_DUR*1e3:.0f} ms at t={T_STEP:.2f}s")
    print(f"  Peak T after step:     {T_max:.2f} K at t={T_max_t:.3f}s  "
          f"(overshoot {T_max - T_pre:+.2f} K above pre-step)")
    print(f"  Min T after step:      {T_min:.2f} K at t={T_min_t:.3f}s  "
          f"(undershoot {T_min - T_pre:+.2f} K)")
    print(f"  Settled within +/-5 K of pre-step T at t={t_settle:.3f}s  "
          f"({settle_after_step*1e3:.0f} ms after step end)")
    return T_pre, T_max, T_min, t_settle


def plot(tube_key, r, T_pre):
    spec = m.TUBES[tube_key]
    p_step = STEP_PCT * spec["P_op"]
    t = r["t"] * 1e3   # ms
    fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
    axes[0].plot(t, r["T"], color="C3", lw=0.7)
    axes[0].axhline(T_pre, color="0.5", ls="--", lw=0.6, label=f"pre-step {T_pre:.1f} K")
    axes[0].axhline(T_pre + 5, color="0.7", ls=":", lw=0.5)
    axes[0].axhline(T_pre - 5, color="0.7", ls=":", lw=0.5)
    axes[0].axvspan(T_STEP*1e3, (T_STEP+T_DUR)*1e3, alpha=0.15, color="C0",
                    label=f"+{p_step*1e3:.1f} mW ({STEP_PCT*100:.0f}% of P_op)")
    axes[0].set_ylabel("T [K]")
    axes[0].set_title(f"{m.TUBES[tube_key]['name']}: closed-loop step response")
    axes[0].legend(loc="upper right", fontsize=9); axes[0].grid(True, alpha=0.4)
    axes[1].plot(t, r["v_i"], color="C4", lw=0.4)
    axes[1].axvspan(T_STEP*1e3, (T_STEP+T_DUR)*1e3, alpha=0.15, color="C0")
    axes[1].set_ylabel("v_int_out [V]")
    axes[1].grid(True, alpha=0.4)
    axes[2].plot(t, r["v_o"] - r["v_a"], color="C2", lw=0.3)
    axes[2].axvspan(T_STEP*1e3, (T_STEP+T_DUR)*1e3, alpha=0.15, color="C0")
    axes[2].set_ylabel("V_fil = v_osc_drive - v_ap_drive [V]")
    axes[2].set_xlabel("t [ms]")
    axes[2].grid(True, alpha=0.4)
    fig.tight_layout()
    out = HERE / f"step_response_{tube_key}.png"
    fig.savefig(out, dpi=120); plt.close(fig)
    print(f"  Wrote {out}")


def main():
    tubes = sys.argv[1:] or ["ilc11_7"]
    for tube in tubes:
        if tube not in m.TUBES:
            print(f"Unknown tube {tube}"); continue
        r = run_step(tube)
        T_pre, _, _, _ = analyse(tube, r)
        plot(tube, r, T_pre)


if __name__ == "__main__":
    main()
