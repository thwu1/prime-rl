
"""
Tests for ISO 20022 pacs.008 validator.
Covers all 25 rule_ids, stdin support, NDJSON output, XSD validation, and edge cases.
"""

import json
import os
import subprocess
import tempfile

import pytest

VALID_UETR = "eb6305c9-1f7e-4c0d-ba1e-5e6b4a1348ac"
VALID_UETR_2 = "ab6305c9-1f7e-4c0d-9a1e-5e6b4a1348ac"
VALID_UETR_3 = "cb6305c9-1f7e-4c0d-8a1e-5e6b4a1348ac"


def default_tx(**overrides):
    tx = {
        "e2e_id": "E2E-001",
        "tx_id": "TX-001",
        "uetr": VALID_UETR,
        "amt": "1000.00",
        "ccy": "EUR",
        "instd_amt": None,
        "xchg_rate": None,
        "chrg_br": None,
        "dbtr_iban": "DE89370400440532013000",
        "dbtr_bic": "DEUTDEFF",
        "cdtr_iban": "GB29NWBK60161331926819",
        "cdtr_bic": "BARCGB22",
    }
    tx.update(overrides)
    return tx


def make_pacs008(
    ns_version="08",
    msg_id="MSG-20250303-001",
    nb_of_txs="1",
    total_amt=None,
    sttlm_dt="2025-03-03",
    sttlm_mtd="INDA",
    clr_sys=None,
    instg_rmbrsmt_agt=None,
    instd_rmbrsmt_agt=None,
    instg_bic="DEUTDEFF",
    instd_bic="BARCGB22",
    txs=None,
):
    ns = f"urn:iso:std:iso:20022:tech:xsd:pacs.008.001.{ns_version}"
    if txs is None:
        txs = [default_tx()]

    total_xml = ""
    if total_amt:
        total_xml = (
            f'<TtlIntrBkSttlmAmt Ccy="{total_amt[1]}">'
            f"{total_amt[0]}</TtlIntrBkSttlmAmt>"
        )

    clr_xml = ""
    if clr_sys:
        clr_xml = f"<ClrSys><Cd>{clr_sys}</Cd></ClrSys>"

    irmbrsmt_xml = ""
    if instg_rmbrsmt_agt:
        irmbrsmt_xml = (
            "<InstgRmbrsmntAgt><FinInstnId>"
            f"<BICFI>{instg_rmbrsmt_agt}</BICFI>"
            "</FinInstnId></InstgRmbrsmntAgt>"
        )

    drmbrsmt_xml = ""
    if instd_rmbrsmt_agt:
        drmbrsmt_xml = (
            "<InstdRmbrsmntAgt><FinInstnId>"
            f"<BICFI>{instd_rmbrsmt_agt}</BICFI>"
            "</FinInstnId></InstdRmbrsmntAgt>"
        )

    tx_parts = []
    for tx in txs:
        instd_xml = ""
        if tx.get("instd_amt"):
            instd_xml = (
                f'<InstdAmt Ccy="{tx["instd_amt"][1]}">'
                f'{tx["instd_amt"][0]}</InstdAmt>'
            )
        xr_xml = ""
        if tx.get("xchg_rate"):
            xr_xml = f'<XchgRate>{tx["xchg_rate"]}</XchgRate>'

        chrg_xml = ""
        if tx.get("chrg_br"):
            chrg_xml = f"<ChrgBr>{tx['chrg_br']}</ChrgBr>"

        tx_parts.append(
            f"""    <CdtTrfTxInf>
      <PmtId>
        <EndToEndId>{tx["e2e_id"]}</EndToEndId>
        <TxId>{tx["tx_id"]}</TxId>
        <UETR>{tx["uetr"]}</UETR>
      </PmtId>
      <IntrBkSttlmAmt Ccy="{tx["ccy"]}">{tx["amt"]}</IntrBkSttlmAmt>
      {instd_xml}
      {xr_xml}
      {chrg_xml}
      <Dbtr><Nm>Debtor</Nm></Dbtr>
      <DbtrAcct><Id><IBAN>{tx["dbtr_iban"]}</IBAN></Id></DbtrAcct>
      <DbtrAgt><FinInstnId><BICFI>{tx["dbtr_bic"]}</BICFI></FinInstnId></DbtrAgt>
      <CdtrAgt><FinInstnId><BICFI>{tx["cdtr_bic"]}</BICFI></FinInstnId></CdtrAgt>
      <Cdtr><Nm>Creditor</Nm></Cdtr>
      <CdtrAcct><Id><IBAN>{tx["cdtr_iban"]}</IBAN></Id></CdtrAcct>
    </CdtTrfTxInf>"""
        )

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="{ns}">
  <FIToFICstmrCdtTrf>
    <GrpHdr>
      <MsgId>{msg_id}</MsgId>
      <CreDtTm>2025-03-03T10:00:00Z</CreDtTm>
      <NbOfTxs>{nb_of_txs}</NbOfTxs>
      {total_xml}
      <IntrBkSttlmDt>{sttlm_dt}</IntrBkSttlmDt>
      <SttlmInf>
        <SttlmMtd>{sttlm_mtd}</SttlmMtd>
        {clr_xml}
        {irmbrsmt_xml}
        {drmbrsmt_xml}
      </SttlmInf>
      <InstgAgt><FinInstnId><BICFI>{instg_bic}</BICFI></FinInstnId></InstgAgt>
      <InstdAgt><FinInstnId><BICFI>{instd_bic}</BICFI></FinInstnId></InstdAgt>
    </GrpHdr>
{"".join(tx_parts)}
  </FIToFICstmrCdtTrf>
