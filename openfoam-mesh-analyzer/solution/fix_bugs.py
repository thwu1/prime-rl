#!/usr/bin/env python3
"""

Fix all four bugs in the mesh analysis pipeline.
"""


def fix_parser():
    """Bug 1: parser.py _normalize_grading swaps lengthFraction and cellFraction.

    The OpenFOAM multi-grading format is (lengthFraction cellFraction expansionRatio).
    The buggy code stores [seg[1], seg[0], seg[2]] (swapped first two fields)
    but the analyzer expects [lenFrac, cellFrac, expRatio] in standard order.
    Fix: use [seg[0], seg[1], seg[2]] to preserve the original order.
    """
    with open('/app/pipeline/parser.py') as f:
        code = f.read()
    code = code.replace(
        'segments.append([seg[1], seg[0], seg[2]])',
        'segments.append([seg[0], seg[1], seg[2]])'
    )
    with open('/app/pipeline/parser.py', 'w') as f:
        f.write(code)
    print("Fixed parser.py: multi-grading segment field order")


def fix_analyzer():
    """Bug 2: analyzer.py find_adjacencies uses > 4 instead of >= 4.

    Hex block faces share exactly 4 vertices. The strict inequality misses
    all face-sharing pairs, producing an empty adjacency list.
    Fix: change > 4 to >= 4.

    Bug 3: analyzer.py compute_cell_sizes uses R^(1/N) instead of R^(1/(N-1)).

    The expansion ratio R = last_cell / first_cell = r^(N-1) where r is the
    common ratio of the geometric series. Therefore r = R^(1/(N-1)), not R^(1/N).
    Fix: change 1.0 / N to 1.0 / (N - 1).
    """
    with open('/app/pipeline/analyzer.py') as f:
        code = f.read()
    # Bug 2: adjacency threshold
    code = code.replace(
        'if len(si & sj) > 4:',
        'if len(si & sj) >= 4:'
    )
    # Bug 3: grading formula exponent
    code = code.replace(
        'r = R ** (1.0 / N)',
        'r = R ** (1.0 / (N - 1))'
    )
    with open('/app/pipeline/analyzer.py', 'w') as f:
        f.write(code)
    print("Fixed analyzer.py: adjacency threshold and grading formula")


def fix_cht_solver():
    """Bug 4: cht_solver.py sign error in interface temperature.

    Heat flows from the heated solid into the fluid, so the solid-fluid
    interface must be hotter than the bulk fluid temperature.
    Newton's cooling: q_flux = h * (T_interface - T_f)
    Therefore: T_interface = T_f + q_flux / h  (not T_f - q_flux / h)
    """
    with open('/app/pipeline/cht_solver.py') as f:
        code = f.read()
    code = code.replace(
        'T_interface = T_f - q_flux / h_conv',
        'T_interface = T_f + q_flux / h_conv'
    )
    with open('/app/pipeline/cht_solver.py', 'w') as f:
        f.write(code)
    print("Fixed cht_solver.py: interface temperature sign")


if __name__ == '__main__':
    fix_parser()
    fix_analyzer()
    fix_cht_solver()
    print("\nAll 4 bugs fixed. Re-run the pipeline to regenerate mesh_report.json.")
