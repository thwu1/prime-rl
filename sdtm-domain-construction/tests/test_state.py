#!/usr/bin/env python3
"""Tests for SDTM domain conformance in XPT format with Define-XML validation."""

import math
import os
import pytest
import pandas as pd
import pyreadstat
from lxml import etree

OUTPUT_DIR = "/app/sdtm_output"


def read_xpt(filename):
    """Read XPT file and return DataFrame and metadata."""
    filepath = os.path.join(OUTPUT_DIR, filename)
    assert os.path.exists(filepath), f"XPT file {filename} not found at {filepath}"
    df, meta = pyreadstat.read_xport(filepath)
    return df, meta


def is_missing(val):
    """Check if a value is missing (NaN, None, or empty string)."""
    if val is None:
        return True
    if isinstance(val, float) and math.isnan(val):
        return True
    if isinstance(val, str) and val.strip() == "":
        return True
    return False


def str_val(val):
    """Convert value to string, handling NaN."""
    if is_missing(val):
        return ""
    return str(val).strip()


# ===== XPT Metadata Tests =====


class TestXPTMetadata:
    def test_all_xpt_files_exist(self):
        expected = ["dm.xpt", "ae.xpt", "ex.xpt", "vs.xpt", "ds.xpt", "ts.xpt", "suppae.xpt"]
        for f in expected:
            assert os.path.exists(os.path.join(OUTPUT_DIR, f)), f"Missing XPT file: {f}"

    def test_variable_name_length(self):
        """All variable names must be <=8 characters per SAS Transport v5."""
        for filename in ["dm.xpt", "ae.xpt", "vs.xpt", "ex.xpt", "ds.xpt"]:
            df, meta = read_xpt(filename)
            for col in df.columns:
                assert len(col) <= 8, \
                    f"Variable name too long in {filename}: {col} ({len(col)} chars)"

    def test_variable_label_length(self):
        """All variable labels must be <=40 characters per SAS Transport v5."""
        for filename in ["dm.xpt", "ae.xpt", "vs.xpt"]:
            df, meta = read_xpt(filename)
            if hasattr(meta, "column_labels") and meta.column_labels:
                labels = meta.column_labels
                names = meta.column_names if hasattr(meta, "column_names") else list(df.columns)
                if isinstance(labels, list):
                    label_pairs = zip(names, labels)
                else:
                    label_pairs = labels.items()
                for col, label in label_pairs:
                    if label:
                        assert len(label) <= 40, \
                            f"Label too long in {filename}: {col}='{label}' ({len(label)} chars)"

    def test_dm_numeric_types(self):
        """AGE must be numeric in DM."""
        df, _ = read_xpt("dm.xpt")
        assert pd.api.types.is_numeric_dtype(df["AGE"]), "AGE must be numeric"

    def test_ae_numeric_types(self):
        """AESEQ and AESTDY must be numeric in AE."""
        df, _ = read_xpt("ae.xpt")
        assert pd.api.types.is_numeric_dtype(df["AESEQ"]), "AESEQ must be numeric"
        assert pd.api.types.is_numeric_dtype(df["AESTDY"]), "AESTDY must be numeric"

    def test_vs_numeric_types(self):
        """VSSEQ, VSSTRESN, VISITNUM, VSDY must be numeric in VS."""
        df, _ = read_xpt("vs.xpt")
        for col in ["VSSEQ", "VSSTRESN", "VISITNUM", "VSDY"]:
            assert pd.api.types.is_numeric_dtype(df[col]), f"{col} must be numeric"

    def test_ex_numeric_types(self):
        """EXSEQ and EXDOSE must be numeric in EX."""
        df, _ = read_xpt("ex.xpt")
        assert pd.api.types.is_numeric_dtype(df["EXSEQ"]), "EXSEQ must be numeric"
        assert pd.api.types.is_numeric_dtype(df["EXDOSE"]), "EXDOSE must be numeric"


# ===== DM Domain Tests =====


