
import os
import re
import pytest
import pandas as pd

OUTPUT_DIR = "/app/sdtm_output"
STUDYID = "ECD-2023-0847"

ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ISO_DATETIME_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")


def read_domain(filename):
    path = os.path.join(OUTPUT_DIR, filename)
    assert os.path.isfile(path), f"Output file {filename} does not exist"
    return pd.read_csv(path, dtype=str)


# ========== FILE EXISTENCE ==========

class TestFileExistence:
    @pytest.mark.parametrize("filename", [
        "dm.csv", "ae.csv", "vs.csv", "lb.csv", "ex.csv",
        "ds.csv", "ts.csv", "suppae.csv"
    ])
    def test_output_file_exists(self, filename):
        path = os.path.join(OUTPUT_DIR, filename)
        assert os.path.isfile(path), f"{filename} not found in {OUTPUT_DIR}"


# ========== DM DOMAIN ==========

class TestDM:
    @pytest.fixture(autouse=True)
    def load_dm(self):
        self.dm = read_domain("dm.csv")

    def test_required_columns(self):
        required = ["STUDYID", "DOMAIN", "USUBJID", "SUBJID"]
        for col in required:
            assert col in self.dm.columns, f"DM missing required column {col}"

    def test_expected_columns(self):
        expected = ["RFSTDTC", "BRTHDTC", "AGE", "AGEU", "SEX", "RACE",
                     "ETHNIC", "ARMCD", "ARM", "COUNTRY", "SITEID"]
        for col in expected:
            assert col in self.dm.columns, f"DM missing expected column {col}"

    def test_row_count(self):
        assert len(self.dm) == 8, f"DM should have 8 rows, got {len(self.dm)}"

    def test_studyid(self):
        assert all(self.dm["STUDYID"] == STUDYID)

    def test_domain(self):
        assert all(self.dm["DOMAIN"] == "DM")

    def test_usubjid_format(self):
        pattern = re.compile(r"^ECD-2023-0847-\d{3}-\d{3}$")
        for uid in self.dm["USUBJID"]:
            assert pattern.match(uid), f"USUBJID '{uid}' does not match expected format"

    def test_sex_values(self):
        valid = {"M", "F"}
        for v in self.dm["SEX"]:
            assert v in valid, f"SEX value '{v}' not in {valid}"

    def test_sex_mapping(self):
        subj_001 = self.dm[self.dm["SUBJID"] == "001"]
        assert len(subj_001) == 1
        assert subj_001.iloc[0]["SEX"] == "M"
        subj_002 = self.dm[self.dm["SUBJID"] == "002"]
        assert len(subj_002) == 1
        assert subj_002.iloc[0]["SEX"] == "F"

    def test_age_values(self):
        # DNA: specific age calculations with edge cases
        # 001: born 02/29/1984 (leap year!), enrolled 12/18/2023 -> 39
        # 002: born 06/14/1971, enrolled 12/22/2023 -> 52
        # 003: born 11/03/1966, enrolled 01/12/2024 -> 57 (bday not passed)
        # 004: born 08/21/1953, enrolled 01/15/2024 -> 70 (bday not passed)
        # 005: born 04/30/1978, enrolled 01/22/2024 -> 45 (bday not passed)
        # 006: born 12/25/1960, enrolled 01/28/2024 -> 63 (bday not passed)
        # 007: born 07/07/1945, enrolled 02/08/2024 -> 78 (bday not passed)
        # 008: born 03/12/1988, enrolled 02/12/2024 -> 35 (bday not passed)
        expected_ages = {
            "001": 39,
            "002": 52,
            "003": 57,
            "004": 70,
            "005": 45,
            "006": 63,
            "007": 78,
            "008": 35,
        }
        for subjid, expected_age in expected_ages.items():
            row = self.dm[self.dm["SUBJID"] == subjid]
            assert len(row) == 1, f"Expected 1 row for SUBJID {subjid}"
            actual_age = int(float(row.iloc[0]["AGE"]))
            assert actual_age == expected_age, \
                f"AGE for {subjid}: expected {expected_age}, got {actual_age}"

    def test_ageu(self):
        assert all(self.dm["AGEU"] == "YEARS")

    def test_rfstdtc_iso8601(self):
        for dtc in self.dm["RFSTDTC"]:
            assert ISO_DATE_PATTERN.match(str(dtc)), f"RFSTDTC '{dtc}' not ISO 8601"

    def test_brthdtc_iso8601(self):
        for dtc in self.dm["BRTHDTC"]:
            assert ISO_DATE_PATTERN.match(str(dtc)), f"BRTHDTC '{dtc}' not ISO 8601"

    def test_leap_year_brthdtc(self):
        # DNA: Subject 001 born on Feb 29 (leap year) must be preserved
        subj_001 = self.dm[self.dm["SUBJID"] == "001"]
        assert subj_001.iloc[0]["BRTHDTC"] == "1984-02-29"

    def test_specific_rfstdtc_cross_year(self):
        # DNA: Subject 001 enrolled in December 2023
        subj_001 = self.dm[self.dm["SUBJID"] == "001"]
        assert subj_001.iloc[0]["RFSTDTC"] == "2023-12-18"

    def test_specific_rfstdtc_jan(self):
        subj_003 = self.dm[self.dm["SUBJID"] == "003"]
        assert subj_003.iloc[0]["RFSTDTC"] == "2024-01-12"

    def test_arm_populated(self):
        assert all(self.dm["ARM"].notna())
        assert all(self.dm["ARMCD"].notna())

    def test_arm_values(self):
        subj_001 = self.dm[self.dm["SUBJID"] == "001"]
        assert subj_001.iloc[0]["ARMCD"] == "COMBO"
        subj_003 = self.dm[self.dm["SUBJID"] == "003"]
        assert subj_003.iloc[0]["ARMCD"] == "VEM"

    def test_country(self):
        subj_001 = self.dm[self.dm["SUBJID"] == "001"]
        assert subj_001.iloc[0]["COUNTRY"] == "USA"
        subj_005 = self.dm[self.dm["SUBJID"] == "005"]
        assert subj_005.iloc[0]["COUNTRY"] == "DEU"
        subj_007 = self.dm[self.dm["SUBJID"] == "007"]
        assert subj_007.iloc[0]["COUNTRY"] == "JPN"


