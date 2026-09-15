#!/usr/bin/env python3
"""
ISDA SIMM v2.5 Calculator — reads parameters from SQLite, writes results to SQLite.
"""
import os, sys, csv, math, sqlite3
from scipy.stats import norm

# ============================================================
# Global parameter variables (populated from SQLite)
# ============================================================
TENOR_LIST = ['2w','1m','3m','6m','1y','2y','3y','5y','10y','15y','20y','30y']
RISK_CLASS_NAMES = ['Rates','CreditQ','CreditNonQ','Equity','Commodity','FX']

REG_VOL_CCY = []
LOW_VOL_CCY = []
HIGH_VOL_FX_CCY = []
FX_CAT1 = []
FX_CAT2 = []
REG_VOL_RW = {}
LOW_VOL_RW = {}
HIGH_VOL_RW = {}
INFLATION_RW = 0
CCY_BASIS_RW = 0
IR_HVR = 0
IR_VRW = 0
IR_CORR = {}
SUB_CURVES_CORR = 0
INFLATION_CORR = 0
CCY_BASIS_SPREAD_CORR = 0
IR_GAMMA = 0
CREDITQ_RW = {}
CREDITQ_VRW = 0
BASE_CORR_WEIGHT = 0
CREDITQ_CORR_SAME_ISSUER = 0
CREDITQ_CORR_DIFF_ISSUER = 0
CREDITQ_CORR_RESIDUAL = 0
CREDITQ_CORR_BASE = 0
CREDITQ_CROSS_BUCKET = []
CREDITNONQ_RW = {}
CREDITNONQ_VRW = 0
CREDITNONQ_CORR_SAME = 0
CREDITNONQ_CORR_DIFF = 0
CREDITNONQ_CORR_RESIDUAL = 0
CREDITNONQ_CROSS_BUCKET = 0
EQUITY_RW = {}
EQUITY_HVR = 0
EQUITY_VRW = 0
EQUITY_VRW_B12 = 0
EQUITY_CORR = {}
EQUITY_CROSS_BUCKET = []
COMMODITY_RW = {}
COMMODITY_HVR = 0
COMMODITY_VRW = 0
COMMODITY_CORR = {}
COMMODITY_CROSS_BUCKET = []
FX_RW = {}
FX_HVR = 0
FX_VRW = 0
FX_VEGA_CORR = 0
FX_REG_VOL_CORR = {}
FX_HIGH_VOL_CORR = {}
IR_DELTA_CT = {}
IR_DELTA_CT_DEFAULT = 33
CREDIT_DELTA_CT_Q = {}
CREDIT_DELTA_CT_NQ = {}
EQUITY_DELTA_CT = {}
COMMODITY_DELTA_CT = {}
FX_DELTA_CT = {}
IR_VEGA_CT = {}
IR_VEGA_CT_DEFAULT = 120
CREDIT_VEGA_CT_Q = 260
CREDIT_VEGA_CT_NQ = 145
EQUITY_VEGA_CT = {}
COMMODITY_VEGA_CT = {}
FX_VEGA_CT = {}
RISK_CLASS_CORR = []


