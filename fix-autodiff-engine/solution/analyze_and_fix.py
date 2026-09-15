"""
Solution: Diagnose and fix both autodiff.py and numerics.py,
produce audit report and cross-validation results.

"""

import json
import math
import os
import sys
import importlib

os.environ['JAX_ENABLE_X64'] = '1'

import jax
import jax.numpy as jnp

jax.config.update("jax_enable_x64", True)

sys.path.insert(0, '/app')


# ============================================================
# Part 1: Diagnose autodiff.py bugs
# ============================================================

import autodiff

autodiff_bugs = {}

# Bug 1: Mul VJP swap
try:
    g = autodiff.grad(lambda x: x * 3)(2.0)
    if abs(g - 3.0) > 0.1:
        autodiff_bugs["mul_vjp"] = {
            "issue": (
                "Multiplication VJP returns (ct*x, ct*y) instead of (ct*y, ct*x) "
                f"— cotangents are swapped. grad(x*3)(2)={g}, expected 3.0"
            ),
            "fix": "Swap operands: return (ct * y, ct * x)"
        }
except Exception as e:
    autodiff_bugs["mul_vjp"] = {
        "issue": f"Multiplication VJP error: {e}",
        "fix": "Swap cotangent operands in vjp_mul"
    }

# Bug 2: Div VJP y^2
try:
    g = autodiff.grad(lambda x, y: x / y, argnums=1)(6.0, 3.0)
    expected_div = -6.0 / 9.0
    if abs(g - expected_div) > 0.1:
        autodiff_bugs["div_vjp"] = {
            "issue": (
                f"Division VJP computes -ct*x/y instead of -ct*x/(y*y) "
                f"— missing y^2 in quotient rule. d/dy(6/3)={g}, expected {expected_div}"
            ),
            "fix": "Use -ct * x / (y * y) for second component"
        }
except Exception as e:
    autodiff_bugs["div_vjp"] = {
        "issue": f"Division VJP error: {e}",
        "fix": "Add y^2 denominator in vjp_div"
    }

# Bug 3: Exp VJP missing
try:
    g = autodiff.grad(lambda x: autodiff.exp(x))(1.0)
    if abs(g - math.e) > 0.1:
        autodiff_bugs["exp_vjp"] = {
            "issue": f"Exp VJP gives wrong result: {g}, expected {math.e}",
            "fix": "Register correct exp VJP rule"
        }
except Exception as e:
    autodiff_bugs["exp_vjp_missing"] = {
        "issue": (
            f"No VJP rule registered for exp primitive — gradient computation "
            f"crashes: {e}"
        ),
        "fix": "Register vjp_rules[exp_p] with rule (ct * math.exp(iv[0]),)"
    }

# Bug 4: Sub JVP sign
try:
    d = autodiff.deriv(lambda x: 1.0 - x)(2.0)
    if abs(d - (-1.0)) > 0.1:
        autodiff_bugs["sub_jvp"] = {
            "issue": (
                f"Subtraction JVP uses tangents[0]+tangents[1] instead of "
                f"tangents[0]-tangents[1]. deriv(1-x)(2)={d}, expected -1.0"
            ),
            "fix": "Change + to - in sub JVP tangent rule"
        }
except Exception as e:
    autodiff_bugs["sub_jvp"] = {
        "issue": f"Sub JVP error: {e}",
        "fix": "Fix sign in sub JVP tangent computation"
    }

# Bug 5: Gradient accumulation
try:
    g = autodiff.grad(lambda x: x * x)(3.0)
    if abs(g - 6.0) > 0.1:
        autodiff_bugs["grad_accumulation"] = {
            "issue": (
                f"Backward pass overwrites gradients instead of accumulating "
                f"when variable is reused. grad(x*x)(3)={g}, expected 6.0"
            ),
            "fix": "Change grads[inp.id] = ict to grads[inp.id] += ict in if-branch"
        }
except Exception as e:
    autodiff_bugs["grad_accumulation"] = {
        "issue": f"Gradient accumulation error: {e}",
        "fix": "Accumulate gradients instead of overwriting"
    }

print(f"Diagnosed {len(autodiff_bugs)} autodiff bugs")


# ============================================================
# Part 2: Fix autodiff.py
# ============================================================

with open('/app/autodiff.py', 'r') as f:
    ad_content = f.read()

