import os, sys, math
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import pytest

import matplotlib
matplotlib.use("Agg")  # headless; must come before any pyplot import

from utils.tolerance import analyze, YieldReport, MetricStats, CachedBackend


# ---------- Report shape ----------

def test_returns_yield_report_with_expected_fields():
    r = analyze(
        nominal_values={"R1": 1e3},
        passive_tolerances={"R": 0.01},
        metrics=lambda R1: {"v": R1},
        spec={"v": ("<", 1e6)},
        n_mc=100, seed=0,
    )
    assert isinstance(r, YieldReport)
    assert r.samples_total == 100
    assert 0 <= r.samples_pass <= 100
    assert "v" in r.per_spec_pass
    assert "v" in r.nominal_metrics
    assert r.nominal_metrics["v"] == pytest.approx(1e3)


def test_zero_tolerance_means_full_yield():
    r = analyze(
        nominal_values={"R1": 1e3, "C1": 1e-9},
        passive_tolerances={"R": 0.0, "C": 0.0},
        metrics=lambda R1, C1: {"fc": 1 / (2 * math.pi * R1 * C1)},
        spec={"fc": ("within", 0.01)},
        n_mc=200, seed=1,
    )
    assert r.samples_pass == 200
    assert r.per_spec_pass["fc"] == 200


# ---------- RC happy path ----------

def test_rc_lowpass_meets_loose_spec():
    """fc=1/(2πRC) with 1%R/5%C: σ_fc/fc ≈ √((1/3)²+(5/3)²)% ≈ 1.7%.
    'fc within 10%' is ≥ 5σ — should be essentially 100%."""
    r = analyze(
        nominal_values={"R": 1e3, "C": 1e-9},
        passive_tolerances={"R": 0.01, "C": 0.05},
        metrics=lambda R, C: {"fc": 1 / (2 * math.pi * R * C)},
        spec={"fc": ("within", 0.10)},
        n_mc=2000, seed=2,
    )
    assert r.samples_pass / r.samples_total >= 0.99


def test_rc_lowpass_tight_spec_partial_yield():
    """Tighter spec (3%) on the same 1%R/5%C — verifies the library
    actually counts failures rather than trivially passing everything.
    3% / 1.7%σ ≈ 1.77σ → ~92% one-spec yield."""
    r = analyze(
        nominal_values={"R": 1e3, "C": 1e-9},
        passive_tolerances={"R": 0.01, "C": 0.05},
        metrics=lambda R, C: {"fc": 1 / (2 * math.pi * R * C)},
        spec={"fc": ("within", 0.03)},
        n_mc=5000, seed=3,
    )
    yield_frac = r.samples_pass / r.samples_total
    assert 0.7 < yield_frac < 0.99


# ---------- Sallen-Key happy path ----------

def test_sallen_key_butterworth_yield_under_realistic_tolerances():
    """Same fixture as tests/test_eseries_opt.py: R1=R2=10k, C1=10n,
    C2=22n → fc≈1073 Hz, Q≈0.7416. With 1%R / 5%C, fc-within-5% and
    Q-within-10% are both ≥3σ — high yield expected."""
    nominal = {"R1": 1e4, "R2": 1e4, "C1": 1e-8, "C2": 2.2e-8}

    def metrics(R1, R2, C1, C2):
        fc = 1 / (2 * math.pi * math.sqrt(R1 * R2 * C1 * C2))
        Q = math.sqrt(R1 * R2 * C2 / C1) / (R1 + R2)
        return {"fc": fc, "Q": Q}

    r = analyze(
        nominal_values=nominal,
        passive_tolerances={"R": 0.01, "C": 0.05},
        metrics=metrics,
        spec={"fc": ("within", 0.05), "Q": ("within", 0.10)},
        n_mc=2000, seed=4,
    )
    assert r.samples_pass / r.samples_total >= 0.95
    assert r.per_spec_pass["fc"] >= 0.95 * r.samples_total
    assert r.per_spec_pass["Q"]  >= 0.95 * r.samples_total

    assert r.nominal_metrics["fc"] == pytest.approx(1073, rel=0.01)
    assert r.nominal_metrics["Q"]  == pytest.approx(0.7416, rel=0.01)


