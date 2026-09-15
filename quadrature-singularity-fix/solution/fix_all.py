#!/usr/bin/env python3
"""
Fix all bugs in the numerical integration pipeline:
1. Makefile: fix GSL include path and add -lgslcblas
2. quad_wrapper.c: fix method-to-GSL-key mapping (0-indexed -> 1-indexed)
3. gsl_bridge.py: fix ctypes argtypes, restype, and byref calls
4. quadrature.py: fix error estimator, GK-21 parity, add infinite domains
"""

import re

# =================================================================
# Fix 1: Makefile — GSL include path + missing CBLAS linker flag
# =================================================================

with open('/app/Makefile', 'r') as f:
    makefile = f.read()

# Fix include path: /usr/local/include/gsl -> /usr/include/gsl
makefile = makefile.replace(
    '-I/usr/local/include/gsl',
    '-I/usr/include/gsl'
)

# Add -lgslcblas to linker flags
makefile = makefile.replace(
    'LDFLAGS = -lgsl -lm',
    'LDFLAGS = -lgsl -lgslcblas -lm'
)

with open('/app/Makefile', 'w') as f:
    f.write(makefile)

print("Fixed Makefile: include path and linker flags")


# =================================================================
# Fix 2: C wrapper — method-to-key mapping
# =================================================================
# GSL keys are 1-indexed: GSL_INTEG_GAUSS15=1, GSL_INTEG_GAUSS21=2, ...
# But our method indices are 0-indexed: 0=GK15, 1=GK21, ...
# The code passes key=method directly, which is off by one.

with open('/app/src/quad_wrapper.c', 'r') as f:
    c_code = f.read()

c_code = c_code.replace(
    'int key = method;',
    'int key = method + 1;'
)

with open('/app/src/quad_wrapper.c', 'w') as f:
    f.write(c_code)

print("Fixed C wrapper: method-to-key mapping (key = method + 1)")


# =================================================================
# Fix 3: gsl_bridge.py — ctypes declarations and calling convention
# =================================================================
# Three bugs:
# a) restype is c_int but should be c_double (return value is double)
# b) argtypes for output params are bare c_double/c_int instead of POINTER
# c) Output params passed by value instead of byref()

with open('/app/gsl_bridge.py', 'r') as f:
    bridge = f.read()

# Fix argtypes: output params need POINTER types
bridge = bridge.replace(
    """_lib.quad_integrate.argtypes = [
    INTEGRAND_FUNC,
    ctypes.c_double,
    ctypes.c_double,
    ctypes.c_double,
    ctypes.c_double,
    ctypes.c_int,
    ctypes.c_double,
    ctypes.c_int,
    ctypes.c_int,
]""",
    """_lib.quad_integrate.argtypes = [
    INTEGRAND_FUNC,
    ctypes.c_double,
    ctypes.c_double,
    ctypes.c_double,
    ctypes.c_double,
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_double),
    ctypes.POINTER(ctypes.c_int),
    ctypes.POINTER(ctypes.c_int),
]"""
)

# Fix restype: c_int -> c_double
bridge = bridge.replace(
    '_lib.quad_integrate.restype = ctypes.c_int',
    '_lib.quad_integrate.restype = ctypes.c_double'
)

# Fix calling convention: pass output params by reference
bridge = bridge.replace(
    '        abserr, neval, status',
    '        ctypes.byref(abserr), ctypes.byref(neval), ctypes.byref(status)'
)

with open('/app/gsl_bridge.py', 'w') as f:
    f.write(bridge)

print("Fixed gsl_bridge.py: argtypes, restype, byref")


# =================================================================
# Fix 4: quadrature.py — numerical bugs + infinite domain support
# =================================================================

with open('/app/quadrature.py', 'r') as f:
    content = f.read()

# Fix 4a: Error estimator in _adaptive
# abs(res_k) - abs(res_g) is wrong — it computes the difference of
# magnitudes, which can go negative. The correct Gauss-Kronrod error
# estimate is abs(res_k - res_g), the magnitude of the difference.
content = content.replace(
    'err = abs(res_k) - abs(res_g)',
    'err = abs(res_k - res_g)'
)

# Fix 4b: GK-21 Gauss node parity
# For embedded G-10 (even Gauss order), nodes sit at ODD Kronrod indices.
# For embedded G-7 in GK-15 (odd Gauss order), nodes sit at EVEN indices.
# Must change i % 2 == 0 to i % 2 == 1 ONLY inside _apply_gk21.
parts = content.split('def _apply_gk21')
assert len(parts) == 2, "Expected exactly one _apply_gk21 definition"

match = re.search(r'\ndef [a-zA-Z_]', parts[1])
if match:
    gk21_section = parts[1][:match.start()]
    after_gk21 = parts[1][match.start():]
else:
    gk21_section = parts[1]
    after_gk21 = ''

gk21_section = gk21_section.replace('i % 2 == 0', 'i % 2 == 1')
content = parts[0] + 'def _apply_gk21' + gk21_section + after_gk21

# Fix 4c: Add variable substitution helpers for infinite domains
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

# Fix 4d: Replace NotImplementedError blocks with working implementations

# Doubly-infinite (-inf, inf): split at 0 into two semi-infinite integrals
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

# Left-infinite (-inf, b]: transform to (0, 1]
content = content.replace(
    '    if a == -math.inf:\n'
    '        raise NotImplementedError(\n'
    '            "Integration over (-inf, b] is not yet supported."\n'
    '        )',
    '    if a == -math.inf:\n'
    '        g = _transform_left_inf(f, b)\n'
    '        return _adaptive(g, 0.0, 1.0, tol, max_depth)'
)

# Right-infinite [a, inf): transform to (0, 1]
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

print("Fixed quadrature.py: error estimator, GK-21 parity, infinite domains")
print("\nAll fixes applied successfully.")
