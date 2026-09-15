#!/usr/bin/env python3
"""Generate deterministic SemTab evaluation data with an RDF knowledge graph
containing owl:sameAs, rdfs:subClassOf, owl:equivalentClass, and rdfs:subPropertyOf."""

import json
import csv
import os

DATA_DIR = "/data"
os.makedirs(f"{DATA_DIR}/tables", exist_ok=True)
os.makedirs(f"{DATA_DIR}/submissions", exist_ok=True)

# ============================================================
# Tables: 5 CSV files representing Wikipedia-style tables
# ============================================================
tables = {
    "T001": [
        ["Name", "Birth Year", "Nationality"],
        ["Albert Einstein", "1879", "German"],
        ["Marie Curie", "1867", "Polish"],
        ["Isaac Newton", "1643", "English"],
        ["Nikola Tesla", "1856", "Serbian"],
    ],
    "T002": [
        ["City", "Country", "Population"],
        ["Paris", "France", "2161000"],
        ["London", "United Kingdom", "8982000"],
        ["Berlin", "Germany", "3645000"],
        ["Tokyo", "Japan", "13960000"],
    ],
    "T003": [
        ["University", "Founded", "Location"],
        ["MIT", "1861", "Cambridge"],
        ["Stanford", "1885", "Stanford"],
        ["Oxford", "1096", "Oxford"],
    ],
    "T004": [
        ["Person", "Occupation", "Award"],
        ["Barack Obama", "Politician", "Nobel Peace Prize"],
        ["Elon Musk", "Entrepreneur", "N/A"],
        ["Ada Lovelace", "Mathematician", "N/A"],
        ["John Doe", "Unknown", "N/A"],
    ],
    "T005": [
        ["Entity", "Type", "Description"],
        ["Einstien", "Scientist", "Physicist"],
        ["Parris", "City", "Capital"],
        ["M.I.T.", "University", "Tech school"],
    ],
}

for name, rows in tables.items():
    with open(f"{DATA_DIR}/tables/{name}.csv", "w", newline="") as f:
        writer = csv.writer(f)
        for row in rows:
            writer.writerow(row)

