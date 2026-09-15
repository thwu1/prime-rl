#!/usr/bin/env python3
"""Financial Identifier Validation and Cross-Reference Engine.

"""

import json
import os
import re
import sqlite3
import sys


# ======================== iban.dat Parser ========================

_prop_re = re.compile(r'([a-z_]+)="([^"]*)"')


def parse_iban_dat(filepath):
    """Parse python-stdnum numdb-format iban.dat to extract BBAN specs."""
    bban_formats = {}
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            cc = line[:2]
            if not cc.isalpha():
                continue
            props = dict(_prop_re.findall(line))
            bban = props.get('bban', '')
            if not bban:
                continue
            tokens = re.findall(r'(\d+)![nac]', bban)
            bban_length = sum(int(t) for t in tokens)
            iban_length = 4 + bban_length
            bban_formats[cc] = {
                'bban': bban,
                'iban_length': iban_length,
            }
    return bban_formats


# ======================== ISO 7064 Mod 97, 10 ========================

def _mod97_to_base10(number):
    return ''.join(str(int(c, 36)) for c in number)


def mod97_checksum(number):
    return int(_mod97_to_base10(number)) % 97


def mod97_calc_check_digits(number):
    return '%02d' % (98 - mod97_checksum(number + '00'))


# ======================== BBAN Structure Parser ========================

_bban_token_re = re.compile(r'(\d+)!([nac])')


def bban_to_regex(structure):
    chars_map = {'n': '[0-9]', 'a': '[A-Z]', 'c': '[A-Za-z0-9]'}
    parts = []
    for m in _bban_token_re.finditer(structure):
        parts.append(f"{chars_map[m.group(2)]}{{{m.group(1)}}}")
    return re.compile('^' + ''.join(parts) + '$')


# ======================== IBAN ========================

def iban_compact(number):
    return re.sub(r'[\s.\-]', '', number).upper()


def iban_validate(number, bban_formats):
    number = iban_compact(number)
    if len(number) < 5:
        return False, 'invalid_length', number
    cc = number[:2]
    if not cc.isalpha():
        return False, 'invalid_format', number
    if not number[2:4].isdigit():
        return False, 'invalid_format', number
    rearranged = number[4:] + number[:4]
    if mod97_checksum(rearranged) != 1:
        return False, 'invalid_checksum', number
    if cc not in bban_formats:
        return False, 'invalid_component', number
    fmt = bban_formats[cc]
    if len(number) != fmt['iban_length']:
        return False, 'invalid_length', number
    bban = number[4:]
    if not bban_to_regex(fmt['bban']).match(bban):
        return False, 'invalid_format', number
    return True, None, number


def iban_calc_check_digits(number):
    number = iban_compact(number)
    body = number[4:] + number[:2]
    return mod97_calc_check_digits(body)


# ======================== BIC ========================

_bic_re = re.compile(r'^[A-Z]{4}([A-Z]{2})[0-9A-Z]{2}([0-9A-Z]{3})?$')

