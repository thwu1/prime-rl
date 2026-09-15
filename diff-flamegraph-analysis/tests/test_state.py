
import json
import os
import re

OUTDIR = "/app/output"


def load_triage():
    with open(os.path.join(OUTDIR, "triage.json")) as f:
        return json.load(f)


def read_folded(path):
    """Parse folded file into list of (stack, count) tuples."""
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.rsplit(None, 1)
            if len(parts) == 2 and parts[1].lstrip("-").isdigit():
                entries.append((parts[0], int(parts[1])))
    return entries


# ── Artifact existence ──

class TestArtifactExistence:
    def test_baseline_folded(self):
        assert os.path.exists(os.path.join(OUTDIR, "baseline.folded"))

    def test_incident_folded(self):
        assert os.path.exists(os.path.join(OUTDIR, "incident.folded"))

    def test_diff_folded(self):
        assert os.path.exists(os.path.join(OUTDIR, "diff.folded"))

    def test_diff_svg(self):
        assert os.path.exists(os.path.join(OUTDIR, "diff_flamegraph.svg"))

    def test_offcpu_folded(self):
        assert os.path.exists(os.path.join(OUTDIR, "offcpu.folded"))

    def test_offcpu_svg(self):
        assert os.path.exists(os.path.join(OUTDIR, "offcpu_flamegraph.svg"))

    def test_triage_json(self):
        assert os.path.exists(os.path.join(OUTDIR, "triage.json"))


# ── Folded file format and content ──

class TestFoldedFormat:
    def test_baseline_valid_folded(self):
        """Each non-empty line must be: semicolon-delimited-stack <space> integer"""
        entries = read_folded(os.path.join(OUTDIR, "baseline.folded"))
        assert len(entries) > 10, "Too few stacks in baseline"
        for stack, count in entries:
            assert ";" in stack, f"Not folded format: {stack}"
            assert count > 0

    def test_incident_valid_folded(self):
        entries = read_folded(os.path.join(OUTDIR, "incident.folded"))
        assert len(entries) > 10, "Too few stacks in incident"
        for stack, count in entries:
            assert ";" in stack
            assert count > 0

    def test_baseline_no_noise_processes(self):
        """Should only contain appserver stacks, not nginx or postgres."""
        entries = read_folded(os.path.join(OUTDIR, "baseline.folded"))
        for stack, _ in entries:
            low = stack.lower()
            assert "nginx" not in low, f"Noise process in baseline: {stack}"
            assert "ngx_" not in low, f"Noise process in baseline: {stack}"
            assert "postgres" not in low, f"Noise process in baseline: {stack}"
            assert "postmaster" not in low, f"Noise process in baseline: {stack}"

    def test_incident_no_noise_processes(self):
        entries = read_folded(os.path.join(OUTDIR, "incident.folded"))
        for stack, _ in entries:
            low = stack.lower()
            assert "nginx" not in low, f"Noise process in incident: {stack}"
            assert "ngx_" not in low, f"Noise process in incident: {stack}"
            assert "postgres" not in low, f"Noise process in incident: {stack}"
            assert "postmaster" not in low, f"Noise process in incident: {stack}"

    def test_baseline_total_samples(self):
        """Baseline appserver stacks should total exactly 406 samples."""
        entries = read_folded(os.path.join(OUTDIR, "baseline.folded"))
        total = sum(c for _, c in entries)
        assert total == 406, f"Expected 406 baseline samples, got {total}"

    def test_incident_total_samples(self):
        """Incident appserver stacks should total exactly 928 samples."""
        entries = read_folded(os.path.join(OUTDIR, "incident.folded"))
        total = sum(c for _, c in entries)
        assert total == 928, f"Expected 928 incident samples, got {total}"


# ── SVG validation ──

