"""Standalone marine carbonate system solver.

Implements the CO2SYS calculation pipeline with:
- Lueker et al. (2000) K1/K2 on Total pH scale
- Weiss (1974) K0
- Dickson (1990) KB on Total scale
- Millero (1995) KW on SWS scale
- Dickson (1990a) KSO4 on Free scale
- Dickson & Riley (1979) KF on Free scale
- Yao & Millero (1995) KP1/KP2/KP3/KSi on SWS scale
- Lee et al. (2010) total borate
- Millero (1995) pressure corrections
- Weiss (1974) fugacity factor
"""

import math

# Gas constant in cm3.bar/(mol.K) - CODATA 2018 exact value (PyCO2SYS default)
RGAS = 83.14462618


# ============================================================================
# Seawater composition from salinity
# ============================================================================

def ionic_strength(S):
    """DOE 1994 ionic strength from practical salinity."""
    if S < 1e-16:
        return 0.0
    return 19.924 * S / (1000.0 - 1.005 * S)


def total_borate(S):
    """Lee et al. 2010 (LKB10). Returns mol/kg-sw."""
    return 0.0004326 * S / 35.0


def total_sulfate(S):
    """Morris & Riley 1966. Returns mol/kg-sw."""
    return (0.14 / 96.062) * (S / 1.80655)


def total_fluoride(S):
    """Riley 1965. Returns mol/kg-sw."""
    return (0.000067 / 18.998) * (S / 1.80655)


# ============================================================================
# Equilibrium constants at 1 atm
# ============================================================================

def k0_W74(TK, S):
    """K0 CO2 solubility: Weiss 1974. mol/kg-sw/atm. Scale-independent."""
    TK100 = TK / 100.0
    lnK0 = (-60.2409 + 93.4517 / TK100 + 23.3585 * math.log(TK100)
             + S * (0.023517 - 0.023656 * TK100 + 0.0047036 * TK100 ** 2))
    return math.exp(lnK0)


def k1k2_LDK00(TK, S):
    """K1, K2 carbonic acid: Lueker, Dickson & Keeling 2000. Total scale."""
    pK1 = (3633.86 / TK - 61.2172 + 9.6777 * math.log(TK)
            - 0.011555 * S + 0.0001152 * S ** 2)
    pK2 = (471.78 / TK + 25.929 - 3.16967 * math.log(TK)
            - 0.01781 * S + 0.0001122 * S ** 2)
    return 10.0 ** (-pK1), 10.0 ** (-pK2)


def kb_D90(TK, S):
    """KB boric acid: Dickson 1990. Total scale."""
    sqrS = math.sqrt(S) if S > 0 else 0.0
    lnKBtop = (-8966.9 - 2890.53 * sqrS - 77.942 * S
                + 1.728 * sqrS * S - 0.0996 * S ** 2)
    lnKB = (lnKBtop / TK + 148.0248 + 137.1942 * sqrS + 1.62142 * S
             + (-24.4344 - 25.085 * sqrS - 0.2474 * S) * math.log(TK)
             + 0.053105 * sqrS * TK)
    return math.exp(lnKB)


def kw_M95(TK, S):
    """KW water: Millero 1995. SWS scale."""
    sqrS = math.sqrt(S) if S > 0 else 0.0
    return math.exp(
        148.9802 - 13847.26 / TK - 23.6521 * math.log(TK)
        + (-5.977 + 118.67 / TK + 1.0495 * math.log(TK)) * sqrS
        - 0.01615 * S
    )


def kso4_D90a(TK, S):
    """KSO4 bisulfate: Dickson 1990a. Free scale."""
    IonS = ionic_strength(S)
    logTK = math.log(TK)
    sqrIonS = math.sqrt(IonS) if IonS > 0 else 0.0
    lnKSO4 = (
        -4276.1 / TK + 141.328 - 23.093 * logTK
        + (-13856.0 / TK + 324.57 - 47.986 * logTK) * sqrIonS
        + (35474.0 / TK - 771.54 + 114.723 * logTK) * IonS
        + (-2698.0 / TK) * sqrIonS * IonS
        + (1776.0 / TK) * IonS ** 2
    )
    return math.exp(lnKSO4) * (1.0 - 0.001005 * S)


