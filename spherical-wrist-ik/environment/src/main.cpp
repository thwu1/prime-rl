#include "manipulator.h"
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <cmath>
#include <cstring>


namespace {
    // Platform-independent 64-bit LCG (Knuth constants) for reproducibility
    static uint64_t rng_state = 12345ULL;
    static double next_rand() {
        rng_state = rng_state * 6364136223846793005ULL + 1442695040888963407ULL;
        return ((rng_state >> 33) & 0x7FFFFFFFULL) / (double)0x7FFFFFFFULL;
    }
}

int main(int argc, char* argv[]) {
    const double PI = M_PI;

    if (argc < 2) {
        printf("Usage:\n");
        printf("  %s --verify N       Round-trip verify N random configs\n", argv[0]);
        printf("  %s --fk q1..q6      Compute forward kinematics\n", argv[0]);
        printf("  %s --ik T0..T15     Compute inverse kinematics\n", argv[0]);
        return 1;
    }

    if (strcmp(argv[1], "--verify") == 0) {
        int N = argc > 2 ? atoi(argv[2]) : 100;
        rng_state = 12345ULL;

        int total_pass = 0, total_fail = 0, total_no_sol = 0;
        int degen_pass = 0, degen_total = 0;

        for (int n = 0; n < N; n++) {
            double q[6];
            for (int i = 0; i < 6; i++)
                q[i] = next_rand() * 2.0 * PI;

            bool is_degen = fabs(sin(q[4])) < 1e-4;
            if (is_degen) degen_total++;

            double T[16];
            manipulator::forward(q, T);

            double q_sols[8 * 6];
            int num_sols = manipulator::inverse(T, q_sols);

            if (num_sols == 0) {
                total_no_sol++;
                printf("FAIL: config %d, no solutions found\n", n);
                printf("  q_orig:");
                for (int j = 0; j < 6; j++) printf(" %.6f", q[j]);
                printf("\n");
                continue;
            }

            bool any_match = false;
            bool all_valid = true;

            for (int i = 0; i < num_sols; i++) {
                double T_chk[16];
                manipulator::forward(&q_sols[i * 6], T_chk);

                double err = 0.0;
                for (int j = 0; j < 16; j++)
                    err += (T[j] - T_chk[j]) * (T[j] - T_chk[j]);
                err = sqrt(err);

                if (err <= 1e-6) {
                    any_match = true;
                } else {
                    all_valid = false;
                    printf("FAIL: config %d, sol %d/%d, error = %.10e\n",
                           n, i, num_sols, err);
                    printf("  q_orig:");
                    for (int j = 0; j < 6; j++) printf(" %.6f", q[j]);
                    printf("\n");
                    printf("  q_sol: ");
                    for (int j = 0; j < 6; j++) printf(" %.6f", q_sols[i * 6 + j]);
                    printf("\n");
                }
            }

            if (any_match && all_valid) {
                total_pass++;
                if (is_degen) degen_pass++;
            } else {
                total_fail++;
            }
        }

        printf("\n=== Round-trip Verification Results ===\n");
        printf("Total configs:  %d\n", N);
        printf("Passed:         %d\n", total_pass);
        printf("Failed:         %d\n", total_fail);
        printf("No solution:    %d\n", total_no_sol);
        printf("Degenerate:     %d/%d passed\n", degen_pass, degen_total);
        printf("Success rate:   %.2f%%\n", 100.0 * total_pass / N);

        if (total_fail == 0 && total_no_sol == 0) {
            printf("STATUS: ALL PASSED\n");
            return 0;
        } else {
            printf("STATUS: FAILED\n");
            return 1;
        }
    }
    else if (strcmp(argv[1], "--fk") == 0 && argc >= 8) {
        double q[6];
        for (int i = 0; i < 6; i++)
            q[i] = atof(argv[i + 2]);

        double T[16];
        manipulator::forward(q, T);

        for (int i = 0; i < 4; i++) {
            for (int j = 0; j < 4; j++)
                printf("%.10f ", T[i * 4 + j]);
            printf("\n");
        }
    }
    else if (strcmp(argv[1], "--ik") == 0 && argc >= 18) {
        double T[16];
        for (int i = 0; i < 16; i++)
            T[i] = atof(argv[i + 2]);

        double q_sols[8 * 6];
        int num_sols = manipulator::inverse(T, q_sols);

        printf("Solutions: %d\n", num_sols);
        for (int i = 0; i < num_sols; i++) {
            for (int j = 0; j < 6; j++)
                printf("%.10f ", q_sols[i * 6 + j]);
            printf("\n");
        }
    }
    else {
        printf("Invalid arguments. Run without arguments for usage.\n");
        return 1;
    }

    return 0;
}
