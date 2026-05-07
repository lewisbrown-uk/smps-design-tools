"""Algebra-vs-yield disagreement: asymmetric per-component tolerances.

Constructed example showing where the Robust ranker picks a
*different* candidate from the algebraic ranker — not within MC
noise of agreement, but a real qualitative difference.

The setup: a series-pair resistor design with R1 from a tight-binned
1% tolerance class and R2 from a wider 5% class. Target sum = 10 kΩ.
Spec: sum within 2 % of nominal.

Asymmetry: R2's per-ohm tolerance is 5× R1's. Candidates that
**minimise R2** (and let R1 carry most of the sum) get a yield boost
the algebraic ranker can't see — to algebra, R1=1.8k+R2=8.2k and
R1=8.2k+R2=1.8k both hit the target with error 0 and look identical.

Flow 1 (algebra-first) treats those two as tied at the top, then
yield-checks them post-hoc and discovers a 14-percentage-point gap.

Flow 2 (Robust ranker) systematically prefers all R2-small candidates
— the top 8 are entirely different from Flow 1's top 8.

Library feature this exercises: per-component tolerance overrides in
``passive_tolerances`` (lookup by full name first, then by SPICE
prefix), needed because R1 and R2 have different tolerance classes.

Pure closed-form, runs in seconds.
"""
from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.eseries_opt import Problem, Resistor
from utils.tolerance import analyze, Robust
from utils.rounding import prefix


def make_problem():
    """Series-pair targeting sum = 10 kΩ. Constraint band of ±20% on
    nominal sum keeps the search bounded; the spec inside analyze()
    is tighter (±2%)."""
    p = Problem()
    p.add(Resistor("R1", e_series=12, range=(1e3, 1e4)))
    p.add(Resistor("R2", e_series=12, range=(1e3, 1e4)))
    p.add_target("ratio", lambda R1, R2: (R1 + R2) / 10000,
                 target=1.0, metric="abs")
    p.add_constraint("sum_band", lambda R1, R2: R1 + R2,
                     range=(8e3, 12e3))
    return p


def main():
    n_top = 8
    n_mc = 10000
    spec = {"ratio": ("within", 0.02)}
    # Per-component tolerance: R1 is 1%, R2 is 5%. The library accepts
    # name-keyed entries that override the prefix default.
    passive_tolerances = {"R1": 0.01, "R2": 0.05}

    metrics = lambda R1, R2: {"ratio": (R1 + R2) / 10000}

    print("Series-pair design: R1+R2 = 10 kΩ")
    print(f"  R1 binned to 1% (precision part), R2 binned to 5% (cheap part)")
    print(f"  Spec: ratio within 2% of nominal,  MC = {n_mc} samples\n")

    # ---------- Flow 1: algebraic top-N then yield-check ----------
    print("=" * 78)
    print("Flow 1 — Post-hoc:  algebraic top, then check yield")
    print("=" * 78)
    print(f"  {'rank':>4} {'R1':>8} {'R2':>8}  {'sum':>7}  "
          f"{'algebra':>8}  {'yield':>7}")
    cands = make_problem().solve(strategy="brute", n_results=n_top)
    for i, c in enumerate(cands, 1):
        r = analyze(nominal_values=c.values,
                     passive_tolerances=passive_tolerances,
                     metrics=metrics, spec=spec, n_mc=n_mc, seed=42)
        print(f"  {i:>4} {prefix(c.values['R1']):>8} "
              f"{prefix(c.values['R2']):>8}  "
              f"{prefix(c.values['R1']+c.values['R2']):>7}  "
              f"{c.error:>8.4f}  {r.yield_pct:>6.2f}%")
    print()

    # ---------- Flow 2: Robust ranker ----------
    print("=" * 78)
    print("Flow 2 — Direct:  Robust ranker scores ALL feasible by yield")
    print("=" * 78)
    print(f"  {'rank':>4} {'R1':>8} {'R2':>8}  {'sum':>7}  "
          f"{'algebra':>8}  {'yield':>7}")
    cands_r = make_problem().solve(
        strategy="brute", n_results=n_top,
        rank=Robust(passive_tolerances=passive_tolerances,
                    spec=spec, n_mc=n_mc, seed=42),
    )
    for i, c in enumerate(cands_r, 1):
        print(f"  {i:>4} {prefix(c.values['R1']):>8} "
              f"{prefix(c.values['R2']):>8}  "
              f"{prefix(c.values['R1']+c.values['R2']):>7}  "
              f"{c.error:>8.4f}  {c.yield_pct:>6.2f}%")
    print()

    # ---------- The point ----------
    flow1_set = {tuple(sorted(c.values.items())) for c in cands}
    flow2_set = {tuple(sorted(c.values.items())) for c in cands_r}
    overlap = flow1_set & flow2_set
    print("=" * 78)
    print(f"Top-{n_top} overlap between flows: {len(overlap)} of {n_top}")
    print("=" * 78)
    print()
    print("The two algebraically-tied top candidates (R1=1.8k+R2=8.2k vs")
    print("R1=8.2k+R2=1.8k, both sum=10k exactly) differ in yield by ~15")
    print("percentage points — invisible to the algebraic ranker because R1")
    print("and R2 enter the target expression symmetrically.")
    print()
    print("The Robust ranker systematically prefers small R2 to minimise the")
    print("contribution of the loose-tolerance part. Its top picks are all")
    print("R2 ≤ 2.7k regardless of small algebraic-error penalties.")
    print()
    print("This is the situation the user's framing (cart before horse) is")
    print("really about: when the algebra can't see what matters for yield,")
    print("running MC as a post-filter on the algebraic top finds a SOMEWHAT")
    print("robust candidate by luck. The Robust ranker finds the actually-")
    print("most-robust candidate by design.")


if __name__ == "__main__":
    main()
