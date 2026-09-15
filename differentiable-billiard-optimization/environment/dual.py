# Dual number implementation for forward-mode automatic differentiation

class Dual:
    __slots__ = ('real', 'dual')

    def __init__(self, real, dual=0.0):
        self.real = float(real)
        self.dual = float(dual)

    def __repr__(self):
        return f"Dual({self.real}, {self.dual})"

    def __add__(self, other):
        if isinstance(other, Dual):
            return Dual(self.real + other.real, self.dual + other.dual)
        return Dual(self.real + float(other), self.dual)

    def __radd__(self, other):
        return Dual(float(other) + self.real, self.dual)

    def __sub__(self, other):
        if isinstance(other, Dual):
            return Dual(self.real - other.real, self.dual - other.dual)
        return Dual(self.real - float(other), self.dual)

    def __rsub__(self, other):
        return Dual(float(other) - self.real, -self.dual)

    def __mul__(self, other):
        if isinstance(other, Dual):
            return Dual(self.real * other.real,
                        self.real * other.dual + self.dual * other.real)
        return Dual(self.real * float(other), self.dual * float(other))

    def __rmul__(self, other):
        return Dual(float(other) * self.real, float(other) * self.dual)

    def __truediv__(self, other):
        if isinstance(other, Dual):
            denom = other.real * other.real
            return Dual(self.real / other.real,
                        (self.dual * other.real + self.real * other.dual) / denom)
        return Dual(self.real / float(other), self.dual / float(other))

    def __rtruediv__(self, other):
        return Dual(float(other) / self.real,
                    -float(other) * self.dual / (self.real ** 2))

    def __neg__(self):
        return Dual(-self.real, -self.dual)

    def __lt__(self, other):
        r = other.real if isinstance(other, Dual) else float(other)
        return self.real < r

    def __gt__(self, other):
        r = other.real if isinstance(other, Dual) else float(other)
        return self.real > r

    def __le__(self, other):
        r = other.real if isinstance(other, Dual) else float(other)
        return self.real <= r

    def __ge__(self, other):
        r = other.real if isinstance(other, Dual) else float(other)
        return self.real >= r

    def sqrt(self):
        import math
        r = math.sqrt(self.real)
        return Dual(r, self.dual / (2.0 * r))
