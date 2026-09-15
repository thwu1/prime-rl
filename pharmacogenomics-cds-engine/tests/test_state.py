
import glob
import json
import os
import shutil
import subprocess
import tempfile

import pytest


@pytest.fixture(scope="session", autouse=True)
def hide_data_files():
    """Temporarily rename all data files to verify query uses PostgreSQL, not files."""
    renamed = []
    for pattern in ["/app/data/*.json", "/app/data/*.sql"]:
        for f in glob.glob(pattern):
            bak = f + ".bak"
            shutil.move(f, bak)
            renamed.append((bak, f))
    yield
    for bak, orig in renamed:
        if os.path.exists(bak):
            shutil.move(bak, orig)


def run_pgx_cds(patient_data):
    """Run the pgx-cds query subcommand with given patient data and return parsed JSON output."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(patient_data, f)
        f.flush()
        tmp_path = f.name

    try:
        result = subprocess.run(
            ["/app/pgx-cds", "query", tmp_path],
            capture_output=True,
            text=True,
            timeout=60,
            cwd="/app",
        )
        assert result.returncode == 0, f"pgx-cds query failed with stderr: {result.stderr}"
        output = json.loads(result.stdout)
        return output
    finally:
        os.unlink(tmp_path)


def get_patient_result(output, patient_id):
    """Extract a specific patient's result from the output."""
    for r in output["results"]:
        if r["patient_id"] == patient_id:
            return r
    raise ValueError(f"Patient {patient_id} not found in output")


class TestExecutableExists:
    def test_pgx_cds_exists(self):
        assert os.path.isfile("/app/pgx-cds"), "/app/pgx-cds must exist"

    def test_pgx_cds_executable(self):
        assert os.access("/app/pgx-cds", os.X_OK), "/app/pgx-cds must be executable"


