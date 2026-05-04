"""Tests for the per-component Sampler implementations and the
active-device library expansion."""
import math
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import numpy as np
import pytest

from utils.tolerance import (
    Sampler,
    RelativeGaussian, RelativeUniform, AbsoluteGaussian,
    Uniform, LogUniform, Constant,
    DEVICES, expand_active_devices,
    analyze,
)


def _rng(seed=0):
    return np.random.default_rng(seed)


# ---------- RelativeGaussian ----------

def test_relative_gaussian_centred_on_nominal_with_3sigma_at_tol():
    s = RelativeGaussian(nominal_value=1000.0, tol=0.03)  # 3% tol, 3σ default
    arr = s.sample(_rng(0), 20000)
    assert arr.mean() == pytest.approx(1000.0, rel=0.005)
    # σ should be nominal·tol/3 = 10
    assert arr.std() == pytest.approx(10.0, rel=0.05)


def test_relative_gaussian_sigmas_kwarg_widens_distribution():
    """sigmas=1 means the tol limit corresponds to ±1σ — 3× wider
    than the default sigmas=3."""
    arr1 = RelativeGaussian(nominal_value=1000.0, tol=0.01,
                            sigmas=1.0).sample(_rng(1), 20000)
    arr3 = RelativeGaussian(nominal_value=1000.0, tol=0.01,
                            sigmas=3.0).sample(_rng(1), 20000)
    assert arr1.std() / arr3.std() == pytest.approx(3.0, rel=0.05)


def test_relative_gaussian_nominal_returns_centre():
    assert RelativeGaussian(nominal_value=4.7e3, tol=0.01).nominal() == 4.7e3


# ---------- RelativeUniform ----------

def test_relative_uniform_hard_cutoff_at_tolerance():
    s = RelativeUniform(nominal_value=1000.0, tol=0.05)
    arr = s.sample(_rng(2), 10000)
    assert arr.min() >= 950.0 - 1e-9
    assert arr.max() <= 1050.0 + 1e-9


def test_relative_uniform_std_matches_analytical():
    """For Uniform(-tol, tol), σ = tol/√3."""
    arr = RelativeUniform(nominal_value=1000.0, tol=0.10).sample(_rng(3), 20000)
    assert arr.std() / 1000.0 == pytest.approx(0.10 / math.sqrt(3), rel=0.03)


# ---------- AbsoluteGaussian ----------

def test_absolute_gaussian_mean_and_sigma_match_args():
    s = AbsoluteGaussian(mean=0.0, sigma=1e-3)
    arr = s.sample(_rng(4), 20000)
    assert arr.mean() == pytest.approx(0.0, abs=2e-5)  # σ/√n at n=20k
    assert arr.std() == pytest.approx(1e-3, rel=0.03)


def test_absolute_gaussian_mean_can_be_zero():
    """The whole point of AbsoluteGaussian: nominal=0 is fine
    (unlike relative tolerance, where 0% nominal is undefined)."""
    s = AbsoluteGaussian(mean=0.0, sigma=5e-3)
    s.sample(_rng(5), 100)  # should not raise
    assert s.nominal() == 0.0


# ---------- Uniform ----------

def test_uniform_samples_in_bounds():
    s = Uniform(lo=-2.3, hi=-0.4)
    arr = s.sample(_rng(6), 5000)
    assert arr.min() >= -2.3 - 1e-9
    assert arr.max() <= -0.4 + 1e-9


def test_uniform_nominal_is_arithmetic_midpoint():
    assert Uniform(lo=10.0, hi=20.0).nominal() == 15.0


# ---------- LogUniform ----------

def test_loguniform_spans_bounds_in_log_space():
    s = LogUniform(lo=50e3, hi=1e6)
    arr = s.sample(_rng(7), 10000)
    assert arr.min() >= 50e3 - 1
    assert arr.max() <= 1e6 + 1
    # Geometric mean should match the analytic √(lo·hi)
    geom = float(np.exp(np.log(arr).mean()))
    assert geom == pytest.approx(math.sqrt(50e3 * 1e6), rel=0.03)


def test_loguniform_nominal_is_geometric_mean():
    s = LogUniform(lo=100, hi=400)
    assert s.nominal() == pytest.approx(200.0)  # √(100·400)


def test_loguniform_rejects_non_positive_bounds():
    with pytest.raises(ValueError, match="positive"):
        LogUniform(lo=0, hi=10)
    with pytest.raises(ValueError, match="positive"):
        LogUniform(lo=-1, hi=10)


def test_loguniform_rejects_inverted_range():
    with pytest.raises(ValueError, match="lo < hi"):
        LogUniform(lo=10, hi=5)


# ---------- Constant ----------

def test_constant_returns_fixed_value():
    s = Constant(value=42.0)
    arr = s.sample(_rng(8), 100)
    assert (arr == 42.0).all()
    assert s.nominal() == 42.0


# ---------- DEVICES library ----------

def test_devices_library_contains_briefing_parts():
    """The four parts in ngspice_examples/ — adding new ones is
    mechanical but the user-facing demo depends on these existing."""
    assert {"NE5532", "TLV9104", "2N3904", "J201"} <= set(DEVICES)


def test_every_device_param_is_a_sampler():
    for part, params in DEVICES.items():
        for name, sampler in params.items():
            assert isinstance(sampler, Sampler), \
                f"{part}.{name} is not a Sampler instance"


def test_ne5532_vos_3sigma_matches_datasheet_max():
    """Convention check: the AbsoluteGaussian σ for an op-amp's Vos
    should be set so 3σ matches the datasheet max. NE5532 max ±3 mV
    → σ = 1 mV."""
    vos = DEVICES["NE5532"]["Vos"]
    assert isinstance(vos, AbsoluteGaussian)
    assert vos.mean == 0.0
    assert vos.sigma == pytest.approx(1e-3)


def test_2n3904_bf_loguniform_matches_datasheet_bounds():
    bf = DEVICES["2N3904"]["BF"]
    assert isinstance(bf, LogUniform)
    assert (bf.lo, bf.hi) == (100, 400)


# ---------- expand_active_devices ----------

def test_expand_active_devices_keys_are_instance_param():
    s = expand_active_devices({"U1": "NE5532"})
    expected = {"U1_Vos", "U1_Ib", "U1_Avol", "U1_GBW"}
    assert set(s) == expected


