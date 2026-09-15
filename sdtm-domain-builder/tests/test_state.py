
import pytest
import pandas as pd
import os
import re

SDTM_DIR = '/app/sdtm'


class TestFileExistence:
    """All required SDTM domain files must be present."""

    @pytest.mark.parametrize("filename", [
        'dm.csv', 'ae.csv', 'vs.csv', 'ex.csv', 'suppae.csv', 'ts.csv'
    ])
    def test_domain_file_exists(self, filename):
        path = os.path.join(SDTM_DIR, filename)
        assert os.path.exists(path), f"{filename} not found in {SDTM_DIR}"


# ---------------------------------------------------------------------------
# DM – Demographics
# ---------------------------------------------------------------------------
class TestDMDomain:
    @pytest.fixture
    def dm(self):
        return pd.read_csv(os.path.join(SDTM_DIR, 'dm.csv'), dtype=str)

    def test_record_count(self, dm):
        assert len(dm) == 6, f"DM should have 6 records, got {len(dm)}"

    def test_required_columns_present(self, dm):
        for col in ['STUDYID', 'DOMAIN', 'USUBJID', 'SUBJID']:
            assert col in dm.columns, f"Required column {col} missing from DM"

    def test_expected_columns_present(self, dm):
        for col in ['RFSTDTC', 'RFENDTC', 'SITEID', 'AGE', 'AGEU',
                     'SEX', 'RACE', 'ETHNIC', 'ARMCD', 'ARM']:
            assert col in dm.columns, f"Expected column {col} missing from DM"

    def test_studyid_value(self, dm):
        assert (dm['STUDYID'] == 'XYZ2024').all(), "STUDYID must be XYZ2024"

    def test_domain_value(self, dm):
        assert (dm['DOMAIN'] == 'DM').all(), "DOMAIN must be DM"

    def test_sex_controlled_terminology(self, dm):
        valid = {'M', 'F'}
        actual = set(dm['SEX'].unique())
        assert actual.issubset(valid), f"Invalid SEX values: {actual - valid}"

    def test_race_controlled_terminology(self, dm):
        valid = {
            'WHITE', 'BLACK OR AFRICAN AMERICAN', 'ASIAN',
            'AMERICAN INDIAN OR ALASKA NATIVE',
            'NATIVE HAWAIIAN OR OTHER PACIFIC ISLANDER',
            'MULTIPLE', 'OTHER', 'UNKNOWN', 'NOT REPORTED',
        }
        for race in dm['RACE'].unique():
            assert race in valid, f"Invalid RACE value: '{race}'"

    def test_ethnic_controlled_terminology(self, dm):
        valid = {'HISPANIC OR LATINO', 'NOT HISPANIC OR LATINO',
                 'NOT REPORTED', 'UNKNOWN'}
        for eth in dm['ETHNIC'].unique():
            assert eth in valid, f"Invalid ETHNIC value: '{eth}'"

    def test_rfstdtc_iso8601(self, dm):
        for dtc in dm['RFSTDTC'].dropna():
            assert re.match(r'^\d{4}-\d{2}-\d{2}', str(dtc)), \
                f"RFSTDTC not ISO 8601: {dtc}"

    def test_age_subject_101_001(self, dm):
        """Born 1968-05-12, RFSTDTC 2024-01-29 => age 55 (birthday not yet passed)."""
        row = dm[dm['SUBJID'] == '101-001']
        assert len(row) == 1, "Subject 101-001 not found in DM"
        assert int(row['AGE'].iloc[0]) == 55

    def test_age_subject_102_001(self, dm):
        """Born 1975-03-07, RFSTDTC 2024-02-05 => age 48."""
        row = dm[dm['SUBJID'] == '102-001']
        assert len(row) == 1
        assert int(row['AGE'].iloc[0]) == 48

    def test_age_subject_103_001(self, dm):
        """Born 1963-06-14, RFSTDTC 2024-02-15 => age 60."""
        row = dm[dm['SUBJID'] == '103-001']
        assert len(row) == 1
        assert int(row['AGE'].iloc[0]) == 60

    def test_race_caucasian_mapped_to_white(self, dm):
        row = dm[dm['SUBJID'] == '101-001']
        assert row['RACE'].iloc[0] == 'WHITE'

    def test_race_african_american_mapped(self, dm):
        row = dm[dm['SUBJID'] == '102-001']
        assert row['RACE'].iloc[0] == 'BLACK OR AFRICAN AMERICAN'

    def test_race_mixed_mapped_to_multiple(self, dm):
        row = dm[dm['SUBJID'] == '103-001']
        assert row['RACE'].iloc[0] == 'MULTIPLE'

    def test_race_native_american_mapped(self, dm):
        row = dm[dm['SUBJID'] == '103-002']
        assert row['RACE'].iloc[0] == 'AMERICAN INDIAN OR ALASKA NATIVE'

    def test_armcd_values(self, dm):
        valid = {'TRTX10', 'PBO'}
        actual = set(dm['ARMCD'].unique())
        assert actual.issubset(valid), f"Invalid ARMCD values: {actual - valid}"

    def test_usubjid_contains_studyid(self, dm):
        for uid in dm['USUBJID']:
            assert str(uid).startswith('XYZ2024'), \
                f"USUBJID should start with STUDYID: {uid}"


