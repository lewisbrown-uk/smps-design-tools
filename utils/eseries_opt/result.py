from dataclasses import dataclass


@dataclass
class Result:
    values: dict
    breakdown: dict
    error: float = 0.0
    sensitivity: float = 0.0

    def __str__(self):
        from utils.rounding import prefix
        parts = [f"{n}={prefix(v)}" for n, v in self.values.items()]
        s = f"{', '.join(parts)} | error={self.error:.4g}"
        if self.sensitivity:
            s += f" worst-case={self.sensitivity:.4g}"
        return s
