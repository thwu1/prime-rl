
import json
import os
import pytest


EXPECTED_PACKAGES = sorted([
    "zlib", "openssl", "xz", "libjpeg-turbo", "openblas", "python",
    "libpng", "libtiff", "sqlite", "libcurl",
    "libhdf5", "hdf5-tools",
    "libxml2", "proj", "netcdf4-c",
    "libgdal", "gdal-python",
    "numpy", "scipy", "h5py", "netcdf4-python", "rasterio",
    "geos",
])

EXPECTED_HOST_DEPS = {
    "geos": [],
    "zlib": [],
    "openssl": [],
    "xz": [],
    "libjpeg-turbo": [],
    "openblas": [],
    "python": sorted(["openssl", "sqlite", "xz", "zlib"]),
    "libpng": ["zlib"],
    "libtiff": sorted(["libjpeg-turbo", "xz", "zlib"]),
    "sqlite": ["zlib"],
    "libcurl": sorted(["openssl", "zlib"]),
    "libhdf5": sorted(["openssl", "zlib"]),
    "hdf5-tools": sorted(["libhdf5", "zlib"]),
    "libxml2": sorted(["xz", "zlib"]),
    "proj": sorted(["geos", "libcurl", "libtiff", "sqlite"]),
    "netcdf4-c": sorted(["libcurl", "libhdf5", "zlib"]),
    "libgdal": sorted([
        "libcurl", "libhdf5", "libpng", "libtiff",
        "libxml2", "netcdf4-c", "proj",
    ]),
    "gdal-python": sorted(["libgdal", "numpy", "python"]),
    "numpy": sorted(["openblas", "python"]),
    "scipy": sorted(["numpy", "openblas", "python"]),
    "h5py": sorted(["libhdf5", "numpy", "python"]),
    "netcdf4-python": sorted(["libhdf5", "netcdf4-c", "numpy", "python"]),
    "rasterio": sorted(["libgdal", "numpy", "python"]),
}

MIGRATED_OUTPUTS = {"libhdf5", "hdf5-tools"}

EXPECTED_DIRECTLY_AFFECTED = sorted(["h5py", "libgdal", "netcdf4-c", "netcdf4-python"])
EXPECTED_TRANSITIVELY_AFFECTED = sorted(["gdal-python", "rasterio"])
EXPECTED_ALL_AFFECTED = sorted(
    EXPECTED_DIRECTLY_AFFECTED + EXPECTED_TRANSITIVELY_AFFECTED
)

# Expected run_exports analysis: packages with valid run_exports declarations
EXPECTED_RUN_EXPORTS_SUBSET = {
    "zlib": {"max_pin": "x.x", "constraint": ">=1.3.1,<1.4.0a0"},
    "openssl": {"max_pin": "x.x.x", "constraint": ">=3.3.0,<3.3.1.0a0"},
    "xz": {"max_pin": "x", "constraint": ">=5.4.6,<6.0a0"},
    "libjpeg-turbo": {"max_pin": "x", "constraint": ">=3.0.0,<4.0a0"},
    "openblas": {"max_pin": "x.x.x", "constraint": ">=0.3.27,<0.3.28.0a0"},
    "sqlite": {"max_pin": "x", "constraint": ">=3.45.2,<4.0a0"},
    "libpng": {"max_pin": "x.x", "constraint": ">=1.6.43,<1.7.0a0"},
    "libtiff": {"max_pin": "x", "constraint": ">=4.6.0,<5.0a0"},
    "libcurl": {"max_pin": "x", "constraint": ">=8.7.1,<9.0a0"},
    "libhdf5": {"max_pin": "x.x", "constraint": ">=1.14.4,<1.15.0a0"},
    "libxml2": {"max_pin": "x", "constraint": ">=2.12.6,<3.0a0"},
    "netcdf4-c": {"max_pin": "x.x.x", "constraint": ">=4.9.2,<4.9.3.0a0"},
    "proj": {"max_pin": "x.x.x", "constraint": ">=9.3.1,<9.3.2.0a0"},
    "libgdal": {"max_pin": "x.x", "constraint": ">=3.8.4,<3.9.0a0"},
    "numpy": {"max_pin": "x", "constraint": ">=1.26.4,<2.0a0"},
}

