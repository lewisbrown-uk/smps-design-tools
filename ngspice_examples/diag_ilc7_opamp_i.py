"""One-shot dump for ILC1-1/7 V_p=-3: write i(v_im_inv), i(v_im_buf0),
i(v_im_int) to a wrdata column so we can see when the peaks occur.
"""
import sys, types, math, subprocess, re
_np = types.ModuleType('numpy'); _np.pi = math.pi
_np.linspace = lambda *a,**k:[]; _np.int64=int; _np.loadtxt=lambda *a,**k:None
_np.where=lambda *a,**k:([],); _np.abs=abs
_np.full=lambda *a,**k:None; _np.full_like=lambda *a,**k:None
_np.nan=float('nan'); _np.nanmean=lambda *a,**k:0; _np.array=lambda *a,**k:[]
_np.random=types.SimpleNamespace(default_rng=lambda s:None)
sys.modules['numpy']=_np
_mpl=types.ModuleType('matplotlib'); _mpl.use=lambda *a,**k:None
sys.modules['matplotlib']=_mpl
sys.modules['matplotlib.pyplot']=types.ModuleType('matplotlib.pyplot')
sys.path.insert(0, '.')
import test_closed_loop as tcl
from verify_opamp_currents import patch_with_ammeters
from validate_cap_470nf_iv6max_level1 import swap_to_level1
from pathlib import Path

tcl.T_END = 4.0
spec = tcl.TUBES['ilc11_7']
I_DSS_mid = 0.6e-3
beta = I_DSS_mid / (3.0**2)
mc = {'r_amb': spec['r_amb'], 'sigma_eps_A': spec['sigma_eps_A'],
      'c_th': spec['c_th'], 'r_top_ref': spec['r_top_ref'],
      'r_bot_ref': spec['r_bot_ref'], 'r_sense': spec['r_sense'],
      'jfet_vp': -3.0, 'jfet_beta': beta, 't_rail_ramp': 0.010,
      'booster': True, 'buf_fb1': spec['buf_fb1'],
      'buf_fb_ap': spec['buf_fb_ap'], 'v_buf': spec['v_buf']}
if spec.get('ce_buf'): mc['ce_buf'] = True
if spec.get('mos_buf'): mc['mos_buf'] = True

raw = tcl.make_netlist(tcl.WORK / 'diag_ilc7_oai.data', v_preset=0.0,
                        t_ramp=0.0, r_int_scale=spec['r_int_scale'], mc=mc)
if spec.get('mos_buf'):
    raw = swap_to_level1(raw)
patched, names = patch_with_ammeters(raw)
# Replace the wrdata line with one that also writes our V_im_ currents and the
# control / integrator / drive voltages so we can correlate.
new_wrdata = ("wrdata /home/lewisbrown/claude-code/smps-design-tools/ngspice_examples/"
              "_closedloop_test/diag_ilc7_oai.data "
              "v(v_int_out) v(v_ctl) v(v_drv_atten) v(v_int_raw) v(n_inv_plus) "
              "v(n_inv_minus) v(n_int_minus) v(node_A) v(node_B) "
              "i(v_im_inv) i(v_im_buf0) i(v_im_int)")
patched = re.sub(r"^wrdata .*$", new_wrdata, patched, count=1, flags=re.MULTILINE)

cir = tcl.WORK / 'diag_ilc7_oai.cir'
cir.write_text(patched)
print(f'Running {cir}...')
res = subprocess.run(['ngspice', '-b', cir.name], cwd=tcl.WORK,
                     capture_output=True, text=True, timeout=600)
print(f'rc={res.returncode}, stdout last 300 chars: ...{res.stdout[-300:]}')
print(f'stderr last 300 chars: ...{res.stderr[-300:]}')
