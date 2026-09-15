#!/usr/bin/env python3

"""
KernelCI Pipeline Configuration Auditor

Analyzes a KernelCI pipeline YAML configuration file for:
- Priority range conflicts between LAVA labs
- Invalid priority ranges (min > max)
- Contradictory tree include/exclude rules
- Placeholder or inherited callback tokens
- Missing required fields
- Storage backend inconsistencies
- Security-relevant misconfigurations

Handles YAML merge keys (<<: *anchor) by using yaml.compose() to
inspect the raw node graph and distinguish inherited vs explicit fields.
"""

import json
import os
import sys

import yaml


# ---------------------------------------------------------------------------
# YAML merge-key analysis (node-graph level)
# ---------------------------------------------------------------------------

def analyze_merge_keys(yaml_path):
    """
    Parse the YAML at *yaml_path* with yaml.compose() to obtain the raw
    node tree.  Walk the ``runtimes`` mapping and, for every runtime that
    uses a merge key (``<<``), record which keys were explicitly set in the
    runtime vs. inherited from the merge source.

    Returns a dict mapping runtime name -> {
        "explicit_keys": [str, ...],
        "inherited_keys": [str, ...],
        "source_runtime": str | None,
    }
    """
    with open(yaml_path) as fh:
        root = yaml.compose(fh)

    if not isinstance(root, yaml.MappingNode):
        return {}

    # Locate the runtimes mapping node
    runtimes_node = None
    for key_node, value_node in root.value:
        if isinstance(key_node, yaml.ScalarNode) and key_node.value == "runtimes":
            runtimes_node = value_node
            break

    if runtimes_node is None or not isinstance(runtimes_node, yaml.MappingNode):
        return {}

    # Build id(node) -> runtime-name map so we can resolve alias targets
    node_id_to_name = {}
    for key_node, value_node in runtimes_node.value:
        if isinstance(key_node, yaml.ScalarNode):
            node_id_to_name[id(value_node)] = key_node.value

    results = {}

    for key_node, value_node in runtimes_node.value:
        if not isinstance(value_node, yaml.MappingNode):
            continue

        runtime_name = key_node.value
        has_merge = False
        explicit_keys = set()
        merge_source_nodes = []

        for k_node, v_node in value_node.value:
            if not isinstance(k_node, yaml.ScalarNode):
                continue
            if k_node.value == "<<":
                has_merge = True
                # Single source or list of sources
                if isinstance(v_node, yaml.MappingNode):
                    merge_source_nodes.append(v_node)
                elif isinstance(v_node, yaml.SequenceNode):
                    for item in v_node.value:
                        if isinstance(item, yaml.MappingNode):
                            merge_source_nodes.append(item)
            else:
                explicit_keys.add(k_node.value)

        if not has_merge:
            continue

        # Gather all keys contributed by merge sources
        source_keys = set()
        source_runtime = None
        for src_node in merge_source_nodes:
            for sk, _sv in src_node.value:
                if isinstance(sk, yaml.ScalarNode) and sk.value != "<<":
                    source_keys.add(sk.value)
            # Try to resolve the source runtime name via node identity
            resolved = node_id_to_name.get(id(src_node))
            if resolved is not None:
                source_runtime = resolved

        inherited_keys = source_keys - explicit_keys

        results[runtime_name] = {
            "explicit_keys": sorted(explicit_keys),
            "inherited_keys": sorted(inherited_keys),
            "source_runtime": source_runtime,
        }

    return results


# ---------------------------------------------------------------------------
# Validation checks
# ---------------------------------------------------------------------------

def check_missing_fields(config):
    findings = []

    for name, entry in config.get("storage", {}).items():
        stype = entry.get("storage_type", "")
        if stype == "ssh" and "host" not in entry:
            findings.append({
                "entry": name,
                "section": "storage",
                "field": "host",
                "severity": "error",
                "message": (
                    f"Storage '{name}' has storage_type 'ssh' "
                    f"but is missing required 'host' field"
                ),
            })
        if stype == "backend" and "base_url" not in entry:
            findings.append({
                "entry": name,
                "section": "storage",
                "field": "base_url",
                "severity": "error",
                "message": (
                    f"Storage '{name}' has storage_type 'backend' "
                    f"but is missing required 'base_url' field"
                ),
            })

    for name, entry in config.get("runtimes", {}).items():
        lab_type = entry.get("lab_type", "")
        if lab_type == "lava" and "url" not in entry:
            findings.append({
                "entry": name,
                "section": "runtimes",
                "field": "url",
                "severity": "error",
                "message": (
                    f"Runtime '{name}' has lab_type 'lava' "
                    f"but is missing required 'url' field"
                ),
            })

    return findings


