
"""
Tests for GLEIF Ownership Chain Forensics.
Verifies the output at /app/output/forensics.json against authoritative GLEIF data,
ownership topology, relationship quality metadata, and cluster analytics.
"""

import json
import os
import pytest


@pytest.fixture(scope="module")
def report():
    path = "/app/output/forensics.json"
    assert os.path.exists(path), f"Output file {path} does not exist"
    with open(path) as f:
        data = json.load(f)
    return data


@pytest.fixture(scope="module")
def entities_by_id(report):
    return {e["id"]: e for e in report["entities"]}


@pytest.fixture(scope="module")
def entities_by_lei(report):
    return {e["resolved_lei"]: e for e in report["entities"] if e["resolved_lei"]}


# ---------- Output structure tests ----------

class TestOutputStructure:
    def test_has_top_level_keys(self, report):
        for key in ["entities", "clusters", "unresolved", "summary"]:
            assert key in report, f"Missing top-level key '{key}'"

    def test_entity_count(self, report):
        assert len(report["entities"]) == 8

    def test_entity_required_fields(self, report):
        required = [
            "id", "input_identifier", "input_type", "resolved_lei",
            "resolution_method", "entity_name", "jurisdiction",
            "parent_chain", "chain_depth", "claimed_ultimate_parent_lei",
            "chain_consistent", "isin_count", "direct_children_count",
            "corroboration_level", "relationship_registration_status",
            "has_reporting_exception", "exception_reason",
            "bic_codes", "entity_status", "registration_status",
            "conformity_flag",
        ]
        for ent in report["entities"]:
            for field in required:
                assert field in ent, (
                    f"Missing field '{field}' in entity {ent.get('id', '?')}"
                )

    def test_cluster_required_fields(self, report):
        required = [
            "member_ids", "member_leis", "jurisdictions",
            "max_chain_depth", "total_isin_exposure", "total_direct_children",
            "data_quality_score",
        ]
        for key, cluster in report["clusters"].items():
            for field in required:
                assert field in cluster, (
                    f"Missing field '{field}' in cluster {key}"
                )

    def test_summary_required_fields(self, report):
        required = [
            "total_entries", "resolved_count", "unresolved_count",
            "cluster_count", "entities_with_parents", "total_chain_depth",
            "total_isin_exposure", "total_direct_children",
        ]
        for field in required:
            assert field in report["summary"], f"Missing summary field '{field}'"


# ---------- Multi-format identifier resolution tests ----------

class TestIdentifierResolution:
    """Tests that LEI/BIC/name identifiers are resolved correctly."""

    def test_lei_checksum_validated(self, entities_by_id):
        for eid in ["E1", "E3", "E5", "E7"]:
            e = entities_by_id[eid]
            assert e["checksum_valid"] is True, (
                f"{eid} should have valid checksum"
            )
            assert e["resolution_method"] == "checksum_validated"
            assert e["resolved_lei"] is not None

    def test_lei_resolution_preserves_identifier(self, entities_by_id):
        assert entities_by_id["E1"]["resolved_lei"] == "784F5XWPLTWKTBV3E584"
        assert entities_by_id["E3"]["resolved_lei"] == "HWUPKR0MPOU8FGXBT394"
        assert entities_by_id["E5"]["resolved_lei"] == "549300RQT6K4WXZL3083"
        assert entities_by_id["E7"]["resolved_lei"] == "7LTWFZYICNSX8D621K86"

    def test_invalid_lei_detected(self, entities_by_id):
        for eid in ["E6", "E8"]:
            e = entities_by_id[eid]
            assert e["checksum_valid"] is False, (
                f"{eid} should have invalid checksum"
            )
            assert e["resolution_method"] == "invalid"
            assert e["resolved_lei"] is None

    def test_bic_resolution(self, entities_by_id):
        e2 = entities_by_id["E2"]
        assert e2["resolution_method"] == "bic_lookup"
        assert e2["resolved_lei"] == "FOR8UP27PHTHYVLBNG30"
        assert e2["input_type"] == "bic"
        assert e2["checksum_valid"] is None

    def test_name_resolution(self, entities_by_id):
        e4 = entities_by_id["E4"]
        assert e4["resolution_method"] == "fulltext_search"
        assert e4["resolved_lei"] == "INR2EJN1ERAN0W5ZP974"
        assert e4["input_type"] == "name"
        assert e4["checksum_valid"] is None

    def test_unresolved_list(self, report):
        assert "E6" in report["unresolved"]
        assert "E8" in report["unresolved"]
        assert len(report["unresolved"]) == 2