# ========== AE DOMAIN ==========

class TestAE:
    @pytest.fixture(autouse=True)
    def load_ae(self):
        self.ae = read_domain("ae.csv")

    def test_required_columns(self):
        required = ["STUDYID", "DOMAIN", "USUBJID", "AESEQ", "AETERM", "AEDECOD"]
        for col in required:
            assert col in self.ae.columns, f"AE missing column {col}"

    def test_expected_columns(self):
        expected = ["AESTDTC", "AESEV", "AESER", "AEREL", "AEOUT", "AESTDY"]
        for col in expected:
            assert col in self.ae.columns, f"AE missing column {col}"

    def test_row_count(self):
        assert len(self.ae) == 12, f"AE should have 12 rows, got {len(self.ae)}"

    def test_studyid(self):
        assert all(self.ae["STUDYID"] == STUDYID)

    def test_domain(self):
        assert all(self.ae["DOMAIN"] == "AE")

    def test_severity_ct(self):
        valid = {"MILD", "MODERATE", "SEVERE"}
        for v in self.ae["AESEV"]:
            assert v in valid, f"AESEV '{v}' not in {valid}"

    def test_severity_mapping_mild(self):
        # Diarrhoea (grade 1) should be MILD
        diarrhoea = self.ae[self.ae["AETERM"].str.upper().str.contains("DIARRHOEA")]
        assert len(diarrhoea) >= 1
        assert diarrhoea.iloc[0]["AESEV"] == "MILD"

    def test_severity_mapping_severe(self):
        # Maculopapular rash (grade 3) should be SEVERE
        rash = self.ae[self.ae["AETERM"].str.upper().str.contains("RASH")]
        assert len(rash) >= 1
        assert rash.iloc[0]["AESEV"] == "SEVERE"

    def test_seriousness_values(self):
        valid = {"Y", "N"}
        for v in self.ae["AESER"]:
            assert v in valid, f"AESER '{v}' not in {valid}"

    def test_seriousness_mapping(self):
        # Maculopapular rash is serious (Yes -> Y)
        rash = self.ae[self.ae["AETERM"].str.upper().str.contains("RASH")]
        assert rash.iloc[0]["AESER"] == "Y"
        # Diarrhoea is not serious (No -> N)
        diarrhoea = self.ae[self.ae["AETERM"].str.upper().str.contains("DIARRHOEA")]
        assert diarrhoea.iloc[0]["AESER"] == "N"

    def test_outcome_ct(self):
        valid = {"RECOVERED/RESOLVED", "NOT RECOVERED/NOT RESOLVED",
                 "RECOVERING/RESOLVING", "FATAL",
                 "RECOVERED/RESOLVED WITH SEQUELAE", "UNKNOWN"}
        for v in self.ae["AEOUT"]:
            assert v in valid, f"AEOUT '{v}' not in {valid}"

    def test_outcome_mapping_recovered(self):
        diarrhoea = self.ae[self.ae["AETERM"].str.upper().str.contains("DIARRHOEA")]
        assert diarrhoea.iloc[0]["AEOUT"] == "RECOVERED/RESOLVED"

    def test_outcome_mapping_not_resolved(self):
        rash = self.ae[self.ae["AETERM"].str.upper().str.contains("RASH")]
        assert rash.iloc[0]["AEOUT"] == "NOT RECOVERED/NOT RESOLVED"

    def test_outcome_mapping_recovering(self):
        qt = self.ae[self.ae["AETERM"].str.upper().str.contains("QT PROLONGATION")]
        assert len(qt) >= 1
        assert qt.iloc[0]["AEOUT"] == "RECOVERING/RESOLVING"

    def test_aedecod_uppercase(self):
        for i, row in self.ae.iterrows():
            assert row["AEDECOD"] == row["AETERM"].upper(), \
                f"AEDECOD should be uppercase AETERM"

    def test_dates_iso8601(self):
        for dtc in self.ae["AESTDTC"]:
            assert ISO_DATE_PATTERN.match(str(dtc)), f"AESTDTC '{dtc}' not ISO 8601"

    def test_study_day_rash_cross_year(self):
        # DNA: Subject 201-001: RFSTDTC=12/18/2023, AE start=01/05/2024
        # diff=18, AESTDY=19 (crosses year boundary)
        rash = self.ae[self.ae["AETERM"].str.upper().str.contains("RASH")]
        aestdy = int(float(rash.iloc[0]["AESTDY"]))
        assert aestdy == 19, f"AESTDY for rash: expected 19, got {aestdy}"

    def test_study_day_diarrhoea(self):
        # DNA: Subject 201-001: RFSTDTC=12/18/2023, AE start=01/15/2024
        # diff=28, AESTDY=29
        diarrhoea = self.ae[self.ae["AETERM"].str.upper().str.contains("DIARRHOEA")]
        aestdy = int(float(diarrhoea.iloc[0]["AESTDY"]))
        assert aestdy == 29, f"AESTDY for diarrhoea: expected 29, got {aestdy}"

    def test_study_day_sqcc(self):
        # DNA: Subject 202-003: RFSTDTC=01/12/2024, AE start=02/28/2024
        # diff=47, AESTDY=48
        sqcc = self.ae[self.ae["AETERM"].str.upper().str.contains("SQUAMOUS")]
        assert len(sqcc) >= 1
        aestdy = int(float(sqcc.iloc[0]["AESTDY"]))
        assert aestdy == 48, f"AESTDY for SQCC: expected 48, got {aestdy}"

    def test_study_day_qt(self):
        # DNA: Subject 203-005: RFSTDTC=01/22/2024, AE start=03/01/2024
        # diff=39 (Jan:9 + Feb:29 + Mar:1), AESTDY=40
        qt = self.ae[self.ae["AETERM"].str.upper().str.contains("QT")]
        assert len(qt) >= 1
        aestdy = int(float(qt.iloc[0]["AESTDY"]))
        assert aestdy == 40, f"AESTDY for QT prolongation: expected 40, got {aestdy}"

    def test_study_day_hepatotoxicity(self):
        # DNA: Subject 204-007: RFSTDTC=02/08/2024, AE start=02/20/2024
        # diff=12, AESTDY=13
        hepato = self.ae[self.ae["AETERM"].str.upper().str.contains("HEPATOTOXICITY")]
        assert len(hepato) >= 1
        aestdy = int(float(hepato.iloc[0]["AESTDY"]))
        assert aestdy == 13, f"AESTDY for hepatotoxicity: expected 13, got {aestdy}"

    def test_aeendy_diarrhoea(self):
        # DNA: Subject 201-001: RFSTDTC=12/18/2023, AE end=01/22/2024
        # diff=35, AEENDY=36
        diarrhoea = self.ae[self.ae["AETERM"].str.upper().str.contains("DIARRHOEA")]
        assert "AEENDY" in self.ae.columns, "AE missing AEENDY column"
        aeendy = int(float(diarrhoea.iloc[0]["AEENDY"]))
        assert aeendy == 36, f"AEENDY for diarrhoea: expected 36, got {aeendy}"


