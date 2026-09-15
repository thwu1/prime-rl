/*
 * Psychrometric calculations for moist air properties.
 * Based on ASHRAE Handbook - Fundamentals (2017) Chapter 1.
 * SI units only.
 *
 */

#include <float.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>

#include "psychro.h"

/*****************************************************************************
 * Constants
 *****************************************************************************/

#define ZERO_CELSIUS_AS_KELVIN    273.15
#define R_DA_SI                   287.042   /* J/(kg_da·K) dry air gas constant */
#define MAX_ITER_COUNT            100
#define MIN_HUM_RATIO             1e-7
#define FREEZING_POINT_WATER_SI   0.0
#define TRIPLE_POINT_WATER_SI     0.01
#define PSYCHROLIB_TOLERANCE      0.001

#ifndef min
#define min(a,b) (((a) < (b)) ? (a) : (b))
#endif
#ifndef max
#define max(a,b) (((a) > (b)) ? (a) : (b))
#endif

/*****************************************************************************
 * Temperature conversions
 *****************************************************************************/

double GetTKelvinFromTCelsius(double T_C)
{
    return T_C + ZERO_CELSIUS_AS_KELVIN;
}

double GetTCelsiusFromTKelvin(double T_K)
{
    return T_K - ZERO_CELSIUS_AS_KELVIN;
}

/*****************************************************************************
 * Saturation vapor pressure
 * Reference: ASHRAE Handbook - Fundamentals (2017) ch. 1 eqn 5 & 6
 *
 * The equations are defined above and below the triple point of water.
 * Eqn 5 applies below the triple point (ice), eqn 6 above (liquid).
 *****************************************************************************/

double GetSatVapPres(double TDryBulb)
{
    double LnPws, T;

    T = GetTKelvinFromTCelsius(TDryBulb);

    if (TDryBulb >= TRIPLE_POINT_WATER_SI)
    {
        /* Equation 5 — saturation pressure over ice */
        LnPws = -5.6745359E+03 / T + 6.3925247 - 9.677843E-03 * T
                + 6.2215701E-07 * T * T + 2.0747825E-09 * pow(T, 3)
                - 9.484024E-13 * pow(T, 4) + 4.1635019 * log(T);
    }
    else
    {
        /* Equation 6 — saturation pressure over liquid water */
        LnPws = -5.8002206E+03 / T + 1.3914993 - 4.8640239E-02 * T
                + 4.1764768E-05 * T * T - 1.4452093E-08 * pow(T, 3)
                + 6.5459673 * log(T);
    }

    return exp(LnPws);
}

/*****************************************************************************
 * Derivative of ln(Pws) — used by Newton-Raphson dew point solver
 * Reference: ASHRAE Handbook - Fundamentals (2017) ch. 1 eqn 5 & 6
 *****************************************************************************/

static double dLnPws_(double TDryBulb)
{
    double dLnPws, T;

    T = GetTKelvinFromTCelsius(TDryBulb);

    if (TDryBulb >= TRIPLE_POINT_WATER_SI)
    {
        dLnPws = 5.6745359E+03 / pow(T, 2) - 9.677843E-03
                 + 2 * 6.2215701E-07 * T + 3 * 2.0747825E-09 * pow(T, 2)
                 - 4 * 9.484024E-13 * pow(T, 3) + 4.1635019 / T;
    }
    else
    {
        dLnPws = 5.8002206E+03 / pow(T, 2) - 4.8640239E-02
                 + 2 * 4.1764768E-05 * T - 3 * 1.4452093E-08 * pow(T, 2)
                 + 6.5459673 / T;
    }

    return dLnPws;
}

/*****************************************************************************
 * Dew point from vapor pressure — Newton-Raphson on ln(Pws)
 * Reference: ASHRAE Handbook - Fundamentals (2017) ch. 1 eqn 5 & 6
 *****************************************************************************/

double GetTDewPointFromVapPres(double TDryBulb, double VapPres)
{
    double TDewPoint = TDryBulb;
    double lnVP = log(VapPres);
    double TDewPoint_iter, lnVP_iter, d_lnVP;
    int index = 1;

    do
    {
        TDewPoint_iter = TDewPoint;
        lnVP_iter = log(GetSatVapPres(TDewPoint_iter));
        d_lnVP = dLnPws_(TDewPoint_iter);

        TDewPoint = TDewPoint_iter - (lnVP_iter - lnVP) / d_lnVP;
        TDewPoint = max(TDewPoint, -100.0);
        TDewPoint = min(TDewPoint, 200.0);

        if (index > MAX_ITER_COUNT)
        {
            fprintf(stderr, "GetTDewPointFromVapPres: convergence failure\n");
            break;
        }
        index++;
    }
    while (fabs(TDewPoint - TDewPoint_iter) > PSYCHROLIB_TOLERANCE);

    return min(TDewPoint, TDryBulb);
}

