/*
 * Stochastic forward model: maps 2D parameters to 2D observations.
 * No tractable likelihood. Prior: Uniform([-1,1]^2).
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <stdint.h>
#include <time.h>

/* ---- xoshiro256** PRNG ---- */
static uint64_t rng_s[4];

static inline uint64_t rotl(const uint64_t x, int k) {
    return (x << k) | (x >> (64 - k));
}

static uint64_t xo_next(void) {
    const uint64_t result = rotl(rng_s[1] * 5, 7) * 9;
    const uint64_t t = rng_s[1] << 17;
    rng_s[2] ^= rng_s[0];
    rng_s[3] ^= rng_s[1];
    rng_s[1] ^= rng_s[2];
    rng_s[0] ^= rng_s[3];
    rng_s[2] ^= t;
    rng_s[3] = rotl(rng_s[3], 45);
    return result;
}

static void xo_seed(uint64_t seed) {
    /* splitmix64 initialization */
    for (int i = 0; i < 4; i++) {
        seed += 0x9e3779b97f4a7c15ULL;
        uint64_t z = seed;
        z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ULL;
        z = (z ^ (z >> 27)) * 0x94d049bb133111ebULL;
        rng_s[i] = z ^ (z >> 31);
    }
}

static double rand_f64(void) {
    return (double)(xo_next() >> 11) * 0x1.0p-53;
}

static double rand_uniform(double lo, double hi) {
    return lo + (hi - lo) * rand_f64();
}

static double rand_normal(double mu, double sigma) {
    double u1, u2;
    do { u1 = rand_f64(); } while (u1 < 1e-300);
    u2 = rand_f64();
    return mu + sigma * sqrt(-2.0 * log(u1)) * cos(2.0 * M_PI * u2);
}

/* ---- Forward model ---- */
static void two_moons_sim(const double *theta, double *out, int n) {
    const double ang = -M_PI / 4.0;
    const double ca = cos(ang), sa = sin(ang);

    for (int i = 0; i < n; i++) {
        double t0 = theta[2 * i];
        double t1 = theta[2 * i + 1];
        double a  = rand_uniform(-M_PI / 2.0, M_PI / 2.0);
        double r  = rand_normal(0.1, 0.01);
        double p0 = cos(a) * r + 0.25;
        double p1 = sin(a) * r;
        double z0 = ca * t0 - sa * t1;
        double z1 = sa * t0 + ca * t1;
        out[2 * i]     = p0 - fabs(z0);
        out[2 * i + 1] = p1 + z1;
    }
}

/* ---- CLI ---- */
static void print_usage(const char *prog) {
    fprintf(stderr,
        "Usage: %s --input FILE --output FILE --n COUNT [--seed SEED]\n\n"
        "Stochastic forward model mapping 2D parameters to 2D observations.\n"
        "No tractable likelihood function. Prior: Uniform([-1,1]^2).\n\n"
        "Options:\n"
        "  --input  FILE   Binary input file containing n parameter pairs.\n"
        "                  Format: n*2 IEEE-754 float64 values, little-endian,\n"
        "                  row-major order. Total bytes: n * 2 * 8.\n"
        "  --output FILE   Binary output file for n simulated observation pairs.\n"
        "                  Same format as input: n*2 float64, little-endian.\n"
        "  --n     COUNT   Number of parameter sets (rows) in input.\n"
        "  --seed  SEED    64-bit unsigned random seed (default: clock).\n"
        "  --help          Show this help message.\n\n"
        "Each parameter set theta = (t0, t1) should satisfy -1 <= ti <= 1.\n"
        "Each simulation produces one stochastic observation (x0, x1).\n",
        prog);
}

int main(int argc, char **argv) {
    const char *input_file = NULL;
    const char *output_file = NULL;
    int n = 0;
    uint64_t seed = (uint64_t)time(NULL) ^ ((uint64_t)clock() << 16);
    int seed_set = 0;

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--help") == 0 || strcmp(argv[i], "-h") == 0) {
            print_usage(argv[0]);
            return 0;
        } else if (strcmp(argv[i], "--input") == 0 && i + 1 < argc) {
            input_file = argv[++i];
        } else if (strcmp(argv[i], "--output") == 0 && i + 1 < argc) {
            output_file = argv[++i];
        } else if (strcmp(argv[i], "--n") == 0 && i + 1 < argc) {
            n = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--seed") == 0 && i + 1 < argc) {
            seed = (uint64_t)strtoull(argv[++i], NULL, 10);
            seed_set = 1;
        } else {
            fprintf(stderr, "Unknown option: %s\n", argv[i]);
            print_usage(argv[0]);
            return 1;
        }
    }

    if (!input_file || !output_file || n <= 0) {
        fprintf(stderr, "Error: --input, --output, and --n (>0) are required.\n\n");
        print_usage(argv[0]);
        return 1;
    }

    /* Read parameters */
    FILE *fin = fopen(input_file, "rb");
    if (!fin) { perror("Cannot open input"); return 1; }

    double *theta = (double *)malloc((size_t)n * 2 * sizeof(double));
    if (!theta) { perror("malloc theta"); fclose(fin); return 1; }

    size_t nread = fread(theta, sizeof(double), (size_t)n * 2, fin);
    fclose(fin);
    if ((int)nread != n * 2) {
        fprintf(stderr, "Error: expected %d float64 values, read %zu\n",
                n * 2, nread);
        free(theta);
        return 1;
    }

    /* Simulate */
    double *out = (double *)malloc((size_t)n * 2 * sizeof(double));
    if (!out) { perror("malloc out"); free(theta); return 1; }

    xo_seed(seed);
    two_moons_sim(theta, out, n);

    /* Write output */
    FILE *fout = fopen(output_file, "wb");
    if (!fout) { perror("Cannot open output"); free(theta); free(out); return 1; }

    fwrite(out, sizeof(double), (size_t)n * 2, fout);
    fclose(fout);

    free(theta);
    free(out);

    fprintf(stderr, "Simulated %d observations (seed=%lu)\n",
            n, (unsigned long)seed);
    return 0;
}
