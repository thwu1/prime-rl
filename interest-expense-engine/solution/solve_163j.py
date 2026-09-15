#!/usr/bin/env python3
"""
IRS Section 163(j) Business Interest Expense Limitation Engine
with Section 385 Intercompany Debt Recharacterization.
"""


import csv
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta


def parse_entities(path):
    entities = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            entities[row["id"]] = row["type"]
    return entities


def parse_financials(path):
    fin = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            eid = row["entity_id"]
            year = int(row["year"])
            data = {}
            for k in [
                "tentative_taxable_income",
                "business_interest_expense",
                "business_interest_income",
                "floor_plan_financing_interest",
                "depreciation",
                "amortization",
                "depletion",
                "nol_deduction",
                "section_199a_deduction",
                "capital_loss_carryover",
            ]:
                data[k] = float(row[k])
            fin.setdefault(eid, {})[year] = data
    return fin


def parse_partnerships(path):
    partnerships = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            pid = row["partnership_id"]
            partnerships.setdefault(pid, []).append(
                {"id": row["partner_id"], "share": float(row["share"])}
            )
    return partnerships


def parse_ownership(path):
    edges = []
    with open(path) as f:
        for row in csv.DictReader(f):
            edges.append(
                (row["parent_id"], row["subsidiary_id"], float(row["ownership_pct"]))
            )
    return edges


def parse_loans(path):
    loans = []
    with open(path) as f:
        for row in csv.DictReader(f):
            loans.append(
                {
                    "loan_id": row["loan_id"],
                    "issuer_id": row["issuer_id"],
                    "holder_id": row["holder_id"],
                    "issue_date": datetime.strptime(row["issue_date"], "%Y-%m-%d"),
                    "principal": float(row["principal"]),
                    "annual_interest": float(row["annual_interest"]),
                    "active_years": [
                        int(y) for y in row["active_years"].split(";") if y.strip()
                    ],
                }
            )
    return loans


def parse_distributions(path):
    dists = []
    with open(path) as f:
        for row in csv.DictReader(f):
            dists.append(
                {
                    "from_entity": row["from_entity"],
                    "to_entity": row["to_entity"],
                    "date": datetime.strptime(row["date"], "%Y-%m-%d"),
                    "amount": float(row["amount"]),
                }
            )
    return dists


def build_expanded_groups(ownership_edges):
    """Build expanded groups using >=80% ownership chains via union-find."""
    graph = defaultdict(set)
    all_entities = set()
    for parent, sub, pct in ownership_edges:
        all_entities.add(parent)
        all_entities.add(sub)
        if pct >= 0.80:
            graph[parent].add(sub)
            graph[sub].add(parent)

    visited = set()
    groups = []
    for entity in all_entities:
        if entity in visited:
            continue
        group = set()
        stack = [entity]
        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            group.add(node)
            for neighbor in graph[node]:
                if neighbor not in visited:
                    stack.append(neighbor)
        groups.append(group)
    return groups


def find_group(entity, groups):
    for g in groups:
        if entity in g:
            return g
    return None


def apply_385(loans, distributions, expanded_groups):
    """Apply Section 385 funding rule. Return recharacterization results and BIE/BII adjustments."""
    recharacterizations = []
    adjustments = defaultdict(lambda: defaultdict(lambda: {"bie_adj": 0.0, "bii_adj": 0.0}))

    for loan in loans:
        issuer = loan["issuer_id"]
        holder = loan["holder_id"]

        issuer_group = find_group(issuer, expanded_groups)
        holder_group = find_group(holder, expanded_groups)

        if issuer_group is None or holder_group is None or issuer_group is not holder_group:
            recharacterizations.append(
                {
                    "loan_id": loan["loan_id"],
                    "recharacterized": 0,
                    "recharacterized_amount": 0.0,
                    "annual_interest_removed": 0.0,
                }
            )
            continue

        issue_date = loan["issue_date"]
        window_start = issue_date - timedelta(days=36 * 30)
        window_end = issue_date + timedelta(days=36 * 30)

        qualifying_amount = 0.0
        for dist in distributions:
            if dist["from_entity"] != issuer:
                continue
            if dist["to_entity"] not in issuer_group:
                continue
            if window_start <= dist["date"] <= window_end:
                qualifying_amount += dist["amount"]

        rechar_amount = min(loan["principal"], qualifying_amount)
        if rechar_amount > 0:
            fraction = rechar_amount / loan["principal"]
            interest_removed = loan["annual_interest"] * fraction
            recharacterizations.append(
                {
                    "loan_id": loan["loan_id"],
                    "recharacterized": 1,
                    "recharacterized_amount": rechar_amount,
                    "annual_interest_removed": interest_removed,
                }
            )
            for yr in loan["active_years"]:
                adjustments[issuer][yr]["bie_adj"] -= interest_removed
                adjustments[holder][yr]["bii_adj"] -= interest_removed
        else:
            recharacterizations.append(
                {
                    "loan_id": loan["loan_id"],
                    "recharacterized": 0,
                    "recharacterized_amount": 0.0,
                    "annual_interest_removed": 0.0,
                }
            )

    return recharacterizations, adjustments


