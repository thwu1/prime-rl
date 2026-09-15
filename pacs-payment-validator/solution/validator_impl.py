#!/usr/bin/env python3

"""ISO 20022 pacs.008 (FIToFI Customer Credit Transfer) validator."""

import sys
import os
import json
import re
import argparse
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from datetime import date, timedelta

SUPPORTED_NS = {
    f"urn:iso:std:iso:20022:tech:xsd:pacs.008.001.{v:02d}"
    for v in (8, 9, 10)
}

# ISO 4217 currency -> minor units.  None = N.A. (reject).
ISO4217 = {
    "AED": 2, "AFN": 2, "ALL": 2, "AMD": 2, "ANG": 2, "AOA": 2, "ARS": 2,
    "AUD": 2, "AWG": 2, "AZN": 2, "BAM": 2, "BBD": 2, "BDT": 2, "BGN": 2,
    "BHD": 3, "BIF": 0, "BMD": 2, "BND": 2, "BOB": 2, "BOV": 2, "BRL": 2,
    "BSD": 2, "BTN": 2, "BWP": 2, "BYN": 2, "BZD": 2, "CAD": 2, "CDF": 2,
    "CHE": 2, "CHF": 2, "CHW": 2, "CLF": 4, "CLP": 0, "CNY": 2, "COP": 2,
    "COU": 2, "CRC": 2, "CUP": 2, "CVE": 2, "CZK": 2, "DJF": 0, "DKK": 2,
    "DOP": 2, "DZD": 2, "EGP": 2, "ERN": 2, "ETB": 2, "EUR": 2, "FJD": 2,
    "FKP": 2, "GBP": 2, "GEL": 2, "GHS": 2, "GIP": 2, "GMD": 2, "GNF": 0,
    "GTQ": 2, "GYD": 2, "HKD": 2, "HNL": 2, "HTG": 2, "HUF": 2, "IDR": 2,
    "ILS": 2, "INR": 2, "IQD": 3, "IRR": 2, "ISK": 0, "JMD": 2, "JOD": 3,
    "JPY": 0, "KES": 2, "KGS": 2, "KHR": 2, "KMF": 0, "KPW": 2, "KRW": 0,
    "KWD": 3, "KYD": 2, "KZT": 2, "LAK": 2, "LBP": 2, "LKR": 2, "LRD": 2,
    "LSL": 2, "LYD": 3, "MAD": 2, "MDL": 2, "MGA": 2, "MKD": 2, "MMK": 2,
    "MNT": 2, "MOP": 2, "MRU": 2, "MUR": 2, "MVR": 2, "MWK": 2, "MXN": 2,
    "MXV": 2, "MYR": 2, "MZN": 2, "NAD": 2, "NGN": 2, "NIO": 2, "NOK": 2,
    "NPR": 2, "NZD": 2, "OMR": 3, "PAB": 2, "PEN": 2, "PGK": 2, "PHP": 2,
    "PKR": 2, "PLN": 2, "PYG": 0, "QAR": 2, "RON": 2, "RSD": 2, "RUB": 2,
    "RWF": 0, "SAR": 2, "SBD": 2, "SCR": 2, "SDG": 2, "SEK": 2, "SGD": 2,
    "SHP": 2, "SLE": 2, "SOS": 2, "SRD": 2, "SSP": 2, "STN": 2, "SVC": 2,
    "SYP": 2, "SZL": 2, "THB": 2, "TJS": 2, "TMT": 2, "TND": 3, "TOP": 2,
    "TRY": 2, "TTD": 2, "TWD": 2, "TZS": 2, "UAH": 2, "UGX": 0, "USD": 2,
    "USN": 2, "UYI": 0, "UYU": 2, "UYW": 4, "UZS": 2, "VED": 2, "VES": 2,
    "VND": 0, "VUV": 0, "WST": 2, "XAF": 0, "XAG": None, "XAU": None,
    "XBA": None, "XBB": None, "XBC": None, "XBD": None, "XCD": 2,
    "XCG": 2, "XDR": None, "XOF": 0, "XPD": None, "XPF": 0, "XPT": None,
    "XSU": None, "XTS": None, "XUA": None, "XXX": None, "XAD": 2,
    "YER": 2, "ZAR": 2, "ZMW": 2, "ZWG": 2,
}

