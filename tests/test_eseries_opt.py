import os, sys, math
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import pytest

from utils.eseries_opt import (
    Problem, Resistor, Capacitor, Inductor,
    Lexicographic, Pareto,
)


# ---------- Components ----------

def test_resistor_e12_single_decade_inclusive():
    R = Resistor("R", e_series=12, range=(1e3, 1e4))
    vals = R.values()
    assert vals[0] == pytest.approx(1e3)
    assert vals[-1] == pytest.approx(1e4)
    # 12 E12 values in [1k, 8.2k] plus 10k boundary
    assert len(vals) == 13


def test_capacitor_multi_decade_sorted_and_bounded():
    C = Capacitor("C", e_series=24, range=(1e-9, 1e-7))
    vals = C.values()
    assert vals[0] == pytest.approx(1e-9)
    assert vals[-1] == pytest.approx(1e-7)
    assert all(vals[i] < vals[i + 1] for i in range(len(vals) - 1))


def test_partial_decade_range_excludes_out_of_band():
    R = Resistor("R", e_series=24, range=(2.2e3, 4.7e3))
    vals = R.values()
    assert vals.min() == pytest.approx(2.2e3)
    assert vals.max() == pytest.approx(4.7e3)
    # E24 between 2.2k and 4.7k inclusive: 2.2, 2.4, 2.7, 3.0, 3.3, 3.6, 3.9, 4.3, 4.7
    assert len(vals) == 9


def test_invalid_e_series_raises():
    with pytest.raises(ValueError):
        Resistor("R", e_series=7, range=(1, 10)).values()


# ---------- Problem construction ----------

def test_add_returns_component_and_registers_it():
    p = Problem()
    R = p.add(Resistor("R", e_series=24, range=(1e3, 1e4)))
    assert R.name == "R"
    assert len(p.components) == 1


def test_duplicate_component_name_raises():
    p = Problem()
    p.add(Resistor("R", e_series=24, range=(1e3, 1e4)))
    with pytest.raises(ValueError):
        p.add(Resistor("R", e_series=24, range=(1e3, 1e4)))


def test_solve_with_no_targets_raises():
    p = Problem()
    p.add(Resistor("R", e_series=24, range=(1e3, 1e4)))
    with pytest.raises(ValueError):
        p.solve()


def test_solve_with_no_components_raises():
    p = Problem()
    p.add_target("x", lambda: 1.0, target=1.0)
    with pytest.raises(ValueError):
        p.solve()


# ---------- BruteForce on known-optimal problems ----------

def test_brute_rc_corner_frequency_hits_exact_solution():
    """fc = 1/(2π·10k·10n) ≈ 1591.55 Hz; both 10k and 10nF are in E24."""
    p = Problem()
    p.add(Resistor("R", e_series=24, range=(1e3, 1e5)))
    p.add(Capacitor("C", e_series=24, range=(1e-9, 1e-6)))
    target = 1 / (2 * math.pi * 1e4 * 1e-8)
    p.add_target("fc", lambda R, C: 1 / (2 * math.pi * R * C), target=target)

    results = p.solve(strategy="brute", n_results=5)
    best = results[0]
    assert best.values["R"] == pytest.approx(1e4)
    assert best.values["C"] == pytest.approx(1e-8)
    assert best.error == pytest.approx(0.0, abs=1e-9)


def test_brute_diff_amp_finds_matched_gain_10():
    """R2/R1 = R4/R3 = 10 is exactly satisfied by R1=R3=1k, R2=R4=10k.
       Single-decade E24 keeps the 25^4 brute-force search tractable."""
    p = Problem()
    for n in ("R1", "R2", "R3", "R4"):
        p.add(Resistor(n, e_series=24, range=(1e3, 1e4)))
    p.add_target("gain",  lambda R1, R2, R3, R4: R2 / R1, target=10.0)
    p.add_target("match", lambda R1, R2, R3, R4: R2 / R1 - R4 / R3,
                 target=0.0, weight=100, metric="abs")

    results = p.solve(strategy="brute", n_results=5)
    best = results[0]
    assert best.values["R2"] / best.values["R1"] == pytest.approx(10.0, rel=1e-9)
    assert best.values["R4"] / best.values["R3"] == pytest.approx(10.0, rel=1e-9)


