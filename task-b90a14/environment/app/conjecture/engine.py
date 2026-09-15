"""
Test execution engine. Runs test functions against choice sequences
and manages the overall testing process.
"""

import random
import string
from .data import (
    ChoiceNode, ChoiceType, ConjectureData, ConjectureResult,
    Status, StopTest,
)


def run_test_function(test_fn, choices):
    """
    Run a test function with the given choice sequence.

    The test function receives a ConjectureData object and draws choices from it.
    Returns a ConjectureResult.
    """
    data = ConjectureData(choices=choices)
    try:
        test_fn(data)
    except StopTest:
        pass
    except Exception as e:
        data.status = Status.INTERESTING
        data.interesting_origin = type(e).__name__
    return data.freeze()


def generate_random_choices(n, label_pool=None):
    """Generate a random choice sequence of length n."""
    if label_pool is None:
        label_pool = ["a", "b", "c", "d", "e"]
    choices = []
    for _ in range(n):
        ctype = random.choice(list(ChoiceType))
        label = random.choice(label_pool)
        if ctype == ChoiceType.INTEGER:
            val = random.randint(0, 1000)
        elif ctype == ChoiceType.BOOLEAN:
            val = random.choice([True, False])
        else:
            length = random.randint(0, 10)
            val = "".join(random.choices(string.ascii_lowercase, k=length))
        choices.append(ChoiceNode(type=ctype, value=val, label=label))
    return choices
