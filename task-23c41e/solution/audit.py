#!/usr/bin/env python3
"""
Cargo workspace feature auditor.

Parses all Cargo.toml files in a multi-crate workspace and computes:
1. Cross-crate feature closures (with sub-crate internal chains)
2. Minimum single-feature activators for dep-feature targets
3. Conditional forwarding analysis
4. Feature dominance pairs
"""

import json
import tomllib
from pathlib import Path


def parse_workspace(workspace_path):
    """Parse the workspace root and all member Cargo.toml files."""
    root_toml = workspace_path / "Cargo.toml"
    with open(root_toml, "rb") as f:
        root = tomllib.load(f)

    members = {}
    for member in root["workspace"]["members"]:
        member_toml = workspace_path / member / "Cargo.toml"
        with open(member_toml, "rb") as f:
            data = tomllib.load(f)
        members[member] = data

    return root, members


def resolve_subcrate_features(features_def, activated):
    """Resolve features within a single sub-crate using fixed-point iteration."""
    active = set(activated)
    changed = True
    while changed:
        changed = False
        for feat in list(active):
            if feat in features_def:
                for dep in features_def[feat]:
                    if dep not in active:
                        active.add(dep)
                        changed = True
    return sorted(active)


def resolve_cross_crate(kernel_features, kernel_optional_deps, subcrate_features,
                         requested, use_defaults):
    """
    Full cross-crate feature resolution with fixed-point iteration.

    Handles: dep:crate, crate?/feat conditionals, plain feature activation,
    and unconditional crate/feat forwarding.
    """
    active_features = set(requested)
    if use_defaults and "default" in kernel_features:
        active_features.add("default")

    enabled_deps = set()
    dep_features = {}

    changed = True
    while changed:
        changed = False
        for feat in list(active_features):
            if feat not in kernel_features:
                continue
            for activation in kernel_features[feat]:
                if activation.startswith("dep:"):
                    dep_name = activation[4:]
                    if dep_name in kernel_optional_deps and dep_name not in enabled_deps:
                        enabled_deps.add(dep_name)
                        changed = True
                elif "?/" in activation:
                    idx = activation.index("?/")
                    dep_name = activation[:idx]
                    dep_feat = activation[idx + 2:]
                    if dep_name in enabled_deps:
                        if dep_name not in dep_features:
                            dep_features[dep_name] = set()
                        if dep_feat not in dep_features[dep_name]:
                            dep_features[dep_name].add(dep_feat)
                            changed = True
                elif "/" in activation:
                    idx = activation.index("/")
                    dep_name = activation[:idx]
                    dep_feat = activation[idx + 1:]
                    if dep_name in kernel_optional_deps and dep_name not in enabled_deps:
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

    # Resolve sub-crate internal feature chains
    resolved_deps = {}
    for dep_name in sorted(enabled_deps):
        forwarded = dep_features.get(dep_name, set())
        if dep_name in subcrate_features:
            resolved = resolve_subcrate_features(subcrate_features[dep_name], forwarded)
        else:
            resolved = sorted(forwarded)
        resolved_deps[dep_name] = resolved

    return {
        "root_features": sorted(active_features),
        "resolved_deps": resolved_deps,
    }


def main():
    workspace = Path("/app/workspace")
    _, members = parse_workspace(workspace)

    # Extract kernel info
    kernel_data = members["kernel"]
    kernel_features = kernel_data.get("features", {})
    kernel_optional_deps = set()
    for name, spec in kernel_data.get("dependencies", {}).items():
        if isinstance(spec, dict) and spec.get("optional", False):
            kernel_optional_deps.add(name)

    # Extract sub-crate feature definitions keyed by package name
    subcrate_features = {}
    for member_dir, data in members.items():
        if member_dir == "kernel":
            continue
        pkg_name = data["package"]["name"]
        subcrate_features[pkg_name] = data.get("features", {})

    # ── 1. Cross-crate closures ──
    with open("/app/queries.json") as f:
        queries = json.load(f)

    closures = {}
    for q in queries:
        use_defaults = not q["no_default_features"]
        result = resolve_cross_crate(
            kernel_features, kernel_optional_deps, subcrate_features,
            q["features"], use_defaults,
        )
        closures[q["id"]] = result

    # ── 2. Minimum activators ──
    with open("/app/targets.json") as f:
        targets = json.load(f)

    all_root_features = sorted(kernel_features.keys())
    min_activators = {}
    for t in targets:
        target_dep = t["dep"]
        target_feat = t["feature"]
        best = None
        for feat in all_root_features:
            result = resolve_cross_crate(
                kernel_features, kernel_optional_deps, subcrate_features,
                [feat], False,
            )
            if target_dep in result["resolved_deps"]:
                if target_feat in result["resolved_deps"][target_dep]:
                    best = feat
                    break  # sorted order → first match is lexicographically smallest
        min_activators[t["id"]] = best

    # ── 3. Conditional analysis ──
    conditionals = []
    for feat_name in sorted(kernel_features.keys()):
        activations = kernel_features[feat_name]
        for activation in sorted(activations):
            if "?/" not in activation:
                continue
            idx = activation.index("?/")
            dep_name = activation[:idx]

            # Check always_fires: does enabling feat_name alone enable the target dep?
            solo = resolve_cross_crate(
                kernel_features, kernel_optional_deps, subcrate_features,
                [feat_name], False,
            )
            always_fires = dep_name in solo["resolved_deps"]

            # Find trigger features: which root features individually enable the target dep?
            triggers = []
            for rf in all_root_features:
                result = resolve_cross_crate(
                    kernel_features, kernel_optional_deps, subcrate_features,
                    [rf], False,
                )
                if dep_name in result["resolved_deps"]:
                    triggers.append(rf)

            conditionals.append({
                "expression": activation,
                "parent_feature": feat_name,
                "always_fires": always_fires,
                "trigger_features": sorted(triggers),
            })

    # ── 4. Dominance pairs ──
    internal = {"net", "virtio"}
    deprecated = {"console", "fs", "fuse", "mmap", "trace", "vsock"}
    excluded = internal | deprecated | {"default"}
    eligible = sorted(f for f in kernel_features if f not in excluded)

    closure_cache = {}
    for feat in eligible:
        result = resolve_cross_crate(
            kernel_features, kernel_optional_deps, subcrate_features,
            [feat], False,
        )
        closure_cache[feat] = set(result["root_features"])

    dominance = []
    for a in eligible:
        for b in eligible:
            if a != b and b in closure_cache[a]:
                dominance.append([a, b])
    dominance.sort()

    # ── Write output ──
    audit = {
        "cross_crate_closures": closures,
        "minimum_activators": min_activators,
        "conditional_analysis": conditionals,
        "dominance_pairs": dominance,
    }

    with open("/app/audit.json", "w") as f:
        json.dump(audit, f, indent=2)


if __name__ == "__main__":
    main()
