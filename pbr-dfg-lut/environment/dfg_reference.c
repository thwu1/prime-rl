/*
 * DFG Reference Tool
 * Derived from Google Filament's CubemapIBL DFG computation.
 * Apache License 2.0 — see https://github.com/google/filament
 *
 * Computes physically correct DFG LUT values for comparison/verification.
 */


#include <stdio.h>
#include <math.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

#define LUT_SIZE 128
#define GGX_SAMPLES 1024
#define CHARLIE_SAMPLES 4096

static double clampd(double x, double lo, double hi) {
    if (x < lo) return lo;
    if (x > hi) return hi;
    return x;
}

static double saturated(double x) {
    return clampd(x, 0.0, 1.0);
}

static double pow5d(double x) {
    double x2 = x * x;
    return x2 * x2 * x;
}

/* Van der Corput radical inverse (base 2, 32-bit) */
static double radical_inverse_vdc(uint32_t bits) {
    bits = (bits << 16u) | (bits >> 16u);
    bits = ((bits & 0x55555555u) << 1u) | ((bits & 0xAAAAAAAAu) >> 1u);
    bits = ((bits & 0x33333333u) << 2u) | ((bits & 0xCCCCCCCCu) >> 2u);
    bits = ((bits & 0x0F0F0F0Fu) << 4u) | ((bits & 0xF0F0F0F0u) >> 4u);
    bits = ((bits & 0x00FF00FFu) << 8u) | ((bits & 0xFF00FF00u) >> 8u);
    return (double)bits * 2.3283064365386963e-10;
}

static void hammersley(uint32_t i, double inv_n, double out[2]) {
    out[0] = (double)i * inv_n;
    out[1] = radical_inverse_vdc(i);
}

/* GGX importance sampling in tangent space (n = [0,0,1]) */
static void importance_sample_ggx(const double u[2], double a, double H[3]) {
    double phi = 2.0 * M_PI * u[0];
    /* (a+1)(a-1) = a^2-1 for numerical stability */
    double cos_theta_sq = (1.0 - u[1]) / (1.0 + (a + 1.0) * ((a - 1.0) * u[1]));
    cos_theta_sq = clampd(cos_theta_sq, 0.0, 1.0);
    double cos_theta = sqrt(cos_theta_sq);
    double sin_theta = sqrt(1.0 - cos_theta_sq);
    H[0] = sin_theta * cos(phi);
    H[1] = sin_theta * sin(phi);
    H[2] = cos_theta;
}

/* Height-correlated Smith-GGX visibility (includes 1/(4*NoV*NoL) denominator) */
static double visibility_smith_ggx(double NoV, double NoL, double a) {
    double a2 = a * a;
    double GGXL = NoV * sqrt(fmax(0.0, (NoL - NoL * a2) * NoL + a2));
    double GGXV = NoL * sqrt(fmax(0.0, (NoV - NoV * a2) * NoV + a2));
    double denom = GGXV + GGXL;
    if (denom < 1e-14) return 0.0;
    return 0.5 / denom;
}

/* Charlie NDF (Estevez-Kulla cloth sheen) */
static double distribution_charlie(double NoH, double a) {
    if (a < 1e-14) return 0.0;
    double inv_alpha = 1.0 / a;
    double cos2h = NoH * NoH;
    double sin2h = fmax(0.0, 1.0 - cos2h);
    return (2.0 + inv_alpha) * pow(fmax(sin2h, 1e-12), inv_alpha * 0.5) / (2.0 * M_PI);
}

/* Ashikhmin visibility (Neubelt-Pettineo cloth) */
static double visibility_ashikhmin(double NoV, double NoL) {
    double denom = 4.0 * (NoL + NoV - NoL * NoV);
    if (denom < 1e-14) return 0.0;
    return 1.0 / denom;
}

/* Multiscatter DFG via importance-sampled GGX integration */
static void dfv_multiscatter(double NoV, double linear_roughness,
                             int num_samples, double result[2]) {
    double rx = 0.0, ry = 0.0;
    double sin_v = sqrt(fmax(0.0, 1.0 - NoV * NoV));
    double V[3] = {sin_v, 0.0, NoV};
    double inv_n = 1.0 / (double)num_samples;

    for (int i = 0; i < num_samples; i++) {
        double u[2], H[3];
        hammersley((uint32_t)i, inv_n, u);
        importance_sample_ggx(u, linear_roughness, H);

        double VdotH = V[0]*H[0] + V[1]*H[1] + V[2]*H[2];
        double L[3] = {
            2.0 * VdotH * H[0] - V[0],
            2.0 * VdotH * H[1] - V[1],
            2.0 * VdotH * H[2] - V[2]
        };

        double VoH = saturated(VdotH);
        double NoL = saturated(L[2]);
        double NoH = saturated(H[2]);

        if (NoL > 0.0) {
            double v = visibility_smith_ggx(NoV, NoL, linear_roughness)
                       * NoL * (VoH / NoH);
            double Fc = pow5d(1.0 - VoH);
            rx += v * Fc;
            ry += v;
        }
    }
    result[0] = rx * 4.0 / (double)num_samples;
    result[1] = ry * 4.0 / (double)num_samples;
}

