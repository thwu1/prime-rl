"""
Tests for Kubernetes Control Plane Forensics and Repair task.

"""

import subprocess
import os
import json
import base64
import tempfile
import yaml


# ============================================================
# Helper functions
# ============================================================

def run_openssl(args):
    """Run an openssl command and return stdout."""
    result = subprocess.run(
        ["openssl"] + args,
        capture_output=True, text=True
    )
    return result


def get_cert_text(cert_path):
    """Get full text output of a certificate."""
    r = run_openssl(["x509", "-in", cert_path, "-text", "-noout"])
    assert r.returncode == 0, f"Failed to read cert {cert_path}: {r.stderr}"
    return r.stdout


def get_cert_subject(cert_path):
    """Get the subject line of a certificate."""
    r = run_openssl(["x509", "-in", cert_path, "-subject", "-noout"])
    assert r.returncode == 0, f"Failed to read subject of {cert_path}: {r.stderr}"
    return r.stdout.strip()


def get_cert_issuer(cert_path):
    """Get the issuer line of a certificate."""
    r = run_openssl(["x509", "-in", cert_path, "-issuer", "-noout"])
    assert r.returncode == 0, f"Failed to read issuer of {cert_path}: {r.stderr}"
    return r.stdout.strip()


def verify_cert_against_ca(cert_path, ca_path):
    """Verify a certificate was signed by a given CA."""
    r = run_openssl(["verify", "-CAfile", ca_path, cert_path])
    return r.returncode == 0


def load_yaml(path):
    """Load a YAML file."""
    with open(path) as f:
        return yaml.safe_load(f)


def load_all_yaml(path):
    """Load all YAML documents from a file."""
    with open(path) as f:
        return [doc for doc in yaml.safe_load_all(f) if doc is not None]


def get_all_rbac_docs():
    """Load all RBAC documents from all YAML files in /app/rbac/."""
    docs = []
    rbac_dir = "/app/rbac"
    for fname in os.listdir(rbac_dir):
        if fname.endswith((".yaml", ".yml")) and fname != "requirements.txt":
            filepath = os.path.join(rbac_dir, fname)
            docs.extend(load_all_yaml(filepath))
    return docs


def get_container_command(manifest):
    """Extract the command list from the first container in a pod manifest."""
    containers = manifest["spec"]["containers"]
    return containers[0].get("command", [])


def command_has_flag(command, flag_prefix):
    """Check if any command item starts with the given flag prefix."""
    return any(item.startswith(flag_prefix) for item in command)


def get_flag_value(command, flag_prefix):
    """Get the value of a flag from a command list (assumes --flag=value format)."""
    for item in command:
        if item.startswith(flag_prefix):
            if "=" in item:
                return item.split("=", 1)[1]
    return None


# ============================================================
# PKI Certificate Tests
# ============================================================

