
import pytest
import psycopg2
import os
import csv


@pytest.fixture(scope="session")
def db():
    conn = psycopg2.connect(dbname="alien_signals", user="postgres")
    conn.autocommit = True
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# 1. Verify all 7 functions exist
# ---------------------------------------------------------------------------
class TestFunctionsExist:
    @pytest.mark.parametrize("fname", [
        "calculate_snqi",
        "calculate_tols",
        "calculate_rpi",
        "calculate_bfr",
        "calculate_lif",
        "calculate_aoi",
        "calculate_oqf",
    ])
    def test_function_exists(self, db, fname):
        cur = db.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM pg_proc WHERE proname = %s", (fname,)
        )
        assert cur.fetchone()[0] >= 1, f"Function {fname} not found"


# ---------------------------------------------------------------------------
# 2. Verify functions return correct values
# ---------------------------------------------------------------------------
class TestFunctionOutputs:
    # SNQI = SnrRatio - 0.1 * |NoiseFloorDbm|
    def test_snqi_positive(self, db):
        cur = db.cursor()
        cur.execute("SELECT calculate_snqi(25.5, -130.0)")
        val = float(cur.fetchone()[0])
        assert abs(val - 12.5) < 0.01

    def test_snqi_negative(self, db):
        cur = db.cursor()
        cur.execute("SELECT calculate_snqi(5.0, -95.0)")
        val = float(cur.fetchone()[0])
        assert abs(val - (-4.5)) < 0.01

    # TOLS = TechSigProb * (1-NatSrcProb) * SigUnique * (0.5 + AnomScore/10)
    def test_tols(self, db):
        cur = db.cursor()
        cur.execute("SELECT calculate_tols(0.85, 0.12, 0.91, 7.2)")
        val = float(cur.fetchone()[0])
        expected = 0.85 * 0.88 * 0.91 * 1.22
        assert abs(val - expected) < 0.01

    def test_tols_low(self, db):
        cur = db.cursor()
        cur.execute("SELECT calculate_tols(0.10, 0.88, 0.20, 0.3)")
        val = float(cur.fetchone()[0])
        expected = 0.10 * 0.12 * 0.20 * 0.53
        assert abs(val - expected) < 0.001

    # RPI = (TechSigProb*4 + BioSigProb/100 + SigUnique*2 + AnomScore/2) * (1-FalsePosProb)
    def test_rpi(self, db):
        cur = db.cursor()
        cur.execute("SELECT calculate_rpi(0.85, 0.05, 0.91, 7.2, 0.02)")
        val = float(cur.fetchone()[0])
        expected = (3.4 + 0.0005 + 1.82 + 3.6) * 0.98
        assert abs(val - expected) < 0.01

    def test_rpi_low(self, db):
        cur = db.cursor()
        cur.execute("SELECT calculate_rpi(0.10, 0.00, 0.20, 0.3, 0.85)")
        val = float(cur.fetchone()[0])
        expected = (0.4 + 0.0 + 0.4 + 0.15) * 0.15
        assert abs(val - expected) < 0.01

    # BFR = BwHz / (CenterFreqMhz * 1e6)
    def test_bfr_broadband(self, db):
        cur = db.cursor()
        cur.execute("SELECT calculate_bfr(5000000.0, 500.0)")
        val = float(cur.fetchone()[0])
        assert abs(val - 0.01) < 0.0001

    def test_bfr_narrowband(self, db):
        cur = db.cursor()
        cur.execute("SELECT calculate_bfr(150.5, 1420.405)")
        val = float(cur.fetchone()[0])
        expected = 150.5 / (1420.405 * 1e6)
        assert abs(val - expected) / max(abs(expected), 1e-15) < 0.01

    # LIF = (1 - LunarDistDeg/180) * (1 - AtmosTransparency)
    def test_lif_low(self, db):
        cur = db.cursor()
        cur.execute("SELECT calculate_lif(165.0, 0.92)")
        val = float(cur.fetchone()[0])
        expected = (1 - 165.0 / 180) * (1 - 0.92)
        assert abs(val - expected) < 0.001

    def test_lif_high(self, db):
        cur = db.cursor()
        cur.execute("SELECT calculate_lif(45.0, 0.45)")
        val = float(cur.fetchone()[0])
        expected = (1 - 45.0 / 180) * (1 - 0.45)
        assert abs(val - expected) < 0.001

    # AOI = AtmosTransparency * (1 - HumidityRate/100) * (1 - 0.02*WindSpeedMs)
    def test_aoi_good(self, db):
        cur = db.cursor()
        cur.execute("SELECT calculate_aoi(0.92, 25.0, 2.5)")
        val = float(cur.fetchone()[0])
        expected = 0.92 * 0.75 * 0.95
        assert abs(val - expected) < 0.001

    def test_aoi_poor(self, db):
        cur = db.cursor()
        cur.execute("SELECT calculate_aoi(0.45, 78.0, 12.0)")
        val = float(cur.fetchone()[0])
        expected = 0.45 * 0.22 * 0.76
        assert abs(val - expected) < 0.001

    # OQF = AOI * (1-LIF) * (PointAccArc<2 ? 1 : 2/PointAccArc)
    def test_oqf_good_pointing(self, db):
        cur = db.cursor()
        cur.execute("SELECT calculate_oqf(0.6555, 0.00667, 1.5)")
        val = float(cur.fetchone()[0])
        expected = 0.6555 * (1 - 0.00667) * 1.0
        assert abs(val - expected) < 0.01

    def test_oqf_poor_pointing(self, db):
        cur = db.cursor()
        cur.execute("SELECT calculate_oqf(0.07524, 0.4125, 5.0)")
        val = float(cur.fetchone()[0])
        expected = 0.07524 * (1 - 0.4125) * 0.4
        assert abs(val - expected) < 0.001

    def test_oqf_medium_pointing(self, db):
        cur = db.cursor()
        cur.execute("SELECT calculate_oqf(0.4212, 0.10389, 2.5)")
        val = float(cur.fetchone()[0])
        expected = 0.4212 * (1 - 0.10389) * (2.0 / 2.5)
        assert abs(val - expected) < 0.01