class TestDM:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.df, self.meta = read_xpt("dm.xpt")

    def test_record_count(self):
        assert len(self.df) == 5, f"DM should have 5 records, got {len(self.df)}"

    def test_required_columns(self):
        required = {
            "STUDYID", "DOMAIN", "USUBJID", "SUBJID", "RFSTDTC", "SITEID",
            "AGE", "AGEU", "SEX", "RACE", "ETHNIC", "ARMCD", "ARM",
        }
        actual = set(self.df.columns)
        for col in required:
            assert col in actual, f"DM missing required column: {col}"

    def test_domain_value(self):
        for val in self.df["DOMAIN"]:
            assert str_val(val) == "DM"

    def test_studyid(self):
        for val in self.df["STUDYID"]:
            assert str_val(val) == "XYZ-2024-001"

    def test_usubjid_format(self):
        for val in self.df["USUBJID"]:
            assert str_val(val).startswith("XYZ-2024-001-"), \
                f"USUBJID should start with STUDYID-, got {val}"

    def test_sex_mapping(self):
        """SEX must be single-character M/F, not Male/Female."""
        sex = dict(zip(self.df["SUBJID"].values, self.df["SEX"].values))
        assert str_val(sex["001"]) == "M"
        assert str_val(sex["002"]) == "F"
        assert str_val(sex["003"]) == "M"
        assert str_val(sex["004"]) == "F"
        assert str_val(sex["005"]) == "M"

    def test_age_calculation(self):
        """AGE must be calculated correctly at reference date."""
        ages = dict(zip(self.df["SUBJID"].values, self.df["AGE"].values))
        assert int(ages["001"]) == 65
        assert int(ages["002"]) == 51
        assert int(ages["003"]) == 58
        assert int(ages["004"]) == 43
        assert int(ages["005"]) == 34

    def test_death_flag(self):
        """DTHFL must be Y for deceased subject 002, blank for others."""
        dthfl = dict(zip(self.df["SUBJID"].values, self.df["DTHFL"].values))
        assert str_val(dthfl["002"]) == "Y"
        assert is_missing(dthfl["001"]) or str_val(dthfl["001"]) == ""
        assert is_missing(dthfl["003"]) or str_val(dthfl["003"]) == ""
        assert is_missing(dthfl["005"]) or str_val(dthfl["005"]) == ""

    def test_screen_failure_arm(self):
        """Screen failure (subject 004) must have ARMCD=SCRNFAIL."""
        subj004 = self.df[self.df["SUBJID"] == "004"].iloc[0]
        assert str_val(subj004["ARMCD"]) == "SCRNFAIL"
        assert "SCREEN FAILURE" in str_val(subj004["ARM"]).upper()

    def test_rfstdtc_values(self):
        """RFSTDTC = first dose date, empty for screen failures."""
        rfst = dict(zip(self.df["SUBJID"].values, self.df["RFSTDTC"].values))
        assert str_val(rfst["001"]) == "2024-01-15"
        assert str_val(rfst["002"]) == "2024-01-17"
        assert str_val(rfst["003"]) == "2024-01-20"
        assert is_missing(rfst["004"]) or str_val(rfst["004"]) == "", \
            "Screen failure should have empty RFSTDTC"
        assert str_val(rfst["005"]) == "2024-01-25"

    def test_ageu(self):
        for val in self.df["AGEU"]:
            assert str_val(val) == "YEARS"


# ===== AE Domain Tests =====


