"""Standalone marine carbonate system solver.

Implements the full marine carbonate system equilibrium calculation from any
pair of (TA, DIC, pH, fCO2, CO3, HCO3) using published thermodynamic
formulations.

Configuration:
- K1, K2: Lueker et al. (2000) - Total pH scale
- KB: Dickson (1990) - Total pH scale
- KW: Millero (1995) - SWS pH scale (converted to Total)
- KSO4: Dickson (1990) - Free pH scale
- KF: Dickson & Riley (1979) - Free pH scale
- KP1, KP2, KP3: Millero (1995) - SWS pH scale (converted to Total)
- KSi: Millero (1995) - SWS pH scale (converted to Total)
- K0: Weiss (1974)
- KCa, KAr: Mucci (1983)
- TB: Uppstrom (1974)
- Pressure corrections: Millero (1995)
- pH scale: Total

"""

import numpy as np


# ============================================================================
# Total concentrations from salinity
# ============================================================================

def salinity_totals(S, total_silicate_umol=0.0, total_phosphate_umol=0.0):
    """Compute total concentrations from salinity (all in mol/kg-sw)."""
    TB = 0.000232 / 10.811 * S / 1.80655     # Uppstrom 1974
    TF = 0.000067 / 18.998 * S / 1.80655     # Riley 1965
    TSO4 = 0.14 / 96.062 * S / 1.80655       # Morris & Riley 1966
    TCa = 0.02128 / 40.087 * S / 1.80655     # Riley & Tongudai 1967
    TSi = total_silicate_umol * 1e-6          # umol/kg to mol/kg
    TPO4 = total_phosphate_umol * 1e-6        # umol/kg to mol/kg
    return {
        "TB": TB, "TF": TF, "TSO4": TSO4, "TCa": TCa,
        "TSi": TSi, "TPO4": TPO4,
    }


# ============================================================================
# Equilibrium constants at 1 atm (no pressure correction)
# ============================================================================

def K0_W74(TK, S):
    """CO2 solubility constant, Weiss 1974. mol/(kg-sw * atm)."""
    TK100 = TK / 100.0
    lnK0 = (-60.2409 + 93.4517 / TK100 + 23.3585 * np.log(TK100)
             + S * (0.023517 - 0.023656 * TK100 + 0.0047036 * TK100**2))
    return np.exp(lnK0)


def K1K2_LDK00(TK, S):
    """Carbonic acid K1, K2 from Lueker et al. 2000. Total pH scale."""
    lnTK = np.log(TK)
    pK1 = (3663.86 / TK - 61.2172 + 9.6777 * lnTK
            - 0.011555 * S + 0.0001152 * S**2)
    pK2 = (471.78 / TK + 25.929 - 3.16967 * lnTK
            - 0.01781 * S + 0.0001122 * S**2)
    return 10.0**(-pK1), 10.0**(-pK2)


def KB_D90(TK, S):
    """Boric acid dissociation, Dickson 1990. Total pH scale."""
    sqrtS = np.sqrt(S)
    lnKB = ((-8966.90 - 2890.53 * sqrtS - 77.942 * S
              + 1.728 * S**1.5 - 0.0996 * S**2) / TK
             + 148.0248 + 137.1942 * sqrtS + 1.62142 * S
             + (-24.4344 - 25.085 * sqrtS - 0.2474 * S) * np.log(TK)
             + 0.053105 * sqrtS * TK)
    return np.exp(lnKB)


def KW_M95(TK, S):
    """Water dissociation, Millero 1995. SWS pH scale."""
    lnTK = np.log(TK)
    sqrtS = np.sqrt(S)
    lnKW = (148.9652 - 13847.26 / TK - 23.6521 * lnTK
             + (-5.977 + 118.67 / TK + 1.0495 * lnTK) * sqrtS
             - 0.01615 * S)
    return np.exp(lnKW)


def KSO4_D90(TK, S):
    """Bisulfate dissociation, Dickson 1990. Free pH scale."""
    IonS = 19.924 * S / (1000.0 - 1.005 * S)
    sqrtI = np.sqrt(IonS)
    lnTK = np.log(TK)
    lnKSO4 = (141.328 - 4276.1 / TK - 23.093 * lnTK
               + (-13856.0 / TK + 324.57 - 47.986 * lnTK) * sqrtI
               + (35474.0 / TK - 771.54 + 114.723 * lnTK) * IonS
               - 2698.0 / TK * IonS**1.5
               + 1776.0 / TK * IonS**2
               + np.log(1.0 - 0.001005 * S))
    return np.exp(lnKSO4)


def KF_DR79(TK, S):
    """Fluoride dissociation, Dickson & Riley 1979. Free pH scale.

    The published formula gives KF on a scale that includes the sulfate
    medium. We convert to the free scale by dividing out the sulfate factor.
    """
    IonS = 19.924 * S / (1000.0 - 1.005 * S)
    sqrtI = np.sqrt(IonS)
    lnKF = 1590.2 / TK - 12.641 + 1.225 * sqrtI
    KF = np.exp(lnKF)
    # Convert from mol/kg-H2O to mol/kg-SW
    KF = KF * (1.0 - 0.001005 * S)
    return KF


