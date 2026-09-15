/*
 * HVAC Air Handling Unit process calculations — correct implementation.
 *
 */

#include "ahu.h"
#include "psychro.h"

/*
 * Compute mixed air state from outdoor and return air streams.
 * The mixed humidity ratio and enthalpy are mass-weighted averages.
 * The mixed dry-bulb temperature is back-calculated from the
 * mixed enthalpy and humidity ratio using the inverse of the
 * moist air enthalpy equation (ASHRAE eqn 30).
 */
AirState compute_mixed_air(AirState oa, AirState ra, double oa_fraction)
{
    AirState mixed;

    mixed.w = oa_fraction * oa.w + (1.0 - oa_fraction) * ra.w;
    mixed.h = oa_fraction * oa.h + (1.0 - oa_fraction) * ra.h;
    mixed.tdb = GetTDryBulbFromEnthalpyAndHumRatio(mixed.h, mixed.w);

    return mixed;
}

/*
 * Compute apparatus dew point (ADP) temperature from the bypass factor
 * relationship.  The bypass factor BF is defined such that:
 *
 *   T_leaving = BF * T_entering + (1 - BF) * T_ADP
 *
 * Solving for T_ADP when T_leaving equals the target supply temperature:
 *
 *   T_ADP = (T_target - BF * T_entering) / (1 - BF)
 */
double compute_adp(double entering_tdb, double target_supply_tdb,
                   double bypass_factor)
{
    return (target_supply_tdb - bypass_factor * entering_tdb)
           / (1.0 - bypass_factor);
}

/*
 * Compute coil leaving air state using the bypass factor model.
 *
 * The portion of air (1-BF) that contacts the coil surface reaches
 * the apparatus dew point temperature and becomes saturated at that
 * temperature.  The remaining portion BF bypasses the coil unchanged.
 *
 *   T_out = BF * T_in + (1 - BF) * T_ADP
 *   W_out = BF * W_in + (1 - BF) * W_sat(T_ADP)
 *   h_out = computed from T_out and W_out via eqn 30
 */
AirState compute_coil_leaving(AirState entering, double adp_temp,
                               double bypass_factor, double pressure)
{
    AirState leaving;

    leaving.tdb = bypass_factor * entering.tdb
                  + (1.0 - bypass_factor) * adp_temp;

    double w_sat_adp = GetSatHumRatio(adp_temp, pressure);
    leaving.w = bypass_factor * entering.w
                + (1.0 - bypass_factor) * w_sat_adp;

    leaving.h = GetMoistAirEnthalpy(leaving.tdb, leaving.w);

    return leaving;
}

/*
 * Compute coil thermal loads from entering and leaving air states.
 *
 *   q_total    = m_dot * (h_in - h_out) / 1000   [kW]
 *   q_sensible = m_dot * 1.006 * (T_in - T_out)  [kW]
 *   q_latent   = q_total - q_sensible             [kW]
 *
 * where 1.006 kJ/(kg·K) is the specific heat of dry air.
 */
CoilLoads compute_coil_loads(AirState entering, AirState leaving,
                             double airflow_kgs)
{
    CoilLoads loads;

    loads.q_total    = airflow_kgs * (entering.h - leaving.h) / 1000.0;
    loads.q_sensible = airflow_kgs * 1.006 * (entering.tdb - leaving.tdb);
    loads.q_latent   = loads.q_total - loads.q_sensible;

    return loads;
}
