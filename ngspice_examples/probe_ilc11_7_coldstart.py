"""ILC1-1/7 cold-start probe: 1.5 s, manufacturer DMP3098L (no Level-1 swap).
Saves V_int_out, V_int_raw, V_ctl, V(n_var_mid), v_drv_atten, n_ap_plus,
v_d (= node_A - node_B differential), v_demout, T_node, R_fil at full
adaptive timestep resolution so we can later reconstruct V_GS(t),
R_DS(t), and the closed-loop dynamics during the cold-start spike.

Result: a single `probe_ilc11_7_coldstart.data` file.
"""
import sys, types, math, subprocess, re, time
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import test_closed_loop as tcl

T_END = 1.5  # seconds (captures the peak and recovery into mid-trajectory)
tcl.T_END = T_END

tube_key = 'ilc11_7'
spec = tcl.TUBES[tube_key]
mc = {'r_amb': spec['r_amb'], 'sigma_eps_A': spec['sigma_eps_A'],
      'c_th': spec['c_th'], 'r_top_ref': spec['r_top_ref'],
      'r_bot_ref': spec['r_bot_ref'], 'r_sense': spec['r_sense'],
      't_rail_ramp': 100e-6}
for k in ('booster', 'ce_buf', 'mos_buf'):
    if spec.get(k): mc[k] = True
for k in ('buf_fb1', 'buf_fb_ap', 'v_buf', 'c_ap'):
    if spec.get(k) is not None: mc[k] = spec[k]

label = f"probe_{tube_key}_coldstart"
cir = tcl.WORK / f'{label}.cir'
dat = tcl.WORK / f'{label}.data'
raw = tcl.make_netlist(dat, v_preset=0.0, t_ramp=0.0,
                        r_int_scale=spec['r_int_scale'], mc=mc)
# ILC1-1/7 has no mos_buf, so manufacturer DMP3098L/DMN3404L is already in use.
# Add probes we need that aren't in the default .save / wrdata list.
extra_save = "save v(n_var_mid) v(v_drv_atten) v(n_ap_plus) v(v_ap)\n"
raw = raw.replace('.control\n', '.control\n' + extra_save, 1)
# Replace the wrdata line so we also write our new probes.
old_wr_re = re.compile(r'^wrdata\s+(\S+).*$', re.MULTILINE)
match = old_wr_re.search(raw)
if match is None:
    raise RuntimeError("Could not find wrdata line to extend.")
new_signals = ("v(v_osc_drive) v(v_ap_drive) v(node_A) v(node_B) v(n_diff) "
               "v(n_demout) v(v_ctl) v(v_int_out) v(T_node) v(r_fil) "
               "v(v_int_raw) v(e_sat) v(n_var_mid) v(v_drv_atten) "
               "v(n_ap_plus) v(v_ap)")
raw = old_wr_re.sub(f"wrdata {match.group(1)} {new_signals}", raw, count=1)
cir.write_text(raw)
print(f"Wrote {cir}; T_END={T_END} s; running on hv3...", flush=True)
t0 = time.time()
res = subprocess.run(['ngspice', '-b', cir.name], cwd=tcl.WORK,
                     capture_output=True, text=True, timeout=14400)
wall = time.time() - t0
print(f"ngspice exit={res.returncode} wall={wall:.1f} s", flush=True)
if res.returncode != 0:
    sys.stderr.write(res.stderr[-1500:])
    sys.exit(1)
print(f"Data file: {dat}; size={dat.stat().st_size/1e6:.1f} MB", flush=True)
print("STDOUT tail:", flush=True)
print(res.stdout[-500:], flush=True)
