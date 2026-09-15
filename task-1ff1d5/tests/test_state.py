
import pytest
import pyreadstat
import pandas as pd
import os
import re
import math

OUTPUT_DIR = "/app/sdtm_output"


def read_xpt(filename):
    """Read XPT file, clean string columns, return DataFrame."""
    path = os.path.join(OUTPUT_DIR, filename)
    assert os.path.exists(path), f"File not found: {path}"
    df, meta = pyreadstat.read_xport(path)
    # Clean string columns: strip whitespace, normalize NaN to ''
    for col in df.select_dtypes(include=["object"]).columns:
        df[col] = df[col].fillna("").astype(str).str.strip()
    return df, meta


def get_subject_rows(df, subjid_suffix):
    """Get rows for a subject by matching end of USUBJID."""
    return df[df["USUBJID"].str.endswith(f"-{subjid_suffix}")]


# ================================================================
# DM DOMAIN TESTS
# ================================================================


class TestDM:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.dm, self.meta = read_xpt("dm.xpt")

    def test_dm_exists_and_has_records(self):
        assert len(self.dm) > 0, "DM domain has no records"

    def test_dm_record_count(self):
        assert len(self.dm) == 8, f"Expected 8 DM records, got {len(self.dm)}"

    def test_dm_required_columns_present(self):
        required = ["STUDYID", "DOMAIN", "USUBJID", "SUBJID", "SEX", "COUNTRY"]
        for col in required:
            assert col in self.dm.columns, f"Missing required column: {col}"

    def test_dm_expected_columns_present(self):
        expected = [
            "RFSTDTC", "RFENDTC", "RFXSTDTC", "RFXENDTC", "RFICDTC",
            "RFPENDTC", "SITEID", "BRTHDTC", "AGE", "AGEU", "RACE",
            "ETHNIC", "ARMCD", "ARM", "ACTARMCD", "ACTARM", "ARMNRS",
        ]
        for col in expected:
            assert col in self.dm.columns, f"Missing expected column: {col}"

    def test_dm_all_studyid(self):
        assert all(self.dm["STUDYID"] == "XYZ001"), "Not all STUDYID = XYZ001"

    def test_dm_all_domain(self):
        assert all(self.dm["DOMAIN"] == "DM"), "Not all DOMAIN = DM"

    def test_dm_sex_controlled_terminology(self):
        valid_sex = {"M", "F"}
        actual = set(self.dm["SEX"].unique()) - {""}
        assert actual.issubset(valid_sex), f"Invalid SEX values: {actual - valid_sex}"

    def test_dm_race_controlled_terminology(self):
        valid_race = {
            "WHITE", "BLACK OR AFRICAN AMERICAN", "ASIAN",
            "AMERICAN INDIAN OR ALASKA NATIVE",
            "NATIVE HAWAIIAN OR OTHER PACIFIC ISLANDER",
            "MULTIPLE", "OTHER",
        }
        actual = set(self.dm["RACE"].unique()) - {""}
        assert actual.issubset(valid_race), f"Invalid RACE values: {actual - valid_race}"

    def test_dm_ethnic_controlled_terminology(self):
        valid_ethnic = {"HISPANIC OR LATINO", "NOT HISPANIC OR LATINO"}
        actual = set(self.dm["ETHNIC"].unique()) - {""}
        assert actual.issubset(valid_ethnic), f"Invalid ETHNIC: {actual - valid_ethnic}"

    def test_dm_country_iso3166(self):
        countries = set(self.dm["COUNTRY"].unique()) - {""}
        assert countries == {"USA"}, f"Expected COUNTRY=USA, got {countries}"

    def test_dm_subject_001_sex(self):
        subj = get_subject_rows(self.dm, "001")
        assert len(subj) == 1
        assert subj.iloc[0]["SEX"] == "M"

    def test_dm_subject_002_sex(self):
        subj = get_subject_rows(self.dm, "002")
        assert len(subj) == 1
        assert subj.iloc[0]["SEX"] == "F"

    def test_dm_subject_001_age(self):
        """Born 1965-08-22, RFSTDTC 2023-03-15 -> AGE=57 (birthday not yet passed)."""
        subj = get_subject_rows(self.dm, "001")
        assert subj.iloc[0]["AGE"] == 57

    def test_dm_subject_003_age(self):
        """Born 1958-02-14, RFSTDTC 2023-03-20 -> AGE=65 (birthday already passed)."""
        subj = get_subject_rows(self.dm, "003")
        assert subj.iloc[0]["AGE"] == 65

    def test_dm_subject_005_age(self):
        """Born 1990-01-15, RFSTDTC 2023-03-22 -> AGE=33."""
        subj = get_subject_rows(self.dm, "005")
        assert subj.iloc[0]["AGE"] == 33

    def test_dm_subject_007_age_missing(self):
        """Subject 007 has no birth date -> AGE should be missing."""
        subj = get_subject_rows(self.dm, "007")
        age = subj.iloc[0]["AGE"]
        assert pd.isna(age) or age == 0 or age == "", f"Expected missing AGE, got {age}"

    def test_dm_subject_001_race(self):
        subj = get_subject_rows(self.dm, "001")
        assert subj.iloc[0]["RACE"] == "WHITE"

    def test_dm_subject_002_race(self):
        """Raw 'Black' -> 'BLACK OR AFRICAN AMERICAN'."""
        subj = get_subject_rows(self.dm, "002")
        assert subj.iloc[0]["RACE"] == "BLACK OR AFRICAN AMERICAN"

    def test_dm_subject_005_race(self):
        """Raw 'AFRICAN AMERICAN' -> 'BLACK OR AFRICAN AMERICAN'."""
        subj = get_subject_rows(self.dm, "005")
        assert subj.iloc[0]["RACE"] == "BLACK OR AFRICAN AMERICAN"

    def test_dm_subject_006_race(self):
        """Raw 'Native Hawaiian...' -> full CDISC term."""
        subj = get_subject_rows(self.dm, "006")
        assert subj.iloc[0]["RACE"] == "NATIVE HAWAIIAN OR OTHER PACIFIC ISLANDER"

    def test_dm_subject_001_ethnic(self):
        """Raw 'Hispanic' -> 'HISPANIC OR LATINO'."""
        subj = get_subject_rows(self.dm, "001")
        assert subj.iloc[0]["ETHNIC"] == "HISPANIC OR LATINO"

    def test_dm_subject_002_ethnic(self):
        """Raw 'Non-Hispanic' -> 'NOT HISPANIC OR LATINO'."""
        subj = get_subject_rows(self.dm, "002")
        assert subj.iloc[0]["ETHNIC"] == "NOT HISPANIC OR LATINO"

    def test_dm_screen_failure_armnrs(self):
        """Subject 008 is a screen failure."""
        subj = get_subject_rows(self.dm, "008")
        assert len(subj) == 1
        assert subj.iloc[0]["ARMNRS"] == "SCREEN FAILURE"

    def test_dm_screen_failure_arm_empty(self):
        """Screen failure should have empty ARM/ARMCD."""
        subj = get_subject_rows(self.dm, "008")
        row = subj.iloc[0]
        assert row["ARMCD"] == "" or pd.isna(row["ARMCD"])
        assert row["ARM"] == "" or pd.isna(row["ARM"])

    def test_dm_screen_failure_rfstdtc_empty(self):
        """Screen failure should have empty RFSTDTC (no treatment)."""
        subj = get_subject_rows(self.dm, "008")
        val = subj.iloc[0]["RFSTDTC"]
        assert val == "" or pd.isna(val), f"Screen failure RFSTDTC should be empty, got {val}"

    def test_dm_dates_iso8601(self):
        iso_pat = re.compile(r"^\d{4}-\d{2}-\d{2}")
        date_cols = ["RFSTDTC", "RFENDTC", "RFICDTC", "BRTHDTC"]
        for col in date_cols:
            if col in self.dm.columns:
                for val in self.dm[col]:
                    if val and val != "":
                        assert iso_pat.match(val), f"{col}='{val}' not ISO 8601"

    def test_dm_usubjid_contains_studyid(self):
        for uid in self.dm["USUBJID"]:
            assert "XYZ001" in uid, f"USUBJID missing study ID: {uid}"

    def test_dm_variable_names_max_8_chars(self):
        for col in self.dm.columns:
            assert len(col) <= 8, f"Variable name too long: {col} ({len(col)} chars)"


