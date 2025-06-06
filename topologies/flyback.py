"""Generic flyback-converter design equations."""

from controllers import Controller
import math


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


def boundary_duty_cycle(Vin, Vout, Nps):
    """
    D_BOUND = Nps * Vout / (Nps * Vout + Vin)
    """
    return (Nps * Vout) / (Nps * Vout + Vin)


def dt_cycle(D, Fsw):
    """
    dt = D / F_sw
    """
    return D / Fsw


def peak_current(Vin, Lp, D, Fsw):
    """
    I_PK = (Vin/Lp) * dt = Vin * D / (Lp * Fsw)
    """
    return Vin * D / (Lp * Fsw)


def energy_inductor(Lp, Ipk):
    """
    E = 1/2 * Lp * Ipk^2
    """
    return 0.5 * Lp * Ipk**2


def boundary_power(Vin, D, Lp, Fsw):
    """
    P_BOUNDARY = Vin^2 * D^2 / (2 * Lp * Fsw)
    """
    return Vin**2 * D**2 / (2 * Lp * Fsw)


def voltage_ratio_DCM(D, Rload, Lp, Fsw):
    """
    Vout/Vin (DCM) = D * sqrt(Rload / (2 * Lp * Fsw))
    """
    return D * math.sqrt(Rload / (2 * Lp * Fsw))


def voltage_ratio_CCM(D, Nps):
    """
    Vout/Vin (CCM) = (D / Nps) / (1 - D)
    """
    return (D / Nps) / (1 - D)
