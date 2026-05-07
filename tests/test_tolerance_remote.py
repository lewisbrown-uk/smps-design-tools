"""Tests for the remote ngspice backend.

Fully stubbed — no ssh, no remote host. The library code being verified
is ssh argv construction, ControlMaster connection pooling, slot
rotation under concurrent calls, and the same failure-handling
contract as the local backend. Whether ssh + ngspice on a real cluster
actually returns sensible answers is integration-tested by running
the demo scripts (e.g. utils/tolerance/README.md).
"""
import math
import os
import subprocess
import sys
import threading
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import pytest

from utils.tolerance import RemoteNgspiceBackend, NgspiceBackend


RC_TEMPLATE = """* RC LP
V1 in 0 AC 1
R1 in out {R}
C1 out 0 {C}
.control
ac dec 200 100 10Meg
meas ac fc when vm(out)=0.7079
.endc
.end
"""


def _make_backend(host="HV2", template=RC_TEMPLATE, outputs=("fc",), **kwargs):
    """Construct without requiring ssh on PATH (patched for portability)."""
    with patch("utils.tolerance.remote.shutil.which",
               return_value="/fake/path/to/ssh"):
        return RemoteNgspiceBackend(template=template, outputs=list(outputs),
                                    host=host, **kwargs)


def _mock_run(returncode=0, stdout="fc                  =  1.59155e+05\n",
              stderr="", capture=None):
    def side_effect(argv, *args, **kwargs):
        if capture is not None:
            capture["argv"] = list(argv)
            capture["input"] = kwargs.get("input")
        return MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)
    return side_effect


# ---------- Construction ----------

def test_init_raises_if_ssh_not_on_path():
    with patch("utils.tolerance.remote.shutil.which", return_value=None):
        with pytest.raises(RuntimeError, match="ssh"):
            RemoteNgspiceBackend(template=RC_TEMPLATE, outputs=["fc"],
                                 host="HV2")


def test_init_rejects_non_template_input():
    with patch("utils.tolerance.remote.shutil.which", return_value="/fake"):
        with pytest.raises(TypeError, match="template"):
            RemoteNgspiceBackend(template=12345, outputs=["fc"], host="HV2")


def test_init_rejects_zero_control_connections():
    with patch("utils.tolerance.remote.shutil.which", return_value="/fake"):
        with pytest.raises(ValueError, match="n_control_connections"):
            RemoteNgspiceBackend(template=RC_TEMPLATE, outputs=["fc"],
                                 host="HV2", n_control_connections=0)


# ---------- ssh argv composition ----------

def test_ssh_argv_includes_host_and_remote_command():
    backend = _make_backend(host="HV2")
    cap = {}
    with patch("utils.tolerance.remote.subprocess.run",
               side_effect=_mock_run(capture=cap)):
        backend(R=1e3, C=1e-9)
    assert cap["argv"][0] == "ssh"
    assert "HV2" in cap["argv"]
    # Remote command is the last argv element; should run ngspice on a
    # tempfile produced by mktemp + cat (the workaround for ngspice
    # 44.x's stdin AC bug).
    remote = cap["argv"][-1]
    assert "mktemp" in remote
    assert "ngspice -b" in remote


def test_ssh_argv_contains_control_master_options_by_default():
    backend = _make_backend(host="HV2")
    cap = {}
    with patch("utils.tolerance.remote.subprocess.run",
               side_effect=_mock_run(capture=cap)):
        backend(R=1e3, C=1e-9)
    flat = " ".join(cap["argv"])
    assert "ControlMaster=auto" in flat
    assert "ControlPath=" in flat
    assert "ControlPersist=" in flat
    assert "BatchMode=yes" in flat


def test_control_master_disabled_when_path_is_none():
    """control_path=None opts out of connection multiplexing entirely
    — the ssh argv should then carry no Control* options."""
    backend = _make_backend(host="HV2", control_path=None)
    cap = {}
    with patch("utils.tolerance.remote.subprocess.run",
               side_effect=_mock_run(capture=cap)):
        backend(R=1e3, C=1e-9)
    flat = " ".join(cap["argv"])
    assert "ControlMaster" not in flat
    assert "ControlPath" not in flat


def test_netlist_passed_to_ssh_via_stdin():
    """The rendered netlist arrives at the remote shell over the ssh
    stdin pipe (input= kwarg of subprocess.run)."""
    backend = _make_backend()
    cap = {}
    with patch("utils.tolerance.remote.subprocess.run",
               side_effect=_mock_run(capture=cap)):
        backend(R=1234.5, C=6.78e-9)
    assert "R1 in out 1234.5" in cap["input"]
    assert "C1 out 0 6.78e-09" in cap["input"]


# ---------- ControlPath rotation ----------

