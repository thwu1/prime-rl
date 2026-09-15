#!/usr/bin/env python3
"""HL7 v2 Conformance Profile Reconciliation Engine.

Reads two HL7 v2 conformance profiles (XInclude-fragmented XML in the
urn:hl7-org:v2:conformance namespace), resolves them using xmllint,
computes their intersection (tightest profile satisfying both), validates
a corpus of ER7 messages against each profile, and produces the
reconciled profile XML and a conformance assessment JSON.
"""

import xml.etree.ElementTree as ET
import json
import os
import re
import copy
import subprocess
import sys

NS = "urn:hl7-org:v2:conformance"


# ========================================================================
# XInclude Resolution
# ========================================================================

def resolve_xinclude(profile_dir):
    """Resolve XInclude references in profile.xml using xmllint."""
    profile_path = os.path.join(profile_dir, "profile.xml")
    result = subprocess.run(
        ["xmllint", "--xinclude", profile_path],
        capture_output=True, text=True, check=True
    )
    # Remove xml:base attributes added by XInclude processing
    resolved = re.sub(r'\s+xml:base="[^"]*"', '', result.stdout)
    return resolved


# ========================================================================
# Profile Parsing
# ========================================================================

def parse_profile(xml_string):
    """Parse resolved conformance profile XML into internal representation."""
    ET.register_namespace('', NS)
    root = ET.fromstring(xml_string)

    seg_defs = {}
    segments_elem = root.find(f"{{{NS}}}Segments")
    if segments_elem is not None:
        for seg_elem in segments_elem.findall(f"{{{NS}}}Segment"):
            seg_id = seg_elem.get("ID")
            fields = []
            for f in seg_elem.findall(f"{{{NS}}}Field"):
                max_len_raw = f.get("MaxLength", "99999")
                try:
                    max_len = int(max_len_raw)
                except ValueError:
                    max_len = 99999
                fields.append({
                    "name": f.get("Name"),
                    "datatype": f.get("Datatype", "ST"),
                    "usage": f.get("Usage", "O"),
                    "min": int(f.get("Min", "0")),
                    "max_str": f.get("Max", "1"),
                    "min_length": int(f.get("MinLength", "0")),
                    "max_length": max_len,
                })
            seg_defs[seg_id] = {
                "id": seg_id,
                "name": seg_elem.get("Name"),
                "fields": fields,
            }

    msg_elem = root.find(f"{{{NS}}}Message")
    structure = _parse_children(msg_elem)

    struct_seg_ids = set()
    _collect_seg_ids(structure, struct_seg_ids)

    return {
        "segment_defs": seg_defs,
        "structure": structure,
        "struct_seg_ids": struct_seg_ids,
    }


def _parse_children(parent_elem):
    children = []
    for elem in parent_elem:
        if elem.tag == f"{{{NS}}}Segment":
            children.append({
                "type": "segment",
                "ref": elem.get("Ref"),
                "usage": elem.get("Usage", "O"),
                "min": int(elem.get("Min", "0")),
                "max_str": elem.get("Max", "1"),
            })
        elif elem.tag == f"{{{NS}}}Group":
            children.append({
                "type": "group",
                "name": elem.get("Name"),
                "usage": elem.get("Usage", "O"),
                "min": int(elem.get("Min", "0")),
                "max_str": elem.get("Max", "1"),
                "children": _parse_children(elem),
            })
    return children


def _collect_seg_ids(children, result):
    for child in children:
        if child["type"] == "segment":
            result.add(child["ref"])
        elif child["type"] == "group":
            _collect_seg_ids(child["children"], result)


# ========================================================================
# ER7 Message Parsing
# ========================================================================

