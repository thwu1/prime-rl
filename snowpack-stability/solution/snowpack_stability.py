#!/usr/bin/env python3
"""SNOWPACK profile stability analyzer.

Replicates the SNOWPACK (WSL/SLF Davos) stability computation pipeline
from the C++ reference implementation.
"""


import sys
import json
import math
import argparse

# Physical constants (from Constants.h)
G = 9.80665
DENSITY_ICE = 917.0

# Reference slope angle (from Stability.cc)
PSI_REF_DEG = 38.0
PSI_REF = math.radians(PSI_REF_DEG)
COS_PSI_REF = math.cos(PSI_REF)
SIN_PSI_REF = math.sin(PSI_REF)

# Skier stress parameters (Foehn 1987, from StabilityAlgorithms.cc)
ALPHA_MAX_DEG = 54.3
ALPHA_MAX = math.radians(ALPHA_MAX_DEG)
SKIER_WEIGHT = 85.0
SKI_LENGTH = 1.7
SKIER_LOAD = SKIER_WEIGHT * G / SKI_LENGTH

# Stability bounds (from Stability.cc)
MIN_STABILITY = 0.05
MAX_STABILITY = 6.0

# Search constraints (from Stability.cc)
MINIMUM_SLAB = 0.1      # m
GROUND_ROUGH = 0.2       # m
SKIER_DEPTH = 1.0        # m
MIN_DEPTH_SSI = 0.1      # m

# SSI parameters (from Stability.cc)
NMAX_LEMON = 2
THRESH_DHARD = 1.5
THRESH_DGSZ = 0.5

# Shear strength constants
MFCR_STRENGTH = 4.0      # kPa
UNDEFINED = -999.0


def parse_pro_file(filepath):
    """Parse a SNOWPACK .pro file."""
    with open(filepath, 'r') as f:
        lines = f.readlines()

    station_params = {}
    timesteps = []
    current_ts = None
    section = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith('#'):
            if section == 'header':
                continue
            if not line:
                continue
            continue

        if line == '[STATION_PARAMETERS]':
            section = 'station'
            continue
        elif line == '[HEADER]':
            section = 'header'
            continue
        elif line == '[DATA]':
            section = 'data'
            continue

        if section == 'station':
            if '=' in line:
                key, val = line.split('=', 1)
                station_params[key.strip()] = val.strip()

        elif section == 'data':
            parts = line.split(',')
            code = parts[0].strip()

            if code == '0500':
                ts_str = ','.join(parts[1:]).strip()
                current_ts = {'timestamp': ts_str, 'data': {}}
                timesteps.append(current_ts)
            elif current_ts is not None and len(parts) >= 2:
                try:
                    count = int(parts[1])
                except ValueError:
                    continue
                values = []
                for v in parts[2:2 + count]:
                    try:
                        values.append(float(v.strip()))
                    except ValueError:
                        values.append(UNDEFINED)
                current_ts['data'][code] = values

    return station_params, timesteps


def clamp(value):
    return max(MIN_STABILITY, min(MAX_STABILITY, value))


def clamp_ccl(value):
    return max(0.0, min(3.0, value))


def grain_f1(code):
    return int(code) // 100


def compute_shear_strength(f1, density, mk, sig_n=0.0):
    """Grain-type-dependent shear strength (kPa) - DEFAULT model."""
    rho_ratio = density / DENSITY_ICE

    if mk % 100 >= 20:
        return MFCR_STRENGTH

    if f1 == 0:   # PPgp (graupel)
        return 0.65 * 82.0 * rho_ratio ** 2.8
    elif f1 == 1:  # PP
        return 2.85 * rho_ratio ** 1.13
    elif f1 == 2:  # DF
        return 8.75 * rho_ratio ** 1.54
    elif f1 == 3:  # RG
        return 7.39 * rho_ratio ** 1.20
    elif f1 == 7:  # MF
        return 21.0 * rho_ratio ** 1.24
    elif f1 == 6:  # SH
        sig_c2 = 18.5 * rho_ratio ** 2.11
        if sig_n > 0:
            sig_c3 = 1.36 * (sig_n / COS_PSI_REF) ** 0.55
            sig_c2 = max(sig_c2, sig_c3)
        return sig_c2
    else:          # FC(4), DH(5), FCxr(9), default
        sig_c2 = 18.5 * rho_ratio ** 2.11
        if sig_n > 0:
            sig_c3 = 1.36 * (sig_n / COS_PSI_REF) ** 0.55
            sig_c2 = max(sig_c2, sig_c3)
        return sig_c2


