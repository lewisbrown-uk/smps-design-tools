import os, sys, math
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import pytest

from utils.eseries_opt import (
    Problem, Resistor, Capacitor, Inductor,
    Lexicographic, Pareto, FactorOne, BruteForce, RelaxAndSnap,
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

def test_constraint_range_filters_to_feasible_only():
    """range=(lo, hi) shortcut: equivalent to predicate=lambda z: lo<=z<=hi
       with an auto-generated bounder."""
    p = Problem()
    p.add(Resistor("R1", e_series=24, range=(1e3, 1e6)))
    p.add(Resistor("R2", e_series=24, range=(1e3, 1e6)))
    p.add_target("ratio", lambda R1, R2: R2 / (R1 + R2), target=0.5)
    p.add_constraint("Zout", lambda R1, R2: R1 + R2, range=(19e3, 21e3))

    results = p.solve(strategy="brute", n_results=10)
    assert results, "expected at least one feasible candidate"
    for r in results:
        z = r.values["R1"] + r.values["R2"]
        assert 19e3 <= z <= 21e3


def test_constraint_explicit_predicate_still_supported():
    """predicate= is the escape hatch for non-range checks (half-open
       intervals, set membership, multi-variate conditions)."""
    p = Problem()
    p.add(Resistor("R", e_series=12, range=(1e3, 1e4)))
    p.add_target("x", lambda R: R, target=1e3)
    p.add_constraint("impossible", lambda R: R, predicate=lambda r: r > 1e9)
    assert p.solve(strategy="brute") == []


def test_constraint_range_works_in_vectorised_mode():
    """range= predicates use bitwise & so they broadcast under
       BruteForce(vectorise=True). Chained-comparison user predicates
       would trip 'truth value of an array is ambiguous' here."""
    p = Problem()
    p.add(Resistor("R1", e_series=24, range=(1e3, 1e4)))
    p.add(Resistor("R2", e_series=24, range=(1e3, 1e4)))
    p.add_target("ratio", lambda R1, R2: R2 / (R1 + R2), target=0.5)
    p.add_constraint("Zout", lambda R1, R2: R1 + R2, range=(15e3, 18e3))

    results = p.solve(strategy=BruteForce(vectorise=True), n_results=5)
    assert results
    for r in results:
        z = r.values["R1"] + r.values["R2"]
        assert 15e3 <= z <= 18e3


def test_constraint_auto_bounder_tight_on_monotonic_expression():
    """Corner evaluation is tight (and sound) when the expression is
       monotonic in each free variable. Sum-of-resistances is the
       canonical case; the bound equals the true min/max over the box."""
    p = Problem()
    p.add(Resistor("R1", e_series=24, range=(1e3, 1e4)))
    p.add(Resistor("R2", e_series=24, range=(1e3, 1e4)))
    p.add_constraint("Zout", lambda R1, R2: R1 + R2, range=(15e3, 25e3))

    con = p.constraints[0]
    # Both free: sum spans (1k+1k, 10k+10k)
    lo, hi = con.bounder({}, {"R1": (1e3, 1e4), "R2": (1e3, 1e4)})
    assert lo == pytest.approx(2e3)
    assert hi == pytest.approx(20e3)
    # R1 fixed, R2 free
    lo, hi = con.bounder({"R1": 5e3}, {"R2": (1e3, 1e4)})
    assert lo == pytest.approx(6e3)
    assert hi == pytest.approx(15e3)
    # All fixed: degenerate point
    lo, hi = con.bounder({"R1": 4e3, "R2": 6e3}, {})
    assert lo == hi == pytest.approx(10e3)


def test_constraint_explicit_bounder_overrides_auto():
    """User-supplied bounder= takes priority over the auto-generated one."""
    user_bounder = lambda fixed, free: (-1.0, 1.0)
    p = Problem()
    p.add(Resistor("R", e_series=12, range=(1e3, 1e4)))
    p.add_constraint("z", lambda R: R, range=(1e3, 1e4),
                     bounder=user_bounder)

    assert p.constraints[0].bounder is user_bounder


def test_constraint_predicate_path_leaves_bounder_none():
    """Without range= or explicit bounder=, B&B has no info to prune;
       Constraint.bounder stays None to signal that."""
    p = Problem()
    p.add(Resistor("R", e_series=12, range=(1e3, 1e4)))
    p.add_constraint("z", lambda R: R, predicate=lambda r: r > 5e3)
    assert p.constraints[0].bounder is None


def test_constraint_requires_range_or_predicate():
    """add_constraint without either form must raise — ambiguous intent."""
    p = Problem()
    p.add(Resistor("R", e_series=12, range=(1e3, 1e4)))
    with pytest.raises(ValueError, match="range.*predicate"):
        p.add_constraint("z", lambda R: R)


def test_constraint_range_and_predicate_together_raises():
    """Specifying both is ambiguous — pick one."""
    p = Problem()
    p.add(Resistor("R", e_series=12, range=(1e3, 1e4)))
    with pytest.raises(ValueError, match="range= or predicate="):
        p.add_constraint("z", lambda R: R,
                         predicate=lambda r: True, range=(0, 1e9))


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


# ---------- BruteForce vectorise flag ----------

def test_brute_force_scalar_accepts_math_module_lambdas():
    """Default vectorise=False mode handles lambdas using math.sqrt /
       math.log / chained comparisons — anything Python evaluates per cell."""
    p = Problem()
    p.add(Inductor("L",  e_series=12, range=(1e-6, 1e-4)))
    p.add(Capacitor("C", e_series=12, range=(1e-9, 1e-7)))
    p.add_target("f0", lambda L, C: 1 / (2 * math.pi * math.sqrt(L * C)),
                 target=1e6)

    best = p.solve(strategy=BruteForce(vectorise=False), n_results=1)[0]
    f0 = 1 / (2 * math.pi * math.sqrt(best.values["L"] * best.values["C"]))
    assert abs(f0 - 1e6) / 1e6 < 0.05


def test_brute_force_scalar_rejects_oversize_problem():
    """Hard cap protects against accidental hours-long brute-force runs."""
    p = Problem()
    for n in ("R1", "R2", "R3", "R4", "R5"):
        p.add(Resistor(n, e_series=96, range=(1e3, 1e5)))   # 193^5 ~ 268B
    p.add_target("dummy",
                 lambda R1, R2, R3, R4, R5: R1 + R2 + R3 + R4 + R5,
                 target=5e4, metric="abs")

    with pytest.raises(ValueError, match="too large"):
        p.solve(strategy=BruteForce(vectorise=False), n_results=1)


def test_brute_force_vectorised_matches_scalar():
    """vectorise=True must produce the same top result as the scalar path
       for arithmetic-only lambdas. Constrained to single decades on both
       components so the optimum is unique — multi-decade RC has tied
       solutions (e.g. 3.3k×39n ≡ 39k×3.3n) that the two iteration orders
       break differently."""
    def make():
        p = Problem()
        p.add(Resistor("R",  e_series=24, range=(1e3, 1e4)))
        p.add(Capacitor("C", e_series=24, range=(1e-9, 1e-8)))
        target = 1 / (2 * math.pi * 1e4 * 1e-8)   # uniquely hit by 10k+10n
        p.add_target("fc", lambda R, C: 1 / (2 * math.pi * R * C),
                     target=target)
        return p

    scalar = make().solve(strategy=BruteForce(vectorise=False), n_results=1)[0]
    vec    = make().solve(strategy=BruteForce(vectorise=True),  n_results=1)[0]

    assert vec.values["R"] == pytest.approx(scalar.values["R"])
    assert vec.values["C"] == pytest.approx(scalar.values["C"])
    assert vec.error == pytest.approx(scalar.error, rel=1e-9)


def test_brute_force_vectorised_rejects_math_module_lambda():
    """vectorise=True with math.sqrt should raise a clear error pointing
       the user to np.sqrt or vectorise=False, not the raw numpy
       'must be real number, not ndarray' message."""
    p = Problem()
    p.add(Inductor("L",  e_series=12, range=(1e-6, 1e-4)))
    p.add(Capacitor("C", e_series=12, range=(1e-9, 1e-7)))
    p.add_target("f0", lambda L, C: 1 / (2 * math.pi * math.sqrt(L * C)),
                 target=1e6)

    with pytest.raises(TypeError) as exc_info:
        p.solve(strategy=BruteForce(vectorise=True), n_results=1)
    msg = str(exc_info.value)
    assert "numpy" in msg
    assert "vectorise=False" in msg


# ---------- Stubbed strategies / rankings ----------
# These exercise the API surface but the underlying implementation is deferred.
# Marked strict=True so they fail loudly the moment the implementation lands
# without removing the marker.

# ---------- BranchAndBound ----------

def test_branch_and_bound_finds_exact_solution():
    """Single-component, target on E-series: B&B finds it exactly."""
    p = Problem()
    p.add(Resistor("R", e_series=12, range=(1e3, 1e4)))
    p.add_target("v", lambda R: R, target=4.7e3, metric="abs")
    best = p.solve(strategy="bnb", n_results=1)[0]
    assert best.values["R"] == pytest.approx(4.7e3)
    assert best.error == pytest.approx(0.0)


def test_branch_and_bound_matches_brute_force_on_unique_optimum():
    """Two-component RC with unique optimum (R=10k, C=10n at corner of
       single-decade box). B&B's auto-bounders should let it agree with
       BruteForce on the global optimum."""
    def make():
        p = Problem()
        p.add(Resistor("R",  e_series=24, range=(1e3, 1e4)))
        p.add(Capacitor("C", e_series=24, range=(1e-9, 1e-8)))
        target = 1 / (2 * math.pi * 1e4 * 1e-8)
        p.add_target("fc", lambda R, C: 1 / (2 * math.pi * R * C),
                     target=target)
        return p

    brute = make().solve(strategy="brute", n_results=1)[0]
    bnb   = make().solve(strategy="bnb",   n_results=1)[0]
    assert bnb.values["R"] == pytest.approx(brute.values["R"])
    assert bnb.values["C"] == pytest.approx(brute.values["C"])
    assert bnb.error == pytest.approx(brute.error, abs=1e-9)


def test_branch_and_bound_honours_range_constraint():
    """B&B prunes subtrees where the constraint's value range can't
       overlap the accepting band, then verifies feasibility at leaves."""
    p = Problem()
    p.add(Resistor("R1", e_series=24, range=(1e3, 1e4)))
    p.add(Resistor("R2", e_series=24, range=(1e3, 1e4)))
    p.add_target("ratio", lambda R1, R2: R2 / (R1 + R2), target=0.5)
    p.add_constraint("Zout", lambda R1, R2: R1 + R2, range=(15e3, 18e3))

    results = p.solve(strategy="bnb", n_results=5)
    assert results
    for r in results:
        z = r.values["R1"] + r.values["R2"]
        assert 15e3 <= z <= 18e3


def test_branch_and_bound_rejects_non_weighted_sum_ranker():
    """B&B's lower-bound mechanism assumes a sum-of-weighted-errors
       composite — Lex/Pareto don't fit that contract."""
    p = Problem()
    p.add(Resistor("R", e_series=12, range=(1e3, 1e4)))
    p.add_target("v", lambda R: R, target=4.7e3, metric="abs")
    with pytest.raises(ValueError, match="WeightedSum"):
        p.solve(strategy="bnb", rank=Pareto())


def test_target_auto_bounder_set_by_default():
    """add_target without bounder= auto-generates a corner bounder so
       B&B has pruning info on every target by default."""
    p = Problem()
    p.add(Resistor("R", e_series=12, range=(1e3, 1e4)))
    p.add_target("v", lambda R: R, target=4.7e3, metric="abs")
    assert p.targets[0].bounder is not None
    # Verify it computes correctly: R ∈ [1k, 10k] gives bound (1k, 10k)
    lo, hi = p.targets[0].bounder({}, {"R": (1e3, 1e4)})
    assert lo == pytest.approx(1e3)
    assert hi == pytest.approx(1e4)


def test_target_explicit_bounder_preserved():
    """User-supplied bounder= overrides the auto-generated one."""
    user_bounder = lambda fixed, free: (0.0, 0.0)
    p = Problem()
    p.add(Resistor("R", e_series=12, range=(1e3, 1e4)))
    p.add_target("v", lambda R: R, target=4.7e3, metric="abs",
                 bounder=user_bounder)
    assert p.targets[0].bounder is user_bounder


def test_relax_and_snap_single_component_finds_nearest_e_series():
    """Continuous optimum equals the target; snap to the nearest E-series."""
    p = Problem()
    p.add(Resistor("R", e_series=24, range=(1e3, 1e4)))
    p.add_target("v", lambda R: R, target=4.7e3, metric="abs")
    best = p.solve(strategy=RelaxAndSnap(), n_results=1)[0]
    assert best.values["R"] == pytest.approx(4.7e3)


def test_relax_and_snap_matches_brute_force_on_unique_optimum():
    """Both strategies should find (10k, 10n) on a single-decade RC where
       the constant-fc curve only touches the box at the corner."""
    def make():
        p = Problem()
        p.add(Resistor("R",  e_series=24, range=(1e3, 1e4)))
        p.add(Capacitor("C", e_series=24, range=(1e-9, 1e-8)))
        target = 1 / (2 * math.pi * 1e4 * 1e-8)
        p.add_target("fc", lambda R, C: 1 / (2 * math.pi * R * C),
                     target=target)
        return p

    brute = make().solve(strategy="brute", n_results=1)[0]
    relax = make().solve(strategy=RelaxAndSnap(), n_results=1)[0]

    assert relax.values["R"] == pytest.approx(brute.values["R"])
    assert relax.values["C"] == pytest.approx(brute.values["C"])
    assert relax.error == pytest.approx(brute.error, abs=1e-9)


def test_relax_and_snap_handles_problem_too_big_for_brute():
    """4-component E96 over 4 decades is ~21B candidates, well past the
       BruteForce hard cap. Auto-dispatch should pick RelaxAndSnap and
       return a result. Optimality is not guaranteed (the snap K-neighbourhood
       may exclude the true discrete optimum); this test exercises the
       pipeline, not the quality."""
    p = Problem()
    for n in ("R1", "R2", "R3", "R4"):
        p.add(Resistor(n, e_series=96, range=(1e3, 1e6)))
    p.add_target("sum",
                 lambda R1, R2, R3, R4: R1 + R2 + R3 + R4,
                 target=4e4, metric="abs")

    results = p.solve(n_results=1)   # auto-dispatch -> RelaxAndSnap
    assert len(results) == 1
    s = sum(results[0].values.values())
    # Loose: continuous solver lands on the sum=4e4 hyperplane and snap
    # finds something within an E-series-spacing's worth of the optimum.
    assert s == pytest.approx(4e4, rel=0.1)


def test_factor_one_finds_exact_solution():
    """fc = 1/(2π·10k·10n) ≈ 1591.55 Hz; FactorOne should snap C to 10nF
       given R=10k and find error=0."""
    p = Problem()
    p.add(Resistor("R",  e_series=24, range=(1e3, 1e5)))
    p.add(Capacitor("C", e_series=24, range=(1e-9, 1e-6)))
    target = 1 / (2 * math.pi * 1e4 * 1e-8)
    p.add_target("fc", lambda R, C: 1 / (2 * math.pi * R * C), target=target)

    factor = FactorOne(
        pivot="C", target="fc",
        solver=lambda fc, R: 1 / (2 * math.pi * R * fc),
    )
    best = p.solve(strategy=factor, n_results=1)[0]
    assert best.values["R"] == pytest.approx(1e4)
    assert best.values["C"] == pytest.approx(1e-8)
    assert best.error == pytest.approx(0.0, abs=1e-9)


def test_factor_one_matches_brute_force_on_single_target():
    """FactorOne is exact for single-target problems with a monotonic pivot.
       Should agree with BruteForce on the global optimum."""
    def make():
        p = Problem()
        p.add(Resistor("R",  e_series=24, range=(1e3, 1e5)))
        p.add(Capacitor("C", e_series=12, range=(1e-9, 1e-6)))
        p.add_target("fc", lambda R, C: 1 / (2 * math.pi * R * C),
                     target=1234.0)
        return p

    brute = make().solve(strategy="brute", n_results=1)[0]

    factor = FactorOne(
        pivot="C", target="fc",
        solver=lambda fc, R: 1 / (2 * math.pi * R * fc),
    )
    factor_best = make().solve(strategy=factor, n_results=1)[0]

    assert factor_best.values["R"] == pytest.approx(brute.values["R"])
    assert factor_best.values["C"] == pytest.approx(brute.values["C"])


def test_factor_one_unknown_pivot_raises():
    p = Problem()
    p.add(Resistor("R",  e_series=12, range=(1e3, 1e4)))
    p.add(Capacitor("C", e_series=12, range=(1e-9, 1e-7)))
    p.add_target("fc", lambda R, C: 1 / (2 * math.pi * R * C), target=1e3)

    factor = FactorOne(pivot="X", target="fc",
                       solver=lambda fc, R: 1 / (2 * math.pi * R * fc))
    with pytest.raises(ValueError, match="pivot"):
        p.solve(strategy=factor)


# ---------- Lexicographic ranking ----------

def test_lexicographic_strict_orders_by_priority():
    """Strict lex (epsilon=0): every primary-tied candidate ranks above
       any candidate with worse primary, regardless of secondary.
       Distinguishing case: WeightedSum would prefer a primary-suboptimal
       candidate that hits secondary perfectly, lex would not."""
    def make():
        p = Problem()
        p.add(Resistor("R1", e_series=24, range=(1e3, 1e4)))
        p.add(Resistor("R2", e_series=24, range=(1e3, 1e4)))
        p.add_target("primary",   lambda R1, R2: R1,
                     target=2.2e3, metric="abs")
        p.add_target("secondary", lambda R1, R2: R2,
                     target=4.7e3, metric="abs")
        return p

    lex = make().solve(strategy="brute",
                       rank=Lexicographic(["primary", "secondary"]),
                       n_results=5)
    ws  = make().solve(strategy="brute", n_results=5)

    # Both pick (2.2k, 4.7k) at the top — error 0 on both targets.
    assert lex[0].values["R1"] == pytest.approx(2.2e3)
    assert lex[0].values["R2"] == pytest.approx(4.7e3)
    assert ws[0].values["R1"]  == pytest.approx(2.2e3)
    assert ws[0].values["R2"]  == pytest.approx(4.7e3)

    # Lex's #2 stays in the primary-perfect band (R1=2.2k, R2 next-best).
    assert lex[1].breakdown["primary"] == pytest.approx(0.0)

    # WS's #2 sacrifices primary to keep secondary perfect: any (R1!=2.2k,
    # R2=4.7k) is total error 200 < (2.2k, R2 next-best) at total 400.
    assert ws[1].breakdown["primary"] > 0.0
    assert ws[1].breakdown["secondary"] == pytest.approx(0.0)


def test_lexicographic_epsilon_widens_tie_band():
    """With epsilon > 0, candidates within epsilon of the best primary
       error are tied and resolved by secondary. Target lies between two
       E-series values so the primary-best is genuinely tied."""
    p = Problem()
    p.add(Resistor("R1", e_series=24, range=(1e3, 1e4)))
    p.add(Resistor("R2", e_series=24, range=(1e3, 1e4)))
    # 2.3k lies between E24's 2.2k and 2.4k (both primary error 100).
    p.add_target("primary",   lambda R1, R2: R1, target=2.3e3, metric="abs")
    p.add_target("secondary", lambda R1, R2: R2, target=4.7e3, metric="abs")

    # epsilon=200: tie band [100, 300] includes R1 in {2k, 2.2k, 2.4k}.
    # Within that band the secondary resolves to R2=4.7k for all three.
    lex = p.solve(strategy="brute",
                  rank=Lexicographic(["primary", "secondary"], epsilon=200),
                  n_results=3)
    for r in lex:
        assert r.values["R2"] == pytest.approx(4.7e3)


def test_lexicographic_unknown_target_raises():
    p = Problem()
    p.add(Resistor("R", e_series=12, range=(1e3, 1e4)))
    p.add_target("a", lambda R: R, target=4.7e3, metric="abs")
    with pytest.raises(ValueError, match="unknown target"):
        p.solve(strategy="brute", rank=Lexicographic(["a", "missing"]))


# ---------- Pareto ranking ----------

def test_pareto_returns_only_nondominated_candidates():
    """No candidate in the returned set may strictly dominate another."""
    p = Problem()
    p.add(Resistor("R1", e_series=12, range=(1e3, 1e5)))
    p.add(Resistor("R2", e_series=12, range=(1e3, 1e5)))
    p.add_target("ratio", lambda R1, R2: R2 / R1, target=10.0)
    p.add_target("Zin",   lambda R1, R2: R1 + R2, target=10e3)

    results = p.solve(strategy="brute", rank=Pareto(), n_results=50)
    assert results, "Pareto front should not be empty"

    for i, ri in enumerate(results):
        for j, rj in enumerate(results):
            if i == j:
                continue
            no_worse_all = all(rj.breakdown[k] <= ri.breakdown[k]
                               for k in ri.breakdown)
            strictly_better_one = any(rj.breakdown[k] < ri.breakdown[k]
                                      for k in ri.breakdown)
            assert not (no_worse_all and strictly_better_one), \
                f"{rj.values} dominates {ri.values}"


def test_pareto_filters_out_most_of_full_set():
    """The Pareto front of a 2-target problem is a curve in error space,
       so it should be much smaller than the full 625-candidate grid."""
    p = Problem()
    p.add(Resistor("R1", e_series=12, range=(1e3, 1e5)))
    p.add(Resistor("R2", e_series=12, range=(1e3, 1e5)))
    p.add_target("ratio", lambda R1, R2: R2 / R1, target=10.0)
    p.add_target("Zin",   lambda R1, R2: R1 + R2, target=10e3)

    full = p.solve(strategy="brute", n_results=10000)
    front = p.solve(strategy="brute", rank=Pareto(), n_results=10000)
    assert 0 < len(front) < len(full) // 5


def test_pareto_includes_each_targets_solo_optimum():
    """The candidate that minimises one target alone is always on the
       Pareto front — nothing dominates it on its perfect axis."""
    p = Problem()
    p.add(Resistor("R1", e_series=12, range=(1e3, 1e5)))
    p.add(Resistor("R2", e_series=12, range=(1e3, 1e5)))
    p.add_target("ratio", lambda R1, R2: R2 / R1, target=10.0)
    p.add_target("Zin",   lambda R1, R2: R1 + R2, target=10e3)

    front = p.solve(strategy="brute", rank=Pareto(), n_results=100)
    # ratio=10 hit exactly by many pairs (1k,10k), (1.2k,12k), ...
    assert any(r.breakdown["ratio"] == pytest.approx(0.0) for r in front)
    # Zin=10k hit by e.g. (1k+8.2k+...) — let's just check some pair
    # achieves zero or near-zero Zin error.
    min_zin_err = min(r.breakdown["Zin"] for r in front)
    assert min_zin_err < 100   # < 1% of 10k
