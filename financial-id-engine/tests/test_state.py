
import json
import os
import sqlite3
import subprocess

import pytest


# ======================== Fixtures ========================

@pytest.fixture(scope="session")
def engine_run():
    """Run the financial identifier engine once."""
    os.makedirs('/app/output', exist_ok=True)
    result = subprocess.run(
        [
            'python3', '/app/fid_engine.py',
            '/app/data/batch.json',
            '/app/data/iban.dat',
            '/app/output/identifiers.db',
            '/app/output/report.json',
        ],
        capture_output=True, text=True, timeout=120, cwd='/app',
    )
    assert result.returncode == 0, (
        f"fid_engine.py failed (rc={result.returncode}).\n"
        f"stdout: {result.stdout[:2000]}\nstderr: {result.stderr[:2000]}"
    )
    return result


@pytest.fixture(scope="session")
def report(engine_run):
    """Parse the JSON report produced by the engine."""
    assert os.path.exists('/app/output/report.json'), "JSON report not created"
    with open('/app/output/report.json') as f:
        data = json.load(f)
    assert 'validations' in data, "Output missing 'validations' key"
    assert 'cross_references' in data, "Output missing 'cross_references' key"
    assert 'repairs' in data, "Output missing 'repairs' key"
    return data


@pytest.fixture(scope="session")
def db_conn(engine_run):
    """Open the SQLite database produced by the engine."""
    db_path = '/app/output/identifiers.db'
    assert os.path.exists(db_path), "SQLite database not created"
    conn = sqlite3.connect(db_path)
    yield conn
    conn.close()


# ======================== Helpers ========================

def _find_validation(report, record_id, field):
    for v in report['validations']:
        if v['record_id'] == record_id and v['field'] == field:
            return v
    return None


def _find_cross_ref(report, record_id, check):
    for cr in report['cross_references']:
        if cr['record_id'] == record_id and cr['check'] == check:
            return cr
    return None


def _find_repair(report, record_id, id_type):
    for r in report['repairs']:
        if r['record_id'] == record_id and r['type'] == id_type:
            return r
    return None


# ====================== SQLite Schema Tests ======================

class TestSQLiteSchema:
    def test_validations_is_table(self, db_conn):
        row = db_conn.execute(
            "SELECT type FROM sqlite_master WHERE name='validations'"
        ).fetchone()
        assert row is not None, "validations not found in database"
        assert row[0] == 'table', f"validations should be a table but is {row[0]}"

    def test_repairs_is_table(self, db_conn):
        row = db_conn.execute(
            "SELECT type FROM sqlite_master WHERE name='repairs'"
        ).fetchone()
        assert row is not None, "repairs not found in database"
        assert row[0] == 'table', f"repairs should be a table but is {row[0]}"

    def test_cross_references_is_view(self, db_conn):
        """cross_references MUST be a VIEW, not a table."""
        row = db_conn.execute(
            "SELECT type FROM sqlite_master WHERE name='cross_references'"
        ).fetchone()
        assert row is not None, "cross_references not found in database"
        assert row[0] == 'view', (
            f"cross_references must be a VIEW (computed via SQL joins), not a {row[0]}"
        )

    def test_validations_columns(self, db_conn):
        columns = {row[1] for row in db_conn.execute("PRAGMA table_info(validations)")}
        expected = {'record_id', 'field', 'input', 'compact', 'detected_type', 'valid', 'error'}
        missing = expected - columns
        assert not missing, f"validations table missing columns: {missing}"

    def test_repairs_columns(self, db_conn):
        columns = {row[1] for row in db_conn.execute("PRAGMA table_info(repairs)")}
        expected = {'record_id', 'input', 'type', 'repaired', 'check_digits'}
        missing = expected - columns
        assert not missing, f"repairs table missing columns: {missing}"

    def test_cross_references_queryable(self, db_conn):
        """The cross_references view must be queryable and return correct columns."""
        cursor = db_conn.execute("SELECT * FROM cross_references LIMIT 1")
        col_names = [desc[0] for desc in cursor.description]
        assert 'record_id' in col_names, f"cross_references missing record_id column, has: {col_names}"
        assert 'consistent' in col_names, f"cross_references missing consistent column, has: {col_names}"


