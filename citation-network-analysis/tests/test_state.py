"""

Tests for the legal citation forensics audit.
"""

import json
import os
import pytest


REPORT_PATH = "/app/report.json"


@pytest.fixture(scope="module")
def report():
    assert os.path.exists(REPORT_PATH), f"Report file not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        data = json.load(f)
    return data


class TestReportStructure:
    """Verify the report has all required top-level keys and correct types."""

    def test_top_level_keys(self, report):
        required_keys = {
            "court_mapping",
            "citations_per_document",
            "id_resolutions",
            "scotus_shared",
            "reporter_frequency",
            "authority_hierarchy",
            "doctrinal_threads",
            "anomalies",
        }
        assert required_keys.issubset(set(report.keys())), (
            f"Missing keys: {required_keys - set(report.keys())}"
        )

    def test_court_mapping_is_dict(self, report):
        assert isinstance(report["court_mapping"], dict)

    def test_citations_per_document_is_dict(self, report):
        assert isinstance(report["citations_per_document"], dict)

    def test_id_resolutions_is_dict(self, report):
        assert isinstance(report["id_resolutions"], dict)

    def test_scotus_shared_is_list(self, report):
        assert isinstance(report["scotus_shared"], list)

    def test_reporter_frequency_is_dict(self, report):
        assert isinstance(report["reporter_frequency"], dict)

    def test_authority_hierarchy_is_dict(self, report):
        assert isinstance(report["authority_hierarchy"], dict)

    def test_doctrinal_threads_is_list(self, report):
        assert isinstance(report["doctrinal_threads"], list)

    def test_anomalies_is_dict(self, report):
        assert isinstance(report["anomalies"], dict)
        assert "orphan_id_citations" in report["anomalies"]
        assert "court_reporter_mismatches" in report["anomalies"]
        assert "abrogation_risks" in report["anomalies"]

    def test_all_five_documents_present(self, report):
        expected_files = {
            "opinion_001.txt",
            "opinion_002.txt",
            "opinion_003.txt",
            "opinion_004.txt",
            "opinion_005.txt",
        }
        assert expected_files == set(report["court_mapping"].keys()), (
            "Court mapping should contain exactly the 5 opinion files"
        )
        assert expected_files == set(report["citations_per_document"].keys())
        assert expected_files == set(report["id_resolutions"].keys())
        assert expected_files == set(report["authority_hierarchy"].keys())


class TestCourtMapping:
    """Verify correct court ID mappings."""

    def test_opinion_001_is_ca2(self, report):
        assert report["court_mapping"]["opinion_001.txt"] == "ca2", (
            "Opinion 001 (Second Circuit) should map to 'ca2'"
        )

    def test_opinion_002_is_scotus(self, report):
        assert report["court_mapping"]["opinion_002.txt"] == "scotus", (
            "Opinion 002 (Supreme Court) should map to 'scotus'"
        )

    def test_opinion_003_is_ca9(self, report):
        assert report["court_mapping"]["opinion_003.txt"] == "ca9", (
            "Opinion 003 (Ninth Circuit) should map to 'ca9'"
        )

    def test_opinion_004_is_cafc(self, report):
        assert report["court_mapping"]["opinion_004.txt"] == "cafc", (
            "Opinion 004 (Federal Circuit) should map to 'cafc'"
        )

    def test_opinion_005_is_ca7(self, report):
        assert report["court_mapping"]["opinion_005.txt"] == "ca7", (
            "Opinion 005 (Seventh Circuit) should map to 'ca7'"
        )

    def test_previous_audit_court_error_fixed(self, report):
        """The previous audit incorrectly used 'fed_circuit' for opinion_004."""
        assert report["court_mapping"]["opinion_004.txt"] != "fed_circuit", (
            "Previous audit error: 'fed_circuit' should have been corrected to 'cafc'"
        )


