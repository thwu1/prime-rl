"""Tests for the database migration tool.

Verifies correctness of migration execution, data integrity, idempotency,
checksum verification, concurrent locking, and the check diagnostic subcommand.
"""

import subprocess
import sqlite3
import json
import os
import sys
import shutil
import pytest

APP_DIR = '/app'
MIGRATE_SCRIPT = os.path.join(APP_DIR, 'migrate.py')
MIGRATIONS_DIR = os.path.join(APP_DIR, 'migrations')

sys.path.insert(0, APP_DIR)


@pytest.fixture
def fresh_db(tmp_path):
    """Create a fresh database path for testing."""
    db_path = str(tmp_path / 'test.db')
    lock_path = db_path + '.lock'
    if os.path.exists(lock_path):
        os.unlink(lock_path)
    return db_path


def run_migrate(db_path, migrations_dir=None):
    """Run the migration tool and return the result."""
    mdir = migrations_dir or MIGRATIONS_DIR
    result = subprocess.run(
        ['python3', MIGRATE_SCRIPT, 'migrate', '--db', db_path,
         '--migrations-dir', mdir],
        capture_output=True, text=True, timeout=30
    )
    return result


def run_check(db_path, migrations_dir=None):
    """Run the check subcommand and return the result."""
    mdir = migrations_dir or MIGRATIONS_DIR
    result = subprocess.run(
        ['python3', MIGRATE_SCRIPT, 'check', '--db', db_path,
         '--migrations-dir', mdir],
        capture_output=True, text=True, timeout=30
    )
    return result


class TestMigrationExecution:
    """Verify that the migration tool applies all migrations correctly."""

    def test_migrations_complete_successfully(self, fresh_db):
        """Running migrate should complete without errors."""
        result = run_migrate(fresh_db)
        assert result.returncode == 0, (
            f"Migration failed: {result.stdout}\n{result.stderr}"
        )

    def test_all_tables_created(self, fresh_db):
        """All migrations should execute, creating all expected tables."""
        result = run_migrate(fresh_db)
        assert result.returncode == 0, (
            f"Migration failed: {result.stdout}\n{result.stderr}"
        )
        conn = sqlite3.connect(fresh_db)
        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master "
                r"WHERE type='table' AND name NOT LIKE '\_%' ESCAPE '\' "
                "ORDER BY name"
            )
            tables = sorted([row[0] for row in cursor.fetchall()])
            assert 'users' in tables, f"users table missing, got: {tables}"
            assert 'posts' in tables, f"posts table missing, got: {tables}"
            assert 'tags' in tables, f"tags table missing, got: {tables}"
            assert 'post_tags' in tables, f"post_tags table missing, got: {tables}"
        finally:
            conn.close()

    def test_dependency_order_respected(self, fresh_db):
        """Migrations must execute in an order that satisfies dependencies."""
        from migrator.graph import DependencyGraph
        g = DependencyGraph()
        g.add_node('001_create_users')
        g.add_node('002_create_posts', ['001_create_users'])
        g.add_node('003_create_tags', ['001_create_users'])
        g.add_node('004_create_post_tags', ['002_create_posts', '003_create_tags'])
        g.add_node('005_seed_data', ['004_create_post_tags'])
        order = g.resolve_order()
        assert order.index('001_create_users') < order.index('002_create_posts')
        assert order.index('001_create_users') < order.index('003_create_tags')
        assert order.index('002_create_posts') < order.index('004_create_post_tags')
        assert order.index('003_create_tags') < order.index('004_create_post_tags')
        assert order.index('004_create_post_tags') < order.index('005_seed_data')

    def test_five_migrations_applied_message(self, fresh_db):
        """Output should report exactly 5 migrations applied."""
        result = run_migrate(fresh_db)
        assert result.returncode == 0
        assert '5 migrations applied' in result.stdout