# ============================================================
# RDF Knowledge Graph in Turtle format
# Contains owl:sameAs, rdfs:subClassOf, owl:equivalentClass,
# rdfs:subPropertyOf, and property/entity declarations.
# ============================================================
kg_ttl = r"""@prefix wd: <http://www.wikidata.org/entity/> .
@prefix wdt: <http://www.wikidata.org/prop/direct/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

# ======== Entity declarations ========

wd:Q100 rdfs:label "Albert Einstein"@en ;
    rdf:type wd:Q215627 ;
    wdt:P27 wd:Q1200 .

wd:Q200 rdfs:label "Paris"@en ;
    rdf:type wd:Q515 ;
    wdt:P17 wd:Q1000 .

wd:Q300 rdfs:label "Massachusetts Institute of Technology"@en ;
    skos:altLabel "MIT"@en ;
    rdf:type wd:Q3918 ;
    wdt:P131 wd:Q2100 .

wd:Q400 rdfs:label "Marie Curie"@en ;
    rdf:type wd:Q215627 ;
    wdt:P27 wd:Q1000 .

wd:Q500 rdfs:label "Barack Obama"@en ;
    rdf:type wd:Q215627 ;
    wdt:P166 wd:Q1800 .

wd:Q600 rdfs:label "London"@en ;
    rdf:type wd:Q515 ;
    wdt:P17 wd:Q1100 .

wd:Q800 rdfs:label "Isaac Newton"@en ;
    rdf:type wd:Q215627 .

wd:Q900 rdfs:label "Nikola Tesla"@en ;
    rdf:type wd:Q215627 .

wd:Q1000 rdfs:label "France"@en ;
    rdf:type wd:Q7275 .

wd:Q1100 rdfs:label "United Kingdom"@en ;
    rdf:type wd:Q7275 .

wd:Q1200 rdfs:label "Germany"@en ;
    rdf:type wd:Q7275 .

wd:Q1300 rdfs:label "Japan"@en ;
    rdf:type wd:Q7275 .

wd:Q1400 rdfs:label "Stanford University"@en ;
    rdf:type wd:Q3918 .

wd:Q1500 rdfs:label "University of Oxford"@en ;
    skos:altLabel "Oxford"@en ;
    rdf:type wd:Q3918 .

wd:Q1600 rdfs:label "Elon Musk"@en ;
    rdf:type wd:Q215627 .

wd:Q1700 rdfs:label "Ada Lovelace"@en ;
    rdf:type wd:Q215627 .

wd:Q1800 rdfs:label "Nobel Peace Prize"@en ;
    rdf:type wd:Q7191 .

wd:Q7191 rdfs:label "Nobel Prize"@en .

wd:Q1900 rdfs:label "Berlin"@en ;
    rdf:type wd:Q515 .

wd:Q2000 rdfs:label "Tokyo"@en ;
    rdf:type wd:Q515 .

wd:Q2100 rdfs:label "Cambridge"@en ;
    rdf:type wd:Q515 .

wd:Q2200 rdfs:label "Stanford"@en ;
    rdf:type wd:Q515 .

wd:Q2300 rdfs:label "Oxford"@en ;
    rdf:type wd:Q515 .

# ======== owl:sameAs equivalences ========
# owl:sameAs is reflexive, symmetric, and transitive per W3C OWL semantics.
# Some triples below are stated in only one direction.

# Q1 = Q100 (direct)
wd:Q1 owl:sameAs wd:Q100 .

# Q2 and Q3 are equivalent to Q100, but Q2->Q3 link requires symmetry inference.
# Full equivalence class: {Q1, Q2, Q3, Q100}
wd:Q3 owl:sameAs wd:Q2 .
wd:Q3 owl:sameAs wd:Q100 .

# Q201 = Q200
wd:Q201 owl:sameAs wd:Q200 .

# Q301 = Q300
wd:Q301 owl:sameAs wd:Q300 .

# Q600 = Q700 = Q701 (transitive chain)
wd:Q700 owl:sameAs wd:Q600 .
wd:Q701 owl:sameAs wd:Q700 .

# Q10 = Q11 (small equivalence class, unrelated to Q200)
wd:Q10 owl:sameAs wd:Q11 .

# Decoy equivalence (not in any ground truth)
wd:Q998 owl:sameAs wd:Q999 .

# ======== rdfs:subClassOf hierarchy ========
wd:Q215627 rdfs:subClassOf wd:Q5 .       # person subClassOf human
wd:Q515 rdfs:subClassOf wd:Q486972 .     # city subClassOf human settlement
wd:Q486972 rdfs:subClassOf wd:Q43229 .   # human settlement subClassOf geographical object
wd:Q3918 rdfs:subClassOf wd:Q4671277 .   # university subClassOf academic institution
wd:Q4671277 rdfs:subClassOf wd:Q43229 .  # academic institution subClassOf geographical object

# ======== owl:equivalentClass ========
# owl:equivalentClass implies mutual rdfs:subClassOf per W3C OWL semantics.
wd:Q515 owl:equivalentClass wd:Q7930989 .

# Class labels
wd:Q5 rdfs:label "human"@en .
wd:Q215627 rdfs:label "person"@en .
wd:Q515 rdfs:label "city"@en .
wd:Q7930989 rdfs:label "city/town"@en .
wd:Q486972 rdfs:label "human settlement"@en .
wd:Q43229 rdfs:label "geographical object"@en .
wd:Q3918 rdfs:label "university"@en .
wd:Q4671277 rdfs:label "academic institution"@en .
wd:Q7275 rdfs:label "state"@en .

# ======== Property declarations ========
wdt:P27 rdf:type owl:ObjectProperty ;
    rdfs:label "country of citizenship"@en .

wdt:P17 rdf:type owl:ObjectProperty ;
    rdfs:label "country"@en .

wdt:P131 rdf:type owl:ObjectProperty ;
    rdfs:label "located in the administrative territorial entity"@en .

wdt:P276 rdf:type owl:ObjectProperty ;
    rdfs:label "location"@en .

wdt:P166 rdf:type owl:ObjectProperty ;
    rdfs:label "award received"@en .

wdt:P1411 rdf:type owl:ObjectProperty ;
    rdfs:label "nominated for"@en .

wdt:P625 rdf:type owl:ObjectProperty ;
    rdfs:label "coordinate location"@en .

# ======== rdfs:subPropertyOf hierarchy ========
# rdfs:subPropertyOf is transitive per W3C RDFS semantics.
wdt:P276 rdfs:subPropertyOf wdt:P131 .
wdt:P1411 rdfs:subPropertyOf wdt:P166 .
"""