def compute_phi(f1, density, mk):
    """Normal load correction factor."""
    if mk % 100 >= 20:
        return 0.0
    if f1 in (1, 2, 3):  # PP, DF, RG - non-persistent
        return 19.5 * (density / DENSITY_ICE) ** 2
    return 0.0


def reduced_stresses(stress_kpa, cos_sl):
    """Reduce stresses to 38-degree reference slope."""
    sig_n = -stress_kpa * (COS_PSI_REF / cos_sl) ** 2
    sig_s = sig_n * SIN_PSI_REF / COS_PSI_REF
    return sig_n, sig_s


def penetration_depth(heights_cm, densities, cos_sl):
    """Skier penetration depth (Jamieson & Johnston 1998)."""
    n = len(heights_cm)
    if n == 0:
        return 0.0

    surface = heights_cm[-1]
    target_cm = 30.0
    total_wt = 0.0
    total_th = 0.0

    for i in range(n - 1, -1, -1):
        bottom = heights_cm[i - 1] if i > 0 else 0.0
        top = heights_cm[i]
        thickness = top - bottom

        depth_bottom = surface - bottom
        if depth_bottom > target_cm:
            contrib = top - (surface - target_cm)
            if contrib <= 0:
                break
            contrib = min(contrib, thickness)
        else:
            contrib = thickness

        total_wt += densities[i] * contrib
        total_th += contrib
        if total_th >= target_cm:
            break

    if total_th <= 0:
        return 0.0

    rho_pk = total_wt / total_th
    if rho_pk <= 0:
        return 0.0

    pk = 0.8 * 43.3 / rho_pk  # meters
    max_pk = (surface / 100.0) / cos_sl
    return min(pk, max_pk)


def skier_stress(depth_below_pk_m):
    """Additional shear stress from skier (kPa), Foehn formula."""
    if depth_below_pk_m <= 0:
        return 0.0
    num = (2.0 * SKIER_LOAD * math.cos(ALPHA_MAX) *
           math.sin(ALPHA_MAX) ** 2 *
           math.sin(ALPHA_MAX + PSI_REF))
    den = math.pi * depth_below_pk_m * COS_PSI_REF
    return num / den / 1000.0  # Pa -> kPa


def young_modulus_pow(rho_slab):
    """Young's modulus, Pow parameterization (for CCL)."""
    if rho_slab <= 0:
        return 0.0
    return 5.07e9 * (rho_slab / DENSITY_ICE) ** 5.13


def critical_cut_length(H_slab, rho_slab, cos_sl, wl_rho, wl_rg_mm, tau_p, stress_kpa):
    """Critical cut length (Gaume et al. 2017)."""
    if H_slab < MINIMUM_SLAB:
        return 3.0

    sin_sl = math.sqrt(max(0.0, 1.0 - cos_sl ** 2))
    D = H_slab
    sigma_n = -stress_kpa  # kPa; stress_kpa is negative (compressive), sigma_n positive

    if sigma_n <= 1e-9:
        return 3.0

    tau_g = sigma_n * sin_sl / cos_sl if cos_sl > 1e-9 else 0.0

    E = young_modulus_pow(rho_slab)
    E_prime = E / (1.0 - 0.04)  # Poisson ratio = 0.2

    gs_m = 2.0 * wl_rg_mm * 0.001  # grain diameter in meters
    if gs_m <= 1e-9 or wl_rho <= 0:
        return 3.0

    Fwl = 6.21e-7 * wl_rho ** (-2.11) * gs_m ** (-2.11) * 0.01  # m/Pa

    lam = math.sqrt(max(0.0, E_prime * D * Fwl))

    sqrt_arg = tau_g ** 2 + 2.0 * sigma_n * (tau_p - tau_g)
    if sqrt_arg < 0:
        return 0.0

    crit_len = lam * (-tau_g + math.sqrt(sqrt_arg)) / sigma_n

    if crit_len > 3.0 or H_slab < MINIMUM_SLAB:
        return 3.0

    return max(0.0, crit_len)


