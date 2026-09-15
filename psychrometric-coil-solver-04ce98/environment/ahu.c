/*
 * HVAC Air Handling Unit process calculations — stub implementations.
 * These functions must be completed.
 */

#include "ahu.h"
#include "psychro.h"

AirState compute_mixed_air(AirState oa, AirState ra, double oa_fraction)
{
    AirState mixed = {0.0, 0.0, 0.0};
    /* TODO: implement mixed air state calculation */
    return mixed;
}

double compute_adp(double entering_tdb, double target_supply_tdb,
                   double bypass_factor)
{
    /* TODO: implement apparatus dew point calculation */
    return 0.0;
}

AirState compute_coil_leaving(AirState entering, double adp_temp,
                               double bypass_factor, double pressure)
{
    AirState leaving = {0.0, 0.0, 0.0};
    /* TODO: implement coil leaving state calculation */
    return leaving;
}

CoilLoads compute_coil_loads(AirState entering, AirState leaving,
                             double airflow_kgs)
{
    CoilLoads loads = {0.0, 0.0, 0.0};
    /* TODO: implement coil load calculation */
    return loads;
}
