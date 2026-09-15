/*
 * CTD Pipeline Driver — processes TEOS-10 check data and writes output.json
 *
 */

#include <stdio.h>
#include <math.h>
#include "gsw_pipeline.h"
#include "gsw_check_data.h"

static void write_json_array(FILE *f, const char *name, const double *arr, int n,
                             int last) {
    int i, first = 1;
    fprintf(f, "  \"%s\": [", name);
    for (i = 0; i < n; i++) {
        if (!is_valid_value(arr[i])) continue;
        if (!first) fprintf(f, ", ");
        fprintf(f, "%.17e", arr[i]);
        first = 0;
    }
    fprintf(f, "]%s\n", last ? "" : ",");
}

int main(void) {
    int i, j, k, n;
    double specvol_out[CAST_TOTAL];
    double rho_out[CAST_TOTAL];
    double alpha_out[CAST_TOTAL];
    double beta_out[CAST_TOTAL];
    double sigma0_out[CAST_TOTAL];
    double n2_out[CAST_MPRES_TOTAL];
    double p_mid_out[CAST_MPRES_TOTAL];
    double grav_arr[CAST_TOTAL];
    FILE *f;

    /* Copy gravity data with per-cast latitude replication */
    for (i = 0; i < CAST_TOTAL; i++) {
        grav_arr[i] = ref_grav[i];
    }

    /* Compute specvol, rho, alpha, beta, sigma0 for each point */
    for (i = 0; i < CAST_TOTAL; i++) {
        if (!is_valid_value(ref_sa[i]) || !is_valid_value(ref_ct[i]) ||
            !is_valid_value(ref_p[i])) {
            specvol_out[i] = GSW_INVALID_VALUE;
            rho_out[i]     = GSW_INVALID_VALUE;
            alpha_out[i]   = GSW_INVALID_VALUE;
            beta_out[i]    = GSW_INVALID_VALUE;
            sigma0_out[i]  = GSW_INVALID_VALUE;
            continue;
        }

        gsw_specvol_alpha_beta(ref_sa[i], ref_ct[i], ref_p[i],
                               &specvol_out[i], &alpha_out[i], &beta_out[i]);
        rho_out[i]    = gsw_rho(ref_sa[i], ref_ct[i], ref_p[i]);
        sigma0_out[i] = gsw_sigma0(ref_sa[i], ref_ct[i]);
    }

    /* Compute N^2 for each cast */
    for (j = 0; j < CAST_N; j++) {
        k = j * CAST_M;
        /* Find the number of valid points in this cast */
        for (n = 0; n < CAST_M; n++) {
            if (!is_valid_value(ref_sa[k + n]) ||
                fabs(ref_sa[k + n]) >= GSW_ERROR_LIMIT)
                break;
        }
        gsw_nsquared(&ref_sa[k], &ref_ct[k], &ref_p[k], &grav_arr[k],
                     n, &n2_out[j * CAST_MPRES_M], &p_mid_out[j * CAST_MPRES_M]);
        /* Fill remaining slots with sentinel */
        for (i = (n > 0 ? n - 1 : 0); i < CAST_MPRES_M; i++) {
            n2_out[j * CAST_MPRES_M + i] = GSW_INVALID_VALUE;
            p_mid_out[j * CAST_MPRES_M + i] = GSW_INVALID_VALUE;
        }
    }

    /* Write output.json */
    f = fopen("/app/output.json", "w");
    if (!f) {
        fprintf(stderr, "Error: cannot open /app/output.json for writing\n");
        return 1;
    }

    fprintf(f, "{\n");
    write_json_array(f, "specvol", specvol_out, CAST_TOTAL, 0);
    write_json_array(f, "rho",     rho_out,     CAST_TOTAL, 0);
    write_json_array(f, "alpha",   alpha_out,   CAST_TOTAL, 0);
    write_json_array(f, "beta",    beta_out,    CAST_TOTAL, 0);
    write_json_array(f, "sigma0",  sigma0_out,  CAST_TOTAL, 0);
    write_json_array(f, "n2",      n2_out,      CAST_MPRES_TOTAL, 0);
    write_json_array(f, "p_mid_n2", p_mid_out,  CAST_MPRES_TOTAL, 1);
    fprintf(f, "}\n");

    fclose(f);
    printf("Output written to /app/output.json\n");
    return 0;
}