def test_expand_active_devices_multiple_instances_distinct_prefixes():
    s = expand_active_devices({"U1": "NE5532", "U2": "TLV9104"})
    assert "U1_Vos" in s and "U2_Vos" in s
    # Different sampler instances even though both are AbsoluteGaussian
    assert s["U1_Vos"] is not s["U2_Vos"]


def test_expand_active_devices_unknown_part_raises():
    with pytest.raises(ValueError, match="MADE_UP_PART"):
        expand_active_devices({"U1": "MADE_UP_PART"})


def test_expand_active_devices_custom_library():
    """library= override lets the user supply test fixtures or
    project-specific parts without modifying the curated DEVICES dict."""
    custom = {"FAKE": {"X": Constant(value=7.0)}}
    s = expand_active_devices({"U1": "FAKE"}, library=custom)
    assert s == {"U1_X": custom["FAKE"]["X"]}


# ---------- analyze() with active_devices ----------

def test_analyze_active_devices_passes_params_to_metrics():
    """The metrics callable should receive the active-device
    parameters as keyword args alongside passives."""
    seen_kwargs = []

    def metrics(R, U1_Vos, U1_Ib, U1_Avol, U1_GBW):
        seen_kwargs.append(set(("R", "U1_Vos", "U1_Ib",
                                "U1_Avol", "U1_GBW")))
        return {"v": R}

    analyze(
        nominal_values={"R": 1e3},
        passive_tolerances={"R": 0.01},
        active_devices={"U1": "NE5532"},
        metrics=metrics,
        spec={"v": ("<", 1e9)},
        n_mc=5, seed=10,
    )
    # All 5 calls plus one nominal evaluation = 6
    assert len(seen_kwargs) == 6


def test_analyze_active_devices_nominal_uses_sampler_nominal():
    """Nominal-evaluation call to metrics() should use each Sampler's
    nominal() value — for AbsoluteGaussian that's mean (0 for Vos),
    for LogUniform that's the geometric mean."""
    captured = {}

    def metrics(R, U1_Vos, U1_Avol, U1_Ib, U1_GBW):
        if not captured:    # first call is the nominal
            captured["U1_Vos"] = U1_Vos
            captured["U1_Avol"] = U1_Avol
        return {"v": R}

    analyze(
        nominal_values={"R": 1e3},
        passive_tolerances={"R": 0.01},
        active_devices={"U1": "NE5532"},
        metrics=metrics,
        spec={"v": ("<", 1e9)},
        n_mc=1, seed=11,
    )
    assert captured["U1_Vos"] == 0.0      # AbsoluteGaussian mean
    assert captured["U1_Avol"] == pytest.approx(
        math.sqrt(50e3 * 1e6)             # LogUniform geometric mean
    )


def test_analyze_distribution_dict_accepts_sampler_instance_for_passive():
    """Per-component override with a custom Sampler — escape hatch for
    passives that need shapes the string API can't express."""
    captured = []
    def metrics(R):
        captured.append(R)
        return {"v": R}

    analyze(
        nominal_values={"R": 1e3},
        passive_tolerances={"R": 0.01},
        distribution={"R": Constant(value=999.0)},
        metrics=metrics,
        spec={"v": ("<", 1e9)},
        n_mc=10, seed=12,
    )
    # First call is nominal (uses nominal_values["R"]), then 10 MC
    # samples all served by Constant(999.0).
    assert captured[1:] == [999.0] * 10


def test_analyze_distribution_dict_overrides_active_device_param():
    """If active_devices and distribution both specify a parameter,
    the explicit distribution entry wins — escape hatch for binning
    a specific instance tighter than the device-library default."""
    captured = []
    def metrics(R, U1_Vos, U1_Ib, U1_Avol, U1_GBW):
        captured.append(U1_Vos)
        return {"v": R}

    analyze(
        nominal_values={"R": 1e3},
        passive_tolerances={"R": 0.01},
        active_devices={"U1": "NE5532"},
        distribution={"U1_Vos": Constant(value=1e-6)},  # 1 µV, very tight
        metrics=metrics,
        spec={"v": ("<", 1e9)},
        n_mc=10, seed=13,
    )
    assert captured[1:] == [1e-6] * 10


def test_analyze_active_devices_collision_with_nominal_values_raises():
    """If the user already declared U1_Vos in nominal_values AND asks
    for active_devices={"U1": "NE5532"}, that's a name collision — fail
    loudly rather than picking one silently."""
    with pytest.raises(ValueError, match="collision"):
        analyze(
            nominal_values={"R": 1e3, "U1_Vos": 1e-3},
            passive_tolerances={"R": 0.01},
            active_devices={"U1": "NE5532"},
            metrics=lambda **kw: {"v": kw["R"]},
            spec={"v": ("<", 1e9)},
            n_mc=5,
        )


def test_analyze_active_devices_distribution_validation_includes_param_keys():
    """An override on an active-device-derived param key (U1_Vos) must
    be accepted by the distribution-key validator — without that, the
    user's escape hatch would falsely report 'unknown component'."""
    # Should not raise:
    analyze(
        nominal_values={"R": 1e3},
        passive_tolerances={"R": 0.01},
        active_devices={"U1": "NE5532"},
        distribution={"U1_Vos": AbsoluteGaussian(0, 0.5e-3)},
        metrics=lambda **kw: {"v": kw["R"]},
        spec={"v": ("<", 1e9)},
        n_mc=3, seed=14,
    )


def test_analyze_explicit_sampler_skips_prefix_classifier():
    """A name with an explicit Sampler in distribution doesn't have
    to match a known passive prefix — useful for one-off active-device
    parameters (e.g., a custom 'Vos_LM358' for an op-amp not in the
    curated DEVICES library) and for derived parameters like 'ESR'.
    Without this, every custom-named param needed a placeholder
    passive_tolerances entry just to satisfy the prefix classifier."""
    seen = []
    def metrics(R, ESR, Vos_my_opamp):
        seen.append((R, ESR, Vos_my_opamp))
        return {"v": R}

    # 'E' and 'V' aren't in passive_tolerances — would normally raise.
    analyze(
        nominal_values={"R": 1e3, "ESR": 1e-3, "Vos_my_opamp": 0.0},
        passive_tolerances={"R": 0.01},
        distribution={
            "ESR":          Uniform(lo=0.5e-3, hi=5e-3),
            "Vos_my_opamp": AbsoluteGaussian(mean=0, sigma=2e-3),
        },
        metrics=metrics,
        spec={"v": ("<", 1e9)},
        n_mc=10, seed=20,
    )
    # 1 nominal + 10 MC = 11 calls
    assert len(seen) == 11


