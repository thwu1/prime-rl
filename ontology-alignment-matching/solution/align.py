#!/usr/bin/env python3
"""Hydrological ontology alignment solver.


Strategy:
1. Parse both OWL files extracting classes, properties, labels, alt-labels,
   hierarchy, definitions, and restriction axioms.
2. Build bidirectional label indexes for classes and properties.
3. Match classes via:
   a. Exact normalized label / alt-label cross-comparison
   b. Token-based Jaccard similarity with structural context weighting
   c. Definition-based matching for restriction-defined classes
   d. Subsumption via descendant-set overlap
4. Reject false friends using hierarchical-context scoring.
5. Match properties via label cross-comparison + domain/range compatibility.
6. Output OAEI alignment XML.
"""
import os
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from xml.sax.saxutils import escape

SOURCE_OWL = "/app/data/source.owl"
TARGET_OWL = "/app/data/target.owl"
OUTPUT_PATH = "/app/output/alignment.rdf"
SOURCE_BASE = "http://wqmo.owl"
TARGET_BASE = "http://hro.owl"
SOURCE_NS = SOURCE_BASE + "#"
TARGET_NS = TARGET_BASE + "#"


def normalize(s):
    """Normalize a label for comparison."""
    s = s.lower().strip()
    s = re.sub(r'\s+', ' ', s)
    return s


def tokenize(s):
    """Split label into normalized tokens."""
    tokens = set(re.split(r'[\s\-_,/()]+', s.lower().strip()))
    tokens.discard('')
    return tokens


def jaccard_tokens(label1, label2):
    """Compute Jaccard similarity between token sets."""
    t1 = tokenize(label1)
    t2 = tokenize(label2)
    if not t1 or not t2:
        return 0.0
    return len(t1 & t2) / len(t1 | t2)


# ---------------------------------------------------------------------------
# Regex-based OWL parser (primary — avoids ElementTree namespace pitfalls)
# ---------------------------------------------------------------------------

