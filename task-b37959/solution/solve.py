#!/usr/bin/env python3

"""
Generalized Matrix Chain Optimizer with BLAS-aligned cost model,
kernel plan extraction, and CBLAS code generation.
"""

import json


def apply_transpose(mat):
    """Apply transpose flag: swap dims and transform property."""
    m = dict(mat)
    if m.get("transposed", False):
        m["rows"], m["cols"] = m["cols"], m["rows"]
        prop = m["property"]
        if prop == "upper_triangular":
            m["property"] = "lower_triangular"
        elif prop == "lower_triangular":
            m["property"] = "upper_triangular"
        # symmetric, diagonal, identity, general are invariant
        m["transposed"] = False
    return m


def multiply_cost(prop_l, m, k, n, prop_r):
    """FLOP cost of multiplying (m x k, prop_l) by (k x n, prop_r).

    Priority order (BLAS-aligned):
      1. Either is identity -> 0
      2. Both diagonal -> k
      3. Exactly one diagonal -> m * n
      4. At least one symmetric or triangular -> m * k * n
      5. Otherwise (both general) -> 2 * m * k * n
    """
    if prop_l == "identity" or prop_r == "identity":
        return 0
    if prop_l == "diagonal" and prop_r == "diagonal":
        return k
    if prop_l == "diagonal" or prop_r == "diagonal":
        return m * n
    structured = {"upper_triangular", "lower_triangular", "symmetric"}
    if prop_l in structured or prop_r in structured:
        return m * k * n
    return 2 * m * k * n


def propagate_property(prop_l, prop_r):
    """Determine structural property of the product L x R."""
    if prop_l == "identity":
        return prop_r
    if prop_r == "identity":
        return prop_l
    if prop_l == "diagonal" and prop_r == "diagonal":
        return "diagonal"
    if prop_l == "diagonal" and prop_r == "upper_triangular":
        return "upper_triangular"
    if prop_l == "upper_triangular" and prop_r == "diagonal":
        return "upper_triangular"
    if prop_l == "diagonal" and prop_r == "lower_triangular":
        return "lower_triangular"
    if prop_l == "lower_triangular" and prop_r == "diagonal":
        return "lower_triangular"
    if prop_l == "upper_triangular" and prop_r == "upper_triangular":
        return "upper_triangular"
    if prop_l == "lower_triangular" and prop_r == "lower_triangular":
        return "lower_triangular"
    return "general"


def select_blas_routine(prop_l, prop_r):
    """Select appropriate BLAS routine for the multiplication."""
    if prop_l == "identity" or prop_r == "identity":
        return "copy"
    if prop_l == "diagonal" or prop_r == "diagonal":
        return "ddiagmm"
    if prop_l == "symmetric" or prop_r == "symmetric":
        return "dsymm"
    tri = {"upper_triangular", "lower_triangular"}
    if prop_l in tri or prop_r in tri:
        return "dtrmm"
    return "dgemm"


def optimize_chain(matrices):
    """Find minimum-FLOP evaluation order using property-aware DP.

    dp[i][j] maps each achievable result property to
    (min_cost, split_k, left_prop, right_prop).
    """
    mats = [apply_transpose(m) for m in matrices]
    n = len(mats)

    if n == 1:
        return 0, []

    rows = [m["rows"] for m in mats]
    cols = [m["cols"] for m in mats]

    dp = [[{} for _ in range(n)] for _ in range(n)]

    for i in range(n):
        dp[i][i] = {mats[i]["property"]: (0, -1, None, None)}

    for length in range(2, n + 1):
        for i in range(n - length + 1):
            j = i + length - 1
            best = {}

            for k in range(i, j):
                m = rows[i]
                kk = cols[k]
                nn = cols[j]

                for prop_l, (cost_l, _, _, _) in dp[i][k].items():
                    for prop_r, (cost_r, _, _, _) in dp[k + 1][j].items():
                        mc = multiply_cost(prop_l, m, kk, nn, prop_r)
                        total = cost_l + cost_r + mc
                        result_prop = propagate_property(prop_l, prop_r)

                        if result_prop not in best or total < best[result_prop][0]:
                            best[result_prop] = (total, k, prop_l, prop_r)

            dp[i][j] = best

    min_cost = min(v[0] for v in dp[0][n - 1].values())

    def extract_routines(i, j, target_prop=None):
        if i == j:
            return []
        if target_prop is None:
            target_prop = min(dp[i][j], key=lambda p: dp[i][j][p][0])
        _, k, prop_l, prop_r = dp[i][j][target_prop]
        left_routines = extract_routines(i, k, prop_l)
        right_routines = extract_routines(k + 1, j, prop_r)
        routine = select_blas_routine(prop_l, prop_r)
        return left_routines + right_routines + [routine]

    routines = extract_routines(0, n - 1)
    routines = [r for r in routines if r != "copy"]

    return min_cost, routines


