/*
 * Simulation harness: runs closed-loop PID + plant simulation
 * and writes trace output to /app/trace_output.csv
 *
 * Output format (CSV, no header):
 *   step_index, reference_hex, output_hex, control_hex, error_hex
 *
 * All hex values are the raw Q16.16 int32_t printed as 8-digit
 * zero-padded lowercase hex (signed values in two's complement).
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include "fixpoint.h"
#include "sim_params.h"
#include "plant.h"
#include "pid_controller.h"

int main(void)
{
    Plant plant;
    PIDController pid;

    plant_init(&plant, PLANT_OMEGA_N, PLANT_ZETA, SIM_TS);
    pid_init(&pid, PID_KP, PID_KI, PID_KD, PID_N, PID_KB,
             SIM_TS, PID_OUT_MIN, PID_OUT_MAX);

    FILE *fp = fopen("/app/trace_output.csv", "w");
    if (!fp) {
        fprintf(stderr, "ERROR: cannot open /app/trace_output.csv\n");
        return 1;
    }

    fix16_t y = 0; /* plant output */

    for (int k = 0; k < SIM_NUM_STEPS; k++) {
        /* Generate reference signal */
        fix16_t ref = 0;
        if (k >= REF_STEP1_INDEX && k < REF_STEP2_INDEX) {
            ref = REF_STEP1_VALUE;
        } else if (k >= REF_STEP2_INDEX) {
            ref = REF_STEP2_VALUE;
        }

        /* Compute control action */
        fix16_t u = pid_step(&pid, ref, y);

        /* Advance plant */
        y = plant_step(&plant, u);

        /* Compute error for trace */
        fix16_t error = fix16_ssub(ref, y);

        /* Write trace line */
        fprintf(fp, "%d,%08x,%08x,%08x,%08x\n",
                k,
                (uint32_t)ref,
                (uint32_t)y,
                (uint32_t)u,
                (uint32_t)error);
    }

    fclose(fp);
    printf("Trace written to /app/trace_output.csv (%d steps)\n",
           SIM_NUM_STEPS);
    return 0;
}
