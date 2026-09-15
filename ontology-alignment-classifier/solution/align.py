#!/usr/bin/env python3
"""
Ontology alignment solution: parse OWL ontologies including complex DL axioms,
extract multi-signal features, classify candidate pairs into 5 relation types.
"""

import csv
import re
from collections import defaultdict

from rdflib import Graph, Namespace, URIRef, BNode
from rdflib.namespace import RDF, RDFS, OWL, SKOS, DC


SOURCE_OWL = "/app/data/source_ontology.owl"
TARGET_OWL = "/app/data/target_ontology.owl"
REFERENCE_CSV = "/app/data/reference_sample.csv"
CANDIDATES_CSV = "/app/data/candidate_pairs.csv"
OUTPUT_CSV = "/app/alignment_output.csv"

SOURCE_NS = "http://example.org/retailprod#"
TARGET_NS = "http://example.org/industrialsupply#"


def parse_rdf_list(g, head):
    """Parse an RDF Collection (rdf:first/rdf:rest) into a Python list."""
    items = []
    current = head
    while current and current != RDF.nil:
        first = None
        for _, _, o in g.triples((current, RDF.first, None)):
            first = o
        if first is not None:
            items.append(first)
        rest = None
        for _, _, o in g.triples((current, RDF.rest, None)):
            rest = o
        current = rest
    return items


def parse_ontology(owl_path, ns_uri):
    """Parse an OWL ontology extracting classes, hierarchy, restrictions, and axioms."""
    g = Graph()
    g.parse(owl_path, format="xml")
    ns = Namespace(ns_uri)

    classes = {}
    for cls in g.subjects(RDF.type, OWL.Class):
        cls_str = str(cls)
        if not cls_str.startswith(ns_uri):
            continue
        cls_id = cls_str.replace(ns_uri, "")

        labels = []
        for lbl in g.objects(cls, RDFS.label):
            labels.append(str(lbl).lower().strip())

        alt_labels = []
        for alt in g.objects(cls, SKOS.altLabel):
            alt_labels.append(str(alt).lower().strip())

        descriptions = []
        for desc in g.objects(cls, RDFS.comment):
            descriptions.append(str(desc).lower().strip())

        parent = None
        for p in g.objects(cls, RDFS.subClassOf):
            p_str = str(p)
            if p_str.startswith(ns_uri) and not isinstance(p, BNode):
                parent = p_str.replace(ns_uri, "")
                break

        classes[cls_id] = {
            "labels": labels,
            "alt_labels": alt_labels,
            "descriptions": descriptions,
            "parent": parent,
            "all_labels": labels + alt_labels,
        }

    # Extract equivalent class axioms with restrictions
    equiv_defs = {}  # class_id -> list of (base_class, property, filler)
    for s, _, o in g.triples((None, OWL.equivalentClass, None)):
        s_str = str(s)
        if not s_str.startswith(ns_uri):
            continue
        cls_id = s_str.replace(ns_uri, "")
        if isinstance(o, BNode):
            # Check for intersectionOf
            for _, _, intersection_head in g.triples((o, OWL.intersectionOf, None)):
                items = parse_rdf_list(g, intersection_head)
                base_class = None
                restriction_prop = None
                restriction_filler = None
                for item in items:
                    if isinstance(item, URIRef):
                        item_str = str(item)
                        if item_str.startswith(ns_uri):
                            base_class = item_str.replace(ns_uri, "")
                    elif isinstance(item, BNode):
                        for _, _, prop in g.triples((item, OWL.onProperty, None)):
                            restriction_prop = str(prop).replace(ns_uri, "")
                        for _, _, filler in g.triples((item, OWL.someValuesFrom, None)):
                            restriction_filler = str(filler).replace(ns_uri, "")
                if base_class and restriction_prop and restriction_filler:
                    if cls_id not in equiv_defs:
                        equiv_defs[cls_id] = []
                    equiv_defs[cls_id].append((base_class, restriction_prop, restriction_filler))

    # Extract subClassOf restriction axioms
    restriction_defs = {}  # class_id -> list of (property, filler)
    for s, _, o in g.triples((None, RDFS.subClassOf, None)):
        s_str = str(s)
        if not s_str.startswith(ns_uri):
            continue
        if not isinstance(o, BNode):
            continue
        cls_id = s_str.replace(ns_uri, "")
        for _, _, prop in g.triples((o, OWL.onProperty, None)):
            for _, _, filler in g.triples((o, OWL.someValuesFrom, None)):
                prop_id = str(prop).replace(ns_uri, "")
                filler_id = str(filler).replace(ns_uri, "")
                if cls_id not in restriction_defs:
                    restriction_defs[cls_id] = []
                restriction_defs[cls_id].append((prop_id, filler_id))

    # Extract disjoint axioms
    disjoints = set()
    for s, _, o in g.triples((None, OWL.disjointWith, None)):
        s_str = str(s).replace(ns_uri, "")
        o_str = str(o).replace(ns_uri, "")
        if s_str in classes and o_str in classes:
            disjoints.add((s_str, o_str))
            disjoints.add((o_str, s_str))

    # Build hierarchy helpers
    children = defaultdict(set)
    for cls_id, info in classes.items():
        if info["parent"]:
            children[info["parent"]].add(cls_id)

    # Compute ancestors for each class
    ancestors = {}
    for cls_id in classes:
        anc = set()
        current = classes[cls_id]["parent"]
        while current and current in classes:
            anc.add(current)
            current = classes[current]["parent"]
        ancestors[cls_id] = anc

    # Compute descendants for each class
    descendants = {}
    def get_descendants(cid):
        if cid in descendants:
            return descendants[cid]
        desc = set()
        for child in children.get(cid, []):
            desc.add(child)
            desc.update(get_descendants(child))
        descendants[cid] = desc
        return desc

    for cls_id in classes:
        get_descendants(cls_id)

    # Compute depth for each class
    depths = {}
    for cls_id in classes:
        depth = 0
        current = classes[cls_id]["parent"]
        while current and current in classes:
            depth += 1
            current = classes[current]["parent"]
        depths[cls_id] = depth

    # Find top-level domain for each class
    domains = {}
    for cls_id in classes:
        if classes[cls_id]["parent"] is None:
            domains[cls_id] = cls_id
        else:
            current = cls_id
            while classes.get(current, {}).get("parent") and \
                  classes.get(classes[current]["parent"], {}).get("parent") is not None:
                current = classes[current]["parent"]
            domains[cls_id] = current

    return {
        "classes": classes,
        "disjoints": disjoints,
        "children": children,
        "ancestors": ancestors,
        "descendants": descendants,
        "depths": depths,
        "domains": domains,
        "equiv_defs": equiv_defs,
        "restriction_defs": restriction_defs,
    }


