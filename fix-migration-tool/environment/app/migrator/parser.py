"""Migration file parser - reads SQL migration files and extracts metadata."""
import re
import os


class MigrationFile:
    def __init__(self, file_id, path, dependencies, description, statements):
        self.file_id = file_id
        self.path = path
        self.dependencies = dependencies
        self.description = description
        self.statements = statements


def parse_migration(filepath):
    """Parse a .sql migration file and extract metadata and statements."""
    with open(filepath) as f:
        content = f.read()

    file_id = None
    dependencies = []
    description = ""

    for line in content.split('\n'):
        line = line.strip()
        m = re.match(r'^--\s*migration:\s*(.+)$', line)
        if m:
            file_id = m.group(1).strip()
        m = re.match(r'^--\s*depends_on:\s*(.+)$', line)
        if m:
            deps_str = m.group(1).strip()
            if deps_str.lower() != 'none':
                dependencies = [d.strip() for d in deps_str.split(',')]
        m = re.match(r'^--\s*description:\s*(.+)$', line)
        if m:
            description = m.group(1).strip()

    if not file_id:
        file_id = os.path.splitext(os.path.basename(filepath))[0]

    statements = split_statements(content)

    return MigrationFile(file_id, filepath, dependencies, description, statements)


def split_statements(sql_content):
    """Split SQL content into individual statements by semicolons.

    Handles comment lines but splits on all semicolons.
    """
    # Remove comment lines
    lines = []
    for line in sql_content.split('\n'):
        stripped = line.strip()
        if stripped.startswith('--'):
            continue
        lines.append(line)

    body = '\n'.join(lines)

    # Split on semicolons
    raw_parts = body.split(';')

    statements = []
    for part in raw_parts:
        stmt = part.strip()
        if stmt:
            statements.append(stmt + ';')

    return statements


def discover_migrations(migrations_dir):
    """Discover all .sql migration files in the given directory."""
    migrations = []
    if not os.path.isdir(migrations_dir):
        raise FileNotFoundError(f"Migrations directory not found: {migrations_dir}")

    for filename in sorted(os.listdir(migrations_dir)):
        if filename.endswith('.sql'):
            filepath = os.path.join(migrations_dir, filename)
            migration = parse_migration(filepath)
            migrations.append(migration)

    return migrations