def parse_er7(text):
    """Parse an ER7-encoded HL7 v2 message.

    Returns (segments, invalid_lines, field_sep) or (None, None, error_msg).
    """
    lines = re.split(r"[\r\n]+", text.strip())
    lines = [l for l in lines if l.strip()]

    if not lines or not lines[0].startswith("MSH"):
        return None, None, "Message must start with MSH"

    msh_line = lines[0]
    if len(msh_line) < 4:
        return None, None, "MSH segment too short"

    field_sep = msh_line[3]
    segments = []
    invalid_lines = []

    for idx, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        if (len(line) >= 3
                and re.match(r"^[A-Z][A-Z0-9]{2}", line)
                and (len(line) == 3 or line[3] == field_sep)):
            seg_id = line[:3]
            if seg_id == "MSH":
                raw = msh_line[4:]
                parts = raw.split(field_sep)
                fields = [field_sep] + parts
            else:
                fields = line[4:].split(field_sep) if len(line) > 3 else []
            segments.append({
                "id": seg_id,
                "fields": fields,
                "line_num": idx + 1,
            })
        else:
            invalid_lines.append({
                "line_num": idx + 1,
                "content": line,
            })

    return segments, invalid_lines, field_sep


# ========================================================================
# Message Validation
# ========================================================================

def _entry_seg_ids(node):
    """Compute segment IDs that can begin this structure node."""
    if node["type"] == "segment":
        return {node["ref"]}
    result = set()
    for child in node["children"]:
        result.update(_entry_seg_ids(child))
        if child.get("usage") == "R" and child.get("min", 0) >= 1:
            break
    return result


def _validate_fields(seg, seg_def, errors):
    """Validate fields of a parsed segment against its definition."""
    seg_id = seg["id"]
    fields = seg["fields"]
    field_defs = seg_def["fields"]

    for i, fdef in enumerate(field_defs):
        field_num = i + 1
        if seg_id == "MSH" and field_num <= 2:
            continue

        value = fields[i] if i < len(fields) else ""
        usage = fdef["usage"]

        if usage == "R" and not value:
            errors.append({
                "category": "required_field",
                "path": f"{seg_id}-{field_num}",
            })
        elif usage == "W" and value:
            errors.append({
                "category": "usage",
                "path": f"{seg_id}-{field_num}",
            })
        elif usage == "X" and value:
            errors.append({
                "category": "usage",
                "path": f"{seg_id}-{field_num}",
            })

        if value:
            vlen = len(value)
            if vlen < fdef["min_length"]:
                errors.append({
                    "category": "length",
                    "path": f"{seg_id}-{field_num}",
                })
            if vlen > fdef["max_length"]:
                errors.append({
                    "category": "length",
                    "path": f"{seg_id}-{field_num}",
                })


def _match_structure(segments, pos, children, profile, errors):
    """Recursively match message segments against profile structure.

    Returns the new position after matching.
    """
    for child in children:
        if child["type"] == "segment":
            ref = child["ref"]
            usage = child["usage"]
            min_count = child["min"]
            max_str = child["max_str"]
            max_count = None if max_str == "*" else int(max_str)

            count = 0
            while pos < len(segments):
                if segments[pos]["id"] == ref:
                    if usage == "X":
                        errors.append({
                            "category": "usage",
                            "path": ref,
                        })
                    else:
                        seg_def = profile["segment_defs"].get(ref)
                        if seg_def:
                            _validate_fields(segments[pos], seg_def, errors)
                    count += 1
                    pos += 1
                    if max_count is not None and count >= max_count:
                        break
                else:
                    break

            if usage == "R" and count < min_count:
                errors.append({
                    "category": "cardinality",
                    "path": ref,
                })

        elif child["type"] == "group":
            name = child["name"]
            usage = child["usage"]
            min_count = child["min"]
            max_str = child["max_str"]
            max_count = None if max_str == "*" else int(max_str)

            entry_ids = _entry_seg_ids(child)
            count = 0
            while pos < len(segments):
                if segments[pos]["id"] in entry_ids:
                    new_pos = _match_structure(
                        segments, pos, child["children"], profile, errors
                    )
                    if new_pos > pos:
                        count += 1
                        pos = new_pos
                        if max_count is not None and count >= max_count:
                            break
                    else:
                        break
                else:
                    break

            if usage == "R" and count < min_count:
                errors.append({
                    "category": "cardinality",
                    "path": name,
                })

    return pos