def generate_blas_eval():
    """Generate /app/blas_eval.c with CBLAS routine calls."""

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <cblas.h>

static void init_general(double *A, int rows, int cols) {
    double total = (double)(rows * cols);
    for (int i = 0; i < rows; i++)
        for (int j = 0; j < cols; j++)
            A[i * cols + j] = (i * cols + j + 1.0) / total;
}

static void init_symmetric(double *S, int n) {
    for (int i = 0; i < n; i++)
        for (int j = 0; j < n; j++)
            S[i * n + j] = 1.0 / (1.0 + abs(i - j));
}

static void init_lower_triangular(double *L, int n) {
    for (int i = 0; i < n; i++)
        for (int j = 0; j < n; j++)
            L[i * n + j] = (j <= i) ? 1.0 / (i - j + 1.0) : 0.0;
}

static double frobenius_norm(const double *A, int rows, int cols) {
    double sum = 0.0;
    for (int i = 0; i < rows * cols; i++)
        sum += A[i] * A[i];
    return sqrt(sum);
}

/* blas_basic: A(4x6,gen) * B(6x3,gen) * C(3x5,gen)
   Optimal: (A*B)*C using dgemm + dgemm */
static void test_basic(void) {
    double A[4*6], B[6*3], C[3*5];
    init_general(A, 4, 6);
    init_general(B, 6, 3);
    init_general(C, 3, 5);

    double AB[4*3];
    memset(AB, 0, sizeof(AB));
    cblas_dgemm(CblasRowMajor, CblasNoTrans, CblasNoTrans,
                4, 3, 6, 1.0, A, 6, B, 3, 0.0, AB, 3);

    double R[4*5];
    memset(R, 0, sizeof(R));
    cblas_dgemm(CblasRowMajor, CblasNoTrans, CblasNoTrans,
                4, 5, 3, 1.0, AB, 3, C, 5, 0.0, R, 5);

    printf("blas_basic=%.10f\n", frobenius_norm(R, 4, 5));
}

/* blas_sym: S(4x4,sym) * A(4x6,gen) * B(6x3,gen)
   Optimal: S*(A*B) using dgemm + dsymm */
static void test_sym(void) {
    double S[4*4], A[4*6], B[6*3];
    init_symmetric(S, 4);
    init_general(A, 4, 6);
    init_general(B, 6, 3);

    double AB[4*3];
    memset(AB, 0, sizeof(AB));
    cblas_dgemm(CblasRowMajor, CblasNoTrans, CblasNoTrans,
                4, 3, 6, 1.0, A, 6, B, 3, 0.0, AB, 3);

    double R[4*3];
    memset(R, 0, sizeof(R));
    cblas_dsymm(CblasRowMajor, CblasLeft, CblasUpper,
                4, 3, 1.0, S, 4, AB, 3, 0.0, R, 3);

    printf("blas_sym=%.10f\n", frobenius_norm(R, 4, 3));
}

/* blas_tri: L(4x4,lower_tri) * S(4x4,sym) * A(4x3,gen)
   Optimal: L*(S*A) using dsymm + dtrmm */
static void test_tri_sym(void) {
    double L[4*4], S[4*4], A[4*3];
    init_lower_triangular(L, 4);
    init_symmetric(S, 4);
    init_general(A, 4, 3);

    /* SA = S*A using dsymm */
    double SA[4*3];
    memset(SA, 0, sizeof(SA));
    cblas_dsymm(CblasRowMajor, CblasLeft, CblasUpper,
                4, 3, 1.0, S, 4, A, 3, 0.0, SA, 3);

    /* R = L * SA using dtrmm (modifies input in-place) */
    double R[4*3];
    memcpy(R, SA, sizeof(SA));
    cblas_dtrmm(CblasRowMajor, CblasLeft, CblasLower,
                CblasNoTrans, CblasNonUnit,
                4, 3, 1.0, L, 4, R, 3);

    printf("blas_tri=%.10f\n", frobenius_norm(R, 4, 3));
}

int main(void) {
    test_basic();
    test_sym();
    test_tri_sym();
    printf("BLAS_EVAL_COMPLETE\n");
    return 0;
}
"""
    with open("/app/blas_eval.c", "w") as f:
        f.write(code)


def main():
    with open("/app/problem/chains.json", "r") as f:
        data = json.load(f)

    results = {}
    kernel_plans = {}
    for chain in data["chains"]:
        name = chain["name"]
        cost, routines = optimize_chain(chain["matrices"])
        results[name] = cost
        kernel_plans[name] = routines

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    with open("/app/kernel_plan.json", "w") as f:
        json.dump(kernel_plans, f, indent=2)

    generate_blas_eval()

    for name, cost in sorted(results.items()):
        print(f"  {name}: {cost}")
    print("\nGenerated /app/blas_eval.c")


if __name__ == "__main__":
    main()
