"""
Tests for SWIFT MT103 validation engine and pacs.008 XML conversion.

"""
import json
import os
import xml.etree.ElementTree as ET
import pytest


NS = {"p": "urn:iso:std:iso:20022:tech:xsd:pacs.008.001.08"}


@pytest.fixture(scope="session")
def report():
    report_path = "/app/output/report.json"
    assert os.path.exists(report_path), f"Report file not found at {report_path}"
    with open(report_path) as f:
        data = json.load(f)
    return data


@pytest.fixture(scope="session")
def summary():
    path = "/app/output/summary.json"
    assert os.path.exists(path), f"summary.json not found at {path}"
    with open(path) as f:
        data = json.load(f)
    return data


@pytest.fixture(scope="session")
def xml_root():
    path = "/app/output/pacs008.xml"
    assert os.path.exists(path), f"pacs008.xml not found at {path}"
    tree = ET.parse(path)
    return tree.getroot()


# ── JSON Report Tests ──────────────────────────────────────────────

class TestMessageCount:
    def test_correct_number_of_messages(self, report):
        """Batch contains 8 messages; ACK-prepended msg 5 should be parsed as one message."""
        assert len(report) == 8


class TestMessage0BasicValid:
    """Message 0: Basic valid MT103 with :50K:, SHA charges, EUR currency."""

    def test_is_valid(self, report):
        assert report[0]["valid"] is True

    def test_reference(self, report):
        assert report[0]["reference"] == "REFERENCE-001"

    def test_not_stp(self, report):
        assert report[0]["stp_compliant"] is False

    def test_settlement_currency(self, report):
        assert report[0]["settlement_currency"] == "EUR"

    def test_settlement_amount(self, report):
        amt = float(report[0]["settlement_amount"])
        assert abs(amt - 50000.0) < 0.01

    def test_sender_bic(self, report):
        assert "BANKBEBB" in report[0]["sender_bic"]

    def test_receiver_bic(self, report):
        assert "BANKDEFF" in report[0]["receiver_bic"]

    def test_no_errors(self, report):
        assert len(report[0]["errors"]) == 0


class TestMessage1StpWithCrossField:
    """Message 1: STP message with :33B: different currency, :36: present. Valid."""

    def test_is_valid(self, report):
        assert report[1]["valid"] is True

    def test_reference(self, report):
        assert report[1]["reference"] == "TXNREF20230115"

    def test_stp_compliant(self, report):
        assert report[1]["stp_compliant"] is True

    def test_settlement_currency(self, report):
        assert report[1]["settlement_currency"] == "USD"

    def test_settlement_amount(self, report):
        amt = float(report[1]["settlement_amount"])
        assert abs(amt - 125000.0) < 0.01

    def test_no_errors(self, report):
        assert len(report[1]["errors"]) == 0


class TestMessage2Minimal:
    """Message 2: Minimal valid MT103 with only mandatory fields."""

    def test_is_valid(self, report):
        assert report[2]["valid"] is True

    def test_reference(self, report):
        assert report[2]["reference"] == "MINREF001"

    def test_not_stp(self, report):
        assert report[2]["stp_compliant"] is False

    def test_settlement_amount(self, report):
        amt = float(report[2]["settlement_amount"])
        assert abs(amt - 1000.0) < 0.01

    def test_no_errors(self, report):
        assert len(report[2]["errors"]) == 0


class TestMessage3ChargesViolation:
    """Message 3: SHA charges with :71G: present -> C5 violation."""

    def test_is_invalid(self, report):
        assert report[3]["valid"] is False

    def test_reference(self, report):
        assert report[3]["reference"] == "REF-CHARGES-001"

    def test_c5_violation(self, report):
        error_rules = [e["rule"] for e in report[3]["errors"]]
        assert "C5_VIOLATION" in error_rules

    def test_settlement_currency(self, report):
        assert report[3]["settlement_currency"] == "GBP"

    def test_settlement_amount(self, report):
        amt = float(report[3]["settlement_amount"])
        assert abs(amt - 75000.0) < 0.01

    def test_c2_no_false_c1(self, report):
        """33B currency == 32A currency (both GBP), :36: absent -> no C1 violation."""
        error_rules = [e["rule"] for e in report[3]["errors"]]
        assert "C1_VIOLATION" not in error_rules