def validate_message(profile, message_text):
    """Validate an ER7 message against a profile.

    Returns (is_valid: bool, errors: list).
    """
    errors = []
    segments, invalid_lines, sep_or_err = parse_er7(message_text)

    if segments is None:
        return False, [{"category": "parse_error", "path": "", "message": sep_or_err}]

    for inv in invalid_lines:
        errors.append({
            "category": "invalid_line",
            "path": f"line-{inv['line_num']}",
        })

    known_ids = set(profile["segment_defs"].keys()) | profile["struct_seg_ids"]
    unexpected_idx = set()
    for i, seg in enumerate(segments):
        if seg["id"] not in known_ids:
            errors.append({
                "category": "unexpected",
                "path": seg["id"],
            })
            unexpected_idx.add(i)

    filtered = [s for i, s in enumerate(segments) if i not in unexpected_idx]

    end_pos = _match_structure(filtered, 0, profile["structure"], profile, errors)

    for i in range(end_pos, len(filtered)):
        errors.append({
            "category": "unexpected",
            "path": filtered[i]["id"],
        })

    return len(errors) == 0, errors


# ========================================================================
# Profile Reconciliation
# ========================================================================

def _reconcile_usage(usage_a, usage_b):
    """Compute reconciled usage from two profiles.

    Returns (reconciled_usage, is_compatible).
    """
    ua = "O" if usage_a == "C" else usage_a
    ub = "O" if usage_b == "C" else usage_b

    pair = frozenset([ua, ub])

    if ua == ub:
        return ua, True

    if pair == frozenset(["R", "O"]):
        return "R", True
    if pair == frozenset(["R", "X"]):
        return "X", False
    if pair == frozenset(["R", "W"]):
        return "X", False
    if pair == frozenset(["O", "X"]):
        return "X", True
    if pair == frozenset(["O", "W"]):
        return "W", True
    if pair == frozenset(["X", "W"]):
        return "X", True

    return "O", True


def _reconcile_cardinality(min_a, max_a_str, min_b, max_b_str):
    """Compute reconciled cardinality range."""
    rec_min = max(min_a, min_b)

    max_a = None if max_a_str == "*" else int(max_a_str)
    max_b = None if max_b_str == "*" else int(max_b_str)

    if max_a is None and max_b is None:
        rec_max_str = "*"
    elif max_a is None:
        rec_max_str = str(max_b)
    elif max_b is None:
        rec_max_str = str(max_a)
    else:
        rec_max_str = str(min(max_a, max_b))

    return rec_min, rec_max_str


def _reconcile_structure(children_a, children_b):
    """Reconcile two lists of structure children (segments/groups)."""
    result = []

    def _key(child):
        return (child["type"], child.get("ref") or child.get("name"))

    b_by_key = {}
    for cb in children_b:
        b_by_key[_key(cb)] = cb
    a_keys_seen = set()

    for child_a in children_a:
        k = _key(child_a)
        a_keys_seen.add(k)
        child_b = b_by_key.get(k)

        if child_b is None:
            rec = copy.deepcopy(child_a)
            rec["usage"] = "X"
            rec["min"] = 0
            result.append(rec)
            continue

        rec_usage, compatible = _reconcile_usage(
            child_a["usage"], child_b["usage"]
        )
        rec_min, rec_max_str = _reconcile_cardinality(
            child_a["min"], child_a["max_str"],
            child_b["min"], child_b["max_str"],
        )

        if child_a["type"] == "segment":
            result.append({
                "type": "segment",
                "ref": child_a["ref"],
                "usage": rec_usage,
                "min": rec_min,
                "max_str": rec_max_str,
            })
        elif child_a["type"] == "group":
            rec_children = _reconcile_structure(
                child_a["children"], child_b["children"]
            )
            result.append({
                "type": "group",
                "name": child_a["name"],
                "usage": rec_usage,
                "min": rec_min,
                "max_str": rec_max_str,
                "children": rec_children,
            })

    for child_b in children_b:
        k = _key(child_b)
        if k not in a_keys_seen:
            rec = copy.deepcopy(child_b)
            rec["usage"] = "X"
            rec["min"] = 0
            result.append(rec)

    return result