_bic_country_codes = {
    'AD', 'AE', 'AF', 'AG', 'AI', 'AL', 'AM', 'AO', 'AQ', 'AR', 'AS', 'AT',
    'AU', 'AW', 'AX', 'AZ', 'BA', 'BB', 'BD', 'BE', 'BF', 'BG', 'BH', 'BI',
    'BJ', 'BL', 'BM', 'BN', 'BO', 'BQ', 'BR', 'BS', 'BT', 'BV', 'BW', 'BY',
    'BZ', 'CA', 'CC', 'CD', 'CF', 'CG', 'CH', 'CI', 'CK', 'CL', 'CM', 'CN',
    'CO', 'CR', 'CU', 'CV', 'CW', 'CX', 'CY', 'CZ', 'DE', 'DJ', 'DK', 'DM',
    'DO', 'DZ', 'EC', 'EE', 'EG', 'EH', 'ER', 'ES', 'ET', 'FI', 'FJ', 'FK',
    'FM', 'FO', 'FR', 'GA', 'GB', 'GD', 'GE', 'GF', 'GG', 'GH', 'GI', 'GL',
    'GM', 'GN', 'GP', 'GQ', 'GR', 'GS', 'GT', 'GU', 'GW', 'GY', 'HK', 'HM',
    'HN', 'HR', 'HT', 'HU', 'ID', 'IE', 'IL', 'IM', 'IN', 'IO', 'IQ', 'IR',
    'IS', 'IT', 'JE', 'JM', 'JO', 'JP', 'KE', 'KG', 'KH', 'KI', 'KM', 'KN',
    'KP', 'KR', 'KW', 'KY', 'KZ', 'LA', 'LB', 'LC', 'LI', 'LK', 'LR', 'LS',
    'LT', 'LU', 'LV', 'LY', 'MA', 'MC', 'MD', 'ME', 'MF', 'MG', 'MH', 'MK',
    'ML', 'MM', 'MN', 'MO', 'MP', 'MQ', 'MR', 'MS', 'MT', 'MU', 'MV', 'MW',
    'MX', 'MY', 'MZ', 'NA', 'NC', 'NE', 'NF', 'NG', 'NI', 'NL', 'NO', 'NP',
    'NR', 'NU', 'NZ', 'OM', 'PA', 'PE', 'PF', 'PG', 'PH', 'PK', 'PL', 'PM',
    'PN', 'PR', 'PS', 'PT', 'PW', 'PY', 'QA', 'RE', 'RO', 'RS', 'RU', 'RW',
    'SA', 'SB', 'SC', 'SD', 'SE', 'SG', 'SH', 'SI', 'SJ', 'SK', 'SL', 'SM',
    'SN', 'SO', 'SR', 'SS', 'ST', 'SV', 'SX', 'SY', 'SZ', 'TC', 'TD', 'TF',
    'TG', 'TH', 'TJ', 'TK', 'TL', 'TM', 'TN', 'TO', 'TR', 'TT', 'TV', 'TW',
    'TZ', 'UA', 'UG', 'UM', 'US', 'UY', 'UZ', 'VA', 'VC', 'VE', 'VG', 'VI',
    'VN', 'VU', 'WF', 'WS', 'XK', 'YE', 'YT', 'ZA', 'ZM', 'ZW',
}


def bic_compact(number):
    return re.sub(r'[\s\-]', '', number).upper()


def bic_validate(number):
    number = bic_compact(number)
    if len(number) not in (8, 11):
        return False, 'invalid_length', number
    m = _bic_re.match(number)
    if not m:
        return False, 'invalid_format', number
    if m.group(1) not in _bic_country_codes:
        return False, 'invalid_component', number
    return True, None, number


# ======================== LEI ========================

def lei_compact(number):
    return re.sub(r'[\s\-]', '', number).upper()


def lei_validate(number):
    number = lei_compact(number)
    if len(number) != 20:
        return False, 'invalid_length', number
    if not re.match(r'^[0-9A-Z]+$', number):
        return False, 'invalid_format', number
    if mod97_checksum(number) != 1:
        return False, 'invalid_checksum', number
    return True, None, number


# ======================== ISIN ========================

_isin_alpha = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'