def parse_ontology(filepath):
    """Parse an OWL/RDF-XML file using regex, robust to namespace issues."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    classes = {}
    properties = {}

    # ------ Object Properties ------
    for m in re.finditer(
        r'<owl:ObjectProperty\s+rdf:about="([^"]+)"[^>]*>(.*?)</owl:ObjectProperty>',
        content, re.DOTALL
    ):
        uri = _unescape(m.group(1))
        block = m.group(2)

        labels = [_unescape(x) for x in re.findall(r'<rdfs:label>([^<]+)</rdfs:label>', block)]
        alt_labels = [_unescape(x) for x in re.findall(r'<skos:altLabel>([^<]+)</skos:altLabel>', block)]
        domain_m = re.search(r'<rdfs:domain\s+rdf:resource="([^"]+)"', block)
        range_m = re.search(r'<rdfs:range\s+rdf:resource="([^"]+)"', block)

        primary_label = labels[0] if labels else uri.split('#')[-1]
        local_id = uri.split('#')[-1] if '#' in uri else uri

        properties[uri] = {
            'label': primary_label,
            'alt_labels': alt_labels,
            'all_labels': [primary_label] + alt_labels,
            'domain': _unescape(domain_m.group(1)) if domain_m else None,
            'range': _unescape(range_m.group(1)) if range_m else None,
            'local_id': local_id,
        }

    # ------ Classes ------
    # We must handle nesting: defined classes contain inner <owl:Class> inside
    # <owl:equivalentClass>.  Strategy: find top-level <owl:Class rdf:about="…">
    # by matching the outermost opening/closing tags using a state machine.
    top_classes = _extract_top_level_blocks(content, 'owl:Class')

    for uri_raw, block in top_classes:
        uri = _unescape(uri_raw)

        labels = [_unescape(x) for x in re.findall(r'<rdfs:label>([^<]+)</rdfs:label>', block)]
        alt_labels = [_unescape(x) for x in re.findall(r'<skos:altLabel>([^<]+)</skos:altLabel>', block)]
        definitions = [_unescape(x) for x in re.findall(r'<skos:definition>([^<]+)</skos:definition>', block)]
        parent_m = re.search(r'<rdfs:subClassOf\s+rdf:resource="([^"]+)"', block)

        # Parse equivalentClass restrictions
        restrictions = []
        for eq_m in re.finditer(r'<owl:equivalentClass>(.*?)</owl:equivalentClass>', block, re.DOTALL):
            eq_block = eq_m.group(1)
            intersection_m = re.search(
                r'<owl:intersectionOf[^>]*>(.*?)</owl:intersectionOf>',
                eq_block, re.DOTALL
            )
            if intersection_m:
                members = []
                inner = intersection_m.group(1)
                for c_m in re.finditer(r'<owl:Class\s+rdf:about="([^"]+)"', inner):
                    members.append({'type': 'named', 'class': _unescape(c_m.group(1))})
                for r_m in re.finditer(r'<owl:Restriction>(.*?)</owl:Restriction>', inner, re.DOTALL):
                    r_block = r_m.group(1)
                    prop_m = re.search(r'<owl:onProperty\s+rdf:resource="([^"]+)"', r_block)
                    some_m = re.search(r'<owl:someValuesFrom\s+rdf:resource="([^"]+)"', r_block)
                    val_m = re.search(r'<owl:hasValue>([^<]+)</owl:hasValue>', r_block)
                    if some_m:
                        members.append({
                            'type': 'someValuesFrom',
                            'property': _unescape(prop_m.group(1)) if prop_m else None,
                            'filler': _unescape(some_m.group(1)),
                        })
                    elif val_m:
                        members.append({
                            'type': 'hasValue',
                            'property': _unescape(prop_m.group(1)) if prop_m else None,
                            'value': _unescape(val_m.group(1)).strip(),
                        })
                if members:
                    restrictions.append({'type': 'intersection', 'members': members})

        primary_label = labels[0] if labels else uri.split('#')[-1]
        local_id = uri.split('#')[-1] if '#' in uri else uri

        classes[uri] = {
            'label': primary_label,
            'alt_labels': alt_labels,
            'definitions': definitions,
            'parent': _unescape(parent_m.group(1)) if parent_m else None,
            'all_labels': [primary_label] + alt_labels,
            'restrictions': restrictions,
            'local_id': local_id,
        }

    return classes, properties


def _unescape(s):
    """Unescape basic XML entities."""
    return s.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"')


def _extract_top_level_blocks(content, tag):
    """Extract top-level blocks for a given XML tag, handling nesting.

    Returns list of (rdf_about_uri, inner_content) for each top-level block.
    """
    results = []
    pattern = re.compile(r'<' + re.escape(tag) + r'\s+rdf:about="([^"]+)"[^>]*>')
    close_tag = '</' + tag + '>'
    open_prefix = '<' + tag

    pos = 0
    while pos < len(content):
        m = pattern.search(content, pos)
        if not m:
            break

        # Check if the matched tag itself is self-closing (ends with />)
        tag_end_pos = content.find('>', m.start())
        if tag_end_pos != -1 and tag_end_pos > m.start() and content[tag_end_pos - 1] == '/':
            # Self-closing top-level element — no inner content
            pos = tag_end_pos + 1
            continue

        uri = m.group(1)
        start_inner = m.end()
        # Track nesting depth
        depth = 1
        search_pos = start_inner
        while depth > 0 and search_pos < len(content):
            next_open = content.find(open_prefix, search_pos)
            next_close = content.find(close_tag, search_pos)
            if next_close == -1:
                break
            if next_open != -1 and next_open < next_close:
                # Check if this nested opening tag is self-closing
                nested_end = content.find('>', next_open)
                if nested_end != -1 and content[nested_end - 1] == '/':
                    # Self-closing nested tag — skip without depth change
                    search_pos = nested_end + 1
                else:
                    depth += 1
                    search_pos = next_open + len(open_prefix)
            else:
                depth -= 1
                if depth == 0:
                    inner = content[start_inner:next_close]
                    results.append((uri, inner))
                search_pos = next_close + len(close_tag)
        pos = search_pos

    return results


# ---------------------------------------------------------------------------
# Label index & hierarchy helpers
# ---------------------------------------------------------------------------

def build_label_index(items):
    """Build normalized label -> set of URIs index."""
    index = defaultdict(set)
    for uri, info in items.items():
        for label in info['all_labels']:
            norm = normalize(label)
            index[norm].add(uri)
    return index


def get_descendants(classes, uri):
    """Get all descendant URIs of a class."""
    children = set()
    for c_uri, info in classes.items():
        if info['parent'] == uri:
            children.add(c_uri)
            children.update(get_descendants(classes, c_uri))
    return children


def get_ancestors(classes, uri):
    """Get all ancestor URIs of a class."""
    ancestors = set()
    current = uri
    while current and current in classes:
        parent = classes[current].get('parent')
        if parent and parent in classes:
            ancestors.add(parent)
            current = parent
        else:
            break
    return ancestors


def hierarchy_path_tokens(classes, uri):
    """Get the set of label tokens from the class and all its ancestors."""
    tokens = set()
    current = uri
    depth = 0
    while current and current in classes and depth < 10:
        tokens.update(tokenize(classes[current]['label']))
        current = classes[current].get('parent')
        depth += 1
    return tokens


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def restriction_similarity(r1, r2, class_match_map):
    """Compare two restriction structures for similarity."""
    if not r1 or not r2:
        return 0.0

    if r1['type'] == 'intersection' and r2['type'] == 'intersection':
        m1 = r1.get('members', [])
        m2 = r2.get('members', [])
        if len(m1) != len(m2):
            return 0.0
        score = 0.0
        for member1 in m1:
            best = max((restriction_similarity(member1, member2, class_match_map)
                       for member2 in m2), default=0.0)
            score += best
        return score / max(len(m1), 1)

    if r1['type'] == 'named' and r2['type'] == 'named':
        c1 = r1['class']
        c2 = r2['class']
        if (c1, c2) in class_match_map or c1 == c2:
            return 1.0
        l1 = c1.split('#')[-1].lower() if '#' in c1 else ''
        l2 = c2.split('#')[-1].lower() if '#' in c2 else ''
        return jaccard_tokens(l1, l2)

    if r1['type'] == r2['type'] and r1['type'] in ('someValuesFrom', 'hasValue'):
        p1 = r1.get('property', '')
        p2 = r2.get('property', '')
        p1_local = p1.split('#')[-1].lower() if p1 and '#' in p1 else ''
        p2_local = p2.split('#')[-1].lower() if p2 and '#' in p2 else ''
        prop_sim = jaccard_tokens(p1_local, p2_local) if p1_local and p2_local else 0.0

        if r1['type'] == 'someValuesFrom':
            f1 = r1.get('filler', '')
            f2 = r2.get('filler', '')
            if f1 and f2:
                if (f1, f2) in class_match_map:
                    filler_sim = 1.0
                else:
                    fl1 = f1.split('#')[-1].lower() if '#' in f1 else ''
                    fl2 = f2.split('#')[-1].lower() if '#' in f2 else ''
                    filler_sim = jaccard_tokens(fl1, fl2)
            else:
                filler_sim = 0.0
            return 0.5 * prop_sim + 0.5 * filler_sim
        elif r1['type'] == 'hasValue':
            v1 = str(r1.get('value', '')).lower()
            v2 = str(r2.get('value', '')).lower()
            val_sim = 1.0 if v1 == v2 else jaccard_tokens(v1, v2)
            return 0.5 * prop_sim + 0.5 * val_sim

    return 0.0


def find_class_alignments(source_classes, target_classes):
    """Find alignments between source and target classes."""
    source_index = build_label_index(source_classes)
    target_index = build_label_index(target_classes)

    alignments = []
    matched_source = set()
    matched_target = set()
    class_match_map = {}

    # Phase 1: Exact label/altLabel matching with structural context
    for norm_label, source_uris in source_index.items():
        if norm_label in target_index:
            target_uris = target_index[norm_label]
            for s_uri in sorted(source_uris):
                if s_uri in matched_source:
                    continue
                for t_uri in sorted(target_uris):
                    if t_uri in matched_target:
                        continue
                    s_path = hierarchy_path_tokens(source_classes, s_uri)
                    t_path = hierarchy_path_tokens(target_classes, t_uri)
                    s_label_norm = normalize(source_classes[s_uri]['label'])
                    t_label_norm = normalize(target_classes[t_uri]['label'])
                    if s_label_norm == t_label_norm or len(s_path & t_path) >= 2:
                        alignments.append((s_uri, t_uri, '=', 1.0))
                        matched_source.add(s_uri)
                        matched_target.add(t_uri)
                        class_match_map[(s_uri, t_uri)] = True
                        break

    # Phase 2: Cross-compare primary labels against alt-labels with context
    for s_uri, s_info in source_classes.items():
        if s_uri in matched_source:
            continue
        s_labels = {normalize(l) for l in s_info['all_labels']}
        for t_uri, t_info in target_classes.items():
            if t_uri in matched_target:
                continue
            t_labels = {normalize(l) for l in t_info['all_labels']}
            overlap = s_labels & t_labels
            if overlap:
                s_path = hierarchy_path_tokens(source_classes, s_uri)
                t_path = hierarchy_path_tokens(target_classes, t_uri)
                context_overlap = len(s_path & t_path)
                if context_overlap >= 1 or len(overlap) >= 2:
                    alignments.append((s_uri, t_uri, '=', 0.9))
                    matched_source.add(s_uri)
                    matched_target.add(t_uri)
                    class_match_map[(s_uri, t_uri)] = True
                    break

    # Phase 3: Token-based Jaccard similarity for remaining unmatched
    unmatched_source = {u: i for u, i in source_classes.items() if u not in matched_source}
    unmatched_target = {u: i for u, i in target_classes.items() if u not in matched_target}

    candidates = []
    for s_uri, s_info in unmatched_source.items():
        for t_uri, t_info in unmatched_target.items():
            best_score = 0.0
            for s_label in s_info['all_labels']:
                for t_label in t_info['all_labels']:
                    score = jaccard_tokens(s_label, t_label)
                    best_score = max(best_score, score)
            if best_score >= 0.45:
                s_path = hierarchy_path_tokens(source_classes, s_uri)
                t_path = hierarchy_path_tokens(target_classes, t_uri)
                context_bonus = min(len(s_path & t_path) * 0.05, 0.15)
                candidates.append((s_uri, t_uri, best_score + context_bonus))

    candidates.sort(key=lambda x: -x[2])
    for s_uri, t_uri, score in candidates:
        if s_uri in matched_source or t_uri in matched_target:
            continue
        alignments.append((s_uri, t_uri, '=', min(score, 1.0)))
        matched_source.add(s_uri)
        matched_target.add(t_uri)
        class_match_map[(s_uri, t_uri)] = True

    # Phase 4: OWL restriction-based matching for defined classes
    for s_uri, s_info in source_classes.items():
        if s_uri in matched_source or not s_info['restrictions']:
            continue
        for t_uri, t_info in target_classes.items():
            if t_uri in matched_target or not t_info['restrictions']:
                continue
            for s_restr in s_info['restrictions']:
                for t_restr in t_info['restrictions']:
                    sim = restriction_similarity(s_restr, t_restr, class_match_map)
                    if sim >= 0.5:
                        alignments.append((s_uri, t_uri, '=', sim))
                        matched_source.add(s_uri)
                        matched_target.add(t_uri)
                        class_match_map[(s_uri, t_uri)] = True
                        break
                if s_uri in matched_source:
                    break

    # Phase 5: Definition-based matching for restriction classes
    for s_uri, s_info in source_classes.items():
        if s_uri in matched_source or not s_info.get('definitions'):
            continue
        s_def_tokens = set()
        for d in s_info['definitions']:
            s_def_tokens.update(tokenize(d))

        best_match = None
        best_score = 0.0
        for t_uri, t_info in target_classes.items():
            if t_uri in matched_target or not t_info.get('definitions'):
                continue
            t_def_tokens = set()
            for d in t_info['definitions']:
                t_def_tokens.update(tokenize(d))

            if s_def_tokens and t_def_tokens:
                sim = len(s_def_tokens & t_def_tokens) / len(s_def_tokens | t_def_tokens)
                label_sim = jaccard_tokens(s_info['label'], t_info['label'])
                combined = 0.6 * sim + 0.4 * label_sim
                if combined > best_score and combined >= 0.35:
                    best_score = combined
                    best_match = t_uri

        if best_match:
            alignments.append((s_uri, best_match, '=', best_score))
            matched_source.add(s_uri)
            matched_target.add(best_match)
            class_match_map[(s_uri, best_match)] = True

    # Phase 6: Subsumption detection via descendant overlap
    for s_uri in source_classes:
        if s_uri in matched_source:
            continue
        s_descendants = get_descendants(source_classes, s_uri)
        if len(s_descendants) < 2 or len(s_descendants) > 25:
            continue
        for t_uri in target_classes:
            if t_uri in matched_target:
                continue
            if (s_uri, t_uri) in class_match_map:
                continue
            t_descendants = get_descendants(target_classes, t_uri)
            if len(t_descendants) < 2 or len(t_descendants) > 25:
                continue

            s_desc_matched = set()
            t_desc_matched = set()
            for a_s, a_t, _, _ in alignments:
                if a_s in s_descendants and a_t in t_descendants:
                    s_desc_matched.add(a_s)
                    t_desc_matched.add(a_t)

            n_matched = len(s_desc_matched)
            if n_matched < 2:
                continue

            s_cov = n_matched / len(s_descendants)
            t_cov = n_matched / len(t_descendants)

            if s_cov >= 0.85 and t_cov < 0.70 and len(t_descendants) > len(s_descendants):
                alignments.append((s_uri, t_uri, '<', 0.7))
            elif t_cov >= 0.85 and s_cov < 0.70 and len(s_descendants) > len(t_descendants):
                alignments.append((s_uri, t_uri, '>', 0.7))

    return alignments, class_match_map


def find_property_alignments(source_props, target_props, class_match_map):
    """Find alignments between source and target object properties."""
    source_index = build_label_index(source_props)
    target_index = build_label_index(target_props)

    alignments = []
    matched_source = set()
    matched_target = set()

    # Phase 1: Exact label/altLabel matching
    for norm_label, source_uris in source_index.items():
        if norm_label in target_index:
            for s_uri in sorted(source_uris):
                if s_uri in matched_source:
                    continue
                for t_uri in sorted(target_index[norm_label]):
                    if t_uri in matched_target:
                        continue
                    alignments.append((s_uri, t_uri, '=', 1.0))
                    matched_source.add(s_uri)
                    matched_target.add(t_uri)
                    break

    # Phase 2: Cross-compare labels with domain/range compatibility
    for s_uri, s_info in source_props.items():
        if s_uri in matched_source:
            continue
        s_labels = {normalize(l) for l in s_info['all_labels']}

        best_match = None
        best_score = 0.0
        for t_uri, t_info in target_props.items():
            if t_uri in matched_target:
                continue
            t_labels = {normalize(l) for l in t_info['all_labels']}

            label_overlap = s_labels & t_labels
            if label_overlap:
                label_sim = 0.8
            else:
                label_sim = max(
                    (jaccard_tokens(sl, tl)
                     for sl in s_info['all_labels']
                     for tl in t_info['all_labels']),
                    default=0.0
                )

            if label_sim < 0.3:
                continue

            dr_score = 0.0
            if s_info['domain'] and t_info['domain']:
                if (s_info['domain'], t_info['domain']) in class_match_map:
                    dr_score += 0.5
            if s_info['range'] and t_info['range']:
                if (s_info['range'], t_info['range']) in class_match_map:
                    dr_score += 0.5

            combined = 0.6 * label_sim + 0.4 * dr_score
            if combined > best_score:
                best_score = combined
                best_match = t_uri

        if best_match and best_score >= 0.3:
            alignments.append((s_uri, best_match, '=', best_score))
            matched_source.add(s_uri)
            matched_target.add(best_match)

    return alignments


def write_alignment(class_alignments, prop_alignments, output_path):
    """Write alignment in OAEI XML format."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    all_alignments = class_alignments + prop_alignments

    lines = []
    lines.append('<?xml version="1.0" encoding="utf-8"?>')
    lines.append('<rdf:RDF xmlns="http://knowledgeweb.semanticweb.org/heterogeneity/alignment"')
    lines.append('     xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"')
    lines.append('     xmlns:xsd="http://www.w3.org/2001/XMLSchema#">')
    lines.append('')
    lines.append('<Alignment>')
    lines.append('<xml>yes</xml>')
    lines.append('<level>0</level>')
    lines.append('<type>??</type>')
    lines.append('<onto1>')
    lines.append('  <Ontology rdf:about="{}">'.format(SOURCE_BASE))
    lines.append('    <location>file:///app/data/source.owl</location>')
    lines.append('  </Ontology>')
    lines.append('</onto1>')
    lines.append('<onto2>')
    lines.append('  <Ontology rdf:about="{}">'.format(TARGET_BASE))
    lines.append('    <location>file:///app/data/target.owl</location>')
    lines.append('  </Ontology>')
    lines.append('</onto2>')
    lines.append('')

    for s_uri, t_uri, relation, confidence in all_alignments:
        # Ensure URIs use correct namespaces
        if '#' in s_uri:
            local = s_uri.split('#')[-1]
            s_uri = SOURCE_NS + local
        if '#' in t_uri:
            local = t_uri.split('#')[-1]
            t_uri = TARGET_NS + local

        rel_escaped = escape(relation)
        lines.append('<map>')
        lines.append('  <Cell>')
        lines.append('    <entity1 rdf:resource="{}"/>'.format(escape(s_uri)))
        lines.append('    <entity2 rdf:resource="{}"/>'.format(escape(t_uri)))
        lines.append('    <measure rdf:datatype="xsd:float">{:.2f}</measure>'.format(confidence))
        lines.append('    <relation>{}</relation>'.format(rel_escaped))
        lines.append('  </Cell>')
        lines.append('</map>')
        lines.append('')

    lines.append('</Alignment>')
    lines.append('</rdf:RDF>')
    lines.append('')

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def main():
    print("Parsing source ontology...")
    source_classes, source_props = parse_ontology(SOURCE_OWL)
    print("  Found {} classes, {} properties".format(len(source_classes), len(source_props)))

    print("Parsing target ontology...")
    target_classes, target_props = parse_ontology(TARGET_OWL)
    print("  Found {} classes, {} properties".format(len(target_classes), len(target_props)))

    # Diagnostic: show sample URIs
    if source_classes:
        sample = next(iter(source_classes))
        print("  Sample source URI: {}".format(sample))
    if target_classes:
        sample = next(iter(target_classes))
        print("  Sample target URI: {}".format(sample))

    print("Finding class alignments...")
    class_alignments, class_match_map = find_class_alignments(source_classes, target_classes)
    equiv = sum(1 for a in class_alignments if a[2] == '=')
    sub = sum(1 for a in class_alignments if a[2] in ('>', '<'))
    print("  Found {} equivalences, {} subsumptions".format(equiv, sub))

    print("Finding property alignments...")
    prop_alignments = find_property_alignments(source_props, target_props, class_match_map)
    print("  Found {} property correspondences".format(len(prop_alignments)))

    print("Writing alignment to {}...".format(OUTPUT_PATH))
    write_alignment(class_alignments, prop_alignments, OUTPUT_PATH)
    print("Done.")


if __name__ == '__main__':
    main()
