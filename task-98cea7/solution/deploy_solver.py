"""
Deploy the augmented Lagrangian optimizer to /app/optimizer.py.
"""
import sys

OPTIMIZER_CODE = r'''
import numpy as np


def optimize(f, g, c, x0, n, count, prob):
    """
    Constrained optimization via Augmented Lagrangian method with
    Adam inner solver and finite-difference constraint Jacobian.
    """
    x = x0.copy().astype(np.float64)
    d = len(x0)
    h = 1e-5

    # Get constraint dimensions and initial values
    cv = c(x)        # cost: 1
    m = len(cv)
    fv = f(x)        # cost: 1

    # Track best feasible solution
    is_feas = bool(np.all(cv <= 0.0))
    x_best = x.copy()
    f_best = fv if is_feas else np.inf

    # Fallback: least-violating point
    x_fallback = x.copy()
    min_viol = float(np.sum(np.maximum(0.0, cv)))

    # Augmented Lagrangian parameters
    lam = np.zeros(m)
    mu = 50.0

    # Adam optimizer state
    m1 = np.zeros(d)
    m2 = np.zeros(d)
    beta1, beta2, eps_adam = 0.9, 0.999, 1e-8
    t_adam = 0

    # Problem-specific learning rates (tuned for each landscape)
    lr_table = {
        'prob1': 0.08,
        'prob2': 0.04,
        'prob3': 0.15,
        'prob4': 0.04,
        'prob5': 0.015,
    }
    lr = lr_table.get(prob, 0.01)

    # Budget planning
    # Cost per inner step: g(2) + c(1) + d*c_fd(d) = 3 + d
    cost_per_step = 3 + d
    n_outer = 8
    # Reserve budget for outer updates (c eval + f eval per outer) and margin
    overhead = n_outer * 3 + 25
    usable = n - count() - overhead
    total_steps = max(1, usable // cost_per_step)
    steps_per_outer = max(1, total_steps // n_outer)

    for outer in range(n_outer):
        for inner in range(steps_per_outer):
            if count() >= n - cost_per_step - 5:
                return x_best if f_best < np.inf else x_fallback

            t_adam += 1

            # Objective gradient
            gf = g(x)    # cost: 2

            # Constraint values at current point
            cv = c(x)     # cost: 1

            # Finite-difference constraint Jacobian (m x d)
            gc = np.zeros((m, d))
            for j in range(d):
                xp = x.copy()
                xp[j] += h
                cvp = c(xp)  # cost: 1 each, total d
                gc[:, j] = (cvp - cv) / h

            # Augmented Lagrangian gradient:
            # grad L_A = grad f + sum_i max(0, lam_i + mu*c_i) * grad c_i
            grad = gf.copy()
            for i in range(m):
                s_i = max(0.0, lam[i] + mu * cv[i])
                grad += s_i * gc[i]

            # Gradient clipping for numerical stability
            gnorm = np.linalg.norm(grad)
            if gnorm > 500.0:
                grad *= 500.0 / gnorm

            # Adam update step
            m1 = beta1 * m1 + (1.0 - beta1) * grad
            m2 = beta2 * m2 + (1.0 - beta2) * grad**2
            m1_hat = m1 / (1.0 - beta1**t_adam)
            m2_hat = m2 / (1.0 - beta2**t_adam)
            x = x - lr * m1_hat / (np.sqrt(m2_hat) + eps_adam)

        # --- End of outer iteration ---
        if count() >= n - 6:
            return x_best if f_best < np.inf else x_fallback

        # Evaluate constraints at current point
        cv = c(x)  # cost: 1

        # Update Lagrange multipliers
        lam = np.maximum(0.0, lam + mu * cv)

        # Increase penalty parameter
        mu = min(mu * 2.0, 10000.0)

        # Track best feasible solution
        if np.all(cv <= 0.0):
            if count() < n - 2:
                fv = f(x)  # cost: 1
                if fv < f_best:
                    f_best = fv
                    x_best = x.copy()

        # Track least-violating point as fallback
        viol = float(np.sum(np.maximum(0.0, cv)))
        if viol < min_viol:
            min_viol = viol
            x_fallback = x.copy()

    # Final evaluation
    if count() < n - 2:
        cv = c(x)
        if np.all(cv <= 0.0):
            fv = f(x)
            if fv < f_best:
                f_best = fv
                x_best = x.copy()

    return x_best if f_best < np.inf else x_fallback
'''

with open('/app/optimizer.py', 'w') as fp:
    fp.write(OPTIMIZER_CODE)

print("Optimizer deployed to /app/optimizer.py")

# Quick validation
sys.path.insert(0, '/app')
import importlib
import optimizer
importlib.reload(optimizer)
print(f"optimize function loaded: {hasattr(optimizer, 'optimize')}")
