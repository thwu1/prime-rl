"""Metabolic assessment of a genome-scale metabolic model.

Loads model from /app/data/model.json, performs multiple analyses,
and writes structured results to /app/results.json.
"""


import json
import math

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


def is_lethal(growth_val, threshold):
    try:
        g = float(growth_val)
        return math.isnan(g) or g < threshold
    except (TypeError, ValueError):
        return True


def main():
    model = load_json_model("/app/data/model.json")
    results = {}

    # Aerobic growth
    sol = model.optimize()
    aerobic = sol.objective_value
    results["aerobic_growth"] = float(aerobic)

    # Anaerobic growth
    with model:
        model.reactions.get_by_id("EX_o2_e").lower_bound = 0
        sol = model.optimize()
        anaerobic = sol.objective_value
    results["anaerobic_growth"] = float(anaerobic)

    threshold = GROWTH_THRESHOLD_PCT * aerobic

    # Essential genes
    gene_del = single_gene_deletion(model, processes=1)
    essential_genes = []
    for _, row in gene_del.iterrows():
        if is_lethal(row["growth"], threshold):
            for gid in row["ids"]:
                essential_genes.append(str(gid))
    essential_genes = sorted(set(essential_genes))
    results["essential_genes"] = essential_genes

    # Essential reactions (exclude exchange and biomass objective)
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
        if is_lethal(row["growth"], threshold):
            for rid in row["ids"]:
                essential_reactions.append(str(rid))
    essential_reactions = sorted(set(essential_reactions))
    results["essential_reactions"] = essential_reactions

    # Isozyme-buffered reactions
    isozyme_buffered = []
    for rxn_id in essential_reactions:
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
    results["isozyme_buffered"] = sorted(isozyme_buffered)

    # Carbon source utilization
    with open("/app/data/carbon_sources.tsv") as f:
        lines = f.read().strip().split("\n")
    carbon_names = [l.strip() for l in lines[1:] if l.strip()]

    carbon_growth = {}
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
                carbon_growth[matched_rxn.id] = float(sol.objective_value)
    results["carbon_utilization"] = carbon_growth

    # Flux ranges at 90% optimality
    with open("/app/data/pathway_reactions.txt") as f:
        rxn_ids = [l.strip() for l in f if l.strip()]
    rxn_list = [model.reactions.get_by_id(r) for r in rxn_ids]
    fva_df = flux_variability_analysis(
        model, reaction_list=rxn_list, fraction_of_optimum=0.9,
    )
    flux_ranges = {}
    for rxn_id in rxn_ids:
        flux_ranges[rxn_id] = {
            "minimum": float(fva_df.loc[rxn_id, "minimum"]),
            "maximum": float(fva_df.loc[rxn_id, "maximum"]),
        }
    results["flux_ranges"] = flux_ranges

    # Synthetic lethal pairs
    with open("/app/data/candidate_genes.txt") as f:
        candidate_ids = [l.strip() for l in f if l.strip()]

    essential_set = set(essential_genes)
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
                if is_lethal(row["growth"], threshold):
                    pair = sorted([str(g) for g in ids_set])
                    sl_pairs.append(pair)
    sl_pairs.sort()
    results["synthetic_lethals"] = sl_pairs

    # Chokepoint metabolites
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
    results["chokepoint_metabolites"] = sorted(chokepoints)

    # Production envelope (anaerobic ethanol)
    biomass = get_biomass_reaction(model)
    growth_rates = [i * anaerobic / 10.0 for i in range(11)]
    max_ethanol = []
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
    results["production_envelope"] = {
        "growth_rates": [float(g) for g in growth_rates],
        "max_ethanol": max_ethanol,
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Analysis complete. Results written to /app/results.json")


if __name__ == "__main__":
    main()
