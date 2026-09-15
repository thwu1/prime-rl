/*
 * LUT Compare Tool
 *
 * Reads a DFGL-format binary LUT and compares every pixel against
 * internally-computed reference values (same algorithms as dfg_reference).
 * Reports per-channel error statistics, worst pixels, and overall pass/fail.
 *
 * Derived from Google Filament's CubemapIBL DFG computation.
 * Apache License 2.0 — see https://github.com/google/filament
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

static void importance_sample_ggx(const double u[2], double a, double H[3]) {
    double phi = 2.0 * M_PI * u[0];
    double cos_theta_sq = (1.0 - u[1]) / (1.0 + (a + 1.0) * ((a - 1.0) * u[1]));
    cos_theta_sq = clampd(cos_theta_sq, 0.0, 1.0);
    double cos_theta = sqrt(cos_theta_sq);
    double sin_theta = sqrt(1.0 - cos_theta_sq);
    H[0] = sin_theta * cos(phi);
    H[1] = sin_theta * sin(phi);
    H[2] = cos_theta;
}

static double visibility_smith_ggx(double NoV, double NoL, double a) {
    double a2 = a * a;
    double GGXL = NoV * sqrt(fmax(0.0, (NoL - NoL * a2) * NoL + a2));
    double GGXV = NoL * sqrt(fmax(0.0, (NoV - NoV * a2) * NoV + a2));
    double denom = GGXV + GGXL;
    if (denom < 1e-14) return 0.0;
    return 0.5 / denom;
}

static double distribution_charlie(double NoH, double a) {
    if (a < 1e-14) return 0.0;
    double inv_alpha = 1.0 / a;
    double cos2h = NoH * NoH;
    double sin2h = fmax(0.0, 1.0 - cos2h);
    return (2.0 + inv_alpha) * pow(fmax(sin2h, 1e-12), inv_alpha * 0.5) / (2.0 * M_PI);
}

static double visibility_ashikhmin(double NoV, double NoL) {
    double denom = 4.0 * (NoL + NoV - NoL * NoV);
    if (denom < 1e-14) return 0.0;
    return 1.0 / denom;
}

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
        fprintf(stderr, "LUT Compare Tool — compares DFGL binary against reference\n\n");
        fprintf(stderr, "Usage:\n");
        fprintf(stderr, "  %s <dfg_lut.bin> [--verbose]\n", argv[0]);
        fprintf(stderr, "  %s <dfg_lut.bin> --region X0 Y0 X1 Y1\n\n", argv[0]);
        fprintf(stderr, "Reports per-channel error statistics and failing pixels.\n");
        fprintf(stderr, "Exit code 0 = all pixels pass, 1 = failures found.\n");
        return 1;
    }

    int verbose = 0;
    int region_mode = 0;
    int rx0 = 0, ry0 = 0, rx1 = LUT_SIZE, ry1 = LUT_SIZE;

    for (int i = 2; i < argc; i++) {
        if (strcmp(argv[i], "--verbose") == 0) verbose = 1;
        if (strcmp(argv[i], "--region") == 0 && i + 4 < argc) {
            region_mode = 1;
            rx0 = atoi(argv[i+1]);
            ry0 = atoi(argv[i+2]);
            rx1 = atoi(argv[i+3]);
            ry1 = atoi(argv[i+4]);
            i += 4;
        }
    }

    FILE *f = fopen(argv[1], "rb");
    if (!f) {
        fprintf(stderr, "ERROR: Cannot open '%s'\n", argv[1]);
        return 2;
    }

    /* Read and validate header */
    char magic[4];
    uint32_t width, height, channels;
    if (fread(magic, 1, 4, f) != 4 ||
        fread(&width, 4, 1, f) != 1 ||
        fread(&height, 4, 1, f) != 1 ||
        fread(&channels, 4, 1, f) != 1) {
        fprintf(stderr, "ERROR: Failed to read header\n");
        fclose(f);
        return 2;
    }

    if (memcmp(magic, "DFGL", 4) != 0) {
        fprintf(stderr, "ERROR: Invalid magic bytes: 0x%02x%02x%02x%02x "
                "(expected 'DFGL')\n",
                (unsigned char)magic[0], (unsigned char)magic[1],
                (unsigned char)magic[2], (unsigned char)magic[3]);
        fclose(f);
        return 2;
    }
    if (width != LUT_SIZE || height != LUT_SIZE || channels != 3) {
        fprintf(stderr, "ERROR: Unexpected dimensions %ux%ux%u "
                "(expected %dx%dx3)\n", width, height, channels,
                LUT_SIZE, LUT_SIZE);
        fclose(f);
        return 2;
    }

    /* Read pixel data */
    size_t npixels = (size_t)width * height * channels;
    float *pixels = (float *)malloc(npixels * sizeof(float));
    if (!pixels) {
        fprintf(stderr, "ERROR: malloc failed\n");
        fclose(f);
        return 2;
    }
    if (fread(pixels, sizeof(float), npixels, f) != npixels) {
        fprintf(stderr, "ERROR: Truncated pixel data\n");
        free(pixels);
        fclose(f);
        return 2;
    }
    fclose(f);

    /* Compare against reference */
    double max_err[3] = {0, 0, 0};
    double sum_err[3] = {0, 0, 0};
    int worst_x[3] = {0, 0, 0};
    int worst_y[3] = {0, 0, 0};
    int fail_count = 0;
    int checked = 0;

    for (int y = ry0; y < ry1 && y < LUT_SIZE; y++) {
        for (int x = rx0; x < rx1 && x < LUT_SIZE; x++) {
            double ref[3];
            compute_pixel(x, y, ref);

            int idx = (y * LUT_SIZE + x) * 3;
            for (int c = 0; c < 3; c++) {
                double err = fabs((double)pixels[idx + c] - ref[c]);
                sum_err[c] += err;
                if (err > max_err[c]) {
                    max_err[c] = err;
                    worst_x[c] = x;
                    worst_y[c] = y;
                }
            }

            double tol_dfg = 2e-4;
            double tol_charlie = fmax(5e-3, fabs(ref[2]) * 0.01);
            int pixel_fail = 0;
            if (fabs((double)pixels[idx] - ref[0]) > tol_dfg) pixel_fail = 1;
            if (fabs((double)pixels[idx+1] - ref[1]) > tol_dfg) pixel_fail = 1;
            if (fabs((double)pixels[idx+2] - ref[2]) > tol_charlie) pixel_fail = 1;

            if (pixel_fail) {
                fail_count++;
                if (verbose && fail_count <= 30) {
                    printf("FAIL (%3d,%3d): "
                           "D1=%.6f(ref %.6f, err=%.2e) "
                           "D2=%.6f(ref %.6f, err=%.2e) "
                           "C=%.6f(ref %.6f, err=%.2e)\n",
                           x, y,
                           pixels[idx], ref[0],
                           fabs(pixels[idx]-ref[0]),
                           pixels[idx+1], ref[1],
                           fabs(pixels[idx+1]-ref[1]),
                           pixels[idx+2], ref[2],
                           fabs(pixels[idx+2]-ref[2]));
                }
            }
            checked++;
        }
    }

    double mean_err[3];
    for (int c = 0; c < 3; c++)
        mean_err[c] = checked > 0 ? sum_err[c] / checked : 0;

    printf("\n=== DFG LUT Comparison Report ===\n");
    printf("File: %s\n", argv[1]);
    printf("Dimensions: %ux%ux%u\n", width, height, channels);
    if (region_mode)
        printf("Region: (%d,%d)-(%d,%d)\n", rx0, ry0, rx1, ry1);
    printf("Pixels checked: %d\n\n", checked);

    const char *names[] = {"DFG1 (Fc-wt)", "DFG2 (total)", "Charlie"};
    for (int c = 0; c < 3; c++) {
        printf("Channel %s:\n", names[c]);
        printf("  Max error:  %.8e  at pixel (%d, %d)\n",
               max_err[c], worst_x[c], worst_y[c]);
        printf("  Mean error: %.8e\n\n", mean_err[c]);
    }

    printf("Failing pixels: %d / %d (%.1f%%)\n",
           fail_count, checked, checked > 0 ? 100.0*fail_count/checked : 0);
    printf("Result: %s\n\n", fail_count == 0 ? "PASS" : "FAIL");

    if (fail_count > 0 && !verbose) {
        printf("Hint: re-run with --verbose to see individual failing pixels.\n");
        printf("Hint: use --region X0 Y0 X1 Y1 to focus on a specific area.\n");
    }

    free(pixels);
    return fail_count > 0 ? 1 : 0;
}
