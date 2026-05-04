"""Temperature-corner and temperature-sweep helpers.

Thin wrappers around the generic ``parametric_sweep`` for the most
common case: T sweeps. For sweeps over other parameters (Vin, Iload,
frequency, ...) use ``parametric_sweep`` directly.

The default ``analyze(temperature=Sampler(...))`` mode samples T per
MC iteration. Useful when temperature genuinely varies during
operation (the "what fraction of moments are in spec" question), but
poor at giving tight confidence intervals on per-temperature
behaviour because each T-band gets only n_mc/(range/band_width)
samples — typically 30-50 per 5°C window at n_mc=1000.

For the engineering questions that actually come up most:

- **"Does the design meet spec at every operating-range corner?"**
  → ``analyze_corners(temperature_corners=[-40, 25, 85])``.
  Standard industry practice. Returns one full YieldReport per
  corner plus a worst-corner aggregate.

- **"Yield-vs-T curve, where does it dip?"**
  → ``temperature_sweep(temperature_points=range(-40, 86, 5))``.
  Returns yield(T) and metric stats(T) for each T point.

Both modes use ``Constant(T)`` internally for each sampled T —
zero T-variance per call, so the per-corner / per-sweep-point yield
is sharp at that temperature instead of being smeared across a
band.

For backward compatibility ``CornerReport`` is exported as an alias
of ``SweepReport``.
"""
from typing import Iterable

from .parametric import SweepReport, parametric_sweep


# Backward-compat alias — old code expects CornerReport
CornerReport = SweepReport


def analyze_corners(*, temperature_corners: Iterable[float],
                    nominal_values, passive_tolerances, metrics, spec,
                    n_mc=1000, seed=None,
                    tolerance_sigma=3.0, distribution="gaussian",
                    active_devices=None,
                    correlations=None,
                    temperature_coefficients=None,
                    temperature_nominal=25.0,
                    workers=1) -> SweepReport:
    """Run an MC at each given T corner. Thin wrapper over
    ``parametric_sweep(parameter='T', ...)``.

    Industry convention: pick at least three corners — minimum,
    nominal, maximum — of the operating range. Add intermediate
    corners (e.g. 0°C, 50°C) if the temperature_coefficients are
    non-monotonic or active-device behaviour has internal turn-over
    points (e.g. bandgap reference TC zero crossing). Use
    ``temperature_sweep`` for finer T resolution.
    """
    return parametric_sweep(
        parameter="T", values=temperature_corners, unit="°C",
        nominal_values=nominal_values,
        passive_tolerances=passive_tolerances,
        metrics=metrics, spec=spec,
        n_mc=n_mc, seed=seed,
        tolerance_sigma=tolerance_sigma,
        distribution=distribution,
        active_devices=active_devices,
        correlations=correlations,
        temperature_coefficients=temperature_coefficients,
        temperature_nominal=temperature_nominal,
        workers=workers,
    )


def temperature_sweep(*, temperature_points: Iterable[float],
                      nominal_values, passive_tolerances, metrics, spec,
                      n_mc=1000, seed=None,
                      tolerance_sigma=3.0, distribution="gaussian",
                      active_devices=None,
                      correlations=None,
                      temperature_coefficients=None,
                      temperature_nominal=25.0,
                      workers=1) -> SweepReport:
    """Sweep T across a range, MC at each point. Synonym for
    ``analyze_corners`` — naming convention only (sweep = many
    points, corners = a few). For other-parameter sweeps see
    ``parametric_sweep`` directly.

    Cost: ``len(temperature_points)`` × ``n_mc`` simulator calls.
    For 26 points × 1000 samples = 26k MC calls, plus the n_mc cost
    per call. Closed-form metrics: seconds. ngspice metrics:
    consider running the points concurrently with ``workers > 1``
    inside each call, or partition across cluster nodes.
    """
    return parametric_sweep(
        parameter="T", values=temperature_points, unit="°C",
        nominal_values=nominal_values,
        passive_tolerances=passive_tolerances,
        metrics=metrics, spec=spec,
        n_mc=n_mc, seed=seed,
        tolerance_sigma=tolerance_sigma,
        distribution=distribution,
        active_devices=active_devices,
        correlations=correlations,
        temperature_coefficients=temperature_coefficients,
        temperature_nominal=temperature_nominal,
        workers=workers,
    )