def tokenize(text):
    """Tokenize a string into lowercase words with basic plural normalization."""
    raw = set(re.findall(r'[a-z]+', text.lower()))
    normalized = set()
    for t in raw:
        if t.endswith('ies') and len(t) > 4:
            normalized.add(t[:-3] + 'y')
        elif t.endswith('s') and len(t) > 2 and not t.endswith('ss'):
            normalized.add(t[:-1])
        else:
            normalized.add(t)
    return normalized


def jaccard(set_a, set_b):
    """Compute Jaccard similarity between two sets."""
    if not set_a and not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union) if union else 0.0


def best_label_similarity(src_info, tgt_info):
    """Find the best label similarity across all label combinations."""
    best = 0.0
    src_texts = src_info["all_labels"]
    tgt_texts = tgt_info["all_labels"]
    if not src_texts or not tgt_texts:
        return 0.0
    for s in src_texts:
        s_tokens = tokenize(s)
        for t in tgt_texts:
            t_tokens = tokenize(t)
            sim = jaccard(s_tokens, t_tokens)
            if sim > best:
                best = sim
    return best


def description_similarity(src_info, tgt_info):
    """Compute description token overlap."""
    src_desc = " ".join(src_info["descriptions"])
    tgt_desc = " ".join(tgt_info["descriptions"])
    src_tokens = tokenize(src_desc)
    tgt_tokens = tokenize(tgt_desc)
    return jaccard(src_tokens, tgt_tokens)


STOPWORDS = {
    "and", "or", "the", "a", "an", "of", "for", "in", "to", "with",
    "from", "by", "on", "at", "is", "are", "all", "any", "it",
    "product", "item", "good", "including",
}


