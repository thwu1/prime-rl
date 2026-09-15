
import json
import os
import re

import pytest

REPORT_PATH = "/app/audit_report.json"
REASSIGNMENT_PATH = "/app/reassignment.json"
REMEDIATION_PATH = "/app/remediation.sh"
CLUSTER_STATE_PATH = "/app/cluster_state.json"


@pytest.fixture
def report():
    """Load the generated audit report."""
    assert os.path.exists(REPORT_PATH), f"Report not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        data = json.load(f)
    return data


@pytest.fixture
def cluster_state():
    """Load cluster state for validation."""
    with open(CLUSTER_STATE_PATH) as f:
        return json.load(f)


def _issue_exists(report, entity_substr, severity=None):
    """Check if an issue matching entity substring and optional severity exists.

    Searches entity, description, and category fields.
    """
    for issue in report.get("issues", []):
        text = " ".join(
            str(issue.get(f, "")) for f in ("entity", "description", "category")
        ).lower()
        if entity_substr.lower() not in text:
            continue
        if severity is None:
            return True
        if issue.get("severity", "").upper() == severity.upper():
            return True
    return False


# ---------------------------------------------------------------------------
# Report structure tests
# ---------------------------------------------------------------------------

class TestReportStructure:
    def test_report_exists_and_valid(self, report):
        assert isinstance(report, dict)
        for key in ("issues", "total_issues", "critical_count", "warning_count",
                     "health_score", "cluster_id"):
            assert key in report, f"Missing required field: {key}"
        assert isinstance(report["issues"], list)

    def test_health_score_valid_range(self, report):
        score = report["health_score"]
        assert isinstance(score, (int, float))
        assert 0 <= score <= 100

    def test_health_score_reflects_problems(self, report):
        """Multiple critical issues should yield a low score."""
        assert report["health_score"] <= 50

    def test_issue_counts_consistent(self, report):
        """total_issues == len(issues); severity sub-counts match."""
        assert report["total_issues"] == len(report["issues"])
        critical = sum(
            1 for i in report["issues"] if i.get("severity") == "CRITICAL"
        )
        warning = sum(
            1 for i in report["issues"] if i.get("severity") == "WARNING"
        )
        assert report["critical_count"] == critical
        assert report["warning_count"] == warning

    def test_issue_schema(self, report):
        """Every issue must have the required fields."""
        required = {"id", "severity", "category", "entity_type", "entity",
                    "description", "recommendation"}
        for issue in report["issues"]:
            missing = required - set(issue.keys())
            assert not missing, f"Issue {issue.get('id')} missing fields: {missing}"
            assert issue["severity"] in ("CRITICAL", "WARNING")

    def test_minimum_issue_count(self, report):
        """The dataset contains at least 10 distinct issues across domains."""
        assert report["total_issues"] >= 10, (
            f"Only {report['total_issues']} issues found; dataset has >=10"
        )


# ---------------------------------------------------------------------------
# Critical issue detection — the agent must identify these from expertise
# ---------------------------------------------------------------------------

class TestCriticalIssues:
    def test_payments_replication_factor_one(self, report):
        """payments topic has RF=1 — no fault tolerance for financial data."""
        assert _issue_exists(report, "payments", severity="CRITICAL"), (
            "Missing CRITICAL: payments topic has replication.factor=1"
        )

    def test_user_events_insync_equals_rf(self, report):
        """user-events min.insync.replicas=3 equals RF=3 — writes fail on any
        single broker loss."""
        assert _issue_exists(report, "user-events", severity="CRITICAL"), (
            "Missing CRITICAL: user-events min.insync.replicas equals RF"
        )

    def test_audit_processor_lag_exceeds_retention(self, report):
        """audit-processor consumer lag far exceeds audit-logs retention period."""
        assert _issue_exists(report, "audit", severity="CRITICAL"), (
            "Missing CRITICAL: audit-processor lag exceeds retention"
        )

    def test_payment_producer_acks_zero(self, report):
        """payment-producer uses acks=0 on financial topic — silent data loss."""
        found = (
            _issue_exists(report, "payment-producer", severity="CRITICAL")
            or _issue_exists(report, "payment-producer", severity="WARNING")
        )
        assert found, "Missing issue: payment-producer uses acks=0"

    def test_unclean_leader_election_enabled(self, report):
        """All brokers have unclean.leader.election.enable=true — data loss risk."""
        found = (
            _issue_exists(report, "unclean", severity="CRITICAL")
            or _issue_exists(report, "unclean", severity="WARNING")
        )
        assert found, (
            "Missing issue: unclean.leader.election.enable=true on brokers"
        )


# ---------------------------------------------------------------------------
# Warning issue detection
# ---------------------------------------------------------------------------

