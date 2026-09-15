#!/usr/bin/env python3
"""Tests for production renderer build chain audit task."""

import json
import os
import re

import pytest


MEMORY_COSTS = {
    "zlib": 0.5,
    "OpenEXR": 3.0,
    "libjpeg-turbo": 1.0,
    "libtiff": 1.0,
    "Boost": 4.0,
    "Random123": 0.5,
    "ISPC": 0.5,
    "TBB": 2.0,
    "OpenColorIO": 2.0,
    "Embree": 4.0,
    "OpenImageIO": 3.0,
    "OpenSubdiv": 2.0,
    "USD": 6.0,
}

MEMORY_BUDGET = 7.0

CORRECT_GRAPH = {
    "zlib": set(),
    "OpenEXR": {"zlib"},
    "libjpeg-turbo": set(),
    "libtiff": {"zlib", "libjpeg-turbo"},
    "Boost": set(),
    "Random123": set(),
    "ISPC": set(),
    "TBB": set(),
    "OpenColorIO": {"OpenEXR"},
    "Embree": {"ISPC", "TBB"},
    "OpenImageIO": {"OpenEXR", "libtiff", "Boost", "OpenColorIO"},
    "OpenSubdiv": {"TBB"},
    "USD": {"Boost", "TBB", "OpenEXR", "OpenSubdiv", "OpenImageIO"},
}

ALL_PROJECTS = set(CORRECT_GRAPH.keys())


def parse_cmake_file(filepath):
    """Parse ExternalProject_Add blocks from a CMake file.

    Uses balanced-parenthesis matching to extract each block, then
    regex to pull DEPENDS, GIT_TAG, and -D CMAKE_ARGS from each.
    """
    if not os.path.exists(filepath):
        pytest.fail(f"CMakeLists.txt not found at {filepath}")

    with open(filepath) as f:
        content = f.read()

    projects = {}
    i = 0
    while True:
        start = content.find("ExternalProject_Add(", i)
        if start == -1:
            break

        paren_pos = start + len("ExternalProject_Add(")
        name_match = re.match(r"\s*([\w-]+)", content[paren_pos:])
        if not name_match:
            i = paren_pos
            continue
        name = name_match.group(1)

        depth = 1
        pos = paren_pos
        while pos < len(content) and depth > 0:
            if content[pos] == "(":
                depth += 1
            elif content[pos] == ")":
                depth -= 1
            pos += 1

        block = content[paren_pos : pos - 1]

        info = {"depends": [], "git_tag": None, "cmake_args": {}}

        dep_match = re.search(
            r"\bDEPENDS\b(.*?)(?=\b(?:CMAKE_ARGS|BUILD_COMMAND|"
            r"CONFIGURE_COMMAND|INSTALL_COMMAND|GIT_REPOSITORY|"
            r"GIT_TAG|URL|BUILD_IN_SOURCE|SOURCE_DIR|INSTALL_DIR)\b|\Z)",
            block,
            re.DOTALL,
        )
        if dep_match:
            deps_text = dep_match.group(1).strip()
            info["depends"] = [d.strip() for d in deps_text.split() if d.strip()]

        tag_match = re.search(r"\bGIT_TAG\b\s+(\S+)", block)
        if tag_match:
            info["git_tag"] = tag_match.group(1)

        for d_match in re.finditer(r"-D([\w]+)=(\S+)", block):
            info["cmake_args"][d_match.group(1)] = d_match.group(2)

        projects[name] = info
        i = pos

    if not projects:
        pytest.fail("No ExternalProject_Add blocks found in CMakeLists.txt")

    return projects