def apply_adjustments(financials, adjustments):
    """Apply 385 adjustments to financial data."""
    adjusted = {}
    for eid, years in financials.items():
        adjusted[eid] = {}
        for year, data in years.items():
            adj_data = dict(data)
            if eid in adjustments and year in adjustments[eid]:
                adj = adjustments[eid][year]
                adj_data["business_interest_expense"] = max(
                    0.0, adj_data["business_interest_expense"] + adj["bie_adj"]
                )
                adj_data["business_interest_income"] = max(
                    0.0, adj_data["business_interest_income"] + adj["bii_adj"]
                )
            adjusted[eid][year] = adj_data
    return adjusted


def compute_ati(yd, year):
    ati = yd["tentative_taxable_income"]
    ati += yd["business_interest_expense"]
    ati += yd["nol_deduction"]
    ati += yd["section_199a_deduction"]
    ati += yd["capital_loss_carryover"]

    if year < 2022:
        ati += yd["depreciation"]
        ati += yd["amortization"]
        ati += yd["depletion"]

    ati -= yd["business_interest_income"]
    ati -= yd["floor_plan_financing_interest"]

    return max(0.0, ati)


def get_ati_pct(year, entity_type):
    if year == 2020:
        return 0.50
    if year == 2019 and entity_type != "partnership":
        return 0.50
    return 0.30


def compute_partnership(eid, partners, financials, entity_results, partner_alloc_results):
    entity_results[eid] = {}

    for year in sorted(financials.get(eid, {}).keys()):
        yd = financials[eid][year]
        ati = compute_ati(yd, year)
        pct = get_ati_pct(year, "partnership")

        bie = yd["business_interest_expense"]
        bii = yd["business_interest_income"]
        floor_plan = yd["floor_plan_financing_interest"]

        pct_ati = ati * pct
        limitation = bii + pct_ati + floor_plan

        deductible = min(bie, limitation)
        excess_bie = max(0.0, bie - limitation)

        if pct_ati > 0:
            net_bie = max(0.0, (bie - floor_plan) - bii)
            eti_num = max(0.0, pct_ati - net_bie)
            excess_taxable_income = ati * eti_num / pct_ati
        else:
            excess_taxable_income = 0.0

        excess_bii = max(0.0, bii - bie)

        entity_results[eid][year] = {
            "ati": ati,
            "limitation": limitation,
            "deductible_bie": deductible,
            "disallowed_bie": excess_bie,
            "carryforward_bie": 0.0,
            "excess_bie": excess_bie,
            "excess_taxable_income": excess_taxable_income,
            "excess_bii": excess_bii,
            "ebie_converted": None,
        }

        for p in partners:
            pid = p["id"]
            share = p["share"]
            partner_alloc_results.append(
                {
                    "partnership_id": eid,
                    "partner_id": pid,
                    "year": year,
                    "deductible_bie": deductible * share,
                    "excess_bie": excess_bie * share,
                    "excess_taxable_income": excess_taxable_income * share,
                    "excess_bii": excess_bii * share,
                }
            )


def compute_nonpartnership(
    eid,
    entity_type,
    partnership_interests,
    financials,
    entity_results,
    ebie_balance_results,
):
    entity_results[eid] = {}
    carryforward = 0.0
    ebie_balances = defaultdict(float)

    for year in sorted(financials.get(eid, {}).keys()):
        yd = financials[eid][year]
        own_ati = compute_ati(yd, year)
        pct = get_ati_pct(year, entity_type)

        own_bie = yd["business_interest_expense"]
        own_bii = yd["business_interest_income"]
        own_floor_plan = yd["floor_plan_financing_interest"]

        total_eti = 0.0
        total_ebii = 0.0
        ebie_converted = 0.0

        for prs_id in partnership_interests:
            if prs_id in entity_results and year in entity_results[prs_id]:
                prs_yr = entity_results[prs_id][year]

                eti_alloc = 0.0
                ebii_alloc = 0.0
                new_ebie = 0.0

                for pa in partner_alloc_list:
                    if (
                        pa["partnership_id"] == prs_id
                        and pa["partner_id"] == eid
                        and pa["year"] == year
                    ):
                        eti_alloc = pa["excess_taxable_income"]
                        ebii_alloc = pa["excess_bii"]
                        new_ebie = pa["excess_bie"]
                        break

                total_eti += eti_alloc
                total_ebii += ebii_alloc

                available = eti_alloc + ebii_alloc
                prior = ebie_balances[prs_id]
                converted = min(prior, available)
                ebie_converted += converted
                ebie_balances[prs_id] = prior - converted + new_ebie

        for prs_id in partnership_interests:
            ebie_balance_results.append(
                {
                    "entity_id": eid,
                    "partnership_id": prs_id,
                    "year": year,
                    "balance": ebie_balances[prs_id],
                }
            )

        total_ati = own_ati + total_eti
        total_bii = own_bii + total_ebii
        total_bie = own_bie + carryforward + ebie_converted

        limitation = total_bii + (total_ati * pct) + own_floor_plan

        deductible = min(total_bie, limitation)
        disallowed = total_bie - deductible
        carryforward = disallowed

        entity_results[eid][year] = {
            "ati": total_ati,
            "limitation": limitation,
            "deductible_bie": deductible,
            "disallowed_bie": disallowed,
            "carryforward_bie": carryforward,
            "excess_bie": None,
            "excess_taxable_income": None,
            "excess_bii": None,
            "ebie_converted": ebie_converted,
        }


