#!/usr/bin/env python3
"""Metabolic network analysis pipeline.

"""

import json
import os
import re
import sqlite3
import sys
from collections import defaultdict, deque

DATA_DIR = "/app/data"
RESULTS_DIR = "/app/results"
DB_PATH = os.path.join(RESULTS_DIR, "metabolic.db")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def parse_reference_file(filepath):
    """Parse KEGG compound reference file (full API response format).

    The ENTRY line format: 'ENTRY       C00024                      Compound'
    Extract just the compound ID (first token after ENTRY).
    """
    compounds = {}
    current = {}
    current_field = None

    with open(filepath) as fh:
        for raw_line in fh:
            line = raw_line.rstrip("\n")
            if line.strip() == "///":
                if current:
                    entry_raw = current.get("ENTRY", "")
                    cid = entry_raw.split()[0].strip() if entry_raw else ""
                    formula = current.get("FORMULA", "").strip()
                    if cid and formula:
                        compounds[cid] = formula
                current = {}
                current_field = None
                continue
            if not line or line.startswith("#"):
                continue
            if line[0] == " " and current_field is not None:
                continue
            match = re.match(r"^(\S+)\s+(.*)", line)
            if match:
                current_field = match.group(1)
                value = match.group(2).strip()
                if current_field not in current:
                    current[current_field] = value

    if current:
        entry_raw = current.get("ENTRY", "")
        cid = entry_raw.split()[0].strip() if entry_raw else ""
        formula = current.get("FORMULA", "").strip()
        if cid and formula:
            compounds[cid] = formula

    return compounds


def parse_formula(formula):
    """Parse a chemical formula like C6H12O6 into element counts."""
    if not formula:
        return {}
    elements = {}
    i = 0
    n = len(formula)
    while i < n:
        if formula[i].isupper():
            elem = formula[i]
            i += 1
            while i < n and formula[i].islower():
                elem += formula[i]
                i += 1
            count_str = ""
            while i < n and formula[i].isdigit():
                count_str += formula[i]
                i += 1
            count = int(count_str) if count_str else 1
            elements[elem] = elements.get(elem, 0) + count
        else:
            i += 1
    return elements


# -- Commands ----------------------------------------------------------------


def cmd_build_db():
    """Import SQL dump, resolve synonyms, recover formulas, create stoich_entries."""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    config = load_config()

    dump_path = os.path.join(DATA_DIR, "metabolic_dump.sql")
    conn = sqlite3.connect(DB_PATH)
    with open(dump_path) as f:
        conn.executescript(f.read())
    conn.commit()

    # Resolve synonyms in reaction_participants
    synonyms = dict(conn.execute(
        "SELECT synonym_id, canonical_id FROM compound_synonyms"
    ).fetchall())
    for syn_id, canon_id in synonyms.items():
        conn.execute(
            "UPDATE reaction_participants SET compound_id = ? WHERE compound_id = ?",
            (canon_id, syn_id)
        )

    # Find compounds with NULL formulas referenced in reactions
    cursor = conn.execute("""
        SELECT DISTINCT c.id FROM compounds c
        JOIN reaction_participants rp ON rp.compound_id = c.id
        WHERE c.formula IS NULL
    """)
    missing = [row[0] for row in cursor.fetchall()]

    ref_file = os.path.join(DATA_DIR, config.get("compound_reference_file", ""))
    ref_compounds = parse_reference_file(ref_file) if os.path.exists(ref_file) else {}

    # Create recovery log table and recover formulas
    conn.execute("DROP TABLE IF EXISTS recovery_log")
    conn.execute("""
        CREATE TABLE recovery_log (
            compound_id TEXT PRIMARY KEY,
            recovered_formula TEXT NOT NULL
        )
    """)
    for cid in missing:
        if cid in ref_compounds:
            conn.execute(
                "UPDATE compounds SET formula = ? WHERE id = ?",
                (ref_compounds[cid], cid)
            )
            conn.execute(
                "INSERT INTO recovery_log VALUES (?, ?)",
                (cid, ref_compounds[cid])
            )

    # Create stoich_entries table with signed coefficients
    conn.execute("DROP TABLE IF EXISTS stoich_entries")
    conn.execute("""
        CREATE TABLE stoich_entries (
            reaction_id TEXT NOT NULL,
            compound_id TEXT NOT NULL,
            coefficient REAL NOT NULL
        )
    """)
    conn.execute("""
        INSERT INTO stoich_entries (reaction_id, compound_id, coefficient)
        SELECT reaction_id, compound_id,
               CASE WHEN side = 'L' THEN -1.0 * coefficient
                    ELSE 1.0 * coefficient END
        FROM reaction_participants
    """)

    conn.commit()
    conn.close()


