
import json
import os
import pytest

REPORT_PATH = "/app/diagnostic_report.json"


def find_pdu(report, addr, pdu_type=None):
    """Find a PDU by advertiser address and optionally PDU type."""
    for pdu in report["pdus"]:
        if pdu.get("advertiser_address", "").upper() == addr.upper():
            if pdu_type is None or pdu.get("pdu_type", "").upper() == pdu_type.upper():
                return pdu
    return None


@pytest.fixture
def report():
    assert os.path.exists(REPORT_PATH), f"Report file not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        data = json.load(f)
    return data


class TestMultiFormatDiscovery:
    """Verify all 3 capture formats were decoded and combined."""

    def test_has_pdus_and_summary(self, report):
        assert "pdus" in report, "Report missing 'pdus' key"
        assert "summary" in report, "Report missing 'summary' key"
        assert isinstance(report["pdus"], list)

    def test_total_pdu_count(self, report):
        assert len(report["pdus"]) == 10, f"Expected 10 PDUs, got {len(report['pdus'])}"

    def test_all_pdu_types_present(self, report):
        types = [p["pdu_type"].upper() for p in report["pdus"]]
        assert types.count("ADV_IND") == 5
        assert types.count("ADV_NONCONN_IND") == 2
        assert types.count("SCAN_RSP") == 1
        assert types.count("ADV_DIRECT_IND") == 1
        assert types.count("ADV_SCAN_IND") == 1


class TestAddressDecoding:
    """Verify BLE address byte-order reversal (LSO-first PDU → MSO-first display)."""

    EXPECTED = [
        ("C3:A4:19:8B:E7:F2", "ADV_IND"),
        ("CB:89:67:45:23:D1", "ADV_NONCONN_IND"),
        ("CB:89:67:45:23:D1", "SCAN_RSP"),
        ("C5:F4:F3:F2:F1:F0", "ADV_DIRECT_IND"),
        ("CF:EE:DD:CC:BB:AA", "ADV_IND"),
        ("BC:9A:78:56:34:12", "ADV_IND"),
        ("C6:E5:E4:E3:E2:E1", "ADV_SCAN_IND"),
        ("C6:B5:B4:B3:B2:B1", "ADV_IND"),
        ("55:44:33:22:11:00", "ADV_NONCONN_IND"),
        ("FF:FF:FF:FF:FF:FF", "ADV_IND"),
    ]

    @pytest.mark.parametrize("addr,ptype", EXPECTED)
    def test_address_found(self, report, addr, ptype):
        pdu = find_pdu(report, addr, ptype)
        assert pdu is not None, f"PDU not found: addr={addr} type={ptype}"


class TestTxAddrType:
    """Verify TxAdd bit decoding — tests that dissector bug #1 is fixed."""

    CASES = [
        ("C3:A4:19:8B:E7:F2", "ADV_IND", "random"),
        ("CB:89:67:45:23:D1", "ADV_NONCONN_IND", "random"),
        ("CB:89:67:45:23:D1", "SCAN_RSP", "random"),
        ("C5:F4:F3:F2:F1:F0", "ADV_DIRECT_IND", "random"),
        ("CF:EE:DD:CC:BB:AA", "ADV_IND", "random"),
        ("BC:9A:78:56:34:12", "ADV_IND", "public"),
        ("C6:E5:E4:E3:E2:E1", "ADV_SCAN_IND", "random"),
        ("C6:B5:B4:B3:B2:B1", "ADV_IND", "random"),
        ("55:44:33:22:11:00", "ADV_NONCONN_IND", "public"),
        ("FF:FF:FF:FF:FF:FF", "ADV_IND", "random"),
    ]

    @pytest.mark.parametrize("addr,ptype,expected", CASES)
    def test_tx_addr_type(self, report, addr, ptype, expected):
        pdu = find_pdu(report, addr, ptype)
        assert pdu is not None, f"PDU not found: {addr} {ptype}"
        actual = pdu.get("tx_addr_type", "").lower()
        assert actual == expected, f"{addr}: expected tx_addr_type={expected}, got={actual}"


