import math

import numpy as np

from .report import YieldReport, MetricStats


_VALID_OPS = {"<", "<=", ">", ">=", "within", "within_db"}
_VALID_DISTS = {"gaussian", "uniform"}


def _classify(name, tolerances):
    """Map a component name to its tolerance-dict key by first character
    (SPICE convention: R/C/L/...). Unknown prefixes raise — silently
    treating an unrecognised component as zero-tolerance would mask a
    real misconfiguration."""
    prefix = name[0]
    if prefix not in tolerances:
        known = sorted(tolerances)
        raise ValueError(
            f"Component {name!r} (prefix {prefix!r}) has no entry in "
            f"passive_tolerances; known prefixes: {known}"
        )
    return prefix


def _resolve_distribution(name, prefix, distribution):
    """Look up which distribution applies to a single component:
    per-component-name first (most specific), then per-prefix, then the
    string default. ``distribution`` may be a string (applies to all)
    or a dict keyed by component name and/or prefix."""
    if isinstance(distribution, str):
        return distribution
    if isinstance(distribution, dict):
        if name in distribution:
            return distribution[name]
        if prefix in distribution:
            return distribution[prefix]
        return "gaussian"
    raise TypeError(
        f"distribution must be a str or dict, got {type(distribution).__name__}"
    )


def _sample_one(rng, nominal, tol, dist, tolerance_sigma, n_mc):
    """Sample n_mc perturbed values for a single component.

    For ``"gaussian"``: ``Normal(nominal, nominal · tol/tolerance_sigma)``
    so the manufacturer's ±tol limit corresponds to ±``tolerance_sigma``
    standard deviations. Default ``tolerance_sigma=3`` means 99.7% of
    samples land within ±tol; lower values widen the distribution
    (more pessimistic), higher values tighten it.

    For ``"uniform"``: ``Uniform(nominal·(1-tol), nominal·(1+tol))``.
    No samples fall outside ±tol — a hard-cutoff worst-case model. The
    ``tolerance_sigma`` argument has no effect on uniform sampling.
    """
    if dist == "gaussian":
        sigma = tol / tolerance_sigma
        return nominal * (1.0 + rng.normal(0.0, sigma, n_mc))
    if dist == "uniform":
        return nominal * (1.0 + rng.uniform(-tol, tol, n_mc))
    raise ValueError(
        f"Unknown distribution: {dist!r}. Valid: {sorted(_VALID_DISTS)}"
    )


