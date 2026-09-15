"""Tests for SMOKE-compatible chemical speciation pipeline."""

import csv
import os
import sqlite3
import subprocess
import pytest

OUTPUT_CSV = "/app/output/speciated.csv"
DIAG_CSV = "/app/output/diagnostics.csv"
SQLITE_DB = "/app/output/speciation.db"
NC_FILE = "/app/output/emissions.nc"
TOOL_PATH = "/app/speciate"


@pytest.fixture(scope="session", autouse=True)
def run_speciate():
    """Run the speciation tool before all tests."""
    if os.path.exists(TOOL_PATH):
        result = subprocess.run(
            [TOOL_PATH],
            capture_output=True,
            text=True,
            timeout=120,
            cwd="/app",
        )
        assert result.returncode == 0, f"speciate failed: {result.stderr}"
    else:
        pytest.fail(f"Tool not found at {TOOL_PATH}")


@pytest.fixture(scope="session")
def output_data():
    """Load the speciated CSV into a list of dicts."""
    assert os.path.exists(OUTPUT_CSV), f"Output file not found: {OUTPUT_CSV}"
    with open(OUTPUT_CSV) as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    return rows


@pytest.fixture(scope="session")
def diag_data():
    """Load the diagnostics CSV into a list of dicts."""
    assert os.path.exists(DIAG_CSV), f"Diagnostics file not found: {DIAG_CSV}"
    with open(DIAG_CSV) as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    return rows


@pytest.fixture(scope="session")
def db_conn():
    """Open the SQLite database."""
    assert os.path.exists(SQLITE_DB), f"Database not found: {SQLITE_DB}"
    conn = sqlite3.connect(SQLITE_DB)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def nc_dataset():
    """Open the NetCDF file."""
    import netCDF4
    assert os.path.exists(NC_FILE), f"NetCDF file not found: {NC_FILE}"
    ds = netCDF4.Dataset(NC_FILE, "r")
    yield ds
    ds.close()


def find_row(rows, region_cd, scc, polid, species_id):
    """Find a specific row in the output."""
    matches = [
        r
        for r in rows
        if r["REGION_CD"] == region_cd
        and r["SCC"] == scc
        and r["POLID"] == polid
        and r["SPECIES_ID"] == species_id
    ]
    assert len(matches) == 1, (
        f"Expected 1 row for ({region_cd}, {scc}, {polid}, {species_id}), "
        f"found {len(matches)}"
    )
    return matches[0]


def find_diag(rows, region_cd, scc, polid):
    """Find a diagnostic row."""
    matches = [
        r
        for r in rows
        if r["REGION_CD"] == region_cd
        and r["SCC"] == scc
        and r["POLID"] == polid
    ]
    assert len(matches) == 1, (
        f"Expected 1 diag row for ({region_cd}, {scc}, {polid}), "
        f"found {len(matches)}"
    )
    return matches[0]


class TestOutputStructure:
    def test_output_file_exists(self, output_data):
        assert len(output_data) > 0

    def test_header_columns(self):
        with open(OUTPUT_CSV) as f:
            header = f.readline().strip()
        expected = "REGION_CD,SCC,POLID,SPECIES_ID,PROFILE_CODE,MASS_TONS,MOLE_AMOUNT"
        assert header == expected, f"Header mismatch: {header}"

    def test_total_row_count(self, output_data):
        assert len(output_data) == 49, f"Expected 49 rows, got {len(output_data)}"

    def test_sort_order(self, output_data):
        keys = [
            (r["REGION_CD"], r["SCC"], r["POLID"], r["SPECIES_ID"])
            for r in output_data
        ]
        assert keys == sorted(keys), "Output not sorted correctly"


