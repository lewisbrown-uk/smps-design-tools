"""Closed-loop yield analysis for circuit candidates.

Companion to ``utils.eseries_opt``: takes one of its candidate component
assignments and reports realistic Monte-Carlo yield against a system-
level spec. See ``utils/tolerance/README.md`` for scope and the long
arc of slices this is the first of.

    from utils.tolerance import analyze

    report = analyze(
        nominal_values={"R1": 1e4, "R2": 1e4, "C1": 1e-8, "C2": 2.2e-8},
        passive_tolerances={"R": 0.01, "C": 0.05},
        metrics=lambda R1, R2, C1, C2: {
            "fc": 1 / (2 * math.pi * math.sqrt(R1*R2*C1*C2)),
            "Q":  math.sqrt(R1*R2*C2/C1) / (R1+R2),
        },
        spec={"fc": ("within", 0.05), "Q": ("within", 0.10)},
        n_mc=2000,
    )
    print(report)
"""

from .analyze import analyze
from .report import YieldReport, MetricStats
from .ngspice import NgspiceBackend
from .remote import RemoteNgspiceBackend
from .cache import CachedBackend
from .samplers import (
    Sampler,
    RelativeGaussian, RelativeUniform, AbsoluteGaussian,
    Uniform, LogUniform, Constant,
)
from .devices import DEVICES, expand_active_devices
from .spice_helpers import lockin_thd_block
from .robust_ranker import Robust
from .temperature import analyze_corners, temperature_sweep, CornerReport
from .tempco import Additive

__all__ = [
    "analyze",
    "YieldReport", "MetricStats",
    "NgspiceBackend", "RemoteNgspiceBackend", "CachedBackend",
    "Sampler", "RelativeGaussian", "RelativeUniform",
    "AbsoluteGaussian", "Uniform", "LogUniform", "Constant",
    "DEVICES", "expand_active_devices",
    "lockin_thd_block",
    "Robust",
    "analyze_corners", "temperature_sweep", "CornerReport",
    "Additive",
]