# ---------------------------------------------------------------------------
# AE – Adverse Events
# ---------------------------------------------------------------------------
class TestAEDomain:
    @pytest.fixture
    def ae(self):
        return pd.read_csv(os.path.join(SDTM_DIR, 'ae.csv'), dtype=str)

    def test_record_count(self, ae):
        assert len(ae) == 8, f"AE should have 8 records, got {len(ae)}"

    def test_required_columns(self, ae):
        for col in ['STUDYID', 'DOMAIN', 'USUBJID', 'AESEQ',
                     'AETERM', 'AEDECOD']:
            assert col in ae.columns, f"Required column {col} missing from AE"

    def test_domain_value(self, ae):
        assert (ae['DOMAIN'] == 'AE').all()

    def test_severity_ct(self, ae):
        valid = {'MILD', 'MODERATE', 'SEVERE'}
        for v in ae['AESEV'].unique():
            assert v in valid, f"Invalid AESEV: {v}"

    def test_seriousness_ct(self, ae):
        valid = {'Y', 'N'}
        for v in ae['AESER'].unique():
            assert v in valid, f"Invalid AESER: {v}"

    def test_outcome_ct(self, ae):
        valid = {
            'RECOVERED/RESOLVED', 'NOT RECOVERED/NOT RESOLVED',
            'RECOVERED/RESOLVED WITH SEQUELAE', 'RECOVERING/RESOLVING',
            'FATAL', 'UNKNOWN',
        }
        for v in ae['AEOUT'].dropna().unique():
            assert v in valid, f"Invalid AEOUT: '{v}'"

    def test_action_ct(self, ae):
        valid = {
            'DOSE NOT CHANGED', 'DOSE REDUCED', 'DRUG WITHDRAWN',
            'DOSE INCREASED', 'DRUG INTERRUPTED', 'NOT APPLICABLE',
        }
        for v in ae['AEACN'].dropna().unique():
            assert v in valid, f"Invalid AEACN: '{v}'"

    def test_aeterm_uppercase(self, ae):
        for term in ae['AETERM']:
            assert str(term) == str(term).upper(), \
                f"AETERM not uppercase: {term}"

    def test_pruritis_coded_to_pruritus(self, ae):
        """Misspelled 'pruritis' must be coded to PRURITUS via dictionary."""
        coded = ae[ae['AETERM'].str.upper() == 'PRURITIS']
        assert len(coded) == 1, "Expected one PRURITIS/PRURITIS AE row"
        assert coded['AEDECOD'].iloc[0] == 'PRURITUS'

    def test_rash_coded_via_dictionary(self, ae):
        """'Severe generalized rash' must be coded to RASH GENERALISED."""
        rash = ae[ae['AETERM'].str.contains('RASH', case=False, na=False)]
        assert len(rash) >= 1
        assert rash['AEDECOD'].iloc[0] == 'RASH GENERALISED'

    def test_study_day_no_day_zero_ae1(self, ae):
        """Subject 101-001 AE1: RFSTDTC=2024-01-29, AESTDTC=2024-02-05 => AESTDY=8."""
        row = ae[(ae['USUBJID'].str.contains('101-001')) &
                 (ae['AESEQ'].astype(int) == 1)]
        assert len(row) == 1
        assert int(row['AESTDY'].iloc[0]) == 8

    def test_study_day_calculation_ae_102002(self, ae):
        """Subject 102-002 AE1: RFSTDTC=2024-02-08, AESTDTC=2024-02-25 => AESTDY=18."""
        row = ae[(ae['USUBJID'].str.contains('102-002')) &
                 (ae['AESEQ'].astype(int) == 1)]
        assert len(row) == 1
        assert int(row['AESTDY'].iloc[0]) == 18

    def test_missing_end_date_handled(self, ae):
        """Subject 103-001 AE2 (Insomnia, Ongoing) should have blank AEENDTC."""
        row = ae[(ae['USUBJID'].str.contains('103-001')) &
                 (ae['AESEQ'].astype(int) == 2)]
        assert len(row) == 1
        val = str(row['AEENDTC'].iloc[0]).strip()
        assert val in ('', 'nan', 'NaT', 'None'), \
            f"Ongoing AE should have empty AEENDTC, got '{val}'"

    def test_iso8601_start_dates(self, ae):
        for dtc in ae['AESTDTC'].dropna():
            assert re.match(r'^\d{4}-\d{2}-\d{2}', str(dtc)), \
                f"AESTDTC not ISO 8601: {dtc}"

    def test_aebodsys_present(self, ae):
        """AE should include AEBODSYS from the medical dictionary."""
        assert 'AEBODSYS' in ae.columns, "AEBODSYS column missing from AE"
        # Verify at least one non-null value
        non_null = ae['AEBODSYS'].dropna()
        assert len(non_null) > 0


