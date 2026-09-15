"""
Verification tests for MySQL split-brain binary log reconciliation.

"""

import json
import os
import pymysql
import pytest


@pytest.fixture(scope="module")
def db():
    """Connect to MySQL and return a connection to the reconciled database."""
    conn = pymysql.connect(
        user="root",
        unix_socket="/tmp/mysql.sock",
        database="github_meta_reconciled",
        cursorclass=pymysql.cursors.DictCursor,
    )
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def report():
    """Load the reconciliation report."""
    report_path = "/app/reconciliation_report.json"
    assert os.path.exists(report_path), (
        f"Reconciliation report not found at {report_path}"
    )
    with open(report_path) as f:
        return json.load(f)


# ---- Database existence and structure ----


class TestDatabaseStructure:
    def test_reconciled_database_exists(self, db):
        """The reconciled database must exist and be connectable."""
        with db.cursor() as cur:
            cur.execute("SELECT DATABASE()")
            row = cur.fetchone()
            assert row["DATABASE()"] == "github_meta_reconciled"

    def test_issues_table_exists(self, db):
        with db.cursor() as cur:
            cur.execute("SHOW TABLES LIKE 'issues'")
            assert cur.fetchone() is not None

    def test_repositories_table_exists(self, db):
        with db.cursor() as cur:
            cur.execute("SHOW TABLES LIKE 'repositories'")
            assert cur.fetchone() is not None


# ---- Row counts ----


class TestRowCounts:
    def test_issues_row_count(self, db):
        """20 base + 2 East inserts + 2 West inserts (reassigned PKs) = 24."""
        with db.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM issues")
            assert cur.fetchone()["cnt"] == 24

    def test_repositories_row_count(self, db):
        """5 repositories, unchanged count."""
        with db.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM repositories")
            assert cur.fetchone()["cnt"] == 5


# ---- Conflict resolution: UPDATE-UPDATE (LWW) ----


class TestUpdateUpdateConflicts:
    def test_issue_1_west_lww_state(self, db):
        """Issue 1: both DCs closed it; West has later timestamp -> West wins."""
        with db.cursor() as cur:
            cur.execute("SELECT * FROM issues WHERE id = 1")
            row = cur.fetchone()
            assert row is not None, "Issue 1 must exist"
            assert row["state"] == "closed"
            assert row["assignee"] == "alee", (
                "West assigned to alee (LWW winner), not jsmith (East)"
            )

    def test_issue_1_west_lww_timestamps(self, db):
        with db.cursor() as cur:
            cur.execute("SELECT * FROM issues WHERE id = 1")
            row = cur.fetchone()
            assert str(row["updated_at"]) == "2018-10-21 22:54:00"
            assert str(row["closed_at"]) == "2018-10-21 22:54:00"

    def test_issue_7_west_lww_body(self, db):
        """Issue 7: East changed assignee, West changed body; West wins by LWW.
        East's assignee change is lost — mirrors real-world data loss in split-brain."""
        with db.cursor() as cur:
            cur.execute("SELECT * FROM issues WHERE id = 7")
            row = cur.fetchone()
            assert row is not None, "Issue 7 must exist"
            assert "Spark 3.x" in row["body"], (
                f"Body should contain West's update. Got: {row['body']}"
            )

    def test_issue_7_west_lww_assignee_lost(self, db):
        """East assigned issue 7 to mchen, but West wins — assignee stays NULL."""
        with db.cursor() as cur:
            cur.execute("SELECT * FROM issues WHERE id = 7")
            row = cur.fetchone()
            assert row["assignee"] is None, (
                f"Assignee should be NULL (West LWW). Got: {row['assignee']}"
            )

    def test_issue_7_west_lww_timestamp(self, db):
        with db.cursor() as cur:
            cur.execute("SELECT * FROM issues WHERE id = 7")
            row = cur.fetchone()
            assert str(row["updated_at"]) == "2018-10-21 22:58:00"


# ---- Conflict resolution: DELETE vs UPDATE (Data Preservation) ----


class TestDeleteUpdateConflict:
    def test_issue_4_preserved(self, db):
        """Issue 4: East closed it (UPDATE), West deleted it.
        Data preservation rule: keep the UPDATE, do not delete."""
        with db.cursor() as cur:
            cur.execute("SELECT * FROM issues WHERE id = 4")
            row = cur.fetchone()
            assert row is not None, (
                "Issue 4 must exist — East UPDATE preserved over West DELETE"
            )
            assert row["state"] == "closed"

    def test_issue_4_timestamps(self, db):
        with db.cursor() as cur:
            cur.execute("SELECT * FROM issues WHERE id = 4")
            row = cur.fetchone()
            assert str(row["updated_at"]) == "2018-10-21 22:52:20"
            assert str(row["closed_at"]) == "2018-10-21 22:52:20"


# ---- Conflict resolution: INSERT-INSERT PK conflict ----


