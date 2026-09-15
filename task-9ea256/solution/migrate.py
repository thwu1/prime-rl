#!/usr/bin/env python3
"""
FHIR ConceptMap-based terminology migration pipeline.

Reads FHIR R4 ConceptMap resources and a migration configuration to translate
coded elements in FHIR NDJSON files from legacy code systems to standard
terminologies.
"""

import json
import os
import re
import sys


def load_config(path):
    with open(path) as f:
        return json.load(f)


def load_concept_maps(dir_path):
    """Load all ConceptMap JSON resources from a directory, keyed by id."""
    maps = {}
    for fname in sorted(os.listdir(dir_path)):
        if fname.endswith(".json"):
            with open(os.path.join(dir_path, fname)) as f:
                cm = json.load(f)
            if cm.get("resourceType") == "ConceptMap" and "id" in cm:
                maps[cm["id"]] = cm
    return maps


def build_lookup(concept_map):
    """Build a structured lookup from a FHIR ConceptMap.

    Returns a list of group lookups, each with:
      source_system, target_system, elements dict, unmapped config.
    """
    groups = []
    for group in concept_map.get("group", []):
        elements = {}
        for element in group.get("element", []):
            targets = []
            for t in element.get("target", []):
                targets.append({
                    "code": t["code"],
                    "display": t.get("display", ""),
                    "equivalence": t.get("equivalence", "equivalent"),
                })
            elements[element["code"]] = {
                "display": element.get("display", ""),
                "targets": targets,
            }
        groups.append({
            "source_system": group.get("source", ""),
            "target_system": group.get("target", ""),
            "elements": elements,
            "unmapped": group.get("unmapped", {}),
        })
    return groups


def parse_fhirpath_selector(expr):
    """Parse a FHIRPath expression of the form:
        path.to.coding.where(field = 'value')

    Returns (cc_path_parts, filter_field, filter_value).
    cc_path_parts is the path to the CodeableConcept (before '.coding').
    """
    m = re.match(
        r"^(.+?)\.coding\.where\(\s*(\w+)\s*=\s*'([^']+)'\s*\)$", expr
    )
    if m:
        cc_path = m.group(1)
        return cc_path.split("."), m.group(2), m.group(3)

    # Fallback: no .where() clause
    parts = expr.split(".")
    if "coding" in parts:
        idx = parts.index("coding")
        return parts[:idx], None, None
    return parts, None, None


def navigate_to_cc(resource, cc_path_parts):
    """Navigate a resource dict to reach a CodeableConcept element.

    Skips resource type prefix if present at the start of the path.
    Returns the CodeableConcept dict, or None.
    """
    current = resource
    path = list(cc_path_parts)

    # Skip resource type prefix
    if path and path[0] == resource.get("resourceType", ""):
        path = path[1:]

    for part in path:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current if isinstance(current, dict) and "coding" in current else None


def apply_translation(resource, cc_path_parts, filter_field, filter_value,
                      groups, preserve_source):
    """Translate matching Coding elements in a resource's CodeableConcept.

    Returns (modified_resource, list_of_translation_records).
    """
    cc = navigate_to_cc(resource, cc_path_parts)
    if cc is None:
        return resource, []

    codings = cc.get("coding", [])
    if not isinstance(codings, list):
        return resource, []

    new_codings = []
    records = []
    resource_id = resource.get("id", "")
    resource_type = resource.get("resourceType", "")

    for coding in codings:
        # Check whether this coding matches the FHIRPath filter
        if filter_field is not None:
            if coding.get(filter_field) != filter_value:
                # Non-matching coding: always keep as-is
                new_codings.append(coding)
                continue

        source_code = coding.get("code", "")
        source_system = coding.get("system", "")

        # Find the applicable ConceptMap group
        translated = False
        for group in groups:
            if group["source_system"] and group["source_system"] != source_system:
                continue

            element = group["elements"].get(source_code)
            if element:
                # --- Mapped code ---
                if preserve_source:
                    new_codings.append(coding)

                for t in element["targets"]:
                    new_codings.append({
                        "system": group["target_system"],
                        "code": t["code"],
                        "display": t["display"],
                    })
                    records.append({
                        "resource_id": resource_id,
                        "resource_type": resource_type,
                        "source_code": source_code,
                        "source_system": source_system,
                        "target_code": t["code"],
                        "target_system": group["target_system"],
                        "equivalence": t["equivalence"],
                        "mapped": True,
                    })
                translated = True
                break
            else:
                # --- Unmapped code ---
                unmapped_cfg = group.get("unmapped", {})
                mode = unmapped_cfg.get("mode", "provided")

                if mode == "provided":
                    new_codings.append(coding)
                elif mode == "fixed":
                    new_codings.append({
                        "system": group["target_system"],
                        "code": unmapped_cfg.get("code", ""),
                        "display": unmapped_cfg.get("display", ""),
                    })

                records.append({
                    "resource_id": resource_id,
                    "resource_type": resource_type,
                    "source_code": source_code,
                    "source_system": source_system,
                    "mapped": False,
                    "unmapped_mode": mode,
                })
                translated = True
                break

        if not translated:
            # No applicable group found: keep coding as-is
            new_codings.append(coding)

    cc["coding"] = new_codings
    return resource, records


