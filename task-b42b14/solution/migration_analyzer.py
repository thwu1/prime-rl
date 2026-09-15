#!/usr/bin/env python3
"""
Cargo resolver v1 -> v2 migration analyzer.

Parses workspace Cargo.toml files, identifies feature-resolution issues
caused by the v1-to-v2 transition, and optionally applies fixes.

Usage:
    python3 migration_analyzer.py [--workspace DIR] [--output FILE] [--apply]
"""

import argparse
import glob as globmod
import json
import os
import re
import sys

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        print("Error: Python 3.11+ (tomllib) or tomli package required",
              file=sys.stderr)
        sys.exit(1)


def parse_toml(path):
    with open(path, "rb") as f:
        return tomllib.load(f)


def get_dep_features(spec):
    """Extract feature set from a dependency specification."""
    if isinstance(spec, str):
        return set()
    return set(spec.get("features", []))


def is_optional(spec):
    if isinstance(spec, str):
        return False
    return spec.get("optional", False)


def merge_workspace_dep(local_spec, ws_deps, dep_name):
    """Merge local dependency spec with workspace-level spec."""
    if isinstance(local_spec, dict) and local_spec.get("workspace"):
        base = {}
        ws = ws_deps.get(dep_name, {})
        if isinstance(ws, dict):
            base = dict(ws)
        for k, v in local_spec.items():
            if k != "workspace":
                base[k] = v
        return base
    if isinstance(local_spec, str):
        return {"version": local_spec}
    return dict(local_spec) if isinstance(local_spec, dict) else {}


