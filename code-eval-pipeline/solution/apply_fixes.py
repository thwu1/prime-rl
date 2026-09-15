#!/usr/bin/env python3
"""Apply all fixes to the broken evaluation harness."""


def fix_extractor():
    """Fix extractor.py:
    1. re.MULTILINE -> re.DOTALL (makes . match newlines for multi-line code blocks)
    2. Off-by-one in fallback: range(i+1, len(lines)) -> range(i+1, len(lines)+1)
    """
    with open('/app/harness/extractor.py') as f:
        src = f.read()
    src = src.replace('re.MULTILINE', 're.DOTALL')
    src = src.replace('range(i + 1, len(lines))', 'range(i + 1, len(lines) + 1)')
    with open('/app/harness/extractor.py', 'w') as f:
        f.write(src)


def fix_sandbox():
    """Fix sandbox.py:
    Missing newline between extracted code and test_code in check program assembly.
    """
    with open('/app/harness/sandbox.py') as f:
        src = f.read()
    src = src.replace(
        '+ code\n        + problem["test_code"]',
        '+ code\n        + "\\n" + problem["test_code"]'
    )
    with open('/app/harness/sandbox.py', 'w') as f:
        f.write(src)


def fix_metrics():
    """Fix metrics.py:
    Boundary condition: 'if c >= k' is wrong.
    Correct: 'if n - c < k' (pass@k = 1.0 when fewer failures than k).
    """
    with open('/app/harness/metrics.py') as f:
        src = f.read()
    src = src.replace('if c >= k:', 'if n - c < k:')
    with open('/app/harness/metrics.py', 'w') as f:
        f.write(src)


def fix_orchestrator():
    """Fix run_eval.sh:
    1. SQL temporal filter: release_date < -> release_date >=
    2. jq sort: ascending -> descending (add | reverse)
    """
    with open('/app/run_eval.sh') as f:
        src = f.read()
    src = src.replace("release_date < '", "release_date >= '")
    src = src.replace(
        'sort_by(.["pass@1"])',
        'sort_by(.["pass@1"]) | reverse'
    )
    with open('/app/run_eval.sh', 'w') as f:
        f.write(src)


if __name__ == '__main__':
    fix_extractor()
    fix_sandbox()
    fix_metrics()
    fix_orchestrator()
    print("All fixes applied.")
