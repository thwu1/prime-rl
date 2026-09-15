#!/usr/bin/env python3
"""
Cargo feature resolver.

Implements Cargo's feature unification algorithm including:
- Transitive feature activation
- Optional dependency activation (dep:crate_name)
- Conditional feature forwarding (crate_name?/feature)
- Default features
- Fixed-point resolution (order-independent)
"""

import json
import tomllib


def parse_cargo_toml(path):
    """Parse feature definitions and optional dependencies from a Cargo.toml."""
    with open(path, "rb") as f:
        data = tomllib.load(f)

    features = data.get("features", {})

    optional_deps = set()
    for name, spec in data.get("dependencies", {}).items():
        if isinstance(spec, dict) and spec.get("optional", False):
            optional_deps.add(name)

    return features, optional_deps


def resolve(features_def, optional_deps, requested_features, use_defaults):
    """
    Resolve the complete set of activated features, enabled optional deps,
    and forwarded dep-features using fixed-point iteration.
    """
    active_features = set(requested_features)
    if use_defaults and "default" in features_def:
        active_features.add("default")

    enabled_deps = set()
    dep_features = {}

    changed = True
    while changed:
        changed = False
        for feat in list(active_features):
            if feat not in features_def:
                continue
            for activation in features_def[feat]:
                if activation.startswith("dep:"):
                    dep_name = activation[4:]
                    if dep_name in optional_deps and dep_name not in enabled_deps:
                        enabled_deps.add(dep_name)
                        changed = True
                elif "?/" in activation:
                    idx = activation.index("?/")
                    dep_name = activation[:idx]
                    dep_feat = activation[idx + 2 :]
                    if dep_name in enabled_deps:
                        if dep_name not in dep_features:
                            dep_features[dep_name] = set()
                        if dep_feat not in dep_features[dep_name]:
                            dep_features[dep_name].add(dep_feat)
                            changed = True
                elif "/" in activation:
                    idx = activation.index("/")
                    dep_name = activation[:idx]
                    dep_feat = activation[idx + 1 :]
                    if dep_name in optional_deps and dep_name not in enabled_deps:
                        enabled_deps.add(dep_name)
                        changed = True
                    if dep_name not in dep_features:
                        dep_features[dep_name] = set()
                    if dep_feat not in dep_features[dep_name]:
                        dep_features[dep_name].add(dep_feat)
                        changed = True
                else:
                    if activation not in active_features:
                        active_features.add(activation)
                        changed = True

    result_dep_features = {}
    for dep_name, feats in sorted(dep_features.items()):
        if feats:
            result_dep_features[dep_name] = sorted(feats)

    return {
        "features": sorted(active_features),
        "optional_deps": sorted(enabled_deps),
        "dep_features": result_dep_features,
    }


def main():
    features_def, optional_deps = parse_cargo_toml("/app/project/Cargo.toml")

    with open("/app/queries.json") as f:
        queries = json.load(f)

    results = {}
    for q in queries:
        use_defaults = not q["no_default_features"]
        result = resolve(features_def, optional_deps, q["features"], use_defaults)
        results[q["id"]] = result

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
