
import json
import os
import subprocess
import sqlite3
import ipaddress
import pytest

APP = "/app"

# ---------------------------------------------------------------------------
# Reference implementation
# ---------------------------------------------------------------------------

def _load(path):
    with open(path) as f:
        return json.load(f)


def _ref_verify_sig(data_file, sig_file, pub_key_file):
    r = subprocess.run(
        ["openssl", "dgst", "-sha256", "-verify", pub_key_file,
         "-signature", sig_file, data_file],
        capture_output=True, text=True
    )
    return r.returncode == 0


def _ref_trust():
    """Compute reference trust status for all RPKI objects."""
    entity_reg = _load(f"{APP}/entity_registry.json")
    revlist = _load(f"{APP}/revocation_list.json")
    revoked = set(revlist.get("revoked_entities", []))
    roa_man = _load(f"{APP}/roa_manifest.json")
    aspa_man = _load(f"{APP}/aspa_manifest.json")

    results = {}
    for manifest in [roa_man, aspa_man]:
        for obj in manifest:
            oid = obj.get("roa_id") or obj.get("aspa_id")
            signer = obj["signing_entity"]
            df = os.path.join(APP, obj["data_file"])
            sf = os.path.join(APP, obj["signature_file"])
            pk = os.path.join(APP, entity_reg[signer]["public_key_file"])

            if signer in revoked:
                results[oid] = {"trusted": False, "reason": "signing_entity_revoked"}
            elif not _ref_verify_sig(df, sf, pk):
                results[oid] = {"trusted": False, "reason": "invalid_signature"}
            else:
                results[oid] = {"trusted": True, "reason": "valid"}
    return results


def _ref_trusted_roas(trust_map):
    roa_man = _load(f"{APP}/roa_manifest.json")
    roas = []
    for entry in roa_man:
        if trust_map.get(entry["roa_id"], {}).get("trusted"):
            roa_data = _load(os.path.join(APP, entry["data_file"]))
            roas.append(roa_data)
    return roas


def _ref_trusted_aspa_db(trust_map):
    aspa_man = _load(f"{APP}/aspa_manifest.json")
    db = {}
    for entry in aspa_man:
        if trust_map.get(entry["aspa_id"], {}).get("trusted"):
            aspa_data = _load(os.path.join(APP, entry["data_file"]))
            key = str(aspa_data["customer_as"])
            db[key] = aspa_data["authorized_providers"]
    return db


def _ref_rov(route, trusted_roas):
    prefix = route["prefix"]
    origin = route["origin_as"]
    route_net = ipaddress.ip_network(prefix)
    covering = []
    for roa in trusted_roas:
        roa_net = ipaddress.ip_network(roa["prefix"])
        if (roa_net.supernet_of(route_net) or roa_net == route_net) \
                and route_net.prefixlen <= roa["max_length"]:
            covering.append(roa)
    if not covering:
        return "NotFound", False
    for roa in covering:
        if roa["asn"] == origin:
            roa_net = ipaddress.ip_network(roa["prefix"])
            unsafe = (roa["max_length"] - roa_net.prefixlen) >= 4
            return "Valid", unsafe
    return "Invalid", False


def _collapse(seq):
    if not seq:
        return []
    out = [seq[0]]
    for a in seq[1:]:
        if a != out[-1]:
            out.append(a)
    return out


def _hop(cust, cand, db):
    k = str(cust)
    if k not in db:
        return "NoAttestation"
    if cand in db[k]:
        return "ProviderPlus"
    return "NotProviderPlus"


def _ref_upstream(path, db):
    n = len(path)
    if n <= 1:
        return "Valid"
    unk = False
    for i in range(n - 1):
        h = _hop(path[i], path[i + 1], db)
        if h == "NotProviderPlus":
            return "Invalid"
        if h == "NoAttestation":
            unk = True
    return "Unknown" if unk else "Valid"


def _ref_downstream(path, db):
    n = len(path)
    if n <= 2:
        return "Valid"
    u = 0
    for i in range(n - 1):
        if _hop(path[i], path[i + 1], db) == "NotProviderPlus":
            break
        u = i + 1
    d = n - 1
    for j in range(n - 1, 0, -1):
        if _hop(path[j], path[j - 1], db) == "NotProviderPlus":
            break
        d = j - 1
    if u + 1 < d:
        return "Invalid"
    for i in range(u):
        if _hop(path[i], path[i + 1], db) == "NoAttestation":
            return "Unknown"
    for j in range(n - 1, d, -1):
        if _hop(path[j], path[j - 1], db) == "NoAttestation":
            return "Unknown"
    return "Valid"