class TestPKICertificates:
    """Tests for the fixed PKI certificates."""

    def test_ca_files_present(self):
        """CA cert and key must be copied to pki-fixed."""
        assert os.path.exists("/app/pki-fixed/ca.crt"), "ca.crt missing from pki-fixed"
        assert os.path.exists("/app/pki-fixed/ca.key"), "ca.key missing from pki-fixed"

    def test_apiserver_cert_exists(self):
        assert os.path.exists("/app/pki-fixed/apiserver.crt"), "apiserver.crt missing"

    def test_apiserver_cert_signed_by_ca(self):
        """API server cert must be signed by the main CA."""
        assert verify_cert_against_ca("/app/pki-fixed/apiserver.crt", "/app/pki/ca.crt"), \
            "apiserver.crt not signed by main CA"

    def test_apiserver_cert_has_all_sans(self):
        """API server cert must have all required SANs."""
        text = get_cert_text("/app/pki-fixed/apiserver.crt")
        required_dns = [
            "kubernetes.default.svc.cluster.local",
            "kubernetes.default.svc",
            "kubernetes.default",
        ]
        required_ips = [
            "10.96.0.1",
            "192.168.1.10",
            "127.0.0.1",
        ]
        for san in required_dns:
            assert san in text, f"Missing DNS SAN: {san}"
        for ip in required_ips:
            assert ip in text, f"Missing IP SAN: {ip}"

    def test_admin_cert_exists(self):
        assert os.path.exists("/app/pki-fixed/admin.crt"), "admin.crt missing"

    def test_admin_cert_signed_by_ca(self):
        """Admin cert must be signed by the main CA."""
        assert verify_cert_against_ca("/app/pki-fixed/admin.crt", "/app/pki/ca.crt"), \
            "admin.crt not signed by main CA"

    def test_admin_cert_has_correct_organization(self):
        """Admin cert must have O=system:masters (not system:admin)."""
        subject = get_cert_subject("/app/pki-fixed/admin.crt")
        assert "system:masters" in subject, \
            f"Admin cert must have O=system:masters, got: {subject}"
        assert "system:admin" not in subject, \
            f"Admin cert still has wrong O=system:admin: {subject}"

    def test_scheduler_cert_exists(self):
        assert os.path.exists("/app/pki-fixed/scheduler.crt"), "scheduler.crt missing"

    def test_scheduler_cert_signed_by_main_ca(self):
        """Scheduler cert must be signed by the main CA, not front-proxy-ca."""
        assert verify_cert_against_ca("/app/pki-fixed/scheduler.crt", "/app/pki/ca.crt"), \
            "scheduler.crt not signed by main CA"

    def test_scheduler_cert_not_signed_by_front_proxy(self):
        """Scheduler cert issuer must not be front-proxy-ca."""
        issuer = get_cert_issuer("/app/pki-fixed/scheduler.crt")
        assert "front-proxy" not in issuer.lower(), \
            f"Scheduler cert still signed by front-proxy-ca: {issuer}"

    def test_scheduler_cert_has_correct_cn(self):
        """Scheduler cert must have CN=system:kube-scheduler."""
        subject = get_cert_subject("/app/pki-fixed/scheduler.crt")
        assert "system:kube-scheduler" in subject, \
            f"Scheduler cert must have CN=system:kube-scheduler, got: {subject}"


# ============================================================
# Static Pod Manifest Tests
# ============================================================

