#!/usr/bin/env python3
"""
Semver violation detector for Rust crates via rustdoc JSON analysis.

Reads baseline.json and current.json (unstable rustdoc-json format),
compares public API surfaces, and reports semantic versioning violations.

"""

import json
import re


# ── JSON helpers ──────────────────────────────────────────────────────────


def load(path):
    with open(path) as f:
        return json.load(f)


def inner_of(item):
    """Return (raw_key, data) from item['inner'], or (None, None)."""
    inner = item.get("inner")
    if not inner or not isinstance(inner, dict):
        return None, None
    key = next(iter(inner))
    return key, inner[key]


def norm_kind(s):
    """Normalize 'StructField' -> 'struct_field', 'function' -> 'function'."""
    if s is None:
        return None
    return re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", s).lower()


def is_public(item):
    v = item.get("visibility")
    if isinstance(v, str):
        return v == "public"
    if isinstance(v, dict):
        return "public" in str(v).lower()
    return False


def attr_strings(item):
    return [str(a) for a in item.get("attrs", [])]


def has_non_exhaustive(item):
    return any("non_exhaustive" in a for a in attr_strings(item))


def has_repr_c(item):
    return any("repr" in a and "C" in a for a in attr_strings(item))


# ── Build path map ────────────────────────────────────────────────────────


def build_path_map(doc):
    """Map 'crate::item' -> {item, kind} for all public, local items."""
    index = doc.get("index", {})
    result = {}
    for item_id, path_info in doc.get("paths", {}).items():
        if path_info.get("crate_id", 0) != 0:
            continue
        item = index.get(item_id) or index.get(str(item_id))
        if item is None or not is_public(item):
            continue
        path_str = "::".join(path_info["path"])
        raw_kind = path_info.get("kind", "")
        kind = raw_kind.lower() if isinstance(raw_kind, str) else str(raw_kind).lower()
        result[path_str] = {"item": item, "kind": kind}
    return result


# ── Struct field analysis ─────────────────────────────────────────────────


def struct_fields(doc, struct_item):
    """Return (list_of_public_field_names, has_private_fields)."""
    index = doc["index"]
    _, data = inner_of(struct_item)
    if data is None:
        return [], False

    kind_data = data.get("kind", {})
    field_ids = []
    has_stripped = False

    if isinstance(kind_data, dict):
        for _key, val in kind_data.items():
            if isinstance(val, dict):
                field_ids = val.get("fields", [])
                has_stripped = val.get(
                    "has_stripped_fields", val.get("fields_stripped", False)
                )
                break
            elif isinstance(val, list):
                # Some formats store fields directly as a list
                field_ids = val
                break

    pub_names = []
    has_private = has_stripped
    for fid in field_ids:
        fi = index.get(fid) or index.get(str(fid))
        if fi is None:
            has_private = True
            continue
        if is_public(fi):
            pub_names.append(fi.get("name", ""))
        else:
            has_private = True

    return pub_names, has_private


# ── Enum variant analysis ────────────────────────────────────────────────


def enum_variant_names(doc, enum_item):
    index = doc["index"]
    _, data = inner_of(enum_item)
    if data is None:
        return []
    names = []
    for vid in data.get("variants", []):
        vi = index.get(vid) or index.get(str(vid))
        if vi:
            names.append(vi.get("name", ""))
    return names


# ── Trait method analysis ────────────────────────────────────────────────


def trait_methods(doc, trait_item):
    """Return list of {'name': str, 'has_body': bool}."""
    index = doc["index"]
    _, data = inner_of(trait_item)
    if data is None:
        return []
    result = []
    for mid in data.get("items", []):
        mi = index.get(mid) or index.get(str(mid))
        if mi is None:
            continue
        mk, md = inner_of(mi)
        nk = norm_kind(mk)
        if nk and ("function" in nk or "method" in nk):
            has_body = md.get("has_body", False) if md else False
            result.append({"name": mi.get("name", ""), "has_body": has_body})
    return result


# ── Function parameter count ─────────────────────────────────────────────


def func_param_count(item):
    _, data = inner_of(item)
    if data is None:
        return 0
    sig = data.get("sig", data.get("decl", {}))
    if isinstance(sig, dict):
        return len(sig.get("inputs", []))
    return 0


# ── Main analysis ────────────────────────────────────────────────────────


def analyze(baseline_path, current_path):
    baseline = load(baseline_path)
    current = load(current_path)

    bmap = build_path_map(baseline)
    cmap = build_path_map(current)

    violations = []

    for path, info in bmap.items():
        kind = info["kind"]
        item = info["item"]

        # ── Functions ────────────────────────────────────────────────
        if kind == "function":
            if path not in cmap or cmap[path]["kind"] != "function":
                violations.append({"type": "function_missing", "path": path})
            else:
                if func_param_count(item) != func_param_count(cmap[path]["item"]):
                    violations.append(
                        {"type": "function_parameter_count_changed", "path": path}
                    )

        # ── Structs ──────────────────────────────────────────────────
        elif kind == "struct":
            if path not in cmap or cmap[path]["kind"] != "struct":
                # struct_missing not in our target categories; skip
                continue
            new_item = cmap[path]["item"]

            # repr(C) removed?
            if has_repr_c(item) and not has_repr_c(new_item):
                violations.append({"type": "repr_c_removed", "path": path})

            old_fields, old_private = struct_fields(baseline, item)
            new_fields, new_private = struct_fields(current, new_item)

            # Public field removed?
            if set(old_fields) - set(new_fields):
                violations.append({"type": "struct_pub_field_missing", "path": path})

            # Constructible struct adds field?
            if not has_non_exhaustive(item) and not old_private:
                added = set(new_fields) - set(old_fields)
                if added and not has_non_exhaustive(new_item):
                    violations.append(
                        {"type": "constructible_struct_adds_field", "path": path}
                    )

        # ── Enums ────────────────────────────────────────────────────
        elif kind == "enum":
            if path in cmap and cmap[path]["kind"] == "enum":
                old_v = enum_variant_names(baseline, item)
                new_v = enum_variant_names(current, cmap[path]["item"])
                if set(old_v) - set(new_v):
                    violations.append({"type": "enum_variant_missing", "path": path})

        # ── Traits ───────────────────────────────────────────────────
        elif kind == "trait":
            if path in cmap and cmap[path]["kind"] == "trait":
                old_names = {m["name"] for m in trait_methods(baseline, item)}
                for m in trait_methods(current, cmap[path]["item"]):
                    if m["name"] not in old_names and not m["has_body"]:
                        violations.append(
                            {"type": "trait_method_added", "path": path}
                        )
                        break  # one per trait is enough

        # ── Constants ────────────────────────────────────────────────
        elif kind == "constant":
            if path not in cmap:
                violations.append(
                    {"type": "pub_module_level_const_missing", "path": path}
                )

    violations.sort(key=lambda v: (v["type"], v["path"]))
    return violations


def main():
    violations = analyze("/app/baseline.json", "/app/current.json")
    report = {"violations": violations}
    with open("/app/report.json", "w") as f:
        json.dump(report, f, indent=2)
    print(f"Detected {len(violations)} semver violation(s):")
    for v in violations:
        print(f"  [{v['type']}] {v['path']}")


if __name__ == "__main__":
    main()
