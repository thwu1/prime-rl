#!/usr/bin/env python3

"""
Permafrost analysis pipeline — corrected version.

Fixes applied:
1. Makefile: produce shared library (.so) with -fPIC -shared
2. Fortran: geometric mean for dry conductivity, power-law water correction
3. Python snow: sqrt in penetration factor
4. Python vegetation: correct sign on temperature offset (dA1*tau1 - dA2*tau2)
5. Python permafrost temp: correct sign (Kt - Kf) for conductivity asymmetry
"""

import ctypes
import json
import math
import os
import subprocess
import sys

try:
    import tomllib
except ImportError:
    import tomli as tomllib

THERMAL_LIB_DIR = "/app/thermal_lib"
THERMAL_LIB_PATH = os.path.join(THERMAL_LIB_DIR, "libthermal.so")


def build_thermal_library():
    """Build the Fortran thermal property library if not present."""
    if os.path.exists(THERMAL_LIB_PATH):
        return True
    result = subprocess.run(
        ["make", "-C", THERMAL_LIB_DIR],
        capture_output=True, text=True,
    )
    if result.stdout:
        print(result.stdout, file=sys.stderr)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return os.path.exists(THERMAL_LIB_PATH)


def load_thermal_library():
    """Load the compiled Fortran thermal property library."""
    if not build_thermal_library():
        print(
            "Error: libthermal.so not found at "
            f"{THERMAL_LIB_PATH}",
            file=sys.stderr,
        )
        sys.exit(1)
    lib = ctypes.CDLL(THERMAL_LIB_PATH)
    _setup_signatures(lib)
    return lib


def _setup_signatures(lib):
    """Configure ctypes function signatures for the Fortran library."""
    lib.compute_conductivity.argtypes = [
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_double),
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_double),
    ]
    lib.compute_conductivity.restype = None

    lib.compute_heat_capacity.argtypes = [
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_double),
        ctypes.c_double,
        ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_double),
    ]
    lib.compute_heat_capacity.restype = None


def load_config(path):
    with open(path, "rb") as f:
        return tomllib.load(f)


def compute_frost_number(T_cold, T_hot):
    """Compute reduced air frost number (Nelson & Outcalt 1983)."""
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


def compute_soil_thermal_properties(lib, soils_config, soil_fractions,
                                     vwc, constants):
    """Call Fortran library for soil thermal conductivity and heat capacity."""
    total_frac = sum(soil_fractions.values())
    if total_frac == 0:
        raise ValueError("Total soil fraction is zero")

    soil_keys = list(soils_config.keys())
    n = len(soil_keys)

    fracs = [soil_fractions.get(k, 0) / total_frac for k in soil_keys]
    kt_dry = [soils_config[k]["conductivity_thawed_dry"] for k in soil_keys]
    kf_dry = [soils_config[k]["conductivity_frozen_dry"] for k in soil_keys]
    spec_heats = [soils_config[k]["specific_heat"] for k in soil_keys]
    bulk_dens = [soils_config[k]["bulk_density"] for k in soil_keys]

    uwc = constants["unfrozen_water_content"]
    kw = constants["thawed_water_conductivity"]
    ki = constants["ice_conductivity"]

    arr_t = ctypes.c_double * n
    frac_arr = arr_t(*fracs)
    kt_dry_arr = arr_t(*kt_dry)
    kf_dry_arr = arr_t(*kf_dry)
    sheat_arr = arr_t(*spec_heats)
    bdens_arr = arr_t(*bulk_dens)

    Kt = ctypes.c_double()
    Kf = ctypes.c_double()
    Ct = ctypes.c_double()
    Cf = ctypes.c_double()

    lib.compute_conductivity(
        ctypes.c_int(n), frac_arr, kt_dry_arr, kf_dry_arr,
        ctypes.c_double(vwc), ctypes.c_double(kw),
        ctypes.c_double(ki), ctypes.c_double(uwc),
        ctypes.byref(Kt), ctypes.byref(Kf),
    )

    lib.compute_heat_capacity(
        ctypes.c_int(n), frac_arr, sheat_arr, bdens_arr,
        ctypes.c_double(vwc),
        ctypes.byref(Ct), ctypes.byref(Cf),
    )

    return Kt.value, Kf.value, Ct.value, Cf.value


def compute_snow_thermal_properties(rho_snow, snow_cp):
    """Snow thermal conductivity (Sturm 1997, eq. 4) and diffusivity."""
    rho_norm = rho_snow / 1000.0
    Ksn = 0.138 - 1.01 * rho_norm + 3.233 * rho_norm ** 2
    kappa = Ksn / (rho_snow * snow_cp)
    return Ksn, kappa


