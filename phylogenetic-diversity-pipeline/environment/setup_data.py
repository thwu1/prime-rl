#!/usr/bin/env python3
"""Generate data files for the phylogenetic microbiome analysis task."""
import os

DATA_DIR = "/app/data"
os.makedirs(DATA_DIR, exist_ok=True)

# Species tree: 10 OTUs, UNROOTED (3 children at root), with branch lengths
# Topology: (((OTU01,OTU02),(OTU03,OTU04)),((OTU05,OTU06),(OTU07,OTU08)),(OTU09,OTU10))
# Must be rooted at OTU09/OTU10 outgroup before UniFrac computation
species_tree = (
    "(((OTU01:0.08,OTU02:0.12):0.18,(OTU03:0.22,OTU04:0.09):0.14):0.25,"
    "((OTU05:0.15,OTU06:0.28):0.11,(OTU07:0.31,OTU08:0.19):0.13):0.20,"
    "(OTU09:0.40,OTU10:0.45):0.35);\n"
)

with open(os.path.join(DATA_DIR, "species_tree.nwk"), "w") as f:
    f.write(species_tree)

# Gene trees: 12 trees with varied topologies
# Some concordant, some discordant with the species tree
gene_trees = [
    # Tree 0: concordant with species tree
    "((((OTU01,OTU02),(OTU03,OTU04)),((OTU05,OTU06),(OTU07,OTU08))),(OTU09,OTU10));",
    # Tree 1: swap OTU01 and OTU03 (discordant)
    "((((OTU03,OTU02),(OTU01,OTU04)),((OTU05,OTU06),(OTU07,OTU08))),(OTU09,OTU10));",
    # Tree 2: concordant
    "((((OTU01,OTU02),(OTU03,OTU04)),((OTU05,OTU06),(OTU07,OTU08))),(OTU09,OTU10));",
    # Tree 3: swap OTU05 and OTU07 (discordant)
    "((((OTU01,OTU02),(OTU03,OTU04)),((OTU07,OTU06),(OTU05,OTU08))),(OTU09,OTU10));",
    # Tree 4: concordant
    "((((OTU01,OTU02),(OTU03,OTU04)),((OTU05,OTU06),(OTU07,OTU08))),(OTU09,OTU10));",
    # Tree 5: major rearrangement (OTU09 groups with OTU01/02)
    "(((OTU01,OTU02),OTU09),((OTU03,OTU04),((OTU05,OTU06),(OTU07,OTU08))),OTU10);",
    # Tree 6: concordant
    "((((OTU01,OTU02),(OTU03,OTU04)),((OTU05,OTU06),(OTU07,OTU08))),(OTU09,OTU10));",
    # Tree 7: OTU04 swapped with OTU06 across clades (discordant)
    "((((OTU01,OTU02),(OTU03,OTU06)),((OTU05,OTU04),(OTU07,OTU08))),(OTU09,OTU10));",
    # Tree 8: concordant
    "((((OTU01,OTU02),(OTU03,OTU04)),((OTU05,OTU06),(OTU07,OTU08))),(OTU09,OTU10));",
    # Tree 9: (OTU08,OTU10) clade (discordant)
    "((((OTU01,OTU02),(OTU03,OTU04)),((OTU05,OTU06),OTU07)),(OTU08,(OTU09,OTU10)));",
    # Tree 10: concordant
    "((((OTU01,OTU02),(OTU03,OTU04)),((OTU05,OTU06),(OTU07,OTU08))),(OTU09,OTU10));",
    # Tree 11: concordant topology (same bipartitions, different child ordering)
    "(((OTU05,OTU06),(OTU07,OTU08)),((OTU01,OTU02),(OTU03,OTU04)),(OTU09,OTU10));",
]

with open(os.path.join(DATA_DIR, "gene_trees.nwk"), "w") as f:
    for t in gene_trees:
        f.write(t + "\n")