# ====================== SQLite Dynamic VIEW Test ======================

class TestSQLiteDynamic:
    def test_cross_ref_view_reacts_to_inserts(self, db_conn):
        """Inserting new valid pairs must produce new cross_references rows,
        proving it is a live SQL view and not a pre-populated table."""
        db_conn.execute("SAVEPOINT synth_test")
        try:
            db_conn.execute(
                "INSERT INTO validations VALUES "
                "('_SYNTH_', 'cusip', '594918104', '594918104', 'cusip', 1, NULL)"
            )
            db_conn.execute(
                "INSERT INTO validations VALUES "
                "('_SYNTH_', 'isin', 'US5949181045', 'US5949181045', 'isin', 1, NULL)"
            )

            rows = db_conn.execute(
                "SELECT * FROM cross_references WHERE record_id = '_SYNTH_'"
            ).fetchall()

            assert len(rows) == 1, (
                f"Expected 1 cross-ref for synthetic cusip/isin pair, got {len(rows)}"
            )
            # row = (record_id, check, consistent)
            assert rows[0][1] == 'cusip_isin'
            assert rows[0][2] == 1, "Synthetic CUSIP 594918104 should match ISIN US5949181045"
        finally:
            db_conn.execute("ROLLBACK TO SAVEPOINT synth_test")
            db_conn.execute("RELEASE SAVEPOINT synth_test")

    def test_cross_ref_view_reacts_to_iban_bic(self, db_conn):
        """Verify iban_bic_country check appears dynamically for inserted pairs."""
        db_conn.execute("SAVEPOINT synth_iban_test")
        try:
            db_conn.execute(
                "INSERT INTO validations VALUES "
                "('_SYNTH2_', 'iban', 'FR7630006000011234567890189', "
                "'FR7630006000011234567890189', 'iban', 1, NULL)"
            )
            db_conn.execute(
                "INSERT INTO validations VALUES "
                "('_SYNTH2_', 'bic', 'BNPAFR2L', 'BNPAFR2L', 'bic', 1, NULL)"
            )

            rows = db_conn.execute(
                "SELECT * FROM cross_references WHERE record_id = '_SYNTH2_'"
            ).fetchall()

            assert len(rows) == 1
            assert rows[0][1] == 'iban_bic_country'
            # FR == FR (IBAN[0:2] == BIC[4:6])
            assert rows[0][2] == 1
        finally:
            db_conn.execute("ROLLBACK TO SAVEPOINT synth_iban_test")
            db_conn.execute("RELEASE SAVEPOINT synth_iban_test")


# ====================== SQLite Data Tests ======================

class TestSQLiteData:
    def test_validations_count_in_db(self, db_conn):
        count = db_conn.execute("SELECT count(*) FROM validations").fetchone()[0]
        assert count == 21, f"Expected 21 validations in DB, got {count}"

    def test_cross_ref_count_in_db(self, db_conn):
        count = db_conn.execute("SELECT count(*) FROM cross_references").fetchone()[0]
        assert count == 5, f"Expected 5 cross-references in DB, got {count}"

    def test_repairs_count_in_db(self, db_conn):
        count = db_conn.execute("SELECT count(*) FROM repairs").fetchone()[0]
        assert count == 6, f"Expected 6 repairs in DB, got {count}"

    def test_valid_iban_in_db(self, db_conn):
        row = db_conn.execute(
            "SELECT compact, valid FROM validations "
            "WHERE record_id='REC001' AND field='iban'"
        ).fetchone()
        assert row is not None
        assert row[0] == 'GB29NWBK60161331926819'
        assert row[1] == 1

    def test_invalid_checksum_in_db(self, db_conn):
        row = db_conn.execute(
            "SELECT valid, error FROM validations "
            "WHERE record_id='REC006' AND field='iban'"
        ).fetchone()
        assert row is not None
        assert row[0] == 0
        assert row[1] == 'invalid_checksum'

    def test_valid_uses_integer_not_string(self, db_conn):
        """valid column must store integers (0/1), not strings or booleans."""
        row = db_conn.execute(
            "SELECT typeof(valid) FROM validations LIMIT 1"
        ).fetchone()
        assert row[0] == 'integer', f"valid column type is {row[0]}, expected integer"

    def test_repair_iban_in_db(self, db_conn):
        row = db_conn.execute(
            "SELECT repaired, check_digits FROM repairs "
            "WHERE record_id='REC012' AND type='iban'"
        ).fetchone()
        assert row is not None
        assert row[0] == 'BE31435411161155'
        assert row[1] == '31'

    def test_autodetected_iban_in_db(self, db_conn):
        row = db_conn.execute(
            "SELECT detected_type, valid FROM validations "
            "WHERE record_id='REC011' AND field='ref1'"
        ).fetchone()
        assert row is not None
        assert row[0] == 'iban'
        assert row[1] == 1