class TestAE:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.df, self.meta = read_xpt("ae.xpt")

    def test_record_count(self):
        assert len(self.df) == 9, f"AE should have 9 records, got {len(self.df)}"

    def test_required_columns(self):
        required = {
            "STUDYID", "DOMAIN", "USUBJID", "AESEQ", "AETERM",
            "AESEV", "AESER", "AESTDTC", "EPOCH",
        }
        actual = set(self.df.columns)
        for col in required:
            assert col in actual, f"AE missing required column: {col}"

    def test_domain_value(self):
        for val in self.df["DOMAIN"]:
            assert str_val(val) == "AE"

    def test_severity_mapping_valid_values(self):
        """Numeric severity grades must be mapped to CDISC CT."""
        valid = {"MILD", "MODERATE", "SEVERE"}
        for val in self.df["AESEV"]:
            assert str_val(val) in valid, \
                f"Invalid AESEV '{val}'. Must be MILD/MODERATE/SEVERE."

    def test_severity_specific_values(self):
        """Verify specific severity mappings."""
        subj001 = self.df[self.df["USUBJID"].str.endswith("-001")].sort_values("AESEQ")
        assert str_val(subj001.iloc[0]["AESEV"]) == "MILD"
        assert str_val(subj001.iloc[1]["AESEV"]) == "MODERATE"

        subj002 = self.df[self.df["USUBJID"].str.endswith("-002")].sort_values("AESEQ")
        assert str_val(subj002.iloc[1]["AESEV"]) == "SEVERE"

    def test_serious_flag_mapping(self):
        """AESER must be Y or N, not Yes/No."""
        for val in self.df["AESER"]:
            assert str_val(val) in ("Y", "N"), \
                f"AESER must be Y/N, got '{val}'"

    def test_serious_specific_values(self):
        subj002 = self.df[self.df["USUBJID"].str.endswith("-002")].sort_values("AESEQ")
        assert str_val(subj002.iloc[0]["AESER"]) == "N"
        assert str_val(subj002.iloc[1]["AESER"]) == "Y"

    def test_study_day_subj001(self):
        """Study day for subject 001: RFSTDTC=2024-01-15."""
        subj001 = self.df[self.df["USUBJID"].str.endswith("-001")].sort_values("AESEQ")
        assert int(subj001.iloc[0]["AESTDY"]) == 1
        assert int(subj001.iloc[1]["AESTDY"]) == 6

    def test_study_day_subj002(self):
        """Study day for subject 002: RFSTDTC=2024-01-17."""
        subj002 = self.df[self.df["USUBJID"].str.endswith("-002")].sort_values("AESEQ")
        assert int(subj002.iloc[0]["AESTDY"]) == 20
        assert int(subj002.iloc[1]["AESTDY"]) == 35

    def test_partial_date_representation(self):
        """Partial dates should be truncated ISO 8601 (YYYY-MM)."""
        subj003 = self.df[self.df["USUBJID"].str.endswith("-003")].sort_values("AESEQ")
        insomnia = subj003.iloc[1]
        assert str_val(insomnia["AESTDTC"]) == "2024-02"

        subj005 = self.df[self.df["USUBJID"].str.endswith("-005")].sort_values("AESEQ")
        vomiting = subj005.iloc[1]
        assert str_val(vomiting["AESTDTC"]) == "2024-03"

    def test_partial_date_study_day_empty(self):
        """Study day should be NaN for records with partial dates."""
        subj003 = self.df[self.df["USUBJID"].str.endswith("-003")].sort_values("AESEQ")
        insomnia_dy = subj003.iloc[1]["AESTDY"]
        assert pd.isna(insomnia_dy), f"Partial date AESTDY should be NaN, got {insomnia_dy}"

        subj005 = self.df[self.df["USUBJID"].str.endswith("-005")].sort_values("AESEQ")
        vomiting_dy = subj005.iloc[1]["AESTDY"]
        assert pd.isna(vomiting_dy), f"Partial date AESTDY should be NaN, got {vomiting_dy}"

    def test_epoch_treatment(self):
        """AEs occurring after first dose should have EPOCH=TREATMENT."""
        subj001 = self.df[self.df["USUBJID"].str.endswith("-001")].sort_values("AESEQ")
        assert str_val(subj001.iloc[0]["EPOCH"]) == "TREATMENT"

        subj002 = self.df[self.df["USUBJID"].str.endswith("-002")].sort_values("AESEQ")
        assert str_val(subj002.iloc[0]["EPOCH"]) == "TREATMENT"

    def test_epoch_partial_date(self):
        """EPOCH for partial dates should be derived from month-year comparison."""
        subj003 = self.df[self.df["USUBJID"].str.endswith("-003")].sort_values("AESEQ")
        assert str_val(subj003.iloc[1]["EPOCH"]) == "TREATMENT"

    def test_seq_unique_per_subject(self):
        """AESEQ must be unique per USUBJID."""
        for usubjid in self.df["USUBJID"].unique():
            subj = self.df[self.df["USUBJID"] == usubjid]
            seqs = subj["AESEQ"].tolist()
            assert len(seqs) == len(set(seqs)), \
                f"Duplicate AESEQ for {usubjid}: {seqs}"


# ===== VS Domain Tests =====


