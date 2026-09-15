#!/usr/bin/env python3
"""
Initialize task environment: generate cryptographic keys, instance-specific
deployment configuration (DNA), and FHIR R4 resources for bulk export.

Every run produces unique instance_id, token_issuer, custom_header name,
assertion lifetime, token lifetime, and FHIR resource IDs — the solver
MUST read these from /app/config/ at runtime.

Writes to /opt/task-data/ during Docker build; files are copied to /app/
afterward and restored at runtime if needed.
"""
import json
import os
import uuid
import random
import base64
from cryptography.hazmat.primitives.asymmetric import ec, rsa


BASE = '/opt/task-data'


def b64url(n, length):
    return base64.urlsafe_b64encode(n.to_bytes(length, 'big')).rstrip(b'=').decode()


def int_to_b64url(n):
    byte_len = max((n.bit_length() + 7) // 8, 1)
    return base64.urlsafe_b64encode(n.to_bytes(byte_len, 'big')).rstrip(b'=').decode()


def generate_ec_p384_keypair(kid):
    key = ec.generate_private_key(ec.SECP384R1())
    pub = key.public_key().public_numbers()
    priv = key.private_numbers()
    cs = 48
    public_jwk = {
        "kty": "EC", "crv": "P-384",
        "x": b64url(pub.x, cs), "y": b64url(pub.y, cs),
        "kid": kid, "use": "sig", "alg": "ES384"
    }
    private_jwk = {**public_jwk, "d": b64url(priv.private_value, cs)}
    return private_jwk, public_jwk


def generate_rsa_keypair(kid):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = key.public_key().public_numbers()
    priv = key.private_numbers()
    public_jwk = {
        "kty": "RSA", "kid": kid, "use": "sig", "alg": "RS256",
        "n": int_to_b64url(pub.n), "e": int_to_b64url(pub.e),
    }
    private_jwk = {
        **public_jwk,
        "d": int_to_b64url(priv.d),
        "p": int_to_b64url(priv.p), "q": int_to_b64url(priv.q),
        "dp": int_to_b64url(priv.dmp1), "dq": int_to_b64url(priv.dmq1),
        "qi": int_to_b64url(priv.iqmp),
    }
    return private_jwk, public_jwk


def main():
    random.seed()

    # ── DNA: instance-specific deployment configuration ────────────────
    instance_id = str(uuid.uuid4())
    deploy_hex = uuid.uuid4().hex[:12]
    token_issuer = f"smart-fhir-{deploy_hex}"
    custom_header_name = f"X-Deployment-{deploy_hex[:8].upper()}"
    max_assertion_lifetime = random.choice([150, 165, 180, 195, 210])
    access_token_lifetime = random.choice([600, 900, 1200, 1800])

    instance_config = {
        "instance_id": instance_id,
        "token_issuer": token_issuer,
        "custom_header": custom_header_name,
        "max_assertion_lifetime_sec": max_assertion_lifetime,
        "access_token_lifetime_sec": access_token_lifetime,
    }

    # ── Cryptographic keys ─────────────────────────────────────────────
    client_private, client_public = generate_ec_p384_keypair("test-client-key-1")
    server_private, server_public = generate_rsa_keypair("server-key-1")

    # ── Registered clients ─────────────────────────────────────────────
    registered_clients = {
        "token_endpoint": "http://localhost:8080/auth/token",
        "clients": {
            "test-backend-service": {
                "client_id": "test-backend-service",
                "allowed_scopes": [
                    "system/Patient.read",
                    "system/Observation.read",
                    "system/Condition.read",
                    "system/AllergyIntolerance.read",
                ],
                "jwks": {"keys": [client_public]},
            }
        }
    }

    # ── DNA: FHIR resources with instance-unique IDs ───────────────────
    uid = instance_id[:8]

    patients = [
        {
            "resourceType": "Patient", "id": f"patient-{uid}-1",
            "meta": {"profile": ["http://hl7.org/fhir/us/core/StructureDefinition/us-core-patient"]},
            "identifier": [{"system": "urn:oid:2.16.840.1.113883.4.3.25",
                            "value": uuid.uuid4().hex[:10].upper()}],
            "name": [{"use": "official", "family": "Whitford", "given": ["Aria"]}],
            "gender": "female", "birthDate": "1987-03-14",
        },
        {
            "resourceType": "Patient", "id": f"patient-{uid}-2",
            "meta": {"profile": ["http://hl7.org/fhir/us/core/StructureDefinition/us-core-patient"]},
            "identifier": [{"system": "urn:oid:2.16.840.1.113883.4.3.25",
                            "value": uuid.uuid4().hex[:10].upper()}],
            "name": [{"use": "official", "family": "Tanaka", "given": ["Declan"]}],
            "gender": "male", "birthDate": "1955-11-28",
        },
        {
            "resourceType": "Patient", "id": f"patient-{uid}-3",
            "meta": {"profile": ["http://hl7.org/fhir/us/core/StructureDefinition/us-core-patient"]},
            "identifier": [{"system": "urn:oid:2.16.840.1.113883.4.3.25",
                            "value": uuid.uuid4().hex[:10].upper()}],
            "name": [{"use": "official", "family": "Okafor", "given": ["Solenne"]}],
            "gender": "female", "birthDate": "2001-07-09",
        },
    ]

    obs_codes = [
        ("8480-6", "Systolic blood pressure", "mmHg", "mm[Hg]"),
        ("8462-4", "Diastolic blood pressure", "mmHg", "mm[Hg]"),
        ("8867-4", "Heart rate", "/min", "/min"),
        ("2708-6", "Oxygen saturation", "%", "%"),
        ("8310-5", "Body temperature", "Cel", "Cel"),
        ("29463-7", "Body weight", "kg", "kg"),
        ("39156-5", "BMI", "kg/m2", "kg/m2"),
    ]
    observations = []
    oc = 1
    for i, pat in enumerate(patients):
        num_obs = 2 + (i % 2)  # 2, 3, 2 observations per patient
        for j in range(num_obs):
            code = obs_codes[(i * 3 + j) % len(obs_codes)]
            observations.append({
                "resourceType": "Observation", "id": f"obs-{uid}-{oc}",
                "status": "final",
                "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                           "code": "vital-signs", "display": "Vital Signs"}]}],
                "code": {"coding": [{"system": "http://loinc.org", "code": code[0], "display": code[1]}]},
                "subject": {"reference": f"Patient/{pat['id']}"},
                "valueQuantity": {"value": round(random.uniform(60, 180), 1),
                                  "unit": code[2], "system": "http://unitsofmeasure.org", "code": code[3]},
            })
            oc += 1

    conditions = [
        {
            "resourceType": "Condition", "id": f"cond-{uid}-1",
            "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                                            "code": "active"}]},
            "verificationStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                                                "code": "confirmed"}]},
            "code": {"coding": [{"system": "http://snomed.info/sct", "code": "38341003",
                                  "display": "Hypertensive disorder"}]},
            "subject": {"reference": f"Patient/{patients[0]['id']}"},
        },
        {
            "resourceType": "Condition", "id": f"cond-{uid}-2",
            "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                                            "code": "active"}]},
            "verificationStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                                                "code": "confirmed"}]},
            "code": {"coding": [{"system": "http://snomed.info/sct", "code": "44054006",
                                  "display": "Diabetes mellitus type 2"}]},
            "subject": {"reference": f"Patient/{patients[1]['id']}"},
        },
        {
            "resourceType": "Condition", "id": f"cond-{uid}-3",
            "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                                            "code": "active"}]},
            "verificationStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                                                "code": "confirmed"}]},
            "code": {"coding": [{"system": "http://snomed.info/sct", "code": "195967001",
                                  "display": "Asthma"}]},
            "subject": {"reference": f"Patient/{patients[2]['id']}"},
        },
    ]

    allergies = [
        {
            "resourceType": "AllergyIntolerance", "id": f"allergy-{uid}-1",
            "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
                                            "code": "active"}]},
            "type": "allergy", "category": ["medication"],
            "code": {"coding": [{"system": "http://snomed.info/sct", "code": "293586001",
                                  "display": "Penicillin allergy"}]},
            "patient": {"reference": f"Patient/{patients[0]['id']}"},
        },
        {
            "resourceType": "AllergyIntolerance", "id": f"allergy-{uid}-2",
            "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
                                            "code": "active"}]},
            "type": "allergy", "category": ["environment"],
            "code": {"coding": [{"system": "http://snomed.info/sct", "code": "418689008",
                                  "display": "Allergy to grass pollen"}]},
            "patient": {"reference": f"Patient/{patients[1]['id']}"},
        },
    ]

    group = {
        "resourceType": "Group", "id": "1",
        "type": "person", "actual": True,
        "member": [{"entity": {"reference": f"Patient/{p['id']}"}} for p in patients],
    }

    # ── Write everything to disk ───────────────────────────────────────
    dirs = [
        f'{BASE}/config',
        f'{BASE}/data/fhir/Patient', f'{BASE}/data/fhir/Observation',
        f'{BASE}/data/fhir/Condition', f'{BASE}/data/fhir/AllergyIntolerance',
        f'{BASE}/data/fhir/Group',
    ]
    for d in dirs:
        os.makedirs(d, exist_ok=True)

    for path, data in [
        (f'{BASE}/config/instance.json', instance_config),
        (f'{BASE}/config/test_client_private_jwk.json', client_private),
        (f'{BASE}/config/server_private_jwk.json', server_private),
        (f'{BASE}/config/server_jwks.json', {"keys": [server_public]}),
        (f'{BASE}/config/registered_clients.json', registered_clients),
    ]:
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)

    all_resources = [
        ("Patient", patients), ("Observation", observations),
        ("Condition", conditions), ("AllergyIntolerance", allergies),
        ("Group", [group]),
    ]
    for rtype, resources in all_resources:
        for r in resources:
            with open(f'{BASE}/data/fhir/{rtype}/{r["id"]}.json', 'w') as f:
                json.dump(r, f, indent=2)

    # Resource manifest for test verification
    manifest = {
        "Patient": [p["id"] for p in patients],
        "Observation": [o["id"] for o in observations],
        "Condition": [c["id"] for c in conditions],
        "AllergyIntolerance": [a["id"] for a in allergies],
        "total_resources": len(patients) + len(observations) + len(conditions) + len(allergies),
    }
    with open(f'{BASE}/config/resource_manifest.json', 'w') as f:
        json.dump(manifest, f, indent=2)

    print(f"Instance {instance_id} initialized")
    print(f"  issuer={token_issuer}  header={custom_header_name}")
    print(f"  max_assertion={max_assertion_lifetime}s  token_ttl={access_token_lifetime}s")
    print(f"  resources: {manifest['total_resources']} total "
          f"({len(patients)}P {len(observations)}O {len(conditions)}C {len(allergies)}A)")


if __name__ == '__main__':
    main()