def content_tokens(info):
    """Get meaningful content tokens from labels and descriptions."""
    all_text = " ".join(info["all_labels"] + info["descriptions"])
    tokens = tokenize(all_text)
    return tokens - STOPWORDS


def restriction_similarity(src_id, tgt_id, src_onto, tgt_onto):
    """Compare restriction scopes between two classes across ontologies."""
    src_equiv = src_onto["equiv_defs"].get(src_id, [])
    tgt_equiv = tgt_onto["equiv_defs"].get(tgt_id, [])
    src_restr = src_onto["restriction_defs"].get(src_id, [])
    tgt_restr = tgt_onto["restriction_defs"].get(tgt_id, [])

    # Collect all restriction filler labels
    src_fillers = set()
    for _, _, filler in src_equiv:
        filler_info = src_onto["classes"].get(filler, {})
        if filler_info:
            src_fillers.update(tokenize(" ".join(filler_info.get("labels", []) +
                                                  filler_info.get("descriptions", []))))
    for _, filler in src_restr:
        filler_info = src_onto["classes"].get(filler, {})
        if filler_info:
            src_fillers.update(tokenize(" ".join(filler_info.get("labels", []) +
                                                  filler_info.get("descriptions", []))))

    tgt_fillers = set()
    for _, _, filler in tgt_equiv:
        filler_info = tgt_onto["classes"].get(filler, {})
        if filler_info:
            tgt_fillers.update(tokenize(" ".join(filler_info.get("labels", []) +
                                                  filler_info.get("descriptions", []))))
    for _, filler in tgt_restr:
        filler_info = tgt_onto["classes"].get(filler, {})
        if filler_info:
            tgt_fillers.update(tokenize(" ".join(filler_info.get("labels", []) +
                                                  filler_info.get("descriptions", []))))

    if src_fillers and tgt_fillers:
        return jaccard(src_fillers, tgt_fillers)
    return 0.0


def check_ancestor_disjoint(src_id, tgt_id, src_onto, tgt_onto, equivalences):
    """Check if src and tgt are in domains that are disjoint."""
    src_domain = src_onto["domains"].get(src_id)
    tgt_domain = tgt_onto["domains"].get(tgt_id)

    if not src_domain or not tgt_domain:
        return False

    src_ancestors_plus = src_onto["ancestors"].get(src_id, set()) | {src_id}
    tgt_ancestors_plus = tgt_onto["ancestors"].get(tgt_id, set()) | {tgt_id}

    for sa in src_ancestors_plus:
        for equiv_tgt in equivalences.get(sa, []):
            et_domain = tgt_onto["domains"].get(equiv_tgt)
            if et_domain and et_domain != tgt_domain:
                for ta in tgt_ancestors_plus:
                    if (equiv_tgt, ta) in tgt_onto["disjoints"] or \
                       (et_domain, tgt_domain) in tgt_onto["disjoints"]:
                        return True

    return False


def check_scope_asymmetry(src_info, tgt_info):
    """Check if descriptions reveal asymmetric scope (one broader than the other)."""
    src_desc_tokens = tokenize(" ".join(src_info["descriptions"]))
    tgt_desc_tokens = tokenize(" ".join(tgt_info["descriptions"]))

    if not src_desc_tokens or not tgt_desc_tokens:
        return 0.0

    # Proportion of target description contained in source
    tgt_in_src = len(tgt_desc_tokens & src_desc_tokens) / len(tgt_desc_tokens)
    src_in_tgt = len(src_desc_tokens & tgt_desc_tokens) / len(src_desc_tokens)

    # Positive means source is broader, negative means target is broader
    return tgt_in_src - src_in_tgt


def count_children_recursive(cls_id, onto):
    """Count total descendants of a class."""
    return len(onto["descendants"].get(cls_id, set()))