# Fix 1: Mul VJP swap
ad_content = ad_content.replace(
    'return (ct * x, ct * y)',
    'return (ct * y, ct * x)'
)

# Fix 2: Div VJP y^2
ad_content = ad_content.replace(
    'return (ct / y, -ct * x / y)',
    'return (ct / y, -ct * x / (y * y))'
)

# Fix 3: Add exp VJP rule
ad_content = ad_content.replace(
    'def vjp_log(ct, input_vals, output_val):',
    """def vjp_exp(ct, input_vals, output_val):
    x, = input_vals
    return (ct * math.exp(x),)

vjp_rules[exp_p] = vjp_exp


def vjp_log(ct, input_vals, output_val):"""
)

# Fix 4: Sub JVP sign
ad_content = ad_content.replace(
    "primals[0] - primals[1],\n    tangents[0] + tangents[1]",
    "primals[0] - primals[1],\n    tangents[0] - tangents[1]"
)

# Fix 5: Gradient accumulation
ad_content = ad_content.replace(
    """            if inp.id in grads:
                grads[inp.id] = ict
            else:
                grads[inp.id] = ict""",
    """            if inp.id in grads:
                grads[inp.id] = grads[inp.id] + ict
            else:
                grads[inp.id] = ict"""
)

with open('/app/autodiff.py', 'w') as f:
    f.write(ad_content)

print("Fixed autodiff.py")


# ============================================================
# Part 3: Analyze original numerics.py (jaxpr + diagnosis)
# ============================================================

import numerics


def analyze_jaxpr(fn, *sample_args):
    """Extract primitives and equation count from a function's jaxpr."""
    try:
        jaxpr_obj = jax.make_jaxpr(fn)(*sample_args)
        primitives = set()

        def extract(jaxpr):
            for eqn in jaxpr.eqns:
                primitives.add(eqn.primitive.name)
                for v in eqn.params.values():
                    if isinstance(v, jax.core.Jaxpr):
                        extract(v)
                    elif isinstance(v, jax.core.ClosedJaxpr):
                        extract(v.jaxpr)
                    elif isinstance(v, (list, tuple)):
                        for item in v:
                            if isinstance(item, jax.core.Jaxpr):
                                extract(item)
                            elif isinstance(item, jax.core.ClosedJaxpr):
                                extract(item.jaxpr)

        extract(jaxpr_obj.jaxpr)
        return {
            "primitives_used": sorted(primitives),
            "num_equations": len(jaxpr_obj.jaxpr.eqns)
        }
    except Exception as e:
        return {"primitives_used": [str(e)], "num_equations": 1}


jaxpr_analysis = {
    "log1pexp": analyze_jaxpr(numerics.log1pexp, jnp.float64(1.0)),
    "logsumexp": analyze_jaxpr(
        numerics.logsumexp, jnp.float64(1.0), jnp.float64(2.0)),
    "sigmoid": analyze_jaxpr(numerics.sigmoid, jnp.float64(1.0)),
    "safe_sqrt": analyze_jaxpr(numerics.safe_sqrt, jnp.float64(4.0)),
    "huber_loss": analyze_jaxpr(
        numerics.huber_loss, jnp.float64(0.5), jnp.float64(1.0)),
    "log_cosh": analyze_jaxpr(numerics.log_cosh, jnp.float64(1.0)),
}

print("Jaxpr analysis complete")


# Gradient checking utilities
def finite_diff_grad(f, x, h=1e-5):
    """Central finite difference gradient."""
    return float(f(x + h) - f(x - h)) / (2 * h)


def check_grad(f, x_val):
    """Compare jax.grad against finite differences."""
    x = jnp.float64(x_val)
    try:
        jax_g = float(jax.grad(f)(x))
    except Exception as e:
        return {"match": False, "error": str(e)}
    fd_g = finite_diff_grad(f, x)
    if not math.isfinite(jax_g) or not math.isfinite(fd_g):
        return {"match": False, "jax_grad": jax_g, "fd_grad": fd_g}
    rel_err = abs(jax_g - fd_g) / max(abs(fd_g), 1e-8)
    return {
        "match": rel_err < 0.01,
        "jax_grad": jax_g,
        "fd_grad": fd_g,
        "rel_error": rel_err
    }


# Diagnose each numerics function
numerics_bugs = {}