</Document>"""


def _run_validator(*xml_strings, extra_args=None):
    """Write XML strings to temp files, run validator, return (parsed_json, returncode)."""
    paths = []
    try:
        for xml in xml_strings:
            f = tempfile.NamedTemporaryFile(
                mode="w", suffix=".xml", delete=False
            )
            f.write(xml)
            f.close()
            paths.append(f.name)

        cmd = ["python3", "/app/validator.py"]
        if extra_args:
            cmd.extend(extra_args)
        cmd.extend(paths)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        parsed = json.loads(result.stdout)
        return parsed, result.returncode
    finally:
        for p in paths:
            os.unlink(p)


def validate_one(xml_string, extra_args=None):
    results, _ = _run_validator(xml_string, extra_args=extra_args)
    return results[0]


def rule_ids(result):
    return {e["rule_id"] for e in result.get("errors", [])}


# ──────────────────────────────────────────────
# Valid base case
# ──────────────────────────────────────────────
class TestValidMessage:
    def test_fully_valid(self):
        r = validate_one(make_pacs008())
        assert r["valid"] is True
        assert r["errors"] == []

    def test_ns_version_09(self):
        r = validate_one(make_pacs008(ns_version="09"))
        assert r["valid"] is True

    def test_ns_version_10(self):
        r = validate_one(make_pacs008(ns_version="10"))
        assert r["valid"] is True


# ──────────────────────────────────────────────
# XML / namespace
# ──────────────────────────────────────────────
class TestXMLParsing:
    def test_malformed_xml(self):
        r = validate_one("<<<not xml at all>>>")
        assert r["valid"] is False
        assert "XML_PARSE" in rule_ids(r)

    def test_invalid_namespace(self):
        r = validate_one(make_pacs008(ns_version="99"))
        assert r["valid"] is False
        assert "NS_INVALID" in rule_ids(r)


# ──────────────────────────────────────────────
# XSD schema validation
# ──────────────────────────────────────────────
class TestXSDValidation:
    def test_xsd_valid_no_error(self):
        """Structurally valid XML should not trigger XSD_SCHEMA_FAIL."""
        r = validate_one(make_pacs008())
        assert "XSD_SCHEMA_FAIL" not in rule_ids(r)

    def test_xsd_fail_extra_element(self):
        """Extra element in Document violates XSD structure."""
        ns = "urn:iso:std:iso:20022:tech:xsd:pacs.008.001.08"
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="{ns}">
  <FIToFICstmrCdtTrf>
    <GrpHdr>
      <MsgId>MSG001</MsgId>
      <CreDtTm>2025-03-03T10:00:00Z</CreDtTm>
      <NbOfTxs>1</NbOfTxs>
      <IntrBkSttlmDt>2025-03-03</IntrBkSttlmDt>
      <SttlmInf><SttlmMtd>INDA</SttlmMtd></SttlmInf>
      <InstgAgt><FinInstnId><BICFI>DEUTDEFF</BICFI></FinInstnId></InstgAgt>
      <InstdAgt><FinInstnId><BICFI>BARCGB22</BICFI></FinInstnId></InstdAgt>
    </GrpHdr>
    <CdtTrfTxInf>
      <PmtId>
        <EndToEndId>E2E-001</EndToEndId>
        <TxId>TX-001</TxId>
        <UETR>{VALID_UETR}</UETR>
      </PmtId>
      <IntrBkSttlmAmt Ccy="EUR">1000.00</IntrBkSttlmAmt>
      <Dbtr><Nm>Debtor</Nm></Dbtr>
      <DbtrAcct><Id><IBAN>DE89370400440532013000</IBAN></Id></DbtrAcct>
      <DbtrAgt><FinInstnId><BICFI>DEUTDEFF</BICFI></FinInstnId></DbtrAgt>
      <CdtrAgt><FinInstnId><BICFI>BARCGB22</BICFI></FinInstnId></CdtrAgt>
      <Cdtr><Nm>Creditor</Nm></Cdtr>
      <CdtrAcct><Id><IBAN>GB29NWBK60161331926819</IBAN></Id></CdtrAcct>
    </CdtTrfTxInf>
  </FIToFICstmrCdtTrf>
  <Bogus>unexpected</Bogus>
</Document>"""
        r = validate_one(xml)
        assert "XSD_SCHEMA_FAIL" in rule_ids(r)

    def test_xsd_skip_missing_schema(self):
        """When schema-dir has no matching XSD, XSD validation is skipped."""
        r = validate_one(
            make_pacs008(),
            extra_args=["--schema-dir", "/tmp/no_such_dir"],
        )
        assert "XSD_SCHEMA_FAIL" not in rule_ids(r)
        assert r["valid"] is True

    def test_xsd_version_09(self):
        """XSD validation works for namespace version 09."""
        r = validate_one(make_pacs008(ns_version="09"))
        assert "XSD_SCHEMA_FAIL" not in rule_ids(r)


