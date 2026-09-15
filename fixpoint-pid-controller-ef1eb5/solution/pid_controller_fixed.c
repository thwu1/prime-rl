/*
 * Reference PID controller implementation.
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
    fix16_t error = fix16_ssub(reference, feedback);

    fix16_t p_term = fix16_smul(pid->kp, error);

    fix16_t ki_ts = fix16_smul(pid->ki, pid->ts);
    fix16_t kb_ts = fix16_smul(pid->kb, pid->ts);

    fix16_t sat_error = fix16_ssub(pid->prev_output, pid->prev_unsat);
    fix16_t aw_correction = fix16_smul(kb_ts, sat_error);

    pid->integral = fix16_sadd(pid->integral,
                    fix16_sadd(fix16_smul(ki_ts, error),
                               aw_correction));

    fix16_t de = fix16_ssub(error, pid->prev_error);

    fix16_t kd_n = fix16_smul(pid->kd, pid->n);
    fix16_t d_num = fix16_sadd(fix16_smul(kd_n, de),
                               pid->deriv_filtered);

    fix16_t n_ts = fix16_smul(pid->n, pid->ts);
    fix16_t d_den = fix16_sadd(FIX16_ONE, n_ts);

    pid->deriv_filtered = fix16_sdiv(d_num, d_den);

    fix16_t u_unsat = fix16_sadd(p_term,
                       fix16_sadd(pid->integral, pid->deriv_filtered));

    fix16_t u_sat = fix16_clamp(u_unsat, pid->out_min, pid->out_max);

    pid->prev_error  = error;
    pid->prev_output = u_sat;
    pid->prev_unsat  = u_unsat;

    return u_sat;
}
