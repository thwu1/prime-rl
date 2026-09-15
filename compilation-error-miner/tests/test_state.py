"""
Tests for C++ build failure root-cause analysis and repair synthesis pipeline.

"""

import json
import subprocess
import os
import shutil
import tempfile
import pytest


@pytest.fixture(scope="module")
def report():
    """Run the pipeline and load the output report."""
    result = subprocess.run(
        ["python3", "/app/combench_analyzer.py"],
        capture_output=True, text=True, timeout=180, cwd="/app"
    )
    assert result.returncode == 0, (
        f"Pipeline failed with exit code {result.returncode}.\n"
        f"Stderr: {result.stderr[:2000]}\nStdout: {result.stdout[:2000]}"
    )

    output_path = "/app/output/analysis.json"
    assert os.path.exists(output_path), f"Output file {output_path} not created"

    with open(output_path) as f:
        data = json.load(f)
    return data


# ============================================================
# Output structure
# ============================================================

class TestOutputStructure:
    def test_is_dict(self, report):
        assert isinstance(report, dict)

    def test_has_errors(self, report):
        assert "errors" in report
        assert isinstance(report["errors"], list)

    def test_has_causal_dag(self, report):
        assert "causal_dag" in report
        assert isinstance(report["causal_dag"], dict)

    def test_has_candidate_evaluation(self, report):
        assert "candidate_evaluation" in report
        assert isinstance(report["candidate_evaluation"], dict)

    def test_has_repair_patch(self, report):
        assert "repair_patch" in report
        assert isinstance(report["repair_patch"], str)
        assert len(report["repair_patch"]) > 50, "repair_patch too short to be a valid diff"

    def test_has_compilation_result(self, report):
        assert "compilation_result" in report
        assert isinstance(report["compilation_result"], dict)


# ============================================================
# Error extraction and deduplication
# ============================================================

def _find_error(report, file_substr, line):
    for err in report["errors"]:
        if file_substr in err["file"] and err["line"] == line:
            return err
    return None


class TestErrorExtraction:
    def test_unique_error_count(self, report):
        """After deduplication, there should be exactly 9 unique errors."""
        assert len(report["errors"]) == 9, (
            f"Expected 9 unique errors, got {len(report['errors'])}. "
            f"Errors: {[(e.get('file','?'), e.get('line','?')) for e in report['errors']]}"
        )

    def test_error_required_fields(self, report):
        """Each error must have required fields."""
        for err in report["errors"]:
            assert "file" in err, f"Missing 'file': {err}"
            assert "line" in err, f"Missing 'line': {err}"
            assert "message" in err, f"Missing 'message': {err}"
            assert "is_cascading" in err, f"Missing 'is_cascading': {err}"
            assert "source_logs" in err, f"Missing 'source_logs': {err}"

    def test_no_warnings_extracted(self, report):
        """Warnings should not appear as extracted errors."""
        for err in report["errors"]:
            msg = err["message"].lower()
            assert "unused variable" not in msg, (
                f"Warning extracted as error: {err['message']}"
            )

    def test_paths_are_project_relative(self, report):
        """File paths should be project-relative, not CI absolute paths."""
        for err in report["errors"]:
            assert not err["file"].startswith("/home/runner"), (
                f"Path not normalized: {err['file']}"
            )

    def test_error_files_correct(self, report):
        """Error files should include the expected source files."""
        basenames = {os.path.basename(err["file"]) for err in report["errors"]}
        expected = {"engine.cpp", "network.cpp", "plugin.cpp", "crypto.cpp", "main.cpp"}
        assert expected == basenames, f"Expected {expected}, got {basenames}"

    def test_network_error_deduplicated(self, report):
        """network.cpp:30 error appears in 2 logs but should be deduplicated to 1."""
        matches = [e for e in report["errors"]
                    if "network" in e["file"].lower() and e["line"] == 30]
        assert len(matches) == 1, (
            f"Expected 1 deduplicated error for network.cpp:30, found {len(matches)}"
        )

    def test_network_source_logs_tracked(self, report):
        """Deduplicated network.cpp:30 error should track >=2 source logs."""
        err = _find_error(report, "network.cpp", 30)
        assert err is not None, "network.cpp:30 error not found"
        logs = err.get("source_logs", [])
        assert len(logs) >= 2, (
            f"network.cpp:30 should be in >=2 logs, found {len(logs)}: {logs}"
        )