class TestMessage4AckPrepended:
    """Message 4: ACK-prepended message with XOF currency, trailing comma amount."""

    def test_is_valid(self, report):
        assert report[4]["valid"] is True

    def test_reference(self, report):
        assert report[4]["reference"] == "5387354"

    def test_settlement_currency(self, report):
        assert report[4]["settlement_currency"] == "XOF"

    def test_settlement_amount_trailing_comma(self, report):
        """Amount '2000000,' means 2000000.00 — trailing comma = zero decimals."""
        amt = float(report[4]["settlement_amount"])
        assert abs(amt - 2000000.0) < 0.01

    def test_sender_bic_from_real_block1(self, report):
        """Should extract BIC from the actual MT103 block1 (F01), not the ACK block1 (F21)."""
        assert "OMFNCIAB" in report[4]["sender_bic"]

    def test_no_errors(self, report):
        assert len(report[4]["errors"]) == 0


class TestMessage5WithD52:
    """Message 5: Valid message with :52D: (non-STP), trailing comma amount."""

    def test_is_valid(self, report):
        assert report[5]["valid"] is True

    def test_reference(self, report):
        assert report[5]["reference"] == "12345677890"

    def test_settlement_amount_trailing_comma(self, report):
        """Amount '500,' means 500.00."""
        amt = float(report[5]["settlement_amount"])
        assert abs(amt - 500.0) < 0.01

    def test_not_stp(self, report):
        assert report[5]["stp_compliant"] is False

    def test_no_errors(self, report):
        assert len(report[5]["errors"]) == 0


class TestMessage6StpViolation:
    """Message 6: Has {119:STP} but uses :50K: -> STP violation."""

    def test_reference(self, report):
        assert report[6]["reference"] == "006135011308"

    def test_stp_violation_reported(self, report):
        """Has {119:STP} but :50K: is used, violating STP constraint 2."""
        error_rules = [e["rule"] for e in report[6]["errors"]]
        assert "STP_VIOLATION" in error_rules

    def test_stp_not_compliant(self, report):
        assert report[6]["stp_compliant"] is False

    def test_settlement_amount_trailing_comma(self, report):
        """Amount '100000,' means 100000.00."""
        amt = float(report[6]["settlement_amount"])
        assert abs(amt - 100000.0) < 0.01


class TestMessage7StpBenViolation:
    """Message 7: Has {119:STP}, :50F:, :59A:, all institution A-options -> STP valid.
    But :71A: BEN with :71F: present -> C3 violation.
    And :33B: GBP differs from :32A: USD, :36: absent -> C1 violation."""

    def test_is_invalid(self, report):
        assert report[7]["valid"] is False

    def test_reference(self, report):
        assert report[7]["reference"] == "STPTEST001"

    def test_c3_violation(self, report):
        error_rules = [e["rule"] for e in report[7]["errors"]]
        assert "C3_VIOLATION" in error_rules

    def test_stp_compliant(self, report):
        """STP structure is valid (:50F:, all A-options), even though C3 is violated."""
        assert report[7]["stp_compliant"] is True

    def test_c1_violation(self, report):
        """33B currency (GBP) differs from 32A currency (USD), :36: missing -> C1 violation."""
        error_rules = [e["rule"] for e in report[7]["errors"]]
        assert "C1_VIOLATION" in error_rules


class TestMultiLineFields:
    """Verify that multi-line fields are parsed correctly."""

    def test_msg0_beneficiary_multiline(self, report):
        """Message 0 :59: has 4 lines (account + 3 address lines). Should be valid."""
        assert report[0]["valid"] is True

    def test_msg1_ordering_customer_multiline(self, report):
        """Message 1 :50F: has 4 lines. Should be valid."""
        assert report[1]["valid"] is True