PACKAGES_WITH_RUN_EXPORTS = set(EXPECTED_RUN_EXPORTS_SUBSET.keys())


@pytest.fixture
def audit():
    with open("/app/output/audit.json") as f:
        return json.load(f)


class TestAuditExists:
    def test_output_dir(self):
        assert os.path.isdir("/app/output"), "/app/output directory missing"

    def test_audit_file(self):
        assert os.path.isfile("/app/output/audit.json"), "audit.json missing"

    def test_audit_valid_json(self):
        with open("/app/output/audit.json") as f:
            data = json.load(f)
        assert isinstance(data, dict), "audit.json must be a JSON object"

    def test_required_keys(self, audit):
        required = {
            "packages", "dependency_graph", "run_exports_analysis",
            "build_order", "migration_detected", "directly_affected",
            "transitively_affected", "rebuild_order", "pin_conflicts",
            "recipe_diagnostics",
        }
        missing = required - set(audit.keys())
        assert not missing, f"Missing top-level keys: {missing}"


class TestPackages:
    def test_all_packages_present(self, audit):
        packages = audit["packages"]
        assert isinstance(packages, list), "packages must be a JSON array"
        assert sorted(packages) == EXPECTED_PACKAGES, (
            f"Expected {EXPECTED_PACKAGES}, got {sorted(packages)}"
        )

    def test_no_duplicates(self, audit):
        packages = audit["packages"]
        assert len(packages) == len(set(packages)), "Duplicate package names"

    def test_count(self, audit):
        assert len(audit["packages"]) == 23, (
            f"Expected 23 packages, got {len(audit['packages'])}"
        )


class TestDependencyGraph:
    def test_is_dict(self, audit):
        assert isinstance(audit["dependency_graph"], dict)

    def test_all_packages_present(self, audit):
        assert sorted(audit["dependency_graph"].keys()) == EXPECTED_PACKAGES

    def test_geos_deps(self, audit):
        assert sorted(audit["dependency_graph"]["geos"]) == []

    def test_zlib_deps(self, audit):
        assert sorted(audit["dependency_graph"]["zlib"]) == []

    def test_openssl_deps(self, audit):
        assert sorted(audit["dependency_graph"]["openssl"]) == []

    def test_python_deps(self, audit):
        assert sorted(audit["dependency_graph"]["python"]) == EXPECTED_HOST_DEPS["python"]

    def test_libpng_deps(self, audit):
        assert sorted(audit["dependency_graph"]["libpng"]) == EXPECTED_HOST_DEPS["libpng"]

    def test_libtiff_deps(self, audit):
        assert sorted(audit["dependency_graph"]["libtiff"]) == EXPECTED_HOST_DEPS["libtiff"]

    def test_sqlite_deps(self, audit):
        assert sorted(audit["dependency_graph"]["sqlite"]) == EXPECTED_HOST_DEPS["sqlite"]

    def test_libcurl_deps(self, audit):
        assert sorted(audit["dependency_graph"]["libcurl"]) == EXPECTED_HOST_DEPS["libcurl"]

    def test_libhdf5_deps(self, audit):
        assert sorted(audit["dependency_graph"]["libhdf5"]) == EXPECTED_HOST_DEPS["libhdf5"]

    def test_hdf5_tools_deps(self, audit):
        assert sorted(audit["dependency_graph"]["hdf5-tools"]) == EXPECTED_HOST_DEPS["hdf5-tools"]

    def test_libxml2_deps(self, audit):
        assert sorted(audit["dependency_graph"]["libxml2"]) == EXPECTED_HOST_DEPS["libxml2"]

    def test_proj_deps(self, audit):
        assert sorted(audit["dependency_graph"]["proj"]) == EXPECTED_HOST_DEPS["proj"]

    def test_netcdf4_c_deps(self, audit):
        assert sorted(audit["dependency_graph"]["netcdf4-c"]) == EXPECTED_HOST_DEPS["netcdf4-c"]

    def test_libgdal_deps(self, audit):
        assert sorted(audit["dependency_graph"]["libgdal"]) == EXPECTED_HOST_DEPS["libgdal"]

    def test_gdal_python_deps(self, audit):
        assert sorted(audit["dependency_graph"]["gdal-python"]) == EXPECTED_HOST_DEPS["gdal-python"]

    def test_numpy_deps(self, audit):
        assert sorted(audit["dependency_graph"]["numpy"]) == EXPECTED_HOST_DEPS["numpy"]

    def test_scipy_deps(self, audit):
        assert sorted(audit["dependency_graph"]["scipy"]) == EXPECTED_HOST_DEPS["scipy"]

    def test_h5py_deps(self, audit):
        assert sorted(audit["dependency_graph"]["h5py"]) == EXPECTED_HOST_DEPS["h5py"]

    def test_netcdf4_python_deps(self, audit):
        assert sorted(audit["dependency_graph"]["netcdf4-python"]) == EXPECTED_HOST_DEPS["netcdf4-python"]

    def test_rasterio_deps(self, audit):
        assert sorted(audit["dependency_graph"]["rasterio"]) == EXPECTED_HOST_DEPS["rasterio"]

    def test_no_compiler_deps(self, audit):
        for pkg, deps in audit["dependency_graph"].items():
            for dep in deps:
                assert "compiler" not in dep.lower(), (
                    f"{pkg} has compiler dep '{dep}'"
                )

    def test_no_build_tools(self, audit):
        build_tools = {"cmake", "ninja", "make", "pkg-config", "autoconf",
                       "automake", "libtool", "nasm", "cython", "pythran",
                       "perl"}
        for pkg, deps in audit["dependency_graph"].items():
            for dep in deps:
                assert dep not in build_tools, (
                    f"{pkg} has build tool '{dep}'"
                )