# ---------------------------------------------------------------------------
# 3. Verify materialized view
# ---------------------------------------------------------------------------
class TestMaterializedView:
    def test_exists(self, db):
        cur = db.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM pg_matviews WHERE matviewname = 'mv_signal_analysis'"
        )
        assert cur.fetchone()[0] == 1

    def test_required_columns(self, db):
        cur = db.cursor()
        # Use pg_attribute (information_schema.columns excludes materialized views)
        cur.execute("""
            SELECT a.attname FROM pg_attribute a
            JOIN pg_class c ON a.attrelid = c.oid
            WHERE c.relname = 'mv_signal_analysis'
              AND a.attnum > 0
              AND NOT a.attisdropped
        """)
        cols = {r[0] for r in cur.fetchall()}
        required = {
            'signalregistry', 'telescref', 'observstation',
            'snqi', 'tols', 'rpi', 'bfr', 'oqf',
            'tols_category', 'is_analyzable', 'is_target_of_opportunity',
        }
        missing = required - cols
        assert not missing, f"Missing columns: {missing}"

    def test_row_count(self, db):
        cur = db.cursor()
        cur.execute("SELECT COUNT(*) FROM mv_signal_analysis")
        assert cur.fetchone()[0] == 8

    # -- SNQI checks --
    def test_sig001_snqi(self, db):
        cur = db.cursor()
        cur.execute(
            "SELECT snqi FROM mv_signal_analysis WHERE signalregistry = 'SIG001'"
        )
        assert abs(float(cur.fetchone()[0]) - 12.5) < 0.01

    def test_sig002_snqi(self, db):
        cur = db.cursor()
        cur.execute(
            "SELECT snqi FROM mv_signal_analysis WHERE signalregistry = 'SIG002'"
        )
        assert abs(float(cur.fetchone()[0]) - (-4.5)) < 0.01

    def test_sig004_snqi(self, db):
        cur = db.cursor()
        cur.execute(
            "SELECT snqi FROM mv_signal_analysis WHERE signalregistry = 'SIG004'"
        )
        assert abs(float(cur.fetchone()[0]) - 18.0) < 0.01

    # -- is_analyzable checks --
    def test_sig001_analyzable(self, db):
        cur = db.cursor()
        cur.execute(
            "SELECT is_analyzable FROM mv_signal_analysis WHERE signalregistry = 'SIG001'"
        )
        assert cur.fetchone()[0] is True

    def test_sig002_not_analyzable(self, db):
        cur = db.cursor()
        cur.execute(
            "SELECT is_analyzable FROM mv_signal_analysis WHERE signalregistry = 'SIG002'"
        )
        assert cur.fetchone()[0] is False

    def test_sig007_not_analyzable(self, db):
        cur = db.cursor()
        cur.execute(
            "SELECT is_analyzable FROM mv_signal_analysis WHERE signalregistry = 'SIG007'"
        )
        assert cur.fetchone()[0] is False

    # -- TOLS category checks --
    def test_sig001_tols_high(self, db):
        cur = db.cursor()
        cur.execute(
            "SELECT tols_category FROM mv_signal_analysis WHERE signalregistry = 'SIG001'"
        )
        assert cur.fetchone()[0] == 'High'

    def test_sig004_tols_high(self, db):
        cur = db.cursor()
        cur.execute(
            "SELECT tols_category FROM mv_signal_analysis WHERE signalregistry = 'SIG004'"
        )
        assert cur.fetchone()[0] == 'High'

    def test_sig006_tols_medium(self, db):
        cur = db.cursor()
        cur.execute(
            "SELECT tols_category FROM mv_signal_analysis WHERE signalregistry = 'SIG006'"
        )
        assert cur.fetchone()[0] == 'Medium'

    def test_sig008_tols_medium(self, db):
        cur = db.cursor()
        cur.execute(
            "SELECT tols_category FROM mv_signal_analysis WHERE signalregistry = 'SIG008'"
        )
        assert cur.fetchone()[0] == 'Medium'

    def test_sig002_tols_low(self, db):
        cur = db.cursor()
        cur.execute(
            "SELECT tols_category FROM mv_signal_analysis WHERE signalregistry = 'SIG002'"
        )
        assert cur.fetchone()[0] == 'Low'

    def test_sig005_tols_low(self, db):
        cur = db.cursor()
        cur.execute(
            "SELECT tols_category FROM mv_signal_analysis WHERE signalregistry = 'SIG005'"
        )
        assert cur.fetchone()[0] == 'Low'

    # -- Target of Opportunity checks --
    # TOO: RPI > 3.5 AND TechSigProb > 0.8 AND AnomScore > 5
    def test_sig001_is_too(self, db):
        cur = db.cursor()
        cur.execute(
            "SELECT is_target_of_opportunity FROM mv_signal_analysis WHERE signalregistry = 'SIG001'"
        )
        assert cur.fetchone()[0] is True

    def test_sig004_is_too(self, db):
        cur = db.cursor()
        cur.execute(
            "SELECT is_target_of_opportunity FROM mv_signal_analysis WHERE signalregistry = 'SIG004'"
        )
        assert cur.fetchone()[0] is True

    def test_sig003_not_too(self, db):
        # RPI > 3.5 but TechSigProb = 0.45 <= 0.8
        cur = db.cursor()
        cur.execute(
            "SELECT is_target_of_opportunity FROM mv_signal_analysis WHERE signalregistry = 'SIG003'"
        )
        assert cur.fetchone()[0] is False

    def test_sig008_not_too(self, db):
        # TechSigProb = 0.75 <= 0.8
        cur = db.cursor()
        cur.execute(
            "SELECT is_target_of_opportunity FROM mv_signal_analysis WHERE signalregistry = 'SIG008'"
        )
        assert cur.fetchone()[0] is False

    def test_sig002_not_too(self, db):
        cur = db.cursor()
        cur.execute(
            "SELECT is_target_of_opportunity FROM mv_signal_analysis WHERE signalregistry = 'SIG002'"
        )
        assert cur.fetchone()[0] is False

    # -- Numeric value spot-checks --
    def test_sig008_tols_value(self, db):
        cur = db.cursor()
        cur.execute(
            "SELECT tols FROM mv_signal_analysis WHERE signalregistry = 'SIG008'"
        )
        # 0.75*(1-0.18)*0.88*(0.5+6.0/10) = 0.75*0.82*0.88*1.1
        expected = 0.75 * 0.82 * 0.88 * 1.1
        assert abs(float(cur.fetchone()[0]) - expected) < 0.01

    def test_sig004_rpi_value(self, db):
        cur = db.cursor()
        cur.execute(
            "SELECT rpi FROM mv_signal_analysis WHERE signalregistry = 'SIG004'"
        )
        expected = (3.68 + 0.0001 + 1.90 + 4.25) * 0.99
        assert abs(float(cur.fetchone()[0]) - expected) < 0.02

    def test_sig001_oqf_value(self, db):
        cur = db.cursor()
        cur.execute(
            "SELECT oqf FROM mv_signal_analysis WHERE signalregistry = 'SIG001'"
        )
        aoi = 0.92 * 0.75 * 0.95
        lif = (1 - 165.0 / 180) * (1 - 0.92)
        expected = aoi * (1 - lif) * 1.0  # pointaccarc=1.5 < 2
        assert abs(float(cur.fetchone()[0]) - expected) < 0.01

    def test_sig003_oqf_value(self, db):
        cur = db.cursor()
        cur.execute(
            "SELECT oqf FROM mv_signal_analysis WHERE signalregistry = 'SIG003'"
        )
        aoi = 0.45 * 0.22 * 0.76
        lif = (1 - 45.0 / 180) * (1 - 0.45)
        expected = aoi * (1 - lif) * (2.0 / 5.0)  # pointaccarc=5.0 >= 2
        assert abs(float(cur.fetchone()[0]) - expected) < 0.005

    def test_sig004_oqf_value(self, db):
        cur = db.cursor()
        cur.execute(
            "SELECT oqf FROM mv_signal_analysis WHERE signalregistry = 'SIG004'"
        )
        aoi = 0.78 * 0.60 * 0.90
        lif = (1 - 95.0 / 180) * (1 - 0.78)
        expected = aoi * (1 - lif) * (2.0 / 2.5)  # pointaccarc=2.5 >= 2
        assert abs(float(cur.fetchone()[0]) - expected) < 0.01

    def test_observstation_join(self, db):
        """Verify the view correctly joins through to observatories."""
        cur = db.cursor()
        cur.execute(
            "SELECT observstation FROM mv_signal_analysis WHERE signalregistry = 'SIG001'"
        )
        assert cur.fetchone()[0].strip() == 'Observatory-Alpha'

    def test_observstation_beta(self, db):
        cur = db.cursor()
        cur.execute(
            "SELECT observstation FROM mv_signal_analysis WHERE signalregistry = 'SIG003'"
        )
        assert cur.fetchone()[0].strip() == 'Observatory-Beta'