class TestADStructures:
    """Verify AD structure parsing across all capture formats."""

    def test_nordic_hrm_name(self, report):
        pdu = find_pdu(report, "C3:A4:19:8B:E7:F2", "ADV_IND")
        names = []
        for ad in pdu.get("ad_structures", []):
            if ad.get("ad_type") in (0x08, 0x09, 8, 9):
                names.append(ad.get("parsed", {}).get("name", ""))
        assert "Nordic_HRM" in names, f"Expected 'Nordic_HRM', found {names}"

    def test_nordic_hrm_16bit_uuids(self, report):
        pdu = find_pdu(report, "C3:A4:19:8B:E7:F2", "ADV_IND")
        found = set()
        for ad in pdu.get("ad_structures", []):
            if ad.get("ad_type") in (0x02, 0x03, 2, 3):
                for u in ad.get("parsed", {}).get("uuids", []):
                    found.add(u.upper())
        assert "180D" in found, f"Expected UUID 180D, found {found}"
        assert "180F" in found, f"Expected UUID 180F, found {found}"

    def test_nordic_hrm_ad_count(self, report):
        pdu = find_pdu(report, "C3:A4:19:8B:E7:F2", "ADV_IND")
        ads = pdu.get("ad_structures", [])
        assert len(ads) == 4, f"Expected 4 AD structures, got {len(ads)}"

    def test_beacon_name(self, report):
        pdu = find_pdu(report, "CB:89:67:45:23:D1", "ADV_NONCONN_IND")
        for ad in pdu.get("ad_structures", []):
            if ad.get("ad_type") in (0x08, 0x09, 8, 9):
                assert ad["parsed"]["name"] == "Beacon", f"Expected 'Beacon', got '{ad['parsed']['name']}'"
                return
        pytest.fail("Beacon name AD structure not found")

    def test_scan_rsp_tx_power(self, report):
        pdu = find_pdu(report, "CB:89:67:45:23:D1", "SCAN_RSP")
        for ad in pdu.get("ad_structures", []):
            if ad.get("ad_type") in (0x0A, 10):
                assert ad["parsed"]["tx_power_dbm"] == -4, f"Expected TX power -4, got {ad['parsed']['tx_power_dbm']}"
                return
        pytest.fail("TX Power Level AD not found in SCAN_RSP")

    def test_direct_ind_target_address(self, report):
        pdu = find_pdu(report, "C5:F4:F3:F2:F1:F0", "ADV_DIRECT_IND")
        target = pdu.get("target_address", "").upper()
        assert target == "66:55:44:33:22:11", f"Expected target 66:55:44:33:22:11, got {target}"

    def test_128bit_uuid_byte_reversal(self, report):
        """Verifies dissector bug #2 is fixed: 128-bit UUID byte order reversal."""
        expected = "12345678-1234-5678-9ABC-DE0012345678"
        pdu = find_pdu(report, "55:44:33:22:11:00", "ADV_NONCONN_IND")
        for ad in pdu.get("ad_structures", []):
            if ad.get("ad_type") in (0x07, 7):
                uuids = [u.upper() for u in ad.get("parsed", {}).get("uuids", [])]
                assert expected in uuids, f"Expected UUID {expected}, found {uuids}"
                return
        pytest.fail("128-bit UUID AD not found")

    def test_nordic_msd_company_id(self, report):
        """Verifies dissector bug #3 is fixed: Company ID endianness."""
        pdu = find_pdu(report, "BC:9A:78:56:34:12", "ADV_IND")
        for ad in pdu.get("ad_structures", []):
            if ad.get("ad_type") in (0xFF, 255):
                cid = ad.get("parsed", {}).get("company_id", "").upper()
                assert cid == "0059", f"Expected Nordic Company ID 0059, got {cid}"
                return
        pytest.fail("Manufacturer Specific Data not found")


class TestViolations:
    """Verify BLE specification violation detection."""

    def test_payload_exceeds_max(self, report):
        pdu = find_pdu(report, "CF:EE:DD:CC:BB:AA", "ADV_IND")
        v = pdu.get("violations", [])
        assert len(v) > 0, "Expected payload length violation"
        text = " ".join(str(x).lower() for x in v)
        assert any(k in text for k in ["exceed", "max", "length", "payload"]), f"Violation text: {v}"

    def test_flags_conflict(self, report):
        pdu = find_pdu(report, "C6:E5:E4:E3:E2:E1", "ADV_SCAN_IND")
        v = pdu.get("violations", [])
        assert len(v) > 0, "Expected flags conflict violation"
        text = " ".join(str(x).lower() for x in v)
        assert any(k in text for k in ["flag", "limited", "general", "conflict"]), f"Violation text: {v}"

    def test_truncated_ad(self, report):
        pdu = find_pdu(report, "C6:B5:B4:B3:B2:B1", "ADV_IND")
        v = pdu.get("violations", [])
        assert len(v) > 0, "Expected truncated AD violation"
        text = " ".join(str(x).lower() for x in v)
        assert any(k in text for k in ["truncat", "malform", "exceed", "incomplete", "length"]), f"Violation text: {v}"

    def test_invalid_static_random_address(self, report):
        pdu = find_pdu(report, "FF:FF:FF:FF:FF:FF", "ADV_IND")
        v = pdu.get("violations", [])
        assert len(v) > 0, "Expected invalid address violation"
        text = " ".join(str(x).lower() for x in v)
        assert any(k in text for k in ["address", "invalid", "static", "random"]), f"Violation text: {v}"

    VALID_PDUS = [
        ("C3:A4:19:8B:E7:F2", "ADV_IND"),
        ("CB:89:67:45:23:D1", "ADV_NONCONN_IND"),
        ("CB:89:67:45:23:D1", "SCAN_RSP"),
        ("C5:F4:F3:F2:F1:F0", "ADV_DIRECT_IND"),
        ("BC:9A:78:56:34:12", "ADV_IND"),
        ("55:44:33:22:11:00", "ADV_NONCONN_IND"),
    ]

    @pytest.mark.parametrize("addr,ptype", VALID_PDUS)
    def test_valid_pdus_no_violations(self, report, addr, ptype):
        pdu = find_pdu(report, addr, ptype)
        assert pdu is not None, f"PDU not found: {addr} {ptype}"
        v = pdu.get("violations", [])
        assert len(v) == 0, f"Expected no violations for {addr}, got {v}"


class TestSummary:
    """Verify aggregate summary statistics."""

    def test_total_pdus(self, report):
        assert report["summary"]["total_pdus"] == 10

    def test_valid_pdus(self, report):
        assert report["summary"]["valid_pdus"] == 6

    def test_invalid_pdus(self, report):
        assert report["summary"]["invalid_pdus"] == 4

    def test_unique_advertisers(self, report):
        assert report["summary"]["unique_advertisers"] == 9

    def test_nordic_msd_count(self, report):
        assert report["summary"]["nordic_msd_count"] == 3

    def test_pdu_type_counts(self, report):
        counts = report["summary"]["pdu_type_counts"]
        assert counts.get("ADV_IND") == 5
        assert counts.get("ADV_NONCONN_IND") == 2
        assert counts.get("SCAN_RSP") == 1
        assert counts.get("ADV_DIRECT_IND") == 1
        assert counts.get("ADV_SCAN_IND") == 1