def analyze(ts_data, slope_deg):
    cos_sl = math.cos(math.radians(slope_deg))
    d = ts_data['data']

    heights = d['0501']
    densities = d['0502']
    markers = d.get('0504', [])
    grain_types_raw = d.get('0513', [])
    grain_sizes = d.get('0512', [])
    stresses = d.get('0517', [])
    hardnesses = d.get('0534', [])

    n = len(heights)
    grain_types = grain_types_raw[:n]
    snow_h_cm = heights[-1]
    snow_h_m = snow_h_cm / 100.0

    pk = penetration_depth(heights, densities, cos_sl)

    # First pass: compute per-layer properties
    layers = []
    for i in range(n):
        f1 = grain_f1(grain_types[i])
        mk = int(markers[i]) if i < len(markers) else 0
        rho = densities[i]
        stress = stresses[i] if i < len(stresses) else 0.0
        gs = grain_sizes[i] if i < len(grain_sizes) else 0.0
        hh = hardnesses[i] if i < len(hardnesses) else UNDEFINED

        sig_n, sig_s = reduced_stresses(stress, cos_sl)
        sig_c2 = compute_shear_strength(f1, rho, mk, sig_n)
        phi = compute_phi(f1, rho, mk)

        depth_m = (snow_h_cm - heights[i]) / 100.0 / cos_sl

        # Natural stability
        if sig_s > 0:
            sn = clamp((sig_c2 + phi * sig_n) / sig_s)
        else:
            sn = MAX_STABILITY

        # Skier stability
        sk = MAX_STABILITY
        in_skier_range = False
        enough_snow = (snow_h_m / cos_sl) > GROUND_ROUGH
        enough_depth = (snow_h_m / cos_sl - pk) > MIN_DEPTH_SSI

        if enough_snow and enough_depth:
            if pk <= depth_m <= pk + SKIER_DEPTH:
                in_skier_range = True
                d_sig = skier_stress(depth_m - pk)
                denom = sig_s + d_sig
                if denom > 0:
                    sk = clamp((sig_c2 + phi * sig_n) / denom)
                else:
                    sk = MAX_STABILITY

        layers.append({
            'height_cm': heights[i],
            'density_kg_m3': rho,
            'grain_type': int(grain_types[i]),
            'grain_size_mm': gs,
            'shear_strength_kPa': sig_c2,
            'Sk38': sk,
            'Sn38': sn,
            'hand_hardness': hh,
            'in_skier_range': in_skier_range,
            'depth_m': depth_m,
            'critical_cut_length_m': 3.0,  # default, updated below
        })

    # SSI: lemon counting at each interface
    for i in range(n):
        sk = layers[i]['Sk38']
        n_lemon = 0
        if i > 0:
            dhard = abs(layers[i]['hand_hardness'] - layers[i - 1]['hand_hardness'])
            if layers[i]['hand_hardness'] != UNDEFINED and layers[i - 1]['hand_hardness'] != UNDEFINED:
                if dhard > THRESH_DHARD:
                    n_lemon += 1
            rg_i = layers[i]['grain_size_mm'] / 2.0
            rg_prev = layers[i - 1]['grain_size_mm'] / 2.0
            dgsz = 2.0 * abs(rg_i - rg_prev)
            if dgsz > THRESH_DGSZ:
                n_lemon += 1
        n_lemon = min(n_lemon, NMAX_LEMON)
        layers[i]['SSI'] = clamp((NMAX_LEMON - n_lemon) + sk)
        layers[i]['n_lemon'] = n_lemon

    # CCL computation (top-to-bottom slab accumulation, matching C++ Stability::checkStability)
    slab_thick_m = 0.0
    slab_mass = 0.0
    for i in range(n - 1, -1, -1):
        bottom_h = heights[i - 1] if i > 0 else 0.0
        thickness_m = (heights[i] - bottom_h) / 100.0
        slab_thick_m += thickness_m
        slab_mass += densities[i] * thickness_m

        # CCL assigned to element i-1 (the layer below current)
        if i < n - 1 and i >= 2:
            rho_slab = slab_mass / slab_thick_m if slab_thick_m > 0 else 100.0
            wl_rho = densities[i - 1]
            wl_gs_mm = grain_sizes[i - 1] if (i - 1) < len(grain_sizes) else 0.5
            wl_rg_mm = wl_gs_mm / 2.0
            tau_p = layers[i]['shear_strength_kPa']
            stress_kpa = stresses[i] if i < len(stresses) else 0.0
            ccl = critical_cut_length(slab_thick_m, rho_slab, cos_sl,
                                      wl_rho, wl_rg_mm, tau_p, stress_kpa)
            layers[i - 1]['critical_cut_length_m'] = clamp_ccl(ccl)

    # Find profile minima (exclude ground_rough and minimum_slab)
    min_sn = MAX_STABILITY
    min_sn_h = 0.0
    min_sk = MAX_STABILITY
    min_sk_h = 0.0
    min_ssi = MAX_STABILITY
    min_ssi_h = 0.0
    weak_idx = -1

    for i, L in enumerate(layers):
        h_m = L['height_cm'] / 100.0
        dm = L['depth_m']
        if h_m < GROUND_ROUGH:
            continue
        if dm < MINIMUM_SLAB:
            continue

        if L['Sn38'] < min_sn:
            min_sn = L['Sn38']
            min_sn_h = L['height_cm']
        if L['Sk38'] < min_sk:
            min_sk = L['Sk38']
            min_sk_h = L['height_cm']
        if L['SSI'] < min_ssi or (abs(L['SSI'] - min_ssi) < 0.09 and L['n_lemon'] > layers[weak_idx]['n_lemon'] if weak_idx >= 0 else False):
            min_ssi = L['SSI']
            min_ssi_h = L['height_cm']
            weak_idx = i

    # Classification (Schweizer-Bellaire2, scheme 2)
    stab_class = -1
    if weak_idx >= 0 and min_ssi < MAX_STABILITY:
        wl = layers[weak_idx]
        nl = wl['n_lemon']
        sk_wl = wl['Sk38']
        if nl >= 2:
            stab_class = 1
        elif nl == 1:
            if sk_wl < 0.48:
                stab_class = 1
            elif sk_wl < 0.71:
                stab_class = 3
            else:
                stab_class = 5
        else:
            stab_class = 3

    result = {
        'timestamp': ts_data['timestamp'],
        'n_elements': n,
        'snow_height_cm': round(snow_h_cm, 2),
        'penetration_depth_m': round(pk, 4),
        'profile': {
            'stability_class': stab_class,
            'min_Sk38': round(min_sk, 4),
            'min_Sk38_height_cm': round(min_sk_h, 2),
            'min_Sn38': round(min_sn, 4),
            'min_Sn38_height_cm': round(min_sn_h, 2),
            'min_SSI': round(min_ssi, 4),
            'min_SSI_height_cm': round(min_ssi_h, 2),
        },
        'layers': [
            {
                'height_cm': round(L['height_cm'], 2),
                'density_kg_m3': round(L['density_kg_m3'], 2),
                'grain_type': L['grain_type'],
                'shear_strength_kPa': round(L['shear_strength_kPa'], 4),
                'Sk38': round(L['Sk38'], 4),
                'Sn38': round(L['Sn38'], 4),
                'SSI': round(L['SSI'], 4),
                'critical_cut_length_m': round(L['critical_cut_length_m'], 4),
            }
            for L in layers
        ],
    }
    return result


def main():
    parser = argparse.ArgumentParser(description='SNOWPACK profile stability analyzer')
    parser.add_argument('pro_file', help='Path to .pro file')
    parser.add_argument('timestamp', help='Timestamp in DD.MM.YYYY HH:MM:SS format')
    parser.add_argument('--slope-angle', type=float, required=True,
                        help='Station slope angle in degrees')
    args = parser.parse_args()

    station, timesteps = parse_pro_file(args.pro_file)

    target_ts = None
    for ts in timesteps:
        if ts['timestamp'] == args.timestamp:
            target_ts = ts
            break

    if target_ts is None:
        print(json.dumps({'error': f'Timestamp {args.timestamp} not found'}))
        sys.exit(1)

    target_ts['timestamp'] = args.timestamp
    result = analyze(target_ts, args.slope_angle)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
