"""
Stack Monoid Parallel Bracket Analyzer - Interface Specification

Implement all functions in /app/stack_monoid.py.
This file defines the expected types and signatures.
"""

from dataclasses import dataclass, field
from typing import List, Dict


@dataclass
class StackMonoidElement:
    """
    A stack monoid element representing a sequence of stack operations:
    first n_pops elements are popped, then each element in pushes is pushed.

    The pushes list contains integer indices (positions of open brackets
    in the input string).

    Two StackMonoidElements are equal iff their n_pops and pushes are equal.
    """
    n_pops: int = 0
    pushes: list = field(default_factory=list)


# Required exports from /app/stack_monoid.py:
#
# StackMonoidElement  - dataclass as defined above (must support == comparison)
# identity()          - returns the monoid identity element
# combine(a, b)       - monoid binary operation; must be associative
# map_token(index, token) - map a single bracket character at position index
#                           to its StackMonoidElement representation
# parallel_inclusive_scan(elements) - work-efficient inclusive prefix scan
#                                     using Blelloch up-sweep / down-sweep
# analyze(tokens)     - given a bracket string, return dict with keys
#                       "matches", "parents", "depths" (each a list of ints)
