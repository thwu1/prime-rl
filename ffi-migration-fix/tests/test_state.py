"""Verification tests for the searchidx FFI migration and wrapper design task."""

import os
import subprocess
import pytest


def run_cargo(args, timeout=180):
    """Run a cargo command in /app/ and return the result."""
    env = os.environ.copy()
    cargo_bin = "/usr/local/cargo/bin"
    if cargo_bin not in env.get("PATH", ""):
        env["PATH"] = cargo_bin + ":" + env.get("PATH", "")
    return subprocess.run(
        ["cargo"] + args,
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


class TestBuild:
    """Verify the project compiles correctly."""

    def test_cargo_build(self):
        """The project must compile without errors."""
        result = run_cargo(["build"])
        assert result.returncode == 0, (
            f"cargo build failed:\nstderr:\n{result.stderr}\nstdout:\n{result.stdout}"
        )


class TestIntegration:
    """Verify all integration tests pass."""

    def test_cargo_test_all(self):
        """All integration tests must pass."""
        result = run_cargo(["test", "--", "--test-threads=1"])
        assert result.returncode == 0, (
            f"cargo test failed:\nstderr:\n{result.stderr}\nstdout:\n{result.stdout}"
        )


class TestFFIStructure:
    """Structural checks for the FFI bridge layer."""

    def test_ffi_free_tokens_exists(self):
        """searchidx_free_tokens must be implemented in ffi.rs."""
        with open("/app/src/ffi.rs") as f:
            content = f.read()
        assert "fn searchidx_free_tokens" in content, (
            "searchidx_free_tokens function not found in ffi.rs"
        )

    def test_build_includes_header_dir(self):
        """build.rs must include the header directory for C compilation."""
        with open("/app/build.rs") as f:
            content = f.read()
        assert "include" in content, "build.rs must reference the include directory"
        assert "index.c" in content, "build.rs must compile index.c"


class TestWrapperStructure:
    """Structural checks for the safe wrapper module."""

    def test_wrapper_module_declared(self):
        """wrapper module must be declared in lib.rs."""
        with open("/app/src/lib.rs") as f:
            content = f.read()
        assert "pub mod wrapper" in content, (
            "lib.rs must declare pub mod wrapper"
        )

    def test_search_error_type(self):
        """SearchError enum with InteriorNull variant must exist in wrapper.rs."""
        with open("/app/src/wrapper.rs") as f:
            content = f.read()
        assert "enum SearchError" in content, (
            "SearchError enum not found in wrapper.rs"
        )
        assert "InteriorNull" in content, (
            "InteriorNull variant not found in SearchError"
        )

    def test_owned_result_type(self):
        """OwnedSearchResult struct with doc_id and score must exist."""
        with open("/app/src/wrapper.rs") as f:
            content = f.read()
        assert "struct OwnedSearchResult" in content, (
            "OwnedSearchResult struct not found in wrapper.rs"
        )
        assert "doc_id" in content, "doc_id field not found in wrapper.rs"
        assert "score" in content, "score field not found in wrapper.rs"

    def test_c_results_freed(self):
        """C-allocated search results must be freed to avoid memory leaks."""
        with open("/app/src/wrapper.rs") as f:
            content = f.read()
        assert "searchidx_free_results" in content, (
            "searchidx_free_results must be called in wrapper.rs to free C memory"
        )

    def test_search_index_methods(self):
        """SearchIndex must have the required public methods."""
        with open("/app/src/wrapper.rs") as f:
            content = f.read()
        assert "fn new" in content, "SearchIndex must have new() method"
        assert "fn index_document" in content, "SearchIndex must have index_document method"
        assert "fn search_sorted" in content, "SearchIndex must have search_sorted method"
        assert "fn reset" in content, "SearchIndex must have reset method"
