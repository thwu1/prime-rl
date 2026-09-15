#!/usr/bin/env python3

"""
Chiptool-style IR transform engine with Sanitize support.

Reads IR JSON and YAML transform config (with tagged-union syntax),
applies transforms in sequence, writes result.
"""

import json
import re
import sys
from copy import deepcopy
import yaml


# ── Rust keywords (for sanitize_ident) ──────────────────────────

RUST_KEYWORDS = {
    "abstract", "as", "async", "await", "become", "box", "break", "const",
    "continue", "crate", "do", "dyn", "else", "enum", "extern", "false",
    "final", "fn", "for", "if", "impl", "in", "let", "loop", "macro",
    "match", "mod", "move", "mut", "override", "priv", "pub", "ref",
    "return", "self", "Self", "static", "struct", "super", "trait", "true",
    "try", "type", "typeof", "unsafe", "unsized", "use", "virtual", "where",
    "while", "yield",
}

INVALID_CHARS = set("()[]/ -")


# ── Case conversion ────────────────────────────────────────────


def split_words(s):
    """Split string into words, with digit boundaries removed (matching
    convert_case with remove_boundaries(&Boundary::digits()))."""
    # Replace delimiter characters with spaces
    result = []
    for ch in s:
        if ch in ('_', '-', ' '):
            result.append(' ')
        elif ch in INVALID_CHARS:
            pass  # strip invalid chars
        else:
            result.append(ch)
    s = ''.join(result)

    # Insert word boundaries at case transitions only (NOT digit transitions)
    # lowercase -> uppercase
    s = re.sub(r'([a-z])([A-Z])', r'\1 \2', s)
    # End of uppercase run before lowercase (e.g. "XMLParser" -> "XML Parser")
    s = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', s)

    return [w for w in s.split() if w]


def to_snake(s):
    """Convert to snake_case."""
    words = split_words(s)
    return '_'.join(w.lower() for w in words)


def to_pascal(s):
    """Convert to PascalCase."""
    words = split_words(s)
    return ''.join(w[0].upper() + w[1:].lower() if len(w) > 1 else w.upper()
                   for w in words)


def to_constant(s):
    """Convert to SCREAMING_SNAKE_CASE."""
    words = split_words(s)
    return '_'.join(w.upper() for w in words)


def sanitize_ident(s):
    """Strip invalid chars and escape Rust keywords."""
    # Invalid chars already stripped in split_words, but handle standalone
    for ch in INVALID_CHARS:
        s = s.replace(ch, '')
    if s in RUST_KEYWORDS:
        return s + '_'
    if s and s[0].isdigit():
        return '_' + s
    return s


def path_snake_pascal(s):
    """PathSnakePascal: split on ::, snake non-last, pascal last."""
    segments = s.split('::')
    result = []
    for i, seg in enumerate(segments):
        if i == len(segments) - 1:
            result.append(sanitize_ident(to_pascal(seg)))
        else:
            result.append(sanitize_ident(to_snake(seg)))
    return '::'.join(result)


def case_snake(s):
    return sanitize_ident(to_snake(s))


def case_pascal(s):
    return sanitize_ident(to_pascal(s))


# ── YAML tag handling ──────────────────────────────────────────


class TransformLoader(yaml.SafeLoader):
    pass


def _tag_constructor(loader, tag_suffix, node):
    """Handle chiptool's tagged-union YAML syntax (!TransformName {fields})."""
    if isinstance(node, yaml.ScalarNode):
        return {"type": tag_suffix}
    mapping = loader.construct_mapping(node, deep=True)
    mapping["type"] = tag_suffix
    return mapping


TransformLoader.add_multi_constructor("!", _tag_constructor)


def load_transforms(path):
    with open(path) as f:
        data = yaml.load(f, Loader=TransformLoader)
    return data["transforms"]


def load_json(path):
    with open(path) as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ── Regex helpers ──────────────────────────────────────────────


def match_expand(s, pattern, replacement):
    """Full-match s against pattern; expand $1, $2, ... in replacement."""
    m = re.match(f"^{pattern}$", s)
    if m is None:
        return None
    result = replacement
    for i, group in enumerate(m.groups(), start=1):
        result = result.replace(f"${i}", group)
    return result


def match_all(keys, pattern):
    """Return all keys that fully match pattern."""
    return [k for k in keys if re.match(f"^{pattern}$", k)]


def match_groups(keys, pattern, to):
    """Group keys by their expanded replacement string."""
    groups = {}
    for k in keys:
        expanded = match_expand(k, pattern, to)
        if expanded is not None:
            groups.setdefault(expanded, set()).add(k)
    return groups


