
import yaml
import json
import os
import glob
import subprocess
import pytest


def load_all_manifests(directory):
    """Load all YAML manifests from a directory, handling multi-document files."""
    manifests = []
    for filepath in sorted(glob.glob(os.path.join(directory, "*.yaml")) +
                           glob.glob(os.path.join(directory, "*.yml"))):
        with open(filepath) as f:
            docs = list(yaml.safe_load_all(f))
            for doc in docs:
                if doc is not None:
                    manifests.append((os.path.basename(filepath), doc))
    return manifests


def find_resource(manifests, kind, name):
    """Find a resource by kind and name."""
    for _, doc in manifests:
        if doc.get("kind") == kind and doc.get("metadata", {}).get("name") == name:
            return doc
    return None


def find_all_by_kind(manifests, kind):
    """Find all resources of a given kind."""
    return [doc for _, doc in manifests if doc.get("kind") == kind]


def parse_storage(value):
    """Parse Kubernetes storage quantity string to GiB float."""
    s = str(value)
    if s.endswith("Gi"):
        return float(s[:-2])
    elif s.endswith("Mi"):
        return float(s[:-2]) / 1024.0
    elif s.endswith("Ti"):
        return float(s[:-2]) * 1024.0
    elif s.endswith("Ki"):
        return float(s[:-2]) / (1024.0 * 1024.0)
    return float(s)