class TestCitationExtraction:
    """Verify key citations are correctly extracted from each document."""

    def _get_triples(self, report, filename):
        doc = report["citations_per_document"][filename]
        return [tuple(t) for t in doc["full_case"]]

    def test_opinion_001_has_celotex(self, report):
        triples = self._get_triples(report, "opinion_001.txt")
        assert ("477", "U.S.", "317") in triples, (
            "Opinion 001 should contain Celotex Corp. v. Catrett, 477 U.S. 317"
        )

    def test_opinion_001_has_mcdonnell_douglas(self, report):
        triples = self._get_triples(report, "opinion_001.txt")
        assert ("411", "U.S.", "792") in triples, (
            "Opinion 001 should contain McDonnell Douglas, 411 U.S. 792"
        )

    def test_opinion_001_has_holcomb(self, report):
        triples = self._get_triples(report, "opinion_001.txt")
        assert ("521", "F.3d", "130") in triples, (
            "Opinion 001 should contain Holcomb v. Iona Coll., 521 F.3d 130"
        )

    def test_opinion_002_has_chevron(self, report):
        triples = self._get_triples(report, "opinion_002.txt")
        assert ("467", "U.S.", "837") in triples, (
            "Opinion 002 should contain Chevron, 467 U.S. 837"
        )

    def test_opinion_002_has_west_virginia_v_epa(self, report):
        triples = self._get_triples(report, "opinion_002.txt")
        assert ("597", "U.S.", "697") in triples, (
            "Opinion 002 should contain West Virginia v. EPA, 597 U.S. 697"
        )

    def test_opinion_003_has_barnes(self, report):
        triples = self._get_triples(report, "opinion_003.txt")
        assert ("570", "F.3d", "1096") in triples, (
            "Opinion 003 should contain Barnes v. Yahoo!, 570 F.3d 1096"
        )

    def test_opinion_003_has_gonzalez(self, report):
        triples = self._get_triples(report, "opinion_003.txt")
        assert ("598", "U.S.", "617") in triples, (
            "Opinion 003 should contain Gonzalez v. Google, 598 U.S. 617"
        )

    def test_opinion_004_has_markman(self, report):
        triples = self._get_triples(report, "opinion_004.txt")
        assert ("517", "U.S.", "370") in triples, (
            "Opinion 004 should contain Markman v. Westview, 517 U.S. 370"
        )

    def test_opinion_004_has_phillips(self, report):
        triples = self._get_triples(report, "opinion_004.txt")
        assert ("415", "F.3d", "1303") in triples, (
            "Opinion 004 should contain Phillips v. AWH Corp., 415 F.3d 1303"
        )

    def test_opinion_005_has_rapanos(self, report):
        triples = self._get_triples(report, "opinion_005.txt")
        assert ("547", "U.S.", "715") in triples, (
            "Opinion 005 should contain Rapanos v. United States, 547 U.S. 715"
        )

    def test_opinion_005_has_sackett(self, report):
        triples = self._get_triples(report, "opinion_005.txt")
        assert ("598", "U.S.", "651") in triples, (
            "Opinion 005 should contain Sackett v. EPA, 598 U.S. 651"
        )

    def test_full_case_sorted_by_volume(self, report):
        """Verify full_case lists are sorted by volume ascending."""
        for filename, doc in report["citations_per_document"].items():
            volumes = [int(t[0]) for t in doc["full_case"] if t[0].isdigit()]
            assert volumes == sorted(volumes), (
                f"Full case citations in {filename} should be sorted by volume ascending"
            )

    def test_previous_audit_sorting_fixed(self, report):
        """The previous audit had opinion_001 citations in wrong order."""
        doc = report["citations_per_document"]["opinion_001.txt"]
        if len(doc["full_case"]) >= 2:
            volumes = [int(t[0]) for t in doc["full_case"] if t[0].isdigit()]
            assert volumes == sorted(volumes), (
                "Previous audit sorting error should be corrected"
            )


