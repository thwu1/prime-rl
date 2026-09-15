A genome-scale metabolic reconstruction is provided at `/app/data/model.json`. Supporting data files are in `/app/data/`. Create `/app/metabolic_assessment.py` that analyzes this model and writes all results to `/app/results.json`. Execute with `python3 /app/metabolic_assessment.py`.

Required fields in `/app/results.json`:

**`aerobic_growth`** (float): Maximum biomass production rate under the model's default constraints.

**`anaerobic_growth`** (float): Maximum biomass production rate with oxygen uptake fully blocked.

**`essential_genes`** (sorted list of strings): Gene IDs whose individual removal reduces growth below 1% of the aerobic wild-type rate or makes growth infeasible.

**`essential_reactions`** (sorted list of strings): Reaction IDs whose individual removal reduces growth below 1% of aerobic wild-type or makes growth infeasible. Exclude exchange reactions (IDs starting with `EX_`) and the biomass objective reaction.

**`isozyme_buffered`** (sorted list of strings): IDs from `essential_reactions` where removing any single associated gene does not disable the reaction — genetic redundancy protects individual genes but the reaction itself is network-critical. Exclude reactions with no gene associations.

**`carbon_utilization`** (object): `/app/data/carbon_sources.tsv` lists carbon source names (header row: `name`). For each entry, identify its corresponding exchange reaction in the model. Block glucose uptake (set the glucose exchange reaction lower bound to 0), enable the listed carbon source uptake (lower bound −20), and report maximum growth. Keys must be the exchange reaction IDs discovered from the model.

**`flux_ranges`** (object): For each reaction ID in `/app/data/pathway_reactions.txt`, report the minimum and maximum steady-state flux achievable while maintaining at least 90% of optimal aerobic growth. Format: `{"reaction_id": {"minimum": float, "maximum": float}}`.

**`synthetic_lethals`** (sorted list of [string, string]): Among individually non-essential genes from `/app/data/candidate_genes.txt`, find all pairs whose combined removal is lethal (below 1% wild-type or infeasible). Each pair sorted alphabetically; outer list sorted lexicographically.

**`chokepoint_metabolites`** (sorted list of strings): Cytoplasmic-compartment metabolite IDs where the metabolite has exactly one producing reaction or exactly one consuming reaction among all non-exchange reactions. A reaction produces a metabolite when its stoichiometric coefficient is positive; consumes when negative.

**`production_envelope`** (object): Under anaerobic conditions, report maximum ethanol secretion flux at 11 evenly spaced biomass production rates from 0 to the anaerobic maximum (inclusive of both endpoints). Format: `{"growth_rates": [float, ...], "max_ethanol": [float, ...]}`.