# ──────────────────────────────────────────────
# MsgId
# ──────────────────────────────────────────────
class TestMsgId:
    def test_too_long(self):
        r = validate_one(make_pacs008(msg_id="A" * 36))
        assert "MSGID_FORMAT" in rule_ids(r)

    def test_starts_with_slash(self):
        r = validate_one(make_pacs008(msg_id="/MSG001"))
        assert "MSGID_FORMAT" in rule_ids(r)

    def test_ends_with_slash(self):
        r = validate_one(make_pacs008(msg_id="MSG001/"))
        assert "MSGID_FORMAT" in rule_ids(r)

    def test_double_slash(self):
        r = validate_one(make_pacs008(msg_id="MSG//001"))
        assert "MSGID_FORMAT" in rule_ids(r)

    def test_msgid_error_tx_index_null(self):
        r = validate_one(make_pacs008(msg_id="A" * 36))
        errs = [e for e in r["errors"] if e["rule_id"] == "MSGID_FORMAT"]
        assert len(errs) == 1
        assert errs[0]["tx_index"] is None


# ──────────────────────────────────────────────
# NbOfTxs
# ──────────────────────────────────────────────
class TestNbOfTxs:
    def test_mismatch(self):
        r = validate_one(make_pacs008(nb_of_txs="5"))
        assert "NBOFTXS_MISMATCH" in rule_ids(r)


# ──────────────────────────────────────────────
# TtlIntrBkSttlmAmt
# ──────────────────────────────────────────────
class TestTotalAmount:
    def test_amount_mismatch(self):
        r = validate_one(make_pacs008(total_amt=("1500.00", "EUR")))
        assert "TOTAL_AMT_MISMATCH" in rule_ids(r)

    def test_currency_mismatch(self):
        r = validate_one(make_pacs008(total_amt=("1000.00", "USD")))
        assert "TOTAL_AMT_CCY" in rule_ids(r)

    def test_matching_total(self):
        r = validate_one(make_pacs008(total_amt=("1000.00", "EUR")))
        assert "TOTAL_AMT_MISMATCH" not in rule_ids(r)
        assert "TOTAL_AMT_CCY" not in rule_ids(r)

    def test_two_tx_sum(self):
        txs = [
            default_tx(e2e_id="E1", tx_id="T1", amt="600.00"),
            default_tx(e2e_id="E2", tx_id="T2", amt="400.00",
                       uetr=VALID_UETR_2),
        ]
        r = validate_one(make_pacs008(
            nb_of_txs="2", total_amt=("1000.00", "EUR"), txs=txs
        ))
        assert "TOTAL_AMT_MISMATCH" not in rule_ids(r)

    def test_three_tx_decimal_precision(self):
        """Total-amount comparison must use exact decimal arithmetic."""
        txs = [
            default_tx(e2e_id="E1", tx_id="T1", amt="10.10"),
            default_tx(e2e_id="E2", tx_id="T2", amt="10.10",
                       uetr=VALID_UETR_2),
            default_tx(e2e_id="E3", tx_id="T3", amt="10.10",
                       uetr=VALID_UETR_3),
        ]
        r = validate_one(make_pacs008(
            nb_of_txs="3", total_amt=("30.30", "EUR"), txs=txs
        ))
        assert "TOTAL_AMT_MISMATCH" not in rule_ids(r)