# IBAN country -> expected total length  (75+ countries)
IBAN_LENGTHS = {
    "AL": 28, "AD": 24, "AT": 20, "AZ": 28, "BH": 22, "BY": 28, "BE": 16,
    "BA": 20, "BR": 29, "BG": 22, "CR": 22, "HR": 21, "CY": 28, "CZ": 24,
    "DK": 18, "DO": 28, "EG": 29, "EE": 20, "FI": 18, "FR": 27, "GE": 22,
    "DE": 22, "GI": 23, "GR": 27, "GT": 28, "HU": 28, "IS": 26, "IE": 22,
    "IL": 23, "IT": 27, "JO": 30, "KZ": 20, "XK": 20, "KW": 30, "LV": 21,
    "LB": 28, "LY": 25, "LI": 21, "LT": 20, "LU": 20, "MT": 31, "MR": 27,
    "MU": 30, "MD": 24, "MC": 27, "ME": 22, "NL": 18, "MK": 19, "NO": 15,
    "PK": 24, "PS": 29, "PL": 28, "PT": 25, "QA": 29, "RO": 24, "SM": 27,
    "SA": 24, "RS": 22, "SK": 24, "SI": 19, "ES": 24, "SE": 24, "CH": 21,
    "TN": 24, "TR": 26, "AE": 23, "GB": 22, "VA": 22, "SC": 31, "LC": 32,
    "ST": 25, "TL": 23, "VG": 24, "IQ": 23, "BI": 27, "DJ": 27, "GA": 27,
}

_BIC_RE = re.compile(r"^[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?$")
_IBAN_FMT_RE = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]+$")
_UUID4_RE = re.compile(
    r"^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$"
)


# ─── Easter (Anonymous Gregorian / Computus) ──────────────────