# ================================================================
# AE DOMAIN TESTS
# ================================================================


class TestAE:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.ae, self.meta = read_xpt("ae.xpt")

    def test_ae_exists_and_has_records(self):
        assert len(self.ae) > 0

    def test_ae_record_count(self):
        assert len(self.ae) == 9, f"Expected 9 AE records, got {len(self.ae)}"

    def test_ae_required_columns(self):
        required = ["STUDYID", "DOMAIN", "USUBJID", "AESEQ", "AETERM",
                     "AESTDTC", "AESEV", "AESER"]
        for col in required:
            assert col in self.ae.columns, f"Missing column: {col}"

    def test_ae_expected_columns(self):
        expected = ["AEDECOD", "AEREL", "AEOUT", "AEACN", "AEENDTC",
                     "AESTDY", "AEENDY"]
        for col in expected:
            assert col in self.ae.columns, f"Missing expected column: {col}"

    def test_ae_severity_controlled_terminology(self):
        valid_sev = {"MILD", "MODERATE", "SEVERE"}
        actual = set(self.ae["AESEV"].unique()) - {""}
        assert actual.issubset(valid_sev), f"Invalid AESEV: {actual - valid_sev}"

    def test_ae_seriousness_controlled_terminology(self):
        valid_ser = {"Y", "N"}
        actual = set(self.ae["AESER"].unique()) - {""}
        assert actual.issubset(valid_ser), f"Invalid AESER: {actual - valid_ser}"

    def test_ae_outcome_controlled_terminology(self):
        valid_out = {
            "RECOVERED/RESOLVED", "RECOVERING/RESOLVING",
            "NOT RECOVERED/NOT RESOLVED",
            "RECOVERED/RESOLVED WITH SEQUELAE",
            "FATAL", "UNKNOWN",
        }
        actual = set(self.ae["AEOUT"].unique()) - {""}
        assert actual.issubset(valid_out), f"Invalid AEOUT: {actual - valid_out}"

    def test_ae_action_controlled_terminology(self):
        valid_acn = {
            "DOSE NOT CHANGED", "DOSE REDUCED", "DRUG WITHDRAWN",
            "DRUG INTERRUPTED", "NOT APPLICABLE", "DOSE INCREASED",
        }
        actual = set(self.ae["AEACN"].unique()) - {""}
        assert actual.issubset(valid_acn), f"Invalid AEACN: {actual - valid_acn}"

    def test_ae_severity_numeric_mapped_correctly(self):
        """Severity code 1 -> MILD for subject 001 AE 1."""
        subj = self.ae[
            (self.ae["USUBJID"].str.endswith("-001")) & (self.ae["AESEQ"] == 1)
        ]
        assert len(subj) == 1
        assert subj.iloc[0]["AESEV"] == "MILD"

    def test_ae_severity_numeric_2_to_moderate(self):
        """Severity code 2 -> MODERATE for subject 001 AE 2."""
        subj = self.ae[
            (self.ae["USUBJID"].str.endswith("-001")) & (self.ae["AESEQ"] == 2)
        ]
        assert len(subj) == 1
        assert subj.iloc[0]["AESEV"] == "MODERATE"

    def test_ae_severity_numeric_3_to_severe(self):
        """Severity code 3 -> SEVERE for subject 005 AE 1."""
        subj = self.ae[
            (self.ae["USUBJID"].str.endswith("-005")) & (self.ae["AESEQ"] == 1)
        ]
        assert len(subj) == 1
        assert subj.iloc[0]["AESEV"] == "SEVERE"

    def test_ae_severity_text_mild(self):
        """Text 'Mild' -> MILD for subject 003 AE 1."""
        subj = self.ae[
            (self.ae["USUBJID"].str.endswith("-003")) & (self.ae["AESEQ"] == 1)
        ]
        assert len(subj) == 1
        assert subj.iloc[0]["AESEV"] == "MILD"

    def test_ae_severity_text_moderate_lowercase(self):
        """Text 'moderate' -> MODERATE for subject 007 AE 1."""
        subj = self.ae[
            (self.ae["USUBJID"].str.endswith("-007")) & (self.ae["AESEQ"] == 1)
        ]
        assert len(subj) == 1
        assert subj.iloc[0]["AESEV"] == "MODERATE"

    def test_ae_seriousness_yes(self):
        """Subject 005 AE 1 is serious."""
        subj = self.ae[
            (self.ae["USUBJID"].str.endswith("-005")) & (self.ae["AESEQ"] == 1)
        ]
        assert subj.iloc[0]["AESER"] == "Y"

    def test_ae_dates_iso8601(self):
        iso_pat = re.compile(r"^\d{4}-\d{2}-\d{2}")
        for val in self.ae["AESTDTC"]:
            if val and val != "":
                assert iso_pat.match(val), f"AESTDTC='{val}' not ISO 8601"

    def test_ae_subject_001_ae1_start_date(self):
        """Raw '03/20/2023' -> '2023-03-20'."""
        subj = self.ae[
            (self.ae["USUBJID"].str.endswith("-001")) & (self.ae["AESEQ"] == 1)
        ]
        assert subj.iloc[0]["AESTDTC"] == "2023-03-20"

    def test_ae_subject_001_ae2_start_date(self):
        """Raw '15-Apr-2023' -> '2023-04-15'."""
        subj = self.ae[
            (self.ae["USUBJID"].str.endswith("-001")) & (self.ae["AESEQ"] == 2)
        ]
        assert subj.iloc[0]["AESTDTC"] == "2023-04-15"

    def test_ae_subject_005_ae1_start_date(self):
        """Raw '01MAY2023' -> '2023-05-01'."""
        subj = self.ae[
            (self.ae["USUBJID"].str.endswith("-005")) & (self.ae["AESEQ"] == 1)
        ]
        assert subj.iloc[0]["AESTDTC"] == "2023-05-01"

    def test_ae_subject_007_ae1_start_date(self):
        """Raw 'May 20 2023' -> '2023-05-20'."""
        subj = self.ae[
            (self.ae["USUBJID"].str.endswith("-007")) & (self.ae["AESEQ"] == 1)
        ]
        assert subj.iloc[0]["AESTDTC"] == "2023-05-20"

    def test_ae_subject_007_ae2_start_date(self):
        """Raw 'Jun-01-2023' -> '2023-06-01'."""
        subj = self.ae[
            (self.ae["USUBJID"].str.endswith("-007")) & (self.ae["AESEQ"] == 2)
        ]
        assert subj.iloc[0]["AESTDTC"] == "2023-06-01"

    def test_ae_study_day_subject_001_ae1(self):
        """RFSTDTC=2023-03-15, AESTDTC=2023-03-20 -> AESTDY=6."""
        subj = self.ae[
            (self.ae["USUBJID"].str.endswith("-001")) & (self.ae["AESEQ"] == 1)
        ]
        assert subj.iloc[0]["AESTDY"] == 6

    def test_ae_study_day_subject_001_ae2(self):
        """RFSTDTC=2023-03-15, AESTDTC=2023-04-15 -> AESTDY=32."""
        subj = self.ae[
            (self.ae["USUBJID"].str.endswith("-001")) & (self.ae["AESEQ"] == 2)
        ]
        assert subj.iloc[0]["AESTDY"] == 32

    def test_ae_outcome_recovered(self):
        """Raw 'Recovered' -> 'RECOVERED/RESOLVED'."""
        subj = self.ae[
            (self.ae["USUBJID"].str.endswith("-001")) & (self.ae["AESEQ"] == 1)
        ]
        assert subj.iloc[0]["AEOUT"] == "RECOVERED/RESOLVED"

    def test_ae_outcome_recovering(self):
        """Raw 'Recovering' -> 'RECOVERING/RESOLVING'."""
        subj = self.ae[
            (self.ae["USUBJID"].str.endswith("-007")) & (self.ae["AESEQ"] == 1)
        ]
        assert subj.iloc[0]["AEOUT"] == "RECOVERING/RESOLVING"

    def test_ae_outcome_not_recovered(self):
        """Raw 'Not Recovered' -> 'NOT RECOVERED/NOT RESOLVED'."""
        subj = self.ae[
            (self.ae["USUBJID"].str.endswith("-005")) & (self.ae["AESEQ"] == 1)
        ]
        assert subj.iloc[0]["AEOUT"] == "NOT RECOVERED/NOT RESOLVED"

    def test_ae_outcome_with_sequelae(self):
        """Raw 'Recovered with Sequelae' -> 'RECOVERED/RESOLVED WITH SEQUELAE'."""
        subj = self.ae[
            (self.ae["USUBJID"].str.endswith("-003")) & (self.ae["AESEQ"] == 1)
        ]
        assert subj.iloc[0]["AEOUT"] == "RECOVERED/RESOLVED WITH SEQUELAE"

    def test_ae_action_none_maps_to_dose_not_changed(self):
        """Raw 'None' -> 'DOSE NOT CHANGED'."""
        subj = self.ae[
            (self.ae["USUBJID"].str.endswith("-001")) & (self.ae["AESEQ"] == 1)
        ]
        assert subj.iloc[0]["AEACN"] == "DOSE NOT CHANGED"

    def test_ae_action_drug_withdrawn(self):
        """Raw 'Drug Withdrawn' -> 'DRUG WITHDRAWN'."""
        subj = self.ae[
            (self.ae["USUBJID"].str.endswith("-005")) & (self.ae["AESEQ"] == 1)
        ]
        assert subj.iloc[0]["AEACN"] == "DRUG WITHDRAWN"

    def test_ae_variable_names_max_8_chars(self):
        for col in self.ae.columns:
            assert len(col) <= 8, f"Variable name too long: {col}"


