
// Test harness for robust incircle predicate.
// Build: g++ -O2 -frounding-math -o test_incircle test_incircle.cpp
// This file must NOT be modified by the solver.

#include "incircle.h"
#include <cstdio>
#include <cmath>
#include <cstdlib>

static int g_pass = 0;
static int g_fail = 0;

static void check(const char* name, int got, int expected) {
    if (got == expected) {
        g_pass++;
    } else {
        g_fail++;
        printf("FAIL %s: expected %d, got %d\n", name, expected, got);
    }
}

// ---- Test group 1: Basic cases ----
static void test_basic() {
    // Unit circle points (CCW): (1,0), (0,1), (-1,0)
    double a[] = {1.0, 0.0};
    double b[] = {0.0, 1.0};
    double c[] = {-1.0, 0.0};

    // Origin is inside
    double d_inside[] = {0.0, 0.0};
    check("basic_inside", robust::incircle(a, b, c, d_inside), 1);

    // (0, -2) is outside
    double d_outside[] = {0.0, -2.0};
    check("basic_outside", robust::incircle(a, b, c, d_outside), -1);

    // (0, -1) is on the circle
    double d_on[] = {0.0, -1.0};
    check("basic_on_circle", robust::incircle(a, b, c, d_on), 0);
}

// ---- Test group 2: Coordinate-based API ----
static void test_coord_api() {
    int r1 = robust::incircle(1.0, 0.0, 0.0, 1.0, -1.0, 0.0, 0.0, 0.0);
    check("coord_api_inside", r1, 1);
    int r2 = robust::incircle(1.0, 0.0, 0.0, 1.0, -1.0, 0.0, 0.0, -2.0);
    check("coord_api_outside", r2, -1);
}

// ---- Test group 3: Adversarial near-cocircular ----
static void test_adversarial() {
    // Case 1: Large-radius circle. R = 2^30, perturbation = 2^-22.
    {
        double R = 1073741824.0; // 2^30
        double eps = 2.384185791015625e-07; // 2^-22
        double a[] = {R, 0.0};
        double b[] = {0.0, R};
        double c[] = {-R, 0.0};
        double d[] = {0.0, -(R - eps)}; // barely inside
        check("adversarial_large_radius", robust::incircle(a, b, c, d), 1);
    }

    // Case 2: Points translated far from origin
    {
        double tx = 1e15, ty = 1e15;
        double a[] = {tx + 1.0, ty + 0.0};
        double b[] = {tx + 0.0, ty + 1.0};
        double c[] = {tx - 1.0, ty + 0.0};
        double d[] = {tx + 0.0, ty + 0.0}; // center, clearly inside
        check("adversarial_translated", robust::incircle(a, b, c, d), 1);
    }

    // Case 3: Cocircular (all four exactly on unit circle) -> 0
    {
        double a[] = {1.0, 0.0};
        double b[] = {0.0, 1.0};
        double c[] = {-1.0, 0.0};
        double d[] = {0.0, -1.0};
        check("adversarial_cocircular", robust::incircle(a, b, c, d), 0);
    }

    // Case 4: 3-4-5 triangle circumscribed circle, d just barely inside
    {
        double a[] = {0.0, 0.0};
        double b[] = {4.0, 0.0};
        double c[] = {0.0, 3.0};
        double eps = 1e-14;
        double d[] = {2.0, -1.0 + eps}; // just inside
        check("adversarial_345_inside", robust::incircle(a, b, c, d), 1);
    }
}

// ---- Test group 4: Degenerate/collinear ----
static void test_degenerate() {
    double a[] = {0.0, 0.0};
    double b[] = {1.0, 0.0};
    double c[] = {2.0, 0.0};
    double d_above[] = {1.0, 1.0};
    double d_below[] = {1.0, -1.0};
    double d_online[] = {3.0, 0.0};

    int r1 = robust::incircle(a, b, c, d_above);
    int r2 = robust::incircle(a, b, c, d_below);
    int r3 = robust::incircle(a, b, c, d_online);
    check("degenerate_opposite", (r1 == -r2) ? 1 : 0, 1);
    check("degenerate_online", r3, 0);
}

// ---- Test group 5: Symmetry and sign convention ----
static void test_symmetry() {
    double a[] = {1.0, 0.0};
    double b[] = {0.0, 1.0};
    double c[] = {-1.0, 0.0};
    double d[] = {0.0, 0.0};

    int r_abc = robust::incircle(a, b, c, d);
    int r_bac = robust::incircle(b, a, c, d);
    check("symmetry_swap_negates", r_abc, -r_bac);

    int r_bca = robust::incircle(b, c, a, d);
    check("symmetry_cyclic_preserves", r_abc, r_bca);
}

// ---- Test group 6: Large coordinates stress test ----
static void test_large_coords() {
    double cx_c = 1e12, cy_c = 1e12, R = 1e8;
    double a[] = {cx_c + R, cy_c};
    double b[] = {cx_c, cy_c + R};
    double c[] = {cx_c - R, cy_c};
    double d_center[] = {cx_c, cy_c};
    check("large_coords_inside", robust::incircle(a, b, c, d_center), 1);
    double d_far[] = {cx_c, cy_c - 2.0 * R};
    check("large_coords_outside", robust::incircle(a, b, c, d_far), -1);
}

