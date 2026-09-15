#!/usr/bin/env python3

"""
Multi-relational ontology alignment for product classification taxonomies.
5-phase pipeline: equivalence, structural super/subclass, direct super/subclass,
overlap detection, and disjoint detection.
"""

import xml.etree.ElementTree as ET
import re
import os
from difflib import SequenceMatcher
from collections import defaultdict

RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"

SOURCE = "/app/data/source.owl"
TARGET = "/app/data/target.owl"
OUTPUT = "/app/output/alignment.rdf"

LABEL_NOISE = {"product", "item", "goods", "and", "of", "the", "a"}
COMMENT_STOP = {
    "product", "products", "item", "items", "including", "included",
    "for", "from", "or", "and", "the", "a", "an", "in", "of", "to",
    "with", "used", "sold", "made", "any", "such", "as", "by", "use",
    "that", "is", "are", "not", "can", "be", "at", "on", "it", "its",
}


def parse_ontology(path):
    tree = ET.parse(path)
    root = tree.getroot()
    classes = {}
    for elem in root:
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag != "Class":
            continue
        uri = elem.get(f"{{{RDF}}}about")
        if not uri:
            continue
        label, comments, alt_labels, parent = "", [], [], None
        for ch in elem:
            ct = ch.tag.split("}")[-1] if "}" in ch.tag else ch.tag
            if ct == "label":
                label = (ch.text or "").strip()
            elif ct == "comment":
                comments.append((ch.text or "").strip())
            elif ct == "altLabel":
                alt_labels.append((ch.text or "").strip())
            elif ct == "subClassOf":
                parent = ch.get(f"{{{RDF}}}resource")
        local = uri.split("#")[-1] if "#" in uri else uri.split("/")[-1]
        classes[uri] = dict(
            uri=uri, local=local, label=label, comments=comments,
            alt_labels=alt_labels, parent=parent, children=[]
        )
    for uri, info in classes.items():
        p = info["parent"]
        if p and p in classes:
            classes[p]["children"].append(uri)
    return classes


def tokenize(text):
    return set(re.findall(r"[a-z]+", text.lower()))


def clean(text):
    return tokenize(text) - LABEL_NOISE


def stem(tok):
    return tok[:6] if len(tok) > 6 else tok


def split_camel(name):
    return re.sub(r"([a-z])([A-Z])", r"\1 \2", name)


def all_labels(cls):
    r = []
    if cls["label"]:
        r.append(cls["label"])
    r.extend(cls["alt_labels"])
    r.append(split_camel(cls["local"]))
    return r