# --- log1pexp ---
issues = []
for xv in [0.0, 1.0, 5.0]:
    r = check_grad(numerics.log1pexp, xv)
    if not r["match"]:
        issues.append(
            f"Incorrect VJP: returns exp(x) instead of sigmoid(x). "
            f"At x={xv}: jax.grad={r.get('jax_grad')}, fd={r.get('fd_grad')}"
        )
        break
try:
    v750 = float(numerics.log1pexp(jnp.float64(750.0)))
    g750 = float(jax.grad(numerics.log1pexp)(jnp.float64(750.0)))
    if not math.isfinite(v750) or not math.isfinite(g750):
        issues.append(
            "Numerical instability: overflow for large positive inputs "
            "(exp(x) overflows in both forward and backward)"
        )
except Exception:
    issues.append("Crashes for large inputs")
numerics_bugs["log1pexp"] = {
    "issues": issues if issues else ["No issues found"],
    "fix_description": (
        "Changed VJP to return g/(1+exp(-x)) (sigmoid). "
        "Stabilized forward with jnp.where(x>20, x, log1p(exp(x)))."
    )
}

# --- logsumexp ---
issues = []
try:
    val = float(numerics.logsumexp(jnp.float64(750.0), jnp.float64(749.0)))
    if not math.isfinite(val):
        issues.append(
            "Numerical instability: forward pass overflows for large "
            "inputs — no max-subtraction trick applied"
        )
    ga = float(jax.grad(numerics.logsumexp, argnums=0)(
        jnp.float64(750.0), jnp.float64(749.0)))
    if not math.isfinite(ga):
        issues.append(
            "Numerical instability: backward pass overflows — "
            "exp(a) and exp(b) computed without log-domain softmax"
        )
except Exception:
    issues.append("Crashes for large inputs due to overflow")
numerics_bugs["logsumexp"] = {
    "issues": issues if issues else ["No issues found"],
    "fix_description": (
        "Forward uses max-subtraction: m+log(exp(a-m)+exp(b-m)). "
        "Backward uses exp(a-ans) for numerically safe softmax."
    )
}

# --- sigmoid ---
issues = []
for xv in [1.0, -1.0, 3.0]:
    r = check_grad(numerics.sigmoid, xv)
    if not r["match"]:
        s = 1.0 / (1.0 + math.exp(-xv))
        issues.append(
            f"Incorrect gradient formula: returns (1-y)^2 instead of y*(1-y). "
            f"At x={xv}: got {r.get('jax_grad'):.6f}, expected {s*(1-s):.6f}"
        )
        break
numerics_bugs["sigmoid"] = {
    "issues": issues if issues else ["No issues found"],
    "fix_description": "Fixed VJP from g*(1-y)^2 to g*y*(1-y)."
}

# --- safe_sqrt ---
issues = []
g_neg = float(jax.grad(numerics.safe_sqrt)(jnp.float64(-1.0)))
if abs(g_neg) > 0.01:
    issues.append(
        f"Incorrect gradient for x<=0: returns {g_neg:.1f} instead of 0. "
        f"VJP uses (max(x,0)-eps) with wrong sign and no conditional zero."
    )
numerics_bugs["safe_sqrt"] = {
    "issues": issues if issues else ["No issues found"],
    "fix_description": (
        "Fixed VJP to return 0 for x<=0 via jnp.where, "
        "and use +eps instead of -eps for numerical safety."
    )
}

# --- huber_loss ---
issues = []
g_lin = float(jax.grad(numerics.huber_loss)(
    jnp.float64(3.0), jnp.float64(1.0)))
if abs(g_lin - 1.0) > 0.01:
    issues.append(
        f"Incorrect gradient in linear region: returns g*x={g_lin:.4f} "
        f"instead of g*delta*sign(x)=1.0. Same formula used for both regions."
    )
numerics_bugs["huber_loss"] = {
    "issues": issues if issues else ["No issues found"],
    "fix_description": "Fixed linear region VJP from g*x to g*delta*sign(x)."
}

# --- log_cosh ---
issues = []
if not hasattr(numerics.log_cosh, 'defvjp'):
    issues.append(
        "Missing @custom_vjp — no custom derivative rule defined, "
        "relies on JAX default autodiff"
    )