def classify_pair(src_id, tgt_id, src_onto, tgt_onto, equivalences):
    """Classify a single pair into one of the 5 relation types."""
    src_info = src_onto["classes"].get(src_id)
    tgt_info = tgt_onto["classes"].get(tgt_id)

    if not src_info or not tgt_info:
        return "!"

    # Feature computation
    label_sim = best_label_similarity(src_info, tgt_info)
    desc_sim = description_similarity(src_info, tgt_info)
    src_depth = src_onto["depths"].get(src_id, 0)
    tgt_depth = tgt_onto["depths"].get(tgt_id, 0)
    src_domain = src_onto["domains"].get(src_id)
    tgt_domain = tgt_onto["domains"].get(tgt_id)

    src_content = content_tokens(src_info)
    tgt_content = content_tokens(tgt_info)
    content_sim = jaccard(src_content, tgt_content)

    combined_sim = 0.5 * label_sim + 0.3 * desc_sim + 0.2 * content_sim

    # Restriction scope comparison
    restr_sim = restriction_similarity(src_id, tgt_id, src_onto, tgt_onto)

    # Scope asymmetry from descriptions
    scope_asym = check_scope_asymmetry(src_info, tgt_info)

    # Subtree size comparison
    src_subtree = count_children_recursive(src_id, src_onto)
    tgt_subtree = count_children_recursive(tgt_id, tgt_onto)

    # Domain similarity
    if src_domain and tgt_domain:
        src_domain_info = src_onto["classes"].get(src_domain, {})
        tgt_domain_info = tgt_onto["classes"].get(tgt_domain, {})
        if src_domain_info and tgt_domain_info:
            domain_label_sim = best_label_similarity(src_domain_info, tgt_domain_info)
            domain_desc_sim = description_similarity(src_domain_info, tgt_domain_info)
        else:
            domain_label_sim = 0.0
            domain_desc_sim = 0.0
    else:
        domain_label_sim = 0.0
        domain_desc_sim = 0.0

    domain_sim = 0.6 * domain_label_sim + 0.4 * domain_desc_sim

    # --- Classification rules ---

    # Rule 1: High label similarity -> likely equivalence, but check for scope differences
    if label_sim >= 0.4 and combined_sim >= 0.3:
        # Check for scope asymmetry indicating subsumption
        # If target has significantly more descendants or broader description
        if tgt_subtree > src_subtree + 2 and (scope_asym < -0.15 or tgt_subtree > src_subtree * 2):
            return "<"
        if src_subtree > tgt_subtree + 2 and (scope_asym > 0.15 or src_subtree > tgt_subtree * 2):
            return ">"

        # Check if src is a parent of something more equivalent to tgt
        src_descs = src_onto["descendants"].get(src_id, set())
        for sd in src_descs:
            sd_info = src_onto["classes"].get(sd)
            if sd_info:
                sd_sim = best_label_similarity(sd_info, tgt_info)
                if sd_sim > label_sim and sd_sim >= 0.4:
                    return ">"

        # Check if tgt is a parent of something more equivalent to src
        tgt_descs = tgt_onto["descendants"].get(tgt_id, set())
        for td in tgt_descs:
            td_info = tgt_onto["classes"].get(td)
            if td_info:
                td_sim = best_label_similarity(src_info, td_info)
                if td_sim > label_sim and td_sim >= 0.4:
                    return "<"

        # Check description scope for broader/narrower hints
        src_desc_text = " ".join(src_info["descriptions"]).lower()
        tgt_desc_text = " ".join(tgt_info["descriptions"]).lower()

        # Count enumerated items in descriptions (comma/and-separated lists)
        src_items = len(re.findall(r',', src_desc_text)) + 1
        tgt_items = len(re.findall(r',', tgt_desc_text)) + 1

        # Indicators that target is broader
        broader_indicators = ["including", "and other", "various", "all types", "multiple"]
        tgt_broader_score = sum(1 for ind in broader_indicators if ind in tgt_desc_text)
        src_broader_score = sum(1 for ind in broader_indicators if ind in src_desc_text)

        if tgt_broader_score > src_broader_score and tgt_subtree >= src_subtree:
            return "<"
        if src_broader_score > tgt_broader_score and src_subtree >= tgt_subtree:
            return ">"

        # If target enumerates significantly more items, it's likely broader
        if tgt_items > src_items + 2 and tgt_subtree >= src_subtree:
            return "<"
        if src_items > tgt_items + 2 and src_subtree >= tgt_subtree:
            return ">"

        return "="

    # Rule 2: Very low domain similarity -> disjoint
    if domain_sim < 0.05 and combined_sim < 0.15:
        return "!"

    # Rule 3: Check for superclass/subclass via hierarchy
    # Source is parent of something equivalent to target
    src_descs = src_onto["descendants"].get(src_id, set())
    for sd in src_descs:
        sd_info = src_onto["classes"].get(sd)
        if sd_info:
            sd_sim = best_label_similarity(sd_info, tgt_info)
            if sd_sim >= 0.35:
                return ">"

    # Target is parent of something equivalent to source
    tgt_descs = tgt_onto["descendants"].get(tgt_id, set())
    for td in tgt_descs:
        td_info = tgt_onto["classes"].get(td)
        if td_info:
            td_sim = best_label_similarity(src_info, td_info)
            if td_sim >= 0.35:
                return "<"

    # Rule 4: Moderate similarity in related domains -> overlap or subsumption
    if domain_sim >= 0.1 or combined_sim >= 0.1:
        # Check for directional subsumption by analyzing description scope
        if scope_asym > 0.2:
            return ">"
        if scope_asym < -0.2:
            return "<"

        # Check subtree asymmetry for nearby classes
        if combined_sim >= 0.2:
            if tgt_subtree > src_subtree * 2 + 1:
                return "<"
            if src_subtree > tgt_subtree * 2 + 1:
                return ">"

        # Same domain, moderate similarity -> overlap
        if combined_sim >= 0.15:
            return "~"

        # Low similarity but same broad area
        if domain_sim >= 0.05 and combined_sim < 0.1:
            return "!"

        return "~"

    # Rule 5: Default to disjoint for very low similarity
    return "!"