class TestProfileAssignment:
    """Verify correct profile based on the hierarchy."""

    def test_level1_scc_county_pollutant(self, output_data):
        row = find_row(output_data, "37001", "2104008000", "VOC", "HCHO")
        assert row["PROFILE_CODE"] == "0004"

    def test_level2_scc_state_pollutant(self, output_data):
        row = find_row(output_data, "37063", "2104008000", "VOC", "HCHO")
        assert row["PROFILE_CODE"] == "0003"

    def test_level2_scc_state_pollutant_ga(self, output_data):
        row = find_row(output_data, "13089", "2302003100", "VOC", "HCHO")
        assert row["PROFILE_CODE"] == "0006"

    def test_level3_scc_pollutant(self, output_data):
        row = find_row(output_data, "13001", "2104008000", "VOC", "HCHO")
        assert row["PROFILE_CODE"] == "0002"

    def test_level3_scc_pollutant_nox(self, output_data):
        row = find_row(output_data, "37001", "2104008000", "NOX", "NO")
        assert row["PROFILE_CODE"] == "0011"

    def test_level3_scc_pollutant_voc_scc2(self, output_data):
        row = find_row(output_data, "37063", "2302003100", "VOC", "HCHO")
        assert row["PROFILE_CODE"] == "0005"

    def test_level4_county_pollutant(self, output_data):
        row = find_row(output_data, "13001", "2104008000", "PM25", "PEC")
        assert row["PROFILE_CODE"] == "0031"

    def test_level6_pollutant_default(self, output_data):
        row = find_row(output_data, "37001", "2104008000", "CO", "CO")
        assert row["PROFILE_CODE"] == "0020"

    def test_nonpollutant_specific_fallback(self, output_data):
        row = find_row(output_data, "45001", "2801500000", "SO2", "SO2")
        assert row["PROFILE_CODE"] == "0040"


class TestSpeciationValues:
    """Verify computed mass and mole amounts."""

    def test_county_voc_hcho_mass(self, output_data):
        row = find_row(output_data, "37001", "2104008000", "VOC", "HCHO")
        assert abs(float(row["MASS_TONS"]) - 2.4) < 0.001

    def test_county_voc_hcho_mole(self, output_data):
        row = find_row(output_data, "37001", "2104008000", "VOC", "HCHO")
        assert abs(float(row["MOLE_AMOUNT"]) - 2.0) < 0.001

    def test_county_voc_par_mass(self, output_data):
        row = find_row(output_data, "37001", "2104008000", "VOC", "PAR")
        assert abs(float(row["MASS_TONS"]) - 33.0) < 0.001

    def test_county_voc_par_mole(self, output_data):
        row = find_row(output_data, "37001", "2104008000", "VOC", "PAR")
        assert abs(float(row["MOLE_AMOUNT"]) - 38.0) < 0.001

    def test_nox_no_mass_mole(self, output_data):
        row = find_row(output_data, "37001", "2104008000", "NOX", "NO")
        assert abs(float(row["MASS_TONS"]) - 32.61) < 0.01
        assert abs(float(row["MOLE_AMOUNT"]) - 45.0) < 0.01

    def test_nox_no2_mass_mole(self, output_data):
        row = find_row(output_data, "37001", "2104008000", "NOX", "NO2")
        assert abs(float(row["MASS_TONS"]) - 17.39) < 0.01
        assert abs(float(row["MOLE_AMOUNT"]) - 5.0) < 0.01

    def test_co_passthrough(self, output_data):
        row = find_row(output_data, "37001", "2104008000", "CO", "CO")
        assert abs(float(row["MASS_TONS"]) - 200.0) < 0.01
        assert abs(float(row["MOLE_AMOUNT"]) - 200.0) < 0.01

    def test_state_level_speciation(self, output_data):
        row = find_row(output_data, "37063", "2104008000", "VOC", "PAR")
        assert abs(float(row["MASS_TONS"]) - 23.25) < 0.01
        assert abs(float(row["MOLE_AMOUNT"]) - 27.0) < 0.01

    def test_pm25_county_fallback_pec(self, output_data):
        row = find_row(output_data, "13001", "2104008000", "PM25", "PEC")
        assert abs(float(row["MASS_TONS"]) - 2.0) < 0.001
        assert abs(float(row["MOLE_AMOUNT"]) - 2.0) < 0.001

    def test_pm25_county_fallback_pmfine(self, output_data):
        row = find_row(output_data, "13001", "2104008000", "PM25", "PMFINE")
        assert abs(float(row["MASS_TONS"]) - 3.8) < 0.001

    def test_pm25_county_fallback_pso4(self, output_data):
        row = find_row(output_data, "13001", "2104008000", "PM25", "PSO4")
        assert abs(float(row["MASS_TONS"]) - 0.8) < 0.001

    def test_scc_only_voc(self, output_data):
        row = find_row(output_data, "37063", "2302003100", "VOC", "OLE")
        assert abs(float(row["MASS_TONS"]) - 1.5) < 0.001
        assert abs(float(row["MOLE_AMOUNT"]) - 1.2) < 0.001

    def test_ga_state_voc(self, output_data):
        row = find_row(output_data, "13089", "2302003100", "VOC", "TOL")
        assert abs(float(row["MASS_TONS"]) - 7.56) < 0.01
        assert abs(float(row["MOLE_AMOUNT"]) - 6.3) < 0.01