# ---------- Spec operators ----------

def test_threshold_lt_about_half_for_symmetric_perturbation():
    """R perturbed symmetrically about 1k with op '<' threshold = 1k:
    ~50% pass by symmetry."""
    r = analyze(
        nominal_values={"R": 1e3},
        passive_tolerances={"R": 0.10},
        metrics=lambda R: {"R": R},
        spec={"R": ("<", 1e3)},
        n_mc=2000, seed=5,
    )
    yield_frac = r.samples_pass / r.samples_total
    assert 0.45 < yield_frac < 0.55


def test_threshold_gt_complements_lt():
    r = analyze(
        nominal_values={"R": 1e3},
        passive_tolerances={"R": 0.10},
        metrics=lambda R: {"R": R},
        spec={"R": (">", 1e3)},
        n_mc=2000, seed=5,
    )
    yield_frac = r.samples_pass / r.samples_total
    assert 0.45 < yield_frac < 0.55


def test_within_db_spec():
    """3 dB tolerance ≈ √2 ratio. With 10%R perturbation on a metric =
    R, ~all samples are well within 3 dB."""
    r = analyze(
        nominal_values={"R": 1e3},
        passive_tolerances={"R": 0.10},
        metrics=lambda R: {"gain": R},
        spec={"gain": ("within_db", 3.0)},
        n_mc=500, seed=7,
    )
    assert r.samples_pass == 500


# ---------- Infeasibility & error handling ----------

def test_infeasible_spec_yields_zero_without_raising():
    """Spec impossible to satisfy under any perturbation. The library
    is for honest yield reporting, not assertion-style failure: it
    should report 0% and return normally."""
    r = analyze(
        nominal_values={"R": 1e3},
        passive_tolerances={"R": 0.01},
        metrics=lambda R: {"v": R},
        spec={"v": ("<", 0)},
        n_mc=200, seed=6,
    )
    assert r.samples_pass == 0
    assert r.per_spec_pass["v"] == 0


def test_unknown_component_prefix_raises():
    """A component without a matching entry in passive_tolerances is a
    user error — better to fail loudly than silently treat as zero-tol."""
    with pytest.raises(ValueError, match="L1"):
        analyze(
            nominal_values={"R1": 1e3, "L1": 1e-3},
            passive_tolerances={"R": 0.01},
            metrics=lambda R1, L1: {"v": R1},
            spec={"v": ("<", 1e9)},
            n_mc=10,
        )


def test_unknown_spec_operator_raises():
    with pytest.raises(ValueError, match="operator"):
        analyze(
            nominal_values={"R": 1e3},
            passive_tolerances={"R": 0.01},
            metrics=lambda R: {"v": R},
            spec={"v": ("≈", 1e3)},
            n_mc=10,
        )


# ---------- Determinism & monotonicity ----------

def test_seed_reproducible():
    kw = dict(
        nominal_values={"R": 1e3, "C": 1e-9},
        passive_tolerances={"R": 0.01, "C": 0.05},
        metrics=lambda R, C: {"fc": 1 / (2 * math.pi * R * C)},
        spec={"fc": ("within", 0.05)},
        n_mc=500, seed=42,
    )
    r1 = analyze(**kw)
    r2 = analyze(**kw)
    assert r1.samples_pass == r2.samples_pass
    assert r1.per_spec_pass == r2.per_spec_pass


# ---------- Metric distribution stats ----------

def test_metric_stats_populated_for_every_metric():
    """metric_stats covers every metric returned by metrics(), not just
    those mentioned in spec — so users can include diagnostic metrics
    and inspect their distribution without faking a spec."""
    r = analyze(
        nominal_values={"R": 1e3, "C": 1e-9},
        passive_tolerances={"R": 0.01, "C": 0.05},
        metrics=lambda R, C: {
            "fc": 1 / (2 * math.pi * R * C),
            "tau": R * C,                      # diagnostic, no spec
        },
        spec={"fc": ("within", 0.10)},
        n_mc=500, seed=10,
    )
    assert "fc"  in r.metric_stats
    assert "tau" in r.metric_stats
    assert isinstance(r.metric_stats["fc"], MetricStats)