with open(f"{DATA_DIR}/kg.ttl", "w") as f:
    f.write(kg_ttl)

# ============================================================
# Evaluation ontology defining the RDF output vocabulary
# ============================================================
eval_ontology_ttl = r"""@prefix eval: <http://example.org/eval#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .

eval:Evaluation a owl:Class ;
    rdfs:label "Evaluation result for a system on a specific task"@en .

eval:system a owl:DatatypeProperty ;
    rdfs:domain eval:Evaluation ;
    rdfs:range xsd:string ;
    rdfs:label "system identifier"@en .

eval:task a owl:DatatypeProperty ;
    rdfs:domain eval:Evaluation ;
    rdfs:range xsd:string ;
    rdfs:label "task identifier (cea, cta, cpa)"@en .

eval:precision a owl:DatatypeProperty ;
    rdfs:domain eval:Evaluation ;
    rdfs:range xsd:decimal ;
    rdfs:label "precision score"@en .

eval:recall a owl:DatatypeProperty ;
    rdfs:domain eval:Evaluation ;
    rdfs:range xsd:decimal ;
    rdfs:label "recall score"@en .

eval:f1 a owl:DatatypeProperty ;
    rdfs:domain eval:Evaluation ;
    rdfs:range xsd:decimal ;
    rdfs:label "F1 score"@en .

eval:coverage a owl:DatatypeProperty ;
    rdfs:domain eval:Evaluation ;
    rdfs:range xsd:decimal ;
    rdfs:label "coverage (non-abstained / total)"@en .

eval:abstentionRate a owl:DatatypeProperty ;
    rdfs:domain eval:Evaluation ;
    rdfs:range xsd:decimal ;
    rdfs:label "abstention rate"@en .

eval:rank a owl:DatatypeProperty ;
    rdfs:domain eval:Evaluation ;
    rdfs:range xsd:integer ;
    rdfs:label "rank by F1 for this task (1-indexed)"@en .
"""

with open(f"{DATA_DIR}/eval_ontology.ttl", "w") as f:
    f.write(eval_ontology_ttl)

# ============================================================
# Ground truth CEA (28 annotations)
# Format: filename,row_id,col_id,entity_id
# ============================================================
gt_cea = [
    ("T001", 0, 0, "Q100"),
    ("T001", 1, 0, "Q400"),
    ("T001", 2, 0, "Q800"),
    ("T001", 3, 0, "Q900"),
    ("T002", 0, 0, "Q200"),
    ("T002", 1, 0, "Q600"),
    ("T002", 2, 0, "Q1900"),
    ("T002", 3, 0, "Q2000"),
    ("T002", 0, 1, "Q1000"),
    ("T002", 1, 1, "Q1100"),
    ("T002", 2, 1, "Q1200"),
    ("T002", 3, 1, "Q1300"),
    ("T003", 0, 0, "Q300"),
    ("T003", 1, 0, "Q1400"),
    ("T003", 2, 0, "Q1500"),
    ("T003", 0, 2, "Q2100"),
    ("T003", 1, 2, "Q2200"),
    ("T003", 2, 2, "Q2300"),
    ("T004", 0, 0, "Q500"),
    ("T004", 1, 0, "Q1600"),
    ("T004", 2, 0, "Q1700"),
    ("T004", 3, 0, "NIL"),
    ("T004", 0, 2, "Q1800"),
    ("T004", 1, 2, "NIL"),
    ("T004", 2, 2, "NIL"),
    ("T005", 0, 0, "Q100"),
    ("T005", 1, 0, "Q200"),
    ("T005", 2, 0, "Q300"),
]