# ============================================================
# Root cause analysis — cascading vs self-rooted
# ============================================================

class TestRootCauseAnalysis:
    def test_cascading_count(self, report):
        """Exactly 4 errors should be marked as cascading."""
        cascading = [e for e in report["errors"] if e.get("is_cascading")]
        assert len(cascading) == 4, (
            f"Expected 4 cascading errors, got {len(cascading)}: "
            f"{[(e['file'], e['line']) for e in cascading]}"
        )

    def test_self_rooted_count(self, report):
        """Exactly 5 errors should be self-rooted (not cascading)."""
        self_rooted = [e for e in report["errors"] if not e.get("is_cascading")]
        assert len(self_rooted) == 5, (
            f"Expected 5 self-rooted errors, got {len(self_rooted)}: "
            f"{[(e['file'], e['line']) for e in self_rooted]}"
        )

    def test_engine_cast_error_cascades_from_header(self, report):
        """ENGINE_CAST error at engine.cpp:58 should cascade from engine.h."""
        err = _find_error(report, "engine.cpp", 58)
        assert err is not None, "engine.cpp:58 error not found"
        assert err["is_cascading"] is True, "engine.cpp:58 should be cascading"
        rc = err.get("root_cause_file", "")
        assert "engine.h" in rc, (
            f"engine.cpp:58 root cause should be engine.h, got {rc}"
        )

    def test_engine_cast_error2_cascades_from_header(self, report):
        """ENGINE_CAST error at engine.cpp:64 should cascade from engine.h."""
        err = _find_error(report, "engine.cpp", 64)
        assert err is not None, "engine.cpp:64 error not found"
        assert err["is_cascading"] is True
        rc = err.get("root_cause_file", "")
        assert "engine.h" in rc, (
            f"engine.cpp:64 root cause should be engine.h, got {rc}"
        )

    def test_network_error_cascades_from_types(self, report):
        """NetworkManager error at network.cpp:30 should cascade from types.h."""
        err = _find_error(report, "network.cpp", 30)
        assert err is not None, "network.cpp:30 error not found"
        assert err["is_cascading"] is True
        rc = err.get("root_cause_file", "")
        assert "types.h" in rc, (
            f"network.cpp:30 root cause should be types.h, got {rc}"
        )

    def test_engine_nm_error_cascades_from_types(self, report):
        """NetworkManager error at engine.cpp:70 should cascade from types.h."""
        err = _find_error(report, "engine.cpp", 70)
        assert err is not None, "engine.cpp:70 error not found"
        assert err["is_cascading"] is True
        rc = err.get("root_cause_file", "")
        assert "types.h" in rc, (
            f"engine.cpp:70 root cause should be types.h, got {rc}"
        )

    def test_iterator_traits_is_self_rooted(self, report):
        """iterator_traits error at engine.cpp:75 should be self-rooted."""
        err = _find_error(report, "engine.cpp", 75)
        assert err is not None, "engine.cpp:75 error not found"
        assert err["is_cascading"] is False, "engine.cpp:75 should be self-rooted"

    def test_static_assert_is_self_rooted(self, report):
        """static_assert error at engine.cpp:80 should be self-rooted."""
        err = _find_error(report, "engine.cpp", 80)
        assert err is not None, "engine.cpp:80 error not found"
        assert err["is_cascading"] is False, "engine.cpp:80 should be self-rooted"

    def test_plugin_is_self_rooted(self, report):
        """flush_buffer error at plugin.cpp:15 should be self-rooted."""
        err = _find_error(report, "plugin.cpp", 15)
        assert err is not None, "plugin.cpp:15 error not found"
        assert err["is_cascading"] is False

    def test_crypto_is_self_rooted(self, report):
        """update() error at crypto.cpp:18 should be self-rooted."""
        err = _find_error(report, "crypto.cpp", 18)
        assert err is not None, "crypto.cpp:18 error not found"
        assert err["is_cascading"] is False

    def test_main_is_self_rooted(self, report):
        """Missing semicolon at main.cpp:20 should be self-rooted."""
        err = _find_error(report, "main.cpp", 20)
        assert err is not None, "main.cpp:20 error not found"
        assert err["is_cascading"] is False


