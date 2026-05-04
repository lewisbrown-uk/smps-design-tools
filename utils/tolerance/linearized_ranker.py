"""Sensitivity-based yield estimation for ``eseries_opt`` candidates.

Companion to ``Robust``. Where ``Robust`` runs a full Monte-Carlo
sweep per candidate, ``Linearized`` does a closed-form propagation:

1. Evaluate the metrics at the nominal point  →  1 call
2. Evaluate at ±ε perturbation per component  →  2·N calls
3. Build the joint covariance Σ of the inputs from samplers +
   correlations
4. Compute ∇g and Var[g] = ∇gᵀ Σ ∇g per metric
5. Per-spec yield drops out of the normal CDF analytically

Cost per candidate: ``1 + 2·N`` metric calls vs ``n_mc`` for Robust.
For a 4-component circuit this is 9 calls vs 500 — ~50× speedup.
For the same circuit with 4 active-device params expanded the gap
widens because the call count scales linearly while MC scales with
n_mc regardless.

Trade-offs to be honest about:

- The linearisation is exact only for metrics that are smooth in
  the inputs near the nominal. Clipping, oscillator capture,
  instability boundaries, log-domain transitions: these break it.
  Detect by re-running with a different ``eps_frac`` — if the yield
  estimate moves significantly, the metric isn't locally linear and
  Linearized's ranking can't be trusted.
- Multi-spec yields are combined assuming independence across
  metrics. Real metrics are correlated through the shared input
  components, so independence overestimates yield when metrics drift
  in the same direction. The relative ranking across candidates
  usually survives this.
- Non-Gaussian inputs (Uniform, LogUniform) propagate as Gaussian
  via empirical-σ extraction. The variance is preserved; the tail
  shape isn't. For 1-σ-band yield questions this matters little; for
  6-σ rare-failure questions FORM/SORM is the right tool, not this.

Use Linearized for first-pass ranking on the full grid, then verify
the top-K with Robust at higher fidelity. The two-phase pattern
gives both speed and rigour.
"""
import math

import numpy as np
from scipy.stats import norm

from .analyze import _build_samplers
from .devices import expand_active_devices
from .samplers import Constant, Sampler


_VALID_OPS = {"<", "<=", ">", ">=", "within", "within_db"}


def _empirical_mu_sigma(sampler, rng, n=2000):
    """Draw n samples and return (mean, std). Works for any Sampler
    type without needing a closed-form variance — costs <1 ms per
    sampler, tiny next to the metrics call cost."""
    samples = sampler.sample(rng, n)
    return float(samples.mean()), float(samples.std(ddof=1))


def _build_covariance(names, mus, sigmas, samplers, correlations):
    """Σ_ij = ρ_ij · σ_i · σ_j. Diagonal = σ_i². Off-diagonals from
    the correlations spec; the rest are zero (independent)."""
    n = len(names)
    cov = np.zeros((n, n))
    np.fill_diagonal(cov, np.array(sigmas) ** 2)
    if not correlations:
        return cov
    name_to_idx = {nm: i for i, nm in enumerate(names)}
    for entry in correlations:
        group_names, rho = entry
        for a in group_names:
            for b in group_names:
                if a == b:
                    continue
                i, j = name_to_idx[a], name_to_idx[b]
                cov[i, j] = rho * sigmas[i] * sigmas[j]
    return cov


