#!/usr/bin/env python3
"""
Fix numerical bugs in the adaptive Gauss-Kronrod quadrature library
and implement semi-infinite/doubly-infinite integration support.

Three fixes applied:
1. Error estimator: |K|-|G| -> |K-G|
   The Gauss-Kronrod error estimate is the absolute difference between
   the Kronrod and embedded Gauss approximations, not the difference
   of their magnitudes.

2. GK-21 Gauss node parity: even -> odd indices
   For embedded G-10 (even Gauss order), the Gauss-Legendre nodes sit
   at ODD Kronrod indices (1,3,5,7,9). For G-7 in GK-15 (odd Gauss
   order), they sit at EVEN indices (0,2,4,6). The GK-21 code
   incorrectly used even-index selection.

3. Variable substitutions for infinite domains:
   [a, inf)  -> (0, 1] via x = a + t/(1-t), Jacobian = 1/(1-t)^2
   (-inf, b] -> (0, 1] via x = b - (1-t)/t, Jacobian = 1/t^2
   (-inf, inf) -> split at 0 into two semi-infinite integrals
"""

import re

with open('/app/quadrature.py', 'r') as f:
    content = f.read()

# =================================================================
# Fix 1: Error estimator in _adaptive
# =================================================================
content = content.replace(
    'err = abs(res_k) - abs(res_g)',
    'err = abs(res_k - res_g)'
)

# =================================================================
# Fix 2: GK-21 Gauss node parity
# =================================================================
# Must change i % 2 == 0 to i % 2 == 1 ONLY inside _apply_gk21,
# not inside _apply_gk15 (where even parity is correct for G-7).
parts = content.split('def _apply_gk21')
assert len(parts) == 2, "Expected exactly one _apply_gk21 definition"

# Find where _apply_gk21 body ends (next top-level def)
match = re.search(r'\ndef [a-zA-Z_]', parts[1])
if match:
    gk21_section = parts[1][:match.start()]
    after_gk21 = parts[1][match.start():]
else:
    gk21_section = parts[1]
    after_gk21 = ''

gk21_section = gk21_section.replace('i % 2 == 0', 'i % 2 == 1')
content = parts[0] + 'def _apply_gk21' + gk21_section + after_gk21

# =================================================================
# Fix 3: Implement infinite-domain integration
# =================================================================

# 3a: Add variable substitution helper functions before integrate()
transform_code = '''

def _transform_right_inf(f, a):
    """Map [a, inf) to (0, 1] via x = a + t/(1-t)."""
    def g(t):
        if t <= 0.0 or t >= 1.0:
            return 0.0
        x = a + t / (1.0 - t)
        return f(x) / ((1.0 - t) ** 2)
    return g


def _transform_left_inf(f, b):
    """Map (-inf, b] to (0, 1] via x = b - (1-t)/t."""
    def g(t):
        if t <= 0.0 or t >= 1.0:
            return 0.0
        x = b - (1.0 - t) / t
        return f(x) / (t ** 2)
    return g

'''

idx = content.find('\ndef integrate(')
assert idx >= 0, "Could not find integrate() function"
content = content[:idx] + transform_code + content[idx:]

# 3b: Replace NotImplementedError blocks with working implementations

# Doubly-infinite: split at 0
content = content.replace(
    '    if a == -math.inf and b == math.inf:\n'
    '        raise NotImplementedError(\n'
    '            "Integration over (-inf, inf) is not yet supported. "\n'
    '            "A variable substitution mapping the real line to a "\n'
    '            "finite interval is required."\n'
    '        )',
    '    if a == -math.inf and b == math.inf:\n'
    '        r1, e1 = integrate(f, a, 0.0, tol / 2, max_depth)\n'
    '        r2, e2 = integrate(f, 0.0, b, tol / 2, max_depth)\n'
    '        return r1 + r2, e1 + e2'
)

# Left-infinite
content = content.replace(
    '    if a == -math.inf:\n'
    '        raise NotImplementedError(\n'
    '            "Integration over (-inf, b] is not yet supported."\n'
    '        )',
    '    if a == -math.inf:\n'
    '        g = _transform_left_inf(f, b)\n'
    '        return _adaptive(g, 0.0, 1.0, tol, max_depth)'
)

# Right-infinite
content = content.replace(
    '    if b == math.inf:\n'
    '        raise NotImplementedError(\n'
    '            "Integration over [a, inf) is not yet supported."\n'
    '        )',
    '    if b == math.inf:\n'
    '        g = _transform_right_inf(f, a)\n'
    '        return _adaptive(g, 0.0, 1.0, tol, max_depth)'
)

with open('/app/quadrature.py', 'w') as f:
    f.write(content)

print("All fixes applied to /app/quadrature.py")