# ---------------------------------------------------------------------------
# VS – Vital Signs
# ---------------------------------------------------------------------------
class TestVSDomain:
    @pytest.fixture
    def vs(self):
        return pd.read_csv(os.path.join(SDTM_DIR, 'vs.csv'), dtype=str)

    def test_required_columns(self, vs):
        for col in ['STUDYID', 'DOMAIN', 'USUBJID', 'VSSEQ',
                     'VSTESTCD', 'VSTEST', 'VSORRES', 'VSORRESU']:
            assert col in vs.columns, f"Column {col} missing from VS"

    def test_standardized_result_columns(self, vs):
        for col in ['VSSTRESC', 'VSSTRESN', 'VSSTRESU']:
            assert col in vs.columns, f"Column {col} missing from VS"

    def test_domain_value(self, vs):
        assert (vs['DOMAIN'] == 'VS').all()

    def test_vstestcd_max_8_chars(self, vs):
        for tc in vs['VSTESTCD'].unique():
            assert len(str(tc)) <= 8, f"VSTESTCD exceeds 8 chars: {tc}"

    def test_sysbp_testcode_exists(self, vs):
        assert 'SYSBP' in vs['VSTESTCD'].values, "SYSBP not found in VSTESTCD"

    def test_diabp_testcode_exists(self, vs):
        assert 'DIABP' in vs['VSTESTCD'].values, "DIABP not found in VSTESTCD"

    def test_pulse_testcode_exists(self, vs):
        assert 'PULSE' in vs['VSTESTCD'].values, "PULSE not found in VSTESTCD"

    def test_weight_testcode_exists(self, vs):
        assert 'WEIGHT' in vs['VSTESTCD'].values, "WEIGHT not found in VSTESTCD"

    def test_weight_standardized_to_kg(self, vs):
        weight = vs[vs['VSTESTCD'] == 'WEIGHT']
        assert len(weight) > 0
        for _, row in weight.iterrows():
            assert str(row['VSSTRESU']).lower() == 'kg', \
                f"Weight VSSTRESU should be kg, got {row['VSSTRESU']}"

    def test_weight_conversion_value(self, vs):
        """Subject 101-001 screening weight: 185 lbs => ~83.9 kg."""
        wt = vs[(vs['USUBJID'].str.contains('101-001')) &
                (vs['VSTESTCD'] == 'WEIGHT')]
        screening_wt = wt[wt['VISITNUM'].astype(int) == 1]
        if len(screening_wt) > 0:
            val = float(screening_wt['VSSTRESN'].iloc[0])
            assert abs(val - 83.9) < 0.5, \
                f"Weight conversion wrong: expected ~83.9, got {val}"

    def test_screening_study_day_negative(self, vs):
        """Screening visits occurred before RFSTDTC => VSDY must be negative."""
        screening = vs[vs['VISITNUM'].astype(int) == 1]
        for _, row in screening.iterrows():
            dy = str(row.get('VSDY', '')).strip()
            if dy and dy not in ('', 'nan', 'None'):
                assert int(float(dy)) < 0, \
                    f"Screening VSDY should be negative: {dy}"

    def test_vstest_for_weight(self, vs):
        """VSTEST for WEIGHT should be 'Weight' (not 'Body Weight')."""
        wt = vs[vs['VSTESTCD'] == 'WEIGHT']
        for _, row in wt.iterrows():
            assert str(row['VSTEST']).strip() == 'Weight', \
                f"VSTEST for WEIGHT should be 'Weight', got '{row['VSTEST']}'"

    def test_iso8601_dates(self, vs):
        for dtc in vs['VSDTC'].dropna():
            assert re.match(r'^\d{4}-\d{2}-\d{2}', str(dtc)), \
                f"VSDTC not ISO 8601: {dtc}"


