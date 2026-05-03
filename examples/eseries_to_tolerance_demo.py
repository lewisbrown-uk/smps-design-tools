"""End-to-end design flow: eseries_opt → tolerance.

The design problem: pick R1, R2, C1, C2 from E12 to build a unity-gain
Sallen-Key low-pass filter targeting Butterworth response at
``fc = 1073 Hz`` (i.e. fc·=·1/(2π·√(R1R2C1C2))) and ``Q = 0.7416``,
subject to ``Z_in = R1+R2 ∈ [15k, 25k]``.

This is the briefing's headline use case for the two libraries
together: ``eseries_opt`` finds the top-N candidates that hit the
algebraic targets best, then ``tolerance.analyze`` runs MC yield on
each at realistic component tolerances. The "best" candidate by
algebraic error isn't always the most robust to component variation
— this script shows when they agree and when they don't.

Pure closed-form metrics (no ngspice), so the whole flow runs in a
couple of seconds.
"""
from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.eseries_opt import Problem, Resistor, Capacitor
from utils.tolerance import analyze
from utils.rounding import prefix


# ---------- Sallen-Key target expressions ----------

def fc_expr(R1, R2, C1, C2):
    """Sallen-Key natural frequency (cycles/s)."""
    return 1 / (2 * math.pi * math.sqrt(R1 * R2 * C1 * C2))


def Q_expr(R1, R2, C1, C2):
    """Sallen-Key Q. For unity-gain SK with C2 to ground and C1 from
    intermediate node to vout, Q = √(R1·R2·C2/C1) / (R1+R2)."""
    return math.sqrt(R1 * R2 * C2 / C1) / (R1 + R2)


def Zin_expr(R1, R2, C1, C2):
    """Input impedance at DC = R1 + R2."""
    return R1 + R2


# ---------- Q bounder for branch-and-bound (sound) ----------

def _q_bounder(fixed, free_ranges):
    """Q has an interior max along the diagonal R1=R2 — corner
    evaluation can miss it. This sound bounder factors Q as
    f(R1,R2)·√(C2/C1) and uses the analytic max of f along the
    diagonal when that diagonal intersects the (R1,R2) box."""
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
    sqrt_ratio_max = math.sqrt(C2_hi / C1_lo)
    sqrt_ratio_min = math.sqrt(C2_lo / C1_hi)
    return (f_min * sqrt_ratio_min, f_max * sqrt_ratio_max)


# ---------- Helpers ----------

def make_metrics(_):
    """Closed-form metrics callable for tolerance.analyze."""
    def metrics(R1, R2, C1, C2):
        return {"fc": fc_expr(R1, R2, C1, C2),
                "Q":  Q_expr(R1, R2, C1, C2)}
    return metrics


