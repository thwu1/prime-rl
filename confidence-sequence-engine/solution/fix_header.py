#!/usr/bin/env python3
"""
Fix bugs and implement stubs in uniform_boundaries.h.

This script reads the broken header, identifies and fixes three mathematical
bugs, and implements four stubbed-out functions by computing the correct
mathematical formulas from the sequential inference framework.

"""

import re
import sys

HEADER_PATH = "/app/uniform_boundaries.h"

with open(HEADER_PATH, "r") as f:
    code = f.read()

original_len = len(code)

# =============================================================================
# BUG FIX 1: OneSidedNormalMixture::log_superMG uses pdf instead of cdf
#
# The one-sided normal mixture supermartingale formula requires the normal CDF
# (cumulative distribution function), not the PDF (probability density).
# The log supermartingale is:
#   (1/2) * log(4*rho/(v+rho)) + s^2/(2*(v+rho)) + log(Phi(s/sqrt(v+rho)))
# where Phi is the standard normal CDF.
# =============================================================================
code = code.replace(
    "log(boost::math::pdf(normal, s / sqrt(v + rho_)))",
    "log(boost::math::cdf(normal, s / sqrt(v + rho_)))",
)

# =============================================================================
# BUG FIX 2: GammaExponentialMixture::get_leading_constant uses gamma_q
#             instead of gamma_p
#
# The gamma-exponential mixture's leading constant uses the lower regularized
# incomplete gamma function (gamma_p), not the upper (gamma_q).
# Formula: rho/c^2 * log(rho/c^2) - lgamma(rho/c^2) - log(P(rho/c^2, rho/c^2))
# where P(a,x) = gamma_p(a,x) is the lower regularized incomplete gamma.
# =============================================================================
gamma_exp_old = """inline double GammaExponentialMixture::get_leading_constant(double rho,
                                                            double c) {
  const double rho_c_sq = rho / (c * c);
  return rho_c_sq * log(rho_c_sq)
      - boost::math::lgamma(rho_c_sq)
      - log(boost::math::gamma_q(rho_c_sq, rho_c_sq));
}"""

gamma_exp_new = """inline double GammaExponentialMixture::get_leading_constant(double rho,
                                                            double c) {
  const double rho_c_sq = rho / (c * c);
  return rho_c_sq * log(rho_c_sq)
      - boost::math::lgamma(rho_c_sq)
      - log(boost::math::gamma_p(rho_c_sq, rho_c_sq));
}"""

code = code.replace(gamma_exp_old, gamma_exp_new)

# =============================================================================
# BUG FIX 3: BetaBinomialMixture::log_superMG missing normalizer subtraction
#
# The beta-binomial log supermartingale must subtract the normalizer (which is
# the log of the incomplete beta evaluated at the mixing distribution's
# normalization point). Without this, the supermartingale is improperly scaled.
# =============================================================================
bb_old = """      + log_incomplete_beta((r_ + v - g_ * s) /  (g_ * (g_ + h_)),
                            (r_ + v + h_ * s) / (h_ * (g_ + h_)),
                            x);
}

inline double BetaBinomialMixture::s_upper_bound"""

bb_new = """      + log_incomplete_beta((r_ + v - g_ * s) /  (g_ * (g_ + h_)),
                            (r_ + v + h_ * s) / (h_ * (g_ + h_)),
                            x)
      - normalizer_;
}

inline double BetaBinomialMixture::s_upper_bound"""

code = code.replace(bb_old, bb_new)

# =============================================================================
# STUB IMPL 1: GammaPoissonMixture::get_leading_constant
#
# The gamma-Poisson mixture is the conjugate companion to gamma-exponential.
# Its leading constant uses gamma_q (upper regularized incomplete gamma)
# where gamma-exponential uses gamma_p (lower).
# Formula: rho/c^2 * log(rho/c^2) - lgamma(rho/c^2) - log(Q(rho/c^2, rho/c^2))
# =============================================================================
gp_lc_old = """inline double GammaPoissonMixture::get_leading_constant(double rho, double c) {
  // TODO: implement gamma-Poisson leading constant
  throw std::runtime_error("GammaPoissonMixture::get_leading_constant not implemented");
}"""

gp_lc_new = """inline double GammaPoissonMixture::get_leading_constant(double rho, double c) {
  const double rho_c_sq = rho / (c * c);
  return rho_c_sq * log(rho_c_sq)
      - boost::math::lgamma(rho_c_sq)
      - log(boost::math::gamma_q(rho_c_sq, rho_c_sq));
}"""

code = code.replace(gp_lc_old, gp_lc_new)

