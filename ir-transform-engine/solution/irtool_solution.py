#!/usr/bin/env python3
"""
Chiptool IR transform engine.
Parses chiptool-format IR YAML, applies a sequence of transforms,
outputs transformed IR, a flat register address map, and a C header.
"""

import copy
import csv
import re
import sys
from collections import OrderedDict

import yaml


# ---------------------------------------------------------------------------
# IR data structure
# ---------------------------------------------------------------------------

class IR:
    def __init__(self):
        self.blocks = OrderedDict()
        self.fieldsets = OrderedDict()
        self.enums = OrderedDict()

    @classmethod
    def from_yaml(cls, path):
        ir = cls()
        with open(path) as f:
            data = yaml.safe_load(f)
        for key, val in data.items():
            if key.startswith("block/"):
                ir.blocks[key[6:]] = val
            elif key.startswith("fieldset/"):
                ir.fieldsets[key[9:]] = val
            elif key.startswith("enum/"):
                ir.enums[key[5:]] = val
        return ir

    def to_yaml(self, path):
        data = OrderedDict()
        for name in sorted(self.blocks.keys()):
            data[f"block/{name}"] = self.blocks[name]
        for name in sorted(self.fieldsets.keys()):
            data[f"fieldset/{name}"] = self.fieldsets[name]
        for name in sorted(self.enums.keys()):
            data[f"enum/{name}"] = self.enums[name]
        with open(path, "w") as f:
            yaml.dump(dict(data), f, default_flow_style=False, sort_keys=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def to_python_repl(s):
    """Convert $N capture-group references to \\N for re.sub."""
    return re.sub(r"\$(\d+)", lambda m: "\\" + m.group(1), s)


# ---------------------------------------------------------------------------
# Transforms
# ---------------------------------------------------------------------------

def apply_rename(ir, params):
    pattern = re.compile("^" + params["from"] + "$")
    repl = to_python_repl(params["to"])

    def rename(path):
        return pattern.sub(repl, path)

    new_blocks = OrderedDict()
    for name, block in ir.blocks.items():
        for item in block.get("items", []):
            if "fieldset" in item and item["fieldset"] is not None:
                item["fieldset"] = rename(item["fieldset"])
            if "block" in item and item["block"] is not None:
                item["block"] = rename(item["block"])
        if "extends" in block and block["extends"] is not None:
            block["extends"] = rename(block["extends"])
        new_blocks[rename(name)] = block
    ir.blocks = new_blocks

    new_fieldsets = OrderedDict()
    for name, fs in ir.fieldsets.items():
        for field in fs.get("fields", []):
            if "enum" in field and field["enum"] is not None:
                field["enum"] = rename(field["enum"])
        if "extends" in fs and fs["extends"] is not None:
            fs["extends"] = rename(fs["extends"])
        new_fieldsets[rename(name)] = fs
    ir.fieldsets = new_fieldsets

    ir.enums = OrderedDict(
        (rename(name), e) for name, e in ir.enums.items()
    )


def apply_merge_fieldsets(ir, params):
    pattern = re.compile("^" + params["from"] + "$")
    target = params["to"]

    matching = [(n, fs) for n, fs in ir.fieldsets.items() if pattern.match(n)]
    if not matching:
        return

    merged = copy.deepcopy(matching[0][1])
    old_names = {n for n, _ in matching}

    for name in old_names:
        del ir.fieldsets[name]
    ir.fieldsets[target] = merged

    for block in ir.blocks.values():
        for item in block.get("items", []):
            if item.get("fieldset") in old_names:
                item["fieldset"] = target


def apply_merge_enums(ir, params):
    pattern = re.compile("^" + params["from"] + "$")
    target = params["to"]

    matching = [(n, e) for n, e in ir.enums.items() if pattern.match(n)]
    if not matching:
        return

    merged = copy.deepcopy(matching[0][1])
    old_names = {n for n, _ in matching}

    for name in old_names:
        del ir.enums[name]
    ir.enums[target] = merged

    for fs in ir.fieldsets.values():
        for field in fs.get("fields", []):
            if field.get("enum") in old_names:
                field["enum"] = target


def apply_make_block(ir, params):
    block_pat = re.compile("^" + params["blocks"] + "$")
    from_pat = re.compile("^" + params["from"] + "$")
    to_block = params["to_block"]
    to_outer_repl = to_python_repl(params["to_outer"])
    to_inner_repl = to_python_repl(params["to_inner"])

    for bname, block in list(ir.blocks.items()):
        if not block_pat.match(bname):
            continue

        groups = OrderedDict()  # outer_name -> [(inner_name, item)]
        keep = []

        for item in block.get("items", []):
            m = from_pat.match(item["name"])
            if m:
                outer = from_pat.sub(to_outer_repl, item["name"])
                inner = from_pat.sub(to_inner_repl, item["name"])
                groups.setdefault(outer, []).append((inner, item))
            else:
                keep.append(item)

        if not groups:
            continue

        # Build the new inner block from the group with the lowest base offset
        first_outer = min(
            groups,
            key=lambda o: min(it["byte_offset"] for _, it in groups[o]),
        )
        first_items = groups[first_outer]
        base = min(it["byte_offset"] for _, it in first_items)

        inner_items = []
        for inner_name, item in first_items:
            new_item = copy.deepcopy(item)
            new_item["name"] = inner_name
            new_item["byte_offset"] -= base
            inner_items.append(new_item)
        inner_items.sort(key=lambda x: x["byte_offset"])

        ir.blocks[to_block] = {"items": inner_items}

        # Replace matched items with outer block references
        for outer in sorted(groups, key=lambda o: min(it["byte_offset"] for _, it in groups[o])):
            items = groups[outer]
            group_base = min(it["byte_offset"] for _, it in items)
            keep.append({
                "name": outer,
                "byte_offset": group_base,
                "block": to_block,
            })

        keep.sort(key=lambda x: x["byte_offset"])
        block["items"] = keep


def apply_make_register_array(ir, params):
    block_pat = re.compile("^" + params["blocks"] + "$")
    from_pat = re.compile("^" + params["from"] + "$")
    to_repl = to_python_repl(params["to"])

    for bname, block in ir.blocks.items():
        if not block_pat.match(bname):
            continue

        matching = []
        non_matching = []
        for item in block.get("items", []):
            if from_pat.match(item["name"]):
                matching.append(item)
            else:
                non_matching.append(item)

        if len(matching) < 2:
            continue

        matching.sort(key=lambda x: x["byte_offset"])
        stride = matching[1]["byte_offset"] - matching[0]["byte_offset"]

        arr_item = copy.deepcopy(matching[0])
        arr_item["name"] = from_pat.sub(to_repl, matching[0]["name"])
        arr_item["array"] = {"len": len(matching), "stride": stride}

        block["items"] = non_matching + [arr_item]
        block["items"].sort(key=lambda x: x["byte_offset"])


def apply_make_field_array(ir, params):
    fs_pat = re.compile("^" + params["fieldsets"] + "$")
    from_pat = re.compile("^" + params["from"] + "$")
    to_repl = to_python_repl(params["to"])

    for fsname, fs in ir.fieldsets.items():
        if not fs_pat.match(fsname):
            continue

        groups = OrderedDict()
        keep = []
        for field in fs.get("fields", []):
            m = from_pat.match(field["name"])
            if m:
                target = from_pat.sub(to_repl, field["name"])
                groups.setdefault(target, []).append(field)
            else:
                keep.append(field)

        for target_name, fields in sorted(groups.items()):
            fields.sort(key=lambda f: f["bit_offset"])
            if len(fields) > 1:
                stride = fields[1]["bit_offset"] - fields[0]["bit_offset"]
            else:
                stride = 1

            arr_field = copy.deepcopy(fields[0])
            arr_field["name"] = target_name
            arr_field["array"] = {"len": len(fields), "stride": stride}
            keep.append(arr_field)

        fs["fields"] = sorted(keep, key=lambda f: f["bit_offset"])


# ---------------------------------------------------------------------------
# Address-map generation
# ---------------------------------------------------------------------------

def generate_addrmap(ir, path):
    # Find root blocks (not referenced as sub-blocks by any other block)
    referenced = set()
    for block in ir.blocks.values():
        for item in block.get("items", []):
            if "block" in item:
                referenced.add(item["block"])

    roots = sorted(n for n in ir.blocks if n not in referenced)

    rows = []
    for root in roots:
        _traverse(ir, root, root, 0, rows)

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["path", "address", "access", "bit_size"]
        )
        writer.writeheader()
        writer.writerows(rows)