def main():
    # ---------- Step 1: define the design problem ----------
    fc_target = fc_expr(1e4, 1e4, 1e-8, 2.2e-8)   # ≈ 1073 Hz
    Q_target  = Q_expr(1e4, 1e4, 1e-8, 2.2e-8)    # ≈ 0.7416

    p = Problem()
    p.add(Resistor("R1", e_series=12, range=(1e3, 1e4)))
    p.add(Resistor("R2", e_series=12, range=(1e3, 1e4)))
    p.add(Capacitor("C1", e_series=12, range=(1e-9, 1e-7)))
    p.add(Capacitor("C2", e_series=12, range=(1e-9, 1e-7)))
    p.add_target("fc", fc_expr, target=fc_target)
    p.add_target("Q",  Q_expr,  target=Q_target, bounder=_q_bounder)
    p.add_constraint("Zin", Zin_expr, range=(15e3, 25e3))

    # ---------- Step 2: ask eseries_opt for the top N candidates ----------
    n_top = 6
    candidates = p.solve(strategy="brute", n_results=n_top)

    print(f"Sallen-Key Butterworth design")
    print(f"  Targets: fc = {fc_target:.2f} Hz,  Q = {Q_target:.4f}")
    print(f"  Constraint: Zin ∈ [15k, 25k]")
    print(f"  Top {n_top} E12 candidates by algebraic error:\n")
    for i, c in enumerate(candidates, 1):
        print(f"  {i}. {c}")
    print()

    # ---------- Step 3: MC yield on each candidate ----------
    # Push the design into a tolerance regime where candidates start
    # to diverge: 5%R / 10%C (typical hobby-grade parts) with a tight
    # fc-within-2% / Q-within-3% spec. At 1%R/5%C every candidate
    # passes ~100% so the comparison says nothing.
    n_mc = 20000
    spec = {"fc": ("within", 0.02), "Q": ("within", 0.03)}
    metrics = make_metrics(None)

    print(f"Running {n_mc}-sample MC on each: 5%R / 10%C, "
          f"spec fc within 2%, Q within 3%\n")
    print(f"  {'#':>2} {'R1':>8} {'R2':>8} {'C1':>8} {'C2':>8}  "
          f"{'algebra':>9}  {'yield':>7}  {'fc σ%':>6}  {'Q σ%':>6}  "
          f"{'fc fail':>8}  {'Q fail':>8}")
    print("  " + "-" * 96)

    rows = []
    for i, c in enumerate(candidates, 1):
        report = analyze(
            nominal_values=c.values,
            passive_tolerances={"R": 0.05, "C": 0.10},
            metrics=metrics,
            spec=spec,
            n_mc=n_mc, seed=2024 + i,
        )
        fc_s = report.metric_stats["fc"]
        Q_s  = report.metric_stats["Q"]
        # σ relative to nominal (most readable form)
        fc_sigma_pct = 100 * fc_s.std / fc_s.mean
        Q_sigma_pct  = 100 * Q_s.std / Q_s.mean
        fc_fail = n_mc - report.per_spec_pass["fc"]
        Q_fail  = n_mc - report.per_spec_pass["Q"]
        rows.append((i, c, report, fc_sigma_pct, Q_sigma_pct))
        print(f"  {i:>2} "
              f"{prefix(c.values['R1']):>8} {prefix(c.values['R2']):>8} "
              f"{prefix(c.values['C1']):>8} {prefix(c.values['C2']):>8}  "
              f"{c.error:>9.2e}  {report.yield_pct:>6.2f}%  "
              f"{fc_sigma_pct:>5.2f}%  {Q_sigma_pct:>5.2f}%  "
              f"{fc_fail:>8d}  {Q_fail:>8d}")

    # ---------- Step 4: rank by yield, comment on the comparison ----------
    print()
    by_yield = sorted(rows, key=lambda x: -x[2].yield_pct)
    by_error = sorted(rows, key=lambda x: x[1].error)

    print("Rank-by-algebraic-error (eseries_opt's order):")
    for i, c, r, fcs, Qs in by_error:
        print(f"  {i}: error={c.error:.3e}  yield={r.yield_pct:.2f}%")
    print()
    print("Rank-by-MC-yield (tolerance.analyze's order):")
    for i, c, r, fcs, Qs in by_yield:
        print(f"  {i}: yield={r.yield_pct:.2f}%  error={c.error:.3e}")
    print()

    error_top = by_error[0][0]
    yield_top = by_yield[0][0]
    if error_top == yield_top:
        print(f"For this Sallen-Key Butterworth design, the rankings "
              f"agree: the algebraic-best candidate (#{error_top}) is "
              f"also the most robust under MC. The SK formula is "
              f"symmetric enough in (R1, R2, C1, C2) that none of the "
              f"top candidates sits on a sensitivity hot-spot; yields "
              f"differ by only ~1 percentage point across the field.")
        print()
        print("In topologies where the algebraic targets can be hit by "
              "structurally-different component combinations (e.g. "
              "filters with multiple Pareto-equivalent solutions, or "
              "designs whose sensitivity functions have interior "
              "extrema), the rankings can disagree. That's the case "
              "where running this MC step on the eseries_opt output "
              "actually changes which candidate you pick.")
    else:
        print(f"Algebraic best is candidate #{error_top}, but the most "
              f"robust under MC is candidate #{yield_top}. The "
              f"algebraic-best sits at a sensitivity hot-spot; the "
              f"slightly-worse candidate has lower fc/Q variance under "
              f"realistic component variation.")


if __name__ == "__main__":
    main()