def test_metric_stats_percentiles_ordered():
    r = analyze(
        nominal_values={"R": 1e3, "C": 1e-9},
        passive_tolerances={"R": 0.01, "C": 0.05},
        metrics=lambda R, C: {"fc": 1 / (2 * math.pi * R * C)},
        spec={"fc": ("within", 0.10)},
        n_mc=2000, seed=11,
    )
    s = r.metric_stats["fc"]
    assert s.min <= s.p1 <= s.p5 <= s.p50 <= s.p95 <= s.p99 <= s.max
    # Mean should sit close to nominal under symmetric Gaussian on RC
    assert s.mean == pytest.approx(r.nominal_metrics["fc"], rel=0.01)


def test_metric_stats_skew_and_kurtosis_for_gaussian_input():
    """An identity metric on a Gaussian-perturbed component should
    produce near-zero skew and excess kurtosis. n=10k MC noise on
    skew is √(6/n) ≈ 0.024; on excess kurtosis √(24/n) ≈ 0.05."""
    r = analyze(
        nominal_values={"R": 1e3},
        passive_tolerances={"R": 0.01},
        metrics=lambda R: {"R": R},
        spec={"R": ("within", 1.0)},
        n_mc=10000, seed=50,
    )
    s = r.metric_stats["R"]
    assert abs(s.skew) < 0.10
    assert abs(s.excess_kurtosis) < 0.20


def test_metric_stats_skew_positive_for_right_skewed_input():
    """A monotonic transform that widens the right tail produces
    positive skew. exp(R/scale) for R~Gaussian is log-normal — its
    skew is (e^σ² + 2)·√(e^σ² - 1) ≈ 3σ for small σ; with σ_R/R=10%
    on R~N(1000,100), expect skew ≈ 0.3."""
    r = analyze(
        nominal_values={"R": 1e3},
        passive_tolerances={"R": 0.30},  # σ_R = tol/3 = 10%
        metrics=lambda R: {"y": math.exp(R / 1e3)},
        spec={"y": ("<", 1e9)},
        n_mc=10000, seed=51,
    )
    s = r.metric_stats["y"]
    assert s.skew > 0.2          # right-tailed, well above MC noise
    assert s.excess_kurtosis > 0  # log-normal has positive excess kurt


def test_metric_stats_std_matches_analytical_for_rc():
    """σ_fc/fc ≈ √(σ_R² + σ_C²) where σ_R = 1/3%, σ_C = 5/3%.
    Expected relative σ ≈ 1.7%. Allow ±15% MC noise on n=5000."""
    r = analyze(
        nominal_values={"R": 1e3, "C": 1e-9},
        passive_tolerances={"R": 0.01, "C": 0.05},
        metrics=lambda R, C: {"fc": 1 / (2 * math.pi * R * C)},
        spec={"fc": ("within", 0.10)},
        n_mc=5000, seed=12,
    )
    s = r.metric_stats["fc"]
    rel_std = s.std / s.mean
    expected = math.sqrt((0.01 / 3) ** 2 + (0.05 / 3) ** 2)
    assert rel_std == pytest.approx(expected, rel=0.15)


# ---------- Failure-mode breakdown ----------

def test_failure_modes_empty_at_full_yield():
    r = analyze(
        nominal_values={"R": 1e3},
        passive_tolerances={"R": 0.0},
        metrics=lambda R: {"v": R},
        spec={"v": ("within", 0.01)},
        n_mc=100, seed=13,
    )
    assert r.failure_modes == {}


