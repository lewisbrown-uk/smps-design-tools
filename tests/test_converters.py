import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import math
from boost_converter import lm3478
from flyback_converter import lt8300


def test_lm3478_duty_cycle():
    d = lm3478.duty_cycle(40, 480, 0.300, 1.2)
    assert math.isclose(d, 0.9174979, rel_tol=1e-6)


def test_lm3478_inductor_value_for_ripple():
    val = lm3478.inductor_value_for_ripple(40, 0.9, 250e3, 0.1)
    assert math.isclose(val, 7.2e-4, rel_tol=1e-2)


def test_lt8300_duty_cycle():
    d = lt8300.duty_cycle(12, 400, 1.45, 0.1)
    assert math.isclose(d, 0.76987247, rel_tol=1e-6)


def test_lt8300_feedback_resistor():
    r = lt8300.feedback_resistor(400, 1.45, 100e-6, 0.1)
    assert math.isclose(r, 401450.0, rel_tol=1e-6)