class TestSVG:
    def test_diff_svg_valid(self):
        with open(os.path.join(OUTDIR, "diff_flamegraph.svg")) as f:
            content = f.read()
        assert "<svg" in content, "Not a valid SVG"
        assert "</svg>" in content, "SVG not closed"
        assert len(content) > 1000, "SVG too small"

    def test_diff_svg_has_interactivity(self):
        """flamegraph.pl generates SVGs with embedded JavaScript."""
        with open(os.path.join(OUTDIR, "diff_flamegraph.svg")) as f:
            content = f.read()
        assert "CDATA" in content or "function" in content, \
            "SVG lacks flamegraph.pl interactivity"

    def test_diff_svg_contains_key_functions(self):
        with open(os.path.join(OUTDIR, "diff_flamegraph.svg")) as f:
            content = f.read()
        # Should contain at least one of the key regression/present functions
        assert any(fn in content for fn in [
            "handle_request", "page_read", "btree_scan", "event_loop"
        ]), "SVG missing expected function names"

    def test_offcpu_svg_valid(self):
        with open(os.path.join(OUTDIR, "offcpu_flamegraph.svg")) as f:
            content = f.read()
        assert "<svg" in content
        assert "</svg>" in content
        assert len(content) > 500

    def test_offcpu_svg_has_offcpu_functions(self):
        with open(os.path.join(OUTDIR, "offcpu_flamegraph.svg")) as f:
            content = f.read()
        assert any(fn in content for fn in [
            "schedule", "futex_wait", "io_schedule", "finish_task_switch"
        ]), "Off-CPU SVG missing expected kernel functions"


# ── Diff folded ──

class TestDiffFolded:
    def test_diff_folded_nonempty(self):
        path = os.path.join(OUTDIR, "diff.folded")
        assert os.path.getsize(path) > 100, "diff.folded is too small"

    def test_diff_folded_has_stacks(self):
        """diff.folded should contain semicolon-delimited stacks."""
        with open(os.path.join(OUTDIR, "diff.folded")) as f:
            content = f.read()
        assert ";" in content, "No semicolons in diff.folded"
        assert "handle_request" in content or "main" in content


# ── Off-CPU folded ──

class TestOffcpuFolded:
    def test_offcpu_folded_valid(self):
        entries = read_folded(os.path.join(OUTDIR, "offcpu.folded"))
        assert len(entries) >= 5, f"Expected >=5 off-CPU stacks, got {len(entries)}"

    def test_offcpu_contains_io_stacks(self):
        with open(os.path.join(OUTDIR, "offcpu.folded")) as f:
            content = f.read()
        assert "io_schedule" in content, "Off-CPU folded missing io_schedule"

    def test_offcpu_contains_lock_stacks(self):
        with open(os.path.join(OUTDIR, "offcpu.folded")) as f:
            content = f.read()
        assert "futex_wait" in content, "Off-CPU folded missing futex_wait"


# ── Triage report structure ──

class TestTriageStructure:
    def test_valid_json(self):
        report = load_triage()
        assert isinstance(report, dict)

    def test_required_top_level_keys(self):
        report = load_triage()
        for key in ["summary", "oncpu_regressions", "oncpu_improvements",
                     "offcpu_hotspots", "elided_code_paths",
                     "new_code_paths", "diagnosis"]:
            assert key in report, f"Missing key: {key}"

    def test_summary_fields(self):
        report = load_triage()
        s = report["summary"]
        for key in ["baseline_oncpu_samples", "incident_oncpu_samples",
                     "duration_ratio", "root_cause_class"]:
            assert key in s, f"Missing summary key: {key}"

    def test_summary_sample_counts(self):
        s = load_triage()["summary"]
        assert s["baseline_oncpu_samples"] == 406
        assert s["incident_oncpu_samples"] == 928

    def test_duration_ratio(self):
        s = load_triage()["summary"]
        assert abs(s["duration_ratio"] - 2.0) < 0.1


# ── Root cause classification ──

class TestRootCause:
    def test_root_cause_is_mixed(self):
        """Both CPU regression and I/O/lock off-CPU issues are present."""
        s = load_triage()["summary"]
        assert s["root_cause_class"] == "mixed", \
            f"Expected 'mixed', got '{s['root_cause_class']}'"


# ── On-CPU regression analysis ──