class TestGSCNVConversion:
    """Verify pollutant-to-pollutant conversion via GSCNV."""

    def test_gscnv_hcho_mass(self, output_data):
        row = find_row(output_data, "37001", "2801500000", "VOC", "HCHO")
        assert abs(float(row["MASS_TONS"]) - 0.4338) < 0.001

    def test_gscnv_hcho_mole(self, output_data):
        row = find_row(output_data, "37001", "2801500000", "VOC", "HCHO")
        assert abs(float(row["MOLE_AMOUNT"]) - 0.3615) < 0.001

    def test_gscnv_unreact_mass(self, output_data):
        row = find_row(output_data, "37001", "2801500000", "VOC", "UNREACT")
        assert abs(float(row["MASS_TONS"]) - 71.5625) < 0.01

    def test_gscnv_unreact_mole(self, output_data):
        row = find_row(output_data, "37001", "2801500000", "VOC", "UNREACT")
        assert abs(float(row["MOLE_AMOUNT"]) - 68.1066) < 0.01

    def test_gscnv_profile_code(self, output_data):
        row = find_row(output_data, "37001", "2801500000", "VOC", "HCHO")
        assert row["PROFILE_CODE"] == "0007"

    def test_gscnv_original_polid(self, output_data):
        row = find_row(output_data, "37001", "2801500000", "VOC", "HCHO")
        assert row["POLID"] == "VOC"

    def test_gscnv_species_count(self, output_data):
        count = sum(
            1
            for r in output_data
            if r["REGION_CD"] == "37001"
            and r["SCC"] == "2801500000"
            and r["POLID"] == "VOC"
        )
        assert count == 3

    def test_gscnv_ald2_mass(self, output_data):
        row = find_row(output_data, "37001", "2801500000", "VOC", "ALD2")
        assert abs(float(row["MASS_TONS"]) - 0.3037) < 0.001


class TestNonPollutantSpecificFallback:
    """Test non-pollutant-specific GSREF matching."""

    def test_so2_profile(self, output_data):
        row = find_row(output_data, "45001", "2801500000", "SO2", "SO2")
        assert row["PROFILE_CODE"] == "0040"

    def test_so2_values(self, output_data):
        row = find_row(output_data, "45001", "2801500000", "SO2", "SO2")
        assert abs(float(row["MASS_TONS"]) - 15.0) < 0.001
        assert abs(float(row["MOLE_AMOUNT"]) - 15.0) < 0.001

    def test_so2_single_species(self, output_data):
        count = sum(
            1
            for r in output_data
            if r["REGION_CD"] == "45001"
            and r["SCC"] == "2801500000"
            and r["POLID"] == "SO2"
        )
        assert count == 1


class TestGANOXSpeciation:
    def test_ga_nox_no_mass(self, output_data):
        row = find_row(output_data, "13089", "2801500000", "NOX", "NO")
        assert row["PROFILE_CODE"] == "0012"
        assert abs(float(row["MASS_TONS"]) - 14.675) < 0.01
        assert abs(float(row["MOLE_AMOUNT"]) - 20.0) < 0.01

    def test_ga_nox_no2_mass(self, output_data):
        row = find_row(output_data, "13089", "2801500000", "NOX", "NO2")
        assert abs(float(row["MASS_TONS"]) - 10.325) < 0.01
        assert abs(float(row["MOLE_AMOUNT"]) - 5.0) < 0.01