def test_failure_modes_count_matches_total_failures():
    """Sum over failure_modes equals samples_total - samples_pass —
    an invariant that catches bookkeeping bugs."""
    r = analyze(
        nominal_values={"R": 1e3, "C": 1e-9},
        passive_tolerances={"R": 0.01, "C": 0.05},
        metrics=lambda R, C: {"fc": 1 / (2 * math.pi * R * C)},
        spec={"fc": ("within", 0.02)},      # tight enough to fail some
        n_mc=2000, seed=14,
    )
    total_failed = sum(r.failure_modes.values())
    assert total_failed == r.samples_total - r.samples_pass
    assert total_failed > 0


def test_failure_modes_distinguish_independent_vs_joint_failure():
    """Two independent specs each failing ~half the time on
    perfectly-correlated metrics → joint failure dominates the
    breakdown. Two specs failing on uncorrelated metrics → marginals
    dominate. This is the structural info per_spec_pass can't show."""
    # Joint case: spec1 and spec2 both ride the same metric — they
    # always fail together.
    joint = analyze(
        nominal_values={"R": 1e3},
        passive_tolerances={"R": 0.10},
        metrics=lambda R: {"a": R, "b": R},
        spec={"a": ("<", 1e3), "b": ("<", 1e3)},
        n_mc=2000, seed=15,
    )
    # Every failing sample fails BOTH a and b together.
    for failing_set in joint.failure_modes:
        assert failing_set == frozenset({"a", "b"})

    # Single-spec failure case: only spec 'a' can fail.
    single = analyze(
        nominal_values={"R": 1e3},
        passive_tolerances={"R": 0.10},
        metrics=lambda R: {"a": R, "b": R},
        spec={"a": ("<", 1e3), "b": ("<", 1e9)},   # b passes always
        n_mc=2000, seed=15,
    )
    for failing_set in single.failure_modes:
        assert failing_set == frozenset({"a"})


# ---------- Monotonicity ----------

# ---------- Plotting ----------

def _two_metric_report(spec):
    return analyze(
        nominal_values={"R": 1e3, "C": 1e-9},
        passive_tolerances={"R": 0.01, "C": 0.05},
        metrics=lambda R, C: {
            "fc":  1 / (2 * math.pi * R * C),
            "tau": R * C,
        },
        spec=spec,
        n_mc=500, seed=20,
    )


def test_plot_returns_figure_with_one_axis_per_metric():
    import matplotlib
    r = _two_metric_report(spec={"fc": ("within", 0.05)})
    fig = r.plot()
    try:
        assert isinstance(fig, matplotlib.figure.Figure)
        # Two metrics → two visible axes (rest are turned off)
        visible = [ax for ax in fig.axes if ax.get_visible()
                   and ax.axison]
        assert len(visible) == 2
    finally:
        matplotlib.pyplot.close(fig)


def test_plot_filters_to_named_metrics():
    r = _two_metric_report(spec={"fc": ("within", 0.05)})
    fig = r.plot(metrics=["fc"])
    try:
        visible = [ax for ax in fig.axes if ax.axison]
        assert len(visible) == 1
        assert "fc" in visible[0].get_title()
    finally:
        import matplotlib.pyplot as plt
        plt.close(fig)


def test_plot_handles_partial_nan_samples_without_raising():
    """Real backends (ngspice with .meas tran .. when v(out)=0 fall=10
    on a non-oscillating sample) can produce NaN per-sample. plot()
    must strip them and annotate the count rather than blowing up
    on np.min(NaN) → set_xlim(NaN). This was a real bug found by the
    100k Wien-with-active-spreads run."""
    import matplotlib.pyplot as plt
    import numpy as np

    # Use a deterministic metric that returns NaN for ~5% of samples
    rng_metric = np.random.default_rng(99)
    def flaky(R):
        # NaN for samples whose R is below the 5th percentile
        return {"v": float("nan") if rng_metric.random() < 0.05 else R}

    r = analyze(
        nominal_values={"R": 1e3},
        passive_tolerances={"R": 0.05},
        metrics=flaky,
        spec={"v": ("within", 0.10)},
        n_mc=200, seed=88,
    )
    fig = r.plot()
    try:
        # NaN count should be visible in the panel title
        titles = [ax.get_title() for ax in fig.axes if ax.axison]
        assert any("NaN" in t for t in titles)
    finally:
        plt.close(fig)