class TestOnCPURegressions:
    def test_regressions_nonempty(self):
        report = load_triage()
        assert len(report["oncpu_regressions"]) >= 3

    def test_backtrack_is_top_regression(self):
        """backtrack should be among the top 3 regressions."""
        regressions = load_triage()["oncpu_regressions"]
        top3_funcs = [r["function"] for r in regressions[:3]]
        assert "backtrack" in top3_funcs, \
            f"backtrack not in top 3: {top3_funcs}"

    def test_backtrack_delta_magnitude(self):
        """backtrack: 120/928=12.93% vs 0% baseline → delta ~12.93%"""
        regressions = load_triage()["oncpu_regressions"]
        bt = next((r for r in regressions if r["function"] == "backtrack"), None)
        assert bt is not None, "backtrack not found in regressions"
        assert bt["delta_pct"] > 10.0, f"backtrack delta too low: {bt['delta_pct']}"
        assert bt["baseline_pct"] < 0.5, f"backtrack should be ~0% in baseline"
        assert bt["incident_pct"] > 10.0

    def test_page_read_is_regression(self):
        """page_read: 28/406=6.90% → 130/928=14.01%, delta ~7.11%"""
        regressions = load_triage()["oncpu_regressions"]
        pr = next((r for r in regressions if r["function"] == "page_read"), None)
        assert pr is not None, "page_read not found in regressions"
        assert pr["delta_pct"] > 5.0, f"page_read delta too low: {pr['delta_pct']}"

    def test_regressions_sorted_descending(self):
        regressions = load_triage()["oncpu_regressions"]
        deltas = [r["delta_pct"] for r in regressions]
        for i in range(len(deltas) - 1):
            assert deltas[i] >= deltas[i + 1], \
                f"Regressions not sorted at index {i}: {deltas[i]} < {deltas[i+1]}"

    def test_improvements_contain_elided_functions(self):
        """Functions from removed code paths should appear as improvements."""
        improvements = load_triage()["oncpu_improvements"]
        funcs = [r["function"] for r in improvements]
        # At least one of the json_marshal or cache_lookup leaf functions
        assert any(f in funcs for f in [
            "reflect_value", "write_string", "encode_number",
            "memcpy_avx2", "murmurhash3"
        ]), f"No elided function in improvements: {funcs}"


# ── Off-CPU hotspot analysis ──

class TestOffCPUHotspots:
    def test_hotspots_nonempty(self):
        report = load_triage()
        assert len(report["offcpu_hotspots"]) >= 3

    def test_io_category_present(self):
        hotspots = load_triage()["offcpu_hotspots"]
        categories = [h["category"] for h in hotspots]
        assert "io" in categories, f"No 'io' category in: {categories}"

    def test_lock_category_present(self):
        hotspots = load_triage()["offcpu_hotspots"]
        categories = [h["category"] for h in hotspots]
        assert "lock" in categories, f"No 'lock' category in: {categories}"

    def test_idle_excluded(self):
        """Voluntary idle waits (epoll, sleep) should be excluded."""
        hotspots = load_triage()["offcpu_hotspots"]
        for h in hotspots:
            assert h["category"] != "idle", \
                f"Idle hotspot not excluded: {h['function']}"

    def test_io_has_highest_duration(self):
        """The I/O blocking path (12800us) should be the top hotspot."""
        hotspots = load_triage()["offcpu_hotspots"]
        if hotspots:
            top = hotspots[0]
            assert top["total_us"] >= 10000, \
                f"Top hotspot duration too low: {top['total_us']}"

    def test_hotspot_entries_have_required_fields(self):
        hotspots = load_triage()["offcpu_hotspots"]
        for h in hotspots:
            assert "function" in h
            assert "total_us" in h
            assert "category" in h
            assert h["category"] in ("io", "lock", "network", "other")


# ── Code path changes ──

class TestCodePathChanges:
    def test_elided_paths_mention_json_or_cache(self):
        """json_marshal or cache_lookup stacks should be in elided paths."""
        report = load_triage()
        elided = " ".join(report["elided_code_paths"])
        assert "json_marshal" in elided or "cache_lookup" in elided, \
            f"Neither json_marshal nor cache_lookup in elided paths"

    def test_new_paths_mention_validate_or_proto(self):
        """validate_input or proto_marshal stacks should be in new paths."""
        report = load_triage()
        new = " ".join(report["new_code_paths"])
        assert "validate_input" in new or "proto_marshal" in new, \
            f"Neither validate_input nor proto_marshal in new paths"


# ── Diagnosis quality ──

class TestDiagnosis:
    def test_diagnosis_nonempty(self):
        report = load_triage()
        assert len(report["diagnosis"]) > 50, "Diagnosis is too short"

    def test_diagnosis_mentions_cpu(self):
        """Diagnosis must reference on-CPU regression."""
        diag = load_triage()["diagnosis"].lower()
        assert any(term in diag for term in [
            "cpu", "backtrack", "regex", "on-cpu", "oncpu", "compute"
        ]), "Diagnosis doesn't mention CPU-side regression"

    def test_diagnosis_mentions_io_or_blocking(self):
        """Diagnosis must reference off-CPU / I/O / blocking."""
        diag = load_triage()["diagnosis"].lower()
        assert any(term in diag for term in [
            "i/o", "io", "disk", "page_read", "block", "off-cpu",
            "offcpu", "lock", "contention", "futex", "wait"
        ]), "Diagnosis doesn't mention I/O or blocking issues"
