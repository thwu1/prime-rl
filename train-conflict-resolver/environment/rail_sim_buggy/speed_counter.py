
from fractions import Fraction
from typing import Optional

SEGMENT_LENGTH: Fraction = Fraction(1)


def _to_fraction(v: Optional[float]) -> Optional[Fraction]:
    """Convert a numeric value to a Fraction."""
    if v is None:
        return None
    if isinstance(v, Fraction):
        return v
    if isinstance(v, int):
        return Fraction(v)
    if isinstance(v, float):
        if v == 0.0:
            return Fraction(0)
        if abs(v - round(v)) < 1e-9:
            return Fraction(round(v))
        return Fraction.from_float(v)
    raise ValueError(f"Cannot convert {v} to Fraction.")


def _cap_speed(max_speed: Fraction, speed: Fraction) -> Fraction:
    return max(Fraction(0), min(max_speed, speed))


class SpeedCounter:
    def __init__(self, speed: float, max_speed: float = None):
        self._speed: Fraction = _to_fraction(speed)
        self._distance: Fraction = Fraction(0)
        self._is_cell_entry: bool = True
        if max_speed is not None:
            self._max_speed: Fraction = _to_fraction(max_speed)
        else:
            self._max_speed = self._speed
        assert self._max_speed <= 1
        assert self._speed <= self._max_speed
        assert self._speed >= 0
        self.reset()

    def step(self, speed: Fraction = None):
        """Advance distance by current speed. Optionally set new speed first."""
        if speed is not None:
            self._speed = _cap_speed(self._max_speed, _to_fraction(speed))

        self._distance += self._speed

        while self._distance >= SEGMENT_LENGTH:
            self._distance -= SEGMENT_LENGTH

        self._is_cell_entry = (self._distance == Fraction(0))

    def is_cell_exit(self, speed: Fraction) -> bool:
        """With the given speed, will we exit the cell at the next step?"""
        capped = _cap_speed(self._max_speed, speed)
        return self._distance + capped >= SEGMENT_LENGTH

    def reset(self):
        self._distance = Fraction(0)
        self._is_cell_entry = True

    @property
    def speed(self) -> Fraction:
        return self._speed

    @property
    def max_speed(self) -> Fraction:
        return self._max_speed

    @property
    def distance(self) -> Fraction:
        return self._distance

    @property
    def is_cell_entry(self) -> bool:
        return self._is_cell_entry
