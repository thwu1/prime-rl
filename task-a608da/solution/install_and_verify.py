#!/usr/bin/env python3
"""Install the shrinker implementation and run a quick sanity check."""


import shutil
import sys

# Copy the implementation into place
shutil.copy("/solution/shrinker_impl.py", "/app/shrinker.py")
print("Wrote shrinker implementation to /app/shrinker.py")

# Quick verification
sys.path.insert(0, "/app")
from choiceseq import Choice, ChoiceConstraints, ChoiceKind
from runner import ConjectureData
from shrinker import Shrinker


def smoke_test(data: ConjectureData):
    x = data.draw_integer(min_value=0, max_value=1000)
    assert x < 42


choices = [Choice(ChoiceKind.INTEGER, 789, ChoiceConstraints(min_value=0, max_value=1000))]
shrinker = Shrinker(smoke_test, choices)
result = shrinker.shrink()
assert result[0].value == 42, f"Expected 42, got {result[0].value}"
print(f"Verification passed: shrunk 789 -> {result[0].value} in {shrinker.calls} calls")
