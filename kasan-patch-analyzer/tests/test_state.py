
import json
import sys
import os
import pytest

sys.path.insert(0, '/app')


# ============================================================
# Parser Tests
# ============================================================

class TestParserOOB:
    """Test parsing of slab-out-of-bounds crash report."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from kasan_analyzer.parser import parse_kasan_report
        with open('/app/crash_reports/report_oob.txt') as f:
            self.report = parse_kasan_report(f.read())

    def test_bug_type(self):
        assert self.report.bug_type == "slab-out-of-bounds"

    def test_access_type(self):
        assert self.report.access_type == "Read"

    def test_access_size(self):
        assert self.report.access_size == 1

    def test_faulting_function(self):
        assert self.report.faulting_function == "usbtmc_interrupt"

    def test_source_file(self):
        assert self.report.source_file == "drivers/usb/class/usbtmc.c"

    def test_source_line(self):
        assert self.report.source_line == 2309

    def test_pid(self):
        assert self.report.pid == 0

    def test_task_name(self):
        assert "swapper" in self.report.task_name

    def test_call_stack_nonempty(self):
        assert len(self.report.call_stack) >= 5

    def test_call_stack_first_frame(self):
        # First non-infrastructure frame in the call stack
        func_names = [f.function for f in self.report.call_stack]
        assert "usbtmc_interrupt" in func_names

    def test_call_stack_frame_has_source(self):
        """At least some call stack frames should have source file info."""
        frames_with_source = [f for f in self.report.call_stack if f.source_file]
        assert len(frames_with_source) >= 3

    def test_alloc_stack_present(self):
        assert self.report.alloc_stack is not None
        assert len(self.report.alloc_stack) >= 2

    def test_alloc_stack_contains_probe(self):
        alloc_funcs = [f.function for f in self.report.alloc_stack]
        assert "usbtmc_probe" in alloc_funcs

    def test_no_free_stack(self):
        """OOB bugs don't have a 'Freed by' section."""
        assert self.report.free_stack is None or len(self.report.free_stack) == 0

    def test_object_cache(self):
        assert self.report.object_cache == "kmalloc-8"

    def test_object_size(self):
        assert self.report.object_size == 8


class TestParserUAF:
    """Test parsing of slab-use-after-free crash report."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from kasan_analyzer.parser import parse_kasan_report
        with open('/app/crash_reports/report_uaf.txt') as f:
            self.report = parse_kasan_report(f.read())

    def test_bug_type(self):
        assert self.report.bug_type == "slab-use-after-free"

    def test_access_type(self):
        assert self.report.access_type == "Write"

    def test_access_size(self):
        assert self.report.access_size == 8

    def test_faulting_function(self):
        assert self.report.faulting_function == "recv_work"

    def test_source_file(self):
        assert "rc.c" in self.report.source_file
        assert "hfi1" in self.report.source_file

    def test_source_line(self):
        assert self.report.source_line == 2563

    def test_pid(self):
        assert self.report.pid == 158

    def test_free_stack_present(self):
        assert self.report.free_stack is not None
        assert len(self.report.free_stack) >= 2

    def test_free_stack_contains_reap_timer(self):
        free_funcs = [f.function for f in self.report.free_stack]
        assert "hfi1_del_tid_reap_timer" in free_funcs

    def test_alloc_stack_present(self):
        assert self.report.alloc_stack is not None
        assert len(self.report.alloc_stack) >= 2

    def test_alloc_stack_contains_setup(self):
        alloc_funcs = [f.function for f in self.report.alloc_stack]
        assert "hfi1_setup_tid_rdma" in alloc_funcs

    def test_object_cache(self):
        assert self.report.object_cache == "hfi1_tid_entry"

    def test_object_size(self):
        assert self.report.object_size == 64


class TestParserNPD:
    """Test parsing of null-ptr-deref crash report."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from kasan_analyzer.parser import parse_kasan_report
        with open('/app/crash_reports/report_npd.txt') as f:
            self.report = parse_kasan_report(f.read())

    def test_bug_type(self):
        assert self.report.bug_type == "null-ptr-deref"

    def test_access_type(self):
        assert self.report.access_type == "Read"

    def test_access_size(self):
        assert self.report.access_size == 8

    def test_faulting_function(self):
        assert self.report.faulting_function == "gfs2_drop_inode"

    def test_source_file(self):
        assert "super.c" in self.report.source_file
        assert "gfs2" in self.report.source_file

    def test_source_line(self):
        assert self.report.source_line == 743

    def test_pid(self):
        assert self.report.pid == 3847

    def test_call_stack_contains_iput(self):
        func_names = [f.function for f in self.report.call_stack]
        assert any("iput" in fn for fn in func_names)