class TestRunExportsAnalysis:
    def test_is_dict(self, audit):
        assert isinstance(audit["run_exports_analysis"], dict)

    def test_expected_packages_have_run_exports(self, audit):
        re_analysis = audit["run_exports_analysis"]
        for pkg in PACKAGES_WITH_RUN_EXPORTS:
            assert pkg in re_analysis, (
                f"Package '{pkg}' should be in run_exports_analysis"
            )

    def test_geos_not_in_run_exports(self, audit):
        re_analysis = audit["run_exports_analysis"]
        assert "geos" not in re_analysis, (
            "geos has broken run_exports and should not be in analysis"
        )

    def test_zlib_constraint(self, audit):
        entry = audit["run_exports_analysis"]["zlib"]
        assert entry["max_pin"] == "x.x"
        assert entry["constraint"] == ">=1.3.1,<1.4.0a0"

    def test_openssl_constraint(self, audit):
        entry = audit["run_exports_analysis"]["openssl"]
        assert entry["max_pin"] == "x.x.x"
        assert entry["constraint"] == ">=3.3.0,<3.3.1.0a0"

    def test_xz_constraint(self, audit):
        entry = audit["run_exports_analysis"]["xz"]
        assert entry["max_pin"] == "x"
        assert entry["constraint"] == ">=5.4.6,<6.0a0"

    def test_libhdf5_constraint(self, audit):
        entry = audit["run_exports_analysis"]["libhdf5"]
        assert entry["max_pin"] == "x.x"
        assert entry["constraint"] == ">=1.14.4,<1.15.0a0"

    def test_openblas_constraint(self, audit):
        entry = audit["run_exports_analysis"]["openblas"]
        assert entry["max_pin"] == "x.x.x"
        assert entry["constraint"] == ">=0.3.27,<0.3.28.0a0"

    def test_numpy_constraint(self, audit):
        entry = audit["run_exports_analysis"]["numpy"]
        assert entry["max_pin"] == "x"
        assert entry["constraint"] == ">=1.26.4,<2.0a0"

    def test_libgdal_constraint(self, audit):
        entry = audit["run_exports_analysis"]["libgdal"]
        assert entry["max_pin"] == "x.x"
        assert entry["constraint"] == ">=3.8.4,<3.9.0a0"

    def test_netcdf4c_constraint(self, audit):
        entry = audit["run_exports_analysis"]["netcdf4-c"]
        assert entry["max_pin"] == "x.x.x"
        assert entry["constraint"] == ">=4.9.2,<4.9.3.0a0"

    def test_proj_constraint(self, audit):
        entry = audit["run_exports_analysis"]["proj"]
        assert entry["max_pin"] == "x.x.x"
        assert entry["constraint"] == ">=9.3.1,<9.3.2.0a0"

    def test_no_packages_without_run_exports(self, audit):
        no_re = {"python", "hdf5-tools", "scipy", "h5py",
                 "netcdf4-python", "rasterio", "gdal-python"}
        for pkg in no_re:
            assert pkg not in audit["run_exports_analysis"], (
                f"'{pkg}' should not be in run_exports_analysis"
            )


