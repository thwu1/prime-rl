#!/usr/bin/env python3
"""Reference implementation: Beckmann microfacet BSDF model."""

import math
import json
import random

with open('/app/params.json') as f:
    P = json.load(f)

N1 = P['dielectric']['ext_ior']
N2 = P['dielectric']['int_ior']
ETA_C = P['conductor']['eta']
K_C = P['conductor']['k']
ALPHA = P['roughness']['alpha']
TEST_ANGLES = P['test_angles_deg']
NDF_ANGLES = P['ndf_eval_angles_deg']
G1_ANGLES = P['g1_eval_angles_deg']
BSDF_PAIRS = P['bsdf_eval_pairs']
MC_ANGLE = P['mc_incident_angle_deg']
MC_N = P['mc_samples']
MC_SEED = P['mc_seed']


def fresnel_dielectric(cos_i, n1, n2):
    sin2_t = (n1 / n2) ** 2 * (1.0 - cos_i ** 2)
    if sin2_t >= 1.0:
        return 1.0
    cos_t = math.sqrt(1.0 - sin2_t)
    rs = (n1 * cos_i - n2 * cos_t) / (n1 * cos_i + n2 * cos_t)
    rp = (n2 * cos_i - n1 * cos_t) / (n2 * cos_i + n1 * cos_t)
    return 0.5 * (rs * rs + rp * rp)


def fresnel_conductor(cos_i, eta, k):
    cos2 = cos_i ** 2
    sin2 = 1.0 - cos2
    eta2 = eta ** 2
    k2 = k ** 2
    t0 = eta2 - k2 - sin2
    a2b2 = math.sqrt(t0 ** 2 + 4.0 * eta2 * k2)
    t1 = a2b2 + cos2
    a = math.sqrt(max(0.0, 0.5 * (a2b2 + t0)))
    t2 = 2.0 * a * cos_i
    rs = (t1 - t2) / (t1 + t2)
    t3 = cos2 * a2b2 + sin2 * sin2
    t4 = t2 * sin2
    rp = rs * (t3 - t4) / (t3 + t4)
    return 0.5 * (rs + rp)


def beckmann_d(cos_h, alpha):
    if cos_h <= 1e-10:
        return 0.0
    cos2 = cos_h ** 2
    cos4 = cos2 ** 2
    tan2 = (1.0 - cos2) / cos2
    return math.exp(-tan2 / (alpha ** 2)) / (math.pi * alpha ** 2 * cos4)


def smith_g1(cos_v, alpha):
    if cos_v >= 1.0:
        return 1.0
    if cos_v <= 0.0:
        return 0.0
    sin_v = math.sqrt(1.0 - cos_v ** 2)
    tan_v = sin_v / cos_v
    a = 1.0 / (alpha * tan_v)
    if a >= 1.6:
        return 1.0
    a2 = a * a
    return (3.535 * a + 2.181 * a2) / (1.0 + 2.276 * a + 2.577 * a2)


def sample_beckmann(alpha, u1, u2):
    log_s = -math.log(max(1e-10, 1.0 - u1))
    tan2 = alpha ** 2 * log_s
    cos_h = 1.0 / math.sqrt(1.0 + tan2)
    sin_h = math.sqrt(max(0.0, 1.0 - cos_h ** 2))
    phi = 2.0 * math.pi * u2
    return (sin_h * math.cos(phi), sin_h * math.sin(phi), cos_h)


def reflect_vec(wi, n):
    d = wi[0] * n[0] + wi[1] * n[1] + wi[2] * n[2]
    return (2 * d * n[0] - wi[0], 2 * d * n[1] - wi[1], 2 * d * n[2] - wi[2])


def normalize(v):
    mag = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    if mag < 1e-12:
        return (0.0, 0.0, 1.0)
    return (v[0] / mag, v[1] / mag, v[2] / mag)