# ---------- Entity data tests ----------

class TestEntityData:
    """Tests that resolved entity attributes match authoritative GLEIF records."""

    EXPECTED = {
        "784F5XWPLTWKTBV3E584": {
            "name": "THE GOLDMAN SACHS GROUP, INC.",
            "jurisdiction": "US-DE",
        },
        "FOR8UP27PHTHYVLBNG30": {
            "name": "GOLDMAN SACHS & CO. LLC",
            "jurisdiction": "US-NY",
        },
        "HWUPKR0MPOU8FGXBT394": {
            "name": "Apple Inc.",
            "jurisdiction": "US-CA",
        },
        "INR2EJN1ERAN0W5ZP974": {
            "name": "MICROSOFT CORPORATION",
            "jurisdiction": "US-WA",
        },
        "549300RQT6K4WXZL3083": {
            "name": "GOLDMAN SACHS GROUP UK LIMITED",
            "jurisdiction": "GB",
        },
    }

    def test_entity_names(self, entities_by_lei):
        for lei, expected in self.EXPECTED.items():
            actual = entities_by_lei[lei]["entity_name"]
            assert actual == expected["name"], (
                f"Name mismatch for {lei}: expected '{expected['name']}', "
                f"got '{actual}'"
            )

    def test_entity_jurisdictions(self, entities_by_lei):
        for lei, expected in self.EXPECTED.items():
            actual = entities_by_lei[lei]["jurisdiction"]
            assert actual == expected["jurisdiction"], (
                f"Jurisdiction mismatch for {lei}: "
                f"expected '{expected['jurisdiction']}', got '{actual}'"
            )

    def test_entity_statuses_active(self, entities_by_lei):
        for lei in self.EXPECTED:
            assert entities_by_lei[lei]["entity_status"] == "ACTIVE"

    def test_invalid_entities_null(self, entities_by_id):
        for eid in ["E6", "E8"]:
            e = entities_by_id[eid]
            assert e["entity_name"] is None
            assert e["jurisdiction"] is None
            assert e["entity_status"] is None

    def test_deutsche_bank_resolved(self, entities_by_lei):
        db = entities_by_lei["7LTWFZYICNSX8D621K86"]
        assert db["entity_name"] is not None
        assert "DEUTSCHE BANK" in db["entity_name"].upper()

    def test_bic_codes_are_lists(self, entities_by_lei):
        for lei in self.EXPECTED:
            bics = entities_by_lei[lei]["bic_codes"]
            assert isinstance(bics, list), (
                f"bic_codes for {lei} should be a list"
            )

    def test_gs_co_has_expected_bic(self, entities_by_lei):
        bics = entities_by_lei["FOR8UP27PHTHYVLBNG30"]["bic_codes"]
        assert "GOLDUS33XXX" in bics

    def test_conformity_flag_present(self, entities_by_lei):
        for lei in self.EXPECTED:
            assert entities_by_lei[lei]["conformity_flag"] is not None


# ---------- Parent chain traversal tests ----------