def kf_DR79(TK, S):
    """KF hydrogen fluoride: Dickson & Riley 1979. Free scale."""
    IonS = ionic_strength(S)
    sqrIonS = math.sqrt(IonS) if IonS > 0 else 0.0
    lnKF = 1590.2 / TK - 12.641 + 1.525 * sqrIonS
    return math.exp(lnKF) * (1.0 - 0.001005 * S)


def kp_YM95(TK, S):
    """KP1, KP2, KP3 phosphoric acid: Yao & Millero 1995. SWS scale."""
    sqrS = math.sqrt(S) if S > 0 else 0.0
    logTK = math.log(TK)
    lnKP1 = (-4576.752 / TK + 115.54 - 18.453 * logTK
              + (-106.736 / TK + 0.69171) * sqrS
              + (-0.65643 / TK - 0.01844) * S)
    lnKP2 = (-8814.715 / TK + 172.1033 - 27.927 * logTK
              + (-160.34 / TK + 1.3566) * sqrS
              + (0.37335 / TK - 0.05778) * S)
    lnKP3 = (-3070.75 / TK - 18.126
              + (17.27039 / TK + 2.81197) * sqrS
              + (-44.99486 / TK - 0.09984) * S)
    return math.exp(lnKP1), math.exp(lnKP2), math.exp(lnKP3)


def ksi_YM95(TK, S):
    """KSi silicic acid: Yao & Millero 1995. SWS scale."""
    IonS = ionic_strength(S)
    sqrIonS = math.sqrt(IonS) if IonS > 0 else 0.0
    logTK = math.log(TK)
    lnKSi = (-8904.2 / TK + 117.4 - 19.334 * logTK
              + (-458.79 / TK + 3.5913) * sqrIonS
              + (188.74 / TK - 1.5998) * IonS
              + (-12.1652 / TK + 0.07871) * IonS ** 2)
    return math.exp(lnKSi) * (1.0 - 0.001005 * S)


# ============================================================================
# Pressure corrections (Millero 1995)
# ============================================================================

def _pressure_correction(TK, Pbar, a0, a1, a2, b0, b1, b2=0.0):
    """Compute pressure correction factor for an equilibrium constant.

    ln(Kp/K0) = (-deltaV + 0.5*Kappa*Pbar) * Pbar / (R*TK)
    where deltaV = a0 + a1*TC + a2*TC^2
          Kappa = b0 + b1*TC + b2*TC^2
    """
    if Pbar <= 0:
        return 1.0
    TC = TK - 273.15
    deltaV = a0 + a1 * TC + a2 * TC ** 2
    Kappa = b0 + b1 * TC + b2 * TC ** 2
    lnKfac = (-deltaV + 0.5 * Kappa * Pbar) * Pbar / (RGAS * TK)
    return math.exp(lnKfac)


def pcx_K1(TK, Pbar):
    return _pressure_correction(TK, Pbar, -25.5, 0.1271, 0.0, -3.08e-3, 0.0877e-3)


def pcx_K2(TK, Pbar):
    return _pressure_correction(TK, Pbar, -15.82, -0.0219, 0.0, 1.13e-3, -0.1475e-3)


def pcx_KB(TK, Pbar):
    return _pressure_correction(TK, Pbar, -29.48, 0.1622, -2.608e-3, -2.84e-3, 0.0)


def pcx_KW(TK, Pbar):
    return _pressure_correction(TK, Pbar, -20.02, 0.1119, -1.409e-3, -5.13e-3, 0.0794e-3)


def pcx_KSO4(TK, Pbar):
    return _pressure_correction(TK, Pbar, -18.03, 0.0466, 0.000316, -4.53e-3, 0.09e-3)


def pcx_KF(TK, Pbar):
    return _pressure_correction(TK, Pbar, -9.78, -0.0090, -0.000942, -3.91e-3, 0.054e-3)


