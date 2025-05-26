"""Design formulas for LT8300-based flyback converters."""


def feedback_resistor(V_out: float, V_f: float, I_Rfb: float, N_ps: float) -> float:
    """Calculate feedback resistor from output voltage and turns ratio."""
    return N_ps * (V_out + V_f) / I_Rfb


def duty_cycle(V_in: float, V_out: float, V_f: float, N_ps: float) -> float:
    """Switch duty cycle."""
    return (V_out + V_f) * N_ps / ((V_out + V_f) * N_ps + V_in)


def output_power(V_in: float, eta: float, D: float, I_sw_max: float) -> float:
    """Maximum output power."""
    return eta * V_in * D * I_sw_max * 0.5


def primary_inductance_min_off(N_ps: float, V_out: float, V_f: float, t_off_min: float, I_sw_min: float) -> float:
    """Minimum primary inductance due to minimum off time."""
    return t_off_min * N_ps * (V_out + V_f) / I_sw_min


def primary_inductance_min_on(V_in: float, t_on_min: float, I_sw_min: float) -> float:
    """Minimum primary inductance due to minimum on time."""
    return t_on_min * V_in / I_sw_min
