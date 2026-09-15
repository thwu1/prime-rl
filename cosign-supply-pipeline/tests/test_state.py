
import json
import os
import subprocess

import pytest

PIPELINE_DIR = "/app/pipeline"
PKI_DIR = f"{PIPELINE_DIR}/pki"
KEYS_DIR = f"{PIPELINE_DIR}/keys"
OFFLINE_DIR = f"{PIPELINE_DIR}/offline"
ATT_DIR = f"{PIPELINE_DIR}/attestations"


# ---------- PKI Structure ----------

class TestPKIStructure:
    def test_root_ca_cert_exists(self):
        assert os.path.isfile(f"{PKI_DIR}/root-ca.pem")

    def test_root_ca_key_exists(self):
        assert os.path.isfile(f"{PKI_DIR}/root-ca-key.pem")

    def test_intermediate_ca_cert_exists(self):
        assert os.path.isfile(f"{PKI_DIR}/intermediate-ca.pem")

    def test_intermediate_ca_key_exists(self):
        assert os.path.isfile(f"{PKI_DIR}/intermediate-ca-key.pem")

    def test_leaf_cert_exists(self):
        assert os.path.isfile(f"{PKI_DIR}/leaf.pem")

    def test_leaf_key_exists(self):
        assert os.path.isfile(f"{PKI_DIR}/leaf-key.pem")

    def test_chain_file_exists(self):
        assert os.path.isfile(f"{PKI_DIR}/chain.pem")


# ---------- PKI Chain Validity ----------