class TestParentChains:
    """Tests recursive parent chain building and consistency verification."""

    GS_GROUP_LEI = "784F5XWPLTWKTBV3E584"

    def test_top_level_no_chain(self, entities_by_lei):
        for lei in [self.GS_GROUP_LEI, "HWUPKR0MPOU8FGXBT394"]:
            e = entities_by_lei[lei]
            assert e["chain_depth"] == 0, (
                f"{lei} should have chain_depth 0, got {e['chain_depth']}"
            )
            assert len(e["parent_chain"]) == 0

    def test_gs_subsidiaries_have_chain(self, entities_by_lei):
        for lei in ["FOR8UP27PHTHYVLBNG30", "549300RQT6K4WXZL3083"]:
            e = entities_by_lei[lei]
            assert e["chain_depth"] >= 1, (
                f"{lei} should have chain_depth >= 1"
            )
            assert len(e["parent_chain"]) >= 1

    def test_gs_subsidiaries_chain_terminates_at_gs_group(self, entities_by_lei):
        for lei in ["FOR8UP27PHTHYVLBNG30", "549300RQT6K4WXZL3083"]:
            e = entities_by_lei[lei]
            chain = e["parent_chain"]
            assert chain[-1] == self.GS_GROUP_LEI, (
                f"Chain for {lei} should terminate at GS Group, "
                f"got {chain[-1]}"
            )

    def test_gs_subsidiaries_ultimate_parent(self, entities_by_lei):
        for lei in ["FOR8UP27PHTHYVLBNG30", "549300RQT6K4WXZL3083"]:
            e = entities_by_lei[lei]
            assert e["claimed_ultimate_parent_lei"] == self.GS_GROUP_LEI

    def test_chain_consistency_all_resolved(self, report):
        for ent in report["entities"]:
            if ent["resolved_lei"] is not None:
                assert ent["chain_consistent"] is True, (
                    f"Chain should be consistent for {ent['id']} "
                    f"({ent['resolved_lei']})"
                )

    def test_top_level_ultimate_parent_is_self(self, entities_by_lei):
        for lei in [
            self.GS_GROUP_LEI,
            "HWUPKR0MPOU8FGXBT394",
            "INR2EJN1ERAN0W5ZP974",
        ]:
            e = entities_by_lei[lei]
            assert e["claimed_ultimate_parent_lei"] == lei, (
                f"Top-level entity {lei} ultimate parent should be itself"
            )

    def test_parent_chain_is_list_of_leis(self, report):
        for ent in report["entities"]:
            chain = ent["parent_chain"]
            assert isinstance(chain, list)
            for item in chain:
                assert isinstance(item, str) and len(item) == 20

    def test_chain_depth_equals_chain_length(self, report):
        for ent in report["entities"]:
            assert ent["chain_depth"] == len(ent["parent_chain"]), (
                f"chain_depth should equal len(parent_chain) for {ent['id']}"
            )

    def test_invalid_lei_no_chain(self, entities_by_id):
        for eid in ["E6", "E8"]:
            e = entities_by_id[eid]
            assert e["chain_depth"] == 0
            assert len(e["parent_chain"]) == 0


# ---------- Relationship quality tests ----------

class TestRelationshipQuality:
    """Tests corroboration level extraction from parent relationship records."""

    VALID_CORROBORATION = {
        "ENTITY_SUPPLIED_ONLY",
        "PARTIALLY_CORROBORATED",
        "FULLY_CORROBORATED",
    }
    VALID_REG_STATUSES = {
        "PUBLISHED", "LAPSED", "PENDING_TRANSFER",
        "PENDING_ARCHIVAL", "RETIRED",
    }

    def test_subsidiaries_have_corroboration(self, entities_by_lei):
        for lei in ["FOR8UP27PHTHYVLBNG30", "549300RQT6K4WXZL3083"]:
            e = entities_by_lei[lei]
            assert e["corroboration_level"] is not None, (
                f"{lei} should have corroboration_level"
            )
            assert e["corroboration_level"] in self.VALID_CORROBORATION, (
                f"Invalid corroboration_level for {lei}: "
                f"'{e['corroboration_level']}'"
            )

    def test_subsidiaries_have_relationship_status(self, entities_by_lei):
        for lei in ["FOR8UP27PHTHYVLBNG30", "549300RQT6K4WXZL3083"]:
            e = entities_by_lei[lei]
            assert e["relationship_registration_status"] is not None, (
                f"{lei} should have relationship_registration_status"
            )
            assert e["relationship_registration_status"] in self.VALID_REG_STATUSES

    def test_top_level_no_corroboration(self, entities_by_lei):
        for lei in ["784F5XWPLTWKTBV3E584", "HWUPKR0MPOU8FGXBT394"]:
            e = entities_by_lei[lei]
            assert e["corroboration_level"] is None
            assert e["relationship_registration_status"] is None


