#!/usr/bin/env python3

"""Reference solution: generates /app/deid_tool.py

This script writes the complete DICOM PS3.15 de-identification profile
resolver, transformer, and conformance auditor to /app/deid_tool.py.
It parses the action table from TSV format and implements compound
action code resolution, option override semantics, VR-aware
de-identification with recursive sequence traversal, multi-file
dataset mode with cross-file UID consistency, and compliance auditing
per PS3.15 Annex E.
"""

import textwrap

TOOL_CODE = textwrap.dedent(r'''
#!/usr/bin/env python3
"""DICOM PS3.15 De-identification Profile Resolver, Transformer, and Auditor.

Parses the action table from TSV, implements action resolution from
Table E.1-1 with option overrides, compound action code resolution
via IOD Type, VR-aware de-identification with consistent UID remapping,
recursive Sequence traversal, multi-file dataset mode, and DICOM file
auditing.
"""

import argparse
import csv
import glob
import json
import os
import sys
from pathlib import Path


ACTION_TABLE_PATH = "/app/data/action_table.tsv"

# Mapping from abbreviated TSV column headers to canonical option names
COLUMN_TO_OPTION = {
    "Rtn. Safe Priv. Opt.": "retain_safe_private",
    "Rtn. UIDs Opt.": "retain_uids",
    "Rtn. Dev. Id. Opt.": "retain_device_id",
    "Rtn. Inst. Id. Opt.": "retain_institution_id",
    "Rtn. Pat. Chars. Opt.": "retain_patient_chars",
    "Rtn. Long. Full Dates Opt.": "retain_full_dates",
    "Rtn. Long. Modif. Dates Opt.": "retain_modified_dates",
    "Clean Desc. Opt.": "clean_descriptors",
    "Clean Struct. Cont. Opt.": "clean_structured_content",
    "Clean Graph. Opt.": "clean_graphics",
}

COMPOUND_RESOLUTION = {
    ("Z/D", 1): "D",
    ("Z/D", 2): "Z",
    ("X/Z", 2): "Z",
    ("X/Z", 3): "X",
    ("X/D", 1): "D",
    ("X/D", 3): "X",
    ("X/Z/D", 1): "D",
    ("X/Z/D", 2): "Z",
    ("X/Z/D", 3): "X",
    ("X/Z/U*", 1): "U",
    ("X/Z/U*", 2): "Z",
    ("X/Z/U*", 3): "X",
}


def load_action_table():
    """Load the DICOM PS3.15 Table E.1-1 from TSV."""
    entries = []
    with open(ACTION_TABLE_PATH, newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            tag = row["Tag"].strip()
            attr_name = row["Attribute Name"].strip()
            basic_action = row["Basic Prof."].strip()

            options = {}
            for col_header, opt_name in COLUMN_TO_OPTION.items():
                val = row.get(col_header, "").strip()
                if val:
                    options[opt_name] = val

            entries.append({
                "tag": tag,
                "attribute_name": attr_name,
                "basic_profile_action": basic_action,
                "options": options,
            })
    return entries


def is_compound(action):
    return "/" in action


def resolve_compound(action, iod_type):
    if iod_type is None:
        return action
    key = (action, iod_type)
    return COMPOUND_RESOLUTION.get(key, action)


def resolve_action(entry, options, iod_type=None):
    action = entry["basic_profile_action"]
    source = "basic_profile"

    entry_options = entry.get("options", {})
    for opt in options:
        if opt in entry_options:
            action = entry_options[opt]
            source = opt

    if is_compound(action):
        action = resolve_compound(action, iod_type)

    return action, source


def parse_options(options_str):
    if not options_str or options_str.strip() == "":
        return []
    return [o.strip() for o in options_str.split(",") if o.strip()]


def parse_tag_to_ints(tag_str):
    tag_str = tag_str.strip()
    lower = tag_str.lower()
    if "xx" in lower or "gg" in lower or "ee" in lower:
        return None
    tag_str = tag_str.strip("()")
    parts = tag_str.split(",")
    if len(parts) != 2:
        return None
    try:
        group = int(parts[0].strip(), 16)
        element = int(parts[1].strip(), 16)
        return group, element
    except (ValueError, IndexError):
        return None


def build_action_map(table, options, iod_type):
    """Build a map from (group, element) -> resolved action string."""
    action_map = {}
    for entry in table:
        parsed = parse_tag_to_ints(entry["tag"])
        if parsed is None:
            continue
        group, element = parsed
        action, source = resolve_action(entry, options, iod_type)
        action_map[(group, element)] = action
    return action_map


def build_action_info_map(table, options, iod_type):
    """Build a map from (group, element) -> {action, attribute_name, tag_str}."""
    info_map = {}
    for entry in table:
        parsed = parse_tag_to_ints(entry["tag"])
        if parsed is None:
            continue
        group, element = parsed
        action, source = resolve_action(entry, options, iod_type)
        info_map[(group, element)] = {
            "action": action,
            "attribute_name": entry["attribute_name"],
            "tag_str": entry["tag"],
        }
    return info_map


def cmd_resolve(args):
    table = load_action_table()
    options = parse_options(args.options) if args.options else []
    iod_type = args.iod_type

    tag = args.tag.upper()

    entry = None
    for e in table:
        if e["tag"].upper() == tag:
            entry = e
            break

    if entry is None:
        result = {"tag": tag, "resolved_action": None, "source": None}
    else:
        action, source = resolve_action(entry, options, iod_type)
        result = {"tag": tag, "resolved_action": action, "source": source}

    print(json.dumps(result))


def cmd_batch_resolve(args):
    table = load_action_table()
    options = parse_options(args.options) if args.options else []
    iod_type = args.iod_type

    results = []
    for entry in table:
        action, source = resolve_action(entry, options, iod_type)
        results.append({
            "tag": entry["tag"],
            "attribute_name": entry["attribute_name"],
            "resolved_action": action,
            "source": source,
        })

    print(json.dumps(results))


def deidentify_dataset(ds, action_map, uid_map):
    """Apply de-identification actions to a pydicom Dataset, recursively
    processing Sequence items. uid_map is shared across calls for consistency."""
    import pydicom
    from pydicom.uid import generate_uid
    from pydicom.sequence import Sequence as SQ

    def get_dummy(vr):
        if vr == "SQ":
            return [pydicom.Dataset()]
        vr_dummies = {
            "AE": "ANON",
            "AS": "000Y",
            "CS": "UNKNOWN",
            "DA": "19000101",
            "DS": "0",
            "DT": "19000101000000.000000",
            "FD": 0.0,
            "FL": 0.0,
            "IS": "0",
            "LO": "ANONYMIZED",
            "LT": "ANONYMIZED",
            "PN": "ANONYMOUS",
            "SH": "ANONYMIZED",
            "SL": 0,
            "SS": 0,
            "ST": "ANONYMIZED",
            "TM": "000000",
            "UC": "ANONYMIZED",
            "UI": generate_uid(),
            "UL": 0,
            "UR": "http://anonymized",
            "US": 0,
            "UT": "ANONYMIZED",
        }
        return vr_dummies.get(vr, "ANONYMIZED")

    def remap_uid(original):
        uid_str = str(original)
        if uid_str not in uid_map:
            uid_map[uid_str] = generate_uid()
        return uid_map[uid_str]

    def process_dataset(dataset):
        """Process a single Dataset (top-level or sequence item)."""
        tags_to_remove = []

        # First, recurse into all sequences before modifying this dataset
        for elem in dataset:
            if elem.VR == "SQ" and elem.value:
                for item in elem.value:
                    process_dataset(item)

        # Apply actions from the action map
        for (group, element), action in action_map.items():
            tag_key = (group, element)

            if action == "X":
                if tag_key in dataset:
                    tags_to_remove.append(tag_key)
            elif action == "Z":
                if tag_key in dataset:
                    elem = dataset[tag_key]
                    if elem.VR == "SQ":
                        elem.value = []
                    elif elem.VR in ("OB", "OW", "OF", "OD", "UN"):
                        elem.value = b""
                    else:
                        elem.value = ""
            elif action == "D":
                if tag_key in dataset:
                    elem = dataset[tag_key]
                    elem.value = get_dummy(elem.VR)
            elif action == "U":
                if tag_key in dataset:
                    elem = dataset[tag_key]
                    if elem.value:
                        elem.value = remap_uid(elem.value)
            # K, C: keep unchanged

        for tag_key in tags_to_remove:
            del dataset[tag_key]

    process_dataset(ds)


def cmd_deidentify(args):
    import pydicom

    table = load_action_table()
    options = parse_options(args.options) if args.options else []
    iod_type = args.iod_type

    action_map = build_action_map(table, options, iod_type)

    # Shared UID map for consistency across files/sequences
    uid_map = {}

    if args.input_dir:
        # Dataset mode
        input_dir = args.input_dir
        output_dir = args.output_dir
        os.makedirs(output_dir, exist_ok=True)

        dcm_files = sorted(glob.glob(os.path.join(input_dir, "*.dcm")))
        count = 0
        for dcm_path in dcm_files:
            ds = pydicom.dcmread(dcm_path, force=True)
            deidentify_dataset(ds, action_map, uid_map)
            ds.add_new(0x00120062, "CS", "YES")
            ds.add_new(0x00120063, "LO", "Per DICOM PS3.15 AnnexE")
            out_path = os.path.join(output_dir, os.path.basename(dcm_path))
            ds.save_as(out_path)
            count += 1

        print(json.dumps({"status": "ok", "files_processed": count}))
    else:
        # Single-file mode
        ds = pydicom.dcmread(args.input, force=True)
        deidentify_dataset(ds, action_map, uid_map)
        ds.add_new(0x00120062, "CS", "YES")
        ds.add_new(0x00120063, "LO", "Per DICOM PS3.15 AnnexE")
        ds.save_as(args.output)
        print(json.dumps({"status": "ok", "output": args.output}))


def cmd_audit(args):
    import pydicom

    table = load_action_table()
    options = parse_options(args.options) if args.options else []
    iod_type = args.iod_type

    info_map = build_action_info_map(table, options, iod_type)

    ds = pydicom.dcmread(args.input, force=True)

    violations = []
    total_checked = [0]  # mutable for nested function access

    def audit_dataset(dataset, location):
        """Audit a single Dataset (top-level or sequence item)."""
        # Check each tag in action map
        for (group, element), info in info_map.items():
            action = info["action"]
            tag_str = info["tag_str"]
            attr_name = info["attribute_name"]
            tag_key = (group, element)

            if action == "X":
                total_checked[0] += 1
                if tag_key in dataset:
                    violations.append({
                        "tag": tag_str,
                        "attribute_name": attr_name,
                        "expected_action": action,
                        "finding": "present_but_should_be_removed",
                        "location": location,
                    })
            elif action == "Z":
                total_checked[0] += 1
                if tag_key in dataset:
                    elem = dataset[tag_key]
                    val = elem.value
                    if val is not None and val != "" and val != b"":
                        violations.append({
                            "tag": tag_str,
                            "attribute_name": attr_name,
                            "expected_action": action,
                            "finding": "non_empty_but_should_be_zeroed",
                            "location": location,
                        })
            elif action == "D":
                total_checked[0] += 1
                if tag_key in dataset:
                    elem = dataset[tag_key]
                    val = elem.value
                    if val is None or val == "" or val == b"":
                        violations.append({
                            "tag": tag_str,
                            "attribute_name": attr_name,
                            "expected_action": action,
                            "finding": "empty_but_should_have_dummy",
                            "location": location,
                        })
            elif action in ("K", "U", "C"):
                total_checked[0] += 1

        # Recurse into sequences
        for elem in dataset:
            if elem.VR == "SQ" and elem.value:
                for item in elem.value:
                    audit_dataset(item, "sequence")

    audit_dataset(ds, "top_level")

    result = {
        "violations": violations,
        "total_checked": total_checked[0],
    }
    print(json.dumps(result))


def main():
    parser = argparse.ArgumentParser(
        description="DICOM PS3.15 De-identification Profile Resolver"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # resolve
    p_resolve = subparsers.add_parser("resolve")
    p_resolve.add_argument("--tag", required=True, help="DICOM tag (GGGG,EEEE)")
    p_resolve.add_argument("--options", default="", help="Comma-separated options")
    p_resolve.add_argument("--iod-type", type=int, choices=[1, 2, 3], default=None)

    # batch-resolve
    p_batch = subparsers.add_parser("batch-resolve")
    p_batch.add_argument("--options", default="", help="Comma-separated options")
    p_batch.add_argument("--iod-type", type=int, choices=[1, 2, 3], default=None)

    # deidentify
    p_deid = subparsers.add_parser("deidentify")
    # Single-file mode
    p_deid.add_argument("--input", default=None, help="Input DICOM file")
    p_deid.add_argument("--output", default=None, help="Output DICOM file")
    # Dataset mode
    p_deid.add_argument("--input-dir", default=None, help="Input directory of DICOM files")
    p_deid.add_argument("--output-dir", default=None, help="Output directory")
    p_deid.add_argument("--options", default="", help="Comma-separated options")
    p_deid.add_argument("--iod-type", type=int, choices=[1, 2, 3], required=True)

    # audit
    p_audit = subparsers.add_parser("audit")
    p_audit.add_argument("--input", required=True, help="Path to DICOM file")
    p_audit.add_argument("--options", default="", help="Comma-separated options")
    p_audit.add_argument("--iod-type", type=int, choices=[1, 2, 3], required=True)

    args = parser.parse_args()

    if args.command == "resolve":
        cmd_resolve(args)
    elif args.command == "batch-resolve":
        cmd_batch_resolve(args)
    elif args.command == "deidentify":
        cmd_deidentify(args)
    elif args.command == "audit":
        cmd_audit(args)


if __name__ == "__main__":
    main()
''').lstrip()

# Write the tool
with open("/app/deid_tool.py", "w") as f:
    f.write(TOOL_CODE)

print("Written /app/deid_tool.py")
