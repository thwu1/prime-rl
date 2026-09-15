#!/usr/bin/env python3
"""Correct microfacet BRDF renderer — all bugs fixed."""

import math
import json
import random


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
    sin2 = 1.0 - cos2  # FIX 1: was sin2 = cos2
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


def beckmann_ndf(cos_h, alpha):
    if cos_h <= 1e-10:
        return 0.0
    cos2 = cos_h ** 2
    cos4 = cos2 ** 2  # FIX 2: added cos4
    tan2 = (1.0 - cos2) / cos2
    return math.exp(-tan2 / (alpha ** 2)) / (math.pi * alpha ** 2 * cos4)


def smith_g1(cos_v, alpha):
    if cos_v >= 1.0:
        return 1.0
    if cos_v <= 0.0:
        return 0.0
    sin_v = math.sqrt(1.0 - cos_v ** 2)
    tan_v = sin_v / cos_v
    a = 1.0 / (alpha * tan_v)  # FIX 3: was a = alpha * tan_v
    if a >= 1.6:
        return 1.0
    a2 = a * a
    return (3.535 * a + 2.181 * a2) / (1.0 + 2.276 * a + 2.577 * a2)


def dot3(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def normalize(v):
    m = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    if m < 1e-12:
        return (0.0, 0.0, 1.0)
    return (v[0] / m, v[1] / m, v[2] / m)


def reflect(wi, n):
    d = dot3(wi, n)
    return (2 * d * n[0] - wi[0], 2 * d * n[1] - wi[1], 2 * d * n[2] - wi[2])


def eval_brdf_cosine(wi, wo, alpha, eta_list, k_list):
    h = normalize((wi[0] + wo[0], wi[1] + wo[1], wi[2] + wo[2]))
    cos_h = h[2]
    wi_dot_h = dot3(wi, h)
    cos_i = wi[2]
    cos_o = wo[2]
    if cos_i <= 0 or cos_o <= 0:
        return [0.0, 0.0, 0.0]
    D = beckmann_ndf(cos_h, alpha)
    G = smith_g1(cos_i, alpha) * smith_g1(cos_o, alpha)
    result = []
    for ch in range(3):
        F = fresnel_conductor(abs(wi_dot_h), eta_list[ch], k_list[ch])
        val = F * D * G / (4.0 * cos_i)  # FIX 4: was / (4.0 * cos_i * cos_o)
        result.append(val)
    return result


def sample_beckmann(alpha, u1, u2):
    log_s = -math.log(max(1e-10, 1.0 - u1))
    tan2 = alpha ** 2 * log_s  # FIX 5: was tan2 = log_s
    cos_h = 1.0 / math.sqrt(1.0 + tan2)
    sin_h = math.sqrt(max(0.0, 1.0 - cos_h ** 2))
    phi = 2.0 * math.pi * u2
    return (sin_h * math.cos(phi), sin_h * math.sin(phi), cos_h)


def mc_reflectance(wi, alpha, eta_list, k_list, n_samples, seed):
    random.seed(seed)
    total = [0.0, 0.0, 0.0]
    for _ in range(n_samples):
        u1 = random.random()
        u2 = random.random()
        m = sample_beckmann(alpha, u1, u2)
        if m[2] <= 0:
            continue
        wi_m = dot3(wi, m)
        if wi_m <= 0:
            continue
        wo = reflect(wi, m)
        if wo[2] <= 0:
            continue
        G = smith_g1(wi[2], alpha) * smith_g1(wo[2], alpha)
        base = G * wi_m / (wi[2] * m[2])
        for ch in range(3):
            F = fresnel_conductor(wi_m, eta_list[ch], k_list[ch])
            w = F * base
            if math.isfinite(w):
                total[ch] += w
    return [t / n_samples for t in total]


def main():
    with open('/app/scene.json') as f:
        scene = json.load(f)
    materials = scene['materials']
    output = {}
    for config in scene['test_configs']:
        name = config['name']
        mat = materials[config['material']]
        if config['type'] == 'fresnel_sweep':
            vals = {}
            for angle in config['angles']:
                cos_i = math.cos(math.radians(angle))
                if mat['kind'] == 'dielectric':
                    vals[str(angle)] = fresnel_dielectric(
                        cos_i, mat['ext_ior'], mat['int_ior'])
                else:
                    vals[str(angle)] = [
                        fresnel_conductor(cos_i, mat['eta'][ch], mat['k'][ch])
                        for ch in range(3)]
            output[name] = vals
        elif config['type'] == 'ndf_eval':
            vals = {}
            for angle in config['angles']:
                cos_h = math.cos(math.radians(angle))
                vals[str(angle)] = beckmann_ndf(cos_h, config['alpha'])
            output[name] = vals
        elif config['type'] == 'g1_eval':
            vals = {}
            for angle in config['angles']:
                cos_v = math.cos(math.radians(angle))
                vals[str(angle)] = smith_g1(cos_v, config['alpha'])
            output[name] = vals
        elif config['type'] == 'brdf_eval':
            vals = {}
            for pair in config['pairs']:
                ti = math.radians(pair['theta_i'])
                to = math.radians(pair['theta_o'])
                po = math.radians(pair['phi_o'])
                wi = (math.sin(ti), 0.0, math.cos(ti))
                wo = (math.sin(to) * math.cos(po),
                      math.sin(to) * math.sin(po),
                      math.cos(to))
                vals[pair['label']] = eval_brdf_cosine(
                    wi, wo, config['alpha'], mat['eta'], mat['k'])
            output[name] = vals
        elif config['type'] == 'mc_reflectance':
            theta = math.radians(config['theta_i'])
            wi = (math.sin(theta), 0.0, math.cos(theta))
            output[name] = mc_reflectance(
                wi, config['alpha'], mat['eta'], mat['k'],
                config['n_samples'], config['seed'])
    with open('/app/output.json', 'w') as f:
        json.dump(output, f, indent=2)
    print("Output written to /app/output.json")


if __name__ == '__main__':
    main()
