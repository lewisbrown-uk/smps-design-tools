"""Per-sample thermal-sensitivity analysis via paired-T dithering.

For each MC sample, evaluate the user's metrics twice — once at
``T_nominal`` and once at ``T_nominal + T_dither`` — with the SAME
component perturbations. The per-sample slope ``∂metric/∂T`` is
exposed as a derived metric named ``{metric}_dT``.

Use cases:

- **Power-dissipation thermal sensitivity**: include ``P_<device>``
  in your metrics; the resulting ``P_<device>_dT`` is the rate at
  which the device's dissipation grows per K of ambient warming.
  Combined with the package thermal resistance R_th_J→A, the
  classical runaway criterion is ``dP/dT × R_th > 1``. Safe designs
  sit well below 1 across the full MC distribution; flag with a
  spec like ``"P_Q1_dT": ("<", 0.005)`` (5 mW/K, comfortably below
  the 10 mW/K runaway threshold for a TO-92 at 100 K/W).

- **Bias-stability metrics**: include ``Iq``, ``Vout``, etc. as
  metrics; the ``_dT`` derivatives quantify drift in operating
  point per K. A spec on these distinguishes well-compensated
  designs (small slopes) from poorly-compensated ones (large slopes
  driven by V_BE drift, β temperature behaviour, leakage growth).

Scope and limits:

- The dither captures the **device's intrinsic temperature
  response** — the metric's ∂g/∂T with components held fixed at
  their (already perturbed for T_nominal) values. Component drift
  with T is NOT swept here; for that, run ``analyze_corners`` over
  a wide T range, which re-applies tempcos at each corner.
- Cost is **2× the simulator calls** of plain ``analyze`` because
  every sample is evaluated at two temperatures. The cache helps
  for downstream re-runs but not within a single sweep (each
  paired call is a fresh point).
- The slope is finite-difference, so ``T_dither`` should be small
  enough to be locally linear (< ~10 K for most semiconductor
  parameters) but large enough above numerical noise. Default 5 K
  is a sensible starting point; sanity-check by re-running with
  ``T_dither=2`` and ``T_dither=10`` and confirming the slopes
  match.
"""
from .analyze import analyze
from .samplers import Constant


def thermal_dither(*, nominal_values, passive_tolerances, metrics, spec,
                    T_nominal=25.0, T_dither=5.0,
                    n_mc=1000, seed=None,
                    tolerance_sigma=3.0, distribution="gaussian",
                    active_devices=None, correlations=None,
                    temperature_coefficients=None,
                    workers=1):
    """Paired-T MC analysis. Returns the same ``YieldReport`` shape as
    ``analyze``, with the user's metrics plus auto-derived ``{m}_dT``
    slopes.

    Args:
        T_nominal: ambient T at which the primary evaluation happens.
            All ``_dT`` slopes are computed around this point.
        T_dither: ΔT used for the paired evaluation. Default 5 K.
            Smaller is more local but more numerically noisy; larger
            risks crossing non-linearities.

        Other args: same shape as ``analyze``. ``temperature`` is
        always set internally to ``Constant(T_nominal)`` — random-T
        sampling and dithering don't compose cleanly. For a yield
        curve over T, run ``temperature_sweep`` instead and post-
        process per-corner data for slopes.

    The user's ``metrics`` callable must accept ``T`` as a kwarg —
    that's how the helper varies the temperature between paired
    evaluations.
    """
    if T_dither <= 0:
        raise ValueError(f"T_dither must be > 0, got {T_dither}")

    def metrics_paired(**values):
        T = values.pop("T", T_nominal)
        m_a = metrics(T=T, **values)
        m_b = metrics(T=T + T_dither, **values)
        out = dict(m_a)
        for k, v in m_a.items():
            try:
                out[f"{k}_dT"] = (m_b[k] - v) / T_dither
            except (TypeError, KeyError, ZeroDivisionError):
                out[f"{k}_dT"] = float("nan")
        return out

    # Forward signature() if the underlying callable has one (cache key)
    if hasattr(metrics, "signature"):
        sig = metrics.signature
        metrics_paired.signature = (
            lambda: f"thermal_dither_{T_dither}_" + str(sig())
        )

    return analyze(
        nominal_values=nominal_values,
        passive_tolerances=passive_tolerances,
        metrics=metrics_paired,
        spec=spec,
        n_mc=n_mc, seed=seed,
        tolerance_sigma=tolerance_sigma,
        distribution=distribution,
        active_devices=active_devices,
        correlations=correlations,
        temperature=Constant(value=T_nominal),
        temperature_coefficients=temperature_coefficients,
        temperature_nominal=T_nominal,
        workers=workers,
    )
