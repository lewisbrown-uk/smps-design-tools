"""Validate the J201 retrofit: 4 tubes × 2 V_p corners, with new defaults
(JMMBFJ201, C_AP = 220 nF, IV-3 on booster+mos_buf, all r_int_scale = 0.3)."""
import sys, subprocess, time
sys.path.insert(0, '.')
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
from test_closed_loop import TUBES, make_netlist, WORK
from diag_ilc7_peak import patch_extra_signals
from validate_cap_470nf_iv6max_level1 import swap_to_level1

def run_case(tube_key, vp_label, vp_value):
    spec = TUBES[tube_key]
    # Beta scales with V_p assuming I_DSS in middle of spec band -- so for
    # V_p=-0.3 use higher beta, V_p=-1.5 use lower beta. I_DSS_mid = 0.6 mA.
    I_DSS_mid = 0.6e-3
    beta = I_DSS_mid / (vp_value**2)
    mc = {'r_amb': spec['r_amb'], 'sigma_eps_A': spec['sigma_eps_A'], 'c_th': spec['c_th'],
          'r_top_ref': spec['r_top_ref'], 'r_bot_ref': spec['r_bot_ref'], 'r_sense': spec['r_sense'],
          'jfet_vp': vp_value, 'jfet_beta': beta}
    if spec.get('booster'): mc['booster'] = True
    if spec.get('buf_fb1') is not None: mc['buf_fb1'] = spec['buf_fb1']
    if spec.get('buf_fb_ap') is not None: mc['buf_fb_ap'] = spec['buf_fb_ap']
    if spec.get('v_buf') is not None: mc['v_buf'] = spec['v_buf']
    if spec.get('ce_buf'): mc['ce_buf'] = True
    if spec.get('mos_buf'): mc['mos_buf'] = True
    label = f'j201_{tube_key}_vp{vp_label}'
    cir = WORK / f'{label}.cir'; dat = WORK / f'{label}.data'
    raw = make_netlist(dat, v_preset=0.0, t_ramp=0.0, r_int_scale=spec['r_int_scale'], mc=mc)
    patched = patch_extra_signals(raw)
    if spec.get('mos_buf'): patched = swap_to_level1(patched)
    cir.write_text(patched)
    t0 = time.time()
    res = subprocess.run(['ngspice','-b',cir.name], cwd=WORK, capture_output=True, text=True)
    if res.returncode != 0:
        print(f'FAIL {tube_key} vp={vp_value}: {res.stderr[-400:]}'); return
    d = np.loadtxt(dat)
    try: dat.unlink()
    except: pass
    n_sig = d.shape[1]//2
    cols = ['v_osc_drive','v_ap_drive','node_A','node_B','n_diff','n_demout','v_ctl','v_int_out','T_node','r_fil','v_int_raw','e_sat','i_clamp_lo','i_clamp_hi','n_int_minus','n_int_pidp']
    r = {'t': d[:,0]}
    for i, c in enumerate(cols[:n_sig]): r[c] = d[:, 2*i+1]
    np.savez(f'{label}.npz', **r)
    print(f'{tube_key} V_p={vp_value} beta={beta*1e3:.2f}m wall={(time.time()-t0)/60:.1f}min', flush=True)

if __name__ == '__main__':
    cases = [(t, l, v) for t in ('iv3','iv6','ilc11_7','ilc11_8') for l,v in (('typ',-0.9),('max',-1.5))]
    print(f'Running {len(cases)} cases (J201, C_AP=220nF, r_int_scale=0.3)...', flush=True)
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(run_case, *c) for c in cases]
        for f in as_completed(futs):
            try: f.result()
            except Exception as e: print(f'EXC: {e}')
    print('done')