# Ground truth CTA (5 annotations)
gt_cta = [
    ("T001", 0, "Q215627"),
    ("T002", 0, "Q515"),
    ("T002", 1, "Q7275"),
    ("T003", 0, "Q3918"),
    ("T004", 0, "Q215627"),
]

# Ground truth CPA (3 annotations)
# T004 has no CPA annotation (award column not annotated with a property)
gt_cpa = [
    ("T001", 0, 2, "P27"),
    ("T002", 0, 1, "P17"),
    ("T003", 0, 2, "P131"),
]


def write_csv(path, data):
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        for row in data:
            writer.writerow(row)


write_csv(f"{DATA_DIR}/gt_cea.csv", gt_cea)
write_csv(f"{DATA_DIR}/gt_cta.csv", gt_cta)
write_csv(f"{DATA_DIR}/gt_cpa.csv", gt_cpa)

# ============================================================
# Challenge categories for CEA cells
# ============================================================
challenge_categories = {
    "disambiguation": ["T002:0:0", "T003:0:2", "T003:1:2", "T003:2:2"],
    "homonymy": ["T001:0:0", "T001:2:0"],
    "alias": ["T005:2:0"],
    "nil": ["T004:3:0", "T004:1:2", "T004:2:2"],
    "noise": ["T005:0:0", "T005:1:0"],
}

with open(f"{DATA_DIR}/challenge_categories.json", "w") as f:
    json.dump(challenge_categories, f, indent=2)

# ============================================================
# System A: High-quality system using redirect entity IDs.
# Uses owl:sameAs equivalent IDs (Q1, Q2, Q201, Q301, Q700).
# 27 CEA submissions (missing T005:2:0). All correct via equivalence.
# CTA: uses Q7930989 (equivalentClass of Q515) for T002 col 0.
# CPA: all exact matches.
# ============================================================
system_a_cea = [
    ("T001", 0, 0, "Q1"),
    ("T001", 1, 0, "Q400"),
    ("T001", 2, 0, "Q800"),
    ("T001", 3, 0, "Q900"),
    ("T002", 0, 0, "Q201"),
    ("T002", 1, 0, "Q700"),
    ("T002", 2, 0, "Q1900"),
    ("T002", 3, 0, "Q2000"),
    ("T002", 0, 1, "Q1000"),
    ("T002", 1, 1, "Q1100"),
    ("T002", 2, 1, "Q1200"),
    ("T002", 3, 1, "Q1300"),
    ("T003", 0, 0, "Q301"),
    ("T003", 1, 0, "Q1400"),
    ("T003", 2, 0, "Q1500"),
    ("T003", 0, 2, "Q2100"),
    ("T003", 1, 2, "Q2200"),
    ("T003", 2, 2, "Q2300"),
    ("T004", 0, 0, "Q500"),
    ("T004", 1, 0, "Q1600"),
    ("T004", 2, 0, "Q1700"),
    ("T004", 3, 0, "NIL"),
    ("T004", 0, 2, "Q1800"),
    ("T004", 1, 2, "NIL"),
    ("T004", 2, 2, "NIL"),
    ("T005", 0, 0, "Q2"),
    ("T005", 1, 0, "Q200"),
]

system_a_cta = [
    ("T001", 0, "Q5"),
    ("T002", 0, "Q7930989"),  # owl:equivalentClass with Q515
    ("T002", 1, "Q7275"),
    ("T003", 0, "Q4671277"),
    ("T004", 0, "Q5"),
]

system_a_cpa = [
    ("T001", 0, 2, "P27"),
    ("T002", 0, 1, "P17"),
    ("T003", 0, 2, "P131"),
]