def test_n_control_connections_rotates_slots_round_robin():
    backend = _make_backend(host="HV2", n_control_connections=3)
    paths = []
    def capture(argv, *a, **kw):
        for arg in argv:
            if arg.startswith("ControlPath="):
                paths.append(arg)
        return MagicMock(returncode=0,
                         stdout="fc = 1.5e3\n", stderr="")
    with patch("utils.tolerance.remote.subprocess.run", side_effect=capture):
        for _ in range(7):
            backend(R=1, C=1e-9)
    # First 3 paths distinct; cycle repeats from index 3 onward
    assert paths[:3] == paths[3:6]
    assert paths[3] == paths[6]
    assert len(set(paths[:3])) == 3


def test_slot_rotation_thread_safe_under_concurrent_calls():
    """The slot counter is shared across threads; the lock guarantees
    each call gets a distinct slot draw (no skips, no doubles, no
    races on next())."""
    backend = _make_backend(host="HV2", n_control_connections=4)
    seen = []
    seen_lock = threading.Lock()
    def capture(argv, *a, **kw):
        for arg in argv:
            if arg.startswith("ControlPath="):
                with seen_lock:
                    seen.append(arg)
        return MagicMock(returncode=0,
                         stdout="fc = 1.5e3\n", stderr="")
    n_calls = 100
    with patch("utils.tolerance.remote.subprocess.run", side_effect=capture):
        threads = [threading.Thread(target=backend,
                                    kwargs={"R": 1, "C": 1e-9})
                   for _ in range(n_calls)]
        for t in threads: t.start()
        for t in threads: t.join()
    # Counter draws should be exactly 100, distributed evenly modulo 4
    assert len(seen) == n_calls
    from collections import Counter
    counts = Counter(seen)
    assert sum(counts.values()) == n_calls
    # With perfect round-robin and 100 calls / 4 slots, each slot
    # should be hit exactly 25 times — no slot skipped, no slot used
    # twice the expected count.
    assert all(v == 25 for v in counts.values()), counts


# ---------- Failure handling (mirrors local backend contract) ----------

def test_meas_failed_returns_nan():
    backend = _make_backend()
    with patch("utils.tolerance.remote.subprocess.run",
               side_effect=_mock_run(stdout="fc = failed\n")):
        out = backend(R=1e3, C=1e-9)
    assert math.isnan(out["fc"])


def test_returncode_nonzero_with_no_meas_raises():
    backend = _make_backend()
    with patch("utils.tolerance.remote.subprocess.run",
               side_effect=_mock_run(returncode=1, stdout="",
                                     stderr="ssh: connection refused")):
        with pytest.raises(RuntimeError, match="HV2"):
            backend(R=1e3, C=1e-9)


def test_returncode_nonzero_with_partial_meas_returns_what_parsed():
    backend = _make_backend()
    with patch("utils.tolerance.remote.subprocess.run",
               side_effect=_mock_run(returncode=1,
                                     stdout="fc = 1.5e5\n")):
        out = backend(R=1e3, C=1e-9)
    assert out["fc"] == pytest.approx(1.5e5)


def test_timeout_returns_all_nan():
    backend = _make_backend(outputs=["fc", "peak"], timeout=0.001)
    def raises(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="ssh", timeout=0.001)
    with patch("utils.tolerance.remote.subprocess.run", side_effect=raises):
        out = backend(R=1e3, C=1e-9)
    assert math.isnan(out["fc"])
    assert math.isnan(out["peak"])


# ---------- close_connection ----------

def test_close_connection_issues_exit_per_slot():
    """With N control connections we should issue ssh -O exit N times,
    each with the corresponding ControlPath. Otherwise we'd leak
    sockets."""
    backend = _make_backend(host="HV2", n_control_connections=4)
    cap_paths = []
    def capture(argv, *a, **kw):
        if "-O" in argv and "exit" in argv:
            for arg in argv:
                if arg.startswith("ControlPath="):
                    cap_paths.append(arg)
        return MagicMock(returncode=0)
    with patch("utils.tolerance.remote.subprocess.run", side_effect=capture):
        backend.close_connection()
    assert len(cap_paths) == 4
    assert len(set(cap_paths)) == 4   # one per slot, all distinct


def test_close_connection_noop_when_path_is_none():
    backend = _make_backend(host="HV2", control_path=None)
    with patch("utils.tolerance.remote.subprocess.run") as mock_run:
        backend.close_connection()
    mock_run.assert_not_called()


# ---------- Signature equivalence with local backend ----------

def test_signature_matches_local_for_same_template():
    """Both backends compute signature from (template, outputs); host
    is deliberately excluded so a cache populated by one is hit by the
    other. This is the headline cross-backend property — verify it
    without needing either tool present."""
    with patch("utils.tolerance.ngspice.shutil.which",
               return_value="/fake/ngspice"), \
         patch("utils.tolerance.remote.shutil.which",
               return_value="/fake/ssh"):
        local  = NgspiceBackend(template=RC_TEMPLATE, outputs=["fc"])
        remote = RemoteNgspiceBackend(template=RC_TEMPLATE, outputs=["fc"],
                                      host="anywhere")
    assert local.signature() == remote.signature()


def test_signature_independent_of_host():
    a = _make_backend(host="HV2")
    b = _make_backend(host="HV3")
    assert a.signature() == b.signature()
