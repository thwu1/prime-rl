#ifndef PSYCHRO_H
#define PSYCHRO_H

/*
 * Psychrometric calculations based on ASHRAE Handbook - Fundamentals (2017) Ch. 1
 * SI units only.
 *
 * Temperatures:       degrees Celsius (C)
 * Pressures:          Pascals (Pa)
 * Humidity ratios:    kg_water / kg_dry_air
 * Enthalpies:         J / kg_dry_air
 * Specific volumes:   m^3 / kg_dry_air
 * Densities:          kg / m^3
 * Relative humidity:  fraction [0, 1]
 */

/* Temperature conversions */
double GetTKelvinFromTCelsius(double T_C);
double GetTCelsiusFromTKelvin(double T_K);

/* Saturation vapor pressure (Pa) */
double GetSatVapPres(double TDryBulb);

/* Dew point from vapor pressure (Newton-Raphson) */
double GetTDewPointFromVapPres(double TDryBulb, double VapPres);

/* Vapor pressure from dew point */
double GetVapPresFromTDewPoint(double TDewPoint);

/* Vapor pressure from relative humidity */
double GetVapPresFromRelHum(double TDryBulb, double RelHum);

/* Relative humidity from vapor pressure */
double GetRelHumFromVapPres(double TDryBulb, double VapPres);

/* Humidity ratio from vapor pressure */
double GetHumRatioFromVapPres(double VapPres, double Pressure);

/* Vapor pressure from humidity ratio */
double GetVapPresFromHumRatio(double HumRatio, double Pressure);

/* Saturated humidity ratio */
double GetSatHumRatio(double TDryBulb, double Pressure);

/* Humidity ratio from wet-bulb (ASHRAE eqn 33/35) */
double GetHumRatioFromTWetBulb(double TDryBulb, double TWetBulb, double Pressure);

/* Wet-bulb from humidity ratio (bisection solver) */
double GetTWetBulbFromHumRatio(double TDryBulb, double HumRatio, double Pressure);

/* Humidity ratio from relative humidity */
double GetHumRatioFromRelHum(double TDryBulb, double RelHum, double Pressure);

/* Relative humidity from humidity ratio */
double GetRelHumFromHumRatio(double TDryBulb, double HumRatio, double Pressure);

/* Relative humidity from dew point */
double GetRelHumFromTDewPoint(double TDryBulb, double TDewPoint);

/* Dew point from relative humidity */
double GetTDewPointFromRelHum(double TDryBulb, double RelHum);

/* Humidity ratio from dew point */
double GetHumRatioFromTDewPoint(double TDewPoint, double Pressure);

/* Dew point from humidity ratio */
double GetTDewPointFromHumRatio(double TDryBulb, double HumRatio, double Pressure);

/* Wet-bulb from relative humidity */
double GetTWetBulbFromRelHum(double TDryBulb, double RelHum, double Pressure);

/* Wet-bulb from dew point */
double GetTWetBulbFromTDewPoint(double TDryBulb, double TDewPoint, double Pressure);

/* Moist air enthalpy (J/kg_da), eqn 30 */
double GetMoistAirEnthalpy(double TDryBulb, double HumRatio);

/* Moist air specific volume (m^3/kg_da), eqn 26 */
double GetMoistAirVolume(double TDryBulb, double HumRatio, double Pressure);

/* Moist air density (kg/m^3) */
double GetMoistAirDensity(double TDryBulb, double HumRatio, double Pressure);

/* Degree of saturation */
double GetDegreeOfSaturation(double TDryBulb, double HumRatio, double Pressure);

/* Dry-bulb from enthalpy and humidity ratio (inverse of eqn 30) */
double GetTDryBulbFromEnthalpyAndHumRatio(double MoistAirEnthalpy, double HumRatio);

/* Saturated air enthalpy */
double GetSatAirEnthalpy(double TDryBulb, double Pressure);

/* Full psychrometric state from wet-bulb */
void CalcPsychrometricsFromTWetBulb(
    double TDryBulb, double TWetBulb, double Pressure,
    double *HumRatio, double *TDewPoint, double *RelHum, double *VapPres,
    double *MoistAirEnthalpy, double *MoistAirVolume, double *DegreeOfSaturation);

/* Full psychrometric state from dew point */
void CalcPsychrometricsFromTDewPoint(
    double TDryBulb, double TDewPoint, double Pressure,
    double *HumRatio, double *TWetBulb, double *RelHum, double *VapPres,
    double *MoistAirEnthalpy, double *MoistAirVolume, double *DegreeOfSaturation);

/* Full psychrometric state from relative humidity */
void CalcPsychrometricsFromRelHum(
    double TDryBulb, double RelHum, double Pressure,
    double *HumRatio, double *TWetBulb, double *TDewPoint, double *VapPres,
    double *MoistAirEnthalpy, double *MoistAirVolume, double *DegreeOfSaturation);

#endif /* PSYCHRO_H */
