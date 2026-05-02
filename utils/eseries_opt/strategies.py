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
    """Continuous solve via scipy.optimize, then enumerate the K nearest
    E-series values per component and brute-force the K^N neighbourhood.

    Default for >=4 components in auto-dispatch. Optimal when the discrete
    optimum lies geometrically near the continuous one — typical for smooth
    objectives. Can miss the true discrete optimum when the continuous
    landscape is flat (many points achieve the same continuous error) and
    the snap neighbourhood happens to fall in a ridge that excludes the
    discrete winner. Increase ``k`` to widen the neighbourhood at the cost
    of K^N evaluations.

    The continuous solve runs in log10-space so wide-ranging components
    (1k-1M) get balanced gradient/scale treatment. Constraint predicates
    are enforced via a large additive penalty in the continuous objective.

    Args:
        k:      Number of nearest E-series values per component to enumerate
                in the snap step. Default 5.
        method: scipy.optimize method. "differential_evolution" (default)
                is a global solver and handles non-smooth, non-convex
                composite-error landscapes; pass an scipy.optimize.minimize
                method name (e.g. "L-BFGS-B") for fast local search.
        seed:   Random seed for differential_evolution. Set for determinism.
    """

    def __init__(self, k=5, method="differential_evolution", seed=0):
        self.k = k
        self.method = method
        self.seed = seed

    def solve(self, problem, n_results, ranker):
        try:
            from scipy.optimize import differential_evolution, minimize
        except ImportError:
            raise ImportError(
                "RelaxAndSnap requires scipy. Install with: pip install scipy"
            ) from None
        from .problem import _error

        names = [c.name for c in problem.components]
        bounds_log = [(np.log10(c.range[0]), np.log10(c.range[1]))
                      for c in problem.components]

        def composite_error(log_x):
            x = 10.0 ** np.asarray(log_x)
            kwargs = {n: float(v) for n, v in zip(names, x)}
            penalty = 0.0
            for con in problem.constraints:
                if not con.predicate(con.expr(**kwargs)):
                    penalty += 1e12
            err = 0.0
            for t in problem.targets:
                err += t.weight * float(_error(t.expr(**kwargs),
                                               t.target, t.metric))
            return err + penalty

        if self.method == "differential_evolution":
            result = differential_evolution(composite_error, bounds_log,
                                            seed=self.seed, tol=1e-7,
                                            polish=True)
        else:
            x0 = np.array([(lo + hi) / 2 for lo, hi in bounds_log])
            result = minimize(composite_error, x0,
                              method=self.method, bounds=bounds_log)
        ideal = 10.0 ** np.asarray(result.x)

        neighbourhoods = []
        for comp, ideal_v in zip(problem.components, ideal):
            vals = comp.values()
            k = min(self.k, len(vals))
            log_dists = np.abs(np.log10(vals) - np.log10(ideal_v))
            idx = np.argpartition(log_dists, k - 1)[:k]
            neighbourhoods.append(vals[idx])

        candidates = []
        for combo in itertools.product(*neighbourhoods):
            kwargs = {n: float(v) for n, v in zip(names, combo)}
            if not all(con.predicate(con.expr(**kwargs))
                       for con in problem.constraints):
                continue
            breakdown = {
                t.name: float(_error(t.expr(**kwargs), t.target, t.metric))
                for t in problem.targets
            }
            candidates.append(Result(values=dict(kwargs), breakdown=breakdown))

        return ranker.rank(candidates, problem.targets)[:n_results]


class BranchAndBound:
    """Depth-first branch-and-bound over E-series values.

    At each internal node (a partial assignment), computes a lower bound
    on the WeightedSum composite error for any completion using each
    target's bounder, and prunes the subtree if that bound exceeds the
    worst error among the current top-N candidates. Also prunes when any
    range= constraint is provably infeasible (its value range as bounded
    over the subtree cannot intersect the constraint's accepting band).

    Soundness: bounds are only as sound as the bounders. The default
    auto-generated corner-evaluation bounders are sound for expressions
    monotonic in each component, which covers most circuit objectives
    and constraints. Non-monotonic expressions need an explicit
    ``bounder=`` to avoid silently pruning correct solutions.

    Targets without a bounder contribute zero to the lower bound (no
    pruning info on that target). Constraints without ``value_range``
    (i.e., custom predicate=) cannot be used for subtree pruning;
    they're only checked at leaves.

    Restricted to WeightedSum ranking — the lower-bound mechanism
    assumes a sum-of-weighted-errors composite.
    """

    def solve(self, problem, n_results, ranker):
        import heapq
        from .problem import _error, _min_error
        from .ranking import WeightedSum

        if not isinstance(ranker, WeightedSum):
            raise ValueError(
                f"BranchAndBound only supports WeightedSum ranking "
                f"(got {type(ranker).__name__})."
            )

        weights = {t.name: t.weight for t in problem.targets}
        heap = []          # max-heap-by-negation: (-error, id, Result)
        counter = [0]

        def best_so_far():
            if len(heap) < n_results:
                return float("inf")
            return -heap[0][0]

        def add_leaf(values_dict, breakdown):
            composite = sum(weights[k] * v for k, v in breakdown.items())
            r = Result(values=values_dict, breakdown=breakdown, error=composite)
            entry = (-composite, counter[0], r)
            counter[0] += 1
            if len(heap) < n_results:
                heapq.heappush(heap, entry)
            else:
                heapq.heappushpop(heap, entry)

        def free_ranges_for(remaining):
            return {c.name: (c.range[0], c.range[1]) for c in remaining}

        def lower_bound(fixed, remaining):
            free_r = free_ranges_for(remaining)
            lb = 0.0
            for t in problem.targets:
                if t.bounder is None:
                    continue
                vlo, vhi = t.bounder(fixed, free_r)
                lb += t.weight * _min_error(vlo, vhi, t.target, t.metric)
            return lb

        def is_feasible(fixed, remaining):
            free_r = free_ranges_for(remaining)
            for con in problem.constraints:
                if con.bounder is None or con.value_range is None:
                    continue   # arbitrary predicate; can't prune ahead of leaf
                vlo, vhi = con.bounder(fixed, free_r)
                lo, hi = con.value_range
                if vhi < lo or vlo > hi:
                    return False
            return True

        def branch(fixed, remaining):
            if not remaining:
                for con in problem.constraints:
                    if not con.predicate(con.expr(**fixed)):
                        return
                breakdown = {
                    t.name: float(_error(t.expr(**fixed), t.target, t.metric))
                    for t in problem.targets
                }
                add_leaf(dict(fixed), breakdown)
                return

            if not is_feasible(fixed, remaining):
                return
            if lower_bound(fixed, remaining) >= best_so_far():
                return

            comp = remaining[0]
            rest = remaining[1:]
            for value in comp.values():
                branch({**fixed, comp.name: float(value)}, rest)

        branch({}, list(problem.components))

        return sorted([r for _, _, r in heap], key=lambda r: r.error)[:n_results]