# ============================================================
# Causal DAG
# ============================================================

class TestCausalDAG:
    def _dag_entry(self, report, file_substr):
        """Find a causal DAG entry matching the given file substring."""
        for key, val in report.get("causal_dag", {}).items():
            if file_substr in key:
                return key, val
        return None, None

    def test_dag_has_engine_h_entry(self, report):
        """Causal DAG should have an entry for engine.h (ENGINE_CAST macro)."""
        key, val = self._dag_entry(report, "engine.h")
        assert key is not None, (
            f"No causal DAG entry for engine.h. Keys: {list(report.get('causal_dag', {}).keys())}"
        )
        assert isinstance(val, list)
        assert len(val) == 2, f"engine.h should cascade to 2 errors, got {len(val)}: {val}"

    def test_dag_engine_h_targets(self, report):
        """engine.h root cause should cascade to engine.cpp:58 and engine.cpp:64."""
        _, cascading = self._dag_entry(report, "engine.h")
        assert cascading is not None
        cascading_str = " ".join(str(c) for c in cascading)
        assert "58" in cascading_str, f"engine.cpp:58 not in cascading: {cascading}"
        assert "64" in cascading_str, f"engine.cpp:64 not in cascading: {cascading}"

    def test_dag_has_types_h_entry(self, report):
        """Causal DAG should have an entry for types.h (forward declaration)."""
        key, val = self._dag_entry(report, "types.h")
        assert key is not None, (
            f"No causal DAG entry for types.h. Keys: {list(report.get('causal_dag', {}).keys())}"
        )
        assert isinstance(val, list)
        assert len(val) == 2, f"types.h should cascade to 2 errors, got {len(val)}: {val}"

    def test_dag_types_h_targets(self, report):
        """types.h root cause should cascade to network.cpp:30 and engine.cpp:70."""
        _, cascading = self._dag_entry(report, "types.h")
        assert cascading is not None
        cascading_str = " ".join(str(c) for c in cascading)
        assert "network" in cascading_str.lower() or "30" in cascading_str, (
            f"network.cpp:30 not in cascading: {cascading}"
        )
        assert "70" in cascading_str, f"engine.cpp:70 not in cascading: {cascading}"

    def test_dag_only_header_entries(self, report):
        """Causal DAG should only contain header-level root causes (2 entries)."""
        dag = report.get("causal_dag", {})
        assert len(dag) == 2, (
            f"Expected 2 DAG entries (engine.h, types.h), got {len(dag)}: {list(dag.keys())}"
        )


# ============================================================
# Candidate patch evaluation
# ============================================================

