
"""
Tests for the FHIR CDS Hooks Medication Safety Service.

Verifies nginx reverse proxy configuration, PostgreSQL audit logging,
CDS Hooks 2.0 compliance, drug-drug interaction detection,
class-level interaction fallback, allergy cross-reactivity, and card
structure conformance.
"""

import json
import subprocess
import time
import signal
import os
import pytest
import requests

BASE_URL = "http://localhost:9000"
RXNORM_SYSTEM = "http://www.nlm.nih.gov/research/umls/rxnorm"


def _make_medication_request(med_id, code, display, status="draft", intent="order", patient_id="patient-1"):
    return {
        "resourceType": "MedicationRequest",
        "id": med_id,
        "status": status,
        "intent": intent,
        "medicationCodeableConcept": {
            "coding": [
                {
                    "system": RXNORM_SYSTEM,
                    "code": code,
                    "display": display,
                }
            ]
        },
        "subject": {"reference": f"Patient/{patient_id}"},
    }


def _make_allergy(allergy_id, code, display, patient_id="patient-1"):
    return {
        "resourceType": "AllergyIntolerance",
        "id": allergy_id,
        "clinicalStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
                    "code": "active",
                }
            ]
        },
        "code": {
            "coding": [
                {
                    "system": RXNORM_SYSTEM,
                    "code": code,
                    "display": display,
                }
            ]
        },
        "patient": {"reference": f"Patient/{patient_id}"},
    }


def _make_hook_request(
    patient_id,
    patient_name_given,
    patient_name_family,
    draft_meds,
    active_meds,
    allergies=None,
):
    """Build a CDS Hooks order-select request."""
    draft_entries = [{"resource": m} for m in draft_meds]
    active_entries = [{"resource": m} for m in active_meds]
    allergy_entries = [{"resource": a} for a in (allergies or [])]

    return {
        "hookInstance": f"hook-{patient_id}",
        "hook": "order-select",
        "context": {
            "userId": "Practitioner/dr-test",
            "patientId": patient_id,
            "selections": [f"MedicationRequest/{m['id']}" for m in draft_meds],
            "draftOrders": {
                "resourceType": "Bundle",
                "type": "collection",
                "entry": draft_entries,
            },
        },
        "prefetch": {
            "patient": {
                "resourceType": "Patient",
                "id": patient_id,
                "name": [
                    {"given": [patient_name_given], "family": patient_name_family}
                ],
            },
            "medications": {
                "resourceType": "Bundle",
                "type": "searchset",
                "entry": active_entries,
            },
            "allergies": {
                "resourceType": "Bundle",
                "type": "searchset",
                "entry": allergy_entries,
            },
        },
    }