# ──────────────────────────────────────────────
# IBAN
# ──────────────────────────────────────────────
class TestIBAN:
    def test_bad_checksum(self):
        r = validate_one(make_pacs008(
            txs=[default_tx(dbtr_iban="DE88370400440532013000")]
        ))
        assert "IBAN_CHECKSUM" in rule_ids(r)

    def test_wrong_length(self):
        r = validate_one(make_pacs008(
            txs=[default_tx(dbtr_iban="DE8937040044053201300")]
        ))
        assert "IBAN_LENGTH" in rule_ids(r)

    def test_bad_format_lowercase(self):
        r = validate_one(make_pacs008(
            txs=[default_tx(dbtr_iban="de89370400440532013000")]
        ))
        assert "IBAN_FORMAT" in rule_ids(r)

    def test_iban_error_has_tx_index(self):
        r = validate_one(make_pacs008(
            txs=[default_tx(dbtr_iban="DE88370400440532013000")]
        ))
        errs = [e for e in r["errors"] if e["rule_id"] == "IBAN_CHECKSUM"]
        assert len(errs) >= 1
        assert errs[0]["tx_index"] == 0

    def test_creditor_iban_checked(self):
        r = validate_one(make_pacs008(
            txs=[default_tx(cdtr_iban="GB28NWBK60161331926819")]
        ))
        assert "IBAN_CHECKSUM" in rule_ids(r)

    def test_french_iban_valid(self):
        r = validate_one(make_pacs008(
            txs=[default_tx(cdtr_iban="FR7630006000011234567890189")]
        ))
        assert "IBAN_CHECKSUM" not in rule_ids(r)
        assert "IBAN_LENGTH" not in rule_ids(r)

    def test_spanish_iban_valid(self):
        r = validate_one(make_pacs008(
            txs=[default_tx(cdtr_iban="ES9121000418450200051332")]
        ))
        assert "IBAN_CHECKSUM" not in rule_ids(r)

    def test_dutch_iban_valid(self):
        """NL91ABNA0417164300 is a valid 18-char Dutch IBAN."""
        r = validate_one(make_pacs008(
            txs=[default_tx(cdtr_iban="NL91ABNA0417164300")]
        ))
        assert "IBAN_LENGTH" not in rule_ids(r)
        assert "IBAN_CHECKSUM" not in rule_ids(r)

    def test_swiss_iban_valid(self):
        """CH9300762011623852957 is a valid 21-char Swiss IBAN."""
        r = validate_one(make_pacs008(
            txs=[default_tx(cdtr_iban="CH9300762011623852957")]
        ))
        assert "IBAN_LENGTH" not in rule_ids(r)
        assert "IBAN_CHECKSUM" not in rule_ids(r)

    def test_swiss_iban_debtor(self):
        """Swiss IBAN on debtor side must also pass validation."""
        r = validate_one(make_pacs008(
            txs=[default_tx(dbtr_iban="CH9300762011623852957",
                            dbtr_bic="UBSWCHZH")]
        ))
        assert "IBAN_LENGTH" not in rule_ids(r)
        assert "IBAN_CHECKSUM" not in rule_ids(r)


# ──────────────────────────────────────────────
# BIC
# ──────────────────────────────────────────────
class TestBIC:
    def test_too_short(self):
        r = validate_one(make_pacs008(
            txs=[default_tx(dbtr_bic="DEUT")]
        ))
        assert "BIC_FORMAT" in rule_ids(r)

    def test_digits_in_institution_code(self):
        r = validate_one(make_pacs008(
            txs=[default_tx(dbtr_bic="1234DEFF")]
        ))
        assert "BIC_FORMAT" in rule_ids(r)

    def test_valid_11_char_bic(self):
        r = validate_one(make_pacs008(
            txs=[default_tx(dbtr_bic="DEUTDEFF500")]
        ))
        assert "BIC_FORMAT" not in rule_ids(r)

    def test_wrong_length_9_chars(self):
        r = validate_one(make_pacs008(
            txs=[default_tx(dbtr_bic="DEUTDEFF5")]
        ))
        assert "BIC_FORMAT" in rule_ids(r)

    def test_invalid_10_char_bic(self):
        """10-char BICs are not valid per ISO 9362 (must be 8 or 11)."""
        r = validate_one(make_pacs008(
            txs=[default_tx(dbtr_bic="DEUTDEFF50")]
        ))
        assert "BIC_FORMAT" in rule_ids(r)