class TestInsertPKConflicts:
    def test_issue_21_east_insert(self, db):
        """East INSERT at PK 21 must be preserved with original PK."""
        with db.cursor() as cur:
            cur.execute("SELECT * FROM issues WHERE id = 21")
            row = cur.fetchone()
            assert row is not None, "East insert at id=21 must exist"
            assert row["title"] == "Upgrade to React 17"
            assert row["repo_id"] == 1
            assert row["number"] == 106

    def test_issue_22_east_insert(self, db):
        """East INSERT at PK 22 must be preserved with original PK."""
        with db.cursor() as cur:
            cur.execute("SELECT * FROM issues WHERE id = 22")
            row = cur.fetchone()
            assert row is not None, "East insert at id=22 must exist"
            assert row["title"] == "Add circuit breaker pattern"
            assert row["repo_id"] == 2
            assert row["number"] == 205

    def test_west_insert_airflow_reassigned(self, db):
        """West INSERT (originally PK 21) must be present with a reassigned PK."""
        with db.cursor() as cur:
            cur.execute(
                "SELECT * FROM issues WHERE title = 'Add Airflow DAG monitoring'"
            )
            row = cur.fetchone()
            assert row is not None, (
                "West insert 'Add Airflow DAG monitoring' must exist with reassigned PK"
            )
            assert row["id"] != 21, (
                f"West insert should NOT have PK 21 (reserved for East). Got id={row['id']}"
            )
            assert row["repo_id"] == 3
            assert row["number"] == 304

    def test_west_insert_tablet_reassigned(self, db):
        """West INSERT (originally PK 22) must be present with a reassigned PK."""
        with db.cursor() as cur:
            cur.execute(
                "SELECT * FROM issues WHERE title = 'Tablet layout optimization'"
            )
            row = cur.fetchone()
            assert row is not None, (
                "West insert 'Tablet layout optimization' must exist with reassigned PK"
            )
            assert row["id"] != 22, (
                f"West insert should NOT have PK 22 (reserved for East). Got id={row['id']}"
            )
            assert row["repo_id"] == 4
            assert row["number"] == 405


# ---- Non-conflicting writes ----


class TestNonConflictingWrites:
    def test_issue_9_west_close(self, db):
        """Issue 9 closed by West only — no conflict, should be applied."""
        with db.cursor() as cur:
            cur.execute("SELECT * FROM issues WHERE id = 9")
            row = cur.fetchone()
            assert row["state"] == "closed"
            assert str(row["updated_at"]) == "2018-10-21 23:05:00"
            assert str(row["closed_at"]) == "2018-10-21 23:05:00"

    def test_issue_13_west_assign(self, db):
        """Issue 13 assigned by West only — no conflict, should be applied."""
        with db.cursor() as cur:
            cur.execute("SELECT * FROM issues WHERE id = 13")
            row = cur.fetchone()
            assert row["assignee"] == "dkim"
            assert str(row["updated_at"]) == "2018-10-21 23:12:00"

    def test_repo_2_east_forks(self, db):
        """Repo 2 forks updated by East only — no conflict."""
        with db.cursor() as cur:
            cur.execute("SELECT * FROM repositories WHERE id = 2")
            row = cur.fetchone()
            assert row["forks"] == 114
            assert str(row["updated_at"]) == "2018-10-21 22:52:35"


# ---- Conflict resolution: Repository counter merging ----


class TestRepositoryCounterMerge:
    def test_repo_1_stars_max(self, db):
        """Repo 1: East set stars=1545, West set stars=1548. MAX=1548."""
        with db.cursor() as cur:
            cur.execute("SELECT * FROM repositories WHERE id = 1")
            row = cur.fetchone()
            assert row["stars"] == 1548

    def test_repo_1_forks_max(self, db):
        """Repo 1: East forks unchanged (203), West set forks=205. MAX=205."""
        with db.cursor() as cur:
            cur.execute("SELECT * FROM repositories WHERE id = 1")
            row = cur.fetchone()
            assert row["forks"] == 205

    def test_repo_1_updated_at_max(self, db):
        """Repo 1: MAX timestamp from the two DCs."""
        with db.cursor() as cur:
            cur.execute("SELECT * FROM repositories WHERE id = 1")
            row = cur.fetchone()
            assert str(row["updated_at"]) == "2018-10-21 23:00:00"


# ---- Unchanged rows ----


class TestUnchangedRows:
    def test_unchanged_issue_2(self, db):
        """Issue 2 not touched by either DC — should match base."""
        with db.cursor() as cur:
            cur.execute("SELECT * FROM issues WHERE id = 2")
            row = cur.fetchone()
            assert row["state"] == "open"
            assert row["assignee"] == "alee"
            assert str(row["updated_at"]) == "2018-10-21 22:10:00"

    def test_unchanged_repo_3(self, db):
        """Repo 3 not touched by either DC — should match base."""
        with db.cursor() as cur:
            cur.execute("SELECT * FROM repositories WHERE id = 3")
            row = cur.fetchone()
            assert row["stars"] == 432
            assert row["forks"] == 67
            assert str(row["updated_at"]) == "2018-10-21 22:30:00"


# ---- Reconciliation report ----


class TestReconciliationReport:
    def test_report_exists(self, report):
        """Report file must exist and be valid JSON."""
        assert isinstance(report, dict)

    def test_east_writes_count(self, report):
        assert report.get("east_writes_count") == 7, (
            f"Expected 7 East writes, got {report.get('east_writes_count')}"
        )

    def test_west_writes_count(self, report):
        assert report.get("west_writes_count") == 8, (
            f"Expected 8 West writes, got {report.get('west_writes_count')}"
        )

    def test_total_conflicts(self, report):
        assert report.get("total_conflicts") == 6, (
            f"Expected 6 conflicts, got {report.get('total_conflicts')}"
        )

    def test_conflicts_array(self, report):
        conflicts = report.get("conflicts", [])
        assert len(conflicts) == 6, (
            f"Expected 6 conflict entries, got {len(conflicts)}"
        )