/* Charlie cloth DFG via uniform hemisphere sampling */
static double dfv_charlie_uniform(double NoV, double linear_roughness,
                                  int num_samples) {
    double r = 0.0;
    double sin_v = sqrt(fmax(0.0, 1.0 - NoV * NoV));
    double V[3] = {sin_v, 0.0, NoV};
    double inv_n = 1.0 / (double)num_samples;

    for (int i = 0; i < num_samples; i++) {
        double u[2];
        hammersley((uint32_t)i, inv_n, u);

        double phi = 2.0 * M_PI * u[0];
        double cos_theta = 1.0 - u[1];
        double sin_theta = sqrt(1.0 - cos_theta * cos_theta);
        double H[3] = {sin_theta * cos(phi), sin_theta * sin(phi), cos_theta};

        double VdotH = V[0]*H[0] + V[1]*H[1] + V[2]*H[2];
        double L[3] = {
            2.0 * VdotH * H[0] - V[0],
            2.0 * VdotH * H[1] - V[1],
            2.0 * VdotH * H[2] - V[2]
        };

        double VoH = saturated(VdotH);
        double NoL = saturated(L[2]);
        double NoH = saturated(H[2]);

        if (NoL > 0.0) {
            double v = visibility_ashikhmin(NoV, NoL);
            double d = distribution_charlie(NoH, linear_roughness);
            r += v * d * NoL * VoH;
        }
    }
    return r * (4.0 * 2.0 * M_PI / (double)num_samples);
}

/* Compute DFG values for a single pixel */
static void compute_pixel(int x, int y, double result[3]) {
    double h = (double)LUT_SIZE;
    double coord = saturated((h - (double)y + 0.5) / h);
    double linear_roughness = coord * coord;
    double NoV = saturated(((double)x + 0.5) / h);

    double dfg[2];
    dfv_multiscatter(NoV, linear_roughness, GGX_SAMPLES, dfg);
    result[0] = dfg[0];
    result[1] = dfg[1];
    result[2] = dfv_charlie_uniform(NoV, linear_roughness, CHARLIE_SAMPLES);
}

int main(int argc, char** argv) {
    if (argc < 2) {
        fprintf(stderr, "DFG Reference Tool (derived from Google Filament IBL)\n\n");
        fprintf(stderr, "Usage:\n");
        fprintf(stderr, "  %s --pixel X Y    Compute reference DFG values at pixel (X,Y)\n",
                argv[0]);
        fprintf(stderr, "  %s --sample        Print reference values at diagnostic points\n",
                argv[0]);
        fprintf(stderr, "  %s --grid [STEP]   Print values on a coarse grid (default step=16)\n",
                argv[0]);
        fprintf(stderr, "\nLUT is %dx%d, 3 channels (DFG1, DFG2, Charlie)\n",
                LUT_SIZE, LUT_SIZE);
        fprintf(stderr, "X axis: cos(theta_v), Y axis: roughness "
                "(y=0 roughest, y=%d smoothest)\n", LUT_SIZE - 1);
        return 1;
    }

    if (strcmp(argv[1], "--pixel") == 0 && argc >= 4) {
        int x = atoi(argv[2]);
        int y = atoi(argv[3]);
        if (x < 0 || x >= LUT_SIZE || y < 0 || y >= LUT_SIZE) {
            fprintf(stderr, "Pixel (%d,%d) out of range [0,%d)\n",
                    x, y, LUT_SIZE);
            return 1;
        }
        double px[3];
        compute_pixel(x, y, px);
        printf("(%d, %d): DFG1=%.17e  DFG2=%.17e  Charlie=%.17e\n",
               x, y, px[0], px[1], px[2]);
    } else if (strcmp(argv[1], "--sample") == 0) {
        int coords[][2] = {
            {0, 0}, {64, 0}, {127, 0},
            {0, 64}, {64, 64}, {127, 64},
            {0, 127}, {64, 127}, {127, 127},
            {32, 32}, {96, 96}, {16, 112}
        };
        int n = (int)(sizeof(coords) / sizeof(coords[0]));
        for (int i = 0; i < n; i++) {
            double px[3];
            compute_pixel(coords[i][0], coords[i][1], px);
            printf("(%3d, %3d): DFG1=%.17e  DFG2=%.17e  Charlie=%.17e\n",
                   coords[i][0], coords[i][1], px[0], px[1], px[2]);
        }
    } else if (strcmp(argv[1], "--grid") == 0) {
        int step = 16;
        if (argc >= 3) step = atoi(argv[2]);
        if (step < 1) step = 1;
        if (step > LUT_SIZE) step = LUT_SIZE;
        for (int y = 0; y < LUT_SIZE; y += step) {
            for (int x = 0; x < LUT_SIZE; x += step) {
                double px[3];
                compute_pixel(x, y, px);
                printf("(%3d,%3d) D1=%12.6f D2=%12.6f C=%12.6f\n",
                       x, y, px[0], px[1], px[2]);
            }
        }
    } else {
        fprintf(stderr, "Unknown option '%s'. Run without arguments for usage.\n",
                argv[1]);
        return 1;
    }
    return 0;
}
