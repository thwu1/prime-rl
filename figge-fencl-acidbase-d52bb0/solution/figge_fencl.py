
"""Figge-Fencl v3.0 acid-base model — Python ctypes wrapper around libfigge.so."""

import ctypes
import json
import os


# ── Model parameter struct matching C FiggeParams ──

class _FiggeParams(ctypes.Structure):
    _fields_ = [
        ('nb_magnitude', ctypes.c_double),
        ('nb_midpoint', ctypes.c_double),
        ('hist_nb_pka', ctypes.c_double * 5),
        ('hist_std_pka', ctypes.c_double * 11),
        ('lys_pka', ctypes.c_double * 6),
        ('arg_pka', ctypes.c_double),
        ('nh2_pka', ctypes.c_double),
        ('cooh_pka', ctypes.c_double),
        ('asp_glu_pka', ctypes.c_double),
        ('cys_pka', ctypes.c_double),
        ('tyr_pka', ctypes.c_double),
        ('phos_pka1', ctypes.c_double),
        ('phos_pka2', ctypes.c_double),
        ('phos_pka3', ctypes.c_double),
        ('kc1', ctypes.c_double),
        ('kc2', ctypes.c_double),
        ('kw', ctypes.c_double),
        ('hh_pka', ctypes.c_double),
        ('hh_alpha', ctypes.c_double),
        ('albumin_mw_kda', ctypes.c_double),
        ('n_hist_nb', ctypes.c_int),
        ('n_hist_std', ctypes.c_int),
        ('n_lys_groups', ctypes.c_int),
        ('lys_count', ctypes.c_int * 6),
        ('arg_count', ctypes.c_int),
        ('nh2_count', ctypes.c_int),
        ('cooh_count', ctypes.c_int),
        ('asp_glu_count', ctypes.c_int),
        ('cys_count', ctypes.c_int),
        ('tyr_count', ctypes.c_int),
    ]


# ── Load C library ──

_lib = ctypes.CDLL('/app/libfigge.so')

_lib.figge_albumin_net_charge.restype = ctypes.c_double
_lib.figge_albumin_net_charge.argtypes = [
    ctypes.c_double, ctypes.POINTER(_FiggeParams)
]

_lib.figge_phosphate_charge.restype = ctypes.c_double
_lib.figge_phosphate_charge.argtypes = [
    ctypes.c_double, ctypes.c_double, ctypes.POINTER(_FiggeParams)
]

_lib.figge_solve_ph.restype = ctypes.c_double
_lib.figge_solve_ph.argtypes = [
    ctypes.c_double, ctypes.c_double, ctypes.c_double,
    ctypes.c_double, ctypes.POINTER(_FiggeParams)
]


# ── Build parameter struct from JSON ──

_c_params = None
_json_params = None


def _load_json():
    global _json_params
    if _json_params is None:
        with open('/app/spec/model_params.json') as f:
            _json_params = json.load(f)
    return _json_params


def _get_c_params():
    global _c_params
    if _c_params is not None:
        return _c_params

    raw = _load_json()
    alb = raw['albumin']

    p = _FiggeParams()
    p.nb_magnitude = alb['NB_transition']['magnitude']
    p.nb_midpoint = alb['NB_transition']['midpoint_pH']

    hist_nb = alb['histidine_residues']['domain1_NB_shifted_pKa']
    for i, v in enumerate(hist_nb):
        p.hist_nb_pka[i] = v
    p.n_hist_nb = len(hist_nb)

    hist_std = alb['histidine_residues']['standard_pKa']
    for i, v in enumerate(hist_std):
        p.hist_std_pka[i] = v
    p.n_hist_std = len(hist_std)

    groups = alb['lysine_residues']['groups']
    for i, g in enumerate(groups):
        p.lys_pka[i] = g['pKa']
        p.lys_count[i] = g['count']
    p.n_lys_groups = len(groups)

    p.arg_pka = alb['arginine']['pKa']
    p.arg_count = alb['arginine']['count']
    p.nh2_pka = alb['amino_terminus']['pKa']
    p.nh2_count = alb['amino_terminus']['count']
    p.cooh_pka = alb['carboxyl_terminus']['pKa']
    p.cooh_count = alb['carboxyl_terminus']['count']
    p.asp_glu_pka = alb['asp_glu']['pKa']
    p.asp_glu_count = alb['asp_glu']['count']
    p.cys_pka = alb['cysteine']['pKa']
    p.cys_count = alb['cysteine']['count']
    p.tyr_pka = alb['tyrosine']['pKa']
    p.tyr_count = alb['tyrosine']['count']

    phos = raw['phosphate']
    p.phos_pka1 = phos['pKa1']
    p.phos_pka2 = phos['pKa2']
    p.phos_pka3 = phos['pKa3']

    co2 = raw['CO2_bicarbonate']
    p.kc1 = co2['Kc1']
    p.kc2 = co2['Kc2']
    p.kw = raw['water']['Kw']
    p.hh_pka = co2['HH_pKa']
    p.hh_alpha = co2['HH_solubility_mmol_L_Torr']
    p.albumin_mw_kda = alb['molecular_weight_Da'] / 1000.0

    _c_params = p
    return _c_params


# ── Public API ──

def hco3(pH, pCO2):
    """Henderson-Hasselbalch: [HCO3-] from pH and pCO2.

    Returns HCO3- in mmol/L.
    """
    raw = _load_json()
    co2 = raw['CO2_bicarbonate']
    alpha = co2['HH_solubility_mmol_L_Torr']
    pKa = co2['HH_pKa']
    return alpha * pCO2 * (10.0 ** (pH - pKa))


def albumin_net_charge_per_mol(pH):
    """Net charge per mol of albumin (Eq/mol). Negative at physiologic pH."""
    p = _get_c_params()
    return _lib.figge_albumin_net_charge(ctypes.c_double(pH), ctypes.byref(p))


def albumin_charge(albumin_g_dL, pH):
    """Albumin anionic buffer contribution Alb- in mEq/L.

    Positive at physiologic pH (albumin carries net negative charge).
    """
    if albumin_g_dL <= 0:
        return 0.0
    p = _get_c_params()
    alb_mM = albumin_g_dL * 10.0 / p.albumin_mw_kda
    net = _lib.figge_albumin_net_charge(ctypes.c_double(pH), ctypes.byref(p))
    return -net * alb_mM


def phosphate_charge(phos_mmol_L, pH):
    """Triprotic phosphate Pi- in mEq/L."""
    if phos_mmol_L <= 0:
        return 0.0
    p = _get_c_params()
    return _lib.figge_phosphate_charge(
        ctypes.c_double(phos_mmol_L), ctypes.c_double(pH), ctypes.byref(p))


def predict_pH(SID, PCO2, Pi, Albumin):
    """Solve electroneutrality for pH. Delegates to C solver."""
    p = _get_c_params()
    return _lib.figge_solve_ph(
        ctypes.c_double(SID), ctypes.c_double(PCO2),
        ctypes.c_double(Pi), ctypes.c_double(Albumin),
        ctypes.byref(p))