def test_metric_stats_compute_on_finite_only():
    """If a sample's metric is NaN, MetricStats should be computed on
    the finite subset rather than itself going NaN. Without this every
    aggregate becomes NaN as soon as one sample fails."""
    def flaky(R):
        # NaN on every other sample
        flaky.n += 1
        return {"v": float("nan") if flaky.n % 2 == 0 else R}
    flaky.n = 0

    r = analyze(
        nominal_values={"R": 1e3},
        passive_tolerances={"R": 0.05},
        metrics=flaky,
        spec={"v": ("within", 0.10)},
        n_mc=100, seed=42,
    )
    s = r.metric_stats["v"]
    # mean should be the mean of the finite half, not NaN
    assert math.isfinite(s.mean)
    assert s.mean == pytest.approx(1e3, rel=0.05)
    assert math.isfinite(s.std)


def test_metric_stats_all_nan_yields_nan_stats_no_exception():
    """Edge case: if every sample's metric is NaN (catastrophic
    template error, dead simulator), the stats are NaN and plot()
    falls back to a 'no finite samples' message rather than raising."""
    import matplotlib.pyplot as plt

    r = analyze(
        nominal_values={"R": 1e3},
        passive_tolerances={"R": 0.05},
        metrics=lambda R: {"v": float("nan")},
        spec={"v": ("within", 0.10)},
        n_mc=20, seed=1,
    )
    s = r.metric_stats["v"]
    assert math.isnan(s.mean) and math.isnan(s.std)
    fig = r.plot()
    try:
        titles = [ax.get_title() for ax in fig.axes if ax.axison]
        assert any("no finite" in t for t in titles)
    finally:
        plt.close(fig)


def test_plot_handles_every_spec_operator_without_raising():
    """All six operators have a defined fail-region; plotting must not
    raise on any of them."""
    import matplotlib.pyplot as plt
    for op, thr in [("<", 1100), ("<=", 1100), (">", 900), (">=", 900),
                    ("within", 0.05), ("within_db", 1.0)]:
        r = analyze(
            nominal_values={"R": 1e3, "C": 1e-9},
            passive_tolerances={"R": 0.01, "C": 0.05},
            metrics=lambda R, C: {"fc": 1 / (2 * math.pi * R * C)},
            spec={"fc": (op, thr)},
            n_mc=200, seed=21,
        )
        fig = r.plot()
        plt.close(fig)


def test_plot_metrics_without_specs():
    """A metric returned by metrics() but absent from spec should still
    plot — just without the fail-region overlay."""
    import matplotlib.pyplot as plt
    r = _two_metric_report(spec={"fc": ("within", 0.05)})
    fig = r.plot()
    try:
        titles = [ax.get_title() for ax in fig.axes if ax.axison]
        # tau has no spec; should label that explicitly
        assert any("no spec" in t for t in titles)
    finally:
        plt.close(fig)


# ---------- Distribution model ----------

def test_tolerance_sigma_default_is_three():
    """Sanity: relative σ at the default convention is tol/3."""
    r = analyze(
        nominal_values={"R": 1e3},
        passive_tolerances={"R": 0.03},
        metrics=lambda R: {"R": R},
        spec={"R": ("within", 1.0)},  # accept everything
        n_mc=20000, seed=30,
    )
    rel_std = r.metric_stats["R"].std / r.nominal_metrics["R"]
    assert rel_std == pytest.approx(0.03 / 3, rel=0.05)


def test_tolerance_sigma_one_widens_the_distribution():
    """tolerance_sigma=1 → σ = tol → 3× wider than the default."""
    common = dict(
        nominal_values={"R": 1e3},
        passive_tolerances={"R": 0.01},
        metrics=lambda R: {"R": R},
        spec={"R": ("within", 1.0)},
        n_mc=20000, seed=31,
    )
    default = analyze(**common)
    wide    = analyze(**common, tolerance_sigma=1.0)
    ratio = wide.metric_stats["R"].std / default.metric_stats["R"].std
    assert ratio == pytest.approx(3.0, rel=0.05)