def has_cycles(projects):
    """Check if the dependency graph has cycles using iterative DFS."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {name: WHITE for name in projects}

    def dfs(start):
        stack = [(start, False)]
        while stack:
            node, returning = stack.pop()
            if returning:
                color[node] = BLACK
                continue
            if color[node] == GRAY:
                return True
            if color[node] == BLACK:
                continue
            color[node] = GRAY
            stack.append((node, True))
            for dep in projects[node]["depends"]:
                if dep not in color:
                    continue
                if color[dep] == GRAY:
                    return True
                if color[dep] == WHITE:
                    stack.append((dep, False))
        return False

    return any(dfs(name) for name in projects if color[name] == WHITE)


# ───────────────────────────────────────────────────────────────────────
# Test suite: CMakeLists.txt bug fixes (8 bugs)
# ───────────────────────────────────────────────────────────────────────


class TestCMakeFixes:
    """Verify all 8 bugs in CMakeLists.txt are fixed."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.projects = parse_cmake_file("/app/CMakeLists.txt")

    def test_all_projects_present(self):
        """All 13 original projects must still be present."""
        assert ALL_PROJECTS.issubset(set(self.projects.keys())), (
            f"Missing projects: {ALL_PROJECTS - set(self.projects.keys())}"
        )

    def test_no_circular_dependencies(self):
        """The dependency graph must be a DAG (no cycles)."""
        assert not has_cycles(self.projects), (
            "Dependency graph still contains a cycle"
        )

    # ── Bug 1: circular dependency OpenEXR ↔ OpenColorIO ──────────
    def test_bug1_openexr_no_ocio_dep(self):
        """OpenEXR must NOT depend on OpenColorIO."""
        assert "OpenColorIO" not in self.projects["OpenEXR"]["depends"], (
            "OpenEXR should not depend on OpenColorIO (circular dependency)"
        )

    # ── Bug 2: wrong ISPC executable path for Embree ───────────────
    def test_bug2_embree_ispc_path(self):
        """Embree ISPC_EXECUTABLE must not have the extra /ispc/ subdir."""
        ispc_path = self.projects["Embree"]["cmake_args"].get(
            "ISPC_EXECUTABLE", ""
        )
        assert "/ispc/bin/" not in ispc_path, (
            f"Embree ISPC path still has extra /ispc/ subdir: {ispc_path}"
        )
        assert "bin/ispc" in ispc_path, (
            f"Embree ISPC path must reference bin/ispc: {ispc_path}"
        )

    # ── Bug 3: missing libjpeg-turbo dep for libtiff ───────────────
    def test_bug3_libtiff_has_jpeg_dep(self):
        """libtiff must depend on libjpeg-turbo for JPEG codec."""
        assert "libjpeg-turbo" in self.projects["libtiff"]["depends"], (
            "libtiff must list libjpeg-turbo in DEPENDS"
        )

    # ── Bug 4: missing OpenColorIO dep for OpenImageIO ─────────────
    def test_bug4_oiio_has_ocio_dep(self):
        """OpenImageIO must depend on OpenColorIO."""
        assert "OpenColorIO" in self.projects["OpenImageIO"]["depends"], (
            "OpenImageIO must list OpenColorIO in DEPENDS"
        )

    # ── Bug 5: USD version incompatible with OpenEXR 3.x ──────────
    def test_bug5_usd_version(self):
        """USD GIT_TAG must be v23.08 for OpenEXR 3.x compatibility."""
        tag = self.projects["USD"]["git_tag"]
        assert tag == "v23.08", f"USD GIT_TAG should be v23.08, got {tag}"

    # ── Bug 6: OpenEXR must be shared (not static even with PIC) ───
    def test_bug6_openexr_shared_libs(self):
        """OpenEXR must be built as shared library (BUILD_SHARED_LIBS=ON).

        The error log misleadingly suggests CMAKE_POSITION_INDEPENDENT_CODE=ON,
        but the build spec requires shared libraries for the renderer plugin
        system's dynamic loading. Static with PIC is insufficient.
        """
        val = self.projects["OpenEXR"]["cmake_args"].get(
            "BUILD_SHARED_LIBS", ""
        )
        assert val.upper() == "ON", (
            f"OpenEXR BUILD_SHARED_LIBS must be ON, got {val!r}. "
            f"CMAKE_POSITION_INDEPENDENT_CODE alone is insufficient — "
            f"the build spec requires shared libraries."
        )

    # ── Bug 7: OpenSubdiv missing NO_TUTORIALS for headless build ──
    def test_bug7_opensubdiv_no_tutorials(self):
        """OpenSubdiv must disable tutorials (NO_TUTORIALS=ON)."""
        val = self.projects["OpenSubdiv"]["cmake_args"].get(
            "NO_TUTORIALS", ""
        )
        assert val.upper() in ("ON", "1", "TRUE"), (
            f"OpenSubdiv must have NO_TUTORIALS=ON for headless build, "
            f"got {val!r}"
        )

    # ── Bug 8: TBB version too old for oneAPI interface ────────────
    def test_bug8_tbb_version(self):
        """TBB must be v2021.1+ for oneapi::tbb namespace."""
        tag = self.projects["TBB"]["git_tag"]
        assert tag is not None, "TBB must have a GIT_TAG"
        match = re.match(r"v(\d+)", tag)
        assert match, f"TBB GIT_TAG should match vYYYY pattern, got {tag}"
        year = int(match.group(1))
        assert year >= 2021, (
            f"TBB version must be 2021 or later for oneAPI interface, "
            f"got {tag}"
        )

    # ── Preservation: correct deps must not be removed ─────────────
    def test_preserved_openexr_zlib_dep(self):
        assert "zlib" in self.projects["OpenEXR"]["depends"]

    def test_preserved_ocio_openexr_dep(self):
        assert "OpenEXR" in self.projects["OpenColorIO"]["depends"]

    def test_preserved_libtiff_zlib_dep(self):
        assert "zlib" in self.projects["libtiff"]["depends"]

    def test_preserved_embree_deps(self):
        assert "ISPC" in self.projects["Embree"]["depends"]
        assert "TBB" in self.projects["Embree"]["depends"]

    def test_preserved_usd_deps(self):
        for dep in ["Boost", "TBB", "OpenEXR", "OpenSubdiv", "OpenImageIO"]:
            assert dep in self.projects["USD"]["depends"], (
                f"USD should still depend on {dep}"
            )

    def test_preserved_oiio_other_deps(self):
        for dep in ["OpenEXR", "libtiff", "Boost"]:
            assert dep in self.projects["OpenImageIO"]["depends"], (
                f"OpenImageIO should still depend on {dep}"
            )

    def test_preserved_opensubdiv_tbb_dep(self):
        assert "TBB" in self.projects["OpenSubdiv"]["depends"]

    def test_preserved_opensubdiv_existing_flags(self):
        args = self.projects["OpenSubdiv"]["cmake_args"]
        for flag in ["NO_PTEX", "NO_OMP", "NO_CUDA", "NO_REGRESSION"]:
            assert args.get(flag, "").upper() in ("ON", "1", "TRUE"), (
                f"OpenSubdiv should still have {flag}=ON"
            )