# ── Reference update helpers ───────────────────────────────────


def replace_enum_ids(ir, from_set, to):
    """Update all enum references in fieldset fields."""
    for fs in ir["fieldsets"].values():
        for field in fs["fields"]:
            if field.get("enum") and field["enum"] in from_set:
                field["enum"] = to


def replace_fieldset_ids(ir, from_set, to):
    """Update all fieldset references in register items."""
    for block in ir["blocks"].values():
        for item in block["items"]:
            if item["inner"]["type"] == "register":
                fs = item["inner"].get("fieldset")
                if fs and fs in from_set:
                    item["inner"]["fieldset"] = to


def replace_block_ids(ir, from_set, to):
    """Update all block references in block items."""
    for block in ir["blocks"].values():
        for item in block["items"]:
            if item["inner"]["type"] == "block":
                if item["inner"]["block"] in from_set:
                    item["inner"]["block"] = to


def remove_fieldset_ids(ir, from_set):
    """Clear fieldset references that point to deleted fieldsets."""
    for block in ir["blocks"].values():
        for item in block["items"]:
            if item["inner"]["type"] == "register":
                fs = item["inner"].get("fieldset")
                if fs and fs in from_set:
                    item["inner"]["fieldset"] = None


def remove_enum_ids(ir, from_set):
    """Clear enum references that point to deleted enums."""
    for fs in ir["fieldsets"].values():
        for field in fs["fields"]:
            if field.get("enum") and field["enum"] in from_set:
                field["enum"] = None


# ── Sanitize transform ────────────────────────────────────────


def apply_sanitize(ir, transform):
    """Sanitize all names using per-NameKind case conversion."""
    # Remap block keys and references
    _remap_namespace(ir, "blocks", path_snake_pascal)
    for block in ir["blocks"].values():
        for item in block["items"]:
            if item["inner"]["type"] == "block":
                item["inner"]["block"] = path_snake_pascal(item["inner"]["block"])

    # Remap fieldset keys and references
    _remap_namespace(ir, "fieldsets", path_snake_pascal)
    for block in ir["blocks"].values():
        for item in block["items"]:
            if item["inner"]["type"] == "register":
                if item["inner"].get("fieldset"):
                    item["inner"]["fieldset"] = path_snake_pascal(
                        item["inner"]["fieldset"]
                    )

    # Remap enum keys and references
    _remap_namespace(ir, "enums", path_snake_pascal)
    for fs in ir["fieldsets"].values():
        for field in fs["fields"]:
            if field.get("enum"):
                field["enum"] = path_snake_pascal(field["enum"])

    # Rename block item names (Snake)
    for block in ir["blocks"].values():
        for item in block["items"]:
            item["name"] = case_snake(item["name"])

    # Rename field names (Snake)
    for fs in ir["fieldsets"].values():
        for field in fs["fields"]:
            field["name"] = case_snake(field["name"])

    # Rename enum variant names (Pascal)
    for enum in ir["enums"].values():
        for v in enum["variants"]:
            v["name"] = case_pascal(v["name"])

    # After sanitize: merge duplicate variants and rename collisions
    for enum in ir["enums"].values():
        _merge_duplicate_variants(enum)
        _rename_duplicate_variants(enum)


def _remap_namespace(ir, namespace, converter):
    """Rename all keys in a namespace dict."""
    new_items = {}
    for key, val in ir[namespace].items():
        new_key = converter(key)
        new_items[new_key] = val
    ir[namespace] = new_items


def _merge_duplicate_variants(enum):
    """Merge enum variants with same name AND same value."""
    seen = {}
    new_variants = []
    for v in enum["variants"]:
        key = (v["name"], v["value"])
        if key not in seen:
            seen[key] = v
            new_variants.append(v)
    enum["variants"] = new_variants


def _rename_duplicate_variants(enum):
    """Rename variants with same name but different values."""
    from collections import Counter
    name_counts = Counter(v["name"] for v in enum["variants"])
    for v in enum["variants"]:
        if name_counts[v["name"]] > 1:
            new_name = f"{v['name']}_{v['value']:x}"
            v["name"] = new_name
            name_counts[new_name] = name_counts.get(new_name, 0) + 1


# ── DeleteFieldsets ────────────────────────────────────────────


def _is_useless(fs):
    """A fieldset is useless if it has no fields, or one field covering
    the entire register with no enum."""
    fields = fs["fields"]
    if len(fields) == 0:
        return True
    if len(fields) == 1:
        f = fields[0]
        bit_offset = f["bit_offset"]
        if isinstance(bit_offset, int):
            return (
                fs["bit_size"] == f["bit_size"]
                and bit_offset == 0
                and not f.get("enum")
            )
    return False