# ---------------------------------------------------------------------------
# EX – Exposure
# ---------------------------------------------------------------------------
class TestEXDomain:
    @pytest.fixture
    def ex(self):
        return pd.read_csv(os.path.join(SDTM_DIR, 'ex.csv'), dtype=str)

    def test_record_count(self, ex):
        assert len(ex) == 6, f"EX should have 6 records, got {len(ex)}"

    def test_required_columns(self, ex):
        for col in ['STUDYID', 'DOMAIN', 'USUBJID', 'EXSEQ', 'EXTRT']:
            assert col in ex.columns, f"Column {col} missing from EX"

    def test_domain_value(self, ex):
        assert (ex['DOMAIN'] == 'EX').all()

    def test_dosing_frequency_ct(self, ex):
        if 'EXDOSFRQ' in ex.columns:
            for v in ex['EXDOSFRQ'].dropna().unique():
                assert v == 'QD', f"EXDOSFRQ should be QD, got {v}"

    def test_dosage_form_ct(self, ex):
        if 'EXDOSFRM' in ex.columns:
            for v in ex['EXDOSFRM'].dropna().unique():
                assert v == 'TABLET', f"EXDOSFRM should be TABLET, got {v}"

    def test_iso8601_dates(self, ex):
        for col in ['EXSTDTC', 'EXENDTC']:
            if col in ex.columns:
                for dtc in ex[col].dropna():
                    assert re.match(r'^\d{4}-\d{2}-\d{2}', str(dtc)), \
                        f"{col} not ISO 8601: {dtc}"