def _spec_yield(op, threshold, g_nominal, g_sigma):
    """Analytic per-spec yield for a Gaussian metric ~ N(g_nominal,
    g_sigma²). Returns probability of pass."""
    if g_sigma == 0:
        # Zero variance — pass iff nominal already passes
        return 1.0 if _spec_pass_at(op, threshold, g_nominal, g_nominal) else 0.0
    if op in ("<", "<="):
        return float(norm.cdf((threshold - g_nominal) / g_sigma))
    if op in (">", ">="):
        return float(1.0 - norm.cdf((threshold - g_nominal) / g_sigma))
    if op == "within":
        if g_nominal == 0:
            raise ValueError(
                "spec ('within', ...) requires non-zero nominal metric"
            )
        lo = abs(g_nominal) * (1.0 - threshold)
        hi = abs(g_nominal) * (1.0 + threshold)
        # Account for sign: spec is |g - g_nominal|/|g_nominal| <= tol
        # so g must lie in [g_nominal - tol·|g_nominal|, g_nominal + tol·|g_nominal|]
        lo, hi = (g_nominal - threshold * abs(g_nominal),
                   g_nominal + threshold * abs(g_nominal))
        return float(norm.cdf((hi - g_nominal) / g_sigma)
                     - norm.cdf((lo - g_nominal) / g_sigma))
    if op == "within_db":
        if g_nominal <= 0:
            return 0.0
        # 20·log10(g/g_nominal) ≈ (20/ln10) · (g - g_nominal)/g_nominal
        # for small relative deviations. Spec |20log10(g/g_nominal)| <= thr
        # → |g - g_nominal| <= g_nominal · thr · ln10/20.
        delta = g_nominal * threshold * math.log(10) / 20.0
        return float(norm.cdf(delta / g_sigma)
                     - norm.cdf(-delta / g_sigma))
    raise ValueError(f"Unknown spec operator: {op!r}. "
                      f"Valid: {sorted(_VALID_OPS)}")


def _spec_pass_at(op, threshold, value, nominal):
    """Discrete pass-check for the zero-variance edge case."""
    if op == "<":  return value < threshold
    if op == "<=": return value <= threshold
    if op == ">":  return value > threshold
    if op == ">=": return value >= threshold
    if op == "within":
        if nominal == 0:
            return False
        return abs(value - nominal) / abs(nominal) <= threshold
    if op == "within_db":
        if nominal <= 0 or value <= 0:
            return False
        return abs(20.0 * math.log10(value / nominal)) <= threshold
    raise ValueError(f"Unknown spec operator: {op!r}")