def check_storage_issues(config):
    findings = []

    for name, entry in config.get("storage", {}).items():
        if entry.get("storage_type") != "backend":
            continue
        base_url = entry.get("base_url", "")
        api_url = entry.get("api_url", "")
        if not base_url or not api_url:
            continue

        base_staging = "staging" in base_url.lower()
        api_staging = "staging" in api_url.lower()

        if base_staging != api_staging:
            findings.append({
                "entry": name,
                "severity": "error",
                "message": (
                    f"Storage '{name}' has environment mismatch: "
                    f"base_url points to "
                    f"{'staging' if base_staging else 'production'} "
                    f"but api_url points to "
                    f"{'staging' if api_staging else 'production'}"
                ),
                "base_url": base_url,
                "api_url": api_url,
            })

    return findings


def check_invalid_ranges(config):
    findings = []

    for name, entry in config.get("runtimes", {}).items():
        if entry.get("lab_type") != "lava":
            continue
        pmin = entry.get("priority_min")
        pmax = entry.get("priority_max")
        if pmin is not None and pmax is not None and pmin > pmax:
            findings.append({
                "runtime": name,
                "lab": name,
                "severity": "error",
                "message": (
                    f"Runtime '{name}' has inverted priority range: "
                    f"min={pmin} > max={pmax}"
                ),
                "priority_min": pmin,
                "priority_max": pmax,
            })

    return findings


def check_priority_conflicts(config):
    findings = []
    runtimes = config.get("runtimes", {})

    # Collect LAVA labs with valid priority ranges
    lava_labs = []
    for name, entry in runtimes.items():
        if entry.get("lab_type") != "lava":
            continue
        pmin = entry.get("priority_min")
        pmax = entry.get("priority_max")
        if pmin is not None and pmax is not None and pmin <= pmax:
            lava_labs.append((name, pmin, pmax))

    for i in range(len(lava_labs)):
        for j in range(i + 1, len(lava_labs)):
            name_a, min_a, max_a = lava_labs[i]
            name_b, min_b, max_b = lava_labs[j]

            overlap_lo = max(min_a, min_b)
            overlap_hi = min(max_a, max_b)

            if overlap_lo <= overlap_hi:
                findings.append({
                    "lab_a": name_a,
                    "lab_b": name_b,
                    "severity": "warning",
                    "message": (
                        f"Priority range overlap between "
                        f"'{name_a}' [{min_a},{max_a}] and "
                        f"'{name_b}' [{min_b},{max_b}]: "
                        f"overlap [{overlap_lo},{overlap_hi}]"
                    ),
                    "overlap_range": [overlap_lo, overlap_hi],
                })

    return findings


def _parse_tree_rules(tree_list):
    """Split tree rules into include and exclude sets."""
    includes, excludes = set(), set()
    for rule in (tree_list or []):
        s = str(rule)
        if s.startswith("!"):
            excludes.add(s[1:])
        else:
            includes.add(s)
    return includes, excludes


