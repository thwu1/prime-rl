#!/usr/bin/env python3
"""Multi-agency MBS Analytics Engine.

Processes Freddie Mac loan-level data and Ginnie Mae pool factor data,
stores everything in SQLite, and produces a JSON analytics report.
"""

import argparse
import json
import math
import os
import sqlite3
import sys
from collections import defaultdict


# ============================================================
# Parsing: Freddie Mac
# ============================================================

def parse_freddie_origination(filepath):
    loans = {}
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            fields = line.split("|")
            if len(fields) < 22:
                continue
            seq = fields[19].strip()

            def sf(s):
                s = s.strip()
                return float(s) if s and s not in ("999", "") else None

            def si(s):
                s = s.strip()
                return int(s) if s and s not in ("999", "9999", "99", "") else None

            loans[seq] = {
                "credit_score": si(fields[0]),
                "first_payment_date": fields[1].strip(),
                "first_time_buyer": fields[2].strip(),
                "maturity_date": fields[3].strip(),
                "msa": fields[4].strip(),
                "mi_pct": si(fields[5]),
                "num_units": si(fields[6]),
                "occ_status": fields[7].strip(),
                "cltv": si(fields[8]),
                "dti": si(fields[9]),
                "orig_upb": sf(fields[10]),
                "ltv": si(fields[11]),
                "orig_rate": sf(fields[12]),
                "channel": fields[13].strip(),
                "ppm_flag": fields[14].strip(),
                "amort_type": fields[15].strip(),
                "state": fields[16].strip(),
                "prop_type": fields[17].strip(),
                "zip_code": fields[18].strip(),
                "loan_seq": seq,
                "purpose": fields[20].strip(),
                "orig_term": si(fields[21]),
                "num_borrowers": si(fields[22]) if len(fields) > 22 else None,
                "seller": fields[23].strip() if len(fields) > 23 else "",
                "servicer": fields[24].strip() if len(fields) > 24 else "",
            }
    return loans


def parse_freddie_performance(filepath):
    records = defaultdict(list)
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            fields = line.split("|")
            if len(fields) < 12:
                continue
            seq = fields[0].strip()

            def sf(s):
                s = s.strip() if s else ""
                if s == "" or s == "U":
                    return 0.0
                try:
                    return float(s)
                except ValueError:
                    return 0.0

            def si(s):
                s = s.strip() if s else ""
                if s == "" or s in ("RA",):
                    return None
                try:
                    return int(s)
                except ValueError:
                    return None

            rec = {
                "loan_seq": seq,
                "period": fields[1].strip(),
                "cur_upb": sf(fields[2]),
                "dlq_status": fields[3].strip(),
                "loan_age": si(fields[4]),
                "rem_months": si(fields[5]),
                "defect_date": fields[6].strip() if len(fields) > 6 else "",
                "mod_flag": fields[7].strip() if len(fields) > 7 else "",
                "zb_code": fields[8].strip() if len(fields) > 8 else "",
                "zb_date": fields[9].strip() if len(fields) > 9 else "",
                "cur_rate": sf(fields[10]),
                "deferred_upb": sf(fields[11]) if len(fields) > 11 else 0.0,
                "ddlpi": fields[12].strip() if len(fields) > 12 else "",
                "mi_recoveries": sf(fields[13]) if len(fields) > 13 else 0.0,
                "net_sale_proceeds": sf(fields[14]) if len(fields) > 14 else 0.0,
                "non_mi_recoveries": sf(fields[15]) if len(fields) > 15 else 0.0,
                "expenses": sf(fields[16]) if len(fields) > 16 else 0.0,
                "legal_costs": sf(fields[17]) if len(fields) > 17 else 0.0,
                "maint_costs": sf(fields[18]) if len(fields) > 18 else 0.0,
                "taxes_insurance": sf(fields[19]) if len(fields) > 19 else 0.0,
                "misc_expenses": sf(fields[20]) if len(fields) > 20 else 0.0,
                "actual_loss": sf(fields[21]) if len(fields) > 21 else 0.0,
                "mod_cost": sf(fields[22]) if len(fields) > 22 else 0.0,
                "step_mod_flag": fields[23].strip() if len(fields) > 23 else "",
                "deferred_plan": fields[24].strip() if len(fields) > 24 else "",
                "eltv": si(fields[25]) if len(fields) > 25 else None,
                "zb_removal_upb": sf(fields[26]) if len(fields) > 26 else 0.0,
                "dlq_accrued_interest": sf(fields[27]) if len(fields) > 27 else 0.0,
                "disaster_flag": fields[28].strip() if len(fields) > 28 else "",
                "borr_assist": fields[29].strip() if len(fields) > 29 else "",
                "cur_month_mod_cost": sf(fields[30]) if len(fields) > 30 else 0.0,
                "ib_upb": sf(fields[31]) if len(fields) > 31 else 0.0,
            }
            records[seq].append(rec)
    return records


