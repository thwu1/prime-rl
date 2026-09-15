
import pytest
import yaml
import subprocess
import os
import re
from pathlib import Path

OUTPUT = "/app/output"
SPEC_PATH = "/app/spec.yaml"


@pytest.fixture(scope="session")
def spec():
    with open(SPEC_PATH) as f:
        return yaml.safe_load(f)


def parse_resource(value):
    """Parse Kubernetes resource quantities to a comparable numeric value."""
    if isinstance(value, (int, float)):
        return float(value)
    value = str(value)
    if value.endswith("Gi"):
        return float(value[:-2]) * 1024 * 1024 * 1024
    elif value.endswith("Mi"):
        return float(value[:-2]) * 1024 * 1024
    elif value.endswith("Ki"):
        return float(value[:-2]) * 1024
    elif value.endswith("m"):
        return float(value[:-1]) / 1000.0
    else:
        return float(value)


# ──────────────────────────── HTPasswd ────────────────────────────


class TestHtpasswd:
    def test_all_users_present(self, spec):
        """All users from spec must have entries in htpasswd file."""
        htpasswd_path = os.path.join(OUTPUT, "htpasswd")
        assert os.path.exists(htpasswd_path), "htpasswd file not found"
        with open(htpasswd_path) as f:
            content = f.read()
        for user in spec["identity_provider"]["users"]:
            assert f"{user['username']}:" in content, (
                f"User {user['username']} missing from htpasswd"
            )

    def test_bcrypt_hashes(self, spec):
        """All entries must use bcrypt ($2y$/$2b$/$2a$), not MD5 ($apr1$)."""
        htpasswd_path = os.path.join(OUTPUT, "htpasswd")
        with open(htpasswd_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(":", 1)
                assert len(parts) == 2, f"Malformed htpasswd line: {line}"
                username, hash_val = parts
                assert hash_val.startswith("$2"), (
                    f"User {username} uses non-bcrypt hash "
                    f"(starts with {hash_val[:6]})"
                )

    def test_passwords_verify(self, spec):
        """Passwords must verify correctly with htpasswd -vb."""
        htpasswd_path = os.path.join(OUTPUT, "htpasswd")
        for user in spec["identity_provider"]["users"]:
            result = subprocess.run(
                [
                    "htpasswd", "-vb", htpasswd_path,
                    user["username"], user["password"],
                ],
                capture_output=True,
            )
            assert result.returncode == 0, (
                f"Password verification failed for {user['username']}"
            )


# ──────────────────────────── OAuth CR ────────────────────────────


class TestOAuth:
    def test_structure(self, spec):
        path = os.path.join(OUTPUT, "oauth.yaml")
        assert os.path.exists(path), "oauth.yaml not found"
        with open(path) as f:
            doc = yaml.safe_load(f)
        assert doc["apiVersion"] == "config.openshift.io/v1"
        assert doc["kind"] == "OAuth"
        assert doc["metadata"]["name"] == "cluster"
        assert "identityProviders" in doc["spec"]

    def test_mapping_method(self, spec):
        path = os.path.join(OUTPUT, "oauth.yaml")
        with open(path) as f:
            doc = yaml.safe_load(f)
        providers = doc["spec"]["identityProviders"]
        idp = next(
            p for p in providers
            if p["name"] == spec["identity_provider"]["name"]
        )
        assert idp.get("mappingMethod") == "claim", (
            "OAuth identity provider missing mappingMethod: claim"
        )


# ──────────────────────────── Namespaces ────────────────────────────


class TestNamespaces:
    def _load_namespaces(self):
        path = os.path.join(OUTPUT, "namespaces.yaml")
        with open(path) as f:
            return [d for d in yaml.safe_load_all(f) if d is not None]

    def test_all_namespaces_present(self, spec):
        docs = self._load_namespaces()
        ns_names = {d["metadata"]["name"] for d in docs}
        for ns in spec["namespaces"]:
            assert ns["name"] in ns_names, (
                f"Namespace {ns['name']} missing from namespaces.yaml"
            )

    def test_namespace_labels(self, spec):
        """Every namespace must have exactly the labels specified."""
        docs = self._load_namespaces()
        ns_map = {d["metadata"]["name"]: d for d in docs}
        for ns_spec in spec["namespaces"]:
            ns = ns_map[ns_spec["name"]]
            labels = ns["metadata"].get("labels", {})
            for key, val in ns_spec["labels"].items():
                assert labels.get(key) == val, (
                    f"Namespace {ns_spec['name']} label {key} expected "
                    f"'{val}', got '{labels.get(key)}'"
                )


# ──────────────────────────── RBAC ────────────────────────────


class TestRBAC:
    def _load_all_rbac_docs(self):
        rbac_dir = os.path.join(OUTPUT, "rbac")
        docs = []
        for fname in os.listdir(rbac_dir):
            if fname.endswith((".yaml", ".yml")):
                with open(os.path.join(rbac_dir, fname)) as f:
                    docs.extend(
                        [d for d in yaml.safe_load_all(f) if d is not None]
                    )
        return docs

    def test_cluster_role_binding_kind(self, spec):
        """ClusterRoleBinding roleRef must use kind: ClusterRole."""
        docs = self._load_all_rbac_docs()
        for crb_spec in spec["rbac"]["cluster_role_bindings"]:
            doc = next(
                (d for d in docs
                 if d.get("metadata", {}).get("name") == crb_spec["name"]),
                None,
            )
            assert doc is not None, (
                f"ClusterRoleBinding {crb_spec['name']} not found"
            )
            assert doc["kind"] == "ClusterRoleBinding"
            assert doc["roleRef"]["kind"] == "ClusterRole", (
                f"ClusterRoleBinding {crb_spec['name']} has "
                f"roleRef.kind={doc['roleRef']['kind']}, expected ClusterRole"
            )

    def test_group_api_group(self):
        """Group subjects must have apiGroup: rbac.authorization.k8s.io."""
        docs = self._load_all_rbac_docs()
        for doc in docs:
            for subj in doc.get("subjects", []):
                if subj["kind"] == "Group":
                    assert subj.get("apiGroup") == "rbac.authorization.k8s.io", (
                        f"Group {subj['name']} in {doc['metadata']['name']} "
                        f"has apiGroup='{subj.get('apiGroup')}', "
                        f"expected 'rbac.authorization.k8s.io'"
                    )

    def test_all_role_bindings_present(self, spec):
        """All specified role bindings exist with correct role and subject."""
        docs = self._load_all_rbac_docs()
        for rb_spec in spec["rbac"]["role_bindings"]:
            doc = next(
                (d for d in docs
                 if d.get("metadata", {}).get("name") == rb_spec["name"]),
                None,
            )
            assert doc is not None, (
                f"RoleBinding {rb_spec['name']} not found in rbac/"
            )
            assert doc["roleRef"]["name"] == rb_spec["role"], (
                f"RoleBinding {rb_spec['name']} role expected "
                f"'{rb_spec['role']}', got '{doc['roleRef']['name']}'"
            )
            if "group" in rb_spec:
                found = any(
                    s["kind"] == "Group" and s["name"] == rb_spec["group"]
                    for s in doc.get("subjects", [])
                )
                assert found, (
                    f"RoleBinding {rb_spec['name']} missing Group subject "
                    f"'{rb_spec['group']}'"
                )
            elif "user" in rb_spec:
                found = any(
                    s["kind"] == "User" and s["name"] == rb_spec["user"]
                    for s in doc.get("subjects", [])
                )
                assert found, (
                    f"RoleBinding {rb_spec['name']} missing User subject "
                    f"'{rb_spec['user']}'"
                )

    def test_cluster_role_binding_present(self, spec):
        """ClusterRoleBinding exists with correct cluster_role."""
        docs = self._load_all_rbac_docs()
        for crb_spec in spec["rbac"]["cluster_role_bindings"]:
            doc = next(
                (d for d in docs
                 if d.get("metadata", {}).get("name") == crb_spec["name"]),
                None,
            )
            assert doc is not None
            assert doc["roleRef"]["name"] == crb_spec["cluster_role"]


# ──────────────────────── NetworkPolicies ────────────────────────


class TestNetworkPolicies:
    def _load_policies(self, namespace):
        path = os.path.join(OUTPUT, "network-policies", f"{namespace}.yaml")
        assert os.path.exists(path), (
            f"NetworkPolicy file for {namespace} not found"
        )
        with open(path) as f:
            return [d for d in yaml.safe_load_all(f) if d is not None]

    def test_all_namespace_policies_present(self, spec):
        for ns in spec["network_policies"]:
            path = os.path.join(OUTPUT, "network-policies", f"{ns}.yaml")
            assert os.path.exists(path), (
                f"Missing network policies file for namespace {ns}"
            )

    def test_deny_all_policy_types(self, spec):
        """default-deny policies must have BOTH Ingress and Egress."""
        for ns in spec["network_policies"]:
            policies = self._load_policies(ns)
            deny = next(
                (p for p in policies
                 if p["metadata"]["name"] == "default-deny"),
                None,
            )
            assert deny is not None, (
                f"default-deny policy missing in {ns}"
            )
            ptypes = deny["spec"].get("policyTypes", [])
            assert "Ingress" in ptypes and "Egress" in ptypes, (
                f"default-deny in {ns} has policyTypes={ptypes}, "
                f"expected [Ingress, Egress]"
            )

    def test_and_semantics_api_gateway(self):
        """allow-from-frontend must use AND (combined ns+pod selector)."""
        policies = self._load_policies("api-gateway")
        pol = next(
            p for p in policies
            if p["metadata"]["name"] == "allow-from-frontend"
        )
        ingress_rules = pol["spec"]["ingress"]
        for rule in ingress_rules:
            from_entries = rule.get("from", [])
            # No entry should have podSelector WITHOUT namespaceSelector
            pod_only = [
                e for e in from_entries
                if "podSelector" in e and "namespaceSelector" not in e
            ]
            assert len(pod_only) == 0, (
                "allow-from-frontend has standalone podSelector (OR semantics). "
                "podSelector must be combined with namespaceSelector in the "
                "same from entry for AND semantics."
            )

    def test_dns_egress_present(self, spec):
        """Egress policies in namespaces with egress rules must allow DNS."""
        for ns in ["web-frontend", "api-gateway", "order-service"]:
            policies = self._load_policies(ns)
            egress_policies = [
                p for p in policies
                if "Egress" in p["spec"].get("policyTypes", [])
                and p["metadata"]["name"] != "default-deny"
            ]
            for pol in egress_policies:
                egress_rules = pol["spec"].get("egress", [])
                dns_found = False
                for rule in egress_rules:
                    ports = rule.get("ports", [])
                    for p in ports:
                        if p.get("port") == 53 and p.get("protocol") == "UDP":
                            dns_found = True
                assert dns_found, (
                    f"Egress policy {pol['metadata']['name']} in {ns} "
                    f"is missing DNS egress (UDP port 53)"
                )

    def test_correct_policy_count(self, spec):
        """Each namespace must have the expected number of policies."""
        for ns, expected_policies in spec["network_policies"].items():
            policies = self._load_policies(ns)
            assert len(policies) == len(expected_policies), (
                f"{ns} has {len(policies)} policies, "
                f"expected {len(expected_policies)}"
            )


# ──────────────────────── LimitRanges ────────────────────────


class TestLimitRanges:
    def test_all_present(self, spec):
        for lr in spec["limit_ranges"]:
            path = os.path.join(
                OUTPUT, "limit-ranges", f"{lr['namespace']}.yaml"
            )
            assert os.path.exists(path), (
                f"Missing limit range for {lr['namespace']}"
            )

    def test_constraint_validity(self, spec):
        """min <= defaultRequest <= default <= max for each resource."""
        for lr_spec in spec["limit_ranges"]:
            ns = lr_spec["namespace"]
            path = os.path.join(OUTPUT, "limit-ranges", f"{ns}.yaml")
            with open(path) as f:
                doc = yaml.safe_load(f)
            for limit in doc["spec"]["limits"]:
                if limit["type"] != "Container":
                    continue
                for resource in ["cpu", "memory"]:
                    min_v = parse_resource(
                        limit.get("min", {}).get(resource, "0")
                    )
                    dreq = parse_resource(
                        limit.get("defaultRequest", {}).get(resource, "0")
                    )
                    dval = parse_resource(
                        limit.get("default", {}).get(resource, "0")
                    )
                    max_v = parse_resource(
                        limit.get("max", {}).get(resource, "0")
                    )
                    assert min_v <= dreq, (
                        f"LimitRange {ns}: min.{resource} ({min_v}) > "
                        f"defaultRequest.{resource} ({dreq})"
                    )
                    assert dreq <= dval, (
                        f"LimitRange {ns}: defaultRequest.{resource} ({dreq}) "
                        f"> default.{resource} ({dval})"
                    )
                    assert dval <= max_v, (
                        f"LimitRange {ns}: default.{resource} ({dval}) > "
                        f"max.{resource} ({max_v})"
                    )

    def test_values_match_spec(self, spec):
        """LimitRange values must match the spec exactly."""
        for lr_spec in spec["limit_ranges"]:
            ns = lr_spec["namespace"]
            path = os.path.join(OUTPUT, "limit-ranges", f"{ns}.yaml")
            with open(path) as f:
                doc = yaml.safe_load(f)
            spec_lim = lr_spec["limits"][0]
            doc_lim = doc["spec"]["limits"][0]
            assert doc_lim["type"] == "Container"
            for section in ["default", "defaultRequest", "max", "min"]:
                for resource in ["cpu", "memory"]:
                    expected = str(spec_lim.get(section, {}).get(resource, ""))
                    actual = str(doc_lim.get(section, {}).get(resource, ""))
                    assert actual == expected, (
                        f"LimitRange {ns}: {section}.{resource} "
                        f"expected '{expected}', got '{actual}'"
                    )


# ──────────────────────── ResourceQuotas ────────────────────────


class TestQuotas:
    def test_all_present(self, spec):
        for q in spec["quotas"]:
            path = os.path.join(OUTPUT, "quotas", f"{q['namespace']}.yaml")
            assert os.path.exists(path), (
                f"Missing quota for {q['namespace']}"
            )

    def test_no_bare_cpu_memory(self, spec):
        """Quotas must NOT use bare 'cpu' or 'memory' keys."""
        for q in spec["quotas"]:
            ns = q["namespace"]
            path = os.path.join(OUTPUT, "quotas", f"{ns}.yaml")
            with open(path) as f:
                doc = yaml.safe_load(f)
            hard = doc["spec"]["hard"]
            assert "cpu" not in hard, (
                f"Quota in {ns} uses bare 'cpu' "
                f"instead of requests.cpu/limits.cpu"
            )
            assert "memory" not in hard, (
                f"Quota in {ns} uses bare 'memory' "
                f"instead of requests.memory/limits.memory"
            )

    def test_quota_values(self, spec):
        """Quota values must match the spec exactly."""
        for q_spec in spec["quotas"]:
            ns = q_spec["namespace"]
            path = os.path.join(OUTPUT, "quotas", f"{ns}.yaml")
            with open(path) as f:
                doc = yaml.safe_load(f)
            for key, value in q_spec["hard"].items():
                actual = doc["spec"]["hard"].get(key)
                assert str(actual) == str(value), (
                    f"Quota {ns}: {key} expected '{value}', got '{actual}'"
                )


# ──────────────────────── Routes ────────────────────────


class TestRoutes:
    def test_passthrough_no_cert(self):
        """Passthrough route must NOT include certificate or key."""
        path = os.path.join(OUTPUT, "routes", "api-passthrough-route.yaml")
        assert os.path.exists(path), "api-passthrough-route.yaml not found"
        with open(path) as f:
            doc = yaml.safe_load(f)
        tls = doc["spec"]["tls"]
        assert tls["termination"] == "passthrough"
        assert "certificate" not in tls, (
            "Passthrough route must not include certificate"
        )
        assert "key" not in tls, (
            "Passthrough route must not include key"
        )

    def test_edge_route_has_cert(self):
        """Edge route must include certificate and key."""
        path = os.path.join(OUTPUT, "routes", "frontend-edge-route.yaml")
        assert os.path.exists(path), "frontend-edge-route.yaml not found"
        with open(path) as f:
            doc = yaml.safe_load(f)
        tls = doc["spec"]["tls"]
        assert tls["termination"] == "edge"
        assert "certificate" in tls and tls["certificate"].strip(), (
            "Edge route must have a non-empty certificate"
        )
        assert "key" in tls and tls["key"].strip(), (
            "Edge route must have a non-empty key"
        )


# ──────────────────────── TLS Certificates ────────────────────────


class TestTLS:
    def test_cert_san(self):
        """Frontend certificate must have correct SANs."""
        cert_path = os.path.join(OUTPUT, "tls", "frontend.crt")
        assert os.path.exists(cert_path), "frontend.crt not found"
        result = subprocess.run(
            ["openssl", "x509", "-in", cert_path, "-text", "-noout"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "www.acme.example.com" in result.stdout, (
            "Missing SAN: www.acme.example.com"
        )
        assert "acme.example.com" in result.stdout, (
            "Missing SAN: acme.example.com"
        )
        assert "wrong-domain" not in result.stdout, (
            "Wrong SAN found: wrong-domain should not be present"
        )

    def test_cert_ca_signed(self):
        """Frontend cert must be verifiable against the CA cert."""
        result = subprocess.run(
            [
                "openssl", "verify",
                "-CAfile", os.path.join(OUTPUT, "tls", "ca.crt"),
                os.path.join(OUTPUT, "tls", "frontend.crt"),
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, (
            f"Certificate CA verification failed: {result.stderr}"
        )

    def test_ca_cert_exists(self):
        for fname in ["ca.crt", "ca.key"]:
            path = os.path.join(OUTPUT, "tls", fname)
            assert os.path.exists(path), f"{fname} not found in tls/"


# ──────────────────────── SCC ────────────────────────


class TestSCC:
    def test_scc_resources(self, spec):
        """ServiceAccount and SCC ClusterRoleBinding must exist."""
        scc_dir = os.path.join(OUTPUT, "scc")
        assert os.path.isdir(scc_dir), "scc/ directory not found"

        for scc_spec in spec["scc"]:
            found_sa = False
            found_crb = False
            for fname in os.listdir(scc_dir):
                if not fname.endswith((".yaml", ".yml")):
                    continue
                fpath = os.path.join(scc_dir, fname)
                with open(fpath) as f:
                    docs = [d for d in yaml.safe_load_all(f) if d is not None]
                for doc in docs:
                    if (
                        doc.get("kind") == "ServiceAccount"
                        and doc["metadata"].get("name")
                        == scc_spec["service_account"]
                        and doc["metadata"].get("namespace")
                        == scc_spec["namespace"]
                    ):
                        found_sa = True
                    if (
                        doc.get("kind") == "ClusterRoleBinding"
                        and doc.get("roleRef", {}).get("name")
                        == f"system:openshift:scc:{scc_spec['scc']}"
                    ):
                        for subj in doc.get("subjects", []):
                            if (
                                subj.get("name")
                                == scc_spec["service_account"]
                                and subj.get("namespace")
                                == scc_spec["namespace"]
                            ):
                                found_crb = True
            assert found_sa, (
                f"ServiceAccount {scc_spec['service_account']} not found"
            )
            assert found_crb, (
                f"SCC ClusterRoleBinding for "
                f"{scc_spec['service_account']} -> {scc_spec['scc']} "
                f"not found"
            )


# ──────────────────────── Kustomize ────────────────────────


class TestKustomize:
    def test_build_succeeds(self):
        """kustomize build must succeed on the output directory."""
        result = subprocess.run(
            ["kustomize", "build", OUTPUT],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, (
            f"kustomize build failed:\n{result.stderr}"
        )

    def test_build_produces_output(self):
        """kustomize build must produce non-empty YAML output."""
        result = subprocess.run(
            ["kustomize", "build", OUTPUT],
            capture_output=True, text=True,
        )
        assert len(result.stdout.strip()) > 100, (
            "kustomize build produced insufficient output"
        )
