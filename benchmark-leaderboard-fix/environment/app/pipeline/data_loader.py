"""Load evaluation data from the SQLite database."""


def load_from_sqlite(db_path):
    """Load and return (models, tasks, evaluations) from the SQLite database.

    Inspect the database schema to understand the table structure.
    The return format must match what pipeline/main.py expects.
    """
    raise NotImplementedError
