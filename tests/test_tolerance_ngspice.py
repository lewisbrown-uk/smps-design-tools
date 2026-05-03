"""Tests for the local ngspice backend.

Fully stubbed — every external call is mocked, so these tests run on
any machine without ngspice installed. The library code being verified
is template rendering, subprocess invocation, ``.meas`` parsing, and
failure handling. Whether ngspice itself produces correct AC sweeps is
not in scope here; that's an integration-test concern verified by
running the demo scripts on a real circuit.
"""
import math
import os
import subprocess
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import pytest

from utils.tolerance import NgspiceBackend


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


def _make_backend(template=RC_TEMPLATE, outputs=("fc",), **kwargs):
    """Construct a backend without requiring ngspice on PATH — patches
    shutil.which during init so tests run on machines without ngspice
    installed."""
    with patch("utils.tolerance.ngspice.shutil.which",
               return_value="/fake/path/to/ngspice"):
        return NgspiceBackend(template=template, outputs=list(outputs),
                              **kwargs)


def _mock_run(returncode=0, stdout="fc                  =  1.591550e+05\n",
              stderr="", capture_netlist=None):
    """Build a subprocess.run replacement that returns canned output and
    optionally captures the netlist tempfile contents into the supplied
    dict for assertion."""
    def side_effect(argv, *args, **kwargs):
        if capture_netlist is not None:
            # argv is [ngspice, -b, /tmp/...cir]; read the tempfile
            cir_path = argv[2]
            with open(cir_path) as f:
                capture_netlist["netlist"] = f.read()
            capture_netlist["argv"] = list(argv)
        return MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)
    return side_effect


# ---------- Construction ----------

def test_init_raises_if_ngspice_not_on_path():
    """The shutil.which check is the user's first line of defence
    against a misconfigured environment — fail at construction, not
    at the first MC sample after a 10-minute setup."""
    with patch("utils.tolerance.ngspice.shutil.which", return_value=None):
        with pytest.raises(RuntimeError, match="ngspice"):
            NgspiceBackend(template=RC_TEMPLATE, outputs=["fc"])


def test_init_rejects_non_template_input():
    with pytest.raises(TypeError, match="template"):
        with patch("utils.tolerance.ngspice.shutil.which",
                   return_value="/fake"):
            NgspiceBackend(template=12345, outputs=["fc"])


# ---------- Template rendering & subprocess invocation ----------

def test_subprocess_invoked_with_ngspice_batch_args():
    backend = _make_backend()
    captured = {}
    with patch("utils.tolerance.ngspice.subprocess.run",
               side_effect=_mock_run(capture_netlist=captured)):
        backend(R=1e3, C=1e-9)
    # backend uses the ngspice command name as passed in (resolution
    # happens via shutil.which only at construction time)
    assert captured["argv"][0] == "ngspice"
    assert captured["argv"][1] == "-b"
    assert captured["argv"][2].endswith(".cir")


def test_string_template_format_substitutes_values():
    backend = _make_backend()
    captured = {}
    with patch("utils.tolerance.ngspice.subprocess.run",
               side_effect=_mock_run(capture_netlist=captured)):
        backend(R=1234.5, C=6.78e-9)
    assert "R1 in out 1234.5" in captured["netlist"]
    assert "C1 out 0 6.78e-09" in captured["netlist"]


def test_callable_template_invoked_with_values():
    """Callable templates get the values dict — confirm by capturing
    what the callable received and what netlist actually got written."""
    seen = {}
    def template(R, C):
        seen["R"] = R; seen["C"] = C
        return f"* placeholder R={R} C={C}\n.end\n"
    backend = _make_backend(template=template)
    captured = {}
    with patch("utils.tolerance.ngspice.subprocess.run",
               side_effect=_mock_run(capture_netlist=captured)):
        backend(R=2.5e3, C=4.7e-9)
    assert seen == {"R": 2.5e3, "C": 4.7e-9}
    assert "R=2500.0 C=4.7e-09" in captured["netlist"]


# ---------- Output parsing ----------