class TestCitationCounts:
    """Verify citation counts are reasonable."""

    def test_opinion_001_has_multiple_full_case(self, report):
        doc = report["citations_per_document"]["opinion_001.txt"]
        assert len(doc["full_case"]) >= 10, (
            "Opinion 001 should have at least 10 full case citations"
        )

    def test_opinion_001_has_id_citations(self, report):
        doc = report["citations_per_document"]["opinion_001.txt"]
        assert doc["id_citations"] >= 2, (
            "Opinion 001 should have at least 2 Id. citations"
        )

    def test_opinion_002_has_id_citations(self, report):
        doc = report["citations_per_document"]["opinion_002.txt"]
        assert doc["id_citations"] >= 4, (
            "Opinion 002 should have at least 4 Id. citations"
        )

    def test_opinion_003_has_full_case_citations(self, report):
        """The previous audit reported 0 citations for opinion_003."""
        doc = report["citations_per_document"]["opinion_003.txt"]
        assert len(doc["full_case"]) >= 5, (
            "Opinion 003 should have at least 5 full case citations "
            "(previous audit incorrectly reported 0)"
        )

    def test_opinion_004_has_full_case_citations(self, report):
        doc = report["citations_per_document"]["opinion_004.txt"]
        assert len(doc["full_case"]) >= 8, (
            "Opinion 004 should have at least 8 full case citations "
            "(previous audit incorrectly reported 0)"
        )

    def test_opinion_004_has_id_citations(self, report):
        doc = report["citations_per_document"]["opinion_004.txt"]
        assert doc["id_citations"] >= 3, (
            "Opinion 004 should have at least 3 Id. citations (Phillips chain)"
        )

    def test_opinion_005_has_full_case_citations(self, report):
        doc = report["citations_per_document"]["opinion_005.txt"]
        assert len(doc["full_case"]) >= 6, (
            "Opinion 005 should have at least 6 full case citations "
            "(previous audit incorrectly reported 0)"
        )


class TestIdResolution:
    """Verify Id. citation resolution is correct."""

    def _find_resolution(self, report, filename, target_triple):
        resolutions = report["id_resolutions"][filename]
        for res in resolutions:
            if tuple(res["resolves_to"]) == tuple(target_triple):
                return True
        return False

    def test_opinion_001_id_resolves_to_mcdonnell_douglas(self, report):
        assert self._find_resolution(
            report, "opinion_001.txt", ["411", "U.S.", "792"]
        ), "Id. citations in opinion_001 should resolve to McDonnell Douglas (411 U.S. 792)"

    def test_opinion_002_id_resolves_to_west_virginia(self, report):
        assert self._find_resolution(
            report, "opinion_002.txt", ["597", "U.S.", "697"]
        ), "Id. in opinion_002 should resolve to West Virginia v. EPA (597 U.S. 697)"

    def test_opinion_002_id_resolves_to_mci(self, report):
        assert self._find_resolution(
            report, "opinion_002.txt", ["512", "U.S.", "218"]
        ), "Id. in opinion_002 should resolve to MCI Telecomm. (512 U.S. 218)"

    def test_opinion_004_id_resolves_to_phillips(self, report):
        assert self._find_resolution(
            report, "opinion_004.txt", ["415", "F.3d", "1303"]
        ), "Id. chain in opinion_004 should resolve to Phillips v. AWH Corp. (415 F.3d 1303)"

    def test_opinion_005_id_resolves_to_rapanos(self, report):
        assert self._find_resolution(
            report, "opinion_005.txt", ["547", "U.S.", "715"]
        ), "Id. in opinion_005 should resolve to Rapanos (547 U.S. 715)"

    def test_opinion_005_id_resolves_to_sackett(self, report):
        assert self._find_resolution(
            report, "opinion_005.txt", ["598", "U.S.", "651"]
        ), "Id. in opinion_005 should resolve to Sackett (598 U.S. 651)"

    def test_id_resolutions_have_required_fields(self, report):
        for filename, resolutions in report["id_resolutions"].items():
            for res in resolutions:
                assert "id_pin" in res, f"Resolution in {filename} missing 'id_pin'"
                assert "resolves_to" in res, f"Resolution in {filename} missing 'resolves_to'"
                assert isinstance(res["resolves_to"], list), (
                    f"resolves_to in {filename} should be a list"
                )
                assert len(res["resolves_to"]) == 3, (
                    f"resolves_to in {filename} should have 3 elements [volume, reporter, page]"
                )

    def test_previous_audit_resolutions_populated(self, report):
        """The previous audit had all id_resolutions empty."""
        total_resolutions = sum(
            len(v) for v in report["id_resolutions"].values()
        )
        assert total_resolutions >= 8, (
            "Corrected audit should have at least 8 total Id. resolutions "
            "(previous audit had 0)"
        )


