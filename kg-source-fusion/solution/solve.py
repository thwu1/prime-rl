#!/usr/bin/env python3
"""

Multi-source knowledge graph fusion pipeline.
"""

import json
import csv
import yaml
from pathlib import Path
from collections import defaultdict
from rdflib import Graph, URIRef, Literal, RDF, RDFS


# =============================================================================
# Union-Find for Entity Resolution
# =============================================================================

class UnionFind:
    def __init__(self):
        self.parent = {}
        self.rank = {}

    def find(self, x):
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x, y):
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self.rank[rx] < self.rank[ry]:
            rx, ry = ry, rx
        self.parent[ry] = rx
        if self.rank[rx] == self.rank[ry]:
            self.rank[rx] += 1

    def get_clusters(self):
        clusters = defaultdict(set)
        for x in self.parent:
            clusters[self.find(x)].add(x)
        return dict(clusters)


# =============================================================================
# Source Parsing
# =============================================================================

def parse_seed(path):
    g = Graph()
    g.parse(path, format="nt")
    triples = []
    labels = {}
    for s, p, o in g:
        s_str = str(s)
        if p == RDFS.label:
            labels[s_str] = str(o)
        triples.append((s_str, str(p), o))
    return triples, labels


def parse_rdf_source(path, schema_mappings):
    g = Graph()
    g.parse(path, format="turtle")

    pred_map = schema_mappings.get("predicates", {})
    class_map = schema_mappings.get("classes", {})

    triples = []
    labels = {}

    for s, p, o in g:
        s_str = str(s)
        p_str = str(p)

        if p_str in pred_map:
            p_str = pred_map[p_str]

        if p_str == str(RDF.type) and isinstance(o, URIRef):
            o_str = str(o)
            if o_str in class_map:
                o = URIRef(class_map[o_str])

        if p == RDFS.label:
            labels[s_str] = str(o)

        triples.append((s_str, p_str, o))

    return triples, labels


def parse_json_source(path, source_config, schema_mappings):
    with open(path) as f:
        records = json.load(f)

    pred_map = schema_mappings.get("predicates", {})
    class_map = schema_mappings.get("classes", {})
    entity_refs = set(source_config.get("entity_references", []))
    prefix = source_config.get("entity_id_prefix", "http://json.source/entity/")

    triples = []
    labels = {}

    for record in records:
        entity_id = record["id"]
        entity_uri = prefix + entity_id

        if "type" in record and record["type"]:
            type_str = record["type"]
            type_uri = class_map.get(type_str, type_str)
            triples.append((entity_uri, str(RDF.type), URIRef(type_uri)))

        if "name" in record and record["name"]:
            triples.append((entity_uri, str(RDFS.label), Literal(record["name"])))
            labels[entity_uri] = record["name"]

        for key, value in record.items():
            if key in ("id", "type", "name"):
                continue
            if value is None or value == "":
                continue
            if key not in pred_map:
                continue

            mapped_pred = pred_map[key]

            if key in entity_refs:
                ref_uri = prefix + str(value)
                triples.append((entity_uri, mapped_pred, URIRef(ref_uri)))
            else:
                triples.append((entity_uri, mapped_pred, Literal(str(value))))

    return triples, labels


def parse_csv_source(path, source_config, schema_mappings):
    pred_map = schema_mappings.get("predicates", {})
    class_map = schema_mappings.get("classes", {})
    prefix = source_config.get("entity_id_prefix", "http://csv.source/entity/")

    triples = []
    labels = {}

    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            entity_id = row["id"].strip()
            if not entity_id:
                continue
            entity_uri = prefix + entity_id

            type_str = row.get("type", "").strip()
            if type_str:
                type_uri = class_map.get(type_str, type_str)
                triples.append((entity_uri, str(RDF.type), URIRef(type_uri)))

            name = row.get("name", "").strip()
            if name:
                triples.append((entity_uri, str(RDFS.label), Literal(name)))
                labels[entity_uri] = name

            for key, value in row.items():
                if key in ("id", "type", "name"):
                    continue
                value = value.strip() if value else ""
                if not value:
                    continue
                if key not in pred_map:
                    continue
                mapped_pred = pred_map[key]
                triples.append((entity_uri, mapped_pred, Literal(value)))

    return triples, labels


# =============================================================================
# Entity Resolution
# =============================================================================

def normalize_label(label):
    return label.strip().lower().replace("_", " ")


def get_source_for_uri(uri, sources_config):
    for name, src in sources_config.items():
        ns = src.get("namespace", src.get("entity_id_prefix", ""))
        if ns and uri.startswith(ns):
            return name
    return "unknown"


