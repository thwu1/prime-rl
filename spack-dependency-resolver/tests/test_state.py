"""
Tests for the ASP-based package dependency resolver.

Verifies that the resolver uses clingo/ASP for constraint solving, and that
it correctly handles version selection, virtual package resolution, conflict
detection, conditional dependencies, variant propagation, and topological ordering.
"""

import os
import sys
sys.path.insert(0, '/app')

import pytest
from models import Version, UnsatisfiableSpecError, ConflictError


@pytest.fixture
def resolver():
    from resolver import Resolver
    return Resolver('/app/packages.json')


# ---------------------------------------------------------------------------
# ASP / clingo implementation verification
# ---------------------------------------------------------------------------

class TestASPImplementation:
    def test_encoding_file_exists(self):
        """The ASP encoding file must exist at /app/encoding.lp."""
        assert os.path.exists('/app/encoding.lp'), \
            "ASP encoding file must exist at /app/encoding.lp"

    def test_encoding_has_asp_rules(self):
        """Encoding must contain ASP rules, optimization, and choice constructs."""
        with open('/app/encoding.lp') as f:
            content = f.read()
        assert ':-' in content, \
            "Encoding must contain ASP rules or integrity constraints (:-)"
        has_opt = any(kw in content for kw in [
            '#minimize', '#maximize', '#minimise', '#maximise'
        ])
        assert has_opt, \
            "Encoding must use ASP optimization directives (#minimize/#maximize)"
        assert '{' in content and '}' in content, \
            "Encoding must use ASP choice rules ({...})"

    def test_resolver_uses_clingo(self):
        """Resolver must import/invoke the clingo solver."""
        with open('/app/resolver.py') as f:
            src = f.read()
        uses_api = 'import clingo' in src or 'from clingo' in src
        uses_cli = ('subprocess' in src or 'os.system' in src) and 'clingo' in src
        assert uses_api or uses_cli, \
            "Resolver must use clingo via Python API or CLI subprocess"

    def test_encoding_parses_in_clingo(self):
        """The encoding must be valid ASP that clingo can parse and ground."""
        import clingo
        ctl = clingo.Control()
        with open('/app/encoding.lp') as f:
            content = f.read()
        ctl.add("test", [], content)
        ctl.ground([("test", [])])

    def test_encoding_not_trivial(self):
        """Encoding must have substantial ASP rules, not a stub."""
        with open('/app/encoding.lp') as f:
            lines = [l.strip() for l in f
                     if l.strip() and not l.strip().startswith('%')]
        assert len(lines) >= 15, \
            f"Encoding has only {len(lines)} non-comment lines; expected >= 15"


# ---------------------------------------------------------------------------
# Version selection
# ---------------------------------------------------------------------------

class TestVersionSelection:
    def test_exact_version(self, resolver):
        """Requesting an exact version produces that version."""
        result = resolver.resolve("zlib@1.3.0")
        assert result.specs["zlib"].version == Version("1.3.0")
        assert len(result.specs) == 1

    def test_version_range_bounded(self, resolver):
        """A bounded range selects the latest version within the range."""
        result = resolver.resolve("zlib@1.2.12:1.3.0")
        assert result.specs["zlib"].version == Version("1.3.0")

    def test_version_range_open(self, resolver):
        """An open-ended lower bound selects the latest available version."""
        result = resolver.resolve("zlib@1.2.12:")
        assert result.specs["zlib"].version == Version("1.3.1")

    def test_no_version_selects_latest(self, resolver):
        """Omitting a version selects the latest available."""
        result = resolver.resolve("zlib")
        assert result.specs["zlib"].version == Version("1.3.1")


# ---------------------------------------------------------------------------
# Dependency chains
# ---------------------------------------------------------------------------

class TestDependencyChains:
    def test_simple_dependency(self, resolver):
        """python depends on zlib; both should appear in the DAG."""
        result = resolver.resolve("python@3.11.0")
        assert "python" in result.specs
        assert "zlib" in result.specs
        assert result.specs["python"].version == Version("3.11.0")
        assert ("python", "zlib") in result.edges

    def test_transitive_dependency(self, resolver):
        """boost (without +python) depends on zlib transitively."""
        result = resolver.resolve("boost ~python")
        assert "boost" in result.specs
        assert "zlib" in result.specs
        assert ("boost", "zlib") in result.edges


# ---------------------------------------------------------------------------
# Virtual packages
# ---------------------------------------------------------------------------