# ====================== IBAN Validation (JSON) ======================

class TestIBANValidation:
    def test_valid_gb_iban(self, report):
        v = _find_validation(report, 'REC001', 'iban')
        assert v is not None, "Missing validation for REC001/iban"
        assert v['valid'] is True
        assert v['compact'] == 'GB29NWBK60161331926819'
        assert v['detected_type'] == 'iban'

    def test_invalid_iban_checksum(self, report):
        v = _find_validation(report, 'REC006', 'iban')
        assert v is not None, "Missing validation for REC006/iban"
        assert v['valid'] is False
        assert v['error'] == 'invalid_checksum'

    def test_valid_de_iban(self, report):
        v = _find_validation(report, 'REC014', 'iban')
        assert v is not None, "Missing validation for REC014/iban"
        assert v['valid'] is True
        assert v['compact'] == 'DE89370400440532013000'
        assert v['detected_type'] == 'iban'

    def test_valid_fr_iban_alphanumeric_bban(self, report):
        v = _find_validation(report, 'REC015', 'iban')
        assert v is not None, "Missing validation for REC015/iban"
        assert v['valid'] is True
        assert v['compact'] == 'FR1420041010050500013M02606'
        assert v['detected_type'] == 'iban'


# ====================== BIC Validation ======================

class TestBICValidation:
    def test_valid_bic(self, report):
        v = _find_validation(report, 'REC001', 'bic')
        assert v is not None, "Missing validation for REC001/bic"
        assert v['valid'] is True
        assert v['compact'] == 'NWBKGB2L'
        assert v['detected_type'] == 'bic'

    def test_invalid_bic_country(self, report):
        v = _find_validation(report, 'REC007', 'bic')
        assert v is not None, "Missing validation for REC007/bic"
        assert v['valid'] is False
        assert v['error'] == 'invalid_component'


# ====================== LEI Validation ======================

class TestLEIValidation:
    def test_valid_lei(self, report):
        v = _find_validation(report, 'REC003', 'lei')
        assert v is not None, "Missing validation for REC003/lei"
        assert v['valid'] is True
        assert v['compact'] == '213800KUD8LAJWSQ9D15'
        assert v['detected_type'] == 'lei'

    def test_invalid_lei_checksum(self, report):
        v = _find_validation(report, 'REC008', 'lei')
        assert v is not None, "Missing validation for REC008/lei"
        assert v['valid'] is False
        assert v['error'] == 'invalid_checksum'


# ====================== ISIN Validation ======================

class TestISINValidation:
    def test_valid_isin_with_cusip(self, report):
        v = _find_validation(report, 'REC002', 'isin')
        assert v is not None, "Missing validation for REC002/isin"
        assert v['valid'] is True
        assert v['compact'] == 'US0378331005'
        assert v['detected_type'] == 'isin'

    def test_valid_isin_with_sedol(self, report):
        v = _find_validation(report, 'REC005', 'isin')
        assert v is not None, "Missing validation for REC005/isin"
        assert v['valid'] is True
        assert v['compact'] == 'GB00B15KXQ89'
        assert v['detected_type'] == 'isin'


# ====================== CUSIP Validation ======================