def _traverse(ir, block_name, path_prefix, base, rows):
    block = ir.blocks[block_name]
    for item in block.get("items", []):
        if "array" in item:
            arr = item["array"]
            for i in range(arr["len"]):
                addr = base + item["byte_offset"] + i * arr["stride"]
                p = f"{path_prefix}.{item['name']}[{i}]"
                if "block" in item:
                    _traverse(ir, item["block"], p, addr, rows)
                else:
                    rows.append({
                        "path": p,
                        "address": addr,
                        "access": item.get("access", "ReadWrite"),
                        "bit_size": item.get("bit_size", 32),
                    })
        else:
            addr = base + item["byte_offset"]
            p = f"{path_prefix}.{item['name']}"
            if "block" in item:
                _traverse(ir, item["block"], p, addr, rows)
            else:
                rows.append({
                    "path": p,
                    "address": addr,
                    "access": item.get("access", "ReadWrite"),
                    "bit_size": item.get("bit_size", 32),
                })


# ---------------------------------------------------------------------------
# C header generation
# ---------------------------------------------------------------------------

def generate_header(ir, path):
    """Generate a C header with register access macros."""
    lines = []
    lines.append("/* Auto-generated chiptool register definitions */")
    lines.append("#ifndef REGISTERS_H")
    lines.append("#define REGISTERS_H")
    lines.append("")
    lines.append("#include <stdint.h>")
    lines.append("")

    # Find root blocks (not referenced as sub-blocks)
    referenced = set()
    for block in ir.blocks.values():
        for item in block.get("items", []):
            if item.get("block"):
                referenced.add(item["block"])

    roots = sorted(n for n in ir.blocks if n not in referenced)

    for root in roots:
        prefix = root.split("::")[-1].upper()
        lines.append(f"/* Block: {root} */")
        _gen_block_macros(ir, root, prefix, lines)

    lines.append("")
    lines.append("#endif /* REGISTERS_H */")
    lines.append("")

    with open(path, "w") as f:
        f.write("\n".join(lines))


