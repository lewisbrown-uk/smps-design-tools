"""Tests for the ngspice backend.

Skipped automatically if the ``ngspice`` binary isn't on PATH — these
tests need a real simulator, not a mock. Each test runs at most a few
ngspice invocations to keep the suite fast.
"""
import math
import os
import shutil
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import pytest

pytestmark = pytest.mark.skipif(
    shutil.which("ngspice") is None, reason="ngspice not installed"
)

from utils.tolerance import NgspiceBackend, CachedBackend, analyze


# AC sweep on a single-pole RC LP. .meas must live inside a .control
# block in modern ngspice for the vdb()/vm() functions to resolve;
# this is the canonical pattern the tests reuse.
RC_TEMPLATE = """* RC LP
V1 in 0 AC 1
R1 in out {R}
C1 out 0 {C}
.control
ac dec 200 1 1Meg
meas ac fc when vdb(out)=-3
.endc
.end
"""


def test_ngspice_backend_returns_meas_values():
    """fc of a 1k/1n RC LP is 1/(2π·RC) ≈ 159.155 kHz. Allow ~1%
    relative error from .meas linear interpolation between AC sweep
    points (200 pts/decade)."""
    backend = NgspiceBackend(template=RC_TEMPLATE, outputs=["fc"])
    out = backend(R=1e3, C=1e-9)
    fc_expected = 1 / (2 * math.pi * 1e3 * 1e-9)
    assert out["fc"] == pytest.approx(fc_expected, rel=0.01)


def test_ngspice_backend_callable_template():
    """Callable template form: full Python expressivity in case the
    netlist structure depends on values (cascade depth, conditional
    stages, etc.). Same RC, same expected result."""
    def template(R, C):
        return RC_TEMPLATE.format(R=R, C=C)

    backend = NgspiceBackend(template=template, outputs=["fc"])
    out = backend(R=1e3, C=1e-9)
    fc_expected = 1 / (2 * math.pi * 1e3 * 1e-9)
    assert out["fc"] == pytest.approx(fc_expected, rel=0.01)


def test_ngspice_meas_failure_returns_nan():
    """If a .meas trigger condition can't be satisfied (here, a -100 dB
    crossing on a -20 dB/dec rolloff that never reaches that depth in
    the swept range), ngspice prints 'failed' for the measurement.
    Backend reports it as NaN — propagates through analyze as a
    sample-level failure, not a hard error."""
    template = """* trigger that won't fire in the swept range
V1 in 0 AC 1
R1 in out 1k
C1 out 0 1n
.control
ac dec 10 1 100
meas ac fc when vdb(out)=-100
.endc
.end
"""
    backend = NgspiceBackend(template=template, outputs=["fc"])
    out = backend()
    assert math.isnan(out["fc"])


def test_ngspice_unknown_output_returns_nan():
    """Asking for a .meas name that isn't in the netlist returns NaN
    rather than raising. Lets the user keep a stable output list
    across template variants without conditional bookkeeping."""
    backend = NgspiceBackend(template=RC_TEMPLATE,
                             outputs=["fc", "nonsense"])
    out = backend(R=1e3, C=1e-9)
    assert not math.isnan(out["fc"])
    assert math.isnan(out["nonsense"])


def test_ngspice_template_syntax_error_raises():
    """Bad netlist (no recognisable circuit, no .meas) → loud failure,
    not silent NaN. Distinguished from one-off convergence failures
    by the absence of any parseable .meas output: a one-off failure
    typically still parses something; a template error parses nothing."""
    backend = NgspiceBackend(
        template="this is not a netlist at all",
        outputs=["fc"],
    )
    with pytest.raises(RuntimeError, match="ngspice"):
        backend()