class TestPKIChainValidity:
    def test_root_ca_is_self_signed(self):
        r = subprocess.run(
            ["openssl", "verify", "-CAfile", f"{PKI_DIR}/root-ca.pem",
             f"{PKI_DIR}/root-ca.pem"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, f"Root CA not self-signed: {r.stderr}"

    def test_root_ca_is_ca(self):
        r = subprocess.run(
            ["openssl", "x509", "-in", f"{PKI_DIR}/root-ca.pem",
             "-text", "-noout"],
            capture_output=True, text=True,
        )
        assert "CA:TRUE" in r.stdout, "Root CA missing CA:TRUE"

    def test_root_ca_has_keycertsign(self):
        r = subprocess.run(
            ["openssl", "x509", "-in", f"{PKI_DIR}/root-ca.pem",
             "-text", "-noout"],
            capture_output=True, text=True,
        )
        assert "Certificate Sign" in r.stdout, "Root CA missing keyCertSign"

    def test_intermediate_signed_by_root(self):
        r = subprocess.run(
            ["openssl", "verify", "-CAfile", f"{PKI_DIR}/root-ca.pem",
             f"{PKI_DIR}/intermediate-ca.pem"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, f"Intermediate not signed by root: {r.stderr}"

    def test_intermediate_is_ca(self):
        r = subprocess.run(
            ["openssl", "x509", "-in", f"{PKI_DIR}/intermediate-ca.pem",
             "-text", "-noout"],
            capture_output=True, text=True,
        )
        assert "CA:TRUE" in r.stdout, "Intermediate CA missing CA:TRUE"

    def test_intermediate_has_keycertsign(self):
        r = subprocess.run(
            ["openssl", "x509", "-in", f"{PKI_DIR}/intermediate-ca.pem",
             "-text", "-noout"],
            capture_output=True, text=True,
        )
        assert "Certificate Sign" in r.stdout, "Intermediate missing keyCertSign"

    def test_intermediate_has_pathlen_zero(self):
        r = subprocess.run(
            ["openssl", "x509", "-in", f"{PKI_DIR}/intermediate-ca.pem",
             "-text", "-noout"],
            capture_output=True, text=True,
        )
        assert "pathlen:0" in r.stdout, "Intermediate CA missing pathlen:0 constraint"

    def test_leaf_signed_by_chain(self):
        r = subprocess.run(
            ["openssl", "verify",
             "-CAfile", f"{PKI_DIR}/root-ca.pem",
             "-untrusted", f"{PKI_DIR}/intermediate-ca.pem",
             f"{PKI_DIR}/leaf.pem"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, f"Leaf not signed by chain: {r.stderr}"

    def test_leaf_is_not_ca(self):
        r = subprocess.run(
            ["openssl", "x509", "-in", f"{PKI_DIR}/leaf.pem",
             "-text", "-noout"],
            capture_output=True, text=True,
        )
        assert "CA:FALSE" in r.stdout, "Leaf cert should have CA:FALSE"

    def test_leaf_has_digital_signature(self):
        r = subprocess.run(
            ["openssl", "x509", "-in", f"{PKI_DIR}/leaf.pem",
             "-text", "-noout"],
            capture_output=True, text=True,
        )
        assert "Digital Signature" in r.stdout, "Leaf missing digitalSignature"

    def test_leaf_no_keycertsign(self):
        r = subprocess.run(
            ["openssl", "x509", "-in", f"{PKI_DIR}/leaf.pem",
             "-text", "-noout"],
            capture_output=True, text=True,
        )
        lines = r.stdout.split('\n')
        for i, line in enumerate(lines):
            if 'X509v3 Key Usage:' in line and 'Extended' not in line:
                usage_line = lines[i + 1].strip() if i + 1 < len(lines) else ""
                assert 'Certificate Sign' not in usage_line, \
                    f"Leaf cert must not have keyCertSign, got: {usage_line}"
                return

    def test_certs_use_ecdsa(self):
        for cert_name in ["root-ca.pem", "intermediate-ca.pem", "leaf.pem"]:
            r = subprocess.run(
                ["openssl", "x509", "-in", f"{PKI_DIR}/{cert_name}",
                 "-text", "-noout"],
                capture_output=True, text=True,
            )
            output_lower = r.stdout.lower()
            assert ("ecdsa" in output_lower or "ec public key" in output_lower
                    or "prime256v1" in output_lower or "id-ecpublickey" in output_lower), \
                f"{cert_name} not using elliptic curve cryptography"

    def test_chain_pem_has_two_certs(self):
        with open(f"{PKI_DIR}/chain.pem") as f:
            content = f.read()
        count = content.count("BEGIN CERTIFICATE")
        assert count >= 2, f"chain.pem has {count} certs, expected >= 2"


# ---------- Cosign Keys ----------

class TestCosignKeys:
    def test_cosign_key_exists(self):
        assert os.path.isfile(f"{KEYS_DIR}/cosign.key")

    def test_cosign_pub_exists(self):
        assert os.path.isfile(f"{KEYS_DIR}/cosign.pub")

    def test_cosign_pub_is_pem(self):
        with open(f"{KEYS_DIR}/cosign.pub") as f:
            content = f.read()
        assert "BEGIN PUBLIC KEY" in content

    def test_cosign_pub_matches_leaf(self):
        """The cosign public key must match the leaf certificate's public key."""
        r = subprocess.run(
            ["openssl", "x509", "-in", f"{PKI_DIR}/leaf.pem", "-pubkey", "-noout"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, f"Failed to extract pubkey from leaf: {r.stderr}"

        with open(f"{KEYS_DIR}/cosign.pub") as f:
            cosign_pub = f.read()

        def extract_b64(pem_text):
            return ''.join(
                line for line in pem_text.strip().split('\n')
                if not line.startswith('-----')
            )

        assert extract_b64(r.stdout) == extract_b64(cosign_pub), \
            "cosign.pub does not match the leaf certificate's public key"


# ---------- Offline Signature Verification ----------

class TestOfflineSignatureVerification:
    def test_webapp_dir_exists(self):
        assert os.path.isdir(f"{OFFLINE_DIR}/webapp")

    def test_worker_dir_exists(self):
        assert os.path.isdir(f"{OFFLINE_DIR}/worker")

    def test_webapp_signature_verifies(self):
        r = subprocess.run(
            ["cosign", "verify",
             "--key", f"{KEYS_DIR}/cosign.pub",
             "--insecure-ignore-tlog",
             "--local-image", f"{OFFLINE_DIR}/webapp"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, f"Webapp signature verification failed: {r.stderr}"

    def test_worker_signature_verifies(self):
        r = subprocess.run(
            ["cosign", "verify",
             "--key", f"{KEYS_DIR}/cosign.pub",
             "--insecure-ignore-tlog",
             "--local-image", f"{OFFLINE_DIR}/worker"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, f"Worker signature verification failed: {r.stderr}"


# ---------- Signature Annotations ----------

class TestSignatureAnnotations:
    @pytest.mark.parametrize("image", ["webapp", "worker"])
    def test_annotation_version(self, image):
        r = subprocess.run(
            ["cosign", "verify",
             "--key", f"{KEYS_DIR}/cosign.pub",
             "--insecure-ignore-tlog",
             "--local-image", f"{OFFLINE_DIR}/{image}",
             "-a", "pipeline.version=v1"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, \
            f"{image} missing annotation pipeline.version=v1: {r.stderr}"

    @pytest.mark.parametrize("image", ["webapp", "worker"])
    def test_annotation_stage(self, image):
        r = subprocess.run(
            ["cosign", "verify",
             "--key", f"{KEYS_DIR}/cosign.pub",
             "--insecure-ignore-tlog",
             "--local-image", f"{OFFLINE_DIR}/{image}",
             "-a", "pipeline.stage=production"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, \
            f"{image} missing annotation pipeline.stage=production: {r.stderr}"


# ---------- Offline Attestation Verification ----------

class TestOfflineAttestationVerification:
    def test_webapp_slsa_attestation(self):
        r = subprocess.run(
            ["cosign", "verify-attestation",
             "--key", f"{KEYS_DIR}/cosign.pub",
             "--type", "slsaprovenance",
             "--insecure-ignore-tlog",
             "--local-image", f"{OFFLINE_DIR}/webapp"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, f"Webapp SLSA attestation failed: {r.stderr}"

    def test_worker_slsa_attestation(self):
        r = subprocess.run(
            ["cosign", "verify-attestation",
             "--key", f"{KEYS_DIR}/cosign.pub",
             "--type", "slsaprovenance",
             "--insecure-ignore-tlog",
             "--local-image", f"{OFFLINE_DIR}/worker"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, f"Worker SLSA attestation failed: {r.stderr}"

    def test_webapp_vuln_attestation(self):
        r = subprocess.run(
            ["cosign", "verify-attestation",
             "--key", f"{KEYS_DIR}/cosign.pub",
             "--type", "vuln",
             "--insecure-ignore-tlog",
             "--local-image", f"{OFFLINE_DIR}/webapp"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, f"Webapp vuln attestation failed: {r.stderr}"


# ---------- Attestation Predicate Files ----------

class TestAttestationPredicates:
    def test_slsa_webapp_exists(self):
        assert os.path.isfile(f"{ATT_DIR}/slsa-provenance-webapp.json")

    def test_slsa_worker_exists(self):
        assert os.path.isfile(f"{ATT_DIR}/slsa-provenance-worker.json")

    def test_vuln_webapp_exists(self):
        assert os.path.isfile(f"{ATT_DIR}/vuln-scan-webapp.json")

    def test_slsa_webapp_has_builder(self):
        with open(f"{ATT_DIR}/slsa-provenance-webapp.json") as f:
            data = json.load(f)
        assert "builder" in data, "SLSA predicate missing 'builder'"
        assert "id" in data["builder"], "builder missing 'id'"

    def test_slsa_webapp_has_materials(self):
        with open(f"{ATT_DIR}/slsa-provenance-webapp.json") as f:
            data = json.load(f)
        assert "materials" in data, "SLSA predicate missing 'materials'"
        assert len(data["materials"]) > 0, "materials should not be empty"

    def test_slsa_webapp_has_metadata(self):
        with open(f"{ATT_DIR}/slsa-provenance-webapp.json") as f:
            data = json.load(f)
        assert "metadata" in data, "SLSA predicate missing 'metadata'"

    def test_slsa_worker_has_builder(self):
        with open(f"{ATT_DIR}/slsa-provenance-worker.json") as f:
            data = json.load(f)
        assert "builder" in data, "Worker SLSA predicate missing 'builder'"

    def test_slsa_worker_has_materials(self):
        with open(f"{ATT_DIR}/slsa-provenance-worker.json") as f:
            data = json.load(f)
        assert "materials" in data, "Worker SLSA predicate missing 'materials'"
        assert len(data["materials"]) > 0, "Worker materials should not be empty"

    def test_slsa_worker_has_metadata(self):
        with open(f"{ATT_DIR}/slsa-provenance-worker.json") as f:
            data = json.load(f)
        assert "metadata" in data, "Worker SLSA predicate missing 'metadata'"


# ---------- Audit Report ----------

class TestAuditReport:
    @pytest.fixture(autouse=True)
    def load_report(self):
        path = f"{PIPELINE_DIR}/audit-report.json"
        assert os.path.isfile(path), "audit-report.json not found"
        with open(path) as f:
            self.report = json.load(f)

    def test_has_images_array(self):
        assert "images" in self.report
        assert isinstance(self.report["images"], list)
        assert len(self.report["images"]) >= 2

    def test_images_have_digest(self):
        for img in self.report["images"]:
            assert "digest" in img, f"Image entry missing digest: {img}"
            assert img["digest"].startswith("sha256:"), \
                f"Digest should start with sha256: got {img['digest']}"

    def test_images_have_reference(self):
        for img in self.report["images"]:
            assert "reference" in img, f"Image entry missing reference: {img}"

    def test_images_have_signature_status(self):
        for img in self.report["images"]:
            has_status = ("signed" in img or "signature_verified" in img)
            assert has_status, f"Image entry missing signature status: {img}"

    def test_images_have_attestation_info(self):
        refs = [img.get("reference", "") for img in self.report["images"]]
        webapp = None
        for img in self.report["images"]:
            ref = img.get("reference", img.get("name", ""))
            if "webapp" in ref:
                webapp = img
                break
        assert webapp is not None, f"No webapp entry found. Refs: {refs}"
        assert "attestations" in webapp, "webapp missing attestations field"

    def test_has_pki_section(self):
        assert "pki" in self.report
        pki = self.report["pki"]
        assert "chain_valid" in pki
        assert pki["chain_valid"] is True

    def test_pki_has_subjects(self):
        pki = self.report["pki"]
        assert "root_ca_subject" in pki
        assert "intermediate_ca_subject" in pki
        assert "leaf_subject" in pki

    def test_overall_status_pass(self):
        assert "overall_status" in self.report
        assert self.report["overall_status"].upper() == "PASS"