def compute_easter(year):
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    ll = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ll) // 451
    month = (h + ll - 7 * m + 114) // 31
    day = ((h + ll - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def is_target2_holiday(d):
    mm, dd = d.month, d.day
    if (mm, dd) in ((1, 1), (5, 1), (12, 25), (12, 26)):
        return True
    easter = compute_easter(d.year)
    if d == easter - timedelta(days=2):   # Good Friday
        return True
    if d == easter + timedelta(days=1):   # Easter Monday
        return True
    return False


# ─── XSD schema validation via xmllint ───────────────────────

def validate_xsd(filepath, ns_version, schema_dir):
    """Run xmllint --schema validation. Returns list of (rule_id, message)."""
    if not schema_dir:
        return []
    xsd_name = f"pacs.008.001.{ns_version}.xsd"
    xsd_path = os.path.join(schema_dir, xsd_name)
    if not os.path.isfile(xsd_path):
        return []
    try:
        result = subprocess.run(
            ["xmllint", "--noout", "--schema", xsd_path, filepath],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            msg = result.stderr.strip() or "XSD validation failed"
            return [("XSD_SCHEMA_FAIL", msg)]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    return []


# ─── Individual validators ────────────────────────────────────

def validate_iban(iban):
    errs = []
    if not _IBAN_FMT_RE.match(iban):
        errs.append(("IBAN_FORMAT", f"Invalid IBAN format: {iban}"))
        return errs
    cc = iban[:2]
    if cc in IBAN_LENGTHS and len(iban) != IBAN_LENGTHS[cc]:
        errs.append((
            "IBAN_LENGTH",
            f"IBAN length {len(iban)} wrong for {cc} "
            f"(expected {IBAN_LENGTHS[cc]})",
        ))
        return errs
    rearranged = iban[4:] + iban[:4]
    numeric = ""
    for ch in rearranged:
        if ch.isdigit():
            numeric += ch
        else:
            numeric += str(ord(ch) - 55)
    if int(numeric) % 97 != 1:
        errs.append(("IBAN_CHECKSUM", f"IBAN mod-97 failed: {iban}"))
    return errs


def validate_bic(bic):
    if not _BIC_RE.match(bic):
        return [("BIC_FORMAT", f"Invalid BIC: {bic}")]
    return []


def validate_ccy_amount(amount_str, ccy):
    errs = []
    if ccy not in ISO4217:
        errs.append(("CCY_INVALID", f"Unknown currency: {ccy}"))
        return errs
    mu = ISO4217[ccy]
    if mu is None:
        errs.append(("CCY_INVALID", f"Currency {ccy} has no minor units"))
        return errs
    if "." in amount_str:
        decimals = len(amount_str.rsplit(".", 1)[1])
        if decimals > mu:
            errs.append((
                "CCY_EXPONENT",
                f"{ccy} allows {mu} decimals but amount has {decimals}",
            ))
    return errs


# ─── File-level validator ─────────────────────────────────────

def _err(rule, msg, tx=None):
    return {"rule_id": rule, "message": msg, "tx_index": tx}


def validate_file(filepath, schema_dir=None):
    errors = []

    # Parse
    try:
        tree = ET.parse(filepath)
        root = tree.getroot()
    except ET.ParseError as exc:
        return {
            "file": filepath, "valid": False,
            "errors": [_err("XML_PARSE", str(exc))],
        }

    # Namespace
    tag = root.tag
    ns = tag[1:tag.index("}")] if tag.startswith("{") else ""
    if ns not in SUPPORTED_NS:
        return {
            "file": filepath, "valid": False,
            "errors": [_err("NS_INVALID", f"Unsupported namespace: {ns}")],
        }

    # XSD schema validation
    ns_version = ns.rsplit(".", 1)[-1] if ns else ""
    for rid, msg in validate_xsd(filepath, ns_version, schema_dir):
        errors.append(_err(rid, msg))

    def f(parent, path):
        parts = path.split("/")
        return parent.find("/".join(f"{{{ns}}}{p}" for p in parts))

    def fa(parent, path):
        parts = path.split("/")
        return parent.findall("/".join(f"{{{ns}}}{p}" for p in parts))

    fi2fi = f(root, "FIToFICstmrCdtTrf")
    if fi2fi is None:
        return {
            "file": filepath, "valid": False,
            "errors": [_err("XML_PARSE", "Missing FIToFICstmrCdtTrf")],
        }

    grp = f(fi2fi, "GrpHdr")
    if grp is None:
        return {
            "file": filepath, "valid": False,
            "errors": [_err("XML_PARSE", "Missing GrpHdr")],
        }

    # ── MsgId ──
    mid_el = f(grp, "MsgId")
    if mid_el is not None and mid_el.text:
        mid = mid_el.text
        if len(mid) > 35 or mid.startswith("/") or mid.endswith("/") or "//" in mid:
            errors.append(_err("MSGID_FORMAT", f"Invalid MsgId: {mid}"))

    # ── NbOfTxs ──
    txs = fa(fi2fi, "CdtTrfTxInf")
    nb_el = f(grp, "NbOfTxs")
    if nb_el is not None and nb_el.text:
        try:
            nb = int(nb_el.text)
            if nb != len(txs):
                errors.append(_err(
                    "NBOFTXS_MISMATCH",
                    f"NbOfTxs={nb} but found {len(txs)}",
                ))
        except ValueError:
            pass

    # ── Settlement date ──
    sd_el = f(grp, "IntrBkSttlmDt")
    if sd_el is not None and sd_el.text:
        try:
            y, m, d = sd_el.text.split("-")
            sd = date(int(y), int(m), int(d))
            if sd.weekday() >= 5:
                errors.append(_err(
                    "STTLM_DATE_WEEKEND",
                    f"Settlement date {sd_el.text} is a weekend",
                ))
            elif is_target2_holiday(sd):
                errors.append(_err(
                    "STTLM_DATE_HOLIDAY",
                    f"Settlement date {sd_el.text} is a TARGET2 holiday",
                ))
        except (ValueError, IndexError):
            pass

    # ── Settlement method ──
    sinf = f(grp, "SttlmInf")
    if sinf is not None:
        sm_el = f(sinf, "SttlmMtd")
        if sm_el is not None and sm_el.text:
            sm = sm_el.text
            if sm == "CLRG" and f(sinf, "ClrSys") is None:
                errors.append(_err("STTLM_CLRG_NO_CLRSYS",
                                   "CLRG without ClrSys"))
            if sm == "COVE":
                if (f(sinf, "InstgRmbrsmntAgt") is None and
                        f(sinf, "InstdRmbrsmntAgt") is None):
                    errors.append(_err("STTLM_COVE_NO_AGENT",
                                       "COVE without reimbursement agent"))

    # ── Group-level agents ──
    def _bic_of(parent, path):
        el = f(parent, path)
        return el.text if el is not None and el.text else None

    instg_bic = _bic_of(grp, "InstgAgt/FinInstnId/BICFI")
    instd_bic = _bic_of(grp, "InstdAgt/FinInstnId/BICFI")

    if instg_bic:
        for rid, msg in validate_bic(instg_bic):
            errors.append(_err(rid, msg))
    if instd_bic:
        for rid, msg in validate_bic(instd_bic):
            errors.append(_err(rid, msg))
    if instg_bic and instd_bic and instg_bic == instd_bic:
        errors.append(_err("INSTG_INSTD_SAME",
                           f"Same BIC: {instg_bic}"))

    # ── Transactions ──
    tx_amounts = []
    tx_ccys = []
    e2e_seen = {}

    for i, tx in enumerate(txs):
        # Amount
        amt_el = f(tx, "IntrBkSttlmAmt")
        if amt_el is not None:
            astr = amt_el.text or "0"
            ccy = amt_el.get("Ccy", "")
            try:
                val = Decimal(astr)
                if val <= 0:
                    errors.append(_err("AMT_NOT_POSITIVE",
                                       f"Amount {astr} not positive", i))
                tx_amounts.append(val)
            except InvalidOperation:
                tx_amounts.append(Decimal(0))
            for rid, msg in validate_ccy_amount(astr, ccy):
                errors.append(_err(rid, msg, i))
            tx_ccys.append(ccy)

            # InstdAmt / XchgRate
            ia_el = f(tx, "InstdAmt")
            xr_el = f(tx, "XchgRate")
            if ia_el is not None:
                ia_ccy = ia_el.get("Ccy", "")
                ia_str = ia_el.text or "0"
                for rid, msg in validate_ccy_amount(ia_str, ia_ccy):
                    errors.append(_err(rid, msg, i))
                if ia_ccy != ccy:
                    if xr_el is None:
                        errors.append(_err("XCHG_RATE_MISSING",
                                           "XchgRate required", i))
                else:
                    if xr_el is not None:
                        errors.append(_err("XCHG_RATE_NOT_ALLOWED",
                                           "XchgRate not allowed", i))

        # IBANs
        for acct_path in ("DbtrAcct/Id/IBAN", "CdtrAcct/Id/IBAN"):
            iban_el = f(tx, acct_path)
            if iban_el is not None and iban_el.text:
                for rid, msg in validate_iban(iban_el.text):
                    errors.append(_err(rid, msg, i))

        # BICs
        for agt_path in ("DbtrAgt/FinInstnId/BICFI",
                         "CdtrAgt/FinInstnId/BICFI"):
            bic_el = f(tx, agt_path)
            if bic_el is not None and bic_el.text:
                for rid, msg in validate_bic(bic_el.text):
                    errors.append(_err(rid, msg, i))

        # UETR
        uetr_el = f(tx, "PmtId/UETR")
        if uetr_el is not None and uetr_el.text:
            if not _UUID4_RE.match(uetr_el.text):
                errors.append(_err("UETR_FORMAT",
                                   f"Invalid UETR: {uetr_el.text}", i))

        # EndToEndId
        e2e_el = f(tx, "PmtId/EndToEndId")
        if e2e_el is not None and e2e_el.text:
            eid = e2e_el.text
            if eid in e2e_seen:
                errors.append(_err("E2EID_DUPLICATE",
                                   f"Duplicate EndToEndId: {eid}", i))
            else:
                e2e_seen[eid] = i

        # ChrgBr
        chrg_el = f(tx, "ChrgBr")
        if chrg_el is not None and chrg_el.text:
            if chrg_el.text not in ("DEBT", "CRED", "SHAR", "SLEV"):
                errors.append(_err("CHRG_BEARER_INVALID",
                                   f"Invalid ChrgBr: {chrg_el.text}", i))

        # Debtor / Creditor same account
        dbtr_iban_el = f(tx, "DbtrAcct/Id/IBAN")
        cdtr_iban_el = f(tx, "CdtrAcct/Id/IBAN")
        if (dbtr_iban_el is not None and cdtr_iban_el is not None
                and dbtr_iban_el.text and cdtr_iban_el.text
                and dbtr_iban_el.text == cdtr_iban_el.text):
            errors.append(_err("DBTR_CDTR_SAME_ACCT",
                               f"Same account: {dbtr_iban_el.text}", i))

    # ── TtlIntrBkSttlmAmt ──
    tot_el = f(grp, "TtlIntrBkSttlmAmt")
    if tot_el is not None and tot_el.text:
        tot_ccy = tot_el.get("Ccy", "")
        tot_str = tot_el.text
        for rid, msg in validate_ccy_amount(tot_str, tot_ccy):
            errors.append(_err(rid, msg))
        try:
            tot_val = Decimal(tot_str)
            if tx_amounts and tot_val != sum(tx_amounts):
                errors.append(_err(
                    "TOTAL_AMT_MISMATCH",
                    f"Total {tot_val} != sum {sum(tx_amounts)}",
                ))
        except InvalidOperation:
            pass
        for c in tx_ccys:
            if c != tot_ccy:
                errors.append(_err(
                    "TOTAL_AMT_CCY",
                    f"Total ccy {tot_ccy} != tx ccy {c}",
                ))
                break

    return {"file": filepath, "valid": len(errors) == 0, "errors": errors}


# ─── CLI ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="ISO 20022 pacs.008 validator"
    )
    parser.add_argument(
        "files", nargs="+",
        help="XML files to validate, or '-' for stdin"
    )
    parser.add_argument(
        "--format", choices=["json", "ndjson"], default="json",
        dest="output_format",
        help="Output format (default: json)"
    )
    parser.add_argument(
        "--schema-dir", default="/app/schemas/",
        dest="schema_dir",
        help="Directory containing XSD schema files (default: /app/schemas/)"
    )
    args = parser.parse_args()

    results = []
    for fpath in args.files:
        if fpath == "-":
            data = sys.stdin.read()
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".xml", delete=False
            ) as tmp:
                tmp.write(data)
                tmp_path = tmp.name
            r = validate_file(tmp_path, args.schema_dir)
            r["file"] = "<stdin>"
            os.unlink(tmp_path)
            results.append(r)
        else:
            results.append(validate_file(fpath, args.schema_dir))

    if args.output_format == "ndjson":
        for r in results:
            print(json.dumps(r))
    else:
        print(json.dumps(results, indent=2))

    sys.exit(1 if any(not r["valid"] for r in results) else 0)


if __name__ == "__main__":
    main()