class TestScotusShared:
    """Verify cross-document SCOTUS citation analysis."""

    def _find_shared(self, report, volume, page):
        for entry in report["scotus_shared"]:
            if entry["citation"][0] == volume and entry["citation"][2] == page:
                return entry
        return None

    def test_scotus_shared_is_non_empty(self, report):
        assert len(report["scotus_shared"]) >= 2, (
            "There should be at least 2 SCOTUS citations shared across documents "
            "(previous audit had 0)"
        )

    def test_anderson_shared_between_001_and_004(self, report):
        """Anderson v. Liberty Lobby, 477 U.S. 242, appears in both
        opinion_001 and opinion_004."""
        entry = self._find_shared(report, "477", "242")
        assert entry is not None, (
            "Anderson v. Liberty Lobby (477 U.S. 242) should be a shared SCOTUS citation"
        )
        assert "opinion_001.txt" in entry["documents"]
        assert "opinion_004.txt" in entry["documents"]

    def test_chevron_shared_between_002_and_005(self, report):
        """Chevron U.S.A., Inc. v. NRDC, 467 U.S. 837, appears in both
        opinion_002 and opinion_005."""
        entry = self._find_shared(report, "467", "837")
        assert entry is not None, (
            "Chevron (467 U.S. 837) should be a shared SCOTUS citation"
        )
        assert "opinion_002.txt" in entry["documents"]
        assert "opinion_005.txt" in entry["documents"]

    def test_598_us_different_pages_not_conflated(self, report):
        """598 U.S. appears in opinion_003 (page 617) and opinion_005 (page 651)
        with different pages. They must not be conflated."""
        entry_617 = self._find_shared(report, "598", "617")
        if entry_617 is not None:
            assert len(entry_617["documents"]) > 1

    def test_shared_entries_have_multiple_documents(self, report):
        for entry in report["scotus_shared"]:
            assert len(entry["documents"]) >= 2, (
                f"Shared citation {entry['citation']} should be in at least 2 documents"
            )

    def test_shared_entries_sorted_by_volume(self, report):
        if len(report["scotus_shared"]) >= 2:
            volumes = [int(e["citation"][0]) for e in report["scotus_shared"]]
            assert volumes == sorted(volumes), (
                "scotus_shared should be sorted by volume ascending"
            )

    def test_shared_citation_structure(self, report):
        for entry in report["scotus_shared"]:
            assert "citation" in entry
            assert "documents" in entry
            assert len(entry["citation"]) == 3
            assert entry["citation"][1] == "U.S."
            assert isinstance(entry["documents"], list)