class TestFixedManifests:
    """Verify that all configuration errors have been fixed."""

    @classmethod
    def setup_class(cls):
        fixed_dir = "/app/fixed"
        assert os.path.isdir(fixed_dir), f"Fixed manifests directory {fixed_dir} does not exist"
        cls.manifests = load_all_manifests(fixed_dir)
        assert len(cls.manifests) > 0, "No manifests found in /app/fixed/"

        audit_path = "/app/audit.json"
        assert os.path.isfile(audit_path), f"Audit report {audit_path} does not exist"
        with open(audit_path) as f:
            cls.audit = json.load(f)

    def test_frontend_service_selector_matches_deployment(self):
        svc = find_resource(self.manifests, "Service", "frontend")
        dep = find_resource(self.manifests, "Deployment", "frontend")
        assert svc is not None, "Service/frontend not found"
        assert dep is not None, "Deployment/frontend not found"
        pod_labels = dep["spec"]["template"]["metadata"]["labels"]
        svc_selector = svc["spec"]["selector"]
        for key, value in svc_selector.items():
            assert key in pod_labels, (
                f"Service selector key '{key}' not found in pod labels"
            )
            assert pod_labels[key] == value, (
                f"Service selector {key}={value} doesn't match pod label {key}={pod_labels[key]}"
            )

    def test_frontend_liveness_probe_port(self):
        dep = find_resource(self.manifests, "Deployment", "frontend")
        assert dep is not None
        container = dep["spec"]["template"]["spec"]["containers"][0]
        container_port = container["ports"][0]["containerPort"]
        probe = container.get("livenessProbe", {})
        assert "httpGet" in probe, "Frontend should have httpGet liveness probe"
        probe_port = probe["httpGet"]["port"]
        assert probe_port == container_port, (
            f"Liveness probe port {probe_port} doesn't match container port {container_port}"
        )

    def test_api_server_has_resources(self):
        dep = find_resource(self.manifests, "Deployment", "api-server")
        assert dep is not None
        container = dep["spec"]["template"]["spec"]["containers"][0]
        assert "resources" in container, "API server container missing resources"
        resources = container["resources"]
        assert "requests" in resources, "Missing resource requests"
        assert "limits" in resources, "Missing resource limits"
        assert "cpu" in resources["requests"], "Missing CPU request"
        assert "memory" in resources["requests"], "Missing memory request"
        assert "cpu" in resources["limits"], "Missing CPU limit"
        assert "memory" in resources["limits"], "Missing memory limit"

    def test_api_server_service_target_port(self):
        svc = find_resource(self.manifests, "Service", "api-server")
        dep = find_resource(self.manifests, "Deployment", "api-server")
        assert svc is not None
        assert dep is not None
        container_port = dep["spec"]["template"]["spec"]["containers"][0]["ports"][0][
            "containerPort"
        ]
        target_port = svc["spec"]["ports"][0]["targetPort"]
        assert target_port == container_port, (
            f"Service targetPort {target_port} doesn't match container port {container_port}"
        )

    def test_api_server_configmap_key(self):
        dep = find_resource(self.manifests, "Deployment", "api-server")
        cm = find_resource(self.manifests, "ConfigMap", "app-config")
        assert dep is not None
        assert cm is not None
        container = dep["spec"]["template"]["spec"]["containers"][0]
        for env_var in container.get("env", []):
            vf = env_var.get("valueFrom", {})
            cmref = vf.get("configMapKeyRef")
            if cmref and cmref.get("name") == "app-config":
                assert cmref["key"] in cm["data"], (
                    f"ConfigMap key '{cmref['key']}' not found in app-config. "
                    f"Available keys: {list(cm['data'].keys())}"
                )

    def test_api_server_service_account(self):
        dep = find_resource(self.manifests, "Deployment", "api-server")
        assert dep is not None
        sa_name = dep["spec"]["template"]["spec"].get("serviceAccountName")
        assert sa_name is not None, "API server Deployment missing serviceAccountName"
        sa = find_resource(self.manifests, "ServiceAccount", sa_name)
        assert sa is not None, (
            f"ServiceAccount '{sa_name}' referenced by api-server not found in manifests"
        )

    def test_worker_security_context(self):
        dep = find_resource(self.manifests, "Deployment", "worker")
        assert dep is not None
        pod_spec = dep["spec"]["template"]["spec"]
        container = pod_spec["containers"][0]
        pod_sc = pod_spec.get("securityContext", {})
        container_sc = container.get("securityContext", {})
        run_as_non_root = container_sc.get(
            "runAsNonRoot", pod_sc.get("runAsNonRoot", False)
        )
        assert run_as_non_root is True, (
            f"runAsNonRoot should be true (got {run_as_non_root})"
        )
        run_as_user = container_sc.get("runAsUser", pod_sc.get("runAsUser"))
        assert run_as_user is not None and run_as_user != 0, (
            f"Container should not run as root (runAsUser={run_as_user})"
        )

    def test_worker_secret_reference(self):
        dep = find_resource(self.manifests, "Deployment", "worker")
        assert dep is not None
        volumes = dep["spec"]["template"]["spec"].get("volumes", [])
        for vol in volumes:
            if "secret" in vol:
                secret_name = vol["secret"]["secretName"]
                secret = find_resource(self.manifests, "Secret", secret_name)
                assert secret is not None, (
                    f"Volume references Secret '{secret_name}' which does not exist"
                )

    def test_pvc_storage_within_pv_capacity(self):
        pv = find_resource(self.manifests, "PersistentVolume", "worker-data-pv")
        pvc = find_resource(
            self.manifests, "PersistentVolumeClaim", "worker-data-pvc"
        )
        assert pv is not None
        assert pvc is not None
        pv_cap = pv["spec"]["capacity"]["storage"]
        pvc_req = pvc["spec"]["resources"]["requests"]["storage"]
        assert parse_storage(pvc_req) <= parse_storage(pv_cap), (
            f"PVC request {pvc_req} exceeds PV capacity {pv_cap}"
        )

    def test_pvc_access_mode_compatible(self):
        pv = find_resource(self.manifests, "PersistentVolume", "worker-data-pv")
        pvc = find_resource(
            self.manifests, "PersistentVolumeClaim", "worker-data-pvc"
        )
        assert pv is not None
        assert pvc is not None
        pv_modes = set(pv["spec"]["accessModes"])
        pvc_modes = set(pvc["spec"]["accessModes"])
        assert pvc_modes.issubset(pv_modes), (
            f"PVC access modes {pvc_modes} not supported by PV (supports {pv_modes})"
        )

    def test_networkpolicy_worker_allows_api_server(self):
        np = find_resource(self.manifests, "NetworkPolicy", "worker-policy")
        dep = find_resource(self.manifests, "Deployment", "api-server")
        assert np is not None, "NetworkPolicy/worker-policy not found"
        assert dep is not None
        api_labels = dep["spec"]["template"]["metadata"]["labels"]
        ingress_rules = np["spec"].get("ingress", [])
        allowed = False
        for rule in ingress_rules:
            for from_rule in rule.get("from", []):
                if "podSelector" in from_rule:
                    selector = from_rule["podSelector"].get("matchLabels", {})
                    if all(
                        api_labels.get(k) == v for k, v in selector.items()
                    ):
                        allowed = True
                        break
            if allowed:
                break
        assert allowed, (
            f"NetworkPolicy worker-policy does not allow ingress from api-server pods "
            f"(api-server labels: {api_labels})"
        )

    def test_cronjob_schedule_valid(self):
        cj = find_resource(self.manifests, "CronJob", "data-cleanup")
        assert cj is not None
        schedule = cj["spec"]["schedule"]
        fields = schedule.strip().split()
        assert len(fields) == 5, (
            f"CronJob schedule should have 5 fields, got {len(fields)}: '{schedule}'"
        )

    def test_rolebinding_references_existing_service_account(self):
        rb = find_resource(self.manifests, "RoleBinding", "api-role-binding")
        assert rb is not None, "RoleBinding/api-role-binding not found"
        subjects = rb.get("subjects", [])
        assert len(subjects) > 0, "RoleBinding has no subjects"
        for subject in subjects:
            if subject.get("kind") == "ServiceAccount":
                sa_name = subject.get("name")
                sa = find_resource(self.manifests, "ServiceAccount", sa_name)
                assert sa is not None, (
                    f"RoleBinding subject references ServiceAccount '{sa_name}' "
                    f"which does not exist in manifests"
                )

    def test_hpa_references_existing_deployment(self):
        hpa = find_resource(
            self.manifests, "HorizontalPodAutoscaler", "api-server-hpa"
        )
        assert hpa is not None, "HorizontalPodAutoscaler/api-server-hpa not found"
        target = hpa["spec"]["scaleTargetRef"]
        target_name = target["name"]
        target_kind = target["kind"]
        target_resource = find_resource(self.manifests, target_kind, target_name)
        assert target_resource is not None, (
            f"HPA scaleTargetRef targets {target_kind}/{target_name} which does not exist"
        )

    def test_audit_report_structure(self):
        assert "findings" in self.audit, "Audit report missing 'findings' key"
        findings = self.audit["findings"]
        assert len(findings) >= 14, (
            f"Expected at least 14 findings in audit report, got {len(findings)}"
        )
        required_fields = {"file", "resource", "severity", "category", "description"}
        for i, finding in enumerate(findings):
            for field in required_fields:
                assert field in finding, (
                    f"Finding #{i} missing required field '{field}'"
                )
            assert finding["severity"] in ("critical", "high", "medium"), (
                f"Finding #{i} has invalid severity: {finding['severity']}"
            )

    def test_all_resources_in_correct_namespace(self):
        """Namespace-scoped resources must be in the ecommerce namespace."""
        namespace_scoped_kinds = {
            "Deployment", "Service", "ConfigMap", "Secret",
            "ServiceAccount", "PersistentVolumeClaim",
            "NetworkPolicy", "CronJob", "LimitRange", "ResourceQuota",
            "Role", "RoleBinding", "HorizontalPodAutoscaler",
        }
        for filename, doc in self.manifests:
            kind = doc.get("kind", "")
            if kind in namespace_scoped_kinds:
                ns = doc.get("metadata", {}).get("namespace", "default")
                name = doc.get("metadata", {}).get("name", "unknown")
                assert ns == "ecommerce", (
                    f"{kind}/{name} in file {filename} is in namespace '{ns}', "
                    f"expected 'ecommerce'"
                )