# ───────────────────────────────────────────────────────────────────────
# Test suite: build audit report
# ───────────────────────────────────────────────────────────────────────


class TestBuildAudit:
    """Verify /app/build_audit.json."""

    @pytest.fixture(autouse=True)
    def setup(self):
        report_path = "/app/build_audit.json"
        assert os.path.exists(report_path), (
            f"build_audit.json not found at {report_path}"
        )
        with open(report_path) as f:
            self.report = json.load(f)

    def test_required_fields(self):
        """Report must contain all required top-level fields."""
        required = [
            "dependency_graph",
            "topological_order",
            "critical_path",
            "critical_path_length",
            "max_parallelism",
            "bugs_found",
            "build_schedule",
            "schedule_makespan",
        ]
        for field in required:
            assert field in self.report, f"Missing field: {field}"

    def test_dependency_graph_correct(self):
        """Dependency graph must match the corrected build specification."""
        graph = self.report["dependency_graph"]

        for project, deps in CORRECT_GRAPH.items():
            assert project in graph, f"Missing project in graph: {project}"
            assert set(graph[project]) == deps, (
                f"Wrong deps for {project}: "
                f"expected {sorted(deps)}, got {sorted(graph[project])}"
            )

        assert set(graph.keys()) == ALL_PROJECTS, (
            f"Unexpected projects in graph: "
            f"{set(graph.keys()) - ALL_PROJECTS}"
        )

    def test_topological_order_valid(self):
        """Topological order must respect all dependency edges."""
        order = self.report["topological_order"]
        graph = self.report["dependency_graph"]

        assert len(order) == len(graph), (
            f"Topological order has {len(order)} items, "
            f"graph has {len(graph)} projects"
        )
        assert set(order) == set(graph.keys()), (
            "Topological order doesn't contain exactly the graph's projects"
        )
        assert len(order) == len(set(order)), (
            "Duplicate entries in topological order"
        )

        position = {name: i for i, name in enumerate(order)}
        for project in graph:
            for dep in graph[project]:
                assert position[dep] < position[project], (
                    f"Invalid order: {dep} (pos {position[dep]}) must come "
                    f"before {project} (pos {position[project]})"
                )

    def test_critical_path_valid_chain(self):
        """Critical path must be a valid dependency chain."""
        path = self.report["critical_path"]
        length = self.report["critical_path_length"]
        graph = self.report["dependency_graph"]

        assert len(path) == length, (
            f"Path list length ({len(path)}) doesn't match "
            f"critical_path_length ({length})"
        )

        for i in range(1, len(path)):
            assert path[i - 1] in graph[path[i]], (
                f"{path[i-1]} must be a direct dependency of {path[i]}"
            )

    def test_critical_path_length(self):
        """Critical path length must be 5."""
        assert self.report["critical_path_length"] == 5, (
            f"Critical path length should be 5, "
            f"got {self.report['critical_path_length']}"
        )

    def test_max_parallelism(self):
        """Max parallelism must be 6 (all root-level projects)."""
        assert self.report["max_parallelism"] == 6, (
            f"Max parallelism should be 6, "
            f"got {self.report['max_parallelism']}"
        )

    def test_bugs_found_count(self):
        """Must identify at least 8 bugs."""
        bugs = self.report["bugs_found"]
        assert len(bugs) >= 8, (
            f"Expected at least 8 bugs, found {len(bugs)}"
        )

    def test_bugs_found_structure(self):
        """Each bug entry must have project, type, fix, and root_cause_chain."""
        for i, bug in enumerate(self.report["bugs_found"]):
            assert "project" in bug, f"Bug {i} missing 'project' field"
            assert "type" in bug, f"Bug {i} missing 'type' field"
            assert "fix" in bug, f"Bug {i} missing 'fix' field"
            assert "root_cause_chain" in bug, (
                f"Bug {i} missing 'root_cause_chain' field"
            )
            assert len(str(bug["root_cause_chain"])) >= 20, (
                f"Bug {i} root_cause_chain is too short to be meaningful"
            )

    def test_bugs_found_projects(self):
        """Bugs must be attributed to the correct projects."""
        bugs = self.report["bugs_found"]
        bug_projects = {b["project"] for b in bugs}
        required = {
            "OpenEXR", "Embree", "libtiff", "OpenImageIO",
            "USD", "OpenSubdiv", "TBB",
        }
        for proj in required:
            assert proj in bug_projects, f"No bug reported for {proj}"