def _gen_block_macros(ir, block_name, prefix, lines):
    """Recursively generate offset/field macros for a block."""
    block = ir.blocks[block_name]

    for item in block.get("items", []):
        name_upper = item["name"].upper()
        item_prefix = f"{prefix}_{name_upper}"
        offset = item["byte_offset"]

        lines.append(f"#define {item_prefix}_OFFSET 0x{offset:x}")

        if "array" in item:
            arr = item["array"]
            lines.append(f"#define {item_prefix}_STRIDE 0x{arr['stride']:x}")
            lines.append(f"#define {item_prefix}_LEN {arr['len']}")

        # Sub-block reference: recurse
        if item.get("block"):
            _gen_block_macros(ir, item["block"], item_prefix, lines)

        # Register with fieldset: emit field macros
        if item.get("fieldset"):
            fs_name = item["fieldset"]
            if fs_name in ir.fieldsets:
                _gen_field_macros(ir.fieldsets[fs_name], item_prefix, lines)

        lines.append("")


def _gen_field_macros(fieldset, prefix, lines):
    """Generate shift/mask macros for each field in a fieldset."""
    for field in fieldset.get("fields", []):
        fname = field["name"].upper()
        shift = field["bit_offset"]
        width = field["bit_size"]
        mask = ((1 << width) - 1) << shift

        mask_str = f"0x{mask:x}"
        if mask >= 0x80000000:
            mask_str += "u"

        lines.append(f"#define {prefix}_{fname}_SHIFT {shift}")
        lines.append(f"#define {prefix}_{fname}_MASK {mask_str}")

        if field.get("array"):
            farr = field["array"]
            lines.append(f"#define {prefix}_{fname}_STRIDE {farr['stride']}")
            lines.append(f"#define {prefix}_{fname}_LEN {farr['len']}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

TRANSFORM_DISPATCH = {
    "Rename": apply_rename,
    "MergeFieldsets": apply_merge_fieldsets,
    "MergeEnums": apply_merge_enums,
    "MakeBlock": apply_make_block,
    "MakeRegisterArray": apply_make_register_array,
    "MakeFieldArray": apply_make_field_array,
}


def main():
    ir = IR.from_yaml("/app/peripheral.yaml")

    with open("/app/transforms.yaml") as f:
        config = yaml.safe_load(f)

    for transform in config.get("transforms", []):
        for ttype, params in transform.items():
            handler = TRANSFORM_DISPATCH.get(ttype)
            if handler is None:
                print(f"Unknown transform: {ttype}", file=sys.stderr)
                sys.exit(1)
            handler(ir, params)

    ir.to_yaml("/app/output.yaml")
    generate_addrmap(ir, "/app/addrmap.csv")
    generate_header(ir, "/app/registers.h")


if __name__ == "__main__":
    main()
