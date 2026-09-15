"""
Delta debugging (ddmin) for 1-minimal input reduction.
"""


def ddmin(test_func, inp):
    """Reduce inp to a 1-minimal failing subsequence.

    test_func(s) must return 'FAIL' or 'PASS'.
    The initial inp must cause test_func to return 'FAIL'.
    """
    assert test_func(inp) == 'FAIL', "Initial input must fail"

    n = 2
    while len(inp) >= 2:
        subset_length = max(int(len(inp) / n), 1)
        start = 0
        some_complement_is_failing = False

        while start < len(inp):
            end = min(start + subset_length, len(inp))
            complement = inp[:start] + inp[end:]

            if len(complement) > 0 and test_func(complement) == 'FAIL':
                inp = complement
                n = max(n - 1, 2)
                some_complement_is_failing = True
                break

            start = end

        if not some_complement_is_failing:
            if n >= len(inp):
                break
            n = min(n * 2, len(inp))

    return inp
