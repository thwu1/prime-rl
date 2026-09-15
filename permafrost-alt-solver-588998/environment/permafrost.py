#!/usr/bin/env python3
"""Permafrost analysis pipeline.

Reads site parameters from config.toml and computes permafrost
properties including frost number, ground surface regime,
permafrost temperature, and active layer thickness.
"""

import json
import math
import sys

try:
    import tomllib
except ImportError:
    import tomli as tomllib


def load_config(path):
    with open(path, "rb") as f:
        return tomllib.load(f)


def compute_frost_number(T_cold, T_hot):
    """Compute reduced air frost number."""
    assert T_hot >= T_cold
    T_avg = (T_hot + T_cold) / 2.0
    T_amp = (T_hot - T_cold) / 2.0

    if T_hot <= 0:
        ddf = -365.0 * T_avg
        ddt = 0.0
    elif T_cold >= 0:
        ddf = 0.0
        ddt = 365.0 * T_avg
    else:
        Beta = math.acos(-T_avg / T_amp)
        T_summer = T_avg + T_amp * math.sin(Beta) / Beta
        T_winter = T_avg - T_amp * math.sin(Beta) / (math.pi - Beta)
        L_summer = 365.0 * Beta / math.pi
        L_winter = 365.0 - L_summer
        ddt = T_summer * L_summer
        ddf = -T_winter * L_winter

    if ddf == 0 and ddt == 0:
        return 0.0
    if ddt == 0:
        return 1.0
    if ddf == 0:
        return 0.0
    return math.sqrt(ddf) / (math.sqrt(ddf) + math.sqrt(ddt))


def compute_soil_heat_capacity(soils_config, soil_fractions, vwc):
    """Compute thawed and frozen volumetric heat capacity."""
    total_frac = sum(soil_fractions.values())
    if total_frac == 0:
        raise ValueError("Total soil fraction is zero")

    w_hc = sum(
        soils_config[k]["specific_heat"] * soil_fractions.get(k, 0) / total_frac
        for k in soils_config
    )
    w_bd = sum(
        soils_config[k]["bulk_density"] * soil_fractions.get(k, 0) / total_frac
        for k in soils_config
    )

    Ct = w_hc * w_bd + 4190.0 * vwc
    Cf = w_hc * w_bd + 2025.0 * vwc
    return Ct, Cf


def compute_soil_thermal_conductivity(soils_config, soil_fractions, vwc, constants):
    """Compute thawed and frozen effective thermal conductivity."""
    total_frac = sum(soil_fractions.values())
    uwc = constants["unfrozen_water_content"]
    kw = constants["thawed_water_conductivity"]
    ki = constants["ice_conductivity"]

    # Effective dry conductivity from weighted soil components
    dry_thawed = 0.0
    dry_frozen = 0.0
    for k in soils_config:
        frac = soil_fractions.get(k, 0) / total_frac
        dry_thawed += soils_config[k]["conductivity_thawed_dry"] * frac
        dry_frozen += soils_config[k]["conductivity_frozen_dry"] * frac

    # Water content correction for effective conductivity
    Kt = dry_thawed + kw * vwc
    Kf = dry_frozen + ki * (vwc - uwc) + kw * uwc

    return Kt, Kf


def compute_snow_thermal_properties(rho_snow, snow_cp):
    """Compute snow thermal conductivity and diffusivity."""
    rho_norm = rho_snow / 1000.0
    Ksn = 0.138 - 1.01 * rho_norm + 3.233 * rho_norm ** 2
    kappa = Ksn / (rho_snow * snow_cp)
    return Ksn, kappa


def compute_ground_surface_regime(Ta, Aa, h_snow, rho_snow, Hvgf, Hvgt, Dvf, Dvt, constants):
    """Compute ground surface temperature and amplitude with snow and vegetation."""
    sec_per_a = constants["seconds_per_year"]
    snow_cp = constants["snow_specific_heat"]

    # Snow thermal properties
    Ksn, kappa_snow = compute_snow_thermal_properties(rho_snow, snow_cp)

    # Season durations
    tao1 = sec_per_a * (0.5 - (1.0 / math.pi) * math.asin(Ta / Aa))
    tao2 = sec_per_a - tao1

    # Snow damping factor
    if h_snow > 0 and kappa_snow > 0:
        nf = h_snow * math.pi / (sec_per_a * kappa_snow)
        temp = math.exp(-nf)
    else:
        temp = 1.0
    dTsn = Aa * (1.0 - temp)
    dAsn = dTsn * 2.0 / math.pi

    Tvg = Ta + dTsn
    Avg = Aa - dAsn

    # Winter vegetation insulation
    if Hvgf > 0 and Dvf > 0 and tao1 > 0:
        inner10 = 1.0 - math.exp(-Hvgf * math.sqrt(math.pi / (2.0 * Dvf * tao1)))
    else:
        inner10 = 0.0
    dA1 = (Avg - Tvg) * inner10

    # Summer vegetation insulation
    if Hvgt > 0 and Dvt > 0 and tao2 > 0:
        inner11 = 1.0 - math.exp(-Hvgt * math.sqrt(math.pi / (2.0 * Dvt * tao2)))
    else:
        inner11 = 0.0
    dA2 = (Avg + Tvg) * inner11

    # Combined vegetation effect on amplitude and temperature
    dAv = (dA1 * tao1 + dA2 * tao2) / sec_per_a
    dTv = (dA2 * tao2 - dA1 * tao1) / sec_per_a * (2.0 / math.pi)

    Tgs = Tvg + dTv
    Ags = Avg - dAv

    return Tgs, Ags


