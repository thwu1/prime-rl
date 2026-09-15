
import hashlib
import json
import os
import sqlite3
import subprocess

import pytest


def load_results():
    with open("/app/results.json") as f:
        return json.load(f)


def _get_by_type(results, atype):
    matches = [a for a in results["anomalies"] if a["type"] == atype]
    assert len(matches) == 1, f"Expected exactly 1 '{atype}' anomaly, got {len(matches)}"
    return matches[0]


def _compute_signature(results):
    """Compute a canonical hash signature of the core result fields."""
    anomalies = sorted(results["anomalies"], key=lambda a: a["type"])
    parts = [str(results["anomaly_count"])]
    for a in anomalies:
        parts.append(a["type"])
        parts.append(",".join(sorted(a["affected_switches"])))
        parts.append(",".join(str(f) for f in sorted(a["affected_flow_ids"])))
        if a["type"] == "attack":
            rc = a["root_cause"]
            parts.append(f"{rc['switch']}:{rc['port']}:{rc['queue']}")
            parts.append(str(a["propagation_depth"]))
        elif a["type"] == "deadlock":
            parts.append(",".join(sorted(a["cycle_switches"])))
            parts.append(str(a["cycle_length"]))
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


# Pre-computed verification digest — does not reveal individual expected values
_VERIFICATION_DIGEST = (
    "a4915ae3a59d80c3efebb7e9ffb588ef46a58b1564759b924fdb034cbf4e03e9"
)


# ── structural tests ───────────────────────────────────────────────────────

class TestResultsStructure:
    def test_results_file_exists(self):
        assert os.path.exists("/app/results.json"), "results.json not found"

    def test_results_valid_json(self):
        results = load_results()
        assert isinstance(results, dict)
        assert "anomaly_count" in results
        assert "anomalies" in results
        assert isinstance(results["anomalies"], list)

    def test_anomaly_count_matches_list(self):
        results = load_results()
        assert results["anomaly_count"] == len(results["anomalies"])

    def test_each_anomaly_has_required_fields(self):
        results = load_results()
        required = {"type", "affected_switches", "affected_flow_ids", "severity_score"}
        for a in results["anomalies"]:
            missing = required - set(a.keys())
            assert not missing, f"Anomaly {a.get('id', '?')} missing fields: {missing}"

    def test_attack_has_specific_fields(self):
        results = load_results()
        attacks = [a for a in results["anomalies"] if a["type"] == "attack"]
        for a in attacks:
            assert "root_cause" in a, "Attack missing root_cause"
            assert "propagation_depth" in a, "Attack missing propagation_depth"
            rc = a["root_cause"]
            assert "switch" in rc and "port" in rc and "queue" in rc

    def test_deadlock_has_specific_fields(self):
        results = load_results()
        deadlocks = [a for a in results["anomalies"] if a["type"] == "deadlock"]
        for a in deadlocks:
            assert "cycle_switches" in a, "Deadlock missing cycle_switches"
            assert "cycle_length" in a, "Deadlock missing cycle_length"

    def test_has_exactly_two_anomaly_types(self):
        results = load_results()
        types = {a["type"] for a in results["anomalies"]}
        assert types == {"attack", "deadlock"}, (
            f"Expected anomaly types attack and deadlock, got {types}"
        )


# ── correctness via signature verification ─────────────────────────────────

class TestCorrectnessSignature:
    def test_result_signature_matches(self):
        """Verify the complete result matches the expected canonical digest."""
        results = load_results()
        actual_sig = _compute_signature(results)
        assert actual_sig == _VERIFICATION_DIGEST, (
            "Result signature does not match expected analysis. "
            "Verify anomaly classification, affected switches, flow mapping, "
            "root cause identification, and cycle detection."
        )


# ── data integrity tests ──────────────────────────────────────────────────