def dot3(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


results = {}

# 1. Dielectric Fresnel reflectance
diel_f = {}
for ang in TEST_ANGLES:
    diel_f[str(ang)] = fresnel_dielectric(math.cos(math.radians(ang)), N1, N2)
results['fresnel_dielectric'] = diel_f

# 2. Conductor Fresnel reflectance (per-channel RGB)
cond_f = {}
for ang in TEST_ANGLES:
    cos_i = math.cos(math.radians(ang))
    cond_f[str(ang)] = [fresnel_conductor(cos_i, ETA_C[ch], K_C[ch]) for ch in range(3)]
results['fresnel_conductor'] = cond_f

# 3. Energy conservation for smooth dielectric (R + T = 1)
energy = {}
for ang in TEST_ANGLES:
    R = diel_f[str(ang)]
    energy[str(ang)] = {'reflectance': R, 'transmittance': 1.0 - R, 'sum': 1.0}
results['energy_conservation'] = energy

# 4. Critical angle for glass-to-air TIR
results['critical_angle_deg'] = math.degrees(math.asin(N1 / N2))

# 5. Refracted angle at theta_i=30 via Snell's law
sin_t = (N1 / N2) * math.sin(math.radians(30))
results['refracted_angle_30'] = math.degrees(math.asin(sin_t))

# 6. Beckmann NDF evaluations
ndf_vals = {}
for ang in NDF_ANGLES:
    ndf_vals[str(ang)] = beckmann_d(math.cos(math.radians(ang)), ALPHA)
results['beckmann_ndf'] = ndf_vals

# 7. Smith G1 evaluations
g1_vals = {}
for ang in G1_ANGLES:
    g1_vals[str(ang)] = smith_g1(math.cos(math.radians(ang)), ALPHA)
results['smith_g1'] = g1_vals

# 8. BSDF eval: f_r(wi,wo)*cos(theta_o) for rough conductor at specific direction pairs
bsdf_vals = {}
for pair in BSDF_PAIRS:
    ti = math.radians(pair['theta_i'])
    to = math.radians(pair['theta_o'])
    po = math.radians(pair['phi_o'])
    wi = (math.sin(ti), 0.0, math.cos(ti))
    wo = (math.sin(to) * math.cos(po), math.sin(to) * math.sin(po), math.cos(to))
    h = normalize((wi[0] + wo[0], wi[1] + wo[1], wi[2] + wo[2]))
    cos_h = h[2]
    wi_h = dot3(wi, h)

    D = beckmann_d(cos_h, ALPHA)
    G = smith_g1(wi[2], ALPHA) * smith_g1(wo[2], ALPHA)

    channel_vals = []
    for ch in range(3):
        F = fresnel_conductor(abs(wi_h), ETA_C[ch], K_C[ch])
        # f_r * cos(theta_o) = F * D * G / (4 * cos_theta_i)
        val = F * D * G / (4.0 * wi[2])
        channel_vals.append(val)
    bsdf_vals[pair['label']] = channel_vals
results['bsdf_eval'] = bsdf_vals

# 9. MC directional-hemispherical reflectance for rough conductor
theta_mc = math.radians(MC_ANGLE)
wi_mc = (math.sin(theta_mc), 0.0, math.cos(theta_mc))

random.seed(MC_SEED)
total_rgb = [0.0, 0.0, 0.0]
for _ in range(MC_N):
    u1 = random.random()
    u2 = random.random()
    m = sample_beckmann(ALPHA, u1, u2)
    if m[2] <= 0:
        continue
    wi_m = dot3(wi_mc, m)
    if wi_m <= 0:
        continue
    wo = reflect_vec(wi_mc, m)
    if wo[2] <= 0:
        continue
    # MC weight derivation:
    # p(m) = D(m) * cos(theta_m)
    # p(wo) = p(m) / (4 * |wi . m|)  (Jacobian for half-vector to reflection)
    # weight = f_r * cos(theta_o) / p(wo)
    #        = [F * D * G / (4*cos_i*cos_o)] * cos_o / [D * cos(theta_m) / (4*|wi.m|)]
    #        = F * G * |wi.m| / (cos_i * m_z)
    G = smith_g1(wi_mc[2], ALPHA) * smith_g1(wo[2], ALPHA)
    base_weight = G * wi_m / (wi_mc[2] * m[2])
    for ch in range(3):
        F = fresnel_conductor(wi_m, ETA_C[ch], K_C[ch])
        w = F * base_weight
        if math.isfinite(w):
            total_rgb[ch] += w

results['mc_reflectance_conductor'] = [t / MC_N for t in total_rgb]

# Write output
with open('/app/results.json', 'w') as f:
    json.dump(results, f, indent=2)
print("Results written to /app/results.json")
