#!/usr/bin/env python3
"""
Solution: Fix all 8 bugs in the CMake ExternalProject dependency chain
and generate a comprehensive build audit report including a
memory-constrained parallel build schedule.

Bugs:
  1. Circular dependency: OpenEXR depends on OpenColorIO (and vice versa)
  2. Wrong path: Embree ISPC_EXECUTABLE has extra /ispc/ subdir
  3. Missing dependency: libtiff needs libjpeg-turbo in DEPENDS
  4. Missing dependency: OpenImageIO needs OpenColorIO in DEPENDS
  5. Version mismatch: USD v23.02 incompatible with OpenEXR 3.x (need v23.08)
  6. Linking conflict: OpenEXR BUILD_SHARED_LIBS=OFF breaks downstream shared libs
  7. Missing flag: OpenSubdiv missing NO_TUTORIALS=ON for headless build
  8. Version mismatch: TBB v2020.3.3 too old for oneAPI interface (need v2021.5.0)
"""

import json
import re
from collections import defaultdict, deque


def fix_cmake():
    """Apply all 8 fixes to /app/CMakeLists.txt."""
    with open("/app/CMakeLists.txt") as f:
        content = f.read()

    # Bug 1: Remove OpenColorIO from OpenEXR DEPENDS (circular dep)
    content = re.sub(
        r"(ExternalProject_Add\(OpenEXR.*?DEPENDS\s+zlib)\s+OpenColorIO",
        r"\1",
        content, count=1, flags=re.DOTALL,
    )

    # Bug 2: Fix Embree ISPC executable path
    content = content.replace(
        "${INSTALL_DIR}/ispc/bin/ispc",
        "${INSTALL_DIR}/bin/ispc",
    )

    # Bug 3: Add libjpeg-turbo to libtiff DEPENDS
    content = re.sub(
        r"(ExternalProject_Add\(libtiff.*?DEPENDS\s+zlib)",
        r"\1 libjpeg-turbo",
        content, count=1, flags=re.DOTALL,
    )

    # Bug 4: Add OpenColorIO to OpenImageIO DEPENDS
    content = re.sub(
        r"(ExternalProject_Add\(OpenImageIO.*?DEPENDS\s+OpenEXR\s+libtiff\s+Boost)",
        r"\1 OpenColorIO",
        content, count=1, flags=re.DOTALL,
    )

    # Bug 5: Fix USD GIT_TAG for OpenEXR 3.x compatibility
    content = re.sub(
        r"(ExternalProject_Add\(USD.*?GIT_TAG\s+)v23\.02",
        r"\g<1>v23.08",
        content, count=1, flags=re.DOTALL,
    )

    # Bug 6: Fix OpenEXR static build — change to shared
    content = re.sub(
        r"(ExternalProject_Add\(OpenEXR.*?)-DBUILD_SHARED_LIBS=OFF",
        r"\1-DBUILD_SHARED_LIBS=ON",
        content, count=1, flags=re.DOTALL,
    )

    # Bug 7: Add NO_TUTORIALS=ON to OpenSubdiv for headless build
    content = re.sub(
        r"(ExternalProject_Add\(OpenSubdiv.*?-DNO_REGRESSION=ON)",
        r"\1\n        -DNO_TUTORIALS=ON",
        content, count=1, flags=re.DOTALL,
    )

    # Bug 8: Fix TBB version for oneAPI interface
    content = re.sub(
        r"(ExternalProject_Add\(TBB.*?GIT_TAG\s+)v2020\.3\.3",
        r"\g<1>v2021.5.0",
        content, count=1, flags=re.DOTALL,
    )

    with open("/app/CMakeLists.txt", "w") as f:
        f.write(content)
    print("Fixed all 8 bugs in CMakeLists.txt")


