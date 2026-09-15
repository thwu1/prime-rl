/*
 * PBR BRDF Evaluation Library — Complete Correct Implementation
 *
 */

#include "brdf.h"
#include <math.h>
#include <string.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

static inline float maxf(float a, float b) { return a > b ? a : b; }
static inline float minf(float a, float b) { return a < b ? a : b; }
static inline float clampf(float x, float lo, float hi) {
    return minf(maxf(x, lo), hi);
}

/* ---------- Quasi-random sampling ---------- */

static float radical_inverse_vdc(uint32_t bits) {
    bits = (bits << 16u) | (bits >> 16u);
    bits = ((bits & 0x55555555u) << 1u) | ((bits & 0xAAAAAAAAu) >> 1u);
    bits = ((bits & 0x33333333u) << 2u) | ((bits & 0xCCCCCCCCu) >> 2u);
    bits = ((bits & 0x0F0F0F0Fu) << 4u) | ((bits & 0xF0F0F0F0u) >> 4u);
    bits = ((bits & 0x00FF00FFu) << 8u) | ((bits & 0xFF00FF00u) >> 8u);
    return (float)bits * 2.3283064365386963e-10f;
}

static void hammersley(int i, float inv_n, float out[2]) {
    out[0] = (float)i * inv_n;
    out[1] = radical_inverse_vdc((uint32_t)i);
}

static void importance_sample_ggx(const float u[2], float alpha, float H[3]) {
    float phi = 2.0f * (float)M_PI * u[0];
    float ct2 = (1.0f - u[1]) / (1.0f + (alpha + 1.0f) * ((alpha - 1.0f) * u[1]));
    float ct  = sqrtf(maxf(ct2, 0.0f));
    float st  = sqrtf(maxf(1.0f - ct2, 0.0f));
    H[0] = st * cosf(phi);
    H[1] = st * sinf(phi);
    H[2] = ct;
}

/* ---------- BRDF components ---------- */

static float D_GGX(float NoH, float a) {
    float a2 = a * a;
    float f  = (NoH * a2 - NoH) * NoH + 1.0f;
    return a2 / ((float)M_PI * f * f);
}

static float V_SmithGGXCorrelated(float NoV, float NoL, float a) {
    float a2   = a * a;
    float GGXL = NoV * sqrtf((-NoL * a2 + NoL) * NoL + a2);
    float GGXV = NoL * sqrtf((-NoV * a2 + NoV) * NoV + a2);
    float denom = GGXV + GGXL;
    if (denom < 1e-7f) return 0.0f;
    return 0.5f / denom;
}

static float V_Kelemen(float LoH) {
    return 0.25f / maxf(LoH * LoH, 1e-7f);
}

static float F_Schlick_scalar(float u, float f0, float f90) {
    float x  = 1.0f - u;
    float x2 = x * x;
#ifdef BRDF_FAST_FRESNEL
    float Fc = x2 * x;
#else
    float Fc = x2 * x2 * x;
#endif
    return f0 * (1.0f - Fc) + f90 * Fc;
}

static void F_Schlick_vec(float u, const float f0[3], float out[3]) {
    float x  = 1.0f - u;
    float x2 = x * x;
#ifdef BRDF_FAST_FRESNEL
    float Fc = x2 * x;
#else
    float Fc = x2 * x2 * x;
#endif
    for (int i = 0; i < 3; i++)
        out[i] = f0[i] + (1.0f - f0[i]) * Fc;
}

/* ---------- DFG (split-sum) integration ---------- */

DFGResult compute_dfg(float NoV, float perceptualRoughness, int numSamples) {
    float alpha = perceptualRoughness * perceptualRoughness;
    float Vdir[3] = { sqrtf(maxf(1.0f - NoV * NoV, 0.0f)), 0.0f, NoV };
    float inv_n = 1.0f / (float)numSamples;
    float rx = 0.0f, ry = 0.0f;

    for (int i = 0; i < numSamples; i++) {
        float u[2], H[3];
        hammersley(i, inv_n, u);
        importance_sample_ggx(u, alpha, H);

        float VoH = maxf(Vdir[0]*H[0] + Vdir[1]*H[1] + Vdir[2]*H[2], 0.0f);
        float L[3] = {
            2.0f * VoH * H[0] - Vdir[0],
            2.0f * VoH * H[1] - Vdir[1],
            2.0f * VoH * H[2] - Vdir[2]
        };

        VoH = clampf(VoH, 0.0f, 1.0f);
        float NoL = clampf(L[2], 0.0f, 1.0f);
        float NoH = clampf(H[2], 0.0f, 1.0f);

        if (NoL > 0.0f) {
            /* MC weight: integrand / p(L)
             * integrand = D * V * F * NoL
             * p(L) = D * NoH / (4 * VoH)
             * weight = V * NoL * 4 * VoH / NoH  (D cancels)
             * Factor out the 4 into the final normalization. */
            float v = V_SmithGGXCorrelated(NoV, NoL, alpha)
                    * NoL * (VoH / maxf(NoH, 1e-7f));
            float om  = 1.0f - VoH;
            float om2 = om * om;
            float Fc  = om2 * om2 * om;
            rx += v * (1.0f - Fc);
            ry += v * Fc;
        }
    }

    DFGResult result;
    result.dfg1 = rx * 4.0f / (float)numSamples;
    result.dfg2 = ry * 4.0f / (float)numSamples;
    return result;
}

/* ---------- Direction helpers ---------- */

