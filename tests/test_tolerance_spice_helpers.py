"""Tests for the .control snippet generators in spice_helpers.

These check that the snippets are syntactically well-formed (right
parameters substituted in the right places, valid window/probe
arguments, etc.) — not that ngspice produces particular numerical
results, which is integration-tested by the example scripts.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import pytest

from utils.tolerance import lockin_thd_block


def test_lockin_substitutes_signal_throughout():
    """`signal` is referenced many times — every use site must inline
    the user's choice (e.g. v(out), v(filt), etc.) rather than a
    hardcoded node."""
    block = lockin_thd_block(
        signal="v(my_node)",
        window=(80e-3, 100e-3),
        f0_init_expr="1/(t2-t1)",
    )
    # The signal appears in: v_dc, psi/pco basis projections,
    # residual computations, sin_out/cos_out, and final residual.
    # Conservative count: at least 8 references.
    assert block.count("v(my_node)") >= 8
    # And the comment header should mention it
    assert "v(my_node)" in block.split("\n")[0]


def test_lockin_window_appears_in_meas_directives():
    """The window endpoints should appear as from=/to= clauses on
    every meas tran directive."""
    block = lockin_thd_block(
        signal="v(out)",
        window=(0.05, 0.123),
        f0_init_expr="1000",
    )
    # ngspice format: "from=5.000000e-02 to=1.230000e-01"
    assert "from=5.000000e-02" in block
    assert "to=1.230000e-01" in block
    # The exact count: 13 meas tran directives use the window
    # (v_dc + 6 sin/cos averages + 3 residual RMS + sin_out + cos_out + h_rms)
    assert block.count("from=5.000000e-02") == 13


def test_lockin_f0_init_expr_inlined_into_let():
    """`f0_init_expr` becomes the RHS of `let f0_est = ...`. It can be
    any ngspice scalar expression — a literal number, a derived
    expression like 1/(t2-t1), or a previously-defined let variable."""
    for expr in ("1000", "1/(t2-t1)", "my_estimated_f0"):
        block = lockin_thd_block(
            signal="v(out)",
            window=(0.0, 1e-3),
            f0_init_expr=expr,
        )
        assert f"let f0_est = {expr}" in block


def test_lockin_df_frac_default_is_one_percent():
    """Default probe spacing is 1% of f0_est. Smaller is tighter
    refinement but more numerical noise on residual differences."""
    block = lockin_thd_block(
        signal="v(out)", window=(0.0, 1e-3), f0_init_expr="1000",
    )
    assert "let df_probe = 0.01 * f0_est" in block

    block = lockin_thd_block(
        signal="v(out)", window=(0.0, 1e-3), f0_init_expr="1000",
        df_frac=0.005,
    )
    assert "let df_probe = 0.005 * f0_est" in block


def test_lockin_print_lists_user_facing_scalars():
    """The `print` line at the bottom is what NgspiceBackend's regex
    parses — the names listed here are the ones that show up in
    backend output dicts."""
    block = lockin_thd_block(
        signal="v(out)", window=(0.0, 1e-3), f0_init_expr="1000",
    )
    # Find the print line
    print_lines = [l for l in block.split("\n")
                   if l.strip().startswith("print")]
    assert len(print_lines) == 1
    for name in ("f_new", "a_rms", "h_rms", "thd", "thd_db"):
        assert name in print_lines[0]


def test_lockin_invalid_window_raises():
    with pytest.raises(ValueError, match="end must be > start"):
        lockin_thd_block(signal="v(out)",
                         window=(0.1, 0.05),    # end before start
                         f0_init_expr="1000")
    with pytest.raises(ValueError, match="end must be > start"):
        lockin_thd_block(signal="v(out)",
                         window=(0.1, 0.1),     # zero-length window
                         f0_init_expr="1000")


def test_lockin_invalid_df_frac_raises():
    with pytest.raises(ValueError, match="df_frac"):
        lockin_thd_block(signal="v(out)", window=(0.0, 1e-3),
                         f0_init_expr="1000", df_frac=0.0)
    with pytest.raises(ValueError, match="df_frac"):
        lockin_thd_block(signal="v(out)", window=(0.0, 1e-3),
                         f0_init_expr="1000", df_frac=1.5)
