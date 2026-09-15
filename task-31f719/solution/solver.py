#!/usr/bin/env python3
"""
Reference solution: Cargo workspace feature audit using TOML parsing.

Parses Cargo.toml files directly with Python's tomllib to build the
complete feature graph (including implicit features and dependency
sub-features), then answers resolve / implicit_features / reverse_deps /
feature_diff / minimal_set queries.

"""

import json
import tomllib
from itertools import combinations
from pathlib import Path


def parse_cargo_workspace(workspace_path):
    """Parse all Cargo.toml files in the workspace to build the feature graph."""
    workspace_path = Path(workspace_path)

    with open(workspace_path / "Cargo.toml", "rb") as f:
        ws_config = tomllib.load(f)

    members = ws_config.get("workspace", {}).get("members", [])

    main_features = {}
    dep_info = {}
    dep_features = {}

    pkg_configs = {}
    for member in members:
        member_path = workspace_path / member
        with open(member_path / "Cargo.toml", "rb") as f:
            pkg_config = tomllib.load(f)
        pkg_name = pkg_config.get("package", {}).get("name", member)
        pkg_configs[pkg_name] = pkg_config

    for pkg_name, pkg_config in pkg_configs.items():
        features = pkg_config.get("features", {})

        if pkg_name == "hyperkernel":
            main_features = {k: list(v) for k, v in features.items()}

            deps = pkg_config.get("dependencies", {})
            for dep_name_raw, dep_spec in deps.items():
                if isinstance(dep_spec, dict) and dep_spec.get("optional", False):
                    dep_info[dep_name_raw] = {
                        "uses_default_features": dep_spec.get(
                            "default-features", True
                        ),
                    }

            # Detect implicit features: optional deps never referenced via dep:
            referenced_via_dep_colon = set()
            for feat_specs in main_features.values():
                for spec in feat_specs:
                    if spec.startswith("dep:"):
                        referenced_via_dep_colon.add(spec[4:])

            for dep_name_raw in dep_info:
                if dep_name_raw not in referenced_via_dep_colon:
                    if dep_name_raw not in main_features:
                        main_features[dep_name_raw] = [f"dep:{dep_name_raw}"]
        else:
            dep_features[pkg_name] = {k: list(v) for k, v in features.items()}

    return main_features, dep_info, dep_features


def _resolve_dep_feats(dep_features, dep_name, feat, active):
    """Resolve transitive features within a dependency crate."""
    if dep_name not in dep_features:
        return
    pkg_feats = dep_features[dep_name]
    if feat not in pkg_feats:
        return
    worklist = list(pkg_feats[feat])
    while worklist:
        sub = worklist.pop()
        if sub in active.get(dep_name, set()):
            continue
        active.setdefault(dep_name, set()).add(sub)
        if sub in pkg_feats:
            worklist.extend(pkg_feats[sub])