class TestReporterFrequency:
    """Verify reporter frequency statistics."""

    def test_us_reporter_present(self, report):
        freq = report["reporter_frequency"]
        assert "U.S." in freq, "U.S. reporter should be in frequency distribution"

    def test_f3d_reporter_present(self, report):
        freq = report["reporter_frequency"]
        assert "F.3d" in freq, "F.3d reporter should be in frequency distribution"

    def test_us_reporter_count_reasonable(self, report):
        freq = report["reporter_frequency"]
        us_count = freq.get("U.S.", 0)
        assert us_count >= 20, (
            f"U.S. reporter count ({us_count}) should be at least 20 across corpus"
        )

    def test_f3d_reporter_count_reasonable(self, report):
        freq = report["reporter_frequency"]
        f3d_count = freq.get("F.3d", 0)
        assert f3d_count >= 8, (
            f"F.3d reporter count ({f3d_count}) should be at least 8 across corpus"
        )

    def test_reporter_keys_sorted(self, report):
        freq = report["reporter_frequency"]
        keys = list(freq.keys())
        assert keys == sorted(keys), (
            "Reporter frequency keys should be sorted alphabetically"
        )

    def test_total_citations_reasonable(self, report):
        freq = report["reporter_frequency"]
        total = sum(freq.values())
        assert total >= 40, (
            f"Total full case citations ({total}) should be at least 40 across corpus"
        )

    def test_previous_audit_frequency_populated(self, report):
        """The previous audit had an empty reporter_frequency."""
        freq = report["reporter_frequency"]
        assert len(freq) >= 3, (
            "Reporter frequency should have at least 3 different reporter types "
            "(previous audit had 0)"
        )


