
"""
ESVTS Mock Server

Flask-based mock of the NIST Entropy Source Validation Test System.
Implements mTLS, TOTP login, JWT auth, and validation-backed registration.
"""

import ssl
import sys
import os
import datetime
import json

sys.path.insert(0, "/app")

from flask import Flask, request, jsonify
from esvts_auth import generate_totp, verify_totp, create_jwt, verify_jwt
from vsf_engine import VsfEngine

app = Flask(__name__)

# --- Configuration ---
TOTP_SEED = bytes.fromhex(open("/app/totp_seed.txt").read().strip())
JWT_SECRET = open("/app/jwt_secret.txt").read().strip()
ESV_VERSION = "1.0"

# --- Validation engine ---
TREE_PATH = "/app/vsf_config/ValidationTrees/RegisterRequest/registerEntropySource.json"
RULES_DIR = "/app/vsf_config/RuleScripts"
engine = VsfEngine(RULES_DIR)

# --- In-memory storage ---
assessments = {}
_next_ea_id = 1
_next_df_id = 100


# ===========================================================
# Field name mapping: camelCase protocol -> PascalCase validation
# ===========================================================

_TOP_MAP = {
    "primaryNoiseSource": "PrimaryNoiseSource",
    "iidClaim": "IidClaim",
    "bitsPerSample": "BitsPerSample",
    "hminEstimate": "HMinEstimate",
    "physical": "IsPhysical",
    "numberOfRestarts": "NumberOfRestarts",
    "samplesPerRestart": "SamplesPerRestart",
    "additionalNoiseSources": "AdditionalNoiseSources",
    "conditioningComponent": "ConditioningComponents",
    "metadata": "Metadata",
}

_CC_MAP = {
    "sequencePosition": "SequencePosition",
    "vetted": "IsVetted",
    "bijectiveClaim": "IsBijectiveClaim",
    "description": "Description",
    "validationNumber": "ValidationNumber",
    "minNin": "MinNIn",
    "nOut": "NOut",
    "hOut": "HOut",
}


def _map_to_pascal(payload):
    """Convert protocol camelCase payload to PascalCase for validation."""
    result = {}
    for k, v in payload.items():
        if k == "numberOfOEs":
            continue  # handled separately
        new_key = _TOP_MAP.get(k, k)
        if k == "conditioningComponent" and isinstance(v, list):
            result[new_key] = [
                {_CC_MAP.get(ck, ck): cv for ck, cv in cc.items()} for cc in v
            ]
        else:
            result[new_key] = v

    # Generate OperatingEnvironmentIds from numberOfOEs (default 1)
    if "OperatingEnvironmentIds" not in result:
        n_oes = payload.get("numberOfOEs", 1)
        result["OperatingEnvironmentIds"] = list(range(1, n_oes + 1))

    # Ensure Metadata is present (defaults to None)
    if "Metadata" not in result:
        result["Metadata"] = None

    return result


# ===========================================================
# Middleware helper
# ===========================================================

