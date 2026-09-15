#!/usr/bin/env python3
"""
Fixed Cargo feature resolver with trace and impact commands.

Reads feature definitions and optional dependency metadata from cargo metadata JSON.
Implements fixpoint-based resolution for weak dependencies, activation chain tracing,
and single-feature impact analysis with exclusive dependency detection.
"""
import sys
import json


def load_metadata(path="/app/metadata.json"):
    """Load feature definitions and optional dep defaults from cargo metadata."""
    with open(path) as f:
        data = json.load(f)
    # Find root/local package (source is null for path dependencies)
    pkg = None
    for p in data["packages"]:
        if p.get("source") is None:
            pkg = p
            break
    if pkg is None:
        pkg = data["packages"][0]
    features = pkg["features"]
    # BUG 1 FIX: use "features" field (explicit feature list from Cargo.toml),
    # not "default_features" (which doesn't exist in cargo metadata deps)
    dep_defaults = {}
    for dep in pkg.get("dependencies", []):
        if dep.get("optional", False):
            dep_defaults[dep["name"]] = dep.get("features", [])
    return features, dep_defaults


def parse_entry(entry):
    """Parse a feature dependency entry into a typed tuple."""
    if entry.startswith("dep:"):
        return ("activate_dep", entry[4:])
    if "?/" in entry:
        dep, feat = entry.split("?/", 1)
        return ("weak_dep_feature", dep, feat)
    if "/" in entry:
        dep, feat = entry.split("/", 1)
        return ("strong_dep_feature", dep, feat)
    return ("feature", entry)


def resolve(features_def, dep_defaults, initial_features, track_weak=False):
    """Resolve features with fixpoint iteration for weak dependencies.

    BUG 2 FIX: Use separate 'enabled' set for features only (not a shared
    'seen' set for both features and deps). This prevents name collisions
    where a feature and dep share the same name (e.g., 'virtio').

    BUG 3 FIX: Wrap resolution in an outer fixpoint loop so that weak
    dependency entries are re-evaluated after each phase-1 pass. Without
    this, weak deps that become satisfiable mid-resolution are missed.
    """
    enabled = set()
    active_deps = {}
    queue = list(initial_features)
    weak_fired = []

    changed = True
    while changed:
        changed = False

        # Phase 1: process feature queue (strong deps only)
        while queue:
            feat = queue.pop(0)
            if feat in enabled:
                continue
            if feat not in features_def:
                print(f"Error: unknown feature '{feat}'", file=sys.stderr)
                sys.exit(1)
            enabled.add(feat)
            changed = True

            for entry in features_def[feat]:
                kind = parse_entry(entry)

                if kind[0] == "feature":
                    if kind[1] not in enabled:
                        queue.append(kind[1])

                elif kind[0] == "activate_dep":
                    dep_name = kind[1]
                    if dep_name not in active_deps:
                        defaults = list(dep_defaults.get(dep_name, []))
                        active_deps[dep_name] = set(defaults)
                        changed = True

                elif kind[0] == "strong_dep_feature":
                    dep_name, feat_name = kind[1], kind[2]
                    if dep_name not in active_deps:
                        defaults = list(dep_defaults.get(dep_name, []))
                        active_deps[dep_name] = set(defaults)
                        changed = True
                    if feat_name not in active_deps[dep_name]:
                        active_deps[dep_name].add(feat_name)
                        changed = True

                # weak_dep_feature: deferred to phase 2

        # Phase 2: evaluate weak deps for all enabled features
        for feat in sorted(enabled):
            for entry in features_def[feat]:
                kind = parse_entry(entry)
                if kind[0] == "weak_dep_feature":
                    dep_name, feat_name = kind[1], kind[2]
                    if dep_name in active_deps and feat_name not in active_deps[dep_name]:
                        active_deps[dep_name].add(feat_name)
                        changed = True
                        if track_weak:
                            weak_fired.append({
                                "source_feature": feat,
                                "dep": dep_name,
                                "dep_feature": feat_name,
                            })

    result = {
        "enabled_features": sorted(enabled),
        "activated_deps": {
            k: sorted(v) for k, v in sorted(active_deps.items())
        },
    }

    if track_weak:
        weak_fired.sort(key=lambda x: (x["source_feature"], x["dep"], x["dep_feature"]))
        return result, weak_fired
    return result


def trace_dep(features_def, dep_defaults, initial_features, target_dep):
    """Trace activation chain for a specific optional dependency."""
    result = resolve(features_def, dep_defaults, initial_features)
    activated = target_dep in result["activated_deps"]
    features_on_dep = result["activated_deps"].get(target_dep, [])

    if not activated:
        return {
            "dep": target_dep,
            "activated": False,
            "features_on_dep": [],
            "activation_chain": [],
        }

    chain = []
    enabled_set = set(result["enabled_features"])

    for feat in sorted(enabled_set):
        for entry in features_def.get(feat, []):
            kind = parse_entry(entry)
            if kind[0] == "activate_dep" and kind[1] == target_dep:
                chain.append(
                    {"source_feature": feat, "entry": entry, "type": "direct"}
                )
            elif kind[0] == "strong_dep_feature" and kind[1] == target_dep:
                chain.append(
                    {"source_feature": feat, "entry": entry, "type": "strong"}
                )
            elif kind[0] == "weak_dep_feature" and kind[1] == target_dep:
                chain.append(
                    {"source_feature": feat, "entry": entry, "type": "weak"}
                )

    chain.sort(key=lambda x: (x["source_feature"], x["entry"]))

    return {
        "dep": target_dep,
        "activated": True,
        "features_on_dep": features_on_dep,
        "activation_chain": chain,
    }


def impact_analysis(features_def, dep_defaults, feature):
    """Compute impact analysis for a single feature.

    Resolves the feature, tracks weak dep firings, and determines which
    activated deps are exclusive (not activated by any other single feature).
    """
    result, weak_fired = resolve(features_def, dep_defaults, [feature], track_weak=True)
    target_deps = set(result["activated_deps"].keys())

    # Resolve every other feature individually to find shared deps
    all_features = sorted(features_def.keys())
    other_deps = set()
    for f in all_features:
        if f == feature:
            continue
        other_result = resolve(features_def, dep_defaults, [f])
        other_deps.update(other_result["activated_deps"].keys())

    exclusive = sorted(target_deps - other_deps)

    return {
        "feature": feature,
        "enabled_features": result["enabled_features"],
        "activated_deps": result["activated_deps"],
        "weak_deps_fired": weak_fired,
        "exclusive_deps": exclusive,
    }


def main():
    if len(sys.argv) < 3:
        print("Usage: resolver <resolve|trace|impact> <args>", file=sys.stderr)
        sys.exit(1)

    features_def, dep_defaults = load_metadata()
    command = sys.argv[1]

    if command == "resolve":
        initial = [f.strip() for f in sys.argv[2].split(",") if f.strip()]
        result = resolve(features_def, dep_defaults, initial)
        print(json.dumps(result))
    elif command == "trace":
        if len(sys.argv) < 4:
            print("Usage: resolver trace <root-features> <dep-name>", file=sys.stderr)
            sys.exit(1)
        initial = [f.strip() for f in sys.argv[2].split(",") if f.strip()]
        target = sys.argv[3].strip()
        result = trace_dep(features_def, dep_defaults, initial, target)
        print(json.dumps(result))
    elif command == "impact":
        target = sys.argv[2].strip()
        result = impact_analysis(features_def, dep_defaults, target)
        print(json.dumps(result))
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