class TestVS:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.df, self.meta = read_xpt("vs.xpt")

    def test_record_count(self):
        assert len(self.df) == 38, f"VS should have 38 records, got {len(self.df)}"

    def test_required_columns(self):
        required = {
            "STUDYID", "DOMAIN", "USUBJID", "VSSEQ", "VSTESTCD",
            "VSTEST", "VSORRES", "VSORRESU", "VSSTRESN", "VSSTRESU",
            "VSDTC", "EPOCH",
        }
        actual = set(self.df.columns)
        for col in required:
            assert col in actual, f"VS missing required column: {col}"

    def test_domain_value(self):
        for val in self.df["DOMAIN"]:
            assert str_val(val) == "VS"

    def test_testcd_values(self):
        """VSTESTCD must use CDISC controlled terminology codes."""
        valid = {"SYSBP", "DIABP", "HR", "TEMP", "WEIGHT", "HEIGHT"}
        for val in self.df["VSTESTCD"]:
            assert str_val(val) in valid, f"Invalid VSTESTCD: {val}"

    def test_baseline_flag_set(self):
        """VSBLFL should be Y for Baseline records."""
        baseline = self.df[self.df["VISIT"] == "Baseline"]
        assert len(baseline) > 0, "No Baseline visit records found"
        for _, row in baseline.iterrows():
            assert str_val(row["VSBLFL"]) == "Y", \
                f"Missing baseline flag for {row['USUBJID']} {row['VSTESTCD']}"

    def test_baseline_flag_not_set_elsewhere(self):
        """VSBLFL should not be Y for non-Baseline records."""
        non_baseline = self.df[self.df["VISIT"] != "Baseline"]
        for _, row in non_baseline.iterrows():
            val = row.get("VSBLFL", "")
            assert is_missing(val) or str_val(val) == "", \
                f"Unexpected VSBLFL for {row['USUBJID']} {row['VSTESTCD']} at {row['VISIT']}"

    def test_unit_conversion_temp_screening(self):
        """Subject 005 Screening temperature: 98.1F -> 36.7C."""
        rows = self.df[
            (self.df["USUBJID"].str.endswith("-005")) &
            (self.df["VISIT"] == "Screening") &
            (self.df["VSTESTCD"] == "TEMP")
        ]
        assert len(rows) == 1
        row = rows.iloc[0]
        assert str_val(row["VSORRESU"]) == "F"
        assert str_val(row["VSSTRESU"]) == "C"
        assert row["VSSTRESN"] == pytest.approx(36.7, abs=0.05)

    def test_unit_conversion_temp_baseline(self):
        """Subject 005 Baseline temperature: 97.7F -> 36.5C."""
        rows = self.df[
            (self.df["USUBJID"].str.endswith("-005")) &
            (self.df["VISIT"] == "Baseline") &
            (self.df["VSTESTCD"] == "TEMP")
        ]
        assert len(rows) == 1
        assert rows.iloc[0]["VSSTRESN"] == pytest.approx(36.5, abs=0.05)

    def test_unit_conversion_weight(self):
        """Subject 005 Screening weight: 170.0 lbs -> 77.1 kg."""
        rows = self.df[
            (self.df["USUBJID"].str.endswith("-005")) &
            (self.df["VISIT"] == "Screening") &
            (self.df["VSTESTCD"] == "WEIGHT")
        ]
        assert len(rows) == 1
        row = rows.iloc[0]
        assert str_val(row["VSORRESU"]) == "lbs"
        assert str_val(row["VSSTRESU"]) == "kg"
        assert row["VSSTRESN"] == pytest.approx(77.1, abs=0.05)

    def test_unit_conversion_height(self):
        """Subject 005 Screening height: 68.5 in -> 174.0 cm."""
        rows = self.df[
            (self.df["USUBJID"].str.endswith("-005")) &
            (self.df["VISIT"] == "Screening") &
            (self.df["VSTESTCD"] == "HEIGHT")
        ]
        assert len(rows) == 1
        row = rows.iloc[0]
        assert str_val(row["VSORRESU"]) == "in"
        assert str_val(row["VSSTRESU"]) == "cm"
        assert row["VSSTRESN"] == pytest.approx(174.0, abs=0.05)

    def test_no_conversion_metric(self):
        """Subject 001 should have same values in original and standard (already metric)."""
        rows = self.df[
            (self.df["USUBJID"].str.endswith("-001")) &
            (self.df["VISIT"] == "Screening") &
            (self.df["VSTESTCD"] == "TEMP")
        ]
        row = rows.iloc[0]
        assert row["VSSTRESN"] == pytest.approx(36.5, abs=0.05)
        assert str_val(row["VSORRESU"]) == "C"
        assert str_val(row["VSSTRESU"]) == "C"

    def test_epoch_screening(self):
        """Screening visits should have EPOCH=SCREENING."""
        subj001_screen = self.df[
            (self.df["USUBJID"].str.endswith("-001")) &
            (self.df["VISIT"] == "Screening")
        ]
        for _, row in subj001_screen.iterrows():
            assert str_val(row["EPOCH"]) == "SCREENING"

    def test_epoch_treatment(self):
        """Baseline visits (on RFSTDTC) should have EPOCH=TREATMENT."""
        subj001_base = self.df[
            (self.df["USUBJID"].str.endswith("-001")) &
            (self.df["VISIT"] == "Baseline")
        ]
        for _, row in subj001_base.iterrows():
            assert str_val(row["EPOCH"]) == "TREATMENT"

    def test_study_day_screening_before_rfstdtc(self):
        """Subject 001 Screening VSDY should be -5."""
        subj001_screen = self.df[
            (self.df["USUBJID"].str.endswith("-001")) &
            (self.df["VISIT"] == "Screening")
        ]
        assert len(subj001_screen) > 0
        assert int(subj001_screen.iloc[0]["VSDY"]) == -5

    def test_study_day_baseline_day1(self):
        """Subject 001 Baseline VSDY should be 1."""
        subj001_base = self.df[
            (self.df["USUBJID"].str.endswith("-001")) &
            (self.df["VISIT"] == "Baseline")
        ]
        assert len(subj001_base) > 0
        assert int(subj001_base.iloc[0]["VSDY"]) == 1

    def test_visitnum_populated(self):
        """VISITNUM should be a valid number for all records."""
        for _, row in self.df.iterrows():
            assert not pd.isna(row["VISITNUM"]), \
                f"VISITNUM empty for {row['USUBJID']} {row['VSTESTCD']}"


