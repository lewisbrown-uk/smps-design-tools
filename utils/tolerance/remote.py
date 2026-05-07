"""Remote ngspice backend over ssh.

Mirrors ``NgspiceBackend`` but dispatches each run to a remote host.
Drop-in replacement: same ``__call__`` signature, same ``signature()``,
same NaN-on-failure semantics. Use with ``CachedBackend`` and
``analyze(workers=N)`` exactly as the local version.

Why a remote backend at all: ngspice on regulator-class transient sims
is seconds per run; an MC sweep with thousands of samples is minutes
to hours of compute. The user's HV2/HV3 cluster has 96–128 cores; a
remote-dispatched sweep that saturates them runs ~50× faster than the
14-core local box.
"""
import itertools
import shutil
import subprocess
import threading

from .ngspice import _parse_meas_output, _signature


_DEFAULT_CONTROL_PATH = "/tmp/tolerance-cm-%C"
"""Default ssh ControlPath. ``%C`` expands to a hash of host:port:user
— stable across calls to the same host but distinct per host. Means
multiple RemoteNgspiceBackend instances against the same host share
one TCP connection without explicit coordination."""


# ngspice 44.x — the version on the user's HV2/HV3 — fails to apply AC
# sources when its netlist arrives via /dev/stdin (v(out) is identically
# zero across the sweep). Reading from a regular file works fine. So
# the ssh remote command writes stdin to a tempfile, runs ngspice on
# that file, then cleans up. Local 45.2 doesn't need this; we use the
# same pattern remotely for portability.
_REMOTE_CMD = (
    "tmp=$(mktemp --suffix=.cir) && "
    "cat > \"$tmp\" && "
    "{ngspice} -b \"$tmp\" 2>&1; "
    "rc=$?; rm -f \"$tmp\"; exit $rc"
)


