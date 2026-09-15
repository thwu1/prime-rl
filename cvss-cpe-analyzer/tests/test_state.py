"""
Tests for the NVD Mirror Forensic Audit & Threat Prioritization.
Verifies HMAC tamper detection, CVSS recomputation, CPE/CWE cross-validation,
EPSS/KEV threat correlation, CPE Dictionary XML generation, and independently
cross-validates all solution claims against raw data sources.
"""


import csv
import hashlib
import hmac as hmac_mod
import json
import math
import os
import sqlite3
import xml.etree.ElementTree as ET

import pytest


REPORT_PATH = "/app/output/audit_report.json"
XML_PATH = "/app/output/cpe_dictionary.xml"

CPE_NS = "http://cpe.mitre.org/dictionary/2.0"
CPE23_NS = "http://scap.nist.gov/schema/cpe-extension/2.3"


@pytest.fixture(scope="module")
def report():
    assert os.path.exists(REPORT_PATH), f"Audit report not found at {REPORT_PATH}."
    with open(REPORT_PATH) as f:
        data = json.load(f)
    return data


# ===================== Report Structure =====================

class TestReportStructure:

    def test_has_tampered_records(self, report):
        assert "tampered_records" in report
        assert isinstance(report["tampered_records"], list)

    def test_has_score_anomalies(self, report):
        assert "score_anomalies" in report
        assert isinstance(report["score_anomalies"], list)

    def test_has_cpe_discrepancies(self, report):
        assert "cpe_discrepancies" in report
        assert isinstance(report["cpe_discrepancies"], list)

    def test_has_cwe_errors(self, report):
        assert "cwe_errors" in report
        assert isinstance(report["cwe_errors"], list)

    def test_has_threat_priority(self, report):
        assert "threat_priority" in report
        assert isinstance(report["threat_priority"], list)

    def test_has_summary(self, report):
        assert "summary" in report
        assert isinstance(report["summary"], dict)


# ===================== HMAC Tamper Detection =====================

class TestTamperedRecords:

    EXPECTED_TAMPERED = {
        "CVE-MIRROR-0002", "CVE-MIRROR-0004", "CVE-MIRROR-0005",
        "CVE-MIRROR-0007", "CVE-MIRROR-0008", "CVE-MIRROR-0009",
        "CVE-MIRROR-0011", "CVE-MIRROR-0012",
    }

    def test_tampered_count(self, report):
        assert len(report["tampered_records"]) == 8

    def test_tampered_cve_ids(self, report):
        found_ids = {r["cve_id"] for r in report["tampered_records"]}
        assert found_ids == self.EXPECTED_TAMPERED

    def test_hmac_fields_present(self, report):
        for rec in report["tampered_records"]:
            assert "hmac_stored" in rec
            assert "hmac_computed" in rec

    def test_hmac_values_differ(self, report):
        for rec in report["tampered_records"]:
            assert rec["hmac_stored"] != rec["hmac_computed"]

    def test_untampered_not_included(self, report):
        untampered = {"CVE-MIRROR-0001", "CVE-MIRROR-0003", "CVE-MIRROR-0006",
                      "CVE-MIRROR-0010"}
        found_ids = {r["cve_id"] for r in report["tampered_records"]}
        assert not (found_ids & untampered)


# ===================== Score Anomalies =====================