class TestManifests:
    """Tests for the fixed static pod manifests."""

    def test_apiserver_manifest_valid_yaml(self):
        manifest = load_yaml("/app/manifests-fixed/kube-apiserver.yaml")
        assert manifest["kind"] == "Pod"
        assert manifest["metadata"]["name"] == "kube-apiserver"

    def test_apiserver_etcd_port(self):
        """etcd-servers must use port 2379 (not 2380)."""
        manifest = load_yaml("/app/manifests-fixed/kube-apiserver.yaml")
        command = get_container_command(manifest)
        etcd_val = get_flag_value(command, "--etcd-servers")
        assert etcd_val is not None, "Missing --etcd-servers flag"
        assert "2379" in etcd_val, f"etcd-servers must use port 2379, got: {etcd_val}"
        assert "2380" not in etcd_val, f"etcd-servers still uses wrong port 2380: {etcd_val}"

    def test_apiserver_tls_cert_path(self):
        """TLS cert file must be apiserver.crt, not server.crt."""
        manifest = load_yaml("/app/manifests-fixed/kube-apiserver.yaml")
        command = get_container_command(manifest)
        tls_cert = get_flag_value(command, "--tls-cert-file")
        assert tls_cert is not None, "Missing --tls-cert-file flag"
        assert "apiserver.crt" in tls_cert, \
            f"TLS cert should reference apiserver.crt, got: {tls_cert}"

    def test_apiserver_tls_key_path(self):
        """TLS key file must be apiserver.key, not server.key."""
        manifest = load_yaml("/app/manifests-fixed/kube-apiserver.yaml")
        command = get_container_command(manifest)
        tls_key = get_flag_value(command, "--tls-private-key-file")
        assert tls_key is not None, "Missing --tls-private-key-file flag"
        assert "apiserver.key" in tls_key, \
            f"TLS key should reference apiserver.key, got: {tls_key}"

    def test_apiserver_authorization_mode(self):
        """Authorization mode must be Node,RBAC (not AlwaysAllow)."""
        manifest = load_yaml("/app/manifests-fixed/kube-apiserver.yaml")
        command = get_container_command(manifest)
        auth_mode = get_flag_value(command, "--authorization-mode")
        assert auth_mode is not None, "Missing --authorization-mode flag"
        assert "Node" in auth_mode and "RBAC" in auth_mode, \
            f"authorization-mode must include Node,RBAC, got: {auth_mode}"
        assert "AlwaysAllow" not in auth_mode, \
            f"authorization-mode must not be AlwaysAllow: {auth_mode}"

    def test_apiserver_service_cluster_ip_range(self):
        """Must have --service-cluster-ip-range flag."""
        manifest = load_yaml("/app/manifests-fixed/kube-apiserver.yaml")
        command = get_container_command(manifest)
        assert command_has_flag(command, "--service-cluster-ip-range"), \
            "Missing --service-cluster-ip-range flag"
        val = get_flag_value(command, "--service-cluster-ip-range")
        assert "10.96.0.0" in val, f"service-cluster-ip-range should be 10.96.0.0/12, got: {val}"

    def test_scheduler_manifest_valid_yaml(self):
        manifest = load_yaml("/app/manifests-fixed/kube-scheduler.yaml")
        assert manifest["kind"] == "Pod"

    def test_scheduler_kubeconfig_path(self):
        """Scheduler kubeconfig must be scheduler.conf (not scheduler.config)."""
        manifest = load_yaml("/app/manifests-fixed/kube-scheduler.yaml")
        command = get_container_command(manifest)
        kc_val = get_flag_value(command, "--kubeconfig")
        assert kc_val is not None, "Missing --kubeconfig flag"
        assert kc_val.endswith("scheduler.conf"), \
            f"kubeconfig should end with scheduler.conf, got: {kc_val}"
        assert "scheduler.config" not in kc_val, \
            f"kubeconfig still has wrong extension .config: {kc_val}"

    def test_scheduler_volume_names_match(self):
        """Volume names in volumeMounts must match volume definitions."""
        manifest = load_yaml("/app/manifests-fixed/kube-scheduler.yaml")
        containers = manifest["spec"]["containers"]
        volume_mounts = containers[0].get("volumeMounts", [])
        volumes = manifest["spec"].get("volumes", [])
        volume_names = {v["name"] for v in volumes}
        for vm in volume_mounts:
            assert vm["name"] in volume_names, \
                f"volumeMount '{vm['name']}' has no matching volume (available: {volume_names})"

    def test_controller_manager_manifest_valid_yaml(self):
        manifest = load_yaml("/app/manifests-fixed/kube-controller-manager.yaml")
        assert manifest["kind"] == "Pod"

    def test_controller_manager_signing_flags(self):
        """Must have --cluster-signing-cert-file and --cluster-signing-key-file."""
        manifest = load_yaml("/app/manifests-fixed/kube-controller-manager.yaml")
        command = get_container_command(manifest)
        assert command_has_flag(command, "--cluster-signing-cert-file"), \
            "Missing --cluster-signing-cert-file flag"
        assert command_has_flag(command, "--cluster-signing-key-file"), \
            "Missing --cluster-signing-key-file flag"

    def test_controller_manager_bind_address(self):
        """bind-address must be 127.0.0.1 (not 0.0.0.0)."""
        manifest = load_yaml("/app/manifests-fixed/kube-controller-manager.yaml")
        command = get_container_command(manifest)
        bind_addr = get_flag_value(command, "--bind-address")
        assert bind_addr is not None, "Missing --bind-address flag"
        assert bind_addr == "127.0.0.1", \
            f"bind-address must be 127.0.0.1, got: {bind_addr}"

    def test_etcd_manifest_valid_yaml(self):
        manifest = load_yaml("/app/manifests-fixed/etcd.yaml")
        assert manifest["kind"] == "Pod"

    def test_etcd_data_dir(self):
        """etcd data-dir must be /var/lib/etcd (not /var/lib/etcd-data)."""
        manifest = load_yaml("/app/manifests-fixed/etcd.yaml")
        command = get_container_command(manifest)
        data_dir = get_flag_value(command, "--data-dir")
        assert data_dir is not None, "Missing --data-dir flag"
        assert data_dir == "/var/lib/etcd", \
            f"data-dir must be /var/lib/etcd, got: {data_dir}"

    def test_etcd_client_port(self):
        """listen-client-urls must use port 2379 (not 2380)."""
        manifest = load_yaml("/app/manifests-fixed/etcd.yaml")
        command = get_container_command(manifest)
        client_urls = get_flag_value(command, "--listen-client-urls")
        assert client_urls is not None, "Missing --listen-client-urls flag"
        # All client URL entries should use 2379
        for url in client_urls.split(","):
            url = url.strip()
            if url:
                assert "2379" in url, \
                    f"listen-client-urls entry must use port 2379, got: {url}"

    def test_etcd_peer_port(self):
        """listen-peer-urls must use port 2380 (not 2379)."""
        manifest = load_yaml("/app/manifests-fixed/etcd.yaml")
        command = get_container_command(manifest)
        peer_urls = get_flag_value(command, "--listen-peer-urls")
        assert peer_urls is not None, "Missing --listen-peer-urls flag"
        for url in peer_urls.split(","):
            url = url.strip()
            if url:
                assert "2380" in url, \
                    f"listen-peer-urls entry must use port 2380, got: {url}"


