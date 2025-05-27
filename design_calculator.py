"""Orchestrates design calculations for a given controller and topology."""

from controllers import Controller
from topologies import boost, flyback


class DesignCalculator:
    """Run design formulas for different topologies."""

    def __init__(self, controller: Controller, topology: str):
        if topology not in controller.topologies:
            raise ValueError(f"Controller {controller.name} does not support {topology}")
        self.controller = controller
        self.topology = topology

    def duty_cycle(self, *args, **kwargs):
        if self.topology == "boost":
            return boost.duty_cycle(*args, **kwargs)
        if self.topology == "flyback":
            return flyback.duty_cycle(*args, **kwargs)
        raise ValueError(f"Unsupported topology {self.topology}")
