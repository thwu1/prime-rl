
import hashlib
import os


def sha256(path):
    """Compute SHA-256 hex digest of a file."""
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def file_size(path):
    """Get file size in bytes."""
    return os.path.getsize(path)


# ---- Scenario 1: Comprehensive multi-type transaction processing ----

class TestScenario1Accounts:
    def test_accounts_output_matches(self):
        """Account output must be byte-identical to COBOL reference."""
        ref = sha256("/tmp/ref1/out/accounts_out.dat")
        mig = sha256("/tmp/mig1/out/accounts_out.dat")
        assert ref == mig, (
            f"Account output mismatch: COBOL={ref[:16]}... Python={mig[:16]}..."
        )

    def test_accounts_output_size(self):
        """Account output must have correct number of records (5 x 66 bytes)."""
        size = file_size("/tmp/mig1/out/accounts_out.dat")
        assert size == 5 * 66, f"Expected {5*66} bytes, got {size}"


class TestScenario1Exceptions:
    def test_exceptions_output_matches(self):
        """Exception output must be byte-identical to COBOL reference."""
        ref = sha256("/tmp/ref1/out/exceptions.dat")
        mig = sha256("/tmp/mig1/out/exceptions.dat")
        assert ref == mig, (
            f"Exception output mismatch: COBOL={ref[:16]}... Python={mig[:16]}..."
        )

    def test_exceptions_output_size(self):
        """Exception output must have exactly 1 rejected transaction (1 x 80 bytes)."""
        size = file_size("/tmp/mig1/out/exceptions.dat")
        assert size == 1 * 80, f"Expected {80} bytes, got {size}"


class TestScenario1Summary:
    def test_summary_output_matches(self):
        """Summary output must be byte-identical to COBOL reference."""
        ref = sha256("/tmp/ref1/out/summary.dat")
        mig = sha256("/tmp/mig1/out/summary.dat")
        assert ref == mig, (
            f"Summary output mismatch: COBOL={ref[:16]}... Python={mig[:16]}..."
        )

    def test_summary_output_size(self):
        """Summary output must have 5 records (5 x 58 bytes)."""
        size = file_size("/tmp/mig1/out/summary.dat")
        assert size == 5 * 58, f"Expected {5*58} bytes, got {size}"


# ---- Scenario 2: Rounding, FX precision, and fee boundary edge cases ----

class TestScenario2Accounts:
    def test_accounts_output_matches(self):
        """Account output must match for rounding/boundary edge cases."""
        ref = sha256("/tmp/ref2/out/accounts_out.dat")
        mig = sha256("/tmp/mig2/out/accounts_out.dat")
        assert ref == mig, (
            f"Scenario 2 account mismatch: COBOL={ref[:16]}... Python={mig[:16]}..."
        )

    def test_accounts_output_size(self):
        """Account output must have correct number of records."""
        size = file_size("/tmp/mig2/out/accounts_out.dat")
        assert size == 5 * 66, f"Expected {5*66} bytes, got {size}"


class TestScenario2Exceptions:
    def test_exceptions_output_empty(self):
        """Scenario 2 should produce no exceptions."""
        ref_size = file_size("/tmp/ref2/out/exceptions.dat")
        assert ref_size == 0, f"COBOL produced {ref_size} bytes of exceptions"
        mig_size = file_size("/tmp/mig2/out/exceptions.dat")
        assert mig_size == 0, f"Python produced {mig_size} bytes of exceptions"


class TestScenario2Summary:
    def test_summary_output_matches(self):
        """Summary output must match for edge case scenario."""
        ref = sha256("/tmp/ref2/out/summary.dat")
        mig = sha256("/tmp/mig2/out/summary.dat")
        assert ref == mig, (
            f"Scenario 2 summary mismatch: COBOL={ref[:16]}... Python={mig[:16]}..."
        )

    def test_summary_output_size(self):
        """Summary output must have 5 records."""
        size = file_size("/tmp/mig2/out/summary.dat")
        assert size == 5 * 58, f"Expected {5*58} bytes, got {size}"


# ---- Scenario 3: CALCRATE rate tier boundary verification ----
# These accounts are at exact tier thresholds to verify the solver
# correctly reverse-engineered the black-box interest calculation.

class TestScenario3Accounts:
    def test_accounts_output_matches(self):
        """Account output must match at rate tier boundaries."""
        ref = sha256("/tmp/ref3/out/accounts_out.dat")
        mig = sha256("/tmp/mig3/out/accounts_out.dat")
        assert ref == mig, (
            f"Scenario 3 account mismatch: COBOL={ref[:16]}... Python={mig[:16]}... "
            f"Rate tier boundaries not correctly reverse-engineered."
        )

    def test_accounts_output_size(self):
        """Account output must have 6 accounts (6 x 66 bytes)."""
        size = file_size("/tmp/mig3/out/accounts_out.dat")
        assert size == 6 * 66, f"Expected {6*66} bytes, got {size}"


class TestScenario3Exceptions:
    def test_exceptions_output_empty(self):
        """Scenario 3 has no today transactions so no exceptions."""
        ref_size = file_size("/tmp/ref3/out/exceptions.dat")
        assert ref_size == 0, f"COBOL produced {ref_size} bytes of exceptions"
        mig_size = file_size("/tmp/mig3/out/exceptions.dat")
        assert mig_size == 0, f"Python produced {mig_size} bytes of exceptions"


class TestScenario3Summary:
    def test_summary_output_matches(self):
        """Summary output must match at rate tier boundaries."""
        ref = sha256("/tmp/ref3/out/summary.dat")
        mig = sha256("/tmp/mig3/out/summary.dat")
        assert ref == mig, (
            f"Scenario 3 summary mismatch: COBOL={ref[:16]}... Python={mig[:16]}... "
            f"Interest or fee calculation incorrect at tier boundaries."
        )

    def test_summary_output_size(self):
        """Summary output must have 6 records (6 x 58 bytes)."""
        size = file_size("/tmp/mig3/out/summary.dat")
        assert size == 6 * 58, f"Expected {6*58} bytes, got {size}"


# ---- Anti-cheat: verify Python migration is self-contained ----

class TestMigrationIntegrity:
    def test_no_shell_out(self):
        """Python migration must not shell out to external programs."""
        with open("/app/migrate/batch_post.py", "r") as f:
            code = f.read()
        shell_mechanisms = [
            "subprocess",
            "os.system",
            "os.popen",
            "os.exec",
            "Popen",
        ]
        for term in shell_mechanisms:
            assert term not in code, (
                f"Found '{term}' in migration code - must not shell out"
            )

    def test_no_cobol_binary_refs(self):
        """Python migration must not reference COBOL binary paths."""
        with open("/app/migrate/batch_post.py", "r") as f:
            code = f.read().lower()
        binaries = [
            "/cobol/mainbatch",
            "/cobol/gendata",
            "/cobol/proberates",
        ]
        for path in binaries:
            assert path not in code, (
                f"Found reference to '{path}' - migration must be self-contained"
            )

    def test_migration_file_exists(self):
        """Migration file must exist at the expected path."""
        assert os.path.isfile("/app/migrate/batch_post.py")

    def test_migration_not_trivial(self):
        """Migration must contain substantial implementation logic."""
        with open("/app/migrate/batch_post.py", "r") as f:
            code = f.read()
        assert len(code) > 1000, (
            f"Migration is only {len(code)} bytes - too small for a real implementation"
        )
