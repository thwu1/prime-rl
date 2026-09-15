#ifndef BRDF_H
#define BRDF_H


#include <stdint.h>

typedef struct {
    float baseColor[3];
    float roughness;
    float metallic;
    float reflectance;
    float clearCoat;
    float clearCoatRoughness;
} Material;

typedef struct {
    float specular[3];
    float diffuse[3];
    float total[3];
    float clearcoat_specular;
} BRDFResult;

typedef struct {
    float dfg1;
    float dfg2;
} DFGResult;

typedef struct {
    float E;
    float compensation[3];
} EnergyCompResult;

DFGResult compute_dfg(float NoV, float perceptualRoughness, int numSamples);
BRDFResult evaluate_standard_brdf(float theta_v_deg, float theta_l_deg,
                                   float phi_l_deg, Material mat);
BRDFResult evaluate_clearcoat_brdf(float theta_v_deg, float theta_l_deg,
                                    float phi_l_deg, Material mat);
EnergyCompResult compute_energy_compensation(float NoV, float perceptualRoughness,
                                              const float f0[3], int numSamples);

#endif /* BRDF_H */
