#!/usr/bin/env python3
"""Clinical NLP Evaluation Engine.

Scores NER/RE system outputs against gold-standard annotations using
optimal bipartite matching and configurable span comparison.
"""

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple

import numpy as np
from scipy.optimize import linear_sum_assignment


# ── Data models ─────────────────────────────────────────────────────


@dataclass
class Entity:
    id: str
    type: str
    spans: List[Tuple[int, int]]
    text: str

    def char_set(self) -> Set[int]:
        s: Set[int] = set()
        for start, end in self.spans:
            s.update(range(start, end))
        return s


@dataclass
class Relation:
    id: str
    type: str
    arg1_id: str
    arg2_id: str


@dataclass
class Attribute:
    id: str
    attr_type: str
    entity_id: str
    value: str


@dataclass
class Document:
    doc_id: str
    text: str
    entities: Dict[str, Entity] = field(default_factory=dict)
    relations: Dict[str, Relation] = field(default_factory=dict)
    attributes: Dict[str, Attribute] = field(default_factory=dict)


# ── Parsers ─────────────────────────────────────────────────────────


def parse_brat(ann_path: str, txt_path: str) -> Document:
    with open(txt_path, encoding="utf-8") as f:
        text = f.read()

    doc_id = os.path.splitext(os.path.basename(ann_path))[0]
    doc = Document(doc_id=doc_id, text=text)

    with open(ann_path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n\r")
            if not line:
                continue
            parts = line.split("\t")

            if line.startswith("T"):
                eid = parts[0]
                type_and_spans = parts[1]
                entity_text = parts[2] if len(parts) > 2 else ""
                space_idx = type_and_spans.index(" ")
                etype = type_and_spans[:space_idx]
                span_str = type_and_spans[space_idx + 1:]
                spans = []
                for seg in span_str.split(";"):
                    seg = seg.strip()
                    sp = seg.split()
                    spans.append((int(sp[0]), int(sp[1])))
                doc.entities[eid] = Entity(eid, etype, spans, entity_text)

            elif line.startswith("R"):
                rid = parts[0]
                tokens = parts[1].split()
                rtype = tokens[0]
                arg1 = tokens[1].split(":")[1]
                arg2 = tokens[2].split(":")[1]
                doc.relations[rid] = Relation(rid, rtype, arg1, arg2)

            elif line.startswith("A"):
                aid = parts[0]
                tokens = parts[1].split()
                attr_type = tokens[0]
                entity_id = tokens[1]
                value = tokens[2] if len(tokens) > 2 else ""
                doc.attributes[aid] = Attribute(aid, attr_type, entity_id, value)

    return doc


def parse_xml(xml_path: str) -> Document:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    doc_id = os.path.splitext(os.path.basename(xml_path))[0]

    text_elem = root.find("TEXT")
    text = text_elem.text if text_elem is not None and text_elem.text else ""

    doc = Document(doc_id=doc_id, text=text)

    tags = root.find("TAGS")
    if tags is not None:
        for elem in tags:
            if elem.tag == "Entity":
                eid = elem.get("id")
                etype = elem.get("type")
                start = int(elem.get("start"))
                end = int(elem.get("end"))
                etext = elem.get("text", "")
                doc.entities[eid] = Entity(eid, etype, [(start, end)], etext)
                assertion = elem.get("assertion")
                if assertion:
                    aid = f"A_{eid}"
                    doc.attributes[aid] = Attribute(
                        aid, "Assertion", eid, assertion
                    )

            elif elem.tag == "Relation":
                rid = elem.get("id")
                rtype = elem.get("type")
                arg1 = elem.get("arg1")
                arg2 = elem.get("arg2")
                doc.relations[rid] = Relation(rid, rtype, arg1, arg2)

            elif elem.tag == "Attribute":
                aid = elem.get("id")
                attr_type = elem.get("type")
                entity_id = elem.get("entity_id")
                value = elem.get("value")
                doc.attributes[aid] = Attribute(aid, attr_type, entity_id, value)

    return doc


# ── Directory loading ───────────────────────────────────────────────


def detect_format(directory: str) -> str:
    for f in os.listdir(directory):
        if f.endswith(".ann"):
            return "brat"
        if f.endswith(".xml"):
            return "xml"
    return "brat"


def load_directory(directory: str) -> Dict[str, Document]:
    fmt = detect_format(directory)
    docs: Dict[str, Document] = {}

    if fmt == "brat":
        for fname in sorted(os.listdir(directory)):
            if fname.endswith(".ann"):
                base = fname[:-4]
                ann = os.path.join(directory, fname)
                txt = os.path.join(directory, base + ".txt")
                if os.path.exists(txt):
                    docs[base] = parse_brat(ann, txt)
    elif fmt == "xml":
        for fname in sorted(os.listdir(directory)):
            if fname.endswith(".xml"):
                base = fname[:-4]
                docs[base] = parse_xml(os.path.join(directory, fname))

    return docs


# ── Matching ────────────────────────────────────────────────────────


def jaccard(e1: Entity, e2: Entity) -> float:
    s1 = e1.char_set()
    s2 = e2.char_set()
    if not s1 and not s2:
        return 1.0
    inter = len(s1 & s2)
    union = len(s1 | s2)
    return inter / union if union > 0 else 0.0


def match_entities_for_type(
    gold: List[Entity],
    system: List[Entity],
    mode: str,
    threshold: float,
) -> List[Tuple[Entity, Entity]]:
    if not gold or not system:
        return []

    n_g, n_s = len(gold), len(system)
    sim = np.zeros((n_g, n_s))

    for i, ge in enumerate(gold):
        for j, se in enumerate(system):
            if mode == "strict":
                sim[i, j] = 1.0 if ge.spans == se.spans else 0.0
            elif mode == "overlap":
                j_val = jaccard(ge, se)
                sim[i, j] = j_val if j_val >= threshold else 0.0
            elif mode == "type":
                sim[i, j] = 1.0 if (ge.char_set() & se.char_set()) else 0.0

    row_ind, col_ind = linear_sum_assignment(-sim)

    matches = []
    for r, c in zip(row_ind, col_ind):
        if sim[r, c] > 0:
            matches.append((gold[r], system[c]))
    return matches


# ── Metrics helpers ─────────────────────────────────────────────────


def prf(tp: int, fp: int, fn: int) -> Tuple[float, float, float]:
    p = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    r = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
    return p, r, f1


def build_metrics(ent_counts, rel_counts, attr_counts):
    """Build metrics dict from count dicts."""
    entity_metrics = {}
    for etype in sorted(ent_counts):
        c = ent_counts[etype]
        p, r, f1 = prf(c["tp"], c["fp"], c["fn"])
        entity_metrics[etype] = {
            "precision": p, "recall": r, "f1": f1,
            "tp": c["tp"], "fp": c["fp"], "fn": c["fn"],
        }

    relation_metrics = {}
    for rtype in sorted(rel_counts):
        c = rel_counts[rtype]
        p, r, f1 = prf(c["tp"], c["fp"], c["fn"])
        relation_metrics[rtype] = {
            "precision": p, "recall": r, "f1": f1,
            "tp": c["tp"], "fp": c["fp"], "fn": c["fn"],
        }

    attribute_metrics = {}
    for at in sorted(attr_counts):
        c = attr_counts[at]
        acc = c["correct"] / c["total"] if c["total"] > 0 else 0.0
        attribute_metrics[at] = {
            "accuracy": acc, "correct": c["correct"], "total": c["total"],
        }

    total_tp = sum(c["tp"] for c in ent_counts.values())
    total_fp = sum(c["fp"] for c in ent_counts.values())
    total_fn = sum(c["fn"] for c in ent_counts.values())
    mi_p, mi_r, mi_f1 = prf(total_tp, total_fp, total_fn)

    if entity_metrics:
        ma_p = sum(m["precision"] for m in entity_metrics.values()) / len(
            entity_metrics
        )
        ma_r = sum(m["recall"] for m in entity_metrics.values()) / len(
            entity_metrics
        )
        ma_f1 = sum(m["f1"] for m in entity_metrics.values()) / len(
            entity_metrics
        )
    else:
        ma_p = ma_r = ma_f1 = 0.0

    return {
        "entity_metrics": entity_metrics,
        "relation_metrics": relation_metrics,
        "attribute_metrics": attribute_metrics,
        "micro": {"precision": mi_p, "recall": mi_r, "f1": mi_f1},
        "macro": {"precision": ma_p, "recall": ma_r, "f1": ma_f1},
    }


# ── Core evaluation ────────────────────────────────────────────────


def evaluate_doc_pair(gdoc, sdoc, mode, threshold):
    """Evaluate a single document pair.

    Returns (ent_counts, rel_counts, attr_counts) dicts.
    Handles the three cases: both present, gold-only, system-only.
    """
    ent_counts: Dict[str, Dict[str, int]] = {}
    rel_counts: Dict[str, Dict[str, int]] = {}
    attr_counts: Dict[str, Dict[str, int]] = {}

    if gdoc is not None and sdoc is not None:
        # Normal paired evaluation
        types = set()
        for e in gdoc.entities.values():
            types.add(e.type)
        for e in sdoc.entities.values():
            types.add(e.type)

        gold_to_sys: Dict[str, str] = {}

        for etype in types:
            g_ents = [e for e in gdoc.entities.values() if e.type == etype]
            s_ents = [e for e in sdoc.entities.values() if e.type == etype]

            matches = match_entities_for_type(g_ents, s_ents, mode, threshold)
            tp = len(matches)
            fp = len(s_ents) - tp
            fn = len(g_ents) - tp

            ent_counts[etype] = {"tp": tp, "fp": fp, "fn": fn}

            for ge, se in matches:
                gold_to_sys[ge.id] = se.id

        # Relations
        rtypes = set()
        for r in gdoc.relations.values():
            rtypes.add(r.type)
        for r in sdoc.relations.values():
            rtypes.add(r.type)

        for rtype in rtypes:
            g_rels = [r for r in gdoc.relations.values() if r.type == rtype]
            s_rels = [r for r in sdoc.relations.values() if r.type == rtype]

            consumed: Set[str] = set()
            tp = 0
            for gr in g_rels:
                if gr.arg1_id in gold_to_sys and gr.arg2_id in gold_to_sys:
                    sa1 = gold_to_sys[gr.arg1_id]
                    sa2 = gold_to_sys[gr.arg2_id]
                    for sr in s_rels:
                        if (
                            sr.id not in consumed
                            and sr.arg1_id == sa1
                            and sr.arg2_id == sa2
                        ):
                            tp += 1
                            consumed.add(sr.id)
                            break

            fp = len(s_rels) - tp
            fn = len(g_rels) - tp
            rel_counts[rtype] = {"tp": tp, "fp": fp, "fn": fn}

        # Attributes
        for ga in gdoc.attributes.values():
            if ga.entity_id in gold_to_sys:
                matched_sid = gold_to_sys[ga.entity_id]
                for sa in sdoc.attributes.values():
                    if sa.entity_id == matched_sid and sa.attr_type == ga.attr_type:
                        ac = attr_counts.setdefault(
                            ga.attr_type, {"correct": 0, "total": 0}
                        )
                        ac["total"] += 1
                        if sa.value == ga.value:
                            ac["correct"] += 1
                        break

    elif gdoc is not None:
        # Gold-only document: all entities FN, all relations FN
        for e in gdoc.entities.values():
            c = ent_counts.setdefault(e.type, {"tp": 0, "fp": 0, "fn": 0})
            c["fn"] += 1
        for r in gdoc.relations.values():
            c = rel_counts.setdefault(r.type, {"tp": 0, "fp": 0, "fn": 0})
            c["fn"] += 1

    elif sdoc is not None:
        # System-only document: all entities FP, all relations FP
        for e in sdoc.entities.values():
            c = ent_counts.setdefault(e.type, {"tp": 0, "fp": 0, "fn": 0})
            c["fp"] += 1
        for r in sdoc.relations.values():
            c = rel_counts.setdefault(r.type, {"tp": 0, "fp": 0, "fn": 0})
            c["fp"] += 1

    return ent_counts, rel_counts, attr_counts


def evaluate(
    gold_docs: Dict[str, Document],
    sys_docs: Dict[str, Document],
    mode: str,
    threshold: float,
) -> dict:
    all_doc_ids = sorted(set(gold_docs) | set(sys_docs))

    agg_ent: Dict[str, Dict[str, int]] = {}
    agg_rel: Dict[str, Dict[str, int]] = {}
    agg_attr: Dict[str, Dict[str, int]] = {}
    per_document = {}

    for doc_id in all_doc_ids:
        gdoc = gold_docs.get(doc_id)
        sdoc = sys_docs.get(doc_id)

        doc_ent, doc_rel, doc_attr = evaluate_doc_pair(
            gdoc, sdoc, mode, threshold
        )

        # Accumulate into aggregate
        for etype, counts in doc_ent.items():
            ac = agg_ent.setdefault(etype, {"tp": 0, "fp": 0, "fn": 0})
            ac["tp"] += counts["tp"]
            ac["fp"] += counts["fp"]
            ac["fn"] += counts["fn"]
        for rtype, counts in doc_rel.items():
            ac = agg_rel.setdefault(rtype, {"tp": 0, "fp": 0, "fn": 0})
            ac["tp"] += counts["tp"]
            ac["fp"] += counts["fp"]
            ac["fn"] += counts["fn"]
        for atype, counts in doc_attr.items():
            ac = agg_attr.setdefault(atype, {"correct": 0, "total": 0})
            ac["correct"] += counts["correct"]
            ac["total"] += counts["total"]

        # Per-document metrics
        per_document[doc_id] = build_metrics(doc_ent, doc_rel, doc_attr)

    result = build_metrics(agg_ent, agg_rel, agg_attr)
    result["matching_mode"] = mode
    result["threshold"] = threshold
    result["per_document"] = per_document

    return result


# ── CLI ─────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Clinical NLP Evaluation Engine"
    )
    parser.add_argument("--gold", required=True)
    parser.add_argument("--system", required=True)
    parser.add_argument(
        "--matching",
        choices=["strict", "overlap", "type"],
        default="strict",
    )
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    gold_docs = load_directory(args.gold)
    sys_docs = load_directory(args.system)
    results = evaluate(gold_docs, sys_docs, args.matching, args.threshold)

    with open(args.output, "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
