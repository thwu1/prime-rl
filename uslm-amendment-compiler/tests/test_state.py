
import json
import os
import pytest


@pytest.fixture
def amended():
    path = "/app/amended_statute.json"
    assert os.path.exists(path), "amended_statute.json not found at /app/amended_statute.json"
    with open(path) as f:
        return json.load(f)


@pytest.fixture
def report():
    path = "/app/reconciliation_report.json"
    assert os.path.exists(path), "reconciliation_report.json not found at /app/reconciliation_report.json"
    with open(path) as f:
        return json.load(f)


# ── Overall structure ────────────────────────────────────────────


class TestOverallStructure:
    def test_all_sections_present(self, amended):
        for s in ["1201", "1202", "1203", "1204", "1205"]:
            assert s in amended["sections"], f"Section {s} missing"

    def test_title_and_chapter(self, amended):
        assert amended["title"] == "6"
        assert amended["chapter"] == "12"


# ── Section 1201 (definitions) ──────────────────────────────────


class TestSection1201:
    """Verifies PL 119-45 renames + addition AND PL 119-67 amendment-on-amendment
    + conditional skip + new paragraph."""

    def test_paragraph_count(self, amended):
        paras = amended["sections"]["1201"]["paragraphs"]
        assert len(paras) == 8, f"Expected 8 paragraphs in 1201, got {len(paras)}"

    def test_para3_covered_info_system(self, amended):
        text = amended["sections"]["1201"]["paragraphs"]["3"]["text"]
        assert "covered information system" in text
        assert text.count("covered information system") == 2

    def test_para3_old_term_removed(self, amended):
        text = amended["sections"]["1201"]["paragraphs"]["3"]["text"]
        assert "electronic information system" not in text

    def test_para5_cloud_infrastructure(self, amended):
        """PL 119-67 amended the already-modified paragraph (5) text."""
        text = amended["sections"]["1201"]["paragraphs"]["5"]["text"]
        assert "cloud-based and hybrid infrastructure" in text

    def test_para5_retains_covered_term(self, amended):
        """PL 119-45's rename from 'electronic information system' persists."""
        text = amended["sections"]["1201"]["paragraphs"]["5"]["text"]
        assert "covered information system" in text
        assert "electronic information system" not in text

    def test_para5_retains_simplified_resources(self, amended):
        """PL 119-45 simplified 'electronic information resources' to 'information resources'."""
        text = amended["sections"]["1201"]["paragraphs"]["5"]["text"]
        assert "information resources" in text
        assert "electronic information resources" not in text

    def test_para7_has_pl45_full_definition(self, amended):
        """Paragraph (7) must have PL 119-45's FULL definition, not PL 119-67's
        shorter conditional version (which should have been skipped)."""
        text = amended["sections"]["1201"]["paragraphs"]["7"]["text"]
        assert "extract data" in text, (
            "Para (7) should contain 'extract data' from PL 119-45's version"
        )

    def test_para7_has_manufacturing(self, amended):
        """Only PL 119-45's version mentions manufacturing/production/distribution."""
        text = amended["sections"]["1201"]["paragraphs"]["7"]["text"]
        assert "manufacturing" in text

    def test_para7_has_surveil(self, amended):
        """Only PL 119-45's version contains the 'surveil, deny, disrupt' language."""
        text = amended["sections"]["1201"]["paragraphs"]["7"]["text"]
        assert "surveil" in text

    def test_para7_not_quoted(self, amended):
        text = amended["sections"]["1201"]["paragraphs"]["7"]["text"]
        assert not text.startswith('"'), "Leading quote mark should be stripped"
        assert not text.endswith('"'), "Trailing quote mark should be stripped"

    def test_para8_zero_trust(self, amended):
        """PL 119-67 added paragraph (8) defining zero trust architecture."""
        para8 = amended["sections"]["1201"]["paragraphs"].get("8")
        assert para8 is not None, "Paragraph (8) should exist"
        assert "zero trust architecture" in para8["text"]

    def test_para8_continuous_verification(self, amended):
        text = amended["sections"]["1201"]["paragraphs"]["8"]["text"]
        assert "continuous verification" in text

    def test_unchanged_paragraphs_preserved(self, amended):
        paras = amended["sections"]["1201"]["paragraphs"]
        assert "Agency" in paras["1"]["text"]
        assert "critical infrastructure" in paras["2"]["text"]
        assert "Director" in paras["4"]["text"]
        assert "sector risk management agency" in paras["6"]["text"]


# ── Section 1202 (critical infrastructure) ──────────────────────