def test_analyze_unknown_prefix_still_raises_without_explicit_sampler():
    """The escape hatch only opens when an explicit Sampler is supplied.
    Without one, an unrecognised prefix should still fail loudly — the
    misconfiguration safety from the original classifier is intact."""
    with pytest.raises(ValueError, match="ESR"):
        analyze(
            nominal_values={"R": 1e3, "ESR": 1e-3},
            passive_tolerances={"R": 0.01},
            metrics=lambda R, ESR: {"v": R},
            spec={"v": ("<", 1e9)},
            n_mc=5,
        )


# ---------- Parameter correlations ----------

def test_correlations_preserve_marginal_variance():
    """Correlated samples must have the same per-component σ as
    independent samples — only the joint distribution changes. Verify
    by comparing σ on a correlated vs independent run."""
    common = dict(
        nominal_values={"R1": 1e3, "R2": 1e3},
        passive_tolerances={"R": 0.05},
        metrics=lambda R1, R2: {"R1": R1, "R2": R2},
        spec={"R1": ("within", 1.0), "R2": ("within", 1.0)},
        n_mc=10000, seed=100,
    )
    indep = analyze(**common)
    corr  = analyze(correlations=[(["R1", "R2"], 0.95)], **common)
    # Marginal σ should match within MC noise (~σ/√(2n) ≈ 0.7%)
    for nm in ("R1", "R2"):
        assert corr.metric_stats[nm].std == pytest.approx(
            indep.metric_stats[nm].std, rel=0.05
        )


def test_correlations_change_joint_distribution():
    """Correlated R1, R2 should be much more correlated in the
    output than independent samples, while keeping the same marginals.
    Test on the metric (R1+R2) — independent samples have
    σ_sum² = 2σ², while ρ=0.95 correlated have σ_sum² ≈ 1.95·2σ²
    ≈ 3.9× higher than independent (or ≈ 2× larger σ_sum)."""
    import numpy as np
    common = dict(
        nominal_values={"R1": 1e3, "R2": 1e3},
        passive_tolerances={"R": 0.05},
        metrics=lambda R1, R2: {"sum": R1 + R2, "diff": R1 - R2},
        spec={"sum": ("<", 1e9), "diff": ("<", 1e9)},
        n_mc=10000, seed=101,
    )
    indep = analyze(**common)
    corr  = analyze(correlations=[(["R1", "R2"], 0.95)], **common)

    # σ(sum) should be much LARGER under positive ρ
    sum_ratio = corr.metric_stats["sum"].std / indep.metric_stats["sum"].std
    assert sum_ratio == pytest.approx(np.sqrt(1 + 0.95), rel=0.05)

    # σ(diff) should be much SMALLER under positive ρ
    diff_ratio = corr.metric_stats["diff"].std / indep.metric_stats["diff"].std
    assert diff_ratio == pytest.approx(np.sqrt(1 - 0.95), rel=0.10)


def test_correlations_negative_rho_for_two_components():
    """ρ = -0.7 between two parameters: standard for op-amp Avol/GBW
    anti-correlation. Verify the sample correlation matches."""
    import numpy as np
    captured_R1, captured_R2 = [], []
    def metrics(R1, R2):
        captured_R1.append(R1); captured_R2.append(R2)
        return {"v": R1}
    analyze(
        nominal_values={"R1": 1e3, "R2": 1e3},
        passive_tolerances={"R": 0.05},
        metrics=metrics,
        spec={"v": ("<", 1e9)},
        n_mc=5000, seed=102,
        correlations=[(["R1", "R2"], -0.7)],
    )
    # Strip the single nominal call (first one) to keep just the MC
    R1, R2 = np.array(captured_R1[1:]), np.array(captured_R2[1:])
    rho_observed = np.corrcoef(R1, R2)[0, 1]
    assert rho_observed == pytest.approx(-0.7, abs=0.03)


def test_correlations_negative_rho_with_three_components_raises():
    with pytest.raises(ValueError, match="negative"):
        analyze(
            nominal_values={"R1": 1e3, "R2": 1e3, "R3": 1e3},
            passive_tolerances={"R": 0.01},
            metrics=lambda R1, R2, R3: {"v": R1},
            spec={"v": ("<", 1e9)},
            n_mc=10,
            correlations=[(["R1", "R2", "R3"], -0.5)],
        )


def test_correlations_unknown_component_raises():
    with pytest.raises(ValueError, match="Rxxxx"):
        analyze(
            nominal_values={"R1": 1e3, "R2": 1e3},
            passive_tolerances={"R": 0.01},
            metrics=lambda R1, R2: {"v": R1},
            spec={"v": ("<", 1e9)},
            n_mc=10,
            correlations=[(["R1", "Rxxxx"], 0.5)],
        )


def test_correlations_overlapping_groups_raise():
    with pytest.raises(ValueError, match="multiple correlation groups"):
        analyze(
            nominal_values={"R1": 1e3, "R2": 1e3, "R3": 1e3},
            passive_tolerances={"R": 0.01},
            metrics=lambda R1, R2, R3: {"v": R1},
            spec={"v": ("<", 1e9)},
            n_mc=10,
            correlations=[(["R1", "R2"], 0.5), (["R2", "R3"], 0.5)],
        )


def test_correlations_non_gaussian_sampler_raises():
    """Correlation requires Gaussian-family marginals. Uniform
    samplers don't compose under simple correlation."""
    with pytest.raises(ValueError, match="Gaussian"):
        analyze(
            nominal_values={"R1": 1e3, "R2": 1e3},
            passive_tolerances={"R": 0.01},
            distribution="uniform",
            metrics=lambda R1, R2: {"v": R1},
            spec={"v": ("<", 1e9)},
            n_mc=10,
            correlations=[(["R1", "R2"], 0.5)],
        )