def _ref_aspa(route, db):
    raw = list(reversed(route["as_path"]))
    path = _collapse(raw)
    if route["relationship"] == "customer":
        return _ref_upstream(path, db)
    else:
        return _ref_downstream(path, db)


def _ref_risk(rov, aspa, unsafe, rev):
    s = 1
    if rov == "Invalid":
        s += 5
    elif rov == "NotFound":
        s += 2
    if aspa == "Invalid":
        s += 4
    elif aspa == "Unknown":
        s += 1
    if unsafe:
        s += 2
    if rev:
        s += 3
    return min(s, 10)


def _ref_verdict(rov, aspa, risk):
    if risk >= 7:
        return "REJECT"
    if rov == "Invalid":
        return "REJECT"
    if aspa == "Invalid":
        return "REJECT"
    if rov != "Valid" and aspa != "Valid":
        return "REJECT"
    if rov == "Valid" and aspa == "Valid":
        return "ACCEPT"
    if rov == "NotFound" and aspa == "Valid":
        return "REVIEW"
    if rov == "Valid" and aspa == "Unknown":
        return "REVIEW"
    if rov == "NotFound" and aspa == "Unknown":
        return "REVIEW"
    return "REVIEW"


def _ref_involves_revoked(route, roa_manifest, trusted_ids, revoked_entities):
    prefix = route["prefix"]
    route_net = ipaddress.ip_network(prefix)
    for entry in roa_manifest:
        if entry["roa_id"] not in trusted_ids:
            try:
                roa_data = _load(os.path.join(APP, entry["data_file"]))
                roa_net = ipaddress.ip_network(roa_data["prefix"])
                if roa_net.supernet_of(route_net) or roa_net == route_net:
                    if entry["signing_entity"] in revoked_entities:
                        return True
            except Exception:
                pass
    return False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def trust_map():
    return _ref_trust()


@pytest.fixture(scope="module")
def trusted_roas(trust_map):
    return _ref_trusted_roas(trust_map)


@pytest.fixture(scope="module")
def aspa_db(trust_map):
    return _ref_trusted_aspa_db(trust_map)


@pytest.fixture(scope="module")
def routes():
    return _load(f"{APP}/rib.json")


@pytest.fixture(scope="module")
def ref_rov(routes, trusted_roas):
    results = {}
    for r in routes:
        status, unsafe = _ref_rov(r, trusted_roas)
        results[r["route_id"]] = {"rov_status": status, "unsafe_maxlength": unsafe}
    return results


@pytest.fixture(scope="module")
def ref_aspa(routes, aspa_db):
    results = {}
    for r in routes:
        results[r["route_id"]] = _ref_aspa(r, aspa_db)
    return results


@pytest.fixture(scope="module")
def ref_verdicts(routes, ref_rov, ref_aspa, trust_map):
    roa_man = _load(f"{APP}/roa_manifest.json")
    revlist = _load(f"{APP}/revocation_list.json")
    revoked = set(revlist.get("revoked_entities", []))
    trusted_ids = {k for k, v in trust_map.items() if v["trusted"]}

    results = {}
    for r in routes:
        rid = r["route_id"]
        rov = ref_rov[rid]["rov_status"]
        aspa = ref_aspa[rid]
        unsafe = ref_rov[rid]["unsafe_maxlength"]
        rev = _ref_involves_revoked(r, roa_man, trusted_ids, revoked)
        risk = _ref_risk(rov, aspa, unsafe, rev)
        verdict = _ref_verdict(rov, aspa, risk)
        results[rid] = {
            "rov_status": rov, "aspa_status": aspa,
            "unsafe_maxlength": unsafe, "risk_score": risk,
            "verdict": verdict
        }
    return results


@pytest.fixture(scope="module")
def agent_trust():
    path = f"{APP}/trusted_objects.json"
    assert os.path.exists(path), f"Missing {path}"
    data = _load(path)
    return {e["id"]: e for e in data}


@pytest.fixture(scope="module")
def agent_rov():
    path = f"{APP}/rov_results.json"
    assert os.path.exists(path), f"Missing {path}"
    data = _load(path)
    return {e["route_id"]: e for e in data}


@pytest.fixture(scope="module")
def agent_aspa():
    path = f"{APP}/aspa_results.json"
    assert os.path.exists(path), f"Missing {path}"
    data = _load(path)
    return {e["route_id"]: e for e in data}