def _reconcile_fields(fields_a, fields_b):
    """Reconcile field definitions. Returns (fields, all_compatible)."""
    result = []
    all_compatible = True
    n = max(len(fields_a), len(fields_b))

    for i in range(n):
        fa = fields_a[i] if i < len(fields_a) else None
        fb = fields_b[i] if i < len(fields_b) else None

        if fa and fb:
            rec_usage, compat = _reconcile_usage(fa["usage"], fb["usage"])
            rec_min, rec_max_str = _reconcile_cardinality(
                fa["min"], fa["max_str"], fb["min"], fb["max_str"]
            )
            rec_min_len = max(fa["min_length"], fb["min_length"])
            rec_max_len = min(fa["max_length"], fb["max_length"])
            if not compat:
                all_compatible = False
            result.append({
                "name": fa["name"],
                "datatype": fa["datatype"],
                "usage": rec_usage,
                "min": rec_min,
                "max_str": rec_max_str,
                "min_length": rec_min_len,
                "max_length": rec_max_len,
            })
        elif fa:
            result.append(copy.deepcopy(fa))
        else:
            result.append(copy.deepcopy(fb))

    return result, all_compatible


def _mark_unusable_segments(children, unusable_segs):
    """Set segments with field-level incompatibilities to X."""
    for child in children:
        if child["type"] == "segment" and child["ref"] in unusable_segs:
            child["usage"] = "X"
            child["min"] = 0
        elif child["type"] == "group":
            _mark_unusable_segments(child["children"], unusable_segs)


def reconcile_profiles(profile_a, profile_b):
    """Reconcile two profiles into the tightest intersection."""
    rec_structure = _reconcile_structure(
        profile_a["structure"], profile_b["structure"]
    )

    rec_seg_defs = {}
    unusable_segs = set()
    all_seg_ids = set(profile_a["segment_defs"].keys()) | set(
        profile_b["segment_defs"].keys()
    )

    for seg_id in all_seg_ids:
        def_a = profile_a["segment_defs"].get(seg_id)
        def_b = profile_b["segment_defs"].get(seg_id)

        if def_a and def_b:
            rec_fields, all_compat = _reconcile_fields(
                def_a["fields"], def_b["fields"]
            )
            if not all_compat:
                unusable_segs.add(seg_id)
            rec_seg_defs[seg_id] = {
                "id": seg_id,
                "name": def_a["name"],
                "fields": rec_fields,
            }
        elif def_a:
            rec_seg_defs[seg_id] = copy.deepcopy(def_a)
        else:
            rec_seg_defs[seg_id] = copy.deepcopy(def_b)

    _mark_unusable_segments(rec_structure, unusable_segs)

    struct_seg_ids = set()
    _collect_seg_ids(rec_structure, struct_seg_ids)

    return {
        "segment_defs": rec_seg_defs,
        "structure": rec_structure,
        "struct_seg_ids": struct_seg_ids,
    }


# ========================================================================
# XML Output
# ========================================================================

def _structure_to_xml(parent_elem, children):
    for child in children:
        if child["type"] == "segment":
            elem = ET.SubElement(parent_elem, f"{{{NS}}}Segment")
            elem.set("Ref", child["ref"])
            elem.set("Usage", child["usage"])
            elem.set("Min", str(child["min"]))
            elem.set("Max", child["max_str"])
        elif child["type"] == "group":
            elem = ET.SubElement(parent_elem, f"{{{NS}}}Group")
            elem.set("Name", child["name"])
            elem.set("Usage", child["usage"])
            elem.set("Min", str(child["min"]))
            elem.set("Max", child["max_str"])
            _structure_to_xml(elem, child["children"])