class TestCandidateEvaluation:
    def _find_hunk(self, report, file_substr):
        hunks = report.get("candidate_evaluation", {}).get("hunks", [])
        for h in hunks:
            if file_substr in h.get("file", ""):
                return h
        return None

    def test_hunk_count(self, report):
        """Candidate patch should have 5 hunks evaluated."""
        hunks = report.get("candidate_evaluation", {}).get("hunks", [])
        assert len(hunks) == 5, (
            f"Expected 5 hunks, got {len(hunks)}: {[h.get('file') for h in hunks]}"
        )

    def test_types_h_hunk_necessary_and_correct(self, report):
        """types.h hunk should be necessary and semantically correct."""
        h = self._find_hunk(report, "types.h")
        assert h is not None, "No hunk evaluation for types.h"
        assert h["necessary"] is True
        assert h["semantically_correct"] is True

    def test_engine_h_hunk_necessary_but_incorrect(self, report):
        """engine.h hunk should be necessary but semantically INCORRECT."""
        h = self._find_hunk(report, "engine.h")
        assert h is not None, "No hunk evaluation for engine.h"
        assert h["necessary"] is True
        assert h["semantically_correct"] is False, (
            "ENGINE_CAST macro change should be flagged as semantically incorrect — "
            "it changes the macro contract for all callers instead of fixing usage sites"
        )

    def test_plugin_hunk_necessary_and_correct(self, report):
        """plugin.cpp hunk should be necessary and semantically correct."""
        h = self._find_hunk(report, "plugin.cpp")
        assert h is not None, "No hunk evaluation for plugin.cpp"
        assert h["necessary"] is True
        assert h["semantically_correct"] is True

    def test_config_h_hunk_unnecessary(self, report):
        """config.h hunk should be unnecessary."""
        h = self._find_hunk(report, "config.h")
        assert h is not None, "No hunk evaluation for config.h"
        assert h["necessary"] is False

    def test_network_h_hunk_unnecessary(self, report):
        """network.h hunk should be unnecessary."""
        h = self._find_hunk(report, "network.h")
        assert h is not None, "No hunk evaluation for network.h"
        assert h["necessary"] is False

    def test_necessary_hunk_count(self, report):
        """Exactly 3 hunks should be necessary."""
        hunks = report.get("candidate_evaluation", {}).get("hunks", [])
        necessary = [h for h in hunks if h.get("necessary")]
        assert len(necessary) == 3, (
            f"Expected 3 necessary hunks, got {len(necessary)}: "
            f"{[h.get('file') for h in necessary]}"
        )

    def test_missing_fixes_count(self, report):
        """Should identify 4 missing fixes."""
        missing = report.get("candidate_evaluation", {}).get("missing_fixes", [])
        assert len(missing) == 4, (
            f"Expected 4 missing fixes, got {len(missing)}: {missing}"
        )

    def test_missing_fixes_includes_crypto(self, report):
        """Missing fixes should include crypto.cpp."""
        missing = report.get("candidate_evaluation", {}).get("missing_fixes", [])
        missing_str = " ".join(str(m) for m in missing)
        assert "crypto" in missing_str.lower(), (
            f"crypto.cpp should be in missing fixes: {missing}"
        )

    def test_missing_fixes_includes_main(self, report):
        """Missing fixes should include main.cpp."""
        missing = report.get("candidate_evaluation", {}).get("missing_fixes", [])
        missing_str = " ".join(str(m) for m in missing)
        assert "main" in missing_str.lower(), (
            f"main.cpp should be in missing fixes: {missing}"
        )


# ============================================================
# Repair patch compilation verification
# ============================================================

class TestRepairCompilation:
    def test_compilation_success_reported(self, report):
        """Pipeline should report successful compilation."""
        comp = report.get("compilation_result", {})
        assert comp.get("success") is True, (
            f"Compilation should succeed, got: {comp}"
        )

    def test_all_files_compiled(self, report):
        """All 5 source files should be compiled."""
        comp = report.get("compilation_result", {})
        files = comp.get("files_compiled", [])
        assert len(files) >= 5, (
            f"Expected >=5 files compiled, got {len(files)}: {files}"
        )

    def test_independent_compilation_verification(self, report):
        """Independently apply the repair patch and compile to verify."""
        repair_patch = report.get("repair_patch", "")
        assert len(repair_patch) > 50, "repair_patch too short"

        # Create temp directory with project copy
        tmpdir = tempfile.mkdtemp(prefix="repair_verify_")
        try:
            shutil.copytree("/app/project", os.path.join(tmpdir, "project"))
            proj = os.path.join(tmpdir, "project")

            # Write repair patch
            patch_path = os.path.join(tmpdir, "repair.patch")
            with open(patch_path, "w") as f:
                f.write(repair_patch)

            # Apply patch
            apply_result = subprocess.run(
                ["patch", "-p1", "-d", proj, "-i", patch_path],
                capture_output=True, text=True, timeout=30
            )
            assert apply_result.returncode == 0, (
                f"Patch apply failed: {apply_result.stderr}"
            )

            # Compile each source file
            src_dir = os.path.join(proj, "src")
            inc_dir = os.path.join(proj, "include")
            cpp_files = [f for f in os.listdir(src_dir) if f.endswith(".cpp")]
            assert len(cpp_files) >= 5, f"Expected >=5 .cpp files, found: {cpp_files}"

            for cpp in cpp_files:
                cpp_path = os.path.join(src_dir, cpp)
                compile_result = subprocess.run(
                    ["g++", "-std=c++17", "-c", "-I", inc_dir,
                     "-o", "/dev/null", cpp_path],
                    capture_output=True, text=True, timeout=30
                )
                assert compile_result.returncode == 0, (
                    f"Compilation of {cpp} failed after repair:\n"
                    f"{compile_result.stderr[:1000]}"
                )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