def test_results_are_sorted_ascending_by_error():
    p = Problem()
    p.add(Resistor("R", e_series=12, range=(1e3, 1e4)))
    p.add(Capacitor("C", e_series=12, range=(1e-9, 1e-7)))
    p.add_target("fc", lambda R, C: 1 / (2 * math.pi * R * C), target=1234.0)

    results = p.solve(strategy="brute", n_results=10)
    errors = [r.error for r in results]
    assert errors == sorted(errors)


def test_n_results_caps_output_length():
    p = Problem()
    p.add(Resistor("R", e_series=24, range=(1e3, 1e4)))
    p.add(Capacitor("C", e_series=24, range=(1e-9, 1e-7)))
    p.add_target("fc", lambda R, C: 1 / (2 * math.pi * R * C), target=1e3)

    results = p.solve(strategy="brute", n_results=3)
    assert len(results) == 3


def test_inductor_in_lc_resonance_problem():
    """LC tank: f0 = 1/(2π√(LC)). Verifies Inductor enumerates and composes
       with other components in a multi-component objective."""
    p = Problem()
    p.add(Inductor("L",  e_series=12, range=(1e-6, 1e-4)))
    p.add(Capacitor("C", e_series=12, range=(1e-9, 1e-7)))
    p.add_target("f0", lambda L, C: 1 / (2 * math.pi * math.sqrt(L * C)),
                 target=1e6)

    best = p.solve(strategy="brute", n_results=1)[0]
    f0 = 1 / (2 * math.pi * math.sqrt(best.values["L"] * best.values["C"]))
    assert abs(f0 - 1e6) / 1e6 < 0.05   # within 5% of 1 MHz on E12


def test_log_metric_is_symmetric_in_scale():
    """log metric = |ln(actual/target)|. When the target lies at the geometric
       mean of two adjacent E-series values, both should rank equal — unlike
       the relative-error metric, which would prefer the lower one."""
    p = Problem()
    p.add(Resistor("R", e_series=12, range=(1e3, 1e4)))
    target = math.sqrt(2.7e3 * 3.3e3)   # geometric mean of E12 neighbours
    p.add_target("v", lambda R: R, target=target, metric="log")

    results = p.solve(strategy="brute", n_results=2)
    top_two = sorted(r.values["R"] for r in results[:2])
    assert top_two[0] == pytest.approx(2.7e3)
    assert top_two[1] == pytest.approx(3.3e3)
    assert results[0].error == pytest.approx(results[1].error, rel=1e-9)
    expected = abs(math.log(2.7e3 / target))
    assert results[0].error == pytest.approx(expected, rel=1e-9)


def test_breakdown_is_populated_per_target():
    p = Problem()
    p.add(Resistor("R", e_series=12, range=(1e3, 1e4)))
    p.add_target("a", lambda R: R,     target=4.7e3, metric="abs")
    p.add_target("b", lambda R: R / 2, target=2.35e3, metric="abs")

    results = p.solve(strategy="brute", n_results=1)
    assert set(results[0].breakdown) == {"a", "b"}


# ---------- Constraints ----------

def test_constraint_filters_to_feasible_only():
    p = Problem()
    p.add(Resistor("R1", e_series=24, range=(1e3, 1e6)))
    p.add(Resistor("R2", e_series=24, range=(1e3, 1e6)))
    p.add_target("ratio", lambda R1, R2: R2 / (R1 + R2), target=0.5)
    p.add_constraint("Zout", lambda R1, R2: R1 + R2,
                     lambda z: 19e3 <= z <= 21e3)

    results = p.solve(strategy="brute", n_results=10)
    assert results, "expected at least one feasible candidate"
    for r in results:
        z = r.values["R1"] + r.values["R2"]
        assert 19e3 <= z <= 21e3


def test_no_feasible_assignment_returns_empty_list():
    p = Problem()
    p.add(Resistor("R", e_series=12, range=(1e3, 1e4)))
    p.add_target("x", lambda R: R, target=1e3)
    p.add_constraint("impossible", lambda R: R, lambda r: r > 1e9)
    assert p.solve(strategy="brute") == []


# ---------- WeightedSum ranking (default) ----------