def compute_permafrost_temperature(Tgs, Ags, Kt, Kf, Ct, Cf):
    """Compute temperature at top of permafrost."""
    ratio = Tgs / Ags
    first_term = 0.5 * Tgs * (Kf + Kt)
    inner = ratio * math.asin(ratio) + math.sqrt(1.0 - ratio ** 2)
    second_term = Ags * (Kf - Kt) / math.pi
    numerator = first_term + second_term * inner

    if numerator > 0:
        # No permafrost — seasonal frost ground
        return None, None, None, None

    K_star = Kf
    C_star = Cf
    Tps = numerator / K_star

    return Tps, K_star, C_star, numerator


def compute_active_layer_thickness(Tps, Ags, K, C, vwc, constants):
    """Compute active layer thickness."""
    sec_per_a = constants["seconds_per_year"]
    L_heat = constants["latent_heat"]
    L = L_heat * 1000.0 * vwc

    abs_Tps = abs(Tps)
    diff = Ags - abs_Tps
    half_L_C = L / (2.0 * C)

    if diff <= 0 or (Ags + half_L_C) <= 0 or (abs_Tps + half_L_C) <= 0:
        return None

    log_arg = (Ags + half_L_C) / (abs_Tps + half_L_C)
    if log_arg <= 0:
        return None

    # Permafrost amplitude
    Aps = diff / math.log(log_arg) - half_L_C

    if Aps <= 0:
        return None

    # Critical depth
    sqrt_KCsec_pi = math.sqrt(K * C * sec_per_a / math.pi)
    B = 2.0 * Aps * C + L
    Zc = 2.0 * diff * sqrt_KCsec_pi / B

    # Active layer thickness
    sqrt_Ksec_Cpi = math.sqrt(K * sec_per_a / (C * math.pi))
    G = 2.0 * Aps * C * Zc + L * Zc
    numer = 2.0 * diff * sqrt_KCsec_pi + G * L * sqrt_Ksec_Cpi / (G + B * sqrt_Ksec_Cpi)
    Zal = numer / B

    if Zal <= 0 or math.isnan(Zal):
        return None

    return Zal


def process_site(site_config, soils_config, constants):
    """Process a single site and return computed values."""
    Ta = site_config["air_temperature"]
    Aa = site_config["temperature_amplitude"]
    h_snow = site_config["snow_depth"]
    rho_snow = site_config["snow_density"]
    vwc = site_config["volumetric_water_content"]
    Hvgf = site_config["frozen_vegetation_height"]
    Hvgt = site_config["thawed_vegetation_height"]
    Dvf = site_config["frozen_vegetation_diffusivity"]
    Dvt = site_config["thawed_vegetation_diffusivity"]
    soil_fracs = site_config["soil_fractions"]

    # Frost number
    T_cold = Ta - Aa
    T_hot = Ta + Aa
    fn = compute_frost_number(T_cold, T_hot)

    # Ground surface regime
    Tgs, Ags = compute_ground_surface_regime(
        Ta, Aa, h_snow, rho_snow, Hvgf, Hvgt, Dvf, Dvt, constants
    )

    # Soil thermal properties
    Ct, Cf = compute_soil_heat_capacity(soils_config, soil_fracs, vwc)
    Kt, Kf = compute_soil_thermal_conductivity(soils_config, soil_fracs, vwc, constants)

    # Permafrost temperature
    Tps, K_star, C_star, numerator = compute_permafrost_temperature(Tgs, Ags, Kt, Kf, Ct, Cf)

    has_permafrost = Tps is not None

    # Active layer thickness
    alt = None
    if has_permafrost:
        alt = compute_active_layer_thickness(Tps, Ags, K_star, C_star, vwc, constants)

    return {
        "air_frost_number": fn,
        "ground_surface_temperature": Tgs,
        "ground_surface_amplitude": Ags,
        "has_permafrost": has_permafrost,
        "permafrost_temperature": Tps,
        "active_layer_thickness": alt,
    }


def main():
    config = load_config("/app/config.toml")
    constants = config["constants"]
    soils = config["soils"]
    sites = config["sites"]

    results = {}
    for site_name, site_config in sites.items():
        results[site_name] = process_site(site_config, soils, constants)

    with open("/app/output.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