def seq_sim(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def jaccard(s1, s2):
    u = s1 | s2
    return len(s1 & s2) / len(u) if u else 0.0


def sym_containment(s1, s2):
    """Symmetric containment: 1.0 only when sets are equal."""
    if not s1 or not s2:
        return 0.0
    inter = s1 & s2
    return min(len(inter) / len(s1), len(inter) / len(s2))


def label_sim(c1, c2):
    """Returns (best_raw, best_sym_containment)."""
    ls1, ls2 = all_labels(c1), all_labels(c2)
    best_raw, best_sc = 0.0, 0.0
    for l1 in ls1:
        cl1 = clean(l1)
        for l2 in ls2:
            best_raw = max(best_raw, seq_sim(l1, l2))
            cl2 = clean(l2)
            if cl1 and cl2:
                best_raw = max(best_raw, jaccard(cl1, cl2))
                best_sc = max(best_sc, sym_containment(cl1, cl2))
    return best_raw, best_sc


def comment_tokens(cls):
    """Stemmed comment tokens with stop words removed."""
    toks = set()
    for c in cls["comments"]:
        words = re.findall(r"[a-z]+", c.lower())
        for w in words:
            if w not in COMMENT_STOP:
                toks.add(stem(w))
    return toks


def comment_sim(c1, c2):
    t1, t2 = comment_tokens(c1), comment_tokens(c2)
    return jaccard(t1, t2)


def name_in_comment(name_cls, comment_cls):
    """Fraction of name_cls's core tokens found in comment_cls's raw comment text."""
    core = clean(name_cls["label"]) | clean(name_cls["local"])
    if not core:
        return 0.0
    cmt_toks = set()
    for c in comment_cls["comments"]:
        cmt_toks |= tokenize(c)
    return len(core & cmt_toks) / len(core)


def depth(uri, onto):
    d, cur, seen = 0, uri, set()
    while cur in onto and cur not in seen:
        seen.add(cur)
        p = onto[cur]["parent"]
        if p and p in onto:
            d += 1
            cur = p
        else:
            break
    return d


def branch_root(uri, onto):
    cur = uri
    while cur in onto:
        p = onto[cur]["parent"]
        if not p or p not in onto:
            return cur
        cur = p
    return cur


def core_stems(cls):
    """Stemmed versions of cleaned label tokens."""
    return {stem(t) for t in clean(cls["label"])}


def align(src, tgt):
    results = []
    existing = set()

    # ══════════════════════════════════════════════════════════════
    # Phase 1: Equivalence detection
    # ══════════════════════════════════════════════════════════════

    cands = []
    for su, sc in src.items():
        for tu, tc in tgt.items():
            raw, sc_val = label_sim(sc, tc)
            csim = comment_sim(sc, tc)
            score = max(raw, sc_val) * 0.55 + csim * 0.45
            if sc_val >= 0.90:
                score = max(score, 0.75)
            if raw >= 0.80:
                score = max(score, 0.75)
            if score >= 0.35:
                cands.append((su, tu, raw, sc_val, csim, score))

    # Sort by score with depth-matching tiebreaker
    for i, (su, tu, raw, sc_val, csim, score) in enumerate(cands):
        sd, td = depth(su, src), depth(tu, tgt)
        adj = score - abs(sd - td) * 0.05
        cands[i] = (su, tu, raw, sc_val, csim, adj)
    cands.sort(key=lambda x: x[5], reverse=True)

    equivs = {}
    used_s, used_t = set(), set()

    for su, tu, raw, sc_val, csim, score in cands:
        if su in used_s or tu in used_t:
            continue
        sd, td = depth(su, src), depth(tu, tgt)
        if abs(sd - td) > 1:
            continue

        is_eq = False
        if sc_val >= 0.90:
            is_eq = True
        elif raw >= 0.85:
            is_eq = True
        elif raw >= 0.70 and csim >= 0.20:
            is_eq = True
        elif sc_val >= 0.70 and raw >= 0.55:
            is_eq = True

        if is_eq:
            equivs[su] = tu
            used_s.add(su)
            used_t.add(tu)
            results.append((su, tu, "=", round(min(1.0, score + 0.1), 2)))
            existing.add((su, tu))

    # ══════════════════════════════════════════════════════════════
    # Phase 2a: Superclass from equivalence propagation
    # If S ≡ T, then S > each child of T
    # ══════════════════════════════════════════════════════════════

    for su_eq, tu_eq in equivs.items():
        for tc_child in tgt[tu_eq]["children"]:
            if (su_eq, tc_child) not in existing:
                results.append((su_eq, tc_child, ">", 0.85))
                existing.add((su_eq, tc_child))

    # ══════════════════════════════════════════════════════════════
    # Phase 2b: Direct superclass via name-in-comment
    # If src's core label stem appears in tgt's comment AND src is
    # at lesser or equal depth → src > tgt
    # ══════════════════════════════════════════════════════════════

    for su, sc in src.items():
        if su in equivs:
            continue  # already has equivalence, use Phase 2a instead
        sd = depth(su, src)
        if sd < 1 or not sc["children"]:
            continue
        sc_stems = core_stems(sc)
        if not sc_stems:
            continue

        for tu, tc in tgt.items():
            if (su, tu) in existing:
                continue
            td = depth(tu, tgt)
            if td <= sd:
                continue  # tgt must be deeper

            tc_cmt_stems = comment_tokens(tc)
            if sc_stems.issubset(tc_cmt_stems):
                results.append((su, tu, ">", 0.80))
                existing.add((su, tu))

    # ══════════════════════════════════════════════════════════════
    # Phase 3a: Subclass from equivalence propagation
    # For equiv (S≡T), each child of S matches best child of T
    # ══════════════════════════════════════════════════════════════

    for su_eq, tu_eq in equivs.items():
        src_children = src[su_eq]["children"]
        tgt_children = tgt[tu_eq]["children"]
        if not tgt_children:
            continue

        for sc_uri in src_children:
            if sc_uri in equivs:
                continue

            scored = []
            for tc_uri in tgt_children:
                fwd = name_in_comment(src[sc_uri], tgt[tc_uri])
                bwd = name_in_comment(tgt[tc_uri], src[sc_uri])
                cs = comment_sim(src[sc_uri], tgt[tc_uri])
                lr, _ = label_sim(src[sc_uri], tgt[tc_uri])
                combo = max(fwd, bwd) * 0.4 + cs * 0.3 + lr * 0.3
                scored.append((tc_uri, combo, fwd, bwd, cs))

            scored.sort(key=lambda x: x[1], reverse=True)
            if scored and scored[0][1] >= 0.08:
                best_tc = scored[0][0]
                if (sc_uri, best_tc) not in existing:
                    results.append((sc_uri, best_tc, "<", 0.75))
                    existing.add((sc_uri, best_tc))

    # ══════════════════════════════════════════════════════════════
    # Phase 3b: Direct subclass via parent-name-in-comment
    # If src.parent's core label stem ∈ tgt's comment tokens
    # AND src is deeper → src < tgt
    # ══════════════════════════════════════════════════════════════

    for su, sc in src.items():
        if su in equivs:
            continue
        sd = depth(su, src)
        sp = sc["parent"]
        if not sp or sp not in src:
            continue
        parent_stems = core_stems(src[sp])
        if not parent_stems:
            continue

        for tu, tc in tgt.items():
            if (su, tu) in existing:
                continue
            td = depth(tu, tgt)
            if td >= sd:
                continue  # tgt must be shallower

            tc_cmt = comment_tokens(tc)
            if parent_stems.issubset(tc_cmt):
                # Additional: src's own label shouldn't be too similar to tgt
                # (that would be equivalence, not subclass)
                raw, _ = label_sim(sc, tc)
                if raw < 0.60:
                    results.append((su, tu, "<", 0.70))
                    existing.add((su, tu))

    # ══════════════════════════════════════════════════════════════
    # Phase 4: Overlap (conservative)
    # Moderate comment similarity, same domain, not equiv-level labels
    # ══════════════════════════════════════════════════════════════

    for su, sc in src.items():
        sd = depth(su, src)
        if sd < 1:
            continue
        for tu, tc in tgt.items():
            if (su, tu) in existing:
                continue
            td = depth(tu, tgt)
            if td < 1:
                continue

            raw, sc_val = label_sim(sc, tc)
            csim = comment_sim(sc, tc)

            # Must have meaningful comment overlap but not equiv-level
            if csim < 0.20:
                continue
            if sc_val >= 0.80:
                continue  # would be equiv
            if raw >= 0.65:
                continue

            # Same broad domain
            sr = branch_root(su, src)
            tr = branch_root(tu, tgt)
            br_raw, _ = label_sim(src[sr], tgt[tr])
            if br_raw < 0.10 and csim < 0.30:
                continue

            results.append((su, tu, "~", round(csim, 2)))
            existing.add((su, tu))

    # ══════════════════════════════════════════════════════════════
    # Phase 5: Disjoint
    # 5a: Cross-branch (different top-level domains)
    # 5b: Within-branch siblings with no similarity
    # ══════════════════════════════════════════════════════════════

    branch_map = defaultdict(set)
    for su_eq, tu_eq in equivs.items():
        sr = branch_root(su_eq, src)
        tr = branch_root(tu_eq, tgt)
        branch_map[sr].add(tr)

    # 5a: Cross-branch
    for su, sc in src.items():
        sd = depth(su, src)
        if sd < 1 or not sc["children"]:
            continue
        sr = branch_root(su, src)
        for tu, tc in tgt.items():
            if (su, tu) in existing:
                continue
            if not tc["children"]:
                continue
            tr = branch_root(tu, tgt)

            equiv_br = branch_map.get(sr, set())
            if tr in equiv_br:
                continue  # same domain

            # Different domain + low similarity
            raw, _ = label_sim(sc, tc)
            csim = comment_sim(sc, tc)
            clean_jac = jaccard(clean(sc["label"]), clean(tc["label"]))

            if clean_jac < 0.10 and csim < 0.10:
                results.append((su, tu, "%", 0.90))
                existing.add((su, tu))

    # 5b: Within-branch siblings of equivalent parents
    for su_eq, tu_eq in equivs.items():
        src_ch = [c for c in src[su_eq]["children"] if src[c].get("children")]
        tgt_ch = [c for c in tgt[tu_eq]["children"] if tgt[c].get("children")]

        for sc_uri in src_ch:
            for tc_uri in tgt_ch:
                if (sc_uri, tc_uri) in existing:
                    continue
                raw, _ = label_sim(src[sc_uri], tgt[tc_uri])
                csim = comment_sim(src[sc_uri], tgt[tc_uri])
                clean_jac = jaccard(clean(src[sc_uri]["label"]),
                                    clean(tgt[tc_uri]["label"]))
                if clean_jac < 0.08 and csim < 0.08 and raw < 0.15:
                    results.append((sc_uri, tc_uri, "%", 0.85))
                    existing.add((sc_uri, tc_uri))

    # Deduplicate
    best = {}
    for e1, e2, rel, conf in results:
        k = (e1, e2)
        if k not in best or conf > best[k][1]:
            best[k] = (rel, conf)
    return [(e1, e2, r, c) for (e1, e2), (r, c) in best.items()]


def write_alignment(alignments, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<rdf:RDF xmlns="http://knowledgeweb.semanticweb.org/heterogeneity/alignment"',
        '         xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"',
        '         xmlns:xsd="http://www.w3.org/2001/XMLSchema#">',
        "<Alignment>", "<xml>yes</xml>", "<level>0</level>", "<type>??</type>",
        "<onto1>",
        '  <Ontology rdf:about="http://example.org/gpc">',
        "    <location>file:///app/data/source.owl</location>",
        "  </Ontology>", "</onto1>", "<onto2>",
        '  <Ontology rdf:about="http://example.org/rpt">',
        "    <location>file:///app/data/target.owl</location>",
        "  </Ontology>", "</onto2>",
    ]
    for e1, e2, rel, conf in alignments:
        esc = rel.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        lines.extend([
            "<map>", "  <Cell>",
            f'    <entity1 rdf:resource="{e1}"/>',
            f'    <entity2 rdf:resource="{e2}"/>',
            f'    <measure rdf:datatype="xsd:float">{conf}</measure>',
            f"    <relation>{esc}</relation>",
            "  </Cell>", "</map>",
        ])
    lines += ["</Alignment>", "</rdf:RDF>"]
    with open(path, "w") as f:
        f.write("\n".join(lines))


def main():
    print("Parsing ontologies...")
    s = parse_ontology(SOURCE)
    t = parse_ontology(TARGET)
    print(f"  Source: {len(s)}, Target: {len(t)}")
    print("Aligning...")
    r = align(s, t)
    from collections import Counter
    c = Counter(rel for _, _, rel, _ in r)
    print(f"  Total: {len(r)}")
    for k, v in sorted(c.items()):
        print(f"    {k}: {v}")
    write_alignment(r, OUTPUT)
    print(f"Written to {OUTPUT}")


if __name__ == "__main__":
    main()