static void compute_directions(float tv, float tl, float pl,
                                float Vdir[3], float Ldir[3]) {
    float theta_v = tv * (float)M_PI / 180.0f;
    float theta_l = tl * (float)M_PI / 180.0f;
    float phi_l   = pl * (float)M_PI / 180.0f;
    Vdir[0] = sinf(theta_v);
    Vdir[1] = 0.0f;
    Vdir[2] = cosf(theta_v);
    Ldir[0] = sinf(theta_l) * cosf(phi_l);
    Ldir[1] = sinf(theta_l) * sinf(phi_l);
    Ldir[2] = cosf(theta_l);
}

/* ---------- Standard BRDF evaluation ---------- */

BRDFResult evaluate_standard_brdf(float tv, float tl, float pl, Material mat) {
    float Vdir[3], Ldir[3];
    compute_directions(tv, tl, pl, Vdir, Ldir);

    float NoV = fabsf(Vdir[2]) + 1e-5f;
    float NoL = clampf(Ldir[2], 0.0f, 1.0f);

    BRDFResult res;
    memset(&res, 0, sizeof(res));
    if (NoL <= 0.0f) return res;

    float Hv[3] = { Vdir[0]+Ldir[0], Vdir[1]+Ldir[1], Vdir[2]+Ldir[2] };
    float hl = sqrtf(Hv[0]*Hv[0] + Hv[1]*Hv[1] + Hv[2]*Hv[2]);
    if (hl < 1e-7f) return res;
    Hv[0] /= hl;  Hv[1] /= hl;  Hv[2] /= hl;

    float NoH = clampf(Hv[2], 0.0f, 1.0f);
    float LoH = clampf(Ldir[0]*Hv[0] + Ldir[1]*Hv[1] + Ldir[2]*Hv[2],
                        0.0f, 1.0f);

    float roughness = mat.roughness * mat.roughness;
    float f0[3], dc[3];
    for (int i = 0; i < 3; i++) {
        f0[i] = 0.16f * mat.reflectance * mat.reflectance * (1.0f - mat.metallic)
              + mat.baseColor[i] * mat.metallic;
        dc[i] = mat.baseColor[i] * (1.0f - mat.metallic);
    }

    float D = D_GGX(NoH, roughness);
    float V = V_SmithGGXCorrelated(NoV, NoL, roughness);
    float F[3];
    F_Schlick_vec(LoH, f0, F);

    for (int i = 0; i < 3; i++) {
        res.specular[i] = D * V * F[i];
        res.diffuse[i]  = dc[i] / (float)M_PI;
        res.total[i]    = (res.specular[i] + res.diffuse[i]) * NoL;
    }
    return res;
}

/* ---------- Clear coat BRDF evaluation ---------- */

BRDFResult evaluate_clearcoat_brdf(float tv, float tl, float pl, Material mat) {
    float Vdir[3], Ldir[3];
    compute_directions(tv, tl, pl, Vdir, Ldir);

    float NoV = fabsf(Vdir[2]) + 1e-5f;
    float NoL = clampf(Ldir[2], 0.0f, 1.0f);

    BRDFResult res;
    memset(&res, 0, sizeof(res));
    if (NoL <= 0.0f) return res;

    float Hv[3] = { Vdir[0]+Ldir[0], Vdir[1]+Ldir[1], Vdir[2]+Ldir[2] };
    float hl = sqrtf(Hv[0]*Hv[0] + Hv[1]*Hv[1] + Hv[2]*Hv[2]);
    if (hl < 1e-7f) return res;
    Hv[0] /= hl;  Hv[1] /= hl;  Hv[2] /= hl;

    float NoH = clampf(Hv[2], 0.0f, 1.0f);
    float LoH = clampf(Ldir[0]*Hv[0] + Ldir[1]*Hv[1] + Ldir[2]*Hv[2],
                        0.0f, 1.0f);

    float roughness = mat.roughness * mat.roughness;
    float ccR = mat.clearCoatRoughness * mat.clearCoatRoughness;

    float f0[3], dc[3];
    for (int i = 0; i < 3; i++) {
        f0[i] = 0.16f * mat.reflectance * mat.reflectance * (1.0f - mat.metallic)
              + mat.baseColor[i] * mat.metallic;
        dc[i] = mat.baseColor[i] * (1.0f - mat.metallic);
    }

    float D = D_GGX(NoH, roughness);
    float V = V_SmithGGXCorrelated(NoV, NoL, roughness);
    float F[3];
    F_Schlick_vec(LoH, f0, F);

    for (int i = 0; i < 3; i++) {
        res.specular[i] = D * V * F[i];
        res.diffuse[i]  = dc[i] / (float)M_PI;
    }

    float Dc = D_GGX(NoH, ccR);
    float Vc = V_Kelemen(LoH);
    float Fc = F_Schlick_scalar(LoH, 0.04f, 1.0f) * mat.clearCoat;
    res.clearcoat_specular = Dc * Vc * Fc;

    for (int i = 0; i < 3; i++) {
        res.total[i] = ((res.diffuse[i] + res.specular[i] * (1.0f - Fc))
                       * (1.0f - Fc) + res.clearcoat_specular) * NoL;
    }
    return res;
}

/* ---------- Energy compensation ---------- */

EnergyCompResult compute_energy_compensation(float NoV, float perceptualRoughness,
                                              const float f0[3], int numSamples) {
    DFGResult dfg = compute_dfg(NoV, perceptualRoughness, numSamples);
    float E = dfg.dfg1 + dfg.dfg2;
    if (E < 1e-7f) E = 1e-7f;

    EnergyCompResult res;
    res.E = E;
    for (int i = 0; i < 3; i++)
        res.compensation[i] = 1.0f + f0[i] * (1.0f / E - 1.0f);
    return res;
}