# ──────────────────────────────────────────────
# Currency / Amount
# ──────────────────────────────────────────────
class TestCurrency:
    def test_invalid_code(self):
        r = validate_one(make_pacs008(
            txs=[default_tx(ccy="XYZ")]
        ))
        assert "CCY_INVALID" in rule_ids(r)

    def test_jpy_with_decimals(self):
        r = validate_one(make_pacs008(
            txs=[default_tx(amt="1000.50", ccy="JPY")]
        ))
        assert "CCY_EXPONENT" in rule_ids(r)

    def test_jpy_no_decimals_ok(self):
        r = validate_one(make_pacs008(
            txs=[default_tx(amt="1000", ccy="JPY")]
        ))
        assert "CCY_EXPONENT" not in rule_ids(r)
        assert "CCY_INVALID" not in rule_ids(r)

    def test_bhd_three_decimals_ok(self):
        r = validate_one(make_pacs008(
            txs=[default_tx(amt="1000.123", ccy="BHD")]
        ))
        assert "CCY_EXPONENT" not in rule_ids(r)

    def test_bhd_four_decimals_bad(self):
        r = validate_one(make_pacs008(
            txs=[default_tx(amt="1000.1234", ccy="BHD")]
        ))
        assert "CCY_EXPONENT" in rule_ids(r)

    def test_clf_four_decimals_ok(self):
        r = validate_one(make_pacs008(
            txs=[default_tx(amt="100.1234", ccy="CLF")]
        ))
        assert "CCY_EXPONENT" not in rule_ids(r)

    def test_na_currency_rejected(self):
        r = validate_one(make_pacs008(
            txs=[default_tx(ccy="XAU")]
        ))
        assert "CCY_INVALID" in rule_ids(r)


# ──────────────────────────────────────────────
# Settlement date
# ──────────────────────────────────────────────
class TestSettlementDate:
    def test_saturday(self):
        r = validate_one(make_pacs008(sttlm_dt="2025-03-01"))
        assert "STTLM_DATE_WEEKEND" in rule_ids(r)

    def test_sunday(self):
        r = validate_one(make_pacs008(sttlm_dt="2025-03-02"))
        assert "STTLM_DATE_WEEKEND" in rule_ids(r)

    def test_new_year(self):
        r = validate_one(make_pacs008(sttlm_dt="2025-01-01"))
        assert "STTLM_DATE_HOLIDAY" in rule_ids(r)
        assert "STTLM_DATE_WEEKEND" not in rule_ids(r)

    def test_good_friday_2025(self):
        # Easter 2025 = April 20 => Good Friday = April 18
        r = validate_one(make_pacs008(sttlm_dt="2025-04-18"))
        assert "STTLM_DATE_HOLIDAY" in rule_ids(r)

    def test_easter_monday_2025(self):
        # Easter 2025 = April 20 => Easter Monday = April 21
        r = validate_one(make_pacs008(sttlm_dt="2025-04-21"))
        assert "STTLM_DATE_HOLIDAY" in rule_ids(r)

    def test_good_friday_2024(self):
        # Easter 2024 = March 31 => Good Friday = March 29
        r = validate_one(make_pacs008(sttlm_dt="2024-03-29"))
        assert "STTLM_DATE_HOLIDAY" in rule_ids(r)

    def test_easter_monday_2026(self):
        # Easter 2026 = April 5 => Easter Monday = April 6
        r = validate_one(make_pacs008(sttlm_dt="2026-04-06"))
        assert "STTLM_DATE_HOLIDAY" in rule_ids(r)

    def test_may_day(self):
        r = validate_one(make_pacs008(sttlm_dt="2025-05-01"))
        assert "STTLM_DATE_HOLIDAY" in rule_ids(r)

    def test_christmas(self):
        r = validate_one(make_pacs008(sttlm_dt="2025-12-25"))
        assert "STTLM_DATE_HOLIDAY" in rule_ids(r)

    def test_st_stephen(self):
        # Dec 26 is a TARGET2 holiday
        r = validate_one(make_pacs008(sttlm_dt="2025-12-26"))
        assert "STTLM_DATE_HOLIDAY" in rule_ids(r)

    def test_valid_business_day(self):
        r = validate_one(make_pacs008(sttlm_dt="2025-03-03"))
        assert "STTLM_DATE_WEEKEND" not in rule_ids(r)
        assert "STTLM_DATE_HOLIDAY" not in rule_ids(r)

    def test_day_after_easter_not_holiday(self):
        # Easter 2025 = April 20 (Sunday), April 22 (Tuesday) is NOT a holiday
        r = validate_one(make_pacs008(sttlm_dt="2025-04-22"))
        assert "STTLM_DATE_HOLIDAY" not in rule_ids(r)
        assert "STTLM_DATE_WEEKEND" not in rule_ids(r)


# ──────────────────────────────────────────────
# Amount positivity
# ──────────────────────────────────────────────
class TestAmountPositive:
    def test_zero(self):
        r = validate_one(make_pacs008(
            txs=[default_tx(amt="0")]
        ))
        assert "AMT_NOT_POSITIVE" in rule_ids(r)

    def test_negative(self):
        r = validate_one(make_pacs008(
            txs=[default_tx(amt="-100.00")]
        ))
        assert "AMT_NOT_POSITIVE" in rule_ids(r)