def KP123_M95(TK, S):
    """Phosphoric acid K1, K2, K3 from Millero 1995. SWS pH scale."""
    lnTK = np.log(TK)
    lnKP1 = (-4576.752 / TK + 115.54 - 18.453 * lnTK
              + (-106.736 / TK + 0.69171) * np.sqrt(S)
              + (-0.65643 / TK - 0.01844) * S)
    lnKP2 = (-8814.715 / TK + 172.1033 - 27.927 * lnTK
              + (-160.340 / TK + 1.3566) * np.sqrt(S)
              + (0.37335 / TK - 0.05778) * S)
    lnKP3 = (-3070.75 / TK - 18.126
              + (17.27039 / TK + 2.81197) * np.sqrt(S)
              + (-44.99486 / TK - 0.09984) * S)
    return np.exp(lnKP1), np.exp(lnKP2), np.exp(lnKP3)


def KSi_M95(TK, S):
    """Silicic acid dissociation, Millero 1995. SWS pH scale."""
    IonS = 19.924 * S / (1000.0 - 1.005 * S)
    sqrtI = np.sqrt(IonS)
    lnTK = np.log(TK)
    lnKSi = (-8904.2 / TK + 117.4 - 19.334 * lnTK
              + (-458.79 / TK + 3.5913) * sqrtI
              + (188.74 / TK - 1.5998) * IonS
              + (-12.1652 / TK + 0.07871) * IonS**2
              + np.log(1.0 - 0.001005 * S))
    return np.exp(lnKSi)


def KCa_M83(TK, S):
    """Calcite solubility product, Mucci 1983."""
    logKCa = (-171.9065 - 0.077993 * TK + 2839.319 / TK
               + 71.595 * np.log10(TK)
               + (-0.77712 + 0.0028426 * TK + 178.34 / TK) * np.sqrt(S)
               - 0.07711 * S + 0.0041249 * S**1.5)
    return 10.0**logKCa


def KAr_M83(TK, S):
    """Aragonite solubility product, Mucci 1983."""
    logKAr = (-171.945 - 0.077993 * TK + 2903.293 / TK
               + 71.595 * np.log10(TK)
               + (-0.068393 + 0.0017276 * TK + 88.135 / TK) * np.sqrt(S)
               - 0.10018 * S + 0.0059415 * S**1.5)
    return 10.0**logKAr


def fugacity_factor(TK):
    """Fugacity factor for CO2, from Weiss 1974.

    pCO2 = fCO2 / FugFac  =>  FugFac = fCO2 / pCO2
    Actually: fCO2 = pCO2 * FugFac, so FugFac < 1 typically.
    """
    # Virial coefficients for CO2 (Weiss 1974)
    B = -1636.75 + 12.0408 * TK - 0.0327957 * TK**2 + 3.16528e-5 * TK**3
    delta = 57.7 - 0.118 * TK
    # R = 82.057 cm^3 atm / (mol K), P = 1 atm
    R_atm = 82.057
    P_atm = 1.0
    return np.exp((B + 2.0 * delta) * P_atm / (R_atm * TK))


# ============================================================================
# Pressure corrections (Millero 1995)
# ============================================================================

def pressure_correction(K, TC, P_bar, deltaV_coeffs, deltaK_coeffs):
    """Apply pressure correction to an equilibrium constant.

    K: constant at 1 atm
    TC: temperature in Celsius
    P_bar: pressure in bar (not dbar!)
    deltaV_coeffs: (a0, a1, a2) for deltaV = a0 + a1*TC + a2*TC^2
    deltaK_coeffs: (b0, b1) for deltaK = (b0 + b1*TC) * 1e-3
    """
    if P_bar <= 0:
        return K
    TK = TC + 273.15
    R = 83.14472  # cm^3 bar / (mol K)
    deltaV = deltaV_coeffs[0] + deltaV_coeffs[1] * TC + deltaV_coeffs[2] * TC**2
    deltaK = (deltaK_coeffs[0] + deltaK_coeffs[1] * TC) * 1e-3
    lnK_ratio = (-deltaV + 0.5 * deltaK * P_bar) * P_bar / (R * TK)
    return K * np.exp(lnK_ratio)


# Pressure correction coefficients (Millero 1995)
# Format: (a0, a1, a2) for deltaV, (b0, b1) for deltaK
PC_K1 = ((-25.50, 0.1271, 0.0), (-3.08, 0.0877))
PC_K2 = ((-15.82, -0.0219, 0.0), (1.13, -0.1475))
PC_KB = ((-29.48, 0.1622, -0.002608), (-2.84, 0.0))
PC_KW = ((-25.60, 0.2324, -0.0036246), (-5.13, 0.0714))
PC_KSO4 = ((-18.03, 0.0466, 0.000316), (-4.53, 0.09))
PC_KF = ((-9.78, -0.0090, -0.000942), (-3.91, 0.054))
PC_KP1 = ((-14.51, 0.1211, -0.000321), (-2.67, 0.0427))
PC_KP2 = ((-23.12, 0.1758, -0.002647), (-5.15, 0.09))
PC_KP3 = ((-26.57, 0.202, -0.003042), (-4.08, 0.0714))
PC_KSi = ((-29.48, 0.1622, -0.002608), (-2.84, 0.0))


