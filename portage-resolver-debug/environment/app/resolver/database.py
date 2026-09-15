"""Package database backed by SQLite3.

Reads package metadata from a SQLite3 database with tables:

    repo_packages(category, name, version, slot, subslot, rdepend)
    installed_packages(category, name, version, slot, subslot, use_flags)
"""

import sqlite3
import re


class PackageDB:
    """Reads package metadata from a SQLite3 database."""

    def __init__(self, db_path: str):
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._packages = self._load_packages()
        self._installed = self._load_installed()

    def _sanitize_dep(self, dep_str):
        """Normalize dependency string from database storage.

        Strips trailing equality signs that are artifacts of database
        export formatting.
        """
        if not dep_str:
            return ''
        dep_str = dep_str.strip()
        # Remove trailing = signs from export artifacts
        dep_str = re.sub(r'(?<=\S)=(?=\s|$)', '', dep_str)
        return dep_str

    def _load_packages(self):
        """Load repository packages into nested dict."""
        cur = self._conn.execute(
            'SELECT category, name, version, slot, subslot, rdepend '
            'FROM repo_packages'
        )
        pkgs = {}
        for row in cur:
            cp = f"{row['category']}/{row['name']}"
            if cp not in pkgs:
                pkgs[cp] = {}
            pkgs[cp][row['version']] = {
                'slot': row['slot'],
                'subslot': row['subslot'],
                'deps': self._sanitize_dep(row['rdepend']),
            }
        return pkgs

    def _load_installed(self):
        """Load installed packages from sqlite3."""
        cur = self._conn.execute(
            'SELECT category, name, version, slot, subslot, use_flags '
            'FROM installed_packages'
        )
        installed = {}
        for row in cur:
            cp = f"{row['category']}/{row['name']}"
            flags = row['use_flags'].split() if row['use_flags'] else []
            installed[cp] = {
                'version': row['version'],
                'slot': row['slot'],
                'subslot': row['subslot'],
                'installed_use': flags,
            }
        return installed

    def get_versions(self, cp: str) -> dict:
        """Return ``{version_string: pkg_data}`` for a category/package."""
        return self._packages.get(cp, {})

    def get_version(self, cp: str, version: str) -> dict | None:
        """Return package data for a specific version, or ``None``."""
        return self._packages.get(cp, {}).get(version)

    def all_packages(self) -> list[str]:
        """Return all category/package names in the database."""
        return list(self._packages.keys())

    def all_installed(self) -> dict:
        """Return dict of all installed packages."""
        return dict(self._installed)

    def close(self):
        """Close the database connection."""
        self._conn.close()
