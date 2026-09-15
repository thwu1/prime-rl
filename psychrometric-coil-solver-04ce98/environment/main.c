/*
 * Psychrometric calculator — command-line driver.
 * Reads commands from stdin, writes computed values to stdout.
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "psychro.h"
#include "ahu.h"

int main(void)
{
    char line[1024];
    char cmd[64];

    while (fgets(line, sizeof(line), stdin) != NULL)
    {
        if (sscanf(line, "%63s", cmd) != 1)
            continue;

        /* ---- Individual function queries ---- */

        if (strcmp(cmd, "SATVP") == 0)
        {
            double tdb;
            sscanf(line, "%*s %lf", &tdb);
            printf("%.2f\n", GetSatVapPres(tdb));
        }
        else if (strcmp(cmd, "SATW") == 0)
        {
            double tdb, p;
            sscanf(line, "%*s %lf %lf", &tdb, &p);
            printf("%.8f\n", GetSatHumRatio(tdb, p));
        }
        else if (strcmp(cmd, "W_WB") == 0)
        {
            double tdb, twb, p;
            sscanf(line, "%*s %lf %lf %lf", &tdb, &twb, &p);
            printf("%.8f\n", GetHumRatioFromTWetBulb(tdb, twb, p));
        }
        else if (strcmp(cmd, "WB_W") == 0)
        {
            double tdb, w, p;
            sscanf(line, "%*s %lf %lf %lf", &tdb, &w, &p);
            printf("%.4f\n", GetTWetBulbFromHumRatio(tdb, w, p));
        }
        else if (strcmp(cmd, "ENTHALPY") == 0)
        {
            double tdb, w;
            sscanf(line, "%*s %lf %lf", &tdb, &w);
            printf("%.1f\n", GetMoistAirEnthalpy(tdb, w));
        }
        else if (strcmp(cmd, "VOLUME") == 0)
        {
            double tdb, w, p;
            sscanf(line, "%*s %lf %lf %lf", &tdb, &w, &p);
            printf("%.6f\n", GetMoistAirVolume(tdb, w, p));
        }
        else if (strcmp(cmd, "DENSITY") == 0)
        {
            double tdb, w, p;
            sscanf(line, "%*s %lf %lf %lf", &tdb, &w, &p);
            printf("%.6f\n", GetMoistAirDensity(tdb, w, p));
        }

        /* ---- Full psychrometric state queries ----
         * Output order: W Tdp Twb RH VapPres h v density
         */

        else if (strcmp(cmd, "STATE_WB") == 0)
        {
            double tdb, twb, p;
            double W, Tdp, RH, Pv, h, v, mu;
            sscanf(line, "%*s %lf %lf %lf", &tdb, &twb, &p);
            CalcPsychrometricsFromTWetBulb(tdb, twb, p,
                &W, &Tdp, &RH, &Pv, &h, &v, &mu);
            printf("%.8f %.4f %.4f %.6f %.2f %.1f %.6f %.6f\n",
                   W, Tdp, twb, RH, Pv, h, v, (1. + W) / v);
        }
        else if (strcmp(cmd, "STATE_DP") == 0)
        {
            double tdb, tdp, p;
            double W, Twb, RH, Pv, h, v, mu;
            sscanf(line, "%*s %lf %lf %lf", &tdb, &tdp, &p);
            CalcPsychrometricsFromTDewPoint(tdb, tdp, p,
                &W, &Twb, &RH, &Pv, &h, &v, &mu);
            printf("%.8f %.4f %.4f %.6f %.2f %.1f %.6f %.6f\n",
                   W, tdp, Twb, RH, Pv, h, v, (1. + W) / v);
        }
        else if (strcmp(cmd, "STATE_RH") == 0)
        {
            double tdb, rh, p;
            double W, Twb, Tdp, Pv, h, v, mu;
            sscanf(line, "%*s %lf %lf %lf", &tdb, &rh, &p);
            CalcPsychrometricsFromRelHum(tdb, rh, p,
                &W, &Twb, &Tdp, &Pv, &h, &v, &mu);
            printf("%.8f %.4f %.4f %.6f %.2f %.1f %.6f %.6f\n",
                   W, Tdp, Twb, rh, Pv, h, v, (1. + W) / v);
        }

        /* ---- HVAC coil process query ---- */

        else if (strcmp(cmd, "COIL") == 0)
        {
            double oa_tdb, oa_twb, ra_tdb, ra_rh;
            double oa_frac, bf, target_tdb, airflow, p;
            sscanf(line, "%*s %lf %lf %lf %lf %lf %lf %lf %lf %lf",
                   &oa_tdb, &oa_twb, &ra_tdb, &ra_rh,
                   &oa_frac, &bf, &target_tdb, &airflow, &p);

            /* Compute outdoor air state from wet-bulb */
            double oa_W, oa_Tdp, oa_RH, oa_Pv, oa_h, oa_v, oa_mu;
            CalcPsychrometricsFromTWetBulb(oa_tdb, oa_twb, p,
                &oa_W, &oa_Tdp, &oa_RH, &oa_Pv, &oa_h, &oa_v, &oa_mu);

            /* Compute return air state from relative humidity */
            double ra_W, ra_Twb, ra_Tdp, ra_Pv, ra_h, ra_v, ra_mu;
            CalcPsychrometricsFromRelHum(ra_tdb, ra_rh, p,
                &ra_W, &ra_Twb, &ra_Tdp, &ra_Pv, &ra_h, &ra_v, &ra_mu);

            AirState oa_state = {oa_tdb, oa_W, oa_h};
            AirState ra_state = {ra_tdb, ra_W, ra_h};

            AirState mixed = compute_mixed_air(oa_state, ra_state, oa_frac);
            double adp = compute_adp(mixed.tdb, target_tdb, bf);
            AirState leaving = compute_coil_leaving(mixed, adp, bf, p);
            CoilLoads loads = compute_coil_loads(mixed, leaving, airflow);

            printf("%.4f %.8f %.4f %.4f %.8f %.3f %.3f %.3f\n",
                   mixed.tdb, mixed.w, adp,
                   leaving.tdb, leaving.w,
                   loads.q_total, loads.q_sensible, loads.q_latent);
        }
        else
        {
            fprintf(stderr, "Unknown command: %s\n", cmd);
        }

        fflush(stdout);
    }

    return 0;
}