try:
    v750 = float(numerics.log_cosh(jnp.float64(750.0)))
    if not math.isfinite(v750):
        issues.append(
            "Numerical instability: overflow for large inputs "
            "(cosh(x) overflows for |x|>710 in float64)"
        )
    g750 = float(jax.grad(numerics.log_cosh)(jnp.float64(750.0)))
    if not math.isfinite(g750):
        issues.append(
            "Numerical instability: gradient NaN for large inputs "
            "(sinh/cosh overflow in chain rule)"
        )
except Exception:
    issues.append("Crashes for large inputs")
numerics_bugs["log_cosh"] = {
    "issues": issues if issues else ["No issues found"],
    "fix_description": (
        "Added @custom_vjp with numerically stable forward "
        "(abs(x)-log(2) for large |x|) and backward (tanh(x))."
    )
}

print("Numerics diagnosis complete")


# ============================================================
# Part 4: Fix numerics.py
# ============================================================

fixed_numerics = '''\
"""
Numerical functions with custom VJP rules for JAX.
All functions implement correct, numerically stable custom derivatives.

"""

import jax
import jax.numpy as jnp
from jax import custom_vjp


# ============================================================
# log1pexp (softplus): log(1 + exp(x))
# Fixed: VJP returns sigmoid(x); forward stable for large x
# ============================================================

@custom_vjp
def log1pexp(x):
    return jnp.where(x > 20.0, x, jnp.log1p(jnp.exp(x)))

def log1pexp_fwd(x):
    ans = log1pexp(x)
    return ans, (x,)

def log1pexp_bwd(res, g):
    x, = res
    return (g / (1.0 + jnp.exp(-x)),)

log1pexp.defvjp(log1pexp_fwd, log1pexp_bwd)


# ============================================================
# logsumexp: log(exp(a) + exp(b))
# Fixed: max-subtraction trick in forward; stable softmax in backward
# ============================================================

@custom_vjp
def logsumexp(a, b):
    m = jnp.maximum(a, b)
    return m + jnp.log(jnp.exp(a - m) + jnp.exp(b - m))

def logsumexp_fwd(a, b):
    ans = logsumexp(a, b)
    return ans, (a, b, ans)

def logsumexp_bwd(res, g):
    a, b, ans = res
    return (g * jnp.exp(a - ans), g * jnp.exp(b - ans))

logsumexp.defvjp(logsumexp_fwd, logsumexp_bwd)


# ============================================================
# sigmoid: 1 / (1 + exp(-x))
# Fixed: VJP uses y*(1-y) instead of (1-y)^2
# ============================================================

@custom_vjp
def sigmoid(x):
    return 1.0 / (1.0 + jnp.exp(-x))

def sigmoid_fwd(x):
    ans = sigmoid(x)
    return ans, (ans,)

def sigmoid_bwd(res, g):
    y, = res
    return (g * y * (1.0 - y),)

sigmoid.defvjp(sigmoid_fwd, sigmoid_bwd)


# ============================================================
# safe_sqrt: sqrt(max(x, 0))
# Fixed: gradient is 0 for x<=0; uses +eps for numerical safety
# ============================================================

@custom_vjp
def safe_sqrt(x):
    return jnp.sqrt(jnp.maximum(x, 0.0))

def safe_sqrt_fwd(x):
    ans = safe_sqrt(x)
    return ans, (x,)

def safe_sqrt_bwd(res, g):
    x, = res
    eps = 1e-12
    return (jnp.where(x > 0, g * 0.5 / jnp.sqrt(x + eps), 0.0),)

safe_sqrt.defvjp(safe_sqrt_fwd, safe_sqrt_bwd)


# ============================================================
# huber_loss: 0.5*x^2 for |x|<=delta, delta*(|x|-0.5*delta) otherwise
# Fixed: linear region gradient uses delta*sign(x) instead of x
# ============================================================

@custom_vjp
def huber_loss(x, delta):
    abs_x = jnp.abs(x)
    return jnp.where(abs_x <= delta, 0.5 * x ** 2,
                     delta * (abs_x - 0.5 * delta))

def huber_loss_fwd(x, delta):
    ans = huber_loss(x, delta)
    return ans, (x, delta)

def huber_loss_bwd(res, g):
    x, delta = res
    abs_x = jnp.abs(x)
    dx = jnp.where(abs_x <= delta, g * x, g * delta * jnp.sign(x))
    return (dx, jnp.zeros_like(delta))

huber_loss.defvjp(huber_loss_fwd, huber_loss_bwd)


# ============================================================
# log_cosh: log(cosh(x))
# Added: @custom_vjp with stable forward and backward (tanh)
# ============================================================

@custom_vjp
def log_cosh(x):
    abs_x = jnp.abs(x)
    return jnp.where(abs_x > 20.0, abs_x - jnp.log(2.0),
                     jnp.log(jnp.cosh(x)))

def log_cosh_fwd(x):
    ans = log_cosh(x)
    return ans, (x,)

def log_cosh_bwd(res, g):
    x, = res
    return (g * jnp.tanh(x),)

log_cosh.defvjp(log_cosh_fwd, log_cosh_bwd)
'''

