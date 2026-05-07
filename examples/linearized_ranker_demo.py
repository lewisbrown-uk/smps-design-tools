"""In-circuit ranking via Linearized — shows where it diverges from
algebraic ranking, and why it's tractable where Robust isn't.

Topology: 1st-order RC low-pass driving an NE5532 unity-gain buffer.
The buffer has explicit input capacitance ``Cin`` (NE5532 typical
~5 pF) modelled as a cap from the filter node to ground.

  Vin ── R ──┬── nfilt ── XU1 (NE5532 buffer) ── out
              │      │
              C      Cin = 5 pF (op-amp input C)
              │      │
              GND   GND

The algebraic transfer function is ``fc = 1/(2π·R·C)`` — assumes the
buffer is ideal (zero input capacitance). In reality the effective
filter cap is ``C + Cin`` and the in-circuit fc is shifted from
algebraic by:

  fc_actual / fc_algebraic = C / (C + Cin)

For target fc = 100 kHz with Cin = 5 pF:

- R = 1 kΩ,    C = 1.59 nF   →  fc_actual ≈ 99.7 kHz   (−0.3% shift)
- R = 10 kΩ,   C = 159 pF    →  fc_actual ≈ 96.9 kHz   (−3.1% shift)
- R = 100 kΩ,  C = 15.9 pF   →  fc_actual ≈ 76.4 kHz   (−24% — fail spec)

The algebraic ranker can't distinguish the three; they all hit the
algebraic target exactly. The in-circuit ranker prefers low-R / high-C
— Cin is dominated when C >> Cin. With realistic R/C tolerances on
top of the systematic shift, yield collapses fast as C approaches Cin.

This script runs three rankings:

1. **Algebraic Linearized**: closed-form `fc = 1/(2πRC)` + sensitivity
   analysis. Many candidates tie at high yield because the algebraic
   metric can't see Rin.
2. **In-circuit Linearized**: ngspice .ac with NE5532 buffer (Rin=
   100 kΩ explicit). Same sensitivity analysis machinery, but the
   metric now includes the buffer loading. Yield drops at high-R.
3. **In-circuit Robust** (top-3 only): ngspice .ac + full MC, used as
   the gold standard for validation. Should agree with #2 on the
   ranking and yield estimates, at 50× the cost.

Lesson: Linearized makes in-circuit ranking on the full grid
tractable. Robust is right but expensive; Linearized is fast and
agrees on the ranking when the metric is locally smooth.
"""
from __future__ import annotations

import math
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.eseries_opt import Problem, Resistor, Capacitor
from utils.tolerance import (
    NgspiceBackend, CachedBackend, Linearized, Robust,
)


HERE = os.path.dirname(os.path.abspath(__file__))
UOPAMP_LIB = os.path.abspath(os.path.join(
    HERE, "..", "ngspice_examples", "uopamp.lib"
))


TARGET_FC = 100e3   # 100 kHz
SPEC_TOL = 0.05     # ±5%


def make_template():
    """1st-order RC LPF + NE5532 buffer with explicit input capacitance.
    Cin=5pF models the NE5532's typical Ci spec. With negative feedback
    the differential Rin sees ~zero voltage across it and doesn't load,
    so Cin is the binding non-ideality."""
    return f"""* RC LPF + NE5532 buffer (Cin parallel with C shifts in-circuit fc)
.include {UOPAMP_LIB}

Vin   in    0      AC 1
R1    in    nfilt  {{R}}
C1    nfilt 0      {{C}}
Cin   nfilt 0      5p

Vcc   vcc   0      15
Vee   vee   0     -15
XU1   nfilt out vcc vee out  uopamp_lvl2
+     Avol=100k GBW=10meg Rin=100k Rout=30 Iq=8m
+     Ilimit=20m Vrail=1.4 Vmax=40

.ac dec 50 1k 10meg

.control
run
let mag_db = 20*log10(vm(out)/vm(in))
meas ac fc when mag_db=-3
print fc
.endc
.end
"""