def pcx_KP1(TK, Pbar):
    return _pressure_correction(TK, Pbar, -14.51, 0.1211, -0.000321, -2.67e-3, 0.0427e-3)


def pcx_KP2(TK, Pbar):
    return _pressure_correction(TK, Pbar, -23.12, 0.1758, -2.647e-3, -5.15e-3, 0.09e-3)


def pcx_KP3(TK, Pbar):
    return _pressure_correction(TK, Pbar, -26.57, 0.2020, -3.042e-3, -4.08e-3, 0.0714e-3)


def pcx_KSi(TK, Pbar):
    return _pressure_correction(TK, Pbar, -29.48, 0.1622, -2.608e-3, -2.84e-3, 0.0)


# ============================================================================
# Fugacity factor
# ============================================================================

def fugacity_factor(TK):
    """Weiss 1974 fugacity factor at 1 atm total pressure.
    FugFac = exp((B + 2*delta) * P_bar / (R * TK))
    Using P_bar = 1.01325 (1 atm in bar) and R = RGAS.
    """
    B = -1636.75 + 12.0408 * TK - 0.0327957 * TK ** 2 + 3.16528e-5 * TK ** 3
    delta = 57.7 - 0.118 * TK
    return math.exp((B + 2.0 * delta) * 1.01325 / (RGAS * TK))


# ============================================================================
# pH scale conversions
# ============================================================================

def sws_to_total(TS, TF, KSO4, KF):
    """Conversion factor from SWS to Total pH scale.
    H_total = H_sws * SWStoTOT
    K_total = K_sws * SWStoTOT  (for first-order-in-H constants)
    """
    return (1.0 + TS / KSO4) / (1.0 + TS / KSO4 + TF / KF)


def total_to_free(TS, KSO4):
    """Conversion factor from Total to Free pH scale.
    H_free = H_total * TOTtoFREE
    """
    return 1.0 / (1.0 + TS / KSO4)


# ============================================================================
# Assemble equilibrium constants
# ============================================================================

def assemble_constants(TK, S, Pbar, TS, TF):
    """Compute all equilibrium constants on Total pH scale with pressure corrections."""
    # Step 1: KSO4, KF at 1 atm on Free scale
    KSO4_P0 = kso4_D90a(TK, S)
    KF_P0 = kf_DR79(TK, S)

    # Step 2: Pressure-correct KSO4, KF (stay on Free scale)
    KSO4_P = KSO4_P0 * pcx_KSO4(TK, Pbar)
    KF_P = KF_P0 * pcx_KF(TK, Pbar)

    # Step 3: pH scale conversion factors
    # At P=0 (for converting K's evaluated at P=0)
    SWStoTOT_P0 = sws_to_total(TS, TF, KSO4_P0, KF_P0)
    # At pressure (for final conversion to Total scale)
    SWStoTOT_P = sws_to_total(TS, TF, KSO4_P, KF_P)

    # Step 4: K1, K2 at 1 atm (Total scale)
    K1_P0, K2_P0 = k1k2_LDK00(TK, S)
    # Convert Total -> SWS at P=0, apply pcx, convert SWS -> Total at P
    K1 = (K1_P0 / SWStoTOT_P0) * pcx_K1(TK, Pbar) * SWStoTOT_P
    K2 = (K2_P0 / SWStoTOT_P0) * pcx_K2(TK, Pbar) * SWStoTOT_P

    # Step 5: KB at 1 atm (Total scale)
    KB_P0 = kb_D90(TK, S)
    KB = (KB_P0 / SWStoTOT_P0) * pcx_KB(TK, Pbar) * SWStoTOT_P

    # Step 6: KW at 1 atm (SWS scale)
    KW_P0 = kw_M95(TK, S)
    KW = KW_P0 * pcx_KW(TK, Pbar) * SWStoTOT_P

    # Step 7: KP1, KP2, KP3 at 1 atm (SWS scale)
    KP1_P0, KP2_P0, KP3_P0 = kp_YM95(TK, S)
    KP1 = KP1_P0 * pcx_KP1(TK, Pbar) * SWStoTOT_P
    KP2 = KP2_P0 * pcx_KP2(TK, Pbar) * SWStoTOT_P
    KP3 = KP3_P0 * pcx_KP3(TK, Pbar) * SWStoTOT_P

    # Step 8: KSi at 1 atm (SWS scale)
    KSi_P0 = ksi_YM95(TK, S)
    KSi = KSi_P0 * pcx_KSi(TK, Pbar) * SWStoTOT_P

    # Step 9: K0 (no pressure correction)
    K0 = k0_W74(TK, S)

    # Step 10: Fugacity factor
    FugFac = fugacity_factor(TK)

    # Total-to-Free conversion at pressure (for alkalinity equation)
    TOTtoFREE = total_to_free(TS, KSO4_P)

    return {
        "K0": K0, "K1": K1, "K2": K2, "KB": KB, "KW": KW,
        "KSO4": KSO4_P, "KF": KF_P,
        "KP1": KP1, "KP2": KP2, "KP3": KP3, "KSi": KSi,
        "FugFac": FugFac, "TOTtoFREE": TOTtoFREE,
    }