def resolve(main_features, dep_info, dep_features, input_features):
    """Resolve a set of hyperkernel features into all transitively enabled items."""
    enabled_features = set()
    enabled_deps = set()
    active_dep_feats = {}

    worklist = list(input_features)

    while worklist:
        item = worklist.pop()
        if item in enabled_features:
            continue
        enabled_features.add(item)

        if item not in main_features:
            continue

        for spec in main_features[item]:
            if spec.startswith("dep:"):
                dep_name = spec[4:]
                if dep_name not in enabled_deps:
                    enabled_deps.add(dep_name)
                    if (
                        dep_name in dep_info
                        and dep_info[dep_name]["uses_default_features"]
                    ):
                        if (
                            dep_name in dep_features
                            and "default" in dep_features[dep_name]
                        ):
                            active_dep_feats.setdefault(dep_name, set()).add(
                                "default"
                            )
                            _resolve_dep_feats(
                                dep_features, dep_name, "default", active_dep_feats
                            )
            elif "?/" in spec:
                dep_name, feat = spec.split("?/", 1)
                if dep_name in enabled_deps:
                    if feat not in active_dep_feats.get(dep_name, set()):
                        active_dep_feats.setdefault(dep_name, set()).add(feat)
                        _resolve_dep_feats(
                            dep_features, dep_name, feat, active_dep_feats
                        )
            elif "/" in spec:
                dep_name, feat = spec.split("/", 1)
                if dep_name not in enabled_deps:
                    enabled_deps.add(dep_name)
                    if (
                        dep_name in dep_info
                        and dep_info[dep_name]["uses_default_features"]
                    ):
                        if (
                            dep_name in dep_features
                            and "default" in dep_features[dep_name]
                        ):
                            active_dep_feats.setdefault(dep_name, set()).add(
                                "default"
                            )
                            _resolve_dep_feats(
                                dep_features, dep_name, "default", active_dep_feats
                            )
                if feat not in active_dep_feats.get(dep_name, set()):
                    active_dep_feats.setdefault(dep_name, set()).add(feat)
                    _resolve_dep_feats(
                        dep_features, dep_name, feat, active_dep_feats
                    )
            else:
                if spec not in enabled_features:
                    worklist.append(spec)

    # Fixed-point iteration for weak conditional dependencies
    changed = True
    while changed:
        changed = False
        for feat in list(enabled_features):
            if feat not in main_features:
                continue
            for spec in main_features[feat]:
                if "?/" in spec:
                    dep_name, feat_name = spec.split("?/", 1)
                    if dep_name in enabled_deps:
                        if feat_name not in active_dep_feats.get(dep_name, set()):
                            active_dep_feats.setdefault(dep_name, set()).add(
                                feat_name
                            )
                            _resolve_dep_feats(
                                dep_features,
                                dep_name,
                                feat_name,
                                active_dep_feats,
                            )
                            changed = True

    result = set()
    result.update(enabled_features)
    result.update(enabled_deps)
    for dn, fs in active_dep_feats.items():
        for f in fs:
            result.add(f"{dn}/{f}")

    return sorted(result)


def get_implicit_features(main_features):
    """Return features auto-generated by Cargo for optional deps not using dep: syntax."""
    implicit = []
    for feat_name, specs in main_features.items():
        if specs == [f"dep:{feat_name}"]:
            implicit.append(feat_name)
    return sorted(implicit)


def reverse_deps_query(main_features, dep_info, dep_features, target):
    """Find all features that transitively enable the target item."""
    all_feats = sorted(main_features.keys())
    result = []
    for feat in all_feats:
        if feat == target:
            continue
        resolved = set(resolve(main_features, dep_info, dep_features, [feat]))
        if target in resolved:
            result.append(feat)
    return sorted(result)


def feature_diff_query(main_features, dep_info, dep_features, features_a, features_b):
    """Compute symmetric difference between two resolved feature sets."""
    resolved_a = set(resolve(main_features, dep_info, dep_features, features_a))
    resolved_b = set(resolve(main_features, dep_info, dep_features, features_b))
    return {
        "only_a": sorted(resolved_a - resolved_b),
        "only_b": sorted(resolved_b - resolved_a),
    }


def minimal_set_query(main_features, dep_info, dep_features, required):
    """Find smallest set of features whose resolution covers all required items."""
    all_feats = sorted(main_features.keys())
    required_set = set(required)

    for size in range(1, len(all_feats) + 1):
        for combo in combinations(all_feats, size):
            resolved = set(
                resolve(main_features, dep_info, dep_features, list(combo))
            )
            if required_set.issubset(resolved):
                return sorted(combo)
    return []


def main():
    main_features, dep_info, dep_features = parse_cargo_workspace("/app/workspace")

    with open("/app/queries.json") as f:
        queries = json.load(f)

    results = []
    for q in queries:
        qid = q["id"]
        qtype = q["type"]

        if qtype == "resolve":
            result = resolve(main_features, dep_info, dep_features, q["features"])
        elif qtype == "implicit_features":
            result = get_implicit_features(main_features)
        elif qtype == "reverse_deps":
            result = reverse_deps_query(
                main_features, dep_info, dep_features, q["feature"]
            )
        elif qtype == "feature_diff":
            result = feature_diff_query(
                main_features,
                dep_info,
                dep_features,
                q["features_a"],
                q["features_b"],
            )
        elif qtype == "minimal_set":
            result = minimal_set_query(
                main_features, dep_info, dep_features, q["required"]
            )
        else:
            result = []

        results.append({"id": qid, "result": result})

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"Wrote {len(results)} results to /app/results.json")


if __name__ == "__main__":
    main()