def pressure_correct_solubility(K, TC, P_bar, mineral="calcite"):
    """Pressure correction for calcite/aragonite solubility."""
    if P_bar <= 0:
        return K
    TK = TC + 273.15
    R = 83.14472
    deltaV_Ca = -48.76 + 0.5304 * TC
    deltaK_Ca = (-11.76 + 0.3692 * TC) * 1e-3
    if mineral == "aragonite":
        deltaV = deltaV_Ca + 2.8
    else:
        deltaV = deltaV_Ca
    deltaK = deltaK_Ca
    lnK_ratio = (-deltaV + 0.5 * deltaK * P_bar) * P_bar / (R * TK)
    return K * np.exp(lnK_ratio)


# ============================================================================
# pH scale conversions
# ============================================================================

def sws_to_total_factor(TSO4, TF, KSO4, KF):
    """Factor to convert from SWS to Total pH scale.

    K_Total = K_SWS * factor
    """
    # [H+]_T = [H+]_F * (1 + TSO4/KSO4)
    # [H+]_SWS = [H+]_F * (1 + TSO4/KSO4 + TF/KF)
    # factor = [H+]_T / [H+]_SWS for the H+ part
    # For equilibrium constants: K_T = K_SWS * [H+]_SWS / [H+]_T
    # Wait, K = [H+]*... so K_T = [H+]_T*... and K_SWS = [H+]_SWS*...
    # K_T / K_SWS = [H+]_T / [H+]_SWS
    # [H+]_T / [H+]_SWS = (1 + TSO4/KSO4) / (1 + TSO4/KSO4 + TF/KF)
    return (1.0 + TSO4 / KSO4) / (1.0 + TSO4 / KSO4 + TF / KF)


# ============================================================================
# Assemble all constants
# ============================================================================

def assemble_constants(temperature, salinity, pressure, totals):
    """Compute all equilibrium constants at given T, S, P on Total pH scale.

    Follows PyCO2SYS convention:
    - KSO4 and KF are always on Free scale
    - All other Ks are pressure-corrected on SWS scale, then converted to Total
    - Constants natively on Total (K1/K2/KB) are first converted to SWS at 1 atm

    temperature: deg C
    salinity: practical salinity
    pressure: dbar (hydrostatic pressure, 0 at surface)
    totals: dict from salinity_totals()
    """
    TK = temperature + 273.15
    TC = temperature
    P_bar = pressure / 10.0  # dbar to bar
    TSO4 = totals["TSO4"]
    TF = totals["TF"]

    # Step 1: KSO4 and KF at 1 atm on Free scale
    KSO4_0 = KSO4_D90(TK, salinity)
    KF_0 = KF_DR79(TK, salinity)

    # Step 2: KSO4 and KF at pressure on Free scale
    KSO4 = pressure_correction(KSO4_0, TC, P_bar, PC_KSO4[0], PC_KSO4[1])
    KF = pressure_correction(KF_0, TC, P_bar, PC_KF[0], PC_KF[1])

    # Step 3: pH scale conversion factors at 1 atm and at pressure
    SWStoTOT_0 = sws_to_total_factor(TSO4, TF, KSO4_0, KF_0)
    SWStoTOT_P = sws_to_total_factor(TSO4, TF, KSO4, KF)

    # K0 - no pH scale dependence
    K0 = K0_W74(TK, salinity)

    # K1, K2: LDK00, natively Total at 1 atm -> SWS -> PC -> Total
    K1_t, K2_t = K1K2_LDK00(TK, salinity)
    K1 = pressure_correction(K1_t / SWStoTOT_0, TC, P_bar,
                             PC_K1[0], PC_K1[1]) * SWStoTOT_P
    K2 = pressure_correction(K2_t / SWStoTOT_0, TC, P_bar,
                             PC_K2[0], PC_K2[1]) * SWStoTOT_P

    # KB: D90, natively Total at 1 atm -> SWS -> PC -> Total
    KB_t = KB_D90(TK, salinity)
    KB = pressure_correction(KB_t / SWStoTOT_0, TC, P_bar,
                             PC_KB[0], PC_KB[1]) * SWStoTOT_P

    # KW: M95, natively SWS at 1 atm -> PC on SWS -> Total
    KW = KW_M95(TK, salinity)
    KW = pressure_correction(KW, TC, P_bar, PC_KW[0], PC_KW[1]) * SWStoTOT_P

    # KP1-3: M95, natively SWS at 1 atm -> PC on SWS -> Total
    KP1, KP2, KP3 = KP123_M95(TK, salinity)
    KP1 = pressure_correction(KP1, TC, P_bar,
                              PC_KP1[0], PC_KP1[1]) * SWStoTOT_P
    KP2 = pressure_correction(KP2, TC, P_bar,
                              PC_KP2[0], PC_KP2[1]) * SWStoTOT_P
    KP3 = pressure_correction(KP3, TC, P_bar,
                              PC_KP3[0], PC_KP3[1]) * SWStoTOT_P

    # KSi: M95, natively SWS at 1 atm -> PC on SWS -> Total
    KSi = KSi_M95(TK, salinity)
    KSi = pressure_correction(KSi, TC, P_bar,
                              PC_KSi[0], PC_KSi[1]) * SWStoTOT_P

    # Calcite and aragonite solubility (no pH scale dependence)
    KCa = KCa_M83(TK, salinity)
    KAr = KAr_M83(TK, salinity)
    KCa = pressure_correct_solubility(KCa, TC, P_bar, "calcite")
    KAr = pressure_correct_solubility(KAr, TC, P_bar, "aragonite")

    # Fugacity factor
    FugFac = fugacity_factor(TK)

    return {
        "K0": K0, "K1": K1, "K2": K2, "KB": KB, "KW": KW,
        "KSO4": KSO4, "KF": KF,
        "KP1": KP1, "KP2": KP2, "KP3": KP3, "KSi": KSi,
        "KCa": KCa, "KAr": KAr, "FugFac": FugFac,
    }