class TestVirtualPackages:
    def test_default_provider(self, resolver):
        """hdf5 +mpi resolves mpi to the first listed provider (openmpi)."""
        result = resolver.resolve("hdf5 +mpi")
        assert "openmpi" in result.specs
        assert "mpich" not in result.specs

    def test_explicit_provider(self, resolver):
        """^mpich forces mpich as the mpi provider."""
        result = resolver.resolve("hdf5 +mpi ^mpich")
        assert "mpich" in result.specs
        assert "openmpi" not in result.specs

    def test_explicit_provider_with_version(self, resolver):
        """^mpich@4.2.0 forces mpich at exactly 4.2.0."""
        result = resolver.resolve("hdf5 +mpi ^mpich@4.2.0")
        assert result.specs["mpich"].version == Version("4.2.0")

    def test_provider_consistency(self, resolver):
        """scipy uses blas and lapack; both must come from the same provider
        (since openblas and intel-mkl each provide both)."""
        result = resolver.resolve("scipy")
        blas_providers = {"openblas", "intel-mkl"}
        found = blas_providers & set(result.specs.keys())
        assert len(found) == 1, (
            f"Expected exactly one blas/lapack provider, got {found}"
        )

    def test_provider_override(self, resolver):
        """^intel-mkl forces intel-mkl as blas/lapack provider for scipy."""
        result = resolver.resolve("scipy ^intel-mkl")
        assert "intel-mkl" in result.specs
        assert "openblas" not in result.specs


# ---------------------------------------------------------------------------
# Conditional dependencies
# ---------------------------------------------------------------------------

class TestConditionalDependencies:
    def test_variant_condition_inactive(self, resolver):
        """hdf5 ~mpi should NOT include any mpi provider."""
        result = resolver.resolve("hdf5 ~mpi")
        assert "openmpi" not in result.specs
        assert "mpich" not in result.specs

    def test_variant_condition_active(self, resolver):
        """hdf5 +mpi should include an mpi provider."""
        result = resolver.resolve("hdf5 +mpi")
        mpi_providers = {"openmpi", "mpich"}
        assert len(mpi_providers & set(result.specs.keys())) == 1

    def test_boost_with_debug(self, resolver):
        """petsc +debug ~complex should include boost."""
        result = resolver.resolve("petsc +debug ~complex")
        assert "boost" in result.specs

    def test_no_boost_without_debug(self, resolver):
        """petsc ~debug ~complex should NOT include boost."""
        result = resolver.resolve("petsc ~debug ~complex")
        assert "boost" not in result.specs

    def test_version_conditional_dep(self, resolver):
        """scipy@1.12.0 activates the numpy@1.24.0: constraint."""
        result = resolver.resolve("scipy@1.12.0")
        assert result.specs["numpy"].version >= Version("1.24.0")

    def test_early_scipy_no_tight_numpy(self, resolver):
        """scipy@1.10.0 does NOT activate the numpy@1.24.0: constraint,
        so numpy@1.23.0 is acceptable."""
        result = resolver.resolve("scipy@1.10.0 ^numpy@1.23.0")
        assert result.specs["numpy"].version == Version("1.23.0")


# ---------------------------------------------------------------------------
# Required dependency variants
# ---------------------------------------------------------------------------

class TestRequiredDepVariants:
    def test_petsc_requires_hdf5_mpi(self, resolver):
        """petsc ~complex depends on hdf5 with required_variants mpi=true."""
        result = resolver.resolve("petsc@3.20.0 ~complex ~debug")
        assert result.specs["hdf5"].variants.get("mpi") is True

    def test_conflicting_user_vs_required(self, resolver):
        """^hdf5 ~mpi conflicts with petsc's required_variants mpi=true."""
        with pytest.raises(UnsatisfiableSpecError):
            resolver.resolve("petsc ~complex ^hdf5 ~mpi")


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------

class TestConflicts:
    def test_variant_conflict(self, resolver):
        """openblas +ilp64 threads=openmp triggers a declared conflict."""
        with pytest.raises((ConflictError, UnsatisfiableSpecError)):
            resolver.resolve("openblas +ilp64 threads=openmp")

    def test_version_variant_conflict(self, resolver):
        """hdf5@1.10.7 +fortran +mpi triggers the Fortran-MPI conflict."""
        with pytest.raises((ConflictError, UnsatisfiableSpecError)):
            resolver.resolve("hdf5@1.10.7 +fortran +mpi")

    def test_petsc_complex_old_version(self, resolver):
        """petsc +complex @3.17.0 triggers the complex-version conflict."""
        with pytest.raises((ConflictError, UnsatisfiableSpecError)):
            resolver.resolve("petsc@3.17.0 +complex")

    def test_petsc_complex_new_version_ok(self, resolver):
        """petsc +complex @3.20.0 is valid (no conflict above 3.18.0)."""
        result = resolver.resolve("petsc@3.20.0 +complex")
        assert result.specs["petsc"].version == Version("3.20.0")
        assert result.specs["petsc"].variants.get("complex") is True
        # +complex means hdf5 dep is NOT active (condition is ~complex)
        assert "hdf5" not in result.specs