@pytest.fixture(scope="module")
def agent_verdicts():
    path = f"{APP}/route_verdicts.json"
    assert os.path.exists(path), f"Missing {path}"
    data = _load(path)
    return {e["route_id"]: e for e in data}


@pytest.fixture(scope="module")
def agent_attacks():
    path = f"{APP}/policy_evaluation.json"
    assert os.path.exists(path), f"Missing {path}"
    data = _load(path)
    return {e["scenario_id"]: e for e in data}


# ---------------------------------------------------------------------------
# Tests: RPKI Trust Verification
# ---------------------------------------------------------------------------

class TestTrustVerification:
    def test_trusted_objects_file_exists(self):
        assert os.path.exists(f"{APP}/trusted_objects.json")

    def test_all_objects_present(self, agent_trust, trust_map):
        for oid in trust_map:
            assert oid in agent_trust, f"Missing trust entry for {oid}"

    @pytest.mark.parametrize("oid", [
        "ROA09", "ROA15",  # revoked signer
    ])
    def test_revoked_signer_detected(self, oid, agent_trust):
        assert not agent_trust[oid]["trusted"], \
            f"{oid} should be untrusted (revoked signer)"
        assert agent_trust[oid]["reason"] == "signing_entity_revoked"

    @pytest.mark.parametrize("oid", [
        "ROA13", "ROA18",  # tampered data
    ])
    def test_tampered_signature_detected(self, oid, agent_trust):
        assert not agent_trust[oid]["trusted"], \
            f"{oid} should be untrusted (invalid signature)"
        assert agent_trust[oid]["reason"] == "invalid_signature"

    @pytest.mark.parametrize("oid", [
        "ASPA06", "ASPA23",  # revoked signer
    ])
    def test_revoked_aspa_signer(self, oid, agent_trust):
        assert not agent_trust[oid]["trusted"]
        assert agent_trust[oid]["reason"] == "signing_entity_revoked"

    @pytest.mark.parametrize("oid", [
        "ASPA10", "ASPA25",  # tampered
    ])
    def test_tampered_aspa_signature(self, oid, agent_trust):
        assert not agent_trust[oid]["trusted"]
        assert agent_trust[oid]["reason"] == "invalid_signature"

    def test_valid_objects_trusted(self, agent_trust, trust_map):
        for oid, ref in trust_map.items():
            if ref["trusted"]:
                assert agent_trust[oid]["trusted"], \
                    f"{oid} should be trusted but agent says untrusted"

    def test_untrusted_count(self, agent_trust, trust_map):
        ref_untrusted = sum(1 for v in trust_map.values() if not v["trusted"])
        agent_untrusted = sum(1 for v in agent_trust.values() if not v["trusted"])
        assert agent_untrusted == ref_untrusted, \
            f"Expected {ref_untrusted} untrusted, got {agent_untrusted}"


# ---------------------------------------------------------------------------
# Tests: ROV Results
# ---------------------------------------------------------------------------

class TestROV:
    def test_rov_file_exists(self):
        assert os.path.exists(f"{APP}/rov_results.json")

    def test_rov_count(self, agent_rov, routes):
        assert len(agent_rov) == len(routes)

    @pytest.mark.parametrize("rid", [
        "R01", "R02", "R03", "R04", "R05", "R07", "R10", "R12",
        "R13", "R14", "R16", "R17",
    ])
    def test_rov_valid_routes(self, rid, agent_rov, ref_rov):
        assert agent_rov[rid]["rov_status"] == ref_rov[rid]["rov_status"], \
            f"{rid}: expected ROV={ref_rov[rid]['rov_status']}, got {agent_rov[rid]['rov_status']}"

    @pytest.mark.parametrize("rid", ["R06", "R08", "R43", "R46", "R56"])
    def test_rov_invalid_routes(self, rid, agent_rov, ref_rov):
        assert agent_rov[rid]["rov_status"] == "Invalid", \
            f"{rid}: expected ROV=Invalid, got {agent_rov[rid]['rov_status']}"

    @pytest.mark.parametrize("rid", ["R09", "R11", "R18", "R20"])
    def test_rov_notfound_routes(self, rid, agent_rov, ref_rov):
        assert agent_rov[rid]["rov_status"] == "NotFound", \
            f"{rid}: expected ROV=NotFound, got {agent_rov[rid]['rov_status']}"

    def test_unsafe_maxlength_roa04(self, agent_rov):
        """ROA04 has max_length=24 on /16 prefix — 8 bits difference >= 4."""
        assert agent_rov["R04"]["unsafe_maxlength"] is True

    def test_unsafe_maxlength_roa06(self, agent_rov):
        """ROA06 has max_length=24 on /20 prefix — 4 bits difference >= 4."""
        assert agent_rov["R10"]["unsafe_maxlength"] is True

    def test_safe_maxlength(self, agent_rov):
        """ROA01 has max_length=24 on /24 prefix — 0 bits, safe."""
        assert agent_rov["R01"]["unsafe_maxlength"] is False

    def test_all_rov_match_ref(self, agent_rov, ref_rov):
        for rid in ref_rov:
            assert agent_rov[rid]["rov_status"] == ref_rov[rid]["rov_status"], \
                f"{rid}: ROV expected={ref_rov[rid]['rov_status']}, got={agent_rov[rid]['rov_status']}"


