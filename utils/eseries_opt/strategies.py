import itertools

import numpy as np

from .result import Result


_BRUTE_FORCE_HARD_CAP = 10_000_000


class BruteForce:
    """Cartesian product over E-series values. Default for small problems
    (<=3 components). Two evaluation modes:

    - ``vectorise=False`` (default): scalar Python loop. Always works,
      including with ``math.sqrt``, chained comparisons, branches, etc.
    - ``vectorise=True``: numpy broadcasting over N-D grids. 100-1000x
      faster on big problems, but every target/constraint expression must
      use numpy-compatible ops (``np.sqrt`` not ``math.sqrt``;
      ``(a <= z) & (z <= b)`` not ``a <= z <= b``). Currently restricted
      to WeightedSum ranking — other rankers need per-candidate
      materialisation, which defeats the speedup.

    Refuses to run if the candidate space exceeds _BRUTE_FORCE_HARD_CAP
    in either mode — switch strategy or shrink ranges past that point.
    """

    def __init__(self, vectorise=False):
        self.vectorise = vectorise

    def solve(self, problem, n_results, ranker):
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

        if self.vectorise:
            from .ranking import WeightedSum
            if not isinstance(ranker, WeightedSum):
                raise ValueError(
                    f"vectorise=True only supports WeightedSum ranking "
                    f"(got {type(ranker).__name__}). Other rankers require "
                    f"per-candidate materialisation."
                )
            return self._solve_vectorised(problem, names, value_lists,
                                          n_results, ranker)
        return self._solve_scalar(problem, names, value_lists,
                                  n_results, ranker)

    def _solve_scalar(self, problem, names, value_lists, n_results, ranker):
        from .problem import _error

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

    def _solve_vectorised(self, problem, names, value_lists, n_results, ranker):
        from .problem import _error

        grids = np.meshgrid(*value_lists, indexing="ij")
        kwargs = {n: g for n, g in zip(names, grids)}
        shape = grids[0].shape

        feasible = np.ones(shape, dtype=bool)
        for con in problem.constraints:
            try:
                vals = con.expr(**kwargs)
                mask = con.predicate(vals)
            except (TypeError, ValueError) as e:
                raise TypeError(
                    f"Constraint '{con.name}': vectorised evaluation failed "
                    f"({e}). Use numpy-compatible ops (np.sqrt not "
                    f"math.sqrt; (a <= z) & (z <= b) not a <= z <= b), "
                    f"or pass vectorise=False."
                ) from e
            feasible &= np.asarray(mask, dtype=bool)

        composite = np.zeros(shape, dtype=float)
        breakdown_arrays = {}
        for t in problem.targets:
            try:
                actual = t.expr(**kwargs)
                err_arr = _error(actual, t.target, t.metric)
            except (TypeError, ValueError) as e:
                raise TypeError(
                    f"Target '{t.name}': vectorised evaluation failed "
                    f"({e}). Use numpy-compatible ops (np.sqrt not "
                    f"math.sqrt), or pass vectorise=False."
                ) from e
            breakdown_arrays[t.name] = np.broadcast_to(err_arr, shape)
            composite = composite + t.weight * err_arr

        composite_masked = np.where(feasible, composite, np.inf)
        flat = composite_masked.ravel()
        n = min(n_results, int(np.isfinite(flat).sum()))
        if n == 0:
            return []
        top_indices = np.argsort(flat)[:n]

        candidates = []
        for idx in top_indices:
            multi_idx = np.unravel_index(int(idx), shape)
            values = {n_: float(grids[i][multi_idx])
                      for i, n_ in enumerate(names)}
            breakdown = {k: float(arr[multi_idx])
                         for k, arr in breakdown_arrays.items()}
            candidates.append(Result(values=values, breakdown=breakdown))

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
