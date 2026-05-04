import math

import numpy as np

from .report import YieldReport, MetricStats
from .samplers import (Sampler, RelativeGaussian, RelativeUniform,
                       AbsoluteGaussian)
from .devices import expand_active_devices


_VALID_OPS = {"<", "<=", ">", ">=", "within", "within_db"}
_VALID_DISTS = {"gaussian", "uniform"}


def _classify(name, tolerances):
    """Map a passive-component name to its tolerance-dict key. Lookup
    order: full name (per-component override), then first character
    (SPICE prefix convention: R/C/L/...). Unknown raises — silently
    treating an unrecognised component as zero-tolerance would mask a
    real misconfiguration.

    Per-name overrides let you give different tolerances to instances
    of the same component class — e.g., a 1% precision divider where
    one resistor is binned tighter than the other:
    ``passive_tolerances={"R": 0.01, "Rsense": 0.001}``."""
    if name in tolerances:
        return name
    prefix = name[0]
    if prefix not in tolerances:
        known = sorted(tolerances)
        raise ValueError(
            f"Component {name!r} (prefix {prefix!r}) has no entry in "
            f"passive_tolerances; known names/prefixes: {known}"
        )
    return prefix


def _resolve_distribution_name(name, prefix, distribution):
    """Look up which string-named distribution applies to a single
    passive component: per-component-name first (most specific), then
    per-prefix, then the global default."""
    if isinstance(distribution, str):
        return distribution
    if isinstance(distribution, dict):
        if name in distribution:
            entry = distribution[name]
            return entry if isinstance(entry, str) else None
        if prefix in distribution:
            entry = distribution[prefix]
            return entry if isinstance(entry, str) else None
        return "gaussian"
    raise TypeError(
        f"distribution must be a str or dict, got {type(distribution).__name__}"
    )


def _build_sampler(nominal, tol, dist_name, sigmas):
    """Construct a passive Sampler from the string-based API knobs."""
    if dist_name == "gaussian":
        return RelativeGaussian(nominal_value=nominal, tol=tol, sigmas=sigmas)
    if dist_name == "uniform":
        return RelativeUniform(nominal_value=nominal, tol=tol)
    raise ValueError(
        f"Unknown distribution: {dist_name!r}. Valid: {sorted(_VALID_DISTS)}"
    )


def _validate_distribution(distribution, nominal_values, passive_tolerances,
                            active_sampler_keys):
    """Per-component / per-prefix dict overrides are easy to mistype —
    a typo silently falls back to gaussian under a permissive lookup,
    masking the misconfiguration. Validate up-front: every key must be
    a known component name, a known active-device-derived sampler key,
    or a known prefix; every value must be a valid distribution name
    string OR a Sampler instance."""
    if isinstance(distribution, str):
        if distribution not in _VALID_DISTS:
            raise ValueError(
                f"Unknown distribution: {distribution!r}. "
                f"Valid: {sorted(_VALID_DISTS)}"
            )
        return
    if not isinstance(distribution, dict):
        raise TypeError(
            f"distribution must be a str or dict, "
            f"got {type(distribution).__name__}"
        )
    known_names = set(nominal_values) | set(active_sampler_keys)
    known_prefixes = set(passive_tolerances)
    for key, val in distribution.items():
        if key not in known_names and key not in known_prefixes:
            raise ValueError(
                f"distribution key {key!r} matches no component name "
                f"in nominal_values, no active-device parameter, and "
                f"no prefix in passive_tolerances"
            )
        if isinstance(val, Sampler):
            continue
        if val not in _VALID_DISTS:
            raise ValueError(
                f"distribution[{key!r}] = {val!r} is not a valid "
                f"distribution; valid string values: "
                f"{sorted(_VALID_DISTS)}, or pass a Sampler instance"
            )


def _gaussian_sigma(sampler):
    """Extract (mean, σ) from a Gaussian-family Sampler — used by the
    correlated-group machinery to build a covariance matrix that has
    the same marginals as the per-component sampler would have
    produced independently. Returns None for non-Gaussian samplers."""
    if isinstance(sampler, RelativeGaussian):
        return (sampler.nominal_value,
                sampler.nominal_value * sampler.tol / sampler.sigmas)
    if isinstance(sampler, AbsoluteGaussian):
        return (sampler.mean, sampler.sigma)
    return None