# ---------------------------------------------------------------------------
# SUPPAE – Supplemental Qualifiers for AE
# ---------------------------------------------------------------------------
class TestSUPPAE:
    @pytest.fixture
    def suppae(self):
        return pd.read_csv(os.path.join(SDTM_DIR, 'suppae.csv'), dtype=str)

    def test_required_columns(self, suppae):
        for col in ['STUDYID', 'RDOMAIN', 'USUBJID', 'IDVAR',
                     'IDVARVAL', 'QNAM', 'QLABEL', 'QVAL', 'QORIG']:
            assert col in suppae.columns, \
                f"Column {col} missing from SUPPAE"

    def test_rdomain_value(self, suppae):
        assert (suppae['RDOMAIN'] == 'AE').all(), \
            "SUPPAE RDOMAIN must be 'AE'"

    def test_qnam_max_8_chars(self, suppae):
        for q in suppae['QNAM'].unique():
            assert len(str(q)) <= 8, f"QNAM exceeds 8 chars: {q}"

    def test_idvar_is_aeseq(self, suppae):
        assert (suppae['IDVAR'] == 'AESEQ').all(), \
            "SUPPAE IDVAR should be 'AESEQ'"

    def test_has_aesifl(self, suppae):
        """SUPPAE should contain AE of Special Interest Flag rows."""
        aesifl = suppae[suppae['QNAM'] == 'AESIFL']
        assert len(aesifl) > 0, "No AESIFL records in SUPPAE"

    def test_aesifl_values(self, suppae):
        aesifl = suppae[suppae['QNAM'] == 'AESIFL']
        valid = {'Y', 'N'}
        for v in aesifl['QVAL'].unique():
            assert v in valid, f"AESIFL QVAL should be Y/N, got {v}"

    def test_record_count(self, suppae):
        """Should have one SUPPAE record per AE (8 total)."""
        assert len(suppae) >= 8, \
            f"SUPPAE should have at least 8 records, got {len(suppae)}"


# ---------------------------------------------------------------------------
# TS – Trial Summary
# ---------------------------------------------------------------------------
class TestTSDomain:
    @pytest.fixture
    def ts(self):
        return pd.read_csv(os.path.join(SDTM_DIR, 'ts.csv'), dtype=str)

    def test_required_columns(self, ts):
        for col in ['STUDYID', 'DOMAIN', 'TSSEQ', 'TSPARMCD',
                     'TSPARM', 'TSVAL']:
            assert col in ts.columns, f"Column {col} missing from TS"

    def test_domain_value(self, ts):
        assert (ts['DOMAIN'] == 'TS').all()

    def test_has_study_start_date(self, ts):
        sstdtc = ts[ts['TSPARMCD'] == 'SSTDTC']
        assert len(sstdtc) >= 1, "TS missing SSTDTC parameter"
        assert '2024' in str(sstdtc['TSVAL'].iloc[0])

    def test_has_trial_phase(self, ts):
        tphase = ts[ts['TSPARMCD'] == 'TPHASE']
        assert len(tphase) >= 1, "TS missing TPHASE parameter"
        assert 'II' in str(tphase['TSVAL'].iloc[0]).upper()

    def test_has_study_type(self, ts):
        stype = ts[ts['TSPARMCD'] == 'STYPE']
        assert len(stype) >= 1, "TS missing STYPE parameter"
        assert 'INTERVENTIONAL' in str(stype['TSVAL'].iloc[0]).upper()

    def test_has_blinding(self, ts):
        tblind = ts[ts['TSPARMCD'] == 'TBLIND']
        assert len(tblind) >= 1, "TS missing TBLIND parameter"
        assert 'DOUBLE' in str(tblind['TSVAL'].iloc[0]).upper()

    def test_has_randomization(self, ts):
        rand = ts[ts['TSPARMCD'] == 'RANDOM']
        assert len(rand) >= 1, "TS missing RANDOM parameter"
        assert str(rand['TSVAL'].iloc[0]).strip() == 'Y'

    def test_minimum_parameter_count(self, ts):
        assert len(ts) >= 8, \
            f"TS should have at least 8 parameters, got {len(ts)}"

    def test_tsseq_unique(self, ts):
        seqs = ts['TSSEQ'].astype(int)
        assert seqs.is_unique, "TSSEQ values must be unique"

    def test_studyid_value(self, ts):
        assert (ts['STUDYID'] == 'XYZ2024').all()