_isin_country_codes = {
    'AD', 'AE', 'AF', 'AG', 'AI', 'AL', 'AM', 'AN', 'AO', 'AQ', 'AR', 'AS',
    'AT', 'AU', 'AW', 'AX', 'AZ', 'BA', 'BB', 'BD', 'BE', 'BF', 'BG', 'BH',
    'BI', 'BJ', 'BL', 'BM', 'BN', 'BO', 'BQ', 'BR', 'BS', 'BT', 'BV', 'BW',
    'BY', 'BZ', 'CA', 'CC', 'CD', 'CF', 'CG', 'CH', 'CI', 'CK', 'CL', 'CM',
    'CN', 'CO', 'CR', 'CS', 'CU', 'CV', 'CW', 'CX', 'CY', 'CZ', 'DE', 'DJ',
    'DK', 'DM', 'DO', 'DZ', 'EC', 'EE', 'EG', 'EH', 'ER', 'ES', 'ET', 'FI',
    'FJ', 'FK', 'FM', 'FO', 'FR', 'GA', 'GB', 'GD', 'GE', 'GF', 'GG', 'GH',
    'GI', 'GL', 'GM', 'GN', 'GP', 'GQ', 'GR', 'GS', 'GT', 'GU', 'GW', 'GY',
    'HK', 'HM', 'HN', 'HR', 'HT', 'HU', 'ID', 'IE', 'IL', 'IM', 'IN', 'IO',
    'IQ', 'IR', 'IS', 'IT', 'JE', 'JM', 'JO', 'JP', 'KE', 'KG', 'KH', 'KI',
    'KM', 'KN', 'KP', 'KR', 'KW', 'KY', 'KZ', 'LA', 'LB', 'LC', 'LI', 'LK',
    'LR', 'LS', 'LT', 'LU', 'LV', 'LY', 'MA', 'MC', 'MD', 'ME', 'MF', 'MG',
    'MH', 'MK', 'ML', 'MM', 'MN', 'MO', 'MP', 'MQ', 'MR', 'MS', 'MT', 'MU',
    'MV', 'MW', 'MX', 'MY', 'MZ', 'NA', 'NC', 'NE', 'NF', 'NG', 'NI', 'NL',
    'NO', 'NP', 'NR', 'NU', 'NZ', 'OM', 'PA', 'PE', 'PF', 'PG', 'PH', 'PK',
    'PL', 'PM', 'PN', 'PR', 'PS', 'PT', 'PW', 'PY', 'QA', 'RE', 'RO', 'RS',
    'RU', 'RW', 'SA', 'SB', 'SC', 'SD', 'SE', 'SG', 'SH', 'SI', 'SJ', 'SK',
    'SL', 'SM', 'SN', 'SO', 'SR', 'SS', 'ST', 'SV', 'SX', 'SY', 'SZ', 'TC',
    'TD', 'TF', 'TG', 'TH', 'TJ', 'TK', 'TL', 'TM', 'TN', 'TO', 'TR', 'TT',
    'TV', 'TW', 'TZ', 'UA', 'UG', 'UM', 'US', 'UY', 'UZ', 'VA', 'VC', 'VE',
    'VG', 'VI', 'VN', 'VU', 'WF', 'WS', 'YE', 'YT', 'ZA', 'ZM', 'ZW',
    'EU', 'QS', 'QT', 'XA', 'XB', 'XC', 'XD', 'XF', 'XK', 'XS',
}


def isin_compact(number):
    return re.sub(r'\s', '', number).upper()


def isin_calc_check_digit(number):
    digits = ''.join(str(_isin_alpha.index(c)) for c in number)
    weighted = ''.join(
        str((2, 1)[i % 2] * int(d))
        for i, d in enumerate(reversed(digits))
    )
    s = sum(int(c) for c in weighted)
    return str((10 - s % 10) % 10)


def isin_validate(number):
    number = isin_compact(number)
    if not all(c in _isin_alpha for c in number):
        return False, 'invalid_format', number
    if len(number) != 12:
        return False, 'invalid_length', number
    if number[:2] not in _isin_country_codes:
        return False, 'invalid_component', number
    if isin_calc_check_digit(number[:11]) != number[11]:
        return False, 'invalid_checksum', number
    return True, None, number


# ======================== CUSIP ========================

_cusip_alpha = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ*@#'


def cusip_compact(number):
    return re.sub(r'\s', '', number).upper()


def cusip_calc_check_digit(number):
    weighted = ''.join(
        str((1, 2)[i % 2] * _cusip_alpha.index(c))
        for i, c in enumerate(number)
    )
    s = sum(int(d) for d in weighted)
    return str((10 - s % 10) % 10)


def cusip_validate(number):
    number = cusip_compact(number)
    if not all(c in _cusip_alpha for c in number):
        return False, 'invalid_format', number
    if len(number) != 9:
        return False, 'invalid_length', number
    if cusip_calc_check_digit(number[:8]) != number[8]:
        return False, 'invalid_checksum', number
    return True, None, number


# ======================== FIGI ========================

_figi_valid_chars = set('0123456789BCDFGHJKLMNPQRSTVWXYZ')
_figi_alpha = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'
_figi_excluded = {'BS', 'BM', 'GG', 'GB', 'VG'}


def figi_compact(number):
    return re.sub(r'\s', '', number).upper()


def figi_calc_check_digit(number):
    weighted = ''.join(
        str(_figi_alpha.index(c) * (1, 2)[i % 2])
        for i, c in enumerate(number[:11])
    )
    s = sum(int(d) for d in weighted)
    return str((10 - s % 10) % 10)


