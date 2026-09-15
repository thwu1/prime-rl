#ifndef AHU_H
#define AHU_H

/*
 * HVAC Air Handling Unit (AHU) process calculations.
 * Cooling coil model with bypass factor and apparatus dew point.
 * All values in SI units.
 */

typedef struct {
    double tdb;   /* dry-bulb temperature (C) */
    double w;     /* humidity ratio (kg_w/kg_da) */
    double h;     /* moist air enthalpy (J/kg_da) */
} AirState;

typedef struct {
    double q_total;     /* total cooling load (kW) */
    double q_sensible;  /* sensible cooling load (kW) */
    double q_latent;    /* latent cooling load (kW) */
} CoilLoads;

/*
 * Compute mixed air state from outdoor and return air streams.
 * oa_fraction is the outdoor air mass fraction of dry air [0,1].
 * Mixed humidity ratio and enthalpy are mass-weighted averages.
 * Mixed dry-bulb is derived from the mixed enthalpy and humidity ratio.
 */
AirState compute_mixed_air(AirState oa, AirState ra, double oa_fraction);

/*
 * Compute apparatus dew point (ADP) temperature.
 * The ADP is the effective coil surface temperature such that
 * the bypass factor relationship yields the target supply temperature:
 *   T_supply = BF * T_entering + (1 - BF) * T_ADP
 */
double compute_adp(double entering_tdb, double target_supply_tdb,
                   double bypass_factor);

/*
 * Compute coil leaving air state using the bypass factor model.
 * Leaving dry-bulb: T_out = BF * T_in + (1 - BF) * T_ADP
 * Leaving humidity ratio: W_out = BF * W_in + (1 - BF) * W_sat(T_ADP)
 * Leaving enthalpy is computed from leaving T_db and W.
 */
AirState compute_coil_leaving(AirState entering, double adp_temp,
                               double bypass_factor, double pressure);

/*
 * Compute coil thermal loads from entering and leaving air states.
 * q_total = m_dot * (h_in - h_out) / 1000        [kW]
 * q_sensible = m_dot * 1.006 * (T_in - T_out)    [kW]
 * q_latent = q_total - q_sensible                 [kW]
 */
CoilLoads compute_coil_loads(AirState entering, AirState leaving,
                             double airflow_kgs);

#endif /* AHU_H */