def test_higher_weight_dominates_choice():
    """Both targets are independently optimisable; the heavier weight wins
       when only one component can hit its target exactly per call."""
    p = Problem()
    p.add(Resistor("R",  e_series=12, range=(1e3, 1e4)))
    p.add(Capacitor("C", e_series=12, range=(1e-9, 1e-7)))
    p.add_target("a", lambda R, C: R, target=1e4,  weight=1)
    p.add_target("b", lambda R, C: C, target=1e-7, weight=1000)

    best = p.solve(strategy="brute", n_results=1)[0]
    assert best.values["C"] == pytest.approx(1e-7)


# ---------- Sensitivity ----------

def test_sensitivity_zero_when_disabled():
    p = Problem()
    p.add(Resistor("R", e_series=24, range=(1e3, 1e4)))
    p.add_target("v", lambda R: R, target=4.7e3, metric="abs")
    results = p.solve(strategy="brute", sensitivity_tol=None, n_results=3)
    assert all(r.sensitivity == 0.0 for r in results)


def test_sensitivity_nonnegative_when_enabled():
    p = Problem()
    p.add(Resistor("R",  e_series=24, range=(1e3, 1e4)))
    p.add(Capacitor("C", e_series=24, range=(1e-9, 1e-7)))
    p.add_target("fc", lambda R, C: 1 / (2 * math.pi * R * C), target=1e3)
    results = p.solve(strategy="brute", sensitivity_tol=0.01, n_results=3)
    for r in results:
        assert r.sensitivity >= 0


# ---------- Auto-dispatch ----------

def test_auto_dispatch_works_for_small_problems():
    p = Problem()
    p.add(Resistor("R",  e_series=12, range=(1e3, 1e4)))
    p.add(Capacitor("C", e_series=12, range=(1e-9, 1e-7)))
    p.add_target("fc", lambda R, C: 1 / (2 * math.pi * R * C), target=1e3)
    results = p.solve(n_results=1)   # strategy unspecified
    assert len(results) == 1


# ---------- Stubbed strategies / rankings ----------
# These exercise the API surface but the underlying implementation is deferred.
# Marked strict=True so they fail loudly the moment the implementation lands
# without removing the marker.

@pytest.mark.xfail(raises=NotImplementedError, strict=True,
                   reason="BranchAndBound deferred")
def test_branch_and_bound_solves_simple_problem():
    p = Problem()
    p.add(Resistor("R", e_series=12, range=(1e3, 1e4)))
    p.add_target("v", lambda R: R, target=4.7e3, metric="abs")
    p.solve(strategy="bnb")


@pytest.mark.xfail(raises=NotImplementedError, strict=True,
                   reason="RelaxAndSnap deferred")
def test_relax_and_snap_solves_simple_problem():
    p = Problem()
    p.add(Resistor("R", e_series=12, range=(1e3, 1e4)))
    p.add_target("v", lambda R: R, target=4.7e3, metric="abs")
    p.solve(strategy="relax")


@pytest.mark.xfail(raises=NotImplementedError, strict=True,
                   reason="FactorOne deferred")
def test_factor_one_solves_two_component_rc():
    p = Problem()
    p.add(Resistor("R",  e_series=96, range=(1e3, 1e5)))
    p.add(Capacitor("C", e_series=24, range=(1e-9, 1e-6)))
    p.add_target("fc", lambda R, C: 1 / (2 * math.pi * R * C), target=1234.0)
    p.solve(strategy="factor")


@pytest.mark.xfail(raises=NotImplementedError, strict=True,
                   reason="Lexicographic ranking deferred")
def test_lexicographic_orders_by_priority():
    p = Problem()
    p.add(Resistor("R1", e_series=24, range=(1e3, 1e4)))
    p.add(Resistor("R2", e_series=24, range=(1e3, 1e4)))
    p.add_target("primary",   lambda R1, R2: R1, target=2.2e3, metric="abs")
    p.add_target("secondary", lambda R1, R2: R2, target=4.7e3, metric="abs")
    p.solve(strategy="brute", rank=Lexicographic(["primary", "secondary"]))


@pytest.mark.xfail(raises=NotImplementedError, strict=True,
                   reason="Pareto ranking deferred")
def test_pareto_returns_only_nondominated():
    p = Problem()
    p.add(Resistor("R1", e_series=12, range=(1e3, 1e5)))
    p.add(Resistor("R2", e_series=12, range=(1e3, 1e5)))
    p.add_target("ratio", lambda R1, R2: R2 / R1, target=10.0)
    p.add_target("Zin",   lambda R1, R2: R1 + R2, target=10e3)
    p.solve(strategy="brute", rank=Pareto())