/*****************************************************************************
 * Vapor pressure from dew point — just the saturation pressure at Tdp
 * Reference: ASHRAE Handbook - Fundamentals (2017) ch. 1 eqn 36
 *****************************************************************************/

double GetVapPresFromTDewPoint(double TDewPoint)
{
    return GetSatVapPres(TDewPoint);
}

/*****************************************************************************
 * Conversions between vapor pressure and relative humidity
 * Reference: ASHRAE Handbook - Fundamentals (2017) ch. 1 eqn 12, 22
 *****************************************************************************/

double GetVapPresFromRelHum(double TDryBulb, double RelHum)
{
    return RelHum * GetSatVapPres(TDryBulb);
}

double GetRelHumFromVapPres(double TDryBulb, double VapPres)
{
    return VapPres / GetSatVapPres(TDryBulb);
}

/*****************************************************************************
 * Conversions between humidity ratio and vapor pressure
 * Reference: ASHRAE Handbook - Fundamentals (2017) ch. 1 eqn 20
 *****************************************************************************/

double GetHumRatioFromVapPres(double VapPres, double Pressure)
{
    double HumRatio = 0.621945 * VapPres / (Pressure - VapPres);
    return max(HumRatio, MIN_HUM_RATIO);
}

double GetVapPresFromHumRatio(double HumRatio, double Pressure)
{
    double BoundedHumRatio = max(HumRatio, MIN_HUM_RATIO);
    return Pressure * BoundedHumRatio / (0.621945 + BoundedHumRatio);
}

/*****************************************************************************
 * Saturated humidity ratio
 * Reference: ASHRAE Handbook - Fundamentals (2017) ch. 1 eqn 36
 *****************************************************************************/

double GetSatHumRatio(double TDryBulb, double Pressure)
{
    double SatVaporPres = GetSatVapPres(TDryBulb);
    double SatHumRatio = 0.621945 * SatVaporPres / (Pressure - SatVaporPres);
    return max(SatHumRatio, MIN_HUM_RATIO);
}

/*****************************************************************************
 * Humidity ratio from wet-bulb temperature
 * Reference: ASHRAE Handbook - Fundamentals (2017) ch. 1 eqn 33 and 35
 *****************************************************************************/

double GetHumRatioFromTWetBulb(double TDryBulb, double TWetBulb, double Pressure)
{
    double Wsstar;
    double HumRatio;

    Wsstar = GetSatHumRatio(TWetBulb, Pressure);

    if (TWetBulb >= FREEZING_POINT_WATER_SI)
      HumRatio = ((2501. - 2.326 * TWetBulb) * Wsstar - 1.006 * (TDryBulb - TWetBulb))
         / (2501. + 1.86 * TDryBulb - 4.186 * TWetBulb);
    else
      HumRatio = ((2501. - 2.326 * TWetBulb) * Wsstar - 1.006 * (TDryBulb - TWetBulb))
         / (2501. + 1.86 * TDryBulb - 4.186 * TWetBulb);  /* below freezing */

    return max(HumRatio, MIN_HUM_RATIO);
}

/*****************************************************************************
 * Wet-bulb from humidity ratio — bisection solver
 * Reference: ASHRAE Handbook - Fundamentals (2017) ch. 1 eqn 33 and 35
 *****************************************************************************/

double GetTWetBulbFromHumRatio(double TDryBulb, double HumRatio, double Pressure)
{
    double Wstar;
    double TDewPoint, TWetBulb, TWetBulbSup, TWetBulbInf, BoundedHumRatio;
    int index = 1;

    BoundedHumRatio = max(HumRatio, MIN_HUM_RATIO);
    TDewPoint = GetTDewPointFromHumRatio(TDryBulb, BoundedHumRatio, Pressure);

    TWetBulbSup = TDryBulb;
    TWetBulbInf = TDewPoint;
    TWetBulb = (TWetBulbInf + TWetBulbSup) / 2.;

    while ((TWetBulbSup - TWetBulbInf) > 100.0 * PSYCHROLIB_TOLERANCE)
    {
        Wstar = GetHumRatioFromTWetBulb(TDryBulb, TWetBulb, Pressure);

        if (Wstar > BoundedHumRatio)
            TWetBulbSup = TWetBulb;
        else
            TWetBulbInf = TWetBulb;

        TWetBulb = (TWetBulbSup + TWetBulbInf) / 2.;

        if (index > MAX_ITER_COUNT)
        {
            fprintf(stderr, "GetTWetBulbFromHumRatio: convergence failure\n");
            break;
        }
        index++;
    }

    return TWetBulb;
}