# ================================================================
# VS DOMAIN TESTS
# ================================================================


class TestVS:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.vs, self.meta = read_xpt("vs.xpt")

    def test_vs_exists_and_has_records(self):
        assert len(self.vs) > 0

    def test_vs_record_count(self):
        # 3 subjects: 001 has 16 records, 002 has 11, 003 has 6 = 33
        assert len(self.vs) == 33, f"Expected 33 VS records, got {len(self.vs)}"

    def test_vs_required_columns(self):
        required = ["STUDYID", "DOMAIN", "USUBJID", "VSSEQ", "VSTESTCD",
                     "VSTEST", "VSORRES", "VSORRESU", "VSSTRESN", "VSSTRESU",
                     "VSDTC"]
        for col in required:
            assert col in self.vs.columns, f"Missing column: {col}"

    def test_vs_expected_columns(self):
        expected = ["VSSTRESC", "VSDY", "VISITNUM", "VISIT", "VSLOBXFL"]
        for col in expected:
            assert col in self.vs.columns, f"Missing expected column: {col}"

    def test_vs_testcd_valid(self):
        valid = {"HEIGHT", "WEIGHT", "SYSBP", "DIABP", "HR", "TEMP"}
        actual = set(self.vs["VSTESTCD"].unique())
        assert actual.issubset(valid), f"Invalid VSTESTCD: {actual - valid}"

    def test_vs_height_conversion_subject_001(self):
        """68 inches * 2.54 = 172.72 cm."""
        subj = self.vs[
            (self.vs["USUBJID"].str.endswith("-001")) &
            (self.vs["VSTESTCD"] == "HEIGHT")
        ]
        assert len(subj) >= 1
        row = subj.iloc[0]
        assert abs(row["VSSTRESN"] - 172.72) < 0.1, \
            f"Expected ~172.72, got {row['VSSTRESN']}"
        assert row["VSSTRESU"] == "cm"

    def test_vs_height_conversion_subject_002(self):
        """64 inches * 2.54 = 162.56 cm."""
        subj = self.vs[
            (self.vs["USUBJID"].str.endswith("-002")) &
            (self.vs["VSTESTCD"] == "HEIGHT")
        ]
        assert len(subj) >= 1
        assert abs(subj.iloc[0]["VSSTRESN"] - 162.56) < 0.1

    def test_vs_weight_conversion_subject_001_screening(self):
        """165 lbs * 0.453592 ≈ 74.84 kg."""
        subj = self.vs[
            (self.vs["USUBJID"].str.endswith("-001")) &
            (self.vs["VSTESTCD"] == "WEIGHT") &
            (self.vs["VISITNUM"] == 1)
        ]
        assert len(subj) >= 1
        assert abs(subj.iloc[0]["VSSTRESN"] - 74.84) < 0.1, \
            f"Expected ~74.84, got {subj.iloc[0]['VSSTRESN']}"
        assert subj.iloc[0]["VSSTRESU"] == "kg"

    def test_vs_temperature_conversion_subject_001_screening(self):
        """(98.6 - 32) * 5/9 = 37.0 C."""
        subj = self.vs[
            (self.vs["USUBJID"].str.endswith("-001")) &
            (self.vs["VSTESTCD"] == "TEMP") &
            (self.vs["VISITNUM"] == 1)
        ]
        assert len(subj) >= 1
        assert abs(subj.iloc[0]["VSSTRESN"] - 37.0) < 0.1, \
            f"Expected ~37.0, got {subj.iloc[0]['VSSTRESN']}"
        assert subj.iloc[0]["VSSTRESU"] == "C"

    def test_vs_temperature_conversion_subject_003(self):
        """(99.1 - 32) * 5/9 ≈ 37.28 C."""
        subj = self.vs[
            (self.vs["USUBJID"].str.endswith("-003")) &
            (self.vs["VSTESTCD"] == "TEMP")
        ]
        assert len(subj) >= 1
        assert abs(subj.iloc[0]["VSSTRESN"] - 37.28) < 0.1

    def test_vs_bp_units_unchanged(self):
        """Blood pressure should stay in mmHg."""
        bp = self.vs[self.vs["VSTESTCD"].isin(["SYSBP", "DIABP"])]
        for _, row in bp.iterrows():
            assert row["VSSTRESU"] == "mmHg", \
                f"BP standard unit should be mmHg, got {row['VSSTRESU']}"

    def test_vs_bp_values_unchanged(self):
        """Subject 001 Screening SYSBP = 128 mmHg (no conversion)."""
        subj = self.vs[
            (self.vs["USUBJID"].str.endswith("-001")) &
            (self.vs["VSTESTCD"] == "SYSBP") &
            (self.vs["VISITNUM"] == 1)
        ]
        assert len(subj) >= 1
        assert abs(subj.iloc[0]["VSSTRESN"] - 128) < 0.1

    def test_vs_study_day_screening(self):
        """Subject 001 Screening 2023-03-14 vs RFSTDTC 2023-03-15 -> VSDY=-1."""
        subj = self.vs[
            (self.vs["USUBJID"].str.endswith("-001")) &
            (self.vs["VISITNUM"] == 1)
        ]
        assert len(subj) > 0
        for _, row in subj.iterrows():
            assert row["VSDY"] == -1, f"Expected VSDY=-1, got {row['VSDY']}"

    def test_vs_study_day_baseline(self):
        """Subject 001 Baseline 2023-03-15 = RFSTDTC -> VSDY=1."""
        subj = self.vs[
            (self.vs["USUBJID"].str.endswith("-001")) &
            (self.vs["VISITNUM"] == 2)
        ]
        assert len(subj) > 0
        for _, row in subj.iterrows():
            assert row["VSDY"] == 1, f"Expected VSDY=1, got {row['VSDY']}"

    def test_vs_study_day_week4(self):
        """Subject 001 Week 4 2023-04-12 -> VSDY=29 (28 days + 1)."""
        subj = self.vs[
            (self.vs["USUBJID"].str.endswith("-001")) &
            (self.vs["VISITNUM"] == 3)
        ]
        assert len(subj) > 0
        for _, row in subj.iterrows():
            assert row["VSDY"] == 29, f"Expected VSDY=29, got {row['VSDY']}"

    def test_vs_lobxfl_screening(self):
        """Screening observations (before RFXSTDTC) should have VSLOBXFL='Y'."""
        screening = self.vs[
            (self.vs["USUBJID"].str.endswith("-001")) &
            (self.vs["VISITNUM"] == 1)
        ]
        for _, row in screening.iterrows():
            assert row["VSLOBXFL"] == "Y", \
                f"Expected VSLOBXFL='Y' for screening {row['VSTESTCD']}"

    def test_vs_lobxfl_post_treatment_not_set(self):
        """Week 4 observations should NOT have VSLOBXFL='Y'."""
        wk4 = self.vs[
            (self.vs["USUBJID"].str.endswith("-001")) &
            (self.vs["VISITNUM"] == 3)
        ]
        for _, row in wk4.iterrows():
            assert row["VSLOBXFL"] != "Y", \
                f"VSLOBXFL should not be Y for post-treatment {row['VSTESTCD']}"

    def test_vs_lobxfl_baseline_not_set(self):
        """Baseline = RFXSTDTC, not strictly before -> VSLOBXFL should NOT be Y."""
        baseline = self.vs[
            (self.vs["USUBJID"].str.endswith("-001")) &
            (self.vs["VISITNUM"] == 2)
        ]
        for _, row in baseline.iterrows():
            assert row["VSLOBXFL"] != "Y", \
                f"VSLOBXFL should not be Y for baseline {row['VSTESTCD']}"

    def test_vs_dates_iso8601(self):
        iso_pat = re.compile(r"^\d{4}-\d{2}-\d{2}")
        for val in self.vs["VSDTC"]:
            if val and val != "":
                assert iso_pat.match(val), f"VSDTC='{val}' not ISO 8601"

    def test_vs_variable_names_max_8_chars(self):
        for col in self.vs.columns:
            assert len(col) <= 8, f"Variable name too long: {col}"


