"""End-to-end design flow: eseries_opt × tolerance.

Two ways to combine algebraic E-series optimisation with Monte-Carlo
yield analysis:

1. **Post-hoc (cart before horse)**: ``eseries_opt`` ranks candidates
   by algebraic target error. ``tolerance.analyze`` then runs MC on
   the top-N to estimate yield. Cheap but can miss the most-robust
   candidate if it isn't in the algebraic top-N.

2. **Direct (Robust ranker)**: every feasible candidate is MC-evaluated
   and ranked by yield. The choice is robust by construction. More
   expensive (one MC sweep per candidate) but always gives the
   right answer in principle.

For the Sallen-Key Butterworth design used here, both flows agree on
the winner — SK has uniform relative-sensitivity across the design
space so all candidates have approximately the same yield, and the
algebraic best is also the yield best to within MC noise. The script
prints both rankings side-by-side so you can see the agreement.

For other circuits (especially ones where active-device spreads,
correlations, or asymmetric topologies break the uniform-sensitivity
assumption), the Robust ranker can pick a different design than the
algebraic best — that's when this approach pays for itself.
"""
from __future__ import annotations

import math
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.eseries_opt import Problem, Resistor, Capacitor
from utils.tolerance import analyze, Robust
from utils.rounding import prefix


def fc_expr(R1, R2, C1, C2):
    return 1 / (2 * math.pi * math.sqrt(R1 * R2 * C1 * C2))


def Q_expr(R1, R2, C1, C2):
    return math.sqrt(R1 * R2 * C2 / C1) / (R1 + R2)


def Zin_expr(R1, R2, C1, C2):
    return R1 + R2


def _q_bounder(fixed, free_ranges):
    """Sound bounder for Q — see test_eseries_opt for derivation."""
    def span(name):
        return ((fixed[name], fixed[name]) if name in fixed
                else free_ranges[name])

    R1_lo, R1_hi = span("R1")
    R2_lo, R2_hi = span("R2")
    C1_lo, C1_hi = span("C1")
    C2_lo, C2_hi = span("C2")

    def f(r1, r2):
        return math.sqrt(r1 * r2) / (r1 + r2)

    diag_intersects = max(R1_lo, R2_lo) <= min(R1_hi, R2_hi)
    f_corners = [f(R1_lo, R2_lo), f(R1_lo, R2_hi),
                 f(R1_hi, R2_lo), f(R1_hi, R2_hi)]
    f_max = 0.5 if diag_intersects else max(f_corners)
    f_min = min(f_corners)
    return (f_min * math.sqrt(C2_lo / C1_hi),
            f_max * math.sqrt(C2_hi / C1_lo))


def make_problem():
    """Sallen-Key Butterworth design: R1=R2=10k, C1=10n, C2=22n is
    the unique E12 candidate that hits both targets exactly."""
    fc_target = fc_expr(1e4, 1e4, 1e-8, 2.2e-8)   # ≈ 1073 Hz
    Q_target = Q_expr(1e4, 1e4, 1e-8, 2.2e-8)     # ≈ 0.7416

    p = Problem()
    p.add(Resistor("R1", e_series=12, range=(1e3, 1e4)))
    p.add(Resistor("R2", e_series=12, range=(1e3, 1e4)))
    p.add(Capacitor("C1", e_series=12, range=(1e-9, 1e-7)))
    p.add(Capacitor("C2", e_series=12, range=(1e-9, 1e-7)))
    p.add_target("fc", fc_expr, target=fc_target)
    p.add_target("Q", Q_expr, target=Q_target, bounder=_q_bounder)
    p.add_constraint("Zin", Zin_expr, range=(15e3, 25e3))
    return p, fc_target, Q_target


def metrics(R1, R2, C1, C2):
    return {"fc": fc_expr(R1, R2, C1, C2),
            "Q": Q_expr(R1, R2, C1, C2)}