# ---------------------------------------------------------------------------
# Tests: ASPA Results
# ---------------------------------------------------------------------------

class TestASPA:
    def test_aspa_file_exists(self):
        assert os.path.exists(f"{APP}/aspa_results.json")

    def test_aspa_count(self, agent_aspa, routes):
        assert len(agent_aspa) == len(routes)

    @pytest.mark.parametrize("rid", [
        "R01", "R02", "R03", "R04", "R05", "R07",
        "R12", "R13", "R16", "R17",
    ])
    def test_aspa_valid_upstream(self, rid, agent_aspa, ref_aspa):
        assert agent_aspa[rid]["aspa_status"] == ref_aspa[rid], \
            f"{rid}: ASPA expected={ref_aspa[rid]}, got={agent_aspa[rid]['aspa_status']}"

    @pytest.mark.parametrize("rid", ["R15", "R19"])
    def test_aspa_invalid_upstream(self, rid, agent_aspa):
        assert agent_aspa[rid]["aspa_status"] == "Invalid"

    @pytest.mark.parametrize("rid", ["R25", "R37", "R38", "R42", "R57"])
    def test_aspa_invalid_downstream(self, rid, agent_aspa):
        assert agent_aspa[rid]["aspa_status"] == "Invalid", \
            f"{rid}: expected ASPA=Invalid, got {agent_aspa[rid]['aspa_status']}"

    def test_prepend_collapse(self, agent_aspa, ref_aspa):
        """R02 has consecutive prepending that must be collapsed."""
        assert agent_aspa["R02"]["aspa_status"] == ref_aspa["R02"]

    def test_all_aspa_match_ref(self, agent_aspa, ref_aspa):
        for rid in ref_aspa:
            assert agent_aspa[rid]["aspa_status"] == ref_aspa[rid], \
                f"{rid}: ASPA expected={ref_aspa[rid]}, got={agent_aspa[rid]['aspa_status']}"


# ---------------------------------------------------------------------------
# Tests: Composite Route Verdicts
# ---------------------------------------------------------------------------

class TestVerdicts:
    def test_verdicts_file_exists(self):
        assert os.path.exists(f"{APP}/route_verdicts.json")

    def test_verdicts_count(self, agent_verdicts, routes):
        assert len(agent_verdicts) == len(routes)

    def test_verdict_fields(self, agent_verdicts):
        for rid, v in agent_verdicts.items():
            assert "rov_status" in v
            assert "aspa_status" in v
            assert "risk_score" in v
            assert "verdict" in v
            assert v["verdict"] in ("ACCEPT", "REJECT", "REVIEW")

    @pytest.mark.parametrize("rid", [
        "R06", "R08", "R15", "R19", "R25", "R30", "R37", "R38",
        "R42", "R43", "R46", "R56", "R57",
    ])
    def test_reject_routes(self, rid, agent_verdicts, ref_verdicts):
        assert agent_verdicts[rid]["verdict"] == "REJECT", \
            f"{rid}: expected REJECT, got {agent_verdicts[rid]['verdict']}"

    @pytest.mark.parametrize("rid", [
        "R01", "R02", "R03", "R05", "R07", "R12", "R13", "R16",
        "R17", "R24", "R28", "R32", "R41", "R58", "R60",
    ])
    def test_accept_routes(self, rid, agent_verdicts, ref_verdicts):
        assert agent_verdicts[rid]["verdict"] == "ACCEPT", \
            f"{rid}: expected ACCEPT, got {agent_verdicts[rid]['verdict']}"

    def test_risk_score_range(self, agent_verdicts):
        for rid, v in agent_verdicts.items():
            assert 1 <= v["risk_score"] <= 10, \
                f"{rid}: risk_score {v['risk_score']} out of range"

    def test_high_risk_always_reject(self, agent_verdicts):
        for rid, v in agent_verdicts.items():
            if v["risk_score"] >= 7:
                assert v["verdict"] == "REJECT", \
                    f"{rid}: risk={v['risk_score']} >= 7 but verdict={v['verdict']}"

    def test_all_verdicts_match_ref(self, agent_verdicts, ref_verdicts):
        for rid in ref_verdicts:
            ref = ref_verdicts[rid]
            agent = agent_verdicts[rid]
            assert agent["verdict"] == ref["verdict"], \
                f"{rid}: verdict expected={ref['verdict']}, got={agent['verdict']}"
            assert agent["risk_score"] == ref["risk_score"], \
                f"{rid}: risk expected={ref['risk_score']}, got={agent['risk_score']}"