def apply_delete_fieldsets(ir, transform):
    """Delete fieldsets matching 'from'; optionally only useless ones."""
    pattern = transform["from"]
    useless = transform.get("useless", False)

    to_delete = set()
    for name, fs in ir["fieldsets"].items():
        if re.match(f"^{pattern}$", name):
            if not useless or _is_useless(fs):
                to_delete.add(name)

    remove_fieldset_ids(ir, to_delete)

    for name in to_delete:
        del ir["fieldsets"][name]


# ── DeleteEnums ────────────────────────────────────────────────


def apply_delete_enums(ir, transform):
    """Delete enums matching 'from'; optionally filter by bit_size."""
    pattern = transform["from"]
    bit_size_filter = transform.get("bit_size")

    to_delete = set()
    for name, enum in ir["enums"].items():
        if re.match(f"^{pattern}$", name):
            if bit_size_filter is None or enum["bit_size"] == bit_size_filter:
                to_delete.add(name)

    remove_enum_ids(ir, to_delete)

    for name in to_delete:
        del ir["enums"][name]


# ── DeleteRegisters ───────────────────────────────────────────


def apply_delete_registers(ir, transform):
    """Delete register items matching 'from' from blocks matching 'block'."""
    block_pattern = transform["block"]
    item_pattern = transform["from"]

    for block_name in match_all(list(ir["blocks"].keys()), block_pattern):
        block = ir["blocks"][block_name]
        block["items"] = [
            item
            for item in block["items"]
            if not re.match(f"^{item_pattern}$", item["name"])
        ]


# ── RenameFields ──────────────────────────────────────────────


def apply_rename_fields(ir, transform):
    """Rename fields within matching fieldsets."""
    fs_pattern = transform["fieldset"]
    from_pattern = transform["from"]
    to_template = transform["to"]

    for fs_name in match_all(list(ir["fieldsets"].keys()), fs_pattern):
        fs = ir["fieldsets"][fs_name]
        for field in fs["fields"]:
            new_name = match_expand(field["name"], from_pattern, to_template)
            if new_name is not None:
                field["name"] = new_name


# ── Rename ────────────────────────────────────────────────────


def apply_rename(ir, transform):
    """Rename keys across all namespaces; update all cross-references."""
    pattern = transform["from"]
    replacement = transform["to"]

    for namespace in ["blocks", "fieldsets", "enums"]:
        rename_map = {}
        new_items = {}

        for key in list(ir[namespace].keys()):
            new_key = match_expand(key, pattern, replacement)
            if new_key is not None:
                rename_map[key] = new_key
                new_items[new_key] = ir[namespace][key]
            else:
                new_items[key] = ir[namespace][key]

        ir[namespace] = new_items

        for old_key, new_key in rename_map.items():
            from_set = {old_key}
            if namespace == "blocks":
                replace_block_ids(ir, from_set, new_key)
            elif namespace == "fieldsets":
                replace_fieldset_ids(ir, from_set, new_key)
            elif namespace == "enums":
                replace_enum_ids(ir, from_set, new_key)


# ── MergeEnums ────────────────────────────────────────────────


def apply_merge_enums(ir, transform):
    """Merge enums matching 'from' into groups determined by 'to' expansion."""
    pattern = transform["from"]
    to_template = transform["to"]

    groups = match_groups(list(ir["enums"].keys()), pattern, to_template)

    for to, group in sorted(groups.items()):
        matched_sorted = sorted(group)
        canonical = deepcopy(ir["enums"][matched_sorted[0]])

        from_set = set(group)
        for name in group:
            del ir["enums"][name]

        ir["enums"][to] = canonical
        replace_enum_ids(ir, from_set, to)


# ── MergeFieldsets ────────────────────────────────────────────


def apply_merge_fieldsets(ir, transform):
    """Merge fieldsets matching 'from' into groups determined by 'to'."""
    pattern = transform["from"]
    to_template = transform["to"]

    groups = match_groups(list(ir["fieldsets"].keys()), pattern, to_template)

    for to, group in sorted(groups.items()):
        matched_sorted = sorted(group)
        # Use 'main' pattern if provided, else first alphabetically
        main_id = matched_sorted[0]
        if "main" in transform:
            for name in matched_sorted:
                if re.match(f"^{transform['main']}$", name):
                    main_id = name
                    break

        canonical = deepcopy(ir["fieldsets"][main_id])

        from_set = set(group)
        for name in group:
            del ir["fieldsets"][name]

        ir["fieldsets"][to] = canonical
        replace_fieldset_ids(ir, from_set, to)