class TestCrossFieldCurrencyComparison:
    """Test that C1/C2 rules properly compare currencies from :32A: and :33B:."""

    def test_msg3_same_currency_no_c1(self, report):
        """Message 3: :32A: GBP, :33B: GBP (same) -> C1 should NOT fire, C2 satisfied (no :36:)."""
        error_rules = [e["rule"] for e in report[3]["errors"]]
        assert "C1_VIOLATION" not in error_rules

    def test_msg1_diff_currency_with_rate(self, report):
        """Message 1: :32A: USD, :33B: EUR (different), :36: present -> C1 satisfied."""
        error_rules = [e["rule"] for e in report[1]["errors"]]
        assert "C1_VIOLATION" not in error_rules

    def test_msg7_diff_currency_no_rate(self, report):
        """Message 7: :32A: USD, :33B: GBP (different), :36: absent -> C1 violation."""
        error_rules = [e["rule"] for e in report[7]["errors"]]
        assert "C1_VIOLATION" in error_rules


# ── JQ Summary Tests ──────────────────────────────────────────────

class TestJqSummary:
    """Verify jq-produced summary.json structure and content."""

    def test_summary_count(self, summary):
        assert len(summary) == 8

    def test_summary_msg0(self, summary):
        assert summary[0]["ref"] == "REFERENCE-001"
        assert summary[0]["valid"] is True
        assert summary[0]["stp"] is False
        assert summary[0]["errors"] == 0

    def test_summary_msg1_stp(self, summary):
        assert summary[1]["ref"] == "TXNREF20230115"
        assert summary[1]["stp"] is True
        assert summary[1]["errors"] == 0

    def test_summary_msg3_errors(self, summary):
        assert summary[3]["valid"] is False
        assert summary[3]["errors"] >= 1

    def test_summary_msg7_errors(self, summary):
        assert summary[7]["valid"] is False
        assert summary[7]["errors"] >= 2


# ── XML pacs.008 Tests ────────────────────────────────────────────

class TestXmlNamespace:
    """Verify correct ISO 20022 namespace in XML output."""

    def test_root_namespace(self, xml_root):
        expected = "{urn:iso:std:iso:20022:tech:xsd:pacs.008.001.08}Document"
        assert xml_root.tag == expected, f"Wrong root tag: {xml_root.tag}"


class TestXmlGroupHeader:
    """Verify GrpHdr structure."""

    def test_nb_of_txs(self, xml_root):
        nb = xml_root.find(".//p:GrpHdr/p:NbOfTxs", NS)
        assert nb is not None, "NbOfTxs element missing"
        assert nb.text == "5"

    def test_settlement_method(self, xml_root):
        mtd = xml_root.find(".//p:GrpHdr/p:SttlmInf/p:SttlmMtd", NS)
        assert mtd is not None, "SttlmMtd element missing"
        assert mtd.text == "INGA"