def load_params(db_path="/app/simm_params.db"):
    """Load all SIMM v2.5 parameters from the SQLite database."""
    global REG_VOL_CCY, LOW_VOL_CCY, HIGH_VOL_FX_CCY, FX_CAT1, FX_CAT2
    global REG_VOL_RW, LOW_VOL_RW, HIGH_VOL_RW
    global INFLATION_RW, CCY_BASIS_RW, IR_HVR, IR_VRW
    global IR_CORR, SUB_CURVES_CORR, INFLATION_CORR, CCY_BASIS_SPREAD_CORR, IR_GAMMA
    global CREDITQ_RW, CREDITQ_VRW, BASE_CORR_WEIGHT
    global CREDITQ_CORR_SAME_ISSUER, CREDITQ_CORR_DIFF_ISSUER, CREDITQ_CORR_RESIDUAL, CREDITQ_CORR_BASE
    global CREDITQ_CROSS_BUCKET
    global CREDITNONQ_RW, CREDITNONQ_VRW
    global CREDITNONQ_CORR_SAME, CREDITNONQ_CORR_DIFF, CREDITNONQ_CORR_RESIDUAL, CREDITNONQ_CROSS_BUCKET
    global EQUITY_RW, EQUITY_HVR, EQUITY_VRW, EQUITY_VRW_B12
    global EQUITY_CORR, EQUITY_CROSS_BUCKET
    global COMMODITY_RW, COMMODITY_HVR, COMMODITY_VRW
    global COMMODITY_CORR, COMMODITY_CROSS_BUCKET
    global FX_RW, FX_HVR, FX_VRW, FX_VEGA_CORR
    global FX_REG_VOL_CORR, FX_HIGH_VOL_CORR
    global IR_DELTA_CT, IR_DELTA_CT_DEFAULT
    global CREDIT_DELTA_CT_Q, CREDIT_DELTA_CT_NQ
    global EQUITY_DELTA_CT, COMMODITY_DELTA_CT, FX_DELTA_CT
    global IR_VEGA_CT, IR_VEGA_CT_DEFAULT
    global CREDIT_VEGA_CT_Q, CREDIT_VEGA_CT_NQ
    global EQUITY_VEGA_CT, COMMODITY_VEGA_CT, FX_VEGA_CT
    global RISK_CLASS_CORR

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Scalar parameters
    p = {}
    for name, value in c.execute("SELECT name, value FROM model_params"):
        p[name] = value

    INFLATION_RW = p['inflation_rw']
    CCY_BASIS_RW = p['ccy_basis_rw']
    IR_HVR = p['ir_hvr']
    IR_VRW = p['ir_vrw']
    SUB_CURVES_CORR = p['sub_curves_corr']
    INFLATION_CORR = p['inflation_corr']
    CCY_BASIS_SPREAD_CORR = p['ccy_basis_spread_corr']
    IR_GAMMA = p['ir_gamma']
    CREDITQ_VRW = p['creditq_vrw']
    BASE_CORR_WEIGHT = p['base_corr_weight']
    CREDITQ_CORR_SAME_ISSUER = p['creditq_corr_same_issuer']
    CREDITQ_CORR_DIFF_ISSUER = p['creditq_corr_diff_issuer']
    CREDITQ_CORR_RESIDUAL = p['creditq_corr_residual']
    CREDITQ_CORR_BASE = p['creditq_corr_base']
    CREDITNONQ_VRW = p['creditnonq_vrw']
    CREDITNONQ_CORR_SAME = p['creditnonq_corr_same']
    CREDITNONQ_CORR_DIFF = p['creditnonq_corr_diff']
    CREDITNONQ_CORR_RESIDUAL = p['creditnonq_corr_residual']
    CREDITNONQ_CROSS_BUCKET = p['creditnonq_cross_bucket_corr']
    EQUITY_HVR = p['equity_hvr']
    EQUITY_VRW = p['equity_vrw']
    EQUITY_VRW_B12 = p['equity_vrw_b12']
    COMMODITY_HVR = p['commodity_hvr']
    COMMODITY_VRW = p['commodity_vrw']
    FX_HVR = p['fx_hvr']
    FX_VRW = p['fx_vrw']
    FX_VEGA_CORR = p['fx_vega_corr']

    # Currency configuration
    REG_VOL_CCY = []
    LOW_VOL_CCY = []
    HIGH_VOL_FX_CCY = []
    FX_CAT1 = []
    FX_CAT2 = []
    for ccy, vol_regime, fx_cat in c.execute("SELECT currency, ir_vol_regime, fx_category FROM currency_config"):
        if vol_regime == 'Regular': REG_VOL_CCY.append(ccy)
        elif vol_regime == 'Low': LOW_VOL_CCY.append(ccy)
        elif vol_regime == 'High': HIGH_VOL_FX_CCY.append(ccy)
        if fx_cat == 'Category1': FX_CAT1.append(ccy)
        elif fx_cat == 'Category2': FX_CAT2.append(ccy)

    # IR risk weights
    REG_VOL_RW = {}
    LOW_VOL_RW = {}
    HIGH_VOL_RW = {}
    for tenor, regime, weight in c.execute("SELECT tenor, vol_regime, weight FROM ir_risk_weights"):
        if regime == 'Regular': REG_VOL_RW[tenor] = weight
        elif regime == 'Low': LOW_VOL_RW[tenor] = weight
        elif regime == 'High': HIGH_VOL_RW[tenor] = weight

    # IR tenor correlations
    IR_CORR = {}
    for t1, t2, corr in c.execute("SELECT tenor1, tenor2, correlation FROM ir_tenor_correlations"):
        IR_CORR[(t1, t2)] = corr

    # CreditQ
    CREDITQ_RW = {}
    for bucket, weight in c.execute("SELECT bucket, weight FROM creditq_bucket_weights"):
        CREDITQ_RW[bucket] = weight
    CREDITQ_CROSS_BUCKET = [[0]*12 for _ in range(12)]
    for b1, b2, corr in c.execute("SELECT bucket1, bucket2, correlation FROM creditq_cross_bucket_corr"):
        CREDITQ_CROSS_BUCKET[b1-1][b2-1] = corr

    # CreditNonQ
    CREDITNONQ_RW = {}
    for bucket, weight in c.execute("SELECT bucket, weight FROM creditnonq_bucket_weights"):
        CREDITNONQ_RW[bucket] = weight

    # Equity
    EQUITY_RW = {}
    for bucket, weight in c.execute("SELECT bucket, weight FROM equity_bucket_weights"):
        EQUITY_RW[bucket] = weight
    EQUITY_CORR = {}
    for bucket, corr in c.execute("SELECT bucket, correlation FROM equity_intra_bucket_corr"):
        EQUITY_CORR[bucket] = corr
    EQUITY_CROSS_BUCKET = [[0]*12 for _ in range(12)]
    for b1, b2, corr in c.execute("SELECT bucket1, bucket2, correlation FROM equity_cross_bucket_corr"):
        EQUITY_CROSS_BUCKET[b1-1][b2-1] = corr

    # Commodity
    COMMODITY_RW = {}
    for bucket, weight in c.execute("SELECT bucket, weight FROM commodity_bucket_weights"):
        COMMODITY_RW[bucket] = weight
    COMMODITY_CORR = {}
    for bucket, corr in c.execute("SELECT bucket, correlation FROM commodity_intra_bucket_corr"):
        COMMODITY_CORR[bucket] = corr
    COMMODITY_CROSS_BUCKET = [[0]*17 for _ in range(17)]
    for b1, b2, corr in c.execute("SELECT bucket1, bucket2, correlation FROM commodity_cross_bucket_corr"):
        COMMODITY_CROSS_BUCKET[b1-1][b2-1] = corr

    # FX
    FX_RW = {"Regular": {}, "High": {}}
    for g1, g2, weight in c.execute("SELECT vol_group1, vol_group2, weight FROM fx_pair_weights"):
        FX_RW[g1][g2] = weight
    FX_REG_VOL_CORR = {"Regular": {}, "High": {}}
    FX_HIGH_VOL_CORR = {"Regular": {}, "High": {}}
    for calc_type, g1, g2, corr in c.execute("SELECT calc_ccy_type, vol_group1, vol_group2, correlation FROM fx_pair_correlations"):
        if calc_type == 'Regular': FX_REG_VOL_CORR[g1][g2] = corr
        else: FX_HIGH_VOL_CORR[g1][g2] = corr

    # Concentration thresholds
    IR_DELTA_CT = {}
    IR_DELTA_CT_DEFAULT = 33
    IR_VEGA_CT = {}
    IR_VEGA_CT_DEFAULT = 120
    CREDIT_DELTA_CT_Q = {}
    CREDIT_DELTA_CT_NQ = {}
    EQUITY_DELTA_CT = {}
    COMMODITY_DELTA_CT = {}
    FX_DELTA_CT = {}
    CREDIT_VEGA_CT_Q = 260
    CREDIT_VEGA_CT_NQ = 145
    EQUITY_VEGA_CT = {}
    COMMODITY_VEGA_CT = {}
    FX_VEGA_CT = {}

    for rc, mt, key, thresh in c.execute("SELECT risk_class, margin_type, key, threshold_millions FROM concentration_thresholds"):
        if rc == 'IR' and mt == 'delta':
            if key == 'DEFAULT': IR_DELTA_CT_DEFAULT = thresh
            else: IR_DELTA_CT[key] = thresh
        elif rc == 'IR' and mt == 'vega':
            if key == 'DEFAULT': IR_VEGA_CT_DEFAULT = thresh
            else: IR_VEGA_CT[key] = thresh
        elif rc == 'CreditQ' and mt == 'delta':
            try: CREDIT_DELTA_CT_Q[int(key)] = thresh
            except: CREDIT_DELTA_CT_Q[0] = thresh
        elif rc == 'CreditNonQ' and mt == 'delta':
            try: CREDIT_DELTA_CT_NQ[int(key)] = thresh
            except: CREDIT_DELTA_CT_NQ[0] = thresh
        elif rc == 'Equity' and mt == 'delta':
            try: EQUITY_DELTA_CT[int(key)] = thresh
            except: EQUITY_DELTA_CT[0] = thresh
        elif rc == 'Commodity' and mt == 'delta':
            try: COMMODITY_DELTA_CT[int(key)] = thresh
            except: COMMODITY_DELTA_CT[0] = thresh
        elif rc == 'FX' and mt == 'delta':
            FX_DELTA_CT[key] = thresh
        elif rc == 'CreditQ' and mt == 'vega':
            CREDIT_VEGA_CT_Q = thresh
        elif rc == 'CreditNonQ' and mt == 'vega':
            CREDIT_VEGA_CT_NQ = thresh
        elif rc == 'Equity' and mt == 'vega':
            try: EQUITY_VEGA_CT[int(key)] = thresh
            except: EQUITY_VEGA_CT[0] = thresh
        elif rc == 'Commodity' and mt == 'vega':
            try: COMMODITY_VEGA_CT[int(key)] = thresh
            except: COMMODITY_VEGA_CT[0] = thresh
        elif rc == 'FX' and mt == 'vega':
            parts = key.split(',')
            FX_VEGA_CT[tuple(parts)] = thresh

    # Risk class correlations
    RISK_CLASS_CORR = [[0]*6 for _ in range(6)]
    rc_idx = {n: i for i, n in enumerate(RISK_CLASS_NAMES)}
    for c1_name, c2_name, corr in c.execute("SELECT class1, class2, correlation FROM risk_class_correlations"):
        RISK_CLASS_CORR[rc_idx[c1_name]][rc_idx[c2_name]] = corr

    conn.close()


