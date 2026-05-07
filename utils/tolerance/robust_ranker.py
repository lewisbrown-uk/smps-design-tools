"""Yield-aware ranker for ``eseries_opt`` Problems.

Plugs into ``Problem.solve(rank=...)`` like the existing ranking
strategies (``WeightedSum``, ``Lexicographic``, ``Pareto``). For each
candidate the strategy generates, the ranker runs a small Monte-Carlo
sweep against a closed-loop spec and orders candidates by yield.

This is the right way to do robust E-series design — the existing
"rank by algebraic-target error, then check robustness afterwards"
flow can miss the most-robust candidate if it's not in the algebraic
top-N. Here, every feasible candidate is MC-evaluated and the choice
is robust by construction.

Cost note: the ranker calls ``analyze`` once per candidate, with
``n_mc`` samples each. For a 4-component E12 problem with a hard
constraint pruning to ~1000 feasible candidates and ``n_mc=500``,
that's ~500k closed-form metric evaluations — still seconds to a
minute on a laptop. For ngspice metrics this would be intractable;
use a smaller ``n_mc`` for screening or pre-filter via a cheaper
ranker first.
"""
from .analyze import analyze


class Robust:
    """Sort eseries_opt candidates by Monte-Carlo yield.

    The metrics callable for ``analyze`` is built automatically from
    the Problem's targets — each target's ``expr`` becomes one entry
    in the returned dict. The user's ``spec`` then references those
    target names.

    Args:
        passive_tolerances: ``{prefix: rel_tol}``, same shape as
            ``analyze(passive_tolerances=...)``.
        spec: ``{target_name: (op, threshold)}``, same shape as
            ``analyze(spec=...)``. The names must match the Problem's
            targets — each target supplies its own metric.
        n_mc: MC samples per candidate. Smaller = faster but noisier
            ranking. Default 500.
        seed: RNG seed reused across all candidates so the comparison
            is fair (each candidate sees the same component-perturbation
            patterns).
        active_devices: optional active-device spreads, same shape as
            ``analyze(active_devices=...)``.
        distribution: optional distribution overrides.
        correlations: optional correlation groups.
        tolerance_sigma: forwarded to ``analyze``.

    The ranker attaches two extra attributes to each Result:

    - ``yield_pct``: MC yield against the spec, in percent.
    - ``yield_report``: the full ``YieldReport`` for diagnostic.

    Sort order: descending yield (most-robust first), with the
    algebraic composite error as the tie-breaker. ``Result.error`` is
    set to the algebraic composite (same as ``WeightedSum``) for
    display compatibility.
    """

    def __init__(self, *, passive_tolerances, spec,
                 n_mc=500, seed=42,
                 active_devices=None, distribution="gaussian",
                 correlations=None, tolerance_sigma=3.0):
        self.passive_tolerances = passive_tolerances
        self.spec = spec
        self.n_mc = n_mc
        self.seed = seed
        self.active_devices = active_devices
        self.distribution = distribution
        self.correlations = correlations
        self.tolerance_sigma = tolerance_sigma

    def rank(self, candidates, targets):
        if not candidates:
            return []

        # Validate spec keys match target names — fail loudly on a typo
        # rather than silently scoring against a non-existent metric.
        target_names = {t.name for t in targets}
        bad = set(self.spec) - target_names
        if bad:
            raise ValueError(
                f"Robust spec references unknown target(s): {sorted(bad)}. "
                f"Known: {sorted(target_names)}"
            )

        # Build metrics callable from the targets — each target's
        # expression becomes one entry in the metrics output dict.
        target_by_name = {t.name: t for t in targets}

        def metrics(**values):
            return {n: t.expr(**values)
                    for n, t in target_by_name.items()}

        # Composite algebraic error as a tie-breaker (same convention
        # as WeightedSum so .error displays consistently).
        weights = {t.name: t.weight for t in targets}
        for c in candidates:
            c.error = sum(weights[k] * v
                          for k, v in c.breakdown.items())

        # MC each candidate. Same seed so all candidates see the same
        # perturbation pattern — the comparison is paired and the
        # variance of (yield_A - yield_B) is much smaller than under
        # independent seeds.
        for c in candidates:
            report = analyze(
                nominal_values=c.values,
                passive_tolerances=self.passive_tolerances,
                metrics=metrics,
                spec=self.spec,
                n_mc=self.n_mc,
                seed=self.seed,
                active_devices=self.active_devices,
                distribution=self.distribution,
                correlations=self.correlations,
                tolerance_sigma=self.tolerance_sigma,
            )
            c.yield_pct = report.yield_pct
            c.yield_report = report

        # Descending by yield, ascending by algebraic error as tiebreak
        return sorted(candidates, key=lambda c: (-c.yield_pct, c.error))
