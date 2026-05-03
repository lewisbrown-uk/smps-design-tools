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