def main():
    p, fc_target, Q_target = make_problem()
    print(f"Sallen-Key Butterworth design")
    print(f"  Targets: fc = {fc_target:.2f} Hz,  Q = {Q_target:.4f}")
    print(f"  Constraint: Zin = R1+R2 ∈ [15k, 25k]")
    print(f"  Tolerances: 5%R / 10%C")
    print(f"  Spec: fc within 2%, Q within 3%")
    print()

    n_top = 6
    n_mc = 5000
    spec = {"fc": ("within", 0.02), "Q": ("within", 0.03)}
    tols = {"R": 0.05, "C": 0.10}

    # ---------- Flow 1: post-hoc (algebraic → yield) ----------
    print("=" * 78)
    print("Flow 1 — Post-hoc:  eseries_opt ranks by algebra, "
          "tolerance checks yield")
    print("=" * 78)
    t0 = time.perf_counter()
    cands_alg = p.solve(strategy="brute", n_results=n_top)
    yields_alg = []
    for c in cands_alg:
        r = analyze(nominal_values=c.values,
                     passive_tolerances=tols, metrics=metrics,
                     spec=spec, n_mc=n_mc, seed=42)
        yields_alg.append(r.yield_pct)
    t_alg = time.perf_counter() - t0
    print(f"  {t_alg:.1f}s for top-{n_top} candidates × {n_mc}-sample MC")
    print(f"  {'rank':>4} {'R1':>8} {'R2':>8} {'C1':>8} {'C2':>8}  "
          f"{'algebra':>9}  {'yield':>7}")
    for i, (c, y) in enumerate(zip(cands_alg, yields_alg), 1):
        print(f"  {i:>4} {prefix(c.values['R1']):>8} "
              f"{prefix(c.values['R2']):>8} {prefix(c.values['C1']):>8} "
              f"{prefix(c.values['C2']):>8}  {c.error:>9.2e}  {y:>6.2f}%")
    print()

    # ---------- Flow 2: direct (Robust ranker) ----------
    print("=" * 78)
    print(f"Flow 2 — Direct:  Robust ranker scores ALL feasible "
          f"candidates by MC yield")
    print("=" * 78)
    t0 = time.perf_counter()
    cands_yld = make_problem()[0].solve(
        strategy="brute", n_results=n_top,
        rank=Robust(passive_tolerances=tols, spec=spec,
                    n_mc=n_mc, seed=42),
    )
    t_yld = time.perf_counter() - t0
    print(f"  {t_yld:.1f}s for ALL feasible × {n_mc}-sample MC")
    print(f"  {'rank':>4} {'R1':>8} {'R2':>8} {'C1':>8} {'C2':>8}  "
          f"{'algebra':>9}  {'yield':>7}")
    for i, c in enumerate(cands_yld, 1):
        print(f"  {i:>4} {prefix(c.values['R1']):>8} "
              f"{prefix(c.values['R2']):>8} {prefix(c.values['C1']):>8} "
              f"{prefix(c.values['C2']):>8}  {c.error:>9.2e}  "
              f"{c.yield_pct:>6.2f}%")
    print()

    # ---------- Comparison ----------
    print("=" * 78)
    print("Comparison")
    print("=" * 78)
    flow1_winner = cands_alg[0].values
    flow2_winner = cands_yld[0].values
    same = all(abs(flow1_winner[k] - flow2_winner[k]) / flow1_winner[k]
               < 0.01 for k in flow1_winner)
    if same:
        print(f"Both flows pick the same winner (R1={prefix(flow1_winner['R1'])}, "
              f"R2={prefix(flow1_winner['R2'])}, C1={prefix(flow1_winner['C1'])}, "
              f"C2={prefix(flow1_winner['C2'])}).")
        print()
        print("For this Sallen-Key Butterworth, the SK transfer function has "
              "uniform relative sensitivity across the design space — every "
              "candidate that hits the targets has approximately the same "
              "yield under proportional component tolerances. The algebraic "
              "best wins by default.")
        print()
        print("The Robust ranker would pick a different winner when:")
        print("  - Active-device spreads interact non-uniformly with passive "
              "values (e.g. op-amp Vos amplified by a gain stage where the "
              "gain depends on R-ratio).")
        print("  - Reel-mate correlation: matched-pair candidates benefit "
              "more from common-mode cancellation than mismatched pairs.")
        print("  - Asymmetric topologies where some component-value "
              "combinations sit at sensitivity hot-spots and others don't.")
    else:
        print(f"Flows DISAGREE on the winner — the Robust ranker found a "
              f"more-robust candidate that wasn't algebraic-best.")


if __name__ == "__main__":
    main()