# ---------------------------------------------------------------------------
# Unsatisfiable specs
# ---------------------------------------------------------------------------

class TestUnsatisfiable:
    def test_impossible_version(self, resolver):
        """A version that doesn't exist should fail."""
        with pytest.raises(UnsatisfiableSpecError):
            resolver.resolve("zlib@99.0.0")

    def test_conflicting_dep_version(self, resolver):
        """scipy@1.12.0 requires numpy@1.24.0:, which conflicts with
        ^numpy@1.22.0 (exact 1.22.0)."""
        with pytest.raises(UnsatisfiableSpecError):
            resolver.resolve("scipy@1.12.0 ^numpy@1.22.0")


# ---------------------------------------------------------------------------
# Complex resolution & topological order
# ---------------------------------------------------------------------------

class TestComplexResolution:
    def test_petsc_full_dag(self, resolver):
        """petsc@3.20.0 ~complex ~debug produces a correct full DAG."""
        result = resolver.resolve("petsc@3.20.0 ~complex ~debug")

        # All expected packages present
        expected = {"petsc", "zlib", "hdf5"}
        assert expected.issubset(set(result.specs.keys()))

        # Exactly one mpi provider
        mpi_providers = {"openmpi", "mpich"}
        found_mpi = mpi_providers & set(result.specs.keys())
        assert len(found_mpi) == 1

        # Exactly one blas/lapack provider
        blas_providers = {"openblas", "intel-mkl"}
        found_blas = blas_providers & set(result.specs.keys())
        assert len(found_blas) == 1

        # hdf5 must have +mpi
        assert result.specs["hdf5"].variants.get("mpi") is True

        # No boost (debug is off)
        assert "boost" not in result.specs

    def test_petsc_with_explicit_providers(self, resolver):
        """petsc with explicit mpich and intel-mkl providers."""
        result = resolver.resolve(
            "petsc@3.20.0 ~complex ~debug ^mpich ^intel-mkl"
        )
        assert "mpich" in result.specs
        assert "intel-mkl" in result.specs
        assert "openmpi" not in result.specs
        assert "openblas" not in result.specs

    def test_topological_invariant(self, resolver):
        """For any resolved DAG, every dependency appears before its
        dependent in the build_order."""
        for spec_str in [
            "petsc@3.20.0 ~complex ~debug",
            "scipy",
            "hdf5 +mpi",
            "boost ~python",
        ]:
            result = resolver.resolve(spec_str)
            order = result.build_order

            # Every spec must appear in the order
            assert set(order) == set(result.specs.keys()), (
                f"build_order {order} does not match specs "
                f"{set(result.specs.keys())} for '{spec_str}'"
            )

            # Every edge (parent, child) must satisfy:
            # child appears before parent in order
            for parent, child in result.edges:
                parent_idx = order.index(parent)
                child_idx = order.index(child)
                assert child_idx < parent_idx, (
                    f"In '{spec_str}': dependency {child} (idx {child_idx}) "
                    f"must appear before {parent} (idx {parent_idx}) "
                    f"in build_order {order}"
                )

    def test_no_duplicate_edges(self, resolver):
        """Resolved DAGs should not contain duplicate edges."""
        result = resolver.resolve("petsc@3.20.0 ~complex ~debug")
        assert len(result.edges) == len(set(result.edges)), (
            f"Duplicate edges found: {result.edges}"
        )

    def test_scipy_full_dag(self, resolver):
        """scipy produces a DAG with python, numpy, a blas/lapack provider,
        and zlib."""
        result = resolver.resolve("scipy")
        assert "scipy" in result.specs
        assert "python" in result.specs
        assert "numpy" in result.specs
        assert "zlib" in result.specs

        blas_providers = {"openblas", "intel-mkl"}
        found = blas_providers & set(result.specs.keys())
        assert len(found) == 1

        # numpy should depend on python
        assert ("numpy", "python") in result.edges
