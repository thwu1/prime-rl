"""
Discrete integer interval operations.

An Interval represents a set of consecutive integers [start, end] (inclusive).
An IntervalSet is a collection of non-overlapping, sorted intervals with
automatic merging on insertion.
"""


class Interval:
    """A discrete integer interval [start, end] (inclusive on both sides)."""

    __slots__ = ('start', 'end')

    def __init__(self, start, end):
        if not isinstance(start, int) or not isinstance(end, int):
            raise TypeError("Endpoints must be integers")
        if start > end:
            raise ValueError(f"Invalid interval: start ({start}) > end ({end})")
        self.start = start
        self.end = end

    def overlaps(self, other):
        """Check if this interval shares at least one integer with another."""
        return self.start <= other.end and other.start <= self.end

    def adjacent(self, other):
        """Check if this interval is directly adjacent to another."""
        return self.end + 1 == other.start or other.end + 1 == self.start

    def contains(self, point):
        """Check if the interval contains the given integer."""
        return self.start <= point <= self.end

    def size(self):
        """Return the number of integers in the interval."""
        return self.end - self.start + 1

    def __eq__(self, other):
        if not isinstance(other, Interval):
            return NotImplemented
        return self.start == other.start and self.end == other.end

    def __hash__(self):
        return hash((self.start, self.end))

    def __repr__(self):
        return f"[{self.start}, {self.end}]"

    def __lt__(self, other):
        return (self.start, self.end) < (other.start, other.end)


class IntervalSet:
    """
    An ordered collection of non-overlapping intervals with automatic merging.
    Intervals are stored sorted by start value. Adding a new interval
    automatically merges it with any overlapping or adjacent existing intervals.

    Uses discrete integer semantics: [1, 3] represents {1, 2, 3}.
    Adjacent intervals like [1, 3] and [4, 6] should merge to [1, 6]
    since there is no integer gap between them.
    """

    def __init__(self, intervals=None):
        self._intervals = []
        if intervals:
            for iv in sorted(intervals, key=lambda x: x.start):
                self.add(iv)

    @property
    def intervals(self):
        """Return a copy of the internal interval list."""
        return list(self._intervals)

    def add(self, interval):
        """Add an interval, merging with any overlapping or adjacent intervals."""
        new_start = interval.start
        new_end = interval.end
        merged = []
        for existing in self._intervals:
            if existing.end < new_start or new_end < existing.start:
                merged.append(existing)
            else:
                new_start = min(new_start, existing.start)
                new_end = max(new_end, existing.end)
        merged.append(Interval(new_start, new_end))
        merged.sort(key=lambda iv: iv.start)
        self._intervals = merged

    def union(self, other):
        """Return the union of this set with another."""
        result = IntervalSet()
        for iv in self._intervals:
            result.add(iv)
        for iv in other._intervals:
            result.add(iv)
        return result

    def intersection(self, other):
        """Return the intersection of this set with another."""
        result = IntervalSet()
        i, j = 0, 0
        while i < len(self._intervals) and j < len(other._intervals):
            a = self._intervals[i]
            b = other._intervals[j]
            if a.start < b.end and b.start < a.end:
                start = max(a.start, b.start)
                end = min(a.end, b.end)
                result._intervals.append(Interval(start, end))
            if a.end < b.end:
                i += 1
            else:
                j += 1
        return result

    def complement(self, universe):
        """Return the complement of this set within the given universe interval."""
        result = IntervalSet()
        current = universe.start
        for iv in self._intervals:
            if iv.start > current:
                result._intervals.append(Interval(current, iv.start - 1))
            current = iv.end + 1
        if current <= universe.end:
            result._intervals.append(Interval(current, universe.end))
        return result

    def difference(self, other):
        """Return self minus other (integers in self but not in other)."""
        result_intervals = []
        for iv in self._intervals:
            remaining = [iv]
            for other_iv in other._intervals:
                new_remaining = []
                for r in remaining:
                    if r.end < other_iv.start or other_iv.end < r.start:
                        new_remaining.append(r)
                    else:
                        if r.start < other_iv.start:
                            new_remaining.append(Interval(r.start, other_iv.start - 1))
                        if r.end > other_iv.end:
                            new_remaining.append(Interval(other_iv.end + 1, r.end))
                remaining = new_remaining
            result_intervals.extend(remaining)
        result = IntervalSet()
        result._intervals = sorted(result_intervals, key=lambda iv: iv.start)
        return result

    def symmetric_difference(self, other):
        """Return the symmetric difference: integers in exactly one of the two sets."""
        return self.difference(other).union(other.difference(self))

    def contains_point(self, point):
        """Check if any interval in the set contains the given point."""
        for iv in self._intervals:
            if iv.contains(point):
                return True
        return False

    def total_size(self):
        """Return the total count of integers across all intervals."""
        return sum(iv.size() for iv in self._intervals)

    def __len__(self):
        return len(self._intervals)

    def __eq__(self, other):
        if not isinstance(other, IntervalSet):
            return NotImplemented
        return self._intervals == other._intervals

    def __repr__(self):
        return "{" + ", ".join(str(iv) for iv in self._intervals) + "}"