def main():
    print("Parsing source ontology...")
    src_onto = parse_ontology(SOURCE_OWL, SOURCE_NS)
    print(f"  Found {len(src_onto['classes'])} classes")
    print(f"  Equivalent class defs: {len(src_onto['equiv_defs'])}")
    print(f"  Restriction axioms: {len(src_onto['restriction_defs'])}")

    print("Parsing target ontology...")
    tgt_onto = parse_ontology(TARGET_OWL, TARGET_NS)
    print(f"  Found {len(tgt_onto['classes'])} classes")
    print(f"  Equivalent class defs: {len(tgt_onto['equiv_defs'])}")
    print(f"  Restriction axioms: {len(tgt_onto['restriction_defs'])}")

    # Load reference sample to build initial equivalence map
    print("Loading reference sample...")
    ref_equivalences = defaultdict(list)
    with open(REFERENCE_CSV, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["relation"].strip() == "=":
                ref_equivalences[row["source_id"].strip()].append(
                    row["target_id"].strip()
                )

    # First pass: find likely equivalences among all candidates
    print("Finding equivalences...")
    equivalences = defaultdict(list)
    equivalences.update(ref_equivalences)

    candidates = []
    with open(CANDIDATES_CSV, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            candidates.append(
                (row["source_id"].strip(), row["target_id"].strip())
            )

    # Pre-scan for high-confidence equivalences
    for src_id, tgt_id in candidates:
        src_info = src_onto["classes"].get(src_id)
        tgt_info = tgt_onto["classes"].get(tgt_id)
        if src_info and tgt_info:
            sim = best_label_similarity(src_info, tgt_info)
            if sim >= 0.5 and src_id not in equivalences:
                equivalences[src_id].append(tgt_id)

    # Classify all candidate pairs
    print("Classifying candidate pairs...")
    results = []
    for src_id, tgt_id in candidates:
        rel = classify_pair(src_id, tgt_id, src_onto, tgt_onto, equivalences)
        results.append((src_id, tgt_id, rel))

    # Write output
    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["source_id", "target_id", "relation"])
        for src_id, tgt_id, rel in results:
            writer.writerow([src_id, tgt_id, rel])

    print(f"Wrote {len(results)} alignments to {OUTPUT_CSV}")

    # Print summary
    from collections import Counter
    counts = Counter(r[2] for r in results)
    print("Relation distribution:")
    for rel, count in sorted(counts.items()):
        print(f"  {rel}: {count}")


if __name__ == "__main__":
    main()
