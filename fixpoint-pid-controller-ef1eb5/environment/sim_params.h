#ifndef SIM_PARAMS_H
#define SIM_PARAMS_H

/*
 * Simulation parameters for closed-loop control simulation.
 *
 */

#include "fixpoint.h"

/* Simulation timing */
#define SIM_NUM_STEPS     5000
/* Ts = 0.001 s */
#define SIM_TS            ((fix16_t)66)

/* Controller gains */
#define PID_KP            FIX16_CONST(2.5)
#define PID_KI            FIX16_CONST(8.0)
#define PID_KD            FIX16_CONST(0.15)
#define PID_N             FIX16_CONST(20.0)
#define PID_KB            FIX16_CONST(5.0)

/* Output saturation limits */
#define PID_OUT_MAX       FIX16_CONST(10.0)
#define PID_OUT_MIN       FIX16_CONST(-10.0)

/* Plant parameters:
 *   G(s) = omega_n^2 / (s^2 + 2*zeta*omega_n*s + omega_n^2)
 */
#define PLANT_OMEGA_N     FIX16_CONST(10.0)
#define PLANT_ZETA        FIX16_CONST(0.3)

/* Reference signal schedule */
#define REF_STEP1_INDEX   100
#define REF_STEP1_VALUE   FIX16_ONE
#define REF_STEP2_INDEX   3000
#define REF_STEP2_VALUE   FIX16_CONST(0.5)

#endif /* SIM_PARAMS_H */
