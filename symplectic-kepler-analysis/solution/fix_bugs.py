#!/usr/bin/env python3
"""
Fix all defects in the benchmark codebase.

Bug 1 (methods.py - method_b): Second force evaluation uses q instead of
       q_new, breaking the kick-drift-kick symplectic splitting. This
       destroys symplecticity and reduces the method to first order.

Bug 2 (methods.py - compose_method): Sign error in denominator of
       composition weight formula (2+c instead of 2-c). This prevents
       the negative middle coefficient needed for order elevation,
       leaving the composed method at the base order instead of base+2.

Bug 3 (benchmark.py - convergence_test): Uses np.log2() to compute
       convergence orders, which assumes a constant step-size refinement
       ratio of 2. The actual step_counts = [50,100,250,500,1250] have
       ratios of 2 and 2.5, causing oscillating order estimates.
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

    with open('/app/methods.py', 'w') as f:
        f.write(code)
    print("Fixed methods.py")


def fix_benchmark():
    with open('/app/benchmark.py', 'r') as f:
        code = f.read()

    # Fix 3: convergence order must use actual step-count ratio
    code = code.replace(
        'order = np.log2(errors[i - 1] / errors[i])',
        'ratio = step_counts[i] / step_counts[i - 1]\n            order = np.log(errors[i - 1] / errors[i]) / np.log(ratio)'
    )

    with open('/app/benchmark.py', 'w') as f:
        f.write(code)
    print("Fixed benchmark.py")


if __name__ == "__main__":
    fix_methods()
    fix_benchmark()
    print("All defects fixed.")
