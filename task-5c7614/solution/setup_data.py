#!/usr/bin/env python3
"""Generate evaluation data for the SemTab evaluation task."""

import json
import os
import csv
import sys

BASE = "/opt/semtab_data"


def mkdirs(*paths):
    for p in paths:
        os.makedirs(p, exist_ok=True)


def write_csv(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        for row in rows:
            w.writerow(row)


def write_json(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)


def write_text(path, content):
    with open(path, "w") as f:
        f.write(content)


WD = "http://www.wikidata.org/entity/"
WD_S = "https://www.wikidata.org/entity/"


def main():
    print(f"Creating SemTab data in {BASE} ...", flush=True)

    mkdirs(
        f"{BASE}/tables",
        f"{BASE}/gold",
        f"{BASE}/predictions/alpha",
        f"{BASE}/predictions/beta",
        f"{BASE}/predictions/gamma",
        f"{BASE}/predictions/delta",
        f"{BASE}/ontology",
    )

    # === Tables ===
    write_csv(f"{BASE}/tables/T001.csv", [
        ["Name", "Country"],
        ["Angela Merkel", "Germany"],
        ["Emmanuel Macron", "France"],
        ["Narendra Modi", "India"],
        ["Shinzo Abe", "Japan"],
    ])
    write_csv(f"{BASE}/tables/T002.csv", [
        ["Film", "Director"],
        ["Inception", "Christopher Nolan"],
        ["Parasite", "Bong Joon-ho"],
        ["The Godfather", "Francis Ford Coppola"],
    ])
    write_csv(f"{BASE}/tables/T003.csv", [
        ["Company", "Headquarters"],
        ["Apple Inc.", "Cupertino"],
        ["Toyota", "Toyota City"],
        ["Samsung", "Suwon"],
    ])

    # === Gold Annotations: 20 CEA, 5 CTA, 3 CPA ===
    write_csv(f"{BASE}/gold/cea.csv", [
        ["T001", "1", "0", f"{WD}Q100"],
        ["T001", "1", "1", f"{WD}Q200"],
        ["T001", "2", "0", f"{WD}Q101"],
        ["T001", "2", "1", f"{WD}Q201"],
        ["T001", "3", "0", f"{WD}Q102"],
        ["T001", "3", "1", f"{WD}Q202"],
        ["T001", "4", "0", f"{WD}Q103"],
        ["T001", "4", "1", f"{WD}Q203"],
        ["T002", "1", "0", f"{WD}Q400"],
        ["T002", "1", "1", f"{WD}Q500"],
        ["T002", "2", "0", f"{WD}Q401"],
        ["T002", "2", "1", f"{WD}Q501"],
        ["T002", "3", "0", f"{WD}Q402"],
        ["T002", "3", "1", f"{WD}Q502"],
        ["T003", "1", "0", f"{WD}Q600"],
        ["T003", "1", "1", f"{WD}Q700"],
        ["T003", "2", "0", f"{WD}Q601"],
        ["T003", "2", "1", f"{WD}Q701"],
        ["T003", "3", "0", f"{WD}Q602"],
        ["T003", "3", "1", f"{WD}Q702"],
    ])
    write_csv(f"{BASE}/gold/cta.csv", [
        ["T001", "0", f"{WD}Q82955"],
        ["T001", "1", f"{WD}Q6256"],
        ["T002", "0", f"{WD}Q11424"],
        ["T002", "1", f"{WD}Q2526255"],
        ["T003", "0", f"{WD}Q4830453"],
    ])
    write_csv(f"{BASE}/gold/cpa.csv", [
        ["T001", "0", "1", f"{WD}P27"],
        ["T002", "0", "1", f"{WD}P57"],
        ["T003", "0", "1", f"{WD}P159"],
    ])

    # === System Alpha: Conservative (high P, lower R) ===
    # CEA: 16 submitted, 16 correct => P=1.0, R=16/20=0.8, F1=8/9
    write_csv(f"{BASE}/predictions/alpha/cea.csv", [
        ["T001", "1", "0", f"{WD}Q100"],
        ["T001", "1", "1", f"{WD}Q200"],
        ["T001", "2", "0", f"{WD}Q101"],
        ["T001", "2", "1", f"{WD}Q201"],
        ["T001", "3", "0", f"{WD}Q102"],
        ["T001", "3", "1", f"{WD}Q202"],
        ["T001", "4", "0", f"{WD}Q103"],
        ["T001", "4", "1", f"{WD}Q203"],
        ["T002", "1", "0", f"{WD}Q400"],
        ["T002", "1", "1", f"{WD}Q500"],
        ["T002", "2", "0", f"{WD}Q401"],
        ["T002", "2", "1", f"{WD}Q501"],
        ["T002", "3", "0", f"{WD}Q402"],
        ["T002", "3", "1", f"{WD}Q502"],
        ["T003", "1", "0", f"{WD}Q600"],
        ["T003", "1", "1", f"{WD}Q700"],
    ])
    write_csv(f"{BASE}/predictions/alpha/cta.csv", [
        ["T001", "0", f"{WD}Q82955"],
        ["T001", "1", f"{WD}Q6256"],
        ["T002", "0", f"{WD}Q11424"],
        ["T002", "1", f"{WD}Q2526255"],
    ])
    write_csv(f"{BASE}/predictions/alpha/cpa.csv", [
        ["T001", "0", "1", f"{WD}P27"],
        ["T002", "0", "1", f"{WD}P57"],
    ])

    # === System Beta: Aggressive (lower P, higher R) ===
    # Some predictions use https:// variant to test URI normalization
    # CEA: 24 submitted, 18 correct => P=0.75, R=0.9, F1=9/11
    write_csv(f"{BASE}/predictions/beta/cea.csv", [
        ["T001", "1", "0", f"{WD_S}Q100"],
        ["T001", "1", "1", f"{WD}Q200"],
        ["T001", "2", "0", f"{WD}Q101"],
        ["T001", "2", "1", f"{WD_S}Q201"],
        ["T001", "3", "0", f"{WD}Q102"],
        ["T001", "3", "1", f"{WD}Q202"],
        ["T001", "4", "0", f"{WD}Q103"],
        ["T001", "4", "1", f"{WD}Q203"],
        ["T002", "1", "0", f"{WD}Q400"],
        ["T002", "1", "1", f"{WD}Q500"],
        ["T002", "2", "0", f"{WD}Q401"],
        ["T002", "2", "1", f"{WD}Q501"],
        ["T002", "3", "0", f"{WD}Q402"],
        ["T002", "3", "1", f"{WD}Q999"],
        ["T003", "1", "0", f"{WD}Q600"],
        ["T003", "1", "1", f"{WD}Q700"],
        ["T003", "2", "0", f"{WD}Q601"],
        ["T003", "2", "1", f"{WD}Q701"],
        ["T003", "3", "0", f"{WD}Q602"],
        ["T003", "3", "1", f"{WD}Q999"],
        ["T001", "1", "2", f"{WD}Q888"],
        ["T001", "2", "2", f"{WD}Q888"],
        ["T002", "1", "2", f"{WD}Q888"],
        ["T002", "2", "2", f"{WD}Q888"],
    ])
    write_csv(f"{BASE}/predictions/beta/cta.csv", [
        ["T001", "0", f"{WD}Q5"],
        ["T001", "1", f"{WD}Q6256"],
        ["T002", "0", f"{WD}Q11424"],
        ["T002", "1", f"{WD}Q2526255"],
        ["T003", "0", f"{WD}Q4830453"],
        ["T003", "1", f"{WD}Q515"],
    ])
    write_csv(f"{BASE}/predictions/beta/cpa.csv", [
        ["T001", "0", "1", f"{WD}P27"],
        ["T002", "0", "1", f"{WD}P57"],
        ["T003", "0", "1", f"{WD}P159"],
        ["T003", "1", "0", f"{WD}P999"],
    ])

    # === System Gamma: Balanced, with confidence scores ===
    # Uses short-form entity IDs (no URI prefix) to test normalization
    # CEA: 20 submitted, 17 correct => P=0.85, R=0.85, F1=0.85
    write_csv(f"{BASE}/predictions/gamma/cea.csv", [
        ["T001", "1", "0", "Q100"],
        ["T001", "1", "1", "Q200"],
        ["T001", "2", "0", "Q101"],
        ["T001", "2", "1", "Q201"],
        ["T001", "3", "0", "Q102"],
        ["T001", "3", "1", "Q202"],
        ["T001", "4", "0", "Q103"],
        ["T001", "4", "1", "Q999"],
        ["T002", "1", "0", "Q400"],
        ["T002", "1", "1", "Q500"],
        ["T002", "2", "0", "Q401"],
        ["T002", "2", "1", "Q501"],
        ["T002", "3", "0", "Q999"],
        ["T002", "3", "1", "Q502"],
        ["T003", "1", "0", "Q600"],
        ["T003", "1", "1", "Q700"],
        ["T003", "2", "0", "Q601"],
        ["T003", "2", "1", "Q701"],
        ["T003", "3", "0", "Q602"],
        ["T003", "3", "1", "Q999"],
    ])
    write_csv(f"{BASE}/predictions/gamma/cea_confidence.csv", [
        ["T001", "1", "0", "0.99"],
        ["T001", "1", "1", "0.98"],
        ["T001", "2", "0", "0.97"],
        ["T001", "2", "1", "0.96"],
        ["T001", "3", "0", "0.95"],
        ["T001", "3", "1", "0.94"],
        ["T001", "4", "0", "0.90"],
        ["T001", "4", "1", "0.85"],
        ["T002", "1", "0", "0.92"],
        ["T002", "1", "1", "0.88"],
        ["T002", "2", "0", "0.87"],
        ["T002", "2", "1", "0.80"],
        ["T002", "3", "0", "0.60"],
        ["T002", "3", "1", "0.75"],
        ["T003", "1", "0", "0.93"],
        ["T003", "1", "1", "0.70"],
        ["T003", "2", "0", "0.65"],
        ["T003", "2", "1", "0.55"],
        ["T003", "3", "0", "0.50"],
        ["T003", "3", "1", "0.35"],
    ])
    write_csv(f"{BASE}/predictions/gamma/cta.csv", [
        ["T001", "0", "Q82955"],
        ["T001", "1", "Q6256"],
        ["T002", "0", "Q11424"],
        ["T002", "1", "Q5"],
        ["T003", "0", "Q4830453"],
    ])
    write_csv(f"{BASE}/predictions/gamma/cpa.csv", [
        ["T001", "0", "1", "P27"],
        ["T002", "0", "1", "P999"],
        ["T003", "0", "1", "P159"],
    ])

    # === System Delta: Uses redirected entity IDs ===
    # CEA: 20 submitted, all correct via redirect resolution => P=R=F1=1.0
    write_csv(f"{BASE}/predictions/delta/cea.csv", [
        ["T001", "1", "0", f"{WD}Q100X"],
        ["T001", "1", "1", f"{WD}Q200"],
        ["T001", "2", "0", f"{WD}Q101"],
        ["T001", "2", "1", f"{WD}Q201R"],
        ["T001", "3", "0", f"{WD}Q102"],
        ["T001", "3", "1", f"{WD}Q202"],
        ["T001", "4", "0", f"{WD}Q103"],
        ["T001", "4", "1", f"{WD}Q203"],
        ["T002", "1", "0", f"{WD}Q400"],
        ["T002", "1", "1", f"{WD}Q500R"],
        ["T002", "2", "0", f"{WD}Q401"],
        ["T002", "2", "1", f"{WD}Q501"],
        ["T002", "3", "0", f"{WD}Q402"],
        ["T002", "3", "1", f"{WD}Q502"],
        ["T003", "1", "0", f"{WD}Q600R"],
        ["T003", "1", "1", f"{WD}Q700"],
        ["T003", "2", "0", f"{WD}Q601"],
        ["T003", "2", "1", f"{WD}Q701"],
        ["T003", "3", "0", f"{WD}Q602"],
        ["T003", "3", "1", f"{WD}Q702"],
    ])
    write_csv(f"{BASE}/predictions/delta/cta.csv", [
        ["T001", "0", f"{WD}Q5"],
        ["T001", "1", f"{WD}Q6256"],
        ["T002", "0", f"{WD}Q11424"],
        ["T002", "1", f"{WD}Q2526255"],
        ["T003", "0", f"{WD}Q43229"],
    ])
    write_csv(f"{BASE}/predictions/delta/cpa.csv", [
        ["T001", "0", "1", f"{WD}P27"],
        ["T002", "0", "1", f"{WD}P57"],
        ["T003", "0", "1", f"{WD}P159"],
    ])

    # === Ontology: Type hierarchy in Turtle RDF format ===
    write_text(f"{BASE}/ontology/type_hierarchy.ttl", """\
@prefix wd: <http://www.wikidata.org/entity/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

wd:Q35120 rdfs:label "Thing" .

wd:Q5 rdfs:subClassOf wd:Q35120 ;
     rdfs:label "Person" .

wd:Q82955 rdfs:subClassOf wd:Q5 ;
          rdfs:label "Politician" .

wd:Q2526255 rdfs:subClassOf wd:Q5 ;
            rdfs:label "FilmDirector" .

wd:Q6256 rdfs:subClassOf wd:Q35120 ;
         rdfs:label "Country" .

wd:Q515 rdfs:subClassOf wd:Q35120 ;
        rdfs:label "City" .

wd:Q43229 rdfs:subClassOf wd:Q35120 ;
          rdfs:label "Organization" .

wd:Q4830453 rdfs:subClassOf wd:Q43229 ;
            rdfs:label "Company" .

wd:Q11424 rdfs:subClassOf wd:Q35120 ;
          rdfs:label "Film" .

wd:Q12737 rdfs:subClassOf wd:Q35120 ;
          rdfs:label "Industry" .
""")

    # === Ontology: Entity redirects in N-Triples RDF format ===
    write_text(f"{BASE}/ontology/entity_redirects.nt", """\
<http://www.wikidata.org/entity/Q100R> <http://www.w3.org/2002/07/owl#sameAs> <http://www.wikidata.org/entity/Q100> .
<http://www.wikidata.org/entity/Q100X> <http://www.w3.org/2002/07/owl#sameAs> <http://www.wikidata.org/entity/Q100R> .
<http://www.wikidata.org/entity/Q201R> <http://www.w3.org/2002/07/owl#sameAs> <http://www.wikidata.org/entity/Q201> .
<http://www.wikidata.org/entity/Q500R> <http://www.w3.org/2002/07/owl#sameAs> <http://www.wikidata.org/entity/Q500> .
<http://www.wikidata.org/entity/Q600R> <http://www.w3.org/2002/07/owl#sameAs> <http://www.wikidata.org/entity/Q600> .
""")

    # === Config ===
    write_json(f"{BASE}/config.json", {
        "systems": ["alpha", "beta", "gamma", "delta"],
        "systems_with_confidence": ["gamma"],
    })

    # === Output schema ===
    write_json(f"{BASE}/schema.json", {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "description": "SemTab system evaluation results",
        "type": "object",
        "required": ["systems", "ranking"],
        "properties": {
            "systems": {
                "type": "object",
                "description": "Evaluation results keyed by system name",
                "additionalProperties": {
                    "type": "object",
                    "required": ["cea", "cta", "cpa", "cta_hierarchy", "cea_per_table", "aurc"],
                    "properties": {
                        "cea": {
                            "description": "Cell Entity Annotation evaluation",
                            "$ref": "#/definitions/prf"
                        },
                        "cta": {
                            "description": "Column Type Annotation evaluation",
                            "$ref": "#/definitions/prf"
                        },
                        "cpa": {
                            "description": "Column Property Annotation evaluation",
                            "$ref": "#/definitions/prf"
                        },
                        "cta_hierarchy": {
                            "description": "Column Type Annotation with type-hierarchy-aware scoring",
                            "$ref": "#/definitions/prf"
                        },
                        "cea_per_table": {
                            "description": "Per-table Cell Entity Annotation breakdown",
                            "type": "object",
                            "additionalProperties": {
                                "$ref": "#/definitions/prf"
                            }
                        },
                        "aurc": {
                            "description": "Area Under Risk-Coverage Curve for selective prediction (null if no confidence data)",
                            "type": ["number", "null"]
                        }
                    }
                }
            },
            "ranking": {
                "description": "Systems ordered by Cell Entity Annotation F1 (descending), precision as tiebreaker",
                "type": "array",
                "items": {"type": "string"}
            }
        },
        "definitions": {
            "prf": {
                "type": "object",
                "required": ["precision", "recall", "f1"],
                "properties": {
                    "precision": {"type": "number", "minimum": 0, "maximum": 1},
                    "recall": {"type": "number", "minimum": 0, "maximum": 1},
                    "f1": {"type": "number", "minimum": 0, "maximum": 1}
                }
            }
        }
    })

    # === Reference values (verified subset) ===
    write_json(f"{BASE}/reference.json", {
        "_note": "Independently verified subset. All values are ground truth (tolerance: 1e-4).",
        "systems": {
            "alpha": {
                "cea": {"precision": 1.0, "recall": 0.8, "f1": 0.8889},
                "cea_per_table": {
                    "T001": {"precision": 1.0, "recall": 1.0, "f1": 1.0}
                }
            },
            "delta": {
                "cea": {"f1": 1.0},
                "cta_hierarchy": {"precision": 0.8, "recall": 0.8, "f1": 0.8}
            },
            "gamma": {
                "aurc": 0.042244
            }
        },
        "ranking": ["delta", "alpha", "gamma", "beta"]
    })

    # Verify
    expected = [
        f"{BASE}/config.json",
        f"{BASE}/schema.json",
        f"{BASE}/reference.json",
        f"{BASE}/gold/cea.csv",
        f"{BASE}/gold/cta.csv",
        f"{BASE}/gold/cpa.csv",
        f"{BASE}/ontology/type_hierarchy.ttl",
        f"{BASE}/ontology/entity_redirects.nt",
    ]
    for fp in expected:
        if not os.path.exists(fp):
            print(f"ERROR: {fp} was not created!", file=sys.stderr)
            sys.exit(1)

    print("SemTab evaluation data generated successfully.", flush=True)
    print(f"Verified {len(expected)} key files exist.", flush=True)


if __name__ == "__main__":
    main()
