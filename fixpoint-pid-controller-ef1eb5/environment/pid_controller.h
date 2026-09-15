#ifndef PID_CONTROLLER_H
#define PID_CONTROLLER_H

/*
 * PID controller interface — Q16.16 fixed-point.
 *
 */

#include "fixpoint.h"

typedef struct {
    /* Configuration (set by pid_init, read-only during stepping) */
    fix16_t kp;
    fix16_t ki;
    fix16_t kd;
    fix16_t n;
    fix16_t kb;
    fix16_t ts;
    fix16_t out_max;
    fix16_t out_min;

    /* Internal state (updated each step) */
    fix16_t integral;
    fix16_t deriv_filtered;
    fix16_t prev_error;
    fix16_t prev_output;
    fix16_t prev_unsat;
} PIDController;

/*
 * Initialize controller state and store configuration parameters.
 */
void pid_init(PIDController *pid,
              fix16_t kp, fix16_t ki, fix16_t kd,
              fix16_t n, fix16_t kb, fix16_t ts,
              fix16_t out_min, fix16_t out_max);

/*
 * Compute one control step given the current reference and
 * plant feedback. Returns the saturated control output.
 */
fix16_t pid_step(PIDController *pid, fix16_t reference, fix16_t feedback);

#endif /* PID_CONTROLLER_H */