# ========== VS DOMAIN ==========

class TestVS:
    @pytest.fixture(autouse=True)
    def load_vs(self):
        self.vs = read_domain("vs.csv")

    def test_required_columns(self):
        required = ["STUDYID", "DOMAIN", "USUBJID", "VSSEQ",
                     "VSTESTCD", "VSTEST"]
        for col in required:
            assert col in self.vs.columns, f"VS missing column {col}"

    def test_expected_columns(self):
        expected = ["VSORRES", "VSORRESU", "VSSTRESC", "VSSTRESN",
                     "VSSTRESU", "VSDTC", "VSDY", "VSBLFL", "VISITNUM", "VISIT"]
        for col in expected:
            assert col in self.vs.columns, f"VS missing column {col}"

    def test_row_count(self):
        assert len(self.vs) == 36, f"VS should have 36 rows, got {len(self.vs)}"

    def test_domain(self):
        assert all(self.vs["DOMAIN"] == "VS")

    def test_testcd_values(self):
        valid = {"SYSBP", "DIABP", "HR", "WEIGHT", "HEIGHT"}
        for v in self.vs["VSTESTCD"]:
            assert v in valid, f"VSTESTCD '{v}' not in {valid}"

    def test_testcd_max_length(self):
        for v in self.vs["VSTESTCD"]:
            assert len(v) <= 8, f"VSTESTCD '{v}' exceeds 8 chars"

    def test_baseline_flag(self):
        baseline_rows = self.vs[self.vs["VISIT"].str.upper().str.contains("BASELINE", na=False)]
        for _, row in baseline_rows.iterrows():
            assert str(row["VSBLFL"]).strip() == "Y", \
                f"VSBLFL should be 'Y' for Baseline visit row"

        non_baseline = self.vs[~self.vs["VISIT"].str.upper().str.contains("BASELINE", na=False)]
        for _, row in non_baseline.iterrows():
            val = str(row.get("VSBLFL", "")).strip()
            assert val in ("", "nan", "None"), \
                f"VSBLFL should be empty for non-baseline, got '{val}'"

    def test_datetime_format(self):
        for dtc in self.vs["VSDTC"]:
            dtc_str = str(dtc)
            assert ISO_DATE_PATTERN.match(dtc_str) or ISO_DATETIME_PATTERN.match(dtc_str), \
                f"VSDTC '{dtc_str}' not ISO 8601"

    def test_datetime_includes_time(self):
        has_time = any(ISO_DATETIME_PATTERN.match(str(dtc)) for dtc in self.vs["VSDTC"])
        assert has_time, "VS should include time in VSDTC when available"

    def test_screening_study_day_cross_year(self):
        # DNA: Subject 201-001: RFSTDTC=12/18/2023, screening=12/10/2023
        # diff=-8, VSDY=-8
        subj_001_screen = self.vs[
            (self.vs["USUBJID"].str.endswith("-001")) &
            (self.vs["VISIT"].str.upper().str.contains("SCREEN", na=False)) &
            (self.vs["VSTESTCD"] == "SYSBP")
        ]
        assert len(subj_001_screen) >= 1
        vsdy = int(float(subj_001_screen.iloc[0]["VSDY"]))
        assert vsdy == -8, f"VSDY for screening SYSBP 001: expected -8, got {vsdy}"

    def test_baseline_study_day(self):
        # DNA: Subject 201-001: RFSTDTC=12/18/2023, baseline=12/18/2023
        # diff=0, VSDY=1
        subj_001_bl = self.vs[
            (self.vs["USUBJID"].str.endswith("-001")) &
            (self.vs["VISIT"].str.upper().str.contains("BASELINE", na=False)) &
            (self.vs["VSTESTCD"] == "SYSBP")
        ]
        assert len(subj_001_bl) >= 1
        vsdy = int(float(subj_001_bl.iloc[0]["VSDY"]))
        assert vsdy == 1, f"VSDY for baseline SYSBP 001: expected 1, got {vsdy}"

    def test_screening_study_day_003(self):
        # DNA: Subject 202-003: RFSTDTC=01/12/2024, screening=01/05/2024
        # diff=-7, VSDY=-7
        subj_003_screen = self.vs[
            (self.vs["USUBJID"].str.endswith("-003")) &
            (self.vs["VISIT"].str.upper().str.contains("SCREEN", na=False)) &
            (self.vs["VSTESTCD"] == "SYSBP")
        ]
        assert len(subj_003_screen) >= 1
        vsdy = int(float(subj_003_screen.iloc[0]["VSDY"]))
        assert vsdy == -7, f"VSDY for screening SYSBP 003: expected -7, got {vsdy}"

    def test_vsdtc_december_2023(self):
        # DNA: Subject 001 screening is in December 2023
        subj_001_screen = self.vs[
            (self.vs["USUBJID"].str.endswith("-001")) &
            (self.vs["VISIT"].str.upper().str.contains("SCREEN", na=False)) &
            (self.vs["VSTESTCD"] == "SYSBP")
        ]
        dtc = str(subj_001_screen.iloc[0]["VSDTC"])
        assert dtc.startswith("2023-12-10"), f"Expected 2023-12-10, got {dtc}"


