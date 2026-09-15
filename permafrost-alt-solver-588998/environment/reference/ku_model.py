"""
Kudryavtsev Permafrost Model - Reference Implementation
Adapted from the permamodel package (Jafarov, Wang, Pierce et al.)

This module implements the Kudryavtsev analytical approach for computing
active layer thickness and permafrost temperature from climate and soil
data. It uses numpy for array operations across spatial grids.

NOTE: This code requires numpy (not installed in this environment).
It is provided as a reference for the correct physical formulations.
"""

import numpy as np


class KudryavtsevModel:
    """Analytical permafrost model computing active layer thickness and
    permafrost temperature from climate inputs and soil/snow/vegetation
    properties.

    Based on formulations from Anisimov et al. (1997) and
    Romanovsky & Osterkamp (1997).
    """

    SEC_PER_YEAR = np.float64(31556926.0)
    RHO_WATER = np.float64(1000.0)  # kg/m^3
    C_WATER = np.float64(4190.0)    # J/(kg*K)
    C_ICE = np.float64(2025.0)      # J/(kg*K)

    def __init__(self, config):
        self.config = config

    # ------------------------------------------------------------------
    # Soil thermal properties
    # ------------------------------------------------------------------

    def compute_soil_heat_capacity(self, soil_fractions, specific_heats,
                                   bulk_densities, vwc):
        """Volumetric heat capacity [J/(m^3*K)] for thawed and frozen states.

        The dry matrix heat capacity is the weighted average of soil
        component contributions (fraction * specific_heat * bulk_density).
        A water/ice content correction is added:

            C_thawed = C_dry + c_water * theta
            C_frozen = C_dry + c_ice * theta

        Parameters
        ----------
        soil_fractions : array
            Fraction of each soil type (must sum to 1.0)
        specific_heats : array
            Specific heat [J/(kg*K)] per soil type
        bulk_densities : array
            Bulk density [kg/m^3] per soil type
        vwc : float or array
            Volumetric water content [m^3/m^3]

        Returns
        -------
        C_thawed, C_frozen : arrays
        """
        weighted_hc = np.sum(soil_fractions * specific_heats)
        weighted_bd = np.sum(soil_fractions * bulk_densities)
        C_dry = weighted_hc * weighted_bd

        C_thawed = C_dry + self.C_WATER * vwc
        C_frozen = C_dry + self.C_ICE * vwc
        return C_thawed, C_frozen

    def compute_soil_thermal_conductivity(self, soil_fractions,
                                          k_dry_thawed, k_dry_frozen,
                                          vwc, k_water, k_ice, theta_u):
        """Thermal conductivity [W/(m*K)] using geometric mean mixing.

        The effective dry soil conductivity is computed as the GEOMETRIC
        mean of individual soil component conductivities, weighted by
        their volume fractions:

            K_dry = prod(k_i ^ f_i)

        This is then combined with water/ice phase conductivities using
        a power-law (de Vries) mixing model:

            K_thawed = K_dry_t^(1 - theta) * k_water^theta
            K_frozen = K_dry_f^(1 - theta) * k_ice^(theta - theta_u) * k_water^theta_u

        where theta is volumetric water content and theta_u is the
        residual unfrozen water content.

        Parameters
        ----------
        soil_fractions : array
            Volume fractions (sum to 1.0)
        k_dry_thawed, k_dry_frozen : arrays
            Dry thermal conductivity per soil type [W/(m*K)]
        vwc : float
            Volumetric water content
        k_water : float
            Thermal conductivity of liquid water [W/(m*K)]
        k_ice : float
            Thermal conductivity of ice [W/(m*K)]
        theta_u : float
            Unfrozen water content

        Returns
        -------
        Kt, Kf : floats
            Thawed and frozen thermal conductivities
        """
        # Geometric mean of dry soil conductivities
        K_geo_thawed = np.prod(k_dry_thawed ** soil_fractions)
        K_geo_frozen = np.prod(k_dry_frozen ** soil_fractions)

        # Power-law mixing with water/ice phases
        Kt = K_geo_thawed ** (np.float64(1.0) - vwc) * k_water ** vwc
        Kf = (K_geo_frozen ** (np.float64(1.0) - vwc)
              * k_ice ** (vwc - theta_u)
              * k_water ** theta_u)

        return Kt, Kf

    # ------------------------------------------------------------------
    # Snow thermal properties
    # ------------------------------------------------------------------

    def compute_snow_conductivity(self, rho_snow):
        """Snow thermal conductivity [W/(m*K)].

        Sturm et al. (1997), Eq. 4:
            k_sn = 0.138 - 1.01*(rho/1000) + 3.233*(rho/1000)^2

        Parameters
        ----------
        rho_snow : float
            Snow density [kg/m^3]
        """
        rho_n = rho_snow / np.float64(1000.0)
        return (np.float64(0.138)
                - np.float64(1.01) * rho_n
                + np.float64(3.233) * rho_n ** 2)

    def compute_snow_insulation(self, Aa, h_snow, k_snow,
                                rho_snow, C_snow):
        """Snow insulation effect on ground surface.

        The snow cover acts as a thermal blanket that warms the ground
        surface relative to the air. The penetration factor is:

            nf = h_snow * sqrt(pi / (kappa * P))

        where kappa = k_snow / (rho_snow * C_snow) is the snow thermal
        diffusivity and P is the period (seconds per year).

        The temperature warming and amplitude reduction are:

            delta_T = A_air * (1 - exp(-nf))
            delta_A = delta_T * 2/pi

        Parameters
        ----------
        Aa : float
            Air temperature amplitude [degC]
        h_snow : float
            Snow depth [m]
        k_snow : float
            Snow thermal conductivity [W/(m*K)]
        rho_snow : float
            Snow density [kg/m^3]
        C_snow : float
            Snow specific heat [J/(kg*K)]

        Returns
        -------
        dT_snow, dA_snow : floats
        """
        kappa = k_snow / (rho_snow * C_snow)

        if h_snow > 0 and kappa > 0:
            nf = h_snow * np.sqrt(np.pi / (kappa * self.SEC_PER_YEAR))
            damping = np.exp(-nf)
        else:
            damping = np.float64(1.0)

        dT = Aa * (np.float64(1.0) - damping)
        dA = dT * np.float64(2.0) / np.pi
        return dT, dA

    # ------------------------------------------------------------------
    # Vegetation effects
    # ------------------------------------------------------------------

    def compute_season_durations(self, Ta, Aa):
        """Freezing and thawing season durations [seconds].

            tau_freeze = P * (0.5 - arcsin(Ta/Aa) / pi)
            tau_thaw   = P - tau_freeze
        """
        tau1 = self.SEC_PER_YEAR * (
            np.float64(0.5) - np.arcsin(Ta / Aa) / np.pi)
        tau2 = self.SEC_PER_YEAR - tau1
        return tau1, tau2

    def compute_vegetation_effect(self, T_vg, A_vg,
                                  H_vf, H_vt, D_vf, D_vt,
                                  tau_freeze, tau_thaw):
        """Vegetation thermal effects on ground surface temperature.

        Vegetation provides insulation that modifies the ground surface
        thermal regime differently in winter (frozen canopy) and summer
        (thawed canopy).

        Winter amplitude reduction (frozen vegetation):
            dA1 = (A_vg - T_vg) * [1 - exp(-H_vf * sqrt(pi / (2*D_vf*tau1)))]

        Summer amplitude reduction (thawed vegetation):
            dA2 = (A_vg + T_vg) * [1 - exp(-H_vt * sqrt(pi / (2*D_vt*tau2)))]

        Net vegetation effects on the annual cycle:
            dA_veg = (dA1*tau1 + dA2*tau2) / P
            dT_veg = (dA1*tau1 - dA2*tau2) / P * (2/pi)

        Note the sign convention: dA1*tau1 corresponds to the winter
        (freezing season) contribution and dA2*tau2 to summer. The
        temperature offset dT_veg is positive when winter insulation
        dominates (dA1*tau1 > dA2*tau2), warming the ground.

        Parameters
        ----------
        T_vg, A_vg : floats
            Temperature and amplitude after snow correction
        H_vf, H_vt : floats
            Vegetation height in frozen/thawed states [m]
        D_vf, D_vt : floats
            Vegetation thermal diffusivity frozen/thawed [m^2/s]
        tau_freeze, tau_thaw : floats
            Season durations [seconds]

        Returns
        -------
        dT_veg, dA_veg : floats
            Temperature and amplitude offsets
        """
        # Winter (freezing season) vegetation insulation
        if H_vf > 0 and D_vf > 0 and tau_freeze > 0:
            inner_w = (np.float64(1.0) - np.exp(
                -H_vf * np.sqrt(np.pi / (2.0 * D_vf * tau_freeze))))
        else:
            inner_w = np.float64(0.0)
        dA1 = (A_vg - T_vg) * inner_w

        # Summer (thawing season) vegetation insulation
        if H_vt > 0 and D_vt > 0 and tau_thaw > 0:
            inner_s = (np.float64(1.0) - np.exp(
                -H_vt * np.sqrt(np.pi / (2.0 * D_vt * tau_thaw))))
        else:
            inner_s = np.float64(0.0)
        dA2 = (A_vg + T_vg) * inner_s

        # Net vegetation effect
        dA_veg = (dA1 * tau_freeze + dA2 * tau_thaw) / self.SEC_PER_YEAR
        dT_veg = ((dA1 * tau_freeze - dA2 * tau_thaw)
                  / self.SEC_PER_YEAR * (np.float64(2.0) / np.pi))

        return dT_veg, dA_veg

    # ------------------------------------------------------------------
    # Permafrost temperature
    # ------------------------------------------------------------------

    def compute_permafrost_temperature(self, Tgs, Ags, Kt, Kf):
        """Temperature at top of permafrost [degC].

        The permafrost temperature accounts for the asymmetry between
        frozen and thawed thermal conductivities:

            r = Tgs / Ags
            bracket = r * arcsin(r) + sqrt(1 - r^2)
            numerator = 0.5 * Tgs * (Kf + Kt)
                      + Ags * (Kt - Kf) / pi * bracket

        When numerator >= 0: no permafrost exists (seasonal frost only).
        When numerator < 0:  Tps = numerator / Kf

        For typical permafrost conditions, Kf > Kt, so the term
        (Kt - Kf) is negative. Combined with the bracket term (always
        positive), this creates a negative correction that pulls Tps
        below Tgs — the "thermal offset" effect.

        Parameters
        ----------
        Tgs : float
            Mean annual ground surface temperature [degC]
        Ags : float
            Ground surface temperature amplitude [degC]
        Kt, Kf : floats
            Thawed and frozen thermal conductivities [W/(m*K)]

        Returns
        -------
        Tps : float or None
            Permafrost temperature, or None if no permafrost
        """
        r = Tgs / Ags
        bracket = r * np.arcsin(r) + np.sqrt(np.float64(1.0) - r ** 2)

        numerator = (np.float64(0.5) * Tgs * (Kf + Kt)
                     + Ags * (Kt - Kf) / np.pi * bracket)

        if numerator >= 0:
            return None  # No permafrost

        return numerator / Kf

    # ------------------------------------------------------------------
    # Active layer thickness
    # ------------------------------------------------------------------

    def compute_active_layer_thickness(self, Tps, Ags, Kf, Cf,
                                       vwc, L_heat):
        """Active layer thickness [m].

        Uses the Romanovsky & Osterkamp (1997) formulation (Eqs. 3-5).

        Volumetric latent heat:
            L = L_heat * rho_water * theta

        where rho_water = 1000 kg/m^3.

        Parameters
        ----------
        Tps : float
            Permafrost temperature [degC]
        Ags : float
            Ground surface amplitude [degC]
        Kf : float
            Frozen thermal conductivity [W/(m*K)]
        Cf : float
            Frozen heat capacity [J/(m^3*K)]
        vwc : float
            Volumetric water content
        L_heat : float
            Latent heat of fusion [J/kg]

        Returns
        -------
        Z_al : float or None
            Active layer thickness [m]
        """
        L = L_heat * self.RHO_WATER * vwc

        abs_Tps = np.abs(Tps)
        diff = Ags - abs_Tps
        if diff <= 0:
            return None

        half_L_C = L / (np.float64(2.0) * Cf)

        log_arg = (Ags + half_L_C) / (abs_Tps + half_L_C)
        if log_arg <= 0:
            return None

        # Eq. 4: permafrost amplitude
        Aps = diff / np.log(log_arg) - half_L_C
        if Aps <= 0:
            return None

        # Eq. 5: critical depth
        sqrt_KC = np.sqrt(Kf * Cf * self.SEC_PER_YEAR / np.pi)
        B = np.float64(2.0) * Aps * Cf + L
        Zc = np.float64(2.0) * diff * sqrt_KC / B

        # Eq. 3: active layer thickness
        sqrt_K = np.sqrt(Kf * self.SEC_PER_YEAR / (Cf * np.pi))
        G = (np.float64(2.0) * Aps * Cf + L) * Zc
        Z_al = (np.float64(2.0) * diff * sqrt_KC
                + G * L * sqrt_K / (G + B * sqrt_K)) / B

        return Z_al if Z_al > 0 else None
