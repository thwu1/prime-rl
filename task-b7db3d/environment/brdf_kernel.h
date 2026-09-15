#ifndef BRDF_KERNEL_H
#define BRDF_KERNEL_H

typedef struct {
    double x;
    double y;
    double z;
} Vec3;

/* BRDF evaluation functions */
double brdf_D_GGX(double NoH, double alpha);
double brdf_V_SmithGGX(double NoV, double NoL, double alpha);
double brdf_F_Schlick_scalar(double VoH, double f0);
double brdf_D_Charlie(double NoH, double roughness);
double brdf_V_Neubelt(double NoV, double NoL);

/* Importance sampling */
Vec3 sample_GGX(double xi_x, double xi_y, double alpha);
Vec3 sample_hemisphere_cosine(double xi_x, double xi_y);
Vec3 sample_hemisphere_uniform(double xi_x, double xi_y);
Vec3 sample_Charlie(double xi_x, double xi_y, double roughness);

/* Utilities */
double hammersley_radical_inverse(unsigned int bits);

#endif