class TestScoreAnomalies:

    EXPECTED_ANOMALIES = {
        "CVE-MIRROR-0002": (8.2, 7.5),
        "CVE-MIRROR-0007": (7.5, 8.1),
        "CVE-MIRROR-0009": (9.1, 8.8),
        "CVE-MIRROR-0012": (7.6, 8.5),
    }

    def test_anomaly_count(self, report):
        assert len(report["score_anomalies"]) == 4

    def test_anomaly_cve_ids(self, report):
        found_ids = {a["cve_id"] for a in report["score_anomalies"]}
        assert found_ids == set(self.EXPECTED_ANOMALIES.keys())

    @pytest.mark.parametrize("cve_id,stored,computed", [
        ("CVE-MIRROR-0002", 8.2, 7.5),
        ("CVE-MIRROR-0007", 7.5, 8.1),
        ("CVE-MIRROR-0009", 9.1, 8.8),
        ("CVE-MIRROR-0012", 7.6, 8.5),
    ])
    def test_anomaly_scores(self, report, cve_id, stored, computed):
        anomaly = next((a for a in report["score_anomalies"] if a["cve_id"] == cve_id), None)
        assert anomaly is not None, f"Score anomaly for {cve_id} not found"
        assert abs(anomaly["stored_score"] - stored) < 0.05
        assert abs(anomaly["computed_score"] - computed) < 0.05

    def test_non_anomalous_not_included(self, report):
        correct_cves = {"CVE-MIRROR-0001", "CVE-MIRROR-0003", "CVE-MIRROR-0004",
                        "CVE-MIRROR-0005", "CVE-MIRROR-0006", "CVE-MIRROR-0008",
                        "CVE-MIRROR-0010", "CVE-MIRROR-0011"}
        found_ids = {a["cve_id"] for a in report["score_anomalies"]}
        assert not (found_ids & correct_cves)


# ===================== CPE Discrepancies =====================

class TestCPEDiscrepancies:

    EXPECTED_CPE_CVES = {"CVE-MIRROR-0005", "CVE-MIRROR-0009", "CVE-MIRROR-0011"}

    def test_discrepancy_count(self, report):
        assert len(report["cpe_discrepancies"]) == 3

    def test_discrepancy_cve_ids(self, report):
        found_ids = {d["cve_id"] for d in report["cpe_discrepancies"]}
        assert found_ids == self.EXPECTED_CPE_CVES


# ===================== CWE Errors =====================

class TestCWEErrors:

    EXPECTED_CWE_ERRORS = {
        "CVE-MIRROR-0004": ("CWE-416", "CWE-362"),
        "CVE-MIRROR-0008": ("CWE-787", "CWE-119"),
    }

    def test_error_count(self, report):
        assert len(report["cwe_errors"]) == 2

    def test_error_cve_ids(self, report):
        found_ids = {e["cve_id"] for e in report["cwe_errors"]}
        assert found_ids == set(self.EXPECTED_CWE_ERRORS.keys())

    @pytest.mark.parametrize("cve_id,stored_cwe,correct_cwe", [
        ("CVE-MIRROR-0004", "CWE-416", "CWE-362"),
        ("CVE-MIRROR-0008", "CWE-787", "CWE-119"),
    ])
    def test_cwe_values(self, report, cve_id, stored_cwe, correct_cwe):
        error = next((e for e in report["cwe_errors"] if e["cve_id"] == cve_id), None)
        assert error is not None, f"CWE error for {cve_id} not found"
        assert error["stored_cwe"] == stored_cwe
        assert error["correct_cwe"] == correct_cwe


# ===================== Threat Priority =====================

