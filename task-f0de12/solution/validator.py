#!/usr/bin/env python3
"""HL7 v2 ER7 Message Conformance Validator.

Validates HL7 v2 ER7 messages against an XML conformance profile, checking
segment-level structure (usage, cardinality, groups) and field-level
constraints (usage, length).
"""

import xml.etree.ElementTree as ET
import json
import sys
import re


def parse_profile(xml_path):
    """Parse the XML conformance profile into an internal representation."""
    tree = ET.parse(xml_path)
    root = tree.getroot()

    seg_defs = {}
    segments_elem = root.find("Segments")
    if segments_elem is not None:
        for seg_elem in segments_elem.findall("Segment"):
            seg_id = seg_elem.get("ID")
            fields = []
            for f in seg_elem.findall("Field"):
                fields.append({
                    "name": f.get("Name"),
                    "datatype": f.get("Datatype"),
                    "usage": f.get("Usage", "O"),
                    "min": int(f.get("Min", "0")),
                    "max_str": f.get("Max", "1"),
                    "min_length": int(f.get("MinLength", "0")),
                    "max_length": int(f.get("MaxLength", "99999")),
                })
            seg_defs[seg_id] = {
                "id": seg_id,
                "name": seg_elem.get("Name"),
                "fields": fields,
            }

    msg_elem = root.find("Message")
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
        if elem.tag == "Segment":
            children.append({
                "type": "segment",
                "ref": elem.get("Ref"),
                "usage": elem.get("Usage", "O"),
                "min": int(elem.get("Min", "0")),
                "max_str": elem.get("Max", "1"),
            })
        elif elem.tag == "Group":
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


def _entry_seg_ids(node):
    """Compute segment IDs that can begin this structure node.

    For a segment node, it is just that segment's ID.
    For a group, we walk its children: each child adds its entry IDs,
    and we stop when we hit a required child with min >= 1 (it must
    appear before anything after it).
    """
    if node["type"] == "segment":
        return {node["ref"]}
    result = set()
    for child in node["children"]:
        result.update(_entry_seg_ids(child))
        if child.get("usage") == "R" and child.get("min", 0) >= 1:
            break
    return result


def parse_er7(text):
    """Parse an ER7 message into a list of segment dicts and invalid lines."""
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


def _validate_fields(seg, seg_def, errors):
    """Validate fields of a parsed segment against the profile definition."""
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
                "message": (
                    f"Required field {seg_id}-{field_num} "
                    f"({fdef['name']}) is empty or missing"
                ),
            })
        elif usage == "W" and value:
            errors.append({
                "category": "usage",
                "path": f"{seg_id}-{field_num}",
                "message": (
                    f"Withdrawn field {seg_id}-{field_num} "
                    f"({fdef['name']}) is populated"
                ),
            })
        elif usage == "X" and value:
            errors.append({
                "category": "usage",
                "path": f"{seg_id}-{field_num}",
                "message": (
                    f"Not-supported field {seg_id}-{field_num} "
                    f"({fdef['name']}) is populated"
                ),
            })

        if value:
            vlen = len(value)
            if vlen < fdef["min_length"]:
                errors.append({
                    "category": "length",
                    "path": f"{seg_id}-{field_num}",
                    "message": (
                        f"Field {seg_id}-{field_num} ({fdef['name']}) "
                        f"length {vlen} below minimum {fdef['min_length']}"
                    ),
                })
            if vlen > fdef["max_length"]:
                errors.append({
                    "category": "length",
                    "path": f"{seg_id}-{field_num}",
                    "message": (
                        f"Field {seg_id}-{field_num} ({fdef['name']}) "
                        f"length {vlen} exceeds maximum {fdef['max_length']}"
                    ),
                })


def _match_structure(segments, pos, children, profile, errors):
    """Recursively match message segments against profile structure.

    Returns the new position after matching all children.
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
                            "message": (
                                f"Segment {ref} is not supported (Usage=X) "
                                f"but present at line {segments[pos]['line_num']}"
                            ),
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
                    "message": (
                        f"Segment {ref} requires minimum "
                        f"{min_count} occurrence(s) but found {count}"
                    ),
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
                    "message": (
                        f"Group {name} requires minimum "
                        f"{min_count} occurrence(s) but found {count}"
                    ),
                })

    return pos


def validate(profile, message_text):
    """Validate an ER7 message against the conformance profile."""
    errors = []

    segments, invalid_lines, sep_or_err = parse_er7(message_text)

    if segments is None:
        return {
            "valid": False,
            "errors": [{
                "category": "invalid_line",
                "path": "",
                "message": sep_or_err,
            }],
            "error_count": 1,
        }

    for inv in invalid_lines:
        errors.append({
            "category": "invalid_line",
            "path": f"line-{inv['line_num']}",
            "message": f"Invalid line at position {inv['line_num']}",
        })

    known_ids = set(profile["segment_defs"].keys()) | profile["struct_seg_ids"]
    unexpected_idx = set()
    for i, seg in enumerate(segments):
        if seg["id"] not in known_ids:
            errors.append({
                "category": "unexpected",
                "path": seg["id"],
                "message": (
                    f"Segment {seg['id']} at line {seg['line_num']} "
                    f"is not defined in the profile"
                ),
            })
            unexpected_idx.add(i)

    filtered = [s for i, s in enumerate(segments) if i not in unexpected_idx]

    end_pos = _match_structure(filtered, 0, profile["structure"], profile, errors)

    for i in range(end_pos, len(filtered)):
        seg = filtered[i]
        errors.append({
            "category": "unexpected",
            "path": seg["id"],
            "message": (
                f"Segment {seg['id']} at line {seg['line_num']} "
                f"does not match expected message structure"
            ),
        })

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "error_count": len(errors),
    }


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <profile> <message>", file=sys.stderr)
        sys.exit(1)

    profile = parse_profile(sys.argv[1])

    with open(sys.argv[2]) as f:
        msg_text = f.read()

    result = validate(profile, msg_text)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