def figi_validate(number):
    number = figi_compact(number)
    if not all(c in _figi_valid_chars for c in number):
        return False, 'invalid_format', number
    if len(number) != 12:
        return False, 'invalid_length', number
    if number[0].isdigit() or number[1].isdigit():
        return False, 'invalid_format', number
    if number[:2] in _figi_excluded:
        return False, 'invalid_component', number
    if number[2] != 'G':
        return False, 'invalid_component', number
    if figi_calc_check_digit(number) != number[11]:
        return False, 'invalid_checksum', number
    return True, None, number


# ======================== SEDOL ========================

_sedol_alpha = '0123456789 BCD FGH JKLMN PQRST VWXYZ'
_sedol_weights = (1, 3, 1, 7, 3, 9)


def sedol_compact(number):
    return re.sub(r'\s', '', number).upper()


def sedol_calc_check_digit(number):
    s = sum(w * _sedol_alpha.index(c) for w, c in zip(_sedol_weights, number))
    return str((10 - s % 10) % 10)


def sedol_validate(number):
    number = sedol_compact(number)
    if not all(c in _sedol_alpha for c in number):
        return False, 'invalid_format', number
    if len(number) != 7:
        return False, 'invalid_length', number
    if number[0].isdigit() and not number.isdigit():
        return False, 'invalid_format', number
    if sedol_calc_check_digit(number[:6]) != number[6]:
        return False, 'invalid_checksum', number
    return True, None, number


# ======================== Auto-detection ========================

def auto_detect(value, bban_formats):
    compact_fallback = re.sub(r'[\s.\-]', '', value).upper()

    valid, error, comp = iban_validate(value, bban_formats)
    if valid:
        return 'iban', True, None, comp

    valid, error, comp = figi_validate(value)
    if valid:
        return 'figi', True, None, comp

    valid, error, comp = isin_validate(value)
    if valid:
        return 'isin', True, None, comp

    valid, error, comp = lei_validate(value)
    if valid:
        return 'lei', True, None, comp

    valid, error, comp = bic_validate(value)
    if valid:
        return 'bic', True, None, comp

    valid, error, comp = cusip_validate(value)
    if valid:
        return 'cusip', True, None, comp

    valid, error, comp = sedol_validate(value)
    if valid:
        return 'sedol', True, None, comp

    return 'unknown', False, 'invalid_format', compact_fallback


# ======================== Repair ========================

def repair(value, id_type):
    if id_type == 'iban':
        c = iban_compact(value)
        body = c[4:] + c[:2]
        chk = mod97_calc_check_digits(body)
        return c[:2] + chk + c[4:], chk
    elif id_type == 'cusip':
        c = cusip_compact(value)
        body = c[:8]
        chk = cusip_calc_check_digit(body)
        return body + chk, chk
    elif id_type == 'isin':
        c = isin_compact(value)
        body = c[:11]
        chk = isin_calc_check_digit(body)
        return body + chk, chk
    elif id_type == 'sedol':
        c = sedol_compact(value)
        body = c[:6]
        chk = sedol_calc_check_digit(body)
        return body + chk, chk
    elif id_type == 'figi':
        c = figi_compact(value)
        body = c[:11]
        chk = figi_calc_check_digit(body)
        return body + chk, chk
    elif id_type == 'lei':
        c = lei_compact(value)
        body = c[:18]
        chk = mod97_calc_check_digits(body)
        return body + chk, chk
    return value, ''


# ======================== Main ========================

_known_types = {'iban', 'bic', 'lei', 'isin', 'cusip', 'figi', 'sedol'}

_validators = {
    'iban': lambda v, bf: iban_validate(v, bf),
    'bic': lambda v, bf: bic_validate(v),
    'lei': lambda v, bf: lei_validate(v),
    'isin': lambda v, bf: isin_validate(v),
    'cusip': lambda v, bf: cusip_validate(v),
    'figi': lambda v, bf: figi_validate(v),
    'sedol': lambda v, bf: sedol_validate(v),
}