class TestCUSIPValidation:
    def test_valid_cusip(self, report):
        v = _find_validation(report, 'REC002', 'cusip')
        assert v is not None, "Missing validation for REC002/cusip"
        assert v['valid'] is True
        assert v['compact'] == '037833100'
        assert v['detected_type'] == 'cusip'

    def test_invalid_cusip_checksum(self, report):
        v = _find_validation(report, 'REC009', 'cusip')
        assert v is not None, "Missing validation for REC009/cusip"
        assert v['valid'] is False
        assert v['error'] == 'invalid_checksum'

    def test_valid_cusip_alphanumeric(self, report):
        v = _find_validation(report, 'REC010', 'cusip')
        assert v is not None, "Missing validation for REC010/cusip"
        assert v['valid'] is True
        assert v['compact'] == 'DUS0421C5'


# ====================== FIGI Validation ======================

class TestFIGIValidation:
    def test_valid_figi(self, report):
        v = _find_validation(report, 'REC004', 'figi')
        assert v is not None, "Missing validation for REC004/figi"
        assert v['valid'] is True
        assert v['compact'] == 'BBG000BLNQ16'
        assert v['detected_type'] == 'figi'

    def test_invalid_figi_excluded_prefix(self, report):
        v = _find_validation(report, 'REC013', 'figi')
        assert v is not None, "Missing validation for REC013/figi"
        assert v['valid'] is False
        assert v['error'] == 'invalid_component'


# ====================== SEDOL Validation ======================

class TestSEDOLValidation:
    def test_valid_sedol(self, report):
        v = _find_validation(report, 'REC005', 'sedol')
        assert v is not None, "Missing validation for REC005/sedol"
        assert v['valid'] is True
        assert v['compact'] == 'B15KXQ8'
        assert v['detected_type'] == 'sedol'


# ====================== Auto-Detection ======================

class TestAutoDetection:
    def test_detect_iban_from_unknown_field(self, report):
        v = _find_validation(report, 'REC011', 'ref1')
        assert v is not None, "Missing validation for REC011/ref1"
        assert v['valid'] is True
        assert v['detected_type'] == 'iban'
        assert v['compact'] == 'DE89370400440532013000'

    def test_detect_isin_from_unknown_field(self, report):
        v = _find_validation(report, 'REC011', 'ref2')
        assert v is not None, "Missing validation for REC011/ref2"
        assert v['valid'] is True
        assert v['detected_type'] == 'isin'
        assert v['compact'] == 'US0378331005'

    def test_detect_figi_from_unknown_field(self, report):
        v = _find_validation(report, 'REC011', 'ref3')
        assert v is not None, "Missing validation for REC011/ref3"
        assert v['valid'] is True
        assert v['detected_type'] == 'figi'
        assert v['compact'] == 'BBG000BLNQ16'


# ====================== Cross-References (JSON) ======================

class TestCrossReferences:
    def test_iban_bic_country_consistent(self, report):
        cr = _find_cross_ref(report, 'REC001', 'iban_bic_country')
        assert cr is not None, "Missing cross-ref REC001/iban_bic_country"
        assert cr['consistent'] is True

    def test_cusip_isin_consistent(self, report):
        cr = _find_cross_ref(report, 'REC002', 'cusip_isin')
        assert cr is not None, "Missing cross-ref REC002/cusip_isin"
        assert cr['consistent'] is True

    def test_sedol_isin_consistent(self, report):
        cr = _find_cross_ref(report, 'REC005', 'sedol_isin')
        assert cr is not None, "Missing cross-ref REC005/sedol_isin"
        assert cr['consistent'] is True

    def test_cusip_isin_inconsistent(self, report):
        cr = _find_cross_ref(report, 'REC010', 'cusip_isin')
        assert cr is not None, "Missing cross-ref REC010/cusip_isin"
        assert cr['consistent'] is False

    def test_iban_bic_country_inconsistent(self, report):
        cr = _find_cross_ref(report, 'REC014', 'iban_bic_country')
        assert cr is not None, "Missing cross-ref REC014/iban_bic_country"
        assert cr['consistent'] is False


# ====================== Repairs (JSON) ======================