# ============================================================================
# Speciation and alkalinity components
# ============================================================================

def carbonate_from_TC_H(TC, H, K1, K2):
    """[CO3^2-] from DIC and [H+]."""
    return TC * K1 * K2 / (H**2 + K1 * H + K1 * K2)


def bicarbonate_from_TC_H(TC, H, K1, K2):
    """[HCO3^-] from DIC and [H+]."""
    return TC * K1 * H / (H**2 + K1 * H + K1 * K2)


def co2aq_from_TC_H(TC, H, K1, K2):
    """[CO2(aq)] from DIC and [H+]."""
    return TC * H**2 / (H**2 + K1 * H + K1 * K2)


def total_alkalinity_from_TC_H(TC, H, totals, Ks):
    """Compute total alkalinity from DIC and [H+] (on Total pH scale)."""
    K1 = Ks["K1"]
    K2 = Ks["K2"]
    KB = Ks["KB"]
    KW = Ks["KW"]
    KP1 = Ks["KP1"]
    KP2 = Ks["KP2"]
    KP3 = Ks["KP3"]
    KSi = Ks["KSi"]
    KSO4 = Ks["KSO4"]
    KF = Ks["KF"]

    HCO3 = bicarbonate_from_TC_H(TC, H, K1, K2)
    CO3 = carbonate_from_TC_H(TC, H, K1, K2)
    BAlk = totals["TB"] * KB / (KB + H)
    OH = KW / H

    # Phosphate alkalinity (Dickson definition)
    denom_P = (H**3 + KP1 * H**2 + KP1 * KP2 * H + KP1 * KP2 * KP3)
    PAlk = totals["TPO4"] * (KP1 * KP2 * H + 2.0 * KP1 * KP2 * KP3 - H**3) / denom_P

    SiAlk = totals["TSi"] * KSi / (KSi + H)

    # Convert H_total to H_free for HSO4 and HF
    Hfree = H / (1.0 + totals["TSO4"] / KSO4)
    HSO4 = totals["TSO4"] / (1.0 + KSO4 / Hfree)
    HF = totals["TF"] / (1.0 + KF / Hfree)

    TA = HCO3 + 2.0 * CO3 + BAlk + OH + PAlk + SiAlk - Hfree - HSO4 - HF
    return TA


# ============================================================================
# pH solvers
# ============================================================================

def pH_from_TA_TC(TA, TC, totals, Ks, tol=1e-8, max_iter=100):
    """Solve for pH from total alkalinity and DIC using Newton-Raphson.

    TA, TC in mol/kg-sw. Returns pH on Total scale.
    """
    # Initial guess (based on Munhoven 2013 approach, simplified)
    K1 = Ks["K1"]
    K2 = Ks["K2"]
    KB = Ks["KB"]
    TB = totals["TB"]

    # Approximate carbonate alkalinity
    CAlk_approx = TA - TB * KB / (KB + 1e-8)
    if CAlk_approx <= 0:
        CAlk_approx = TA * 0.9
    if CAlk_approx <= 0:
        CAlk_approx = 1e-6

    # From CAlk = TC*K1*(H + 2*K2) / (H^2 + K1*H + K1*K2)
    # Approximate: pH ~ pK1 + log10(CAlk / (TC - CAlk)) if TC > CAlk
    ratio = CAlk_approx / max(TC - CAlk_approx * 0.5, 1e-10)
    pH = -np.log10(K1) + np.log10(max(ratio, 1e-10))
    pH = max(min(pH, 14.0), 2.0)

    for _ in range(max_iter):
        H = 10.0**(-pH)
        # Compute TA at current pH
        TA_calc = total_alkalinity_from_TC_H(TC, H, totals, Ks)
        residual = TA_calc - TA

        # Numerical derivative dTA/dpH
        dpH = 1e-6
        H2 = 10.0**(-(pH + dpH))
        TA_calc2 = total_alkalinity_from_TC_H(TC, H2, totals, Ks)
        dTA_dpH = (TA_calc2 - TA_calc) / dpH

        if abs(dTA_dpH) < 1e-30:
            break

        delta_pH = -residual / dTA_dpH

        # Limit jump size
        if abs(delta_pH) > 1.0:
            delta_pH = np.sign(delta_pH) * 1.0

        pH = pH + delta_pH

        if abs(delta_pH) < tol:
            break

    return pH


