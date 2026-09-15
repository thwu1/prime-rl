
"""
Tests for WAL forensic recovery.

Verifies that /app/recovered.db contains the correct data after
reconstructing the base state and applying only durably committed
WAL transactions.
"""

import os
import struct
import subprocess
import zlib

import pytest

DB_PATH = "/app/recovered.db"
PAGE_SIZE = 4096
HEADER_SIZE = 32


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_header(data: bytes) -> dict:
    magic, version, page_size, total_pages, checksum = struct.unpack_from(
        ">6sHIII", data, 0
    )
    return {
        "magic": magic,
        "version": version,
        "page_size": page_size,
        "total_pages": total_pages,
        "checksum": checksum,
    }


def parse_page(data: bytes, offset: int = 0) -> dict:
    num_entries = struct.unpack_from(">H", data, offset)[0]
    pos = offset + 2
    entries = {}
    for _ in range(num_entries):
        klen, vlen = struct.unpack_from(">HH", data, pos)
        pos += 4
        key = data[pos : pos + klen].decode("utf-8")
        pos += klen
        value = data[pos : pos + vlen].decode("utf-8")
        pos += vlen
        entries[key] = value
    return entries


def load_recovered():
    with open(DB_PATH, "rb") as f:
        raw = f.read()
    header = parse_header(raw)
    pages = []
    for i in range(header["total_pages"]):
        start = HEADER_SIZE + i * PAGE_SIZE
        pages.append(parse_page(raw, start))
    return header, pages, raw


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def recovered():
    return load_recovered()


@pytest.fixture(scope="module")
def header(recovered):
    return recovered[0]


@pytest.fixture(scope="module")
def pages(recovered):
    return recovered[1]


@pytest.fixture(scope="module")
def raw_data(recovered):
    return recovered[2]


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------

class TestFileStructure:
    def test_file_exists(self):
        assert os.path.exists(DB_PATH), "recovered.db not found"

    def test_magic_bytes(self, header):
        assert header["magic"] == b"SIMDB\x00"

    def test_version(self, header):
        assert header["version"] == 1

    def test_page_size(self, header):
        assert header["page_size"] == PAGE_SIZE

    def test_page_count(self, header):
        assert header["total_pages"] == 6

    def test_file_size(self, raw_data, header):
        expected = HEADER_SIZE + header["total_pages"] * PAGE_SIZE
        assert len(raw_data) == expected

    def test_header_checksum(self, raw_data, header):
        page_bytes = raw_data[HEADER_SIZE:]
        computed = zlib.crc32(page_bytes) & 0xFFFFFFFF
        assert header["checksum"] == computed, (
            f"Header CRC 0x{header['checksum']:08X} != "
            f"computed 0x{computed:08X}"
        )


# ---------------------------------------------------------------------------
# Committed transaction: txn 1001 (config update + add user:3)
# ---------------------------------------------------------------------------

class TestTxn1001Committed:
    def test_config_version_updated(self, pages):
        assert pages[0]["config:version"] == "2.0.0"

    def test_user3_exists(self, pages):
        assert pages[1].get("user:3:name") == "Charlie"
        assert pages[1].get("user:3:email") == "charlie@example.com"


# ---------------------------------------------------------------------------
# Uncommitted transaction: txn 1002 (deleted user:1, added user:4)
# ---------------------------------------------------------------------------

class TestTxn1002Uncommitted:
    def test_user1_preserved(self, pages):
        assert pages[1]["user:1:name"] == "Alice"
        assert pages[1]["user:1:email"] == "alice@example.com"

    def test_user4_absent(self, pages):
        assert "user:4:name" not in pages[1]
        assert "user:4:email" not in pages[1]


# ---------------------------------------------------------------------------
# Committed transaction: txn 1003 (counter update with same-page double write)
# ---------------------------------------------------------------------------

class TestTxn1003Committed:
    def test_counter_visits_final_value(self, pages):
        """Second PAGE_WRITE in same txn should win (108, not 100)."""
        assert pages[2]["counter:visits"] == "108"

    def test_counter_visits_not_intermediate(self, pages):
        assert pages[2]["counter:visits"] != "100"


# ---------------------------------------------------------------------------
# Aborted transaction: txn 1004 (renamed user:2 to Robert)
# ---------------------------------------------------------------------------

class TestTxn1004Aborted:
    def test_user2_not_robert(self, pages):
        assert pages[1]["user:2:name"] != "Robert"


# ---------------------------------------------------------------------------
# Corrupted transaction: txn 1005 (BEGIN had bad CRC)
# Writes to page 3 (session:ghi789) AND page 4 (modified permissions)
# ---------------------------------------------------------------------------

class TestTxn1005Corrupted:
    def test_session_ghi789_absent(self, pages):
        assert "session:ghi789" not in pages[3]

    def test_guest_perm_absent(self, pages):
        """Txn 1005 wrote perm:guest:read to page 4 -- must not be applied."""
        assert "perm:guest:read" not in pages[4]

    def test_user_write_perm_unchanged(self, pages):
        """Txn 1005 changed perm:user:write to true -- must remain false."""
        assert pages[4]["perm:user:write"] == "false"


# ---------------------------------------------------------------------------
# Committed transaction: txn 1006 (user:2 -> Bobby, add session:jkl012)
# ---------------------------------------------------------------------------