def process_ndjson(input_path, output_path, cc_path_parts, filter_field,
                   filter_value, groups, preserve_source):
    """Process a single NDJSON file, translating coded elements."""
    all_records = []
    resource_count = 0

    with open(input_path) as fin, open(output_path, "w") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            resource = json.loads(line)
            resource, records = apply_translation(
                resource, cc_path_parts, filter_field, filter_value,
                groups, preserve_source,
            )
            all_records.extend(records)
            fout.write(json.dumps(resource, ensure_ascii=False) + "\n")
            resource_count += 1

    return resource_count, all_records


def build_report(total_resources, all_records):
    """Build the structured migration report."""
    mapped_records = [r for r in all_records if r.get("mapped")]
    unmapped_records = [r for r in all_records if not r.get("mapped")]

    return {
        "summary": {
            "resources_processed": total_resources,
            "codes_translated": len(set(
                (r["resource_id"], r["source_code"]) for r in mapped_records
            )),
            "codes_unmapped": len(unmapped_records),
        },
        "translations": [
            {
                "resource_id": r["resource_id"],
                "resource_type": r["resource_type"],
                "source_code": r["source_code"],
                "source_system": r["source_system"],
                "target_code": r["target_code"],
                "target_system": r["target_system"],
                "equivalence": r["equivalence"],
            }
            for r in mapped_records
        ],
        "unmapped_codes": [
            {
                "resource_id": r["resource_id"],
                "resource_type": r["resource_type"],
                "source_code": r["source_code"],
                "source_system": r["source_system"],
                "unmapped_mode": r.get("unmapped_mode", "provided"),
            }
            for r in unmapped_records
        ],
    }


def main():
    config = load_config("/app/migration_config.json")
    concept_maps = load_concept_maps("/app/conceptmaps")

    source_dir = config.get("source_dir", "/app/bulk_export")
    output_dir = config.get("output_dir", "/app/output")
    os.makedirs(output_dir, exist_ok=True)

    total_resources = 0
    all_records = []

    for migration in config["migrations"]:
        cm_id = migration["concept_map_id"]
        cm = concept_maps.get(cm_id)
        if cm is None:
            print(f"WARNING: ConceptMap '{cm_id}' not found, skipping",
                  file=sys.stderr)
            continue

        groups = build_lookup(cm)

        cc_path_parts, filter_field, filter_value = parse_fhirpath_selector(
            migration["fhirpath_selector"]
        )
        preserve_source = migration.get("preserve_source_coding", True)

        source_file = migration["source_file"]
        input_path = os.path.join(source_dir, source_file)
        output_path = os.path.join(output_dir, source_file)

        if not os.path.exists(input_path):
            print(f"WARNING: Input file '{input_path}' not found, skipping",
                  file=sys.stderr)
            continue

        count, records = process_ndjson(
            input_path, output_path, cc_path_parts, filter_field,
            filter_value, groups, preserve_source,
        )
        total_resources += count
        all_records.extend(records)

        print(f"Processed {source_file}: {count} resources, "
              f"{sum(1 for r in records if r.get('mapped'))} translated, "
              f"{sum(1 for r in records if not r.get('mapped'))} unmapped")

    # Generate report
    report = build_report(total_resources, all_records)
    report_path = config.get("report_path", "/app/output/migration_stats.json")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"\nMigration complete:")
    print(f"  Resources processed: {report['summary']['resources_processed']}")
    print(f"  Codes translated: {report['summary']['codes_translated']}")
    print(f"  Codes unmapped: {report['summary']['codes_unmapped']}")
    print(f"  Report written to: {report_path}")


if __name__ == "__main__":
    main()