def _validate_correlations(correlations, samplers):
    """Each correlation entry: (list of names, ρ in [-1, 1]). Every
    name must have a Gaussian-family sampler — non-Gaussian shapes
    don't have a clean joint distribution under simple correlation."""
    seen = set()
    for entry in correlations:
        if (not isinstance(entry, (list, tuple))) or len(entry) != 2:
            raise TypeError(
                f"correlation entry must be (names_list, rho), got {entry!r}"
            )
        names, rho = entry
        if not isinstance(names, (list, tuple)) or len(names) < 2:
            raise ValueError(
                f"correlation group must have ≥2 names, got {names!r}"
            )
        if not (-1 <= rho <= 1):
            raise ValueError(
                f"correlation ρ must be in [-1, 1], got {rho}"
            )
        if rho < 0 and len(names) > 2:
            # ρ<0 with >2 components doesn't yield a valid PSD
            # covariance matrix (off-diagonals can't all be negative
            # of the same magnitude). Refuse rather than emit garbage.
            raise ValueError(
                f"negative ρ only supported for 2-component groups; "
                f"got {len(names)} components with ρ={rho}"
            )
        for nm in names:
            if nm not in samplers:
                raise ValueError(
                    f"correlation references unknown component {nm!r}"
                )
            if _gaussian_sigma(samplers[nm]) is None:
                raise ValueError(
                    f"correlation requires Gaussian-family sampler "
                    f"for {nm!r}; got {type(samplers[nm]).__name__}"
                )
            if nm in seen:
                raise ValueError(
                    f"component {nm!r} appears in multiple correlation "
                    f"groups — overlapping groups aren't supported"
                )
            seen.add(nm)


def _evaluate(value, op, threshold, nominal_value):
    if op == "<":  return value <  threshold
    if op == "<=": return value <= threshold
    if op == ">":  return value >  threshold
    if op == ">=": return value >= threshold
    if op == "within":
        if nominal_value == 0:
            raise ValueError(
                "spec ('within', ...) requires non-zero nominal metric"
            )
        return abs(value - nominal_value) / abs(nominal_value) <= threshold
    if op == "within_db":
        if nominal_value <= 0 or value <= 0:
            return False
        return abs(20.0 * math.log10(value / nominal_value)) <= threshold
    raise ValueError(
        f"Unknown spec operator: {op!r}. Valid: {sorted(_VALID_OPS)}"
    )


