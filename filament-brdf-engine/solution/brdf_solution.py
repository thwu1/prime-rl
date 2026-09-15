#!/usr/bin/env python3
"""
Filament PBR BRDF Evaluation Engine - Reference Implementation


Standalone Python reference that computes all evaluation results without
the C library. Used as backup verification.
"""

import math
import json

PI = math.pi


def radical_inverse_vdc(bits):
    bits = ((bits << 16) | (bits >> 16)) & 0xFFFFFFFF
    bits = (((bits & 0x55555555) << 1) | ((bits & 0xAAAAAAAA) >> 1)) & 0xFFFFFFFF
    bits = (((bits & 0x33333333) << 2) | ((bits & 0xCCCCCCCC) >> 2)) & 0xFFFFFFFF
    bits = (((bits & 0x0F0F0F0F) << 4) | ((bits & 0xF0F0F0F0) >> 4)) & 0xFFFFFFFF
    bits = (((bits & 0x00FF00FF) << 8) | ((bits & 0xFF00FF00) >> 8)) & 0xFFFFFFFF
    return bits * 2.3283064365386963e-10


def hammersley(i, inv_num_samples):
    return (i * inv_num_samples, radical_inverse_vdc(i))


def D_GGX(NoH, alpha):
    a2 = alpha * alpha
    f = (NoH * a2 - NoH) * NoH + 1.0
    return a2 / (PI * f * f)


def V_SmithGGXCorrelated(NoV, NoL, alpha):
    a2 = alpha * alpha
    GGXV = NoL * math.sqrt((NoV - NoV * a2) * NoV + a2)
    GGXL = NoV * math.sqrt((NoL - NoL * a2) * NoL + a2)
    denom = GGXV + GGXL
    if denom < 1e-7:
        return 0.0
    return 0.5 / denom


def V_Kelemen(LoH):
    return 0.25 / max(LoH * LoH, 1e-7)


def F_Schlick_vec(u, f0):
    f = (1.0 - u) ** 5
    return [f0i + (1.0 - f0i) * f for f0i in f0]


def F_Schlick_scalar(u, f0, f90=1.0):
    Fc = (1.0 - u) ** 5
    return f0 * (1.0 - Fc) + f90 * Fc


def pow5(x):
    x2 = x * x
    return x2 * x2 * x


def hemisphere_importance_sample_dggx(u, alpha):
    phi = 2.0 * PI * u[0]
    cos_theta2 = (1.0 - u[1]) / (1.0 + (alpha + 1.0) * ((alpha - 1.0) * u[1]))
    cos_theta = math.sqrt(max(cos_theta2, 0.0))
    sin_theta = math.sqrt(max(1.0 - cos_theta2, 0.0))
    return (sin_theta * math.cos(phi), sin_theta * math.sin(phi), cos_theta)


def compute_dfv(NoV, linear_roughness, num_samples):
    V = (math.sqrt(max(1.0 - NoV * NoV, 0.0)), 0.0, NoV)
    inv_num_samples = 1.0 / num_samples
    rx = 0.0
    ry = 0.0
    for i in range(num_samples):
        u = hammersley(i, inv_num_samples)
        H = hemisphere_importance_sample_dggx(u, linear_roughness)
        VoH = max(V[0]*H[0] + V[1]*H[1] + V[2]*H[2], 0.0)
        L = (2.0 * VoH * H[0] - V[0],
             2.0 * VoH * H[1] - V[1],
             2.0 * VoH * H[2] - V[2])
        VoH = max(min(VoH, 1.0), 0.0)
        NoL = max(min(L[2], 1.0), 0.0)
        NoH = max(min(H[2], 1.0), 0.0)
        if NoL > 0.0:
            v = V_SmithGGXCorrelated(NoV, NoL, linear_roughness) * NoL * (VoH / max(NoH, 1e-7))
            Fc = pow5(1.0 - VoH)
            rx += v * (1.0 - Fc)
            ry += v * Fc
    return (rx * 4.0 / num_samples, ry * 4.0 / num_samples)


def evaluate_standard_brdf(theta_v_deg, theta_l_deg, phi_l_deg, material):
    theta_v = math.radians(theta_v_deg)
    theta_l = math.radians(theta_l_deg)
    phi_l = math.radians(phi_l_deg)
    V = (math.sin(theta_v), 0.0, math.cos(theta_v))
    L = (math.sin(theta_l) * math.cos(phi_l),
         math.sin(theta_l) * math.sin(phi_l),
         math.cos(theta_l))
    NoV = abs(V[2]) + 1e-5
    NoL = max(min(L[2], 1.0), 0.0)
    if NoL <= 0.0:
        return {"specular": [0, 0, 0], "diffuse": [0, 0, 0], "total": [0, 0, 0]}
    Hx, Hy, Hz = V[0]+L[0], V[1]+L[1], V[2]+L[2]
    H_len = math.sqrt(Hx*Hx + Hy*Hy + Hz*Hz)
    if H_len < 1e-7:
        return {"specular": [0, 0, 0], "diffuse": [0, 0, 0], "total": [0, 0, 0]}
    H = (Hx/H_len, Hy/H_len, Hz/H_len)
    NoH = max(min(H[2], 1.0), 0.0)
    LoH = max(min(L[0]*H[0] + L[1]*H[1] + L[2]*H[2], 1.0), 0.0)
    baseColor = material["baseColor"]
    metallic = material["metallic"]
    perceptualRoughness = material["roughness"]
    reflectance = material["reflectance"]
    roughness = perceptualRoughness * perceptualRoughness
    f0 = [0.16 * reflectance * reflectance * (1.0 - metallic) + baseColor[i] * metallic
          for i in range(3)]
    diffuseColor = [baseColor[i] * (1.0 - metallic) for i in range(3)]
    D = D_GGX(NoH, roughness)
    vis = V_SmithGGXCorrelated(NoV, NoL, roughness)
    F = F_Schlick_vec(LoH, f0)
    specular = [D * vis * F[i] for i in range(3)]
    diffuse = [diffuseColor[i] / PI for i in range(3)]
    total = [(specular[i] + diffuse[i]) * NoL for i in range(3)]
    return {"specular": specular, "diffuse": diffuse, "total": total}