# ===== EX Domain Tests =====


class TestEX:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.df, self.meta = read_xpt("ex.xpt")

    def test_record_count(self):
        assert len(self.df) == 6, f"EX should have 6 records, got {len(self.df)}"

    def test_required_columns(self):
        required = {
            "STUDYID", "DOMAIN", "USUBJID", "EXSEQ", "EXTRT",
            "EXDOSE", "EXSTDTC", "EPOCH",
        }
        actual = set(self.df.columns)
        for col in required:
            assert col in actual, f"EX missing required column: {col}"

    def test_domain_value(self):
        for val in self.df["DOMAIN"]:
            assert str_val(val) == "EX"

    def test_first_dose_study_day_is_one(self):
        """First dose for each subject should have EXSTDY=1."""
        for _, row in self.df.iterrows():
            if int(row["EXSEQ"]) == 1:
                assert int(row["EXSTDY"]) == 1, \
                    f"First dose EXSTDY should be 1, got {row['EXSTDY']} for {row['USUBJID']}"

    def test_dose_reduction_subject_002(self):
        """Subject 002 should have dose reduction from 50 to 25."""
        subj002 = self.df[self.df["USUBJID"].str.endswith("-002")].sort_values("EXSEQ")
        assert len(subj002) == 2
        assert subj002.iloc[0]["EXDOSE"] == pytest.approx(50.0)
        assert subj002.iloc[1]["EXDOSE"] == pytest.approx(25.0)

    def test_dose_reduction_subject_005(self):
        """Subject 005 should have dose reduction from 50 to 25."""
        subj005 = self.df[self.df["USUBJID"].str.endswith("-005")].sort_values("EXSEQ")
        assert len(subj005) == 2
        assert subj005.iloc[0]["EXDOSE"] == pytest.approx(50.0)
        assert subj005.iloc[1]["EXDOSE"] == pytest.approx(25.0)

    def test_epoch_all_treatment(self):
        """All exposure records should have EPOCH=TREATMENT."""
        for _, row in self.df.iterrows():
            assert str_val(row["EPOCH"]) == "TREATMENT"


# ===== DS Domain Tests =====