def generate_report():
    """Compute full build audit and write /app/build_audit.json."""
    # Corrected dependency graph
    graph = {
        "zlib": [],
        "OpenEXR": ["zlib"],
        "libjpeg-turbo": [],
        "libtiff": ["zlib", "libjpeg-turbo"],
        "Boost": [],
        "Random123": [],
        "ISPC": [],
        "TBB": [],
        "OpenColorIO": ["OpenEXR"],
        "Embree": ["ISPC", "TBB"],
        "OpenImageIO": ["OpenEXR", "libtiff", "Boost", "OpenColorIO"],
        "OpenSubdiv": ["TBB"],
        "USD": ["Boost", "TBB", "OpenEXR", "OpenSubdiv", "OpenImageIO"],
    }

    memory_costs = {
        "zlib": 0.5, "OpenEXR": 3.0, "libjpeg-turbo": 1.0,
        "libtiff": 1.0, "Boost": 4.0, "Random123": 0.5,
        "ISPC": 0.5, "TBB": 2.0, "OpenColorIO": 2.0,
        "Embree": 4.0, "OpenImageIO": 3.0, "OpenSubdiv": 2.0,
        "USD": 6.0,
    }
    budget = 7.0

    # Build adjacency list: project -> list of dependents
    adj = defaultdict(list)
    for node, deps in graph.items():
        for dep in deps:
            adj[dep].append(node)

    # Topological sort (Kahn's algorithm, deterministic via sorted queues)
    in_deg = {n: len(graph[n]) for n in graph}
    queue = deque(sorted(n for n in graph if in_deg[n] == 0))
    topo_order = []
    while queue:
        node = queue.popleft()
        topo_order.append(node)
        for dependent in sorted(adj[node]):
            in_deg[dependent] -= 1
            if in_deg[dependent] == 0:
                queue.append(dependent)

    # Critical path (longest path in DAG via dynamic programming)
    dist = {node: 1 for node in graph}
    parent = {node: None for node in graph}
    for node in topo_order:
        for dependent in adj[node]:
            if dist[node] + 1 > dist[dependent]:
                dist[dependent] = dist[node] + 1
                parent[dependent] = node

    max_node = max(dist, key=dist.get)
    critical_path = []
    node = max_node
    while node is not None:
        critical_path.append(node)
        node = parent[node]
    critical_path.reverse()

    # Max parallelism (unlimited memory): widest level in the DAG
    level = {}
    for node in topo_order:
        if not graph[node]:
            level[node] = 0
        else:
            level[node] = max(level[dep] for dep in graph[node]) + 1
    level_groups = defaultdict(list)
    for node, lev in level.items():
        level_groups[lev].append(node)
    max_parallelism = max(len(nodes) for nodes in level_groups.values())

    # Longest path from each node to any terminal (for scheduling priority)
    longest_to_term = {n: 1 for n in graph}
    for node in reversed(topo_order):
        for dependent in adj[node]:
            longest_to_term[node] = max(
                longest_to_term[node], longest_to_term[dependent] + 1
            )

    # Memory-constrained parallel schedule (greedy, critical-path priority)
    scheduled = set()
    stages = []
    while len(scheduled) < len(graph):
        # Find all available projects whose deps are fully scheduled
        available = sorted(
            [n for n in graph if n not in scheduled
             and all(d in scheduled for d in graph[n])],
            key=lambda n: (-longest_to_term[n], n),
        )
        stage = []
        stage_mem = 0.0
        for proj in available:
            if stage_mem + memory_costs[proj] <= budget:
                stage.append(proj)
                stage_mem += memory_costs[proj]
        for proj in stage:
            scheduled.add(proj)
        stages.append(stage)

    # Bug descriptions with root cause chain analysis
    bugs = [
        {
            "project": "OpenEXR",
            "type": "circular_dependency",
            "fix": "Removed OpenColorIO from OpenEXR DEPENDS list",
            "root_cause_chain": (
                "OpenEXR listed OpenColorIO as a dependency while OpenColorIO "
                "depends on OpenEXR, creating a build-time dependency cycle. "
                "CMake detects this as a strongly connected component in the "
                "ExternalProject dependency graph and refuses to configure. "
                "The actual dependency direction is strictly unidirectional: "
                "OpenColorIO depends on OpenEXR for EXR color space support, "
                "not vice versa. OpenEXR has no awareness of color management."
            ),
        },
        {
            "project": "Embree",
            "type": "incorrect_path",
            "fix": (
                "Changed ISPC_EXECUTABLE from "
                "${INSTALL_DIR}/ispc/bin/ispc to ${INSTALL_DIR}/bin/ispc"
            ),
            "root_cause_chain": (
                "ISPC is distributed as a pre-built binary tarball. The "
                "ExternalProject INSTALL_COMMAND copies the binary directly "
                "to ${INSTALL_DIR}/bin/ispc (flat bin directory). The Embree "
                "configuration referenced ${INSTALL_DIR}/ispc/bin/ispc with "
                "a spurious /ispc/ subdirectory that doesn't exist, causing "
                "CMake to fail at configure time when Embree tried to verify "
                "the ISPC compiler path."
            ),
        },
        {
            "project": "libtiff",
            "type": "missing_dependency",
            "fix": "Added libjpeg-turbo to libtiff DEPENDS list",
            "root_cause_chain": (
                "libtiff enables JPEG-in-TIFF codec (jpeg=ON) which requires "
                "libjpeg-turbo headers and libraries at configure time. Without "
                "a DEPENDS entry, CMake does not enforce build ordering and "
                "libjpeg-turbo may not be installed when libtiff configures. "
                "This causes silent degradation: libtiff builds successfully "
                "but without JPEG support. The failure propagates downstream "
                "when OpenImageIO attempts to read JPEG-compressed TIFF images "
                "and encounters an unsupported codec error at runtime."
            ),
        },
        {
            "project": "OpenImageIO",
            "type": "missing_dependency",
            "fix": "Added OpenColorIO to OpenImageIO DEPENDS list",
            "root_cause_chain": (
                "OpenImageIO requires OpenColorIO for color-managed image I/O. "
                "Without OpenColorIO in the DEPENDS list, CMake may schedule "
                "OpenImageIO's configure step before OpenColorIO finishes "
                "installing. This produces an intermittent (~40% failure rate) "
                "FindOpenColorIO error. The error message misleadingly suggests "
                "the OpenColorIO installation is corrupted, but the root cause "
                "is a missing build ordering constraint causing a race condition."
            ),
        },
        {
            "project": "USD",
            "type": "version_incompatibility",
            "fix": "Changed USD GIT_TAG from v23.02 to v23.08",
            "root_cause_chain": (
                "USD v23.02 was written against the OpenEXR 2.x C++ API which "
                "uses the Imf_2_5 namespace. The build chain installs OpenEXR "
                "3.1.8 which uses the Imf_3_1 namespace. This causes ~49 "
                "compile errors in USD's imaging code (pxr/imaging/) where "
                "explicit Imf_2_5:: references are unresolved. USD v23.08 "
                "added OpenEXR 3.x namespace support, resolving all errors."
            ),
        },
        {
            "project": "OpenEXR",
            "type": "linking_conflict",
            "fix": "Changed OpenEXR BUILD_SHARED_LIBS from OFF to ON",
            "root_cause_chain": (
                "OpenEXR was built as static libraries (BUILD_SHARED_LIBS=OFF) "
                "which produces .a archives without position-independent code. "
                "Downstream OpenColorIO builds as a shared library (.so) and "
                "links against OpenEXR, causing linker relocation errors. The "
                "error log suggests adding CMAKE_POSITION_INDEPENDENT_CODE=ON "
                "to generate PIC in static archives, but this is incorrect: "
                "the build spec requires shared libraries throughout the chain "
                "because the renderer's plugin system uses dlopen() for "
                "runtime loading. Static archives with PIC do not satisfy "
                "this requirement."
            ),
        },
        {
            "project": "OpenSubdiv",
            "type": "missing_cmake_flag",
            "fix": "Added -DNO_TUTORIALS=ON to OpenSubdiv CMAKE_ARGS",
            "root_cause_chain": (
                "OpenSubdiv's tutorial programs include GLFW/glfw3.h which "
                "transitively includes GL/glx.h. In the headless server build "
                "environment, OpenGL development headers are not installed. "
                "The build error suggests installing mesa-libGL-devel, but "
                "the correct fix for a headless renderer build is disabling "
                "tutorial compilation with NO_TUTORIALS=ON. The build spec "
                "explicitly requires disabling all GUI components."
            ),
        },
        {
            "project": "TBB",
            "type": "version_incompatibility",
            "fix": "Changed TBB GIT_TAG from v2020.3.3 to v2021.5.0",
            "root_cause_chain": (
                "TBB v2020.3.3 uses the legacy tbb:: namespace and deprecated "
                "CMake integration. OpenSubdiv v3.5.0 and USD v23.08 require "
                "the oneAPI TBB interface (oneapi::tbb namespace) introduced "
                "in v2021.1. The old TBB version appears to build successfully "
                "due to CMake compatibility shims, producing no error in the "
                "build log. However, the ABI mismatch causes crashes at "
                "runtime when the renderer loads OpenSubdiv's TBB-parallel "
                "subdivision evaluation. The build spec requires v2021.1+."
            ),
        },
    ]

    report = {
        "dependency_graph": graph,
        "topological_order": topo_order,
        "critical_path": critical_path,
        "critical_path_length": len(critical_path),
        "max_parallelism": max_parallelism,
        "bugs_found": bugs,
        "build_schedule": stages,
        "schedule_makespan": len(stages),
    }

    with open("/app/build_audit.json", "w") as f:
        json.dump(report, f, indent=2)

    print("Generated build_audit.json")
    print(f"  Critical path: {' -> '.join(critical_path)} "
          f"(length {len(critical_path)})")
    print(f"  Max parallelism: {max_parallelism}")
    print(f"  Schedule makespan: {len(stages)} stages")
    for i, stage in enumerate(stages):
        mem = sum(memory_costs[p] for p in stage)
        print(f"  Stage {i}: {stage} ({mem:.1f} GB)")


if __name__ == "__main__":
    fix_cmake()
    generate_report()