def build_match_clusters(known_matches_path, all_labels):
    uf = UnionFind()

    with open(known_matches_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) == 2:
                uf.union(parts[0].strip(), parts[1].strip())

    for uri in all_labels:
        uf.find(uri)

    label_to_uris = defaultdict(list)
    for uri, label in all_labels.items():
        norm = normalize_label(label)
        label_to_uris[norm].append(uri)

    for norm_label, uris in label_to_uris.items():
        for i in range(1, len(uris)):
            uf.union(uris[0], uris[i])

    return uf


def select_canonical(members, sources_config, source_trust):
    best_uri = None
    best_trust = -1.0
    for uri in sorted(members):
        source = get_source_for_uri(uri, sources_config)
        trust = source_trust.get(source, 0.0)
        if trust > best_trust:
            best_trust = trust
            best_uri = uri
    return best_uri


# =============================================================================
# Fusion
# =============================================================================

def fuse_triples(all_source_triples, canonical_map, functional_properties, source_trust):
    sp_values = defaultdict(list)

    for source_name, triples in all_source_triples:
        trust = source_trust.get(source_name, 0.0)
        for s, p, o in triples:
            canonical_s = canonical_map.get(s, s)

            if isinstance(o, URIRef):
                o_str = str(o)
                if o_str in canonical_map:
                    o = URIRef(canonical_map[o_str])

            sp_values[(canonical_s, p)].append((o, trust))

    fused = set()
    for (s, p), values_with_trust in sp_values.items():
        if p in functional_properties:
            best_value = max(values_with_trust, key=lambda x: x[1])[0]
            fused.add((s, p, best_value))
        else:
            seen = set()
            for v, _ in values_with_trust:
                v_key = (str(v), isinstance(v, URIRef))
                if v_key not in seen:
                    seen.add(v_key)
                    fused.add((s, p, v))

    return fused


# =============================================================================
# Main Pipeline
# =============================================================================

def main():
    with open("/app/config.yaml") as f:
        config = yaml.safe_load(f)

    sources_config = config["sources"]
    schema_mappings = config["schema_mappings"]
    functional_props = set(config["functional_properties"])
    output_config = config["output"]

    source_trust = {name: src["trust"] for name, src in sources_config.items()}

    all_labels = {}
    all_source_triples = []

    # Parse seed
    seed_cfg = sources_config["seed"]
    seed_triples, seed_labels = parse_seed(seed_cfg["path"])
    all_labels.update(seed_labels)
    all_source_triples.append(("seed", seed_triples))

    # Parse RDF source
    rdf_cfg = sources_config["rdf_source"]
    rdf_triples, rdf_labels = parse_rdf_source(
        rdf_cfg["path"], schema_mappings["rdf_source"]
    )
    all_labels.update(rdf_labels)
    all_source_triples.append(("rdf_source", rdf_triples))

    # Parse JSON source
    json_cfg = sources_config["json_source"]
    json_triples, json_labels = parse_json_source(
        json_cfg["path"], json_cfg, schema_mappings["json_source"]
    )
    all_labels.update(json_labels)
    all_source_triples.append(("json_source", json_triples))

    # Parse CSV source
    csv_cfg = sources_config["csv_source"]
    csv_triples, csv_labels = parse_csv_source(
        csv_cfg["path"], csv_cfg, schema_mappings["csv_source"]
    )
    all_labels.update(csv_labels)
    all_source_triples.append(("csv_source", csv_triples))

    # Entity Resolution
    uf = build_match_clusters(config["known_matches_path"], all_labels)

    for _, triples in all_source_triples:
        for s, p, o in triples:
            uf.find(s)
            if isinstance(o, URIRef):
                uf.find(str(o))

    clusters = uf.get_clusters()
    canonical_map = {}
    cluster_list = []

    for root, members in clusters.items():
        canonical = select_canonical(members, sources_config, source_trust)
        for member in members:
            canonical_map[member] = canonical
        if any(m in all_labels for m in members):
            cluster_list.append({
                "canonical": canonical,
                "members": sorted(list(members))
            })

    # Fusion
    fused_triples = fuse_triples(
        all_source_triples, canonical_map, functional_props, source_trust
    )

    # Build rdflib Graph
    fused_graph = Graph()
    for s, p, o in fused_triples:
        s_node = URIRef(s)
        p_node = URIRef(p)
        if isinstance(o, (URIRef, Literal)):
            fused_graph.add((s_node, p_node, o))
        else:
            fused_graph.add((s_node, p_node, Literal(str(o))))

    # Write Outputs
    output_dir = Path("/app/output")
    output_dir.mkdir(parents=True, exist_ok=True)

    fused_graph.serialize(destination=output_config["fused_kg"], format="nt")

    with open(output_config["match_clusters"], "w") as f:
        json.dump(
            {"clusters": sorted(cluster_list, key=lambda x: x["canonical"])},
            f, indent=2
        )

    entities = set(str(s) for s in fused_graph.subjects())
    print(f"Fusion complete: {len(entities)} entities, {len(fused_graph)} triples")


if __name__ == "__main__":
    main()
