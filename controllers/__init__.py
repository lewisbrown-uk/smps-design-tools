from dataclasses import dataclass
from typing import Tuple, Optional


@dataclass
class Controller:
    """Parameters describing a switch-mode controller."""

    name: str
    topologies: Tuple[str, ...]
    V_ref: Optional[float] = None
    V_sense: Optional[float] = None
    ratio_V_sl: Optional[float] = None
    V_sl: Optional[float] = None
    I_Rfb: Optional[float] = None
    I_sw_max: Optional[float] = None
    I_sw_min: Optional[float] = None
    t_on_min: Optional[float] = None
    t_off_min: Optional[float] = None
    f_sw_range: Optional[Tuple[float, float]] = None


# Example controller definitions used in the notebooks
LM3478 = Controller(
    name="LM3478",
    topologies=("boost",),
    V_ref=1.26,
    V_sense=156e-3,
    ratio_V_sl=0.49,
    V_sl=92e-3,
    f_sw_range=(100e3, 1e6),
)

LT8300 = Controller(
    name="LT8300",
    topologies=("flyback",),
    I_Rfb=100e-6,
    I_sw_max=260e-3,
    I_sw_min=52e-3,
    t_off_min=350e-9,
    t_on_min=160e-9,
)

LM5156 = Controller(
    name="LM5156",
    topologies=("boost", "flyback",),
    v_ref=1.0,
    V_sense=100e-3,
    f_sw_range=(100e3, 2.2e6),
)