def test_meas_value_parsed_as_float():
    backend = _make_backend()
    with patch("utils.tolerance.ngspice.subprocess.run",
               side_effect=_mock_run(stdout="fc = 1.59155e+05\n")):
        out = backend(R=1e3, C=1e-9)
    assert out["fc"] == pytest.approx(1.59155e5)


def test_meas_failed_keyword_returns_nan():
    """ngspice prints ``= failed`` when a .meas trigger condition
    can't be satisfied. We surface that as NaN so analyze() counts
    it as a sample-level failure (not a hard error)."""
    backend = _make_backend()
    with patch("utils.tolerance.ngspice.subprocess.run",
               side_effect=_mock_run(stdout="fc = failed\n")):
        out = backend(R=1e3, C=1e-9)
    assert math.isnan(out["fc"])


def test_missing_meas_in_output_returns_nan():
    """Asking for a .meas name that doesn't appear in stdout → NaN.
    Lets the user keep a stable outputs list across template
    variants without conditional bookkeeping."""
    backend = _make_backend(outputs=["fc", "absent"])
    with patch("utils.tolerance.ngspice.subprocess.run",
               side_effect=_mock_run(stdout="fc = 1.5e5\n")):
        out = backend(R=1e3, C=1e-9)
    assert out["fc"] == pytest.approx(1.5e5)
    assert math.isnan(out["absent"])


def test_unparseable_value_returns_nan():
    """A garbled value (anything that doesn't float()) maps to NaN
    rather than raising — a malformed line shouldn't abort the sweep."""
    backend = _make_backend()
    with patch("utils.tolerance.ngspice.subprocess.run",
               side_effect=_mock_run(stdout="fc = not_a_number\n")):
        out = backend(R=1e3, C=1e-9)
    assert math.isnan(out["fc"])


# ---------- Failure handling ----------

def test_returncode_nonzero_with_no_meas_raises():
    """Subprocess fails AND no parseable measurements: most likely a
    template error (syntax, undefined model) rather than a one-off
    convergence problem. Raise loudly to save a sweep that would
    otherwise return 100% NaN."""
    backend = _make_backend()
    with patch("utils.tolerance.ngspice.subprocess.run",
               side_effect=_mock_run(returncode=1, stdout="",
                                     stderr="syntax error")):
        with pytest.raises(RuntimeError, match="ngspice"):
            backend(R=1e3, C=1e-9)


def test_returncode_nonzero_with_partial_meas_returns_what_parsed():
    """Subprocess fails BUT some .meas output was parsed: a per-sample
    convergence failure that still reported some measurements. Return
    those (NaN for any unparseable) and let the sweep continue."""
    backend = _make_backend(outputs=["fc"])
    with patch("utils.tolerance.ngspice.subprocess.run",
               side_effect=_mock_run(returncode=1,
                                     stdout="fc = 1.5e5\n")):
        out = backend(R=1e3, C=1e-9)
    assert out["fc"] == pytest.approx(1.5e5)


def test_timeout_returns_all_nan():
    backend = _make_backend(outputs=["fc", "peak"], timeout=0.001)
    def raises(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="ngspice", timeout=0.001)
    with patch("utils.tolerance.ngspice.subprocess.run", side_effect=raises):
        out = backend(R=1e3, C=1e-9)
    assert math.isnan(out["fc"])
    assert math.isnan(out["peak"])


# ---------- Signature ----------

def test_signature_stable_for_same_template():
    a = _make_backend(template=RC_TEMPLATE, outputs=["fc"])
    b = _make_backend(template=RC_TEMPLATE, outputs=["fc"])
    assert a.signature() == b.signature()


def test_signature_differs_for_different_template():
    a = _make_backend(template=RC_TEMPLATE, outputs=["fc"])
    b = _make_backend(template=RC_TEMPLATE + "* extra\n", outputs=["fc"])
    assert a.signature() != b.signature()


def test_signature_differs_for_different_outputs():
    a = _make_backend(template=RC_TEMPLATE, outputs=["fc"])
    b = _make_backend(template=RC_TEMPLATE, outputs=["fc", "peak"])
    assert a.signature() != b.signature()
