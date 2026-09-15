"""Z3 formal verification for IRC Section 121 properties.

"""

import json
from z3 import Real, RealVal, If, Solver, unsat, sat

results = []

# -----------------------------------------------------------------------
# Property 1: single_cap_bound
# For any single-filer computation, excluded_gain <= 250,000.
# -----------------------------------------------------------------------
gain = Real("gain")
depr = Real("depr")
nq_ratio = Real("nq_ratio")
cap = Real("cap")

s = Solver()
s.add(gain >= 0)
s.add(depr >= 0, depr <= gain)
s.add(nq_ratio >= 0, nq_ratio <= 1)
s.add(cap >= 0, cap <= 250000)

eligible = (gain - depr) * (1 - nq_ratio)
eligible_clamped = If(eligible < 0, RealVal(0), eligible)
excluded = If(eligible_clamped < cap, eligible_clamped, cap)
excluded_final = If(excluded < gain, excluded, gain)

s.add(excluded_final > 250000)
r = s.check()
results.append({
    "property": "single_cap_bound",
    "result": "proved" if r == unsat else "disproved",
    "solver_result": str(r),
})

# -----------------------------------------------------------------------
# Property 2: joint_cap_bound
# For any joint-filer computation, excluded_gain <= 500,000.
# -----------------------------------------------------------------------
gain2 = Real("gain2")
depr2 = Real("depr2")
nq_ratio2 = Real("nq_ratio2")
cap2 = Real("cap2")

s2 = Solver()
s2.add(gain2 >= 0)
s2.add(depr2 >= 0, depr2 <= gain2)
s2.add(nq_ratio2 >= 0, nq_ratio2 <= 1)
s2.add(cap2 >= 0, cap2 <= 500000)

elig2 = (gain2 - depr2) * (1 - nq_ratio2)
elig2_c = If(elig2 < 0, RealVal(0), elig2)
excl2 = If(elig2_c < cap2, elig2_c, cap2)
excl2_f = If(excl2 < gain2, excl2, gain2)

s2.add(excl2_f > 500000)
r2 = s2.check()
results.append({
    "property": "joint_cap_bound",
    "result": "proved" if r2 == unsat else "disproved",
    "solver_result": str(r2),
})

# -----------------------------------------------------------------------
# Property 3: reduced_leq_full
# For any base_cap >= 0 and days in [0, 730), reduced cap <= base_cap.
# -----------------------------------------------------------------------
base_cap = Real("base_cap")
days = Real("days")

s3 = Solver()
s3.add(base_cap >= 0)
s3.add(days >= 0, days < 730)

reduced = base_cap * days / 730
s3.add(reduced > base_cap)

r3 = s3.check()
results.append({
    "property": "reduced_leq_full",
    "result": "proved" if r3 == unsat else "disproved",
    "solver_result": str(r3),
})

# -----------------------------------------------------------------------
# Property 4: nq_use_can_reduce
# There exist inputs where NQ use reduces the excluded amount.
# -----------------------------------------------------------------------
gain4 = Real("gain4")
nq_r4 = Real("nq_r4")
cap4 = RealVal(250000)

s4 = Solver()
s4.add(gain4 > 0, gain4 <= 1000000)
s4.add(nq_r4 > 0, nq_r4 <= 1)

# Without NQ: excluded = min(gain, 250000)
excl_no_nq = If(gain4 < cap4, gain4, cap4)

# With NQ: excluded = min(max(0, gain * (1 - nq_ratio)), 250000)
elig_nq = gain4 * (1 - nq_r4)
elig_nq_c = If(elig_nq < 0, RealVal(0), elig_nq)
excl_nq = If(elig_nq_c < cap4, elig_nq_c, cap4)
excl_nq_f = If(excl_nq < gain4, excl_nq, gain4)

s4.add(excl_nq_f < excl_no_nq)

r4 = s4.check()
results.append({
    "property": "nq_use_can_reduce",
    "result": "witness_found" if r4 == sat else "no_witness",
    "solver_result": str(r4),
})

# -----------------------------------------------------------------------
# Write results
# -----------------------------------------------------------------------
with open("/app/verification_results.json", "w") as f:
    json.dump(results, f, indent=2)

print("Verification complete. Results written to /app/verification_results.json")
