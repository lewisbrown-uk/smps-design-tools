"""Generic parametric sweeps over any external parameter.

Generalises the temperature-specific helpers (``analyze_corners``,
``temperature_sweep``, ``thermal_dither``) to work with **any** kwarg
the user's metrics callable accepts: ``T``, ``Vin``, ``Iload``,
``f``, supply voltage, bias current, anything.

Two patterns:

- **`parametric_sweep`** — MC at each of N fixed values of the
  swept parameter. Returns one ``YieldReport`` per value plus
  worst-corner aggregates. Use for "does this design pass at every
  operating point?" questions: line regulation across Vin range,
  load regulation across Iload range, T corners across the operating
  range, etc.

- **`parametric_dither`** — paired-sample evaluation at base and
  base+dither, exposes per-metric slopes ``{m}_d{param}`` as derived
  metrics. Use for sensitivity questions: ∂Vout/∂Iload (load reg
  slope), ∂P/∂T (thermal sensitivity / runaway proxy), ∂fc/∂Vsupply
  (PSRR), etc.

Pairing: the same RNG seed is reused across all parameter values, so
each value's MC sees the same component-perturbation pattern. This
gives variance-reduced comparison across the sweep — `slope` and
`worst_yield_difference` estimates are dramatically tighter than
they would be under independent seeds.

Special case for ``parameter='T'``: the temperature-coefficient
machinery applies (component values drift with T per
``temperature_coefficients`` and ``DEVICE_TEMPCOS``). For other
parameters, no tempcos — the parameter is injected as a pinned
input value.
"""
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Tuple

from .analyze import analyze
from .report import YieldReport
from .samplers import Constant, Sampler


@dataclass
class SweepReport:
    """One YieldReport per swept-parameter value, plus aggregates.
    Generalises ``CornerReport`` to any parameter — keeps the same
    field names so display code that uses ``corners`` doesn't break."""
    parameter: str = "T"
    """Name of the swept parameter (kwarg the metrics callable
    receives). Used by ``__str__`` for display."""
    unit: str = "°C"
    """Display unit shown in ``__str__``."""
    corners: List[Tuple[float, YieldReport]] = field(default_factory=list)
    """``[(value, YieldReport), ...]`` in the order requested."""

    @property
    def worst_yield(self) -> float:
        """Yield % at the worst-performing parameter value."""
        if not self.corners:
            return float("nan")
        return min(r.yield_pct for _, r in self.corners)

    @property
    def worst_corner(self) -> float:
        """Parameter value where yield is lowest."""
        if not self.corners:
            return float("nan")
        return min(self.corners, key=lambda tr: tr[1].yield_pct)[0]

    def __str__(self):
        if not self.corners:
            return "SweepReport: no values evaluated"
        lines = [f"Worst {self.parameter} = "
                 f"{self.worst_corner:+g} {self.unit}, "
                 f"yield = {self.worst_yield:.2f}%"]
        header = f"{self.parameter} ({self.unit})"
        lines.append(f"{header:>14s}  {'yield':>7s}  per-spec yields")
        for v, r in self.corners:
            spec_str = ", ".join(f"{n} {100*c/r.samples_total:.1f}%"
                                  for n, c in r.per_spec_pass.items())
            lines.append(f"{v:>+14g}  {r.yield_pct:>6.2f}%  {spec_str}")
        return "\n".join(lines)


def _inject_parameter(parameter, value, nominal_values, distribution,
                       passive_tolerances, temperature):
    """Pin ``parameter`` to ``value`` for one analyze call.

    Two paths:

    - ``parameter == 'T'``: use the analyze ``temperature=`` machinery
      (triggers the tempco loop that drifts component values with T).
    - Other parameters: inject via ``Constant`` sampler in
      ``distribution`` + augmented ``nominal_values``. The user's
      ``temperature=`` (if any) is forwarded to analyze unchanged —
      pass ``Constant(25)`` if your template needs ``.temp {T}``
      fixed at room T while you're sweeping Vin / Iload / etc.
    """
    if parameter == "T":
        return (
            nominal_values, distribution,
            {"temperature": Constant(value=float(value))},
        )
    if parameter in nominal_values:
        raise ValueError(
            f"parameter {parameter!r} is already in nominal_values — "
            f"swept parameters must not also be component nominals"
        )
    aug_nominal = {**nominal_values, parameter: float(value)}
    aug_dist = (dict(distribution) if isinstance(distribution, dict)
                else {})
    aug_dist[parameter] = Constant(value=float(value))
    extras = {} if temperature is None else {"temperature": temperature}
    return (aug_nominal, aug_dist, extras)