# ============================================================
# Parsing: Ginnie Mae Fixed-Width
# ============================================================

def parse_ginniemae_factors(filepath):
    records = defaultdict(list)
    with open(filepath) as f:
        for line in f:
            line = line.rstrip("\n").rstrip("\r")
            if not line.strip():
                continue
            if len(line) < 90:
                line = line.ljust(90)

            pool_id = line[0:10].strip()
            report_date = line[10:18].strip()
            orig_face = float(line[18:33].strip())
            curr_face = float(line[33:48].strip())
            pool_factor = float(line[48:60].strip())
            sec_rate = float(line[60:68].strip())
            wac = float(line[68:76].strip())
            wam = int(line[76:80].strip())
            wala = int(line[80:84].strip())
            loan_count = int(line[84:90].strip())

            records[pool_id].append({
                "pool_id": pool_id,
                "report_date": report_date,
                "original_face": orig_face,
                "current_face": curr_face,
                "pool_factor": pool_factor,
                "security_rate": sec_rate,
                "wac": wac,
                "wam": wam,
                "wala": wala,
                "loan_count": loan_count,
            })

    for pool_id in records:
        records[pool_id].sort(key=lambda x: x["report_date"])
    return records


# ============================================================
# Pool Assignment
# ============================================================

def get_pool_id(loan_seq):
    if len(loan_seq) >= 5 and loan_seq[0] == "F":
        yy = loan_seq[1:3]
        qn = loan_seq[3:5]
        return f"20{yy}{qn}"
    return "UNKNOWN"


# ============================================================
# Financial Math
# ============================================================

def monthly_payment(principal, annual_rate, term_months):
    r = annual_rate / 12.0
    if r == 0 or term_months <= 0:
        return principal / max(term_months, 1)
    return principal * (r * (1 + r) ** term_months) / ((1 + r) ** term_months - 1)


def smm_from_cpr(cpr):
    if cpr >= 1.0:
        return 1.0
    return 1.0 - (1.0 - cpr) ** (1.0 / 12.0)


def cpr_from_smm(smm):
    if smm >= 1.0:
        return 1.0
    return 1.0 - (1.0 - smm) ** 12.0


def psa_cpr(month, psa_speed=1.0):
    if month <= 30:
        cpr = 0.002 * month
    else:
        cpr = 0.06
    return cpr * psa_speed


def psa_smm(month, psa_speed=1.0):
    return smm_from_cpr(psa_cpr(month, psa_speed))


# ============================================================
# Pool Metrics
# ============================================================