# ================================================================
# TS DOMAIN TESTS
# ================================================================


class TestTS:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.ts, self.meta = read_xpt("ts.xpt")

    def test_ts_exists_and_has_records(self):
        assert len(self.ts) > 0

    def test_ts_required_columns(self):
        required = ["STUDYID", "DOMAIN", "TSSEQ", "TSPARMCD", "TSPARM", "TSVAL"]
        for col in required:
            assert col in self.ts.columns, f"Missing column: {col}"

    def test_ts_all_studyid(self):
        assert all(self.ts["STUDYID"] == "XYZ001")

    def test_ts_all_domain(self):
        assert all(self.ts["DOMAIN"] == "TS")

    def test_ts_contains_key_parameters(self):
        parmcds = set(self.ts["TSPARMCD"].unique())
        required = {"SPONSOR", "SSTDTC", "SENDTC", "TITLE", "TPHASE", "RANDOM"}
        missing = required - parmcds
        assert len(missing) == 0, f"Missing TS parameters: {missing}"

    def test_ts_sstdtc_iso8601(self):
        """'March 1 2023' -> '2023-03-01'."""
        row = self.ts[self.ts["TSPARMCD"] == "SSTDTC"]
        assert len(row) == 1
        assert row.iloc[0]["TSVAL"] == "2023-03-01"

    def test_ts_sendtc_iso8601(self):
        """'August 31 2023' -> '2023-08-31'."""
        row = self.ts[self.ts["TSPARMCD"] == "SENDTC"]
        assert len(row) == 1
        assert row.iloc[0]["TSVAL"] == "2023-08-31"

    def test_ts_dcutdtc_iso8601(self):
        """'September 15 2023' -> '2023-09-15'."""
        row = self.ts[self.ts["TSPARMCD"] == "DCUTDTC"]
        assert len(row) == 1
        assert row.iloc[0]["TSVAL"] == "2023-09-15"

    def test_ts_tsseq_sequential(self):
        """TSSEQ should be sequential positive integers."""
        seqs = sorted(self.ts["TSSEQ"].tolist())
        expected = list(range(1, len(seqs) + 1))
        assert seqs == expected, f"TSSEQ not sequential: {seqs}"

    def test_ts_variable_names_max_8_chars(self):
        for col in self.ts.columns:
            assert len(col) <= 8, f"Variable name too long: {col}"


