#!/usr/bin/env python3
"""
CDS Hooks 2.0 Medication Safety Service with PostgreSQL audit logging.
"""

import json
import os
import hashlib

from flask import Flask, request, jsonify
import psycopg2
from interaction_engine import InteractionEngine

app = Flask(__name__)
engine = InteractionEngine(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))

DB_CONFIG = {
    "dbname": "cds_audit",
    "user": "postgres",
    "host": "127.0.0.1",
}


def _log_decision(patient_id, hook_instance, cards_count, max_severity, request_hash):
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO decision_log (patient_id, hook_instance, cards_count, max_severity, request_hash) "
            "VALUES (%s, %s, %s, %s, %s)",
            (patient_id, hook_instance, cards_count, max_severity, request_hash),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        app.logger.error(f"Audit logging failed: {e}")


@app.route("/cds-services", methods=["GET"])
def discovery():
    return jsonify(
        {
            "services": [
                {
                    "hook": "order-select",
                    "title": "Medication Safety CDS Service",
                    "description": (
                        "Checks for drug-drug interactions, pharmacological class "
                        "interactions, and allergy cross-reactivity for newly ordered "
                        "medications."
                    ),
                    "id": "medication-safety",
                    "prefetch": {
                        "patient": "Patient/{context.patientId}",
                        "medications": "MedicationRequest?patient={context.patientId}",
                        "allergies": "AllergyIntolerance?patient={context.patientId}",
                    },
                }
            ]
        }
    )


def _extract_resources_from_prefetch(prefetch_value, resource_type):
    if not prefetch_value or not isinstance(prefetch_value, dict):
        return []
    resources = []
    if prefetch_value.get("resourceType") == "Bundle":
        for entry in prefetch_value.get("entry", []):
            res = entry.get("resource", entry)
            if res.get("resourceType") == resource_type:
                resources.append(res)
    elif prefetch_value.get("resourceType") == resource_type:
        resources.append(prefetch_value)
    return resources


@app.route("/cds-services/medication-safety", methods=["POST"])
def medication_safety():
    raw_body = request.get_data(as_text=True)
    request_hash = hashlib.md5(raw_body.encode("utf-8")).hexdigest()
    hook_request = json.loads(raw_body)

    context = hook_request.get("context", {})
    draft_orders_bundle = context.get("draftOrders", {})
    draft_meds = []
    for entry in draft_orders_bundle.get("entry", []):
        resource = entry.get("resource", entry)
        if resource.get("resourceType") == "MedicationRequest":
            draft_meds.append(resource)

    prefetch = hook_request.get("prefetch", {})
    current_meds = _extract_resources_from_prefetch(
        prefetch.get("medications"), "MedicationRequest"
    )
    allergies = _extract_resources_from_prefetch(
        prefetch.get("allergies"), "AllergyIntolerance"
    )

    cards = engine.check_all(draft_meds, current_meds, allergies)

    severity_order = {"critical": 0, "warning": 1, "info": 2}
    cards.sort(key=lambda c: severity_order.get(c.get("indicator", "info"), 3))

    if cards:
        max_severity = cards[0]["indicator"]
    else:
        max_severity = "none"

    patient_id = context.get("patientId", "unknown")
    hook_instance = hook_request.get("hookInstance", "unknown")
    _log_decision(patient_id, hook_instance, len(cards), max_severity, request_hash)

    return jsonify({"cards": cards})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