# ============================================================
# etcd Backup/Restore Tests
# ============================================================

class TestEtcdOperations:
    """Tests for etcd backup and restore operations."""

    def test_restored_data_dir_exists(self):
        """Restored data directory must exist."""
        assert os.path.isdir("/app/etcd/restored"), \
            "/app/etcd/restored directory does not exist"

    def test_backup_snapshot_exists(self):
        """Backup snapshot file must exist."""
        assert os.path.exists("/app/etcd/backup.db"), \
            "/app/etcd/backup.db does not exist"

    def test_backup_snapshot_valid(self):
        """Backup snapshot must be a valid etcd snapshot."""
        result = subprocess.run(
            ["etcdutl", "snapshot", "status", "/app/etcd/backup.db",
             "--write-out=json"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, \
            f"etcdutl snapshot status failed: {result.stderr}"
        status = json.loads(result.stdout)
        assert status.get("totalKey", 0) > 0, \
            f"Backup snapshot has no keys: {status}"


# ============================================================
# Kubeconfig Tests
# ============================================================

class TestKubeconfig:
    """Tests for the reconstructed admin kubeconfig."""

    def test_kubeconfig_exists(self):
        assert os.path.exists("/app/kubeconfig/admin.kubeconfig"), \
            "admin.kubeconfig does not exist"

    def test_kubeconfig_valid_yaml(self):
        config = load_yaml("/app/kubeconfig/admin.kubeconfig")
        assert config["apiVersion"] == "v1"
        assert config["kind"] == "Config"

    def test_kubeconfig_server_address(self):
        """Server must be https://192.168.1.10:6443."""
        config = load_yaml("/app/kubeconfig/admin.kubeconfig")
        clusters = config.get("clusters", [])
        assert len(clusters) > 0, "No clusters in kubeconfig"
        server = clusters[0]["cluster"]["server"]
        assert server == "https://192.168.1.10:6443", \
            f"Server must be https://192.168.1.10:6443, got: {server}"

    def test_kubeconfig_has_ca_data(self):
        """Kubeconfig must have certificate-authority-data."""
        config = load_yaml("/app/kubeconfig/admin.kubeconfig")
        ca_data = config["clusters"][0]["cluster"].get("certificate-authority-data")
        assert ca_data is not None and len(ca_data) > 0, \
            "Missing certificate-authority-data"

    def test_kubeconfig_client_cert_has_correct_org(self):
        """Client certificate in kubeconfig must have O=system:masters."""
        config = load_yaml("/app/kubeconfig/admin.kubeconfig")
        users = config.get("users", [])
        assert len(users) > 0, "No users in kubeconfig"
        cert_data_b64 = users[0]["user"].get("client-certificate-data")
        assert cert_data_b64 is not None, "Missing client-certificate-data"

        cert_data = base64.b64decode(cert_data_b64)
        with tempfile.NamedTemporaryFile(suffix=".crt", delete=False) as f:
            f.write(cert_data)
            f.flush()
            temp_path = f.name

        try:
            subject = get_cert_subject(temp_path)
            assert "system:masters" in subject, \
                f"Client cert in kubeconfig must have O=system:masters, got: {subject}"
        finally:
            os.unlink(temp_path)

    def test_kubeconfig_has_client_key(self):
        """Kubeconfig must have client-key-data."""
        config = load_yaml("/app/kubeconfig/admin.kubeconfig")
        users = config.get("users", [])
        key_data = users[0]["user"].get("client-key-data")
        assert key_data is not None and len(key_data) > 0, \
            "Missing client-key-data"


# ============================================================
# RBAC Tests
# ============================================================

class TestRBAC:
    """Tests for the RBAC manifests."""

    def test_rbac_files_exist(self):
        """At least one RBAC YAML file must exist in /app/rbac/."""
        rbac_dir = "/app/rbac"
        yaml_files = [f for f in os.listdir(rbac_dir)
                      if f.endswith((".yaml", ".yml")) and f != "requirements.txt"]
        assert len(yaml_files) > 0, "No RBAC YAML files found in /app/rbac/"

    def test_rbac_deployment_permissions(self):
        """A Role in production must allow create/update/delete Deployments."""
        docs = get_all_rbac_docs()
        production_rules = []
        for doc in docs:
            if doc["kind"] == "Role" and \
               doc.get("metadata", {}).get("namespace") == "production":
                production_rules.extend(doc.get("rules", []))

        deploy_verbs = set()
        for rule in production_rules:
            api_groups = rule.get("apiGroups", [])
            resources = rule.get("resources", [])
            verbs = set(rule.get("verbs", []))
            if "deployments" in resources and \
               any(g in api_groups for g in ["apps", "*"]):
                deploy_verbs.update(verbs)

        if "*" not in deploy_verbs:
            required = {"create", "update", "delete"}
            assert required.issubset(deploy_verbs), \
                f"Missing deployment verbs. Need {required}, have {deploy_verbs}"

    def test_rbac_service_permissions(self):
        """A Role in production must allow create/update/delete Services."""
        docs = get_all_rbac_docs()
        production_rules = []
        for doc in docs:
            if doc["kind"] == "Role" and \
               doc.get("metadata", {}).get("namespace") == "production":
                production_rules.extend(doc.get("rules", []))

        svc_verbs = set()
        for rule in production_rules:
            api_groups = rule.get("apiGroups", [])
            resources = rule.get("resources", [])
            verbs = set(rule.get("verbs", []))
            if "services" in resources and \
               any(g in api_groups for g in ["", "*"]):
                svc_verbs.update(verbs)

        if "*" not in svc_verbs:
            required = {"create", "update", "delete"}
            assert required.issubset(svc_verbs), \
                f"Missing service verbs. Need {required}, have {svc_verbs}"

    def test_rbac_configmap_permissions(self):
        """A Role in production must allow create/update/delete ConfigMaps."""
        docs = get_all_rbac_docs()
        production_rules = []
        for doc in docs:
            if doc["kind"] == "Role" and \
               doc.get("metadata", {}).get("namespace") == "production":
                production_rules.extend(doc.get("rules", []))

        cm_verbs = set()
        for rule in production_rules:
            api_groups = rule.get("apiGroups", [])
            resources = rule.get("resources", [])
            verbs = set(rule.get("verbs", []))
            if "configmaps" in resources and \
               any(g in api_groups for g in ["", "*"]):
                cm_verbs.update(verbs)

        if "*" not in cm_verbs:
            required = {"create", "update", "delete"}
            assert required.issubset(cm_verbs), \
                f"Missing configmap verbs. Need {required}, have {cm_verbs}"

    def test_rbac_pod_view_permissions(self):
        """A Role in production must allow get/list Pods."""
        docs = get_all_rbac_docs()
        production_rules = []
        for doc in docs:
            if doc["kind"] == "Role" and \
               doc.get("metadata", {}).get("namespace") == "production":
                production_rules.extend(doc.get("rules", []))

        pod_verbs = set()
        for rule in production_rules:
            api_groups = rule.get("apiGroups", [])
            resources = rule.get("resources", [])
            verbs = set(rule.get("verbs", []))
            if "pods" in resources and \
               any(g in api_groups for g in ["", "*"]):
                pod_verbs.update(verbs)

        if "*" not in pod_verbs:
            assert "get" in pod_verbs and "list" in pod_verbs, \
                f"Missing pod get/list verbs. Have {pod_verbs}"

    def test_rbac_pod_log_permissions(self):
        """A Role in production must allow get on pods/log."""
        docs = get_all_rbac_docs()
        production_rules = []
        for doc in docs:
            if doc["kind"] == "Role" and \
               doc.get("metadata", {}).get("namespace") == "production":
                production_rules.extend(doc.get("rules", []))

        log_verbs = set()
        for rule in production_rules:
            api_groups = rule.get("apiGroups", [])
            resources = rule.get("resources", [])
            verbs = set(rule.get("verbs", []))
            if "pods/log" in resources and \
               any(g in api_groups for g in ["", "*"]):
                log_verbs.update(verbs)

        assert "get" in log_verbs or "*" in log_verbs, \
            f"Missing pods/log get verb. Have {log_verbs}"

    def test_rbac_namespace_cluster_role(self):
        """A ClusterRole must allow create/delete Namespaces."""
        docs = get_all_rbac_docs()
        ns_verbs = set()
        for doc in docs:
            if doc["kind"] == "ClusterRole":
                for rule in doc.get("rules", []):
                    api_groups = rule.get("apiGroups", [])
                    resources = rule.get("resources", [])
                    verbs = set(rule.get("verbs", []))
                    if "namespaces" in resources and \
                       any(g in api_groups for g in ["", "*"]):
                        ns_verbs.update(verbs)

        if "*" not in ns_verbs:
            required = {"create", "delete"}
            assert required.issubset(ns_verbs), \
                f"Missing namespace verbs. Need {required}, have {ns_verbs}"

    def test_rbac_ci_deployer_binding(self):
        """At least one binding must reference ServiceAccount ci-deployer in ci-cd."""
        docs = get_all_rbac_docs()
        found = False
        for doc in docs:
            if doc["kind"] in ("RoleBinding", "ClusterRoleBinding"):
                for subj in doc.get("subjects", []):
                    if subj.get("kind") == "ServiceAccount" and \
                       subj.get("name") == "ci-deployer" and \
                       subj.get("namespace") == "ci-cd":
                        found = True
                        break
        assert found, \
            "No binding references ServiceAccount ci-deployer in namespace ci-cd"

    def test_rbac_role_binding_in_production(self):
        """At least one RoleBinding must exist in the production namespace."""
        docs = get_all_rbac_docs()
        found = False
        for doc in docs:
            if doc["kind"] == "RoleBinding" and \
               doc.get("metadata", {}).get("namespace") == "production":
                found = True
                break
        assert found, "No RoleBinding found in production namespace"

    def test_rbac_cluster_role_binding_exists(self):
        """A ClusterRoleBinding must exist for namespace management."""
        docs = get_all_rbac_docs()
        found = False
        for doc in docs:
            if doc["kind"] == "ClusterRoleBinding":
                found = True
                break
        assert found, "No ClusterRoleBinding found"