def write_reconciled_profile(profile, output_path):
    """Write reconciled profile to namespace-qualified XML."""
    ET.register_namespace('', NS)
    root = ET.Element(f"{{{NS}}}ConformanceProfile")

    msg_elem = ET.SubElement(root, f"{{{NS}}}Message")
    msg_elem.set("ID", "ORU_R01")
    msg_elem.set("Name", "ORU^R01")
    msg_elem.set("Type", "ORU")
    msg_elem.set("Event", "R01")
    msg_elem.set("StructID", "ORU_R01")
    _structure_to_xml(msg_elem, profile["structure"])

    segs_elem = ET.SubElement(root, f"{{{NS}}}Segments")
    for seg_id in sorted(profile["segment_defs"].keys()):
        seg_def = profile["segment_defs"][seg_id]
        seg_elem = ET.SubElement(segs_elem, f"{{{NS}}}Segment")
        seg_elem.set("ID", seg_id)
        seg_elem.set("Name", seg_def["name"])
        for fld in seg_def["fields"]:
            f_elem = ET.SubElement(seg_elem, f"{{{NS}}}Field")
            f_elem.set("Name", fld["name"])
            f_elem.set("Datatype", fld.get("datatype", "ST"))
            f_elem.set("Usage", fld["usage"])
            f_elem.set("Min", str(fld["min"]))
            f_elem.set("Max", fld["max_str"])
            f_elem.set("MinLength", str(fld["min_length"]))
            f_elem.set("MaxLength", str(fld["max_length"]))

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    tree.write(output_path, encoding="unicode", xml_declaration=True)


# ========================================================================
# XSD Validation
# ========================================================================

def validate_xsd(xml_path, xsd_path):
    """Validate reconciled profile against XSD using xmllint."""
    result = subprocess.run(
        ["xmllint", "--schema", xsd_path, "--noout", xml_path],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"XSD validation warning: {result.stderr}", file=sys.stderr)
    return result.returncode == 0


# ========================================================================
# Main
# ========================================================================

def main():
    profiles_dir = "/app/profiles"
    messages_dir = "/app/messages"
    output_dir = "/app/output"
    schema_path = "/app/schemas/conformance_profile.xsd"

    # Resolve XInclude fragments into complete profiles
    xml_a = resolve_xinclude(os.path.join(profiles_dir, "system_a"))
    xml_b = resolve_xinclude(os.path.join(profiles_dir, "system_b"))

    profile_a = parse_profile(xml_a)
    profile_b = parse_profile(xml_b)

    reconciled = reconcile_profiles(profile_a, profile_b)

    reconciled_path = os.path.join(output_dir, "reconciled_profile.xml")
    write_reconciled_profile(reconciled, reconciled_path)

    # Validate reconciled profile against XSD
    if validate_xsd(reconciled_path, schema_path):
        print("XSD validation passed.")
    else:
        print("XSD validation failed.", file=sys.stderr)

    assessment = {}
    for msg_file in sorted(os.listdir(messages_dir)):
        if not msg_file.endswith(".hl7"):
            continue
        msg_path = os.path.join(messages_dir, msg_file)
        with open(msg_path) as f:
            msg_text = f.read()

        valid_a, _ = validate_message(profile_a, msg_text)
        valid_b, _ = validate_message(profile_b, msg_text)
        valid_rec, _ = validate_message(reconciled, msg_text)

        assessment[msg_file] = {
            "system_a": valid_a,
            "system_b": valid_b,
            "reconciled": valid_rec,
        }

    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, "assessment.json"), "w") as f:
        json.dump(assessment, f, indent=2)

    print("Reconciliation complete.")
    print(f"  Reconciled profile: {output_dir}/reconciled_profile.xml")
    print(f"  Assessment: {output_dir}/assessment.json")


if __name__ == "__main__":
    main()