def analyze(*, nominal_values, passive_tolerances, metrics, spec,
            n_mc=1000, seed=None,
            tolerance_sigma=3.0, distribution="gaussian",
            active_devices=None,
            correlations=None,
            temperature=None,
            temperature_coefficients=None,
            temperature_nominal=25.0,
            workers=1):
    """Monte-Carlo yield analysis on a circuit candidate.

    Args:
        nominal_values: ``{name: value}`` for every passive in the
            circuit (typically a ``Result.values`` from ``eseries_opt``).
            Active-device parameters are added automatically when
            ``active_devices=`` is supplied; their nominal values come
            from each Sampler's ``nominal()``.
        passive_tolerances: ``{prefix: rel_tol}`` keyed by component-
            name first character. ``{"R": 0.01, "C": 0.05}`` means 1%
            on every R and 5% on every C. Components in
            ``nominal_values`` are classified by first letter (SPICE
            convention); unknown prefixes raise.
        metrics: ``(**values) -> {name: value}``. Receives the union
            of passive samples and active-device parameter samples.
        spec: ``{metric_name: (op, threshold)}``. Operators:

            - ``"<"``, ``"<="``, ``">"``, ``">="`` — absolute thresholds
            - ``"within"`` — ``|m - nominal| / |nominal| <= threshold``
            - ``"within_db"`` — ``|20·log10(m/nominal)| <= threshold``

        n_mc: Number of Monte-Carlo samples.
        seed: RNG seed for reproducibility.
        tolerance_sigma: For Gaussian distributions, how many σ the
            stated tolerance corresponds to. Default 3.0 (~99.7%
            within ±tol) matches the standard yield-engineering
            convention. Set lower to widen, higher to tighten.
        distribution: ``"gaussian"`` (default) or ``"uniform"``
            applied to every passive, OR a dict to override by
            component name or by prefix. Dict values may also be
            ``Sampler`` instances (from ``utils.tolerance.samplers``)
            for shapes the string API can't express. Examples:

            - ``"uniform"`` — every passive sampled uniformly
            - ``{"C": "uniform"}`` — uniform Cs, gaussian everything else
            - ``{"R1": LogUniform(lo=900, hi=1100)}`` — explicit
              sampler for one component
            - ``{"U1_Vos": AbsoluteGaussian(0, 1e-3)}`` — override an
              active-device parameter that ``active_devices`` would
              otherwise resolve via the device library

        active_devices: ``{instance: part_number}`` — looks up each
            ``part_number`` in ``utils.tolerance.devices.DEVICES`` and
            adds per-parameter samplers keyed as ``{instance}_{param}``.
            ``"NE5532"`` adds ``Vos``, ``Ib``, ``Avol``, ``GBW`` etc.
            The metrics callable receives these as named arguments.
        correlations: List of ``(names, rho)`` tuples declaring that
            the named components are jointly Gaussian with pairwise
            correlation ``rho``. Per-component variances are taken
            from each component's existing Sampler (the marginals are
            preserved). Headline use cases:

            - **Reel-mate passives**: ``([R1, R2, R3], 0.95)``
              means the three resistors come off the same reel and
              their tolerances move together at ρ = 0.95. Differential
              metrics (R1+R2, R1/R2) become much tighter than they'd
              be under independent sampling.
            - **Op-amp Avol/GBW anti-correlation**:
              ``([U1_Avol, U1_GBW], -0.7)`` reflects the typical
              anti-correlation of those parameters across a process
              run.

            Constraints: components in a correlation group must have
            Gaussian-family samplers (RelativeGaussian or
            AbsoluteGaussian); ρ in [-1, 1]; negative ρ only allowed
            for 2-component groups (PSD requirement); a component can
            appear in at most one correlation group.
        temperature: Optional ``Sampler`` for ambient °C. Sampled
            once per MC iteration and applied to all components via
            ``temperature_coefficients``. Also passed to ``metrics``
            as the kwarg ``T`` so the user can inject it into
            ngspice ``.temp`` for active-device temperature
            dependence. When ``None`` (default), tempcos have no
            effect and ``metrics`` doesn't receive ``T``.

            **Coverage caveat**: random-T sampling smears n_mc
            samples across the temperature range, so per-T-band
            confidence intervals are loose unless ``n_mc`` is large.
            For "does it work at every corner?" use
            ``analyze_corners(temperature_corners=[...])`` instead;
            for "yield-vs-T curve" use ``temperature_sweep``. The
            random-T mode is only the right tool when temperature
            during operation really is a random variable to be
            integrated over (e.g. unconditioned ambient with a wide
            distribution).
        temperature_coefficients: ``{name_or_prefix: tempco}`` in
            fractional change per °C (e.g. ``50e-6`` for 50 ppm/°C
            metal-film R, ``1500e-6`` for X7R ceramic C). Lookup
            order: full name (per-component override), then SPICE
            prefix. After standard tolerance perturbation, each
            component's value is multiplied by
            ``1 + tempco · (T - temperature_nominal)``.
        temperature_nominal: Reference °C where tempco = 0 (default
            25). Only meaningful when ``temperature`` is set.
        workers: Concurrent metric evaluations via
            ``ThreadPoolExecutor``. Default 1 (serial). For ngspice
            backends N threads → N concurrent processes, near-linear
            speedup. For pure-Python metrics ``workers > 1`` has no
            effect (GIL).

    Returns:
        YieldReport with overall pass count, per-spec pass count, and
        the nominal metric values.

    Distribution notes:

    - **RelativeGaussian** (default for passives): not truncated.
      Rare samples beyond ±tol do occur, matching reality (a 1%
      resistor has a ~0.3% chance of sitting outside the ±1% band
      under ``tolerance_sigma=3``).
    - **Active-device** parameters use the curated sampler shapes from
      ``utils/tolerance/devices.py`` — see that module's docstring
      for the conventions (max-as-3σ for AbsoluteGaussian, log-uniform
      on bounds for Avol/β).
    - Components are sampled **independently** — no part-to-part or
      param-to-param correlation modelling. Avol/GBW anti-correlation
      and reel-mate correlation are real effects not captured here.
    """
    if not nominal_values:
        raise ValueError("nominal_values is empty")
    if not spec:
        raise ValueError("spec is empty")
    if tolerance_sigma <= 0:
        raise ValueError(
            f"tolerance_sigma must be positive, got {tolerance_sigma}"
        )
    if workers < 1:
        raise ValueError(f"workers must be >= 1, got {workers}")

    # 1. Expand active_devices into per-parameter samplers, keyed by
    # f"{instance}_{param}".
    active_samplers = (expand_active_devices(active_devices)
                       if active_devices else {})

    # 2. Check no name collisions between passives and active params.
    overlap = set(nominal_values) & set(active_samplers)
    if overlap:
        raise ValueError(
            f"name collision between nominal_values and "
            f"active_devices-generated parameters: {sorted(overlap)}"
        )

    # 3. Validate the distribution dict against the union of names.
    _validate_distribution(distribution, nominal_values,
                           passive_tolerances, active_samplers)

    # 4. Spec operators: validate up-front so a bad op fails before
    # we spend N samples computing metrics.
    for spec_name, (op, _thr) in spec.items():
        if op not in _VALID_OPS:
            raise ValueError(
                f"Unknown spec operator: {op!r} for {spec_name!r}. "
                f"Valid: {sorted(_VALID_OPS)}"
            )

    # 5. Build the per-component sampler map. Order matters for
    # determinism: passives in their declared order, then active
    # params in declared order. A given (seed, sampler-set) → same
    # samples, regardless of insertion order in the underlying dict.
    samplers = {}
    component_types = {}
    for name in nominal_values:
        # Per-component override in distribution dict can be a Sampler
        # instance (full custom shape) or a string ("gaussian"/"uniform").
        # When the user provides an explicit Sampler, the name doesn't
        # need to match a passive prefix — it can be anything (e.g., a
        # one-off active-device param like "Vos_U1" outside the curated
        # device library, or a derived parameter like "ESR" for a cap's
        # series resistance). Skip the prefix classifier in that case.
        explicit = (isinstance(distribution, dict) and name in distribution
                    and isinstance(distribution[name], Sampler))
        if explicit:
            samplers[name] = distribution[name]
            component_types[name] = None
        else:
            prefix = _classify(name, passive_tolerances)
            component_types[name] = prefix
            dist_name = _resolve_distribution_name(name, prefix,
                                                    distribution)
            tol = passive_tolerances[prefix]
            samplers[name] = _build_sampler(
                nominal_values[name], tol, dist_name, tolerance_sigma
            )
    for name, sampler in active_samplers.items():
        # Per-component override beats device-library default
        if isinstance(distribution, dict) and name in distribution \
                and isinstance(distribution[name], Sampler):
            samplers[name] = distribution[name]
        else:
            samplers[name] = sampler

    # 6. Build the enriched nominal-values dict for the metrics()
    # reference call. Active params use Sampler.nominal().
    enriched_nominal = dict(nominal_values)
    for name, sampler in active_samplers.items():
        if name not in enriched_nominal:
            enriched_nominal[name] = sampler.nominal()

    # Validate temperature inputs early
    if temperature is not None and not isinstance(temperature, Sampler):
        raise TypeError(
            f"temperature must be a Sampler instance or None, "
            f"got {type(temperature).__name__}"
        )

    # Nominal call: at temperature_nominal (where tempco contribution
    # is zero by definition). If temperature is enabled, pass T as a
    # kwarg so the metrics signature is consistent across nominal and
    # MC calls.
    if temperature is not None:
        nominal_metrics = metrics(**enriched_nominal,
                                  T=temperature_nominal)
    else:
        nominal_metrics = metrics(**enriched_nominal)

    # 7. Generate the n_mc × n_components sample matrix. Independent
    # samples per component first; then for each correlation group,
    # OVERWRITE the columns with jointly-Gaussian samples that have
    # the same marginals.
    rng = np.random.default_rng(seed)
    names = list(samplers)
    samples = np.empty((n_mc, len(names)))
    for j, name in enumerate(names):
        samples[:, j] = samplers[name].sample(rng, n_mc)

    if correlations:
        _validate_correlations(correlations, samplers)
        for group_names, rho in correlations:
            # Build covariance matrix with diagonal σ_i² and off-diagonal
            # ρ·σ_i·σ_j. Marginals (means, variances) match what the
            # independent sampler would have produced.
            n_g = len(group_names)
            means = np.empty(n_g)
            sigmas = np.empty(n_g)
            for k, nm in enumerate(group_names):
                means[k], sigmas[k] = _gaussian_sigma(samplers[nm])
            cov = np.outer(sigmas, sigmas) * rho
            np.fill_diagonal(cov, sigmas ** 2)
            joint = rng.multivariate_normal(means, cov, size=n_mc)
            for k, nm in enumerate(group_names):
                samples[:, names.index(nm)] = joint[:, k]

    # Apply temperature scaling: sample T per MC, multiply each
    # component's already-perturbed value by (1 + tempco·(T - T_ref)).
    # Tempcos are looked up by full name first, then by SPICE prefix.
    if temperature is not None:
        T_samples = temperature.sample(rng, n_mc)
        tcs = temperature_coefficients or {}
        for j, name in enumerate(names):
            tc = tcs.get(name)
            if tc is None:
                tc = tcs.get(name[0])
            if tc:
                samples[:, j] *= 1.0 + tc * (T_samples - temperature_nominal)
    else:
        T_samples = None

    metric_keys = list(nominal_metrics)
    metric_arrays = {k: np.empty(n_mc) for k in metric_keys}

    if temperature is not None:
        sample_dicts = [
            {**{names[j]: samples[i, j] for j in range(len(names))},
             "T": float(T_samples[i])}
            for i in range(n_mc)
        ]
    else:
        sample_dicts = [
            {names[j]: samples[i, j] for j in range(len(names))}
            for i in range(n_mc)
        ]

    if workers == 1:
        sample_results = (metrics(**s) for s in sample_dicts)
    else:
        # ThreadPoolExecutor.map preserves submission order, so the
        # accumulation loop sees samples in the same order as
        # workers=1 — yields are bit-identical for a given seed
        # regardless of parallelism.
        from concurrent.futures import ThreadPoolExecutor
        ex = ThreadPoolExecutor(max_workers=workers)
        try:
            sample_results = list(ex.map(lambda s: metrics(**s),
                                         sample_dicts))
        finally:
            ex.shutdown(wait=True)

    per_spec_pass = {k: 0 for k in spec}
    failure_modes = {}
    samples_pass = 0
    for i, m in enumerate(sample_results):
        for k in metric_keys:
            metric_arrays[k][i] = m[k]
        failing = []
        for spec_name, (op, thr) in spec.items():
            if _evaluate(m[spec_name], op, thr,
                         nominal_metrics.get(spec_name)):
                per_spec_pass[spec_name] += 1
            else:
                failing.append(spec_name)
        if failing:
            key = frozenset(failing)
            failure_modes[key] = failure_modes.get(key, 0) + 1
        else:
            samples_pass += 1

    metric_stats = {}
    for k, arr in metric_arrays.items():
        # NaN samples are real (failed simulator extractions, undefined
        # metrics) but they shouldn't poison every aggregate. Use
        # NaN-aware aggregations; if every sample is NaN, fall back to
        # NaN stats with a clear "no finite samples" signal.
        finite = arr[np.isfinite(arr)]
        if finite.size == 0:
            metric_stats[k] = MetricStats(
                min=float("nan"), max=float("nan"),
                mean=float("nan"), std=float("nan"),
                p1=float("nan"), p5=float("nan"), p50=float("nan"),
                p95=float("nan"), p99=float("nan"),
                skew=float("nan"), excess_kurtosis=float("nan"),
            )
            continue
        pcts = np.percentile(finite, [1, 5, 50, 95, 99])
        mean = float(finite.mean())
        std  = float(finite.std())
        if std > 0:
            # Standardised central moments — Fisher-Pearson skew, and
            # excess kurtosis (kurtosis - 3, so a Gaussian → 0).
            z = (finite - mean) / std
            skew = float(np.mean(z ** 3))
            excess_kurt = float(np.mean(z ** 4) - 3.0)
        else:
            skew = 0.0
            excess_kurt = 0.0
        metric_stats[k] = MetricStats(
            min=float(finite.min()), max=float(finite.max()),
            mean=mean, std=std,
            p1=float(pcts[0]),  p5=float(pcts[1]),  p50=float(pcts[2]),
            p95=float(pcts[3]), p99=float(pcts[4]),
            skew=skew, excess_kurtosis=excess_kurt,
        )

    return YieldReport(
        samples_total=n_mc,
        samples_pass=samples_pass,
        per_spec_pass=per_spec_pass,
        nominal_metrics=nominal_metrics,
        metric_stats=metric_stats,
        failure_modes=failure_modes,
        metric_samples=metric_arrays,
        spec=dict(spec),
    )