class TestDS:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.df, self.meta = read_xpt("ds.xpt")

    def test_record_count(self):
        assert len(self.df) == 14, f"DS should have 14 records, got {len(self.df)}"

    def test_required_columns(self):
        required = {"STUDYID", "DOMAIN", "USUBJID", "DSSEQ", "DSDECOD", "DSSTDTC", "EPOCH"}
        actual = set(self.df.columns)
        for col in required:
            assert col in actual, f"DS missing required column: {col}"

    def test_domain_value(self):
        for val in self.df["DOMAIN"]:
            assert str_val(val) == "DS"

    def test_disposition_events_present(self):
        """Key disposition events must exist."""
        decods = set(str_val(v) for v in self.df["DSDECOD"])
        assert "COMPLETED" in decods
        assert "DEATH" in decods
        assert "SCREEN FAILURE" in decods
        assert "INFORMED CONSENT OBTAINED" in decods
        assert "RANDOMIZED" in decods

    def test_dscat_values(self):
        """DSCAT should distinguish protocol milestones from disposition events."""
        if "DSCAT" not in self.df.columns:
            pytest.skip("DSCAT not present")
        consent = self.df[self.df["DSDECOD"] == "INFORMED CONSENT OBTAINED"]
        for _, row in consent.iterrows():
            assert str_val(row["DSCAT"]) == "PROTOCOL MILESTONE"
        completed = self.df[self.df["DSDECOD"] == "COMPLETED"]
        for _, row in completed.iterrows():
            assert str_val(row["DSCAT"]) == "DISPOSITION EVENT"

    def test_epoch_consent_screening(self):
        """INFORMED CONSENT events should have EPOCH=SCREENING."""
        consent = self.df[self.df["DSDECOD"] == "INFORMED CONSENT OBTAINED"]
        for _, row in consent.iterrows():
            assert str_val(row["EPOCH"]) == "SCREENING"

    def test_epoch_completed_followup(self):
        """COMPLETED events should have EPOCH=FOLLOW-UP (after last dose)."""
        completed = self.df[self.df["DSDECOD"] == "COMPLETED"]
        for _, row in completed.iterrows():
            assert str_val(row["EPOCH"]) == "FOLLOW-UP"

    def test_epoch_screen_failure(self):
        """Screen failure subject (004) should have EPOCH=SCREENING for all events."""
        subj004 = self.df[self.df["USUBJID"].str.endswith("-004")]
        for _, row in subj004.iterrows():
            assert str_val(row["EPOCH"]) == "SCREENING"

    def test_screen_failure_no_study_day(self):
        """Screen failure subject (004) should have empty study day."""
        subj004 = self.df[self.df["USUBJID"].str.endswith("-004")]
        if "DSSTDY" in self.df.columns:
            for _, row in subj004.iterrows():
                assert pd.isna(row["DSSTDY"]), \
                    f"Screen failure should have NaN DSSTDY, got {row['DSSTDY']}"


# ===== TS Domain Tests =====


class TestTS:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.df, self.meta = read_xpt("ts.xpt")

    def test_required_columns(self):
        required = {"STUDYID", "DOMAIN", "TSSEQ", "TSPARMCD", "TSPARM", "TSVAL"}
        actual = set(self.df.columns)
        for col in required:
            assert col in actual, f"TS missing required column: {col}"

    def test_domain_value(self):
        for val in self.df["DOMAIN"]:
            assert str_val(val) == "TS"

    def test_required_parameters(self):
        """TS must contain key trial summary parameters."""
        parmcds = set(str_val(v) for v in self.df["TSPARMCD"])
        for p in ["SSTDTC", "SENDTC", "INDIC", "TRT", "STYPE", "TPHASE", "RANDOM"]:
            assert p in parmcds, f"Missing required TS parameter: {p}"

    def test_parameter_values(self):
        """Check specific TS parameter values."""
        parm_vals = dict(zip(
            [str_val(v) for v in self.df["TSPARMCD"]],
            [str_val(v) for v in self.df["TSVAL"]],
        ))
        assert parm_vals["STYPE"] == "INTERVENTIONAL"
        assert "PHASE II" in parm_vals["TPHASE"].upper()
        assert parm_vals["RANDOM"] == "Y"

    def test_seq_unique(self):
        """TSSEQ must be unique."""
        seqs = self.df["TSSEQ"].tolist()
        assert len(seqs) == len(set(seqs)), f"Duplicate TSSEQ values"


# ===== SUPPAE Domain Tests =====


