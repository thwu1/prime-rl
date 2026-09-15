"""Migration executor - orchestrates the migration process."""
import sqlite3
from .graph import DependencyGraph
from .parser import discover_migrations
from .state import MigrationState
from .checksum import compute_checksum
from .lock import MigrationLock


class MigrationExecutor:
    """Executes database migrations in dependency order."""

    def __init__(self, db_path, migrations_dir):
        self.db_path = db_path
        self.migrations_dir = migrations_dir
        self.lock_path = db_path + '.lock'

    def migrate(self):
        """Apply all pending migrations in dependency order."""
        migrations = discover_migrations(self.migrations_dir)
        if not migrations:
            print("No migration files found.")
            return True

        graph = DependencyGraph()
        migration_map = {}
        for m in migrations:
            graph.add_node(m.file_id, m.dependencies)
            migration_map[m.file_id] = m

        try:
            order = graph.resolve_order()
        except ValueError as e:
            print(f"Error: {e}")
            return False

        state = MigrationState(self.db_path)

        with MigrationLock(self.lock_path):
            applied_count = 0
            for migration_id in order:
                if state.is_applied(migration_id):
                    print(f"  Skipping {migration_id} (already applied)")
                    continue

                migration = migration_map[migration_id]
                checksum = compute_checksum(migration.path)

                print(f"  Applying {migration_id}...")
                try:
                    self._execute_migration(migration)
                    state.mark_applied(migration_id, checksum)
                    applied_count += 1
                    print(f"  Applied {migration_id} successfully")
                except Exception as e:
                    print(f"  FAILED: {migration_id}: {e}")
                    return False

            print(f"Migration complete. {applied_count} migrations applied.")
            return True

    def _execute_migration(self, migration):
        """Execute all SQL statements in a migration within a transaction."""
        conn = sqlite3.connect(self.db_path)
        try:
            for stmt in migration.statements:
                conn.execute(stmt)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def status(self):
        """Print the status of all migrations."""
        migrations = discover_migrations(self.migrations_dir)
        state = MigrationState(self.db_path)

        for m in migrations:
            applied = state.is_applied(m.file_id)
            marker = "applied" if applied else "pending"
            print(f"  [{marker}] {m.file_id}")

    def verify(self):
        """Verify migration file checksums against applied checksums."""
        migrations = discover_migrations(self.migrations_dir)
        state = MigrationState(self.db_path)

        all_ok = True
        for m in migrations:
            stored_checksum = state.get_applied_checksum(m.file_id)
            if stored_checksum is None:
                continue

            current_checksum = compute_checksum(m.path)
            if stored_checksum != current_checksum:
                print(f"  MISMATCH: {m.file_id}")
                all_ok = False
            else:
                print(f"  OK: {m.file_id}")

        return all_ok
