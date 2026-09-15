#!/usr/bin/env python3
"""Cargo feature resolver - reads feature graph from cargo metadata JSON.

Resolves crate features by processing transitive feature dependencies,
optional dependency activation, and conditional (weak) dependency features.
"""
import sys
import json


def load_metadata(path="/app/metadata.json"):
    """Load feature definitions and optional dep defaults from cargo metadata."""
    with open(path) as f:
        data = json.load(f)

    # Find the root/local package (source field is null for path deps)
    pkg = None
    for p in data["packages"]:
        if p.get("source") is None:
            pkg = p
            break
    if pkg is None:
        pkg = data["packages"][0]

    features = pkg["features"]

    # Build optional dependency defaults lookup from metadata
    dep_defaults = {}
    for dep in pkg.get("dependencies", []):
        if dep.get("optional", False):
            dep_defaults[dep["name"]] = dep.get("default_features", [])

    return features, dep_defaults


def parse_entry(entry):
    """Parse a feature dependency entry into a typed tuple.

    Entry types:
      "feature_name"        -> ("feature", name)
      "dep:dep_name"        -> ("activate_dep", name)
      "dep_name/feat_name"  -> ("strong_dep_feature", dep, feat)
      "dep_name?/feat_name" -> ("weak_dep_feature", dep, feat)
    """
    if entry.startswith("dep:"):
        return ("activate_dep", entry[4:])
    if "?/" in entry:
        dep, feat = entry.split("?/", 1)
        return ("weak_dep_feature", dep, feat)
    if "/" in entry:
        dep, feat = entry.split("/", 1)
        return ("strong_dep_feature", dep, feat)
    return ("feature", entry)


def resolve(features_def, dep_defaults, initial_features):
    """Compute fully resolved feature state from initial feature set.

    Processes feature dependencies, activates optional deps, and handles
    weak dependency features that only fire when their target dep is active.
    """
    enabled = set()
    active_deps = {}   # dep_name -> set of features enabled on that dep
    seen = set()       # all names encountered (features + deps) to prevent re-processing
    queue = list(initial_features)

    while queue:
        feat = queue.pop(0)
        if feat in seen:
            continue
        if feat not in features_def:
            print(f"Error: unknown feature '{feat}'", file=sys.stderr)
            sys.exit(1)
        seen.add(feat)
        enabled.add(feat)

        for entry in features_def[feat]:
            kind = parse_entry(entry)

            if kind[0] == "feature":
                target = kind[1]
                if target not in seen:
                    queue.append(target)

            elif kind[0] == "activate_dep":
                dep_name = kind[1]
                if dep_name not in seen:
                    defaults = list(dep_defaults.get(dep_name, []))
                    active_deps[dep_name] = set(defaults)
                    seen.add(dep_name)

            elif kind[0] == "strong_dep_feature":
                dep_name, feat_name = kind[1], kind[2]
                if dep_name not in active_deps:
                    if dep_name not in seen:
                        defaults = list(dep_defaults.get(dep_name, []))
                        active_deps[dep_name] = set(defaults)
                        seen.add(dep_name)
                    else:
                        continue
                active_deps[dep_name].add(feat_name)

            elif kind[0] == "weak_dep_feature":
                dep_name, feat_name = kind[1], kind[2]
                if dep_name in active_deps:
                    active_deps[dep_name].add(feat_name)

    return {
        "enabled_features": sorted(enabled),
        "activated_deps": {
            k: sorted(v) for k, v in sorted(active_deps.items())
        }
    }


def main():
    if len(sys.argv) < 3:
        print("Usage: resolver <command> <args>", file=sys.stderr)
        sys.exit(1)

    features_def, dep_defaults = load_metadata()
    command = sys.argv[1]

    if command == "resolve":
        initial = [f.strip() for f in sys.argv[2].split(",") if f.strip()]
        result = resolve(features_def, dep_defaults, initial)
        print(json.dumps(result))
    else:
        print(f"Command not implemented: {command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