class TestBuildOrder:
    def test_is_list(self, audit):
        assert isinstance(audit["build_order"], list)

    def test_contains_all_packages(self, audit):
        assert sorted(audit["build_order"]) == EXPECTED_PACKAGES

    def test_no_duplicates(self, audit):
        order = audit["build_order"]
        assert len(order) == len(set(order))

    def test_valid_topological_order(self, audit):
        graph = audit["dependency_graph"]
        order = audit["build_order"]
        position = {pkg: i for i, pkg in enumerate(order)}
        violations = []
        for pkg, deps in graph.items():
            for dep in deps:
                if dep in position and position[dep] >= position[pkg]:
                    violations.append(
                        f"{dep} (pos {position[dep]}) must come before "
                        f"{pkg} (pos {position[pkg]})"
                    )
        assert not violations, (
            f"Topological order violations:\n" + "\n".join(violations)
        )


class TestMigrationDetection:
    def test_migration_detected(self, audit):
        m = audit["migration_detected"]
        assert m is not None, "No migration detected"
        assert isinstance(m, dict)

    def test_primary_package(self, audit):
        assert audit["migration_detected"]["primary_package"] == "libhdf5"

    def test_recipe_version(self, audit):
        assert audit["migration_detected"]["recipe_version"] == "1.14.4"

    def test_pinned_version(self, audit):
        assert audit["migration_detected"]["pinned_version"] == "1.14.3"

    def test_all_migrated_outputs(self, audit):
        outputs = sorted(audit["migration_detected"]["all_migrated_outputs"])
        assert outputs == sorted(["libhdf5", "hdf5-tools"]), (
            f"Expected migrated outputs ['hdf5-tools', 'libhdf5'], got {outputs}"
        )


class TestImpactAnalysis:
    def test_directly_affected(self, audit):
        directly = sorted(audit["directly_affected"])
        assert directly == EXPECTED_DIRECTLY_AFFECTED, (
            f"Expected directly_affected={EXPECTED_DIRECTLY_AFFECTED}, "
            f"got {directly}"
        )

    def test_directly_affected_excludes_migrated(self, audit):
        for pkg in MIGRATED_OUTPUTS:
            assert pkg not in audit["directly_affected"], (
                f"Migrated output '{pkg}' should not be in directly_affected"
            )

    def test_transitively_affected(self, audit):
        transitively = sorted(audit["transitively_affected"])
        assert transitively == EXPECTED_TRANSITIVELY_AFFECTED, (
            f"Expected transitively_affected={EXPECTED_TRANSITIVELY_AFFECTED}, "
            f"got {transitively}"
        )

    def test_transitively_affected_excludes_migrated(self, audit):
        for pkg in MIGRATED_OUTPUTS:
            assert pkg not in audit["transitively_affected"]

    def test_no_overlap(self, audit):
        direct = set(audit["directly_affected"])
        transitive = set(audit["transitively_affected"])
        assert not direct & transitive, (
            f"Overlap between directly and transitively affected: "
            f"{direct & transitive}"
        )


