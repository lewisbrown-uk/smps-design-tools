"""Sweep r_int_scale to map cold-start thermal overshoot vs integrator
slowness. Captures peak T_node (not just settled) via vecmax in ngspice
nutmeg. With PMOS variable-R the wrong-basin trap is gone, but cold-start
dynamic overshoot still exists on high-K_buf tubes (ILC1-1/7 at +121 K,
worst case).

Slower integrator => loop catches the bridge crossover sooner => less
dynamic overshoot, at the cost of longer settling. Goal: find an
r_int_scale per tube where peak T-T_op < ~30 K (below the lifetime-impact
threshold) while keeping settling time reasonable.
"""
import sys, types, math, subprocess, re, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

_np = types.ModuleType('numpy'); _np.pi = math.pi
_np.linspace=lambda *a,**k:[]; _np.int64=int; _np.loadtxt=lambda *a,**k:None
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

tcl.T_END = 6.0  # longer to capture settled value after slow-integrator overshoot recovery


def run_case(tube_key, r_int_scale):
    spec = tcl.TUBES[tube_key]
    mc = {'r_amb': spec['r_amb'], 'sigma_eps_A': spec['sigma_eps_A'],
          'c_th': spec['c_th'], 'r_top_ref': spec['r_top_ref'],
          'r_bot_ref': spec['r_bot_ref'], 'r_sense': spec['r_sense'],
          't_rail_ramp': 100e-6}
    for k in ('booster', 'ce_buf', 'mos_buf'):
        if spec.get(k): mc[k] = True
    for k in ('buf_fb1', 'buf_fb_ap', 'v_buf', 'c_ap'):
        if spec.get(k) is not None: mc[k] = spec[k]
    label = f"rsweep_{tube_key}_s{int(r_int_scale*10):03d}"
    cir = tcl.WORK / f'{label}.cir'
    dat = tcl.WORK / f'{label}.data'
    raw = tcl.make_netlist(dat, v_preset=0.0, t_ramp=0.0,
                            r_int_scale=r_int_scale, mc=mc)
    if spec.get('mos_buf'):
        raw = swap_to_level1(raw)
    # Add peak-T extraction + final-state extraction.
    extras = """let n_last = length(v(T_node)) - 1
let T_peak = vecmax(v(T_node))
let T_final = v(T_node)[n_last]
let V_final = v(v_int_out)[n_last]
echo "MEAS_PEAK:"
print T_peak
echo "MEAS_TFINAL:"
print T_final
echo "MEAS_VFINAL:"
print V_final
"""
    # Drop wrdata for memory budget
    raw = re.sub(r'^wrdata\s+\S+.*$', '* wrdata suppressed', raw, count=1, flags=re.MULTILINE)
    raw = raw.replace('.control\n', '.control\nsave v(T_node) v(v_int_out)\n', 1)
    raw = raw.replace('.endcontrol', extras + '.endcontrol', 1)
    cir.write_text(raw)
    t0 = time.time()
    res = subprocess.run(['ngspice', '-b', cir.name], cwd=tcl.WORK,
                          capture_output=True, text=True, timeout=1800)
    wall = time.time() - t0
    if res.returncode != 0:
        return {'tube': tube_key, 'r_int_scale': r_int_scale,
                'error': res.stderr[-300:], 'wall': wall}
    T_peak = T_final = V_final = None
    cur = None
    for line in res.stdout.splitlines():
        s = line.strip()
        if s == 'MEAS_PEAK:': cur = 'p'; continue
        if s == 'MEAS_TFINAL:': cur = 't'; continue
        if s == 'MEAS_VFINAL:': cur = 'v'; continue
        m = re.match(r'^\s*(?:T_peak|t_peak|T_final|t_final|V_final|v_final)\s*=\s*([-+0-9.eE]+)', line)
        if m and cur:
            val = float(m.group(1))
            if cur == 'p': T_peak = val
            elif cur == 't': T_final = val
            elif cur == 'v': V_final = val
            cur = None
    return {'tube': tube_key, 'r_int_scale': r_int_scale, 'wall': wall,
            'T_peak': T_peak, 'T_final': T_final, 'V_final': V_final,
            'T_op': spec['T_op']}


def main():
    # Concentrate on ILC1-1/7 (worst overshoot) first. Compare with current 1.5.
    # Then also check IV-6 and ILC1-1/8 at their current vs 2x.
    cases = []
    for s in (1.5, 3.0, 5.0, 8.0):
        cases.append(('ilc11_7', s))
    for s in (0.7, 1.5, 3.0):
        cases.append(('iv6', s))
        cases.append(('ilc11_8', s))
    for s in (0.5, 1.0, 2.0):
        cases.append(('iv18', s))
    print(f"Running {len(cases)} cases (max_workers=4)...", flush=True)
    with ThreadPoolExecutor(max_workers=4) as ex:
        fut_to_case = {ex.submit(run_case, *c): c for c in cases}
        results = []
        for f in as_completed(fut_to_case):
            try:
                r = f.result()
            except Exception as e:
                c = fut_to_case[f]
                r = {'tube': c[0], 'r_int_scale': c[1],
                     'error': f'{type(e).__name__}: {e}', 'wall': 0.0}
            results.append(r)
            if 'error' in r:
                print(f"  FAIL {r['tube']:8s} scale={r['r_int_scale']:.1f} "
                      f"({r['wall']:.0f}s): {r['error'][:120]}", flush=True)
            elif r.get('T_peak') is None or r.get('T_final') is None:
                print(f"  PARSE-FAIL {r['tube']:8s} scale={r['r_int_scale']:.1f} "
                      f"({r['wall']:.0f}s): T_peak={r.get('T_peak')} "
                      f"T_final={r.get('T_final')} -- check stdout parsing", flush=True)
            else:
                Tp = r['T_peak']; Tf = r['T_final']; Vf = r['V_final']
                Top = r['T_op']
                over = Tp - Top
                final_err = Tf - Top
                verdict = 'BIG' if over > 50 else ('OK ' if over > 20 else 'GOOD')
                print(f"  {r['tube']:8s} scale={r['r_int_scale']:>4.1f}  "
                      f"T_peak={Tp:.0f}K (+{over:.0f}K) "
                      f"T_final={Tf:.0f}K ({final_err:+.1f}K) "
                      f"V_final={Vf:+.3f}V  {verdict} ({r['wall']:.0f}s)",
                      flush=True)
    # Summary per tube
    print()
    for tube in ('iv18', 'iv6', 'ilc11_7', 'ilc11_8'):
        tr = sorted((r for r in results if r['tube'] == tube
                     and 'error' not in r and r.get('T_peak') is not None),
                    key=lambda r: r['r_int_scale'])
        print(f"--- {tube} ---")
        for r in tr:
            print(f"  scale={r['r_int_scale']:>4.1f}  "
                  f"T_peak=+{r['T_peak']-r['T_op']:.0f}K  "
                  f"T_final={r['T_final']-r['T_op']:+.1f}K")


if __name__ == '__main__':
    main()