def _check_bearer():
    """Extract and verify Bearer JWT. Returns (claims, error_response)."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None, (jsonify([{"esvVersion": ESV_VERSION},
                               {"error": "Missing authorization"}]), 401)
    token = auth[7:]
    claims = verify_jwt(token, JWT_SECRET)
    if claims is None:
        return None, (jsonify([{"esvVersion": ESV_VERSION},
                               {"error": "Invalid or expired token"}]), 401)
    return claims, None


# ===========================================================
# Endpoints
# ===========================================================

@app.route("/esv/v1/login", methods=["POST"])
def login():
    data = request.get_json(silent=True)
    if not data or len(data) < 2:
        return jsonify([{"esvVersion": ESV_VERSION},
                        {"error": "Invalid request"}]), 400

    password = data[1].get("password", "")
    if not verify_totp(TOTP_SEED, password):
        return jsonify([{"esvVersion": ESV_VERSION},
                        {"error": "Invalid TOTP"}]), 403

    claims = {"userId": 1, "type": "session"}
    token = create_jwt(claims, JWT_SECRET)
    return jsonify([{"esvVersion": ESV_VERSION}, {"accessToken": token}])


@app.route("/esv/v1/entropyAssessments", methods=["POST"])
def register_entropy():
    global _next_ea_id, _next_df_id

    user_claims, err = _check_bearer()
    if err:
        return err

    data = request.get_json(silent=True)
    if not data or len(data) < 2:
        return jsonify([{"esvVersion": ESV_VERSION},
                        {"error": "Invalid request"}]), 400

    payload = data[1]

    # Map to PascalCase and validate
    mapped = _map_to_pascal(payload)
    result = engine.validate(TREE_PATH, mapped)

    if not result.passed:
        errors = [{"propertyPath": e.property_path, "ruleText": e.rule_text}
                  for e in result.errors]
        return jsonify([{"esvVersion": ESV_VERSION},
                        {"error": "Validation failed", "details": errors}]), 400

    ea_id = _next_ea_id
    _next_ea_id += 1

    # Build data file URLs
    data_file_urls = []
    raw_id = _next_df_id; _next_df_id += 1
    restart_id = _next_df_id; _next_df_id += 1
    data_file_urls.append(
        {"rawNoiseBits": f"/esv/v1/entropyAssessments/{ea_id}/dataFiles/{raw_id}"})
    data_file_urls.append(
        {"restartTestBits": f"/esv/v1/entropyAssessments/{ea_id}/dataFiles/{restart_id}"})

    for cc in payload.get("conditioningComponent", []):
        if not cc.get("vetted", False) and not cc.get("bijectiveClaim", False):
            df_id = _next_df_id; _next_df_id += 1
            data_file_urls.append({
                "conditionedBits": f"/esv/v1/entropyAssessments/{ea_id}/dataFiles/{df_id}",
                "sequencePosition": cc.get("sequencePosition", 1),
            })

    # Assessment JWT with eaId claim
    ea_claims = {"userId": 1, "eaId": ea_id, "type": "entropyAssessment"}
    ea_token = create_jwt(ea_claims, JWT_SECRET)

    now = datetime.datetime.utcnow()
    assessments[ea_id] = {
        "createdOn": now.isoformat(),
        "status": "pendingEvaluation",
        "primaryNoiseSource": payload.get("primaryNoiseSource", ""),
        "iidClaim": payload.get("iidClaim", False),
        "bitsPerSample": payload.get("bitsPerSample", 0),
        "hminEstimate": payload.get("hminEstimate", 0.0),
        "physical": payload.get("physical", False),
    }

    response_obj = {
        "url": f"/esv/v1/entropyAssessments/{ea_id}",
        "createdOn": now.isoformat(),
        "expiresOn": (now + datetime.timedelta(days=30)).isoformat(),
        "dataFileUrls": data_file_urls,
        "publishable": False,
        "accessToken": ea_token,
    }

    return jsonify([{"esvVersion": ESV_VERSION}, [response_obj]])


@app.route("/esv/v1/entropyAssessments/<int:ea_id>", methods=["GET"])
def get_entropy(ea_id):
    user_claims, err = _check_bearer()
    if err:
        return err

    if ea_id not in assessments:
        return jsonify([{"esvVersion": ESV_VERSION},
                        {"error": "Not found"}]), 404

    return jsonify([{"esvVersion": ESV_VERSION}, assessments[ea_id]])


# ===========================================================
# Main — start with mTLS
# ===========================================================

if __name__ == "__main__":
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain("/app/pki/server.crt", "/app/pki/server.key")
    ctx.load_verify_locations("/app/pki/ca.crt")
    ctx.verify_mode = ssl.CERT_REQUIRED

    app.run(host="0.0.0.0", port=7443, ssl_context=ctx)
