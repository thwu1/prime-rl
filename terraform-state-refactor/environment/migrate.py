#!/usr/bin/env python3
"""Terraform state migration tool - refactors monolithic state into modules."""

import copy
import json
import re
from collections import defaultdict


def parse_address(addr):
    """Parse Terraform resource address into components."""
    index_key = None
    m = re.match(r'^(.*)\[(\d+)\]$', addr)
    if m:
        addr = m.group(1)
        index_key = int(m.group(2))
    else:
        m = re.match(r'^(.*)\["([^"]+)"\]$', addr)
        if m:
            addr = m.group(1)
            index_key = m.group(2)

    parts = addr.split('.')
    module_parts = []
    i = 0
    while i < len(parts) - 2:
        if parts[i] == 'module':
            module_parts.append(f"module.{parts[i+1]}")
            i += 2
        else:
            break

    return '.'.join(module_parts), parts[i], parts[i+1], index_key


def format_hcl_address(module_path, rtype, rname, index_key):
    """Format resource address for HCL moved blocks."""
    parts = []
    if module_path:
        parts.append(module_path)
    parts.append(f"{rtype}.{rname}")
    addr = '.'.join(parts)
    if index_key is not None:
        if isinstance(index_key, int):
            addr += f"[{index_key}]"
        else:
            addr += f'["{index_key}"]'
    return addr


def normalize_provider(provider_str):
    """Normalize provider string to canonical form."""
    m = re.match(r'provider\["([^"]+)"\]', provider_str)
    if m:
        return f'provider["{m.group(1)}"]'
    return provider_str


# Fields to transfer when migrating an instance to its new address
INSTANCE_FIELDS = [
    "schema_version", "attributes", "sensitive_attributes",
    "private", "index_key",
]


def migrate_instance(source_inst, target_key):
    """Create a migrated copy of a source instance with updated addressing."""
    new_inst = {}
    for field in INSTANCE_FIELDS:
        if field in source_inst:
            new_inst[field] = copy.deepcopy(source_inst[field])

    if target_key is not None:
        new_inst["index_key"] = target_key
    else:
        new_inst.pop("index_key", None)

    return new_inst


def main():
    with open("/app/monolith.tfstate") as f:
        state = json.load(f)

    with open("/app/migration.json") as f:
        migration = json.load(f)

    target_groups = defaultdict(list)
    target_sources = {}

    for mapping in migration["mappings"]:
        from_mod, from_type, from_name, from_key = parse_address(mapping["from"])
        to_mod, to_type, to_name, to_key = parse_address(mapping["to"])

        # Locate source resource and specific instance
        source_res = None
        source_inst = None
        for res in state["resources"]:
            if (res.get("module", "") == from_mod and
                    res["type"] == from_type and
                    res["name"] == from_name):
                source_res = res
                for inst in res["instances"]:
                    ik = inst.get("index_key")
                    if ik == from_key or (from_key is None and ik is None):
                        source_inst = inst
                        break
                break

        if source_inst is None:
            raise ValueError(f"Cannot locate instance: {mapping['from']}")

        new_inst = migrate_instance(source_inst, to_key)

        tgt = (to_mod, to_type, to_name)
        target_groups[tgt].append(new_inst)
        if tgt not in target_sources:
            target_sources[tgt] = source_res

    # Assemble output resources
    new_resources = []
    for (module, rtype, rname), instances in target_groups.items():
        src = target_sources[(module, rtype, rname)]

        new_res = {
            "mode": src["mode"],
            "type": rtype,
            "name": rname,
            "provider": normalize_provider(src["provider"]),
            "instances": instances,
        }
        if module:
            new_res["module"] = module

        # Carry forward dependency declarations
        if "depends_on" in src:
            new_res["depends_on"] = list(src["depends_on"])

        new_resources.append(new_res)

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

    # Generate HCL moved blocks
    blocks = []
    for mapping in migration["mappings"]:
        fp = parse_address(mapping["from"])
        tp = parse_address(mapping["to"])
        blocks.append(
            f'moved {{\n  from = {format_hcl_address(*fp)}\n'
            f'  to   = {format_hcl_address(*tp)}\n}}'
        )

    with open("/app/moved.tf", "w") as f:
        f.write("\n\n".join(blocks))
        f.write("\n")

    total_instances = sum(len(r["instances"]) for r in new_resources)
    print(f"Migration complete:")
    print(f"  {len(new_resources)} resources with {total_instances} instances")
    print(f"  {len(blocks)} moved blocks")
    print(f"  Serial: {state['serial']} -> {new_state['serial']}")


if __name__ == "__main__":
    main()