class TestSection1202:
    """Verifies PL 119-45 structural changes AND PL 119-67's additions to
    PL 119-45's inserted subsection + redesignated subsection text change."""

    def test_four_subsections(self, amended):
        subsecs = amended["sections"]["1202"]["subsections"]
        assert len(subsecs) == 4
        for key in ["a", "b", "c", "d"]:
            assert key in subsecs, f"Subsection ({key}) missing from 1202"

    def test_b3_five_subparagraphs(self, amended):
        subparas = amended["sections"]["1202"]["subsections"]["b"]["paragraphs"]["3"][
            "subparagraphs"
        ]
        assert len(subparas) == 5
        for key in ["A", "B", "C", "D", "E"]:
            assert key in subparas

    def test_b3E_supply_chain(self, amended):
        text = amended["sections"]["1202"]["subsections"]["b"]["paragraphs"]["3"][
            "subparagraphs"
        ]["E"]["text"]
        assert "supply chain risk" in text.lower()

    def test_c_heading(self, amended):
        heading = amended["sections"]["1202"]["subsections"]["c"].get("heading", "")
        assert "threat mitigation" in heading.lower() or "advanced" in heading.lower()

    def test_c_four_paragraphs(self, amended):
        """Subsection (c) should have 4 paragraphs: 3 from PL 119-45 + 1 from PL 119-67."""
        paras = amended["sections"]["1202"]["subsections"]["c"]["paragraphs"]
        assert len(paras) == 4, f"Expected 4 paragraphs in (c), got {len(paras)}"

    def test_c_para4_ai_anomaly(self, amended):
        """PL 119-67 added paragraph (4) about AI-based anomaly detection."""
        text = amended["sections"]["1202"]["subsections"]["c"]["paragraphs"]["4"]["text"]
        assert "artificial intelligence" in text.lower()
        assert "anomaly detection" in text.lower()

    def test_c_original_paragraphs_intact(self, amended):
        paras = amended["sections"]["1202"]["subsections"]["c"]["paragraphs"]
        assert "endpoint detection" in paras["1"]["text"].lower()
        assert "network segmentation" in paras["2"]["text"].lower()
        assert "monitoring" in paras["3"]["text"].lower()

    def test_d_18_months(self, amended):
        """PL 119-67 changed the compliance deadline from '2 years' to '18 months'."""
        text = amended["sections"]["1202"]["subsections"]["d"]["text"]
        assert "18 months" in text

    def test_d_not_2_years(self, amended):
        text = amended["sections"]["1202"]["subsections"]["d"]["text"]
        assert "2 years" not in text

    def test_d_compliance_heading(self, amended):
        heading = amended["sections"]["1202"]["subsections"]["d"].get("heading", "")
        assert "compliance" in heading.lower()

    def test_a_unchanged(self, amended):
        text = amended["sections"]["1202"]["subsections"]["a"]["text"]
        assert "risk-based cybersecurity measures" in text


# ── Section 1203 (incident reporting) ───────────────────────────


class TestSection1203:
    """Verifies PL 119-45 full replacement + penalty AND PL 119-67's
    amendment-on-amendment changes to both."""

    def test_a_has_three_paragraphs(self, amended):
        paras = amended["sections"]["1203"]["subsections"]["a"]["paragraphs"]
        assert len(paras) == 3

    def test_a1_12_hours(self, amended):
        """PL 119-67 changed the imminent-threat deadline from 24h to 12h."""
        text = amended["sections"]["1203"]["subsections"]["a"]["paragraphs"]["1"]["text"]
        assert "12 hours" in text

    def test_a1_not_24_hours(self, amended):
        text = amended["sections"]["1203"]["subsections"]["a"]["paragraphs"]["1"]["text"]
        assert "24 hours" not in text

    def test_a1_imminent_threat(self, amended):
        text = amended["sections"]["1203"]["subsections"]["a"]["paragraphs"]["1"]["text"]
        assert "imminent threat" in text or "national security" in text

    def test_a2_72_hours_unchanged(self, amended):
        text = amended["sections"]["1203"]["subsections"]["a"]["paragraphs"]["2"]["text"]
        assert "72 hours" in text

    def test_a3_48_hours_supply_chain(self, amended):
        text = amended["sections"]["1203"]["subsections"]["a"]["paragraphs"]["3"]["text"]
        assert "48 hours" in text
        assert "supply chain" in text

    def test_b2_750k(self, amended):
        """PL 119-67 changed the penalty from $500,000 (set by PL 119-45) to $750,000."""
        text = amended["sections"]["1203"]["subsections"]["b"]["paragraphs"]["2"]["text"]
        assert "$750,000" in text

    def test_b2_not_500k(self, amended):
        text = amended["sections"]["1203"]["subsections"]["b"]["paragraphs"]["2"]["text"]
        assert "$500,000" not in text

    def test_b2_not_100k(self, amended):
        text = amended["sections"]["1203"]["subsections"]["b"]["paragraphs"]["2"]["text"]
        assert "$100,000" not in text

    def test_b1_50k_unchanged(self, amended):
        text = amended["sections"]["1203"]["subsections"]["b"]["paragraphs"]["1"]["text"]
        assert "$50,000" in text


# ── Section 1204 (enforcement) ──────────────────────────────────