class TestThreatPriority:

    def _find_item(self, report, vendor, product, version):
        for entry in report["threat_priority"]:
            if (entry["vendor"] == vendor and
                    entry["product"] == product and
                    entry["version"] == version):
                return entry
        return None

    def test_affected_count(self, report):
        assert len(report["threat_priority"]) == 10

    def test_loglib_2_14_1_affected(self, report):
        item = self._find_item(report, "acme", "loglib", "2.14.1")
        assert item is not None
        assert "CVE-MIRROR-0001" in item["matched_cves"]
        assert abs(item["cvss_score"] - 10.0) < 0.05

    def test_cryptolib_1_0_1_affected(self, report):
        item = self._find_item(report, "acme", "cryptolib", "1.0.1")
        assert item is not None
        assert "CVE-MIRROR-0002" in item["matched_cves"]
        assert abs(item["cvss_score"] - 7.5) < 0.05

    def test_shellutil_4_3_0_affected(self, report):
        item = self._find_item(report, "acme", "shellutil", "4.3.0")
        assert item is not None
        assert abs(item["cvss_score"] - 9.8) < 0.05

    def test_blogengine_5_8_0_affected(self, report):
        item = self._find_item(report, "acme", "blogengine", "5.8.0")
        assert item is not None

    def test_analytics_2_4_0_affected(self, report):
        item = self._find_item(report, "acme", "analytics", "2.4.0")
        assert item is not None
        assert "CVE-MIRROR-0011" in item["matched_cves"]

    def test_container_rt_1_5_0_affected(self, report):
        item = self._find_item(report, "acme", "container_rt", "1.5.0")
        assert item is not None
        assert "CVE-MIRROR-0009" in item["matched_cves"]
        assert abs(item["cvss_score"] - 8.8) < 0.05

    def test_container_rt_1_0_0_not_affected(self, report):
        item = self._find_item(report, "acme", "container_rt", "1.0.0")
        assert item is None

    def test_loglib_2_15_1_not_affected(self, report):
        item = self._find_item(report, "acme", "loglib", "2.15.1")
        assert item is None

    def test_kernelos_4_8_3_not_affected(self, report):
        item = self._find_item(report, "acme", "kernelos", "4.8.3")
        assert item is None

    def test_shellutil_4_4_0_not_affected(self, report):
        item = self._find_item(report, "acme", "shellutil", "4.4.0")
        assert item is None

    # --- EPSS/KEV Correlation ---

    def test_loglib_kev_status(self, report):
        item = self._find_item(report, "acme", "loglib", "2.14.1")
        assert item is not None
        assert item["in_kev"] is True

    def test_datastore_kev_status(self, report):
        item = self._find_item(report, "acme", "datastore", "8.1.0")
        assert item is not None
        assert item["in_kev"] is False

    def test_loglib_epss(self, report):
        item = self._find_item(report, "acme", "loglib", "2.14.1")
        assert item is not None
        assert abs(item["epss_score"] - 0.97150) < 0.001

    def test_analytics_epss(self, report):
        item = self._find_item(report, "acme", "analytics", "2.4.0")
        assert item is not None
        assert abs(item["epss_score"] - 0.87340) < 0.001

    # --- Priority Scores ---

    def test_loglib_priority(self, report):
        item = self._find_item(report, "acme", "loglib", "2.14.1")
        assert item is not None
        assert abs(item["priority_score"] - 19.43) < 0.01

    def test_shellutil_priority(self, report):
        item = self._find_item(report, "acme", "shellutil", "4.3.0")
        assert item is not None
        assert abs(item["priority_score"] - 18.4652) < 0.01

    def test_analytics_priority(self, report):
        item = self._find_item(report, "acme", "analytics", "2.4.0")
        assert item is not None
        assert abs(item["priority_score"] - 15.8959) < 0.01

    def test_cryptolib_priority(self, report):
        item = self._find_item(report, "acme", "cryptolib", "1.0.1")
        assert item is not None
        assert abs(item["priority_score"] - 5.874) < 0.01

    def test_msgqueue_priority(self, report):
        item = self._find_item(report, "acme", "msgqueue", "3.1.0")
        assert item is not None
        assert abs(item["priority_score"] - 0.6307) < 0.01

    def test_sorted_by_priority_desc(self, report):
        scores = [item["priority_score"] for item in report["threat_priority"]]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1]


# ===================== Summary Statistics =====================

class TestSummaryStatistics:

    def test_total_cves(self, report):
        assert report["summary"]["total_cves_audited"] == 12

    def test_tampered_count(self, report):
        assert report["summary"]["tampered_count"] == 8

    def test_score_anomalies_count(self, report):
        assert report["summary"]["score_anomalies_found"] == 4

    def test_cpe_discrepancies_count(self, report):
        assert report["summary"]["cpe_discrepancies_found"] == 3

    def test_cwe_errors_count(self, report):
        assert report["summary"]["cwe_errors_found"] == 2

    def test_inventory_total(self, report):
        assert report["summary"]["inventory_items_total"] == 15

    def test_vulnerable_items(self, report):
        assert report["summary"]["inventory_items_vulnerable"] == 10

    def test_risk_score(self, report):
        expected = 82.4
        actual = report["summary"]["risk_score"]
        assert abs(actual - expected) < 0.15