# ============================================================================
# Speciation from DIC and H+ (on Total scale)
# ============================================================================

def carbonate_from_dic_h(DIC, H, K1, K2):
    """CO3^2- from DIC and [H+]."""
    denom = H ** 2 + K1 * H + K1 * K2
    return DIC * K1 * K2 / denom


def bicarbonate_from_dic_h(DIC, H, K1, K2):
    """HCO3- from DIC and [H+]."""
    denom = H ** 2 + K1 * H + K1 * K2
    return DIC * K1 * H / denom


def co2aq_from_dic_h(DIC, H, K1, K2):
    """CO2(aq) from DIC and [H+]."""
    denom = H ** 2 + K1 * H + K1 * K2
    return DIC * H ** 2 / denom


# ============================================================================
# Total alkalinity from DIC, H+, and auxiliary species
# ============================================================================

def compute_ta(H, DIC, Ks, TB, TS, TF, TSi, TPO4):
    """Compute total alkalinity from [H+] (Total scale) and DIC."""
    K1, K2 = Ks["K1"], Ks["K2"]
    KB, KW = Ks["KB"], Ks["KW"]
    KP1, KP2, KP3 = Ks["KP1"], Ks["KP2"], Ks["KP3"]
    KSi = Ks["KSi"]
    KSO4, KF = Ks["KSO4"], Ks["KF"]
    TOTtoFREE = Ks["TOTtoFREE"]

    # Carbonate alkalinity
    denom_c = H ** 2 + K1 * H + K1 * K2
    HCO3 = DIC * K1 * H / denom_c
    CO3 = DIC * K1 * K2 / denom_c

    # Borate alkalinity
    BAlk = TB * KB / (KB + H)

    # Water
    OH = KW / H

    # Phosphate alkalinity (Dickson definition)
    denom_p = H ** 3 + KP1 * H ** 2 + KP1 * KP2 * H + KP1 * KP2 * KP3
    PAlk = TPO4 * (KP1 * KP2 * H + 2.0 * KP1 * KP2 * KP3 - H ** 3) / denom_p

    # Silicate alkalinity
    SiAlk = TSi * KSi / (KSi + H)

    # Free H+
    Hfree = H * TOTtoFREE

    # HSO4 and HF (KSO4, KF on Free scale)
    HSO4 = TS / (1.0 + KSO4 / Hfree)
    HF = TF / (1.0 + KF / Hfree)

    TA = HCO3 + 2.0 * CO3 + BAlk + OH + PAlk + SiAlk - Hfree - HSO4 - HF
    return TA


# ============================================================================
# Newton-Raphson pH solvers
# ============================================================================