def parametric_sweep(*, parameter: str, values: Iterable[float],
                      nominal_values, passive_tolerances, metrics, spec,
                      n_mc=1000, seed=None,
                      tolerance_sigma=3.0, distribution="gaussian",
                      active_devices=None, correlations=None,
                      temperature=None,
                      temperature_coefficients=None,
                      temperature_nominal=25.0,
                      unit: str = "",
                      workers=1) -> SweepReport:
    """Run an MC at each value of the swept parameter.

    Args:
        parameter: name of the kwarg the metrics callable receives.
            For ``'T'``, the analyze tempco machinery applies
            automatically. For any other name, the parameter is
            injected as a pinned input via ``Constant`` sampler.
        values: parameter values to evaluate at. Sampled in order;
            the same ``seed`` is used at each value for paired
            comparison.
        unit: display string in the SweepReport (e.g. ``'V'``,
            ``'mA'``, ``'kHz'``). Default ``'°C'`` when
            ``parameter == 'T'`` for backward compatibility.

        Other args: same shape as ``analyze``. ``temperature``,
        ``temperature_coefficients``, and ``temperature_nominal``
        are forwarded to ``analyze`` only when the swept parameter
        is ``'T'``; for other parameters they're inert.

    Returns:
        ``SweepReport`` with one ``YieldReport`` per value, plus
        worst-corner aggregates.
    """
    values = list(values)
    if not values:
        raise ValueError("values must be non-empty")
    if not parameter:
        raise ValueError("parameter must be a non-empty string")

    if not unit:
        unit = "°C" if parameter == "T" else ""

    results = []
    for v in values:
        nominal, dist, extras = _inject_parameter(
            parameter, v, nominal_values, distribution, passive_tolerances,
            temperature,
        )
        report = analyze(
            nominal_values=nominal,
            passive_tolerances=passive_tolerances,
            metrics=metrics,
            spec=spec,
            n_mc=n_mc, seed=seed,
            tolerance_sigma=tolerance_sigma,
            distribution=dist,
            active_devices=active_devices,
            correlations=correlations,
            temperature_coefficients=temperature_coefficients,
            temperature_nominal=temperature_nominal,
            workers=workers,
            **extras,
        )
        results.append((float(v), report))
    return SweepReport(parameter=parameter, unit=unit, corners=results)


def parametric_dither(*, parameter: str, base: float, dither: float,
                       nominal_values, passive_tolerances, metrics, spec,
                       n_mc=1000, seed=None,
                       tolerance_sigma=3.0, distribution="gaussian",
                       active_devices=None, correlations=None,
                       temperature=None,
                       temperature_coefficients=None,
                       temperature_nominal=25.0,
                       workers=1):
    """Per-sample paired evaluation at ``base`` and ``base + dither``.

    For each MC sample the metric is evaluated at two values of the
    swept parameter with the SAME component perturbations. The
    finite-difference slope ``∂metric/∂param`` is exposed as a
    derived metric named ``{metric}_d{parameter}``. Spec on those
    derived metrics to bound parameter sensitivity.

    Headline use cases:

    - ``parameter='T'``, slope ``P_Q1_dT``: thermal-sensitivity,
      runaway proxy.
    - ``parameter='Iload'``, slope ``Vout_dIload``: load-regulation
      sensitivity.
    - ``parameter='Vin'``, slope ``Vout_dVin``: line regulation /
      PSRR-DC.
    - ``parameter='f'``, slope ``|H|_df``: filter-rolloff slope.

    Args:
        parameter: kwarg name passed to metrics for the dither.
        base: nominal parameter value.
        dither: ΔX for the paired evaluation. Small enough to be
            locally linear in ``parameter``, large enough above
            numerical noise. Default-sized values (5K for T, 10mA
            for currents, 1V for supplies) usually work; sanity-
            check by halving and confirming the slopes match.

        Other args: same shape as ``analyze``. Cost is **2× the
        simulator calls** of plain analyze.

    Returns:
        ``YieldReport`` with the user's metrics PLUS auto-derived
        ``{m}_d{param}`` slopes.
    """
    if dither == 0:
        raise ValueError(f"dither must be non-zero, got {dither}")

    def metrics_paired(**values):
        v = values.pop(parameter, base)
        m_a = metrics(**{parameter: v, **values})
        m_b = metrics(**{parameter: v + dither, **values})
        out = dict(m_a)
        for k, val in m_a.items():
            try:
                out[f"{k}_d{parameter}"] = (m_b[k] - val) / dither
            except (TypeError, KeyError, ZeroDivisionError):
                out[f"{k}_d{parameter}"] = float("nan")
        return out

    # Forward signature() if the underlying callable has one (cache key)
    if hasattr(metrics, "signature"):
        sig = metrics.signature
        metrics_paired.signature = (
            lambda: f"dither_{parameter}_{dither}_" + str(sig())
        )

    nominal, dist, extras = _inject_parameter(
        parameter, base, nominal_values, distribution, passive_tolerances,
        temperature,
    )
    return analyze(
        nominal_values=nominal,
        passive_tolerances=passive_tolerances,
        metrics=metrics_paired,
        spec=spec,
        n_mc=n_mc, seed=seed,
        tolerance_sigma=tolerance_sigma,
        distribution=dist,
        active_devices=active_devices,
        correlations=correlations,
        temperature_coefficients=temperature_coefficients,
        temperature_nominal=temperature_nominal,
        workers=workers,
        **extras,
    )
