"""Per-component sampling distributions.

Every component in an MC run — passive R/L/C, op-amp parameters, BJT β,
JFET Vto — is represented internally by a ``Sampler`` instance. The
existing string-based API (``passive_tolerances`` + ``distribution=
"gaussian"``) builds ``RelativeGaussian`` / ``RelativeUniform``
instances under the hood; user code can also pass ``Sampler`` objects
directly via ``distribution[name]`` for parameters that need shapes
the string API can't express (zero-mean Gaussian for op-amp Vos,
log-uniform for op-amp Avol, hard bounds for JFET Vto).

The four common shapes:

- ``RelativeGaussian(nominal, tol)`` — the default for passives;
  ``Normal(nominal, nominal·tol/sigmas)`` so the manufacturer's ±tol
  limit corresponds to ±``sigmas`` standard deviations (default 3).
- ``RelativeUniform(nominal, tol)`` — hard cutoff on
  ``[nominal·(1-tol), nominal·(1+tol)]``; flat density inside.
- ``AbsoluteGaussian(mean, sigma)`` — for params whose nominal is
  zero or whose spread is in absolute units (op-amp Vos in volts,
  Ib in amps).
- ``Uniform(lo, hi)`` — flat density on ``[lo, hi]`` with no nominal
  reference; for params whose datasheet specifies bounds and nothing
  about distribution shape (J201 Vto from −2.3 V to −0.4 V).
- ``LogUniform(lo, hi)`` — uniform in log space; for params spanning
  more than a decade where the manufacturer gives bounds (op-amp
  Avol from 50k to 1M, BJT β from 100 to 400).
- ``Constant(value)`` — fixed value, no perturbation. Useful for
  locking one parameter while sweeping others.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np


class Sampler(ABC):
    """Generate Monte-Carlo samples and report a nominal value.

    The ``nominal()`` method returns the "centre" of the distribution
    — used by ``analyze`` to compute reference metric values for
    ``"within"`` / ``"within_db"`` specs and to populate
    ``YieldReport.nominal_metrics``. For symmetric samplers it's the
    mean; for asymmetric samplers (LogUniform) it's the geometric
    mean, which is the natural centre on the log axis the sampler
    operates on."""

    @abstractmethod
    def sample(self, rng: np.random.Generator, n: int) -> np.ndarray:
        ...

    @abstractmethod
    def nominal(self) -> float:
        ...


@dataclass
class RelativeGaussian(Sampler):
    """``Normal(nominal, nominal·tol/sigmas)``. Default for passives.
    ``sigmas=3`` means the manufacturer's ±tol limit sits at the 3σ
    point — ~99.7% of samples land within ±tol, the rest spill into
    the realistic-but-out-of-spec tail."""
    nominal_value: float
    tol: float
    sigmas: float = 3.0

    def sample(self, rng, n):
        sigma = self.nominal_value * self.tol / self.sigmas
        return rng.normal(self.nominal_value, sigma, n)

    def nominal(self):
        return self.nominal_value


@dataclass
class RelativeUniform(Sampler):
    """``Uniform(nominal·(1-tol), nominal·(1+tol))``. Hard cutoff;
    flat density. More pessimistic than the default Gaussian at the
    99% interval, less so at the 99.99% tail."""
    nominal_value: float
    tol: float

    def sample(self, rng, n):
        lo = self.nominal_value * (1.0 - self.tol)
        hi = self.nominal_value * (1.0 + self.tol)
        return rng.uniform(lo, hi, n)

    def nominal(self):
        return self.nominal_value


@dataclass
class AbsoluteGaussian(Sampler):
    """``Normal(mean, sigma)`` in absolute units. For op-amp Vos
    (mean=0, σ in volts), Ib (mean=typ_Ib, σ in amps), and any other
    param whose nominal is zero or whose spread isn't specified as
    a relative tolerance.

    Convention for op-amp parameters: σ is chosen so that ±3σ matches
    the datasheet's worst-case max — ignoring "typical" datasheet
    values, which have no industry-standard meaning. See
    ``utils/tolerance/devices.py`` for the curated examples."""
    mean: float
    sigma: float

    def sample(self, rng, n):
        return rng.normal(self.mean, self.sigma, n)

    def nominal(self):
        return self.mean


@dataclass
class Uniform(Sampler):
    """``Uniform(lo, hi)`` with no nominal reference. For datasheet-
    bounded params with no shape claim — JFET Vto, BJT VBE_sat, etc.
    Nominal is the arithmetic midpoint, useful as a reference point
    but not implied to be more likely than the bounds."""
    lo: float
    hi: float

    def sample(self, rng, n):
        return rng.uniform(self.lo, self.hi, n)

    def nominal(self):
        return 0.5 * (self.lo + self.hi)


@dataclass
class LogUniform(Sampler):
    """Uniform in log space on ``[lo, hi]``. Natural for parameters
    that span a decade or more and whose datasheet quotes only bounds
    (Avol 50k–1M, β 100–400). Nominal is the geometric mean —
    equidistant from both ends on the log axis."""
    lo: float
    hi: float

    def __post_init__(self):
        if self.lo <= 0 or self.hi <= 0:
            raise ValueError(
                "LogUniform requires positive lo and hi "
                f"(got lo={self.lo}, hi={self.hi})"
            )
        if self.lo >= self.hi:
            raise ValueError(
                f"LogUniform requires lo < hi (got lo={self.lo}, "
                f"hi={self.hi})"
            )

    def sample(self, rng, n):
        return np.exp(rng.uniform(np.log(self.lo), np.log(self.hi), n))

    def nominal(self):
        return float(np.sqrt(self.lo * self.hi))


@dataclass
class Constant(Sampler):
    """Fixed value, no perturbation. Use to pin a single parameter
    while sweeping the rest, or to disable an active-device spread
    you want to study in isolation."""
    value: float

    def sample(self, rng, n):
        return np.full(n, self.value)

    def nominal(self):
        return self.value