_CROSS_REF_VIEW_SQL = """
CREATE VIEW cross_references AS
    SELECT
        c.record_id,
        'cusip_isin' AS "check",
        CASE WHEN SUBSTR(i.compact, 3, 9) = c.compact
             THEN 1 ELSE 0 END AS consistent
    FROM validations c
    JOIN validations i ON c.record_id = i.record_id
    WHERE c.detected_type = 'cusip' AND c.valid = 1
      AND i.detected_type = 'isin' AND i.valid = 1

    UNION ALL

    SELECT
        s.record_id,
        'sedol_isin' AS "check",
        CASE WHEN SUBSTR(i.compact, 3, 9) = SUBSTR('000000000' || s.compact, -9)
             THEN 1 ELSE 0 END AS consistent
    FROM validations s
    JOIN validations i ON s.record_id = i.record_id
    WHERE s.detected_type = 'sedol' AND s.valid = 1
      AND i.detected_type = 'isin' AND i.valid = 1

    UNION ALL

    SELECT
        ib.record_id,
        'iban_bic_country' AS "check",
        CASE WHEN SUBSTR(ib.compact, 1, 2) = SUBSTR(bi.compact, 5, 2)
             THEN 1 ELSE 0 END AS consistent
    FROM validations ib
    JOIN validations bi ON ib.record_id = bi.record_id
    WHERE ib.detected_type = 'iban' AND ib.valid = 1
      AND bi.detected_type = 'bic' AND bi.valid = 1
"""


def main():
    input_path = sys.argv[1]
    bban_path = sys.argv[2]
    db_path = sys.argv[3]
    output_path = sys.argv[4]

    with open(input_path) as f:
        records = json.load(f)
    bban_formats = parse_iban_dat(bban_path)

    all_validations = []
    all_repairs = []

    for record in records:
        rid = record['id']
        rec_vals = []

        if 'identifiers' in record:
            for field, value in record['identifiers'].items():
                fl = field.lower()
                if fl in _known_types:
                    det_type = fl
                    valid, error, comp = _validators[fl](value, bban_formats)
                else:
                    det_type, valid, error, comp = auto_detect(value, bban_formats)

                entry = {
                    'record_id': rid,
                    'field': field,
                    'input': value,
                    'compact': comp,
                    'detected_type': det_type,
                    'valid': valid,
                    'error': error,
                }
                rec_vals.append(entry)
                all_validations.append(entry)

        if 'repair' in record:
            for value, id_type in record['repair'].items():
                repaired, chk = repair(value, id_type)
                all_repairs.append({
                    'record_id': rid,
                    'input': value,
                    'type': id_type,
                    'repaired': repaired,
                    'check_digits': chk,
                })

    # ---- Create SQLite database ----
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)

    conn.execute("""CREATE TABLE validations (
        record_id TEXT,
        field TEXT,
        input TEXT,
        compact TEXT,
        detected_type TEXT,
        valid INTEGER,
        error TEXT
    )""")

    conn.execute("""CREATE TABLE repairs (
        record_id TEXT,
        input TEXT,
        type TEXT,
        repaired TEXT,
        check_digits TEXT
    )""")

    for v in all_validations:
        conn.execute(
            "INSERT INTO validations VALUES (?,?,?,?,?,?,?)",
            (v['record_id'], v['field'], v['input'], v['compact'],
             v['detected_type'], 1 if v['valid'] else 0, v['error']),
        )

    for r in all_repairs:
        conn.execute(
            "INSERT INTO repairs VALUES (?,?,?,?,?)",
            (r['record_id'], r['input'], r['type'], r['repaired'],
             r['check_digits']),
        )

    conn.execute(_CROSS_REF_VIEW_SQL)
    conn.commit()

    # ---- Export JSON report from database ----
    conn.row_factory = sqlite3.Row

    json_validations = []
    for row in conn.execute("SELECT * FROM validations"):
        json_validations.append({
            'record_id': row['record_id'],
            'field': row['field'],
            'input': row['input'],
            'compact': row['compact'],
            'detected_type': row['detected_type'],
            'valid': bool(row['valid']),
            'error': row['error'],
        })

    json_cross_refs = []
    for row in conn.execute("SELECT * FROM cross_references"):
        json_cross_refs.append({
            'record_id': row['record_id'],
            'check': row['check'],
            'consistent': bool(row['consistent']),
        })

    json_repairs = []
    for row in conn.execute("SELECT * FROM repairs"):
        json_repairs.append({
            'record_id': row['record_id'],
            'input': row['input'],
            'type': row['type'],
            'repaired': row['repaired'],
            'check_digits': row['check_digits'],
        })

    conn.close()

    report = {
        'validations': json_validations,
        'cross_references': json_cross_refs,
        'repairs': json_repairs,
    }

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(report, f, indent=2)


if __name__ == '__main__':
    main()