# ---------- Reporting exception tests ----------

class TestReportingExceptions:
    """Tests reporting exception detection for parentless entities."""

    def test_top_level_exception_field_present(self, entities_by_lei):
        for lei in [
            "784F5XWPLTWKTBV3E584",
            "HWUPKR0MPOU8FGXBT394",
            "INR2EJN1ERAN0W5ZP974",
        ]:
            e = entities_by_lei[lei]
            assert "has_reporting_exception" in e
            assert isinstance(e["has_reporting_exception"], bool)

    def test_subsidiaries_no_exception(self, entities_by_lei):
        for lei in ["FOR8UP27PHTHYVLBNG30", "549300RQT6K4WXZL3083"]:
            e = entities_by_lei[lei]
            assert e["has_reporting_exception"] is False

    def test_invalid_entities_no_exception(self, entities_by_id):
        for eid in ["E6", "E8"]:
            assert entities_by_id[eid]["has_reporting_exception"] is False


# ---------- Count metric tests ----------

class TestCountMetrics:
    """Tests paginated ISIN and subsidiary count retrieval."""

    def test_gs_group_children(self, entities_by_lei):
        count = entities_by_lei["784F5XWPLTWKTBV3E584"]["direct_children_count"]
        assert count >= 150, (
            f"GS Group should have >= 150 direct children, got {count}"
        )

    def test_gs_group_isins(self, entities_by_lei):
        count = entities_by_lei["784F5XWPLTWKTBV3E584"]["isin_count"]
        assert count >= 5000, (
            f"GS Group should have >= 5000 ISINs, got {count}"
        )

    def test_microsoft_children(self, entities_by_lei):
        count = entities_by_lei["INR2EJN1ERAN0W5ZP974"]["direct_children_count"]
        assert count >= 10, (
            f"Microsoft should have >= 10 direct children, got {count}"
        )

    def test_invalid_entities_zero_counts(self, entities_by_id):
        for eid in ["E6", "E8"]:
            e = entities_by_id[eid]
            assert e["isin_count"] == 0
            assert e["direct_children_count"] == 0


# ---------- Cluster tests ----------