# ========== LB DOMAIN ==========

class TestLB:
    @pytest.fixture(autouse=True)
    def load_lb(self):
        self.lb = read_domain("lb.csv")

    def test_required_columns(self):
        required = ["STUDYID", "DOMAIN", "USUBJID", "LBSEQ",
                     "LBTESTCD", "LBTEST", "LBORRES", "LBORRESU",
                     "LBSTRESC", "LBSTRESN", "LBSTRESU", "LBNRIND"]
        for col in required:
            assert col in self.lb.columns, f"LB missing column {col}"

    def test_expected_columns(self):
        expected = ["LBSPEC", "VISITNUM", "VISIT", "LBDTC", "LBDY", "LBBLFL"]
        for col in expected:
            assert col in self.lb.columns, f"LB missing column {col}"

    def test_row_count(self):
        assert len(self.lb) == 16, f"LB should have 16 rows, got {len(self.lb)}"

    def test_domain(self):
        assert all(self.lb["DOMAIN"] == "LB")

    def test_studyid(self):
        assert all(self.lb["STUDYID"] == STUDYID)

    def test_testcd_values(self):
        valid = {"GLUC", "CREAT", "ALT", "HGB"}
        for v in self.lb["LBTESTCD"]:
            assert v in valid, f"LBTESTCD '{v}' not in {valid}"

    def test_si_conversion_glucose_001(self):
        # DNA: 126 mg/dL * 0.05551 = 6.99426 -> round(2dp) = 6.99
        row = self.lb[
            (self.lb["USUBJID"].str.endswith("-001")) &
            (self.lb["LBTESTCD"] == "GLUC")
        ]
        assert len(row) == 1
        val = float(row.iloc[0]["LBSTRESN"])
        assert abs(val - 6.99) < 0.02, f"GLUC SI for 001: expected ~6.99, got {val}"

    def test_si_conversion_glucose_002(self):
        # DNA: 92 mg/dL * 0.05551 = 5.10692 -> round(2dp) = 5.11
        row = self.lb[
            (self.lb["USUBJID"].str.endswith("-002")) &
            (self.lb["LBTESTCD"] == "GLUC")
        ]
        assert len(row) == 1
        val = float(row.iloc[0]["LBSTRESN"])
        assert abs(val - 5.11) < 0.02, f"GLUC SI for 002: expected ~5.11, got {val}"

    def test_si_conversion_glucose_003(self):
        # DNA: 187 mg/dL * 0.05551 = 10.38037 -> round(2dp) = 10.38
        row = self.lb[
            (self.lb["USUBJID"].str.endswith("-003")) &
            (self.lb["LBTESTCD"] == "GLUC")
        ]
        assert len(row) == 1
        val = float(row.iloc[0]["LBSTRESN"])
        assert abs(val - 10.38) < 0.02, f"GLUC SI for 003: expected ~10.38, got {val}"

    def test_si_conversion_glucose_004(self):
        # DNA: 108 mg/dL * 0.05551 = 5.99508 -> round(2dp) = 6.00
        row = self.lb[
            (self.lb["USUBJID"].str.endswith("-004")) &
            (self.lb["LBTESTCD"] == "GLUC")
        ]
        assert len(row) == 1
        val = float(row.iloc[0]["LBSTRESN"])
        assert abs(val - 6.00) < 0.02, f"GLUC SI for 004: expected ~6.00, got {val}"

    def test_si_conversion_creatinine_003(self):
        # DNA: 1.5 mg/dL * 88.4 = 132.60
        row = self.lb[
            (self.lb["USUBJID"].str.endswith("-003")) &
            (self.lb["LBTESTCD"] == "CREAT")
        ]
        assert len(row) == 1
        val = float(row.iloc[0]["LBSTRESN"])
        assert abs(val - 132.60) < 0.1, f"CREAT SI for 003: expected ~132.60, got {val}"

    def test_si_conversion_creatinine_001(self):
        # DNA: 1.1 mg/dL * 88.4 = 97.24
        row = self.lb[
            (self.lb["USUBJID"].str.endswith("-001")) &
            (self.lb["LBTESTCD"] == "CREAT")
        ]
        assert len(row) == 1
        val = float(row.iloc[0]["LBSTRESN"])
        assert abs(val - 97.24) < 0.1, f"CREAT SI for 001: expected ~97.24, got {val}"

    def test_si_conversion_hemoglobin_003(self):
        # DNA: 11.8 g/dL * 10 = 118.0
        row = self.lb[
            (self.lb["USUBJID"].str.endswith("-003")) &
            (self.lb["LBTESTCD"] == "HGB")
        ]
        assert len(row) == 1
        val = float(row.iloc[0]["LBSTRESN"])
        assert abs(val - 118.0) < 0.1, f"HGB SI for 003: expected ~118.0, got {val}"

    def test_si_conversion_alt_no_change(self):
        # DNA: ALT factor is 1.0, so value stays the same
        row = self.lb[
            (self.lb["USUBJID"].str.endswith("-001")) &
            (self.lb["LBTESTCD"] == "ALT")
        ]
        assert len(row) == 1
        val = float(row.iloc[0]["LBSTRESN"])
        assert abs(val - 42.0) < 0.1, f"ALT SI for 001: expected ~42.0, got {val}"

    def test_si_unit_glucose(self):
        gluc = self.lb[self.lb["LBTESTCD"] == "GLUC"]
        for v in gluc["LBSTRESU"]:
            assert v == "mmol/L", f"GLUC LBSTRESU should be mmol/L, got {v}"

    def test_si_unit_creatinine(self):
        creat = self.lb[self.lb["LBTESTCD"] == "CREAT"]
        for v in creat["LBSTRESU"]:
            assert v == "umol/L", f"CREAT LBSTRESU should be umol/L, got {v}"

    def test_si_unit_hemoglobin(self):
        hgb = self.lb[self.lb["LBTESTCD"] == "HGB"]
        for v in hgb["LBSTRESU"]:
            assert v == "g/L", f"HGB LBSTRESU should be g/L, got {v}"

    def test_reference_flag_glucose_001_high(self):
        # DNA: 126 mg/dL > 100 (normal_high) -> HIGH
        row = self.lb[
            (self.lb["USUBJID"].str.endswith("-001")) &
            (self.lb["LBTESTCD"] == "GLUC")
        ]
        assert row.iloc[0]["LBNRIND"] == "HIGH", \
            f"GLUC LBNRIND for 001: expected HIGH, got {row.iloc[0]['LBNRIND']}"

    def test_reference_flag_glucose_002_normal(self):
        # DNA: 92 mg/dL within 70-100 -> NORMAL
        row = self.lb[
            (self.lb["USUBJID"].str.endswith("-002")) &
            (self.lb["LBTESTCD"] == "GLUC")
        ]
        assert row.iloc[0]["LBNRIND"] == "NORMAL", \
            f"GLUC LBNRIND for 002: expected NORMAL, got {row.iloc[0]['LBNRIND']}"

    def test_reference_flag_creatinine_003_high(self):
        # DNA: 1.5 mg/dL > 1.3 (normal_high) -> HIGH
        row = self.lb[
            (self.lb["USUBJID"].str.endswith("-003")) &
            (self.lb["LBTESTCD"] == "CREAT")
        ]
        assert row.iloc[0]["LBNRIND"] == "HIGH", \
            f"CREAT LBNRIND for 003: expected HIGH, got {row.iloc[0]['LBNRIND']}"

    def test_reference_flag_hemoglobin_003_low(self):
        # DNA: 11.8 g/dL < 12.0 (normal_low) -> LOW
        row = self.lb[
            (self.lb["USUBJID"].str.endswith("-003")) &
            (self.lb["LBTESTCD"] == "HGB")
        ]
        assert row.iloc[0]["LBNRIND"] == "LOW", \
            f"HGB LBNRIND for 003: expected LOW, got {row.iloc[0]['LBNRIND']}"

    def test_reference_flag_alt_003_high(self):
        # DNA: 87 U/L > 56 (normal_high) -> HIGH
        row = self.lb[
            (self.lb["USUBJID"].str.endswith("-003")) &
            (self.lb["LBTESTCD"] == "ALT")
        ]
        assert row.iloc[0]["LBNRIND"] == "HIGH", \
            f"ALT LBNRIND for 003: expected HIGH, got {row.iloc[0]['LBNRIND']}"

    def test_specimen(self):
        for v in self.lb["LBSPEC"]:
            assert v == "BLOOD", f"LBSPEC should be BLOOD, got {v}"

    def test_baseline_flag(self):
        for _, row in self.lb.iterrows():
            assert str(row["LBBLFL"]).strip() == "Y", \
                f"LBBLFL should be 'Y' for all baseline labs"

    def test_lbdy_all_one(self):
        # All labs collected on enrollment day, so LBDY = 1
        for _, row in self.lb.iterrows():
            lbdy = int(float(row["LBDY"]))
            assert lbdy == 1, f"LBDY should be 1 for baseline labs, got {lbdy}"

    def test_lborres_preserved(self):
        # Original result values should be preserved
        row = self.lb[
            (self.lb["USUBJID"].str.endswith("-003")) &
            (self.lb["LBTESTCD"] == "GLUC")
        ]
        val = float(row.iloc[0]["LBORRES"])
        assert val == 187.0, \
            f"LBORRES for GLUC 003: expected 187, got {val}"