def test_correlations_rho_out_of_range_raises():
    for bad in (-1.5, 1.5, 2.0):
        with pytest.raises(ValueError, match="ρ must be in"):
            analyze(
                nominal_values={"R1": 1e3, "R2": 1e3},
                passive_tolerances={"R": 0.01},
                metrics=lambda R1, R2: {"v": R1},
                spec={"v": ("<", 1e9)},
                n_mc=10,
                correlations=[(["R1", "R2"], bad)],
            )


def test_correlations_default_none_unchanged_behaviour():
    """correlations=None must produce the same sample-level results as
    the pre-correlation API. Regression check on the new code path."""
    common = dict(
        nominal_values={"R": 1e3, "C": 1e-9},
        passive_tolerances={"R": 0.01, "C": 0.05},
        metrics=lambda R, C: {"fc": 1 / (3.14159 * 2 * R * C)},
        spec={"fc": ("within", 0.05)},
        n_mc=500, seed=55,
    )
    a = analyze(correlations=None, **common)
    b = analyze(**common)
    assert a.samples_pass == b.samples_pass
    assert a.metric_stats["fc"].mean == b.metric_stats["fc"].mean


# ---------- Temperature dependence ----------

def test_temperature_passes_T_to_metrics():
    """When temperature is set, metrics callable must receive T as
    kwarg. Without temperature, metrics signature is unchanged."""
    seen = []
    def metrics_with_T(R, T):
        seen.append(("with_T", R, T))
        return {"v": R}
    def metrics_no_T(R):
        seen.append(("no_T", R))
        return {"v": R}

    # No temperature → metrics doesn't get T
    analyze(nominal_values={"R": 1e3},
            passive_tolerances={"R": 0.01},
            metrics=metrics_no_T,
            spec={"v": ("<", 1e9)},
            n_mc=3, seed=10)
    assert all(s[0] == "no_T" for s in seen)

    # With temperature → metrics gets T
    seen.clear()
    analyze(nominal_values={"R": 1e3},
            passive_tolerances={"R": 0.01},
            metrics=metrics_with_T,
            spec={"v": ("<", 1e9)},
            n_mc=3, seed=11,
            temperature=Uniform(lo=-40, hi=85),
            temperature_coefficients={"R": 50e-6})
    assert all(s[0] == "with_T" for s in seen)
    # T values should be in the [-40, 85] range
    for _, _, T in seen:
        assert -40 <= T <= 85


def test_temperature_scales_components_by_tempco():
    """A pure-tempco resistor sweep over the operating range should
    produce a deterministic output proportional to (1 + tempco·ΔT).
    Use Constant samplers for tolerance to isolate the tempco effect."""
    captured = []
    def metrics(R, T):
        captured.append((R, T))
        return {"R": R}

    analyze(
        nominal_values={"R": 1000.0},
        passive_tolerances={"R": 0.0},   # zero tolerance
        distribution={"R": Constant(value=1000.0)},
        metrics=metrics,
        spec={"R": ("<", 1e9)},
        n_mc=2000, seed=42,
        temperature=Uniform(lo=-40, hi=85),
        temperature_coefficients={"R": 100e-6},  # 100 ppm/°C
        temperature_nominal=25,
    )
    # First call is the nominal (T=25, R=1000 exactly)
    nominal_R, nominal_T = captured[0]
    assert nominal_R == pytest.approx(1000.0)
    assert nominal_T == 25
    # MC calls: R(T) = 1000 · (1 + 100e-6·(T-25))
    for R, T in captured[1:]:
        expected = 1000.0 * (1.0 + 100e-6 * (T - 25))
        assert R == pytest.approx(expected, rel=1e-9)


def test_additive_tempco_zero_at_T_nominal():
    """At T = T_nominal, the additive tempco contribution is zero by
    construction (drift × 0 = 0). The sample equals the per-component
    sampler's draw."""
    from utils.tolerance import Additive
    captured = []
    def metrics(Vos, T=25):
        captured.append((Vos, T))
        return {"v": Vos}

    analyze(
        nominal_values={"Vos": 0.0},
        passive_tolerances={"V": 0.0},   # placeholder for prefix lookup
        distribution={"Vos": AbsoluteGaussian(mean=0.0, sigma=1e-3)},
        metrics=metrics,
        spec={"v": ("<", 1e9)},
        n_mc=500, seed=0,
        temperature=Constant(value=25.0),     # all samples at T=25
        temperature_coefficients={"Vos": Additive(sigma=5e-6)},
        temperature_nominal=25,
    )
    # At T=25, drift × 0 = 0, so Vos values come entirely from the
    # sampler. σ should be ~1mV (the Vos sampler), not influenced by drift.
    Vos_values = [v for v, T in captured[1:]]   # skip nominal call
    import numpy as np
    sigma = np.std(Vos_values)
    assert sigma == pytest.approx(1e-3, rel=0.10)


def test_additive_tempco_widens_distribution_at_corners():
    """At a corner T (e.g., +85°C), Additive tempco adds drift × ΔT
    in quadrature with the room-T distribution. Total σ = √(σ_room² +
    (sigma_drift · ΔT)²)."""
    from utils.tolerance import Additive
    import numpy as np

    captured = []
    def metrics(Vos, T=25):
        captured.append(Vos)
        return {"v": Vos}

    analyze(
        nominal_values={"Vos": 0.0},
        passive_tolerances={"V": 0.0},
        distribution={"Vos": AbsoluteGaussian(mean=0.0, sigma=1e-3)},
        metrics=metrics,
        spec={"v": ("<", 1e9)},
        n_mc=20000, seed=1,
        temperature=Constant(value=85.0),     # +60°C from nominal
        temperature_coefficients={"Vos": Additive(sigma=5e-6)},  # 5 µV/°C
        temperature_nominal=25,
    )
    # Expected: σ_total = √(1mV² + (5e-6 · 60)²) = √(1e-6 + 9e-8)
    # = √(1.09e-6) ≈ 1.044 mV
    Vos_values = np.array(captured[1:])
    sigma = Vos_values.std()
    expected = np.sqrt(1e-3 ** 2 + (5e-6 * 60) ** 2)
    assert sigma == pytest.approx(expected, rel=0.05)


