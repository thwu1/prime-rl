import json
import os
import subprocess
import pytest


LOCK_PATH = "/app/env/spack.lock"


def _spack_env():
    """Return env dict with spack on PATH."""
    env = os.environ.copy()
    env["SPACK_ROOT"] = "/opt/spack"
    env["PATH"] = "/opt/spack/bin:" + env.get("PATH", "")
    return env


@pytest.fixture(scope="session")
def concretize():
    """Run spack concretize --force and return the subprocess result."""
    result = subprocess.run(
        ["spack", "-e", "/app/env", "concretize", "--force"],
        capture_output=True,
        text=True,
        timeout=180,
        env=_spack_env(),
    )
    return result


@pytest.fixture(scope="session")
def lock_data(concretize):
    """Parse spack.lock after successful concretization."""
    assert concretize.returncode == 0, (
        f"spack concretize failed (exit {concretize.returncode}):\n"
        f"{concretize.stderr[-2000:]}"
    )
    assert os.path.exists(LOCK_PATH), "spack.lock was not generated"
    with open(LOCK_PATH) as f:
        data = json.load(f)
    assert "concrete_specs" in data, (
        f"Unexpected lockfile format, keys: {list(data.keys())}"
    )
    return data


@pytest.fixture(scope="session")
def specs_by_name(lock_data):
    """Map package name -> spec data from the lockfile."""
    result = {}
    for _hash, spec_data in lock_data["concrete_specs"].items():
        name = spec_data.get("name", "")
        result[name] = spec_data
    return result


# ---------------------------------------------------------------------------
# Concretization success
# ---------------------------------------------------------------------------
class TestConcretization:
    def test_concretize_succeeds(self, concretize):
        assert concretize.returncode == 0, (
            f"Concretization failed:\n{concretize.stderr[-2000:]}"
        )

    def test_lock_file_generated(self, concretize):
        assert concretize.returncode == 0
        assert os.path.exists(LOCK_PATH), "spack.lock not found after concretize"

    def test_lock_file_valid_structure(self, lock_data):
        assert "concrete_specs" in lock_data
        assert len(lock_data["concrete_specs"]) > 0, "No concrete specs in lockfile"


# ---------------------------------------------------------------------------
# Root specs present
# ---------------------------------------------------------------------------
class TestRootSpecs:
    def test_scisolver_present(self, specs_by_name):
        assert "scisolver" in specs_by_name, (
            f"scisolver missing from DAG. Found: {sorted(specs_by_name.keys())}"
        )

    def test_scifft_present(self, specs_by_name):
        assert "scifft" in specs_by_name, (
            f"scifft missing from DAG. Found: {sorted(specs_by_name.keys())}"
        )


# ---------------------------------------------------------------------------
# scisolver variant correctness
# ---------------------------------------------------------------------------
class TestScisolverVariants:
    def test_scisolver_mpi_enabled(self, specs_by_name):
        params = specs_by_name["scisolver"].get("parameters", {})
        assert params.get("mpi") is True, (
            f"scisolver should have +mpi, got parameters: {params}"
        )

    def test_scisolver_has_debug_variant(self, specs_by_name):
        params = specs_by_name["scisolver"].get("parameters", {})
        assert "debug" in params, (
            f"scisolver should define a debug variant, got parameters: {params}"
        )


# ---------------------------------------------------------------------------
# scifft variant correctness
# ---------------------------------------------------------------------------
class TestScifftVariants:
    def test_scifft_mpi_enabled(self, specs_by_name):
        params = specs_by_name["scifft"].get("parameters", {})
        assert params.get("mpi") is True, (
            f"scifft should have +mpi, got parameters: {params}"
        )

    def test_scifft_precision_double(self, specs_by_name):
        params = specs_by_name["scifft"].get("parameters", {})
        assert params.get("precision") == "double", (
            f"scifft should have precision=double, got: {params.get('precision')}"
        )


# ---------------------------------------------------------------------------
# Virtual provider resolution
# ---------------------------------------------------------------------------
class TestProviderResolution:
    def test_scicomm_ng_is_provider(self, specs_by_name):
        """scicomm-ng must be chosen as the scimpi provider (provides @3.1)."""
        assert "scicomm-ng" in specs_by_name, (
            f"scicomm-ng missing — was the scimpi@3.1 provider created? "
            f"Found: {sorted(specs_by_name.keys())}"
        )

    def test_old_scicomm_not_in_dag(self, specs_by_name):
        """scicomm (provides only @:2.0) should not be selected since @3: is required."""
        assert "scicomm" not in specs_by_name, (
            f"scicomm should not be in the DAG — it only provides scimpi@:2.0 "
            f"but scimpi@3: is required. Found: {sorted(specs_by_name.keys())}"
        )


# ---------------------------------------------------------------------------
# Dependency graph verification
# ---------------------------------------------------------------------------
class TestDependencyGraph:
    def test_scibase_version_at_least_1_2(self, specs_by_name):
        """scibase must be >= 1.2."""
        assert "scibase" in specs_by_name, "scibase missing from DAG"
        version = specs_by_name["scibase"]["version"]
        parts = [int(x) for x in version.split(".")]
        assert (parts[0], parts[1]) >= (1, 2), (
            f"scibase {version} too old, need >= 1.2.0"
        )

    def test_scilinalg_present(self, specs_by_name):
        assert "scilinalg" in specs_by_name, (
            f"scilinalg missing from DAG. Found: {sorted(specs_by_name.keys())}"
        )

    def test_scilinalg_mpi_enabled(self, specs_by_name):
        """scilinalg must have +mpi (propagated from scisolver dependency)."""
        assert "scilinalg" in specs_by_name
        params = specs_by_name["scilinalg"].get("parameters", {})
        assert params.get("mpi") is True, (
            f"scilinalg should have +mpi (required by scisolver), got: {params}"
        )

    def test_scilinalg_has_precision(self, specs_by_name):
        """scilinalg must have a precision variant with value double."""
        assert "scilinalg" in specs_by_name
        params = specs_by_name["scilinalg"].get("parameters", {})
        assert params.get("precision") == "double", (
            f"scilinalg should have precision=double, got: {params.get('precision')}"
        )

    def test_all_core_packages_present(self, specs_by_name):
        """All expected core packages must be in the dependency graph."""
        expected = {"scisolver", "scifft", "scilinalg", "scibase", "scicomm-ng"}
        found = set(specs_by_name.keys())
        missing = expected - found
        assert not missing, (
            f"Missing packages: {missing}. Found: {sorted(found)}"
        )

    def test_minimum_package_count(self, specs_by_name):
        """DAG should contain at least 5 packages."""
        assert len(specs_by_name) >= 5, (
            f"Expected at least 5 packages, found {len(specs_by_name)}: "
            f"{sorted(specs_by_name.keys())}"
        )
