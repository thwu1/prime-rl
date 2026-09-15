
import subprocess
import json
import os
import tempfile
import pytest

ANALYZER = "/app/analyzer.py"


def run_query(src, dst, port, protocol="TCP"):
    """Run a pod-to-pod connectivity query."""
    cmd = ["python3", ANALYZER, "query", src, dst, str(port)]
    if protocol != "TCP":
        cmd.append(protocol)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, (
        f"Analyzer exited with code {result.returncode}. "
        f"stderr: {result.stderr}"
    )
    return result.stdout.strip()


def run_query_ip(src_ip, dst, port, protocol="TCP"):
    """Run an external IP ingress query."""
    cmd = ["python3", ANALYZER, "query-ip", src_ip, dst, str(port)]
    if protocol != "TCP":
        cmd.append(protocol)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, (
        f"Analyzer exited with code {result.returncode}. "
        f"stderr: {result.stderr}"
    )
    return result.stdout.strip()


def run_unprotected():
    """Run unprotected pod analysis."""
    cmd = ["python3", ANALYZER, "unprotected"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, (
        f"Analyzer exited with code {result.returncode}. "
        f"stderr: {result.stderr}"
    )
    return json.loads(result.stdout.strip())


def run_graph():
    """Run graph generation and return DOT output."""
    cmd = ["python3", ANALYZER, "graph"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, (
        f"Analyzer exited with code {result.returncode}. "
        f"stderr: {result.stderr}"
    )
    return result.stdout.strip()


class TestKustomizeRendering:
    """Verify the analyzer correctly uses kustomize build."""

    def test_kustomize_build_works(self):
        """The analyzer must successfully render the production overlay."""
        result = subprocess.run(
            ["python3", ANALYZER, "unprotected"],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, (
            f"Analyzer failed (possibly kustomize build issue). "
            f"stderr: {result.stderr}"
        )
        data = json.loads(result.stdout.strip())
        assert "unprotected_ingress" in data
        assert "unprotected_egress" in data


class TestAllowedConnections:
    """Verify connections that must be ALLOWED."""

    def test_frontend_to_api_8080(self):
        """Frontend egress allows compute:backend:named('http-api')=8080; API ingress allows web:8080."""
        assert run_query("alpha/web-frontend", "beta/api-server", 8080) == "ALLOWED"

    def test_cache_to_api_8080(self):
        """Cache pod has tier=frontend so same egress policy applies."""
        assert run_query("alpha/web-cache", "beta/api-server", 8080) == "ALLOWED"

    def test_api_to_db_primary_5432(self):
        """Backend egress allows storage:5432; data ingress allows compute:backend:named('pg')=5432."""
        assert run_query("beta/api-server", "gamma/db-primary", 5432) == "ALLOWED"

    def test_worker_to_db_primary_5432(self):
        """Worker has tier=backend, same egress+ingress evaluation."""
        assert run_query("beta/task-worker", "gamma/db-primary", 5432) == "ALLOWED"

    def test_primary_to_replica_5432(self):
        """Primary egress named('pg')=5432 to replica; data-ingress named('pg')=5432 from primary."""
        assert run_query("gamma/db-primary", "gamma/db-replica", 5432) == "ALLOWED"

    def test_monitor_to_frontend_80(self):
        """No egress policy in delta; frontend ingress allows port 80 from any namespace."""
        assert run_query("delta/monitor", "alpha/web-frontend", 80) == "ALLOWED"

    def test_monitor_to_frontend_443(self):
        """Frontend ingress allows tier=infra AND purpose=monitoring namespace on port 443."""
        assert run_query("delta/monitor", "alpha/web-frontend", 443) == "ALLOWED"

    def test_monitor_to_api_9090(self):
        """API ingress allows tier=infra AND purpose=monitoring on all ports (no port spec)."""
        assert run_query("delta/monitor", "beta/api-server", 9090) == "ALLOWED"

    def test_delta_intra_no_policy(self):
        """No NetworkPolicies in delta; all intra-namespace traffic allowed."""
        assert run_query("delta/monitor", "delta/logger", 24224) == "ALLOWED"

    def test_api_to_search_9200(self):
        """Backend-search-egress named('es-http')=9200 on search-engine; search-ingress matchExpressions tier In [backend,infra] named('es-http')=9200."""
        assert run_query("beta/api-server", "gamma/search-engine", 9200) == "ALLOWED"

    def test_monitor_to_search_9200(self):
        """No delta egress; search-ingress matchExpressions tier In [backend,infra]; monitor has tier=infra."""
        assert run_query("delta/monitor", "gamma/search-engine", 9200) == "ALLOWED"

    def test_ingress_ctrl_to_frontend_80(self):
        """Edge egress allows alpha:80 endPort 82; frontend ingress allows port 80 from any ns."""
        assert run_query("epsilon/ingress-ctrl", "alpha/web-frontend", 80) == "ALLOWED"


class TestDeniedConnections:
    """Verify connections that must be DENIED."""

    def test_frontend_to_db_egress_blocked(self):
        """Frontend egress only allows compute namespace, not storage."""
        assert run_query("alpha/web-frontend", "gamma/db-primary", 5432) == "DENIED"

    def test_frontend_to_api_wrong_port(self):
        """Frontend egress named('http-api')=8080, not 9090."""
        assert run_query("alpha/web-frontend", "beta/api-server", 9090) == "DENIED"

    def test_frontend_same_ns_blocked(self):
        """Frontend egress has no rule for alpha namespace traffic."""
        assert run_query("alpha/web-frontend", "alpha/web-cache", 6379) == "DENIED"

    def test_api_to_frontend_egress_blocked(self):
        """Backend egress only allows storage namespace, not web."""
        assert run_query("beta/api-server", "alpha/web-frontend", 80) == "DENIED"

    def test_monitor_to_worker_denied(self):
        """Worker has deny-all ingress (policyTypes: [Ingress] with no rules)."""
        assert run_query("delta/monitor", "beta/task-worker", 8080) == "DENIED"

    def test_replica_egress_denied(self):
        """Replica has deny-all egress (policyTypes: [Egress] with no rules)."""
        assert run_query("gamma/db-replica", "gamma/db-primary", 5432) == "DENIED"

    def test_monitor_to_db_wrong_labels(self):
        """Data ingress requires compute:backend via named('pg'); monitor is infra, not backend."""
        assert run_query("delta/monitor", "gamma/db-primary", 5432) == "DENIED"

    def test_api_to_db_wrong_port(self):
        """Backend egress to storage allows port 5432 only, not 80."""
        assert run_query("beta/api-server", "gamma/db-primary", 80) == "DENIED"

    def test_api_to_db_primary_9200_named_port_no_resolve(self):
        """Backend-search-egress named('es-http') doesn't resolve on db-primary (no 'es-http' port)."""
        assert run_query("beta/api-server", "gamma/db-primary", 9200) == "DENIED"

    def test_search_egress_denied(self):
        """search-engine has deny-all egress policy."""
        assert run_query("gamma/search-engine", "gamma/db-primary", 5432) == "DENIED"

    def test_ingress_ctrl_to_frontend_443_outside_endport(self):
        """Edge egress port range [80,82] does not include 443."""
        assert run_query("epsilon/ingress-ctrl", "alpha/web-frontend", 443) == "DENIED"

    def test_frontend_to_worker_named_port_no_resolve(self):
        """Frontend egress named('http-api') doesn't resolve on task-worker (no container ports)."""
        assert run_query("alpha/web-frontend", "beta/task-worker", 8080) == "DENIED"

    def test_monitor_to_ingress_ctrl_ipblock_only(self):
        """ingress-ctrl has ipBlock-only ingress policy; pod sources don't match ipBlock peers."""
        assert run_query("delta/monitor", "epsilon/ingress-ctrl", 80) == "DENIED"


class TestQueryIp:
    """Verify external IP ingress queries with ipBlock CIDR rules."""

    def test_ip_in_cidr_allowed(self):
        """10.1.2.3 is in 10.0.0.0/8 and not in except 10.255.0.0/16; port 80 matches."""
        assert run_query_ip("10.1.2.3", "epsilon/ingress-ctrl", 80) == "ALLOWED"

    def test_ip_in_except_denied(self):
        """10.255.1.1 is in 10.0.0.0/8 but also in except range 10.255.0.0/16."""
        assert run_query_ip("10.255.1.1", "epsilon/ingress-ctrl", 80) == "DENIED"

    def test_ip_second_cidr_allowed(self):
        """172.16.5.10 is in 172.16.0.0/12; port 443 matches second rule."""
        assert run_query_ip("172.16.5.10", "epsilon/ingress-ctrl", 443) == "ALLOWED"

    def test_ip_no_cidr_match_denied(self):
        """192.168.1.1 is not in any configured CIDR range."""
        assert run_query_ip("192.168.1.1", "epsilon/ingress-ctrl", 80) == "DENIED"

    def test_ip_wrong_port_denied(self):
        """10.1.2.3 matches CIDR for port 80 rule, but querying port 443; not in 172.16.0.0/12."""
        assert run_query_ip("10.1.2.3", "epsilon/ingress-ctrl", 443) == "DENIED"


class TestUnprotectedPods:
    """Verify identification of pods not covered by any NetworkPolicy."""

    def test_unprotected_pods(self):
        """Only delta namespace pods have no NetworkPolicies selecting them."""
        result = run_unprotected()
        assert "unprotected_ingress" in result, "Missing 'unprotected_ingress' key"
        assert "unprotected_egress" in result, "Missing 'unprotected_egress' key"
        assert sorted(result["unprotected_ingress"]) == [
            "delta/logger", "delta/monitor"
        ]
        assert sorted(result["unprotected_egress"]) == [
            "delta/logger", "delta/monitor"
        ]


class TestGraph:
    """Verify DOT graph generation."""

    def test_graph_valid_dot(self):
        """Graph output must be valid DOT parseable by graphviz."""
        dot_output = run_graph()
        assert dot_output.startswith("digraph"), "Output must start with 'digraph'"
        assert dot_output.endswith("}"), "Output must end with '}'"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".dot", delete=False) as f:
            f.write(dot_output)
            dot_file = f.name

        try:
            result = subprocess.run(
                ["dot", "-Tsvg", dot_file],
                capture_output=True, text=True, timeout=30
            )
            assert result.returncode == 0, (
                f"graphviz dot failed to parse output: {result.stderr}"
            )
            assert "<svg" in result.stdout, "dot did not produce SVG output"
        finally:
            os.unlink(dot_file)

    def test_graph_edges(self):
        """Graph must contain expected edges and not contain impossible ones."""
        dot_output = run_graph()

        # These edges must exist (ALLOWED connections)
        assert '"alpha/web-frontend" -> "beta/api-server"' in dot_output, \
            "Missing edge: web-frontend -> api-server"
        assert '"beta/api-server" -> "gamma/db-primary"' in dot_output, \
            "Missing edge: api-server -> db-primary"
        assert '"delta/monitor" -> "alpha/web-frontend"' in dot_output, \
            "Missing edge: monitor -> web-frontend"
        assert '"beta/api-server" -> "gamma/search-engine"' in dot_output, \
            "Missing edge: api-server -> search-engine"
        assert '"gamma/db-primary" -> "gamma/db-replica"' in dot_output, \
            "Missing edge: db-primary -> db-replica"
        assert '"epsilon/ingress-ctrl" -> "alpha/web-frontend"' in dot_output, \
            "Missing edge: ingress-ctrl -> web-frontend"

        # These edges must NOT exist (DENIED connections)
        assert '"gamma/db-replica" -> "gamma/db-primary"' not in dot_output, \
            "Unexpected edge: db-replica -> db-primary (deny-all egress)"
        assert '"gamma/search-engine" -> "gamma/db-primary"' not in dot_output, \
            "Unexpected edge: search-engine -> db-primary (deny-all egress)"
        assert '"alpha/web-frontend" -> "gamma/db-primary"' not in dot_output, \
            "Unexpected edge: web-frontend -> db-primary (egress blocked)"