class TestAuthorityHierarchy:
    """Verify precedential authority classifications."""

    def _find_entry(self, report, filename, volume, page):
        for entry in report["authority_hierarchy"][filename]:
            if entry["citation"][0] == volume and entry["citation"][2] == page:
                return entry
        return None

    def test_all_documents_present(self, report):
        expected = {
            "opinion_001.txt", "opinion_002.txt", "opinion_003.txt",
            "opinion_004.txt", "opinion_005.txt",
        }
        assert expected == set(report["authority_hierarchy"].keys()), (
            "authority_hierarchy should have entries for all 5 documents"
        )

    def test_opinion_001_has_entries(self, report):
        entries = report["authority_hierarchy"]["opinion_001.txt"]
        assert len(entries) >= 10, (
            "Opinion 001 should have authority entries for at least 10 citations"
        )

    def test_opinion_001_holcomb_same_circuit_binding(self, report):
        """521 F.3d 130 (2d Cir.) cited by ca2 — same circuit, binding."""
        entry = self._find_entry(report, "opinion_001.txt", "521", "130")
        assert entry is not None, "Holcomb (521 F.3d 130) should be in authority_hierarchy"
        assert entry["cited_court"] == "ca2", (
            "Holcomb (2d Cir.) should have cited_court 'ca2'"
        )
        assert entry["binding"] is True, (
            "Same-circuit precedent should be binding"
        )

    def test_opinion_003_netchoice_paxton_sister_circuit_persuasive(self, report):
        """49 F.4th 439 (5th Cir.) cited by ca9 — sister circuit, persuasive."""
        entry = self._find_entry(report, "opinion_003.txt", "49", "439")
        assert entry is not None, "NetChoice v. Paxton should be in authority_hierarchy"
        assert entry["cited_court"] == "ca5", (
            "NetChoice v. Paxton (5th Cir.) should have cited_court 'ca5'"
        )
        assert entry["binding"] is False, (
            "Sister-circuit precedent should be persuasive (not binding)"
        )

    def test_opinion_003_force_facebook_sister_circuit_persuasive(self, report):
        """934 F.3d 53 (2d Cir.) cited by ca9 — sister circuit, persuasive."""
        entry = self._find_entry(report, "opinion_003.txt", "934", "53")
        assert entry is not None, "Force v. Facebook should be in authority_hierarchy"
        assert entry["cited_court"] == "ca2", (
            "Force v. Facebook (2d Cir.) should have cited_court 'ca2'"
        )
        assert entry["binding"] is False, (
            "Sister-circuit precedent should be persuasive (not binding)"
        )

    def test_opinion_005_chesapeake_sister_circuit_persuasive(self, report):
        """85 F.4th 323 (4th Cir.) cited by ca7 — sister circuit, persuasive."""
        entry = self._find_entry(report, "opinion_005.txt", "85", "323")
        assert entry is not None, "Chesapeake Bay Found. should be in authority_hierarchy"
        assert entry["cited_court"] == "ca4", (
            "Chesapeake Bay Found. (4th Cir.) should have cited_court 'ca4'"
        )
        assert entry["binding"] is False, (
            "Sister-circuit precedent should be persuasive (not binding)"
        )

    def test_opinion_005_gerke_same_circuit_binding(self, report):
        """464 F.3d 723 (7th Cir.) cited by ca7 — same circuit, binding."""
        entry = self._find_entry(report, "opinion_005.txt", "464", "723")
        assert entry is not None, "Gerke should be in authority_hierarchy"
        assert entry["cited_court"] == "ca7", (
            "Gerke (7th Cir.) should have cited_court 'ca7'"
        )
        assert entry["binding"] is True, (
            "Same-circuit precedent should be binding"
        )

    def test_scotus_always_binding(self, report):
        """All citations with U.S. reporter must be scotus and binding."""
        for filename, entries in report["authority_hierarchy"].items():
            for entry in entries:
                if entry["citation"][1] == "U.S.":
                    assert entry["cited_court"] == "scotus", (
                        f"U.S. reporter citation {entry['citation']} in {filename} "
                        f"should have cited_court 'scotus'"
                    )
                    assert entry["binding"] is True, (
                        f"SCOTUS citation {entry['citation']} in {filename} "
                        f"must be binding on all federal courts"
                    )

    def test_opinion_004_unpublished_not_binding(self, report):
        """536 F. App'x 985 — unpublished, should not be binding."""
        entry = self._find_entry(report, "opinion_004.txt", "536", "985")
        if entry is not None:
            assert entry["binding"] is False, (
                "Unpublished F. App'x citations should be persuasive, not binding"
            )

    def test_entries_have_required_fields(self, report):
        for filename, entries in report["authority_hierarchy"].items():
            for entry in entries:
                assert "citation" in entry, f"Entry in {filename} missing 'citation'"
                assert "cited_court" in entry, f"Entry in {filename} missing 'cited_court'"
                assert "binding" in entry, f"Entry in {filename} missing 'binding'"
                assert isinstance(entry["citation"], list) and len(entry["citation"]) == 3
                assert isinstance(entry["binding"], bool)

    def test_previous_audit_authority_errors_fixed(self, report):
        """Previous audit had wrong cited_court values (ca9 for 5th Cir.)."""
        entry = self._find_entry(report, "opinion_003.txt", "49", "439")
        assert entry is not None
        assert entry["cited_court"] != "ca9", (
            "Previous audit error: 5th Circuit was mislabeled as ca9"
        )


