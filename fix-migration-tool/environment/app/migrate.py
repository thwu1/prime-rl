#!/usr/bin/env python3
"""Custom database migration tool for SQLite with dependency resolution."""
import argparse
import sys
from migrator.executor import MigrationExecutor


def main():
    parser = argparse.ArgumentParser(description='SQLite migration tool')
    subparsers = parser.add_subparsers(dest='command', required=True)

    migrate_p = subparsers.add_parser('migrate', help='Apply pending migrations')
    migrate_p.add_argument('--db', required=True)
    migrate_p.add_argument('--migrations-dir', required=True)

    status_p = subparsers.add_parser('status', help='Show migration status')
    status_p.add_argument('--db', required=True)
    status_p.add_argument('--migrations-dir', required=True)

    verify_p = subparsers.add_parser('verify', help='Verify migration checksums')
    verify_p.add_argument('--db', required=True)
    verify_p.add_argument('--migrations-dir', required=True)

    args = parser.parse_args()
    executor = MigrationExecutor(args.db, args.migrations_dir)

    if args.command == 'migrate':
        result = executor.migrate()
        sys.exit(0 if result else 1)
    elif args.command == 'status':
        executor.status()
    elif args.command == 'verify':
        result = executor.verify()
        sys.exit(0 if result else 1)


if __name__ == '__main__':
    main()