class TestValidator:
    """Verify the cross-resource validation tool works correctly."""

    @classmethod
    def setup_class(cls):
        assert os.path.isfile("/app/validate.py"), (
            "Validation script /app/validate.py not found"
        )

    def test_validator_passes_fixed_manifests(self):
        """Validator must report 0 issues on corrected manifests."""
        result = subprocess.run(
            ["python3", "/app/validate.py", "/app/fixed/"],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, (
            f"Validator exited with code {result.returncode} on fixed manifests.\n"
            f"stderr: {result.stderr[:500]}"
        )
        try:
            output = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail(f"Validator stdout is not valid JSON: {result.stdout[:500]}")
        assert output.get("total") == 0, (
            f"Validator found {output.get('total')} issues in fixed manifests: "
            f"{json.dumps(output.get('issues', [])[:3], indent=2)}"
        )

    def test_validator_detects_original_issues(self):
        """Validator must detect issues in the original broken manifests."""
        result = subprocess.run(
            ["python3", "/app/validate.py", "/app/manifests/"],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode != 0, (
            "Validator should exit non-zero when issues are found"
        )
        try:
            output = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail(f"Validator stdout is not valid JSON: {result.stdout[:500]}")
        assert output.get("total", 0) >= 5, (
            f"Validator found only {output.get('total', 0)} issues in original "
            f"manifests (expected >= 5)"
        )

    def test_validator_output_schema(self):
        """Validator output must conform to the specified JSON schema."""
        result = subprocess.run(
            ["python3", "/app/validate.py", "/app/manifests/"],
            capture_output=True, text=True, timeout=60
        )
        try:
            output = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail(f"Validator stdout is not valid JSON: {result.stdout[:500]}")
        assert "issues" in output, "Output missing 'issues' key"
        assert "total" in output, "Output missing 'total' key"
        assert isinstance(output["issues"], list), "'issues' must be a list"
        assert isinstance(output["total"], int), "'total' must be an integer"
        required_fields = {"resource", "check", "message"}
        for i, issue in enumerate(output["issues"][:5]):
            for field in required_fields:
                assert field in issue, (
                    f"Issue #{i} missing required field '{field}'"
                )
