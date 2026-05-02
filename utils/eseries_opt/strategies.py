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
    """Solve one component analytically given the others. Not yet implemented."""

    def solve(self, problem, n_results, ranker):
        raise NotImplementedError("FactorOne not yet implemented")


class RelaxAndSnap:
    """Continuous solve via scipy.optimize then enumerate the K nearest
       E-series values per component. Not yet implemented."""

    def solve(self, problem, n_results, ranker):
        raise NotImplementedError("RelaxAndSnap not yet implemented")


class BranchAndBound:
    """Reserved. Will accept per-target bound= callables to prune subtrees."""

    def solve(self, problem, n_results, ranker):
        raise NotImplementedError("BranchAndBound not yet implemented")