# ========== EX DOMAIN ==========

class TestEX:
    @pytest.fixture(autouse=True)
    def load_ex(self):
        self.ex = read_domain("ex.csv")

    def test_required_columns(self):
        required = ["STUDYID", "DOMAIN", "USUBJID", "EXSEQ", "EXTRT"]
        for col in required:
            assert col in self.ex.columns, f"EX missing column {col}"

    def test_expected_columns(self):
        expected = ["EXDOSE", "EXDOSU", "EXDOSFRQ", "EXSTDTC", "EXENDTC",
                     "EXSTDY", "EXENDY"]
        for col in expected:
            assert col in self.ex.columns, f"EX missing column {col}"

    def test_row_count(self):
        assert len(self.ex) == 15, f"EX should have 15 rows, got {len(self.ex)}"

    def test_domain(self):
        assert all(self.ex["DOMAIN"] == "EX")

    def test_dates_iso8601(self):
        for dtc in self.ex["EXSTDTC"]:
            assert ISO_DATE_PATTERN.match(str(dtc)), f"EXSTDTC '{dtc}' not ISO 8601"
        for dtc in self.ex["EXENDTC"]:
            assert ISO_DATE_PATTERN.match(str(dtc)), f"EXENDTC '{dtc}' not ISO 8601"

    def test_extrt_populated(self):
        for v in self.ex["EXTRT"]:
            assert str(v).strip() not in ("", "nan", "None"), "EXTRT must be populated"

    def test_dose_modification_subject_003(self):
        # DNA: Subject 003 has dose reduction: 960mg -> 720mg
        subj_003 = self.ex[self.ex["USUBJID"].str.endswith("-003")]
        assert len(subj_003) == 2, \
            f"Subject 003 should have 2 EX records (dose mod), got {len(subj_003)}"
        doses = sorted([int(float(d)) for d in subj_003["EXDOSE"]])
        assert doses == [720, 960], \
            f"Subject 003 doses should be [720, 960], got {doses}"

    def test_dose_interruption_subject_005(self):
        # DNA: Subject 005 has dose interruption: 2 separate periods
        subj_005 = self.ex[self.ex["USUBJID"].str.endswith("-005")]
        assert len(subj_005) == 2, \
            f"Subject 005 should have 2 EX records (interruption), got {len(subj_005)}"

    def test_combo_arm_two_treatments(self):
        # Subject 001 (COMBO arm) gets both Cobimetinib and Vemurafenib
        subj_001 = self.ex[self.ex["USUBJID"].str.endswith("-001")]
        assert len(subj_001) == 2, f"Subject 001 should have 2 EX records"
        trts = set(subj_001["EXTRT"])
        assert "Cobimetinib" in trts, "Subject 001 should have Cobimetinib"
        assert "Vemurafenib" in trts, "Subject 001 should have Vemurafenib"

    def test_vem_arm_one_treatment(self):
        # Subject 007 (VEM arm) gets only Vemurafenib
        subj_007 = self.ex[self.ex["USUBJID"].str.endswith("-007")]
        assert len(subj_007) == 1, f"Subject 007 should have 1 EX record"
        assert subj_007.iloc[0]["EXTRT"] == "Vemurafenib"

    def test_exstdy_first_dose_is_one(self):
        # For subjects with enrollment-day dosing, first EXSTDY = 1
        for uid in self.ex["USUBJID"].unique():
            subj = self.ex[self.ex["USUBJID"] == uid].sort_values("EXSEQ")
            first_exstdy = int(float(subj.iloc[0]["EXSTDY"]))
            assert first_exstdy == 1, \
                f"First EXSTDY for {uid}: expected 1, got {first_exstdy}"

    def test_exendy_003_seq1(self):
        # DNA: Subject 003, EX seq 1: end=02/14/2024, RFSTDTC=01/12/2024
        # diff=33, EXENDY=34
        subj_003 = self.ex[self.ex["USUBJID"].str.endswith("-003")].sort_values("EXSEQ")
        exendy = int(float(subj_003.iloc[0]["EXENDY"]))
        assert exendy == 34, f"EXENDY for 003 seq 1: expected 34, got {exendy}"

    def test_exstdy_003_seq2(self):
        # DNA: Subject 003, EX seq 2: start=02/15/2024, RFSTDTC=01/12/2024
        # diff=34, EXSTDY=35
        subj_003 = self.ex[self.ex["USUBJID"].str.endswith("-003")].sort_values("EXSEQ")
        exstdy = int(float(subj_003.iloc[1]["EXSTDY"]))
        assert exstdy == 35, f"EXSTDY for 003 seq 2: expected 35, got {exstdy}"

    def test_exstdy_005_seq2(self):
        # DNA: Subject 005, EX seq 2: start=02/28/2024, RFSTDTC=01/22/2024
        # diff=37, EXSTDY=38
        subj_005 = self.ex[self.ex["USUBJID"].str.endswith("-005")].sort_values("EXSEQ")
        exstdy = int(float(subj_005.iloc[1]["EXSTDY"]))
        assert exstdy == 38, f"EXSTDY for 005 seq 2: expected 38, got {exstdy}"

    def test_exendy_001_cross_year(self):
        # DNA: Subject 001: RFSTDTC=12/18/2023, end=04/18/2024
        # diff=122, EXENDY=123
        subj_001 = self.ex[self.ex["USUBJID"].str.endswith("-001")]
        exendys = [int(float(r["EXENDY"])) for _, r in subj_001.iterrows()]
        assert 123 in exendys, \
            f"EXENDY for 001 should include 123, got {exendys}"