def make_problem(fc_expr, tol=SPEC_TOL):
    """Two-sided fixed-target spec built as twin margin metrics so
    the spec compares against TARGET_FC absolutely (not the
    candidate's own nominal, which is what 'within' would do).

    fc_above_min = fc - TARGET_FC·(1−tol)  must be > 0
    fc_below_max = TARGET_FC·(1+tol) − fc  must be > 0

    Both are linear in fc, so they're linear in (R, C) at first order
    too — clean for the Linearized ranker. The optimisation target
    'fc' is added with metric="rel" so the algebraic error column
    measures distance to TARGET_FC."""
    p = Problem()
    p.add(Resistor("R", e_series=12, range=(1e3, 100e3)))
    p.add(Capacitor("C", e_series=12, range=(10e-12, 10e-9)))
    p.add_target("fc", fc_expr, target=TARGET_FC, weight=0.0)
    p.add_target("fc_above_min",
                  lambda **v: fc_expr(**v) - TARGET_FC * (1 - tol),
                  target=0, metric="abs", weight=0.0)
    p.add_target("fc_below_max",
                  lambda **v: TARGET_FC * (1 + tol) - fc_expr(**v),
                  target=0, metric="abs", weight=0.0)
    return p


SPEC = {"fc_above_min": (">", 0), "fc_below_max": (">", 0)}