# ============================================================
# Utility Functions
# ============================================================

def scaling_func(t):
    t = t.lower().strip()
    if t == '2w':
        return 0.5
    elif 'm' in t:
        days = (365.0/12) * float(t.replace('m',''))
        return 0.5 * min(1.0, 14.0/days)
    elif 'y' in t:
        days = 365.0 * float(t.replace('y',''))
        return 0.5 * min(1.0, 14.0/days)
    return 0.5

def cr(sum_s, T_millions):
    T = T_millions * 1_000_000
    return max(1.0, math.sqrt(abs(sum_s) / T))

def get_ir_ct(ccy):
    return IR_DELTA_CT.get(ccy, IR_DELTA_CT_DEFAULT)

def get_fx_category(ccy):
    if ccy in FX_CAT1: return 'Category1'
    if ccy in FX_CAT2: return 'Category2'
    return 'Category3'

def get_fx_vol_group(ccy):
    return 'High' if ccy in HIGH_VOL_FX_CCY else 'Regular'

def get_ir_rw(ccy, tenor):
    if ccy in REG_VOL_CCY: return REG_VOL_RW[tenor]
    if ccy in LOW_VOL_CCY: return LOW_VOL_RW[tenor]
    return HIGH_VOL_RW[tenor]

def parse_bucket(b):
    b = str(b).strip()
    if b.lower() == 'residual' or b == '': return 0
    try: return int(b)
    except: return 0

def unique_ordered(lst):
    seen = set()
    result = []
    for x in lst:
        if x not in seen:
            seen.add(x)
            result.append(x)
    return result

def norm_pair(p):
    if len(p) == 6:
        a, b = p[:3], p[3:]
        if a > b: return b + a
        return a + b
    return p


# ============================================================
# CRIF Parsing
# ============================================================