class TestDataIntegrity:
    def test_all_anomaly_switches_have_significant_pfc_activity(self):
        """Every affected switch must have substantial PFC events above XOFF."""
        results = load_results()
        conn = sqlite3.connect("/app/fabric.db")
        c = conn.cursor()
        c.execute("SELECT xoff_threshold_bytes FROM pfc_config WHERE priority=3")
        xoff = c.fetchone()[0]

        for anomaly in results["anomalies"]:
            for sw in anomaly["affected_switches"]:
                c.execute("""
                    SELECT COUNT(*) FROM pfc_events
                    WHERE event_type = 'PFC_PAUSE_SENT'
                      AND switch_id = ?
                      AND queue_depth_bytes >= ?
                """, (sw, xoff))
                count = c.fetchone()[0]
                assert count >= 10, (
                    f"Switch {sw} in anomaly {anomaly.get('id', '?')} has only "
                    f"{count} significant PFC events — insufficient to indicate "
                    f"a real anomaly"
                )
        conn.close()

    def test_affected_flows_traverse_affected_switches(self):
        """Each claimed affected flow must route through an affected switch."""
        results = load_results()
        with open("/app/victim_flows.json") as f:
            flows = json.load(f)
        flow_map = {f["flow_id"]: f for f in flows}

        for anomaly in results["anomalies"]:
            affected_sw = set(anomaly["affected_switches"])
            for fid in anomaly["affected_flow_ids"]:
                assert fid in flow_map, (
                    f"Flow {fid} not found in victim_flows.json"
                )
                path = set(flow_map[fid]["path"])
                assert path & affected_sw, (
                    f"Flow {fid} does not traverse any affected switch "
                    f"in anomaly {anomaly.get('id', '?')}"
                )

    def test_no_flow_in_multiple_anomalies(self):
        """Each flow should be attributed to at most one anomaly."""
        results = load_results()
        seen = set()
        for anomaly in results["anomalies"]:
            fids = set(anomaly["affected_flow_ids"])
            overlap = seen & fids
            assert not overlap, (
                f"Flow(s) {overlap} appear in multiple anomalies"
            )
            seen |= fids


# ── severity property tests ───────────────────────────────────────────────

class TestSeverityProperties:
    def test_severity_scores_are_positive(self):
        results = load_results()
        for a in results["anomalies"]:
            assert isinstance(a["severity_score"], (int, float))
            assert a["severity_score"] > 0, (
                f"Anomaly {a.get('id', '?')} has non-positive severity"
            )

    def test_deadlock_more_severe_than_attack(self):
        results = load_results()
        attack = _get_by_type(results, "attack")
        deadlock = _get_by_type(results, "deadlock")
        assert deadlock["severity_score"] > attack["severity_score"], (
            "Deadlock anomaly should have higher severity than attack"
        )

    def test_severity_consistent_with_pfc_data(self):
        """Verify severity is consistent with PFC event data for the claimed switches."""
        results = load_results()
        conn = sqlite3.connect("/app/fabric.db")
        c = conn.cursor()
        c.execute("SELECT xoff_threshold_bytes FROM pfc_config WHERE priority=3")
        xoff = c.fetchone()[0]

        for anomaly in results["anomalies"]:
            switches = anomaly["affected_switches"]
            if not switches:
                continue
            placeholders = ",".join("?" * len(switches))
            c.execute(f"""
                SELECT SUM(pause_duration_us), MIN(timestamp_us), MAX(timestamp_us)
                FROM pfc_events
                WHERE event_type = 'PFC_PAUSE_SENT'
                  AND queue_depth_bytes >= ?
                  AND switch_id IN ({placeholders})
            """, [xoff] + list(switches))
            total_pause, min_ts, max_ts = c.fetchone()
            assert total_pause is not None and total_pause > 0, (
                f"No significant PFC pause duration for anomaly {anomaly.get('id', '?')}"
            )
            assert max_ts > min_ts, (
                f"Zero time span for anomaly {anomaly.get('id', '?')}"
            )
        conn.close()


# ── provenance DOT output ────────────────────────────────────────────────

class TestProvenanceDot:
    def test_dot_file_exists(self):
        assert os.path.exists("/app/provenance.dot"), "provenance.dot not found"

    def test_dot_valid_syntax(self):
        result = subprocess.run(
            ["dot", "-Tsvg", "/app/provenance.dot", "-o", "/dev/null"],
            capture_output=True,
        )
        assert result.returncode == 0, (
            f"dot compilation failed: {result.stderr.decode()}"
        )

    def test_dot_is_digraph(self):
        with open("/app/provenance.dot") as f:
            content = f.read()
        assert "digraph" in content, "provenance.dot must be a directed graph"

    def test_dot_has_directed_edges(self):
        with open("/app/provenance.dot") as f:
            content = f.read()
        assert "->" in content, "provenance.dot must contain directed edges (->)"

    def test_dot_references_anomaly_switches(self):
        """Provenance graph should reference switches from all anomalies."""
        results = load_results()
        with open("/app/provenance.dot") as f:
            dot_content = f.read()
        all_switches = set()
        for a in results["anomalies"]:
            all_switches.update(a["affected_switches"])
        for sw in all_switches:
            assert sw in dot_content, (
                f"Switch {sw} from anomaly results not found in provenance.dot"
            )