def cmd_export_recovery():
    """Export data_recovery.json from the recovery_log table."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT compound_id, recovered_formula FROM recovery_log"
    ).fetchall()
    conn.close()
    recovery = dict(rows)
    with open(os.path.join(RESULTS_DIR, "data_recovery.json"), "w") as f:
        json.dump(recovery, f, indent=2)


def get_compounds(conn):
    return dict(conn.execute("SELECT id, formula FROM compounds").fetchall())


def get_reactions(conn):
    reactions = defaultdict(list)
    cursor = conn.execute(
        "SELECT reaction_id, compound_id, coefficient, side FROM reaction_participants"
    )
    for rxn_id, cpd_id, coeff, side in cursor:
        reactions[rxn_id].append((cpd_id, coeff, side))
    all_rxn_ids = [row[0] for row in conn.execute(
        "SELECT id FROM reactions"
    ).fetchall()]
    for rid in all_rxn_ids:
        if rid not in reactions:
            reactions[rid] = []
    return dict(reactions)


def get_pathways(conn):
    pathways = defaultdict(list)
    cursor = conn.execute(
        "SELECT pathway_id, reaction_id, flux_coefficient FROM pathway_reactions"
    )
    for pwy_id, rxn_id, flux in cursor:
        pathways[pwy_id].append((rxn_id, flux))
    return dict(pathways)


def cmd_balance():
    """Compute balance report for all reactions."""
    conn = sqlite3.connect(DB_PATH)
    compounds = get_compounds(conn)
    reactions = get_reactions(conn)
    conn.close()

    report = {}
    for rxn_id, participants in reactions.items():
        left_elements = defaultdict(int)
        right_elements = defaultdict(int)
        for cpd_id, coeff, side in participants:
            formula = compounds.get(cpd_id, "")
            parsed = parse_formula(formula)
            target = left_elements if side == "L" else right_elements
            for elem, count in parsed.items():
                target[elem] += coeff * count
        all_elements = sorted(set(left_elements.keys()) | set(right_elements.keys()))
        deltas = {}
        for elem in all_elements:
            deltas[elem] = left_elements[elem] - right_elements[elem]
        balanced = all(d == 0 for d in deltas.values())
        report[rxn_id] = {"balanced": balanced, "element_deltas": deltas}

    with open(os.path.join(RESULTS_DIR, "balance_report.json"), "w") as f:
        json.dump(report, f, indent=2)


def cmd_pathways():
    """Compute pathway stoichiometry with flux coefficients."""
    conn = sqlite3.connect(DB_PATH)
    compounds = get_compounds(conn)
    reactions = get_reactions(conn)
    pathways = get_pathways(conn)
    conn.close()

    result = {}
    for pwy_id, rxn_list in pathways.items():
        net = defaultdict(int)
        for rxn_id, flux in rxn_list:
            participants = reactions.get(rxn_id, [])
            if flux > 0:
                for cpd_id, coeff, side in participants:
                    if side == "L":
                        net[cpd_id] -= coeff * flux
                    else:
                        net[cpd_id] += coeff * flux
            else:
                abs_flux = abs(flux)
                for cpd_id, coeff, side in participants:
                    if side == "R":
                        net[cpd_id] -= coeff * abs_flux
                    else:
                        net[cpd_id] += coeff * abs_flux

        consumed = {}
        produced = {}
        for cid, amount in net.items():
            if amount < 0:
                consumed[cid] = -amount
            elif amount > 0:
                produced[cid] = amount

        consumed_elements = defaultdict(int)
        produced_elements = defaultdict(int)
        for cid, amount in consumed.items():
            for elem, count in parse_formula(compounds.get(cid, "")).items():
                consumed_elements[elem] += count * amount
        for cid, amount in produced.items():
            for elem, count in parse_formula(compounds.get(cid, "")).items():
                produced_elements[elem] += count * amount

        all_elems = set(consumed_elements.keys()) | set(produced_elements.keys())
        element_deltas = {}
        for elem in sorted(all_elems):
            delta = consumed_elements[elem] - produced_elements[elem]
            if delta != 0:
                element_deltas[elem] = delta

        result[pwy_id] = {
            "net_consumed": consumed,
            "net_produced": produced,
            "element_balance": {
                "consistent": len(element_deltas) == 0,
                "element_deltas": element_deltas,
            },
        }

    with open(os.path.join(RESULTS_DIR, "pathway_stoichiometry.json"), "w") as f:
        json.dump(result, f, indent=2)


def cmd_graph():
    """Compute dead-end compounds and chokepoint reactions."""
    conn = sqlite3.connect(DB_PATH)
    reactions = get_reactions(conn)
    conn.close()

    compound_reactions = defaultdict(set)
    for rxn_id, participants in reactions.items():
        for cpd_id, _, _ in participants:
            compound_reactions[cpd_id].add(rxn_id)

    dead_ends = sorted(
        cid for cid, rxns in compound_reactions.items() if len(rxns) == 1
    )
    dead_end_set = set(dead_ends)

    chokepoints = set()
    for rxn_id, participants in reactions.items():
        for cpd_id, _, _ in participants:
            if cpd_id in dead_end_set:
                chokepoints.add(rxn_id)
                break

    with open(os.path.join(RESULTS_DIR, "dead_ends.json"), "w") as f:
        json.dump(dead_ends, f, indent=2)
    with open(os.path.join(RESULTS_DIR, "chokepoints.json"), "w") as f:
        json.dump(sorted(chokepoints), f, indent=2)


def cmd_shortest():
    """Compute shortest paths between compound pairs excluding currency metabolites."""
    config = load_config()
    conn = sqlite3.connect(DB_PATH)
    reactions = get_reactions(conn)
    conn.close()

    currency = set(config["currency_metabolites"])
    queries = config["shortest_path_queries"]

    rxn_compounds = {}
    for rxn_id, participants in reactions.items():
        non_currency = set()
        for cpd_id, _, _ in participants:
            if cpd_id not in currency:
                non_currency.add(cpd_id)
        rxn_compounds[rxn_id] = non_currency

    compound_to_rxns = defaultdict(set)
    for rxn_id, cids in rxn_compounds.items():
        for cid in cids:
            compound_to_rxns[cid].add(rxn_id)

    result = {}
    for source, target in queries:
        key = f"{source}->{target}"
        if source == target:
            result[key] = 0
            continue
        if source in currency or target in currency:
            result[key] = -1
            continue
        visited_compounds = {source}
        visited_reactions = set()
        queue = deque([(source, 0)])
        found = False
        while queue and not found:
            current_compound, dist = queue.popleft()
            for rxn_id in compound_to_rxns.get(current_compound, set()):
                if rxn_id in visited_reactions:
                    continue
                visited_reactions.add(rxn_id)
                for neighbor in rxn_compounds[rxn_id]:
                    if neighbor in visited_compounds:
                        continue
                    visited_compounds.add(neighbor)
                    if neighbor == target:
                        result[key] = dist + 1
                        found = True
                        break
                    queue.append((neighbor, dist + 1))
                if found:
                    break
        if not found:
            result[key] = -1

    with open(os.path.join(RESULTS_DIR, "shortest_paths.json"), "w") as f:
        json.dump(result, f, indent=2)


def cmd_matrix():
    """Export stoichiometric matrix in Matrix Market coordinate format."""
    conn = sqlite3.connect(DB_PATH)
    entries = conn.execute(
        "SELECT reaction_id, compound_id, coefficient FROM stoich_entries"
    ).fetchall()
    conn.close()

    rxn_ids = sorted(set(e[0] for e in entries))
    cpd_ids = sorted(set(e[1] for e in entries))
    rxn_idx = {rid: i + 1 for i, rid in enumerate(rxn_ids)}
    cpd_idx = {cid: i + 1 for i, cid in enumerate(cpd_ids)}

    sorted_entries = sorted(
        entries, key=lambda e: (rxn_idx[e[0]], cpd_idx[e[1]])
    )

    with open(os.path.join(RESULTS_DIR, "stoichiometric_matrix.mtx"), "w") as f:
        f.write("%%MatrixMarket matrix coordinate real general\n")
        f.write(f"% ROWS: {' '.join(rxn_ids)}\n")
        f.write(f"% COLS: {' '.join(cpd_ids)}\n")
        f.write(f"{len(rxn_ids)} {len(cpd_ids)} {len(sorted_entries)}\n")
        for rxn_id, cpd_id, coeff in sorted_entries:
            f.write(f"{rxn_idx[rxn_id]} {cpd_idx[cpd_id]} {float(coeff)}\n")


COMMANDS = {
    "build-db": cmd_build_db,
    "export-recovery": cmd_export_recovery,
    "balance": cmd_balance,
    "pathways": cmd_pathways,
    "graph": cmd_graph,
    "shortest": cmd_shortest,
    "matrix": cmd_matrix,
}


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"Usage: {sys.argv[0]} <{'|'.join(COMMANDS.keys())}>")
        sys.exit(1)
    COMMANDS[sys.argv[1]]()