class RemoteNgspiceBackend:
    """Run ngspice on a remote host over ssh.

    Use as the ``metrics=`` argument of ``analyze``::

        backend = RemoteNgspiceBackend(
            template=netlist_template,
            outputs=["fc"],
            host="HV2",
        )
        report = analyze(metrics=backend, ..., workers=64)

    ssh ``ControlMaster`` is enabled automatically with a per-host
    ControlPath under ``/tmp``, so repeated calls reuse one TCP
    connection. The first call pays the full ssh-handshake cost
    (~150-300 ms); subsequent calls are ~5 ms of multiplexing
    overhead. For ``analyze(workers=N)`` with thousands of samples
    this matters a lot.

    Args:
        template: Same as ``NgspiceBackend`` — callable or
            ``str.format`` template.
        outputs: ``.meas`` names to extract from the remote ngspice
            stdout.
        host: ssh target. Anything ``ssh <host>`` accepts: alias from
            ``~/.ssh/config``, ``user@hostname``, IP, etc.
        ssh: Path to the local ssh binary (default ``"ssh"`` on PATH).
        ngspice: Remote ngspice command. Default ``"ngspice"``; override
            if it lives at a non-PATH location on the remote.
        timeout: Per-call wall-clock timeout including ssh overhead.
            Default 120 s (more generous than local default since the
            first call also pays ControlMaster setup).
        control_path: ssh ControlPath template. Default
            ``/tmp/tolerance-cm-%C`` (per-host hash). Set to ``None``
            to disable connection multiplexing entirely (~10x slower
            for repeat calls but no shared state).
        control_persist: How long the multiplexed connection stays up
            after the last client disconnects (any ``ControlPersist``
            value ssh accepts — seconds, ``"10m"``, ``"1h"``, etc.).
            Default ``"600"`` = 10 min.
        n_control_connections: Number of ControlMaster sockets to
            rotate through. OpenSSH's default ``MaxSessions=10`` caps
            concurrent channels per TCP connection — saturating a
            multi-core remote requires multiple TCP connections. Set
            this to ``ceil(workers / 8)`` or so for headroom; default 1
            is fine for serial / lightly-parallel use. When > 1, a
            ``-{slot}`` suffix is appended to ``control_path`` if it
            doesn't already contain ``{slot}``.

    Failure handling matches the local backend:

    - ``.meas`` missing or ``= failed`` → that output is NaN.
    - ssh / subprocess timeout → all outputs NaN.
    - Remote ngspice exits non-zero with no parseable measurements →
      raise ``RuntimeError``. This catches template errors, missing
      remote dependencies, etc. — failing loudly is better than
      silently NaN-ing every sample.
    - ssh itself fails (host unreachable, auth, etc.) → exit code is
      typically 255 with no .meas output → falls through to the
      RuntimeError path.
    """

    def __init__(self, template, outputs, *, host,
                 ssh="ssh", ngspice="ngspice", timeout=120.0,
                 control_path=_DEFAULT_CONTROL_PATH,
                 control_persist="600",
                 n_control_connections=1):
        if not (callable(template) or isinstance(template, str)):
            raise TypeError(
                "template must be a callable (**values) -> str or a "
                "format string"
            )
        if shutil.which(ssh) is None:
            raise RuntimeError(f"ssh binary not found: {ssh!r}")
        if n_control_connections < 1:
            raise ValueError(
                f"n_control_connections must be >= 1, "
                f"got {n_control_connections}"
            )
        self.template = template
        self.outputs = list(outputs)
        self.host = host
        self.ssh = ssh
        self.ngspice = ngspice
        self.timeout = timeout
        self.control_persist = str(control_persist) if control_persist \
                               is not None else None
        self.n_control_connections = n_control_connections
        if (control_path is not None and n_control_connections > 1
                and "{slot}" not in control_path):
            control_path = control_path + "-{slot}"
        self.control_path = control_path
        self._slot_counter = itertools.count()
        self._slot_lock = threading.Lock()

    def signature(self):
        """Same template+outputs signature as ``NgspiceBackend.signature()``
        — host is *not* included so a cache populated by a local run
        will hit on a remote run with the same netlist (and vice
        versa). The simulator output should be identical regardless of
        where it ran."""
        return _signature(self.template, self.outputs)

    def _control_path(self):
        if self.control_path is None or self.n_control_connections == 1:
            return self.control_path
        with self._slot_lock:
            slot = next(self._slot_counter) % self.n_control_connections
        return self.control_path.format(slot=slot)

    def _ssh_args(self):
        args = [self.ssh, "-o", "BatchMode=yes"]
        path = self._control_path()
        if path is not None:
            args += [
                "-o", "ControlMaster=auto",
                "-o", f"ControlPath={path}",
            ]
            if self.control_persist is not None:
                args += ["-o", f"ControlPersist={self.control_persist}"]
        return args

    def _render(self, values):
        if callable(self.template):
            return self.template(**values)
        return self.template.format(**values)

    def __call__(self, **values):
        netlist = self._render(values)
        remote_cmd = _REMOTE_CMD.format(ngspice=self.ngspice)
        try:
            result = subprocess.run(
                [*self._ssh_args(), self.host, remote_cmd],
                input=netlist, capture_output=True, text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            return {name: float("nan") for name in self.outputs}

        parsed = _parse_meas_output(result.stdout)

        if result.returncode != 0 and not parsed:
            raise RuntimeError(
                f"remote ngspice on {self.host!r} failed "
                f"(returncode {result.returncode}) and produced no "
                f".meas output — likely a template error, missing "
                f"remote dependency, or ssh failure.\n"
                f"stdout (last 2k):\n{result.stdout[-2000:]}\n"
                f"stderr (last 2k):\n{result.stderr[-2000:]}"
            )

        return {name: parsed.get(name, float("nan"))
                for name in self.outputs}

    def close_connection(self):
        """Tear down every shared ssh ControlMaster socket for this
        host (one per slot when ``n_control_connections > 1``). Safe
        to call multiple times. Useful at end-of-script to avoid
        leaving multiplexer sockets alive for ``control_persist``
        seconds; without this, they self-clean on timeout."""
        if self.control_path is None:
            return
        if self.n_control_connections == 1:
            paths = [self.control_path]
        else:
            paths = [self.control_path.format(slot=i)
                     for i in range(self.n_control_connections)]
        for path in paths:
            subprocess.run(
                [self.ssh, "-O", "exit",
                 "-o", f"ControlPath={path}", self.host],
                capture_output=True, text=True,
            )