def pH_from_TA_fCO2(TA, fCO2, totals, Ks, tol=1e-8, max_iter=100):
    """Solve for pH from total alkalinity and fCO2."""
    K0 = Ks["K0"]
    K1 = Ks["K1"]
    K2 = Ks["K2"]

    # fCO2 determines [CO2(aq)] = K0 * fCO2
    CO2 = K0 * fCO2

    # pH guess
    pH = 8.0

    for _ in range(max_iter):
        H = 10.0**(-pH)
        # DIC from CO2 and pH: CO2 = DIC * H^2 / (H^2 + K1*H + K1*K2)
        # => DIC = CO2 * (H^2 + K1*H + K1*K2) / H^2
        TC = CO2 * (H**2 + K1 * H + K1 * K2) / H**2
        TA_calc = total_alkalinity_from_TC_H(TC, H, totals, Ks)
        residual = TA_calc - TA

        dpH = 1e-6
        H2 = 10.0**(-(pH + dpH))
        TC2 = CO2 * (H2**2 + K1 * H2 + K1 * K2) / H2**2
        TA_calc2 = total_alkalinity_from_TC_H(TC2, H2, totals, Ks)
        dTA_dpH = (TA_calc2 - TA_calc) / dpH

        if abs(dTA_dpH) < 1e-30:
            break

        delta_pH = -residual / dTA_dpH
        if abs(delta_pH) > 1.0:
            delta_pH = np.sign(delta_pH) * 1.0

        pH = pH + delta_pH
        if abs(delta_pH) < tol:
            break

    return pH


def pH_from_TA_CO3(TA, CO3, totals, Ks, tol=1e-8, max_iter=100):
    """Solve for pH from total alkalinity and carbonate ion."""
    K1 = Ks["K1"]
    K2 = Ks["K2"]

    pH = 8.0

    for _ in range(max_iter):
        H = 10.0**(-pH)
        # CO3 = TC * K1*K2 / (H^2 + K1*H + K1*K2)
        # => TC = CO3 * (H^2 + K1*H + K1*K2) / (K1*K2)
        TC = CO3 * (H**2 + K1 * H + K1 * K2) / (K1 * K2)
        TA_calc = total_alkalinity_from_TC_H(TC, H, totals, Ks)
        residual = TA_calc - TA

        dpH = 1e-6
        H2 = 10.0**(-(pH + dpH))
        TC2 = CO3 * (H2**2 + K1 * H2 + K1 * K2) / (K1 * K2)
        TA_calc2 = total_alkalinity_from_TC_H(TC2, H2, totals, Ks)
        dTA_dpH = (TA_calc2 - TA_calc) / dpH

        if abs(dTA_dpH) < 1e-30:
            break

        delta_pH = -residual / dTA_dpH
        if abs(delta_pH) > 1.0:
            delta_pH = np.sign(delta_pH) * 1.0

        pH = pH + delta_pH
        if abs(delta_pH) < tol:
            break

    return pH


def pH_from_TA_HCO3(TA, HCO3, totals, Ks, tol=1e-8, max_iter=100):
    """Solve for pH from total alkalinity and bicarbonate ion."""
    K1 = Ks["K1"]
    K2 = Ks["K2"]

    pH = 8.0

    for _ in range(max_iter):
        H = 10.0**(-pH)
        # HCO3 = TC * K1*H / (H^2 + K1*H + K1*K2)
        # => TC = HCO3 * (H^2 + K1*H + K1*K2) / (K1*H)
        TC = HCO3 * (H**2 + K1 * H + K1 * K2) / (K1 * H)
        TA_calc = total_alkalinity_from_TC_H(TC, H, totals, Ks)
        residual = TA_calc - TA

        dpH = 1e-6
        H2 = 10.0**(-(pH + dpH))
        TC2 = HCO3 * (H2**2 + K1 * H2 + K1 * K2) / (K1 * H2)
        TA_calc2 = total_alkalinity_from_TC_H(TC2, H2, totals, Ks)
        dTA_dpH = (TA_calc2 - TA_calc) / dpH

        if abs(dTA_dpH) < 1e-30:
            break

        delta_pH = -residual / dTA_dpH
        if abs(delta_pH) > 1.0:
            delta_pH = np.sign(delta_pH) * 1.0

        pH = pH + delta_pH
        if abs(delta_pH) < tol:
            break

    return pH


def TC_from_TA_pH(TA, pH, totals, Ks):
    """Calculate DIC from TA and pH algebraically."""
    H = 10.0**(-pH)
    K1 = Ks["K1"]
    K2 = Ks["K2"]
    # TA at TC=0
    TA0 = total_alkalinity_from_TC_H(0.0, H, totals, Ks)
    CAlk = TA - TA0
    # CAlk = TC * K1 * (H + 2*K2) / (H^2 + K1*H + K1*K2)
    TC = CAlk * (H**2 + K1 * H + K1 * K2) / (K1 * (H + 2.0 * K2))
    return TC


