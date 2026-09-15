"""
PEP 440/508-compliant Python dependency resolver with recursive backtracking.
"""

import json
import re

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version


class ResolutionError(Exception):
    """Raised when dependencies cannot be resolved."""
    pass


def _canonicalize(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def _make_env(python_version, sys_platform):
    parts = python_version.split(".")
    major_minor = f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else python_version
    full = python_version if len(parts) >= 3 else f"{python_version}.0"
    return {
        "os_name": "posix" if sys_platform in ("linux", "darwin") else "nt",
        "sys_platform": sys_platform,
        "platform_system": {"linux": "Linux", "darwin": "Darwin", "win32": "Windows"}.get(
            sys_platform, sys_platform
        ),
        "platform_machine": "x86_64",
        "platform_python_implementation": "CPython",
        "platform_release": "",
        "platform_version": "",
        "python_version": major_minor,
        "python_full_version": full,
        "implementation_name": "cpython",
        "implementation_version": full,
    }


def resolve(requirements, index_path, python_version="3.11", sys_platform="linux"):
    with open(index_path) as f:
        index = json.load(f)

    env = _make_env(python_version, sys_platform)
    pv_parts = python_version.split(".")
    python_ver_full = python_version if len(pv_parts) >= 3 else f"{python_version}.0"

    parsed = [Requirement(r) for r in requirements]
    result = _backtrack(parsed, {}, index, env, python_ver_full)
    if result is None:
        raise ResolutionError(f"Cannot resolve: {requirements}")

    return {name: str(ver) for name, ver in sorted(result.items())}


def _get_candidates(index, name, specifier, python_ver_full):
    canon = _canonicalize(name)
    if canon not in index:
        raise ResolutionError(f"Unknown package: {canon}")

    versions = []
    for v_str, meta in index[canon]["versions"].items():
        ver = Version(v_str)
        if ver not in specifier:
            continue
        req_py = meta.get("requires_python")
        if req_py and req_py != "null":
            if Version(python_ver_full) not in SpecifierSet(req_py):
                continue
        versions.append(ver)

    return sorted(versions, reverse=True)


def _get_deps(index, name, version, extras, env):
    canon = _canonicalize(name)
    meta = index[canon]["versions"][str(version)]
    deps = []

    for dep_str in meta.get("dependencies", []):
        req = Requirement(dep_str)
        if req.marker and not req.marker.evaluate(env):
            continue
        deps.append(req)

    for extra in (extras or set()):
        for dep_str in meta.get("extras", {}).get(extra, []):
            req = Requirement(dep_str)
            if req.marker and not req.marker.evaluate(env):
                continue
            deps.append(req)

    return deps


def _backtrack(requirements, resolved, index, env, python_ver_full):
    if not requirements:
        return dict(resolved)

    req = requirements[0]
    remaining = requirements[1:]
    canon = _canonicalize(req.name)

    if canon in resolved:
        if resolved[canon] in req.specifier:
            return _backtrack(remaining, resolved, index, env, python_ver_full)
        return None

    candidates = _get_candidates(index, canon, req.specifier, python_ver_full)

    for version in candidates:
        new_resolved = dict(resolved)
        new_resolved[canon] = version

        deps = _get_deps(index, canon, version, req.extras, env)
        result = _backtrack(remaining + deps, new_resolved, index, env, python_ver_full)
        if result is not None:
            return result

    return None
