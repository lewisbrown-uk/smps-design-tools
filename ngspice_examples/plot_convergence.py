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

tcl.T_END = 4.0


def run_case(tube_key):
    spec = tcl.TUBES[tube_key]
    mc = {'r_amb': spec['r_amb'], 'sigma_eps_A': spec['sigma_eps_A'],
          'c_th': spec['c_th'], 'r_top_ref': spec['r_top_ref'],
          'r_bot_ref': spec['r_bot_ref'], 'r_sense': spec['r_sense'],
          't_rail_ramp': 100e-6}
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
        raw = swap_to_level1(raw)
    # Keep wrdata for these single-case runs (small set of signals -> manageable file size).
    cir.write_text(raw)
    t0 = time.time()
    res = subprocess.run(['ngspice', '-b', cir.name], cwd=tcl.WORK,
                          capture_output=True, text=True, timeout=900)
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
    fig, axes = plt.subplots(2, 2, figsize=(14, 9), sharex=False)
    fig.suptitle("PMOS variable-R architecture: convergence per tube\n"
                 "(C_AP=1uF, T_END=4s, t_rail_ramp=100us, lvl3 op-amp, "
                 "realistic Ilimit, Schottky Dclamp)", fontsize=11)
    for idx, tube_key in enumerate(('iv3', 'iv6', 'ilc11_7', 'ilc11_8')):
        ax = axes[idx // 2][idx % 2]
        r = next((x for x in results if x['tube'] == tube_key), None)
        if r is None or 'error' in r:
            ax.set_title(f"{tube_key}: FAIL")
            continue
        d = r['data']
        ax2 = ax.twinx()
        ax.plot(d['t'], d['v_int_out'], color='tab:blue',
                label='V_int_out (V)', linewidth=1.0)
        ax2.plot(d['t'], d['T_node'], color='tab:red',
                 label='T_node (K)', linewidth=1.0)
        ax2.axhline(r['T_op'], color='tab:red', linestyle='--',
                    alpha=0.5, label=f"T_op = {r['T_op']:.0f} K")
        # Pull last values for annotation
        v_final = d['v_int_out'][-1]
        T_final = d['T_node'][-1]
        T_over = T_final - r['T_op']
        ax.set_title(f"{tcl.TUBES[tube_key]['name']}  --  "
                     f"V_int_out_final = {v_final:+.3f} V, "
                     f"T_final = {T_final:.1f} K "
                     f"({T_over:+.1f} K from T_op)",
                     fontsize=10)
        ax.set_xlabel("time [s]")
        ax.set_ylabel("V_int_out [V]", color='tab:blue')
        ax2.set_ylabel("T_node [K]", color='tab:red')
        ax.tick_params(axis='y', labelcolor='tab:blue')
        ax2.tick_params(axis='y', labelcolor='tab:red')
        ax.grid(alpha=0.3)
        # Legend (combined)
        h1, l1 = ax.get_legend_handles_labels()
        h2, l2 = ax2.get_legend_handles_labels()
        ax.legend(h1 + h2, l1 + l2, loc='lower right', fontsize=9)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    out = HERE / "pmos_convergence.png"
    fig.savefig(out, dpi=110)
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
