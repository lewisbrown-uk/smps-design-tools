"""ngspice ``.control``-block generators for measurement patterns
that don't fit a single ``.meas`` directive.

Right now this is just the lock-in THD pattern. The intent is to keep
the patterns self-contained and parameterisable so the same circuit
template can be reused at different signal nodes / windows / frequency
estimates without copy-pasting 30 lines of ngspice script.
"""


def lockin_thd_block(signal: str,
                     window: tuple[float, float],
                     f0_init_expr: str,
                     df_frac: float = 0.01) -> str:
    """Return an ngspice ``.control`` snippet that measures THD+N of
    ``signal`` over ``window`` via parabolic-fit lock-in detection.

    The snippet projects the (DC-removed) signal onto sin/cos basis
    vectors at three nearby frequencies (``f0_est``, ``f0_est ± df``),
    refines ``f0`` by parabolic fit on the three residual RMS values,
    re-projects at the refined frequency, and computes:

    - ``f_new``  : refined fundamental frequency [Hz]
    - ``a_rms``  : RMS amplitude of the fundamental [V]
    - ``h_rms``  : RMS of harmonic+noise residual [V]
    - ``thd``    : h_rms / a_rms (ratio)
    - ``thd_db`` : 20·log10(thd) [dB]

    All five end up in the snippet's ``print`` statement, so a
    NgspiceBackend that includes them in ``outputs=`` will receive
    them as scalars in its result dict.

    Args:
        signal: ngspice voltage expression, e.g. ``"v(out)"``.
        window: ``(t_start, t_end)`` in seconds — the integration
            window. Should be ≥ 10 cycles long; longer is better for
            residual averaging but costs simulator time. The window
            should be after the oscillator has settled.
        f0_init_expr: ngspice expression evaluating to the initial
            frequency estimate. Common forms:

            - ``"1/(t2-t1)"`` if you've measured two zero-crossing
              times ``t1`` and ``t2`` one period apart via prior
              ``meas tran`` directives.
            - ``"1000"`` for a literal nominal frequency.
            - The name of any previously-defined ``let`` scalar.

            The parabolic refinement converges quickly so the initial
            estimate just needs to be within a few percent of the true
            value.
        df_frac: probe spacing for the parabolic fit, as a fraction
            of ``f0_est``. Default 0.01 = ±1%. Smaller values give
            tighter refinement but risk numerical noise on the
            residual differences; larger values widen the parabolic
            fit's effective window.

    Returns:
        A multi-line string suitable for splicing between ``.control``
        and ``.endc`` in an ngspice netlist. The caller is responsible
        for any prior measurements the ``f0_init_expr`` depends on
        (e.g., the zero-crossing ``t1`` / ``t2`` measurements) and
        for ensuring ``signal`` is a valid voltage reference in the
        tran results.

    Example::

        from utils.tolerance import lockin_thd_block

        template = f\"\"\"
        ... circuit + .tran ...
        .control
        run
        meas tran t1 when v(out)=0 fall=20
        meas tran t2 when v(out)=0 fall=21
        meas tran amp_max max v(out) from=80m to=100m
        meas tran amp_min min v(out) from=80m to=100m
        {{lockin}}
        .endc
        .end
        \"\"\".replace("{{lockin}}", lockin_thd_block(
            signal="v(out)",
            window=(80e-3, 100e-3),
            f0_init_expr="1/(t2-t1)",
        ))

    Note on signal substitution: the snippet inlines ``signal``
    multiple times. Keep it short and side-effect-free (e.g.
    ``"v(out)"``, not a complex expression that triggers ngspice
    re-evaluation each substitution).
    """
    t_start, t_end = window
    if not (t_end > t_start):
        raise ValueError(
            f"window end must be > start (got {window})"
        )
    if not (0 < df_frac < 1):
        raise ValueError(
            f"df_frac must be in (0, 1) (got {df_frac})"
        )

    win = f"from={t_start:.6e} to={t_end:.6e}"
    sig = signal
    return f"""\
* --- lock-in THD on {sig} over [{t_start:g}, {t_end:g}] s ---
let f0_est = {f0_init_expr}
let df_probe = {df_frac} * f0_est
meas tran v_dc avg {sig} {win}
let basis_sin0 = sin(2*3.14159265*f0_est*time)
let basis_cos0 = cos(2*3.14159265*f0_est*time)
let basis_sinp = sin(2*3.14159265*(f0_est+df_probe)*time)
let basis_cosp = cos(2*3.14159265*(f0_est+df_probe)*time)
let basis_sinm = sin(2*3.14159265*(f0_est-df_probe)*time)
let basis_cosm = cos(2*3.14159265*(f0_est-df_probe)*time)
let psi0 = 2*({sig}-v_dc)*basis_sin0
let pco0 = 2*({sig}-v_dc)*basis_cos0
let psip = 2*({sig}-v_dc)*basis_sinp
let pcop = 2*({sig}-v_dc)*basis_cosp
let psim = 2*({sig}-v_dc)*basis_sinm
let pcom = 2*({sig}-v_dc)*basis_cosm
meas tran sin0 avg psi0 {win}
meas tran cos0 avg pco0 {win}
meas tran sinp avg psip {win}
meas tran cosp avg pcop {win}
meas tran sinm avg psim {win}
meas tran cosm avg pcom {win}
let r0v = {sig} - v_dc - sin0*basis_sin0 - cos0*basis_cos0
let rpv = {sig} - v_dc - sinp*basis_sinp - cosp*basis_cosp
let rmv = {sig} - v_dc - sinm*basis_sinm - cosm*basis_cosm
meas tran res0 rms r0v {win}
meas tran resp rms rpv {win}
meas tran resm rms rmv {win}
let f_new = f0_est - ((resp - resm)/(2*df_probe)) * df_probe^2 / (resp - 2*res0 + resm)
let basis_sin = sin(2*3.14159265*f_new*time)
let basis_cos = cos(2*3.14159265*f_new*time)
let psi = 2*({sig}-v_dc)*basis_sin
let pco = 2*({sig}-v_dc)*basis_cos
meas tran sin_out avg psi {win}
meas tran cos_out avg pco {win}
let a_rms = sqrt(sin_out^2 + cos_out^2)/sqrt(2)
let residual = {sig} - v_dc - sin_out*basis_sin - cos_out*basis_cos
meas tran h_rms rms residual {win}
let thd = h_rms / a_rms
let thd_db = 20*log10(thd)
print f_new a_rms h_rms thd thd_db
* --- end lock-in block ---"""
