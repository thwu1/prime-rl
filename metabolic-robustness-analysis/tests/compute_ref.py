"""Compute reference values for metabolic assessment verification.

Runs as a standalone script OUTSIDE pytest to avoid multiprocessing
deadlocks with cobra's deletion functions. Writes to /tmp/ref_values.json.
"""


import json
import math
import sys

from cobra.io import load_json_model
from cobra.util.solver import linear_reaction_coefficients
from cobra.flux_analysis import (
    single_gene_deletion,
    single_reaction_deletion,
    flux_variability_analysis,
    double_gene_deletion,
)

GROWTH_THRESHOLD_PCT = 0.01


def get_biomass_reaction(model):
    obj_rxns = linear_reaction_coefficients(model)
    return list(obj_rxns.keys())[0]


def main():
    model = load_json_model("/app/data/model.json")
    out = {}

    # --- Aerobic growth ---
    sol = model.optimize()
    out["aerobic"] = float(sol.objective_value)

    # --- Anaerobic growth ---
    with model:
        model.reactions.get_by_id("EX_o2_e").lower_bound = 0
        sol = model.optimize()
        out["anaerobic"] = float(sol.objective_value)

    threshold = GROWTH_THRESHOLD_PCT * out["aerobic"]

    # --- Essential genes ---
    gene_del = single_gene_deletion(model, processes=1)
    essential_genes = []
    for _, row in gene_del.iterrows():
        try:
            growth = float(row["growth"])
            is_lethal = math.isnan(growth) or growth < threshold
        except (TypeError, ValueError):
            is_lethal = True
        if is_lethal:
            for gid in row["ids"]:
                essential_genes.append(str(gid))
    out["essential_genes"] = sorted(set(essential_genes))

    # --- Essential reactions ---
    biomass_rxn = get_biomass_reaction(model)
    non_exchange = [
        r for r in model.reactions
        if not r.id.startswith("EX_") and r.id != biomass_rxn.id
    ]
    rxn_del = single_reaction_deletion(
        model, reaction_list=non_exchange, processes=1
    )
    essential_reactions = []
    for _, row in rxn_del.iterrows():
        try:
            growth = float(row["growth"])
            is_lethal = math.isnan(growth) or growth < threshold
        except (TypeError, ValueError):
            is_lethal = True
        if is_lethal:
            for rid in row["ids"]:
                essential_reactions.append(str(rid))
    out["essential_reactions"] = sorted(set(essential_reactions))

    # --- Isozyme-buffered reactions ---
    isozyme_buffered = []
    for rxn_id in out["essential_reactions"]:
        rxn = model.reactions.get_by_id(rxn_id)
        if not rxn.genes:
            continue
        any_single_ko_disables = False
        for gene in rxn.genes:
            with model:
                gene.knock_out()
                rxn_after = model.reactions.get_by_id(rxn_id)
                if rxn_after.lower_bound == 0 and rxn_after.upper_bound == 0:
                    any_single_ko_disables = True
                    break
        if not any_single_ko_disables:
            isozyme_buffered.append(rxn_id)
    out["isozyme_buffered"] = sorted(isozyme_buffered)

    # --- Carbon source utilization ---
    with open("/app/data/carbon_sources.tsv") as f:
        lines = f.read().strip().split("\n")
    carbon_names = [l.strip() for l in lines[1:] if l.strip()]

    carbon = {}
    for name in carbon_names:
        matched_rxn = None
        for met in model.metabolites:
            if met.name == name and met.compartment == "e":
                for rxn in met.reactions:
                    if rxn.id.startswith("EX_"):
                        matched_rxn = rxn
                        break
                break
        if matched_rxn:
            with model:
                model.reactions.get_by_id("EX_glc__D_e").lower_bound = 0
                matched_rxn.lower_bound = -20
                sol = model.optimize()
                carbon[matched_rxn.id] = float(sol.objective_value)
    out["carbon"] = carbon

    # --- Flux ranges at 90% optimality ---
    with open("/app/data/pathway_reactions.txt") as f:
        rxn_ids = [l.strip() for l in f if l.strip()]
    rxn_list = [model.reactions.get_by_id(r) for r in rxn_ids]
    fva_df = flux_variability_analysis(
        model, reaction_list=rxn_list, fraction_of_optimum=0.9,
    )
    fva = {}
    for rxn_id in rxn_ids:
        fva[rxn_id] = {
            "minimum": float(fva_df.loc[rxn_id, "minimum"]),
            "maximum": float(fva_df.loc[rxn_id, "maximum"]),
        }
    out["fva"] = fva

    # --- Synthetic lethal pairs ---
    with open("/app/data/candidate_genes.txt") as f:
        candidate_ids = [l.strip() for l in f if l.strip()]

    essential_set = set(out["essential_genes"])
    candidate_genes = []
    for gid in candidate_ids:
        try:
            gene = model.genes.get_by_id(gid)
            if gid not in essential_set:
                candidate_genes.append(gene)
        except KeyError:
            pass
    candidate_genes.sort(key=lambda g: g.id)

    sl_pairs = []
    if len(candidate_genes) >= 2:
        double_del = double_gene_deletion(
            model, gene_list1=candidate_genes, processes=1,
        )
        for _, row in double_del.iterrows():
            ids_set = row["ids"]
            if len(ids_set) == 2:
                try:
                    growth = float(row["growth"])
                    is_lethal = math.isnan(growth) or growth < threshold
                except (TypeError, ValueError):
                    is_lethal = True
                if is_lethal:
                    pair = sorted([str(g) for g in ids_set])
                    sl_pairs.append(pair)
    sl_pairs.sort()
    out["synthetic_lethals"] = sl_pairs

    # --- Chokepoint metabolites ---
    non_ex_rxn_ids = set(
        r.id for r in model.reactions if not r.id.startswith("EX_")
    )
    cyto_mets = [m for m in model.metabolites if m.compartment == "c"]
    chokepoints = []
    for met in cyto_mets:
        producers = 0
        consumers = 0
        for rxn in met.reactions:
            if rxn.id not in non_ex_rxn_ids:
                continue
            coeff = rxn.get_coefficient(met)
            if coeff > 0:
                producers += 1
            elif coeff < 0:
                consumers += 1
        if producers == 1 or consumers == 1:
            chokepoints.append(met.id)
    out["chokepoint_metabolites"] = sorted(chokepoints)

    # --- Ethanol production envelope ---
    anaerobic_max = out["anaerobic"]
    growth_rates = [i * anaerobic_max / 10.0 for i in range(11)]
    max_ethanol = []
    biomass = get_biomass_reaction(model)
    for gr in growth_rates:
        with model:
            model.reactions.get_by_id("EX_o2_e").lower_bound = 0
            biomass.lower_bound = gr
            biomass.upper_bound = gr
            model.objective = "EX_etoh_e"
            sol = model.optimize()
            if sol.status == "optimal":
                max_ethanol.append(float(sol.objective_value))
            else:
                max_ethanol.append(0.0)
    out["production_envelope"] = {
        "growth_rates": [float(g) for g in growth_rates],
        "max_ethanol": max_ethanol,
    }

    with open("/tmp/ref_values.json", "w") as f:
        json.dump(out, f, indent=2)

    print("Reference values computed successfully.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR computing reference values: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
