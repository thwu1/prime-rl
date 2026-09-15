
import json
import os
import pytest

REPORT_PATH = "/app/output/report.json"

APPLE_LEI = "HWUPKR0MPOU8FGXBT394"
GS_LEI = "784F5XWPLTWKTBV3E584"
MS_LEI = "INR2EJN1ERAN0W5ZP974"

VALID_EXCEPTION_REASONS = {
    "NO_KNOWN_PERSON", "NATURAL_PERSONS",
    "NON_CONSOLIDATING", "NON_PUBLIC",
}
VALID_EXCEPTION_CATEGORIES = {
    "DIRECT_ACCOUNTING_CONSOLIDATION_PARENT",
    "ULTIMATE_ACCOUNTING_CONSOLIDATION_PARENT",
}


@pytest.fixture
def report():
    assert os.path.exists(REPORT_PATH), f"Report not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        return json.load(f)


def _lei(entry):
    return entry.get("lei", "") if isinstance(entry, dict) else str(entry)


# ─── Report structure ────────────────────────────────────────────────────────

class TestReportStructure:
    def test_report_exists(self):
        assert os.path.exists(REPORT_PATH)
        with open(REPORT_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_all_sections_present(self, report):
        required = {
            "checksum_validation", "registry_assessment", "ownership_topology",
            "metadata_discrepancies", "risk_classification", "summary",
        }
        missing = required - set(report.keys())
        assert not missing, f"Missing sections: {missing}"


# ─── Checksum validation ─────────────────────────────────────────────────────

class TestChecksumValidation:
    VALID_SET = {
        "HWUPKR0MPOU8FGXBT394", "784F5XWPLTWKTBV3E584",
        "INR2EJN1ERAN0W5ZP974", "549300L353AIX124FT40",
        "LOHX32U76Y88P6ZDFO91", "5493003GK0I4R67A1K76",
        "8EU8ZMZ2E88YR971GW85", "GGCMDC0OOHBLHHFALS29",
        "549300WCLFVEBTBNRF76", "213800JCN6PSGDRLT915",
        "549300EW6ZGTZTR6TO90", "5493002T25TVL3GUHD37",
        "549300F3N5K27RILT474",
    }
    INVALID_SET = {
        "HWUPKR0MPOU8FGXBT395", "784F5XWPLTWKTBV3E585",
        "XXXXXXXXXXXXXXXXXXXX", "A1B2C3D4E5F6G7H8I900", "SHORT123",
    }

    def test_valid_count(self, report):
        assert len(report["checksum_validation"]["valid_leis"]) == 13

    def test_invalid_count(self, report):
        assert len(report["checksum_validation"]["invalid_leis"]) == 5

    def test_all_valid_identified(self, report):
        found = set(report["checksum_validation"]["valid_leis"])
        missing = self.VALID_SET - found
        assert not missing, f"Missing valid LEIs: {missing}"

    def test_all_invalid_identified(self, report):
        found = {_lei(e) for e in report["checksum_validation"]["invalid_leis"]}
        missing = self.INVALID_SET - found
        assert not missing, f"Missing invalid LEIs: {missing}"

    def test_no_crossover(self, report):
        v = set(report["checksum_validation"]["valid_leis"])
        i = {_lei(e) for e in report["checksum_validation"]["invalid_leis"]}
        assert not (v & self.INVALID_SET), "Invalid LEI in valid set"
        assert not (i & self.VALID_SET), "Valid LEI in invalid set"

    def test_invalid_has_reason(self, report):
        for entry in report["checksum_validation"]["invalid_leis"]:
            assert isinstance(entry, dict), "invalid_leis entries must be objects"
            assert "lei" in entry, "invalid entry missing 'lei'"
            assert "reason" in entry, "invalid entry missing 'reason'"


# ─── Registry assessment ─────────────────────────────────────────────────────

class TestRegistryAssessment:
    REQUIRED_FIELDS = {
        "legal_name", "country", "jurisdiction", "registration_status",
        "conformity_flag", "corroboration_level", "managing_lou", "bic",
        "relationship_registration_status",
    }

    def test_all_valid_assessed(self, report):
        ents = report["registry_assessment"]["entities"]
        assert len(ents) == 13, f"Expected 13 entities, got {len(ents)}"

    def test_entity_fields_present(self, report):
        for lei, data in report["registry_assessment"]["entities"].items():
            missing = self.REQUIRED_FIELDS - set(data.keys())
            assert not missing, f"{lei} missing fields: {missing}"

    def test_apple_legal_name(self, report):
        apple = report["registry_assessment"]["entities"][APPLE_LEI]
        assert apple["legal_name"] == "Apple Inc."

    def test_apple_country(self, report):
        apple = report["registry_assessment"]["entities"][APPLE_LEI]
        assert apple["country"] == "US"

    def test_apple_jurisdiction(self, report):
        apple = report["registry_assessment"]["entities"][APPLE_LEI]
        assert apple["jurisdiction"] == "US-CA"

    def test_apple_registration_issued(self, report):
        apple = report["registry_assessment"]["entities"][APPLE_LEI]
        assert apple["registration_status"] == "ISSUED"

    def test_apple_conformity(self, report):
        apple = report["registry_assessment"]["entities"][APPLE_LEI]
        assert apple["conformity_flag"] == "CONFORMING"

    def test_apple_corroboration(self, report):
        apple = report["registry_assessment"]["entities"][APPLE_LEI]
        assert apple["corroboration_level"] == "FULLY_CORROBORATED"

    def test_apple_bic(self, report):
        apple = report["registry_assessment"]["entities"][APPLE_LEI]
        assert isinstance(apple["bic"], list)
        assert "APLEUS66XXX" in apple["bic"]

    def test_apple_no_parent_relationship(self, report):
        apple = report["registry_assessment"]["entities"][APPLE_LEI]
        assert apple["relationship_registration_status"] is None

    def test_gs_legal_name(self, report):
        gs = report["registry_assessment"]["entities"][GS_LEI]
        assert "GOLDMAN SACHS" in gs["legal_name"].upper()

    def test_gs_jurisdiction(self, report):
        gs = report["registry_assessment"]["entities"][GS_LEI]
        assert gs["jurisdiction"] == "US-DE"

    def test_gs_registration_issued(self, report):
        gs = report["registry_assessment"]["entities"][GS_LEI]
        assert gs["registration_status"] == "ISSUED"

    def test_gs_bic(self, report):
        gs = report["registry_assessment"]["entities"][GS_LEI]
        assert isinstance(gs["bic"], list)
        assert "GSGIUS31XXX" in gs["bic"]

    def test_ms_legal_name(self, report):
        ms = report["registry_assessment"]["entities"][MS_LEI]
        assert "MICROSOFT" in ms["legal_name"].upper()

    def test_ms_jurisdiction(self, report):
        ms = report["registry_assessment"]["entities"][MS_LEI]
        assert ms["jurisdiction"] == "US-WA"

    def test_ms_bic(self, report):
        ms = report["registry_assessment"]["entities"][MS_LEI]
        assert isinstance(ms["bic"], list)
        assert "MSFTUS66XXX" in ms["bic"]

    def test_gs_subsidiary_lapsed_relationship(self, report):
        """GS Finance Corp has LAPSED relationship registration."""
        ent = report["registry_assessment"]["entities"].get("549300L353AIX124FT40")
        assert ent is not None, "GS Finance Corp not in registry assessment"
        assert ent["relationship_registration_status"] == "LAPSED"

    def test_ms_subsidiary_published_relationship(self, report):
        """Microsoft Regional Sales Corp has PUBLISHED relationship."""
        ent = report["registry_assessment"]["entities"].get("549300WCLFVEBTBNRF76")
        assert ent is not None, "MS Regional Sales Corp not in registry assessment"
        assert ent["relationship_registration_status"] == "PUBLISHED"

    def test_managing_lou_present(self, report):
        for lei, data in report["registry_assessment"]["entities"].items():
            assert data["managing_lou"], f"{lei} missing managing_lou"


# ─── Ownership topology ──────────────────────────────────────────────────────

class TestOwnershipTopology:
    def test_at_least_two_conglomerates(self, report):
        assert len(report["ownership_topology"]["conglomerates"]) >= 2

    def test_gs_conglomerate_exists(self, report):
        conglos = report["ownership_topology"]["conglomerates"]
        gs = [c for c in conglos if c["ultimate_parent_lei"] == GS_LEI]
        assert len(gs) == 1, "GS conglomerate not found"

    def test_gs_conglomerate_subsidiaries(self, report):
        conglos = report["ownership_topology"]["conglomerates"]
        gs = [c for c in conglos if c["ultimate_parent_lei"] == GS_LEI][0]
        assert gs["subsidiary_count"] >= 5, \
            f"GS should have >= 5 subsidiaries, got {gs['subsidiary_count']}"
        assert len(gs["subsidiaries"]) == gs["subsidiary_count"]

    def test_ms_conglomerate_exists(self, report):
        conglos = report["ownership_topology"]["conglomerates"]
        ms = [c for c in conglos if c["ultimate_parent_lei"] == MS_LEI]
        assert len(ms) == 1, "MS conglomerate not found"

    def test_ms_conglomerate_subsidiaries(self, report):
        conglos = report["ownership_topology"]["conglomerates"]
        ms = [c for c in conglos if c["ultimate_parent_lei"] == MS_LEI][0]
        assert ms["subsidiary_count"] >= 2

    def test_apple_standalone(self, report):
        assert APPLE_LEI in report["ownership_topology"]["standalone_entities"]

    def test_conglomerate_structure(self, report):
        required = {
            "ultimate_parent_lei", "ultimate_parent_name", "subsidiaries",
            "subsidiary_count", "jurisdictions_spanned", "cross_border_links",
        }
        for c in report["ownership_topology"]["conglomerates"]:
            missing = required - set(c.keys())
            assert not missing, f"Conglomerate missing fields: {missing}"
            assert c["subsidiary_count"] == len(c["subsidiaries"])
            assert isinstance(c["jurisdictions_spanned"], list)
            assert isinstance(c["cross_border_links"], int)

    def test_gs_jurisdictions_spanned(self, report):
        conglos = report["ownership_topology"]["conglomerates"]
        gs = [c for c in conglos if c["ultimate_parent_lei"] == GS_LEI][0]
        assert len(gs["jurisdictions_spanned"]) >= 2, \
            f"GS should span >= 2 jurisdictions, got {gs['jurisdictions_spanned']}"

    def test_ms_jurisdictions_spanned(self, report):
        conglos = report["ownership_topology"]["conglomerates"]
        ms = [c for c in conglos if c["ultimate_parent_lei"] == MS_LEI][0]
        assert len(ms["jurisdictions_spanned"]) >= 2

    def test_gs_cross_border(self, report):
        conglos = report["ownership_topology"]["conglomerates"]
        gs = [c for c in conglos if c["ultimate_parent_lei"] == GS_LEI][0]
        assert gs["cross_border_links"] >= 1, \
            "GS should have >= 1 cross-border ownership link"

    def test_ms_cross_border(self, report):
        conglos = report["ownership_topology"]["conglomerates"]
        ms = [c for c in conglos if c["ultimate_parent_lei"] == MS_LEI][0]
        assert ms["cross_border_links"] >= 1

    def test_max_depth_positive(self, report):
        assert report["ownership_topology"]["max_depth"] >= 1

    # ─── Reporting exceptions ─────────────────────────────────────────────

    def test_reporting_exceptions_present(self, report):
        exc = report["ownership_topology"]["reporting_exceptions"]
        assert isinstance(exc, dict)
        assert len(exc) >= 3, \
            "At least Apple, GS, MS should have reporting exceptions"

    def test_apple_has_exception(self, report):
        exc = report["ownership_topology"]["reporting_exceptions"]
        assert APPLE_LEI in exc, "Apple should have a reporting exception"

    def test_gs_has_exception(self, report):
        exc = report["ownership_topology"]["reporting_exceptions"]
        assert GS_LEI in exc, "GS Group should have a reporting exception"

    def test_ms_has_exception(self, report):
        exc = report["ownership_topology"]["reporting_exceptions"]
        assert MS_LEI in exc, "Microsoft should have a reporting exception"

    def test_exception_structure(self, report):
        for lei, exc in report["ownership_topology"]["reporting_exceptions"].items():
            assert "exception_category" in exc, f"{lei} missing exception_category"
            assert "exception_reason" in exc, f"{lei} missing exception_reason"
            assert isinstance(exc["exception_category"], str)
            assert isinstance(exc["exception_reason"], str)
            assert len(exc["exception_category"]) > 0
            assert len(exc["exception_reason"]) > 0

    def test_exception_categories_valid(self, report):
        for lei, exc in report["ownership_topology"]["reporting_exceptions"].items():
            assert exc["exception_category"] in VALID_EXCEPTION_CATEGORIES, \
                f"{lei}: unexpected category '{exc['exception_category']}'"

    def test_exception_reasons_valid(self, report):
        for lei, exc in report["ownership_topology"]["reporting_exceptions"].items():
            assert exc["exception_reason"] in VALID_EXCEPTION_REASONS, \
                f"{lei}: unexpected reason '{exc['exception_reason']}'"


# ─── Metadata discrepancies ──────────────────────────────────────────────────

class TestMetadataDiscrepancies:
    def test_discrepancy_structure(self, report):
        required = {"lei", "field", "local_value", "registry_value"}
        for d in report["metadata_discrepancies"]["discrepancies"]:
            missing = required - set(d.keys())
            assert not missing, f"Discrepancy entry missing: {missing}"

    def test_gs_name_discrepancy(self, report):
        discs = report["metadata_discrepancies"]["discrepancies"]
        gs_name = [d for d in discs if d["lei"] == GS_LEI and d["field"] == "name"]
        assert len(gs_name) >= 1, \
            "GS should have name discrepancy (local 'Goldman Sachs Inc.' vs registry)"
        assert gs_name[0]["local_value"] == "Goldman Sachs Inc."

    def test_gs_jurisdiction_discrepancy(self, report):
        discs = report["metadata_discrepancies"]["discrepancies"]
        gs_j = [d for d in discs if d["lei"] == GS_LEI and d["field"] == "jurisdiction"]
        assert len(gs_j) >= 1, \
            "GS should have jurisdiction discrepancy (US-NY vs US-DE)"
        assert gs_j[0]["local_value"] == "US-NY"
        assert gs_j[0]["registry_value"] == "US-DE"

    def test_at_least_two_discrepancies(self, report):
        assert len(report["metadata_discrepancies"]["discrepancies"]) >= 2

    def test_valid_fields(self, report):
        valid = {"name", "country", "jurisdiction"}
        for d in report["metadata_discrepancies"]["discrepancies"]:
            assert d["field"] in valid, \
                f"Unexpected discrepancy field '{d['field']}'"


# ─── Risk classification ─────────────────────────────────────────────────────

class TestRiskClassification:
    def test_all_valid_classified(self, report):
        classifs = report["risk_classification"]["classifications"]
        assert len(classifs) == 13, \
            f"Expected 13 classifications, got {len(classifs)}"

    def test_classification_structure(self, report):
        for lei, c in report["risk_classification"]["classifications"].items():
            assert "risk_tier" in c, f"{lei} missing risk_tier"
            assert "risk_factors" in c, f"{lei} missing risk_factors"
            assert c["risk_tier"] in {"HIGH", "MEDIUM", "LOW"}, \
                f"{lei}: invalid tier '{c['risk_tier']}'"
            assert isinstance(c["risk_factors"], list)

    def test_apple_low_risk(self, report):
        """Apple: ISSUED, CONFORMING, FULLY_CORROBORATED, standalone, no discrepancies."""
        apple = report["risk_classification"]["classifications"][APPLE_LEI]
        assert apple["risk_tier"] == "LOW", \
            f"Apple should be LOW risk, got {apple}"

    def test_ms_low_risk(self, report):
        """Microsoft: ISSUED, CONFORMING, FULLY_CORROBORATED, standalone, no case-sensitive discrepancies."""
        ms = report["risk_classification"]["classifications"][MS_LEI]
        assert ms["risk_tier"] == "LOW", \
            f"Microsoft should be LOW risk, got {ms}"

    def test_gs_not_low_risk(self, report):
        """GS Group has metadata discrepancies and should not be LOW."""
        gs = report["risk_classification"]["classifications"][GS_LEI]
        assert gs["risk_tier"] != "LOW", \
            f"GS should not be LOW risk (has metadata discrepancies), got {gs}"
        assert len(gs["risk_factors"]) >= 1

    def test_gs_subsidiary_not_low(self, report):
        """GS Finance Corp has LAPSED relationship — should not be LOW."""
        c = report["risk_classification"]["classifications"]["549300L353AIX124FT40"]
        assert c["risk_tier"] != "LOW", \
            f"GS subsidiary with LAPSED relationship should not be LOW: {c}"
        assert len(c["risk_factors"]) >= 1

    def test_risk_tier_consistency(self, report):
        """Tier must follow the factor-count rule: HIGH ≥3, MEDIUM 1-2, LOW 0."""
        for lei, c in report["risk_classification"]["classifications"].items():
            n = len(c["risk_factors"])
            if n >= 3:
                expected = "HIGH"
            elif n >= 1:
                expected = "MEDIUM"
            else:
                expected = "LOW"
            assert c["risk_tier"] == expected, \
                f"{lei}: {n} factors should be {expected}, got {c['risk_tier']}"


# ─── Summary ─────────────────────────────────────────────────────────────────

class TestSummary:
    def test_total_entities(self, report):
        assert report["summary"]["total_entities"] == 18

    def test_valid_checksums(self, report):
        assert report["summary"]["valid_checksums"] == 13

    def test_invalid_checksums(self, report):
        assert report["summary"]["invalid_checksums"] == 5

    def test_conglomerate_count(self, report):
        assert report["summary"]["conglomerate_count"] >= 2

    def test_risk_counts_present(self, report):
        s = report["summary"]
        for k in ["high_risk_count", "medium_risk_count", "low_risk_count"]:
            assert k in s, f"Missing summary field: {k}"

    def test_risk_counts_sum_to_valid(self, report):
        s = report["summary"]
        total = s["high_risk_count"] + s["medium_risk_count"] + s["low_risk_count"]
        assert total == 13, f"Risk counts sum to {total}, expected 13"

    def test_consistency_with_sections(self, report):
        s = report["summary"]
        cv = report["checksum_validation"]
        ot = report["ownership_topology"]
        md = report["metadata_discrepancies"]
        rc = report["risk_classification"]
        assert s["valid_checksums"] == len(cv["valid_leis"])
        assert s["invalid_checksums"] == len(cv["invalid_leis"])
        assert s["conglomerate_count"] == len(ot["conglomerates"])
        assert s["discrepancy_count"] == len(md["discrepancies"])
        hi = sum(1 for c in rc["classifications"].values() if c["risk_tier"] == "HIGH")
        me = sum(1 for c in rc["classifications"].values() if c["risk_tier"] == "MEDIUM")
        lo = sum(1 for c in rc["classifications"].values() if c["risk_tier"] == "LOW")
        assert s["high_risk_count"] == hi
        assert s["medium_risk_count"] == me
        assert s["low_risk_count"] == lo