# ========== DS DOMAIN ==========

class TestDS:
    @pytest.fixture(autouse=True)
    def load_ds(self):
        self.ds = read_domain("ds.csv")

    def test_required_columns(self):
        required = ["STUDYID", "DOMAIN", "USUBJID", "DSSEQ",
                     "DSTERM", "DSDECOD"]
        for col in required:
            assert col in self.ds.columns, f"DS missing column {col}"

    def test_expected_columns(self):
        expected = ["DSCAT", "DSSTDTC", "DSDY"]
        for col in expected:
            assert col in self.ds.columns, f"DS missing column {col}"

    def test_row_count(self):
        assert len(self.ds) == 8, f"DS should have 8 rows, got {len(self.ds)}"

    def test_domain(self):
        assert all(self.ds["DOMAIN"] == "DS")

    def test_dsdecod_uppercase(self):
        for v in self.ds["DSDECOD"]:
            assert v == v.upper(), f"DSDECOD '{v}' should be uppercase"

    def test_dsdecod_values(self):
        vals = set(self.ds["DSDECOD"])
        assert "COMPLETED" in vals, "DSDECOD should contain COMPLETED"
        assert "DISCONTINUED" in vals, "DSDECOD should contain DISCONTINUED"

    def test_dscat(self):
        assert all(self.ds["DSCAT"] == "DISPOSITION EVENT")

    def test_dates_iso8601(self):
        for dtc in self.ds["DSSTDTC"]:
            assert ISO_DATE_PATTERN.match(str(dtc)), f"DSSTDTC '{dtc}' not ISO 8601"

    def test_study_day_001_cross_year(self):
        # DNA: Subject 201-001: RFSTDTC=12/18/2023, DS=04/18/2024
        # diff=122, DSDY=123
        subj_001 = self.ds[self.ds["USUBJID"].str.endswith("-001")]
        assert len(subj_001) >= 1
        dsdy = int(float(subj_001.iloc[0]["DSDY"]))
        assert dsdy == 123, f"DSDY for 001: expected 123, got {dsdy}"

    def test_study_day_003(self):
        # DNA: Subject 202-003: RFSTDTC=01/12/2024, DS=04/12/2024
        # diff=91, DSDY=92
        subj_003 = self.ds[self.ds["USUBJID"].str.endswith("-003")]
        assert len(subj_003) >= 1
        dsdy = int(float(subj_003.iloc[0]["DSDY"]))
        assert dsdy == 92, f"DSDY for 003: expected 92, got {dsdy}"

    def test_study_day_007(self):
        # DNA: Subject 204-007: RFSTDTC=02/08/2024, DS=04/08/2024
        # diff=60, DSDY=61
        subj_007 = self.ds[self.ds["USUBJID"].str.endswith("-007")]
        assert len(subj_007) >= 1
        dsdy = int(float(subj_007.iloc[0]["DSDY"]))
        assert dsdy == 61, f"DSDY for 007: expected 61, got {dsdy}"


