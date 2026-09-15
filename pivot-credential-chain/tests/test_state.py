
import json
import os
import pytest


EXPECTED_DA_PASSWORD = "D0ma!nRuler#2024"

EXPECTED_PATH = ["svc_dbadmin", "db_admins", "server_operators", "dc01", "domain_admins"]

EXPECTED_FRAGMENTS = [
    "Project Nightfall",
    "47.6062N 122.3321W",
    "ALPHA-SEVEN-NINER-DELTA",
    "7429-ECHO-3851",
]


class TestDomainAdminPassword:
    """Verify recovery of the effective Domain Admin password."""

    def test_da_password_file_exists(self):
        assert os.path.isfile("/app/results/da_password.txt"), (
            "DA password file not found at /app/results/da_password.txt"
        )

    def test_da_password_correct(self):
        with open("/app/results/da_password.txt") as f:
            password = f.read().strip()
        assert password == EXPECTED_DA_PASSWORD, (
            f"DA password incorrect: got '{password}'"
        )


class TestViableAttackPath:
    """Verify correct evaluation of the AD security graph."""

    def test_viable_path_file_exists(self):
        assert os.path.isfile("/app/results/viable_path.json"), (
            "Viable path file not found at /app/results/viable_path.json"
        )

    def test_viable_path_is_valid_json(self):
        with open("/app/results/viable_path.json") as f:
            content = f.read().strip()
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            pytest.fail(f"viable_path.json is not valid JSON: {e}")
        assert isinstance(data, list), (
            f"viable_path.json should be a JSON array, got {type(data).__name__}"
        )

    def test_viable_path_correct(self):
        with open("/app/results/viable_path.json") as f:
            path = json.loads(f.read().strip())
        assert path == EXPECTED_PATH, (
            f"Viable path incorrect.\n"
            f"Expected: {EXPECTED_PATH}\n"
            f"Got:      {path}"
        )

    def test_viable_path_starts_with_user(self):
        with open("/app/results/viable_path.json") as f:
            path = json.loads(f.read().strip())
        assert len(path) > 0, "Path is empty"
        assert path[0] == "svc_dbadmin", (
            f"Path should start with 'svc_dbadmin', got '{path[0]}'"
        )

    def test_viable_path_ends_with_domain_admins(self):
        with open("/app/results/viable_path.json") as f:
            path = json.loads(f.read().strip())
        assert len(path) > 0, "Path is empty"
        assert path[-1] == "domain_admins", (
            f"Path should end with 'domain_admins', got '{path[-1]}'"
        )


class TestDecryptedDocument:
    """Verify the classified document was correctly decrypted."""

    def test_decrypted_document_file_exists(self):
        assert os.path.isfile("/app/results/decrypted_document.txt"), (
            "Decrypted document not found at /app/results/decrypted_document.txt"
        )

    def test_decrypted_document_contains_project_name(self):
        with open("/app/results/decrypted_document.txt") as f:
            content = f.read().strip()
        assert EXPECTED_FRAGMENTS[0] in content, (
            f"Decrypted document missing '{EXPECTED_FRAGMENTS[0]}'"
        )

    def test_decrypted_document_contains_coordinates(self):
        with open("/app/results/decrypted_document.txt") as f:
            content = f.read().strip()
        assert EXPECTED_FRAGMENTS[1] in content, (
            f"Decrypted document missing coordinates '{EXPECTED_FRAGMENTS[1]}'"
        )

    def test_decrypted_document_contains_auth_code(self):
        with open("/app/results/decrypted_document.txt") as f:
            content = f.read().strip()
        assert EXPECTED_FRAGMENTS[2] in content, (
            f"Decrypted document missing authorization code '{EXPECTED_FRAGMENTS[2]}'"
        )

    def test_decrypted_document_contains_pin(self):
        with open("/app/results/decrypted_document.txt") as f:
            content = f.read().strip()
        assert EXPECTED_FRAGMENTS[3] in content, (
            f"Decrypted document missing facility PIN '{EXPECTED_FRAGMENTS[3]}'"
        )

    def test_decrypted_document_is_classified(self):
        with open("/app/results/decrypted_document.txt") as f:
            content = f.read().strip()
        assert content.startswith("CLASSIFIED:"), (
            "Decrypted document should start with 'CLASSIFIED:'"
        )
