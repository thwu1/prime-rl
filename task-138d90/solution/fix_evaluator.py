#!/usr/bin/env python3
"""Fix all 5 bugs in the evaluator.

Bug 1 - Greedy assignment score ordering:
    np.argsort(scores) sorts ASCENDING (lowest confidence first).
    The spec requires DESCENDING order (highest confidence first).
    Fix: np.argsort(-scores)

Bug 2 - Missing VOC-style precision interpolation:
    AP computation must apply the monotonic precision envelope before
    interpolating at recall sample points.
    Fix: precision = np.maximum.accumulate(precision[::-1])[::-1]

Bug 3 - AOE angle wrapping:
    abs(diff) does not handle the circular nature of angles.
    When yaw values are near +pi and -pi, the raw difference can be ~2*pi
    instead of the correct small angle.
    Fix: abs(arctan2(sin(diff), cos(diff)))

Bug 4 - CDS formula uses sum instead of mean:
    ap * (atm + asm + aom) gives values up to 3, not [0, 1].
    The spec says CDS = AP * mean(ATM, ASM, AOM).
    Fix: ap * np.mean([atm, asm, aom])

Bug 5 - Range filter uses L-infinity norm instead of L2:
    max(|tx|, |ty|, |tz|) is the Chebyshev distance.
    The spec requires Euclidean (L2) norm: sqrt(tx^2 + ty^2 + tz^2).
    Fix: np.sqrt(tx**2 + ty**2 + tz**2)
"""


def main():
    with open('/app/evaluator.py', 'r') as f:
        code = f.read()

    # Fix 1: Score sorting ascending -> descending
    code = code.replace(
        '    sorted_indices = np.argsort(scores)\n',
        '    sorted_indices = np.argsort(-scores)\n',
    )

    # Fix 2: Add VOC-style precision interpolation
    code = code.replace(
        '    recall_interp = np.linspace(0, 1, NUM_RECALL_SAMPLES, endpoint=True)\n'
        '    precision_interp = np.interp(recall_interp, recall, precision, right=0)',
        '    # VOC-style precision interpolation (monotonic envelope)\n'
        '    precision = np.maximum.accumulate(precision[::-1])[::-1]\n'
        '\n'
        '    recall_interp = np.linspace(0, 1, NUM_RECALL_SAMPLES, endpoint=True)\n'
        '    precision_interp = np.interp(recall_interp, recall, precision, right=0)',
    )

    # Fix 3: AOE wrapping
    code = code.replace(
        '    diff = dt[\'yaw\'] - gt[\'yaw\']\n'
        '    return abs(diff)',
        '    diff = dt[\'yaw\'] - gt[\'yaw\']\n'
        '    return abs(np.arctan2(np.sin(diff), np.cos(diff)))',
    )

    # Fix 4: CDS sum -> mean
    code = code.replace(
        '    cds = ap * (atm + asm + aom)\n',
        '    cds = ap * np.mean([atm, asm, aom])\n',
    )

    # Fix 5: Range L-inf -> L2
    code = code.replace(
        "    return max(abs(entry['tx']), abs(entry['ty']), abs(entry['tz']))",
        "    return np.sqrt(entry['tx']**2 + entry['ty']**2 + entry['tz']**2)",
    )

    with open('/app/evaluator.py', 'w') as f:
        f.write(code)

    print("Applied 5 fixes to /app/evaluator.py")


if __name__ == '__main__':
    main()