def compute_ground_surface_regime(Ta, Aa, h_snow, rho_snow,
                                   Hvgf, Hvgt, Dvf, Dvt, constants):
    """Compute ground surface temperature and amplitude."""
    sec_per_a = constants["seconds_per_year"]
    snow_cp = constants["snow_specific_heat"]

    Ksn, kappa_snow = compute_snow_thermal_properties(rho_snow, snow_cp)

    tao1 = sec_per_a * (0.5 - (1.0 / math.pi) * math.asin(Ta / Aa))
    tao2 = sec_per_a - tao1

    # Snow insulation effect — FIX: sqrt in penetration factor
    if h_snow > 0 and kappa_snow > 0:
        nf = h_snow * math.sqrt(math.pi / (sec_per_a * kappa_snow))
        temp = math.exp(-nf)
    else:
        temp = 1.0
    dTsn = Aa * (1.0 - temp)
    dAsn = dTsn * 2.0 / math.pi

    Tvg = Ta + dTsn
    Avg = Aa - dAsn

    # Vegetation effects
    if Hvgf > 0 and Dvf > 0 and tao1 > 0:
        inner10 = 1.0 - math.exp(
            -Hvgf * math.sqrt(math.pi / (2.0 * Dvf * tao1))
        )
    else:
        inner10 = 0.0
    dA1 = (Avg - Tvg) * inner10

    if Hvgt > 0 and Dvt > 0 and tao2 > 0:
        inner11 = 1.0 - math.exp(
            -Hvgt * math.sqrt(math.pi / (2.0 * Dvt * tao2))
        )
    else:
        inner11 = 0.0
    dA2 = (Avg + Tvg) * inner11

    dAv = (dA1 * tao1 + dA2 * tao2) / sec_per_a
    # FIX: correct sign — dA1*tau1 - dA2*tau2, not reversed
    dTv = (dA1 * tao1 - dA2 * tao2) / sec_per_a * (2.0 / math.pi)

    Tgs = Tvg + dTv
    Ags = Avg - dAv

    return Tgs, Ags


def compute_permafrost_temperature(Tgs, Ags, Kt, Kf, Ct, Cf):
    """Compute temperature at top of permafrost."""
    ratio = Tgs / Ags
    first_term = 0.5 * Tgs * (Kf + Kt)
    inner = ratio * math.asin(ratio) + math.sqrt(1.0 - ratio ** 2)
    # FIX: correct sign — (Kt - Kf), not (Kf - Kt)
    second_term = Ags * (Kt - Kf) / math.pi
    numerator = first_term + second_term * inner

    if numerator > 0:
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

    Aps = diff / math.log(log_arg) - half_L_C
    if Aps <= 0:
        return None

    sqrt_KCsec_pi = math.sqrt(K * C * sec_per_a / math.pi)
    B = 2.0 * Aps * C + L
    Zc = 2.0 * diff * sqrt_KCsec_pi / B

    sqrt_Ksec_Cpi = math.sqrt(K * sec_per_a / (C * math.pi))
    G = 2.0 * Aps * C * Zc + L * Zc
    numer = (2.0 * diff * sqrt_KCsec_pi
             + G * L * sqrt_Ksec_Cpi / (G + B * sqrt_Ksec_Cpi))
    Zal = numer / B

    if Zal <= 0 or math.isnan(Zal):
        return None

    return Zal


def process_site(lib, site_config, soils_config, constants):
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

    T_cold = Ta - Aa
    T_hot = Ta + Aa
    fn = compute_frost_number(T_cold, T_hot)

    Tgs, Ags = compute_ground_surface_regime(
        Ta, Aa, h_snow, rho_snow, Hvgf, Hvgt, Dvf, Dvt, constants
    )

    Kt, Kf, Ct, Cf = compute_soil_thermal_properties(
        lib, soils_config, site_config["soil_fractions"], vwc, constants
    )

    Tps, K_star, C_star, _ = compute_permafrost_temperature(
        Tgs, Ags, Kt, Kf, Ct, Cf
    )
    has_permafrost = Tps is not None

    alt = None
    if has_permafrost:
        alt = compute_active_layer_thickness(
            Tps, Ags, K_star, C_star, vwc, constants
        )

    return {
        "air_frost_number": fn,
        "ground_surface_temperature": Tgs,
        "ground_surface_amplitude": Ags,
        "has_permafrost": has_permafrost,
        "permafrost_temperature": Tps,
        "active_layer_thickness": alt,
    }


def main():
    lib = load_thermal_library()

    config = load_config("/app/config.toml")
    constants = config["constants"]
    soils = config["soils"]
    sites = config["sites"]

    results = {}
    for site_name, site_config in sites.items():
        results[site_name] = process_site(lib, site_config, soils, constants)

    with open("/app/output.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