def _query_audit_db(sql):
    """Query the PostgreSQL cds_audit database via psql using TCP trust auth."""
    result = subprocess.run(
        ["psql", "-h", "127.0.0.1", "-U", "postgres", "-d", "cds_audit", "-tA"],
        input=sql,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip()


@pytest.fixture(scope="session", autouse=True)
def cds_server():
    """Start the CDS service and wait for it to become ready via nginx."""
    proc = subprocess.Popen(
        ["python3", "/app/server.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd="/app",
        preexec_fn=os.setsid,
    )
    ready = False
    for _ in range(40):
        try:
            r = requests.get(f"{BASE_URL}/cds-services", timeout=2)
            if r.status_code == 200:
                ready = True
                break
        except Exception:
            pass
        time.sleep(0.5)

    if not ready:
        proc.terminate()
        proc.wait()
        pytest.fail("CDS service failed to start within 20 seconds (via nginx on port 9000)")

    yield proc
    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    proc.wait()


# -- Test group: nginx Reverse Proxy --

class TestNginxCORS:
    def test_cors_allow_origin(self):
        r = requests.get(f"{BASE_URL}/cds-services")
        assert r.headers.get("Access-Control-Allow-Origin") == "*", \
            f"Missing or wrong Access-Control-Allow-Origin header: {r.headers.get('Access-Control-Allow-Origin')}"

    def test_cors_allow_methods(self):
        r = requests.get(f"{BASE_URL}/cds-services")
        methods = r.headers.get("Access-Control-Allow-Methods", "")
        for m in ["GET", "POST", "OPTIONS"]:
            assert m in methods, f"Access-Control-Allow-Methods missing '{m}': got '{methods}'"

    def test_cors_allow_headers(self):
        r = requests.get(f"{BASE_URL}/cds-services")
        headers_val = r.headers.get("Access-Control-Allow-Headers", "")
        assert "Content-Type" in headers_val, f"Allow-Headers missing 'Content-Type': got '{headers_val}'"
        assert "Authorization" in headers_val, f"Allow-Headers missing 'Authorization': got '{headers_val}'"

    def test_options_preflight(self):
        r = requests.options(f"{BASE_URL}/cds-services/medication-safety")
        assert r.status_code == 204, f"OPTIONS should return 204, got {r.status_code}"
        assert r.headers.get("Access-Control-Allow-Origin") == "*"

    def test_version_header(self):
        r = requests.get(f"{BASE_URL}/cds-services")
        assert r.headers.get("X-CDS-Service-Version") == "2.0", \
            f"Missing or wrong X-CDS-Service-Version: {r.headers.get('X-CDS-Service-Version')}"

    def test_body_size_limit(self):
        """nginx should reject request bodies larger than 2MB with 413."""
        big_body = "x" * (3 * 1024 * 1024)
        try:
            r = requests.post(
                f"{BASE_URL}/cds-services/medication-safety",
                data=big_body,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            assert r.status_code == 413, f"Expected 413 for oversized body, got {r.status_code}"
        except requests.exceptions.ConnectionError:
            # nginx may close connection before reading full body — acceptable
            pass


# -- Test group: PostgreSQL Audit Logging --

class TestAuditLog:
    def test_audit_record_created(self):
        hook = _make_hook_request(
            patient_id="patient-audit-1",
            patient_name_given="Audit",
            patient_name_family="Test",
            draft_meds=[
                _make_medication_request("d-audit1", "1191", "Aspirin", patient_id="patient-audit-1"),
            ],
            active_meds=[
                _make_medication_request("m-audit1", "11289", "Warfarin", status="active", patient_id="patient-audit-1"),
            ],
        )
        r = requests.post(f"{BASE_URL}/cds-services/medication-safety", json=hook)
        assert r.status_code == 200

        time.sleep(0.5)

        result = _query_audit_db(
            "SELECT patient_id, cards_count, max_severity FROM decision_log "
            "WHERE patient_id = 'patient-audit-1' ORDER BY id DESC LIMIT 1;"
        )
        assert result, "No audit record found in decision_log for patient-audit-1"
        parts = result.split("|")
        assert parts[0] == "patient-audit-1"
        assert int(parts[1]) >= 1, f"Expected cards_count >= 1, got {parts[1]}"
        assert parts[2] == "critical", f"Expected max_severity 'critical', got '{parts[2]}'"

    def test_audit_request_hash_sha256(self):
        hook = _make_hook_request(
            patient_id="patient-audit-hash",
            patient_name_given="Hash",
            patient_name_family="Verify",
            draft_meds=[
                _make_medication_request("d-hash1", "6809", "Metformin", patient_id="patient-audit-hash"),
            ],
            active_meds=[],
        )
        r = requests.post(f"{BASE_URL}/cds-services/medication-safety", json=hook)
        assert r.status_code == 200

        time.sleep(0.5)

        result = _query_audit_db(
            "SELECT request_hash, hook_instance FROM decision_log "
            "WHERE patient_id = 'patient-audit-hash' ORDER BY id DESC LIMIT 1;"
        )
        assert result, "No audit record found for patient-audit-hash"
        parts = result.split("|")
        assert len(parts[0]) == 64, f"request_hash should be SHA-256 hex (64 chars), got {len(parts[0])} chars"
        assert parts[1] == "hook-patient-audit-hash", f"hook_instance mismatch: {parts[1]}"

    def test_audit_severity_none_when_no_alerts(self):
        hook = _make_hook_request(
            patient_id="patient-audit-none",
            patient_name_given="NoAlert",
            patient_name_family="Check",
            draft_meds=[
                _make_medication_request("d-none1", "6809", "Metformin", patient_id="patient-audit-none"),
            ],
            active_meds=[
                _make_medication_request("m-none1", "29046", "Lisinopril", status="active", patient_id="patient-audit-none"),
            ],
        )
        r = requests.post(f"{BASE_URL}/cds-services/medication-safety", json=hook)
        assert r.status_code == 200

        time.sleep(0.5)

        result = _query_audit_db(
            "SELECT max_severity FROM decision_log "
            "WHERE patient_id = 'patient-audit-none' ORDER BY id DESC LIMIT 1;"
        )
        assert result, "No audit record found for patient-audit-none"
        assert result == "none", f"Expected max_severity 'none' when no alerts, got '{result}'"


# -- Test group: Discovery Endpoint --

class TestDiscovery:
    def test_discovery_returns_200(self):
        r = requests.get(f"{BASE_URL}/cds-services")
        assert r.status_code == 200

    def test_discovery_has_services_array(self):
        r = requests.get(f"{BASE_URL}/cds-services")
        data = r.json()
        assert "services" in data
        assert isinstance(data["services"], list)
        assert len(data["services"]) >= 1

    def test_discovery_medication_safety_service(self):
        r = requests.get(f"{BASE_URL}/cds-services")
        services = r.json()["services"]
        med_svc = [s for s in services if s.get("id") == "medication-safety"]
        assert len(med_svc) == 1, "Expected exactly one 'medication-safety' service"
        svc = med_svc[0]
        assert svc["hook"] == "order-select"
        assert "title" in svc
        assert isinstance(svc["title"], str)
        assert "description" in svc
        assert isinstance(svc["description"], str)

    def test_discovery_prefetch_templates(self):
        r = requests.get(f"{BASE_URL}/cds-services")
        services = r.json()["services"]
        svc = [s for s in services if s.get("id") == "medication-safety"][0]
        prefetch = svc.get("prefetch", {})
        assert len(prefetch) >= 3, "Prefetch must request patient, medications, and allergies"

        prefetch_values = " ".join(str(v) for v in prefetch.values())
        assert "Patient" in prefetch_values, "Prefetch must include Patient resource"
        assert "MedicationRequest" in prefetch_values, "Prefetch must include MedicationRequest"
        assert "AllergyIntolerance" in prefetch_values, "Prefetch must include AllergyIntolerance"
        assert "status=active" in prefetch_values or "status%3Dactive" in prefetch_values, \
            "Medications prefetch must filter by status=active"

    def test_discovery_prefetch_token_syntax(self):
        """CDS Hooks prefetch templates must use double-brace token syntax."""
        r = requests.get(f"{BASE_URL}/cds-services")
        services = r.json()["services"]
        svc = [s for s in services if s.get("id") == "medication-safety"][0]
        prefetch = svc.get("prefetch", {})
        prefetch_values = " ".join(str(v) for v in prefetch.values())
        assert "{{context.patientId}}" in prefetch_values, \
            "Prefetch templates must use CDS Hooks double-brace token syntax: {{context.patientId}}"


# -- Test group: Warfarin + Aspirin (Critical Interaction) --

class TestWarfarinAspirin:
    def _send(self):
        hook = _make_hook_request(
            patient_id="patient-a",
            patient_name_given="Alice",
            patient_name_family="Smith",
            draft_meds=[
                _make_medication_request("draft-aspirin", "1191", "Aspirin", patient_id="patient-a"),
            ],
            active_meds=[
                _make_medication_request("med-warfarin", "11289", "Warfarin", status="active", patient_id="patient-a"),
            ],
        )
        return requests.post(f"{BASE_URL}/cds-services/medication-safety", json=hook)

    def test_returns_cards(self):
        r = self._send()
        assert r.status_code == 200
        data = r.json()
        assert "cards" in data
        assert len(data["cards"]) >= 1

    def test_critical_indicator(self):
        r = self._send()
        cards = r.json()["cards"]
        critical_cards = [c for c in cards if c.get("indicator") == "critical"]
        assert len(critical_cards) >= 1, "Expected at least one critical card for warfarin+aspirin"


# -- Test group: No Interaction (Metformin + Lisinopril) --

class TestNoInteraction:
    def test_no_critical_or_warning_cards(self):
        hook = _make_hook_request(
            patient_id="patient-b",
            patient_name_given="Bob",
            patient_name_family="Jones",
            draft_meds=[
                _make_medication_request("draft-lisinopril", "29046", "Lisinopril", patient_id="patient-b"),
            ],
            active_meds=[
                _make_medication_request("med-metformin", "6809", "Metformin", status="active", patient_id="patient-b"),
            ],
        )
        r = requests.post(f"{BASE_URL}/cds-services/medication-safety", json=hook)
        assert r.status_code == 200
        cards = r.json()["cards"]
        severe = [c for c in cards if c.get("indicator") in ("critical", "warning")]
        assert len(severe) == 0, f"Expected no critical/warning cards for metformin+lisinopril, got {len(severe)}"


# -- Test group: Multiple Interactions with Severity Ordering --

class TestMultipleInteractions:
    def _send(self):
        hook = _make_hook_request(
            patient_id="patient-e",
            patient_name_given="Eve",
            patient_name_family="Multi",
            draft_meds=[
                _make_medication_request("draft-aspirin", "1191", "Aspirin", patient_id="patient-e"),
                _make_medication_request("draft-spiro", "9997", "Spironolactone", patient_id="patient-e"),
            ],
            active_meds=[
                _make_medication_request("med-warfarin", "11289", "Warfarin", status="active", patient_id="patient-e"),
                _make_medication_request("med-lisinopril", "29046", "Lisinopril", status="active", patient_id="patient-e"),
            ],
        )
        return requests.post(f"{BASE_URL}/cds-services/medication-safety", json=hook)

    def test_multiple_cards(self):
        r = self._send()
        cards = r.json()["cards"]
        assert len(cards) >= 2, f"Expected at least 2 interaction cards, got {len(cards)}"

    def test_has_critical_and_warning(self):
        r = self._send()
        cards = r.json()["cards"]
        indicators = [c.get("indicator") for c in cards]
        assert "critical" in indicators, "Expected a critical card (warfarin+aspirin)"
        assert "warning" in indicators, "Expected a warning card (lisinopril+spironolactone)"

    def test_severity_ordering(self):
        r = self._send()
        cards = r.json()["cards"]
        severity_rank = {"critical": 0, "warning": 1, "info": 2}
        ranks = [severity_rank.get(c.get("indicator"), 3) for c in cards]
        assert ranks == sorted(ranks), "Cards must be ordered by severity: critical first, then warning, then info"


# -- Test group: Allergy Cross-Reactivity --

class TestAllergyCrossReactivity:
    def _send(self):
        hook = _make_hook_request(
            patient_id="patient-d",
            patient_name_given="Diana",
            patient_name_family="Allergy",
            draft_meds=[
                _make_medication_request("draft-amoxicillin", "723", "Amoxicillin", patient_id="patient-d"),
            ],
            active_meds=[],
            allergies=[
                _make_allergy("allergy-pcn", "7980", "Penicillin V", patient_id="patient-d"),
            ],
        )
        return requests.post(f"{BASE_URL}/cds-services/medication-safety", json=hook)

    def test_returns_allergy_card(self):
        r = self._send()
        assert r.status_code == 200
        cards = r.json()["cards"]
        assert len(cards) >= 1, "Expected at least one card for penicillin allergy + amoxicillin order"

    def test_allergy_card_severity(self):
        r = self._send()
        cards = r.json()["cards"]
        severe = [c for c in cards if c.get("indicator") in ("critical", "warning")]
        assert len(severe) >= 1, "Allergy cross-reactivity card should be critical or warning"


# -- Test group: SSRI + MAOI (Critical) --

class TestSSRIMAOI:
    def test_serotonin_syndrome_detected(self):
        hook = _make_hook_request(
            patient_id="patient-c",
            patient_name_given="Charlie",
            patient_name_family="Neuro",
            draft_meds=[
                _make_medication_request("draft-phenelzine", "8123", "Phenelzine", patient_id="patient-c"),
            ],
            active_meds=[
                _make_medication_request("med-fluoxetine", "4493", "Fluoxetine", status="active", patient_id="patient-c"),
            ],
        )
        r = requests.post(f"{BASE_URL}/cds-services/medication-safety", json=hook)
        assert r.status_code == 200
        cards = r.json()["cards"]
        critical = [c for c in cards if c.get("indicator") == "critical"]
        assert len(critical) >= 1, "Expected critical card for SSRI + MAOI combination"


# -- Test group: Card Structure Validation --

class TestCardStructure:
    def test_all_cards_have_required_fields(self):
        """Verify every card across all test scenarios has required CDS Hooks fields."""
        scenarios = [
            _make_hook_request("p1", "A", "B",
                [_make_medication_request("d1", "1191", "Aspirin", patient_id="p1")],
                [_make_medication_request("m1", "11289", "Warfarin", status="active", patient_id="p1")]),
            _make_hook_request("p2", "C", "D",
                [_make_medication_request("d2", "8123", "Phenelzine", patient_id="p2")],
                [_make_medication_request("m2", "4493", "Fluoxetine", status="active", patient_id="p2")]),
            _make_hook_request("p3", "E", "F",
                [_make_medication_request("d3", "723", "Amoxicillin", patient_id="p3")],
                [],
                [_make_allergy("a1", "7980", "Penicillin V", patient_id="p3")]),
        ]
        for hook in scenarios:
            r = requests.post(f"{BASE_URL}/cds-services/medication-safety", json=hook)
            assert r.status_code == 200
            cards = r.json().get("cards", [])
            for card in cards:
                assert "summary" in card, f"Card missing 'summary': {card}"
                assert isinstance(card["summary"], str), f"summary must be string: {card}"
                assert "detail" in card, f"Card missing 'detail': {card}"
                assert isinstance(card["detail"], str), f"detail must be string: {card}"
                assert "indicator" in card, f"Card missing 'indicator': {card}"
                assert card["indicator"] in ("info", "warning", "critical"), \
                    f"Invalid indicator '{card['indicator']}': must be info/warning/critical"
                assert "source" in card, f"Card missing 'source': {card}"
                assert isinstance(card["source"], dict), f"source must be object: {card}"
                assert "label" in card["source"], f"source missing 'label': {card}"


# -- Test group: CYP3A4 Interaction (Simvastatin + Clarithromycin) --

class TestCYP3A4Interaction:
    def test_statin_macrolide_detected(self):
        hook = _make_hook_request(
            patient_id="patient-f",
            patient_name_given="Frank",
            patient_name_family="Statin",
            draft_meds=[
                _make_medication_request("draft-clarithro", "21212", "Clarithromycin", patient_id="patient-f"),
            ],
            active_meds=[
                _make_medication_request("med-simvastatin", "36567", "Simvastatin", status="active", patient_id="patient-f"),
            ],
        )
        r = requests.post(f"{BASE_URL}/cds-services/medication-safety", json=hook)
        assert r.status_code == 200
        cards = r.json()["cards"]
        assert len(cards) >= 1, "Expected interaction card for simvastatin + clarithromycin"
        severe = [c for c in cards if c.get("indicator") in ("critical", "warning")]
        assert len(severe) >= 1, "Simvastatin + clarithromycin interaction should be critical or warning"
