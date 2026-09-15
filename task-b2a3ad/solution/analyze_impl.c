#include "fdtd3d.h"
#include <stdio.h>
#include <stdlib.h>
#include <math.h>

int analyze_outputs(const char *file_naive, const char *file_tiled,
                    const char *json_out,
                    int outer_dimx, int outer_dimy, int outer_dimz,
                    int radius)
{
    size_t vol = (size_t)outer_dimx * outer_dimy * outer_dimz;

    float *naive_data = (float *)malloc(vol * sizeof(float));
    float *tiled_data = (float *)malloc(vol * sizeof(float));
    if (!naive_data || !tiled_data) {
        fprintf(stderr, "analyze: memory allocation failed\n");
        free(naive_data);
        free(tiled_data);
        return -1;
    }

    /* Read naive output */
    FILE *f1 = fopen(file_naive, "rb");
    if (!f1) {
        fprintf(stderr, "analyze: cannot open %s\n", file_naive);
        free(naive_data); free(tiled_data);
        return -1;
    }
    size_t r1 = fread(naive_data, sizeof(float), vol, f1);
    fclose(f1);
    if (r1 != vol) {
        fprintf(stderr, "analyze: %s: read %zu of %zu elements\n",
                file_naive, r1, vol);
        free(naive_data); free(tiled_data);
        return -1;
    }

    /* Read tiled output */
    FILE *f2 = fopen(file_tiled, "rb");
    if (!f2) {
        fprintf(stderr, "analyze: cannot open %s\n", file_tiled);
        free(naive_data); free(tiled_data);
        return -1;
    }
    size_t r2 = fread(tiled_data, sizeof(float), vol, f2);
    fclose(f2);
    if (r2 != vol) {
        fprintf(stderr, "analyze: %s: read %zu of %zu elements\n",
                file_tiled, r2, vol);
        free(naive_data); free(tiled_data);
        return -1;
    }

    /* Compute error metrics over interior elements */
    int dimx = outer_dimx - 2 * radius;
    int dimy = outer_dimy - 2 * radius;
    int dimz = outer_dimz - 2 * radius;

    double max_abs_err = 0.0;
    double sum_abs_err = 0.0;
    double sum_sq_diff = 0.0;
    double sum_sq_ref  = 0.0;
    int max_ix = 0, max_iy = 0, max_iz = 0;
    int count = 0;

    for (int iz = 0; iz < dimz; iz++) {
        for (int iy = 0; iy < dimy; iy++) {
            for (int ix = 0; ix < dimx; ix++) {
                int idx = (iz + radius) * outer_dimy * outer_dimx
                        + (iy + radius) * outer_dimx
                        + (ix + radius);
                double a = (double)naive_data[idx];
                double b = (double)tiled_data[idx];
                double d = fabs(a - b);
                sum_abs_err += d;
                sum_sq_diff += d * d;
                sum_sq_ref  += a * a;
                if (d > max_abs_err) {
                    max_abs_err = d;
                    max_ix = ix;
                    max_iy = iy;
                    max_iz = iz;
                }
                count++;
            }
        }
    }

    double mean_abs_err = (count > 0) ? sum_abs_err / count : 0.0;
    double rel_l2 = (sum_sq_ref > 0.0)
                    ? sqrt(sum_sq_diff) / sqrt(sum_sq_ref)
                    : 0.0;

    /* Compute full-volume checksums */
    double naive_sum = 0.0, tiled_sum = 0.0;
    for (size_t i = 0; i < vol; i++) {
        naive_sum += (double)naive_data[i];
        tiled_sum += (double)tiled_data[i];
    }

    int match = (max_abs_err < 1e-5) ? 1 : 0;

    /* Write JSON report */
    FILE *jf = fopen(json_out, "w");
    if (!jf) {
        fprintf(stderr, "analyze: cannot open %s for writing\n", json_out);
        free(naive_data); free(tiled_data);
        return -1;
    }

    fprintf(jf, "{\n");
    fprintf(jf, "  \"grid\": {\"dimx\": %d, \"dimy\": %d, \"dimz\": %d},\n",
            dimx, dimy, dimz);
    fprintf(jf, "  \"stencil\": {\"radius\": %d, \"timesteps\": %d},\n",
            RADIUS, TIMESTEPS);
    fprintf(jf, "  \"comparison\": {\n");
    fprintf(jf, "    \"max_absolute_error\": %.10e,\n", max_abs_err);
    fprintf(jf, "    \"mean_absolute_error\": %.10e,\n", mean_abs_err);
    fprintf(jf, "    \"relative_l2_error\": %.10e,\n", rel_l2);
    fprintf(jf, "    \"max_error_location\": {\"ix\": %d, \"iy\": %d, \"iz\": %d},\n",
            max_ix, max_iy, max_iz);
    fprintf(jf, "    \"interior_elements_compared\": %d,\n", count);
    fprintf(jf, "    \"match\": %s\n", match ? "true" : "false");
    fprintf(jf, "  },\n");
    fprintf(jf, "  \"naive_checksum\": %.10f,\n", naive_sum);
    fprintf(jf, "  \"tiled_checksum\": %.10f\n", tiled_sum);
    fprintf(jf, "}\n");
    fclose(jf);

    printf("Comparison results:\n");
    printf("  Max absolute error:   %.10e\n", max_abs_err);
    printf("  Mean absolute error:  %.10e\n", mean_abs_err);
    printf("  Relative L2 error:    %.10e\n", rel_l2);
    printf("  Max error at (%d, %d, %d)\n", max_ix, max_iy, max_iz);
    printf("  Interior elements:    %d\n", count);
    printf("  Match:                %s\n", match ? "YES" : "NO");

    free(naive_data);
    free(tiled_data);
    return 0;
}