# ──────────────────────────────────────────────
# Exchange rate
# ──────────────────────────────────────────────
class TestExchangeRate:
    def test_missing_when_currencies_differ(self):
        r = validate_one(make_pacs008(
            txs=[default_tx(instd_amt=("500.00", "USD"))]
        ))
        assert "XCHG_RATE_MISSING" in rule_ids(r)

    def test_present_when_currencies_same(self):
        r = validate_one(make_pacs008(
            txs=[default_tx(instd_amt=("1000.00", "EUR"),
                            xchg_rate="1.0")]
        ))
        assert "XCHG_RATE_NOT_ALLOWED" in rule_ids(r)

    def test_present_when_currencies_differ_ok(self):
        r = validate_one(make_pacs008(
            txs=[default_tx(instd_amt=("500.00", "USD"),
                            xchg_rate="1.12")]
        ))
        assert "XCHG_RATE_MISSING" not in rule_ids(r)
        assert "XCHG_RATE_NOT_ALLOWED" not in rule_ids(r)


# ──────────────────────────────────────────────
# Agents
# ──────────────────────────────────────────────
class TestAgents:
    def test_same_instg_instd(self):
        r = validate_one(make_pacs008(
            instg_bic="DEUTDEFF", instd_bic="DEUTDEFF"
        ))
        assert "INSTG_INSTD_SAME" in rule_ids(r)

    def test_different_instg_instd_ok(self):
        r = validate_one(make_pacs008())
        assert "INSTG_INSTD_SAME" not in rule_ids(r)


# ──────────────────────────────────────────────
# UETR
# ──────────────────────────────────────────────
class TestUETR:
    def test_invalid_format(self):
        r = validate_one(make_pacs008(
            txs=[default_tx(uetr="not-a-valid-uuid-here")]
        ))
        assert "UETR_FORMAT" in rule_ids(r)

    def test_not_v4_version(self):
        r = validate_one(make_pacs008(
            txs=[default_tx(uetr="eb6305c9-1f7e-1c0d-ba1e-5e6b4a1348ac")]
        ))
        assert "UETR_FORMAT" in rule_ids(r)

    def test_not_v4_variant(self):
        r = validate_one(make_pacs008(
            txs=[default_tx(uetr="eb6305c9-1f7e-4c0d-0a1e-5e6b4a1348ac")]
        ))
        assert "UETR_FORMAT" in rule_ids(r)


# ──────────────────────────────────────────────
# EndToEndId
# ──────────────────────────────────────────────
class TestEndToEndId:
    def test_duplicate(self):
        txs = [
            default_tx(e2e_id="SAME-E2E", tx_id="TX-001"),
            default_tx(e2e_id="SAME-E2E", tx_id="TX-002",
                       uetr=VALID_UETR_2),
        ]
        r = validate_one(make_pacs008(nb_of_txs="2", txs=txs))
        assert "E2EID_DUPLICATE" in rule_ids(r)

    def test_unique_ok(self):
        txs = [
            default_tx(e2e_id="E2E-A", tx_id="TX-001"),
            default_tx(e2e_id="E2E-B", tx_id="TX-002",
                       uetr=VALID_UETR_2),
        ]
        r = validate_one(make_pacs008(nb_of_txs="2", txs=txs))
        assert "E2EID_DUPLICATE" not in rule_ids(r)


# ──────────────────────────────────────────────
# Settlement method
# ──────────────────────────────────────────────
class TestSettlementMethod:
    def test_clrg_no_clrsys(self):
        r = validate_one(make_pacs008(sttlm_mtd="CLRG"))
        assert "STTLM_CLRG_NO_CLRSYS" in rule_ids(r)

    def test_clrg_with_clrsys(self):
        r = validate_one(make_pacs008(sttlm_mtd="CLRG", clr_sys="TGT"))
        assert "STTLM_CLRG_NO_CLRSYS" not in rule_ids(r)

    def test_cove_no_agent(self):
        r = validate_one(make_pacs008(sttlm_mtd="COVE"))
        assert "STTLM_COVE_NO_AGENT" in rule_ids(r)

    def test_cove_with_instg_rmbrsmt(self):
        r = validate_one(make_pacs008(
            sttlm_mtd="COVE", instg_rmbrsmt_agt="DEUTDEFF"
        ))
        assert "STTLM_COVE_NO_AGENT" not in rule_ids(r)

    def test_cove_with_instd_rmbrsmt(self):
        r = validate_one(make_pacs008(
            sttlm_mtd="COVE", instd_rmbrsmt_agt="BARCGB22"
        ))
        assert "STTLM_COVE_NO_AGENT" not in rule_ids(r)