class TestSection1204:
    """Verifies PL 119-45 repeal + punctuation fix (no PL 119-67 changes)."""

    def test_three_paragraphs_only(self, amended):
        paras = amended["sections"]["1204"]["subsections"]["a"]["paragraphs"]
        assert len(paras) == 3

    def test_paragraph_4_removed(self, amended):
        paras = amended["sections"]["1204"]["subsections"]["a"]["paragraphs"]
        assert "4" not in paras

    def test_paragraph_3_ends_with_period(self, amended):
        text = amended["sections"]["1204"]["subsections"]["a"]["paragraphs"]["3"]["text"]
        assert text.rstrip().endswith(".")
        assert "; and" not in text

    def test_paragraphs_1_2_unchanged(self, amended):
        paras = amended["sections"]["1204"]["subsections"]["a"]["paragraphs"]
        assert "compliance orders" in paras["1"]["text"]
        assert "civil penalties" in paras["2"]["text"]


# ── Section 1205 (federal agency) ───────────────────────────────


class TestSection1205:
    """Verifies PL 119-45 zero trust addition AND PL 119-67's extension of it."""

    def test_four_subsections(self, amended):
        subsecs = amended["sections"]["1205"]["subsections"]
        assert len(subsecs) == 4
        for key in ["a", "b", "c", "d"]:
            assert key in subsecs

    def test_d_heading(self, amended):
        heading = amended["sections"]["1205"]["subsections"]["d"].get("heading", "")
        assert "zero trust" in heading.lower()

    def test_d_four_paragraphs(self, amended):
        """PL 119-67 added paragraph (4) to the zero trust subsection."""
        paras = amended["sections"]["1205"]["subsections"]["d"]["paragraphs"]
        assert len(paras) == 4, f"Expected 4 paragraphs in 1205(d), got {len(paras)}"

    def test_d_para4_orchestration(self, amended):
        text = amended["sections"]["1205"]["subsections"]["d"]["paragraphs"]["4"]["text"]
        assert "orchestration" in text.lower()
        assert "zero trust" in text.lower()

    def test_d_original_paragraphs_intact(self, amended):
        paras = amended["sections"]["1205"]["subsections"]["d"]["paragraphs"]
        assert "verification" in paras["1"]["text"].lower()
        assert "least-privilege" in paras["2"]["text"].lower()
        assert "security posture" in paras["3"]["text"].lower() or "validation" in paras["3"]["text"].lower()

    def test_existing_subsections_unchanged(self, amended):
        subsecs = amended["sections"]["1205"]["subsections"]
        assert "section 1202" in subsecs["a"]["text"]
        assert "section 1203" in subsecs["b"]["text"]
        assert "sector risk management" in subsecs["c"]["text"]


# ── Reconciliation report ───────────────────────────────────────


class TestReconciliationReport:
    """Verifies the audit trail is correct and complete."""

    def test_report_exists(self, report):
        assert report is not None

    def test_enactment_order_correct(self, report):
        order = report["enactment_order"]
        assert len(order) == 2
        assert order[0]["law_id"] == "pl-119-45"
        assert order[1]["law_id"] == "pl-119-67"

    def test_enactment_dates(self, report):
        order = report["enactment_order"]
        assert order[0]["enacted_date"] < order[1]["enacted_date"]

    def test_amendments_list_not_empty(self, report):
        amendments = report["amendments"]
        assert len(amendments) >= 15, (
            f"Expected at least 15 amendment records, got {len(amendments)}"
        )

    def test_has_both_laws(self, report):
        sources = {a["source_law"] for a in report["amendments"]}
        assert "pl-119-45" in sources
        assert "pl-119-67" in sources

    def test_exactly_one_skipped(self, report):
        skipped = [a for a in report["amendments"] if a["status"] == "skipped"]
        assert len(skipped) == 1, f"Expected exactly 1 skipped, got {len(skipped)}"

    def test_skipped_targets_1201_7(self, report):
        skipped = [a for a in report["amendments"] if a["status"] == "skipped"]
        target = skipped[0]["target_provision"]
        assert "1201" in target, f"Skipped should target 1201, got {target}"
        assert "7" in target, f"Skipped should target paragraph 7, got {target}"

    def test_skipped_is_from_pl67(self, report):
        skipped = [a for a in report["amendments"] if a["status"] == "skipped"]
        assert skipped[0]["source_law"] == "pl-119-67"

    def test_skipped_has_reason(self, report):
        skipped = [a for a in report["amendments"] if a["status"] == "skipped"]
        reason = skipped[0].get("skip_reason", "")
        assert "prior" in reason.lower() or "already" in reason.lower(), (
            f"Skip reason should mention prior enactment, got: {reason}"
        )

    def test_summary_counts(self, report):
        summary = report["summary"]
        assert summary["total_amendments"] >= 15
        assert summary["applied"] >= 14
        assert summary["skipped"] == 1
        assert summary["applied"] + summary["skipped"] == summary["total_amendments"]

    def test_all_applied_have_status(self, report):
        for a in report["amendments"]:
            assert a["status"] in ("applied", "skipped"), (
                f"Invalid status: {a['status']}"
            )

    def test_all_have_required_fields(self, report):
        required = {"source_law", "source_section", "target_provision", "action_type", "status"}
        for i, a in enumerate(report["amendments"]):
            missing = required - set(a.keys())
            assert not missing, f"Amendment {i} missing fields: {missing}"