def test_temperature_per_component_tempco_overrides_prefix():
    """Per-name tempcos override the prefix default — allows mixing
    e.g. one precision low-tempco part with standard parts."""
    captured = {}
    def metrics(R1, R2, T):
        captured.setdefault(round(T, 4), []).append((R1, R2))
        return {"v": R1}

    analyze(
        nominal_values={"R1": 1000.0, "R2": 1000.0},
        passive_tolerances={"R": 0.0},
        distribution={"R1": Constant(value=1000.0),
                       "R2": Constant(value=1000.0)},
        metrics=metrics,
        spec={"v": ("<", 1e9)},
        n_mc=200, seed=7,
        temperature=Uniform(lo=0, hi=100),
        temperature_coefficients={"R": 1000e-6, "R2": 5e-6},  # R2 tighter
        temperature_nominal=25,
    )
    # At any sample T, R1 should drift 200× more than R2
    sample_T = max(t for t in captured if abs(t - 25) > 30)  # well off-nominal
    R1, R2 = captured[sample_T][0]
    drift_R1 = (R1 - 1000) / 1000
    drift_R2 = (R2 - 1000) / 1000
    # Ratio should be 1000/5 = 200 (approximate due to rounding above)
    assert abs(drift_R1 / drift_R2) == pytest.approx(200, rel=0.01)


def test_temperature_disabled_by_default_no_T_kwarg():
    """Backward compatibility: existing metrics without T parameter
    must continue to work when temperature is not specified."""
    def metrics_old(R, C):    # no T parameter
        return {"fc": 1 / (2 * math.pi * R * C)}
    # Should not raise
    r = analyze(nominal_values={"R": 1e3, "C": 1e-9},
                passive_tolerances={"R": 0.01, "C": 0.05},
                metrics=metrics_old,
                spec={"fc": ("within", 0.05)},
                n_mc=200, seed=0)
    assert r.samples_total == 200


def test_analyze_corners_returns_per_corner_yield():
    """analyze_corners runs an MC at each given T (Constant sampler
    internally) and returns one YieldReport per corner plus
    aggregate worst-corner numbers."""
    from utils.tolerance import analyze_corners
    def metrics(R, T=25):
        # fc-like metric that drifts with T via tempco applied by analyze
        return {"R": R}

    report = analyze_corners(
        temperature_corners=[-40, 25, 85],
        nominal_values={"R": 1000.0},
        passive_tolerances={"R": 0.01},
        metrics=metrics,
        spec={"R": ("within", 0.01)},
        n_mc=2000, seed=0,
        temperature_coefficients={"R": 100e-6},   # 100 ppm/°C
    )
    assert len(report.corners) == 3
    Ts = [T for T, _ in report.corners]
    assert Ts == [-40, 25, 85]
    # Yield should be lowest at the corner farthest from T_nominal=25
    # (where tempco drift is largest, so spec ±1% is hardest to meet)
    yields = {T: r.yield_pct for T, r in report.corners}
    assert yields[25] >= yields[-40]
    assert yields[25] >= yields[85]
    assert report.worst_yield == min(yields.values())
    assert report.worst_corner in (-40, 85)


def test_analyze_corners_paired_seed():
    """Same seed across corners → paired comparison; per-corner
    component-perturbation patterns are identical (same RNG state
    at each corner's analyze() call)."""
    from utils.tolerance import analyze_corners
    # Capture by corner T separately. Each corner's MC calls all have
    # T equal to the corner value; the nominal call has T=25 and goes
    # into a fourth bucket.
    by_T = {}
    def metrics(R, T=25):
        by_T.setdefault(round(T, 1), []).append(R)
        return {"R": R}

    analyze_corners(
        temperature_corners=[-40, 0, 85],   # avoid T=25 to keep MC samples separate from nominal
        nominal_values={"R": 1000.0},
        passive_tolerances={"R": 0.01},
        metrics=metrics,
        spec={"R": ("<", 1e9)},
        n_mc=20, seed=42,
        temperature_coefficients={"R": 0.0},   # no tempco → identical samples
    )
    # With zero tempco + same seed, R sequences at each corner should
    # be identical (the paired-seed property)
    assert by_T[-40] == by_T[0] == by_T[85]
    assert len(by_T[-40]) == 20
    # Nominal calls (T=25) should also exist
    assert len(by_T[25]) == 3


def test_temperature_sweep_returns_corner_report():
    """temperature_sweep is just analyze_corners with many points —
    same return type, used for yield-vs-T curves."""
    from utils.tolerance import temperature_sweep
    report = temperature_sweep(
        temperature_points=range(-40, 86, 25),    # 6 points
        nominal_values={"R": 1000.0},
        passive_tolerances={"R": 0.01},
        metrics=lambda R, T=25: {"R": R},
        spec={"R": ("within", 0.01)},
        n_mc=500, seed=1,
        temperature_coefficients={"R": 100e-6},
    )
    assert len(report.corners) == 6


def test_temperature_non_sampler_raises():
    with pytest.raises(TypeError, match="Sampler"):
        analyze(
            nominal_values={"R": 1e3},
            passive_tolerances={"R": 0.01},
            metrics=lambda R, T: {"v": R},
            spec={"v": ("<", 1e9)},
            n_mc=3,
            temperature=(-40, 85),  # tuple, not Sampler
        )


# ---------- Robust ranker (eseries_opt integration) ----------

def test_robust_ranker_attaches_yield_to_results():
    """Robust ranker runs MC on each candidate and tags the Result
    with a yield_pct attribute. Sort order is descending by yield."""
    from utils.eseries_opt import Problem, Resistor, Capacitor
    from utils.tolerance import Robust

    p = Problem()
    p.add(Resistor("R", e_series=12, range=(1e3, 1e4)))
    p.add(Capacitor("C", e_series=12, range=(1e-9, 1e-7)))
    p.add_target("fc", lambda R, C: 1 / (2 * math.pi * R * C),
                 target=1591.55)

    ranker = Robust(
        passive_tolerances={"R": 0.01, "C": 0.05},
        spec={"fc": ("within", 0.05)},
        n_mc=200, seed=1,
    )
    results = p.solve(strategy="brute", n_results=5, rank=ranker)
    for c in results:
        assert hasattr(c, "yield_pct")
        assert hasattr(c, "yield_report")
        assert 0 <= c.yield_pct <= 100
    # Sorted descending by yield
    yields = [c.yield_pct for c in results]
    assert yields == sorted(yields, reverse=True)


