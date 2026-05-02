"""E-series optimisation framework.

Define a Problem with E-series-constrained components, soft targets, and
optional hard constraints, then solve to get ranked candidate assignments.

    import math
    from utils.eseries_opt import Problem, Resistor, Capacitor

    p = Problem()
    p.add(Resistor("R",  e_series=96, range=(1e3, 1e5)))
    p.add(Capacitor("C", e_series=24, range=(1e-9, 1e-6)))
    p.add_target("fc", lambda R, C: 1/(2*math.pi*R*C), target=1591.55)
    for r in p.solve(n_results=5):
        print(r)
"""

from .components import Component, Resistor, Capacitor, Inductor
from .problem import Problem, Target, Constraint
from .result import Result
from .ranking import WeightedSum, Lexicographic, Pareto
from .strategies import BruteForce, FactorOne, RelaxAndSnap

__all__ = [
    "Component", "Resistor", "Capacitor", "Inductor",
    "Problem", "Target", "Constraint",
    "Result",
    "WeightedSum", "Lexicographic", "Pareto",
    "BruteForce", "FactorOne", "RelaxAndSnap",
]
