"""E-series optimisation framework — stub.

Public surface only; everything that does real work raises NotImplementedError.
This stub exists so tests/test_eseries_opt.py collects per-test rather than
failing wholesale at import. Replace with the real implementation.
"""


class Component:
    def __init__(self, name, e_series, range, unit=""):
        self.name = name
        self.e_series = e_series
        self.range = range
        self.unit = unit

    def values(self):
        raise NotImplementedError


class Resistor(Component):
    pass


class Capacitor(Component):
    pass


class Inductor(Component):
    pass


class Lexicographic:
    def __init__(self, order, epsilon=0.0):
        self.order = order
        self.epsilon = epsilon


class Pareto:
    def __init__(self):
        pass


class Problem:
    def __init__(self):
        self.components = []
        self.targets = []
        self.constraints = []

    def add(self, component):
        raise NotImplementedError

    def add_target(self, name, expr, target, weight=1.0, metric="rel"):
        raise NotImplementedError

    def add_constraint(self, name, expr, predicate):
        raise NotImplementedError

    def solve(self, strategy="auto", n_results=10, rank=None, sensitivity_tol=0.01):
        raise NotImplementedError