// ---- Test group 7: Expansion arithmetic stress ----
static void test_expansion_stress() {
    // Case 1: d at (small_eps, -1), just outside unit circle
    {
        double a[] = {1.0, 0.0};
        double b[] = {0.0, 1.0};
        double c[] = {-1.0, 0.0};
        double eps = 1e-10;
        double d[] = {eps, -1.0};
        int r = robust::incircle(a, b, c, d);
        check("expansion_small_outside", r, -1);
    }

    // Case 2: d at (0, -1+delta), just inside unit circle
    {
        double a[] = {1.0, 0.0};
        double b[] = {0.0, 1.0};
        double c[] = {-1.0, 0.0};
        double dy = -1.0 + 5e-16;
        double d[] = {0.0, dy};
        int r = robust::incircle(a, b, c, d);
        check("expansion_tiny_inside", r, 1);
    }

    // Case 3: Powers of 2, exactly cocircular
    {
        double a[] = {1048576.0, 0.0};       // 2^20
        double b[] = {0.0, 1048576.0};
        double c[] = {-1048576.0, 0.0};
        double d[] = {0.0, -1048576.0};
        check("expansion_powers_cocircular", robust::incircle(a, b, c, d), 0);
    }

    // Case 4: Tight near-cocircular, large power-of-2 radius
    {
        double R = 65536.0; // 2^16
        double a[] = {R, 0.0};
        double b[] = {0.0, R};
        double c[] = {-R, 0.0};
        double eps = 1.4551915228366852e-11; // 2^-36
        double d[] = {0.0, -(R - eps)};
        check("expansion_tight_inside", robust::incircle(a, b, c, d), 1);
    }
}

// ---- Test group 8: Near-ULP adversarial (requires exact arithmetic) ----
static void test_near_ulp() {
    // Case 1: Unit circle, d perturbed by 1 ULP from cocircular -> inside
    {
        double a[] = {1.0, 0.0};
        double b[] = {0.0, 1.0};
        double c[] = {-1.0, 0.0};
        double d[] = {0.0, std::nextafter(-1.0, 0.0)}; // -1 + 2^-52
        check("ulp_unit_inside", robust::incircle(a, b, c, d), 1);
    }

    // Case 2: Unit circle, d perturbed by 1 ULP outward -> outside
    {
        double a[] = {1.0, 0.0};
        double b[] = {0.0, 1.0};
        double c[] = {-1.0, 0.0};
        double d[] = {0.0, std::nextafter(-1.0, -2.0)}; // -1 - 2^-52
        check("ulp_unit_outside", robust::incircle(a, b, c, d), -1);
    }

    // Case 3: R=2^24 circle, 1 ULP inside
    {
        double R = 16777216.0; // 2^24
        double a[] = {R, 0.0};
        double b[] = {0.0, R};
        double c[] = {-R, 0.0};
        double d[] = {0.0, std::nextafter(-R, 0.0)};
        check("ulp_2p24_inside", robust::incircle(a, b, c, d), 1);
    }

    // Case 4: R=2^24 circle, 1 ULP outside
    {
        double R = 16777216.0; // 2^24
        double a[] = {R, 0.0};
        double b[] = {0.0, R};
        double c[] = {-R, 0.0};
        double d[] = {0.0, std::nextafter(-R, -2.0 * R)};
        check("ulp_2p24_outside", robust::incircle(a, b, c, d), -1);
    }
}

// ---- Test group 9: Off-center circle with ULP perturbation ----
static void test_shifted_adversarial() {
    // Circle centered at (7, 11), radius 13
    // Points: (20,11), (7,24), (-6,11) are CCW on this circle
    // d = (7, -2) is on the circle (distance from center = 13)

    // Case 1: d perturbed 1 ULP inward -> inside
    {
        double a[] = {20.0, 11.0};
        double b[] = {7.0, 24.0};
        double c[] = {-6.0, 11.0};
        double d[] = {7.0, std::nextafter(-2.0, 0.0)};
        check("shifted_ulp_inside", robust::incircle(a, b, c, d), 1);
    }

    // Case 2: d perturbed 1 ULP outward -> outside
    {
        double a[] = {20.0, 11.0};
        double b[] = {7.0, 24.0};
        double c[] = {-6.0, 11.0};
        double d[] = {7.0, std::nextafter(-2.0, -3.0)};
        check("shifted_ulp_outside", robust::incircle(a, b, c, d), -1);
    }
}

// ---- Test group 10: Pythagorean-triple cocircular ----
static void test_cocircular_exact() {
    // Four Pythagorean-triple points on circle of radius 5
    // (3,4), (-3,4), (-4,-3), (4,-3) all have |p| = 5
    {
        double a[] = {3.0, 4.0};
        double b[] = {-3.0, 4.0};
        double c[] = {-4.0, -3.0};
        double d[] = {4.0, -3.0};
        check("cocircular_pyth5", robust::incircle(a, b, c, d), 0);
    }

    // Four points on circle of radius 13
    // (5,12), (-5,12), (-12,-5), (12,-5) all have |p| = 13
    {
        double a[] = {5.0, 12.0};
        double b[] = {-5.0, 12.0};
        double c[] = {-12.0, -5.0};
        double d[] = {12.0, -5.0};
        check("cocircular_pyth13", robust::incircle(a, b, c, d), 0);
    }
}

int main() {
    test_basic();
    test_coord_api();
    test_adversarial();
    test_degenerate();
    test_symmetry();
    test_large_coords();
    test_expansion_stress();
    test_near_ulp();
    test_shifted_adversarial();
    test_cocircular_exact();

    printf("\n=== Results: %d passed, %d failed ===\n", g_pass, g_fail);
    if (g_fail == 0) {
        printf("ALL_TESTS_PASSED\n");
        return 0;
    } else {
        printf("SOME_TESTS_FAILED\n");
        return 1;
    }
}
