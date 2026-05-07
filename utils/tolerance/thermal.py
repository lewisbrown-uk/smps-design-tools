"""Thermal-sensitivity analysis via paired-T dithering.

Thin wrapper around the generic ``parametric_dither`` for the
common temperature case. For dither over other parameters (Iload,
Vin, frequency, ...) use ``parametric_dither`` directly with the
appropriate ``parameter=`` and ``base=`` / ``dither=`` values.

For each MC sample, evaluate the user's metrics twice — once at
``T_nominal`` and once at ``T_nominal + T_dither`` — with the SAME
component perturbations. The per-sample slope ``∂metric/∂T`` is
exposed as a derived metric named ``{metric}_dT``.

Use cases:

- **Power-dissipation thermal sensitivity**: include ``P_<device>``
  in your metrics; the resulting ``P_<device>_dT`` is the rate at
  which the device's dissipation grows per K of ambient warming.
  Combined with the package thermal resistance R_th_J→A, the
  classical runaway criterion is ``dP/dT × R_th > 1``.

- **Bias-stability metrics**: include ``Iq``, ``Vout``, etc. as
  metrics; the ``_dT`` derivatives quantify drift in operating
  point per K.

Scope and limits:

- The dither captures the **device's intrinsic temperature
  response** — the metric's ∂g/∂T with components held fixed at
  their (already perturbed for T_nominal) values. Component drift
  with T is NOT swept here; for that, run ``analyze_corners`` over
  a wide T range, which re-applies tempcos at each corner.
- Cost is **2× the simulator calls** of plain ``analyze`` because
  every sample is evaluated at two temperatures.
- The slope is finite-difference, so ``T_dither`` should be small
  enough to be locally linear (< ~10 K for most semiconductor
  parameters) but large enough above numerical noise. Default 5 K
  is a sensible starting point.
"""
from .parametric import parametric_dither


def thermal_dither(*, nominal_values, passive_tolerances, metrics, spec,
                    T_nominal=25.0, T_dither=5.0,
                    n_mc=1000, seed=None,
                    tolerance_sigma=3.0, distribution="gaussian",
                    active_devices=None, correlations=None,
                    temperature_coefficients=None,
                    workers=1):
    """Paired-T MC analysis. Thin wrapper over
    ``parametric_dither(parameter='T', base=T_nominal,
    dither=T_dither, ...)`` — kept for backward compatibility and
    discoverability. Same return shape as ``analyze``."""
    if T_dither <= 0:
        raise ValueError(f"T_dither must be > 0, got {T_dither}")
    return parametric_dither(
        parameter="T", base=T_nominal, dither=T_dither,
        nominal_values=nominal_values,
        passive_tolerances=passive_tolerances,
        metrics=metrics, spec=spec,
        n_mc=n_mc, seed=seed,
        tolerance_sigma=tolerance_sigma,
        distribution=distribution,
        active_devices=active_devices,
        correlations=correlations,
        temperature_coefficients=temperature_coefficients,
        temperature_nominal=T_nominal,
        workers=workers,
    )