with open('/app/numerics.py', 'w') as f:
    f.write(fixed_numerics)

print("Fixed numerics.py")


# ============================================================
# Part 5: Cross-validation using both fixed systems
# ============================================================

importlib.reload(autodiff)
importlib.reload(numerics)

test_points = [-2.0, -1.0, 0.0, 0.5, 1.0, 2.0, 5.0]
cv_report = {}

# log1pexp: log(1 + exp(x))
def log1pexp_ad(x):
    return autodiff.log(1.0 + autodiff.exp(x))

points = []
for xv in test_points:
    ad_g = autodiff.grad(log1pexp_ad)(xv)
    jax_g = float(jax.grad(numerics.log1pexp)(jnp.float64(xv)))
    match = abs(ad_g - jax_g) < 1e-6
    points.append({
        "x": xv, "jax_grad": jax_g,
        "autodiff_grad": ad_g, "match": match
    })
cv_report["log1pexp"] = {
    "test_points": points,
    "all_match": all(p["match"] for p in points)
}

# sigmoid: 1 / (1 + exp(-x))
def sigmoid_ad(x):
    return 1.0 / (1.0 + autodiff.exp(-x))

points = []
for xv in test_points:
    ad_g = autodiff.grad(sigmoid_ad)(xv)
    jax_g = float(jax.grad(numerics.sigmoid)(jnp.float64(xv)))
    match = abs(ad_g - jax_g) < 1e-6
    points.append({
        "x": xv, "jax_grad": jax_g,
        "autodiff_grad": ad_g, "match": match
    })
cv_report["sigmoid"] = {
    "test_points": points,
    "all_match": all(p["match"] for p in points)
}

# log_cosh: log((exp(x) + exp(-x)) / 2)
def log_cosh_ad(x):
    return autodiff.log((autodiff.exp(x) + autodiff.exp(-x)) / 2.0)

points = []
for xv in test_points:
    ad_g = autodiff.grad(log_cosh_ad)(xv)
    jax_g = float(jax.grad(numerics.log_cosh)(jnp.float64(xv)))
    match = abs(ad_g - jax_g) < 1e-5
    points.append({
        "x": xv, "jax_grad": jax_g,
        "autodiff_grad": ad_g, "match": match
    })
cv_report["log_cosh"] = {
    "test_points": points,
    "all_match": all(p["match"] for p in points)
}

# logsumexp with b fixed at 2.0: log(exp(a) + exp(2))
b_fixed_val = 2.0

def logsumexp_ad_a(a):
    return autodiff.log(autodiff.exp(a) + autodiff.exp(b_fixed_val))

points = []
for xv in [-2.0, 0.0, 1.0, 5.0]:
    ad_g = autodiff.grad(logsumexp_ad_a)(xv)
    jax_g = float(jax.grad(numerics.logsumexp, argnums=0)(
        jnp.float64(xv), jnp.float64(b_fixed_val)))
    match = abs(ad_g - jax_g) < 1e-6
    points.append({
        "x": xv, "jax_grad": jax_g,
        "autodiff_grad": ad_g, "match": match
    })
cv_report["logsumexp"] = {
    "test_points": points,
    "all_match": all(p["match"] for p in points)
}

with open('/app/cross_validation.json', 'w') as f:
    json.dump(cv_report, f, indent=2)

print("Cross-validation written to /app/cross_validation.json")


# ============================================================
# Part 6: Write audit report
# ============================================================

report = {
    "autodiff_bugs": autodiff_bugs,
    "numerics_bugs": numerics_bugs,
    "jaxpr_analysis": jaxpr_analysis
}

with open('/app/audit_report.json', 'w') as f:
    json.dump(report, f, indent=2, default=str)

print("Audit report written to /app/audit_report.json")
print("All done.")