class TestClusters:
    """Tests ownership cluster grouping and metric computation."""

    GS_GROUP_LEI = "784F5XWPLTWKTBV3E584"

    def test_cluster_count(self, report):
        assert report["summary"]["cluster_count"] == 4

    def test_clusters_is_dict(self, report):
        assert isinstance(report["clusters"], dict)

    def test_gs_cluster_exists(self, report):
        assert self.GS_GROUP_LEI in report["clusters"]

    def test_gs_cluster_member_ids(self, report):
        gs = report["clusters"][self.GS_GROUP_LEI]
        member_ids = gs["member_ids"]
        assert "E1" in member_ids
        assert "E2" in member_ids
        assert "E5" in member_ids
        assert len(member_ids) == 3

    def test_gs_cluster_member_leis(self, report):
        gs = report["clusters"][self.GS_GROUP_LEI]
        leis = gs["member_leis"]
        assert "784F5XWPLTWKTBV3E584" in leis
        assert "FOR8UP27PHTHYVLBNG30" in leis
        assert "549300RQT6K4WXZL3083" in leis

    def test_gs_cluster_jurisdictions(self, report):
        gs = report["clusters"][self.GS_GROUP_LEI]
        jurisdictions = gs["jurisdictions"]
        assert isinstance(jurisdictions, list)
        assert "US-DE" in jurisdictions
        assert "US-NY" in jurisdictions
        assert "GB" in jurisdictions

    def test_gs_cluster_max_depth(self, report):
        gs = report["clusters"][self.GS_GROUP_LEI]
        assert gs["max_chain_depth"] >= 1

    def test_gs_cluster_isin_exposure(self, report):
        gs = report["clusters"][self.GS_GROUP_LEI]
        assert gs["total_isin_exposure"] >= 5000

    def test_gs_cluster_children(self, report):
        gs = report["clusters"][self.GS_GROUP_LEI]
        assert gs["total_direct_children"] >= 150

    def test_gs_cluster_data_quality_score(self, report):
        gs = report["clusters"][self.GS_GROUP_LEI]
        dqs = gs["data_quality_score"]
        assert dqs is not None, "GS cluster should have DQS (has parent relationships)"
        assert 0.0 <= dqs <= 1.0

    def test_singleton_cluster_apple(self, report):
        apple_lei = "HWUPKR0MPOU8FGXBT394"
        assert apple_lei in report["clusters"]
        assert len(report["clusters"][apple_lei]["member_ids"]) == 1
        assert report["clusters"][apple_lei]["data_quality_score"] is None

    def test_singleton_cluster_microsoft(self, report):
        msft_lei = "INR2EJN1ERAN0W5ZP974"
        assert msft_lei in report["clusters"]
        assert len(report["clusters"][msft_lei]["member_ids"]) == 1
        assert report["clusters"][msft_lei]["data_quality_score"] is None

    def test_deutsche_bank_in_some_cluster(self, report):
        db_lei = "7LTWFZYICNSX8D621K86"
        found = False
        for cluster in report["clusters"].values():
            if db_lei in cluster["member_leis"]:
                found = True
                break
        assert found, "Deutsche Bank should appear in some cluster"

    def test_data_quality_scores_in_range(self, report):
        for key, cluster in report["clusters"].items():
            dqs = cluster["data_quality_score"]
            if dqs is not None:
                assert 0.0 <= dqs <= 1.0, (
                    f"DQS for cluster {key} out of range: {dqs}"
                )

    def test_jurisdictions_sorted(self, report):
        for key, cluster in report["clusters"].items():
            jur = cluster["jurisdictions"]
            assert jur == sorted(jur), (
                f"Jurisdictions for cluster {key} should be sorted"
            )


# ---------- Summary consistency tests ----------

class TestSummaryConsistency:
    """Tests arithmetic consistency of summary statistics."""

    def test_total_entries(self, report):
        assert report["summary"]["total_entries"] == 8

    def test_resolved_count(self, report):
        assert report["summary"]["resolved_count"] == 6

    def test_unresolved_count(self, report):
        assert report["summary"]["unresolved_count"] == 2

    def test_resolved_plus_unresolved_equals_total(self, report):
        s = report["summary"]
        assert s["resolved_count"] + s["unresolved_count"] == s["total_entries"]

    def test_cluster_count_matches_dict(self, report):
        assert report["summary"]["cluster_count"] == len(report["clusters"])

    def test_entities_with_parents(self, report):
        assert report["summary"]["entities_with_parents"] >= 2

    def test_isin_sum_consistency(self, report):
        computed = sum(
            e["isin_count"] for e in report["entities"]
            if e["resolved_lei"] is not None
        )
        assert computed == report["summary"]["total_isin_exposure"]

    def test_children_sum_consistency(self, report):
        computed = sum(
            e["direct_children_count"] for e in report["entities"]
            if e["resolved_lei"] is not None
        )
        assert computed == report["summary"]["total_direct_children"]

    def test_chain_depth_sum_consistency(self, report):
        computed = sum(
            e["chain_depth"] for e in report["entities"]
            if e["resolved_lei"] is not None
        )
        assert computed == report["summary"]["total_chain_depth"]

    def test_records_list_matches_total(self, report):
        assert len(report["entities"]) == report["summary"]["total_entries"]

    def test_cluster_members_sum_to_resolved(self, report):
        total_in_clusters = sum(
            len(c["member_ids"]) for c in report["clusters"].values()
        )
        assert total_in_clusters == report["summary"]["resolved_count"]
