import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import pytest
from utils import rounding as rnd


def test_sig_figs_basic():
    assert rnd.sig_figs(1234, 2) == 1200
    assert rnd.sig_figs(0.012345, 3) == pytest.approx(0.0123)
    assert rnd.sig_figs(-1234, 2) == -1200


def test_prefix_basic():
    assert rnd.prefix(0) == "0"
    assert rnd.prefix(1000) == "1k"
    assert rnd.prefix(0.001) == "1m"
    assert rnd.prefix(2.5e-6) == "2.5\u00b5"


def test_closest_e_series_value():
    assert rnd.closest_E_series_value(55, e_series=24) == pytest.approx(56.0)
    assert rnd.closest_E_series_value(55, e_series=24, method='gt') == pytest.approx(56.0)
    assert rnd.closest_E_series_value(55, e_series=24, method='lt') == pytest.approx(51.0)
    assert rnd.closest_E_series_value(0.72, e_series=12) == pytest.approx(0.68)
