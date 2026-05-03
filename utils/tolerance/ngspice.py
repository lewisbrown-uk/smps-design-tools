"""ngspice backend for the tolerance library.

Renders a parameterised netlist with one Monte-Carlo sample's component
values, runs ``ngspice -b``, parses the ``.meas`` output. Drop-in for
the ``metrics=`` argument of ``analyze`` — the rest of the library is
unchanged.
"""
import hashlib
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


# Matches lines of the form "name = number" or "name = failed" at the
# start of a line (re.MULTILINE), which is the format ngspice uses for
# .meas output in batch mode. The leading-anchor + \b discipline keeps
# us from matching the trailing 'targ=...' / 'trig=...' / 'FROM=...'
# fields that appear after the value on the same line.
_MEAS_RE = re.compile(
    r"^\s*(\w+)\s*=\s*([-+0-9.eE]+|failed)\b",
    re.MULTILINE,
)


def _parse_meas_output(stdout):
    """Extract every ``name = value`` from ngspice batch-mode stdout
    into a dict. ``= failed`` and unparseable numbers map to NaN.
    Used by both ``NgspiceBackend`` (local) and ``RemoteNgspiceBackend``
    (ssh) — the format is the same regardless of where ngspice ran."""
    parsed = {}
    for m in _MEAS_RE.finditer(stdout):
        name, val = m.group(1), m.group(2)
        if val == "failed":
            parsed[name] = float("nan")
        else:
            try:
                parsed[name] = float(val)
            except ValueError:
                parsed[name] = float("nan")
    return parsed


def _signature(template, outputs):
    """Hash of (template + outputs) — short stable identifier shared by
    local and remote backends so they index the same cache namespace
    when run against the same circuit."""
    if isinstance(template, str):
        template_part = template
    else:
        template_part = repr(template)
    digest_input = (template_part + "\x00"
                    + ",".join(outputs)).encode()
    return hashlib.sha256(digest_input).hexdigest()[:16]


class NgspiceBackend:
    """Callable that runs ngspice on a parameterised netlist and returns
    the ``.meas`` results as a dict.

    Use as the ``metrics=`` argument of ``analyze``::

        backend = NgspiceBackend(
            template=\"\"\"
            V1 in 0 AC 1
            R1 in out {R}
            C1 out 0 {C}
            .ac dec 100 1 1Meg
            .meas ac fc when vdb(out)=-3
            .end
            \"\"\",
            outputs=["fc"],
        )

        report = analyze(
            nominal_values={"R": 1e3, "C": 1e-9},
            passive_tolerances={"R": 0.01, "C": 0.05},
            metrics=backend,
            spec={"fc": ("within", 0.05)},
            n_mc=100,
        )

    Args:
        template: How to build the netlist text from one sample of
            component values. Either:

            - A callable ``(**values) -> str`` returning the full
              netlist. Most flexible — full Python expressivity for
              circuits whose structure depends on values.
            - A string with Python format placeholders (``{R1}``,
              ``{C2}``, ...). Substituted via ``str.format(**values)``;
              escape literal braces as ``{{`` / ``}}`` if needed.

        outputs: Names of ``.meas`` directives whose values to return.
            Each must appear in the netlist as
            ``.meas <type> name ...``. Names are case-sensitive and
            must match exactly what ngspice prints.
        ngspice: Path to the ngspice binary. Default ``"ngspice"`` on
            ``PATH``.
        timeout: Per-run wall-clock timeout in seconds. ngspice can
            spin on pathological convergence problems; the timeout
            means a stuck sample doesn't stall the whole sweep.

    Failure handling:

    - Missing ``.meas`` name in the parsed output, or ``= failed`` in
      the ngspice text → that output's value is ``float("nan")``.
    - Subprocess timeout → all outputs ``nan``.
    - Subprocess returncode nonzero **with at least one parsed
      measurement** → return what we have (samples in a sweep can
      individually fail without aborting the whole MC run).
    - Subprocess returncode nonzero **and no parsed measurements at
      all** → raise ``RuntimeError``. This pattern indicates a
      template-level mistake (syntax error, undefined symbol, etc.)
      rather than a one-off convergence problem; failing loudly here
      saves the user from a sweep that returns 100% NaN.

    NaN propagates through ``analyze``'s spec evaluation as a fail
    (NaN comparisons are always False), so convergence problems show
    up naturally in the yield report's failure-mode breakdown.
    """

    def __init__(self, template, outputs, *,
                 ngspice="ngspice", timeout=60.0):
        if not (callable(template) or isinstance(template, str)):
            raise TypeError(
                "template must be a callable (**values) -> str or a "
                "format string"
            )
        if shutil.which(ngspice) is None:
            raise RuntimeError(f"ngspice binary not found: {ngspice!r}")
        self.template = template
        self.outputs = list(outputs)
        self.ngspice = ngspice
        self.timeout = timeout

    def signature(self):
        """Stable identifier for this backend's template + outputs.

        Used by ``CachedBackend`` to isolate cache namespaces — if you
        change the template, the new backend's signature differs and
        the previous template's cached values won't be returned for
        the new circuit. Callable templates fall back to their ``repr``,
        which is enough to distinguish *different* function objects
        but won't catch in-place edits to a function's body. The
        signature deliberately ignores host (local vs remote) — running
        the same netlist on a different machine should hit the same
        cached values."""
        return _signature(self.template, self.outputs)

    def _render(self, values):
        if callable(self.template):
            return self.template(**values)
        return self.template.format(**values)

    def __call__(self, **values):
        netlist = self._render(values)

        # Tempfile per call so concurrent invocations don't race on
        # filename. Cost is one mkstemp + unlink per ngspice run, which
        # is dwarfed by ngspice's own startup time.
        with tempfile.NamedTemporaryFile(
            suffix=".cir", mode="w", delete=False
        ) as f:
            f.write(netlist)
            cir_path = Path(f.name)

        try:
            try:
                result = subprocess.run(
                    [self.ngspice, "-b", str(cir_path)],
                    capture_output=True, text=True,
                    timeout=self.timeout,
                )
            except subprocess.TimeoutExpired:
                return {name: float("nan") for name in self.outputs}

            parsed = _parse_meas_output(result.stdout)

            if result.returncode != 0 and not parsed:
                raise RuntimeError(
                    f"ngspice failed (returncode {result.returncode}) "
                    f"and produced no .meas output — likely a template "
                    f"error.\nstderr (last 2k):\n"
                    f"{result.stderr[-2000:]}"
                )

            return {name: parsed.get(name, float("nan"))
                    for name in self.outputs}
        finally:
            try:
                cir_path.unlink()
            except OSError:
                pass