class TestRepairs:
    def test_iban_check_digit_repair(self, report):
        r = _find_repair(report, 'REC012', 'iban')
        assert r is not None, "Missing repair REC012/iban"
        assert r['repaired'] == 'BE31435411161155'
        assert r['check_digits'] == '31'

    def test_cusip_check_digit_repair(self, report):
        r = _find_repair(report, 'REC012', 'cusip')
        assert r is not None, "Missing repair REC012/cusip"
        assert r['repaired'] == '037833100'
        assert r['check_digits'] == '0'

    def test_isin_check_digit_repair(self, report):
        r = _find_repair(report, 'REC012', 'isin')
        assert r is not None, "Missing repair REC012/isin"
        assert r['repaired'] == 'US0378331005'
        assert r['check_digits'] == '5'

    def test_lei_check_digit_repair(self, report):
        r = _find_repair(report, 'REC012', 'lei')
        assert r is not None, "Missing repair REC012/lei"
        assert r['repaired'] == '213800KUD8LAJWSQ9D15'
        assert r['check_digits'] == '15'

    def test_sedol_check_digit_repair(self, report):
        r = _find_repair(report, 'REC012', 'sedol')
        assert r is not None, "Missing repair REC012/sedol"
        assert r['repaired'] == 'B15KXQ8'
        assert r['check_digits'] == '8'

    def test_figi_check_digit_repair(self, report):
        r = _find_repair(report, 'REC012', 'figi')
        assert r is not None, "Missing repair REC012/figi"
        assert r['repaired'] == 'BBG000BLNQ16'
        assert r['check_digits'] == '6'


# ====================== Structural Tests ======================

class TestStructure:
    def test_validation_count(self, report):
        assert len(report['validations']) == 21, (
            f"Expected 21 validations, got {len(report['validations'])}"
        )

    def test_cross_reference_count(self, report):
        assert len(report['cross_references']) == 5, (
            f"Expected 5 cross-references, got {len(report['cross_references'])}"
        )

    def test_repair_count(self, report):
        assert len(report['repairs']) == 6, (
            f"Expected 6 repairs, got {len(report['repairs'])}"
        )

    def test_output_is_valid_json(self, report):
        assert isinstance(report, dict)
        assert isinstance(report['validations'], list)
        assert isinstance(report['cross_references'], list)
        assert isinstance(report['repairs'], list)

    def test_validation_schema(self, report):
        required = {'record_id', 'field', 'input', 'compact', 'detected_type', 'valid', 'error'}
        for v in report['validations']:
            missing = required - set(v.keys())
            assert not missing, f"Validation {v.get('record_id')}/{v.get('field')} missing keys: {missing}"

    def test_cross_ref_schema(self, report):
        required = {'record_id', 'check', 'consistent'}
        for cr in report['cross_references']:
            missing = required - set(cr.keys())
            assert not missing, f"Cross-ref {cr.get('record_id')}/{cr.get('check')} missing keys: {missing}"

    def test_repair_schema(self, report):
        required = {'record_id', 'input', 'type', 'repaired', 'check_digits'}
        for r in report['repairs']:
            missing = required - set(r.keys())
            assert not missing, f"Repair {r.get('record_id')}/{r.get('type')} missing keys: {missing}"

    def test_valid_entries_have_null_error(self, report):
        for v in report['validations']:
            if v['valid']:
                assert v['error'] is None, (
                    f"{v['record_id']}/{v['field']} is valid but error={v['error']}"
                )

    def test_invalid_entries_have_error(self, report):
        valid_errors = {'invalid_length', 'invalid_format', 'invalid_checksum', 'invalid_component'}
        for v in report['validations']:
            if not v['valid']:
                assert v['error'] in valid_errors, (
                    f"{v['record_id']}/{v['field']} is invalid but error={v['error']!r}"
                )

    def test_json_valid_is_boolean(self, report):
        """In JSON output, valid must be true/false (boolean), not 0/1."""
        for v in report['validations']:
            assert isinstance(v['valid'], bool), (
                f"{v['record_id']}/{v['field']}: valid should be bool, got {type(v['valid']).__name__}"
            )

    def test_json_consistent_is_boolean(self, report):
        """In JSON output, consistent must be true/false (boolean), not 0/1."""
        for cr in report['cross_references']:
            assert isinstance(cr['consistent'], bool), (
                f"{cr['record_id']}/{cr['check']}: consistent should be bool, got {type(cr['consistent']).__name__}"
            )