class TestDoctrinalThreads:
    """Verify doctrinal thread identification across the corpus."""

    def _find_thread_with_cases(self, report, vol1, pg1, vol2, pg2):
        """Find a thread containing both specified cases."""
        for thread in report["doctrinal_threads"]:
            case_keys = {(c[0], c[2]) for c in thread["cases"]}
            if (vol1, pg1) in case_keys and (vol2, pg2) in case_keys:
                return thread
        return None

    def test_at_least_three_threads(self, report):
        assert len(report["doctrinal_threads"]) >= 3, (
            "Should identify at least 3 doctrinal threads across the corpus"
        )

    def test_burden_shifting_thread(self, report):
        """McDonnell Douglas (411 U.S. 792) and Burdine (450 U.S. 248)
        should be in the same Title VII burden-shifting thread."""
        thread = self._find_thread_with_cases(report, "411", "792", "450", "248")
        assert thread is not None, (
            "Should have a doctrinal thread linking McDonnell Douglas and Burdine "
            "(Title VII burden-shifting framework)"
        )
        assert "opinion_001.txt" in thread["documents"]

    def test_major_questions_thread(self, report):
        """Chevron (467 U.S. 837) and West Virginia v. EPA (597 U.S. 697)
        should be in the same major questions doctrine thread."""
        thread = self._find_thread_with_cases(report, "467", "837", "597", "697")
        assert thread is not None, (
            "Should have a doctrinal thread linking Chevron and West Virginia v. EPA "
            "(major questions doctrine)"
        )
        assert "opinion_002.txt" in thread["documents"]

    def test_cwa_jurisdiction_thread(self, report):
        """Rapanos (547 U.S. 715) and Sackett (598 U.S. 651)
        should be in the same CWA jurisdiction thread."""
        thread = self._find_thread_with_cases(report, "547", "715", "598", "651")
        assert thread is not None, (
            "Should have a doctrinal thread linking Rapanos and Sackett "
            "(Clean Water Act jurisdiction)"
        )
        assert "opinion_005.txt" in thread["documents"]

    def test_threads_have_required_fields(self, report):
        for thread in report["doctrinal_threads"]:
            assert "thread_name" in thread, "Thread missing 'thread_name'"
            assert "cases" in thread, "Thread missing 'cases'"
            assert "documents" in thread, "Thread missing 'documents'"
            assert isinstance(thread["cases"], list) and len(thread["cases"]) >= 2, (
                f"Thread '{thread.get('thread_name', '?')}' must have at least 2 cases"
            )
            assert isinstance(thread["documents"], list) and len(thread["documents"]) >= 1

    def test_thread_cases_sorted_by_volume(self, report):
        for thread in report["doctrinal_threads"]:
            volumes = [int(c[0]) for c in thread["cases"] if c[0].isdigit()]
            assert volumes == sorted(volumes), (
                f"Thread '{thread['thread_name']}' cases should be sorted by volume ascending"
            )

    def test_previous_audit_threads_enhanced(self, report):
        """Previous audit had only 1 incomplete thread."""
        total_cases = sum(len(t["cases"]) for t in report["doctrinal_threads"])
        assert total_cases >= 8, (
            "Should have at least 8 total cases across all doctrinal threads "
            "(previous audit had only 2)"
        )


class TestAbrogationRisks:
    """Verify detection of explicit abrogation/vacatur."""

    def _find_abrogation(self, report, abrogated_vol, abrogated_pg):
        for risk in report["anomalies"]["abrogation_risks"]:
            if (risk["abrogated_case"][0] == abrogated_vol and
                    risk["abrogated_case"][2] == abrogated_pg):
                return risk
        return None

    def test_abrogation_risks_present(self, report):
        risks = report["anomalies"]["abrogation_risks"]
        assert len(risks) >= 2, (
            "Should detect at least 2 abrogation risks "
            "(previous audit had 0)"
        )

    def test_rueth_abrogated_by_sackett(self, report):
        """Opinion 005 explicitly states that Sackett (598 U.S. 651)
        abrogated Rueth Dev. Co. (335 F.3d 598)."""
        risk = self._find_abrogation(report, "335", "598")
        assert risk is not None, (
            "Rueth Dev. Co. (335 F.3d 598) should be identified as abrogated"
        )
        assert risk["abrogating_case"][0] == "598" and risk["abrogating_case"][2] == "651", (
            "Rueth should be abrogated by Sackett (598 U.S. 651)"
        )
        assert risk["document"] == "opinion_005.txt"

    def test_netchoice_vacated_by_moody(self, report):
        """Opinion 003 explicitly states that Moody v. NetChoice (603 U.S. 707)
        vacated both NetChoice decisions."""
        risk_paxton = self._find_abrogation(report, "49", "439")
        risk_ag = self._find_abrogation(report, "34", "1196")
        assert risk_paxton is not None or risk_ag is not None, (
            "At least one NetChoice decision should be identified as vacated by Moody"
        )
        # Verify the abrogating case is Moody
        found = risk_paxton or risk_ag
        assert found["abrogating_case"][0] == "603" and found["abrogating_case"][2] == "707", (
            "NetChoice should be vacated by Moody v. NetChoice (603 U.S. 707)"
        )

    def test_abrogation_entries_have_required_fields(self, report):
        for risk in report["anomalies"]["abrogation_risks"]:
            assert "abrogated_case" in risk, "Abrogation entry missing 'abrogated_case'"
            assert "abrogating_case" in risk, "Abrogation entry missing 'abrogating_case'"
            assert "document" in risk, "Abrogation entry missing 'document'"
            assert "reason" in risk, "Abrogation entry missing 'reason'"
            assert isinstance(risk["abrogated_case"], list) and len(risk["abrogated_case"]) == 3
            assert isinstance(risk["abrogating_case"], list) and len(risk["abrogating_case"]) == 3