# ---------------------------------------------------------------------------
# 4. Verify trigger system
# ---------------------------------------------------------------------------
class TestTrigger:
    def test_auto_snqi_column(self, db):
        cur = db.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_name = 'signals' AND column_name = 'auto_snqi'
        """)
        assert cur.fetchone()[0] == 1

    def test_analyzable_column(self, db):
        cur = db.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_name = 'signals' AND column_name = 'analyzable'
        """)
        assert cur.fetchone()[0] == 1

    def test_trigger_on_signals(self, db):
        cur = db.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM pg_trigger t
            JOIN pg_class c ON t.tgrelid = c.oid
            WHERE c.relname = 'signals' AND NOT t.tgisinternal
        """)
        assert cur.fetchone()[0] >= 1, "No user trigger found on signals table"

    def test_backfill_sig001(self, db):
        cur = db.cursor()
        cur.execute(
            "SELECT auto_snqi, analyzable FROM signals WHERE signalregistry = 'SIG001'"
        )
        row = cur.fetchone()
        assert row is not None and row[0] is not None
        assert abs(float(row[0]) - 12.5) < 0.01
        assert row[1] is True

    def test_backfill_sig002(self, db):
        cur = db.cursor()
        cur.execute(
            "SELECT auto_snqi, analyzable FROM signals WHERE signalregistry = 'SIG002'"
        )
        row = cur.fetchone()
        assert row is not None and row[0] is not None
        assert abs(float(row[0]) - (-4.5)) < 0.01
        assert row[1] is False

    def test_backfill_sig007(self, db):
        cur = db.cursor()
        cur.execute(
            "SELECT auto_snqi, analyzable FROM signals WHERE signalregistry = 'SIG007'"
        )
        row = cur.fetchone()
        assert row is not None and row[0] is not None
        assert abs(float(row[0]) - (-6.0)) < 0.01
        assert row[1] is False

    def test_trigger_insert_analyzable(self, db):
        cur = db.cursor()
        # Cleanup any prior test data
        cur.execute("DELETE FROM observationalconditions WHERE signalref LIKE 'SIGTEST%'")
        cur.execute("DELETE FROM signalprobabilities WHERE signalref LIKE 'SIGTEST%'")
        cur.execute("DELETE FROM signaldynamics WHERE signalref LIKE 'SIGTEST%'")
        cur.execute("DELETE FROM signalclassification WHERE signalref LIKE 'SIGTEST%'")
        cur.execute("DELETE FROM signaldecoding WHERE signalref LIKE 'SIGTEST%'")
        cur.execute("DELETE FROM sourceproperties WHERE signalref LIKE 'SIGTEST%'")
        cur.execute("DELETE FROM signaladvancedphenomena WHERE signalref LIKE 'SIGTEST%'")
        cur.execute("DELETE FROM researchprocess WHERE signalref LIKE 'SIGTEST%'")
        cur.execute("DELETE FROM signals WHERE signalregistry LIKE 'SIGTEST%'")
        # Insert: SNQI = 20 - 0.1*100 = 10.0 > 0
        cur.execute("""
            INSERT INTO signals (signalregistry, telescref, snrratio, noisefloordbm,
                freqmhz, bwhz, centerfreqmhz, sigstrdb, sigdursec)
            VALUES ('SIGTEST01', 'T001', 20.0, -100.0, 1000.0, 500.0, 1000.0, -50.0, 100.0)
        """)
        cur.execute(
            "SELECT auto_snqi, analyzable FROM signals WHERE signalregistry = 'SIGTEST01'"
        )
        row = cur.fetchone()
        assert row is not None and row[0] is not None
        assert abs(float(row[0]) - 10.0) < 0.01
        assert row[1] is True

    def test_trigger_insert_not_analyzable(self, db):
        cur = db.cursor()
        cur.execute("DELETE FROM signals WHERE signalregistry = 'SIGTEST02'")
        # Insert: SNQI = 3 - 0.1*80 = -5.0 < 0
        cur.execute("""
            INSERT INTO signals (signalregistry, telescref, snrratio, noisefloordbm,
                freqmhz, bwhz, centerfreqmhz, sigstrdb, sigdursec)
            VALUES ('SIGTEST02', 'T001', 3.0, -80.0, 1000.0, 500.0, 1000.0, -50.0, 100.0)
        """)
        cur.execute(
            "SELECT auto_snqi, analyzable FROM signals WHERE signalregistry = 'SIGTEST02'"
        )
        row = cur.fetchone()
        assert row is not None and row[0] is not None
        assert abs(float(row[0]) - (-5.0)) < 0.01
        assert row[1] is False


# ---------------------------------------------------------------------------
# 5. Verify CSV export
# ---------------------------------------------------------------------------
class TestCSVExport:
    def test_file_exists(self, db):
        assert os.path.exists('/app/signal_report.csv'), \
            "signal_report.csv not found at /app/"

    def test_has_header_and_data(self, db):
        with open('/app/signal_report.csv', 'r') as f:
            reader = csv.reader(f)
            rows = list(reader)
        assert len(rows) >= 9, \
            f"Expected at least 9 rows (header + 8 data), got {len(rows)}"

    def test_has_required_columns(self, db):
        with open('/app/signal_report.csv', 'r') as f:
            reader = csv.reader(f)
            header = [h.lower().strip() for h in next(reader)]
        for col in ['signalregistry', 'snqi', 'tols', 'rpi', 'bfr', 'oqf']:
            assert col in header, f"Column '{col}' missing from CSV header"