# ===================== CPE Dictionary XML =====================

class TestCPEDictionaryXML:

    @pytest.fixture(scope="class")
    def xml_tree(self):
        assert os.path.exists(XML_PATH)
        return ET.parse(XML_PATH)

    def test_xml_exists(self):
        assert os.path.exists(XML_PATH)

    def test_xml_well_formed(self, xml_tree):
        assert xml_tree.getroot() is not None

    def test_root_namespace(self, xml_tree):
        root = xml_tree.getroot()
        assert root.tag == f"{{{CPE_NS}}}cpe-list"

    def test_cpe_item_count(self, xml_tree):
        root = xml_tree.getroot()
        items = root.findall(f"{{{CPE_NS}}}cpe-item")
        assert len(items) == 10

    def test_cpe_items_have_names(self, xml_tree):
        root = xml_tree.getroot()
        for item in root.findall(f"{{{CPE_NS}}}cpe-item"):
            assert "name" in item.attrib
            assert item.attrib["name"].startswith("cpe:/")

    def test_cpe23_items_present(self, xml_tree):
        root = xml_tree.getroot()
        for item in root.findall(f"{{{CPE_NS}}}cpe-item"):
            cpe23 = item.find(f"{{{CPE23_NS}}}cpe23-item")
            assert cpe23 is not None
            assert "name" in cpe23.attrib
            assert cpe23.attrib["name"].startswith("cpe:2.3:")

    def test_kernelos_uses_os_part_type(self, xml_tree):
        root = xml_tree.getroot()
        kernelos_found = False
        for item in root.findall(f"{{{CPE_NS}}}cpe-item"):
            cpe23 = item.find(f"{{{CPE23_NS}}}cpe23-item")
            if cpe23 is not None and "kernelos" in cpe23.attrib.get("name", ""):
                kernelos_found = True
                assert ":o:" in cpe23.attrib["name"]
                assert item.attrib["name"].startswith("cpe:/o:")
        assert kernelos_found

    def test_loglib_cpe_uri(self, xml_tree):
        root = xml_tree.getroot()
        found = False
        for item in root.findall(f"{{{CPE_NS}}}cpe-item"):
            cpe23 = item.find(f"{{{CPE23_NS}}}cpe23-item")
            if cpe23 is not None:
                if cpe23.attrib.get("name") == "cpe:2.3:a:acme:loglib:2.14.1:*:*:*:*:*:*:*":
                    found = True
                    break
        assert found

    def test_titles_present(self, xml_tree):
        root = xml_tree.getroot()
        for item in root.findall(f"{{{CPE_NS}}}cpe-item"):
            title = item.find(f"{{{CPE_NS}}}title")
            assert title is not None
            assert title.text and len(title.text) > 0


# ===================== Dynamic Verification =====================
# Cross-validate solution output by independently recomputing expected
# values from the raw data sources (database, canonical feed, EPSS CSV,
# KEV catalog). This prevents fabricated output from passing.