class MigrationAnalyzer:
    """Analyzes a Cargo workspace for resolver v1->v2 migration issues."""

    def __init__(self, workspace_root):
        self.root = os.path.abspath(workspace_root)
        self.root_toml = parse_toml(os.path.join(self.root, "Cargo.toml"))
        self.ws_deps = self.root_toml.get("workspace", {}).get("dependencies", {})
        self.members = self._load_members()
        self.issues = []
        self._flagged = set()   # (crate, dep, feature) already reported

    # ----- member loading -----

    def _load_members(self):
        patterns = self.root_toml.get("workspace", {}).get("members", [])
        result = {}
        for pat in patterns:
            for member_dir in sorted(globmod.glob(os.path.join(self.root, pat))):
                toml_path = os.path.join(member_dir, "Cargo.toml")
                if not os.path.exists(toml_path):
                    continue
                data = parse_toml(toml_path)
                name = data.get("package", {}).get("name",
                                                    os.path.basename(member_dir))
                result[name] = {
                    "path": toml_path,
                    "dir": member_dir,
                    "data": data,
                    "rel_path": os.path.relpath(toml_path, self.root),
                }
        return result

    # ----- source helpers -----

    def _read_source(self, member_dir):
        content = ""
        src_dir = os.path.join(member_dir, "src")
        if not os.path.isdir(src_dir):
            return content
        for root, _dirs, files in os.walk(src_dir):
            for fname in files:
                if fname.endswith(".rs"):
                    with open(os.path.join(root, fname)) as f:
                        content += f.read() + "\n"
        return content

    def _source_uses_dep_module(self, member_dir, dep_name, module_name):
        """Return True if source contains dep_name::module_name."""
        src = self._read_source(member_dir)
        return bool(re.search(rf"{dep_name}\s*::\s*{module_name}", src))

    # ----- analysis entry point -----

    def analyze(self):
        self.issues = []
        self._flagged = set()
        self._check_dep_not_optional()
        self._check_dev_dep_leaks()
        self._check_host_dep_leaks()
        self._check_broken_propagation()
        self._check_workspace_feature_gaps()
        self._check_missing_features()
        return self.issues

    # ----- detection passes -----

    def _check_dep_not_optional(self):
        """dep:X used in [features] but X lacks optional = true."""
        for name, member in self.members.items():
            data = member["data"]
            features = data.get("features", {})
            deps = data.get("dependencies", {})
            for _feat_name, feat_vals in features.items():
                if not isinstance(feat_vals, list):
                    continue
                for val in feat_vals:
                    if not isinstance(val, str) or not val.startswith("dep:"):
                        continue
                    dep_name = val[4:]
                    dep_spec = deps.get(dep_name)
                    if dep_spec is None:
                        continue
                    merged = merge_workspace_dep(dep_spec, self.ws_deps, dep_name)
                    if not is_optional(dep_spec) and not is_optional(merged):
                        self.issues.append({
                            "crate_name": name,
                            "file": member["rel_path"],
                            "category": "dep_not_optional",
                            "dependency": dep_name,
                            "detail": (
                                f"Feature '{_feat_name}' uses dep:{dep_name} "
                                f"but '{dep_name}' is not marked optional=true"
                            ),
                            "_dep": dep_name,
                        })

    def _check_dev_dep_leaks(self):
        """Features activated only through [dev-dependencies]."""
        for name, member in self.members.items():
            data = member["data"]
            deps = data.get("dependencies", {})
            dev_deps = data.get("dev-dependencies", {})
            for dep_name, dev_spec in dev_deps.items():
                if dep_name not in deps:
                    continue
                dev_merged = merge_workspace_dep(dev_spec, self.ws_deps, dep_name)
                normal_merged = merge_workspace_dep(deps[dep_name], self.ws_deps,
                                                     dep_name)
                leaked = get_dep_features(dev_merged) - get_dep_features(normal_merged)
                if not leaked:
                    continue
                used = set()
                for feat in leaked:
                    if self._source_uses_dep_module(member["dir"], dep_name, feat):
                        used.add(feat)
                        self._flagged.add((name, dep_name, feat))
                if used:
                    self.issues.append({
                        "crate_name": name,
                        "file": member["rel_path"],
                        "category": "dev_dep_leak",
                        "dependency": dep_name,
                        "detail": (
                            f"Features {sorted(used)} on '{dep_name}' are only "
                            f"in [dev-dependencies]; isolated under resolver v2"
                        ),
                        "_leaked_features": sorted(used),
                    })

    def _check_host_dep_leaks(self):
        """Features leaking through [build-dependencies] chain."""
        # Pre-compute each member's normal-dep feature activations
        dep_feat_map = {}
        for n, m in self.members.items():
            dep_feat_map[n] = {}
            for dn, spec in m["data"].get("dependencies", {}).items():
                merged = merge_workspace_dep(spec, self.ws_deps, dn)
                dep_feat_map[n][dn] = get_dep_features(merged)

        for name, member in self.members.items():
            build_deps = member["data"].get("build-dependencies", {})
            normal_deps = member["data"].get("dependencies", {})
            for bdep_name in build_deps:
                if bdep_name not in self.members:
                    continue
                for shared, bdep_activated in dep_feat_map.get(bdep_name, {}).items():
                    if shared not in normal_deps or not bdep_activated:
                        continue
                    normal_merged = merge_workspace_dep(
                        normal_deps[shared], self.ws_deps, shared)
                    leaked = bdep_activated - get_dep_features(normal_merged)
                    if not leaked:
                        continue
                    used = set()
                    for feat in leaked:
                        if self._source_uses_dep_module(member["dir"], shared, feat):
                            used.add(feat)
                            self._flagged.add((name, shared, feat))
                    if used:
                        self.issues.append({
                            "crate_name": name,
                            "file": member["rel_path"],
                            "category": "host_dep_leak",
                            "dependency": shared,
                            "detail": (
                                f"Features {sorted(used)} on '{shared}' are activated "
                                f"via build-dep '{bdep_name}' but not in [dependencies]; "
                                f"isolated under resolver v2"
                            ),
                            "_leaked_features": sorted(used),
                        })

    def _check_broken_propagation(self):
        """Feature F = [] should forward to dep/F."""
        for name, member in self.members.items():
            features = member["data"].get("features", {})
            deps = member["data"].get("dependencies", {})
            for feat_name, feat_vals in features.items():
                if feat_name == "default":
                    continue
                if not isinstance(feat_vals, list) or len(feat_vals) > 0:
                    continue
                for dep_name in deps:
                    if dep_name not in self.members:
                        continue
                    dep_feats = self.members[dep_name]["data"].get("features", {})
                    if feat_name not in dep_feats:
                        continue
                    if self._source_uses_dep_module(member["dir"],
                                                     dep_name, feat_name):
                        self.issues.append({
                            "crate_name": name,
                            "file": member["rel_path"],
                            "category": "broken_propagation",
                            "dependency": dep_name,
                            "detail": (
                                f"Feature '{feat_name}' is empty but should "
                                f"propagate to '{dep_name}/{feat_name}'"
                            ),
                            "_feature_name": feat_name,
                        })
                        self._flagged.add((name, dep_name, feat_name))

    def _check_workspace_feature_gaps(self):
        """Workspace-level dependency missing commonly needed features."""
        for dep_name, ws_spec in self.ws_deps.items():
            ws_features = set()
            if isinstance(ws_spec, dict):
                ws_features = set(ws_spec.get("features", []))
            if dep_name == "serde" and "derive" not in ws_features:
                for mname, member in self.members.items():
                    src = self._read_source(member["dir"])
                    if "Serialize" in src and "Deserialize" in src:
                        self.issues.append({
                            "crate_name": "__workspace__",
                            "file": "Cargo.toml",
                            "category": "workspace_feature_gap",
                            "dependency": "serde",
                            "detail": (
                                f"Workspace serde dependency missing 'derive' "
                                f"feature; crate '{mname}' uses derive macros"
                            ),
                            "_missing_ws_features": ["derive"],
                        })
                        return  # report once

    def _check_missing_features(self):
        """Source uses dep::module but the feature is not activated."""
        for name, member in self.members.items():
            data = member["data"]
            deps = data.get("dependencies", {})
            crate_feats = data.get("features", {})

            # Collect features forwarded via "dep/feat" syntax
            forwarded = set()
            for cf_vals in crate_feats.values():
                if isinstance(cf_vals, list):
                    for v in cf_vals:
                        if isinstance(v, str) and "/" in v and not v.startswith("dep:"):
                            parts = v.split("/", 1)
                            forwarded.add((parts[0], parts[1]))

            for dep_name, spec in deps.items():
                if dep_name not in self.members:
                    continue
                dep_data = self.members[dep_name]["data"]
                dep_features = dep_data.get("features", {})
                merged = merge_workspace_dep(spec, self.ws_deps, dep_name)
                activated = get_dep_features(merged)

                for feat in dep_features:
                    if feat == "default" or feat in activated:
                        continue
                    if (dep_name, feat) in forwarded:
                        continue
                    if (name, dep_name, feat) in self._flagged:
                        continue
                    if self._source_uses_dep_module(member["dir"], dep_name, feat):
                        self.issues.append({
                            "crate_name": name,
                            "file": member["rel_path"],
                            "category": "missing_feature",
                            "dependency": dep_name,
                            "detail": (
                                f"Source uses '{dep_name}::{feat}' but feature "
                                f"'{feat}' is not activated"
                            ),
                            "_missing_features": [feat],
                        })
                        self._flagged.add((name, dep_name, feat))

    # ----- fix application -----

    def apply_fixes(self):
        """Patch Cargo.toml files for all detected issues."""
        patches = {}  # filepath -> [(old, new)]
        for issue in self.issues:
            path = os.path.join(self.root, issue["file"])
            patch = self._compute_patch(issue)
            if patch:
                patches.setdefault(path, []).append(patch)
        for path, file_patches in patches.items():
            with open(path) as f:
                content = f.read()
            for old, new in file_patches:
                content = content.replace(old, new, 1)
            with open(path, "w") as f:
                f.write(content)

    def _compute_patch(self, issue):
        cat = issue["category"]
        dep = issue["dependency"]

        if cat == "dep_not_optional":
            return (
                f"{dep} = {{ workspace = true }}",
                f"{dep} = {{ workspace = true, optional = true }}",
            )

        if cat in ("dev_dep_leak", "host_dep_leak", "missing_feature"):
            feats = issue.get("_leaked_features") or issue.get("_missing_features", [])
            feat_str = ", ".join(f'"{f}"' for f in sorted(feats))
            return (
                f"{dep} = {{ workspace = true }}",
                f'{dep} = {{ workspace = true, features = [{feat_str}] }}',
            )

        if cat == "workspace_feature_gap":
            feats = issue.get("_missing_ws_features", [])
            feat_str = ", ".join(f'"{f}"' for f in feats)
            ws_spec = self.ws_deps.get(dep, {})
            if isinstance(ws_spec, str):
                return (
                    f'{dep} = "{ws_spec}"',
                    f'{dep} = {{ version = "{ws_spec}", features = [{feat_str}] }}',
                )
            version = ws_spec.get("version", "")
            return (
                f'{dep} = {{ version = "{version}" }}',
                f'{dep} = {{ version = "{version}", features = [{feat_str}] }}',
            )

        if cat == "broken_propagation":
            feat = issue.get("_feature_name", "")
            return (f'{feat} = []', f'{feat} = ["{dep}/{feat}"]')

        return None

    # ----- report generation -----

    def get_report(self):
        clean = []
        for issue in self.issues:
            clean.append({k: v for k, v in issue.items() if not k.startswith("_")})
        return {"issues": clean}


def main():
    parser = argparse.ArgumentParser(
        description="Cargo resolver v1->v2 migration analyzer")
    parser.add_argument("--workspace", default=None,
                        help="Workspace root (default: script directory)")
    parser.add_argument("--output", default=None,
                        help="Report output path")
    parser.add_argument("--apply", action="store_true",
                        help="Apply Cargo.toml patches")
    args = parser.parse_args()

    if args.workspace is None:
        args.workspace = os.path.dirname(os.path.abspath(__file__))
    if args.output is None:
        args.output = os.path.join(args.workspace, "migration_report.json")

    analyzer = MigrationAnalyzer(args.workspace)
    issues = analyzer.analyze()

    report = analyzer.get_report()
    with open(args.output, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Found {len(issues)} issue(s). Report: {args.output}")

    if args.apply and issues:
        analyzer.apply_fixes()
        print(f"Applied {len(issues)} fix(es).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
