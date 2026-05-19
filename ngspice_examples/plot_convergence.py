"""Run one case per tube with wrdata enabled, plot V_int_out + T_node vs time
for visual verification of the PMOS architecture convergence. PNGs are
saved next to this script -- rsync back from hv3 to inspect.
"""
import sys, types, math, subprocess, re, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import test_closed_loop as tcl
from validate_cap_470nf_iv6max_level1 import swap_to_level1

tcl.T_END = 2.0


def run_case(tube_key):
    spec = tcl.TUBES[tube_key]
    mc = {'r_amb': spec['r_amb'], 'sigma_eps_A': spec['sigma_eps_A'],
          'c_th': spec['c_th'], 'r_top_ref': spec['r_top_ref'],
          'r_bot_ref': spec['r_bot_ref'], 'r_sense': spec['r_sense'],
          't_rail_ramp': 100e-6}  # realistic LDO soft-start (100 us); the
                                  # NMOS+level-shift arch removes the need
                                  # for the 500 ms rail-ramp mitigation.
    for k in ('booster', 'ce_buf', 'mos_buf'):
        if spec.get(k): mc[k] = True
    for k in ('buf_fb1', 'buf_fb_ap', 'v_buf', 'c_ap'):
        if spec.get(k) is not None: mc[k] = spec[k]

    label = f"conv_{tube_key}"
    cir = tcl.WORK / f'{label}.cir'
    dat = tcl.WORK / f'{label}.data'
    raw = tcl.make_netlist(dat, v_preset=0.0, t_ramp=0.0,
                            r_int_scale=spec['r_int_scale'], mc=mc)
    if spec.get('mos_buf'):
        # swap_to_level1 now skips M_var1/M_var2 (variable-R, must keep
        # manufacturer V_TO to match V_offset) and only swaps the heavier
        # bridge-driver MOSFETs to Level-1 for runtime. 2026-05-19.
        raw = swap_to_level1(raw)
    # Keep wrdata for these single-case runs (small set of signals -> manageable file size).
    cir.write_text(raw)
    t0 = time.time()
    res = subprocess.run(['ngspice', '-b', cir.name], cwd=tcl.WORK,
                          capture_output=True, text=True, timeout=1800)
    wall = time.time() - t0
    if res.returncode != 0:
        return {'tube': tube_key, 'error': res.stderr[-300:], 'wall': wall}
    d = np.loadtxt(dat)
    # wrdata columns: pairs of (time, value) per signal.
    n_sig = d.shape[1] // 2
    cols = ['v_osc_drive','v_ap_drive','node_A','node_B','n_diff','n_demout',
            'v_ctl','v_int_out','T_node','r_fil','v_int_raw','e_sat']
    r = {'t': d[:, 0]}
    for i, c in enumerate(cols[:n_sig]):
        r[c] = d[:, 2*i+1]
    try: dat.unlink()
    except: pass
    return {'tube': tube_key, 'wall': wall, 'data': r,
            'T_op': spec['T_op']}


def make_plot(results):
    # 4 rows (one per tube) x 2 cols: full T_END on left, zoomed 0-1s on right.
    # T peak is annotated -- the prior 4-up grid hid the cold-start thermal
    # overshoot when rendered at thumbnail size.
    fig, axes = plt.subplots(4, 2, figsize=(14, 14), sharex=False)
    fig.suptitle("NMOS+level-shift variable-R architecture: convergence per tube\n"
                 "(C_AP=1uF, T_END=2s, V_offset=+2.0V, V_clamp_lo=-0.7V, "
                 "manufacturer DMN3404L/DMP3098L, lvl3 op-amp)", fontsize=11)
    for idx, tube_key in enumerate(('iv3', 'iv6', 'ilc11_7', 'ilc11_8')):
        r = next((x for x in results if x['tube'] == tube_key), None)
        if r is None or 'error' in r:
            axes[idx][0].set_title(f"{tube_key}: FAIL")
            continue
        d = r['data']
        t = d['t']
        # Peak temperature: maximum across full transient
        T_peak = float(np.max(d['T_node']))
        T_peak_t = float(t[int(np.argmax(d['T_node']))])
        T_final = float(d['T_node'][-1])
        v_final = float(d['v_int_out'][-1])

        for col_idx, t_max in enumerate((2.0, 0.8)):
            ax = axes[idx][col_idx]
            ax2 = ax.twinx()
            mask = t <= t_max
            ax.plot(t[mask], d['v_int_out'][mask], color='tab:blue',
                    label='V_int_out (V)', linewidth=1.0)
            ax2.plot(t[mask], d['T_node'][mask], color='tab:red',
                     label='T_node (K)', linewidth=1.0)
            ax2.axhline(r['T_op'], color='tab:red', linestyle='--',
                        alpha=0.5)
            # Mark T peak in the panel if it falls in window
            if T_peak_t <= t_max:
                ax2.plot(T_peak_t, T_peak, 'rv', markersize=8)
                ax2.annotate(f"peak {T_peak:.0f} K  (+{T_peak-r['T_op']:.0f} K)",
                             xy=(T_peak_t, T_peak),
                             xytext=(8, -2), textcoords='offset points',
                             color='darkred', fontsize=9,
                             verticalalignment='top')
            zoom_txt = "(0-2s)" if col_idx == 0 else "(0-0.8s zoom)"
            ax.set_title(f"{tcl.TUBES[tube_key]['name']}  {zoom_txt}  --  "
                         f"V_final={v_final:+.3f}V, "
                         f"T_final={T_final:.0f}K "
                         f"({T_final-r['T_op']:+.1f}K), "
                         f"T_peak=+{T_peak-r['T_op']:.0f}K",
                         fontsize=9)
            ax.set_xlabel("time [s]")
            ax.set_ylabel("V_int_out [V]", color='tab:blue')
            ax2.set_ylabel("T_node [K]", color='tab:red')
            ax.tick_params(axis='y', labelcolor='tab:blue')
            ax2.tick_params(axis='y', labelcolor='tab:red')
            ax.grid(alpha=0.3)
            if col_idx == 0:
                h1, l1 = ax.get_legend_handles_labels()
                h2, l2 = ax2.get_legend_handles_labels()
                ax.legend(h1 + h2, l1 + l2 + [f"T_op = {r['T_op']:.0f} K"],
                          loc='lower right', fontsize=8)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    out = HERE / "pmos_convergence.png"
    fig.savefig(out, dpi=120)
    print(f"Wrote {out}", flush=True)
    return out


def main():
    print(f"Running 4 cases in parallel...", flush=True)
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(run_case, t): t for t in ('iv3', 'iv6', 'ilc11_7', 'ilc11_8')}
        results = []
        for f in as_completed(futs):
            try:
                r = f.result()
                results.append(r)
                if 'error' in r:
                    print(f"  FAIL {r['tube']}: {r['error'][:120]}", flush=True)
                else:
                    print(f"  OK   {r['tube']:8s} wall={r['wall']:.1f}s, "
                          f"n_samples={len(r['data']['t']):,}", flush=True)
            except Exception as e:
                print(f"  EXC: {e}", flush=True)
    make_plot(results)


if __name__ == '__main__':
    main()