# ---------------------------------------------------------------------------
# Tests: SQLite Database
# ---------------------------------------------------------------------------

class TestDatabase:
    def test_db_exists(self):
        assert os.path.exists(f"{APP}/route_security.db")

    def test_trusted_objects_table(self):
        conn = sqlite3.connect(f"{APP}/route_security.db")
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM trusted_objects")
        count = c.fetchone()[0]
        conn.close()
        assert count == 45, f"trusted_objects should have 45 rows, got {count}"

    def test_route_verdicts_table(self):
        conn = sqlite3.connect(f"{APP}/route_security.db")
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM route_verdicts")
        count = c.fetchone()[0]
        conn.close()
        assert count == 60, f"route_verdicts should have 60 rows, got {count}"

    def test_db_reject_count(self, ref_verdicts):
        conn = sqlite3.connect(f"{APP}/route_security.db")
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM route_verdicts WHERE verdict='REJECT'")
        db_reject = c.fetchone()[0]
        conn.close()
        ref_reject = sum(1 for v in ref_verdicts.values() if v["verdict"] == "REJECT")
        assert db_reject == ref_reject

    def test_db_schema_trusted_objects(self):
        conn = sqlite3.connect(f"{APP}/route_security.db")
        c = conn.cursor()
        c.execute("PRAGMA table_info(trusted_objects)")
        cols = {row[1] for row in c.fetchall()}
        conn.close()
        assert {"id", "type", "trusted", "reason"}.issubset(cols)

    def test_db_schema_route_verdicts(self):
        conn = sqlite3.connect(f"{APP}/route_security.db")
        c = conn.cursor()
        c.execute("PRAGMA table_info(route_verdicts)")
        cols = {row[1] for row in c.fetchall()}
        conn.close()
        required = {"route_id", "prefix", "origin_as", "relationship",
                    "rov_status", "aspa_status", "unsafe_maxlength",
                    "risk_score", "verdict"}
        assert required.issubset(cols), f"Missing columns: {required - cols}"


# ---------------------------------------------------------------------------
# Tests: Attack Evaluation
# ---------------------------------------------------------------------------

class TestAttackEvaluation:
    def test_policy_eval_file_exists(self):
        assert os.path.exists(f"{APP}/policy_evaluation.json")

    def test_all_scenarios_present(self, agent_attacks):
        for i in range(1, 9):
            sid = f"ATK0{i}"
            assert sid in agent_attacks, f"Missing scenario {sid}"

    @pytest.mark.parametrize("sid", [
        "ATK01", "ATK02", "ATK03", "ATK04", "ATK05", "ATK06", "ATK07", "ATK08",
    ])
    def test_attack_detected(self, sid, agent_attacks):
        assert agent_attacks[sid]["detected"] is True, \
            f"{sid} should be detected"

    @pytest.mark.parametrize("sid,expected", [
        ("ATK01", True),
        ("ATK02", True),
        ("ATK03", True),
        ("ATK04", True),
        ("ATK05", False),
        ("ATK06", True),
        ("ATK07", False),
        ("ATK08", False),
    ])
    def test_attack_mitigation(self, sid, expected, agent_attacks):
        assert agent_attacks[sid]["mitigated"] is expected, \
            f"{sid}: mitigated expected={expected}, got={agent_attacks[sid]['mitigated']}"

    def test_attack_route_verdicts(self, agent_attacks, ref_verdicts):
        attacks = _load(f"{APP}/attack_scenarios.json")
        for attack in attacks:
            sid = attack["scenario_id"]
            for rid in attack["affected_routes"]:
                expected = ref_verdicts[rid]["verdict"]
                actual = agent_attacks[sid]["affected_route_verdicts"].get(rid)
                assert actual == expected, \
                    f"{sid}/{rid}: expected {expected}, got {actual}"