# ── MakeBlock ─────────────────────────────────────────────────


def apply_make_block(ir, transform):
    """Extract register items into nested sub-blocks."""
    block_pattern = transform["blocks"]
    from_pattern = transform["from"]
    to_outer = transform["to_outer"]
    to_inner = transform["to_inner"]
    to_block = transform["to_block"]

    for block_name in match_all(list(ir["blocks"].keys()), block_pattern):
        block = ir["blocks"][block_name]

        # Group items by outer name
        groups = {}
        for item in block["items"]:
            expanded_outer = match_expand(item["name"], from_pattern, to_outer)
            if expanded_outer is not None:
                groups.setdefault(expanded_outer, []).append(item)

        if not groups:
            continue

        # Use first group (alphabetically) to define sub-block structure
        first_group_key = sorted(groups.keys())[0]
        first_group = sorted(
            groups[first_group_key], key=lambda i: i["byte_offset"]
        )
        base_offset = first_group[0]["byte_offset"]

        sub_block_items = []
        for item in first_group:
            new_item = deepcopy(item)
            new_item["name"] = match_expand(item["name"], from_pattern, to_inner)
            new_item["byte_offset"] -= base_offset
            sub_block_items.append(new_item)

        ir["blocks"][to_block] = {"items": sub_block_items}

        # Collect all matched item names
        matched_names = set()
        for items in groups.values():
            for item in items:
                matched_names.add(item["name"])

        # Remove matched items from original block
        block["items"] = [i for i in block["items"] if i["name"] not in matched_names]

        # Add block references for each group
        for group_name in sorted(groups.keys()):
            items = sorted(groups[group_name], key=lambda i: i["byte_offset"])
            base = items[0]["byte_offset"]
            block["items"].append(
                {
                    "name": group_name,
                    "byte_offset": base,
                    "inner": {"type": "block", "block": to_block},
                }
            )


# ── MakeRegisterArray ─────────────────────────────────────────


def apply_make_register_array(ir, transform):
    """Combine matched block items into a single array item."""
    block_pattern = transform["blocks"]
    from_pattern = transform["from"]
    to_name = transform["to"]

    for block_name in match_all(list(ir["blocks"].keys()), block_pattern):
        block = ir["blocks"][block_name]

        # Find matching items
        matched = [
            item
            for item in block["items"]
            if re.match(f"^{from_pattern}$", item["name"])
        ]

        if len(matched) < 2:
            continue

        # Sort by byte offset
        matched.sort(key=lambda i: i["byte_offset"])

        # Calculate stride from uniform spacing
        offsets = [i["byte_offset"] for i in matched]
        stride = offsets[1] - offsets[0]

        # Verify regular spacing
        for idx in range(len(offsets)):
            expected = offsets[0] + idx * stride
            if offsets[idx] != expected:
                raise ValueError(
                    f"Irregular array spacing at index {idx}: "
                    f"expected offset {expected}, got {offsets[idx]}"
                )

        # Create array item from first matched item
        array_item = deepcopy(matched[0])
        array_item["name"] = to_name
        array_item["array"] = {"len": len(matched), "stride": stride}

        # Remove matched items and add array item
        matched_names = {i["name"] for i in matched}
        block["items"] = [
            i for i in block["items"] if i["name"] not in matched_names
        ]
        block["items"].append(array_item)


# ── Transform dispatch ─────────────────────────────────────────

TRANSFORM_HANDLERS = {
    "Sanitize": apply_sanitize,
    "DeleteRegisters": apply_delete_registers,
    "DeleteFieldsets": apply_delete_fieldsets,
    "DeleteEnums": apply_delete_enums,
    "Rename": apply_rename,
    "RenameFields": apply_rename_fields,
    "MergeEnums": apply_merge_enums,
    "MergeFieldsets": apply_merge_fieldsets,
    "MakeBlock": apply_make_block,
    "MakeRegisterArray": apply_make_register_array,
}


def main():
    ir = load_json("/app/ir.json")
    transforms = load_transforms("/app/transforms.yaml")

    for i, transform in enumerate(transforms):
        ttype = transform["type"]
        handler = TRANSFORM_HANDLERS.get(ttype)
        if handler is None:
            print(f"Unknown transform type: {ttype}", file=sys.stderr)
            sys.exit(1)
        handler(ir, transform)

    save_json("/app/output.json", ir)


if __name__ == "__main__":
    main()