class TestGAVOCSpeciation:
    def test_ga_voc_profile(self, output_data):
        row = find_row(output_data, "13001", "2104008000", "VOC", "HCHO")
        assert row["PROFILE_CODE"] == "0002"

    def test_ga_voc_hcho(self, output_data):
        row = find_row(output_data, "13001", "2104008000", "VOC", "HCHO")
        assert abs(float(row["MASS_TONS"]) - 2.16) < 0.001

    def test_ga_voc_xyl(self, output_data):
        row = find_row(output_data, "13001", "2104008000", "VOC", "XYL")
        assert abs(float(row["MASS_TONS"]) - 18.0) < 0.01
        assert abs(float(row["MOLE_AMOUNT"]) - 14.4) < 0.01

    def test_ga_voc_species_count(self, output_data):
        count = sum(
            1
            for r in output_data
            if r["REGION_CD"] == "13001"
            and r["SCC"] == "2104008000"
            and r["POLID"] == "VOC"
        )
        assert count == 7


class TestDiagnosticsStructure:
    """Verify diagnostics.csv structure."""

    def test_diagnostics_exists(self, diag_data):
        assert len(diag_data) > 0

    def test_diagnostics_header(self):
        with open(DIAG_CSV) as f:
            header = f.readline().strip()
        expected = "REGION_CD,SCC,POLID,PROFILE_CODE,GSREF_SCC,GSREF_FIPS,GSREF_POLLUTANT"
        assert header == expected, f"Header mismatch: {header}"

    def test_diagnostics_row_count(self, diag_data):
        assert len(diag_data) == 11, f"Expected 11 diag rows, got {len(diag_data)}"

    def test_diagnostics_sort_order(self, diag_data):
        keys = [(r["REGION_CD"], r["SCC"], r["POLID"]) for r in diag_data]
        assert keys == sorted(keys), "Diagnostics not sorted correctly"


class TestDiagnosticsContent:
    """Verify correct GSREF match resolution in diagnostics."""

    def test_county_match_reports_fips(self, diag_data):
        """County-level match should report the county FIPS from GSREF."""
        row = find_diag(diag_data, "37001", "2104008000", "VOC")
        assert row["PROFILE_CODE"] == "0004"
        assert row["GSREF_SCC"] == "2104008000"
        assert row["GSREF_FIPS"] == "037001"
        assert row["GSREF_POLLUTANT"] == "VOC"

    def test_state_match_reports_state_fips(self, diag_data):
        """State-level match should report the state FIPS (YSS000)."""
        row = find_diag(diag_data, "37063", "2104008000", "VOC")
        assert row["PROFILE_CODE"] == "0003"
        assert row["GSREF_FIPS"] == "037000"

    def test_scc_pollutant_match_empty_fips(self, diag_data):
        """SCC+pollutant match with no FIPS should report empty GSREF_FIPS."""
        row = find_diag(diag_data, "37001", "2104008000", "NOX")
        assert row["PROFILE_CODE"] == "0011"
        assert row["GSREF_SCC"] == "2104008000"
        assert row["GSREF_FIPS"] == ""
        assert row["GSREF_POLLUTANT"] == "NOX"

    def test_default_pollutant_match(self, diag_data):
        """Default pollutant match (SCC=0, no FIPS)."""
        row = find_diag(diag_data, "37001", "2104008000", "CO")
        assert row["PROFILE_CODE"] == "0020"
        assert row["GSREF_SCC"] == "0000000000"
        assert row["GSREF_FIPS"] == ""
        assert row["GSREF_POLLUTANT"] == "CO"

    def test_county_noscc_match(self, diag_data):
        """County match without SCC specificity."""
        row = find_diag(diag_data, "13001", "2104008000", "PM25")
        assert row["PROFILE_CODE"] == "0031"
        assert row["GSREF_SCC"] == "0000000000"
        assert row["GSREF_FIPS"] == "013001"

    def test_nonpollutant_fallback_reports_zero(self, diag_data):
        """Non-pollutant-specific fallback should report pollutant=0."""
        row = find_diag(diag_data, "45001", "2801500000", "SO2")
        assert row["PROFILE_CODE"] == "0040"
        assert row["GSREF_POLLUTANT"] == "0"
        assert row["GSREF_SCC"] == "2801500000"

    def test_ga_state_match(self, diag_data):
        """GA state-level match for SCC 2302003100."""
        row = find_diag(diag_data, "13089", "2302003100", "VOC")
        assert row["PROFILE_CODE"] == "0006"
        assert row["GSREF_FIPS"] == "013000"

    def test_gscnv_source_reports_original_profile(self, diag_data):
        """GSCNV-converted source reports profile from GSREF."""
        row = find_diag(diag_data, "37001", "2801500000", "VOC")
        assert row["PROFILE_CODE"] == "0007"
        assert row["GSREF_POLLUTANT"] == "VOC"


