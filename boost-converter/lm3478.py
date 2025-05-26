"""Design formulas for the LM3478 boost converter."""

import math


def duty_cycle(V_in: float, V_out: float, V_q: float = 0.0, V_f: float = 0.0) -> float:
    """Calculate continuous conduction mode duty cycle."""
    return 1 - (V_in - V_q) / (V_out + V_f)


def min_inductor_ccm(D: float, V_in: float, f_sw: float, I_out: float) -> float:
    """Minimum inductance to maintain CCM."""
    return D * (1 - D) * V_in / (2 * f_sw * I_out)


def inductor_ripple_current(V_in: float, D: float, f_sw: float, L: float) -> float:
    """Inductor ripple current."""
    return D * V_in / (2 * f_sw * L)


def inductor_value_for_ripple(V_in: float, D: float, f_sw: float, I_ripple: float) -> float:
    """Inductor value required for a given ripple current."""
    return D * V_in / (2 * f_sw * I_ripple)


def diode_peak_current(I_L_peak: float, D: float, I_out: float) -> float:
    """Peak diode current."""
    return I_L_peak - D * I_out


def sense_resistor(V_sense: float, ratio_V_sl: float, I_limit: float, D: float) -> float:
    """Calculate sense resistor value for a desired current limit."""
    return (V_sense - (D * V_sense * ratio_V_sl)) / I_limit


def sense_resistor_limit(V_sl: float, f_sw: float, L: float, V_out: float, V_in: float) -> float:
    """Maximum sense resistor before external slope compensation is required."""
    return (2 * V_sl * f_sw * L) / (V_out - 2 * V_in)


def mosfet_losses(I_L: float, I_L_peak: float, I_L_valley: float, D: float, V_out: float,
                  R_ds_on: float, temp_factor: float, t_LH: float, t_HL: float, f_sw: float) -> tuple:
    """Return MOSFET conduction and switching losses."""
    P_cond = I_L ** 2 * R_ds_on * temp_factor * D
    P_sw = 0.5 * I_L_peak * V_out * t_LH * f_sw + 0.5 * I_L_valley * V_out * t_HL * f_sw
    return P_cond, P_sw, P_cond + P_sw


def capacitor_rms_currents(I_ripple: float, D: float, I_out: float) -> tuple:
    """Return input and output capacitor RMS currents."""
    I_cin = I_ripple / math.sqrt(3)
    I_cout = math.sqrt((1 - D) * ((I_out ** 2 * D / (1 - D)) + I_ripple ** 2 / 3))
    return I_cin, I_cout
