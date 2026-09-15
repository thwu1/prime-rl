"""
Fix build issues, runtime bugs, and implement analytics for the gilt engine.

Build fix:
- Add analytics.o to Makefile OBJS and add its build rule

Bug fixes in rpi.cpp:
1. RPI interpolation denominator: (D-1) -> D
2. Hardcoded lag=3 shadows the lag_months parameter

Bug fixes in pricing.cpp:
3. v1 discount factor exponent: pow(v2, xi) -> pow(v2, 1.0 - xi)
4. Ex-div accrued interest returns 0 instead of (xi - 1) * coupon
5. AI_y in clean_price_from_yield not adjusted for ex-div
6. Newton-Raphson update: += -> -=
7. General case loop exponent: pow(v2, i - 2) -> pow(v2, i - 1)

Implementation:
- analytics.cpp: modified_duration, convexity, bpv, breakeven_inflation
"""


# --- Fix Makefile: add analytics.o ---
with open("/app/Makefile", "r") as f:
    makefile = f.read()

makefile = makefile.replace(
    "OBJS = main.o rpi.o schedule.o pricing.o",
    "OBJS = main.o rpi.o schedule.o pricing.o analytics.o"
)

# Append analytics build rule before clean target
makefile = makefile.replace(
    "clean:",
    "analytics.o: analytics.cpp analytics.h pricing.h date_utils.h\n"
    "\t$(CXX) $(CXXFLAGS) -c analytics.cpp\n\n"
    "clean:"
)

with open("/app/Makefile", "w") as f:
    f.write(makefile)

# --- Fix rpi.cpp ---
with open("/app/rpi.cpp", "r") as f:
    code = f.read()

# Bug 1: Interpolation denominator (D-1) -> D
code = code.replace(
    "(double)(D - 1);",
    "(double)(D);"
)

# Bug 2: Hardcoded lag=3 shadows parameter
code = code.replace(
    "int lag = 3;",
    "int lag = lag_months;"
)

with open("/app/rpi.cpp", "w") as f:
    f.write(code)

# --- Fix pricing.cpp ---
with open("/app/pricing.cpp", "r") as f:
    code = f.read()

# Bug 3: v1 exponent (xi -> 1-xi)
code = code.replace(
    "double v1 = std::pow(v2, xi);",
    "double v1 = std::pow(v2, 1.0 - xi);"
)

# Bug 4: Ex-div accrued interest returns 0 instead of (xi-1)*coupon
code = code.replace(
    "return 0.0;  // ex-div: buyer doesn't receive next coupon",
    "return (xi - 1.0) * coupon_per_period;  // ex-div: negative AI"
)

# Bug 5: AI_y not adjusted for ex-div in clean_price_from_yield
code = code.replace(
    "double ai_y = xi * coupon;\n    return dirty - ai_y;",
    "double ai_y = ex_div ? (xi - 1.0) * coupon : xi * coupon;\n    return dirty - ai_y;"
)

# Bug 6: Newton-Raphson sign error
code = code.replace(
    "y += diff / deriv;",
    "y -= diff / deriv;"
)

# Bug 7: General case loop exponent (i-2 -> i-1)
code = code.replace(
    "std::pow(v2, i - 2)",
    "std::pow(v2, i - 1)"
)

with open("/app/pricing.cpp", "w") as f:
    f.write(code)

# --- Implement analytics.cpp ---
analytics_impl = '''#include "analytics.h"
#include "pricing.h"
#include <cmath>


double modified_duration(double yield_rate, double coupon_rate, int n_remaining,
                         double xi, int freq, bool ex_div) {
    double dy = 0.0001;
    double p = dirty_price_from_yield(yield_rate, coupon_rate, n_remaining,
                                       xi, freq, ex_div);
    double p_up = dirty_price_from_yield(yield_rate + dy, coupon_rate, n_remaining,
                                          xi, freq, ex_div);
    double p_dn = dirty_price_from_yield(yield_rate - dy, coupon_rate, n_remaining,
                                          xi, freq, ex_div);
    return -(p_up - p_dn) / (2.0 * dy * p);
}

double convexity(double yield_rate, double coupon_rate, int n_remaining,
                 double xi, int freq, bool ex_div) {
    double dy = 0.0001;
    double p = dirty_price_from_yield(yield_rate, coupon_rate, n_remaining,
                                       xi, freq, ex_div);
    double p_up = dirty_price_from_yield(yield_rate + dy, coupon_rate, n_remaining,
                                          xi, freq, ex_div);
    double p_dn = dirty_price_from_yield(yield_rate - dy, coupon_rate, n_remaining,
                                          xi, freq, ex_div);
    return (p_up - 2.0 * p + p_dn) / (dy * dy * p);
}

double bpv(double modified_dur, double dirty_price) {
    return modified_dur * dirty_price / 10000.0;
}

double breakeven_inflation(double index_ratio, const Date& effective,
                           const Date& settlement) {
    int days = days_between(effective, settlement);
    double years = (double)days / 365.25;
    if (years <= 0.0) return 0.0;
    return std::pow(index_ratio, 1.0 / years) - 1.0;
}
'''

with open("/app/analytics.cpp", "w") as f:
    f.write(analytics_impl)

print("All fixes applied and analytics implemented.")