# ───────────────────────────────────────────────────────────────────────
# Test suite: memory-constrained build schedule
# ───────────────────────────────────────────────────────────────────────


class TestBuildSchedule:
    """Verify the memory-constrained parallel build schedule."""

    @pytest.fixture(autouse=True)
    def setup(self):
        report_path = "/app/build_audit.json"
        with open(report_path) as f:
            self.report = json.load(f)
        self.schedule = self.report.get("build_schedule", [])

    def test_schedule_makespan(self):
        """Optimal makespan under 7 GB constraint must be 5."""
        assert self.report["schedule_makespan"] == 5, (
            f"Schedule makespan should be 5, "
            f"got {self.report['schedule_makespan']}"
        )
        assert len(self.schedule) == 5, (
            f"Schedule should have 5 stages, has {len(self.schedule)}"
        )

    def test_schedule_contains_all_projects(self):
        """All 13 projects must appear exactly once across all stages."""
        all_projects = []
        for stage in self.schedule:
            all_projects.extend(stage)
        assert len(all_projects) == 13, (
            f"Schedule should contain 13 projects, has {len(all_projects)}"
        )
        assert set(all_projects) == ALL_PROJECTS, (
            f"Schedule projects don't match expected set. "
            f"Missing: {ALL_PROJECTS - set(all_projects)}, "
            f"Extra: {set(all_projects) - ALL_PROJECTS}"
        )
        assert len(all_projects) == len(set(all_projects)), (
            "Duplicate project in schedule"
        )

    def test_schedule_memory_constraint(self):
        """Each stage must not exceed 7 GB peak memory."""
        for i, stage in enumerate(self.schedule):
            total_mem = sum(MEMORY_COSTS[p] for p in stage)
            assert total_mem <= MEMORY_BUDGET + 0.001, (
                f"Stage {i} exceeds {MEMORY_BUDGET} GB budget: "
                f"{stage} = {total_mem} GB"
            )

    def test_schedule_dependency_order(self):
        """All dependencies must be scheduled in earlier stages."""
        project_stage = {}
        for i, stage in enumerate(self.schedule):
            for project in stage:
                project_stage[project] = i

        for project, deps in CORRECT_GRAPH.items():
            for dep in deps:
                assert dep in project_stage, (
                    f"Dependency {dep} of {project} not found in schedule"
                )
                assert project_stage[dep] < project_stage[project], (
                    f"Dependency violation: {dep} (stage "
                    f"{project_stage[dep]}) must be scheduled before "
                    f"{project} (stage {project_stage[project]})"
                )