class TestWarningIssues:
    def test_orders_rack_awareness_violation(self, report):
        """orders has partitions with multiple replicas on the same rack."""
        assert _issue_exists(report, "orders", severity="WARNING"), (
            "Missing WARNING: orders rack-awareness violation"
        )

    def test_notifications_leader_imbalance(self, report):
        """notifications leaders concentrated on brokers 0 and 1."""
        assert _issue_exists(report, "notifications", severity="WARNING"), (
            "Missing WARNING: notifications leader imbalance"
        )

    def test_clickstream_under_replicated(self, report):
        """clickstream has partitions with ISR smaller than replica set."""
        assert _issue_exists(report, "clickstream", severity="WARNING"), (
            "Missing WARNING: clickstream under-replicated partitions"
        )

    def test_analytics_idle_consumers(self, report):
        """analytics-pipeline has more consumers than subscribed partitions."""
        assert _issue_exists(report, "analytics", severity="WARNING"), (
            "Missing WARNING: analytics-pipeline idle consumers"
        )

    def test_connect_task_failure(self, report):
        """jdbc-sink-orders has a failed task."""
        assert _issue_exists(report, "jdbc-sink-orders"), (
            "Missing issue: jdbc-sink-orders connector task failure"
        )

    def test_payments_wildcard_acl(self, report):
        """Wildcard principal (User:*) has WRITE access to payments topic."""
        found = _issue_exists(report, "payments") and (
            _issue_exists(report, "acl")
            or _issue_exists(report, "wildcard")
            or _issue_exists(report, "User:*")
        )
        assert found, (
            "Missing issue: wildcard ACL granting write to payments topic"
        )

    def test_schema_compatibility_none(self, report):
        """schema-events-value has compatibility=NONE — deserialization risk."""
        found = (
            _issue_exists(report, "schema-events")
            or _issue_exists(report, "compatibility")
        )
        assert found, (
            "Missing issue: schema-events-value compatibility set to NONE"
        )


# ---------------------------------------------------------------------------
# Partition reassignment plan tests
# ---------------------------------------------------------------------------

class TestReassignmentPlan:
    def test_reassignment_exists_and_valid(self):
        assert os.path.exists(REASSIGNMENT_PATH), (
            f"Reassignment plan not found at {REASSIGNMENT_PATH}"
        )
        with open(REASSIGNMENT_PATH) as f:
            plan = json.load(f)
        assert plan.get("version") == 1, "Reassignment plan must have version: 1"
        assert "partitions" in plan, "Reassignment plan must have partitions array"
        assert isinstance(plan["partitions"], list)
        assert len(plan["partitions"]) > 0, "Reassignment plan is empty"

    def test_reassignment_format(self):
        with open(REASSIGNMENT_PATH) as f:
            plan = json.load(f)
        for entry in plan["partitions"]:
            assert "topic" in entry, f"Missing 'topic' in reassignment entry"
            assert "partition" in entry, f"Missing 'partition' in reassignment entry"
            assert "replicas" in entry, f"Missing 'replicas' in reassignment entry"
            assert isinstance(entry["replicas"], list)

    def test_reassignment_fixes_rack_violations(self, cluster_state):
        broker_rack = {b["id"]: b["rack"] for b in cluster_state["brokers"]}
        with open(REASSIGNMENT_PATH) as f:
            plan = json.load(f)

        for entry in plan["partitions"]:
            racks = [broker_rack[r] for r in entry["replicas"]]
            assert len(racks) == len(set(racks)), (
                f"Reassignment for {entry['topic']}-{entry['partition']} still "
                f"has replicas on same rack: brokers {entry['replicas']} -> "
                f"racks {racks}"
            )

    def test_reassignment_includes_orders(self):
        """Orders topic has rack violations that must appear in the plan."""
        with open(REASSIGNMENT_PATH) as f:
            plan = json.load(f)
        topics = {e["topic"] for e in plan["partitions"]}
        assert "orders" in topics, (
            "Reassignment plan must include orders topic partitions"
        )


# ---------------------------------------------------------------------------
# Remediation script tests
# ---------------------------------------------------------------------------

class TestRemediation:
    def test_remediation_exists_and_nonempty(self):
        assert os.path.exists(REMEDIATION_PATH), (
            f"Remediation script not found at {REMEDIATION_PATH}"
        )
        with open(REMEDIATION_PATH) as f:
            content = f.read()
        assert len(content.strip()) > 100, "Remediation script is too short"

    def test_remediation_has_kafka_commands(self):
        with open(REMEDIATION_PATH) as f:
            content = f.read().lower()
        kafka_cmds = [
            "kafka-configs", "kafka-topics", "kafka-reassign",
            "kafka-leader-election", "kafka-acls"
        ]
        found = sum(1 for cmd in kafka_cmds if cmd in content)
        assert found >= 2, (
            "Remediation must contain multiple distinct Kafka CLI commands"
        )

    def test_remediation_addresses_insync(self):
        with open(REMEDIATION_PATH) as f:
            content = f.read()
        assert "min.insync.replicas" in content, (
            "Remediation must address min.insync.replicas"
        )

    def test_remediation_addresses_retention(self):
        with open(REMEDIATION_PATH) as f:
            content = f.read()
        assert "retention" in content.lower(), (
            "Remediation must address retention configuration"
        )

    def test_remediation_addresses_acls(self):
        with open(REMEDIATION_PATH) as f:
            content = f.read()
        assert "kafka-acls" in content.lower() or "acl" in content.lower(), (
            "Remediation must address ACL security issues"
        )

    def test_remediation_addresses_unclean_election(self):
        with open(REMEDIATION_PATH) as f:
            content = f.read()
        assert "unclean.leader.election" in content.lower(), (
            "Remediation must address unclean leader election"
        )