def _ph_from_ta_generic(TA, compute_ta_func, pH_init=8.0, tol=1e-10, max_iter=200):
    """Generic Newton-Raphson solver for pH from TA.

    compute_ta_func(H) -> TA_calculated
    """
    pH = pH_init
    for _ in range(max_iter):
        H = 10.0 ** (-pH)
        ta_calc = compute_ta_func(H)
        residual = ta_calc - TA

        # Numerical derivative
        dpH = 1e-8
        H2 = 10.0 ** (-(pH + dpH))
        ta_calc2 = compute_ta_func(H2)
        slope = (ta_calc2 - ta_calc) / dpH

        if abs(slope) < 1e-30:
            break

        delta = -residual / slope

        # Limit step size
        if abs(delta) > 1.0:
            delta = math.copysign(1.0, delta)

        pH += delta

        if abs(delta) < tol:
            break

    return pH


def ph_from_ta_dic(TA, DIC, Ks, TB, TS, TF, TSi, TPO4):
    """Solve pH from TA and DIC using Newton-Raphson."""
    def ta_func(H):
        return compute_ta(H, DIC, Ks, TB, TS, TF, TSi, TPO4)
    return _ph_from_ta_generic(TA, ta_func)


def ph_from_ta_fco2(TA, fCO2, Ks, TB, TS, TF, TSi, TPO4):
    """Solve pH from TA and fCO2 using Newton-Raphson."""
    K0, K1, K2 = Ks["K0"], Ks["K1"], Ks["K2"]

    def ta_func(H):
        # DIC from fCO2 and H
        CO2aq = K0 * fCO2
        DIC = CO2aq * (H ** 2 + K1 * H + K1 * K2) / (H ** 2)
        return compute_ta(H, DIC, Ks, TB, TS, TF, TSi, TPO4)

    return _ph_from_ta_generic(TA, ta_func)


def ph_from_ta_carb(TA, CO3, Ks, TB, TS, TF, TSi, TPO4):
    """Solve pH from TA and CO3 using Newton-Raphson."""
    K1, K2 = Ks["K1"], Ks["K2"]

    def ta_func(H):
        # DIC from CO3 and H
        DIC = CO3 * (H ** 2 + K1 * H + K1 * K2) / (K1 * K2)
        return compute_ta(H, DIC, Ks, TB, TS, TF, TSi, TPO4)

    return _ph_from_ta_generic(TA, ta_func)


def ph_from_ta_hco3(TA, HCO3, Ks, TB, TS, TF, TSi, TPO4):
    """Solve pH from TA and HCO3 using Newton-Raphson."""
    K1, K2 = Ks["K1"], Ks["K2"]

    def ta_func(H):
        # DIC from HCO3 and H
        DIC = HCO3 * (H ** 2 + K1 * H + K1 * K2) / (K1 * H)
        return compute_ta(H, DIC, Ks, TB, TS, TF, TSi, TPO4)

    return _ph_from_ta_generic(TA, ta_func)


# ============================================================================
# Direct solvers for specific pair types
# ============================================================================

def dic_from_ta_ph(TA, pH, Ks, TB, TS, TF, TSi, TPO4):
    """DIC from TA and pH (direct calculation)."""
    H = 10.0 ** (-pH)
    # TA at DIC=0
    ta_dic0 = compute_ta(H, 0.0, Ks, TB, TS, TF, TSi, TPO4)
    CAlk = TA - ta_dic0
    K1, K2 = Ks["K1"], Ks["K2"]
    DIC = CAlk * (H ** 2 + K1 * H + K1 * K2) / (K1 * (H + 2.0 * K2))
    return DIC


def ph_from_dic_fco2(DIC, fCO2, K0, K1, K2):
    """pH from DIC and fCO2 (quadratic in H)."""
    RR = K0 * fCO2 / DIC
    if RR >= 1.0:
        return float("nan")
    Discr = (K1 * RR) ** 2 + 4.0 * (1.0 - RR) * K1 * K2 * RR
    if Discr <= 0:
        return float("nan")
    H = 0.5 * (K1 * RR + math.sqrt(Discr)) / (1.0 - RR)
    return -math.log10(H)


def dic_from_ph_fco2(pH, fCO2, K0, K1, K2):
    """DIC from pH and fCO2."""
    H = 10.0 ** (-pH)
    return K0 * fCO2 * (H ** 2 + K1 * H + K1 * K2) / (H ** 2)