def test_uniform_distribution_has_hard_cutoff_at_tolerance():
    """Every uniform sample lies within ±tol of nominal — the defining
    property that distinguishes it from Gaussian (which has tails)."""
    tol = 0.01
    r = analyze(
        nominal_values={"R": 1e3},
        passive_tolerances={"R": tol},
        metrics=lambda R: {"R": R},
        spec={"R": ("within", 1.0)},
        n_mc=10000, seed=32,
        distribution="uniform",
    )
    s = r.metric_stats["R"]
    nom = r.nominal_metrics["R"]
    assert s.min >= nom * (1 - tol) - 1e-9
    assert s.max <= nom * (1 + tol) + 1e-9


def test_uniform_distribution_std_matches_analytical():
    """For Uniform(-tol, +tol), σ = tol/√3."""
    tol = 0.10
    r = analyze(
        nominal_values={"R": 1e3},
        passive_tolerances={"R": tol},
        metrics=lambda R: {"R": R},
        spec={"R": ("within", 1.0)},
        n_mc=20000, seed=33,
        distribution="uniform",
    )
    rel_std = r.metric_stats["R"].std / r.nominal_metrics["R"]
    assert rel_std == pytest.approx(tol / math.sqrt(3), rel=0.03)


def test_distribution_dict_per_prefix():
    """{'R': 'uniform'} routes only resistors through uniform; the
    capacitor still defaults to gaussian."""
    r = analyze(
        nominal_values={"R": 1e3, "C": 1e-9},
        passive_tolerances={"R": 0.01, "C": 0.05},
        metrics=lambda R, C: {"R": R, "C": C},
        spec={"R": ("within", 1.0), "C": ("within", 1.0)},
        n_mc=10000, seed=34,
        distribution={"R": "uniform"},
    )
    # R: uniform, hard cutoff
    assert r.metric_stats["R"].max <= 1e3 * 1.01 + 1e-9
    # C: gaussian — likely has a sample outside ±5% in 10000 (3σ tail
    # is ~0.27% per side, so ≥ 1 sample beyond ±5% expected)
    assert r.metric_stats["C"].max > 1e-9 * 1.05


def test_distribution_dict_per_component():
    """Per-component override beats per-prefix: {'C1': 'uniform'}
    routes one specific cap through uniform, leaves C2 gaussian."""
    r = analyze(
        nominal_values={"C1": 1e-8, "C2": 1e-8},
        passive_tolerances={"C": 0.10},
        metrics=lambda C1, C2: {"C1": C1, "C2": C2},
        spec={"C1": ("within", 1.0), "C2": ("within", 1.0)},
        n_mc=10000, seed=35,
        distribution={"C1": "uniform"},
    )
    assert r.metric_stats["C1"].max <= 1e-8 * 1.10 + 1e-12
    # C2 gaussian → some samples will spill past ±10%
    assert r.metric_stats["C2"].max > 1e-8 * 1.10


def test_unknown_distribution_name_raises():
    with pytest.raises(ValueError, match="distribution"):
        analyze(
            nominal_values={"R": 1e3},
            passive_tolerances={"R": 0.01},
            metrics=lambda R: {"v": R},
            spec={"v": ("within", 1.0)},
            n_mc=10,
            distribution="cauchy",
        )


def test_distribution_dict_unknown_key_raises():
    """Typos in a per-component override would otherwise fall back to
    gaussian silently — fail loudly instead, same principle as
    unknown component prefix."""
    with pytest.raises(ValueError, match="C99"):
        analyze(
            nominal_values={"C1": 1e-8},
            passive_tolerances={"C": 0.05},
            metrics=lambda C1: {"v": C1},
            spec={"v": ("within", 1.0)},
            n_mc=10,
            distribution={"C99": "uniform"},
        )