# ──────────────────────────────────────────────
# Charge bearer
# ──────────────────────────────────────────────
class TestChargeBearer:
    def test_invalid_value(self):
        r = validate_one(make_pacs008(
            txs=[default_tx(chrg_br="XXXX")]
        ))
        assert "CHRG_BEARER_INVALID" in rule_ids(r)

    def test_debt_valid(self):
        r = validate_one(make_pacs008(
            txs=[default_tx(chrg_br="DEBT")]
        ))
        assert "CHRG_BEARER_INVALID" not in rule_ids(r)

    def test_shar_valid(self):
        r = validate_one(make_pacs008(
            txs=[default_tx(chrg_br="SHAR")]
        ))
        assert "CHRG_BEARER_INVALID" not in rule_ids(r)

    def test_slev_valid(self):
        r = validate_one(make_pacs008(
            txs=[default_tx(chrg_br="SLEV")]
        ))
        assert "CHRG_BEARER_INVALID" not in rule_ids(r)

    def test_cred_valid(self):
        r = validate_one(make_pacs008(
            txs=[default_tx(chrg_br="CRED")]
        ))
        assert "CHRG_BEARER_INVALID" not in rule_ids(r)

    def test_absent_no_error(self):
        """ChrgBr is optional; absent element should not trigger error."""
        r = validate_one(make_pacs008())
        assert "CHRG_BEARER_INVALID" not in rule_ids(r)

    def test_invalid_bearer_tx_index(self):
        """CHRG_BEARER_INVALID error should carry the correct tx_index."""
        txs = [
            default_tx(e2e_id="E1", tx_id="T1"),
            default_tx(e2e_id="E2", tx_id="T2", uetr=VALID_UETR_2,
                       chrg_br="NOPE"),
        ]
        r = validate_one(make_pacs008(nb_of_txs="2", txs=txs))
        errs = [e for e in r["errors"] if e["rule_id"] == "CHRG_BEARER_INVALID"]
        assert len(errs) == 1
        assert errs[0]["tx_index"] == 1


# ──────────────────────────────────────────────
# Debtor / creditor same account
# ──────────────────────────────────────────────
class TestDbtrCdtrSameAcct:
    def test_same_iban(self):
        r = validate_one(make_pacs008(
            txs=[default_tx(
                dbtr_iban="DE89370400440532013000",
                cdtr_iban="DE89370400440532013000",
            )]
        ))
        assert "DBTR_CDTR_SAME_ACCT" in rule_ids(r)

    def test_different_ok(self):
        r = validate_one(make_pacs008())
        assert "DBTR_CDTR_SAME_ACCT" not in rule_ids(r)

    def test_same_acct_tx_index(self):
        """Same-account error should report correct tx_index."""
        txs = [
            default_tx(e2e_id="E1", tx_id="T1"),
            default_tx(e2e_id="E2", tx_id="T2", uetr=VALID_UETR_2,
                       dbtr_iban="GB29NWBK60161331926819",
                       cdtr_iban="GB29NWBK60161331926819"),
        ]
        r = validate_one(make_pacs008(nb_of_txs="2", txs=txs))
        errs = [e for e in r["errors"] if e["rule_id"] == "DBTR_CDTR_SAME_ACCT"]
        assert len(errs) == 1
        assert errs[0]["tx_index"] == 1

    def test_same_acct_multi_tx(self):
        """Multiple transactions with same-account should each be flagged."""
        txs = [
            default_tx(e2e_id="E1", tx_id="T1",
                       dbtr_iban="DE89370400440532013000",
                       cdtr_iban="DE89370400440532013000"),
            default_tx(e2e_id="E2", tx_id="T2", uetr=VALID_UETR_2,
                       dbtr_iban="GB29NWBK60161331926819",
                       cdtr_iban="GB29NWBK60161331926819"),
        ]
        r = validate_one(make_pacs008(nb_of_txs="2", txs=txs))
        errs = [e for e in r["errors"] if e["rule_id"] == "DBTR_CDTR_SAME_ACCT"]
        assert len(errs) == 2
        assert errs[0]["tx_index"] == 0
        assert errs[1]["tx_index"] == 1