# ============================================================
# System B: Mediocre system with errors and no redirect handling.
# Q10 for GT Q200 — separate equivalence class, wrong.
# CPA uses P625 (no relation to P131) — wrong.
# ============================================================
system_b_cea = [
    ("T001", 0, 0, "Q100"),
    ("T001", 1, 0, "Q400"),
    ("T001", 2, 0, "Q800"),
    ("T001", 3, 0, "Q999"),
    ("T002", 0, 0, "Q200"),
    ("T002", 1, 0, "Q600"),
    ("T002", 2, 0, "Q1900"),
    ("T002", 3, 0, "Q2000"),
    ("T002", 0, 1, "Q1000"),
    ("T002", 1, 1, "Q1100"),
    ("T002", 2, 1, "Q1200"),
    ("T002", 3, 1, "Q1300"),
    ("T003", 0, 0, "Q300"),
    ("T003", 1, 0, "Q1400"),
    ("T003", 2, 0, "Q1500"),
    ("T003", 0, 2, "Q2100"),
    ("T003", 1, 2, "Q1400"),
    ("T003", 2, 2, "Q2300"),
    ("T004", 0, 0, "Q500"),
    ("T004", 1, 0, "Q1600"),
    ("T004", 2, 0, "Q1700"),
    ("T004", 3, 0, "Q999"),
    ("T004", 0, 2, "Q1800"),
    ("T004", 1, 2, "Q999"),
    ("T004", 2, 2, "NIL"),
    ("T005", 0, 0, "Q100"),
    ("T005", 1, 0, "Q10"),
    ("T005", 2, 0, "Q300"),
]

system_b_cta = [
    ("T001", 0, "Q215627"),
    ("T002", 0, "Q486972"),
    ("T002", 1, "Q7275"),
    ("T003", 0, "Q43229"),
    ("T004", 0, "Q999"),
]

system_b_cpa = [
    ("T001", 0, 2, "P27"),
    ("T002", 0, 1, "P17"),
    ("T003", 0, 2, "P625"),   # P625 has no subPropertyOf relation to P131
]

# ============================================================
# System C: Selective prediction with ABSTAIN.
# CPA uses P276 (subPropertyOf P131) for T003.
# ============================================================
system_c_cea = [
    ("T001", 0, 0, "Q100"),
    ("T001", 1, 0, "Q400"),
    ("T001", 2, 0, "Q800"),
    ("T001", 3, 0, "Q900"),
    ("T002", 0, 0, "Q200"),
    ("T002", 1, 0, "Q600"),
    ("T002", 2, 0, "Q1900"),
    ("T002", 3, 0, "Q2000"),
    ("T002", 0, 1, "Q1000"),
    ("T002", 1, 1, "Q1100"),
    ("T002", 2, 1, "Q1200"),
    ("T002", 3, 1, "Q1300"),
    ("T003", 0, 0, "Q300"),
    ("T003", 1, 0, "Q1400"),
    ("T003", 2, 0, "Q1500"),
    ("T003", 0, 2, "ABSTAIN"),
    ("T003", 1, 2, "ABSTAIN"),
    ("T003", 2, 2, "ABSTAIN"),
    ("T004", 0, 0, "Q500"),
    ("T004", 1, 0, "Q1600"),
    ("T004", 2, 0, "Q1700"),
    ("T004", 3, 0, "NIL"),
    ("T004", 0, 2, "Q1800"),
    ("T004", 1, 2, "ABSTAIN"),
    ("T004", 2, 2, "ABSTAIN"),
    ("T005", 0, 0, "ABSTAIN"),
    ("T005", 1, 0, "ABSTAIN"),
    ("T005", 2, 0, "ABSTAIN"),
]

system_c_cta = [
    ("T001", 0, "Q215627"),
    ("T002", 0, "Q515"),
    ("T002", 1, "ABSTAIN"),
    ("T003", 0, "Q3918"),
    ("T004", 0, "Q215627"),
]

system_c_cpa = [
    ("T001", 0, 2, "P27"),
    ("T002", 0, 1, "ABSTAIN"),
    ("T003", 0, 2, "P276"),   # P276 rdfs:subPropertyOf P131 — matches via subsumption
]

