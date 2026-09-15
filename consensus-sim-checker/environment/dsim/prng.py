"""SplitMix64 deterministic pseudo-random number generator."""

import math


class DeterministicPRNG:
    MASK = (1 << 64) - 1
    GOLDEN = 0x9e3779b97f4a7c15
    MIX1 = 0xbf58476d1ce4e5b9
    MIX2 = 0x94d049bb133111eb

    def __init__(self, seed: int):
        self.state = seed & self.MASK

    def next_u64(self) -> int:
        self.state = (self.state + self.GOLDEN) & self.MASK
        z = self.state
        z = ((z ^ (z >> 30)) * self.MIX1) & self.MASK
        z = ((z ^ (z >> 27)) * self.MIX2) & self.MASK
        z = z ^ (z >> 31)
        return z

    def boolean(self) -> bool:
        return (self.next_u64() & 1) == 1

    def chance(self, numerator: int, denominator: int) -> bool:
        if denominator == 0 or numerator <= 0:
            return False
        if numerator >= denominator:
            return True
        return (self.next_u64() % denominator) < numerator

    def range_inclusive(self, low: int, high: int) -> int:
        if low == high:
            return low
        return low + (self.next_u64() % (high - low))

    def shuffle(self, lst: list) -> list:
        result = list(lst)
        for i in range(len(result) - 1, 0, -1):
            j = self.next_u64() % (i + 1)
            result[i], result[j] = result[j], result[i]
        return result

    def exponential(self, mean: float) -> float:
        if mean <= 0.0:
            return 0.0
        u = (self.next_u64() + 1.0) / (2 ** 64)
        return -mean * math.log(u)
