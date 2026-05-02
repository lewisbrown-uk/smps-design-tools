from dataclasses import dataclass


@dataclass
class Result:
    values: dict
    breakdown: dict
    error: float = 0.0
    sensitivity: float = 0.0
    """Worst-case composite error at the 2^N corners of a uniform ±tol
    perturbation of the chosen components. Pessimistic — assumes every
    component sits at its tolerance extreme pushing the same direction,
    which Gaussian-distributed real components essentially never do
    (typical 99th-percentile MC error is 2-4× lower than this number).

    Honest-but-rough first-look indicator only:

    - Treats the open-loop algebraic target as the system. Inside a
      feedback loop, component perturbations are absorbed until they
      push gain margin negative, at which point regulation collapses
      catastrophically — neither smooth nor captured here.
    - Uses one tolerance for all components; real designs mix 1% R
      with 5% C with 20% electrolytics.
    - Ignores active-device spreads (op-amp Vos / Avol, BJT β, FET
      Vto), which routinely swamp passive tolerances.

    For production yield numbers, evaluate the chosen Result against a
    closed-loop spec via simulation (ngspice / Bode / state-space)
    with realistic per-part spread models. That's a separate-library
    job — see the project README for the scope split."""

    def __str__(self):
        from utils.rounding import prefix
        parts = [f"{n}={prefix(v)}" for n, v in self.values.items()]
        s = f"{', '.join(parts)} | error={self.error:.4g}"
        if self.sensitivity:
            s += f" worst-case={self.sensitivity:.4g}"
        return s