def check_tree_rule_conflicts(config):
    findings = []
    runtimes = config.get("runtimes", {})

    # --- intra-lab contradictions ---
    for name, entry in runtimes.items():
        if entry.get("lab_type") != "lava":
            continue
        tree_rules = entry.get("rules", {}).get("tree", [])
        if not tree_rules:
            continue
        includes, excludes = _parse_tree_rules(tree_rules)
        for tree in includes & excludes:
            findings.append({
                "lab": name,
                "runtime": name,
                "tree": tree,
                "severity": "error",
                "message": (
                    f"Runtime '{name}' has contradictory tree rules: "
                    f"'{tree}' is both included and excluded ('!{tree}')"
                ),
            })

    # --- cross-lab conflicts at overlapping priority tiers ---
    lab_info = {}
    for name, entry in runtimes.items():
        if entry.get("lab_type") != "lava":
            continue
        pmin = entry.get("priority_min")
        pmax = entry.get("priority_max")
        rules = entry.get("rules", {}).get("tree", [])
        if pmin is not None and pmax is not None and pmin <= pmax:
            inc, exc = _parse_tree_rules(rules)
            lab_info[name] = {"pmin": pmin, "pmax": pmax, "inc": inc, "exc": exc}

    names = list(lab_info)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = lab_info[names[i]], lab_info[names[j]]
            if max(a["pmin"], b["pmin"]) > min(a["pmax"], b["pmax"]):
                continue  # no priority overlap
            cross = (a["inc"] & b["exc"]) | (b["inc"] & a["exc"])
            for tree in sorted(cross):
                findings.append({
                    "lab_a": names[i],
                    "lab_b": names[j],
                    "tree": tree,
                    "severity": "warning",
                    "message": (
                        f"Cross-lab tree conflict: '{tree}' is allowed in "
                        f"one of '{names[i]}'/'{names[j]}' but denied in "
                        f"the other, and their priority ranges overlap"
                    ),
                })

    return findings


def check_token_issues(config, merge_info):
    findings = []
    runtimes = config.get("runtimes", {})

    placeholder_patterns = [
        "REPLACE", "TODO", "CHANGEME", "PLACEHOLDER", "FIXME",
        "YOUR-TOKEN", "INSERT-HERE", "DEFAULT",
    ]

    for name, entry in runtimes.items():
        if entry.get("lab_type") != "lava":
            continue

        token = (
            entry.get("notify", {}).get("callback", {}).get("token", "")
        )
        if not token:
            continue

        # Placeholder detection
        upper = token.upper()
        for pat in placeholder_patterns:
            if pat in upper:
                findings.append({
                    "lab": name,
                    "runtime": name,
                    "token": token,
                    "severity": "critical",
                    "message": (
                        f"Runtime '{name}' uses a placeholder callback "
                        f"token: '{token}'"
                    ),
                })
                break

        # Inherited token via merge key
        if name in merge_info:
            info = merge_info[name]
            if "notify" in info.get("inherited_keys", []):
                source = info.get("source_runtime", "unknown")
                findings.append({
                    "lab": name,
                    "runtime": name,
                    "token": token,
                    "inherited_from": source,
                    "severity": "warning",
                    "message": (
                        f"Runtime '{name}' inherits its callback token "
                        f"'{token}' from '{source}' via YAML merge key. "
                        f"Both labs share the same callback authentication."
                    ),
                })

    return findings


def check_security_warnings(config):
    findings = []
    runtimes = config.get("runtimes", {})

    for name, entry in runtimes.items():
        if entry.get("lab_type") != "lava":
            continue

        if entry.get("disable_queue_limit", False):
            findings.append({
                "lab": name,
                "runtime": name,
                "severity": "warning",
                "message": (
                    f"Runtime '{name}' has disable_queue_limit set to true. "
                    f"Queue depth checking is disabled, risking unbounded "
                    f"job submissions."
                ),
            })

    return findings


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    config_path = "/app/pipeline.yaml"
    output_path = "/app/audit_report.json"

    if not os.path.exists(config_path):
        print(f"Error: {config_path} not found", file=sys.stderr)
        return 1

    config = yaml.safe_load(open(config_path))
    merge_info = analyze_merge_keys(config_path)

    report = {
        "config_file": config_path,
        "priority_conflicts": check_priority_conflicts(config),
        "invalid_ranges": check_invalid_ranges(config),
        "tree_rule_conflicts": check_tree_rule_conflicts(config),
        "token_issues": check_token_issues(config, merge_info),
        "missing_fields": check_missing_fields(config),
        "storage_issues": check_storage_issues(config),
        "security_warnings": check_security_warnings(config),
    }

    total = sum(len(v) for v in report.values() if isinstance(v, list))
    report["summary"] = {
        "total_findings": total,
        "by_category": {
            k: len(v) for k, v in report.items() if isinstance(v, list)
        },
    }

    with open(output_path, "w") as fh:
        json.dump(report, fh, indent=2)

    print(f"Audit complete. {total} finding(s) written to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