def main():
    # ---- 1. Algebraic Linearized
    print("=" * 72)
    print("1. Algebraic Linearized ranker (fc = 1/(2πRC); ignores buffer Rin)")
    print("=" * 72)
    fc_alg = lambda R, C: 1 / (2 * math.pi * R * C)
    p_alg = make_problem(fc_alg)
    t0 = time.perf_counter()
    alg = p_alg.solve(strategy="brute", n_results=10,
                       rank=Linearized(
                           passive_tolerances={"R": 0.01, "C": 0.05},
                           spec=SPEC))
    print(f"  ranked in {time.perf_counter()-t0:.2f}s\n")
    print(f"  {'rank':>4s}  {'R':>10s}  {'C':>10s}  {'fc_alg':>11s}  "
          f"{'yield':>8s}")
    for i, c in enumerate(alg, 1):
        fc_val = fc_alg(**c.values)
        print(f"  {i:>4d}  {_fmt(c.values['R'], 'Ω'):>10s}  "
              f"{_fmt(c.values['C'], 'F'):>10s}  "
              f"{_fmt(fc_val, 'Hz'):>11s}  "
              f"{c.yield_pct:>7.2f}%")
    print()

    # ---- 2. In-circuit Linearized
    print("=" * 72)
    print("2. In-circuit Linearized ranker (ngspice .ac with NE5532 buffer)")
    print("=" * 72)
    backend = NgspiceBackend(template=make_template(),
                              outputs=["fc"], timeout=10)
    cached = CachedBackend(backend, path="/tmp/linearized_demo.sqlite")
    def in_circuit_fc(R, C):
        r = cached(R=R, C=C)
        return r["fc"]
    in_circuit_fc.signature = lambda: cached.signature

    p2 = make_problem(in_circuit_fc)

    t0 = time.perf_counter()
    ic = p2.solve(strategy="brute", n_results=10,
                   rank=Linearized(
                       passive_tolerances={"R": 0.01, "C": 0.05},
                       spec=SPEC, eps_frac=0.20))
    dt_lin = time.perf_counter() - t0
    print(f"  ranked in {dt_lin:.2f}s  "
          f"({cached.misses} ngspice calls, {cached.hits} cache hits)\n")
    print(f"  {'rank':>4s}  {'R':>10s}  {'C':>10s}  {'fc_ic':>11s}  "
          f"{'fc_dev':>8s}  {'yield':>8s}")
    for i, c in enumerate(ic, 1):
        fc_actual = in_circuit_fc(**c.values)
        fc_dev = (fc_actual - TARGET_FC) / TARGET_FC * 100
        print(f"  {i:>4d}  {_fmt(c.values['R'], 'Ω'):>10s}  "
              f"{_fmt(c.values['C'], 'F'):>10s}  "
              f"{_fmt(fc_actual, 'Hz'):>11s}  "
              f"{fc_dev:+7.2f}%  "
              f"{c.yield_pct:>7.2f}%")
    print()

    # ---- 3. In-circuit Robust (top-3 only, for validation)
    print("=" * 72)
    print("3. In-circuit Robust ranker on the top-3 — validation")
    print("=" * 72)
    print("    (full MC sweep on each — slower; should agree with Linearized)")
    top3_values = [c.values for c in ic[:3]]

    p3 = make_problem(in_circuit_fc)
    # Reuse the cached backend from step 2 — many of the perturbation
    # points are already cached. Robust will only make new ngspice
    # calls for the MC perturbations not already evaluated.
    rob_ranker = Robust(passive_tolerances={"R": 0.01, "C": 0.05},
                         spec=SPEC, n_mc=200, seed=11)
    # We re-rank ALL candidates to re-use Problem.solve infrastructure,
    # but only print the top-3 for comparison. The full Robust sweep
    # would take ~10× longer than the Linearized sweep.
    misses_before = cached.misses
    t0 = time.perf_counter()
    # Restrict to top-3 by re-using the candidates from step 2
    from utils.eseries_opt.result import Result
    cands_top3 = [c for c in ic if c.values in top3_values]
    rob_ranker.rank(cands_top3, p3.targets)
    dt_rob = time.perf_counter() - t0
    print(f"  ranked in {dt_rob:.2f}s  "
          f"(+{cached.misses - misses_before} new ngspice calls)\n")
    print(f"  {'R':>10s}  {'C':>10s}  "
          f"{'lin_yield':>10s}  {'rob_yield':>10s}")
    lin_lookup = {tuple(sorted(c.values.items())): c.yield_pct
                   for c in ic[:3]}
    for c in cands_top3:
        key = tuple(sorted(c.values.items()))
        print(f"  {_fmt(c.values['R'], 'Ω'):>10s}  "
              f"{_fmt(c.values['C'], 'F'):>10s}  "
              f"{lin_lookup[key]:>9.2f}%  "
              f"{c.yield_pct:>9.2f}%")
    print()

    # ---- summary
    n_brute = _count_grid(p_alg)
    rob_n_mc = 200          # matches Robust(n_mc=200) above
    n_components = len(p_alg.components)
    lin_calls_per_cand = 1 + 2 * n_components
    rob_calls_per_cand = rob_n_mc
    rob_full_calls = rob_calls_per_cand * n_brute
    lin_full_calls = lin_calls_per_cand * n_brute
    print("=" * 72)
    print("Summary")
    print("=" * 72)
    print(f"  Algebraic ranker top-3 R values:  "
          f"{[_fmt(c.values['R'], 'Ω') for c in alg[:3]]}")
    print(f"  In-circuit ranker top-3 R values: "
          f"{[_fmt(c.values['R'], 'Ω') for c in ic[:3]]}")
    print(f"  Brute-force grid size: {n_brute} candidates "
          f"({n_components} components)")
    print(f"  In-circuit Linearized cost:   "
          f"{lin_calls_per_cand} ngspice calls/candidate × "
          f"{n_brute} = {lin_full_calls} total  "
          f"({dt_lin:.1f}s wall)")
    print(f"  In-circuit Robust full grid:  "
          f"{rob_calls_per_cand} ngspice calls/candidate × "
          f"{n_brute} = {rob_full_calls} total")
    print(f"  Linearized speedup (calls):   {rob_full_calls/lin_full_calls:.0f}×")


def _count_grid(problem):
    """Brute-force grid size = product of per-component value counts."""
    n = 1
    for c in problem.components:
        n *= len(c.values())
    return n


def _fmt(value, unit):
    """Engineering-prefix format (10k, 1.5n, etc.)."""
    from utils.rounding import prefix
    return f"{prefix(value)}{unit}"


if __name__ == "__main__":
    main()