/*****************************************************************************
 * Conversions between humidity ratio and relative humidity
 * Reference: ASHRAE Handbook - Fundamentals (2017) ch. 1
 *****************************************************************************/

double GetHumRatioFromRelHum(double TDryBulb, double RelHum, double Pressure)
{
    double VapPres = GetVapPresFromRelHum(TDryBulb, RelHum);
    return GetHumRatioFromVapPres(VapPres, Pressure);
}

double GetRelHumFromHumRatio(double TDryBulb, double HumRatio, double Pressure)
{
    double VapPres = GetVapPresFromHumRatio(HumRatio, Pressure);
    return GetRelHumFromVapPres(TDryBulb, VapPres);
}

/*****************************************************************************
 * Conversions between dew point and relative humidity
 * Reference: ASHRAE Handbook - Fundamentals (2017) ch. 1 eqn 22
 *****************************************************************************/

double GetRelHumFromTDewPoint(double TDryBulb, double TDewPoint)
{
    return GetSatVapPres(TDewPoint) / GetSatVapPres(TDryBulb);
}

double GetTDewPointFromRelHum(double TDryBulb, double RelHum)
{
    double VapPres = GetVapPresFromRelHum(TDryBulb, RelHum);
    return GetTDewPointFromVapPres(TDryBulb, VapPres);
}

/*****************************************************************************
 * Conversions between humidity ratio and dew point
 * Reference: ASHRAE Handbook - Fundamentals (2017) ch. 1
 *****************************************************************************/

double GetHumRatioFromTDewPoint(double TDewPoint, double Pressure)
{
    double VapPres = GetSatVapPres(TDewPoint);
    return GetHumRatioFromVapPres(VapPres, Pressure);
}

double GetTDewPointFromHumRatio(double TDryBulb, double HumRatio, double Pressure)
{
    double VapPres = GetVapPresFromHumRatio(HumRatio, Pressure);
    return GetTDewPointFromVapPres(TDryBulb, VapPres);
}

/*****************************************************************************
 * Convenience: wet-bulb from relative humidity or dew point
 *****************************************************************************/

double GetTWetBulbFromRelHum(double TDryBulb, double RelHum, double Pressure)
{
    double HumRatio = GetHumRatioFromRelHum(TDryBulb, RelHum, Pressure);
    return GetTWetBulbFromHumRatio(TDryBulb, HumRatio, Pressure);
}

double GetTWetBulbFromTDewPoint(double TDryBulb, double TDewPoint, double Pressure)
{
    double HumRatio = GetHumRatioFromTDewPoint(TDewPoint, Pressure);
    return GetTWetBulbFromHumRatio(TDryBulb, HumRatio, Pressure);
}

/*****************************************************************************
 * Moist air enthalpy
 * Reference: ASHRAE Handbook - Fundamentals (2017) ch. 1 eqn 30
 *****************************************************************************/

double GetMoistAirEnthalpy(double TDryBulb, double HumRatio)
{
    double BoundedHumRatio = max(HumRatio, MIN_HUM_RATIO);
    return (1.006 * TDryBulb + BoundedHumRatio * (2501. + 1.86 * TDryBulb)) * 1000.;
}

/*****************************************************************************
 * Moist air specific volume
 * Reference: ASHRAE Handbook - Fundamentals (2017) ch. 1 eqn 26
 *****************************************************************************/

double GetMoistAirVolume(double TDryBulb, double HumRatio, double Pressure)
{
    double BoundedHumRatio = max(HumRatio, MIN_HUM_RATIO);
    return R_DA_SI * GetTKelvinFromTCelsius(TDryBulb)
           * (1. + 1.007858 * BoundedHumRatio) / Pressure;
}

/*****************************************************************************
 * Moist air density
 * Reference: ASHRAE Handbook - Fundamentals (2017) ch. 1 eqn 11
 *****************************************************************************/

double GetMoistAirDensity(double TDryBulb, double HumRatio, double Pressure)
{
    double BoundedHumRatio = max(HumRatio, MIN_HUM_RATIO);
    return (1. + BoundedHumRatio) / GetMoistAirVolume(TDryBulb, BoundedHumRatio, Pressure);
}