# ──────────────────────────────────────────────
# Exit codes & multi-file
# ──────────────────────────────────────────────
class TestExitCode:
    def test_exit_0_when_valid(self):
        _, rc = _run_validator(make_pacs008())
        assert rc == 0

    def test_exit_1_when_invalid(self):
        _, rc = _run_validator(make_pacs008(msg_id="A" * 36))
        assert rc == 1

    def test_multiple_files(self):
        valid_xml = make_pacs008()
        invalid_xml = make_pacs008(msg_id="A" * 36)
        results, rc = _run_validator(valid_xml, invalid_xml)
        assert len(results) == 2
        assert results[0]["valid"] is True
        assert results[1]["valid"] is False
        assert rc == 1

    def test_both_valid(self):
        results, rc = _run_validator(
            make_pacs008(msg_id="MSGA"),
            make_pacs008(msg_id="MSGB"),
        )
        assert len(results) == 2
        assert results[0]["valid"] is True
        assert results[1]["valid"] is True
        assert rc == 0


# ──────────────────────────────────────────────
# Combined errors
# ──────────────────────────────────────────────
class TestMultipleErrors:
    def test_several_errors_in_one_file(self):
        r = validate_one(make_pacs008(
            msg_id="A" * 36,
            nb_of_txs="5",
            sttlm_dt="2025-03-01",
        ))
        ids = rule_ids(r)
        assert "MSGID_FORMAT" in ids
        assert "NBOFTXS_MISMATCH" in ids
        assert "STTLM_DATE_WEEKEND" in ids
        assert r["valid"] is False

    def test_combined_iban_and_bearer(self):
        """Multiple distinct errors on the same transaction."""
        r = validate_one(make_pacs008(
            txs=[default_tx(
                dbtr_iban="DE88370400440532013000",
                chrg_br="INVALID",
            )]
        ))
        ids = rule_ids(r)
        assert "IBAN_CHECKSUM" in ids
        assert "CHRG_BEARER_INVALID" in ids


# ──────────────────────────────────────────────
# Stdin support
# ──────────────────────────────────────────────
class TestStdinSupport:
    def test_stdin_dash(self):
        """Passing '-' as filename reads from stdin."""
        xml = make_pacs008()
        result = subprocess.run(
            ["python3", "/app/validator.py", "-"],
            input=xml,
            capture_output=True,
            text=True,
            timeout=30,
        )
        parsed = json.loads(result.stdout)
        assert len(parsed) == 1
        assert parsed[0]["valid"] is True
        assert parsed[0]["file"] == "<stdin>"

    def test_stdin_mixed_with_file(self):
        """Stdin ('-') can be combined with file path arguments."""
        xml_stdin = make_pacs008(msg_id="STDIN-MSG")
        xml_file = make_pacs008(msg_id="FILE-MSG")
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False)
        f.write(xml_file)
        f.close()
        try:
            result = subprocess.run(
                ["python3", "/app/validator.py", "-", f.name],
                input=xml_stdin,
                capture_output=True,
                text=True,
                timeout=30,
            )
            parsed = json.loads(result.stdout)
            assert len(parsed) == 2
            assert parsed[0]["file"] == "<stdin>"
            assert parsed[0]["valid"] is True
            assert parsed[1]["file"] == f.name
            assert parsed[1]["valid"] is True
        finally:
            os.unlink(f.name)


# ──────────────────────────────────────────────
# NDJSON output
# ──────────────────────────────────────────────
class TestNDJSON:
    def test_ndjson_single(self):
        """--format ndjson outputs one JSON object per line."""
        xml = make_pacs008()
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False)
        f.write(xml)
        f.close()
        try:
            result = subprocess.run(
                ["python3", "/app/validator.py", "--format", "ndjson", f.name],
                capture_output=True,
                text=True,
                timeout=30,
            )
            lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
            assert len(lines) == 1
            obj = json.loads(lines[0])
            assert obj["valid"] is True
            assert obj["file"] == f.name
        finally:
            os.unlink(f.name)

    def test_ndjson_multi(self):
        """Multiple files produce one NDJSON line each."""
        xml1 = make_pacs008(msg_id="MSG1")
        xml2 = make_pacs008(msg_id="A" * 36)
        paths = []
        for xml in (xml1, xml2):
            f = tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False)
            f.write(xml)
            f.close()
            paths.append(f.name)
        try:
            result = subprocess.run(
                ["python3", "/app/validator.py", "--format", "ndjson"] + paths,
                capture_output=True,
                text=True,
                timeout=30,
            )
            lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
            assert len(lines) == 2
            r1 = json.loads(lines[0])
            r2 = json.loads(lines[1])
            assert r1["valid"] is True
            assert r2["valid"] is False
        finally:
            for p in paths:
                os.unlink(p)

    def test_ndjson_exit_code(self):
        """NDJSON mode still produces correct exit codes."""
        xml = make_pacs008()
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False)
        f.write(xml)
        f.close()
        try:
            result = subprocess.run(
                ["python3", "/app/validator.py", "--format", "ndjson", f.name],
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert result.returncode == 0
        finally:
            os.unlink(f.name)