def test_passive_tolerances_per_component_override():
    """passive_tolerances accepts full-name keys that override the
    prefix default. Lookup order: name, then prefix."""
    captured = []
    def metrics(R1, R2):
        captured.append((R1, R2))
        return {"v": R1 + R2}
    analyze(
        nominal_values={"R1": 1e3, "R2": 1e3},
        passive_tolerances={"R": 0.01, "R2": 0.10},   # R1 → 1%, R2 → 10%
        metrics=metrics,
        spec={"v": ("<", 1e9)},
        n_mc=2000, seed=10,
    )
    import numpy as np
    R1 = np.array([c[0] for c in captured[1:]])
    R2 = np.array([c[1] for c in captured[1:]])
    # R2 should have ~10× wider relative spread than R1
    assert R2.std()/R2.mean() == pytest.approx(10 * R1.std()/R1.mean(),
                                               rel=0.10)


def test_robust_ranker_unknown_spec_target_raises():
    """A spec key that doesn't match any Problem target is a typo —
    fail loudly rather than silently scoring against a missing metric."""
    from utils.eseries_opt import Problem, Resistor
    from utils.tolerance import Robust

    p = Problem()
    p.add(Resistor("R", e_series=12, range=(1e3, 1e4)))
    p.add_target("v", lambda R: R, target=4.7e3, metric="abs")
    ranker = Robust(
        passive_tolerances={"R": 0.01},
        spec={"made_up_metric": ("<", 1)},
        n_mc=10, seed=0,
    )
    with pytest.raises(ValueError, match="made_up_metric"):
        p.solve(strategy="brute", n_results=3, rank=ranker)


def test_robust_ranker_paired_seed_gives_stable_ranking():
    """Same seed across all candidates means each candidate sees the
    same component-perturbation pattern. A re-run with the same
    Problem + Robust config must produce the same ranking."""
    from utils.eseries_opt import Problem, Resistor, Capacitor
    from utils.tolerance import Robust

    def make_problem():
        p = Problem()
        p.add(Resistor("R", e_series=12, range=(1e3, 1e4)))
        p.add(Capacitor("C", e_series=12, range=(1e-9, 1e-7)))
        p.add_target("fc", lambda R, C: 1 / (2 * math.pi * R * C),
                     target=1591.55)
        return p

    rk_args = dict(passive_tolerances={"R": 0.01, "C": 0.05},
                   spec={"fc": ("within", 0.05)},
                   n_mc=500, seed=99)
    r1 = make_problem().solve(strategy="brute", n_results=5,
                              rank=Robust(**rk_args))
    r2 = make_problem().solve(strategy="brute", n_results=5,
                              rank=Robust(**rk_args))
    assert [c.values for c in r1] == [c.values for c in r2]
    assert [c.yield_pct for c in r1] == [c.yield_pct for c in r2]


def test_analyze_no_active_devices_yields_unchanged():
    """The active_devices=None path must produce the same yields as
    the pre-slice-3 API — regression check on the refactor."""
    common = dict(
        nominal_values={"R": 1e3, "C": 1e-9},
        passive_tolerances={"R": 0.01, "C": 0.05},
        metrics=lambda R, C: {"fc": 1 / (2 * math.pi * R * C)},
        spec={"fc": ("within", 0.05)},
        n_mc=500, seed=99,
    )
    r_no_active = analyze(active_devices=None, **common)
    r_default   = analyze(**common)
    assert r_no_active.samples_pass == r_default.samples_pass


# ---------- Exponential tempco ----------

def test_exponential_tempco_doubles_per_K():
    """Exponential(factor=2, per_K=10) should double the value per
    +10°C of warming above T_nominal — the bipolar Ib pattern."""
    from utils.tolerance import Exponential

    captured = []
    def metrics(Ib, T):
        captured.append((Ib, T))
        return {"v": Ib}

    analyze(
        nominal_values={"Ib": 200e-9},
        passive_tolerances={"I": 0.0},
        distribution={"Ib": Constant(value=200e-9)},
        metrics=metrics,
        spec={"v": ("<", 1)},
        n_mc=500, seed=0,
        temperature=Constant(value=85.0),     # +60°C → 6 doublings
        temperature_coefficients={"Ib": Exponential(factor=2.0, per_K=10.0)},
        temperature_nominal=25,
    )
    Ib_values = [v for v, T in captured[1:]]
    expected = 200e-9 * (2.0 ** 6)         # 12.8 µA
    assert Ib_values[0] == pytest.approx(expected, rel=1e-9)
    # All samples identical (Constant sampler + Constant T)
    assert max(Ib_values) - min(Ib_values) < 1e-15


def test_exponential_tempco_zero_at_T_nominal():
    """At T = T_nominal, factor^0 = 1, so the value is unchanged."""
    from utils.tolerance import Exponential

    captured = []
    def metrics(Ib, T):
        captured.append(Ib)
        return {"v": Ib}

    analyze(
        nominal_values={"Ib": 200e-9},
        passive_tolerances={"I": 0.0},
        distribution={"Ib": Constant(value=200e-9)},
        metrics=metrics,
        spec={"v": ("<", 1)},
        n_mc=200, seed=0,
        temperature=Constant(value=25.0),
        temperature_coefficients={"Ib": Exponential(factor=2.0, per_K=10.0)},
        temperature_nominal=25,
    )
    Ib_values = captured[1:]
    assert all(v == pytest.approx(200e-9, rel=1e-12) for v in Ib_values)


# ---------- DEVICE_TEMPCOS auto-merge ----------

def test_device_tempcos_auto_applied_for_active_devices():
    """When active_devices includes a part with library tempcos, those
    tempcos must be applied automatically without the user passing them
    via temperature_coefficients."""
    from utils.tolerance import Exponential
    from utils.tolerance.devices import DEVICE_TEMPCOS

    # Sanity: NE5532 has Ib in its tempco library
    assert "Ib" in DEVICE_TEMPCOS["NE5532"]
    assert isinstance(DEVICE_TEMPCOS["NE5532"]["Ib"], Exponential)

    captured = []
    def metrics(R1, U1_Vos, U1_Ib, U1_Avol, U1_GBW, T):
        captured.append((U1_Ib, T))
        return {"ib": U1_Ib}

    analyze(
        nominal_values={"R1": 1e3},   # placeholder; analyze requires ≥1 passive
        passive_tolerances={"R": 0.0},
        active_devices={"U1": "NE5532"},
        distribution={"U1_Vos": Constant(value=0.0),
                       "U1_Ib": Constant(value=200e-9),
                       "U1_Avol": Constant(value=1e5),
                       "U1_GBW": Constant(value=10e6)},
        metrics=metrics,
        spec={"ib": ("<", 1)},
        n_mc=200, seed=0,
        temperature=Constant(value=85.0),     # +60°C → 6 doublings
        temperature_nominal=25,
        # No temperature_coefficients passed — must come from library
    )
    Ib_values = [v for v, T in captured[1:]]
    expected = 200e-9 * (2.0 ** 6)
    assert Ib_values[0] == pytest.approx(expected, rel=1e-9)


