#!/usr/bin/env python3
"""
FHIR Bundle Anonymizer — HIPAA Safe Harbor compliant.

Reads a FHIR R4 bundle and a FHIRPath anonymization configuration,
applies crypto-hashing, date-shifting, redaction, and postal-code
generalization while maintaining referential integrity.
"""

import json
import hmac
import hashlib
import copy
import re
import os
from datetime import datetime, timedelta, date

# ── Constants ────────────────────────────────────────────────────────────────

REFERENCE_RE = re.compile(r"^([A-Z][a-zA-Z]+)/(.+)$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T")
REFERENCE_DATE = date(2024, 6, 1)

CONTACT_SYSTEMS = {"phone", "fax", "email", "pager", "url", "sms", "other"}

SECURITY_LABELS = [
    {
        "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationValue",
        "code": "REDACTED",
        "display": "redacted",
    },
    {
        "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationValue",
        "code": "CRYPTOHASH",
        "display": "cryptographic hash function",
    },
]

# ── Crypto helpers ───────────────────────────────────────────────────────────


def hmac_sha256(key: str, value: str) -> str:
    return hmac.new(
        key.encode("utf-8"), value.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def compute_date_offset(
    date_shift_key: str, resource_id: str, date_shift_range: int
) -> int:
    h = hmac.new(
        date_shift_key.encode("utf-8"),
        resource_id.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    n = int.from_bytes(h[:4], byteorder="big")
    return (n % (2 * date_shift_range + 1)) - date_shift_range


# ── Date helpers ─────────────────────────────────────────────────────────────


def is_date_value(v) -> bool:
    return isinstance(v, str) and bool(DATE_RE.match(v) or DATETIME_RE.match(v))


def shift_date(date_str: str, offset_days: int) -> str:
    if "T" in date_str:
        parts = date_str.split("T", 1)
        d = datetime.strptime(parts[0], "%Y-%m-%d").date() + timedelta(
            days=offset_days
        )
        return d.isoformat() + "T" + parts[1]
    d = datetime.strptime(date_str, "%Y-%m-%d").date() + timedelta(
        days=offset_days
    )
    return d.isoformat()


def is_elderly(birth_date_str: str) -> bool:
    d = datetime.strptime(birth_date_str[:10], "%Y-%m-%d").date()
    return (REFERENCE_DATE - d).days / 365.25 > 89


# ── Postal code ──────────────────────────────────────────────────────────────


def generalize_postal(postal: str, restricted: set) -> str:
    digits = re.sub(r"[^0-9]", "", postal)
    prefix = digits[:3]
    if prefix in restricted:
        return "00000"
    return prefix + "0" * max(0, 5 - len(prefix))


# ── Tree walkers ─────────────────────────────────────────────────────────────


def walk(
    node: dict,
    crypto_key: str,
    offset: int,
    elderly: bool,
    restricted: set,
):
    if not isinstance(node, dict):
        return
    for key in list(node.keys()):
        if key not in node:
            continue
        val = node[key]

        # ── HumanName ────────────────────────────────────────────────
        if key == "name":
            if isinstance(val, list):
                has_human = any(
                    isinstance(v, dict) and ("family" in v or "given" in v)
                    for v in val
                )
                if has_human:
                    for item in val:
                        if isinstance(item, dict):
                            for f in ("family", "given", "prefix", "suffix", "text"):
                                item.pop(f, None)
                    continue
            elif isinstance(val, dict) and ("family" in val or "given" in val):
                for f in ("family", "given", "prefix", "suffix", "text"):
                    val.pop(f, None)
                continue

        # ── ContactPoint ─────────────────────────────────────────────
        if key == "telecom" and isinstance(val, list):
            for item in val:
                if isinstance(item, dict) and item.get("system") in CONTACT_SYSTEMS:
                    item.pop("value", None)
            continue

        # ── Address ──────────────────────────────────────────────────
        if key == "address":
            addrs = val if isinstance(val, list) else [val]
            for addr in addrs:
                if isinstance(addr, dict) and any(
                    k in addr for k in ("line", "city", "postalCode")
                ):
                    addr.pop("line", None)
                    addr.pop("city", None)
                    addr.pop("district", None)
                    if "postalCode" in addr:
                        addr["postalCode"] = generalize_postal(
                            addr["postalCode"], restricted
                        )
            continue

        # ── Identifier ───────────────────────────────────────────────
        if key == "identifier":
            idents = val if isinstance(val, list) else [val]
            for ident in idents:
                if (
                    isinstance(ident, dict)
                    and "value" in ident
                    and isinstance(ident["value"], str)
                ):
                    ident["value"] = hmac_sha256(crypto_key, ident["value"])
            continue

        # ── Date / dateTime / instant values ─────────────────────────
        if isinstance(val, str) and is_date_value(val):
            if elderly and key == "birthDate":
                del node[key]
            else:
                node[key] = shift_date(val, offset)
            continue

        # ── Recurse ──────────────────────────────────────────────────
        if isinstance(val, dict):
            walk(val, crypto_key, offset, elderly, restricted)
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    walk(item, crypto_key, offset, elderly, restricted)


def update_references(obj, ref_map: dict):
    if isinstance(obj, dict):
        if "reference" in obj and isinstance(obj["reference"], str):
            m = REFERENCE_RE.match(obj["reference"])
            if m:
                res_type, res_id = m.groups()
                if res_id in ref_map:
                    obj["reference"] = f"{res_type}/{ref_map[res_id]}"
            obj.pop("display", None)
        for v in obj.values():
            update_references(v, ref_map)
    elif isinstance(obj, list):
        for item in obj:
            update_references(item, ref_map)


# ── Main pipeline ────────────────────────────────────────────────────────────


def anonymize(bundle_path: str, config_path: str, output_path: str):
    with open(bundle_path) as f:
        bundle = json.load(f)
    with open(config_path) as f:
        config = json.load(f)

    params = config["parameters"]
    crypto_key = params["cryptoHashKey"]
    date_shift_key = params["dateShiftKey"]
    date_shift_range = params.get("dateShiftRange", 50)
    restricted = set(params.get("restrictedZipCodeTabulationAreas", []))

    result = copy.deepcopy(bundle)

    # Phase 1: build old-id -> hashed-id mapping
    ref_map: dict[str, str] = {}
    for entry in result["entry"]:
        r = entry["resource"]
        ref_map[r["id"]] = hmac_sha256(crypto_key, r["id"])

    # Phase 2: process each resource
    for entry in result["entry"]:
        r = entry["resource"]
        original_id = next(
            (old for old, new in ref_map.items() if r["id"] == old), None
        )
        if original_id is None:
            continue

        # Check elderly before any modification
        eld = (
            r["resourceType"] == "Patient"
            and "birthDate" in r
            and is_elderly(r["birthDate"])
        )

        # Hash the resource ID
        r["id"] = ref_map[original_id]

        # Compute date offset from original ID
        offset = compute_date_offset(date_shift_key, original_id, date_shift_range)

        # Remove narrative text
        r.pop("text", None)

        # Walk and anonymize fields
        walk(r, crypto_key, offset, eld, restricted)

        # Add security labels
        if "meta" not in r:
            r["meta"] = {}
        r["meta"]["security"] = list(SECURITY_LABELS)

    # Phase 3: update all references consistently
    update_references(result, ref_map)

    # Write output
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)


if __name__ == "__main__":
    anonymize(
        "/app/data/bundle.json",
        "/app/config.json",
        "/app/output/anonymized.json",
    )