def read_crif(path):
    rows = []
    with open(path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            r = {}
            r['ProductClass'] = row.get('ProductClass','').strip()
            r['RiskType'] = row.get('RiskType','').strip()
            r['Qualifier'] = row.get('Qualifier','').strip()
            r['Bucket'] = row.get('Bucket','').strip()
            r['Label1'] = row.get('Label1','').strip()
            r['Label2'] = row.get('Label2','').strip()
            try:
                r['AmountUSD'] = float(row.get('AmountUSD','0').strip())
            except:
                r['AmountUSD'] = 0.0
            rows.append(r)
    return rows


# ============================================================
# Delta Margin: Interest Rates
# ============================================================

def ir_delta_margin(crif, calc_ccy='USD'):
    ir_rows = [r for r in crif if r['RiskType'] in ('Risk_IRCurve','Risk_Inflation','Risk_XCcyBasis')]
    if not ir_rows:
        return 0.0

    currencies = unique_ordered([r['Qualifier'] for r in ir_rows])
    list_K = []
    list_S = []
    dict_CR = {}

    for ccy in currencies:
        ccy_rows = [r for r in ir_rows if r['Qualifier'] == ccy]
        cr_rows = [r for r in ccy_rows if r['RiskType'] != 'Risk_XCcyBasis']
        sum_s_cr = sum(r['AmountUSD'] for r in cr_rows)
        T_ct = get_ir_ct(ccy)
        CR = cr(sum_s_cr, T_ct)
        dict_CR[ccy] = CR

        list_WS = []
        ws_tenors = []
        ws_types = []

        risk_types_present = unique_ordered([r['RiskType'] for r in ccy_rows])
        for rt in risk_types_present:
            rt_rows = [r for r in ccy_rows if r['RiskType'] == rt]
            if rt == 'Risk_Inflation':
                s = sum(r['AmountUSD'] for r in rt_rows)
                WS = INFLATION_RW * s * CR
                list_WS.append(WS)
                ws_tenors.append('Inf')
                ws_types.append('Inf')
            elif rt == 'Risk_XCcyBasis':
                s = sum(r['AmountUSD'] for r in rt_rows)
                WS = CCY_BASIS_RW * s
                list_WS.append(WS)
                ws_tenors.append('XCcy')
                ws_types.append('XCcy')
            elif rt == 'Risk_IRCurve':
                subcurves = unique_ordered([r['Label2'] for r in rt_rows])
                for sc in subcurves:
                    sc_rows = [r for r in rt_rows if r['Label2'] == sc]
                    tenors = unique_ordered([r['Label1'].lower() for r in sc_rows if r['Label1'].lower() in TENOR_LIST])
                    for tenor in tenors:
                        t_rows = [r for r in sc_rows if r['Label1'].lower() == tenor]
                        s = sum(r['AmountUSD'] for r in t_rows)
                        RW = get_ir_rw(ccy, tenor)
                        WS = RW * s * CR
                        list_WS.append(WS)
                        ws_tenors.append(tenor)
                        ws_types.append(sc)

        K_sq = 0.0
        n = len(list_WS)
        for i in range(n):
            K_sq += list_WS[i] ** 2
            for j in range(n):
                if i == j: continue
                if ws_types[i] == ws_types[j]: phi = 1.0
                elif ws_types[i] == 'XCcy' or ws_types[j] == 'XCcy': phi = CCY_BASIS_SPREAD_CORR
                elif ws_types[i] == 'Inf' or ws_types[j] == 'Inf': phi = INFLATION_CORR
                else: phi = SUB_CURVES_CORR
                if ws_tenors[i] not in TENOR_LIST or ws_tenors[j] not in TENOR_LIST: rho = 1.0
                else: rho = IR_CORR.get((ws_tenors[i], ws_tenors[j]), 1.0)
                K_sq += rho * list_WS[i] * list_WS[j] * phi

        K = math.sqrt(max(K_sq, 0.0))
        list_K.append(K)
        S_b = max(min(sum(list_WS), K), -K)
        list_S.append(S_b)

    total_sq = sum(k**2 for k in list_K)
    for i in range(len(currencies)):
        for j in range(len(currencies)):
            if i == j: continue
            g = min(dict_CR[currencies[i]], dict_CR[currencies[j]]) / max(dict_CR[currencies[i]], dict_CR[currencies[j]])
            total_sq += IR_GAMMA * list_S[i] * list_S[j] * g

    return math.sqrt(max(total_sq, 0.0))


# ============================================================
# Delta Margin: FX
# ============================================================

def fx_delta_margin(crif, calc_ccy='USD'):
    fx_rows = [r for r in crif if r['RiskType'] == 'Risk_FX']
    if not fx_rows:
        return 0.0

    currencies = unique_ordered([r['Qualifier'] for r in fx_rows])
    list_WS = []
    list_CR = []
    ccy_list = []

    for ccy in currencies:
        ccy_rows = [r for r in fx_rows if r['Qualifier'] == ccy]
        s = sum(r['AmountUSD'] for r in ccy_rows)
        cat = get_fx_category(ccy)
        T = FX_DELTA_CT[cat] if cat in FX_DELTA_CT else FX_DELTA_CT['Others']
        CR_val = cr(s, T)
        list_CR.append(CR_val)
        if ccy == calc_ccy: RW = 0
        else:
            vg_ccy = get_fx_vol_group(ccy)
            vg_calc = get_fx_vol_group(calc_ccy)
            RW = FX_RW[vg_ccy][vg_calc]
        WS = s * CR_val * RW
        list_WS.append(WS)
        ccy_list.append(ccy)

    K_sq = 0.0
    n = len(list_WS)
    for i in range(n):
        K_sq += list_WS[i] ** 2
        for j in range(n):
            if i == j: continue
            f = min(list_CR[i], list_CR[j]) / max(list_CR[i], list_CR[j])
            c1 = ccy_list[i]
            c2 = ccy_list[j]
            vg1 = get_fx_vol_group(c1)
            vg2 = get_fx_vol_group(c2)
            if calc_ccy not in HIGH_VOL_FX_CCY:
                rho = FX_REG_VOL_CORR[vg1][vg2]
            else:
                rho = FX_HIGH_VOL_CORR[vg1][vg2]
            K_sq += rho * list_WS[i] * list_WS[j] * f

    return math.sqrt(max(K_sq, 0.0))


# ============================================================
# Delta Margin: CreditQ, CreditNonQ, Equity, Commodity
# ============================================================

def _get_rw(risk_type, bucket):
    if risk_type == 'Risk_CreditQ': return CREDITQ_RW.get(bucket, CREDITQ_RW[0])
    if risk_type == 'Risk_CreditNonQ': return CREDITNONQ_RW.get(bucket, CREDITNONQ_RW[0])
    if risk_type == 'Risk_Equity': return EQUITY_RW.get(bucket, EQUITY_RW[0])
    if risk_type == 'Risk_Commodity': return COMMODITY_RW.get(bucket, max(COMMODITY_RW.values()))
    return 0

def _get_delta_ct(risk_type, bucket):
    if risk_type == 'Risk_CreditQ': return CREDIT_DELTA_CT_Q.get(bucket, CREDIT_DELTA_CT_Q[0])
    if risk_type == 'Risk_CreditNonQ': return CREDIT_DELTA_CT_NQ.get(bucket, CREDIT_DELTA_CT_NQ[0])
    if risk_type == 'Risk_Equity': return EQUITY_DELTA_CT.get(bucket, EQUITY_DELTA_CT[0])
    if risk_type == 'Risk_Commodity': return COMMODITY_DELTA_CT.get(bucket, min(COMMODITY_DELTA_CT.values()))
    return 1.0

def _credit_intra_rho(risk_type, idx_i, idx_j):
    if risk_type == 'Risk_CreditQ':
        if idx_i == 'Res' or idx_j == 'Res': return CREDITQ_CORR_RESIDUAL
        if idx_i == idx_j: return CREDITQ_CORR_SAME_ISSUER
        return CREDITQ_CORR_DIFF_ISSUER
    else:
        if idx_i == 'Res' or idx_j == 'Res': return CREDITNONQ_CORR_RESIDUAL
        if idx_i == idx_j: return CREDITNONQ_CORR_SAME
        return CREDITNONQ_CORR_DIFF

def _cross_bucket_gamma(risk_type, b1, b2):
    if risk_type == 'Risk_CreditQ': return CREDITQ_CROSS_BUCKET[b1-1][b2-1]
    if risk_type == 'Risk_CreditNonQ': return CREDITNONQ_CROSS_BUCKET
    if risk_type == 'Risk_Equity': return EQUITY_CROSS_BUCKET[b1-1][b2-1]
    if risk_type == 'Risk_Commodity': return COMMODITY_CROSS_BUCKET[b1-1][b2-1]
    return 0

def other_delta_margin(crif, risk_type, calc_ccy='USD'):
    rows = [r for r in crif if r['RiskType'] == risk_type]
    if not rows:
        return 0.0

    buckets_raw = unique_ordered([r['Bucket'] for r in rows])
    buckets = unique_ordered([parse_bucket(b) for b in buckets_raw])

    K_Res = 0.0
    list_K = []
    list_S = []
    non_res_buckets = []

    for bucket in buckets:
        b_rows = [r for r in rows if parse_bucket(r['Bucket']) == bucket]
        RW = _get_rw(risk_type, bucket)
        T = _get_delta_ct(risk_type, bucket)

        list_WS = []
        list_CR = []
        index = []

        qualifiers = unique_ordered([r['Qualifier'] for r in b_rows])
        for qual in qualifiers:
            q_rows = [r for r in b_rows if r['Qualifier'] == qual]
            if risk_type in ('Risk_CreditQ', 'Risk_CreditNonQ'):
                s_qual = sum(r['AmountUSD'] for r in q_rows)
                CR_val = cr(s_qual, T)
                label2s = unique_ordered([r['Label2'] for r in q_rows])
                for l2 in label2s:
                    l2_rows = [r for r in q_rows if r['Label2'] == l2]
                    tenors = unique_ordered([r['Label1'].lower() for r in l2_rows if r['Label1'].lower() in TENOR_LIST])
                    for tenor in tenors:
                        t_rows = [r for r in l2_rows if r['Label1'].lower() == tenor]
                        s = sum(r['AmountUSD'] for r in t_rows)
                        list_WS.append(RW * s * CR_val)
                        list_CR.append(CR_val)
                        if bucket == 0: index.append('Res')
                        elif risk_type == 'Risk_CreditQ': index.append(qual)
                        else: index.append(l2)
            else:
                s_qual = sum(r['AmountUSD'] for r in q_rows)
                CR_val = cr(s_qual, T)
                list_CR.append(CR_val)
                list_WS.append(RW * s_qual * CR_val)

        K_sq = 0.0
        n = len(list_WS)
        for i in range(n):
            K_sq += list_WS[i] ** 2
            for j in range(n):
                if i == j: continue
                if risk_type in ('Risk_CreditQ', 'Risk_CreditNonQ'):
                    rho = _credit_intra_rho(risk_type, index[i], index[j])
                else:
                    rho = EQUITY_CORR.get(bucket, 0) if risk_type == 'Risk_Equity' else COMMODITY_CORR.get(bucket, 0)
                f = min(list_CR[i], list_CR[j]) / max(list_CR[i], list_CR[j]) if list_CR else 1.0
                K_sq += rho * list_WS[i] * list_WS[j] * f

        K = math.sqrt(max(K_sq, 0.0))
        if bucket == 0:
            K_Res += K
        else:
            list_K.append(K)
            S_b = max(min(sum(list_WS), K), -K)
            list_S.append(S_b)
            non_res_buckets.append(bucket)

    total_sq = sum(k**2 for k in list_K)
    for i in range(len(non_res_buckets)):
        for j in range(len(non_res_buckets)):
            if i == j: continue
            gamma = _cross_bucket_gamma(risk_type, non_res_buckets[i], non_res_buckets[j])
            total_sq += gamma * list_S[i] * list_S[j]

    return math.sqrt(max(total_sq, 0.0)) + K_Res


# ============================================================
# Base Correlation Margin
# ============================================================

def base_corr_margin(crif):
    rows = [r for r in crif if r['RiskType'] == 'Risk_BaseCorr']
    if not rows:
        return 0.0

    qualifiers = unique_ordered([r['Qualifier'] for r in rows])
    list_WS = []
    for qual in qualifiers:
        q_rows = [r for r in rows if r['Qualifier'] == qual]
        s = sum(r['AmountUSD'] for r in q_rows)
        WS = BASE_CORR_WEIGHT * s
        list_WS.append(WS)

    K_sq = 0.0
    n = len(list_WS)
    for i in range(n):
        for j in range(n):
            rho = 1.0 if i == j else CREDITQ_CORR_BASE
            K_sq += list_WS[i] * list_WS[j] * rho

    return math.sqrt(max(K_sq, 0.0))


# ============================================================
# Vega Margin: IR
# ============================================================

def ir_vega_margin(crif, calc_ccy='USD'):
    vega_rows = [r for r in crif if r['RiskType'] in ('Risk_IRVol', 'Risk_InflationVol')]
    if not vega_rows:
        return 0.0

    currencies = unique_ordered([r['Qualifier'] for r in vega_rows])
    list_K = []
    list_S = []
    dict_VCR = {}

    for ccy in currencies:
        ccy_rows = [r for r in vega_rows if r['Qualifier'] == ccy]
        s_total = sum(r['AmountUSD'] for r in ccy_rows)
        VT = IR_VEGA_CT.get(ccy, IR_VEGA_CT_DEFAULT) * 1_000_000
        VCR = max(1.0, math.sqrt(abs(s_total) / VT))
        dict_VCR[ccy] = VCR

        VR_list = []
        vr_index = []

        risk_types_present = unique_ordered([r['RiskType'] for r in ccy_rows])
        for rt in risk_types_present:
            rt_rows = [r for r in ccy_rows if r['RiskType'] == rt]
            tenors = unique_ordered([r['Label1'].lower() for r in rt_rows if r['Label1'].strip()])
            for tenor in tenors:
                t_rows = [r for r in rt_rows if r['Label1'].lower() == tenor]
                s = sum(r['AmountUSD'] for r in t_rows)
                VR_list.append(IR_VRW * s * VCR)
                vr_index.append(tenor if rt == 'Risk_IRVol' else 'Inf')

        K_sq = 0.0
        n = len(VR_list)
        for i in range(n):
            K_sq += VR_list[i] ** 2
            for j in range(n):
                if i == j: continue
                if vr_index[i] == 'Inf' and vr_index[j] == 'Inf': rho = 1.0
                elif vr_index[i] == 'Inf' or vr_index[j] == 'Inf': rho = INFLATION_CORR
                else: rho = IR_CORR.get((vr_index[i], vr_index[j]), 1.0)
                K_sq += rho * VR_list[i] * VR_list[j]

        K = math.sqrt(max(K_sq, 0.0))
        list_K.append(K)
        S = max(min(sum(VR_list), K), -K)
        list_S.append(S)

    total_sq = sum(k**2 for k in list_K)
    for i in range(len(currencies)):
        for j in range(len(currencies)):
            if i == j: continue
            g = min(dict_VCR[currencies[i]], dict_VCR[currencies[j]]) / max(dict_VCR[currencies[i]], dict_VCR[currencies[j]])
            total_sq += IR_GAMMA * list_S[i] * list_S[j] * g

    return math.sqrt(max(total_sq, 0.0))


# ============================================================
# Vega Margin: FX
# ============================================================

def fx_vega_margin(crif, calc_ccy='USD'):
    rows = [r for r in crif if r['RiskType'] == 'Risk_FXVol']
    if not rows:
        return 0.0

    all_pairs = [r['Qualifier'] for r in rows if len(r['Qualifier'].strip()) == 6]
    norm_pairs = {}
    for p in all_pairs:
        np_ = norm_pair(p)
        if np_ not in norm_pairs:
            norm_pairs[np_] = p
    pair_list = list(norm_pairs.keys())

    list_VR = []
    list_VCR = []

    for cp in pair_list:
        c1, c2 = cp[:3], cp[3:]
        rev = c2 + c1
        cp_rows = [r for r in rows if r['Qualifier'] in (cp, rev)]

        vg1 = get_fx_vol_group(c1)
        vg2 = get_fx_vol_group(c2)
        RW = FX_RW[vg2][vg1]
        sigma = RW * math.sqrt(365.0/14) / norm.ppf(0.99)

        s = sum(r['AmountUSD'] for r in cp_rows)
        VR_ik = FX_HVR * sigma * s

        cat1, cat2 = get_fx_category(c1), get_fx_category(c2)
        VT_key = (min(cat1, cat2), max(cat1, cat2))
        if VT_key not in FX_VEGA_CT:
            VT_key = (cat1, cat2)
        VT = FX_VEGA_CT.get(VT_key, 200) * 1_000_000

        VCR = max(1.0, math.sqrt(abs(VR_ik) / VT))
        list_VCR.append(VCR)
        VR_k = FX_VRW * VR_ik * VCR
        list_VR.append(VR_k)

    K_sq = 0.0
    n = len(list_VR)
    for i in range(n):
        K_sq += list_VR[i] ** 2
        for j in range(n):
            if i == j: continue
            f = min(list_VCR[i], list_VCR[j]) / max(list_VCR[i], list_VCR[j])
            K_sq += FX_VEGA_CORR * list_VR[i] * list_VR[j] * f

    return math.sqrt(max(K_sq, 0.0))


# ============================================================
# Vega Margin: CreditQ/CreditNonQ/Equity/Commodity
# ============================================================

def _get_vega_rw(risk_type):
    if risk_type == 'Risk_CreditVol': return CREDITQ_VRW
    if risk_type == 'Risk_CreditVolNonQ': return CREDITNONQ_VRW
    return 0

def _get_vega_ct(risk_type, bucket=None):
    if risk_type == 'Risk_CreditVol': return CREDIT_VEGA_CT_Q
    if risk_type == 'Risk_CreditVolNonQ': return CREDIT_VEGA_CT_NQ
    if risk_type == 'Risk_EquityVol': return EQUITY_VEGA_CT.get(bucket, EQUITY_VEGA_CT[0])
    if risk_type == 'Risk_CommodityVol': return COMMODITY_VEGA_CT.get(bucket, 65)
    return 100

def _get_delta_rw_for_vega(risk_type, bucket):
    if risk_type in ('Risk_CreditVol', 'Risk_CreditVolNonQ'): return 0
    if risk_type == 'Risk_EquityVol': return EQUITY_RW.get(bucket, EQUITY_RW[0])
    if risk_type == 'Risk_CommodityVol': return COMMODITY_RW.get(bucket, COMMODITY_RW[1])
    return 0

def _vega_intra_rho(risk_type, bucket, idx_i=None, idx_j=None):
    if risk_type == 'Risk_CreditVol': return _credit_intra_rho('Risk_CreditQ', idx_i, idx_j)
    if risk_type == 'Risk_CreditVolNonQ': return _credit_intra_rho('Risk_CreditNonQ', idx_i, idx_j)
    if risk_type == 'Risk_EquityVol': return EQUITY_CORR.get(bucket, 0)
    if risk_type == 'Risk_CommodityVol': return COMMODITY_CORR.get(bucket, 0)
    return 0

def _vega_cross_bucket(risk_type, b1, b2):
    if risk_type == 'Risk_CreditVol': return CREDITQ_CROSS_BUCKET[b1-1][b2-1]
    if risk_type == 'Risk_CreditVolNonQ': return CREDITNONQ_CROSS_BUCKET
    if risk_type == 'Risk_EquityVol': return EQUITY_CROSS_BUCKET[b1-1][b2-1]
    if risk_type == 'Risk_CommodityVol': return COMMODITY_CROSS_BUCKET[b1-1][b2-1]
    return 0

def other_vega_margin(crif, risk_type, calc_ccy='USD'):
    rows = [r for r in crif if r['RiskType'] == risk_type]
    if not rows:
        return 0.0

    is_credit = risk_type in ('Risk_CreditVol', 'Risk_CreditVolNonQ')
    is_equity = risk_type == 'Risk_EquityVol'

    buckets = unique_ordered([parse_bucket(r['Bucket']) for r in rows])

    K_Res = 0.0
    list_K = []
    list_S = []
    non_res_buckets = []

    for bucket in buckets:
        b_rows = [r for r in rows if parse_bucket(r['Bucket']) == bucket]
        VR_list = []
        VCR_list = []
        vr_index = []

        qualifiers = unique_ordered([r['Qualifier'] for r in b_rows])
        for qual in qualifiers:
            q_rows = [r for r in b_rows if r['Qualifier'] == qual]
            if is_credit:
                VT = _get_vega_ct(risk_type, bucket) * 1_000_000
                s_qual = sum(r['AmountUSD'] for r in q_rows)
                VCR = max(1.0, math.sqrt(abs(s_qual) / VT))
                label2s = unique_ordered([r['Label2'] for r in q_rows])
                for l2 in label2s:
                    l2_rows = [r for r in q_rows if r['Label2'] == l2]
                    tenors = unique_ordered([r['Label1'].lower() for r in l2_rows if r['Label1'].strip()])
                    for tenor in tenors:
                        t_rows = [r for r in l2_rows if r['Label1'].lower() == tenor]
                        s = sum(r['AmountUSD'] for r in t_rows)
                        VRW = _get_vega_rw(risk_type)
                        VR_list.append(VRW * s * VCR)
                        VCR_list.append(VCR)
                        if bucket == 0: vr_index.append('Res')
                        elif risk_type == 'Risk_CreditVol': vr_index.append(qual)
                        else: vr_index.append(l2)
            else:
                RW = _get_delta_rw_for_vega(risk_type, bucket)
                sigma = RW * math.sqrt(365.0/14) / norm.ppf(0.99)
                if is_equity:
                    HVR = EQUITY_HVR
                    VRW = EQUITY_VRW_B12 if bucket == 12 else EQUITY_VRW
                else:
                    HVR = COMMODITY_HVR
                    VRW = COMMODITY_VRW
                s = sum(r['AmountUSD'] for r in q_rows)
                VR_ik = HVR * sigma * s
                VT = _get_vega_ct(risk_type, bucket) * 1_000_000
                VCR = max(1.0, math.sqrt(abs(VR_ik) / VT))
                VCR_list.append(VCR)
                VR_list.append(VR_ik * VRW * VCR)
                vr_index.append('')

        K_sq = 0.0
        n = len(VR_list)
        for i in range(n):
            K_sq += VR_list[i] ** 2
            for j in range(n):
                if i == j: continue
                if is_credit: rho = _vega_intra_rho(risk_type, bucket, vr_index[i], vr_index[j])
                else: rho = _vega_intra_rho(risk_type, bucket)
                f = min(VCR_list[i], VCR_list[j]) / max(VCR_list[i], VCR_list[j]) if VCR_list else 1.0
                K_sq += f * rho * VR_list[i] * VR_list[j]

        K = math.sqrt(max(K_sq, 0.0))
        if bucket == 0:
            K_Res += K
        else:
            list_K.append(K)
            S = max(min(sum(VR_list), K), -K)
            list_S.append(S)
            non_res_buckets.append(bucket)

    total_sq = sum(k**2 for k in list_K)
    for i in range(len(non_res_buckets)):
        for j in range(len(non_res_buckets)):
            if i == j: continue
            gamma = _vega_cross_bucket(risk_type, non_res_buckets[i], non_res_buckets[j])
            total_sq += gamma * list_S[i] * list_S[j]

    return math.sqrt(max(total_sq, 0.0)) + K_Res


# ============================================================
# Curvature Margin: IR
# ============================================================

def ir_curvature_margin(crif, calc_ccy='USD'):
    rows = [r for r in crif if r['RiskType'] in ('Risk_IRVol', 'Risk_InflationVol')]
    if not rows:
        return 0.0

    currencies = unique_ordered([r['Qualifier'] for r in rows])
    list_K = []
    list_S = []
    CVR_sum = 0.0
    CVR_abs_sum = 0.0

    for ccy in currencies:
        ccy_rows = [r for r in rows if r['Qualifier'] == ccy]
        CVR_ik = []
        cvr_index = []

        risk_types_present = unique_ordered([r['RiskType'] for r in ccy_rows])
        for rt in risk_types_present:
            rt_rows = [r for r in ccy_rows if r['RiskType'] == rt]
            tenors = unique_ordered([r['Label1'].lower() for r in rt_rows if r['Label1'].strip()])
            for tenor in tenors:
                t_rows = [r for r in rt_rows if r['Label1'].lower() == tenor]
                s = sum(r['AmountUSD'] for r in t_rows)
                sf = scaling_func(tenor)
                CVR = sf * s
                CVR_ik.append(CVR)
                CVR_sum += CVR
                CVR_abs_sum += abs(CVR)
                cvr_index.append(tenor if rt == 'Risk_IRVol' else 'Inf')

        K_sq = 0.0
        n = len(CVR_ik)
        for i in range(n):
            K_sq += CVR_ik[i] ** 2
            for j in range(n):
                if i == j: continue
                if cvr_index[i] == 'Inf' and cvr_index[j] == 'Inf': rho = 1.0
                elif cvr_index[i] == 'Inf' or cvr_index[j] == 'Inf': rho = INFLATION_CORR
                else: rho = IR_CORR.get((cvr_index[i], cvr_index[j]), 1.0)
                K_sq += (rho**2) * CVR_ik[i] * CVR_ik[j]

        K = math.sqrt(max(K_sq, 0.0))
        list_K.append(K)
        S = max(min(sum(CVR_ik), K), -K)
        list_S.append(S)

    if CVR_abs_sum == 0:
        return 0.0

    theta = min(CVR_sum / CVR_abs_sum, 0)
    _lambda = (norm.ppf(0.995)**2 - 1) * (1 + theta) - theta

    K_total_sq = sum(k**2 for k in list_K)
    for i in range(len(list_S)):
        for j in range(len(list_S)):
            if i == j: continue
            K_total_sq += list_S[i] * list_S[j] * (IR_GAMMA**2)

    return max(CVR_sum + _lambda * math.sqrt(max(K_total_sq, 0.0)), 0) / (IR_HVR**2)


# ============================================================
# Curvature Margin: FX
# ============================================================

def fx_curvature_margin(crif, calc_ccy='USD'):
    rows = [r for r in crif if r['RiskType'] == 'Risk_FXVol']
    if not rows:
        return 0.0

    all_pairs = [r['Qualifier'] for r in rows if len(r['Qualifier'].strip()) == 6]
    norm_pairs = {}
    for p in all_pairs:
        np_ = norm_pair(p)
        if np_ not in norm_pairs:
            norm_pairs[np_] = p
    pair_list = list(norm_pairs.keys())

    list_CVR = []
    for cp in pair_list:
        c1, c2 = cp[:3], cp[3:]
        rev = c2 + c1
        cp_rows = [r for r in rows if r['Qualifier'] in (cp, rev)]

        vg1 = get_fx_vol_group(c1)
        vg2 = get_fx_vol_group(c2)
        RW = FX_RW[vg2][vg1]
        sigma = RW * math.sqrt(365.0/14) / norm.ppf(0.99)

        CVR = 0.0
        for r in cp_rows:
            tenor = r['Label1'] if r['Label1'] else '2w'
            sf = scaling_func(tenor)
            CVR += sf * sigma * r['AmountUSD']
        list_CVR.append(CVR)

    K_sq = 0.0
    n = len(list_CVR)
    for i in range(n):
        K_sq += list_CVR[i] ** 2
        for j in range(n):
            if i == j: continue
            K_sq += (FX_VEGA_CORR**2) * list_CVR[i] * list_CVR[j]

    K = math.sqrt(max(K_sq, 0.0))

    CVR_sum = sum(list_CVR)
    CVR_abs_sum = sum(abs(c) for c in list_CVR)

    if CVR_abs_sum == 0: theta = 0
    else: theta = min(CVR_sum / CVR_abs_sum, 0)

    _lambda = (norm.ppf(0.995)**2 - 1) * (1 + theta) - theta

    return max(CVR_sum + _lambda * K, 0)


# ============================================================
# Curvature Margin: CreditQ/CreditNonQ/Equity/Commodity
# ============================================================

def other_curvature_margin(crif, risk_type, calc_ccy='USD'):
    rows = [r for r in crif if r['RiskType'] == risk_type]
    if not rows:
        return 0.0

    is_credit = risk_type in ('Risk_CreditVol', 'Risk_CreditVolNonQ')
    is_equity = risk_type == 'Risk_EquityVol'

    buckets = unique_ordered([parse_bucket(r['Bucket']) for r in rows])

    K_Res = 0.0
    list_K = []
    list_S = []
    non_res_buckets = []
    CVR_sum = 0.0
    CVR_abs_sum = 0.0
    CVR_sum_res = 0.0
    CVR_abs_sum_res = 0.0

    for bucket in buckets:
        b_rows = [r for r in rows if parse_bucket(r['Bucket']) == bucket]
        CVR_i = []
        cvr_index = []

        qualifiers = unique_ordered([r['Qualifier'] for r in b_rows])
        for qual in qualifiers:
            q_rows = [r for r in b_rows if r['Qualifier'] == qual]
            if is_credit:
                label2s = unique_ordered([r['Label2'] for r in q_rows])
                for l2 in label2s:
                    l2_rows = [r for r in q_rows if r['Label2'] == l2]
                    tenors = unique_ordered([r['Label1'].lower() for r in l2_rows if r['Label1'].strip()])
                    for tenor in tenors:
                        t_rows = [r for r in l2_rows if r['Label1'].lower() == tenor]
                        s = sum(r['AmountUSD'] for r in t_rows)
                        sf = scaling_func(tenor)
                        CVR_i.append(sf * s)
                        if bucket == 0: cvr_index.append('Res')
                        elif risk_type == 'Risk_CreditVol': cvr_index.append(qual)
                        else: cvr_index.append(l2)
            else:
                RW = _get_delta_rw_for_vega(risk_type, bucket)
                sigma = RW * math.sqrt(365.0/14) / norm.ppf(0.99)
                if is_equity and bucket == 12: sigma = 0
                tenor_list = [r['Label1'] for r in q_rows]
                vega_list = [r['AmountUSD'] for r in q_rows]
                cvr_sum_qual = 0.0
                for tenor, vega in zip(tenor_list, vega_list):
                    if not tenor.strip(): tenor = '2w'
                    cvr_sum_qual += scaling_func(tenor) * sigma * vega
                CVR_i.append(cvr_sum_qual)
                cvr_index.append('')

        K_sq = 0.0
        n = len(CVR_i)
        for i in range(n):
            K_sq += CVR_i[i] ** 2
            for j in range(n):
                if i == j: continue
                if is_credit:
                    rho = _credit_intra_rho(
                        'Risk_CreditQ' if risk_type == 'Risk_CreditVol' else 'Risk_CreditNonQ',
                        cvr_index[i], cvr_index[j])
                else:
                    rho = EQUITY_CORR.get(bucket, 0) if is_equity else COMMODITY_CORR.get(bucket, 0)
                K_sq += (rho**2) * CVR_i[i] * CVR_i[j]

        K = math.sqrt(max(K_sq, 0.0))

        if bucket == 0:
            K_Res += K
            CVR_sum_res += sum(CVR_i)
            CVR_abs_sum_res += sum(abs(c) for c in CVR_i)
        else:
            if is_equity and bucket == 12:
                pass
            else:
                list_K.append(K)
                S = max(min(sum(CVR_i), K), -K)
                list_S.append(S)
                non_res_buckets.append(bucket)
                CVR_sum += sum(CVR_i)
                CVR_abs_sum += sum(abs(c) for c in CVR_i)

    if is_equity and not list_K and K_Res == 0:
        return 0.0

    if CVR_abs_sum > 0:
        theta = min(CVR_sum / CVR_abs_sum, 0)
        _lambda = (norm.ppf(0.995)**2 - 1) * (1 + theta) - theta
    else:
        _lambda = 0

    if CVR_abs_sum_res > 0:
        theta_res = min(CVR_sum_res / CVR_abs_sum_res, 0)
        _lambda_res = (norm.ppf(0.995)**2 - 1) * (1 + theta_res) - theta_res
    else:
        _lambda_res = 0

    K_total_sq = sum(k**2 for k in list_K)
    for i in range(len(non_res_buckets)):
        for j in range(len(non_res_buckets)):
            if i == j: continue
            if risk_type == 'Risk_CreditVolNonQ': gamma = CREDITNONQ_CROSS_BUCKET
            elif risk_type == 'Risk_CreditVol': gamma = CREDITQ_CROSS_BUCKET[non_res_buckets[i]-1][non_res_buckets[j]-1]
            elif risk_type == 'Risk_EquityVol': gamma = EQUITY_CROSS_BUCKET[non_res_buckets[i]-1][non_res_buckets[j]-1]
            else: gamma = COMMODITY_CROSS_BUCKET[non_res_buckets[i]-1][non_res_buckets[j]-1]
            K_total_sq += list_S[i] * list_S[j] * (gamma**2)

    curv_non_res = max(CVR_sum + _lambda * math.sqrt(max(K_total_sq, 0.0)), 0)
    curv_res = max(CVR_sum_res + _lambda_res * K_Res, 0)

    return curv_non_res + curv_res


# ============================================================
# Total SIMM Calculation
# ============================================================

def compute_simm(crif_path, calc_ccy='USD'):
    crif = read_crif(crif_path)
    product_classes = unique_ordered([r['ProductClass'] for r in crif if r['ProductClass']])

    total_simm = 0.0
    total_addon = 0.0
    breakdown_delta = 0.0
    breakdown_vega = 0.0
    breakdown_curv = 0.0
    breakdown_bc = 0.0

    for pc in product_classes:
        pc_crif = [r for r in crif if r['ProductClass'] == pc]

        margins = {}
        d_ir = ir_delta_margin(pc_crif, calc_ccy)
        d_fx = fx_delta_margin(pc_crif, calc_ccy)
        d_cq = other_delta_margin(pc_crif, 'Risk_CreditQ', calc_ccy)
        d_cnq = other_delta_margin(pc_crif, 'Risk_CreditNonQ', calc_ccy)
        d_eq = other_delta_margin(pc_crif, 'Risk_Equity', calc_ccy)
        d_cm = other_delta_margin(pc_crif, 'Risk_Commodity', calc_ccy)

        v_ir = ir_vega_margin(pc_crif, calc_ccy)
        v_fx = fx_vega_margin(pc_crif, calc_ccy)
        v_cq = other_vega_margin(pc_crif, 'Risk_CreditVol', calc_ccy)
        v_cnq = other_vega_margin(pc_crif, 'Risk_CreditVolNonQ', calc_ccy)
        v_eq = other_vega_margin(pc_crif, 'Risk_EquityVol', calc_ccy)
        v_cm = other_vega_margin(pc_crif, 'Risk_CommodityVol', calc_ccy)

        c_ir = ir_curvature_margin(pc_crif, calc_ccy)
        c_fx = fx_curvature_margin(pc_crif, calc_ccy)
        c_cq = other_curvature_margin(pc_crif, 'Risk_CreditVol', calc_ccy)
        c_cnq = other_curvature_margin(pc_crif, 'Risk_CreditVolNonQ', calc_ccy)
        c_eq = other_curvature_margin(pc_crif, 'Risk_EquityVol', calc_ccy)
        c_cm = other_curvature_margin(pc_crif, 'Risk_CommodityVol', calc_ccy)

        bc = base_corr_margin(pc_crif)

        margins['Rates'] = d_ir + v_ir + c_ir
        margins['CreditQ'] = d_cq + v_cq + c_cq + bc
        margins['CreditNonQ'] = d_cnq + v_cnq + c_cnq
        margins['Equity'] = d_eq + v_eq + c_eq
        margins['Commodity'] = d_cm + v_cm + c_cm
        margins['FX'] = d_fx + v_fx + c_fx

        breakdown_delta += d_ir + d_fx + d_cq + d_cnq + d_eq + d_cm
        breakdown_vega += v_ir + v_fx + v_cq + v_cnq + v_eq + v_cm
        breakdown_curv += c_ir + c_fx + c_cq + c_cnq + c_eq + c_cm
        breakdown_bc += bc

        rc_list = RISK_CLASS_NAMES
        simm_product = 0.0
        for i in range(6):
            for j in range(6):
                psi = 1.0 if i == j else RISK_CLASS_CORR[i][j]
                simm_product += psi * margins[rc_list[i]] * margins[rc_list[j]]

        simm_pc = math.sqrt(max(simm_product, 0.0))
        total_simm += simm_pc

        # Add-on
        addon_pc = 0.0
        fixed_rows = [r for r in pc_crif if r['RiskType'] == 'Param_AddOnFixedAmount']
        addon_pc += sum(r['AmountUSD'] for r in fixed_rows)

        factor_rows = [r for r in pc_crif if r['RiskType'] == 'Param_AddOnNotionalFactor']
        notional_rows = [r for r in pc_crif if r['RiskType'] == 'Notional']
        quals = unique_ordered([r['Qualifier'] for r in factor_rows] + [r['Qualifier'] for r in notional_rows])
        for q in quals:
            f_sum = sum(r['AmountUSD'] for r in factor_rows if r['Qualifier'] == q) / 100.0
            n_sum = sum(r['AmountUSD'] for r in notional_rows if r['Qualifier'] == q)
            addon_pc += f_sum * n_sum

        mult_rows = [r for r in pc_crif if r['RiskType'] == 'Param_ProductClassMultiplier']
        if mult_rows:
            ms = sum(r['AmountUSD'] for r in mult_rows) - 1
            addon_pc += simm_pc * ms

        total_addon += addon_pc

    total_simm += total_addon

    def fmt(v):
        if v == 0 or abs(v) < 0.5: return '-'
        return str(int(round(v)))

    return (
        breakdown_delta, breakdown_vega, breakdown_curv, breakdown_bc, total_addon, total_simm,
        f"SIMM Delta,SIMM Vega,SIMM Curvature,SIMM Base Corr,SIMM AddOn,SIMM Benchmark\n"
        f"{fmt(breakdown_delta)},{fmt(breakdown_vega)},{fmt(breakdown_curv)},{fmt(breakdown_bc)},{fmt(total_addon)},{str(int(round(total_simm)))}"
    )


def write_results_db(test_id, delta, vega, curvature, base_corr, addon, benchmark, db_path="/app/simm_results.db"):
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS margin_results (
            id TEXT PRIMARY KEY,
            delta REAL, vega REAL, curvature REAL,
            base_corr REAL, addon REAL, benchmark REAL
        )
    """)
    conn.execute(
        "INSERT OR REPLACE INTO margin_results VALUES (?,?,?,?,?,?,?)",
        (test_id, delta, vega, curvature, base_corr, addon, benchmark)
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 simm_calc.py <crif_csv_path>", file=sys.stderr)
        sys.exit(1)

    crif_path = sys.argv[1]
    load_params()

    delta, vega, curvature, base_corr, addon, benchmark, csv_output = compute_simm(crif_path)
    print(csv_output)

    # Extract test ID from filename
    basename = os.path.basename(crif_path)
    test_id = basename.replace('_crif.csv', '').replace('.csv', '')
    write_results_db(test_id, delta, vega, curvature, base_corr, addon, benchmark)