class TestParserGlobalOOB:
    """Test parsing of global-out-of-bounds crash report."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from kasan_analyzer.parser import parse_kasan_report
        with open('/app/crash_reports/report_global_oob.txt') as f:
            self.report = parse_kasan_report(f.read())

    def test_bug_type(self):
        assert self.report.bug_type == "global-out-of-bounds"

    def test_access_type(self):
        assert self.report.access_type == "Read"

    def test_access_size(self):
        assert self.report.access_size == 4

    def test_faulting_function(self):
        assert self.report.faulting_function == "ip6gre_header"

    def test_source_file(self):
        assert "ip6_gre.c" in self.report.source_file

    def test_source_line(self):
        assert self.report.source_line == 487


# ============================================================
# Localizer Tests
# ============================================================

class TestLocalizer:
    """Test bug localization from call stacks."""

    def _parse_and_localize(self, report_file):
        from kasan_analyzer.parser import parse_kasan_report
        from kasan_analyzer.localizer import localize_bug
        with open(report_file) as f:
            report = parse_kasan_report(f.read())
        return localize_bug(report)

    def test_localize_oob_first_candidate(self):
        results = self._parse_and_localize('/app/crash_reports/report_oob.txt')
        assert len(results) >= 1
        assert results[0][0] == "usbtmc_interrupt"
        assert "usbtmc.c" in results[0][1]

    def test_localize_uaf_first_candidate(self):
        results = self._parse_and_localize('/app/crash_reports/report_uaf.txt')
        assert len(results) >= 1
        assert results[0][0] == "recv_work"

    def test_localize_npd_first_candidate(self):
        results = self._parse_and_localize('/app/crash_reports/report_npd.txt')
        assert len(results) >= 1
        assert results[0][0] == "gfs2_drop_inode"

    def test_localize_global_oob_first_candidate(self):
        results = self._parse_and_localize('/app/crash_reports/report_global_oob.txt')
        assert len(results) >= 1
        assert results[0][0] == "ip6gre_header"

    def test_filters_kasan_infrastructure(self):
        """KASAN reporting functions must not appear in results."""
        results = self._parse_and_localize('/app/crash_reports/report_oob.txt')
        func_names = [r[0] for r in results]
        for infra_fn in ["kasan_report", "print_report", "print_address_description",
                         "__dump_stack", "dump_stack_lvl"]:
            assert infra_fn not in func_names, f"{infra_fn} should be filtered"

    def test_filters_memory_allocator(self):
        """Memory allocator functions must not appear in results."""
        results = self._parse_and_localize('/app/crash_reports/report_uaf.txt')
        func_names = [r[0] for r in results]
        for infra_fn in ["kmem_cache_free", "kmem_cache_alloc_noprof",
                         "__kasan_slab_free", "__kasan_slab_alloc",
                         "kasan_save_stack", "kasan_save_track"]:
            assert infra_fn not in func_names, f"{infra_fn} should be filtered"

    def test_filters_generic_workqueue(self):
        """Generic workqueue/scheduling functions must not appear."""
        results = self._parse_and_localize('/app/crash_reports/report_uaf.txt')
        func_names = [r[0] for r in results]
        for infra_fn in ["process_one_work", "worker_thread", "kthread",
                         "ret_from_fork", "ret_from_fork_asm"]:
            assert infra_fn not in func_names, f"{infra_fn} should be filtered"

    def test_confidence_decreases(self):
        """Confidence scores should be non-increasing (first = highest)."""
        results = self._parse_and_localize('/app/crash_reports/report_oob.txt')
        if len(results) >= 2:
            for i in range(len(results) - 1):
                assert results[i][3] >= results[i + 1][3], \
                    "Confidence should be non-increasing"

    def test_results_have_source_info(self):
        """Localization results should include source file and line."""
        results = self._parse_and_localize('/app/crash_reports/report_oob.txt')
        assert len(results) >= 1
        # Each result is (function, source_file, source_line, confidence)
        assert len(results[0]) == 4
        assert isinstance(results[0][1], str)  # source_file
        assert isinstance(results[0][2], int)  # source_line
        assert isinstance(results[0][3], float)  # confidence


# ============================================================
# Verifier Tests
# ============================================================

class TestVerifier:
    """Test verification outcome classification per RGym protocol."""

    @pytest.fixture(autouse=True)
    def setup(self):
        with open('/app/verification_data/runs.json') as f:
            self.data = json.load(f)

    def test_classify_pass(self):
        from kasan_analyzer.verifier import classify_verification, VerificationOutcome
        result = classify_verification(self.data["scenario_pass"]["runs"])
        assert result == VerificationOutcome.PASS

    def test_classify_trigger(self):
        from kasan_analyzer.verifier import classify_verification, VerificationOutcome
        result = classify_verification(self.data["scenario_trigger"]["runs"])
        assert result == VerificationOutcome.TRIGGER

    def test_classify_racey(self):
        from kasan_analyzer.verifier import classify_verification, VerificationOutcome
        result = classify_verification(self.data["scenario_racey"]["runs"])
        assert result == VerificationOutcome.RACEY

    def test_classify_boot_fail(self):
        from kasan_analyzer.verifier import classify_verification, VerificationOutcome
        result = classify_verification(self.data["scenario_boot_fail"]["runs"])
        assert result == VerificationOutcome.BOOT_FAIL

    def test_classify_single_crash_is_racey(self):
        from kasan_analyzer.verifier import classify_verification, VerificationOutcome
        result = classify_verification(self.data["scenario_single_crash"]["runs"])
        assert result == VerificationOutcome.RACEY

    def test_classify_mixed_boot_fail(self):
        from kasan_analyzer.verifier import classify_verification, VerificationOutcome
        result = classify_verification(self.data["scenario_mixed_boot_fail"]["runs"])
        assert result == VerificationOutcome.BOOT_FAIL

    def test_outcome_enum_values(self):
        from kasan_analyzer.verifier import VerificationOutcome
        assert VerificationOutcome.PASS.value == "pass"
        assert VerificationOutcome.TRIGGER.value == "trigger"
        assert VerificationOutcome.RACEY.value == "racey"
        assert VerificationOutcome.BOOT_FAIL.value == "boot_fail"


# ============================================================
# Patch Analyzer Tests
# ============================================================

class TestPatchAnalyzer:
    """Test patch analysis against crash reports."""

    def _analyze(self, report_file, patch_file):
        from kasan_analyzer.parser import parse_kasan_report
        from kasan_analyzer.localizer import localize_bug
        from kasan_analyzer.patch_analyzer import analyze_patch
        with open(report_file) as f:
            report = parse_kasan_report(f.read())
        candidates = localize_bug(report)
        with open(patch_file) as f:
            patch_text = f.read()
        return analyze_patch(patch_text, report, candidates)

    def test_oob_bounds_check_targets_buggy_file(self):
        analysis = self._analyze(
            '/app/crash_reports/report_oob.txt',
            '/app/patches/patch_oob_bounds_check.diff'
        )
        assert analysis.targets_buggy_file

    def test_oob_bounds_check_strategy(self):
        analysis = self._analyze(
            '/app/crash_reports/report_oob.txt',
            '/app/patches/patch_oob_bounds_check.diff'
        )
        assert analysis.patch_strategy in ("bounds_check", "input_validation")

    def test_oob_bounds_check_matches_bug(self):
        analysis = self._analyze(
            '/app/crash_reports/report_oob.txt',
            '/app/patches/patch_oob_bounds_check.diff'
        )
        assert analysis.strategy_matches_bug is True

    def test_oob_bounds_check_classification(self):
        analysis = self._analyze(
            '/app/crash_reports/report_oob.txt',
            '/app/patches/patch_oob_bounds_check.diff'
        )
        assert analysis.classification == "plausible"

    def test_npd_null_check_targets_buggy_file(self):
        analysis = self._analyze(
            '/app/crash_reports/report_npd.txt',
            '/app/patches/patch_npd_null_check.diff'
        )
        assert analysis.targets_buggy_file

    def test_npd_null_check_strategy(self):
        analysis = self._analyze(
            '/app/crash_reports/report_npd.txt',
            '/app/patches/patch_npd_null_check.diff'
        )
        assert analysis.patch_strategy == "null_check"

    def test_npd_null_check_matches_bug(self):
        analysis = self._analyze(
            '/app/crash_reports/report_npd.txt',
            '/app/patches/patch_npd_null_check.diff'
        )
        assert analysis.strategy_matches_bug is True

    def test_npd_null_check_classification(self):
        analysis = self._analyze(
            '/app/crash_reports/report_npd.txt',
            '/app/patches/patch_npd_null_check.diff'
        )
        assert analysis.classification == "plausible"

    def test_wrong_function_patch_does_not_target_buggy_file(self):
        analysis = self._analyze(
            '/app/crash_reports/report_uaf.txt',
            '/app/patches/patch_uaf_wrong_function.diff'
        )
        assert analysis.targets_buggy_file is False

    def test_wrong_function_patch_classification(self):
        analysis = self._analyze(
            '/app/crash_reports/report_uaf.txt',
            '/app/patches/patch_uaf_wrong_function.diff'
        )
        assert analysis.classification == "wrong"

    def test_patch_analysis_has_target_files(self):
        analysis = self._analyze(
            '/app/crash_reports/report_oob.txt',
            '/app/patches/patch_oob_bounds_check.diff'
        )
        assert len(analysis.target_files) >= 1
        assert any("usbtmc.c" in f for f in analysis.target_files)

    def test_patch_analysis_has_target_functions(self):
        analysis = self._analyze(
            '/app/crash_reports/report_oob.txt',
            '/app/patches/patch_oob_bounds_check.diff'
        )
        assert len(analysis.target_functions) >= 1
        assert "usbtmc_interrupt" in analysis.target_functions

    # Patch applicability tests (require kernel source at /app/kernel_src/)

    def test_oob_patch_applies_cleanly(self):
        analysis = self._analyze(
            '/app/crash_reports/report_oob.txt',
            '/app/patches/patch_oob_bounds_check.diff'
        )
        assert analysis.applies_cleanly is True

    def test_npd_patch_applies_cleanly(self):
        analysis = self._analyze(
            '/app/crash_reports/report_npd.txt',
            '/app/patches/patch_npd_null_check.diff'
        )
        assert analysis.applies_cleanly is True

    def test_wrong_function_patch_applies_cleanly(self):
        analysis = self._analyze(
            '/app/crash_reports/report_uaf.txt',
            '/app/patches/patch_uaf_wrong_function.diff'
        )
        assert analysis.applies_cleanly is True

    def test_refcount_patch_does_not_apply(self):
        analysis = self._analyze(
            '/app/crash_reports/report_uaf.txt',
            '/app/patches/patch_uaf_refcount.diff'
        )
        assert analysis.applies_cleanly is False

    def test_refcount_patch_targets_buggy_file(self):
        analysis = self._analyze(
            '/app/crash_reports/report_uaf.txt',
            '/app/patches/patch_uaf_refcount.diff'
        )
        assert analysis.targets_buggy_file is True

    def test_refcount_patch_classification(self):
        analysis = self._analyze(
            '/app/crash_reports/report_uaf.txt',
            '/app/patches/patch_uaf_refcount.diff'
        )
        assert analysis.classification == "plausible"


# ============================================================
# Integration Tests
# ============================================================

class TestIntegration:
    """End-to-end integration tests."""

    def test_full_pipeline_oob(self):
        """Full pipeline: parse -> localize -> verify -> analyze patch."""
        from kasan_analyzer.parser import parse_kasan_report
        from kasan_analyzer.localizer import localize_bug
        from kasan_analyzer.verifier import classify_verification, VerificationOutcome
        from kasan_analyzer.patch_analyzer import analyze_patch

        # Parse
        with open('/app/crash_reports/report_oob.txt') as f:
            report = parse_kasan_report(f.read())
        assert report.bug_type == "slab-out-of-bounds"

        # Localize
        candidates = localize_bug(report)
        assert candidates[0][0] == "usbtmc_interrupt"

        # Verify
        with open('/app/verification_data/runs.json') as f:
            data = json.load(f)
        outcome = classify_verification(data["scenario_pass"]["runs"])
        assert outcome == VerificationOutcome.PASS

        # Analyze patch
        with open('/app/patches/patch_oob_bounds_check.diff') as f:
            patch_text = f.read()
        analysis = analyze_patch(patch_text, report, candidates)
        assert analysis.classification == "plausible"

    def test_all_reports_parseable(self):
        """All crash reports in the data directory should parse without error."""
        from kasan_analyzer.parser import parse_kasan_report
        import glob
        reports = glob.glob('/app/crash_reports/report_*.txt')
        assert len(reports) >= 4, "Expected at least 4 crash reports"
        for report_file in reports:
            with open(report_file) as f:
                report = parse_kasan_report(f.read())
            assert report.bug_type is not None
            assert report.faulting_function is not None
            assert report.source_file is not None
            assert len(report.call_stack) >= 1

    def test_all_reports_localizable(self):
        """All crash reports should produce localization results."""
        from kasan_analyzer.parser import parse_kasan_report
        from kasan_analyzer.localizer import localize_bug
        import glob
        reports = glob.glob('/app/crash_reports/report_*.txt')
        for report_file in reports:
            with open(report_file) as f:
                report = parse_kasan_report(f.read())
            results = localize_bug(report)
            assert len(results) >= 1, f"No localization for {report_file}"
            # No infrastructure function should be first
            assert results[0][0] not in [
                "kasan_report", "print_report", "dump_stack_lvl",
                "__dump_stack", "print_address_description"
            ], f"Infrastructure function ranked first for {report_file}"