class TestPostgreSQLBackend:
    """Verify that data is stored in and queried from PostgreSQL."""

    def test_database_accessible(self):
        """The cpic_cds PostgreSQL database must exist and be accessible."""
        result = subprocess.run(
            ["psql", "-U", "postgres", "-d", "cpic_cds", "-c", "SELECT 1"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Cannot access cpic_cds database: {result.stderr}"

    def test_database_has_tables(self):
        """The database must contain tables with loaded reference data."""
        result = subprocess.run(
            [
                "psql",
                "-U",
                "postgres",
                "-d",
                "cpic_cds",
                "-t",
                "-c",
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public'",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        count = int(result.stdout.strip())
        assert count >= 4, f"Expected at least 4 tables in cpic_cds, got {count}"

    def test_query_works_with_data_files_hidden(self):
        """Query must function with all data files hidden (proving PostgreSQL usage)."""
        # Data files are already hidden by the session fixture
        data = {
            "patients": [
                {
                    "id": "PG_VERIFY",
                    "genotypes": {"CYP2C19": {"diplotype": "*1/*1"}},
                    "drugs": ["clopidogrel"],
                }
            ]
        }
        output = run_pgx_cds(data)
        p = get_patient_result(output, "PG_VERIFY")
        assert p["gene_results"]["CYP2C19"]["phenotype"] == "Normal Metabolizer"
        assert "clopidogrel" in p["drug_recommendations"]

    def test_sql_supplement_data_in_database(self):
        """CYP3A5 (SQL-only gene) must be queryable, proving SQL supplement was loaded."""
        data = {
            "patients": [
                {
                    "id": "PG_SQL",
                    "genotypes": {"CYP3A5": {"diplotype": "*3/*3"}},
                    "drugs": ["tacrolimus"],
                }
            ]
        }
        output = run_pgx_cds(data)
        p = get_patient_result(output, "PG_SQL")
        assert p["gene_results"]["CYP3A5"]["phenotype"] == "Poor Metabolizer"
        assert "tacrolimus" in p["drug_recommendations"]


class TestOutputStructure:
    """Test that output has correct top-level structure."""

    def test_results_key(self):
        data = {
            "patients": [
                {
                    "id": "STRUCT1",
                    "genotypes": {"CYP2C19": {"diplotype": "*1/*1"}},
                    "drugs": ["clopidogrel"],
                }
            ]
        }
        output = run_pgx_cds(data)
        assert "results" in output
        assert isinstance(output["results"], list)
        assert len(output["results"]) == 1

    def test_patient_fields(self):
        data = {
            "patients": [
                {
                    "id": "STRUCT2",
                    "genotypes": {"CYP2C19": {"diplotype": "*1/*1"}},
                    "drugs": ["clopidogrel"],
                }
            ]
        }
        output = run_pgx_cds(data)
        p = output["results"][0]
        assert p["patient_id"] == "STRUCT2"
        assert "gene_results" in p
        assert "drug_recommendations" in p


class TestCYP2C19PhenotypeLookup:
    """Test CYP2C19 phenotype-based lookup for clopidogrel."""

    def test_intermediate_metabolizer(self):
        data = {
            "patients": [
                {
                    "id": "P001",
                    "genotypes": {"CYP2C19": {"diplotype": "*1/*2"}},
                    "drugs": ["clopidogrel"],
                }
            ]
        }
        output = run_pgx_cds(data)
        p = get_patient_result(output, "P001")

        gene = p["gene_results"]["CYP2C19"]
        assert gene["diplotype"] == "*1/*2"
        assert gene["phenotype"] == "Intermediate Metabolizer"
        assert gene["lookup_method"] == "PHENOTYPE"

        drug = p["drug_recommendations"]["clopidogrel"]
        assert "Avoid" in drug["recommendation"] or "avoid" in drug["recommendation"].lower()
        assert drug["classification"] == "Strong"
        assert "CYP2C19" in drug["genes_involved"]

    def test_poor_metabolizer(self):
        data = {
            "patients": [
                {
                    "id": "PM1",
                    "genotypes": {"CYP2C19": {"diplotype": "*2/*3"}},
                    "drugs": ["clopidogrel"],
                }
            ]
        }
        output = run_pgx_cds(data)
        p = get_patient_result(output, "PM1")

        gene = p["gene_results"]["CYP2C19"]
        assert gene["phenotype"] == "Poor Metabolizer"

        drug = p["drug_recommendations"]["clopidogrel"]
        assert "Avoid clopidogrel" in drug["recommendation"]
        assert drug["classification"] == "Strong"

    def test_normal_metabolizer(self):
        data = {
            "patients": [
                {
                    "id": "NM1",
                    "genotypes": {"CYP2C19": {"diplotype": "*1/*1"}},
                    "drugs": ["clopidogrel"],
                }
            ]
        }
        output = run_pgx_cds(data)
        p = get_patient_result(output, "NM1")

        gene = p["gene_results"]["CYP2C19"]
        assert gene["phenotype"] == "Normal Metabolizer"

        drug = p["drug_recommendations"]["clopidogrel"]
        assert "standard dose" in drug["recommendation"].lower()
        assert drug["classification"] == "Strong"

    def test_rapid_metabolizer(self):
        data = {
            "patients": [
                {
                    "id": "RM1",
                    "genotypes": {"CYP2C19": {"diplotype": "*1/*17"}},
                    "drugs": ["clopidogrel"],
                }
            ]
        }
        output = run_pgx_cds(data)
        p = get_patient_result(output, "RM1")

        gene = p["gene_results"]["CYP2C19"]
        assert gene["phenotype"] == "Rapid Metabolizer"

    def test_cyp2c19_activity_score_is_null(self):
        """CYP2C19 does not use activity scores for clopidogrel."""
        data = {
            "patients": [
                {
                    "id": "AS_NULL",
                    "genotypes": {"CYP2C19": {"diplotype": "*1/*2"}},
                    "drugs": ["clopidogrel"],
                }
            ]
        }
        output = run_pgx_cds(data)
        p = get_patient_result(output, "AS_NULL")
        gene = p["gene_results"]["CYP2C19"]
        assert gene["activity_score"] is None


class TestCYP2D6ActivityScoreLookup:
    """Test CYP2D6 activity-score-based lookup for codeine."""

    def test_poor_metabolizer_codeine(self):
        data = {
            "patients": [
                {
                    "id": "P002",
                    "genotypes": {"CYP2D6": {"diplotype": "*4/*4"}},
                    "drugs": ["codeine"],
                }
            ]
        }
        output = run_pgx_cds(data)
        p = get_patient_result(output, "P002")

        gene = p["gene_results"]["CYP2D6"]
        assert gene["diplotype"] == "*4/*4"
        assert gene["phenotype"] == "Poor Metabolizer"
        assert gene["activity_score"] == 0.0
        assert gene["lookup_method"] == "ACTIVITY_SCORE"

        drug = p["drug_recommendations"]["codeine"]
        assert "Avoid codeine" in drug["recommendation"]
        assert "diminished analgesia" in drug["recommendation"]
        assert drug["classification"] == "Strong"

    def test_intermediate_metabolizer_codeine(self):
        data = {
            "patients": [
                {
                    "id": "IM_COD",
                    "genotypes": {"CYP2D6": {"diplotype": "*9/*10"}},
                    "drugs": ["codeine"],
                }
            ]
        }
        output = run_pgx_cds(data)
        p = get_patient_result(output, "IM_COD")

        gene = p["gene_results"]["CYP2D6"]
        # *9 AV=0.25, *10 AV=0.25 -> total=0.5
        assert gene["activity_score"] == 0.5

        drug = p["drug_recommendations"]["codeine"]
        assert "label recommended" in drug["recommendation"].lower()

    def test_activity_score_computation(self):
        """Test that activity score is correctly computed from allele data."""
        data = {
            "patients": [
                {
                    "id": "AS_COMP",
                    "genotypes": {"CYP2D6": {"diplotype": "*1/*9"}},
                    "drugs": ["codeine"],
                }
            ]
        }
        output = run_pgx_cds(data)
        p = get_patient_result(output, "AS_COMP")
        gene = p["gene_results"]["CYP2D6"]
        # *1 AV=1.0, *9 AV=0.25 -> total=1.25
        assert gene["activity_score"] == 1.25

    def test_activity_score_is_number(self):
        """Activity scores must be JSON numbers, not strings."""
        data = {
            "patients": [
                {
                    "id": "AS_NUM",
                    "genotypes": {"CYP2D6": {"diplotype": "*4/*4"}},
                    "drugs": ["codeine"],
                }
            ]
        }
        output = run_pgx_cds(data)
        p = get_patient_result(output, "AS_NUM")
        gene = p["gene_results"]["CYP2D6"]
        assert isinstance(gene["activity_score"], (int, float))
        assert not isinstance(gene["activity_score"], bool)


class TestDPYDActivityScore:
    """Test DPYD activity-score-based lookup for capecitabine."""

    def test_dpyd_intermediate_1_5(self):
        data = {
            "patients": [
                {
                    "id": "P004",
                    "genotypes": {"DPYD": {"diplotype": "Reference/c.2846A>T"}},
                    "drugs": ["capecitabine"],
                }
            ]
        }
        output = run_pgx_cds(data)
        p = get_patient_result(output, "P004")

        gene = p["gene_results"]["DPYD"]
        # Reference AV=1.0, c.2846A>T AV=0.5 -> total=1.5
        assert gene["activity_score"] == 1.5
        assert gene["phenotype"] == "Intermediate Metabolizer"

        drug = p["drug_recommendations"]["capecitabine"]
        assert "Reduce starting dose by 50%" in drug["recommendation"]

    def test_dpyd_intermediate_1_0(self):
        data = {
            "patients": [
                {
                    "id": "DPYD_10",
                    "genotypes": {
                        "DPYD": {"diplotype": "Reference/c.1905+1G>A (*2A)"}
                    },
                    "drugs": ["capecitabine"],
                }
            ]
        }
        output = run_pgx_cds(data)
        p = get_patient_result(output, "DPYD_10")

        gene = p["gene_results"]["DPYD"]
        # Reference AV=1.0, c.1905+1G>A (*2A) AV=0.0 -> total=1.0
        assert gene["activity_score"] == 1.0

        drug = p["drug_recommendations"]["capecitabine"]
        assert "Reduce starting dose by 50%" in drug["recommendation"]
        assert drug["classification"] == "Strong"


class TestHLABAlleleStatus:
    """Test HLA-B allele-status-based lookup for abacavir."""

    def test_hlab_positive_abacavir(self):
        data = {
            "patients": [
                {
                    "id": "P005",
                    "genotypes": {"HLA-B": {"status": "*57:01 positive"}},
                    "drugs": ["abacavir"],
                }
            ]
        }
        output = run_pgx_cds(data)
        p = get_patient_result(output, "P005")

        gene = p["gene_results"]["HLA-B"]
        assert gene["lookup_method"] == "ALLELE_STATUS"

        drug = p["drug_recommendations"]["abacavir"]
        assert "not recommended" in drug["recommendation"].lower()
        assert drug["classification"] == "Strong"

    def test_hlab_negative_abacavir(self):
        data = {
            "patients": [
                {
                    "id": "HLA_NEG",
                    "genotypes": {"HLA-B": {"status": "*57:01 negative"}},
                    "drugs": ["abacavir"],
                }
            ]
        }
        output = run_pgx_cds(data)
        p = get_patient_result(output, "HLA_NEG")

        drug = p["drug_recommendations"]["abacavir"]
        assert "standard dosing" in drug["recommendation"].lower()
        assert drug["classification"] == "Strong"


class TestSLCO1B1PhenotypeLookup:
    """Test SLCO1B1 phenotype-based lookup for simvastatin."""

    def test_decreased_function_simvastatin(self):
        data = {
            "patients": [
                {
                    "id": "P006",
                    "genotypes": {"SLCO1B1": {"diplotype": "*1/*5"}},
                    "drugs": ["simvastatin"],
                }
            ]
        }
        output = run_pgx_cds(data)
        p = get_patient_result(output, "P006")

        gene = p["gene_results"]["SLCO1B1"]
        assert gene["phenotype"] == "Decreased Function"
        assert gene["lookup_method"] == "PHENOTYPE"

        drug = p["drug_recommendations"]["simvastatin"]
        assert "alternative statin" in drug["recommendation"].lower()
        assert drug["classification"] == "Strong"

    def test_normal_function_simvastatin(self):
        data = {
            "patients": [
                {
                    "id": "SLCO_NF",
                    "genotypes": {"SLCO1B1": {"diplotype": "*1/*1"}},
                    "drugs": ["simvastatin"],
                }
            ]
        }
        output = run_pgx_cds(data)
        p = get_patient_result(output, "SLCO_NF")

        gene = p["gene_results"]["SLCO1B1"]
        assert gene["phenotype"] == "Normal Function"

        drug = p["drug_recommendations"]["simvastatin"]
        assert "desired starting dose" in drug["recommendation"].lower()


class TestMultiGeneDrug:
    """Test multi-gene lookup for amitriptyline (CYP2D6 + CYP2C19)."""

    def test_amitriptyline_multi_gene(self):
        data = {
            "patients": [
                {
                    "id": "P003",
                    "genotypes": {
                        "CYP2D6": {"diplotype": "*1/*4"},
                        "CYP2C19": {"diplotype": "*1/*17"},
                    },
                    "drugs": ["amitriptyline"],
                }
            ]
        }
        output = run_pgx_cds(data)
        p = get_patient_result(output, "P003")

        # CYP2D6: *1 (AV=1.0) + *4 (AV=0.0) = 1.0
        cyp2d6 = p["gene_results"]["CYP2D6"]
        assert cyp2d6["activity_score"] == 1.0

        # CYP2C19: *1/*17 -> Rapid Metabolizer
        cyp2c19 = p["gene_results"]["CYP2C19"]
        assert cyp2c19["phenotype"] == "Rapid Metabolizer"

        drug = p["drug_recommendations"]["amitriptyline"]
        assert "CYP2D6" in drug["genes_involved"]
        assert "CYP2C19" in drug["genes_involved"]
        assert "CYP2D6" in drug["lookup_key"]
        assert "CYP2C19" in drug["lookup_key"]
        assert drug["classification"] == "Optional"

    def test_amitriptyline_pm_cyp2d6_nm_cyp2c19(self):
        data = {
            "patients": [
                {
                    "id": "AMI_PM",
                    "genotypes": {
                        "CYP2D6": {"diplotype": "*4/*4"},
                        "CYP2C19": {"diplotype": "*1/*1"},
                    },
                    "drugs": ["amitriptyline"],
                }
            ]
        }
        output = run_pgx_cds(data)
        p = get_patient_result(output, "AMI_PM")

        drug = p["drug_recommendations"]["amitriptyline"]
        assert "Avoid" in drug["recommendation"] or "avoid" in drug["recommendation"]
        assert drug["lookup_key"]["CYP2D6"] == "0.0"
        assert drug["lookup_key"]["CYP2C19"] == "Normal Metabolizer"
        assert drug["classification"] == "Strong"


class TestCYP3A5Tacrolimus:
    """Test CYP3A5 phenotype-based lookup for tacrolimus (data from SQL supplement)."""

    def test_cyp3a5_poor_metabolizer(self):
        """CYP3A5 *3/*3 is Poor Metabolizer -> standard dose tacrolimus."""
        data = {
            "patients": [
                {
                    "id": "CYP3A5_PM",
                    "genotypes": {"CYP3A5": {"diplotype": "*3/*3"}},
                    "drugs": ["tacrolimus"],
                }
            ]
        }
        output = run_pgx_cds(data)
        p = get_patient_result(output, "CYP3A5_PM")

        gene = p["gene_results"]["CYP3A5"]
        assert gene["diplotype"] == "*3/*3"
        assert gene["phenotype"] == "Poor Metabolizer"
        assert gene["lookup_method"] == "PHENOTYPE"

        drug = p["drug_recommendations"]["tacrolimus"]
        assert "standard recommended dose" in drug["recommendation"].lower()
        assert drug["classification"] == "Strong"
        assert "CYP3A5" in drug["genes_involved"]
        assert drug["lookup_key"]["CYP3A5"] == "Poor Metabolizer"
        assert drug["population"] == "general"

    def test_cyp3a5_intermediate_metabolizer(self):
        """CYP3A5 *1/*3 is Intermediate Metabolizer -> increase dose."""
        data = {
            "patients": [
                {
                    "id": "CYP3A5_IM",
                    "genotypes": {"CYP3A5": {"diplotype": "*1/*3"}},
                    "drugs": ["tacrolimus"],
                }
            ]
        }
        output = run_pgx_cds(data)
        p = get_patient_result(output, "CYP3A5_IM")

        gene = p["gene_results"]["CYP3A5"]
        assert gene["phenotype"] == "Intermediate Metabolizer"

        drug = p["drug_recommendations"]["tacrolimus"]
        assert "Increase starting dose" in drug["recommendation"]
        assert "1.5 to 2 times" in drug["recommendation"]
        assert drug["classification"] == "Strong"

    def test_cyp3a5_normal_metabolizer(self):
        """CYP3A5 *1/*1 is Normal Metabolizer -> increase dose."""
        data = {
            "patients": [
                {
                    "id": "CYP3A5_NM",
                    "genotypes": {"CYP3A5": {"diplotype": "*1/*1"}},
                    "drugs": ["tacrolimus"],
                }
            ]
        }
        output = run_pgx_cds(data)
        p = get_patient_result(output, "CYP3A5_NM")

        gene = p["gene_results"]["CYP3A5"]
        assert gene["phenotype"] == "Normal Metabolizer"

        drug = p["drug_recommendations"]["tacrolimus"]
        assert "Increase starting dose" in drug["recommendation"]
        assert drug["classification"] == "Strong"


class TestTPMTNUDT15Azathioprine:
    """Test TPMT+NUDT15 multi-gene lookup for azathioprine.

    TPMT data spans both JSON and SQL; NUDT15 data is SQL-only.
    This tests cross-format multi-gene drug handling.
    """

    def test_both_normal_metabolizers(self):
        """TPMT *1/*1 NM + NUDT15 *1/*1 NM -> standard dose azathioprine."""
        data = {
            "patients": [
                {
                    "id": "AZA_NM_NM",
                    "genotypes": {
                        "TPMT": {"diplotype": "*1/*1"},
                        "NUDT15": {"diplotype": "*1/*1"},
                    },
                    "drugs": ["azathioprine"],
                }
            ]
        }
        output = run_pgx_cds(data)
        p = get_patient_result(output, "AZA_NM_NM")

        tpmt = p["gene_results"]["TPMT"]
        assert tpmt["phenotype"] == "Normal Metabolizer"

        nudt15 = p["gene_results"]["NUDT15"]
        assert nudt15["phenotype"] == "Normal Metabolizer"

        drug = p["drug_recommendations"]["azathioprine"]
        assert "standard starting dose" in drug["recommendation"].lower()
        assert drug["classification"] == "Strong"
        assert "TPMT" in drug["genes_involved"]
        assert "NUDT15" in drug["genes_involved"]
        assert drug["lookup_key"]["TPMT"] == "Normal Metabolizer"
        assert drug["lookup_key"]["NUDT15"] == "Normal Metabolizer"

    def test_tpmt_intermediate_nudt15_normal(self):
        """TPMT *1/*3A IM + NUDT15 *1/*1 NM -> reduced dose azathioprine."""
        data = {
            "patients": [
                {
                    "id": "AZA_IM_NM",
                    "genotypes": {
                        "TPMT": {"diplotype": "*1/*3A"},
                        "NUDT15": {"diplotype": "*1/*1"},
                    },
                    "drugs": ["azathioprine"],
                }
            ]
        }
        output = run_pgx_cds(data)
        p = get_patient_result(output, "AZA_IM_NM")

        tpmt = p["gene_results"]["TPMT"]
        assert tpmt["phenotype"] == "Intermediate Metabolizer"

        drug = p["drug_recommendations"]["azathioprine"]
        assert "reduced starting dose" in drug["recommendation"].lower()
        assert drug["classification"] == "Strong"
        assert drug["lookup_key"]["TPMT"] == "Intermediate Metabolizer"
        assert drug["lookup_key"]["NUDT15"] == "Normal Metabolizer"

    def test_both_poor_metabolizers(self):
        """TPMT *3A/*3A PM + NUDT15 *2/*2 PM -> alternative therapy."""
        data = {
            "patients": [
                {
                    "id": "AZA_PM_PM",
                    "genotypes": {
                        "TPMT": {"diplotype": "*3A/*3A"},
                        "NUDT15": {"diplotype": "*2/*2"},
                    },
                    "drugs": ["azathioprine"],
                }
            ]
        }
        output = run_pgx_cds(data)
        p = get_patient_result(output, "AZA_PM_PM")

        tpmt = p["gene_results"]["TPMT"]
        assert tpmt["phenotype"] == "Poor Metabolizer"

        nudt15 = p["gene_results"]["NUDT15"]
        assert nudt15["phenotype"] == "Poor Metabolizer"

        drug = p["drug_recommendations"]["azathioprine"]
        assert "alternative" in drug["recommendation"].lower()
        assert drug["classification"] == "Strong"

    def test_nudt15_intermediate_tpmt_normal(self):
        """TPMT *1/*1 NM + NUDT15 *1/*3 IM -> reduced dose azathioprine."""
        data = {
            "patients": [
                {
                    "id": "AZA_NM_IM",
                    "genotypes": {
                        "TPMT": {"diplotype": "*1/*1"},
                        "NUDT15": {"diplotype": "*1/*3"},
                    },
                    "drugs": ["azathioprine"],
                }
            ]
        }
        output = run_pgx_cds(data)
        p = get_patient_result(output, "AZA_NM_IM")

        nudt15 = p["gene_results"]["NUDT15"]
        assert nudt15["phenotype"] == "Intermediate Metabolizer"

        drug = p["drug_recommendations"]["azathioprine"]
        assert "reduced starting dose" in drug["recommendation"].lower()
        assert drug["lookup_key"]["TPMT"] == "Normal Metabolizer"
        assert drug["lookup_key"]["NUDT15"] == "Intermediate Metabolizer"


class TestMultiDrugPatient:
    """Test batch processing of a patient with multiple drugs and genes."""

    def test_complex_patient(self):
        data = {
            "patients": [
                {
                    "id": "P007",
                    "genotypes": {
                        "CYP2C19": {"diplotype": "*2/*3"},
                        "CYP2D6": {"diplotype": "*9/*10"},
                        "HLA-B": {"status": "*57:01 negative"},
                        "DPYD": {"diplotype": "Reference/c.1905+1G>A (*2A)"},
                    },
                    "drugs": [
                        "clopidogrel",
                        "codeine",
                        "abacavir",
                        "capecitabine",
                        "amitriptyline",
                    ],
                }
            ]
        }
        output = run_pgx_cds(data)
        p = get_patient_result(output, "P007")

        # Verify all gene results present
        assert "CYP2C19" in p["gene_results"]
        assert "CYP2D6" in p["gene_results"]
        assert "HLA-B" in p["gene_results"]
        assert "DPYD" in p["gene_results"]

        # CYP2C19 *2/*3 -> Poor Metabolizer
        assert p["gene_results"]["CYP2C19"]["phenotype"] == "Poor Metabolizer"

        # CYP2D6 *9/*10 -> AS=0.5
        assert p["gene_results"]["CYP2D6"]["activity_score"] == 0.5

        # DPYD Reference/c.1905+1G>A (*2A) -> AS=1.0
        assert p["gene_results"]["DPYD"]["activity_score"] == 1.0

        # Verify drug recommendations exist
        assert "clopidogrel" in p["drug_recommendations"]
        assert "codeine" in p["drug_recommendations"]
        assert "abacavir" in p["drug_recommendations"]
        assert "capecitabine" in p["drug_recommendations"]
        assert "amitriptyline" in p["drug_recommendations"]

        # Verify clopidogrel recommendation (CYP2C19 PM)
        clop = p["drug_recommendations"]["clopidogrel"]
        assert "Avoid clopidogrel" in clop["recommendation"]

        # Verify abacavir (HLA-B negative)
        aba = p["drug_recommendations"]["abacavir"]
        assert "standard dosing" in aba["recommendation"].lower()

        # Verify capecitabine (DPYD AS=1.0)
        cape = p["drug_recommendations"]["capecitabine"]
        assert "Reduce starting dose by 50%" in cape["recommendation"]

    def test_cross_format_complex_patient(self):
        """Patient with genes from both JSON and SQL data sources, multiple drugs."""
        data = {
            "patients": [
                {
                    "id": "P008",
                    "genotypes": {
                        "CYP2C19": {"diplotype": "*1/*1"},
                        "CYP3A5": {"diplotype": "*3/*3"},
                        "TPMT": {"diplotype": "*1/*1"},
                        "NUDT15": {"diplotype": "*1/*1"},
                    },
                    "drugs": [
                        "clopidogrel",
                        "tacrolimus",
                        "azathioprine",
                    ],
                }
            ]
        }
        output = run_pgx_cds(data)
        p = get_patient_result(output, "P008")

        # All four genes should be in gene_results
        assert "CYP2C19" in p["gene_results"]
        assert "CYP3A5" in p["gene_results"]
        assert "TPMT" in p["gene_results"]
        assert "NUDT15" in p["gene_results"]

        # CYP2C19/clopidogrel (JSON data)
        assert p["gene_results"]["CYP2C19"]["phenotype"] == "Normal Metabolizer"
        assert "clopidogrel" in p["drug_recommendations"]
        assert (
            "standard dose"
            in p["drug_recommendations"]["clopidogrel"]["recommendation"].lower()
        )

        # CYP3A5/tacrolimus (SQL data)
        assert p["gene_results"]["CYP3A5"]["phenotype"] == "Poor Metabolizer"
        assert "tacrolimus" in p["drug_recommendations"]
        assert (
            "standard recommended dose"
            in p["drug_recommendations"]["tacrolimus"]["recommendation"].lower()
        )

        # TPMT+NUDT15/azathioprine (JSON+SQL cross-format)
        assert p["gene_results"]["TPMT"]["phenotype"] == "Normal Metabolizer"
        assert p["gene_results"]["NUDT15"]["phenotype"] == "Normal Metabolizer"
        assert "azathioprine" in p["drug_recommendations"]
        assert (
            "standard starting dose"
            in p["drug_recommendations"]["azathioprine"]["recommendation"].lower()
        )


class TestBatchProcessing:
    """Test that multiple patients are processed correctly in a single batch."""

    def test_multiple_patients(self):
        data = {
            "patients": [
                {
                    "id": "BATCH1",
                    "genotypes": {"CYP2C19": {"diplotype": "*1/*1"}},
                    "drugs": ["clopidogrel"],
                },
                {
                    "id": "BATCH2",
                    "genotypes": {"CYP2D6": {"diplotype": "*1/*1"}},
                    "drugs": ["codeine"],
                },
                {
                    "id": "BATCH3",
                    "genotypes": {"HLA-B": {"status": "*57:01 positive"}},
                    "drugs": ["abacavir"],
                },
            ]
        }
        output = run_pgx_cds(data)
        assert len(output["results"]) == 3

        ids = {r["patient_id"] for r in output["results"]}
        assert ids == {"BATCH1", "BATCH2", "BATCH3"}


class TestLookupMethodReporting:
    """Test that lookup_method is correctly reported per gene."""

    def test_phenotype_method(self):
        data = {
            "patients": [
                {
                    "id": "LM_PHENO",
                    "genotypes": {"CYP2C19": {"diplotype": "*1/*2"}},
                    "drugs": ["clopidogrel"],
                }
            ]
        }
        output = run_pgx_cds(data)
        p = get_patient_result(output, "LM_PHENO")
        assert p["gene_results"]["CYP2C19"]["lookup_method"] == "PHENOTYPE"

    def test_activity_score_method(self):
        data = {
            "patients": [
                {
                    "id": "LM_AS",
                    "genotypes": {"CYP2D6": {"diplotype": "*4/*4"}},
                    "drugs": ["codeine"],
                }
            ]
        }
        output = run_pgx_cds(data)
        p = get_patient_result(output, "LM_AS")
        assert p["gene_results"]["CYP2D6"]["lookup_method"] == "ACTIVITY_SCORE"

    def test_allele_status_method(self):
        data = {
            "patients": [
                {
                    "id": "LM_STAT",
                    "genotypes": {"HLA-B": {"status": "*57:01 positive"}},
                    "drugs": ["abacavir"],
                }
            ]
        }
        output = run_pgx_cds(data)
        p = get_patient_result(output, "LM_STAT")
        assert p["gene_results"]["HLA-B"]["lookup_method"] == "ALLELE_STATUS"

    def test_cyp3a5_phenotype_method(self):
        """CYP3A5 uses phenotype-based lookup (SQL data)."""
        data = {
            "patients": [
                {
                    "id": "LM_CYP3A5",
                    "genotypes": {"CYP3A5": {"diplotype": "*1/*3"}},
                    "drugs": ["tacrolimus"],
                }
            ]
        }
        output = run_pgx_cds(data)
        p = get_patient_result(output, "LM_CYP3A5")
        assert p["gene_results"]["CYP3A5"]["lookup_method"] == "PHENOTYPE"


class TestGeneResultsWithoutDrug:
    """Test that gene_results includes genes not relevant to any requested drug."""

    def test_extra_gene_included(self):
        data = {
            "patients": [
                {
                    "id": "EXTRA_GENE",
                    "genotypes": {
                        "CYP2C19": {"diplotype": "*1/*2"},
                        "HLA-B": {"status": "*57:01 negative"},
                    },
                    "drugs": ["clopidogrel"],
                }
            ]
        }
        output = run_pgx_cds(data)
        p = get_patient_result(output, "EXTRA_GENE")

        # HLA-B is not relevant to clopidogrel, but should still be in gene_results
        assert "HLA-B" in p["gene_results"]
        assert "CYP2C19" in p["gene_results"]

    def test_sql_gene_without_drug(self):
        """SQL-sourced gene included in gene_results even if not needed for drugs."""
        data = {
            "patients": [
                {
                    "id": "SQL_EXTRA",
                    "genotypes": {
                        "CYP2C19": {"diplotype": "*1/*1"},
                        "CYP3A5": {"diplotype": "*3/*3"},
                    },
                    "drugs": ["clopidogrel"],
                }
            ]
        }
        output = run_pgx_cds(data)
        p = get_patient_result(output, "SQL_EXTRA")

        assert "CYP3A5" in p["gene_results"]
        assert p["gene_results"]["CYP3A5"]["phenotype"] == "Poor Metabolizer"


class TestDrugLookupKey:
    """Test that drug recommendations include the correct lookup_key."""

    def test_single_gene_lookup_key(self):
        data = {
            "patients": [
                {
                    "id": "LK_SINGLE",
                    "genotypes": {"CYP2D6": {"diplotype": "*4/*4"}},
                    "drugs": ["codeine"],
                }
            ]
        }
        output = run_pgx_cds(data)
        p = get_patient_result(output, "LK_SINGLE")

        drug = p["drug_recommendations"]["codeine"]
        assert drug["lookup_key"] == {"CYP2D6": "0.0"}

    def test_multi_gene_lookup_key(self):
        data = {
            "patients": [
                {
                    "id": "LK_MULTI",
                    "genotypes": {
                        "CYP2D6": {"diplotype": "*1/*4"},
                        "CYP2C19": {"diplotype": "*1/*17"},
                    },
                    "drugs": ["amitriptyline"],
                }
            ]
        }
        output = run_pgx_cds(data)
        p = get_patient_result(output, "LK_MULTI")

        drug = p["drug_recommendations"]["amitriptyline"]
        assert drug["lookup_key"]["CYP2D6"] == "1.0"
        assert drug["lookup_key"]["CYP2C19"] == "Rapid Metabolizer"

    def test_azathioprine_multi_gene_lookup_key(self):
        """Azathioprine lookup key spans TPMT + NUDT15 (cross-format)."""
        data = {
            "patients": [
                {
                    "id": "LK_AZA",
                    "genotypes": {
                        "TPMT": {"diplotype": "*1/*1"},
                        "NUDT15": {"diplotype": "*1/*1"},
                    },
                    "drugs": ["azathioprine"],
                }
            ]
        }
        output = run_pgx_cds(data)
        p = get_patient_result(output, "LK_AZA")

        drug = p["drug_recommendations"]["azathioprine"]
        assert drug["lookup_key"]["TPMT"] == "Normal Metabolizer"
        assert drug["lookup_key"]["NUDT15"] == "Normal Metabolizer"
        assert "TPMT" in drug["genes_involved"]
        assert "NUDT15" in drug["genes_involved"]
