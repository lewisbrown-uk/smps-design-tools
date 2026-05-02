class WeightedSum:
    """Composite error = sum of (weight × per-target error). Default ranker."""

    def rank(self, candidates, targets):
        weights = {t.name: t.weight for t in targets}
        for c in candidates:
            c.error = sum(weights[k] * v for k, v in c.breakdown.items())
        return sorted(candidates, key=lambda c: c.error)


class Lexicographic:
    """Rank by targets in priority order; ties (within epsilon) fall through
       to the next target. Not yet implemented."""

    def __init__(self, order, epsilon=0.0):
        self.order = order
        self.epsilon = epsilon

    def rank(self, candidates, targets):
        raise NotImplementedError("Lexicographic ranking not yet implemented")


class Pareto:
    """Return only the non-dominated frontier. Not yet implemented."""

    def __init__(self):
        pass

    def rank(self, candidates, targets):
        raise NotImplementedError("Pareto ranking not yet implemented")