class TestSQLiteStructure:
    """Verify SQLite database schema."""

    def test_database_exists(self):
        assert os.path.exists(SQLITE_DB)

    def test_inventory_table_exists(self, db_conn):
        cur = db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='inventory'"
        )
        assert cur.fetchone() is not None, "Table 'inventory' does not exist"

    def test_speciated_table_exists(self, db_conn):
        cur = db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='speciated'"
        )
        assert cur.fetchone() is not None, "Table 'speciated' does not exist"

    def test_match_log_table_exists(self, db_conn):
        cur = db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='match_log'"
        )
        assert cur.fetchone() is not None, "Table 'match_log' does not exist"

    def test_speciated_index_exists(self, db_conn):
        cur = db_conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='index' AND name='idx_speciated_lookup'"
        )
        assert cur.fetchone() is not None, "Index 'idx_speciated_lookup' does not exist"

    def test_index_columns(self, db_conn):
        """Verify the index covers the correct columns."""
        cur = db_conn.execute("PRAGMA index_info(idx_speciated_lookup)")
        cols = [row["name"] for row in cur.fetchall()]
        assert cols == ["region_cd", "scc", "polid", "species_id"]


class TestSQLiteData:
    """Verify SQLite data matches CSV outputs."""

    def test_inventory_row_count(self, db_conn):
        cur = db_conn.execute("SELECT COUNT(*) FROM inventory")
        count = cur.fetchone()[0]
        assert count == 11, f"Expected 11 inventory rows, got {count}"

    def test_speciated_row_count(self, db_conn):
        cur = db_conn.execute("SELECT COUNT(*) FROM speciated")
        count = cur.fetchone()[0]
        assert count == 49, f"Expected 49 speciated rows, got {count}"

    def test_match_log_row_count(self, db_conn):
        cur = db_conn.execute("SELECT COUNT(*) FROM match_log")
        count = cur.fetchone()[0]
        assert count == 11, f"Expected 11 match_log rows, got {count}"

    def test_inventory_values(self, db_conn):
        """Verify specific inventory record."""
        cur = db_conn.execute(
            "SELECT ann_value FROM inventory "
            "WHERE region_cd='37001' AND scc='2104008000' AND polid='VOC'"
        )
        row = cur.fetchone()
        assert row is not None
        assert abs(row[0] - 100.0) < 0.001

    def test_speciated_values_via_sql(self, db_conn):
        """Verify speciated values match CSV expectations."""
        cur = db_conn.execute(
            "SELECT mass_tons, mole_amount FROM speciated "
            "WHERE region_cd='37001' AND scc='2104008000' "
            "AND polid='VOC' AND species_id='HCHO'"
        )
        row = cur.fetchone()
        assert row is not None
        assert abs(row[0] - 2.4) < 0.001
        assert abs(row[1] - 2.0) < 0.001

    def test_match_log_content(self, db_conn):
        """Verify match_log contains correct GSREF match info."""
        cur = db_conn.execute(
            "SELECT profile_code, gsref_scc, gsref_fips, gsref_pollutant "
            "FROM match_log "
            "WHERE region_cd='37001' AND scc='2104008000' AND polid='VOC'"
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "0004"
        assert row[1] == "2104008000"
        assert row[2] == "037001"
        assert row[3] == "VOC"

    def test_gscnv_in_speciated_db(self, db_conn):
        """Verify GSCNV-converted entries in database."""
        cur = db_conn.execute(
            "SELECT mass_tons FROM speciated "
            "WHERE region_cd='37001' AND scc='2801500000' "
            "AND polid='VOC' AND species_id='HCHO'"
        )
        row = cur.fetchone()
        assert row is not None
        assert abs(row[0] - 0.4338) < 0.001

    def test_aggregate_by_pollutant(self, db_conn):
        """Verify SQL aggregation works correctly on the indexed table."""
        cur = db_conn.execute(
            "SELECT polid, SUM(mass_tons) as total_mass FROM speciated "
            "GROUP BY polid ORDER BY polid"
        )
        results = {row[0]: row[1] for row in cur.fetchall()}
        assert "VOC" in results
        assert "NOX" in results
        assert "CO" in results
        assert "PM25" in results
        assert "SO2" in results

    def test_match_log_nonpollutant_fallback(self, db_conn):
        """Verify non-pollutant-specific fallback is recorded in match_log."""
        cur = db_conn.execute(
            "SELECT profile_code, gsref_pollutant FROM match_log "
            "WHERE region_cd='45001' AND scc='2801500000' AND polid='SO2'"
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "0040"
        assert row[1] == "0"

    def test_inventory_all_pollutants_present(self, db_conn):
        """Verify all 5 pollutant types are in the inventory."""
        cur = db_conn.execute(
            "SELECT DISTINCT polid FROM inventory ORDER BY polid"
        )
        pols = [row[0] for row in cur.fetchall()]
        assert pols == ["CO", "NOX", "PM25", "SO2", "VOC"]


class TestNetCDFOutput:
    """Verify I/O API-conformant NetCDF output."""

    def test_netcdf_exists(self):
        assert os.path.exists(NC_FILE), f"NetCDF file not found: {NC_FILE}"

    def test_ncdump_validates(self):
        """Verify ncdump can read the file without errors."""
        result = subprocess.run(
            ["ncdump", "-h", NC_FILE],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, f"ncdump failed: {result.stderr}"
        assert "GDTYP" in result.stdout
        assert "P_ALP" in result.stdout
        assert "TFLAG" in result.stdout

    def test_ftype(self, nc_dataset):
        assert int(nc_dataset.FTYPE) == 1

    def test_gdtyp(self, nc_dataset):
        assert int(nc_dataset.GDTYP) == 2

    def test_p_alp(self, nc_dataset):
        assert abs(float(nc_dataset.P_ALP) - 33.0) < 0.001

    def test_p_bet(self, nc_dataset):
        assert abs(float(nc_dataset.P_BET) - 45.0) < 0.001

    def test_p_gam(self, nc_dataset):
        assert abs(float(nc_dataset.P_GAM) - (-97.0)) < 0.001

    def test_xcent(self, nc_dataset):
        assert abs(float(nc_dataset.XCENT) - (-97.0)) < 0.001

    def test_ycent(self, nc_dataset):
        assert abs(float(nc_dataset.YCENT) - 40.0) < 0.001

    def test_xorig(self, nc_dataset):
        assert abs(float(nc_dataset.XORIG) - (-2556000.0)) < 0.1

    def test_yorig(self, nc_dataset):
        assert abs(float(nc_dataset.YORIG) - (-1728000.0)) < 0.1

    def test_xcell(self, nc_dataset):
        assert abs(float(nc_dataset.XCELL) - 12000.0) < 0.1

    def test_ycell(self, nc_dataset):
        assert abs(float(nc_dataset.YCELL) - 12000.0) < 0.1

    def test_ncols(self, nc_dataset):
        assert int(nc_dataset.NCOLS) == 50

    def test_nrows(self, nc_dataset):
        assert int(nc_dataset.NROWS) == 40

    def test_nlays(self, nc_dataset):
        assert int(nc_dataset.NLAYS) == 1

    def test_nthik(self, nc_dataset):
        assert int(nc_dataset.NTHIK) == 1

    def test_nvars(self, nc_dataset):
        assert int(nc_dataset.NVARS) == 16

    def test_sdate(self, nc_dataset):
        assert int(nc_dataset.SDATE) == 2020001

    def test_stime(self, nc_dataset):
        assert int(nc_dataset.STIME) == 0

    def test_tstep(self, nc_dataset):
        assert int(nc_dataset.TSTEP) == 0

    def test_vgtyp(self, nc_dataset):
        assert int(nc_dataset.VGTYP) == -9999

    def test_vgtop(self, nc_dataset):
        assert float(nc_dataset.VGTOP) < -9e36

    def test_vglvls(self, nc_dataset):
        vglvls = nc_dataset.VGLVLS
        assert len(vglvls) == 2
        assert abs(float(vglvls[0])) < 0.001
        assert abs(float(vglvls[1])) < 0.001

    def test_gdnam(self, nc_dataset):
        gdnam = str(nc_dataset.GDNAM).strip()
        assert gdnam == "SE_US_12KM"

    def test_var_list_content(self, nc_dataset):
        var_list = nc_dataset.getncattr("VAR-LIST")
        species_names = [var_list[i:i+16].strip() for i in range(0, len(var_list), 16)]
        expected = sorted(["ALD2", "CO", "HCHO", "NO", "NO2", "OLE", "PAR",
                          "PEC", "PMFINE", "PNO3", "POC", "PSO4", "SO2",
                          "TOL", "UNREACT", "XYL"])
        assert species_names == expected, f"VAR-LIST mismatch: {species_names}"

    def test_dimensions_exist(self, nc_dataset):
        for dim_name in ["TSTEP", "DATE-TIME", "LAY", "VAR", "ROW", "COL"]:
            assert dim_name in nc_dataset.dimensions, f"Missing dimension: {dim_name}"

    def test_dimension_sizes(self, nc_dataset):
        assert len(nc_dataset.dimensions["DATE-TIME"]) == 2
        assert len(nc_dataset.dimensions["LAY"]) == 1
        assert len(nc_dataset.dimensions["VAR"]) == 16
        assert len(nc_dataset.dimensions["ROW"]) == 40
        assert len(nc_dataset.dimensions["COL"]) == 50

    def test_tflag_variable_exists(self, nc_dataset):
        assert "TFLAG" in nc_dataset.variables

    def test_tflag_dimensions(self, nc_dataset):
        tflag = nc_dataset.variables["TFLAG"]
        assert tflag.dimensions == ("TSTEP", "VAR", "DATE-TIME")

    def test_tflag_dtype(self, nc_dataset):
        tflag = nc_dataset.variables["TFLAG"]
        assert str(tflag.dtype) == "int32"

    def test_tflag_date_values(self, nc_dataset):
        tflag = nc_dataset.variables["TFLAG"][:]
        assert all(tflag[0, :, 0] == 2020001), "TFLAG date values should be 2020001"

    def test_tflag_time_values(self, nc_dataset):
        tflag = nc_dataset.variables["TFLAG"][:]
        assert all(tflag[0, :, 1] == 0), "TFLAG time values should be 0"

    def test_species_variables_exist(self, nc_dataset):
        expected = ["ALD2", "CO", "HCHO", "NO", "NO2", "OLE", "PAR",
                   "PEC", "PMFINE", "PNO3", "POC", "PSO4", "SO2",
                   "TOL", "UNREACT", "XYL"]
        for sp in expected:
            assert sp in nc_dataset.variables, f"Missing species variable: {sp}"

    def test_species_dimensions(self, nc_dataset):
        """All species variables must have (TSTEP, LAY, ROW, COL) dims."""
        expected_species = ["ALD2", "CO", "HCHO", "NO", "NO2", "OLE", "PAR",
                           "PEC", "PMFINE", "PNO3", "POC", "PSO4", "SO2",
                           "TOL", "UNREACT", "XYL"]
        for sp in expected_species:
            var = nc_dataset.variables[sp]
            assert var.dimensions == ("TSTEP", "LAY", "ROW", "COL"), \
                f"Variable {sp} has wrong dimensions: {var.dimensions}"

    def test_species_dtype(self, nc_dataset):
        """Species variables must be float32."""
        expected_species = ["ALD2", "CO", "HCHO", "NO", "NO2", "OLE", "PAR",
                           "PEC", "PMFINE", "PNO3", "POC", "PSO4", "SO2",
                           "TOL", "UNREACT", "XYL"]
        for sp in expected_species:
            var = nc_dataset.variables[sp]
            assert str(var.dtype) == "float32", \
                f"Variable {sp} has wrong dtype: {var.dtype}"

    def test_species_variable_shape(self, nc_dataset):
        """Verify species variable data shape matches grid dimensions."""
        var = nc_dataset.variables["HCHO"]
        data = var[:]
        assert data.shape == (1, 1, 40, 50), f"Wrong shape: {data.shape}"