def test_tolerance_sigma_non_positive_raises():
    with pytest.raises(ValueError, match="tolerance_sigma"):
        analyze(
            nominal_values={"R": 1e3},
            passive_tolerances={"R": 0.01},
            metrics=lambda R: {"v": R},
            spec={"v": ("within", 1.0)},
            n_mc=10,
            tolerance_sigma=0.0,
        )


# ---------- Parallelism ----------

def test_workers_match_serial_results():
    """workers > 1 must give bit-identical yield + per-spec pass +
    failure_modes as the serial path. Sample order is preserved by
    ThreadPoolExecutor.map, so determinism per seed is unchanged."""
    common = dict(
        nominal_values={"R": 1e3, "C": 1e-9},
        passive_tolerances={"R": 0.01, "C": 0.05},
        metrics=lambda R, C: {"fc": 1 / (2 * math.pi * R * C)},
        spec={"fc": ("within", 0.02)},
        n_mc=500, seed=999,
    )
    serial = analyze(workers=1, **common)
    parallel = analyze(workers=4, **common)
    assert parallel.samples_pass == serial.samples_pass
    assert parallel.per_spec_pass == serial.per_spec_pass
    assert parallel.failure_modes == serial.failure_modes


def test_workers_zero_or_negative_raises():
    with pytest.raises(ValueError, match="workers"):
        analyze(
            nominal_values={"R": 1e3},
            passive_tolerances={"R": 0.01},
            metrics=lambda R: {"v": R},
            spec={"v": ("<", 1e9)},
            n_mc=10, workers=0,
        )


def test_workers_propagates_metric_exception():
    """An exception inside metrics() under workers > 1 must surface,
    not silently produce a partial yield report. ThreadPoolExecutor.map
    re-raises on iteration; we must not swallow it."""
    def bad_metrics(R):
        raise RuntimeError("simulated metric failure")

    with pytest.raises(RuntimeError, match="simulated metric failure"):
        analyze(
            nominal_values={"R": 1e3},
            passive_tolerances={"R": 0.01},
            metrics=bad_metrics,
            spec={"v": ("<", 1e9)},
            n_mc=20, workers=4,
        )


# ---------- CachedBackend ----------

class _CountingBackend:
    """Lightweight stand-in for an expensive backend — counts calls so
    we can assert the cache prevents recomputation. Has a signature so
    different instances are isolated under one cache file."""
    def __init__(self, name="default"):
        self.calls = 0
        self.name = name
    def __call__(self, **values):
        self.calls += 1
        return {"sum": sum(values.values())}
    def signature(self):
        return f"counting:{self.name}"


def test_cached_backend_in_memory_hit_skips_recompute():
    base = _CountingBackend()
    cached = CachedBackend(base)
    r1 = cached(R=1.0, C=2.0)
    r2 = cached(R=1.0, C=2.0)
    assert r1 == r2 == {"sum": 3.0}
    assert base.calls == 1
    assert cached.hits == 1
    assert cached.misses == 1


def test_cached_backend_distinct_args_both_compute():
    base = _CountingBackend()
    cached = CachedBackend(base)
    cached(R=1.0)
    cached(R=2.0)
    cached(R=1.0)
    assert base.calls == 2
    assert cached.hits == 1
    assert cached.misses == 2


def test_cached_backend_persists_to_sqlite(tmp_path):
    """A new CachedBackend instance pointing at the same sqlite file
    should serve cached values from the previous run — the headline
    persistent-cache promise."""
    db = tmp_path / "cache.sqlite"
    base1 = _CountingBackend()
    cached1 = CachedBackend(base1, path=db)
    cached1(R=1.0, C=2.0)
    cached1.close()

    base2 = _CountingBackend()
    cached2 = CachedBackend(base2, path=db)
    r = cached2(R=1.0, C=2.0)
    assert r == {"sum": 3.0}
    assert base2.calls == 0   # served from disk; backend never called
    assert cached2.hits == 1
    cached2.close()


