
import json
import os
import subprocess
import pytest


def load_assessment():
    with open("/app/assessment.json") as f:
        return json.load(f)


def find_item(data, vendor, product, version):
    """Find an assessed item by vendor/product/version."""
    for item in data["assessed_items"]:
        if (item["vendor"] == vendor and
                item["product"] == product and
                item["version"] == version):
            return item
    return None


def get_cve_ids(item):
    """Get sorted list of CVE IDs for an assessed item."""
    if item is None or "cves" not in item:
        return []
    return sorted([c["id"] for c in item["cves"]])


class TestAssessmentFileExists:
    def test_assessment_json_exists(self):
        assert os.path.exists("/app/assessment.json"), \
            "assessment.json not found at /app/"

    def test_cvss_calc_exists(self):
        assert os.path.exists("/app/cvss_calc.py"), \
            "cvss_calc.py not found at /app/"


class TestCVSSCalculator:
    """Test the standalone CVSS v3.1 calculator with vectors both from
    the dataset and NOT from the dataset (to prevent hardcoding)."""

    VECTORS = [
        # From the dataset
        ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H", 10.0),
        ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", 9.8),
        ("CVSS:3.1/AV:N/AC:L/PR:H/UI:N/S:C/C:H/I:H/A:H", 9.1),
        ("CVSS:3.1/AV:L/AC:H/PR:L/UI:N/S:U/C:H/I:H/A:H", 7.0),
        ("CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:U/C:H/I:N/A:N", 5.9),
        # NOT from the dataset — agent must implement the calculator
        ("CVSS:3.1/AV:P/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", 6.8),
        ("CVSS:3.1/AV:L/AC:L/PR:N/UI:R/S:U/C:H/I:H/A:H", 7.8),
        ("CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:C/C:L/I:L/A:N", 6.4),
    ]

    @pytest.mark.parametrize("vector,expected", VECTORS)
    def test_cvss_score(self, vector, expected):
        result = subprocess.run(
            ["python3", "/app/cvss_calc.py", vector],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, \
            f"cvss_calc.py failed for {vector}: {result.stderr}"
        score = float(result.stdout.strip())
        assert abs(score - expected) < 0.05, \
            f"CVSS score for {vector}: expected {expected}, got {score}"


class TestCVEMatching:
    """Test that the correct CVEs are matched to the correct inventory items."""

    def test_log4j_214_has_two_cves(self):
        data = load_assessment()
        item = find_item(data, "apache", "log4j", "2.14.0")
        assert item is not None, "log4j 2.14.0 not found in assessment"
        cve_ids = get_cve_ids(item)
        assert "CVE-2024-28001" in cve_ids, \
            f"CVE-2024-28001 should affect log4j 2.14.0, got {cve_ids}"
        assert "CVE-2024-28010" in cve_ids, \
            f"CVE-2024-28010 should affect log4j 2.14.0, got {cve_ids}"
        assert len(cve_ids) == 2, \
            f"log4j 2.14.0 should have exactly 2 CVEs, got {len(cve_ids)}"

    def test_openssl_101c_affected(self):
        data = load_assessment()
        item = find_item(data, "openssl", "openssl", "1.0.1c")
        assert item is not None
        cve_ids = get_cve_ids(item)
        assert cve_ids == ["CVE-2024-28002"], \
            f"openssl 1.0.1c: expected [CVE-2024-28002], got {cve_ids}"

    def test_openssl_111k_affected(self):
        data = load_assessment()
        item = find_item(data, "openssl", "openssl", "1.1.1k")
        assert item is not None
        cve_ids = get_cve_ids(item)
        assert cve_ids == ["CVE-2024-28007"], \
            f"openssl 1.1.1k: expected [CVE-2024-28007], got {cve_ids}"

    def test_bash_42_affected(self):
        data = load_assessment()
        item = find_item(data, "gnu", "bash", "4.2")
        assert item is not None
        cve_ids = get_cve_ids(item)
        assert cve_ids == ["CVE-2024-28003"], \
            f"bash 4.2: expected [CVE-2024-28003], got {cve_ids}"

    def test_kernel_482_affected(self):
        data = load_assessment()
        item = find_item(data, "linux", "linux_kernel", "4.8.2")
        assert item is not None
        cve_ids = get_cve_ids(item)
        assert cve_ids == ["CVE-2024-28004"], \
            f"kernel 4.8.2: expected [CVE-2024-28004], got {cve_ids}"

    def test_httpd_2449_affected(self):
        data = load_assessment()
        item = find_item(data, "apache", "http_server", "2.4.49")
        assert item is not None
        cve_ids = get_cve_ids(item)
        assert cve_ids == ["CVE-2024-28005"], \
            f"http_server 2.4.49: expected [CVE-2024-28005], got {cve_ids}"

    def test_exchange_20191_affected(self):
        data = load_assessment()
        item = find_item(data, "microsoft", "exchange_server", "2019.1")
        assert item is not None
        cve_ids = get_cve_ids(item)
        assert cve_ids == ["CVE-2024-28006"], \
            f"exchange 2019.1: expected [CVE-2024-28006], got {cve_ids}"

    def test_nginx_1201_affected(self):
        data = load_assessment()
        item = find_item(data, "nginx", "nginx", "1.20.1")
        assert item is not None
        cve_ids = get_cve_ids(item)
        assert cve_ids == ["CVE-2024-28008"], \
            f"nginx 1.20.1: expected [CVE-2024-28008], got {cve_ids}"

    def test_redis_608_affected(self):
        data = load_assessment()
        item = find_item(data, "redis", "redis", "6.0.8")
        assert item is not None
        cve_ids = get_cve_ids(item)
        assert cve_ids == ["CVE-2024-28009"], \
            f"redis 6.0.8: expected [CVE-2024-28009], got {cve_ids}"


class TestUnaffectedItems:
    """Test that items outside vulnerable version ranges are not matched."""

    def test_bash_50_not_affected(self):
        data = load_assessment()
        item = find_item(data, "gnu", "bash", "5.0")
        assert item is not None
        cve_ids = get_cve_ids(item)
        assert len(cve_ids) == 0, \
            f"bash 5.0 should have no CVEs, got {cve_ids}"

    def test_log4j_2170_not_affected(self):
        data = load_assessment()
        item = find_item(data, "apache", "log4j", "2.17.0")
        assert item is not None
        cve_ids = get_cve_ids(item)
        assert len(cve_ids) == 0, \
            f"log4j 2.17.0 should have no CVEs, got {cve_ids}"

    def test_postgresql_132_not_affected(self):
        data = load_assessment()
        item = find_item(data, "postgresql", "postgresql", "13.2")
        assert item is not None
        cve_ids = get_cve_ids(item)
        assert len(cve_ids) == 0, \
            f"postgresql 13.2 should have no CVEs, got {cve_ids}"


class TestSeverityLabels:
    """Verify severity classification for CVEs in the assessment."""

    EXPECTED_SEVERITIES = {
        "CVE-2024-28001": "CRITICAL",  # 10.0
        "CVE-2024-28002": "HIGH",      # 7.5
        "CVE-2024-28003": "CRITICAL",  # 9.8
        "CVE-2024-28004": "HIGH",      # 7.0
        "CVE-2024-28005": "CRITICAL",  # 9.8
        "CVE-2024-28006": "HIGH",      # 8.8
        "CVE-2024-28007": "MEDIUM",    # 5.9
        "CVE-2024-28008": "MEDIUM",    # 6.1
        "CVE-2024-28009": "CRITICAL",  # 9.1
        "CVE-2024-28010": "HIGH",      # 7.4
    }

    def test_severity_labels(self):
        data = load_assessment()
        for item in data["assessed_items"]:
            for cve in item.get("cves", []):
                cve_id = cve["id"]
                if cve_id in self.EXPECTED_SEVERITIES:
                    expected = self.EXPECTED_SEVERITIES[cve_id]
                    assert cve["severity"] == expected, \
                        f"{cve_id}: expected severity {expected}, got {cve['severity']}"


class TestScoresInAssessment:
    """Verify CVSS scores in the assessment output."""

    EXPECTED_SCORES = {
        "CVE-2024-28001": 10.0,
        "CVE-2024-28002": 7.5,
        "CVE-2024-28003": 9.8,
        "CVE-2024-28004": 7.0,
        "CVE-2024-28005": 9.8,
        "CVE-2024-28006": 8.8,
        "CVE-2024-28007": 5.9,
        "CVE-2024-28008": 6.1,
        "CVE-2024-28009": 9.1,
        "CVE-2024-28010": 7.4,
    }

    def test_cvss_scores_in_assessment(self):
        data = load_assessment()
        for item in data["assessed_items"]:
            for cve in item.get("cves", []):
                cve_id = cve["id"]
                if cve_id in self.EXPECTED_SCORES:
                    expected = self.EXPECTED_SCORES[cve_id]
                    actual = cve["cvss_v3_1_score"]
                    assert abs(actual - expected) < 0.05, \
                        f"{cve_id}: expected score {expected}, got {actual}"


class TestRiskScores:
    """Verify risk_score (max CVSS) for each inventory item."""

    def test_log4j_214_risk(self):
        data = load_assessment()
        item = find_item(data, "apache", "log4j", "2.14.0")
        assert abs(item["risk_score"] - 10.0) < 0.05

    def test_unaffected_risk_zero(self):
        data = load_assessment()
        for vendor, product, version in [
            ("gnu", "bash", "5.0"),
            ("apache", "log4j", "2.17.0"),
            ("postgresql", "postgresql", "13.2"),
        ]:
            item = find_item(data, vendor, product, version)
            assert item is not None
            assert item["risk_score"] == 0.0, \
                f"{vendor}:{product}:{version} risk_score should be 0.0"


class TestStatistics:
    """Verify aggregate statistics in the assessment."""

    def test_total_items(self):
        data = load_assessment()
        assert data["statistics"]["total_items"] == 12

    def test_affected_items(self):
        data = load_assessment()
        assert data["statistics"]["affected_items"] == 9

    def test_unaffected_items(self):
        data = load_assessment()
        assert data["statistics"]["unaffected_items"] == 3

    def test_total_cve_matches(self):
        data = load_assessment()
        assert data["statistics"]["total_cve_matches"] == 10

    def test_severity_counts(self):
        data = load_assessment()
        sev = data["statistics"]["by_severity"]
        assert sev["CRITICAL"] == 4, f"Expected 4 CRITICAL, got {sev['CRITICAL']}"
        assert sev["HIGH"] == 4, f"Expected 4 HIGH, got {sev['HIGH']}"
        assert sev["MEDIUM"] == 2, f"Expected 2 MEDIUM, got {sev['MEDIUM']}"
        assert sev["LOW"] == 0, f"Expected 0 LOW, got {sev['LOW']}"


class TestCWEClassification:
    """Verify CWE IDs are correctly extracted."""

    def test_single_cwe(self):
        data = load_assessment()
        item = find_item(data, "gnu", "bash", "4.2")
        cve = [c for c in item["cves"] if c["id"] == "CVE-2024-28003"][0]
        assert "CWE-78" in cve["cwes"], \
            f"CVE-2024-28003 should have CWE-78, got {cve['cwes']}"

    def test_multiple_cwes(self):
        data = load_assessment()
        item = find_item(data, "redis", "redis", "6.0.8")
        cve = [c for c in item["cves"] if c["id"] == "CVE-2024-28009"][0]
        cwes = sorted(cve["cwes"])
        assert "CWE-502" in cwes, \
            f"CVE-2024-28009 should have CWE-502, got {cwes}"
        assert "CWE-20" in cwes, \
            f"CVE-2024-28009 should have CWE-20, got {cwes}"
