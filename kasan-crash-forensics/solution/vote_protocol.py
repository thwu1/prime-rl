
"""
Multi-VM patch verification voting protocol.
Implements the classification and aggregation logic used by
kernel APR evaluation frameworks (RGym-style 26-VM protocol).
"""


def classify_patch(results):
    """
    Classify a patch based on multi-VM test results.

    Args:
        results: list of dicts, each with:
            vm_id: int
            outcome: str - one of "no_crash", "crash_same",
                     "crash_different", "boot_fail", "timeout"

    Returns:
        dict with:
            verdict: str - "Pass", "Trigger", "Racey", or "BootFail"
            confidence: float - 0.0 to 1.0
            details: dict - breakdown of outcome counts
    """
    total = len(results)
    if total == 0:
        return {
            'verdict': 'Pass',
            'confidence': 0.0,
            'details': {},
        }

    counts = {
        'no_crash': 0,
        'crash_same': 0,
        'crash_different': 0,
        'boot_fail': 0,
        'timeout': 0,
    }
    for r in results:
        outcome = r.get('outcome', 'timeout')
        if outcome in counts:
            counts[outcome] += 1

    crash_count = counts['crash_same'] + counts['crash_different']
    clean_count = counts['no_crash'] + counts['timeout']
    boot_fails = counts['boot_fail']

    # Priority 1: Any boot failure
    if boot_fails > 0:
        verdict = 'BootFail'
        confidence = boot_fails / total

    # Priority 2: All clean (no crashes)
    elif crash_count == 0:
        verdict = 'Pass'
        confidence = clean_count / total

    # Priority 3: Majority crash (>50%)
    elif crash_count > total / 2:
        verdict = 'Trigger'
        confidence = counts['crash_same'] / total

    # Priority 4: Mixed results
    else:
        verdict = 'Racey'
        confidence = 1.0 - abs(crash_count - clean_count) / total

    return {
        'verdict': verdict,
        'confidence': round(confidence, 4),
        'details': {
            'total_vms': total,
            'no_crash': counts['no_crash'],
            'crash_same': counts['crash_same'],
            'crash_different': counts['crash_different'],
            'boot_fail': boot_fails,
            'timeout': counts['timeout'],
        },
    }


def compute_pass_rate(configs):
    """
    Compute pass rate for each APR configuration.

    Args:
        configs: dict mapping config_name -> list of verdict strings
                 e.g. {"config_a": ["Pass", "Trigger", "Pass"]}

    Returns:
        dict mapping config_name -> float (0.0-1.0)
    """
    result = {}
    for name, verdicts in configs.items():
        if not verdicts:
            result[name] = 0.0
        else:
            passes = sum(1 for v in verdicts if v == 'Pass')
            result[name] = passes / len(verdicts)
    return result


def compute_unique_solves(configs):
    """
    Identify bugs uniquely solved by each configuration.

    A bug is "solved" if the verdict is "Pass". A bug is "uniquely solved"
    by config X if X solves it but no other config does.

    Args:
        configs: dict mapping config_name -> dict of {bug_id: verdict}
                 e.g. {"config_a": {"bug_1": "Pass", "bug_2": "Trigger"}}

    Returns:
        dict mapping config_name -> set of uniquely solved bug IDs
    """
    # Collect all bug IDs
    all_bugs = set()
    for results in configs.values():
        all_bugs.update(results.keys())

    unique = {name: set() for name in configs}

    for bug in all_bugs:
        # Find which configs solved this bug
        solvers = [
            name for name, results in configs.items()
            if results.get(bug) == 'Pass'
        ]
        if len(solvers) == 1:
            unique[solvers[0]].add(bug)

    return unique
