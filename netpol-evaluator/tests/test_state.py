"""Tests for Kubernetes NetworkPolicy traffic evaluator.

Verifies the evaluator at /app/netpol-eval produces correct ALLOW/DENY
decisions for traffic flows across 9 static YAML scenarios, 2 tool-
integration scenarios (kustomize overlay and split YAML files), and
6 dynamically generated scenarios.

"""

import os
import subprocess

import pytest

EVAL_PATH = "/app/netpol-eval"
MANIFESTS_DIR = "/app/manifests"


def run_eval(manifests_dir, src, dst, port, protocol):
    """Run the evaluator and return stripped stdout."""
    result = subprocess.run(
        [EVAL_PATH, manifests_dir, src, dst, str(port), protocol],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout.strip()


# -- Static scenario test cases -----------------------------------------------
# Queries and expected values defined here, NOT in the scenario YAML files.

STATIC_CASES = [
    # scenario-01: default-allow (no policies)
    ("scenario-01", "alpha/web", "beta/api", 8080, "TCP", "ALLOW"),
    ("scenario-01", "beta/api", "alpha/web", 80, "TCP", "ALLOW"),
    ("scenario-01", "alpha/web", "alpha/cache", 6379, "TCP", "ALLOW"),
    ("scenario-01", "beta/worker", "beta/api", 443, "UDP", "ALLOW"),

    # scenario-02: deny-all ingress on 'secure' namespace
    ("scenario-02", "open/frontend", "secure/db", 5432, "TCP", "DENY"),
    ("scenario-02", "open/external-api", "secure/internal-api", 8080, "TCP", "DENY"),
    ("scenario-02", "secure/db", "open/frontend", 80, "TCP", "ALLOW"),
    ("scenario-02", "secure/internal-api", "secure/db", 5432, "TCP", "DENY"),
    ("scenario-02", "open/frontend", "open/external-api", 8080, "TCP", "ALLOW"),
    ("scenario-02", "secure/internal-api", "open/external-api", 8080, "TCP", "ALLOW"),

    # scenario-03: selective ingress (frontend->backend api on port 8080)
    ("scenario-03", "frontend/webapp", "backend/api-server", 8080, "TCP", "ALLOW"),
    ("scenario-03", "frontend/admin", "backend/api-server", 8080, "TCP", "ALLOW"),
    ("scenario-03", "frontend/webapp", "backend/api-server", 9090, "TCP", "DENY"),
    ("scenario-03", "frontend/webapp", "backend/worker", 8080, "TCP", "DENY"),
    ("scenario-03", "monitoring/prometheus", "backend/api-server", 8080, "TCP", "DENY"),
    ("scenario-03", "backend/api-server", "backend/worker", 8080, "TCP", "DENY"),

    # scenario-04: AND vs OR selector composition
    ("scenario-04", "prod-ns/prod-client", "target/server-and", 8080, "TCP", "ALLOW"),
    ("scenario-04", "prod-ns/prod-admin", "target/server-and", 8080, "TCP", "DENY"),
    ("scenario-04", "dev-ns/dev-client", "target/server-and", 8080, "TCP", "DENY"),
    ("scenario-04", "target/local-client", "target/server-and", 8080, "TCP", "DENY"),
    ("scenario-04", "prod-ns/prod-client", "target/server-or", 8080, "TCP", "ALLOW"),
    ("scenario-04", "prod-ns/prod-admin", "target/server-or", 8080, "TCP", "ALLOW"),
    ("scenario-04", "dev-ns/dev-client", "target/server-or", 8080, "TCP", "DENY"),
    ("scenario-04", "target/local-client", "target/server-or", 8080, "TCP", "ALLOW"),
    ("scenario-04", "staging-ns/staging-client", "target/server-or", 8080, "TCP", "DENY"),
    ("scenario-04", "staging-ns/staging-client", "target/server-and", 8080, "TCP", "DENY"),

    # scenario-05: bidirectional egress+ingress evaluation
    ("scenario-05", "client-ns/allowed-client", "server-ns/service", 443, "TCP", "ALLOW"),
    ("scenario-05", "client-ns/allowed-client", "server-ns/service", 8080, "TCP", "DENY"),
    ("scenario-05", "client-ns/allowed-client", "server-ns/database", 443, "TCP", "DENY"),
    ("scenario-05", "client-ns/blocked-client", "server-ns/service", 443, "TCP", "DENY"),
    ("scenario-05", "server-ns/service", "client-ns/allowed-client", 80, "TCP", "ALLOW"),
    ("scenario-05", "server-ns/database", "server-ns/service", 443, "TCP", "DENY"),

    # scenario-06: multi-policy union
    ("scenario-06", "admin/dashboard", "apps/webserver", 443, "TCP", "ALLOW"),
    ("scenario-06", "admin/dashboard", "apps/webserver", 8080, "TCP", "DENY"),
    ("scenario-06", "cicd/deployer", "apps/webserver", 8080, "TCP", "ALLOW"),
    ("scenario-06", "cicd/deployer", "apps/webserver", 443, "TCP", "DENY"),
    ("scenario-06", "apps/backend", "apps/webserver", 9090, "TCP", "ALLOW"),
    ("scenario-06", "apps/backend", "apps/webserver", 443, "TCP", "ALLOW"),
    ("scenario-06", "admin/dashboard", "apps/backend", 8080, "TCP", "DENY"),
    ("scenario-06", "apps/webserver", "apps/backend", 8080, "TCP", "DENY"),

    # scenario-07: port ranges with endPort, protocol filtering
    ("scenario-07", "nettest/client-a", "nettest/server", 8080, "TCP", "ALLOW"),
    ("scenario-07", "nettest/client-a", "nettest/server", 8000, "TCP", "ALLOW"),
    ("scenario-07", "nettest/client-a", "nettest/server", 9000, "TCP", "ALLOW"),
    ("scenario-07", "nettest/client-a", "nettest/server", 7999, "TCP", "DENY"),
    ("scenario-07", "nettest/client-a", "nettest/server", 9001, "TCP", "DENY"),
    ("scenario-07", "nettest/client-a", "nettest/server", 8080, "UDP", "DENY"),
    ("scenario-07", "nettest/client-b", "nettest/server", 53, "UDP", "ALLOW"),
    ("scenario-07", "nettest/client-b", "nettest/server", 53, "TCP", "DENY"),
    ("scenario-07", "nettest/client-b", "nettest/server", 8080, "TCP", "DENY"),
    ("scenario-07", "nettest/client-a", "nettest/server", 53, "UDP", "DENY"),

    # scenario-08: CIDR blocks with exceptions
    ("scenario-08", "corp/app-a", "dmz/lb", 443, "TCP", "ALLOW"),
    ("scenario-08", "corp/app-b", "dmz/lb", 443, "TCP", "DENY"),
    ("scenario-08", "corp/app-c", "dmz/lb", 443, "TCP", "ALLOW"),
    ("scenario-08", "corp/app-a", "dmz/lb", 8080, "TCP", "DENY"),
    ("scenario-08", "corp/app-a", "dmz/lb", 443, "UDP", "DENY"),
    ("scenario-08", "dmz/lb", "corp/app-a", 80, "TCP", "ALLOW"),
    ("scenario-08", "corp/app-b", "dmz/lb", 80, "TCP", "DENY"),
    ("scenario-08", "corp/app-c", "dmz/lb", 80, "TCP", "DENY"),

    # scenario-09: complex multi-tenant with matchExpressions
    ("scenario-09", "tenant-a/payment-api", "tenant-a/payment-worker", 8080, "TCP", "ALLOW"),
    ("scenario-09", "tenant-a/payment-api", "tenant-b/health-api", 8080, "TCP", "DENY"),
    ("scenario-09", "tenant-a/payment-api", "shared-infra/logging", 5514, "TCP", "ALLOW"),
    ("scenario-09", "tenant-a/payment-api", "shared-infra/logging", 8080, "TCP", "DENY"),
    ("scenario-09", "dev-sandbox/test-app", "shared-infra/logging", 5514, "TCP", "DENY"),
    ("scenario-09", "tenant-b/health-api", "shared-infra/logging", 5514, "TCP", "ALLOW"),
    ("scenario-09", "tenant-b/health-api", "shared-infra/metrics", 9090, "TCP", "DENY"),
    ("scenario-09", "dev-sandbox/test-app", "tenant-a/payment-api", 8080, "TCP", "DENY"),
    ("scenario-09", "shared-infra/logging", "tenant-a/payment-api", 8080, "TCP", "DENY"),
    ("scenario-09", "tenant-a/payment-worker", "shared-infra/metrics", 9090, "TCP", "ALLOW"),

    # scenario-10: kustomize overlay — zero-trust service mesh
    ("scenario-10", "mesh-control/envoy-proxy", "mesh-data/worker-a", 15001, "TCP", "ALLOW"),
    ("scenario-10", "mesh-control/config-server", "mesh-data/worker-a", 15001, "TCP", "DENY"),
    ("scenario-10", "mesh-data/worker-a", "mesh-control/config-server", 8443, "TCP", "ALLOW"),
    ("scenario-10", "mesh-data/worker-a", "mesh-control/envoy-proxy", 8443, "TCP", "DENY"),
    ("scenario-10", "mesh-data/worker-a", "mesh-data/worker-b", 8080, "TCP", "DENY"),
    ("scenario-10", "mesh-control/envoy-proxy", "mesh-data/worker-a", 8080, "TCP", "DENY"),

    # scenario-11: split YAML files — edge gateway
    ("scenario-11", "edge/ingress-gw", "core/app", 8080, "TCP", "ALLOW"),
    ("scenario-11", "edge/waf", "core/app", 8080, "TCP", "DENY"),
    ("scenario-11", "edge/ingress-gw", "core/db", 5432, "TCP", "DENY"),
    ("scenario-11", "edge/ingress-gw", "core/app", 9090, "TCP", "DENY"),
    ("scenario-11", "core/app", "core/db", 5432, "TCP", "DENY"),
    ("scenario-11", "edge/waf", "edge/ingress-gw", 80, "TCP", "ALLOW"),
]


def make_test_id(case):
    scenario, src, dst, port, proto, expected = case
    return f"{scenario}::{src}->{dst}:{port}/{proto}={expected}"


class TestEvaluatorBasic:
    def test_evaluator_exists_and_executable(self):
        assert os.path.exists(EVAL_PATH), f"Evaluator not found at {EVAL_PATH}"
        assert os.access(EVAL_PATH, os.X_OK), (
            f"Evaluator at {EVAL_PATH} is not executable"
        )

    def test_manifests_present(self):
        dirs = [
            d
            for d in os.listdir(MANIFESTS_DIR)
            if os.path.isdir(os.path.join(MANIFESTS_DIR, d))
        ]
        assert len(dirs) >= 11, (
            f"Expected at least 11 scenario directories, found {len(dirs)}"
        )

    def test_kustomize_available(self):
        result = subprocess.run(
            ["kustomize", "version"], capture_output=True, text=True
        )
        assert result.returncode == 0, "kustomize must be available on PATH"

    def test_yq_available(self):
        result = subprocess.run(
            ["yq", "--version"], capture_output=True, text=True
        )
        assert result.returncode == 0, "yq must be available on PATH"


class TestStaticScenarios:
    @pytest.mark.parametrize(
        "scenario,src,dst,port,protocol,expected",
        STATIC_CASES,
        ids=[make_test_id(c) for c in STATIC_CASES],
    )
    def test_traffic_evaluation(self, scenario, src, dst, port, protocol, expected):
        manifests_dir = os.path.join(MANIFESTS_DIR, scenario)
        actual = run_eval(manifests_dir, src, dst, port, protocol)
        assert actual == expected, (
            f"Traffic {src} -> {dst}:{port}/{protocol}: "
            f"expected {expected}, got '{actual}'"
        )


# -- Dynamically generated scenarios (anti-cheat) -----------------------------
# These scenarios are created at test time and do NOT exist in the
# Docker image, preventing lookup-table bypasses.


def _write_yaml(path, content):
    with open(path, "w") as f:
        f.write(content)


class TestDynamicScenarioDefaultAllow:
    """Runtime-generated: no policies -> all traffic allowed."""

    @pytest.fixture(autouse=True)
    def setup_scenario(self, tmp_path):
        self.scenario_dir = str(tmp_path / "dyn-default-allow")
        os.makedirs(self.scenario_dir, exist_ok=True)
        _write_yaml(
            os.path.join(self.scenario_dir, "cluster.yaml"),
            """\
apiVersion: v1
kind: Namespace
metadata:
  name: ns-x
  labels:
    env: test
---
apiVersion: v1
kind: Pod
metadata:
  name: ping
  namespace: ns-x
  labels:
    app: ping
status:
  podIP: "10.200.0.1"
---
apiVersion: v1
kind: Pod
metadata:
  name: pong
  namespace: ns-x
  labels:
    app: pong
status:
  podIP: "10.200.0.2"
""",
        )

    def test_all_traffic_allowed(self):
        assert run_eval(self.scenario_dir, "ns-x/ping", "ns-x/pong", 80, "TCP") == "ALLOW"
        assert run_eval(self.scenario_dir, "ns-x/pong", "ns-x/ping", 443, "UDP") == "ALLOW"


class TestDynamicScenarioDenyAll:
    """Runtime-generated: deny-all ingress -> all inbound denied."""

    @pytest.fixture(autouse=True)
    def setup_scenario(self, tmp_path):
        self.scenario_dir = str(tmp_path / "dyn-deny-all")
        os.makedirs(self.scenario_dir, exist_ok=True)
        _write_yaml(
            os.path.join(self.scenario_dir, "cluster.yaml"),
            """\
apiVersion: v1
kind: Namespace
metadata:
  name: locked
  labels:
    env: locked
---
apiVersion: v1
kind: Pod
metadata:
  name: sender
  namespace: locked
  labels:
    role: sender
status:
  podIP: "10.201.0.1"
---
apiVersion: v1
kind: Pod
metadata:
  name: receiver
  namespace: locked
  labels:
    role: receiver
status:
  podIP: "10.201.0.2"
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-all
  namespace: locked
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
""",
        )

    def test_all_traffic_denied(self):
        assert run_eval(self.scenario_dir, "locked/sender", "locked/receiver", 80, "TCP") == "DENY"
        assert run_eval(self.scenario_dir, "locked/receiver", "locked/sender", 443, "TCP") == "DENY"


class TestDynamicScenarioSelectiveAllow:
    """Runtime-generated: deny-all + allow from specific namespace."""

    @pytest.fixture(autouse=True)
    def setup_scenario(self, tmp_path):
        self.scenario_dir = str(tmp_path / "dyn-selective")
        os.makedirs(self.scenario_dir, exist_ok=True)
        _write_yaml(
            os.path.join(self.scenario_dir, "cluster.yaml"),
            """\
apiVersion: v1
kind: Namespace
metadata:
  name: allowed
  labels:
    tier: web
---
apiVersion: v1
kind: Namespace
metadata:
  name: blocked
  labels:
    tier: batch
---
apiVersion: v1
kind: Namespace
metadata:
  name: protected
  labels:
    tier: db
---
apiVersion: v1
kind: Pod
metadata:
  name: webclient
  namespace: allowed
  labels:
    app: webclient
status:
  podIP: "10.202.1.1"
---
apiVersion: v1
kind: Pod
metadata:
  name: batchjob
  namespace: blocked
  labels:
    app: batchjob
status:
  podIP: "10.202.2.1"
---
apiVersion: v1
kind: Pod
metadata:
  name: dbserver
  namespace: protected
  labels:
    app: database
status:
  podIP: "10.202.3.1"
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-all
  namespace: protected
spec:
  podSelector: {}
  policyTypes:
  - Ingress
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-web-tier
  namespace: protected
spec:
  podSelector: {}
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          tier: web
    ports:
    - protocol: TCP
      port: 5432
  policyTypes:
  - Ingress
""",
        )

    def test_selective_access(self):
        assert run_eval(self.scenario_dir, "allowed/webclient", "protected/dbserver", 5432, "TCP") == "ALLOW"
        assert run_eval(self.scenario_dir, "blocked/batchjob", "protected/dbserver", 5432, "TCP") == "DENY"
        assert run_eval(self.scenario_dir, "allowed/webclient", "protected/dbserver", 3306, "TCP") == "DENY"


class TestDynamicPolicyTypesInference:
    """Runtime-generated: policyTypes absent -> inferred from spec."""

    @pytest.fixture(autouse=True)
    def setup_scenario(self, tmp_path):
        self.scenario_dir = str(tmp_path / "dyn-infer")
        os.makedirs(self.scenario_dir, exist_ok=True)
        _write_yaml(
            os.path.join(self.scenario_dir, "cluster.yaml"),
            """\
apiVersion: v1
kind: Namespace
metadata:
  name: infer
  labels:
    env: test
---
apiVersion: v1
kind: Pod
metadata:
  name: src
  namespace: infer
  labels:
    app: src
status:
  podIP: "10.203.0.1"
---
apiVersion: v1
kind: Pod
metadata:
  name: dst
  namespace: infer
  labels:
    app: dst
status:
  podIP: "10.203.0.2"
---
apiVersion: v1
kind: Pod
metadata:
  name: other
  namespace: infer
  labels:
    app: other
status:
  podIP: "10.203.0.3"
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: implicit-types
  namespace: infer
spec:
  podSelector:
    matchLabels:
      app: src
  egress:
  - to:
    - podSelector:
        matchLabels:
          app: dst
""",
        )

    def test_policytypes_inferred(self):
        # policyTypes absent + egress present -> Ingress and Egress both inferred.
        # Ingress to src: denied (no ingress rules in policy, but Ingress type inferred)
        assert run_eval(self.scenario_dir, "infer/other", "infer/src", 80, "TCP") == "DENY"
        # Egress from src to dst: allowed (explicit egress rule)
        assert run_eval(self.scenario_dir, "infer/src", "infer/dst", 80, "TCP") == "ALLOW"
        # Egress from src to other: denied (only dst allowed)
        assert run_eval(self.scenario_dir, "infer/src", "infer/other", 80, "TCP") == "DENY"
        # Traffic not involving src: no policies select dst or other -> default allow
        assert run_eval(self.scenario_dir, "infer/other", "infer/dst", 80, "TCP") == "ALLOW"


class TestDynamicKustomize:
    """Runtime-generated: kustomize overlay with deny-all policy.

    Verifies that the evaluator correctly handles kustomize-format
    manifest directories by running kustomize build at evaluation time.
    """

    @pytest.fixture(autouse=True)
    def setup_scenario(self, tmp_path):
        self.scenario_dir = str(tmp_path / "dyn-kustomize")
        os.makedirs(self.scenario_dir, exist_ok=True)

        _write_yaml(
            os.path.join(self.scenario_dir, "kustomization.yaml"),
            """\
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - resources.yaml
""",
        )

        _write_yaml(
            os.path.join(self.scenario_dir, "resources.yaml"),
            """\
apiVersion: v1
kind: Namespace
metadata:
  name: ktest
  labels:
    env: test
---
apiVersion: v1
kind: Pod
metadata:
  name: client
  namespace: ktest
  labels:
    app: client
status:
  podIP: "10.210.0.1"
---
apiVersion: v1
kind: Pod
metadata:
  name: server
  namespace: ktest
  labels:
    app: server
status:
  podIP: "10.210.0.2"
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-all
  namespace: ktest
spec:
  podSelector: {}
  policyTypes:
    - Ingress
""",
        )

    def test_kustomize_deny(self):
        assert run_eval(self.scenario_dir, "ktest/client", "ktest/server", 80, "TCP") == "DENY"

    def test_kustomize_reverse_deny(self):
        assert run_eval(self.scenario_dir, "ktest/server", "ktest/client", 80, "TCP") == "DENY"


class TestDynamicSplitFiles:
    """Runtime-generated: split YAML files (no cluster.yaml, no kustomization.yaml).

    Verifies the evaluator can load manifests from multiple .yaml files
    when neither cluster.yaml nor kustomization.yaml is present.
    """

    @pytest.fixture(autouse=True)
    def setup_scenario(self, tmp_path):
        self.scenario_dir = str(tmp_path / "dyn-split")
        os.makedirs(self.scenario_dir, exist_ok=True)

        _write_yaml(
            os.path.join(self.scenario_dir, "namespaces.yaml"),
            """\
apiVersion: v1
kind: Namespace
metadata:
  name: split-ns
  labels:
    env: split
""",
        )

        _write_yaml(
            os.path.join(self.scenario_dir, "pods.yaml"),
            """\
apiVersion: v1
kind: Pod
metadata:
  name: alpha
  namespace: split-ns
  labels:
    role: alpha
status:
  podIP: "10.211.0.1"
---
apiVersion: v1
kind: Pod
metadata:
  name: beta
  namespace: split-ns
  labels:
    role: beta
status:
  podIP: "10.211.0.2"
""",
        )

        _write_yaml(
            os.path.join(self.scenario_dir, "policies.yaml"),
            """\
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-all
  namespace: split-ns
spec:
  podSelector: {}
  policyTypes:
    - Ingress
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-alpha
  namespace: split-ns
spec:
  podSelector:
    matchLabels:
      role: beta
  ingress:
    - from:
        - podSelector:
            matchLabels:
              role: alpha
      ports:
        - protocol: TCP
          port: 9090
  policyTypes:
    - Ingress
""",
        )

    def test_split_allowed(self):
        assert run_eval(self.scenario_dir, "split-ns/alpha", "split-ns/beta", 9090, "TCP") == "ALLOW"

    def test_split_denied_wrong_source(self):
        assert run_eval(self.scenario_dir, "split-ns/beta", "split-ns/alpha", 9090, "TCP") == "DENY"

    def test_split_denied_wrong_port(self):
        assert run_eval(self.scenario_dir, "split-ns/alpha", "split-ns/beta", 8080, "TCP") == "DENY"