def evaluate_clearcoat_brdf(theta_v_deg, theta_l_deg, phi_l_deg, material):
    theta_v = math.radians(theta_v_deg)
    theta_l = math.radians(theta_l_deg)
    phi_l = math.radians(phi_l_deg)
    V = (math.sin(theta_v), 0.0, math.cos(theta_v))
    L = (math.sin(theta_l) * math.cos(phi_l),
         math.sin(theta_l) * math.sin(phi_l),
         math.cos(theta_l))
    NoV = abs(V[2]) + 1e-5
    NoL = max(min(L[2], 1.0), 0.0)
    if NoL <= 0.0:
        return {"specular": [0,0,0], "diffuse": [0,0,0], "clearcoat_specular": 0.0, "total": [0,0,0]}
    Hx, Hy, Hz = V[0]+L[0], V[1]+L[1], V[2]+L[2]
    H_len = math.sqrt(Hx*Hx + Hy*Hy + Hz*Hz)
    if H_len < 1e-7:
        return {"specular": [0,0,0], "diffuse": [0,0,0], "clearcoat_specular": 0.0, "total": [0,0,0]}
    H = (Hx/H_len, Hy/H_len, Hz/H_len)
    NoH = max(min(H[2], 1.0), 0.0)
    LoH = max(min(L[0]*H[0] + L[1]*H[1] + L[2]*H[2], 1.0), 0.0)
    baseColor = material["baseColor"]
    metallic = material["metallic"]
    perceptualRoughness = material["roughness"]
    reflectance = material["reflectance"]
    clearCoat = material["clearCoat"]
    clearCoatPerceptualRoughness = material["clearCoatRoughness"]
    roughness = perceptualRoughness * perceptualRoughness
    clearCoatRoughness = clearCoatPerceptualRoughness * clearCoatPerceptualRoughness
    f0 = [0.16 * reflectance * reflectance * (1.0 - metallic) + baseColor[i] * metallic
          for i in range(3)]
    diffuseColor = [baseColor[i] * (1.0 - metallic) for i in range(3)]
    D = D_GGX(NoH, roughness)
    vis = V_SmithGGXCorrelated(NoV, NoL, roughness)
    F = F_Schlick_vec(LoH, f0)
    specular = [D * vis * F[i] for i in range(3)]
    diffuse = [diffuseColor[i] / PI for i in range(3)]
    Dc = D_GGX(NoH, clearCoatRoughness)
    Vc = V_Kelemen(LoH)
    Fc = F_Schlick_scalar(LoH, 0.04) * clearCoat
    Frc = Dc * Vc * Fc
    total = [((diffuse[i] + specular[i] * (1.0 - Fc)) * (1.0 - Fc) + Frc) * NoL
             for i in range(3)]
    return {"specular": specular, "diffuse": diffuse, "clearcoat_specular": Frc, "total": total}


def compute_energy_compensation(NoV, perceptual_roughness, f0, num_samples=1024):
    linear_roughness = perceptual_roughness * perceptual_roughness
    dfv_x, dfv_y = compute_dfv(NoV, linear_roughness, num_samples)
    E = dfv_x + dfv_y
    E = max(E, 1e-7)
    compensation = [1.0 + f0[i] * (1.0 / E - 1.0) for i in range(3)]
    return {"dfg1": dfv_x, "dfg2": dfv_y, "E": E, "compensation": compensation}


def main():
    with open('/app/config.json', 'r') as f:
        config = json.load(f)

    results = {}

    for eval_cfg in config["dfg_evaluations"]:
        linear_roughness = eval_cfg["perceptual_roughness"] ** 2
        dfv_x, dfv_y = compute_dfv(eval_cfg["NoV"], linear_roughness, eval_cfg["num_samples"])
        results[eval_cfg["id"]] = {"dfg1": dfv_x, "dfg2": dfv_y}

    for eval_cfg in config["brdf_evaluations"]:
        result = evaluate_standard_brdf(
            eval_cfg["theta_v"], eval_cfg["theta_l"],
            eval_cfg["phi_l"], eval_cfg["material"])
        results[eval_cfg["id"]] = result

    for eval_cfg in config["clear_coat_evaluations"]:
        result = evaluate_clearcoat_brdf(
            eval_cfg["theta_v"], eval_cfg["theta_l"],
            eval_cfg["phi_l"], eval_cfg["material"])
        results[eval_cfg["id"]] = result

    for eval_cfg in config["energy_compensation"]:
        result = compute_energy_compensation(
            eval_cfg["NoV"], eval_cfg["perceptual_roughness"], eval_cfg["f0"])
        results[eval_cfg["id"]] = result

    with open('/app/output.json', 'w') as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