class TestAnomalyDetection:
    """Verify basic anomaly detection capabilities."""

    def test_anomalies_structure(self, report):
        anomalies = report["anomalies"]
        assert isinstance(anomalies["orphan_id_citations"], list)
        assert isinstance(anomalies["court_reporter_mismatches"], list)
        assert isinstance(anomalies["abrogation_risks"], list)

    def test_orphan_id_entries_have_required_fields(self, report):
        for entry in report["anomalies"]["orphan_id_citations"]:
            assert "file" in entry, "Orphan Id. entry missing 'file' field"
            assert "text" in entry, "Orphan Id. entry missing 'text' field"

    def test_mismatch_entries_have_required_fields(self, report):
        for entry in report["anomalies"]["court_reporter_mismatches"]:
            assert "file" in entry, "Mismatch entry missing 'file' field"
            assert "citation" in entry, "Mismatch entry missing 'citation' field"
            assert "expected_court_type" in entry, (
                "Mismatch entry missing 'expected_court_type' field"
            )


class TestDataIntegrity:
    """Cross-cutting checks for data consistency."""

    def test_all_filenames_are_basenames(self, report):
        for filename in report["court_mapping"].keys():
            assert "/" not in filename, (
                f"Filename '{filename}' should be a basename, not a full path"
            )

    def test_id_resolution_count_matches_id_citation_count(self, report):
        for filename in report["citations_per_document"]:
            id_count = report["citations_per_document"][filename]["id_citations"]
            resolution_count = len(report["id_resolutions"][filename])
            orphan_count = len([
                o for o in report["anomalies"]["orphan_id_citations"]
                if o["file"] == filename
            ])
            assert resolution_count + orphan_count <= id_count + 1, (
                f"In {filename}: resolved ({resolution_count}) + orphan ({orphan_count}) "
                f"should not greatly exceed Id. count ({id_count})"
            )

    def test_citation_triples_are_string_lists(self, report):
        for filename, doc in report["citations_per_document"].items():
            for triple in doc["full_case"]:
                assert isinstance(triple, list) and len(triple) == 3, (
                    f"Citation triple in {filename} should be [volume, reporter, page]"
                )
                assert all(isinstance(s, str) for s in triple), (
                    f"All elements of citation triple should be strings in {filename}"
                )

    def test_report_not_identical_to_previous_audit(self, report):
        """The corrected report should differ significantly from the broken audit."""
        total_citations = sum(
            len(doc["full_case"])
            for doc in report["citations_per_document"].values()
        )
        assert total_citations >= 40, (
            "Corrected report should have substantially more citations than "
            "the incomplete previous audit"
        )

    def test_authority_hierarchy_consistent_with_citations(self, report):
        """Authority hierarchy should cover the same citations as citations_per_document."""
        for filename in report["citations_per_document"]:
            cite_count = len(report["citations_per_document"][filename]["full_case"])
            auth_count = len(report["authority_hierarchy"][filename])
            assert auth_count >= cite_count - 2, (
                f"In {filename}: authority_hierarchy ({auth_count}) should cover "
                f"most citations from citations_per_document ({cite_count})"
            )