class TestXmlTransactions:
    """Verify CdtTrfTxInf elements for valid messages."""

    def test_transaction_count(self, xml_root):
        """Only valid messages (0,1,2,4,5) should appear as transactions."""
        txns = xml_root.findall(".//p:CdtTrfTxInf", NS)
        assert len(txns) == 5

    def test_txn0_tx_id(self, xml_root):
        txns = xml_root.findall(".//p:CdtTrfTxInf", NS)
        tx_id = txns[0].find("p:PmtId/p:TxId", NS)
        assert tx_id is not None
        assert tx_id.text == "REFERENCE-001"

    def test_txn0_end_to_end_id(self, xml_root):
        txns = xml_root.findall(".//p:CdtTrfTxInf", NS)
        e2e = txns[0].find("p:PmtId/p:EndToEndId", NS)
        assert e2e is not None
        assert e2e.text == "REFERENCE-001"

    def test_txn0_amount(self, xml_root):
        txns = xml_root.findall(".//p:CdtTrfTxInf", NS)
        amt = txns[0].find("p:IntrBkSttlmAmt", NS)
        assert abs(float(amt.text) - 50000.0) < 0.01
        assert amt.get("Ccy") == "EUR"

    def test_txn0_date(self, xml_root):
        txns = xml_root.findall(".//p:CdtTrfTxInf", NS)
        dt = txns[0].find("p:IntrBkSttlmDt", NS)
        assert dt.text == "2023-01-15"

    def test_txn0_charge_bearer(self, xml_root):
        """SHA should map to SHAR."""
        txns = xml_root.findall(".//p:CdtTrfTxInf", NS)
        cb = txns[0].find("p:ChrgBr", NS)
        assert cb.text == "SHAR"

    def test_txn2_charge_bearer(self, xml_root):
        """OUR should map to CRED (message 2, third valid txn)."""
        txns = xml_root.findall(".//p:CdtTrfTxInf", NS)
        cb = txns[2].find("p:ChrgBr", NS)
        assert cb.text == "CRED"

    def test_txn0_debtor_name(self, xml_root):
        """Debtor name should be the customer name, not the account number."""
        txns = xml_root.findall(".//p:CdtTrfTxInf", NS)
        nm = txns[0].find("p:Dbtr/p:Nm", NS)
        assert nm.text == "ORDERING CUSTOMER NAME"

    def test_txn0_creditor_name(self, xml_root):
        txns = xml_root.findall(".//p:CdtTrfTxInf", NS)
        nm = txns[0].find("p:Cdtr/p:Nm", NS)
        assert nm.text == "BENEFICIARY CUSTOMER NAME"

    def test_txn1_debtor_structured(self, xml_root):
        """Message 1 uses :50F:. Name comes from line starting with '1/'."""
        txns = xml_root.findall(".//p:CdtTrfTxInf", NS)
        nm = txns[1].find("p:Dbtr/p:Nm", NS)
        assert nm.text == "JOHN DOE"

    def test_txn1_creditor_structured(self, xml_root):
        """Message 1 :59F: name from line '1/JANE SMITH GMBH'."""
        txns = xml_root.findall(".//p:CdtTrfTxInf", NS)
        nm = txns[1].find("p:Cdtr/p:Nm", NS)
        assert nm.text == "JANE SMITH GMBH"

    def test_txn3_date_century(self, xml_root):
        """Message 4 (index 3 in XML): date 151104, YY=15 < 50 -> 2015-11-04."""
        txns = xml_root.findall(".//p:CdtTrfTxInf", NS)
        dt = txns[3].find("p:IntrBkSttlmDt", NS)
        assert dt.text == "2015-11-04"

    def test_txn4_date_century(self, xml_root):
        """Message 5 (index 4 in XML): date 160217, YY=16 < 50 -> 2016-02-17."""
        txns = xml_root.findall(".//p:CdtTrfTxInf", NS)
        dt = txns[4].find("p:IntrBkSttlmDt", NS)
        assert dt.text == "2016-02-17"

    def test_txn3_amount_trailing_comma(self, xml_root):
        """Message 4 (index 3 in XML): amount 2000000, -> 2000000.00."""
        txns = xml_root.findall(".//p:CdtTrfTxInf", NS)
        amt = txns[3].find("p:IntrBkSttlmAmt", NS)
        assert abs(float(amt.text) - 2000000.0) < 0.01
        assert amt.get("Ccy") == "XOF"

    def test_txn0_instg_agt(self, xml_root):
        """Instructing agent BIC from block 1."""
        txns = xml_root.findall(".//p:CdtTrfTxInf", NS)
        bic = txns[0].find("p:InstgAgt/p:FinInstnId/p:BICFI", NS)
        assert "BANKBEBB" in bic.text

    def test_txn0_instd_agt(self, xml_root):
        """Instructed agent BIC from block 2."""
        txns = xml_root.findall(".//p:CdtTrfTxInf", NS)
        bic = txns[0].find("p:InstdAgt/p:FinInstnId/p:BICFI", NS)
        assert "BANKDEFF" in bic.text
