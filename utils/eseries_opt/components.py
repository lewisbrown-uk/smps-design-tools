import math
import numpy as np

from utils.rounding import e3, e6, e12, e24, e48, e96


_E_SERIES_DIGITS = {
    1:  [1.0],
    3:  e3,
    6:  e6,
    12: e12,
    24: e24,
    48: e48,
    96: e96,
}


def _digits_for(e_series):
    if e_series not in _E_SERIES_DIGITS:
        raise ValueError(
            f"Unsupported E-series: {e_series}. "
            f"Supported: {sorted(_E_SERIES_DIGITS)}"
        )
    return _E_SERIES_DIGITS[e_series]


class Component:
    unit = ""

    def __init__(self, name, e_series, range):
        self.name = name
        self.e_series = e_series
        self.range = range

    def values(self):
        digits = _digits_for(self.e_series)
        lo, hi = self.range
        if lo > hi:
            raise ValueError(f"Component {self.name}: range lo > hi")

        lo_dec = math.floor(math.log10(lo))
        hi_dec = math.floor(math.log10(hi))

        # Widen the decade scan by one in each direction to absorb FP edge
        # cases on exact-decade boundaries.
        out = set()
        for d in range(lo_dec - 1, hi_dec + 2):
            scale = 10.0 ** d
            for digit in digits:
                v = digit * scale
                if lo * (1 - 1e-12) <= v <= hi * (1 + 1e-12):
                    out.add(v)
        return np.array(sorted(out))


class Resistor(Component):
    unit = "Ω"


class Capacitor(Component):
    unit = "F"


class Inductor(Component):
    unit = "H"
