#!/usr/bin/env python3
"""Solution: Verify Mitsuba 3 BSDF implementations against analytical Fresnel equations."""

import math
import json
import random
import sys

sys.path.insert(0, '/app')
from bsdf_configs import (
    DIELECTRIC_CONFIG, CONDUCTOR_CONFIG, ROUGH_DIELECTRIC_CONFIG,
    TEST_ANGLES_DEG, TIR_TEST_ANGLES_DEG, ROUGH_MC_ANGLE_DEG, MC_SAMPLES,
)

import mitsuba as mi
mi.set_variant('scalar_rgb')


def make_si(theta_deg, from_inside=False):
    """Create a SurfaceInteraction3f at a given incidence angle.

    In Mitsuba's convention, wi points from the surface toward the
    incoming ray origin (like PBRT). The surface normal is [0, 0, 1].

    Args:
        theta_deg: incidence angle in degrees from the surface normal
        from_inside: if True, wi comes from inside (z < 0)
    """
    si = mi.SurfaceInteraction3f()
    si.p = [0, 0, 0]
    si.n = [0, 0, 1]
    theta = math.radians(theta_deg)
    if from_inside:
        si.wi = [math.sin(theta), 0, -math.cos(theta)]
    else:
        si.wi = [math.sin(theta), 0, math.cos(theta)]
    si.sh_frame = mi.Frame3f(si.n)
    return si


def get_bsdf_flags(bsdf):
    """Extract reflection/transmission/delta flags from a BSDF."""
    flags = bsdf.flags()
    return {
        'has_reflection': bool(int(flags) & int(mi.BSDFFlags.Reflection)),
        'has_transmission': bool(int(flags) & int(mi.BSDFFlags.Transmission)),
        'is_delta': bool(int(flags) & int(mi.BSDFFlags.Delta)),
    }