def compute_pool_metrics(loans, perf_records):
    pool_loans = defaultdict(list)
    for seq in loans:
        pool_id = get_pool_id(seq)
        pool_loans[pool_id].append(seq)

    pool_orig_upb = {}
    for pool_id, seqs in pool_loans.items():
        pool_orig_upb[pool_id] = sum(loans[s]["orig_upb"] for s in seqs)

    pool_periods = defaultdict(set)
    for seq, recs in perf_records.items():
        pool_id = get_pool_id(seq)
        for r in recs:
            pool_periods[pool_id].add(r["period"])

    result = {}
    for pool_id in sorted(pool_loans.keys()):
        seqs = pool_loans[pool_id]
        periods = sorted(pool_periods[pool_id])
        orig_upb = pool_orig_upb[pool_id]
        period_metrics = []

        for period in periods:
            active_loans = 0
            total_upb = 0.0
            wac_num = 0.0
            wam_num = 0.0
            wala_num = 0.0
            dlq_30 = 0
            dlq_60 = 0
            dlq_90plus = 0

            for seq in seqs:
                recs = perf_records.get(seq, [])
                rec = None
                for r in recs:
                    if r["period"] == period:
                        rec = r
                        break
                if rec is None:
                    continue
                if rec["zb_code"] or rec["cur_upb"] <= 0:
                    continue

                active_loans += 1
                upb = rec["cur_upb"]
                total_upb += upb
                wac_num += rec["cur_rate"] * upb
                if rec["rem_months"] is not None:
                    wam_num += rec["rem_months"] * upb
                if rec["loan_age"] is not None:
                    wala_num += rec["loan_age"] * upb

                dlq = rec["dlq_status"]
                if dlq == "1":
                    dlq_30 += 1
                elif dlq == "2":
                    dlq_60 += 1
                elif dlq not in ("0", "", "RA"):
                    try:
                        if int(dlq) >= 3:
                            dlq_90plus += 1
                    except ValueError:
                        pass

            wac = (wac_num / total_upb / 100.0) if total_upb > 0 else 0.0
            wam = (wam_num / total_upb) if total_upb > 0 else 0.0
            wala = (wala_num / total_upb) if total_upb > 0 else 0.0
            pf = total_upb / orig_upb if orig_upb > 0 else 0.0

            period_metrics.append({
                "period": period,
                "active_loans": active_loans,
                "total_upb": round(total_upb, 2),
                "pool_factor": round(pf, 8),
                "wac": round(wac, 8),
                "wam": round(wam, 8),
                "wala": round(wala, 8),
                "dlq_30_count": dlq_30,
                "dlq_60_count": dlq_60,
                "dlq_90plus_count": dlq_90plus,
            })

        result[pool_id] = period_metrics
    return result, pool_loans, pool_orig_upb


# ============================================================
# Prepayment
# ============================================================

def compute_prepayment(loans, perf_records, pool_loans):
    result = {}
    for pool_id, seqs in sorted(pool_loans.items()):
        all_periods = set()
        for seq in seqs:
            for r in perf_records.get(seq, []):
                all_periods.add(r["period"])
        periods = sorted(all_periods)

        if len(periods) < 2:
            result[pool_id] = []
            continue

        loan_by_period = {}
        for seq in seqs:
            lookup = {}
            for r in perf_records.get(seq, []):
                lookup[r["period"]] = r
            loan_by_period[seq] = lookup

        prepay_records = []
        for i in range(1, len(periods)):
            prev_period = periods[i - 1]
            cur_period = periods[i]

            total_beginning_upb = 0.0
            total_scheduled_principal = 0.0
            total_prepayment = 0.0
            total_wala = 0.0
            total_wala_weight = 0.0

            for seq in seqs:
                prev_rec = loan_by_period[seq].get(prev_period)
                cur_rec = loan_by_period[seq].get(cur_period)

                if prev_rec is None or prev_rec["zb_code"] or prev_rec["cur_upb"] <= 0:
                    continue

                beg_upb = prev_rec["cur_upb"]
                total_beginning_upb += beg_upb

                if cur_rec and cur_rec["loan_age"] is not None:
                    total_wala += cur_rec["loan_age"] * beg_upb
                    total_wala_weight += beg_upb

                dlq = prev_rec["dlq_status"]
                is_delinquent = dlq not in ("0", "")

                sched_prin = 0.0
                if not is_delinquent:
                    loan_info = loans.get(seq)
                    if loan_info:
                        rate = prev_rec["cur_rate"] / 100.0
                        pmt = monthly_payment(
                            beg_upb, rate,
                            prev_rec["rem_months"] if prev_rec["rem_months"] else 360
                        )
                        interest = beg_upb * rate / 12.0
                        sched_prin = max(pmt - interest, 0)

                total_scheduled_principal += sched_prin

                if cur_rec is None:
                    pass
                elif cur_rec["zb_code"] == "01":
                    removal_upb = cur_rec["zb_removal_upb"]
                    if removal_upb > 0:
                        total_prepayment += max(removal_upb - sched_prin, 0)
                elif cur_rec["zb_code"]:
                    pass
                else:
                    end_upb = cur_rec["cur_upb"]
                    actual_reduction = beg_upb - end_upb
                    unscheduled = actual_reduction - sched_prin
                    if unscheduled > 0 and not is_delinquent:
                        total_prepayment += unscheduled

            denom = total_beginning_upb - total_scheduled_principal
            if denom > 0 and total_prepayment >= 0:
                smm = total_prepayment / denom
            else:
                smm = 0.0

            smm = min(max(smm, 0.0), 1.0)
            cpr = cpr_from_smm(smm)

            pool_wala = (total_wala / total_wala_weight) if total_wala_weight > 0 else 1
            benchmark_cpr = psa_cpr(pool_wala, 1.0)
            implied_psa = cpr / benchmark_cpr if benchmark_cpr > 0 else 0.0

            prepay_records.append({
                "period": cur_period,
                "smm": round(smm, 8),
                "cpr": round(cpr, 8),
                "implied_psa": round(implied_psa, 8),
            })

        result[pool_id] = prepay_records
    return result