def ph_from_dic_carb(DIC, CO3, K1, K2):
    """pH from DIC and CO3 (quadratic in H)."""
    RR = 1.0 - DIC / CO3
    Discr = K1 ** 2 - 4.0 * K1 * K2 * RR
    if Discr <= 0:
        return float("nan")
    H = (-K1 + math.sqrt(Discr)) / 2.0
    if H <= 0:
        return float("nan")
    return -math.log10(H)


def ph_from_dic_hco3(DIC, HCO3, K1, K2):
    """pH from DIC and HCO3 (quadratic in H)."""
    a = HCO3 / K1
    b = HCO3 - DIC
    c = HCO3 * K2
    Discr = b ** 2 - 4.0 * a * c
    if Discr <= 0:
        return float("nan")
    # Take the negative root (standard seawater)
    H = (-b - math.sqrt(Discr)) / (2.0 * a)
    if H <= 0:
        return float("nan")
    return -math.log10(H)


def dic_from_ph_hco3(pH, HCO3, K1, K2):
    """DIC from pH and HCO3."""
    H = 10.0 ** (-pH)
    return HCO3 * (1.0 + H / K1 + K2 / H)


def dic_from_ph_carb(pH, CO3, K1, K2):
    """DIC from pH and CO3."""
    H = 10.0 ** (-pH)
    return CO3 * (1.0 + H / K2 + H ** 2 / (K1 * K2))


def ph_from_fco2_carb(fCO2, CO3, K0, K1, K2):
    """pH from fCO2 and CO3."""
    H = math.sqrt(K0 * K1 * K2 * fCO2 / CO3)
    return -math.log10(H)


def carb_from_fco2_hco3(fCO2, HCO3, K0, K1, K2):
    """CO3 from fCO2 and HCO3."""
    return HCO3 ** 2 * K2 / (K0 * fCO2 * K1)


def fco2_from_carb_hco3(CO3, HCO3, K0, K1, K2):
    """fCO2 from CO3 and HCO3."""
    return HCO3 ** 2 * K2 / (CO3 * K1 * K0)


def ph_from_fco2_hco3(fCO2, HCO3, K0, K1):
    """pH from fCO2 and HCO3."""
    H = K0 * K1 * fCO2 / HCO3
    return -math.log10(H)


def ph_from_carb_hco3(CO3, HCO3, K2):
    """pH from CO3 and HCO3."""
    H = K2 * HCO3 / CO3
    return -math.log10(H)


# ============================================================================
# Complete all variables from DIC and pH
# ============================================================================

def complete_from_dic_ph(DIC, pH, Ks, TB, TS, TF, TSi, TPO4):
    """Compute all core variables from DIC and pH."""
    H = 10.0 ** (-pH)
    K0, K1, K2 = Ks["K0"], Ks["K1"], Ks["K2"]
    FugFac = Ks["FugFac"]

    CO3 = carbonate_from_dic_h(DIC, H, K1, K2)
    HCO3 = bicarbonate_from_dic_h(DIC, H, K1, K2)
    CO2aq = DIC - CO3 - HCO3
    fCO2 = CO2aq / K0
    pCO2 = fCO2 / FugFac
    TA = compute_ta(H, DIC, Ks, TB, TS, TF, TSi, TPO4)

    return {
        "TA": TA, "DIC": DIC, "pH": pH,
        "pCO2": pCO2, "fCO2": fCO2,
        "CO3": CO3, "HCO3": HCO3, "CO2aq": CO2aq,
    }


# ============================================================================
# Main solver
# ============================================================================