write_csv(f"{DATA_DIR}/submissions/system_A_cea.csv", system_a_cea)
write_csv(f"{DATA_DIR}/submissions/system_A_cta.csv", system_a_cta)
write_csv(f"{DATA_DIR}/submissions/system_A_cpa.csv", system_a_cpa)
write_csv(f"{DATA_DIR}/submissions/system_B_cea.csv", system_b_cea)
write_csv(f"{DATA_DIR}/submissions/system_B_cta.csv", system_b_cta)
write_csv(f"{DATA_DIR}/submissions/system_B_cpa.csv", system_b_cpa)
write_csv(f"{DATA_DIR}/submissions/system_C_cea.csv", system_c_cea)
write_csv(f"{DATA_DIR}/submissions/system_C_cta.csv", system_c_cta)
write_csv(f"{DATA_DIR}/submissions/system_C_cpa.csv", system_c_cpa)

# ============================================================
# Evaluation specification — output format and high-level rules.
# Does NOT spell out OWL/RDFS semantics; the solver must know them.
# ============================================================
spec = {
    "description": "SemTab evaluation pipeline specification",
    "output_files": {
        "json": "/app/results.json",
        "ntriples": "/app/results.nt",
    },
    "knowledge_graph": f"{DATA_DIR}/kg.ttl",
    "eval_ontology": f"{DATA_DIR}/eval_ontology.ttl",
    "format": {
        "json": {
            "systems": {
                "<system_name>": {
                    "cea": {
                        "precision": "float",
                        "recall": "float",
                        "f1": "float",
                        "coverage": "float (non-ABSTAIN submissions / GT total)",
                        "abstention_rate": "float (ABSTAIN count / total submissions)",
                    },
                    "cta": "same structure as cea",
                    "cpa": "same structure as cea",
                }
            },
            "rankings": {
                "cea_f1": ["list of system names sorted by CEA F1 descending"],
                "cta_f1": ["list of system names sorted by CTA F1 descending"],
                "cpa_f1": ["list of system names sorted by CPA F1 descending"],
            },
            "category_metrics": {
                "<system_name>": {
                    "<category>": {
                        "correct": "int",
                        "total": "int",
                        "accuracy": "float",
                    }
                }
            },
        },
        "ntriples": {
            "description": "One eval:Evaluation instance per (system, task) pair",
            "uri_pattern": "http://example.org/eval#{system_name}_{task}",
            "required_properties": [
                "rdf:type eval:Evaluation",
                "eval:system (xsd:string)",
                "eval:task (xsd:string)",
                "eval:precision (xsd:decimal)",
                "eval:recall (xsd:decimal)",
                "eval:f1 (xsd:decimal)",
                "eval:coverage (xsd:decimal)",
                "eval:abstentionRate (xsd:decimal)",
                "eval:rank (xsd:integer)",
            ],
            "namespaces": {
                "eval": "http://example.org/eval#",
                "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
                "xsd": "http://www.w3.org/2001/XMLSchema#",
            },
        },
    },
    "evaluation_semantics": {
        "entity_matching": "Use OWL 2 and RDFS entailment from the knowledge graph to determine entity equivalence for CEA.",
        "class_matching": "Use the class hierarchy and class equivalences from the knowledge graph to determine CTA matches via subsumption.",
        "property_matching": "Use the property hierarchy from the knowledge graph to determine CPA matches via subsumption.",
        "nil": "NIL matches only NIL (case-insensitive). NIL entities have no KG presence.",
        "abstain": "ABSTAIN entries are excluded from precision computation. Not counted as correct for recall. Coverage = non-ABSTAIN / GT total.",
        "metrics": "P = #correct / #submitted (excl. ABSTAIN), R = #correct / #GT, F1 = 2*P*R/(P+R) or 0 if P+R=0.",
        "category_accuracy": "#correct_in_category / #total_GT_in_category. ABSTAIN counts as incorrect.",
    },
}

with open(f"{DATA_DIR}/evaluation_spec.json", "w") as f:
    json.dump(spec, f, indent=2)

print("Data generation complete.")
print(f"  Tables: {len(tables)}")
print(f"  GT CEA: {len(gt_cea)} annotations")
print(f"  GT CTA: {len(gt_cta)} annotations")
print(f"  GT CPA: {len(gt_cpa)} annotations")
print(f"  Systems: A, B, C")