class TestDataIntegrity:
    """Verify that seed data is correctly inserted and relationships hold."""

    def test_string_values_with_special_chars(self, fresh_db):
        """Seed data containing special characters in strings must be preserved."""
        result = run_migrate(fresh_db)
        assert result.returncode == 0
        conn = sqlite3.connect(fresh_db)
        try:
            cursor = conn.execute(
                "SELECT body FROM posts WHERE title = 'Welcome Post'"
            )
            row = cursor.fetchone()
            assert row is not None, "Welcome Post not found in database"
            assert row[0] == 'Hello; welcome to the platform!', (
                f"Post body corrupted: {row[0]}"
            )
        finally:
            conn.close()

    def test_all_seed_data_present(self, fresh_db):
        """All seed data rows should be present after migration."""
        result = run_migrate(fresh_db)
        assert result.returncode == 0
        conn = sqlite3.connect(fresh_db)
        try:
            assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2
            assert conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 1
            assert conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0] == 1
            assert conn.execute("SELECT COUNT(*) FROM post_tags").fetchone()[0] == 1
        finally:
            conn.close()

    def test_sql_parser_handles_special_chars(self):
        """Direct test: SQL parser must not split on characters inside quotes."""
        from migrator.parser import split_statements
        sql = (
            "INSERT INTO t (a, b) VALUES (1, 'foo; bar');\n"
            "INSERT INTO t (a, b) VALUES (2, 'baz');\n"
        )
        stmts = split_statements(sql)
        assert len(stmts) == 2, f"Expected 2 statements, got {len(stmts)}: {stmts}"
        assert "'foo; bar'" in stmts[0]

    def test_foreign_key_relationships(self, fresh_db):
        """Foreign key relationships should be intact across all tables."""
        result = run_migrate(fresh_db)
        assert result.returncode == 0
        conn = sqlite3.connect(fresh_db)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            cursor = conn.execute('''
                SELECT u.username, p.title, t.name
                FROM post_tags pt
                JOIN posts p ON pt.post_id = p.id
                JOIN tags t ON pt.tag_id = t.id
                JOIN users u ON p.user_id = u.id
            ''')
            row = cursor.fetchone()
            assert row is not None, "Join query returned no results"
            assert row[0] == 'admin'
            assert row[1] == 'Welcome Post'
            assert row[2] == 'announcements'
        finally:
            conn.close()


class TestIdempotency:
    """Verify that running migrations twice is safe."""

    def test_second_run_applies_nothing(self, fresh_db):
        """Running migrate twice must not re-execute applied migrations."""
        result1 = run_migrate(fresh_db)
        assert result1.returncode == 0
        result2 = run_migrate(fresh_db)
        assert result2.returncode == 0, (
            f"Second run failed: {result2.stdout}\n{result2.stderr}"
        )
        assert '0 migrations applied' in result2.stdout

    def test_no_duplicate_data(self, fresh_db):
        """After two migrate runs, seed data must not be duplicated."""
        run_migrate(fresh_db)
        result2 = run_migrate(fresh_db)
        if result2.returncode != 0:
            pytest.skip("Second migration failed; state tracking blocks this test")
        conn = sqlite3.connect(fresh_db)
        try:
            count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            assert count == 2, f"Expected 2 users, got {count} (data duplicated)"
        finally:
            conn.close()

    def test_state_tracking_direct(self, fresh_db):
        """Direct test: marking a migration applied then querying must return True."""
        from migrator.state import MigrationState
        state = MigrationState(fresh_db)
        state.mark_applied('test_migration_001', 'checksum_abc')
        assert state.is_applied('test_migration_001')

    def test_stored_checksum_retrievable(self, fresh_db):
        """Direct test: stored checksum must be retrievable after marking applied."""
        from migrator.state import MigrationState
        state = MigrationState(fresh_db)
        state.mark_applied('test_m', 'sha256_deadbeef')
        result = state.get_applied_checksum('test_m')
        assert result == 'sha256_deadbeef'


