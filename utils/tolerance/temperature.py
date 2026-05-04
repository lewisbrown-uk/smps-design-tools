"""Temperature-corner and temperature-sweep helpers.

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
"""
from dataclasses import dataclass, field
from typing import Iterable, List, Tuple

from .analyze import analyze
from .report import YieldReport
from .samplers import Constant


@dataclass
class CornerReport:
    """One YieldReport per temperature corner, plus aggregate
    summary across corners."""
    corners: List[Tuple[float, YieldReport]] = field(default_factory=list)
    """``[(T_celsius, YieldReport), ...]`` in the order requested."""

    @property
    def worst_yield(self) -> float:
        """Yield % at the worst-performing corner. Use this as the
        single design-passes-everywhere number."""
        if not self.corners:
            return float("nan")
        return min(r.yield_pct for _, r in self.corners)

    @property
    def worst_corner(self) -> float:
        """Temperature (°C) of the worst-performing corner."""
        if not self.corners:
            return float("nan")
        return min(self.corners, key=lambda tr: tr[1].yield_pct)[0]

    def __str__(self):
        if not self.corners:
            return "CornerReport: no corners evaluated"
        lines = [f"Worst corner: T = {self.worst_corner:+.1f}°C, "
                 f"yield = {self.worst_yield:.2f}%"]
        lines.append(f"{'T (°C)':>8s}  {'yield':>7s}  per-spec yields")
        for T, r in self.corners:
            spec_str = ", ".join(f"{n} {100*c/r.samples_total:.1f}%"
                                  for n, c in r.per_spec_pass.items())
            lines.append(f"{T:>+8.1f}  {r.yield_pct:>6.2f}%  {spec_str}")
        return "\n".join(lines)


def analyze_corners(*, temperature_corners: Iterable[float],
                    nominal_values, passive_tolerances, metrics, spec,
                    n_mc=1000, seed=None,
                    tolerance_sigma=3.0, distribution="gaussian",
                    active_devices=None,
                    correlations=None,
                    temperature_coefficients=None,
                    temperature_nominal=25.0,
                    workers=1) -> CornerReport:
    """Run an MC at each given T corner. Returns ``CornerReport`` with
    a YieldReport per corner plus aggregate worst-corner numbers.

    The MC at each corner uses ``Constant(T)`` internally — T is
    fixed, so all the n_mc samples land at exactly that T and the
    per-corner yield CI is determined by n_mc alone (no smearing
    across a T band).

    All other args are forwarded to ``analyze``. ``seed`` is reused
    across corners so the comparison is paired (each corner sees the
    same component-perturbation pattern), reducing the variance of
    ``yield(T1) - yield(T2)`` differences relative to independent
    seeds.

    Industry convention: pick at least three corners — minimum,
    nominal, maximum — of the operating range. Add intermediate
    corners (e.g. 0°C, 50°C) if the temperature_coefficients are
    non-monotonic or active-device behaviour has internal turn-over
    points (e.g. bandgap reference TC zero crossing). Use
    ``temperature_sweep`` for finer T resolution.
    """
    corners = list(temperature_corners)
    if not corners:
        raise ValueError("temperature_corners must be non-empty")

    results = []
    for T in corners:
        report = analyze(
            nominal_values=nominal_values,
            passive_tolerances=passive_tolerances,
            metrics=metrics,
            spec=spec,
            n_mc=n_mc, seed=seed,
            tolerance_sigma=tolerance_sigma,
            distribution=distribution,
            active_devices=active_devices,
            correlations=correlations,
            temperature=Constant(value=float(T)),
            temperature_coefficients=temperature_coefficients,
            temperature_nominal=temperature_nominal,
            workers=workers,
        )
        results.append((float(T), report))
    return CornerReport(corners=results)


def temperature_sweep(*, temperature_points: Iterable[float],
                      nominal_values, passive_tolerances, metrics, spec,
                      n_mc=1000, seed=None,
                      tolerance_sigma=3.0, distribution="gaussian",
                      active_devices=None,
                      correlations=None,
                      temperature_coefficients=None,
                      temperature_nominal=25.0,
                      workers=1) -> CornerReport:
    """Sweep T across a range, MC at each point. Same return type as
    ``analyze_corners`` but typically with many more points (e.g.
    every 5°C across the operating range) for finding non-monotonic
    yield behaviour.

    Same pairing convention: ``seed`` reused across all T points.

    Cost: ``len(temperature_points)`` × ``n_mc`` simulator calls.
    For 26 points × 1000 samples = 26k MC calls, plus the n_mc cost
    per call. Closed-form metrics: seconds. ngspice metrics:
    consider running the points concurrently with ``workers > 1``
    inside each call, or partition across cluster nodes.
    """
    return analyze_corners(
        temperature_corners=list(temperature_points),
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