class TestDynamicVerification:

    @pytest.fixture(scope="class")
    def hmac_key(self):
        with open("/app/data/.hmac_key") as f:
            return f.read().strip()

    @pytest.fixture(scope="class")
    def db_records(self):
        conn = sqlite3.connect("/app/data/nvd_mirror.db")
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM cve_records")
        records = {row["cve_id"]: dict(row) for row in c.fetchall()}
        conn.close()
        return records

    @pytest.fixture(scope="class")
    def canonical_data(self):
        with open("/app/data/canonical/nvd_snapshot.json") as f:
            data = json.load(f)
        result = {}
        for vuln in data["vulnerabilities"]:
            cve = vuln["cve"]
            result[cve["id"]] = cve
        return result

    @pytest.fixture(scope="class")
    def epss_data(self):
        with open("/app/data/feeds/epss_scores.csv") as f:
            lines = [l for l in f if not l.startswith("#")]
        reader = csv.DictReader(lines)
        return {row["cve"]: float(row["epss"]) for row in reader}

    @pytest.fixture(scope="class")
    def kev_cves(self):
        with open("/app/data/feeds/kev_catalog.json") as f:
            data = json.load(f)
        return {v["cveID"] for v in data["vulnerabilities"]}

    def _canonical_json(self, obj):
        return json.dumps(obj, separators=(',', ':'), sort_keys=True)

    def _compute_hmac(self, key, cve_id, vector, score, cwe, cpe_json):
        msg = f"{cve_id}|{vector}|{score:.1f}|{cwe}|{cpe_json}"
        return hmac_mod.new(key.encode(), msg.encode(), hashlib.sha256).hexdigest()

    def _roundup(self, x):
        return math.ceil(x * 10) / 10.0

    def _compute_cvss31(self, vector_string):
        parts = vector_string.replace("CVSS:3.1/", "").split("/")
        m = {}
        for p in parts:
            k, v = p.split(":")
            m[k] = v
        av = {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.20}[m["AV"]]
        ac = {"L": 0.77, "H": 0.44}[m["AC"]]
        ui = {"N": 0.85, "R": 0.62}[m["UI"]]
        cia = {"H": 0.56, "L": 0.22, "N": 0.0}
        scope = m["S"]
        pr = ({"N": 0.85, "L": 0.68, "H": 0.50} if scope == "C"
              else {"N": 0.85, "L": 0.62, "H": 0.27})[m["PR"]]
        c_v, i_v, a_v = cia[m["C"]], cia[m["I"]], cia[m["A"]]
        iss = 1 - (1 - c_v) * (1 - i_v) * (1 - a_v)
        if scope == "U":
            impact = 6.42 * iss
        else:
            impact = 7.52 * (iss - 0.029) - 3.25 * ((iss - 0.02) ** 15)
        exploit = 8.22 * av * ac * pr * ui
        if impact <= 0:
            return 0.0
        if scope == "U":
            return self._roundup(min(impact + exploit, 10.0))
        return self._roundup(min(1.08 * (impact + exploit), 10.0))

    def test_all_hmac_mismatches_detected(self, report, hmac_key, db_records):
        """Independently compute all HMACs; every mismatch must be reported
        and every match must not be reported."""
        reported = {r["cve_id"] for r in report["tampered_records"]}
        for cve_id, db in db_records.items():
            cpe_json = self._canonical_json(json.loads(db["cpe_config"]))
            computed = self._compute_hmac(
                hmac_key, cve_id, db["cvss_vector"],
                db["cvss_base_score"], db["cwe_id"], cpe_json
            )
            if computed != db["hmac_sha256"]:
                assert cve_id in reported, (
                    f"{cve_id}: HMAC mismatch not reported by solution"
                )
            else:
                assert cve_id not in reported, (
                    f"{cve_id}: no HMAC mismatch but incorrectly reported"
                )

    def test_reported_hmac_values_correct(self, report, hmac_key, db_records):
        """Verify the hmac_computed values match independent recomputation."""
        for rec in report["tampered_records"]:
            cve_id = rec["cve_id"]
            db = db_records[cve_id]
            cpe_json = self._canonical_json(json.loads(db["cpe_config"]))
            computed = self._compute_hmac(
                hmac_key, cve_id, db["cvss_vector"],
                db["cvss_base_score"], db["cwe_id"], cpe_json
            )
            assert rec["hmac_computed"] == computed, (
                f"{cve_id}: hmac_computed in report doesn't match "
                f"independently computed value"
            )

    def test_all_cvss_anomalies_detected(self, report, db_records):
        """Independently recompute all CVSS v3.1 scores; every divergence
        from stored score must be reported."""
        reported = {a["cve_id"] for a in report["score_anomalies"]}
        for cve_id, db in db_records.items():
            recomputed = self._compute_cvss31(db["cvss_vector"])
            if abs(recomputed - db["cvss_base_score"]) > 0.01:
                assert cve_id in reported, (
                    f"{cve_id}: CVSS anomaly (stored={db['cvss_base_score']}, "
                    f"recomputed={recomputed}) not reported"
                )
            else:
                assert cve_id not in reported, (
                    f"{cve_id}: no CVSS anomaly but reported"
                )

    def test_reported_cvss_scores_correct(self, report, db_records):
        """Verify computed_score values match independent CVSS recomputation."""
        for anomaly in report["score_anomalies"]:
            vector = db_records[anomaly["cve_id"]]["cvss_vector"]
            recomputed = self._compute_cvss31(vector)
            assert abs(anomaly["computed_score"] - recomputed) < 0.05, (
                f"{anomaly['cve_id']}: computed_score={anomaly['computed_score']} "
                f"but independent recomputation gives {recomputed}"
            )

    def test_all_cpe_discrepancies_detected(self, report, db_records, canonical_data):
        """Independently compare DB CPE configs against canonical for all CVEs."""
        reported = {d["cve_id"] for d in report["cpe_discrepancies"]}
        for cve_id in canonical_data:
            db_cpe = self._canonical_json(json.loads(db_records[cve_id]["cpe_config"]))
            canon_cpe = self._canonical_json(canonical_data[cve_id]["configurations"])
            if db_cpe != canon_cpe:
                assert cve_id in reported, (
                    f"{cve_id}: CPE discrepancy not reported"
                )
            else:
                assert cve_id not in reported, (
                    f"{cve_id}: no CPE discrepancy but reported"
                )

    def test_all_cwe_errors_detected(self, report, db_records, canonical_data):
        """Independently compare DB CWE mappings against canonical for all CVEs."""
        reported = {e["cve_id"] for e in report["cwe_errors"]}
        for cve_id in canonical_data:
            canon_cwe = canonical_data[cve_id]["weaknesses"][0]["description"][0]["value"]
            db_cwe = db_records[cve_id]["cwe_id"]
            if db_cwe != canon_cwe:
                assert cve_id in reported, (
                    f"{cve_id}: CWE error not reported"
                )
            else:
                assert cve_id not in reported, (
                    f"{cve_id}: no CWE error but reported"
                )

    def test_kev_statuses_match_catalog(self, report, kev_cves):
        """Verify reported KEV statuses by cross-referencing the catalog."""
        for item in report["threat_priority"]:
            expected = any(cve in kev_cves for cve in item["matched_cves"])
            assert item["in_kev"] == expected, (
                f"{item['product']} {item['version']}: "
                f"in_kev should be {expected}"
            )

    def test_epss_scores_match_feed(self, report, epss_data):
        """Verify reported EPSS scores by reading the CSV feed directly."""
        for item in report["threat_priority"]:
            max_epss = max(epss_data.get(cve, 0.0) for cve in item["matched_cves"])
            assert abs(item["epss_score"] - max_epss) < 0.001, (
                f"{item['product']} {item['version']}: "
                f"epss_score={item['epss_score']} but feed gives {max_epss}"
            )

    def test_priority_formula_correct(self, report):
        """Verify priority_score = cvss_score * epss_score * kev_multiplier."""
        for item in report["threat_priority"]:
            kev_mult = 2.0 if item["in_kev"] else 1.0
            expected = item["cvss_score"] * item["epss_score"] * kev_mult
            assert abs(item["priority_score"] - expected) < 0.01, (
                f"{item['product']} {item['version']}: priority_score should "
                f"be {expected}, got {item['priority_score']}"
            )

    def test_risk_score_is_cvss_sum(self, report):
        """Verify risk_score equals sum of cvss_score across vulnerable items."""
        computed = sum(item["cvss_score"] for item in report["threat_priority"])
        assert abs(report["summary"]["risk_score"] - computed) < 0.15