# ========== TS DOMAIN ==========

class TestTS:
    @pytest.fixture(autouse=True)
    def load_ts(self):
        self.ts = read_domain("ts.csv")

    def test_required_columns(self):
        required = ["STUDYID", "DOMAIN", "TSSEQ", "TSPARMCD", "TSPARM", "TSVAL"]
        for col in required:
            assert col in self.ts.columns, f"TS missing column {col}"

    def test_domain(self):
        assert all(self.ts["DOMAIN"] == "TS")

    def test_studyid(self):
        assert all(self.ts["STUDYID"] == STUDYID)

    def test_minimum_row_count(self):
        assert len(self.ts) >= 6, f"TS should have >= 6 rows, got {len(self.ts)}"

    def test_required_parameters(self):
        parmcds = set(self.ts["TSPARMCD"])
        required_params = {"SSTDTC", "SENDTC", "TITLE", "SPONSOR", "INDIC", "PHASE"}
        for p in required_params:
            assert p in parmcds, f"TS missing required parameter {p}"

    def test_sstdtc_value(self):
        # DNA: study start = 12/01/2023 -> 2023-12-01
        row = self.ts[self.ts["TSPARMCD"] == "SSTDTC"]
        assert len(row) >= 1
        assert row.iloc[0]["TSVAL"] == "2023-12-01"

    def test_sendtc_value(self):
        row = self.ts[self.ts["TSPARMCD"] == "SENDTC"]
        assert len(row) >= 1
        assert row.iloc[0]["TSVAL"] == "2024-06-30"

    def test_sponsor_value(self):
        row = self.ts[self.ts["TSPARMCD"] == "SPONSOR"]
        assert len(row) >= 1
        assert "Rare Therapeutics" in row.iloc[0]["TSVAL"]

    def test_indication_value(self):
        row = self.ts[self.ts["TSPARMCD"] == "INDIC"]
        assert len(row) >= 1
        assert "Erdheim" in row.iloc[0]["TSVAL"]

    def test_tsseq_unique(self):
        assert self.ts["TSSEQ"].is_unique, "TSSEQ must be unique within TS"


