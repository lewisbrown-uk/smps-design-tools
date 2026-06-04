"""Sweep V_clamp_lo to find a value that (a) escapes the wrong-polarity
stable point on ILC1-1/7 and (b) doesn't over-clip natural OP on any tube.

Per-case: 2 s sim (enough for cold-start + settling), use realistic
op-amp Ilimit (lvl3 with 50/65 mA). Extract final v_int_out value.
"""
import sys, types, math, subprocess, re, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

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
from validate_cap_470nf_iv6max_level1 import swap_to_level1

tcl.T_END = 4.0  # ILC1-1/7 (r_int_scale=1.5) needs ~2.5 s to fully settle in good basin

def run_case(tube_key, vp_value, v_clamp_lo):
    spec = tcl.TUBES[tube_key]
    beta = 0.6e-3 / (vp_value ** 2)
    mc = {'r_amb': spec['r_amb'], 'sigma_eps_A': spec['sigma_eps_A'],
          'c_th': spec['c_th'], 'r_top_ref': spec['r_top_ref'],
          'r_bot_ref': spec['r_bot_ref'], 'r_sense': spec['r_sense'],
          'jfet_vp': vp_value, 'jfet_beta': beta, 't_rail_ramp': 100e-6,
          'v_clamp_lo': v_clamp_lo}
    for k in ('booster', 'ce_buf', 'mos_buf'):
        if spec.get(k): mc[k] = True
    for k in ('buf_fb1', 'buf_fb_ap', 'v_buf', 'c_ap'):
        if spec.get(k) is not None: mc[k] = spec[k]
    label = f"sweepclamp_{tube_key}_vp{abs(vp_value):.0f}_clo{int(v_clamp_lo*100):03d}"
    cir = tcl.WORK / f'{label}.cir'
    dat = tcl.WORK / f'{label}.data'
    raw = tcl.make_netlist(dat, v_preset=0.0, t_ramp=0.0,
                            r_int_scale=spec['r_int_scale'], mc=mc)
    if spec.get('mos_buf'):
        raw = swap_to_level1(raw)
    # Inject a measurement of final v_int_out (last 100 ms average) and
    # the loop's final T (last 100 ms average).
    # Last-sample measurements. Loop is at steady state by t=T_END for
    # ILC1-1/7 (r_int_scale=1.5 → settle ~1 s), so the last value is
    # representative. Use $&vec at the final index instead of slicing,
    # which nutmeg parses reliably.
    extras = """let n_last = length(v(v_int_out)) - 1
let vint_final = v(v_int_out)[n_last]
let temp_final = v(T_node)[n_last]
echo "MEAS_VINT:"
print vint_final
echo "MEAS_TEMP:"
print temp_final
"""
    raw = raw.replace('.endcontrol', extras + '.endcontrol', 1)
    raw = raw.replace('.control\n', '.control\nsave all\n', 1)
    cir.write_text(raw)
    t0 = time.time()
    res = subprocess.run(['ngspice', '-b', cir.name], cwd=tcl.WORK,
                          capture_output=True, text=True, timeout=2400)
    wall = time.time() - t0
    if res.returncode != 0:
        return {'tube': tube_key, 'vp': vp_value, 'clo': v_clamp_lo,
                'error': res.stderr[-300:], 'wall': wall}
    vint = temp = None
    cur = None
    for line in res.stdout.splitlines():
        if line.strip() == 'MEAS_VINT:': cur = 'vint'; continue
        if line.strip() == 'MEAS_TEMP:': cur = 'temp'; continue
        m = re.match(r'^\s*(vint_final|temp_final)\s*=\s*([-+0-9.eE]+)', line)
        if m and cur:
            if cur == 'vint': vint = float(m.group(2))
            else: temp = float(m.group(2))
            cur = None
    return {'tube': tube_key, 'vp': vp_value, 'clo': v_clamp_lo,
            'vint': vint, 'temp': temp, 'wall': wall}


def main():
    # With Schottky Dclamp, only V_clamp_lo=0.3 needs validating across tubes.
    clo_values = [0.3]
    cases = []
    for clo in clo_values:
        for tube in ('iv18', 'iv6', 'ilc11_7', 'ilc11_8'):
            for vp in (-1.0, -3.0):
                cases.append((tube, vp, clo))
    print(f"Running {len(cases)} cases in parallel...", flush=True)
    with ThreadPoolExecutor(max_workers=8) as ex:
        fut_to_case = {ex.submit(run_case, *c): c for c in cases}
        results = []
        for f in as_completed(fut_to_case):
            try:
                r = f.result()
            except Exception as e:
                c = fut_to_case[f]
                r = {'tube': c[0], 'vp': c[1], 'clo': c[2],
                     'error': f'{type(e).__name__}: {e}', 'wall': 0.0}
            results.append(r)
            if 'error' in r:
                print(f"  FAIL {r['tube']:8s} V_p={r['vp']:+.1f} clo={r['clo']:.2f} "
                      f"({r['wall']:.1f}s): {r['error'][:160]}", flush=True)
            else:
                vint = r['vint'] if r['vint'] is not None else float('nan')
                temp = r['temp'] if r['temp'] is not None else float('nan')
                basin = 'GOOD' if vint > 0.1 else 'BAD '
                print(f"  {r['tube']:8s} V_p={r['vp']:+.1f} clo={r['clo']:.2f} "
                      f"vint={vint:+.3f}V T={temp:.0f}K {basin} ({r['wall']:.1f}s)",
                      flush=True)

    # Table
    print()
    print(f"{'tube':10s}  {'V_p':>5s}  ", end='')
    for clo in clo_values: print(f" clo={clo:.2f}    ", end='')
    print()
    for tube in ('iv18', 'iv6', 'ilc11_7', 'ilc11_8'):
        for vp in (-1.0, -3.0):
            print(f"{tube:10s}  {vp:+.1f}  ", end='')
            for clo in clo_values:
                r = next((x for x in results if x['tube']==tube and x['vp']==vp and x['clo']==clo), None)
                if r and 'error' not in r and r['vint'] is not None:
                    basin = 'G' if r['vint'] > 0.1 else 'B'
                    print(f" {r['vint']:+.2f}V {basin}  ", end='')
                else:
                    print(f"   FAIL    ", end='')
            print()


if __name__ == '__main__':
    main()