def test_workers_speedup_with_ngspice_backend():
    """ngspice runs in a subprocess, releasing the GIL during the wait.
    workers > 1 should therefore give a meaningful wall-clock speedup
    even though Python threads (not processes) are doing the dispatch.
    Threshold is conservative — we assert > 1.5× on 4 workers, which
    leaves headroom for thread-startup overhead and is well below the
    theoretical 4× ceiling. The point is to catch a regression where
    parallelism is silently broken, not to pin down the exact factor."""
    import time

    backend = NgspiceBackend(template=RC_TEMPLATE, outputs=["fc"])
    common = dict(
        nominal_values={"R": 1e3, "C": 1e-9},
        passive_tolerances={"R": 0.01, "C": 0.05},
        metrics=backend,
        spec={"fc": ("within", 0.05)},
        n_mc=40, seed=400,
    )
    t0 = time.perf_counter(); serial = analyze(workers=1, **common)
    t_serial = time.perf_counter() - t0

    t0 = time.perf_counter(); parallel = analyze(workers=4, **common)
    t_parallel = time.perf_counter() - t0

    # Determinism: same MC samples → same metric distribution either way
    assert parallel.samples_pass == serial.samples_pass

    # Speedup: at minimum 1.5× on 4 workers (real number is usually 3-4×
    # but the floor catches "parallelism silently broken")
    assert t_serial / t_parallel > 1.5, (
        f"expected > 1.5× speedup, got {t_serial/t_parallel:.2f}× "
        f"(serial={t_serial:.2f}s, parallel={t_parallel:.2f}s)"
    )


def test_cached_ngspice_persists_across_runs(tmp_path):
    """Run a small MC twice with a persistent cache; the second run
    must serve every sample from disk and finish much faster than
    the cache-warming run. End-to-end check that the headline payoff
    of the slice — re-running a sweep is near-instant — actually works."""
    import time

    db = tmp_path / "ngspice_cache.sqlite"
    backend = NgspiceBackend(template=RC_TEMPLATE, outputs=["fc"])
    common = dict(
        nominal_values={"R": 1e3, "C": 1e-9},
        passive_tolerances={"R": 0.01, "C": 0.05},
        spec={"fc": ("within", 0.05)},
        n_mc=30, seed=600, workers=4,
    )

    # n_mc samples + 1 nominal-evaluation done by analyze() up-front
    expected_calls = common["n_mc"] + 1

    cached1 = CachedBackend(backend, path=db)
    t0 = time.perf_counter()
    r1 = analyze(metrics=cached1, **common)
    t_cold = time.perf_counter() - t0
    assert cached1.misses == expected_calls and cached1.hits == 0
    cached1.close()

    cached2 = CachedBackend(NgspiceBackend(template=RC_TEMPLATE,
                                           outputs=["fc"]), path=db)
    t0 = time.perf_counter()
    r2 = analyze(metrics=cached2, **common)
    t_warm = time.perf_counter() - t0
    cached2.close()

    assert cached2.hits == expected_calls and cached2.misses == 0
    assert r1.samples_pass == r2.samples_pass
    # Warm cache should be at least 5× faster than cold (typically
    # 50-100×; threshold is conservative to avoid flaky CI)
    assert t_cold / t_warm > 5, (
        f"expected cache to give >5× speedup, got {t_cold/t_warm:.1f}× "
        f"(cold={t_cold:.2f}s, warm={t_warm:.2f}s)"
    )


def test_analyze_with_ngspice_backend_matches_closed_form_yield():
    """End-to-end: identical seed + same nominal/tolerances on the RC
    LP, run once with the closed-form metric and once with ngspice.
    Pass counts should be very close — they're computing the same
    quantity to within ngspice's interpolation accuracy. The 50-sample
    run keeps the ngspice end of the test under a couple of seconds."""
    backend = NgspiceBackend(template=RC_TEMPLATE, outputs=["fc"])

    common = dict(
        nominal_values={"R": 1e3, "C": 1e-9},
        passive_tolerances={"R": 0.01, "C": 0.05},
        spec={"fc": ("within", 0.05)},
        n_mc=50, seed=200,
    )
    closed_form = analyze(
        metrics=lambda R, C: {"fc": 1 / (2 * math.pi * R * C)},
        **common,
    )
    ng = analyze(metrics=backend, **common)

    # Same RNG → same component samples. fc differs only by ngspice's
    # interpolation error (~0.2-1%); on a within-5% spec that error
    # rarely flips a sample's pass/fail. Allow a few-sample discrepancy.
    assert abs(ng.samples_pass - closed_form.samples_pass) <= 3
    # And the metric distributions should track each other closely.
    assert ng.metric_stats["fc"].mean == pytest.approx(
        closed_form.metric_stats["fc"].mean, rel=0.01
    )
