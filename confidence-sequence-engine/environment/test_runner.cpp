#include <iostream>
#include <cmath>
#include <cstdlib>
#include <string>


#include "uniform_boundaries.h"

static int g_pass = 0, g_fail = 0, g_error = 0;

void expect_near(const char* name, double actual, double expected,
                 double tol = 1e-5) {
  if (std::abs(actual - expected) <= tol) {
    g_pass++;
    std::cout << "  PASS: " << name << std::endl;
  } else {
    g_fail++;
    std::cout << "  FAIL: " << name << " = " << actual
              << " (expected " << expected << ", diff="
              << std::abs(actual - expected) << ")" << std::endl;
  }
}

#define TEST_NEAR(expr, expected) \
  do { \
    try { \
      double _val = (expr); \
      expect_near(#expr, _val, expected); \
    } catch (const std::exception& e) { \
      g_error++; \
      std::cout << "  ERROR: " << #expr << " threw: " << e.what() \
                << std::endl; \
    } \
  } while(0)

#define TEST_PAIR(expr, exp_first, exp_second) \
  do { \
    try { \
      auto _pair = (expr); \
      expect_near(#expr ".first", _pair.first, exp_first); \
      expect_near(#expr ".second", _pair.second, exp_second); \
    } catch (const std::exception& e) { \
      g_error += 2; \
      std::cout << "  ERROR: " << #expr << " threw: " << e.what() \
                << std::endl; \
    } \
  } while(0)

int main() {
  using namespace confseq;

  const double V_OPT = 100;
  const double ALPHA_OPT = 0.05;
  const double ALPHA = 0.05;

  // All reference values verified against R implementation

  std::cout << "=== Two-Sided Normal Mixture ===" << std::endl;
  TEST_NEAR(TwoSidedNormalMixture::best_rho(V_OPT, ALPHA_OPT), 12.60056);
  TEST_NEAR(normal_log_mixture(10, 100, V_OPT, ALPHA_OPT, false), -0.6510052);
  TEST_NEAR(normal_mixture_bound(100, ALPHA, V_OPT, ALPHA_OPT, false),
            30.35209);

  std::cout << "\n=== One-Sided Normal Mixture ===" << std::endl;
  TEST_NEAR(normal_log_mixture(10, 100, V_OPT), -0.06502391);
  TEST_NEAR(normal_mixture_bound(100, ALPHA, V_OPT), 27.66071);

  std::cout << "\n=== Gamma-Exponential Mixture ===" << std::endl;
  TEST_NEAR(gamma_exponential_log_mixture(10, 100, V_OPT, 2), -0.2490165);
  TEST_NEAR(gamma_exponential_mixture_bound(100, ALPHA, V_OPT, 2), 33.02017);

  std::cout << "\n=== Gamma-Poisson Mixture ===" << std::endl;
  TEST_NEAR(gamma_poisson_log_mixture(10, 100, V_OPT, 2), -0.06991219);
  TEST_NEAR(gamma_poisson_mixture_bound(100, ALPHA, V_OPT, 2), 30.1949);

  std::cout << "\n=== Two-Sided Beta-Binomial Mixture ===" << std::endl;
  TEST_NEAR(
      beta_binomial_log_mixture(10, 100, V_OPT, 0.2, 0.8, ALPHA_OPT, false),
      -0.6941012);
  TEST_NEAR(
      beta_binomial_mixture_bound(100, ALPHA, V_OPT, 0.2, 0.8, ALPHA_OPT,
                                  false),
      31.4308);

  std::cout << "\n=== One-Sided Beta-Binomial Mixture ===" << std::endl;
  TEST_NEAR(beta_binomial_log_mixture(10, 100, V_OPT, 0.2, 0.8),
            -0.07134019);
  TEST_NEAR(beta_binomial_mixture_bound(100, ALPHA, V_OPT, 0.2, 0.8),
            28.41238);
  TEST_NEAR(
      beta_binomial_mixture_bound(2 * 0.2 * 0.8, 0.05, 100, 0.2, 0.8),
      2 * 0.8);

  std::cout << "\n=== Polynomial Stitching Bound ===" << std::endl;
  TEST_NEAR(poly_stitching_bound(100, ALPHA, 10, 3), 64.48755);
  TEST_NEAR(poly_stitching_bound(100, ALPHA, 10, -1), 28.99389);

  std::cout << "\n=== Bernoulli Confidence Interval ===" << std::endl;
  TEST_PAIR(bernoulli_confidence_interval(700, 1000, 0.05, 100),
            0.651629, 0.745949);
  TEST_PAIR(bernoulli_confidence_interval(15, 50, 0.05, 50),
            0.129556, 0.511896);
  TEST_PAIR(bernoulli_confidence_interval(5, 50, 0.05, 50),
            0.013021, 0.269264);
  TEST_PAIR(bernoulli_confidence_interval(1, 50, 0.05, 50),
            0.0, 0.13489);
  TEST_PAIR(bernoulli_confidence_interval(1, 2, 0.05, 50),
            0.0, 1.0);
  TEST_PAIR(bernoulli_confidence_interval(100, 200, 0.05, 1),
            0.328923, 0.671076);
  TEST_PAIR(bernoulli_confidence_interval(0, 1, 0.05, 50),
            0.0, 1.0);
  TEST_PAIR(bernoulli_confidence_interval(1, 1, 0.05, 50),
            0.0, 1.0);

  std::cout << "\n========================================" << std::endl;
  int total_issues = g_fail + g_error;
  std::cout << g_pass << " passed, " << g_fail << " failed, "
            << g_error << " errors" << std::endl;

  if (total_issues == 0) {
    std::cout << "ALL TESTS PASSED" << std::endl;
    return 0;
  }
  return 1;
}