class TestTxn1006Committed:
    def test_user2_renamed_bobby(self, pages):
        assert pages[1]["user:2:name"] == "Bobby"

    def test_session_jkl012_exists(self, pages):
        assert pages[3]["session:jkl012"] == "user:3"

    def test_overwrites_txn1001_page1(self, pages):
        """Txn 1006 writes to page 1 after txn 1001; 1006 version should win."""
        assert pages[1]["user:2:name"] == "Bobby"
        assert pages[1]["user:2:email"] == "bob@example.com"


# ---------------------------------------------------------------------------
# Truncated transaction: txn 1007 (counter:visits -> 999)
# ---------------------------------------------------------------------------

class TestTxn1007Truncated:
    def test_counter_visits_not_999(self, pages):
        assert pages[2]["counter:visits"] != "999"

    def test_counter_errors_unchanged(self, pages):
        """If txn 1007 were applied, errors would be 0."""
        assert pages[2]["counter:errors"] == "7"


# ---------------------------------------------------------------------------
# Base-only pages: pages 4-5 not touched by any committed WAL transaction
# Must be correctly reconstructed from the SQLite backup
# ---------------------------------------------------------------------------

class TestBaseStatePages:
    def test_permissions_admin_read(self, pages):
        assert pages[4]["perm:admin:read"] == "true"

    def test_permissions_admin_write(self, pages):
        assert pages[4]["perm:admin:write"] == "true"

    def test_permissions_user_read(self, pages):
        assert pages[4]["perm:user:read"] == "true"

    def test_permissions_user_write(self, pages):
        assert pages[4]["perm:user:write"] == "false"

    def test_audit_entry_1_action(self, pages):
        assert pages[5]["audit:001:action"] == "create_user"

    def test_audit_entry_1_target(self, pages):
        assert pages[5]["audit:001:target"] == "user:1"

    def test_audit_entry_1_timestamp(self, pages):
        assert pages[5]["audit:001:timestamp"] == "2024-01-15T10:31:00Z"

    def test_audit_entry_2_action(self, pages):
        assert pages[5]["audit:002:action"] == "create_user"

    def test_audit_entry_2_target(self, pages):
        assert pages[5]["audit:002:target"] == "user:2"

    def test_audit_entry_2_timestamp(self, pages):
        assert pages[5]["audit:002:timestamp"] == "2024-01-15T10:32:00Z"


# ---------------------------------------------------------------------------
# Full page contents
# ---------------------------------------------------------------------------

class TestCompletePageContents:
    def test_page0(self, pages):
        assert pages[0] == {
            "config:version": "2.0.0",
            "config:name": "testdb",
            "config:created_at": "2024-01-15T10:30:00Z",
        }

    def test_page1(self, pages):
        assert pages[1] == {
            "user:1:name": "Alice",
            "user:1:email": "alice@example.com",
            "user:2:name": "Bobby",
            "user:2:email": "bob@example.com",
            "user:3:name": "Charlie",
            "user:3:email": "charlie@example.com",
        }

    def test_page2(self, pages):
        assert pages[2] == {
            "counter:visits": "108",
            "counter:errors": "7",
            "counter:signups": "15",
        }

    def test_page3(self, pages):
        assert pages[3] == {
            "session:abc123": "user:1",
            "session:def456": "user:2",
            "session:jkl012": "user:3",
        }

    def test_page4(self, pages):
        assert pages[4] == {
            "perm:admin:read": "true",
            "perm:admin:write": "true",
            "perm:user:read": "true",
            "perm:user:write": "false",
        }

    def test_page5(self, pages):
        assert pages[5] == {
            "audit:001:action": "create_user",
            "audit:001:target": "user:1",
            "audit:001:timestamp": "2024-01-15T10:31:00Z",
            "audit:002:action": "create_user",
            "audit:002:target": "user:2",
            "audit:002:timestamp": "2024-01-15T10:32:00Z",
        }


# ---------------------------------------------------------------------------
# Preserved data (not touched by any committed transaction)
# ---------------------------------------------------------------------------

class TestPreservedData:
    def test_config_name(self, pages):
        assert pages[0]["config:name"] == "testdb"

    def test_config_created_at(self, pages):
        assert pages[0]["config:created_at"] == "2024-01-15T10:30:00Z"

    def test_counter_errors(self, pages):
        assert pages[2]["counter:errors"] == "7"

    def test_counter_signups(self, pages):
        assert pages[2]["counter:signups"] == "15"

    def test_session_abc123(self, pages):
        assert pages[3]["session:abc123"] == "user:1"

    def test_session_def456(self, pages):
        assert pages[3]["session:def456"] == "user:2"


# ---------------------------------------------------------------------------
# simdb-ctl strict validation
# ---------------------------------------------------------------------------

class TestToolValidation:
    def test_simdb_ctl_validate(self):
        """recovered.db must pass simdb-ctl strict validation.

        simdb-ctl validate checks: magic, version, page size, file size,
        header CRC-32, reserved header bytes, per-page entry sort order,
        and zero-padding after entries.
        """
        result = subprocess.run(
            ["simdb-ctl", "validate", DB_PATH],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"simdb-ctl validate failed:\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
