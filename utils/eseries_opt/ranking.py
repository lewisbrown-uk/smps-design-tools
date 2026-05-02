class WeightedSum:
    """Composite error = sum of (weight × per-target error). Default ranker."""

    def rank(self, candidates, targets):
        weights = {t.name: t.weight for t in targets}
        for c in candidates:
            c.error = sum(weights[k] * v for k, v in c.breakdown.items())
        return sorted(candidates, key=lambda c: c.error)


class Lexicographic:
    """Rank by targets in priority order; ties (within epsilon on each
    level) fall through to the next target.

    A leading group within ``epsilon`` of the best on the primary target
    is resolved by the secondary target, that group's leaders by the
    tertiary, and so on. ``epsilon=0`` is strict lexicographic.

    Args:
        order:   Target names, most-important first.
        epsilon: Absolute tie-band width on each level.
    """

    def __init__(self, order, epsilon=0.0):
        self.order = order
        self.epsilon = epsilon

    def rank(self, candidates, targets):
        if not candidates:
            return []
        target_by_name = {t.name: t for t in targets}
        missing = [n for n in self.order if n not in target_by_name]
        if missing:
            raise ValueError(
                f"Lexicographic order references unknown target(s): "
                f"{missing}. Known: {sorted(target_by_name)}"
            )
        ordered = [target_by_name[n] for n in self.order]

        # Assign composite error for the .error field (for display).
        # Sort order is determined by lex on per-target errors, not by .error.
        weights = {t.name: t.weight for t in targets}
        for c in candidates:
            c.error = sum(weights[k] * v for k, v in c.breakdown.items())

        return self._lex_sort(list(candidates), ordered)

    def _lex_sort(self, candidates, ordered_targets):
        if not ordered_targets or len(candidates) <= 1:
            return candidates
        primary = ordered_targets[0]
        rest = ordered_targets[1:]
        sorted_cands = sorted(candidates,
                              key=lambda c: c.breakdown[primary.name])
        out = []
        i = 0
        while i < len(sorted_cands):
            best = sorted_cands[i].breakdown[primary.name]
            j = i + 1
            while (j < len(sorted_cands) and
                   sorted_cands[j].breakdown[primary.name] - best
                   <= self.epsilon):
                j += 1
            out.extend(self._lex_sort(sorted_cands[i:j], rest))
            i = j
        return out


class Pareto:
    """Return only the non-dominated frontier — candidates such that no
    other candidate is no-worse on every target AND strictly better on
    at least one. Within the frontier, secondary sort by WeightedSum.

    Naive O(N^2 × M) dominance check. Adequate for candidate counts up
    to a few thousand, which covers BruteForce on small problems and
    RelaxAndSnap's K^N snap neighbourhood. Larger sets would need an
    efficient frontier algorithm.
    """

    def rank(self, candidates, targets):
        if not candidates:
            return []
        target_names = [t.name for t in targets]
        weights = {t.name: t.weight for t in targets}
        for c in candidates:
            c.error = sum(weights[k] * v for k, v in c.breakdown.items())

        frontier = []
        for c in candidates:
            dominated = any(
                _dominates(other, c, target_names)
                for other in candidates if other is not c
            )
            if not dominated:
                frontier.append(c)
        return sorted(frontier, key=lambda c: c.error)


def _dominates(a, b, target_names):
    """a dominates b iff a is no worse on every target AND strictly
    better on at least one."""
    strictly_better = False
    for n in target_names:
        if a.breakdown[n] > b.breakdown[n]:
            return False
        if a.breakdown[n] < b.breakdown[n]:
            strictly_better = True
    return strictly_better
