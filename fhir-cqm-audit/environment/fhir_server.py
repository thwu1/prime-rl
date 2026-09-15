"""
FHIR R4 Mock Server for Clinical Quality Measures Audit Task.

Implements a subset of FHIR R4 REST API using Python stdlib with in-memory
storage and automatic state persistence to disk.
Supports Patient, Condition, Observation, MedicationRequest, and ServiceRequest
resources with search, read, create, and update operations.

"""

import json
import uuid
import sys
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

resources = {}
initial_resource_ids = {}

STATE_FILE = "/app/fhir_state.json"


def save_state():
    """Persist current resources and initial_resource_ids to disk."""
    state = {
        "resources": resources,
        "initial_resource_ids": initial_resource_ids,
    }
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, STATE_FILE)


def load_data(path="/app/patient_data.json"):
    """Load from persisted state file if available, otherwise from seed data."""
    global resources, initial_resource_ids

    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            state = json.load(f)
        resources = state["resources"]
        initial_resource_ids = state["initial_resource_ids"]
        return

    with open(path) as f:
        data = json.load(f)
    for resource_type, entries in data.items():
        resources[resource_type] = {}
        initial_resource_ids[resource_type] = []
        for entry in entries:
            rid = entry["id"]
            resources[resource_type][rid] = entry
            initial_resource_ids[resource_type].append(rid)

    save_state()


def match_patient_ref(resource, patient_param):
    patient_id = patient_param.replace("Patient/", "")
    patient_ref = "Patient/" + patient_id
    for field in ("subject", "patient"):
        ref = resource.get(field, {})
        if isinstance(ref, dict):
            ref_val = ref.get("reference", "")
            if ref_val in (patient_ref, patient_id):
                return True
    return False


def match_code(resource, code_param):
    code_obj = resource.get("code", {})
    for coding in code_obj.get("coding", []):
        if coding.get("code") == code_param:
            return True
    med_obj = resource.get("medicationCodeableConcept", {})
    for coding in med_obj.get("coding", []):
        if coding.get("code") == code_param:
            return True
    return False


def match_status(resource, status_param):
    return resource.get("status") == status_param


def make_bundle(entries, bundle_type="searchset"):
    return {
        "resourceType": "Bundle",
        "type": bundle_type,
        "total": len(entries),
        "entry": [
            {
                "resource": e,
                "fullUrl": "http://localhost:8080/fhir/{}/{}".format(
                    e.get("resourceType", "Resource"), e.get("id", "")
                ),
            }
            for e in entries
        ],
    }


class FHIRHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        sys.stderr.write("%s - - [%s] %s\n" % (
            self.client_address[0],
            self.log_date_time_string(),
            format % args,
        ))

    def send_fhir_response(self, data, status=200):
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/fhir+json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def parse_path(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        return path, params

    def do_GET(self):
        path, params = self.parse_path()

        if path == "/fhir/metadata":
            self.handle_metadata()
        elif path == "/fhir/_initial_ids":
            self.handle_initial_ids()
        elif path.startswith("/fhir/"):
            parts = path[6:].split("/")
            if len(parts) == 1:
                self.handle_search(parts[0], params)
            elif len(parts) == 2:
                self.handle_read(parts[0], parts[1])
            else:
                self.send_fhir_response({"error": "Not found"}, 404)
        else:
            self.send_fhir_response({"error": "Not found"}, 404)

    def do_POST(self):
        path, _ = self.parse_path()
        if path.startswith("/fhir/"):
            parts = path[6:].split("/")
            if len(parts) == 1:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length)
                try:
                    data = json.loads(body)
                except (json.JSONDecodeError, ValueError):
                    self.send_fhir_response({
                        "resourceType": "OperationOutcome",
                        "issue": [{"severity": "error", "code": "invalid",
                                   "diagnostics": "Invalid JSON body"}],
                    }, 400)
                    return
                self.handle_create(parts[0], data)
            else:
                self.send_fhir_response({"error": "Not found"}, 404)
        else:
            self.send_fhir_response({"error": "Not found"}, 404)

    def do_PUT(self):
        path, _ = self.parse_path()
        if path.startswith("/fhir/"):
            parts = path[6:].split("/")
            if len(parts) == 2:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length)
                try:
                    data = json.loads(body)
                except (json.JSONDecodeError, ValueError):
                    self.send_fhir_response({
                        "resourceType": "OperationOutcome",
                        "issue": [{"severity": "error", "code": "invalid",
                                   "diagnostics": "Invalid JSON body"}],
                    }, 400)
                    return
                self.handle_update(parts[0], parts[1], data)
            else:
                self.send_fhir_response({"error": "Not found"}, 404)
        else:
            self.send_fhir_response({"error": "Not found"}, 404)

    def handle_metadata(self):
        cap = {
            "resourceType": "CapabilityStatement",
            "status": "active",
            "date": "2025-01-15",
            "kind": "instance",
            "fhirVersion": "4.0.1",
            "format": ["json"],
            "rest": [
                {
                    "mode": "server",
                    "resource": [
                        {
                            "type": rt,
                            "interaction": [
                                {"code": "read"},
                                {"code": "search-type"},
                                {"code": "create"},
                                {"code": "update"},
                            ],
                            "searchParam": [
                                {"name": "patient", "type": "reference"},
                                {"name": "subject", "type": "reference"},
                                {"name": "code", "type": "token"},
                                {"name": "status", "type": "token"},
                            ],
                        }
                        for rt in [
                            "Patient", "Condition", "Observation",
                            "MedicationRequest", "ServiceRequest",
                        ]
                    ],
                }
            ],
        }
        self.send_fhir_response(cap)

    def handle_initial_ids(self):
        self.send_fhir_response(initial_resource_ids)

    def handle_search(self, resource_type, params):
        if resource_type not in resources:
            self.send_fhir_response(make_bundle([]))
            return

        entries = list(resources[resource_type].values())

        patient_param = params.get("patient") or params.get("subject")
        if patient_param:
            entries = [e for e in entries if match_patient_ref(e, patient_param)]

        code_param = params.get("code")
        if code_param:
            entries = [e for e in entries if match_code(e, code_param)]

        status_param = params.get("status")
        if status_param:
            entries = [e for e in entries if match_status(e, status_param)]

        category_param = params.get("category")
        if category_param:
            filtered = []
            for e in entries:
                for cat in e.get("category", []):
                    for coding in cat.get("coding", []):
                        if coding.get("code") == category_param:
                            filtered.append(e)
                            break
            entries = filtered

        count_param = params.get("_count")
        if count_param:
            try:
                entries = entries[:int(count_param)]
            except ValueError:
                pass

        self.send_fhir_response(make_bundle(entries))

    def handle_read(self, resource_type, resource_id):
        if resource_type in resources and resource_id in resources[resource_type]:
            self.send_fhir_response(resources[resource_type][resource_id])
        else:
            self.send_fhir_response({
                "resourceType": "OperationOutcome",
                "issue": [{
                    "severity": "error",
                    "code": "not-found",
                    "diagnostics": "{}/{} not found".format(resource_type, resource_id),
                }],
            }, 404)

    def handle_create(self, resource_type, body):
        new_id = str(uuid.uuid4())[:8]
        body["id"] = new_id
        body["resourceType"] = resource_type
        if resource_type not in resources:
            resources[resource_type] = {}
        resources[resource_type][new_id] = body
        save_state()
        self.send_fhir_response(body, 201)

    def handle_update(self, resource_type, resource_id, body):
        body["id"] = resource_id
        body["resourceType"] = resource_type
        if resource_type not in resources:
            resources[resource_type] = {}
        resources[resource_type][resource_id] = body
        save_state()
        self.send_fhir_response(body, 200)


def main():
    data_path = "/app/patient_data.json"
    if len(sys.argv) > 1:
        data_path = sys.argv[1]
    load_data(data_path)
    print("FHIR server starting with {} resource types".format(len(resources)))
    for rt, entries in resources.items():
        print("  {}: {} resources".format(rt, len(entries)))
    sys.stdout.flush()

    server = HTTPServer(("0.0.0.0", 8080), FHIRHandler)
    print("FHIR server listening on port 8080")
    sys.stdout.flush()
    server.serve_forever()


if __name__ == "__main__":
    main()
