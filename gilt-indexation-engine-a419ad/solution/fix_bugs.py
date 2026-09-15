"""
Fix 5 bugs in gilt_engine.cpp:

1. RPI interpolation denominator: (D-1) -> D
2. Hardcoded lag=3 ignoring parameter: use lag_months
3. v1 discount factor: pow(v2, xi) -> pow(v2, 1.0-xi)
4. Ex-div accrued interest: return 0 -> return (xi-1)*coupon
   Also fix AI_y in clean_price_from_yield for ex-div
5. Newton-Raphson step sign: += -> -=
"""


with open("/app/gilt_engine.cpp", "r") as f:
    code = f.read()

# Bug 1: Interpolation denominator (D-1) should be D
code = code.replace(
    "(double)(D - 1);",
    "(double)(D);"
)

# Bug 2: Hardcoded lag=3 shadows the lag_months parameter
code = code.replace(
    "// Standard 3-month lag for daily interpolation\n    int lag = 3;",
    "int lag = lag_months;"
)

# Bug 3: v1 uses wrong exponent (xi instead of 1-xi)
code = code.replace(
    "double v1 = std::pow(v2, xi);",
    "double v1 = std::pow(v2, 1.0 - xi);"
)

# Bug 4a: Ex-div physical accrued interest returns 0 instead of (xi-1)*coupon
code = code.replace(
    "// Buyer does not receive the next coupon\n        return 0.0;",
    "// Buyer does not receive the next coupon — AI is negative\n        return (xi - 1.0) * coupon_per_period;"
)

# Bug 4b: AI_y in clean_price_from_yield doesn't handle ex-div
code = code.replace(
    "double ai_y = xi * coupon;\n    return dirty - ai_y;",
    "double ai_y = ex_div ? (xi - 1.0) * coupon : xi * coupon;\n    return dirty - ai_y;"
)

# Bug 5: Newton-Raphson step sign error: += should be -=
code = code.replace(
    "y += diff / deriv;",
    "y -= diff / deriv;"
)

with open("/app/gilt_engine.cpp", "w") as f:
    f.write(code)

print("All 5 bugs fixed in gilt_engine.cpp")
