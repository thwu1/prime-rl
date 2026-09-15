"""Validation script for the bracket analysis pipeline."""

import sys

sys.path.insert(0, '/app')
from pipeline import analyze


def sequential_reference(tokens):
    """Simple sequential bracket analysis for ground truth."""
    n = len(tokens)
    matches = [-1] * n
    parents = [-1] * n
    depths = [0] * n
    stack = []
    for i in range(n):
        if tokens[i] == '[':
            depths[i] = len(stack)
            parents[i] = stack[-1] if stack else -1
            stack.append(i)
        elif tokens[i] == ']':
            if stack:
                j = stack.pop()
                matches[i] = j
                matches[j] = i
                depths[i] = len(stack)
                parents[i] = parents[j]
            else:
                depths[i] = 0
                parents[i] = -1
    return {"matches": matches, "parents": parents, "depths": depths}


def check(tokens, label=""):
    result = analyze(tokens)
    expected = sequential_reference(tokens)
    ok = result == expected
    status = "PASS" if ok else "FAIL"
    display = tokens[:50] + ('...' if len(tokens) > 50 else '')
    print(f"[{status}] {label}: {display}")
    if not ok:
        for key in ["matches", "parents", "depths"]:
            if result[key] != expected[key]:
                got = str(result[key][:20])
                exp = str(expected[key][:20])
                if len(result[key]) > 20:
                    got += "..."
                    exp += "..."
                print(f"  {key}: got    {got}")
                print(f"  {key}: expect {exp}")
    return ok


if __name__ == "__main__":
    cases = [
        ("[]", "simple pair"),
        ("[[]]", "nested"),
        ("[][]", "sequential"),
        ("[[][[][][[]]][][]]", "complex"),
        ("]][[", "unbalanced mixed"),
        ("[[[", "all opens"),
        ("]]]", "all closes"),
        ("[[[]", "extra open"),
        ("[]]", "extra close"),
        ("][", "close-open"),
        ("[" * 50 + "]" * 50, "deep nesting"),
        ("[]" * 30, "alternating"),
    ]
    passed = sum(check(t, l) for t, l in cases)
    print(f"\n{passed}/{len(cases)} passed")
