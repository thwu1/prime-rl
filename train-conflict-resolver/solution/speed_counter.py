
from decimal import Decimal
from fractions import Fraction
from typing import Optional, Tuple


SEGMENT_LENGTH: Fraction = Fraction(1)


def _to_fraction(v: Optional[float]) -> Optional[Fraction]:
    """Convert a float to a Fraction, with special handling for inverse-of-integer values."""
    if v is None:
        return None
    if isinstance(v, Fraction):
        return v
    if isinstance(v, Decimal):
        return Fraction.from_decimal(v)
    if isinstance(v, int):
        return Fraction(v)
    if isinstance(v, float):
        if v == 0.0:
            return Fraction(0)
        # Check if it's close to an integer
        if abs(v - round(v)) < 1e-9:
            return Fraction(round(v))
        # Check if it's close to 1/n for small n
        if v > 0:
            inv = 1.0 / v
            inv_rounded = round(inv)
            if inv_rounded > 0 and abs(inv - inv_rounded) < 1e-2:
                return Fraction(1, inv_rounded)
        # Fallback: use Decimal string conversion for exactness
        try:
            return Fraction.from_decimal(Decimal(str(v)))
        except Exception:
            return Fraction.from_float(v)
    raise ValueError(f"Cannot convert {v} to Fraction.")


def _cap_speed(max_speed: Fraction, speed: Fraction) -> Fraction:
    v = max(Fraction(0), min(max_speed, speed))
    return v


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
        """
        Step the speed counter. Advances distance by current speed.
        If speed is provided, update speed first (capped to max_speed).
        """
        if speed is not None:
            self._speed = _cap_speed(self._max_speed, _to_fraction(speed))

        self._distance += self._speed

        # Wrap distance if past segment boundary
        entered_new_cell = False
        while self._distance >= SEGMENT_LENGTH:
            self._distance -= SEGMENT_LENGTH
            entered_new_cell = True

        # is_cell_entry is True if we entered a new cell (distance wrapped past segment length)
        # which means distance < speed (we went past the boundary)
        self._is_cell_entry = self._distance < self._speed or entered_new_cell

    def is_cell_exit(self, speed: Fraction) -> bool:
        """
        With the given speed, will we exit the cell at next time step?
        i.e., distance + capped_speed >= SEGMENT_LENGTH
        """
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
