#!/usr/bin/env python3
"""
Terraform State Decomposition Engine

Reads a monolithic Terraform v4 state file and a decomposition specification,
then produces a refactored state organized into modules and HCL moved blocks.

Handles production edge cases: deposed instances, tainted status, depends_on
remapping, and provider alias preservation.
"""

import copy
import json
import re
from collections import defaultdict


def main():
    with open("/app/monolith.tfstate") as f:
        state = json.load(f)

    with open("/app/decomposition_spec.json") as f:
        spec = json.load(f)

    target_structure = spec["target_structure"]
    renames = spec["renames"]
    index_conversions = spec["index_conversions"]

    # Build lookup tables from the specification.
    # Specific resource matches (type.name) take precedence over type-based.
    resource_to_module = {}
    type_to_module = {}

    for module_path, config in target_structure.items():
        if "resources" in config:
            for res_addr in config["resources"]:
                resource_to_module[res_addr] = module_path
        if "resource_types" in config:
            for rtype in config["resource_types"]:
                type_to_module[rtype] = module_path

    def get_target_module(res_type, res_name):
        key = f"{res_type}.{res_name}"
        if key in resource_to_module:
            return resource_to_module[key]
        return type_to_module.get(res_type, "")

    def get_new_name(res_type, res_name):
        key = f"{res_type}.{res_name}"
        return renames.get(key, res_name)

    def convert_index(res_type, res_name, instance):
        key = f"{res_type}.{res_name}"
        if key not in index_conversions:
            return instance.get("index_key")

        conv = index_conversions[key]
        old_key = instance.get("index_key")

        if conv["strategy"] == "count_to_for_each":
            if "key_map" in conv:
                return conv["key_map"][str(old_key)]
            elif "key_from_attribute" in conv:
                return instance["attributes"][conv["key_from_attribute"]]
            elif "key_from_tag" in conv:
                tag_val = instance["attributes"]["tags"][conv["key_from_tag"]]
                m = re.match(conv["key_pattern"], tag_val)
                return m.group(1) if m else tag_val

        return old_key

    # First pass: process all resources, build address remap and instance groups
    target_groups = defaultdict(list)
    target_metadata = {}
    source_to_target = {}
    address_remap = {}
    moved_entries = []

    for res in state["resources"]:
        src_type = res["type"]
        src_name = res["name"]
        src_module = res.get("module", "")

        tgt_module = get_target_module(src_type, src_name)
        new_name = get_new_name(src_type, src_name)

        src_key = (src_module, src_type, src_name)
        tgt_key = (tgt_module, src_type, new_name)
        source_to_target[src_key] = tgt_key

        if tgt_key not in target_metadata:
            target_metadata[tgt_key] = res

        # Build resource-level address remap for depends_on transformation
        if src_module:
            old_addr = f"{src_module}.{src_type}.{src_name}"
        else:
            old_addr = f"{src_type}.{src_name}"
        if tgt_module:
            new_addr = f"{tgt_module}.{src_type}.{new_name}"
        else:
            new_addr = f"{src_type}.{new_name}"
        address_remap[old_addr] = new_addr

        # Process active (non-deposed) instances
        for inst in res["instances"]:
            if "deposed" in inst:
                continue

            old_index = inst.get("index_key")
            new_index = convert_index(src_type, src_name, inst)

            # Deep copy preserves all fields: status (tainted), schema_version,
            # sensitive_attributes, private, etc.
            new_inst = copy.deepcopy(inst)
            if new_index is not None:
                new_inst["index_key"] = new_index
            else:
                new_inst.pop("index_key", None)

            target_groups[tgt_key].append(new_inst)

            moved_entries.append((
                src_module, src_type, src_name, old_index,
                tgt_module, src_type, new_name, new_index,
            ))

    # Second pass: collect deposed instances and attach to their target resources
    for res in state["resources"]:
        src_key = (res.get("module", ""), res["type"], res["name"])
        if src_key in source_to_target:
            tgt_key = source_to_target[src_key]
            for inst in res["instances"]:
                if "deposed" in inst:
                    target_groups[tgt_key].append(copy.deepcopy(inst))

    # Assemble output resources with remapped depends_on
    new_resources = []
    for tgt_key, instances in target_groups.items():
        module, rtype, rname = tgt_key
        source_res = target_metadata[tgt_key]

        new_res = {
            "mode": source_res["mode"],
            "type": rtype,
            "name": rname,
            # Preserve provider string verbatim — this maintains aliases
            "provider": source_res["provider"],
            "instances": instances,
        }
        if module:
            new_res["module"] = module
        if "depends_on" in source_res:
            new_res["depends_on"] = [
                address_remap.get(dep, dep) for dep in source_res["depends_on"]
            ]

        new_resources.append(new_res)

    # Build output state with incremented serial
    new_state = {
        "version": state["version"],
        "terraform_version": state["terraform_version"],
        "serial": state["serial"] + 1,
        "lineage": state["lineage"],
        "outputs": copy.deepcopy(state.get("outputs", {})),
        "resources": new_resources,
    }

    with open("/app/refactored.tfstate", "w") as f:
        json.dump(new_state, f, indent=2)
        f.write("\n")

    # Generate HCL moved blocks (one per active instance)
    def fmt_addr(module, rtype, rname, key):
        parts = [module] if module else []
        parts.append(f"{rtype}.{rname}")
        addr = ".".join(parts)
        if key is not None:
            if isinstance(key, int):
                addr += f"[{key}]"
            else:
                addr += f'["{key}"]'
        return addr

    blocks = []
    for entry in moved_entries:
        f_mod, f_type, f_name, f_key, t_mod, t_type, t_name, t_key = entry
        blocks.append(
            f"moved {{\n"
            f"  from = {fmt_addr(f_mod, f_type, f_name, f_key)}\n"
            f"  to   = {fmt_addr(t_mod, t_type, t_name, t_key)}\n"
            f"}}"
        )

    with open("/app/moved.tf", "w") as f:
        f.write("\n\n".join(blocks))
        f.write("\n")

    total = sum(len(r["instances"]) for r in new_resources)
    print(f"Decomposition: {len(new_resources)} resources, {total} instances, {len(blocks)} moved blocks")


if __name__ == "__main__":
    main()