class TestIntegrityVerification:
    """Verify the checksum and verification subsystem."""

    def test_checksum_stable_across_comment_changes(self, tmp_path):
        """Changing only comments should not change the checksum."""
        sql_v1 = (
            "-- migration: test_m\n"
            "-- depends_on: none\n"
            "-- This is version 1\n"
            "\n"
            "CREATE TABLE test (id INTEGER PRIMARY KEY);\n"
        )
        sql_v2 = (
            "-- migration: test_m\n"
            "-- depends_on: none\n"
            "-- This is version 2 with more comments\n"
            "-- Another comment line added here\n"
            "\n"
            "CREATE TABLE test (id INTEGER PRIMARY KEY);\n"
        )
        file_v1 = tmp_path / 'v1.sql'
        file_v2 = tmp_path / 'v2.sql'
        file_v1.write_text(sql_v1)
        file_v2.write_text(sql_v2)

        from migrator.checksum import compute_checksum
        cs1 = compute_checksum(str(file_v1))
        cs2 = compute_checksum(str(file_v2))
        assert cs1 == cs2, f"Checksums differ when only comments changed: {cs1} != {cs2}"

    def test_checksum_changes_on_sql_modification(self, tmp_path):
        """Changing actual SQL content must change the checksum."""
        sql_v1 = (
            "-- migration: test_m\n"
            "-- depends_on: none\n"
            "\n"
            "CREATE TABLE test (id INTEGER PRIMARY KEY);\n"
        )
        sql_v2 = (
            "-- migration: test_m\n"
            "-- depends_on: none\n"
            "\n"
            "CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT);\n"
        )
        file_v1 = tmp_path / 'v1.sql'
        file_v2 = tmp_path / 'v2.sql'
        file_v1.write_text(sql_v1)
        file_v2.write_text(sql_v2)

        from migrator.checksum import compute_checksum
        cs1 = compute_checksum(str(file_v1))
        cs2 = compute_checksum(str(file_v2))
        assert cs1 != cs2

    def test_verify_subcommand_after_migrate(self, fresh_db):
        """The verify subcommand should report all OK after successful migration."""
        run_migrate(fresh_db)
        result = subprocess.run(
            ['python3', MIGRATE_SCRIPT, 'verify', '--db', fresh_db,
             '--migrations-dir', MIGRATIONS_DIR],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0

    def test_status_shows_all_applied(self, fresh_db):
        """The status subcommand should show all migrations as applied."""
        run_migrate(fresh_db)
        result = subprocess.run(
            ['python3', MIGRATE_SCRIPT, 'status', '--db', fresh_db,
             '--migrations-dir', MIGRATIONS_DIR],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0
        assert result.stdout.count('[applied]') == 5
        assert '[pending]' not in result.stdout


class TestConcurrency:
    """Verify the file-based locking mechanism."""

    def test_stale_lock_from_dead_process_cleaned(self, tmp_path):
        """Lock file from a dead process must be cleaned up."""
        lock_path = str(tmp_path / 'test.lock')

        stale_pid = 4194300
        try:
            os.kill(stale_pid, 0)
            pytest.skip("Test PID unexpectedly exists")
        except PermissionError:
            pytest.skip("Test PID exists with different permissions")
        except ProcessLookupError:
            pass

        with open(lock_path, 'w') as f:
            f.write(str(stale_pid))

        from migrator.lock import MigrationLock
        lock = MigrationLock(lock_path)
        acquired = False
        try:
            lock.acquire(timeout=3)
            acquired = True
            lock.release()
        except TimeoutError:
            pass

        assert acquired, "Failed to acquire lock: stale lock was not cleaned"

    def test_active_lock_blocks_acquisition(self, tmp_path):
        """Lock file from a running process must block acquisition."""
        lock_path = str(tmp_path / 'test.lock')

        with open(lock_path, 'w') as f:
            f.write(str(os.getpid()))

        from migrator.lock import MigrationLock
        lock = MigrationLock(lock_path)
        blocked = False
        try:
            lock.acquire(timeout=2)
        except TimeoutError:
            blocked = True

        assert blocked, "Lock from running process should block acquisition"
        os.unlink(lock_path)


class TestCheckSubcommand:
    """Verify the check diagnostic subcommand."""

    def test_check_fresh_database(self, fresh_db):
        """Check on a fresh database should show all migrations as pending."""
        result = run_check(fresh_db)
        assert result.returncode == 0, f"check failed: {result.stderr}"
        report = json.loads(result.stdout)
        assert report['total'] == 5
        assert report['applied'] == 0
        assert report['pending'] == 5
        assert report['graph_valid'] is True
        assert report['checksum_mismatches'] == []
        assert report['orphaned_records'] == []
        assert report['valid'] is True

    def test_check_fully_migrated(self, fresh_db):
        """Check on a fully migrated database should show all applied."""
        migrate_result = run_migrate(fresh_db)
        assert migrate_result.returncode == 0
        result = run_check(fresh_db)
        assert result.returncode == 0, f"check failed: {result.stderr}"
        report = json.loads(result.stdout)
        assert report['total'] == 5
        assert report['applied'] == 5
        assert report['pending'] == 0
        assert report['graph_valid'] is True
        assert report['valid'] is True

    def test_check_detects_checksum_mismatch(self, fresh_db, tmp_path):
        """Check should detect when a migration file changed after being applied."""
        migrate_result = run_migrate(fresh_db)
        assert migrate_result.returncode == 0

        alt_dir = str(tmp_path / 'migrations')
        shutil.copytree(MIGRATIONS_DIR, alt_dir)

        with open(os.path.join(alt_dir, '001_create_users.sql'), 'a') as f:
            f.write('\nALTER TABLE users ADD COLUMN bio TEXT;\n')

        result = run_check(fresh_db, migrations_dir=alt_dir)
        assert result.returncode == 0, f"check failed: {result.stderr}"
        report = json.loads(result.stdout)
        assert '001_create_users' in report['checksum_mismatches']
        assert report['valid'] is False

    def test_check_detects_orphaned_record(self, fresh_db):
        """Check should detect tracking records with no matching migration file."""
        migrate_result = run_migrate(fresh_db)
        assert migrate_result.returncode == 0

        conn = sqlite3.connect(fresh_db)
        conn.execute(
            "INSERT INTO _schema_migrations "
            "(migration_id, checksum, applied_at, status) "
            "VALUES ('999_nonexistent', 'abc', '2024-01-01', 'applied')"
        )
        conn.commit()
        conn.close()

        result = run_check(fresh_db)
        assert result.returncode == 0, f"check failed: {result.stderr}"
        report = json.loads(result.stdout)
        assert '999_nonexistent' in report['orphaned_records']
        assert report['valid'] is False

    def test_check_against_production_reference(self):
        """Check subcommand must validate the production reference database."""
        result = run_check('/app/production.db')
        assert result.returncode == 0, f"check failed: {result.stderr}"
        report = json.loads(result.stdout)
        assert report['valid'] is True
        assert report['applied'] == 5
        assert report['pending'] == 0
        assert report['checksum_mismatches'] == []
        assert report['orphaned_records'] == []
        assert report['graph_valid'] is True

    def test_check_output_is_valid_json_with_all_fields(self, fresh_db):
        """Check output must be a JSON object containing all required fields."""
        result = run_check(fresh_db)
        assert result.returncode == 0
        report = json.loads(result.stdout)
        required_fields = ['valid', 'total', 'applied', 'pending',
                           'graph_valid', 'checksum_mismatches', 'orphaned_records']
        for field in required_fields:
            assert field in report, f"Missing required field: {field}"
        assert isinstance(report['valid'], bool)
        assert isinstance(report['total'], int)
        assert isinstance(report['applied'], int)
        assert isinstance(report['pending'], int)
        assert isinstance(report['graph_valid'], bool)
        assert isinstance(report['checksum_mismatches'], list)
        assert isinstance(report['orphaned_records'], list)