# OTU abundance table: 15 samples x 12 OTUs
# OTU11 and OTU12 are NOT in the tree (agent must filter them)
# Clear group structure: Treatment vs Control vs Baseline
header = "SampleID\tOTU01\tOTU02\tOTU03\tOTU04\tOTU05\tOTU06\tOTU07\tOTU08\tOTU09\tOTU10\tOTU11\tOTU12"
rows = [
    # Treatment group (S01-S05): high OTU01-04, low OTU05-10
    "S01\t120\t95\t80\t65\t12\t8\t5\t10\t15\t18\t30\t25",
    "S02\t135\t88\t72\t70\t10\t6\t8\t12\t18\t20\t28\t22",
    "S03\t110\t102\t85\t60\t15\t10\t6\t8\t12\t16\t35\t20",
    "S04\t128\t90\t78\t68\t11\t7\t7\t11\t16\t19\t32\t24",
    "S05\t118\t98\t82\t62\t14\t9\t4\t9\t14\t17\t31\t23",
    # Control group (S06-S10): high OTU05-08, low OTU01-04
    "S06\t10\t8\t12\t15\t110\t95\t88\t102\t20\t18\t22\t28",
    "S07\t12\t6\t15\t18\t125\t100\t92\t98\t22\t16\t25\t30",
    "S08\t8\t10\t10\t12\t105\t88\t95\t108\t18\t20\t20\t26",
    "S09\t15\t7\t14\t16\t118\t92\t85\t95\t24\t14\t24\t32",
    "S10\t11\t9\t11\t14\t112\t98\t90\t100\t21\t17\t23\t29",
    # Baseline group (S11-S15): moderate all, higher OTU09-10
    "S11\t40\t35\t38\t42\t45\t40\t38\t35\t85\t90\t18\t15",
    "S12\t38\t40\t35\t40\t42\t38\t40\t38\t90\t88\t20\t16",
    "S13\t42\t32\t40\t38\t48\t42\t35\t32\t82\t95\t16\t14",
    "S14\t35\t38\t42\t45\t40\t35\t42\t40\t88\t85\t19\t17",
    "S15\t44\t36\t36\t40\t44\t44\t36\t36\t80\t92\t17\t15",
]

with open(os.path.join(DATA_DIR, "otu_table.tsv"), "w") as f:
    f.write(header + "\n")
    for row in rows:
        f.write(row + "\n")

# Sample metadata: 3 groups
metadata_header = "SampleID\tTreatment\tSite"
metadata_rows = [
    "S01\tDrugA\tHospital1",
    "S02\tDrugA\tHospital1",
    "S03\tDrugA\tHospital2",
    "S04\tDrugA\tHospital2",
    "S05\tDrugA\tHospital1",
    "S06\tControl\tHospital1",
    "S07\tControl\tHospital2",
    "S08\tControl\tHospital1",
    "S09\tControl\tHospital2",
    "S10\tControl\tHospital1",
    "S11\tBaseline\tHospital1",
    "S12\tBaseline\tHospital2",
    "S13\tBaseline\tHospital1",
    "S14\tBaseline\tHospital2",
    "S15\tBaseline\tHospital1",
]

with open(os.path.join(DATA_DIR, "metadata.tsv"), "w") as f:
    f.write(metadata_header + "\n")
    for row in metadata_rows:
        f.write(row + "\n")

# Study notes: contains experimental design context including outgroup info
study_notes = """\
Gut Microbiome Response to Drug A Treatment
============================================

Study Design:
- 15 subjects recruited from two hospital sites (Hospital1, Hospital2)
- Three arms: DrugA (n=5, S01-S05), Control (n=5, S06-S10), Baseline (n=5, S11-S15)
- 16S rRNA V4 amplicon sequencing, OTUs clustered at 97% similarity

Taxonomic Context:
- Core study taxa (OTU01-OTU08): in-group gut commensals under investigation
- Phylogenetic calibration references (OTU09, OTU10): environmental outgroup isolates
  included for rooting the reference phylogeny
- Additional exploratory OTUs detected in sequencing but not present in reference tree
- 12 single-copy marker genes sequenced for gene tree concordance analysis

Notes:
- Reference phylogeny was reconstructed from full-length 16S sequences
- Some marker gene trees show discordance with the species tree topology
- Abundance data has not been pre-filtered to match the reference phylogeny
"""

with open(os.path.join(DATA_DIR, "study_notes.txt"), "w") as f:
    f.write(study_notes)

print("Data files created successfully in", DATA_DIR)