/*****************************************************************************
 * Degree of saturation
 * Reference: ASHRAE Handbook - Fundamentals (2009) ch. 1 eqn 12
 *****************************************************************************/

double GetDegreeOfSaturation(double TDryBulb, double HumRatio, double Pressure)
{
    double BoundedHumRatio = max(HumRatio, MIN_HUM_RATIO);
    return BoundedHumRatio / GetSatHumRatio(TDryBulb, Pressure);
}

/*****************************************************************************
 * Dry-bulb temperature from enthalpy and humidity ratio
 * Reference: ASHRAE Handbook - Fundamentals (2017) ch. 1 eqn 30 rearranged
 *****************************************************************************/

double GetTDryBulbFromEnthalpyAndHumRatio(double MoistAirEnthalpy, double HumRatio)
{
    double BoundedHumRatio = max(HumRatio, MIN_HUM_RATIO);
    return (MoistAirEnthalpy / 1000.0 - 2501.0 * BoundedHumRatio)
           / (1.006 + 1.86 * BoundedHumRatio);
}

/*****************************************************************************
 * Saturated air enthalpy
 *****************************************************************************/

double GetSatAirEnthalpy(double TDryBulb, double Pressure)
{
    return GetMoistAirEnthalpy(TDryBulb, GetSatHumRatio(TDryBulb, Pressure));
}

/*****************************************************************************
 * Full psychrometric state calculations
 *****************************************************************************/

void CalcPsychrometricsFromTWetBulb(
    double TDryBulb, double TWetBulb, double Pressure,
    double *HumRatio, double *TDewPoint, double *RelHum, double *VapPres,
    double *MoistAirEnthalpy, double *MoistAirVolume, double *DegreeOfSaturation)
{
    *HumRatio = GetHumRatioFromTWetBulb(TDryBulb, TWetBulb, Pressure);
    *TDewPoint = GetTDewPointFromHumRatio(TDryBulb, *HumRatio, Pressure);
    *RelHum = GetRelHumFromHumRatio(TDryBulb, *HumRatio, Pressure);
    *VapPres = GetVapPresFromHumRatio(*HumRatio, Pressure);
    *MoistAirEnthalpy = GetMoistAirEnthalpy(TDryBulb, *HumRatio);
    *MoistAirVolume = GetMoistAirVolume(TDryBulb, *HumRatio, Pressure);
    *DegreeOfSaturation = GetDegreeOfSaturation(TDryBulb, *HumRatio, Pressure);
}

void CalcPsychrometricsFromTDewPoint(
    double TDryBulb, double TDewPoint, double Pressure,
    double *HumRatio, double *TWetBulb, double *RelHum, double *VapPres,
    double *MoistAirEnthalpy, double *MoistAirVolume, double *DegreeOfSaturation)
{
    *HumRatio = GetHumRatioFromTDewPoint(TDewPoint, Pressure);
    *TWetBulb = GetTWetBulbFromHumRatio(TDryBulb, *HumRatio, Pressure);
    *RelHum = GetRelHumFromHumRatio(TDryBulb, *HumRatio, Pressure);
    *VapPres = GetVapPresFromHumRatio(*HumRatio, Pressure);
    *MoistAirEnthalpy = GetMoistAirEnthalpy(TDryBulb, *HumRatio);
    *MoistAirVolume = GetMoistAirVolume(TDryBulb, *HumRatio, Pressure);
    *DegreeOfSaturation = GetDegreeOfSaturation(TDryBulb, *HumRatio, Pressure);
}

void CalcPsychrometricsFromRelHum(
    double TDryBulb, double RelHum, double Pressure,
    double *HumRatio, double *TWetBulb, double *TDewPoint, double *VapPres,
    double *MoistAirEnthalpy, double *MoistAirVolume, double *DegreeOfSaturation)
{
    *HumRatio = GetHumRatioFromRelHum(TDryBulb, RelHum, Pressure);
    *TWetBulb = GetTWetBulbFromHumRatio(TDryBulb, *HumRatio, Pressure);
    *TDewPoint = GetTDewPointFromHumRatio(TDryBulb, *HumRatio, Pressure);
    *VapPres = GetVapPresFromHumRatio(*HumRatio, Pressure);
    *MoistAirEnthalpy = GetMoistAirEnthalpy(TDryBulb, *HumRatio);
    *MoistAirVolume = GetMoistAirVolume(TDryBulb, *HumRatio, Pressure);
    *DegreeOfSaturation = GetDegreeOfSaturation(TDryBulb, *HumRatio, Pressure);
}