# =============================================================================
# STUB IMPL 2: GammaPoissonMixture::log_superMG
#
# The gamma-Poisson log supermartingale uses gamma_q and has a different
# variable arrangement than gamma-exponential.
# =============================================================================
gp_sm_old = """inline double GammaPoissonMixture::log_superMG(const double s, const double v)
    const {
  // TODO: implement gamma-Poisson log supermartingale
  throw std::runtime_error("GammaPoissonMixture::log_superMG not implemented");
}"""

gp_sm_new = """inline double GammaPoissonMixture::log_superMG(const double s, const double v)
    const {
  const double c_sq = c_ * c_;
  const double v_rho_csq = (v + rho_) / c_sq;
  const double cs_v_rho_csq = s / c_ + v_rho_csq;
  return leading_constant_
      + boost::math::lgamma(cs_v_rho_csq)
      + log(boost::math::gamma_q(cs_v_rho_csq, v_rho_csq))
      - cs_v_rho_csq * log(v_rho_csq)
      + v / c_sq;
}"""

code = code.replace(gp_sm_old, gp_sm_new)

# =============================================================================
# STUB IMPL 3: PolyStitchingBound::operator()
#
# The polynomial stitching bound uses epochs scaled by eta with crossing
# probability distributed via the Riemann zeta function.
# =============================================================================
ps_old = """inline double PolyStitchingBound::operator()(double v, double alpha) const {
  // TODO: implement polynomial stitching bound
  throw std::runtime_error("PolyStitchingBound::operator() not implemented");
}"""

ps_new = """inline double PolyStitchingBound::operator()(double v, double alpha) const {
  double use_v = std::max(v, v_min_);
  double ell = s_ * log(log(eta_ * use_v / v_min_)) + A_ + log(1 / alpha);
  double term2 = k2_ * c_ * ell;
  return sqrt(k1_ * k1_ * use_v * ell + term2 * term2) + term2;
}"""

code = code.replace(ps_old, ps_new)

# =============================================================================
# STUB IMPL 4: bernoulli_confidence_interval
#
# Uses bisection root-finding over the two-sided BetaBinomialMixture
# supermartingale to compute anytime-valid confidence bounds for the mean
# of a [0,1]-bounded distribution.
# =============================================================================
bci_old = """inline std::pair<double, double> bernoulli_confidence_interval(
    const double num_successes, const int num_trials, const double alpha,
    const double t_opt, const double alpha_opt) {
  // TODO: implement Bernoulli confidence interval using bisection
  // over the beta-binomial mixture supermartingale
  throw std::runtime_error("bernoulli_confidence_interval not implemented");
}"""

bci_new = """inline std::pair<double, double> bernoulli_confidence_interval(
    const double num_successes, const int num_trials, const double alpha,
    const double t_opt, const double alpha_opt) {
  using namespace std::placeholders;
  const double threshold = log(1 / alpha);
  const double empirical_p = 1.0 * num_successes / num_trials;

  auto objective = [empirical_p, num_trials, t_opt, alpha_opt, threshold]
                   (const double p, const double zero_value,
                    const double one_value) {
    if (p <= 0) {
      return zero_value;
    } else if (p >= 1) {
      return one_value;
    } else {
      const BetaBinomialMixture mixture(p * (1 - p) * t_opt, alpha_opt,
                                        p, 1 - p, false);
      const double log_superMG = mixture.log_superMG(
          (empirical_p - p) * num_trials, p * (1 - p) * num_trials);
      return log_superMG - threshold;
    }
  };

  boost::math::tools::eps_tolerance<double> tolerance(40);
  double lower_bound = 0.0;
  if (empirical_p > 0) {
    auto lower_bound_pair = boost::math::tools::bisect(
        std::bind(objective, _1, 1.0, -1.0), 0.0, empirical_p, tolerance);
    lower_bound = pair_average(lower_bound_pair);
  }
  double upper_bound = 1.0;
  if (empirical_p < 1) {
    auto upper_bound_pair = boost::math::tools::bisect(
        std::bind(objective, _1, -1.0, 1.0), empirical_p, 1.0, tolerance);
    upper_bound = pair_average(upper_bound_pair);
  }
  return std::make_pair(lower_bound, upper_bound);
}"""

code = code.replace(bci_old, bci_new)

# Verify all replacements were applied
assert len(code) != original_len, "No changes were made - replacement strings may not match"
assert "not implemented" not in code, "Some stubs were not replaced"
assert "boost::math::pdf(normal" not in code, "PDF bug was not fixed"
assert "// TODO:" not in code, "Some TODOs remain"

with open(HEADER_PATH, "w") as f:
    f.write(code)

print(f"Successfully patched {HEADER_PATH}")
print(f"  Original size: {original_len} bytes")
print(f"  Patched size:  {len(code)} bytes")
print(f"  Applied 3 bug fixes and 4 stub implementations")
