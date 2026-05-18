"""Sweep V_clamp_hi to test the structural fix: lower the cold-start
ceiling so the integrator can't wind up past the slew-bounded recovery
distance, which was driving the loop into the wrong-polarity basin
under realistic op-amp Ilimit.

Per-case: 4 s sim (enough for ILC1-1/7 with r_int_scale=1.5 to settle),
lvl3 op-amp model with realistic Ilimit (50 mA chopper / 65 mA std),
Schottky Dclamp (already in source), C_intfb = 318 nF (reverted from
the 64 nF experiment that made no difference), t_rail_ramp = 100 us
(realistic LDO/buck startup).

Tests V_p = -1, -3, -5 corners (the J112 spec range), so we verify
that lowering V_clamp_hi doesn't cripple the V_p = -5 worst-case
delivery.
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

tcl.T_END = 4.0

def run_case(tube_key, vp_value, v_clamp_hi):
    spec = tcl.TUBES[tube_key]
    beta = 0.6e-3 / (vp_value ** 2)
    mc = {'r_amb': spec['r_amb'], 'sigma_eps_A': spec['sigma_eps_A'],
          'c_th': spec['c_th'], 'r_top_ref': spec['r_top_ref'],
          'r_bot_ref': spec['r_bot_ref'], 'r_sense': spec['r_sense'],
          'jfet_vp': vp_value, 'jfet_beta': beta, 't_rail_ramp': 100e-6,
          'v_clamp_hi': v_clamp_hi}
    for k in ('booster', 'ce_buf', 'mos_buf'):
        if spec.get(k): mc[k] = True
    for k in ('buf_fb1', 'buf_fb_ap', 'v_buf', 'c_ap'):
        if spec.get(k) is not None: mc[k] = spec[k]

    label = f"swcli_{tube_key}_vp{abs(vp_value):.0f}_chi{int(v_clamp_hi*10):03d}"
    cir = tcl.WORK / f'{label}.cir'
    dat = tcl.WORK / f'{label}.data'
    raw = tcl.make_netlist(dat, v_preset=0.0, t_ramp=0.0,
                            r_int_scale=spec['r_int_scale'], mc=mc)
    if spec.get('mos_buf'):
        raw = swap_to_level1(raw)
    extras = """let n_last = length(v(v_int_out)) - 1
let vint_final = v(v_int_out)[n_last]
let temp_final = v(T_node)[n_last]
echo "MEAS_VINT:"
print vint_final
echo "MEAS_TEMP:"
print temp_final
"""
    # Drop the wrdata line entirely -- we only need final-sample scalars,
    # writing the full transient to disk burns ~300 MB per case (~2.4 GB of
    # disk cache across 8 parallel workers, which hits hv3's 6 GB cgroup
    # soft throttle and slows every worker to a crawl).
    raw = re.sub(r'^wrdata\s+\S+.*$', '* wrdata suppressed for memory budget',
                 raw, count=1, flags=re.MULTILINE)
    raw = raw.replace('.endcontrol', extras + '.endcontrol', 1)
    raw = raw.replace('.control\n', '.control\nsave v(v_int_out) v(T_node)\n', 1)
    cir.write_text(raw)
    t0 = time.time()
    res = subprocess.run(['ngspice', '-b', cir.name], cwd=tcl.WORK,
                          capture_output=True, text=True, timeout=900)
    wall = time.time() - t0
    if res.returncode != 0:
        return {'tube': tube_key, 'vp': vp_value, 'chi': v_clamp_hi,
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
    # Free up the big wrdata file once we have the scalars we need
    try:
        if dat.exists():
            dat.unlink()
    except: pass
    return {'tube': tube_key, 'vp': vp_value, 'chi': v_clamp_hi,
            'vint': vint, 'temp': temp, 'wall': wall}


def main():
    chi_values = [6.0]  # match the HEAD-committed reference (natural OP for iv6 V_p=-3 is +1.56V, so +3V was clipping)
    cases = []
    for chi in chi_values:
        for tube in ('iv3', 'iv6', 'ilc11_7', 'ilc11_8'):
            for vp in (-1.0, -3.0, -5.0):
                cases.append((tube, vp, chi))
    print(f"Running {len(cases)} cases (max_workers=4 to fit cgroup memory cap)...", flush=True)
    with ThreadPoolExecutor(max_workers=4) as ex:
        fut_to_case = {ex.submit(run_case, *c): c for c in cases}
        results = []
        for f in as_completed(fut_to_case):
            try:
                r = f.result()
            except Exception as e:
                c = fut_to_case[f]
                r = {'tube': c[0], 'vp': c[1], 'chi': c[2],
                     'error': f'{type(e).__name__}: {e}', 'wall': 0.0}
            results.append(r)
            if 'error' in r:
                print(f"  FAIL {r['tube']:8s} V_p={r['vp']:+.1f} chi={r['chi']:.1f} "
                      f"({r['wall']:.1f}s): {r['error'][:160]}", flush=True)
            else:
                vint = r['vint'] if r['vint'] is not None else float('nan')
                temp = r['temp'] if r['temp'] is not None else float('nan')
                # GOOD: vint positive AND T within ~30 K of T_op
                basin = 'GOOD' if (vint > 0.05 and abs(temp - 800) < 40) else 'BAD '
                print(f"  {r['tube']:8s} V_p={r['vp']:+.1f} chi={r['chi']:.1f} "
                      f"vint={vint:+.3f}V T={temp:.0f}K {basin} ({r['wall']:.1f}s)",
                      flush=True)
    print()
    print(f"{'tube':10s}  {'V_p':>5s}  ", end='')
    for chi in chi_values: print(f" chi={chi:.1f}        ", end='')
    print()
    for tube in ('iv3', 'iv6', 'ilc11_7', 'ilc11_8'):
        for vp in (-1.0, -3.0, -5.0):
            print(f"{tube:10s}  {vp:+.1f}  ", end='')
            for chi in chi_values:
                r = next((x for x in results if x['tube']==tube and x['vp']==vp and x['chi']==chi), None)
                if r and 'error' not in r and r['vint'] is not None:
                    bad_thermal = abs(r['temp'] - 800) >= 40
                    bad_basin = r['vint'] <= 0.05
                    flag = 'B' if (bad_thermal or bad_basin) else 'G'
                    print(f"  {r['vint']:+.2f}V {r['temp']:>4.0f}K {flag}", end='')
                else:
                    print(f"     FAIL       ", end='')
            print()


if __name__ == '__main__':
    main()