def write_db(entity_results, partner_allocs, ebie_balances, recharacterizations, db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute(
        """CREATE TABLE entity_results (
            entity_id TEXT,
            year INTEGER,
            ati REAL,
            limitation REAL,
            deductible_bie REAL,
            disallowed_bie REAL,
            carryforward_bie REAL,
            excess_bie REAL,
            excess_taxable_income REAL,
            excess_bii REAL,
            ebie_converted REAL,
            PRIMARY KEY (entity_id, year)
        )"""
    )

    c.execute(
        """CREATE TABLE partner_allocations (
            partnership_id TEXT,
            partner_id TEXT,
            year INTEGER,
            deductible_bie REAL,
            excess_bie REAL,
            excess_taxable_income REAL,
            excess_bii REAL,
            PRIMARY KEY (partnership_id, partner_id, year)
        )"""
    )

    c.execute(
        """CREATE TABLE ebie_balances (
            entity_id TEXT,
            partnership_id TEXT,
            year INTEGER,
            balance REAL,
            PRIMARY KEY (entity_id, partnership_id, year)
        )"""
    )

    c.execute(
        """CREATE TABLE loan_recharacterizations (
            loan_id TEXT PRIMARY KEY,
            recharacterized INTEGER,
            recharacterized_amount REAL,
            annual_interest_removed REAL
        )"""
    )

    for eid, years in entity_results.items():
        for year, r in years.items():
            c.execute(
                "INSERT INTO entity_results VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    eid,
                    year,
                    r["ati"],
                    r["limitation"],
                    r["deductible_bie"],
                    r["disallowed_bie"],
                    r["carryforward_bie"],
                    r["excess_bie"],
                    r["excess_taxable_income"],
                    r["excess_bii"],
                    r["ebie_converted"],
                ),
            )

    for pa in partner_allocs:
        c.execute(
            "INSERT INTO partner_allocations VALUES (?,?,?,?,?,?,?)",
            (
                pa["partnership_id"],
                pa["partner_id"],
                pa["year"],
                pa["deductible_bie"],
                pa["excess_bie"],
                pa["excess_taxable_income"],
                pa["excess_bii"],
            ),
        )

    for eb in ebie_balances:
        c.execute(
            "INSERT INTO ebie_balances VALUES (?,?,?,?)",
            (eb["entity_id"], eb["partnership_id"], eb["year"], eb["balance"]),
        )

    for rc in recharacterizations:
        c.execute(
            "INSERT INTO loan_recharacterizations VALUES (?,?,?,?)",
            (
                rc["loan_id"],
                rc["recharacterized"],
                rc["recharacterized_amount"],
                rc["annual_interest_removed"],
            ),
        )

    conn.commit()
    conn.close()


partner_alloc_list = []


def main():
    global partner_alloc_list

    entities = parse_entities("/app/data/entities.csv")
    financials = parse_financials("/app/data/financials.csv")
    partnerships_data = parse_partnerships("/app/data/partnerships.csv")
    ownership = parse_ownership("/app/data/ownership.csv")
    loans = parse_loans("/app/data/intercompany_loans.csv")
    distributions = parse_distributions("/app/data/distributions.csv")

    expanded_groups = build_expanded_groups(ownership)
    recharacterizations, adjustments = apply_385(loans, distributions, expanded_groups)
    adj_financials = apply_adjustments(financials, adjustments)

    partnership_interests = defaultdict(list)
    for pid, partners in partnerships_data.items():
        for p in partners:
            partnership_interests[p["id"]].append(pid)

    entity_results = {}
    partner_alloc_list = []
    ebie_balance_results = []

    for eid, etype in entities.items():
        if etype == "partnership":
            compute_partnership(
                eid,
                partnerships_data.get(eid, []),
                adj_financials,
                entity_results,
                partner_alloc_list,
            )

    for eid, etype in entities.items():
        if etype != "partnership":
            compute_nonpartnership(
                eid,
                etype,
                partnership_interests.get(eid, []),
                adj_financials,
                entity_results,
                ebie_balance_results,
            )

    import os

    db_path = "/app/results.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    write_db(
        entity_results,
        partner_alloc_list,
        ebie_balance_results,
        recharacterizations,
        db_path,
    )


if __name__ == "__main__":
    main()
