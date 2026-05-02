import math
import itertools
from dataclasses import dataclass
from typing import Callable

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


def _error(actual, target, metric):
    if metric == "abs":
        return abs(actual - target)
    if metric == "rel":
        if target == 0:
            raise ValueError("metric='rel' is undefined when target=0; use 'abs'")
        return abs((actual - target) / target)
    if metric == "log":
        return abs(math.log(actual / target))
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

    def add_constraint(self, name, expr, predicate):
        self.constraints.append(Constraint(name, expr, predicate))

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