# ============================================================
# Losses
# ============================================================

def compute_losses(perf_records):
    loss_zb_codes = {"02", "03", "09", "15"}
    losses = []
    for seq, recs in sorted(perf_records.items()):
        for rec in recs:
            if rec["zb_code"] in loss_zb_codes:
                zb_removal = rec["zb_removal_upb"]
                dai = rec["dlq_accrued_interest"]
                nsp = rec["net_sale_proceeds"]
                mi = rec["mi_recoveries"]
                non_mi = rec["non_mi_recoveries"]
                expenses = rec["expenses"]
                computed_loss = (zb_removal + dai) - nsp - mi - non_mi + expenses
                losses.append({
                    "loan_seq": seq,
                    "zb_code": rec["zb_code"],
                    "zb_date": rec["zb_date"],
                    "zb_removal_upb": round(zb_removal, 2),
                    "mi_recoveries": round(mi, 2),
                    "net_sale_proceeds": round(nsp, 2),
                    "non_mi_recoveries": round(non_mi, 2),
                    "expenses": round(expenses, 2),
                    "dlq_accrued_interest": round(dai, 2),
                    "computed_actual_loss": round(computed_loss, 2),
                })
                break
    return losses


# ============================================================
# Cash Flow Projection
# ============================================================

def compute_cashflow_projection(loans, perf_records, pool_loans, pool_orig_upb,
                                psa_speed, projection_months):
    result = {}
    for pool_id, seqs in sorted(pool_loans.items()):
        orig_upb = pool_orig_upb[pool_id]
        last_period = ""
        active_loans_state = []

        for seq in seqs:
            recs = perf_records.get(seq, [])
            if not recs:
                continue
            last_rec = recs[-1]
            for r in recs:
                if r["period"] > last_period:
                    last_period = r["period"]
            if not last_rec["zb_code"] and last_rec["cur_upb"] > 0:
                loan_info = loans.get(seq)
                if loan_info:
                    active_loans_state.append({
                        "seq": seq,
                        "upb": last_rec["cur_upb"],
                        "rate": last_rec["cur_rate"] / 100.0,
                        "rem_months": last_rec["rem_months"] if last_rec["rem_months"] else 360,
                        "loan_age": last_rec["loan_age"] if last_rec["loan_age"] else 0,
                    })

        if not active_loans_state:
            result[pool_id] = []
            continue

        total_active_upb = sum(ls["upb"] for ls in active_loans_state)
        pool_wac = sum(ls["rate"] * ls["upb"] for ls in active_loans_state) / total_active_upb
        pool_wam = sum(ls["rem_months"] * ls["upb"] for ls in active_loans_state) / total_active_upb
        pool_wala_val = sum(ls["loan_age"] * ls["upb"] for ls in active_loans_state) / total_active_upb

        balance = total_active_upb
        projection = []

        for month in range(1, projection_months + 1):
            if balance <= 0.01:
                projection.append({
                    "month": month, "beginning_upb": 0.0,
                    "scheduled_principal": 0.0, "prepayment": 0.0,
                    "total_principal": 0.0, "ending_upb": 0.0,
                    "pool_factor": 0.0, "interest": 0.0,
                })
                continue

            beg = balance
            rem = max(pool_wam - month + 1, 1)
            r = pool_wac / 12.0
            pmt = monthly_payment(beg, pool_wac, rem)
            interest = beg * r
            sched_prin = max(pmt - interest, 0)
            cur_wala = pool_wala_val + month
            smm = psa_smm(cur_wala, psa_speed)
            prepayment = (beg - sched_prin) * smm
            total_prin = sched_prin + prepayment
            if total_prin > beg:
                total_prin = beg
                prepayment = total_prin - sched_prin
            ending = beg - total_prin
            pf = ending / orig_upb if orig_upb > 0 else 0.0

            projection.append({
                "month": month,
                "beginning_upb": round(beg, 2),
                "scheduled_principal": round(sched_prin, 2),
                "prepayment": round(prepayment, 2),
                "total_principal": round(total_prin, 2),
                "ending_upb": round(ending, 2),
                "pool_factor": round(pf, 8),
                "interest": round(interest, 2),
            })
            balance = ending

        result[pool_id] = projection
    return result