class TestSUPPAE:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.df, self.meta = read_xpt("suppae.xpt")

    def test_record_count(self):
        assert len(self.df) == 2, f"SUPPAE should have 2 records, got {len(self.df)}"

    def test_required_columns(self):
        required = {
            "STUDYID", "RDOMAIN", "USUBJID", "IDVAR", "IDVARVAL",
            "QNAM", "QLABEL", "QVAL",
        }
        actual = set(self.df.columns)
        for col in required:
            assert col in actual, f"SUPPAE missing required column: {col}"

    def test_rdomain_value(self):
        for val in self.df["RDOMAIN"]:
            assert str_val(val) == "AE"

    def test_idvar_value(self):
        for val in self.df["IDVAR"]:
            assert str_val(val) == "AESEQ"

    def test_qnam_value(self):
        for val in self.df["QNAM"]:
            assert str_val(val) == "AELOC"

    def test_reaction_locations(self):
        """Check specific reaction location values."""
        locs = set(str_val(v) for v in self.df["QVAL"])
        assert "LEFT ARM" in locs, "Missing LEFT ARM in SUPPAE"
        assert "RIGHT KNEE" in locs, "Missing RIGHT KNEE in SUPPAE"

    def test_correct_subject_mapping(self):
        """SUPPAE records should map to correct subjects."""
        subj_map = dict(zip(
            [str_val(v) for v in self.df["QVAL"]],
            [str_val(v) for v in self.df["USUBJID"]],
        ))
        assert subj_map["LEFT ARM"].endswith("-002"), \
            f"LEFT ARM should be for subject 002, got {subj_map['LEFT ARM']}"
        assert subj_map["RIGHT KNEE"].endswith("-003"), \
            f"RIGHT KNEE should be for subject 003, got {subj_map['RIGHT KNEE']}"


# ===== Define-XML Tests =====


class TestDefineXML:
    ODM_NS = "http://www.cdisc.org/ns/odm/v1.3"
    DEF_NS = "http://www.cdisc.org/ns/def/v2.0"
    NSMAP = {"odm": ODM_NS, "def": DEF_NS}

    @pytest.fixture(autouse=True)
    def setup(self):
        filepath = os.path.join(OUTPUT_DIR, "define.xml")
        assert os.path.exists(filepath), "define.xml not found"
        self.tree = etree.parse(filepath)
        self.root = self.tree.getroot()

    def test_root_element_odm(self):
        """Root must be ODM with correct namespace."""
        assert self.root.tag == f"{{{self.ODM_NS}}}ODM"

    def test_study_element_exists(self):
        """Study element must exist."""
        studies = self.root.findall("odm:Study", self.NSMAP)
        assert len(studies) >= 1, "No Study element found"

    def test_metadata_version_sdtmig(self):
        """MetaDataVersion must reference SDTMIG 3.3."""
        mdv = self.root.findall(".//odm:MetaDataVersion", self.NSMAP)
        assert len(mdv) >= 1, "No MetaDataVersion element found"
        mdv_elem = mdv[0]
        std_name = mdv_elem.get(f"{{{self.DEF_NS}}}StandardName")
        std_ver = mdv_elem.get(f"{{{self.DEF_NS}}}StandardVersion")
        assert std_name == "SDTMIG", f"StandardName should be SDTMIG, got {std_name}"
        assert std_ver == "3.3", f"StandardVersion should be 3.3, got {std_ver}"

    def test_itemgroupdef_for_each_domain(self):
        """ItemGroupDef must exist for each SDTM domain."""
        igds = self.root.findall(".//odm:ItemGroupDef", self.NSMAP)
        dataset_names = set()
        for igd in igds:
            name = igd.get("Name") or igd.get("SASDatasetName") or ""
            dataset_names.add(name)
        for domain in ["DM", "AE", "EX", "VS", "DS", "TS", "SUPPAE"]:
            assert domain in dataset_names, f"Missing ItemGroupDef for {domain}"

    def test_itemgroupdef_has_sasdatasetname(self):
        """Each ItemGroupDef should have SASDatasetName attribute."""
        igds = self.root.findall(".//odm:ItemGroupDef", self.NSMAP)
        for igd in igds:
            sas_name = igd.get("SASDatasetName")
            assert sas_name is not None and sas_name != "", \
                f"ItemGroupDef {igd.get('Name')} missing SASDatasetName"

    def test_itemdef_elements_exist(self):
        """ItemDef elements must exist for key variables."""
        idefs = self.root.findall(".//odm:ItemDef", self.NSMAP)
        assert len(idefs) > 0, "No ItemDef elements found"
        idef_names = set(idef.get("Name", "") for idef in idefs)
        for var in ["STUDYID", "USUBJID", "DOMAIN"]:
            assert var in idef_names, f"Missing ItemDef for {var}"

    def test_codelist_elements_exist(self):
        """At least one CodeList should exist for controlled terminology."""
        codelists = self.root.findall(".//odm:CodeList", self.NSMAP)
        assert len(codelists) > 0, "No CodeList elements found"