def _validate_distribution(distribution, nominal_values, passive_tolerances):
    """Per-component / per-prefix dict overrides are easy to mistype —
    a typo silently falls back to gaussian under a permissive lookup,
    masking the misconfiguration. Validate up-front: every key must be
    a known component name OR a known prefix, and every value must be
    a valid distribution name."""
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
    known_names = set(nominal_values)
    known_prefixes = set(passive_tolerances)
    for key, val in distribution.items():
        if key not in known_names and key not in known_prefixes:
            raise ValueError(
                f"distribution key {key!r} matches no component name "
                f"in nominal_values nor prefix in passive_tolerances"
            )
        if val not in _VALID_DISTS:
            raise ValueError(
                f"distribution[{key!r}] = {val!r} is not a valid "
                f"distribution; valid: {sorted(_VALID_DISTS)}"
            )


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
            workers=1):
    """Monte-Carlo yield analysis on a circuit candidate.

    Args:
        nominal_values: ``{name: value}`` for every component in the
            circuit (typically a ``Result.values`` from ``eseries_opt``).
        passive_tolerances: ``{prefix: rel_tol}`` keyed by component-name
            first character. ``{"R": 0.01, "C": 0.05}`` means 1% on every
            R and 5% on every C. Components are classified by first
            letter (SPICE convention); unknown prefixes raise.
        metrics: ``(**values) -> {name: value}``. Computes the metrics
            of interest (fc, Q, gain, phase margin, ...) from one
            perturbed sample.
        spec: ``{metric_name: (op, threshold)}``. Operators:

            - ``"<"``, ``"<="``, ``">"``, ``">="`` — absolute thresholds
            - ``"within"`` — ``|m - nominal| / |nominal| <= threshold``
            - ``"within_db"`` — ``|20·log10(m/nominal)| <= threshold``

        n_mc: Number of Monte-Carlo samples.
        seed: RNG seed for reproducibility.
        tolerance_sigma: For Gaussian distributions, how many σ the
            stated tolerance corresponds to. Default 3.0 (~99.7% within
            ±tol) matches the standard yield-engineering convention.
            Set to 1.0 for the pessimistic "tol = ±1σ" reading; raise
            above 3.0 for tighter-than-spec parts. No effect on uniform
            distributions.
        distribution: ``"gaussian"`` (default) or ``"uniform"`` applied
            to every component, OR a dict to override by component name
            or by prefix. Lookup order: component-name → prefix →
            ``"gaussian"``. Examples:

            - ``"uniform"`` — every component sampled uniformly
            - ``{"C": "uniform"}`` — uniform Cs, gaussian everything else
            - ``{"C1": "uniform"}`` — uniform on just one capacitor

        workers: Number of concurrent metric evaluations via
            ``ThreadPoolExecutor``. Default 1 (serial). Threads (not
            processes) so the metrics callable doesn't have to be
            picklable; ngspice's ``subprocess.run`` releases the GIL
            during the simulator wait, so N threads → N concurrent
            ngspice processes with near-linear speedup. For pure-Python
            closed-form metrics ``workers > 1`` has no effect (GIL).
            Sample order is preserved so results are deterministic for
            a given seed regardless of ``workers``.

    Returns:
        YieldReport with overall pass count, per-spec pass count, and
        the nominal metric values.

    Distribution notes:

    - **Gaussian** (default): ``Normal(nominal, nominal · tol/tolerance_sigma)``,
      not truncated. Rare samples beyond ±tol do occur, matching reality
      (a 1% resistor has a ~0.3% chance of sitting outside the ±1% band
      under the default ``tolerance_sigma=3``).
    - **Uniform**: ``Uniform(nominal·(1-tol), nominal·(1+tol))``. Hard
      cutoff at ±tol; flat density inside. More pessimistic than the
      default Gaussian at the 99% interval (uniform's 99% is at ±0.99·tol
      vs Gaussian-3σ's ±0.86·tol), less pessimistic at the 99.99% tail.
    - Components are sampled **independently** — no part-to-part
      correlation modelling. Single-reel correlation can be a meaningful
      effect when many copies of one part appear on a board; not handled
      here yet.
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

    component_types = {n: _classify(n, passive_tolerances)
                       for n in nominal_values}
    _validate_distribution(distribution, nominal_values, passive_tolerances)

    # Validate spec operators up-front so a bad op fails before we
    # spend N samples computing metrics.
    for spec_name, (op, _thr) in spec.items():
        if op not in _VALID_OPS:
            raise ValueError(
                f"Unknown spec operator: {op!r} for {spec_name!r}. "
                f"Valid: {sorted(_VALID_OPS)}"
            )

    nominal_metrics = metrics(**nominal_values)

    rng = np.random.default_rng(seed)
    names = list(nominal_values)
    samples = np.empty((n_mc, len(names)))
    for j, name in enumerate(names):
        prefix = component_types[name]
        tol = passive_tolerances[prefix]
        dist = _resolve_distribution(name, prefix, distribution)
        samples[:, j] = _sample_one(
            rng, nominal_values[name], tol, dist, tolerance_sigma, n_mc
        )

    metric_keys = list(nominal_metrics)
    metric_arrays = {k: np.empty(n_mc) for k in metric_keys}

    sample_dicts = [
        {names[j]: samples[i, j] for j in range(len(names))}
        for i in range(n_mc)
    ]

    if workers == 1:
        sample_results = (metrics(**s) for s in sample_dicts)
    else:
        # ThreadPoolExecutor.map preserves submission order, so the
        # accumulation loop sees samples in the same order as workers=1
        # — yields are bit-identical for a given seed regardless of
        # parallelism.
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
        pcts = np.percentile(arr, [1, 5, 50, 95, 99])
        mean = float(arr.mean())
        std  = float(arr.std())
        if std > 0:
            # Standardised central moments — Fisher-Pearson skew, and
            # excess kurtosis (kurtosis - 3, so a Gaussian → 0).
            z = (arr - mean) / std
            skew = float(np.mean(z ** 3))
            excess_kurt = float(np.mean(z ** 4) - 3.0)
        else:
            skew = 0.0
            excess_kurt = 0.0
        metric_stats[k] = MetricStats(
            min=float(arr.min()),  max=float(arr.max()),
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
