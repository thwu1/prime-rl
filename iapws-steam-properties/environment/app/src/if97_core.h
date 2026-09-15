#ifndef IF97_CORE_H
#define IF97_CORE_H


typedef struct {
    double v;   /* specific volume, m^3/kg */
    double h;   /* specific enthalpy, kJ/kg */
    double u;   /* specific internal energy, kJ/kg */
    double s;   /* specific entropy, kJ/(kg*K) */
    double cp;  /* isobaric heat capacity, kJ/(kg*K) */
    double w;   /* speed of sound, m/s */
    double p;   /* pressure, MPa (input for Gibbs regions, computed for Region 3) */
} IF97Props;

/* Forward property equations */
IF97Props region1_props(double T, double p);
IF97Props region2_props(double T, double p);
IF97Props region3_props(double T, double rho);
IF97Props region5_props(double T, double p);

/* Saturation curve */
double saturation_pressure(double T);
double saturation_temperature(double p);

/* Region detection: returns 1-5, or -1 for out-of-range */
int determine_region(double T, double p);

#endif
