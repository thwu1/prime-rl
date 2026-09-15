
import sys

import pytest

sys.path.insert(0, "/app")

from resolver import ResolutionError, resolve

INDEX = "/app/index/packages.json"


class TestBasicResolution:
    def test_direct_dependencies(self):
        """Two direct requirements with transitive deps from mathcore."""
        result = resolve(
            requirements=["cryptolib>=1.0", "mathcore>=2.0"],
            index_path=INDEX,
            python_version="3.11",
            sys_platform="linux",
        )
        assert result == {"cryptolib": "2.1.0", "mathcore": "3.0.0"}

    def test_transitive_dependencies(self):
        """Multi-level transitive chain: webcore -> netutils -> cryptolib, etc."""
        result = resolve(
            requirements=["webcore>=2.0"],
            index_path=INDEX,
            python_version="3.11",
            sys_platform="linux",
        )
        assert result == {
            "cryptolib": "2.1.0",
            "dataformat": "2.0.0",
            "mathcore": "3.0.0",
            "netutils": "2.1.0",
            "webcore": "3.0.0",
        }


class TestBacktracking:
    def test_upper_bound_forces_older_versions(self):
        """cryptolib<2.0 forces webcore, netutils, and mathcore to older versions."""
        result = resolve(
            requirements=["webcore>=1.0", "cryptolib<2.0"],
            index_path=INDEX,
            python_version="3.11",
            sys_platform="linux",
        )
        assert result == {
            "cryptolib": "1.1.0",
            "dataformat": "2.0.0",
            "mathcore": "2.0.0",
            "netutils": "1.0.0",
            "webcore": "1.0.0",
        }

    def test_not_equal_with_transitive_deps(self):
        """dataformat!=1.5.0 combined with loglib's pinned dataformat deps."""
        result = resolve(
            requirements=["reporter>=1.0"],
            index_path=INDEX,
            python_version="3.11",
            sys_platform="linux",
        )
        assert result == {
            "cryptolib": "2.1.0",
            "dataformat": "2.0.0",
            "loglib": "1.2.0",
            "mathcore": "3.0.0",
            "reporter": "1.0.0",
        }


class TestConflicts:
    def test_unsolvable_raises_error(self):
        """conflicta needs cryptolib>=2.0, conflictb needs cryptolib<2.0."""
        with pytest.raises(ResolutionError):
            resolve(
                requirements=["conflicta>=1.0", "conflictb>=1.0"],
                index_path=INDEX,
                python_version="3.11",
                sys_platform="linux",
            )


class TestExtras:
    def test_extras_include_optional_deps(self):
        """Requesting [postgres] extra should pull in pglib."""
        result = resolve(
            requirements=["dbdriver[postgres]>=2.0"],
            index_path=INDEX,
            python_version="3.11",
            sys_platform="linux",
        )
        assert result == {
            "cryptolib": "2.1.0",
            "dbdriver": "2.0.0",
            "pglib": "2.0.0",
        }

    def test_no_extras_exclude_optional_deps(self):
        """Without extras, optional deps should not be included."""
        result = resolve(
            requirements=["dbdriver>=2.0"],
            index_path=INDEX,
            python_version="3.11",
            sys_platform="linux",
        )
        assert result == {"cryptolib": "2.1.0", "dbdriver": "2.0.0"}
        assert "pglib" not in result
        assert "mysqlclient" not in result


class TestEnvironmentMarkers:
    def test_linux_includes_posix_deps(self):
        """On linux, posixtools is included and winapi is excluded."""
        result = resolve(
            requirements=["oscompat>=1.0"],
            index_path=INDEX,
            python_version="3.11",
            sys_platform="linux",
        )
        assert result == {"oscompat": "1.0.0", "posixtools": "1.0.0"}

    def test_windows_includes_win_deps(self):
        """On win32, winapi is included and posixtools is excluded."""
        result = resolve(
            requirements=["oscompat>=1.0"],
            index_path=INDEX,
            python_version="3.11",
            sys_platform="win32",
        )
        assert result == {"oscompat": "1.0.0", "winapi": "1.0.0"}


class TestPythonVersion:
    def test_filters_incompatible_python(self):
        """asynchelper 3.0.0 requires >=3.12, should be skipped for 3.11."""
        result = resolve(
            requirements=["asynchelper>=1.0"],
            index_path=INDEX,
            python_version="3.11",
            sys_platform="linux",
        )
        assert result == {"asynchelper": "2.0.0"}

    def test_allows_compatible_python(self):
        """asynchelper 3.0.0 requires >=3.12, should be available for 3.12."""
        result = resolve(
            requirements=["asynchelper>=1.0"],
            index_path=INDEX,
            python_version="3.12",
            sys_platform="linux",
        )
        assert result == {"asynchelper": "3.0.0"}


class TestVersionOperators:
    def test_compatible_release_tilde_equals(self):
        """~=1.1 should match >=1.1, <2.0 — picks 1.2.0 over 2.0.0."""
        result = resolve(
            requirements=["configtool~=1.1"],
            index_path=INDEX,
            python_version="3.11",
            sys_platform="linux",
        )
        assert result == {"configtool": "1.2.0"}


class TestComplexScenario:
    def test_multi_level_pipeline(self):
        """Deep transitive chain with Python version filtering and pinned loglib."""
        result = resolve(
            requirements=["pipeline>=2.0"],
            index_path=INDEX,
            python_version="3.11",
            sys_platform="linux",
        )
        assert result == {
            "asynchelper": "2.0.0",
            "cryptolib": "2.1.0",
            "dataformat": "2.0.0",
            "dbdriver": "2.0.0",
            "loglib": "1.2.0",
            "mathcore": "3.0.0",
            "pipeline": "2.0.0",
            "scheduler": "2.0.0",
        }