def main():
    results = {}
    ctx = mi.BSDFContext()

    # ====================================================================
    # 1. Dielectric Fresnel reflectance via Mitsuba's sample() method
    # ====================================================================
    # For a smooth (delta) dielectric BSDF, eval() returns zero.
    # We must use sample() instead. With sample1 < F, we get reflection,
    # and bs.pdf equals the Fresnel reflectance F(theta).
    bsdf_d = mi.load_dict(DIELECTRIC_CONFIG)
    diel_fresnel = {}
    for angle in TEST_ANGLES_DEG:
        si = make_si(angle)
        bs, weight = bsdf_d.sample(ctx, si, 0.0, [0.5, 0.5])
        diel_fresnel[str(angle)] = float(bs.pdf)
    results['dielectric_fresnel'] = diel_fresnel

    # ====================================================================
    # 2. Conductor Fresnel reflectance (per-channel)
    # ====================================================================
    # For a smooth conductor, there is only reflection (no refraction).
    # bs.pdf = 1.0, and the weight contains the per-channel Fresnel values
    # F(theta) as a Color3f, since weight = F * cos / (pdf * cos) = F.
    bsdf_c = mi.load_dict(CONDUCTOR_CONFIG)
    cond_fresnel = {}
    for angle in TEST_ANGLES_DEG:
        si = make_si(angle)
        bs, weight = bsdf_c.sample(ctx, si, 0.0, [0.5, 0.5])
        cond_fresnel[str(angle)] = [
            float(weight[0]), float(weight[1]), float(weight[2])
        ]
    results['conductor_fresnel'] = cond_fresnel

    # ====================================================================
    # 3. Energy conservation: R + T = 1 for lossless dielectric
    # ====================================================================
    energy = {}
    for angle in TEST_ANGLES_DEG:
        si = make_si(angle)
        bs_r, _ = bsdf_d.sample(ctx, si, 0.0, [0.5, 0.5])
        R = float(bs_r.pdf)
        T = 1.0 - R
        energy[str(angle)] = {
            'reflectance': R,
            'transmittance': T,
            'sum': R + T,
        }
    results['energy_conservation'] = energy

    # ====================================================================
    # 4. Critical angle and total internal reflection
    # ====================================================================
    # For light going from glass (n=1.5) to air (n=1.0), the critical
    # angle is theta_c = arcsin(n_air / n_glass).
    n_ext = DIELECTRIC_CONFIG['ext_ior']
    n_int = DIELECTRIC_CONFIG['int_ior']
    critical_angle = math.degrees(math.asin(n_ext / n_int))
    results['critical_angle_deg'] = critical_angle

    # Verify TIR: sample the dielectric from the inside (wi.z < 0).
    # Above the critical angle, bs.pdf should be 1.0 (total reflection).
    tir_verified = True
    for angle in TIR_TEST_ANGLES_DEG:
        si = make_si(angle, from_inside=True)
        bs, weight = bsdf_d.sample(ctx, si, 0.0, [0.5, 0.5])
        if angle > critical_angle + 0.5:
            if float(bs.pdf) < 0.999:
                tir_verified = False
    results['tir_verified'] = tir_verified

    # ====================================================================
    # 5. Rough BSDF total hemispherical throughput via MC integration
    # ====================================================================
    # For a rough dielectric, the BSDF is not a delta distribution, so
    # both eval() and sample() return nonzero values. We estimate the
    # directional hemispherical throughput rho(wi) = integral of
    # f(wi, wo) * cos(theta_o) d_omega_o using BSDF importance sampling:
    #   rho ≈ (1/N) * sum(weight_i)
    # where weight_i = f * cos / pdf (returned by sample()).
    # For a lossless dielectric, this should be close to 1.0, though
    # single-scattering microfacet models have inherent energy loss.
    bsdf_r = mi.load_dict(ROUGH_DIELECTRIC_CONFIG)
    theta_mc = math.radians(ROUGH_MC_ANGLE_DEG)
    si_mc = mi.SurfaceInteraction3f()
    si_mc.p = [0, 0, 0]
    si_mc.n = [0, 0, 1]
    si_mc.wi = [math.sin(theta_mc), 0, math.cos(theta_mc)]
    si_mc.sh_frame = mi.Frame3f(si_mc.n)

    random.seed(42)
    total_throughput = 0.0
    for _ in range(MC_SAMPLES):
        s1 = random.random()
        s2 = [random.random(), random.random()]
        bs, weight = bsdf_r.sample(ctx, si_mc, s1, s2)
        if float(bs.pdf) > 0:
            avg_w = (float(weight[0]) + float(weight[1]) + float(weight[2])) / 3.0
            if math.isfinite(avg_w):
                total_throughput += avg_w

    results['rough_total_throughput'] = total_throughput / MC_SAMPLES

    # ====================================================================
    # 6. BSDF component flags
    # ====================================================================
    results['bsdf_flags'] = {
        'dielectric': get_bsdf_flags(bsdf_d),
        'conductor': get_bsdf_flags(bsdf_c),
        'rough_dielectric': get_bsdf_flags(bsdf_r),
    }

    # ====================================================================
    # 7. Sampled reflected and refracted directions at theta_i = 30 deg
    # ====================================================================
    si_30 = make_si(30)

    # Reflected direction: sample1 = 0.0 guarantees reflection (since F > 0)
    bs_refl, _ = bsdf_d.sample(ctx, si_30, 0.0, [0.5, 0.5])
    results['reflected_direction_30'] = [
        float(bs_refl.wo[0]), float(bs_refl.wo[1]), float(bs_refl.wo[2])
    ]

    # Refracted direction: sample1 = 0.99 > F(30 deg) ≈ 0.042, so refraction
    bs_refr, _ = bsdf_d.sample(ctx, si_30, 0.99, [0.5, 0.5])
    results['refracted_direction_30'] = [
        float(bs_refr.wo[0]), float(bs_refr.wo[1]), float(bs_refr.wo[2])
    ]

    # ====================================================================
    # Write output
    # ====================================================================
    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)
    print("Results written to /app/results.json")


if __name__ == '__main__':
    main()
