#!/usr/bin/env python3
"""Write the FHIRPath anonymization configuration."""
import json

config = {
    "fhirVersion": "R4",
    "processingErrors": "raise",
    "fhirPathRules": [
        # Extensions contain unpredictable PHI — redact first
        {"path": "nodesByType('Extension')", "method": "redact"},

        # Keep rules — must precede catch-all redact/transform rules
        {"path": "Organization.identifier", "method": "keep"},
        {"path": "Organization.name", "method": "keep"},
        {"path": "Organization.telecom", "method": "keep"},
        {"path": "nodesByType('HumanName').use", "method": "keep"},
        {"path": "nodesByType('Address').country", "method": "keep"},
        {"path": "nodesByType('Address').state", "method": "keep"},

        # CryptoHash — deterministic pseudonymization
        {"path": "Resource.id", "method": "cryptoHash"},
        {"path": "nodesByType('Reference').reference", "method": "cryptoHash"},
        {"path": "nodesByType('Identifier').value", "method": "cryptoHash"},

        # Redact reference display text (PHI leakage vector)
        {"path": "nodesByType('Reference').display", "method": "redact"},
        {"path": "Bundle.entry.fullUrl", "method": "redact"},

        # Redact PHI-bearing complex types
        {"path": "nodesByType('Narrative')", "method": "redact"},
        {"path": "nodesByType('HumanName')", "method": "redact"},
        {"path": "nodesByType('ContactPoint')", "method": "redact"},
        {"path": "nodesByType('Address')", "method": "redact"},

        # DateShift — temporal types
        {"path": "nodesByType('date')", "method": "dateShift"},
        {"path": "nodesByType('dateTime')", "method": "dateShift"},
        {"path": "nodesByType('instant')", "method": "dateShift"},
    ],
    "parameters": {
        "cryptoHashKey": "hipaa-safe-harbor-2024",
        "dateShiftKey": "date-shift-key-2024",
        "dateShiftRange": 50,
        "dateShiftScope": "resource",
        "enablePartialAgesForRedact": True,
        "enablePartialDatesForRedact": False,
        "enablePartialZipCodesForRedact": True,
        "restrictedZipCodeTabulationAreas": [
            "036", "059", "063", "102", "203", "556", "692",
            "790", "821", "823", "830", "831", "878", "879",
            "884", "890", "893"
        ]
    }
}

with open("/app/config.json", "w") as f:
    json.dump(config, f, indent=2)

print("Wrote /app/config.json")