def test_user_tempco_overrides_device_library():
    """User-supplied temperature_coefficients must override the
    DEVICE_TEMPCOS library entry for the same name."""
    from utils.tolerance import Exponential

    captured = []
    def metrics(R1, U1_Vos, U1_Ib, U1_Avol, U1_GBW, T):
        captured.append(U1_Ib)
        return {"ib": U1_Ib}

    analyze(
        nominal_values={"R1": 1e3},   # placeholder; analyze requires ≥1 passive
        passive_tolerances={"R": 0.0},
        active_devices={"U1": "NE5532"},
        distribution={"U1_Vos": Constant(value=0.0),
                       "U1_Ib": Constant(value=200e-9),
                       "U1_Avol": Constant(value=1e5),
                       "U1_GBW": Constant(value=10e6)},
        metrics=metrics,
        spec={"ib": ("<", 1)},
        n_mc=100, seed=0,
        temperature=Constant(value=85.0),
        temperature_nominal=25,
        # Override: tripling per 10°C instead of doubling
        temperature_coefficients={"U1_Ib": Exponential(factor=3.0, per_K=10.0)},
    )
    Ib_values = captured[1:]
    expected = 200e-9 * (3.0 ** 6)         # 6 tripling intervals
    assert Ib_values[0] == pytest.approx(expected, rel=1e-9)


def test_expand_active_tempcos_skips_parts_without_tempco():
    """Parts with no DEVICE_TEMPCOS entry (e.g. 2N3904 — handled
    natively by ngspice .temp) contribute nothing to the expansion."""
    from utils.tolerance.devices import expand_active_tempcos

    tcs = expand_active_tempcos({"U1": "NE5532", "Q1": "2N3904"})
    # NE5532 entries appear, 2N3904 does not
    assert "U1_Vos" in tcs
    assert "U1_Ib" in tcs
    assert "U1_Avol" in tcs
    assert "U1_GBW" in tcs
    assert not any(k.startswith("Q1_") for k in tcs)


# ---------- Linearized ranker ----------

def test_linearized_ranker_attaches_yield_to_results():
    """Linearized ranker estimates yield analytically and tags each
    Result with yield_pct, yield_per_spec, metric_sigma."""
    from utils.eseries_opt import Problem, Resistor, Capacitor
    from utils.tolerance import Linearized

    p = Problem()
    p.add(Resistor("R", e_series=12, range=(1e3, 1e4)))
    p.add(Capacitor("C", e_series=12, range=(1e-9, 1e-7)))
    p.add_target("fc", lambda R, C: 1 / (2 * math.pi * R * C),
                 target=1591.55)
    ranker = Linearized(
        passive_tolerances={"R": 0.01, "C": 0.05},
        spec={"fc": ("within", 0.05)},
    )
    results = p.solve(strategy="brute", n_results=5, rank=ranker)
    for c in results:
        assert hasattr(c, "yield_pct")
        assert hasattr(c, "yield_per_spec")
        assert hasattr(c, "metric_sigma")
        assert "fc" in c.yield_per_spec
        assert "fc" in c.metric_sigma
        assert 0 <= c.yield_pct <= 100
    assert [c.yield_pct for c in results] == \
        sorted([c.yield_pct for c in results], reverse=True)


def test_linearized_yield_matches_robust_for_smooth_metric():
    """For a smooth closed-form metric, Linearized's analytic yield
    should match Robust's MC yield within a few percentage points.
    Pick a few hand-chosen candidates and compare directly — avoids
    the tie-break ambiguity of comparing top-N lists when many
    candidates tie at high yield."""
    from utils.eseries_opt import Problem, Resistor, Capacitor
    from utils.tolerance import Linearized, Robust

    def fc(R, C):
        return 1 / (2 * math.pi * R * C)

    # Build a Problem and grab one mid-yield candidate by setting a
    # target it doesn't perfectly hit — with the wide tolerance + tight
    # spec the yield will sit somewhere in the [50, 99]% range where
    # MC vs analytic comparison is most discriminating.
    common = dict(
        passive_tolerances={"R": 0.05, "C": 0.10},   # wide
        spec={"fc": ("within", 0.05)},                # tight
    )

    p = Problem()
    p.add(Resistor("R", e_series=24, range=(1e3, 1e4)))
    p.add(Capacitor("C", e_series=24, range=(1e-9, 1e-7)))
    p.add_target("fc", fc, target=1591.55)

    lin = p.solve(strategy="brute", n_results=20,
                  rank=Linearized(**common))
    # Match Robust on the same candidates by re-using their (R, C)
    # — pull MC yield for each top-20 Linearized result.
    rob_ranker = Robust(n_mc=4000, seed=7, **common)

    class _Cand:
        def __init__(self, values, breakdown):
            self.values = values; self.breakdown = breakdown
            self.error = 0.0

    p2 = Problem()
    p2.add(Resistor("R", e_series=24, range=(1e3, 1e4)))
    p2.add(Capacitor("C", e_series=24, range=(1e-9, 1e-7)))
    p2.add_target("fc", fc, target=1591.55)
    targets = p2.targets

    cands = [_Cand(c.values, c.breakdown) for c in lin]
    rob_ranker.rank(cands, targets)
    rob_lookup = {tuple(sorted(c.values.items())): c.yield_pct
                   for c in cands}
    for c in lin:
        key = tuple(sorted(c.values.items()))
        diff = abs(c.yield_pct - rob_lookup[key])
        # ±3 pp tolerance — within MC sampling noise at n_mc=4000
        assert diff < 3.0, (
            f"Yield mismatch on {c.values}: "
            f"lin={c.yield_pct:.2f}, rob={rob_lookup[key]:.2f}"
        )