def solve(par1, par2, par1_type, par2_type,
          temperature=25.0, salinity=35.0, pressure=0.0,
          total_silicate=0.0, total_phosphate=0.0):
    """Solve the marine carbonate system from any two core parameters.

    Parameters
    ----------
    par1, par2 : float
        Input parameter values.
    par1_type, par2_type : int
        Parameter type codes:
        1=TA (umol/kg), 2=DIC (umol/kg), 3=pH (Total),
        4=pCO2 (uatm), 5=fCO2 (uatm), 6=CO3 (umol/kg), 7=HCO3 (umol/kg)
    temperature : float
        Temperature in degC.
    salinity : float
        Practical salinity.
    pressure : float
        Hydrostatic pressure in dbar.
    total_silicate : float
        Total silicate in umol/kg.
    total_phosphate : float
        Total phosphate in umol/kg.

    Returns
    -------
    dict with keys: TA, DIC, pH, pCO2, fCO2, CO3, HCO3, CO2aq
    """
    # Ensure par1_type < par2_type for canonical ordering
    if par1_type > par2_type:
        par1, par2 = par2, par1
        par1_type, par2_type = par2_type, par1_type

    # Unit conversions: umol/kg -> mol/kg, uatm -> atm
    TK = temperature + 273.15
    S = salinity
    Pbar = pressure / 10.0  # dbar to bar

    # Salt concentrations (mol/kg)
    TB = total_borate(S)
    TS = total_sulfate(S)
    TF = total_fluoride(S)
    TSi_mol = total_silicate * 1e-6
    TPO4_mol = total_phosphate * 1e-6

    # Equilibrium constants
    Ks = assemble_constants(TK, S, Pbar, TS, TF)

    K0 = Ks["K0"]
    K1, K2 = Ks["K1"], Ks["K2"]
    FugFac = Ks["FugFac"]

    # Convert inputs to internal units (mol/kg, atm)
    # Types 1,2,6,7 are concentrations in umol/kg -> mol/kg
    # Types 4,5 are pressures in uatm -> atm
    # Type 3 is pH (no conversion)
    def to_internal(val, typ):
        if typ in (1, 2, 6, 7):
            return val * 1e-6
        elif typ in (4, 5):
            return val * 1e-6
        else:  # pH
            return val

    p1 = to_internal(par1, par1_type)
    p2 = to_internal(par2, par2_type)

    # Icase: canonical pair identifier
    Icase = 100 * par1_type + par2_type

    # Solve for DIC and pH based on input pair
    DIC = None
    pH = None

    if Icase == 102:  # TA + DIC
        TA, DIC = p1, p2
        pH = ph_from_ta_dic(TA, DIC, Ks, TB, TS, TF, TSi_mol, TPO4_mol)

    elif Icase == 103:  # TA + pH
        TA, pH = p1, p2
        DIC = dic_from_ta_ph(TA, pH, Ks, TB, TS, TF, TSi_mol, TPO4_mol)

    elif Icase == 104:  # TA + pCO2
        TA, pCO2 = p1, p2
        fCO2 = pCO2 * FugFac
        pH = ph_from_ta_fco2(TA, fCO2, Ks, TB, TS, TF, TSi_mol, TPO4_mol)
        DIC = dic_from_ta_ph(TA, pH, Ks, TB, TS, TF, TSi_mol, TPO4_mol)

    elif Icase == 105:  # TA + fCO2
        TA, fCO2 = p1, p2
        pH = ph_from_ta_fco2(TA, fCO2, Ks, TB, TS, TF, TSi_mol, TPO4_mol)
        DIC = dic_from_ta_ph(TA, pH, Ks, TB, TS, TF, TSi_mol, TPO4_mol)

    elif Icase == 106:  # TA + CO3
        TA, CO3 = p1, p2
        pH = ph_from_ta_carb(TA, CO3, Ks, TB, TS, TF, TSi_mol, TPO4_mol)
        DIC = dic_from_ta_ph(TA, pH, Ks, TB, TS, TF, TSi_mol, TPO4_mol)

    elif Icase == 107:  # TA + HCO3
        TA, HCO3 = p1, p2
        pH = ph_from_ta_hco3(TA, HCO3, Ks, TB, TS, TF, TSi_mol, TPO4_mol)
        DIC = dic_from_ta_ph(TA, pH, Ks, TB, TS, TF, TSi_mol, TPO4_mol)

    elif Icase == 203:  # DIC + pH
        DIC, pH = p1, p2

    elif Icase == 204:  # DIC + pCO2
        DIC, pCO2 = p1, p2
        fCO2 = pCO2 * FugFac
        pH = ph_from_dic_fco2(DIC, fCO2, K0, K1, K2)

    elif Icase == 205:  # DIC + fCO2
        DIC, fCO2 = p1, p2
        pH = ph_from_dic_fco2(DIC, fCO2, K0, K1, K2)

    elif Icase == 206:  # DIC + CO3
        DIC, CO3 = p1, p2
        pH = ph_from_dic_carb(DIC, CO3, K1, K2)

    elif Icase == 207:  # DIC + HCO3
        DIC, HCO3 = p1, p2
        pH = ph_from_dic_hco3(DIC, HCO3, K1, K2)

    elif Icase == 304:  # pH + pCO2
        pH, pCO2 = p1, p2
        fCO2 = pCO2 * FugFac
        DIC = dic_from_ph_fco2(pH, fCO2, K0, K1, K2)

    elif Icase == 305:  # pH + fCO2
        pH, fCO2 = p1, p2
        DIC = dic_from_ph_fco2(pH, fCO2, K0, K1, K2)

    elif Icase == 306:  # pH + CO3
        pH, CO3 = p1, p2
        DIC = dic_from_ph_carb(pH, CO3, K1, K2)

    elif Icase == 307:  # pH + HCO3
        pH, HCO3 = p1, p2
        DIC = dic_from_ph_hco3(pH, HCO3, K1, K2)

    elif Icase == 406:  # pCO2 + CO3
        pCO2, CO3 = p1, p2
        fCO2 = pCO2 * FugFac
        pH = ph_from_fco2_carb(fCO2, CO3, K0, K1, K2)
        DIC = dic_from_ph_fco2(pH, fCO2, K0, K1, K2)

    elif Icase == 407:  # pCO2 + HCO3
        pCO2, HCO3 = p1, p2
        fCO2 = pCO2 * FugFac
        CO3 = carb_from_fco2_hco3(fCO2, HCO3, K0, K1, K2)
        pH = ph_from_fco2_carb(fCO2, CO3, K0, K1, K2)
        DIC = dic_from_ph_fco2(pH, fCO2, K0, K1, K2)

    elif Icase == 506:  # fCO2 + CO3
        fCO2, CO3 = p1, p2
        pH = ph_from_fco2_carb(fCO2, CO3, K0, K1, K2)
        DIC = dic_from_ph_fco2(pH, fCO2, K0, K1, K2)

    elif Icase == 507:  # fCO2 + HCO3
        fCO2, HCO3 = p1, p2
        CO3 = carb_from_fco2_hco3(fCO2, HCO3, K0, K1, K2)
        pH = ph_from_fco2_carb(fCO2, CO3, K0, K1, K2)
        DIC = dic_from_ph_fco2(pH, fCO2, K0, K1, K2)

    elif Icase == 607:  # CO3 + HCO3
        CO3, HCO3 = p1, p2
        fCO2 = fco2_from_carb_hco3(CO3, HCO3, K0, K1, K2)
        pH = ph_from_fco2_carb(fCO2, CO3, K0, K1, K2)
        DIC = dic_from_ph_fco2(pH, fCO2, K0, K1, K2)

    else:
        raise ValueError(f"Invalid parameter pair: types ({par1_type}, {par2_type})")

    # Complete all variables from DIC and pH
    result = complete_from_dic_ph(DIC, pH, Ks, TB, TS, TF, TSi_mol, TPO4_mol)

    # For cases where we had specific input values (e.g. TA+pCO2), we want to
    # preserve the exact input-derived fCO2 for consistency in some pair types.
    # But generally, back-computing from DIC+pH is the most consistent approach.

    # Convert back to output units (mol/kg -> umol/kg, atm -> uatm)
    return {
        "TA": result["TA"] * 1e6,
        "DIC": result["DIC"] * 1e6,
        "pH": result["pH"],
        "pCO2": result["pCO2"] * 1e6,
        "fCO2": result["fCO2"] * 1e6,
        "CO3": result["CO3"] * 1e6,
        "HCO3": result["HCO3"] * 1e6,
        "CO2aq": result["CO2aq"] * 1e6,
    }