def test_cached_backend_signature_isolates_namespaces(tmp_path):
    """Two backends with different signatures sharing one cache file
    must not see each other's entries — otherwise swapping templates
    would silently return wrong data."""
    db = tmp_path / "cache.sqlite"
    base_a = _CountingBackend(name="A")
    base_b = _CountingBackend(name="B")
    cached_a = CachedBackend(base_a, path=db)
    cached_b = CachedBackend(base_b, path=db)
    cached_a(x=1.0)
    cached_b(x=1.0)
    # B should NOT find A's cached value
    assert base_a.calls == 1
    assert base_b.calls == 1
    cached_a.close(); cached_b.close()


def test_cached_backend_clear_drops_only_own_signature(tmp_path):
    db = tmp_path / "cache.sqlite"
    base_a = _CountingBackend(name="A")
    base_b = _CountingBackend(name="B")
    cached_a = CachedBackend(base_a, path=db)
    cached_b = CachedBackend(base_b, path=db)
    cached_a(x=1.0); cached_b(x=1.0)
    cached_a.clear()

    # Re-instantiate to confirm disk state matches expectations
    cached_a.close(); cached_b.close()
    cached_a2 = CachedBackend(_CountingBackend(name="A"), path=db)
    cached_b2 = CachedBackend(_CountingBackend(name="B"), path=db)
    cached_a2(x=1.0); cached_b2(x=1.0)
    assert cached_a2.misses == 1   # cleared, recomputed
    assert cached_b2.hits == 1     # untouched
    cached_a2.close(); cached_b2.close()


def test_cached_backend_thread_safe_with_workers():
    """Cache must be safe under analyze(workers=N). Repeat the same
    yield computation twice; the second run is fully cache-served and
    must give bit-identical results without raising."""
    base = _CountingBackend(name="thread")
    cached = CachedBackend(base)

    common = dict(
        nominal_values={"R": 1e3, "C": 1e-9},
        passive_tolerances={"R": 0.01, "C": 0.05},
        metrics=cached,
        spec={"sum": ("<", 1e9)},
        n_mc=200, seed=777, workers=4,
    )
    r1 = analyze(**common)
    calls_after_first = base.calls
    r2 = analyze(**common)
    assert r1.samples_pass == r2.samples_pass
    assert r1.metric_stats["sum"].mean == r2.metric_stats["sum"].mean
    # Second run: every sample served from cache
    assert base.calls == calls_after_first


def test_cached_backend_handles_nan_outputs():
    """NaN must round-trip through json so failed samples cache too —
    otherwise repeated runs would re-execute every previously-failed
    simulation."""
    class NaNBackend:
        def __init__(self): self.calls = 0
        def __call__(self, **v): self.calls += 1; return {"x": float("nan")}
        def signature(self): return "nan"
    base = NaNBackend()
    cached = CachedBackend(base)
    r1 = cached(a=1.0)
    r2 = cached(a=1.0)
    assert math.isnan(r1["x"]) and math.isnan(r2["x"])
    assert base.calls == 1


def test_cached_backend_explicit_signature_overrides_auto():
    """User-supplied signature= takes precedence over wrapped.signature()
    — escape hatch for sharing a cache across two backends that you
    know are equivalent."""
    base = _CountingBackend(name="A")
    cached = CachedBackend(base, signature="custom-namespace")
    cached(x=1.0)
    assert cached.signature == "custom-namespace"


# ---------- Monotonicity ----------

def test_looser_spec_yields_at_least_as_much_as_tighter():
    """Behavioural sanity: loosening the spec must not reduce yield
    when MC seed is fixed."""
    base = dict(
        nominal_values={"R": 1e3, "C": 1e-9},
        passive_tolerances={"R": 0.01, "C": 0.05},
        metrics=lambda R, C: {"fc": 1 / (2 * math.pi * R * C)},
        n_mc=1000, seed=99,
    )
    tight = analyze(**base, spec={"fc": ("within", 0.02)})
    loose = analyze(**base, spec={"fc": ("within", 0.10)})
    assert loose.samples_pass >= tight.samples_pass
