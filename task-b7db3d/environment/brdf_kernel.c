#include "brdf_kernel.h"
#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

/* ---------- Normal Distribution Functions ---------- */

double brdf_D_GGX(double NoH, double alpha) {
    double a2 = alpha;
    double f = NoH * NoH * (a2 - 1.0) + 1.0;
    return a2 / (M_PI * f * f);
}

double brdf_D_Charlie(double NoH, double roughness) {
    double sin2h = fmax(1.0 - NoH * NoH, 0.0);
    if (sin2h < 1e-15) return 0.0;
    double inv_r = 1.0 / roughness;
    return (2.0 + inv_r) * pow(sin2h, inv_r) / (2.0 * M_PI);
}

/* ---------- Visibility / Geometry ---------- */

double brdf_V_SmithGGX(double NoV, double NoL, double alpha) {
    double a = alpha;
    double GGXV = NoL * (NoV * (1.0 - a) + a);
    double GGXL = NoV * (NoL * (1.0 - a) + a);
    return 0.5 / (GGXV + GGXL + 1e-7);
}

double brdf_V_Neubelt(double NoV, double NoL) {
    return 1.0 / (4.0 * (NoL + NoV - NoL * NoV) + 1e-7);
}

/* ---------- Fresnel ---------- */

double brdf_F_Schlick_scalar(double VoH, double f0) {
    return f0 + (1.0 - f0) * pow(1.0 - VoH, 4.0);
}

/* ---------- Hammersley Sequence ---------- */

double hammersley_radical_inverse(unsigned int bits) {
    bits = (bits << 16u) | (bits >> 16u);
    bits = ((bits & 0x55555555u) << 1u) | ((bits & 0xAAAAAAAAu) >> 1u);
    bits = ((bits & 0x33333333u) << 2u) | ((bits & 0xCCCCCCCCu) >> 2u);
    bits = ((bits & 0x0F0F0F0Fu) << 4u) | ((bits & 0xF0F0F0F0u) >> 4u);
    bits = ((bits & 0x00FF00FFu) << 8u) | ((bits & 0xFF00FF00u) >> 8u);
    return (double)bits * 2.3283064365386963e-10;
}

/* ---------- Importance Sampling ---------- */

Vec3 sample_GGX(double xi_x, double xi_y, double alpha) {
    double a2 = alpha;
    double cosTheta2 = (1.0 - xi_y) / (1.0 + (a2 - 1.0) * xi_y);
    double cosTheta = sqrt(fmax(cosTheta2, 0.0));
    double sinTheta = sqrt(fmax(1.0 - cosTheta2, 0.0));
    double phi = 2.0 * M_PI * xi_x;
    Vec3 H;
    H.x = sinTheta * cos(phi);
    H.y = sinTheta * sin(phi);
    H.z = cosTheta;
    return H;
}

Vec3 sample_hemisphere_cosine(double xi_x, double xi_y) {
    double sinTheta = sqrt(xi_y);
    double cosTheta = sqrt(fmax(1.0 - xi_y, 0.0));
    double phi = 2.0 * M_PI * xi_x;
    Vec3 H;
    H.x = sinTheta * cos(phi);
    H.y = sinTheta * sin(phi);
    H.z = cosTheta;
    return H;
}

Vec3 sample_hemisphere_uniform(double xi_x, double xi_y) {
    double cosTheta = xi_y;
    double sinTheta = sqrt(fmax(1.0 - cosTheta * cosTheta, 0.0));
    double phi = 2.0 * M_PI * xi_x;
    Vec3 H;
    H.x = sinTheta * cos(phi);
    H.y = sinTheta * sin(phi);
    H.z = cosTheta;
    return H;
}

Vec3 sample_Charlie(double xi_x, double xi_y, double roughness) {
    double sinTheta = pow(fmax(xi_y, 1e-10), roughness / (2.0 * roughness + 1.0));
    double cosTheta = sqrt(fmax(1.0 - sinTheta * sinTheta, 0.0));
    double phi = 2.0 * M_PI * xi_x;
    Vec3 H;
    H.x = sinTheta * cos(phi);
    H.y = sinTheta * sin(phi);
    H.z = cosTheta;
    return H;
}