def fCO2_from_TC_pH(TC, pH, Ks):
    """Calculate fCO2 from DIC and pH."""
    H = 10.0**(-pH)
    K0 = Ks["K0"]
    K1 = Ks["K1"]
    K2 = Ks["K2"]
    return TC * H**2 / (H**2 + K1 * H + K1 * K2) / K0


def pH_from_TC_fCO2(TC, fCO2, Ks):
    """Calculate pH from DIC and fCO2 via quadratic."""
    K0 = Ks["K0"]
    K1 = Ks["K1"]
    K2 = Ks["K2"]
    RR = K0 * fCO2 / TC
    if RR >= 1.0:
        return np.nan
    Discr = (K1 * RR)**2 + 4.0 * (1.0 - RR) * K1 * K2 * RR
    if Discr <= 0:
        return np.nan
    H = 0.5 * (K1 * RR + np.sqrt(Discr)) / (1.0 - RR)
    return -np.log10(H)


def pH_from_TC_CO3(TC, CO3, Ks):
    """Calculate pH from DIC and carbonate ion via quadratic."""
    K1 = Ks["K1"]
    K2 = Ks["K2"]
    # CO3 = TC * K1*K2 / (H^2 + K1*H + K1*K2)
    # => CO3*H^2 + CO3*K1*H + CO3*K1*K2 = TC*K1*K2
    # => CO3*H^2 + CO3*K1*H + (CO3 - TC)*K1*K2 = 0
    a = CO3
    b = CO3 * K1
    c = (CO3 - TC) * K1 * K2
    if CO3 >= TC:
        return np.nan
    RR = 1.0 - TC / CO3
    Discr = K1**2 - 4.0 * K1 * K2 * RR
    if Discr <= 0:
        return np.nan
    H = (-K1 + np.sqrt(Discr)) / 2.0
    if H <= 0:
        return np.nan
    return -np.log10(H)


def pH_from_TC_HCO3(TC, HCO3, Ks):
    """Calculate pH from DIC and bicarbonate ion via quadratic."""
    K1 = Ks["K1"]
    K2 = Ks["K2"]
    # HCO3 = TC * K1*H / (H^2 + K1*H + K1*K2)
    # => HCO3*H^2 + HCO3*K1*H + HCO3*K1*K2 = TC*K1*H
    # => HCO3*H^2 + (HCO3 - TC)*K1*H + HCO3*K1*K2 = 0
    # => (HCO3/K1)*H^2 + (HCO3 - TC)*H + HCO3*K2 = 0
    a = HCO3 / K1
    b = HCO3 - TC
    c = HCO3 * K2
    Discr = b**2 - 4.0 * a * c
    if HCO3 >= TC or Discr <= 0:
        return np.nan
    H = (-b - np.sqrt(Discr)) / (2.0 * a)  # negative root
    if H <= 0:
        return np.nan
    return -np.log10(H)


def TC_from_pH_fCO2(pH, fCO2, Ks):
    """DIC from pH and fCO2."""
    H = 10.0**(-pH)
    K0 = Ks["K0"]
    K1 = Ks["K1"]
    K2 = Ks["K2"]
    return K0 * fCO2 * (H**2 + K1 * H + K1 * K2) / H**2


def TC_from_pH_CO3(pH, CO3, Ks):
    """DIC from pH and carbonate ion."""
    H = 10.0**(-pH)
    K1 = Ks["K1"]
    K2 = Ks["K2"]
    return CO3 * (H**2 / (K1 * K2) + H / K2 + 1.0)


def TC_from_pH_HCO3(pH, HCO3, Ks):
    """DIC from pH and bicarbonate ion."""
    H = 10.0**(-pH)
    K1 = Ks["K1"]
    K2 = Ks["K2"]
    return HCO3 * (1.0 + H / K1 + K2 / H)


def pH_from_fCO2_CO3(fCO2, CO3, Ks):
    """pH from fCO2 and carbonate ion."""
    K0 = Ks["K0"]
    K1 = Ks["K1"]
    K2 = Ks["K2"]
    H = np.sqrt(K0 * K1 * K2 * fCO2 / CO3)
    return -np.log10(H)


def pH_from_fCO2_HCO3(fCO2, HCO3, Ks):
    """pH from fCO2 and bicarbonate ion."""
    K0 = Ks["K0"]
    K1 = Ks["K1"]
    H = K0 * K1 * fCO2 / HCO3
    return -np.log10(H)


def pH_from_CO3_HCO3(CO3, HCO3, Ks):
    """pH from carbonate and bicarbonate ions."""
    K2 = Ks["K2"]
    H = K2 * HCO3 / CO3
    return -np.log10(H)


def CO3_from_fCO2_HCO3(fCO2, HCO3, Ks):
    """Carbonate ion from fCO2 and bicarbonate ion."""
    K0 = Ks["K0"]
    K1 = Ks["K1"]
    K2 = Ks["K2"]
    return HCO3**2 * K2 / (K0 * fCO2 * K1)


def fCO2_from_CO3_HCO3(CO3, HCO3, Ks):
    """fCO2 from carbonate and bicarbonate ions."""
    K0 = Ks["K0"]
    K1 = Ks["K1"]
    K2 = Ks["K2"]
    return HCO3**2 * K2 / (CO3 * K1 * K0)


# ============================================================================
# Revelle factor (finite differences)
# ============================================================================

