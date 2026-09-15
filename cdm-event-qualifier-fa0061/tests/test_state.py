
import subprocess
import os
import json
import shutil
import tempfile
import re
import pytest

EVENTS_DIR = "/app/events"

# Expected qualifiers — NOT available in the agent environment
EXPECTED = {
    "evt_3d7a.json": "Novation",
    "evt_9c2f.json": "PartialNovation",
    "evt_5b8e.json": "Allocation",
    "evt_1a4d.json": "ClearedTrade",
    "evt_8e6c.json": "Termination",
    "evt_2f9b.json": "PartialTermination",
    "evt_6d1a.json": "Increase",
    "evt_4c8f.json": "Execution",
    "evt_7a3e.json": "ContractFormation",
    "evt_0e5d.json": "Compression",
}


def build_classpath():
    parts = ["/app/build"]
    lib_dir = "/app/lib"
    if os.path.isdir(lib_dir):
        jars = [f for f in os.listdir(lib_dir) if f.endswith(".jar")]
        if jars:
            parts.append(os.path.join(lib_dir, "*"))
    return ":".join(parts)


def run_qualifier(event_path):
    classpath = build_classpath()
    result = subprocess.run(
        ["java", "-cp", classpath, "cdm.EventQualifier", event_path],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode, result.stdout.strip(), result.stderr


# ==================================================================
# Core classification tests
# ==================================================================

@pytest.mark.parametrize("event_file,expected_qualifier", list(EXPECTED.items()))
def test_event_qualifier(event_file, expected_qualifier):
    """Test that EventQualifier correctly classifies each CDM business event."""
    event_path = os.path.join(EVENTS_DIR, event_file)
    assert os.path.exists(event_path), f"Event file not found: {event_path}"

    rc, actual, stderr = run_qualifier(event_path)

    assert rc == 0, (
        f"EventQualifier failed for {event_file}.\n"
        f"Exit code: {rc}\nStderr: {stderr[:500]}"
    )
    assert actual == expected_qualifier, (
        f"Wrong qualifier for {event_file}.\n"
        f"Expected: {expected_qualifier}\nActual: {actual}"
    )


def test_all_events_present():
    """Verify all expected event files exist."""
    event_files = sorted(
        f for f in os.listdir(EVENTS_DIR)
        if f.startswith("evt_") and f.endswith(".json")
    )
    expected_files = sorted(EXPECTED.keys())
    assert event_files == expected_files


def test_unique_qualifiers():
    """Verify 10 distinct qualifier types are covered."""
    qualifiers = set(EXPECTED.values())
    expected_set = {
        "Novation", "PartialNovation", "Allocation", "ClearedTrade",
        "Termination", "PartialTermination", "Increase",
        "Execution", "ContractFormation", "Compression",
    }
    assert qualifiers == expected_set


# ==================================================================
# Anti-cheat: filename / content independence
# ==================================================================

def test_classifier_content_based():
    """Copy an event to a different filename and verify same result."""
    source_file = "evt_3d7a.json"
    expected = EXPECTED[source_file]
    temp_name = os.path.join(EVENTS_DIR, "tmp_anticheat_probe.json")
    shutil.copy2(os.path.join(EVENTS_DIR, source_file), temp_name)
    try:
        rc, actual, stderr = run_qualifier(temp_name)
        assert rc == 0, f"Classifier failed on renamed file: {stderr[:300]}"
        assert actual == expected, (
            f"Different result for identical content under different filename.\n"
            f"Expected: {expected}, Got: {actual}"
        )
    finally:
        if os.path.exists(temp_name):
            os.remove(temp_name)


def test_no_hardcoded_filenames():
    """Source must not contain hardcoded event filenames."""
    src_path = "/app/src/cdm/EventQualifier.java"
    if not os.path.exists(src_path):
        pytest.skip("Source file not found")
    with open(src_path, "r") as f:
        source = f.read()
    for fname in EXPECTED:
        assert fname not in source, (
            f"Source contains hardcoded filename '{fname}'"
        )


# ==================================================================
# Anti-cheat: no content fingerprinting / hashing
# ==================================================================

def test_no_content_fingerprinting():
    """Source must not use hashing, checksums, or file-size to classify events."""
    src_dir = "/app/src"
    if not os.path.isdir(src_dir):
        pytest.skip("Source directory not found")

    forbidden_patterns = [
        r"MessageDigest",
        r"\.hashCode\s*\(",
        r"MD5|SHA-?1|SHA-?256|SHA-?512",
        r"CRC32|Adler32|Checksum",
        r"Files\.size\s*\(",
        r"\.length\s*\(\s*\)",
        r"file\.length",
        r"contentEquals",
    ]

    for root, _dirs, files in os.walk(src_dir):
        for fname in files:
            if not fname.endswith(".java"):
                continue
            fpath = os.path.join(root, fname)
            with open(fpath, "r") as f:
                source = f.read()
            for pattern in forbidden_patterns:
                matches = re.findall(pattern, source)
                assert not matches, (
                    f"Source file {fpath} contains fingerprinting pattern "
                    f"'{pattern}' (matches: {matches}). "
                    f"Classification must use structural analysis, not content hashing."
                )


def test_no_hardcoded_identifiers():
    """Source must not contain LEI values or trade IDs from the event files."""
    src_path = "/app/src/cdm/EventQualifier.java"
    if not os.path.exists(src_path):
        pytest.skip("Source file not found")
    with open(src_path, "r") as f:
        source = f.read()

    # Identifiers from event files that would indicate hardcoding
    forbidden_ids = [
        "LEI-NOVP001", "LEI-NOVP002", "LEI-NOVP003",
        "LEI-PNV001", "LEI-PNV002", "LEI-PNV003",
        "LEI-ALLOC", "LEI-CLR",
        "LEI-TERM001", "LEI-TERM002",
        "LEI-PT001", "LEI-PT002",
        "LEI-INC001", "LEI-INC002",
        "LEI-EXEC001", "LEI-EXEC002",
        "LEI-CF001", "LEI-CF002",
        "LEI-CMP",
        "NOV-TRADE", "PNV-TRADE", "ALLOC-TRADE", "CLR-TRADE",
        "TERM-TRADE", "PT-TRADE", "INC-TRADE", "EXEC-TRADE",
        "CF-TRADE", "CMP-TRADE",
    ]
    for ident in forbidden_ids:
        assert ident not in source, (
            f"Source contains hardcoded identifier '{ident}' from event files. "
            f"Classification must not be based on specific event data."
        )


# ==================================================================
# Anti-cheat: synthetic events generated at test time
# These events have never existed on disk — they are constructed
# dynamically so a memorizing or hash-based classifier will fail.
# ==================================================================

def _write_temp_event(event_dict):
    """Write a synthetic event to a temp file and return its path."""
    fd, path = tempfile.mkstemp(suffix=".json", prefix="synth_", dir=EVENTS_DIR)
    with os.fdopen(fd, "w") as f:
        json.dump(event_dict, f, indent=2)
    return path


def test_synthetic_execution():
    """Classify a brand-new Execution event generated at test time."""
    event = {
        "@type": "cdm.event.common.BusinessEvent",
        "eventDate": "2025-09-12",
        "instruction": [{
            "primitiveInstruction": {
                "execution": {
                    "product": {
                        "taxonomy": [{"primaryAssetClass": {"@data": "Credit"}}],
                        "economicTerms": {
                            "payout": [{"@type": "cdm.product.asset.CreditDefaultPayout",
                                        "payerReceiver": {"payer": "Party1", "receiver": "Party2"}}],
                            "nonStandardisedTerms": False
                        }
                    },
                    "priceQuantity": [{"quantity": [{"value": 15000000.0,
                                                     "unit": {"currency": {"@data": "CHF"}}}]}],
                    "counterparty": [
                        {"role": "Party1", "partyReference": {"@ref:external": "synthA"}},
                        {"role": "Party2", "partyReference": {"@ref:external": "synthB"}}
                    ],
                    "parties": [
                        {"@key:external": "synthA",
                         "partyId": [{"identifier": {"@data": "LEI-SYNEX001"}, "identifierType": "LEI"}],
                         "name": {"@data": "Zurich Trading AG"}},
                        {"@key:external": "synthB",
                         "partyId": [{"identifier": {"@data": "LEI-SYNEX002"}, "identifierType": "LEI"}],
                         "name": {"@data": "Geneva Capital SA"}}
                    ],
                    "executionDetails": {"executionType": "Electronic"},
                    "tradeDate": "2025-09-12",
                    "tradeIdentifier": [{"issuer": {"@data": "LEI-SYNEX001"},
                                         "assignedIdentifier": [{"identifier": {"@data": "SYNEX-001"}}],
                                         "identifierType": "UniqueTransactionIdentifier"}]
                }
            }
        }],
        "after": [{
            "trade": {
                "product": {
                    "taxonomy": [{"primaryAssetClass": {"@data": "Credit"}}],
                    "economicTerms": {
                        "payout": [{"@type": "cdm.product.asset.CreditDefaultPayout",
                                    "payerReceiver": {"payer": "Party1", "receiver": "Party2"}}],
                        "nonStandardisedTerms": False
                    }
                },
                "tradeLot": [{"priceQuantity": [{"quantity": [{"value": 15000000.0,
                                                               "unit": {"currency": {"@data": "CHF"}}}]}]}],
                "counterparty": [
                    {"role": "Party1", "partyReference": {"@ref:external": "synthA"}},
                    {"role": "Party2", "partyReference": {"@ref:external": "synthB"}}
                ],
                "tradeDate": {"@data": "2025-09-12"},
                "party": [
                    {"@key:external": "synthA",
                     "partyId": [{"identifier": {"@data": "LEI-SYNEX001"}, "identifierType": "LEI"}],
                     "name": {"@data": "Zurich Trading AG"}},
                    {"@key:external": "synthB",
                     "partyId": [{"identifier": {"@data": "LEI-SYNEX002"}, "identifierType": "LEI"}],
                     "name": {"@data": "Geneva Capital SA"}}
                ]
            }
        }]
    }
    path = _write_temp_event(event)
    try:
        rc, actual, stderr = run_qualifier(path)
        assert rc == 0, f"Synthetic execution failed: {stderr[:300]}"
        assert actual == "Execution", f"Expected Execution, got: {actual}"
    finally:
        os.remove(path)


def test_synthetic_termination():
    """Classify a brand-new Termination event generated at test time."""
    event = {
        "@type": "cdm.event.common.BusinessEvent",
        "eventDate": "2025-11-20",
        "instruction": [{
            "primitiveInstruction": {
                "quantityChange": {
                    "change": [{"quantity": [{"value": 0.0, "unit": {"currency": {"@data": "EUR"}}}]}],
                    "direction": "Replace"
                }
            },
            "before": {
                "trade": {
                    "product": {
                        "taxonomy": [{"primaryAssetClass": {"@data": "Credit"}}],
                        "economicTerms": {
                            "payout": [{"@type": "cdm.product.asset.CreditDefaultPayout",
                                        "payerReceiver": {"payer": "Party1", "receiver": "Party2"}}],
                            "nonStandardisedTerms": False
                        }
                    },
                    "tradeLot": [{"priceQuantity": [{"quantity": [{"value": 42000000.0,
                                                                   "unit": {"currency": {"@data": "EUR"}}}]}]}],
                    "counterparty": [
                        {"role": "Party1", "partyReference": {"@ref:external": "trmX"}},
                        {"role": "Party2", "partyReference": {"@ref:external": "trmY"}}
                    ],
                    "tradeIdentifier": [{"issuer": {"@data": "LEI-SYNTERM01"},
                                         "assignedIdentifier": [{"identifier": {"@data": "SYNTERM-001"}}],
                                         "identifierType": "UniqueTransactionIdentifier"}],
                    "tradeDate": {"@data": "2025-01-10"},
                    "party": [
                        {"@key:external": "trmX",
                         "partyId": [{"identifier": {"@data": "LEI-SYNTERM01"}, "identifierType": "LEI"}],
                         "name": {"@data": "Terminus GmbH"}},
                        {"@key:external": "trmY",
                         "partyId": [{"identifier": {"@data": "LEI-SYNTERM02"}, "identifierType": "LEI"}],
                         "name": {"@data": "Finalis SA"}}
                    ]
                }
            }
        }],
        "after": [{
            "trade": {
                "product": {
                    "taxonomy": [{"primaryAssetClass": {"@data": "Credit"}}],
                    "economicTerms": {
                        "payout": [{"@type": "cdm.product.asset.CreditDefaultPayout",
                                    "payerReceiver": {"payer": "Party1", "receiver": "Party2"}}],
                        "nonStandardisedTerms": False
                    }
                },
                "tradeLot": [{"priceQuantity": [{"quantity": [{"value": 0.0,
                                                               "unit": {"currency": {"@data": "EUR"}}}]}]}],
                "counterparty": [
                    {"role": "Party1", "partyReference": {"@ref:external": "trmX"}},
                    {"role": "Party2", "partyReference": {"@ref:external": "trmY"}}
                ],
                "tradeIdentifier": [{"issuer": {"@data": "LEI-SYNTERM01"},
                                     "assignedIdentifier": [{"identifier": {"@data": "SYNTERM-001"}}],
                                     "identifierType": "UniqueTransactionIdentifier"}],
                "tradeDate": {"@data": "2025-01-10"},
                "party": [
                    {"@key:external": "trmX",
                     "partyId": [{"identifier": {"@data": "LEI-SYNTERM01"}, "identifierType": "LEI"}],
                     "name": {"@data": "Terminus GmbH"}},
                    {"@key:external": "trmY",
                     "partyId": [{"identifier": {"@data": "LEI-SYNTERM02"}, "identifierType": "LEI"}],
                     "name": {"@data": "Finalis SA"}}
                ]
            },
            "state": {
                "closedState": {"state": "Terminated"},
                "positionState": "Closed"
            }
        }]
    }
    path = _write_temp_event(event)
    try:
        rc, actual, stderr = run_qualifier(path)
        assert rc == 0, f"Synthetic termination failed: {stderr[:300]}"
        assert actual == "Termination", f"Expected Termination, got: {actual}"
    finally:
        os.remove(path)


def test_synthetic_increase():
    """Classify a brand-new Increase event generated at test time."""
    event = {
        "@type": "cdm.event.common.BusinessEvent",
        "eventDate": "2025-07-05",
        "instruction": [{
            "primitiveInstruction": {
                "quantityChange": {
                    "change": [{"quantity": [{"value": 90000000.0,
                                             "unit": {"currency": {"@data": "JPY"}}}]}],
                    "direction": "Replace"
                }
            },
            "before": {
                "trade": {
                    "product": {
                        "taxonomy": [{"primaryAssetClass": {"@data": "Equity"}}],
                        "economicTerms": {
                            "payout": [{"@type": "cdm.product.asset.EquityPayout",
                                        "payerReceiver": {"payer": "Party1", "receiver": "Party2"}}],
                            "nonStandardisedTerms": False
                        }
                    },
                    "tradeLot": [{"priceQuantity": [{"quantity": [{"value": 55000000.0,
                                                                   "unit": {"currency": {"@data": "JPY"}}}]}]}],
                    "counterparty": [
                        {"role": "Party1", "partyReference": {"@ref:external": "incM"}},
                        {"role": "Party2", "partyReference": {"@ref:external": "incN"}}
                    ],
                    "tradeIdentifier": [{"issuer": {"@data": "LEI-SYNINC01"},
                                         "assignedIdentifier": [{"identifier": {"@data": "SYNINC-001"}}],
                                         "identifierType": "UniqueTransactionIdentifier"}],
                    "tradeDate": {"@data": "2025-02-15"},
                    "party": [
                        {"@key:external": "incM",
                         "partyId": [{"identifier": {"@data": "LEI-SYNINC01"}, "identifierType": "LEI"}],
                         "name": {"@data": "Growth Securities"}},
                        {"@key:external": "incN",
                         "partyId": [{"identifier": {"@data": "LEI-SYNINC02"}, "identifierType": "LEI"}],
                         "name": {"@data": "Expand Capital"}}
                    ]
                }
            }
        }],
        "after": [{
            "trade": {
                "product": {
                    "taxonomy": [{"primaryAssetClass": {"@data": "Equity"}}],
                    "economicTerms": {
                        "payout": [{"@type": "cdm.product.asset.EquityPayout",
                                    "payerReceiver": {"payer": "Party1", "receiver": "Party2"}}],
                        "nonStandardisedTerms": False
                    }
                },
                "tradeLot": [{"priceQuantity": [{"quantity": [{"value": 90000000.0,
                                                               "unit": {"currency": {"@data": "JPY"}}}]}]}],
                "counterparty": [
                    {"role": "Party1", "partyReference": {"@ref:external": "incM"}},
                    {"role": "Party2", "partyReference": {"@ref:external": "incN"}}
                ],
                "tradeIdentifier": [{"issuer": {"@data": "LEI-SYNINC01"},
                                     "assignedIdentifier": [{"identifier": {"@data": "SYNINC-001"}}],
                                     "identifierType": "UniqueTransactionIdentifier"}],
                "tradeDate": {"@data": "2025-02-15"},
                "party": [
                    {"@key:external": "incM",
                     "partyId": [{"identifier": {"@data": "LEI-SYNINC01"}, "identifierType": "LEI"}],
                     "name": {"@data": "Growth Securities"}},
                    {"@key:external": "incN",
                     "partyId": [{"identifier": {"@data": "LEI-SYNINC02"}, "identifierType": "LEI"}],
                     "name": {"@data": "Expand Capital"}}
                ]
            }
        }]
    }
    path = _write_temp_event(event)
    try:
        rc, actual, stderr = run_qualifier(path)
        assert rc == 0, f"Synthetic increase failed: {stderr[:300]}"
        assert actual == "Increase", f"Expected Increase, got: {actual}"
    finally:
        os.remove(path)


def test_synthetic_contract_formation():
    """Classify a brand-new ContractFormation event generated at test time."""
    event = {
        "@type": "cdm.event.common.BusinessEvent",
        "eventDate": "2025-08-22",
        "instruction": [{
            "primitiveInstruction": {
                "contractFormation": {
                    "legalAgreement": [{
                        "agreementDate": "2025-08-22",
                        "legalAgreementIdentification": {
                            "agreementName": {"masterAgreementType": {"@data": "ISDAMaster"}},
                            "vintage": 2002
                        }
                    }]
                }
            },
            "before": None
        }],
        "after": [{
            "trade": {
                "product": {
                    "taxonomy": [{"primaryAssetClass": {"@data": "Commodity"}}],
                    "economicTerms": {
                        "payout": [{"@type": "cdm.product.asset.CommodityPayout",
                                    "payerReceiver": {"payer": "Party1", "receiver": "Party2"}}],
                        "nonStandardisedTerms": False
                    }
                },
                "tradeLot": [{"priceQuantity": [{"quantity": [{"value": 5000000.0,
                                                               "unit": {"currency": {"@data": "AUD"}}}]}]}],
                "counterparty": [
                    {"role": "Party1", "partyReference": {"@ref:external": "cfX"}},
                    {"role": "Party2", "partyReference": {"@ref:external": "cfY"}}
                ],
                "tradeIdentifier": [{"issuer": {"@data": "LEI-SYNCF01"},
                                     "assignedIdentifier": [{"identifier": {"@data": "SYNCF-001"}}],
                                     "identifierType": "UniqueTransactionIdentifier"}],
                "tradeDate": {"@data": "2025-08-22"},
                "party": [
                    {"@key:external": "cfX",
                     "partyId": [{"identifier": {"@data": "LEI-SYNCF01"}, "identifierType": "LEI"}],
                     "name": {"@data": "Pacific Resources Ltd"}},
                    {"@key:external": "cfY",
                     "partyId": [{"identifier": {"@data": "LEI-SYNCF02"}, "identifierType": "LEI"}],
                     "name": {"@data": "Meridian Partners Pty"}}
                ]
            }
        }]
    }
    path = _write_temp_event(event)
    try:
        rc, actual, stderr = run_qualifier(path)
        assert rc == 0, f"Synthetic contract formation failed: {stderr[:300]}"
        assert actual == "ContractFormation", f"Expected ContractFormation, got: {actual}"
    finally:
        os.remove(path)


def test_mutated_termination():
    """Mutate an existing Termination event (change all identifiers/amounts)
    and verify the classifier still produces 'Termination'.

    This defeats hash-based or content-memorizing classifiers.
    """
    event = {
        "@type": "cdm.event.common.BusinessEvent",
        "eventDate": "2026-01-30",
        "instruction": [{
            "primitiveInstruction": {
                "quantityChange": {
                    "change": [{"quantity": [{"value": 0.0, "unit": {"currency": {"@data": "SGD"}}}]}],
                    "direction": "Replace"
                }
            },
            "before": {
                "trade": {
                    "product": {
                        "taxonomy": [{"primaryAssetClass": {"@data": "ForeignExchange"}},
                                     {"source": "ISDA",
                                      "value": {"name": {"@data": "ForeignExchange_NDF"}},
                                      "calculated": True}],
                        "economicTerms": {
                            "payout": [
                                {"@type": "cdm.product.asset.ForeignExchangePayout",
                                 "payerReceiver": {"payer": "Party1", "receiver": "Party2"},
                                 "dayCountFraction": {"@data": "ACT/365.FIXED"}},
                            ],
                            "nonStandardisedTerms": False
                        }
                    },
                    "tradeLot": [{"priceQuantity": [
                        {"quantity": [{"value": 200000000.0,
                                       "unit": {"currency": {"@data": "SGD"}}}]},
                        {"price": [{"value": 0.74,
                                    "unit": {"currency": {"@data": "SGD"}},
                                    "perUnitOf": {"currency": {"@data": "USD"}},
                                    "priceType": "ExchangeRate"}],
                         "quantity": [{"value": 200000000.0,
                                       "unit": {"currency": {"@data": "SGD"}}}]}
                    ]}],
                    "counterparty": [
                        {"role": "Party1", "partyReference": {"@ref:external": "mutA"}},
                        {"role": "Party2", "partyReference": {"@ref:external": "mutB"}}
                    ],
                    "tradeIdentifier": [
                        {"issuer": {"@data": "LEI-MUTTERM01"},
                         "assignedIdentifier": [{"identifier": {"@data": "MUT-TERM-777"}}],
                         "identifierType": "UniqueTransactionIdentifier"}
                    ],
                    "tradeDate": {"@data": "2025-06-01"},
                    "party": [
                        {"@key:external": "mutA",
                         "partyId": [{"identifier": {"@data": "LEI-MUTTERM01"},
                                      "identifierType": "LEI"}],
                         "name": {"@data": "Singapore Capital Pte"}},
                        {"@key:external": "mutB",
                         "partyId": [{"identifier": {"@data": "LEI-MUTTERM02"},
                                      "identifierType": "LEI"}],
                         "name": {"@data": "ASEAN Markets Ltd"}}
                    ]
                }
            }
        }],
        "after": [{
            "trade": {
                "product": {
                    "taxonomy": [{"primaryAssetClass": {"@data": "ForeignExchange"}},
                                 {"source": "ISDA",
                                  "value": {"name": {"@data": "ForeignExchange_NDF"}},
                                  "calculated": True}],
                    "economicTerms": {
                        "payout": [
                            {"@type": "cdm.product.asset.ForeignExchangePayout",
                             "payerReceiver": {"payer": "Party1", "receiver": "Party2"},
                             "dayCountFraction": {"@data": "ACT/365.FIXED"}},
                        ],
                        "nonStandardisedTerms": False
                    }
                },
                "tradeLot": [{"priceQuantity": [
                    {"quantity": [{"value": 0.0,
                                   "unit": {"currency": {"@data": "SGD"}}}]},
                    {"price": [{"value": 0.74,
                                "unit": {"currency": {"@data": "SGD"}},
                                "perUnitOf": {"currency": {"@data": "USD"}},
                                "priceType": "ExchangeRate"}],
                     "quantity": [{"value": 0.0,
                                   "unit": {"currency": {"@data": "SGD"}}}]}
                ]}],
                "counterparty": [
                    {"role": "Party1", "partyReference": {"@ref:external": "mutA"}},
                    {"role": "Party2", "partyReference": {"@ref:external": "mutB"}}
                ],
                "tradeIdentifier": [
                    {"issuer": {"@data": "LEI-MUTTERM01"},
                     "assignedIdentifier": [{"identifier": {"@data": "MUT-TERM-777"}}],
                     "identifierType": "UniqueTransactionIdentifier"}
                ],
                "tradeDate": {"@data": "2025-06-01"},
                "party": [
                    {"@key:external": "mutA",
                     "partyId": [{"identifier": {"@data": "LEI-MUTTERM01"},
                                  "identifierType": "LEI"}],
                     "name": {"@data": "Singapore Capital Pte"}},
                    {"@key:external": "mutB",
                     "partyId": [{"identifier": {"@data": "LEI-MUTTERM02"},
                                  "identifierType": "LEI"}],
                     "name": {"@data": "ASEAN Markets Ltd"}}
                ]
            },
            "state": {
                "closedState": {"state": "Terminated"},
                "positionState": "Closed"
            }
        }]
    }
    path = _write_temp_event(event)
    try:
        rc, actual, stderr = run_qualifier(path)
        assert rc == 0, f"Mutated termination failed: {stderr[:300]}"
        assert actual == "Termination", f"Expected Termination, got: {actual}"
    finally:
        os.remove(path)
