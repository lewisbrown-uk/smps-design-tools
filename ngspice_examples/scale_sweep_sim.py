"""Empirical r_int_scale sweep at V_p=-1.5 for IV-6 and ILC1-1/8.
T_END scales with r_int_scale to ensure each sim runs long enough to
characterize settling time (4x expected settle, min 6s).
"""
import sys, subprocess, time
sys.path.insert(0, '.')
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
from test_closed_loop import TUBES, make_netlist, WORK
from diag_ilc7_peak import patch_extra_signals
from validate_cap_470nf_iv6max_level1 import swap_to_level1
import test_closed_loop as tcl

# Per-case T_END proportional to scale
def run_case(tube_key, scale):
    tcl.T_END = max(4.0 * scale, 6.0)
    spec = TUBES[tube_key]
    mc = {'r_amb': spec['r_amb'], 'sigma_eps_A': spec['sigma_eps_A'], 'c_th': spec['c_th'],
          'r_top_ref': spec['r_top_ref'], 'r_bot_ref': spec['r_bot_ref'], 'r_sense': spec['r_sense'],
          'c_ap': 470e-9 if tube_key != 'iv3' else 100e-9, 'jfet_vp': -1.5}
    if spec.get('booster'): mc['booster'] = True
    if spec.get('buf_fb1') is not None: mc['buf_fb1'] = spec['buf_fb1']
    if spec.get('buf_fb_ap') is not None: mc['buf_fb_ap'] = spec['buf_fb_ap']
    if spec.get('v_buf') is not None: mc['v_buf'] = spec['v_buf']
    if spec.get('ce_buf'): mc['ce_buf'] = True
    if spec.get('mos_buf'): mc['mos_buf'] = True
    label = f'sweep_{tube_key}_s{int(scale*100):03d}'
    cir = WORK / f'{label}.cir'; dat = WORK / f'{label}.data'
    raw = make_netlist(dat, v_preset=0.0, t_ramp=0.0, r_int_scale=scale, mc=mc)
    patched = patch_extra_signals(raw)
    if spec.get('mos_buf'): patched = swap_to_level1(patched)
    cir.write_text(patched)
    t0 = time.time()
    res = subprocess.run(['ngspice','-b',cir.name], cwd=WORK, capture_output=True, text=True)
    wall = time.time() - t0
    if res.returncode != 0:
        print(f'FAIL {tube_key} scale={scale}: {res.stderr[-300:]}'); return None
    d = np.loadtxt(dat)
    try: dat.unlink()
    except: pass
    n_sig = d.shape[1]//2
    cols = ['v_osc_drive','v_ap_drive','node_A','node_B','n_diff','n_demout','v_ctl','v_int_out','T_node','r_fil','v_int_raw','e_sat','i_clamp_lo','i_clamp_hi','n_int_minus','n_int_pidp']
    r = {'t': d[:,0]}
    for i, c in enumerate(cols[:n_sig]): r[c] = d[:, 2*i+1]
    np.savez(f'{label}.npz', **r)
    print(f'{tube_key} scale={scale} T_END={tcl.T_END:.1f}s wall={wall/60:.1f} min', flush=True)

if __name__ == '__main__':
    # Target PM 20-30° per the analytical sweep.
    # IV-6: scale 0.7-2.0; ILC1-1/8: scale 0.7-2.0 (way smaller than commented 7.2)
    cases = []
    cases += [('iv6', s) for s in (0.7, 1.0, 1.5, 2.0)]
    cases += [('ilc11_8', s) for s in (0.7, 1.0, 1.5, 2.0)]
    cases += [('ilc11_7', s) for s in (1.0, 1.5)]  # already have 1.98
    print(f'Running {len(cases)} cases in parallel...', flush=True)
    with ThreadPoolExecutor(max_workers=len(cases)) as ex:
        futs = [ex.submit(run_case, *c) for c in cases]
        for f in as_completed(futs):
            try: f.result()
            except Exception as e: print(f'EXC: {e}')
    print('done')
