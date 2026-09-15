#!/usr/bin/env python3
"""Fix all mathematical bugs in the LVQ implementation.

Bugs fixed:
1. gmlvq.py _optimize: omega normalization uses sum of all elements of
   omega.T @ omega instead of the trace (sum of diagonal). Must use
   np.sum(np.diag(...)) for trace normalization.
2a. gmlvq.py _optfun: regularization term has wrong sign (+ instead of -).
    Log-determinant regularization should be subtracted to reward large
    determinant and prevent degeneracy.
2b. gmlvq.py _optgrad: regularization gradient has wrong sign (+ instead of -),
    matching the cost function bug.
3. rslvq.py posterior: returns raw cost ratios s1/s2 instead of
   exp-normalized probabilities. Must use softmax-style normalization
   (log-sum-exp) like the existing _p() method.
4. rslvq.py _optgrad: gradient multiplication missing negation sign.
   The cost function returns -log_likelihood, so the gradient of the
   positive log-likelihood must be negated to match.
"""

import re


def fix_gmlvq():
    with open('/app/lvq/gmlvq.py', 'r') as f:
        code = f.read()

    # Bug 1: omega normalization - use trace (np.diag) not full sum
    code = code.replace(
        'np.sum(self.omega_.T.dot(self.omega_))',
        'np.sum(np.diag(self.omega_.T.dot(self.omega_)))'
    )

    # Bug 2a: regularization sign in cost function
    code = code.replace(
        'return np.vectorize(self.phi)(mu).sum(0) + reg_term',
        'return np.vectorize(self.phi)(mu).sum(0) - reg_term'
    )

    # Bug 2b: regularization sign in gradient
    code = code.replace(
        '* lr_relevances * gw + self.regularization * f3',
        '* lr_relevances * gw - self.regularization * f3'
    )

    with open('/app/lvq/gmlvq.py', 'w') as f:
        f.write(code)
    print("Fixed gmlvq.py: omega normalization, regularization sign (cost + gradient)")


def fix_rslvq():
    with open('/app/lvq/rslvq.py', 'r') as f:
        code = f.read()

    # Bug 3: posterior must use exp normalization, not raw cost ratios
    old_body = (
        "        s1 = sum([self._costf(x, self.w_[i]) for i in\n"
        "                  range(self.w_.shape[0]) if\n"
        "                  self.c_w_[i] == y])\n"
        "        s2 = sum([self._costf(x, w) for w in self.w_])\n"
        "        return s1 / s2"
    )
    new_body = (
        "        fs = [self._costf(x, w) for w in self.w_]\n"
        "        fs_max = max(fs)\n"
        "        s_total = sum([np.math.exp(f - fs_max) for f in fs])\n"
        "        s_class = sum([np.math.exp(self._costf(x, self.w_[i]) - fs_max)\n"
        "                       for i in range(self.w_.shape[0])\n"
        "                       if self.c_w_[i] == y])\n"
        "        return s_class / s_total"
    )
    code = code.replace(old_body, new_body)

    # Bug 4: gradient sign - missing negation
    code = code.replace(
        "g *= (1 + 0.0001 * (random_state.rand(*g.shape) - 0.5))",
        "g *= -(1 + 0.0001 * (random_state.rand(*g.shape) - 0.5))"
    )

    with open('/app/lvq/rslvq.py', 'w') as f:
        f.write(code)
    print("Fixed rslvq.py: posterior exp normalization, gradient negation")


if __name__ == '__main__':
    fix_gmlvq()
    fix_rslvq()
    print("All bugs fixed successfully.")
