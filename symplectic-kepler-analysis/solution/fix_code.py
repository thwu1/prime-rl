#!/usr/bin/env python3
"""
Fix all defects in the benchmark codebase and extend it.

Bug 1 (methods.py - method_b): Second force evaluation uses q instead of
       q_new, breaking the kick-drift-kick symplectic splitting.

Bug 2 (methods.py - compose_method): Sign error in denominator of
       composition weight formula (2+c instead of 2-c).

Bug 3 (benchmark.py - convergence_test): Uses np.log2() to compute
       convergence orders, assuming constant step-size ratio of 2.
       Actual step_counts = [50,100,250,500,1250] have ratios of 2 and 2.5.

Extension: Add method_f = compose_method(method_d, 4) for 6th-order
           symplectic integration. Update benchmark to include method_f.
"""


def fix_methods():
    with open('/app/methods.py', 'r') as f:
        code = f.read()

    # Fix 1: method_b - second kick must use force at updated position
    code = code.replace(
        'p_new = p_half + 0.5 * dt * force_fn(q)',
        'p_new = p_half + 0.5 * dt * force_fn(q_new)'
    )

    # Fix 2: compose_method - denominator should be (2 - c) not (2 + c)
    code = code.replace(
        'w1 = 1.0 / (2.0 + c)',
        'w1 = 1.0 / (2.0 - c)'
    )

    # Extension: add method_f (6th-order Yoshida composition of method_d)
    code = code.replace(
        'method_d = compose_method(method_e, 2)',
        'method_d = compose_method(method_e, 2)\n\n\n'
        'method_f = compose_method(method_d, 4)'
    )

    with open('/app/methods.py', 'w') as f:
        f.write(code)
    print("Fixed and extended methods.py")


def fix_benchmark():
    with open('/app/benchmark.py', 'r') as f:
        code = f.read()

    # Fix 3: convergence order must use actual step-count ratio
    code = code.replace(
        'order = np.log2(errors[i - 1] / errors[i])',
        'ratio = step_counts[i] / step_counts[i - 1]\n'
        '            order = np.log(errors[i - 1] / errors[i]) / np.log(ratio)'
    )

    # Extension: add method_f import
    code = code.replace(
        'from methods import method_a, method_b, method_c, method_d, method_e, integrate',
        'from methods import method_a, method_b, method_c, method_d, method_e, method_f, integrate'
    )

    # Extension: add method_f to integrators dict
    code = code.replace(
        '"method_e": method_e,',
        '"method_e": method_e,\n        "method_f": method_f,'
    )

    with open('/app/benchmark.py', 'w') as f:
        f.write(code)
    print("Fixed and extended benchmark.py")


if __name__ == '__main__':
    fix_methods()
    fix_benchmark()
    print("All fixes and extensions applied.")