def revelle_factor(TA, TC, totals, Ks):
    """Compute Revelle factor via finite differences.

    R = (DIC/fCO2) * (dfCO2/dDIC) at constant TA.
    """
    delta = TC * 1e-6
    if delta < 1e-12:
        delta = 1e-12

    pH0 = pH_from_TA_TC(TA, TC, totals, Ks)
    fCO2_0 = fCO2_from_TC_pH(TC, pH0, Ks)

    pH1 = pH_from_TA_TC(TA, TC + delta, totals, Ks)
    fCO2_1 = fCO2_from_TC_pH(TC + delta, pH1, Ks)

    dfCO2_dTC = (fCO2_1 - fCO2_0) / delta
    R = (TC / fCO2_0) * dfCO2_dTC
    return R


# ============================================================================
# Main solve function
# ============================================================================

def solve(par1, par2, par1_type, par2_type, temperature, salinity, pressure,
          total_silicate=0.0, total_phosphate=0.0):
    """Solve the marine carbonate system from any pair of core variables.

    Parameter types:
        1: Total Alkalinity (umol/kg-sw)
        2: Dissolved Inorganic Carbon (umol/kg-sw)
        3: pH (Total scale)
        4: fCO2 (uatm)
        5: Carbonate ion [CO3^2-] (umol/kg-sw)
        6: Bicarbonate ion [HCO3^-] (umol/kg-sw)

    Returns dict with keys:
        TA, DIC, pH, fCO2, pCO2, CO3, HCO3, CO2aq, OmegaCa, OmegaAr, Revelle
    """
    # Compute totals and constants
    totals = salinity_totals(salinity, total_silicate, total_phosphate)
    Ks = assemble_constants(temperature, salinity, pressure, totals)

    # Convert inputs to internal units (mol/kg-sw, atm)
    par_values = {par1_type: par1, par2_type: par2}

    # Extract given values, converting units
    TA = par_values.get(1, None)
    TC = par_values.get(2, None)
    pH = par_values.get(3, None)
    fCO2 = par_values.get(4, None)
    CO3 = par_values.get(5, None)
    HCO3 = par_values.get(6, None)

    # Convert umol/kg to mol/kg, uatm to atm
    if TA is not None:
        TA = TA * 1e-6
    if TC is not None:
        TC = TC * 1e-6
    if fCO2 is not None:
        fCO2 = fCO2 * 1e-6  # uatm to atm
    if CO3 is not None:
        CO3 = CO3 * 1e-6
    if HCO3 is not None:
        HCO3 = HCO3 * 1e-6

    # Normalize pair order (lower type first)
    pt1 = min(par1_type, par2_type)
    pt2 = max(par1_type, par2_type)
    Icase = 100 * pt1 + pt2

    # Solve based on input pair
    if Icase == 102:  # TA + DIC
        pH = pH_from_TA_TC(TA, TC, totals, Ks)
        H = 10.0**(-pH)
        fCO2 = fCO2_from_TC_pH(TC, pH, Ks)
        CO3 = carbonate_from_TC_H(TC, H, Ks["K1"], Ks["K2"])
        HCO3 = bicarbonate_from_TC_H(TC, H, Ks["K1"], Ks["K2"])

    elif Icase == 103:  # TA + pH
        TC = TC_from_TA_pH(TA, pH, totals, Ks)
        H = 10.0**(-pH)
        fCO2 = fCO2_from_TC_pH(TC, pH, Ks)
        CO3 = carbonate_from_TC_H(TC, H, Ks["K1"], Ks["K2"])
        HCO3 = bicarbonate_from_TC_H(TC, H, Ks["K1"], Ks["K2"])

    elif Icase == 104:  # TA + fCO2
        pH = pH_from_TA_fCO2(TA, fCO2, totals, Ks)
        H = 10.0**(-pH)
        TC = TC_from_pH_fCO2(pH, fCO2, Ks)
        CO3 = carbonate_from_TC_H(TC, H, Ks["K1"], Ks["K2"])
        HCO3 = bicarbonate_from_TC_H(TC, H, Ks["K1"], Ks["K2"])

    elif Icase == 105:  # TA + CO3
        pH = pH_from_TA_CO3(TA, CO3, totals, Ks)
        H = 10.0**(-pH)
        TC = TC_from_pH_CO3(pH, CO3, Ks)
        fCO2 = fCO2_from_TC_pH(TC, pH, Ks)
        HCO3 = bicarbonate_from_TC_H(TC, H, Ks["K1"], Ks["K2"])

    elif Icase == 106:  # TA + HCO3
        pH = pH_from_TA_HCO3(TA, HCO3, totals, Ks)
        H = 10.0**(-pH)
        TC = TC_from_pH_HCO3(pH, HCO3, Ks)
        fCO2 = fCO2_from_TC_pH(TC, pH, Ks)
        CO3 = carbonate_from_TC_H(TC, H, Ks["K1"], Ks["K2"])

    elif Icase == 203:  # DIC + pH
        H = 10.0**(-pH)
        TA = total_alkalinity_from_TC_H(TC, H, totals, Ks)
        fCO2 = fCO2_from_TC_pH(TC, pH, Ks)
        CO3 = carbonate_from_TC_H(TC, H, Ks["K1"], Ks["K2"])
        HCO3 = bicarbonate_from_TC_H(TC, H, Ks["K1"], Ks["K2"])

    elif Icase == 204:  # DIC + fCO2
        pH = pH_from_TC_fCO2(TC, fCO2, Ks)
        H = 10.0**(-pH)
        TA = total_alkalinity_from_TC_H(TC, H, totals, Ks)
        CO3 = carbonate_from_TC_H(TC, H, Ks["K1"], Ks["K2"])
        HCO3 = bicarbonate_from_TC_H(TC, H, Ks["K1"], Ks["K2"])

    elif Icase == 205:  # DIC + CO3
        pH = pH_from_TC_CO3(TC, CO3, Ks)
        H = 10.0**(-pH)
        TA = total_alkalinity_from_TC_H(TC, H, totals, Ks)
        fCO2 = fCO2_from_TC_pH(TC, pH, Ks)
        HCO3 = bicarbonate_from_TC_H(TC, H, Ks["K1"], Ks["K2"])

    elif Icase == 206:  # DIC + HCO3
        pH = pH_from_TC_HCO3(TC, HCO3, Ks)
        H = 10.0**(-pH)
        TA = total_alkalinity_from_TC_H(TC, H, totals, Ks)
        fCO2 = fCO2_from_TC_pH(TC, pH, Ks)
        CO3 = carbonate_from_TC_H(TC, H, Ks["K1"], Ks["K2"])

    elif Icase == 304:  # pH + fCO2
        TC = TC_from_pH_fCO2(pH, fCO2, Ks)
        H = 10.0**(-pH)
        TA = total_alkalinity_from_TC_H(TC, H, totals, Ks)
        CO3 = carbonate_from_TC_H(TC, H, Ks["K1"], Ks["K2"])
        HCO3 = bicarbonate_from_TC_H(TC, H, Ks["K1"], Ks["K2"])

    elif Icase == 305:  # pH + CO3
        TC = TC_from_pH_CO3(pH, CO3, Ks)
        H = 10.0**(-pH)
        TA = total_alkalinity_from_TC_H(TC, H, totals, Ks)
        fCO2 = fCO2_from_TC_pH(TC, pH, Ks)
        HCO3 = bicarbonate_from_TC_H(TC, H, Ks["K1"], Ks["K2"])

    elif Icase == 306:  # pH + HCO3
        TC = TC_from_pH_HCO3(pH, HCO3, Ks)
        H = 10.0**(-pH)
        TA = total_alkalinity_from_TC_H(TC, H, totals, Ks)
        fCO2 = fCO2_from_TC_pH(TC, pH, Ks)
        CO3 = carbonate_from_TC_H(TC, H, Ks["K1"], Ks["K2"])

    elif Icase == 405:  # fCO2 + CO3
        pH = pH_from_fCO2_CO3(fCO2, CO3, Ks)
        H = 10.0**(-pH)
        TC = TC_from_pH_fCO2(pH, fCO2, Ks)
        TA = total_alkalinity_from_TC_H(TC, H, totals, Ks)
        HCO3 = bicarbonate_from_TC_H(TC, H, Ks["K1"], Ks["K2"])

    elif Icase == 406:  # fCO2 + HCO3
        CO3 = CO3_from_fCO2_HCO3(fCO2, HCO3, Ks)
        pH = pH_from_fCO2_CO3(fCO2, CO3, Ks)
        H = 10.0**(-pH)
        TC = TC_from_pH_fCO2(pH, fCO2, Ks)
        TA = total_alkalinity_from_TC_H(TC, H, totals, Ks)

    elif Icase == 506:  # CO3 + HCO3
        pH = pH_from_CO3_HCO3(CO3, HCO3, Ks)
        H = 10.0**(-pH)
        fCO2 = fCO2_from_CO3_HCO3(CO3, HCO3, Ks)
        TC = TC_from_pH_CO3(pH, CO3, Ks)
        TA = total_alkalinity_from_TC_H(TC, H, totals, Ks)

    else:
        raise ValueError(f"Invalid input pair combination: types {par1_type} and {par2_type}")

    # Compute derived quantities
    H = 10.0**(-pH)
    CO2aq = co2aq_from_TC_H(TC, H, Ks["K1"], Ks["K2"])
    pCO2 = fCO2 / Ks["FugFac"]

    # Saturation states
    OmegaCa = CO3 * totals["TCa"] / Ks["KCa"]
    OmegaAr = CO3 * totals["TCa"] / Ks["KAr"]

    # Revelle factor
    Rev = revelle_factor(TA, TC, totals, Ks)

    # Convert back to umol/kg and uatm
    return {
        "TA": TA * 1e6,
        "DIC": TC * 1e6,
        "pH": pH,
        "fCO2": fCO2 * 1e6,
        "pCO2": pCO2 * 1e6,
        "CO3": CO3 * 1e6,
        "HCO3": HCO3 * 1e6,
        "CO2aq": CO2aq * 1e6,
        "OmegaCa": OmegaCa,
        "OmegaAr": OmegaAr,
        "Revelle": Rev,
    }