# ============================================================
# SQLite Database
# ============================================================

def create_database(db_path, loans, perf_records, gm_records,
                    pool_metrics_data, pool_loans, pool_orig_upb,
                    prepayment_data):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # freddie_origination
    c.execute("""CREATE TABLE freddie_origination (
        loan_seq TEXT PRIMARY KEY,
        credit_score INTEGER,
        first_payment_date TEXT,
        first_time_buyer TEXT,
        maturity_date TEXT,
        msa TEXT,
        mi_pct INTEGER,
        num_units INTEGER,
        occ_status TEXT,
        cltv INTEGER,
        dti INTEGER,
        orig_upb REAL,
        ltv INTEGER,
        orig_rate REAL,
        channel TEXT,
        ppm_flag TEXT,
        amort_type TEXT,
        state TEXT,
        prop_type TEXT,
        zip_code TEXT,
        purpose TEXT,
        orig_term INTEGER,
        num_borrowers INTEGER,
        seller TEXT,
        servicer TEXT
    )""")

    for seq, loan in loans.items():
        c.execute(
            "INSERT INTO freddie_origination VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (loan["loan_seq"], loan["credit_score"], loan["first_payment_date"],
             loan["first_time_buyer"], loan["maturity_date"], loan["msa"],
             loan["mi_pct"], loan["num_units"], loan["occ_status"],
             loan["cltv"], loan["dti"], loan["orig_upb"], loan["ltv"],
             loan["orig_rate"], loan["channel"], loan["ppm_flag"],
             loan["amort_type"], loan["state"], loan["prop_type"],
             loan["zip_code"], loan["purpose"], loan["orig_term"],
             loan["num_borrowers"], loan["seller"], loan["servicer"])
        )

    # freddie_performance
    c.execute("""CREATE TABLE freddie_performance (
        loan_seq TEXT, period TEXT, cur_upb REAL, dlq_status TEXT,
        loan_age INTEGER, rem_months INTEGER, defect_date TEXT,
        mod_flag TEXT, zb_code TEXT, zb_date TEXT, cur_rate REAL,
        deferred_upb REAL, ddlpi TEXT, mi_recoveries REAL,
        net_sale_proceeds REAL, non_mi_recoveries REAL, expenses REAL,
        legal_costs REAL, maint_costs REAL, taxes_insurance REAL,
        misc_expenses REAL, actual_loss REAL, mod_cost REAL,
        step_mod_flag TEXT, deferred_plan TEXT, eltv INTEGER,
        zb_removal_upb REAL, dlq_accrued_interest REAL,
        disaster_flag TEXT, borr_assist TEXT,
        cur_month_mod_cost REAL, ib_upb REAL
    )""")

    for seq, recs in perf_records.items():
        for rec in recs:
            c.execute(
                "INSERT INTO freddie_performance VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (rec["loan_seq"], rec["period"], rec["cur_upb"], rec["dlq_status"],
                 rec["loan_age"], rec["rem_months"], rec["defect_date"], rec["mod_flag"],
                 rec["zb_code"], rec["zb_date"], rec["cur_rate"], rec["deferred_upb"],
                 rec["ddlpi"], rec["mi_recoveries"], rec["net_sale_proceeds"],
                 rec["non_mi_recoveries"], rec["expenses"], rec["legal_costs"],
                 rec["maint_costs"], rec["taxes_insurance"], rec["misc_expenses"],
                 rec["actual_loss"], rec["mod_cost"], rec["step_mod_flag"],
                 rec["deferred_plan"], rec["eltv"], rec["zb_removal_upb"],
                 rec["dlq_accrued_interest"], rec["disaster_flag"], rec["borr_assist"],
                 rec["cur_month_mod_cost"], rec["ib_upb"])
            )

    # ginniemae_factors
    c.execute("""CREATE TABLE ginniemae_factors (
        pool_id TEXT, report_date TEXT, original_face REAL,
        current_face REAL, pool_factor REAL, security_rate REAL,
        wac REAL, wam INTEGER, wala INTEGER, loan_count INTEGER
    )""")

    for pool_id, recs in gm_records.items():
        for rec in recs:
            c.execute(
                "INSERT INTO ginniemae_factors VALUES (?,?,?,?,?,?,?,?,?,?)",
                (rec["pool_id"], rec["report_date"], rec["original_face"],
                 rec["current_face"], rec["pool_factor"], rec["security_rate"],
                 rec["wac"], rec["wam"], rec["wala"], rec["loan_count"])
            )

    # pool_metrics
    c.execute("""CREATE TABLE pool_metrics (
        pool_id TEXT, period TEXT, active_loans INTEGER,
        total_upb REAL, pool_factor REAL, wac REAL,
        wam REAL, wala REAL, dlq_30_count INTEGER,
        dlq_60_count INTEGER, dlq_90plus_count INTEGER
    )""")

    for pool_id, metrics_list in pool_metrics_data.items():
        for m in metrics_list:
            c.execute(
                "INSERT INTO pool_metrics VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (pool_id, m["period"], m["active_loans"], m["total_upb"],
                 m["pool_factor"], m["wac"], m["wam"], m["wala"],
                 m["dlq_30_count"], m["dlq_60_count"], m["dlq_90plus_count"])
            )

    # cross_agency_summary
    c.execute("""CREATE TABLE cross_agency_summary (
        pool_id TEXT, agency TEXT, total_upb REAL,
        pool_factor REAL, wac REAL, wam REAL, loan_count INTEGER
    )""")

    for pool_id, metrics_list in pool_metrics_data.items():
        if metrics_list:
            last = metrics_list[-1]
            c.execute(
                "INSERT INTO cross_agency_summary VALUES (?,?,?,?,?,?,?)",
                (pool_id, "FREDDIE", last["total_upb"], last["pool_factor"],
                 last["wac"], last["wam"], last["active_loans"])
            )

    for pool_id, recs in gm_records.items():
        if recs:
            last = recs[-1]
            c.execute(
                "INSERT INTO cross_agency_summary VALUES (?,?,?,?,?,?,?)",
                (pool_id, "GINNIEMAE", last["current_face"], last["pool_factor"],
                 last["wac"], last["wam"], last["loan_count"])
            )

    # prepayment_detail
    c.execute("""CREATE TABLE prepayment_detail (
        pool_id TEXT, period TEXT, smm REAL, cpr REAL, implied_psa REAL
    )""")

    for pool_id, recs in prepayment_data.items():
        for rec in recs:
            c.execute(
                "INSERT INTO prepayment_detail VALUES (?,?,?,?,?)",
                (pool_id, rec["period"], rec["smm"], rec["cpr"], rec["implied_psa"])
            )

    # Analytical views using SQL window functions
    c.execute("""
        CREATE VIEW v_prepayment_momentum AS
        SELECT
            pool_id,
            period,
            smm,
            LAG(smm) OVER (PARTITION BY pool_id ORDER BY period) AS prev_smm,
            smm - LAG(smm) OVER (PARTITION BY pool_id ORDER BY period) AS smm_acceleration
        FROM prepayment_detail
    """)

    c.execute("""
        CREATE VIEW v_factor_decline_rate AS
        WITH factor_lag AS (
            SELECT
                pool_id,
                report_date,
                pool_factor,
                LAG(pool_factor) OVER (PARTITION BY pool_id ORDER BY report_date) AS prior_factor
            FROM ginniemae_factors
        )
        SELECT
            pool_id,
            report_date,
            pool_factor,
            prior_factor,
            prior_factor - pool_factor AS decline_rate,
            AVG(prior_factor - pool_factor) OVER (
                PARTITION BY pool_id ORDER BY report_date
                ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
            ) AS avg_decline_3
        FROM factor_lag
    """)

    conn.commit()
    conn.close()