class TestRebuildOrder:
    def test_contains_all_affected(self, audit):
        rebuild = audit["rebuild_order"]
        assert sorted(rebuild) == EXPECTED_ALL_AFFECTED, (
            f"Expected all affected={EXPECTED_ALL_AFFECTED}, "
            f"got {sorted(rebuild)}"
        )

    def test_rebuild_order_valid(self, audit):
        graph = audit["dependency_graph"]
        rebuild = audit["rebuild_order"]
        affected_set = set(rebuild)
        position = {pkg: i for i, pkg in enumerate(rebuild)}
        violations = []
        for pkg in rebuild:
            for dep in graph.get(pkg, []):
                if dep in affected_set and position[dep] >= position[pkg]:
                    violations.append(
                        f"{dep} (pos {position[dep]}) must come before "
                        f"{pkg} (pos {position[pkg]})"
                    )
        assert not violations, (
            f"Rebuild order violations:\n" + "\n".join(violations)
        )

    def test_netcdf4c_before_libgdal(self, audit):
        order = audit["rebuild_order"]
        assert order.index("netcdf4-c") < order.index("libgdal")

    def test_libgdal_before_gdal_python(self, audit):
        order = audit["rebuild_order"]
        assert order.index("libgdal") < order.index("gdal-python")

    def test_libgdal_before_rasterio(self, audit):
        order = audit["rebuild_order"]
        assert order.index("libgdal") < order.index("rasterio")


class TestPinConflicts:
    def test_is_list(self, audit):
        assert isinstance(audit["pin_conflicts"], list)

    def test_conflict_count(self, audit):
        assert len(audit["pin_conflicts"]) == 2, (
            f"Expected 2 pin conflict entries, got {len(audit['pin_conflicts'])}"
        )

    def test_netcdf4c_conflict(self, audit):
        entries = [c for c in audit["pin_conflicts"]
                   if c["package"] == "netcdf4-c"]
        assert len(entries) == 1, "Missing netcdf4-c conflict entry"
        c = entries[0]
        assert c["dependency"] == "libhdf5"
        assert c["satisfiable"] is False
        assert "1.14.4" in str(c.get("new_version", ""))

    def test_netcdf4c_constraint_string(self, audit):
        entries = [c for c in audit["pin_conflicts"]
                   if c["package"] == "netcdf4-c"]
        c = entries[0]
        assert "1.14.4a0" in c["constraint"] or "1.14.4" in c["constraint"]

    def test_h5py_constraint(self, audit):
        entries = [c for c in audit["pin_conflicts"]
                   if c["package"] == "h5py"]
        assert len(entries) == 1, "Missing h5py constraint entry"
        c = entries[0]
        assert c["dependency"] == "libhdf5"
        assert c["satisfiable"] is True

    def test_conflict_required_keys(self, audit):
        required = {"package", "dependency", "constraint", "new_version",
                     "satisfiable"}
        for c in audit["pin_conflicts"]:
            missing = required - set(c.keys())
            assert not missing, (
                f"Conflict entry for {c.get('package', '?')} missing keys: "
                f"{missing}"
            )


class TestRecipeDiagnostics:
    def test_is_list(self, audit):
        assert isinstance(audit["recipe_diagnostics"], list)

    def test_at_least_one_diagnostic(self, audit):
        assert len(audit["recipe_diagnostics"]) >= 1, (
            "Expected at least one recipe diagnostic"
        )

    def test_geos_diagnostic_detected(self, audit):
        geos_diags = [d for d in audit["recipe_diagnostics"]
                      if d.get("feedstock") == "geos"]
        assert len(geos_diags) >= 1, (
            "Expected diagnostic for geos feedstock"
        )

    def test_geos_diagnostic_mentions_lib_name(self, audit):
        geos_diags = [d for d in audit["recipe_diagnostics"]
                      if d.get("feedstock") == "geos"]
        diag = geos_diags[0]
        all_values = " ".join(str(v) for v in diag.values())
        assert "lib_name" in all_values, (
            "Geos diagnostic should mention 'lib_name' as the problematic reference"
        )

    def test_diagnostic_required_keys(self, audit):
        required = {"feedstock", "issue", "detail"}
        for d in audit["recipe_diagnostics"]:
            missing = required - set(d.keys())
            assert not missing, (
                f"Diagnostic for {d.get('feedstock', '?')} missing keys: "
                f"{missing}"
            )
