"""Generic flyback-converter design equations."""

from controllers import Controller


def feedback_resistor(controller: Controller, V_out: float, V_f: float, N_ps: float) -> float:
    """Feedback resistor from output voltage and turns ratio."""
    if controller.I_Rfb is None:
        raise ValueError("Controller lacks I_Rfb parameter")
    return N_ps * (V_out + V_f) / controller.I_Rfb


def duty_cycle(V_in: float, V_out: float, V_f: float, N_ps: float) -> float:
    """Switch duty cycle."""
    return (V_out + V_f) * N_ps / ((V_out + V_f) * N_ps + V_in)


def output_power(controller: Controller, V_in: float, eta: float, D: float) -> float:
    """Maximum output power."""
    if controller.I_sw_max is None:
        raise ValueError("Controller lacks I_sw_max parameter")
    return eta * V_in * D * controller.I_sw_max * 0.5


def primary_inductance_min_off(controller: Controller, N_ps: float, V_out: float, V_f: float) -> float:
    """Minimum primary inductance due to minimum off time."""
    if controller.t_off_min is None or controller.I_sw_min is None:
        raise ValueError("Controller lacks t_off_min or I_sw_min")
    return controller.t_off_min * N_ps * (V_out + V_f) / controller.I_sw_min


def primary_inductance_min_on(controller: Controller, V_in: float) -> float:
    """Minimum primary inductance due to minimum on time."""
    if controller.t_on_min is None or controller.I_sw_min is None:
        raise ValueError("Controller lacks t_on_min or I_sw_min")
    return controller.t_on_min * V_in / controller.I_sw_min
