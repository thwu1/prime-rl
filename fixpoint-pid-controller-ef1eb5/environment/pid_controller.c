/*
 * PID controller implementation — STUB.
 *
 * pid_init stores configuration into the struct.
 * pid_step is unimplemented and returns zero.
 *
 */

#include "pid_controller.h"

void pid_init(PIDController *pid,
              fix16_t kp, fix16_t ki, fix16_t kd,
              fix16_t n, fix16_t kb, fix16_t ts,
              fix16_t out_min, fix16_t out_max)
{
    pid->kp = kp;
    pid->ki = ki;
    pid->kd = kd;
    pid->n  = n;
    pid->kb = kb;
    pid->ts = ts;
    pid->out_min = out_min;
    pid->out_max = out_max;

    pid->integral       = 0;
    pid->deriv_filtered = 0;
    pid->prev_error     = 0;
    pid->prev_output    = 0;
    pid->prev_unsat     = 0;
}

fix16_t pid_step(PIDController *pid, fix16_t reference, fix16_t feedback)
{
    (void)pid;
    (void)reference;
    (void)feedback;
    return 0;
}