# ============================================================
# Validation SQL
# ============================================================

def write_validation_sql(output_path):
    sql = """\
.headers off
.mode list

SELECT CASE
    WHEN cnt = 0 THEN 'gm_factor_consistency|PASS'
    ELSE 'gm_factor_consistency|FAIL|' || cnt || ' records with factor mismatch'
END FROM (
    SELECT COUNT(*) AS cnt FROM ginniemae_factors
    WHERE ABS(pool_factor - current_face / original_face) > 0.0001
);

SELECT CASE
    WHEN cnt = 0 THEN 'upb_non_negative|PASS'
    ELSE 'upb_non_negative|FAIL|' || cnt || ' records with negative UPB'
END FROM (
    SELECT COUNT(*) AS cnt FROM freddie_performance WHERE cur_upb < 0
);

SELECT CASE
    WHEN cnt = 0 THEN 'pool_factor_bounds|PASS'
    ELSE 'pool_factor_bounds|FAIL|' || cnt || ' records out of bounds'
END FROM (
    SELECT COUNT(*) AS cnt FROM pool_metrics
    WHERE pool_factor < 0 OR pool_factor > 1.01
);

SELECT CASE
    WHEN cnt = 0 THEN 'origination_upb_match|PASS'
    ELSE 'origination_upb_match|FAIL|' || cnt || ' pools with mismatch'
END FROM (
    SELECT COUNT(*) AS cnt FROM (
        SELECT o.pool_id FROM (
            SELECT '20' || SUBSTR(loan_seq, 2, 2) || SUBSTR(loan_seq, 4, 2) AS pool_id,
                   SUM(orig_upb) AS total_orig
            FROM freddie_origination GROUP BY pool_id
        ) o
        JOIN (
            SELECT pm.pool_id, pm.total_upb AS first_upb
            FROM pool_metrics pm
            INNER JOIN (
                SELECT pool_id, MIN(period) AS min_period
                FROM pool_metrics GROUP BY pool_id
            ) fp ON pm.pool_id = fp.pool_id AND pm.period = fp.min_period
        ) p ON o.pool_id = p.pool_id
        WHERE ABS(o.total_orig - p.first_upb) >= 0.01
    )
);
"""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(sql)


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Multi-agency MBS Analytics Engine")
    parser.add_argument("--freddie-orig", required=True)
    parser.add_argument("--freddie-perf", required=True)
    parser.add_argument("--ginniemae-factors", required=True)
    parser.add_argument("--psa-speed", type=float, default=100.0)
    parser.add_argument("--projection-months", type=int, default=36)
    parser.add_argument("--output-json", default="/app/output/report.json")
    parser.add_argument("--output-db", default="/app/output/mbs.db")
    args = parser.parse_args()

    loans = parse_freddie_origination(args.freddie_orig)
    perf = parse_freddie_performance(args.freddie_perf)
    gm_data = parse_ginniemae_factors(args.ginniemae_factors)

    pool_metrics, pool_loans, pool_orig_upb = compute_pool_metrics(loans, perf)
    prepayment = compute_prepayment(loans, perf, pool_loans)
    losses = compute_losses(perf)
    cashflow = compute_cashflow_projection(
        loans, perf, pool_loans, pool_orig_upb,
        args.psa_speed / 100.0, args.projection_months
    )

    ginniemae_pools = {}
    for pool_id, recs in sorted(gm_data.items()):
        ginniemae_pools[pool_id] = [{
            "report_date": r["report_date"],
            "original_face": round(r["original_face"], 2),
            "current_face": round(r["current_face"], 2),
            "pool_factor": round(r["pool_factor"], 8),
            "security_rate": round(r["security_rate"], 8),
            "wac": round(r["wac"], 8),
            "wam": r["wam"],
            "wala": r["wala"],
            "loan_count": r["loan_count"],
        } for r in recs]

    report = {
        "pool_metrics": pool_metrics,
        "prepayment": prepayment,
        "losses": losses,
        "cashflow_projection": cashflow,
        "ginniemae_pools": ginniemae_pools,
    }

    os.makedirs(os.path.dirname(args.output_json), exist_ok=True)
    with open(args.output_json, "w") as f:
        json.dump(report, f, indent=2)
    print(f"JSON report written to {args.output_json}")

    create_database(
        args.output_db, loans, perf, gm_data, pool_metrics,
        pool_loans, pool_orig_upb, prepayment
    )
    print(f"SQLite database written to {args.output_db}")

    validate_path = os.path.join(os.path.dirname(args.output_json), "validate.sql")
    write_validation_sql(validate_path)
    print(f"Validation SQL written to {validate_path}")


if __name__ == "__main__":
    main()