def test_linearized_unknown_spec_raises():
    """Same loud-fail behaviour as Robust on a spec typo."""
    from utils.eseries_opt import Problem, Resistor
    from utils.tolerance import Linearized

    p = Problem()
    p.add(Resistor("R", e_series=12, range=(1e3, 1e4)))
    p.add_target("v", lambda R: R, target=4.7e3, metric="abs")
    ranker = Linearized(
        passive_tolerances={"R": 0.01},
        spec={"made_up_metric": ("<", 1)},
    )
    with pytest.raises(ValueError, match="made_up_metric"):
        p.solve(strategy="brute", n_results=3, rank=ranker)


def test_linearized_eps_frac_robust_to_perturbation_size():
    """The yield ESTIMATE for one fixed candidate should match across
    reasonable eps_frac values — sanity check on the central-
    difference choice for a smooth metric."""
    from utils.tolerance import Linearized

    class _T:
        name = "fc"; weight = 1.0
        @staticmethod
        def expr(R, C):
            return 1 / (2 * math.pi * R * C)

    class _C:
        def __init__(self):
            self.values = {"R": 4.7e3, "C": 22e-9}
            self.breakdown = {"fc": 0.0}
            self.error = 0.0

    common = dict(passive_tolerances={"R": 0.05, "C": 0.10},
                   spec={"fc": ("within", 0.05)})
    yields = []
    for eps in (0.05, 0.10, 0.20):
        cand = _C()
        Linearized(eps_frac=eps, **common).rank([cand], [_T])
        yields.append(cand.yield_pct)
    # All three should match to <0.1 pp for a smooth metric
    assert max(yields) - min(yields) < 0.1, (
        f"eps_frac yield sensitivity: {yields}"
    )


def test_linearized_constant_input_contributes_zero_variance():
    """Constant samplers have σ=0 — they should be skipped in the
    perturbation loop and contribute nothing to metric variance."""
    from utils.tolerance import Linearized
    from utils.tolerance.samplers import Constant

    class FakeTarget:
        name = "v"
        weight = 1.0
        expr = staticmethod(lambda R, K: R + K)

    class FakeCandidate:
        def __init__(self):
            self.values = {"R": 1e3, "K": 5.0}
            self.breakdown = {"v": 0.0}
            self.error = 0.0

    ranker = Linearized(
        passive_tolerances={"R": 0.01},
        spec={"v": ("within", 0.05)},
        distribution={"K": Constant(value=5.0)},   # K pinned
    )
    cand = FakeCandidate()
    ranked = ranker.rank([cand], [FakeTarget])
    # K contributes zero; only R variance matters. R is 1% with default
    # tolerance_sigma=3, so σ_R ≈ 1000·0.01/3 ≈ 3.33, σ_v = σ_R = 3.33,
    # spec is ±5% of (R+K) = ±50.25 → ~15σ, ~100% yield.
    assert ranked[0].metric_sigma["v"] == pytest.approx(3.33, rel=0.10)
    assert ranked[0].yield_pct > 99.5


# ---------- thermal_dither ----------

def test_thermal_dither_computes_known_slope():
    """For a metric m(T) = a + b·T, the dither slope must equal b
    exactly (linear function → finite-difference is exact)."""
    from utils.tolerance import thermal_dither

    def metrics(R, T):
        return {"m": 10.0 + 0.05 * (T - 25)}      # slope = 0.05

    report = thermal_dither(
        nominal_values={"R": 1e3},
        passive_tolerances={"R": 0.0},
        metrics=metrics,
        spec={"m": ("<", 1e9), "m_dT": ("<", 1.0)},
        n_mc=20, seed=0,
        T_nominal=25.0, T_dither=5.0,
    )
    assert report.metric_stats["m_dT"].mean == pytest.approx(0.05, abs=1e-9)
    assert report.metric_stats["m_dT"].std == pytest.approx(0.0, abs=1e-9)


def test_thermal_dither_negative_slope_for_self_stabilizing():
    """A metric whose value falls with T (e.g., a self-stabilising
    bias) should produce negative slopes."""
    from utils.tolerance import thermal_dither

    def metrics(R, T):
        return {"m": 100.0 - 0.5 * (T - 25)}     # slope = -0.5

    report = thermal_dither(
        nominal_values={"R": 1e3},
        passive_tolerances={"R": 0.0},
        metrics=metrics,
        spec={"m_dT": ("<", 0)},     # require dropping with T
        n_mc=20, seed=0,
        T_dither=2.0,
    )
    assert report.metric_stats["m_dT"].mean == pytest.approx(-0.5, abs=1e-9)
    assert report.yield_pct == 100.0


def test_thermal_dither_distinguishes_smooth_vs_steep():
    """A spec on a `_dT` derived metric should pass for shallow-
    sensitivity designs and fail for steep ones — this is the whole
    point of the helper."""
    from utils.tolerance import thermal_dither

    # Steep slope: 5 mW/K
    def metrics_steep(R, T):
        return {"P": 0.030 + 0.005 * (T - 25)}
    # Shallow slope: 0.1 mW/K
    def metrics_shallow(R, T):
        return {"P": 0.030 + 0.0001 * (T - 25)}

    common = dict(
        nominal_values={"R": 1e3},
        passive_tolerances={"R": 0.0},
        n_mc=10, seed=0, T_dither=5.0,
        spec={"P_dT": ("<", 0.001)},   # < 1 mW/K
    )
    rep_steep = thermal_dither(metrics=metrics_steep, **common)
    rep_shallow = thermal_dither(metrics=metrics_shallow, **common)
    assert rep_steep.yield_pct == 0.0           # 5 mW/K > 1 mW/K, all fail
    assert rep_shallow.yield_pct == 100.0       # 0.1 mW/K < 1 mW/K, all pass


def test_thermal_dither_validates_T_dither():
    """Zero or negative T_dither is a usage bug."""
    from utils.tolerance import thermal_dither
    with pytest.raises(ValueError, match="T_dither"):
        thermal_dither(
            nominal_values={"R": 1e3},
            passive_tolerances={"R": 0.0},
            metrics=lambda R, T: {"m": 0},
            spec={"m": ("<", 1)},
            n_mc=5, T_dither=0,
        )
