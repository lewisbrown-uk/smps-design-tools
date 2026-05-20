"""Sweep r_int_scale for each tube and predict (f_crossover, PM, zeta) at each.
Goal: identify the scale that gives PM ~ 25-30° (matching IV-18 baseline)."""
import sys
sys.path.insert(0, '.')
import numpy as np
from closed_loop_analysis import (
    TUBES, compensator_tf, tube_op, plant_tf, analyse_loop
)

scales_to_try = {
    'IV-6':     [0.3, 0.5, 0.7, 1.0, 1.5, 2.0, 2.85],
    'ILC1-1/7': [0.3, 0.7, 1.0, 1.5, 1.98, 3.0],
    'ILC1-1/8': [0.3, 0.5, 0.7, 1.0, 1.5, 2.0, 3.0, 5.0, 7.2],
}

print(f"{'Tube':<10}  {'scale':>5}  {'f_cross':>8}  {'PM':>6}  {'zeta':>6}  {'tau_close':>9}  {'verdict'}")
print(f"{'':<10}  {'':>5}  {'[Hz]':>8}  {'[°]':>6}  {'':>6}  {'[ms]':>9}")
for tube_name, scales in scales_to_try.items():
    tube = dict(TUBES[tube_name])
    for s in scales:
        tube['r_int_scale'] = s
        op = tube_op(tube)
        if op is None: print(f"{tube_name:<10}  {s:>5.2f}  invalid OP"); continue
        K_DC, f_pole, G_p, _ = plant_tf(tube, op)
        G_c = compensator_tf(s)
        res = analyse_loop(G_c, G_p)
        # Find dominant closed-loop pole pair (max imag part)
        cl = res['cl_poles']
        complex_poles = [p for p in cl if abs(p.imag) > 1e-3]
        if complex_poles:
            p_dom = max(complex_poles, key=lambda p: abs(p))
            wn = abs(p_dom); zeta = -p_dom.real/wn
        else:
            zeta = 1.0; wn = abs(min(cl, key=lambda p: abs(p.real)))
        tau_close = 1/abs(min(cl, key=lambda p: abs(p.real)))*1000  # ms, dominant pole settling
        # Verdict
        if not np.isfinite(res['phase_margin_deg']) or res['phase_margin_deg'] < 5:
            verdict = 'BAD (PM too low)'
        elif res['phase_margin_deg'] < 20:
            verdict = 'underdamped'
        elif res['phase_margin_deg'] < 40:
            verdict = 'GOOD'
        elif res['phase_margin_deg'] < 60:
            verdict = 'over-damped'
        else:
            verdict = 'critically slow'
        print(f"{tube_name:<10}  {s:>5.2f}  {res['f_cross']:8.2f}  {res['phase_margin_deg']:6.1f}  {zeta:6.3f}  {tau_close:9.0f}  {verdict}")
    print()
