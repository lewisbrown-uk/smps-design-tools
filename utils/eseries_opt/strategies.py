import itertools

from .result import Result


_BRUTE_FORCE_HARD_CAP = 10_000_000


class BruteForce:
    """Scalar Cartesian product over E-series values. Default for small
       problems (<=3 components). Refuses to run if the candidate space
       exceeds _BRUTE_FORCE_HARD_CAP — switch strategy or shrink ranges."""

    def solve(self, problem, n_results, ranker):
        from .problem import _error    # local import avoids cycle

        names = [c.name for c in problem.components]
        value_lists = [c.values() for c in problem.components]

        total = 1
        for arr in value_lists:
            total *= len(arr)
        if total > _BRUTE_FORCE_HARD_CAP:
            raise ValueError(
                f"BruteForce candidate space too large ({total:,}). "
                f"Reduce ranges/series or pick another strategy."
            )

        candidates = []
        for combo in itertools.product(*value_lists):
            kwargs = {n: float(v) for n, v in zip(names, combo)}

            if not all(con.predicate(con.expr(**kwargs))
                       for con in problem.constraints):
                continue

            breakdown = {
                t.name: _error(t.expr(**kwargs), t.target, t.metric)
                for t in problem.targets
            }
            candidates.append(Result(values=dict(kwargs), breakdown=breakdown))

        return ranker.rank(candidates, problem.targets)[:n_results]


class FactorOne:
    """For each combination of the non-pivot components, solve the pivot
    component analytically against a designated target, then evaluate the
    two E-series values adjacent to the ideal. O(S^(N-1)) instead of O(S^N).

    Exact (matches BruteForce) for single-target problems where the target
    is monotonic in the pivot around the optimum — RC time constants,
    LC resonance, dividers, gain ratios. For multi-target problems the
    pivot is chosen by one named target alone, so the result may not be
    the global multi-target optimum (the ranker still considers all
    targets when ordering candidates).

    Args:
        pivot:  Name of the component to solve for analytically.
        target: Name of the target to factor against.
        solver: Callable ``(target_value, **other_components) -> pivot``.
    """

    def __init__(self, pivot, target, solver):
        self.pivot = pivot
        self.target_name = target
        self.solver = solver

    def solve(self, problem, n_results, ranker):
        from .problem import _error

        comp_names = {c.name for c in problem.components}
        if self.pivot not in comp_names:
            raise ValueError(
                f"FactorOne pivot '{self.pivot}' not in components: "
                f"{sorted(comp_names)}"
            )
        target_names = {t.name for t in problem.targets}
        if self.target_name not in target_names:
            raise ValueError(
                f"FactorOne target '{self.target_name}' not in targets: "
                f"{sorted(target_names)}"
            )

        pivot_comp = next(c for c in problem.components if c.name == self.pivot)
        the_target = next(t for t in problem.targets
                          if t.name == self.target_name)
        other_comps = [c for c in problem.components if c.name != self.pivot]
        other_names = [c.name for c in other_comps]
        other_value_lists = [c.values() for c in other_comps]
        pivot_values = pivot_comp.values()

        candidates = []
        for combo in itertools.product(*other_value_lists):
            other_kwargs = {n: float(v) for n, v in zip(other_names, combo)}
            ideal = self.solver(the_target.target, **other_kwargs)

            for pivot_val in _adjacent(pivot_values, ideal):
                kwargs = {**other_kwargs, self.pivot: pivot_val}

                if not all(con.predicate(con.expr(**kwargs))
                           for con in problem.constraints):
                    continue

                breakdown = {
                    t.name: _error(t.expr(**kwargs), t.target, t.metric)
                    for t in problem.targets
                }
                candidates.append(Result(values=dict(kwargs),
                                         breakdown=breakdown))

        return ranker.rank(candidates, problem.targets)[:n_results]


def _adjacent(values, ideal):
    """Up to two candidates from a sorted-ascending array: the largest
    value <= ideal and the smallest value >= ideal. Falls back to the
    nearest endpoint when ideal is outside the array's range."""
    out = []
    below = values[values <= ideal]
    above = values[values >= ideal]
    if len(below):
        out.append(float(below[-1]))
    if len(above):
        out.append(float(above[0]))
    return list(dict.fromkeys(out))   # de-dup if ideal hits an E-series value


class RelaxAndSnap:
    """Continuous solve via scipy.optimize then enumerate the K nearest
       E-series values per component. Not yet implemented."""

    def solve(self, problem, n_results, ranker):
        raise NotImplementedError("RelaxAndSnap not yet implemented")


class BranchAndBound:
    """Reserved. Will accept per-target bound= callables to prune subtrees."""

    def solve(self, problem, n_results, ranker):
        raise NotImplementedError("BranchAndBound not yet implemented")
