import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import math

from controllers import LM3478, LT8300
from topologies import boost, flyback


def test_boost_duty_cycle():
    d = boost.duty_cycle(40, 480, 0.300, 1.2)
    assert math.isclose(d, 0.9174979, rel_tol=1e-6)


def test_boost_inductor_value_for_ripple():
    val = boost.inductor_value_for_ripple(40, 0.9, 250e3, 0.1)
    assert math.isclose(val, 7.2e-4, rel_tol=1e-2)


def test_boost_sense_resistor():
    R = boost.sense_resistor(LM3478, 1.0, 0.5)
    expected = (LM3478.V_sense - (0.5 * LM3478.V_sense * LM3478.ratio_V_sl)) / 1.0
    assert math.isclose(R, expected, rel_tol=1e-6)


def test_flyback_duty_cycle():
    d = flyback.duty_cycle(12, 400, 1.45, 0.1)
    assert math.isclose(d, 0.76987247, rel_tol=1e-6)


def test_flyback_feedback_resistor():
    r = flyback.feedback_resistor(LT8300, 400, 1.45, 0.1)
    assert math.isclose(r, 401450.0, rel_tol=1e-6)
