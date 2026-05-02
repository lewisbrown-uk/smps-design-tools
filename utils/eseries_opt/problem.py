import itertools
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from .ranking import WeightedSum
from .strategies import BruteForce, FactorOne, RelaxAndSnap, BranchAndBound


_VALID_METRICS = {"rel", "abs", "log"}

# String-shortcut registry for parameterless strategies. FactorOne is
# omitted because it requires explicit configuration — pass an instance
# to solve(strategy=FactorOne(pivot=..., target=..., solver=...)) instead.
_STRATEGIES = {
    "brute": BruteForce,
    "relax": RelaxAndSnap,
    "bnb":   BranchAndBound,
}


@dataclass
class Target:
    name: str
    expr: Callable
    target: float
    weight: float = 1.0
    metric: str = "rel"


@dataclass
class Constraint:
    name: str
    expr: Callable
    predicate: Callable
    bounder: Optional[Callable] = None
    """``bounder(fixed_kwargs, free_ranges) -> (lo, hi)`` returns the value
    range of ``expr`` over a partial assignment — fixed components and the
    (lo, hi) ranges of the free ones. Used by BranchAndBound for subtree
    pruning. Auto-generated when the constraint is added with ``range=``;
    must be supplied explicitly alongside a custom ``predicate=`` to enable
    pruning. ``None`` means B&B can't prune on this constraint."""


def _range_predicate(lo, hi):
    """Predicate equivalent to ``lo <= z <= hi`` but using bitwise ``&``,
    so it broadcasts cleanly under ``BruteForce(vectorise=True)`` without
    tripping the chained-comparison 'truth value of an array is ambiguous'
    error. Bitwise ``&`` on bool returns 0/1 in scalar mode (still truthy)
    so it works in both modes uniformly."""
    return lambda z: (lo <= z) & (z <= hi)


def _corner_bounder(expr):
    """Auto-generated bounder via corner evaluation: evaluates ``expr`` at
    every combination of (lo, hi) endpoints of the free components, returns
    (min, max). Tight (and sound) for expressions monotonic in each free
    variable — sums, ratios, products of components, which covers most
    circuit constraints. Non-monotonic expressions can have interior
    extrema that corner evaluation misses; supply an explicit ``bounder=``
    in those cases."""
    def bounder(fixed_kwargs, free_ranges):
        free_names = list(free_ranges)
        if not free_names:
            v = expr(**fixed_kwargs)
            return (v, v)
        values = []
        for corner in itertools.product(*(free_ranges[n] for n in free_names)):
            kwargs = {**fixed_kwargs, **dict(zip(free_names, corner))}
            values.append(expr(**kwargs))
        return (min(values), max(values))
    return bounder


def _error(actual, target, metric):
    """Error metric. Works on scalars and numpy arrays alike — np.abs / np.log
    broadcast cleanly, so the same function serves the scalar and vectorised
    BruteForce paths without divergence."""
    if metric == "abs":
        return np.abs(actual - target)
    if metric == "rel":
        if target == 0:
            raise ValueError("metric='rel' is undefined when target=0; use 'abs'")
        return np.abs((actual - target) / target)
    if metric == "log":
        return np.abs(np.log(actual / target))
    raise ValueError(f"Unknown metric: {metric}")


def _sensitivity(problem, result, tol):
    """Worst-case weighted-sum error at the 2^N tolerance corners."""
    names = [c.name for c in problem.components]
    base = [result.values[n] for n in names]

    worst = 0.0
    for signs in itertools.product([-1, +1], repeat=len(base)):
        perturbed = {n: v * (1 + s * tol)
                     for n, v, s in zip(names, base, signs)}

        if not all(c.predicate(c.expr(**perturbed))
                   for c in problem.constraints):
            continue

        composite = sum(
            t.weight * _error(t.expr(**perturbed), t.target, t.metric)
            for t in problem.targets
        )
        if composite > worst:
            worst = composite
    return worst


class Problem:
    def __init__(self):
        self.components = []
        self.targets = []
        self.constraints = []

    def add(self, component):
        if any(c.name == component.name for c in self.components):
            raise ValueError(f"Duplicate component name: {component.name}")
        self.components.append(component)
        return component

    def add_target(self, name, expr, target, weight=1.0, metric="rel"):
        if metric not in _VALID_METRICS:
            raise ValueError(
                f"Unknown metric: {metric}. Valid: {sorted(_VALID_METRICS)}"
            )
        self.targets.append(Target(name, expr, target, weight, metric))

    def add_constraint(self, name, expr, predicate=None, *,
                       range=None, bounder=None):
        """Add a hard feasibility constraint.

        Provide either:

        - ``range=(lo, hi)``: ``expr`` must satisfy ``lo <= expr <= hi``.
          A bitwise-safe predicate and a corner-evaluation bounder are
          auto-generated. This is the common path for circuit constraints
          (impedance windows, current/voltage limits, ratio bands).
        - ``predicate=fn`` (positional or keyword): explicit boolean
          callable on the value of ``expr``. Use for non-range checks.
          Optionally pair with ``bounder=`` to enable BranchAndBound
          subtree pruning.

        Args:
            name:      Identifier.
            expr:      ``(**components) -> value`` being constrained.
            predicate: ``(value) -> bool``. Required if ``range`` is None.
            range:     ``(lo, hi)`` shortcut.
            bounder:   ``(fixed_kwargs, free_ranges) -> (lo, hi)`` over
                       partial assignments. Used by BranchAndBound.
                       Auto-generated when ``range=`` is supplied.
        """
        if range is not None:
            if predicate is not None:
                raise ValueError(
                    f"Constraint '{name}': specify either range= or "
                    f"predicate=, not both"
                )
            lo, hi = range
            predicate = _range_predicate(lo, hi)
            if bounder is None:
                bounder = _corner_bounder(expr)
        elif predicate is None:
            raise ValueError(
                f"Constraint '{name}' needs either range=(lo, hi) "
                f"or predicate="
            )
        self.constraints.append(Constraint(name, expr, predicate, bounder))

    def solve(self, strategy="auto", n_results=10, rank=None,
              sensitivity_tol=0.01):
        if not self.components:
            raise ValueError("Problem has no components")
        if not self.targets:
            raise ValueError("Problem has no targets")

        if strategy == "auto":
            strat = (BruteForce() if len(self.components) <= 3
                     else RelaxAndSnap())
        elif isinstance(strategy, str):
            if strategy not in _STRATEGIES:
                raise ValueError(
                    f"Unknown strategy: {strategy!r}. "
                    f"Known: {sorted(_STRATEGIES)}"
                )
            strat = _STRATEGIES[strategy]()
        else:
            strat = strategy   # pre-constructed strategy instance

        ranker = rank if rank is not None else WeightedSum()
        results = strat.solve(self, n_results=n_results, ranker=ranker)

        if sensitivity_tol is not None:
            for r in results:
                r.sensitivity = _sensitivity(self, r, sensitivity_tol)
        return results