# ================================================================
# SUPPAE DOMAIN TESTS
# ================================================================


class TestSUPPAE:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.suppae, self.meta = read_xpt("suppae.xpt")

    def test_suppae_exists_and_has_records(self):
        assert len(self.suppae) > 0

    def test_suppae_required_columns(self):
        required = ["STUDYID", "RDOMAIN", "USUBJID", "IDVAR", "IDVARVAL",
                     "QNAM", "QLABEL", "QVAL", "QORIG"]
        for col in required:
            assert col in self.suppae.columns, f"Missing column: {col}"

    def test_suppae_all_rdomain_ae(self):
        assert all(self.suppae["RDOMAIN"] == "AE"), "RDOMAIN should be AE"

    def test_suppae_idvar_is_aeseq(self):
        assert all(self.suppae["IDVAR"] == "AESEQ"), "IDVAR should be AESEQ"

    def test_suppae_qnam_max_8_chars(self):
        for qnam in self.suppae["QNAM"].unique():
            assert len(qnam) <= 8, f"QNAM too long: {qnam} ({len(qnam)} chars)"

    def test_suppae_record_count(self):
        """One SUPPAE record per AE for follow_up_needed."""
        assert len(self.suppae) == 9, f"Expected 9 SUPPAE records, got {len(self.suppae)}"

    def test_suppae_all_studyid(self):
        assert all(self.suppae["STUDYID"] == "XYZ001")

    def test_suppae_qval_values(self):
        """Follow-up values should be Y or N."""
        valid_vals = {"Y", "N"}
        actual = set(self.suppae["QVAL"].unique())
        assert actual.issubset(valid_vals), f"Unexpected QVAL values: {actual}"

    def test_suppae_has_y_values(self):
        """At least some AEs should have follow_up_needed = Y."""
        y_count = (self.suppae["QVAL"] == "Y").sum()
        assert y_count >= 3, f"Expected at least 3 Y values, got {y_count}"

    def test_suppae_variable_names_max_8_chars(self):
        for col in self.suppae.columns:
            assert len(col) <= 8, f"Variable name too long: {col}"