# ========== SUPPAE DOMAIN ==========

class TestSUPPAE:
    @pytest.fixture(autouse=True)
    def load_suppae(self):
        self.suppae = read_domain("suppae.csv")

    def test_required_columns(self):
        required = ["STUDYID", "RDOMAIN", "USUBJID", "IDVAR",
                     "IDVARVAL", "QNAM", "QLABEL", "QVAL", "QORIG"]
        for col in required:
            assert col in self.suppae.columns, f"SUPPAE missing column {col}"

    def test_row_count(self):
        # 4 AE records have body_location: rash(TRUNK), photo(FACE AND ARMS),
        # sqcc(LEFT FOREARM), hfs(HANDS AND FEET)
        assert len(self.suppae) == 4, \
            f"SUPPAE should have 4 rows, got {len(self.suppae)}"

    def test_rdomain(self):
        assert all(self.suppae["RDOMAIN"] == "AE")

    def test_idvar(self):
        assert all(self.suppae["IDVAR"] == "AESEQ")

    def test_qnam(self):
        assert all(self.suppae["QNAM"] == "AELOC")

    def test_qlabel(self):
        for v in self.suppae["QLABEL"]:
            assert "location" in v.lower()

    def test_qorig(self):
        assert all(self.suppae["QORIG"] == "CRF")

    def test_qval_values(self):
        vals = set(self.suppae["QVAL"])
        assert "TRUNK" in vals, "SUPPAE should contain TRUNK"
        assert "HANDS AND FEET" in vals, "SUPPAE should contain HANDS AND FEET"
        assert "LEFT FOREARM" in vals, "SUPPAE should contain LEFT FOREARM"
        assert "FACE AND ARMS" in vals, "SUPPAE should contain FACE AND ARMS"


# ========== CROSS-DOMAIN ==========

class TestCrossDomain:
    @pytest.fixture(autouse=True)
    def load_all(self):
        self.dm = read_domain("dm.csv")
        self.ae = read_domain("ae.csv")
        self.vs = read_domain("vs.csv")
        self.lb = read_domain("lb.csv")
        self.ex = read_domain("ex.csv")
        self.ds = read_domain("ds.csv")

    def test_usubjid_consistency(self):
        dm_ids = set(self.dm["USUBJID"])
        for domain_name, df in [("AE", self.ae), ("VS", self.vs),
                                 ("LB", self.lb), ("EX", self.ex),
                                 ("DS", self.ds)]:
            domain_ids = set(df["USUBJID"])
            missing = domain_ids - dm_ids
            assert len(missing) == 0, \
                f"{domain_name} has USUBJIDs not in DM: {missing}"

    def test_studyid_consistency(self):
        for domain_name, df in [("AE", self.ae), ("VS", self.vs),
                                 ("LB", self.lb), ("EX", self.ex),
                                 ("DS", self.ds)]:
            assert all(df["STUDYID"] == STUDYID), \
                f"STUDYID mismatch in {domain_name}"

    def test_all_dm_subjects_in_ds(self):
        dm_ids = set(self.dm["USUBJID"])
        ds_ids = set(self.ds["USUBJID"])
        assert dm_ids == ds_ids, "All DM subjects should appear in DS"

    def test_all_dm_subjects_in_ex(self):
        dm_ids = set(self.dm["USUBJID"])
        ex_ids = set(self.ex["USUBJID"])
        assert dm_ids == ex_ids, "All DM subjects should appear in EX"

    def test_dm_subject_count(self):
        assert len(self.dm["USUBJID"].unique()) == 8, "Should have 8 unique subjects"