class Linearized:
    """Sensitivity-based yield ranker — companion to ``Robust``.

    Same plug-in shape as ``Robust`` for ``Problem.solve(rank=...)``.
    Per candidate, evaluates the user's metrics at the nominal point
    plus 2·N perturbed points (one per component, ±ε), builds the
    Jacobian ∇g, combines with the joint input covariance Σ to get
    analytic per-metric variances, and reports yield from the normal
    CDF.

    Args:
        passive_tolerances: ``{prefix: rel_tol}``, same as
            ``analyze(passive_tolerances=...)``.
        spec: ``{target_name: (op, threshold)}``, same as
            ``analyze(spec=...)``. Names must match Problem targets.
        active_devices: optional ``{instance: part}`` for active-device
            spreads — the curated DEVICES library is consulted for
            samplers, same as in ``analyze``.
        distribution: optional per-component distribution overrides,
            same shape as in ``analyze``.
        correlations: optional ``[(names_list, rho), ...]`` — joint
            Gaussian correlations contribute to the input Σ off-
            diagonals.
        tolerance_sigma: forwarded to the string-API sampler builder.
        eps_frac: perturbation fraction of each input's σ for the
            central-difference Jacobian. Default 0.1 — small enough
            that the metric is locally linear, large enough above
            numerical noise. Sanity check by re-running with 0.05
            and 0.2; consistent results mean the linearisation holds.
        n_sigma_samples: per-sampler sample count for empirical
            (mean, σ) extraction. Default 2000.
        seed: RNG seed for the σ extraction. The same seed across
            candidates means each candidate sees the same input
            statistics and the comparison is fair. Default 42.

    Per-candidate Result attributes set:

    - ``yield_pct``: estimated yield against the spec, in percent.
    - ``yield_estimate_method``: ``"linearized"`` for traceability.
    - ``yield_per_spec``: ``{spec_name: yield_fraction}`` — useful
      when a spec is dragging the joint yield down.
    - ``metric_sigma``: ``{metric_name: σ}`` — the linearised standard
      deviation of each metric, for sanity-checking against MC.
    """

    def __init__(self, *, passive_tolerances, spec,
                 active_devices=None, distribution="gaussian",
                 correlations=None, tolerance_sigma=3.0,
                 eps_frac=0.1, n_sigma_samples=2000, seed=42):
        for name, (op, _thr) in spec.items():
            if op not in _VALID_OPS:
                raise ValueError(
                    f"Unknown spec operator {op!r} for {name!r}. "
                    f"Valid: {sorted(_VALID_OPS)}"
                )
        if eps_frac <= 0:
            raise ValueError(f"eps_frac must be > 0, got {eps_frac}")
        self.passive_tolerances = passive_tolerances
        self.spec = spec
        self.active_devices = active_devices
        self.distribution = distribution
        self.correlations = correlations
        self.tolerance_sigma = tolerance_sigma
        self.eps_frac = eps_frac
        self.n_sigma_samples = n_sigma_samples
        self.seed = seed

    def rank(self, candidates, targets):
        if not candidates:
            return []

        target_names = {t.name for t in targets}
        bad = set(self.spec) - target_names
        if bad:
            raise ValueError(
                f"Linearized spec references unknown target(s): "
                f"{sorted(bad)}. Known: {sorted(target_names)}"
            )

        target_by_name = {t.name: t for t in targets}

        def metrics(**values):
            return {n: t.expr(**values) for n, t in target_by_name.items()}

        weights = {t.name: t.weight for t in targets}
        for c in candidates:
            c.error = sum(weights[k] * v for k, v in c.breakdown.items())
            (yp, yps, msigma) = self._estimate_yield(c, metrics)
            c.yield_pct = yp
            c.yield_per_spec = yps
            c.metric_sigma = msigma
            c.yield_estimate_method = "linearized"

        return sorted(candidates, key=lambda c: (-c.yield_pct, c.error))

    def _estimate_yield(self, candidate, metrics):
        active_samplers = (expand_active_devices(self.active_devices)
                           if self.active_devices else {})
        samplers = _build_samplers(
            candidate.values, self.passive_tolerances,
            self.distribution, self.tolerance_sigma, active_samplers,
        )
        # Add active-device nominal values to the candidate's value
        # dict so the metrics callable receives them.
        nominal_values = dict(candidate.values)
        for name, sampler in active_samplers.items():
            if name not in nominal_values:
                nominal_values[name] = sampler.nominal()

        rng = np.random.default_rng(self.seed)
        names = list(samplers)
        mus, sigmas = [], []
        for nm in names:
            mu, sigma = _empirical_mu_sigma(samplers[nm], rng,
                                             self.n_sigma_samples)
            mus.append(mu)
            sigmas.append(sigma)
        mus = np.array(mus); sigmas = np.array(sigmas)

        # Constants (Constant sampler) have σ=0 — these are pinned and
        # contribute nothing to metric variance. Skip the perturbation
        # loop for them to save calls and avoid divide-by-zero.
        # Use the candidate's nominal_values (or active sampler nominal)
        # for the centerpoint, not the empirical mean (which equals
        # nominal for symmetric distributions but might drift slightly
        # from finite-sample noise for asymmetric ones).
        center = {nm: nominal_values[nm] for nm in names}
        g_nominal = metrics(**center)
        metric_keys = list(g_nominal)

        # Build Jacobian J[k, i] = ∂g_k / ∂x_i via central differences.
        n_inputs = len(names)
        n_metrics = len(metric_keys)
        J = np.zeros((n_metrics, n_inputs))
        for i, nm in enumerate(names):
            sigma_i = sigmas[i]
            if sigma_i == 0:
                continue       # constant input → zero column
            eps = self.eps_frac * sigma_i
            plus = dict(center); plus[nm] = center[nm] + eps
            minus = dict(center); minus[nm] = center[nm] - eps
            g_plus = metrics(**plus)
            g_minus = metrics(**minus)
            for k, mk in enumerate(metric_keys):
                J[k, i] = (g_plus[mk] - g_minus[mk]) / (2.0 * eps)

        cov = _build_covariance(names, mus, sigmas, samplers,
                                 self.correlations)
        # Var[g_k] = J_k · Σ · J_kᵀ
        metric_var = np.einsum("ki,ij,kj->k", J, cov, J)
        metric_sigma = np.sqrt(np.maximum(metric_var, 0.0))

        msigma_dict = {mk: float(metric_sigma[k])
                        for k, mk in enumerate(metric_keys)}
        yield_per_spec = {}
        joint = 1.0
        for spec_name, (op, thr) in self.spec.items():
            k = metric_keys.index(spec_name)
            yp = _spec_yield(op, thr, g_nominal[spec_name],
                              float(metric_sigma[k]))
            yield_per_spec[spec_name] = yp
            joint *= yp
        return (100.0 * joint, yield_per_spec, msigma_dict)
