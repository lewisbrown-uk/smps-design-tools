"""Tempco models beyond the simple multiplicative scalar.

The bare-scalar form in ``temperature_coefficients={"R": 50e-6}``
applies ``value(T) = nominal · (1 + tc · ΔT)``. That's correct for
ratiometric drift (passive R/C tempcos, op-amp Avol/GBW drift) but
breaks for active-device parameters that don't fit:

- **Op-amp Vos drift**: nominal Vos is zero, so multiplicative gives
  zero drift. The right model is *additive* with a per-part drift
  coefficient: ``Vos(T) = Vos_25 + drift_i · ΔT`` where ``drift_i``
  is sampled once per part from a distribution (typically zero-mean
  Gaussian with σ = the datasheet's drift spec).
- **Op-amp Ib (bipolar)**: doubles every ~10°C; exponential, not
  linear. Add an ``Exponential`` model later if a real circuit needs it.

Use these where bare scalars don't fit; ``temperature_coefficients``
accepts a mix of scalars and tempco-model instances.
"""
from dataclasses import dataclass

import numpy as np


@dataclass
class Exponential:
    """Exponential tempco: ``value(T) = value · factor ^ ((T - T_nominal)/per_K)``.

    Headline use case: bipolar op-amp input bias current, which doubles
    roughly every 10°C — ``Exponential(factor=2, per_K=10)``. CMOS
    leakage current has a similar pattern but with a different per_K
    (typically 8-10°C as well, but the absolute current at room temp
    is much smaller).

    Args:
        factor: scale factor over each ``per_K`` of warming. ``2`` for
            doubling-every-N-degrees patterns. Use ``< 1`` for params
            that decrease with temperature.
        per_K: temperature interval over which one ``factor`` of
            scaling happens.
    """
    factor: float
    per_K: float

    def apply(self, sample_array: np.ndarray, T_samples: np.ndarray,
              T_nominal: float, rng: np.random.Generator) -> np.ndarray:
        scale = self.factor ** ((T_samples - T_nominal) / self.per_K)
        return sample_array * scale


@dataclass
class Additive:
    """Additive tempco with per-part drift coefficient.

    ``value_eff(T) = value_sample + drift_per_part · (T - T_nominal)``

    where ``drift_per_part`` is sampled once per MC iteration from
    ``Normal(mean, sigma)``. Use sigma equal to the datasheet's
    quoted drift spec (e.g., NE5532 Vos drift ~5 µV/°C → sigma=5e-6).

    Headline use case: op-amp Vos drift. Without this, modelling Vos
    at corners would just sample the same room-temp distribution at
    every T, missing the per-part T-coefficient that's the real
    binding factor for precision amps.

    Args:
        sigma: standard deviation of the per-part drift coefficient,
            in units of (param-units / °C). Sampled per MC sample,
            independent across components.
        mean: optional systematic drift offset (default 0). For
            unbiased datasheet-typical drift specs, leave at 0.
    """
    sigma: float
    mean: float = 0.0

    def apply(self, sample_array: np.ndarray, T_samples: np.ndarray,
              T_nominal: float, rng: np.random.Generator) -> np.ndarray:
        """Apply additive tempco. ``sample_array`` is the per-MC
        column of the chosen component's pre-tempco values; ``T_samples``
        is the per-MC ambient temperatures. Returns the tempco-adjusted
        array (does not modify ``sample_array`` in place)."""
        drifts = rng.normal(self.mean, self.sigma, len(sample_array))
        return sample_array + drifts * (T_samples - T_nominal)
