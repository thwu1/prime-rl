"""Tests for MCUboot flash dump forensic analysis report."""
import json
import struct
import hashlib
import os
import re
import pytest

# MCUboot constants for independent verification
FLASH_SIZE = 0x100000
PRIMARY_OFFSET = 0x0C000
SECONDARY_OFFSET = 0x7E000
SLOT_SIZE = 0x72000
HEADER_SIZE = 0x200
TRAILER_SIZE = 0x1000
IMAGE_MAGIC = 0x96f3b83d
TLV_INFO_MAGIC = 0x6907
TLV_SHA256 = 0x10
BOOT_MAGIC = [0xf395c277, 0x7fefd260, 0x0f505235, 0x8079b62c]


@pytest.fixture
def report():
    with open('/app/report.json') as f:
        return json.load(f)


@pytest.fixture
def flash_data():
    with open('/app/flash_dump.bin', 'rb') as f:
        return f.read()


# --- Extraction tests ---

class TestExtraction:
    """Verify that image slots were properly extracted."""

    def test_extracted_dir_exists(self):
        assert os.path.isdir('/app/extracted'), "/app/extracted/ directory not found"

    def test_primary_bin_exists(self):
        assert os.path.exists('/app/extracted/primary.bin'), \
            "Extracted primary.bin not found"

    def test_secondary_bin_exists(self):
        assert os.path.exists('/app/extracted/secondary.bin'), \
            "Extracted secondary.bin not found"

    def test_primary_bin_size(self):
        size = os.path.getsize('/app/extracted/primary.bin')
        assert size == SLOT_SIZE, \
            f"primary.bin size {size} != expected {SLOT_SIZE}"

    def test_secondary_bin_size(self):
        size = os.path.getsize('/app/extracted/secondary.bin')
        assert size == SLOT_SIZE, \
            f"secondary.bin size {size} != expected {SLOT_SIZE}"

    def test_primary_bin_content(self, flash_data):
        """Extracted primary.bin must match the corresponding flash region."""
        with open('/app/extracted/primary.bin', 'rb') as f:
            extracted = f.read()
        expected = flash_data[PRIMARY_OFFSET:PRIMARY_OFFSET + SLOT_SIZE]
        assert extracted == expected, \
            "primary.bin content does not match flash dump region"

    def test_secondary_bin_content(self, flash_data):
        """Extracted secondary.bin must match the corresponding flash region."""
        with open('/app/extracted/secondary.bin', 'rb') as f:
            extracted = f.read()
        expected = flash_data[SECONDARY_OFFSET:SECONDARY_OFFSET + SLOT_SIZE]
        assert extracted == expected, \
            "secondary.bin content does not match flash dump region"


# --- Checksum tests ---

class TestChecksums:
    """Verify that SHA256 checksums were computed."""

    def test_checksums_file_exists(self):
        assert os.path.exists('/app/extracted/checksums.txt'), \
            "checksums.txt not found"

    def test_checksums_contain_hashes(self):
        with open('/app/extracted/checksums.txt') as f:
            content = f.read()
        hashes = re.findall(r'[0-9a-fA-F]{64}', content)
        assert len(hashes) >= 2, \
            f"Expected at least 2 SHA256 hashes in checksums.txt, found {len(hashes)}"

    def test_primary_checksum_correct(self):
        """SHA256 in checksums.txt must match actual primary.bin content."""
        with open('/app/extracted/checksums.txt') as f:
            content = f.read().lower()
        with open('/app/extracted/primary.bin', 'rb') as f:
            data = f.read()
        expected = hashlib.sha256(data).hexdigest()
        assert expected in content, \
            f"SHA256 of primary.bin ({expected}) not in checksums.txt"

    def test_secondary_checksum_correct(self):
        """SHA256 in checksums.txt must match actual secondary.bin content."""
        with open('/app/extracted/checksums.txt') as f:
            content = f.read().lower()
        with open('/app/extracted/secondary.bin', 'rb') as f:
            data = f.read()
        expected = hashlib.sha256(data).hexdigest()
        assert expected in content, \
            f"SHA256 of secondary.bin ({expected}) not in checksums.txt"


# --- Partition layout tests ---

class TestPartitionLayout:
    """Verify partition layout was derived from pm_static.yml."""

    def test_has_partition_layout(self, report):
        assert 'partition_layout' in report, \
            "report.json missing partition_layout section"

    def test_primary_offset(self, report):
        assert report['partition_layout']['primary_offset'] == PRIMARY_OFFSET

    def test_primary_size(self, report):
        assert report['partition_layout']['primary_size'] == SLOT_SIZE

    def test_secondary_offset(self, report):
        assert report['partition_layout']['secondary_offset'] == SECONDARY_OFFSET

    def test_secondary_size(self, report):
        assert report['partition_layout']['secondary_size'] == SLOT_SIZE


# --- Report structure tests ---

class TestReportStructure:
    def test_report_exists(self):
        assert os.path.exists('/app/report.json'), "report.json not found"

    def test_report_valid_json(self):
        with open('/app/report.json') as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_has_primary_slot(self, report):
        assert 'primary_slot' in report

    def test_has_secondary_slot(self, report):
        assert 'secondary_slot' in report

    def test_has_primary_trailer(self, report):
        assert 'primary_trailer' in report

    def test_has_secondary_trailer(self, report):
        assert 'secondary_trailer' in report

    def test_has_diagnosis(self, report):
        assert 'diagnosis' in report


# --- Primary slot value tests ---

class TestPrimarySlot:
    def test_header_valid(self, report):
        assert report['primary_slot']['header_valid'] is True

    def test_version(self, report):
        assert report['primary_slot']['version'] == '1.2.0+100'

    def test_image_size(self, report):
        assert report['primary_slot']['image_size'] == 0x60000

    def test_hash_valid(self, report):
        assert report['primary_slot']['hash_valid'] is True

    def test_has_stored_hash(self, report):
        assert 'stored_hash' in report['primary_slot']
        assert isinstance(report['primary_slot']['stored_hash'], str)
        assert len(report['primary_slot']['stored_hash']) == 64

    def test_has_computed_hash(self, report):
        assert 'computed_hash' in report['primary_slot']
        assert isinstance(report['primary_slot']['computed_hash'], str)
        assert len(report['primary_slot']['computed_hash']) == 64

    def test_hashes_match(self, report):
        """Primary stored and computed hashes must be equal (valid image)."""
        assert report['primary_slot']['stored_hash'] == \
            report['primary_slot']['computed_hash']


# --- Secondary slot value tests ---

class TestSecondarySlot:
    def test_header_valid(self, report):
        assert report['secondary_slot']['header_valid'] is True

    def test_version(self, report):
        assert report['secondary_slot']['version'] == '1.0.0+50'

    def test_image_size(self, report):
        assert report['secondary_slot']['image_size'] == 0x60000

    def test_hash_invalid(self, report):
        assert report['secondary_slot']['hash_valid'] is False

    def test_hashes_differ(self, report):
        """Secondary stored and computed hashes must differ (corrupted)."""
        assert report['secondary_slot']['stored_hash'] != \
            report['secondary_slot']['computed_hash']


# --- Primary trailer value tests ---

class TestPrimaryTrailer:
    def test_magic_valid(self, report):
        assert report['primary_trailer']['magic_valid'] is True

    def test_swap_type_is_test(self, report):
        assert report['primary_trailer']['swap_type'] == 'test'

    def test_copy_done(self, report):
        assert report['primary_trailer']['copy_done'] is True

    def test_image_ok_unset(self, report):
        assert report['primary_trailer']['image_ok'] is False


# --- Secondary trailer value tests ---

class TestSecondaryTrailer:
    def test_magic_invalid(self, report):
        assert report['secondary_trailer']['magic_valid'] is False


# --- Diagnosis tests ---

class TestDiagnosis:
    def test_boot_failure_reason_keywords(self, report):
        """Diagnosis must identify key aspects: unconfirmed swap + corruption."""
        reason = report['diagnosis']['boot_failure_reason'].lower()
        has_swap_keyword = ('unconfirmed' in reason or 'test' in reason
                           or 'revert' in reason)
        has_corruption_keyword = ('corrupt' in reason or 'invalid' in reason
                                 or 'hash' in reason or 'fail' in reason)
        assert has_swap_keyword, \
            f"boot_failure_reason must mention swap issue: {reason}"
        assert has_corruption_keyword, \
            f"boot_failure_reason must mention corruption/invalidity: {reason}"

    def test_swap_state_keywords(self, report):
        state = report['diagnosis'].get('swap_state', '').lower()
        assert ('revert' in state or 'pending' in state or 'test' in state
                or 'loop' in state), \
            f"swap_state should indicate revert/pending/test state: {state}"


# --- Independent binary verification tests ---

class TestIndependentVerification:
    """Verify report claims by independently parsing the flash binary."""

    def _read_header_at(self, data, offset):
        magic = struct.unpack_from('<I', data, offset)[0]
        img_size = struct.unpack_from('<I', data, offset + 12)[0]
        major = data[offset + 20]
        minor = data[offset + 21]
        revision = struct.unpack_from('<H', data, offset + 22)[0]
        build = struct.unpack_from('<I', data, offset + 24)[0]
        return magic, img_size, major, minor, revision, build

    def _find_tlv_sha256(self, data, slot_offset, img_size):
        tlv_off = slot_offset + HEADER_SIZE + img_size
        tlv_magic = struct.unpack_from('<H', data, tlv_off)[0]
        if tlv_magic != TLV_INFO_MAGIC:
            return None
        tlv_total = struct.unpack_from('<H', data, tlv_off + 2)[0]
        pos = tlv_off + 4
        end = tlv_off + tlv_total
        while pos + 4 <= end:
            t = data[pos]
            l = struct.unpack_from('<H', data, pos + 2)[0]
            if t == TLV_SHA256 and l == 32:
                return data[pos + 4:pos + 4 + 32]
            pos += 4 + l
        return None

    def test_primary_header_magic(self, flash_data):
        magic, _, _, _, _, _ = self._read_header_at(flash_data, PRIMARY_OFFSET)
        assert magic == IMAGE_MAGIC

    def test_primary_version_binary(self, flash_data):
        _, _, major, minor, rev, build = self._read_header_at(
            flash_data, PRIMARY_OFFSET)
        assert (major, minor, rev, build) == (1, 2, 0, 100)

    def test_secondary_header_magic(self, flash_data):
        magic, _, _, _, _, _ = self._read_header_at(
            flash_data, SECONDARY_OFFSET)
        assert magic == IMAGE_MAGIC

    def test_secondary_version_binary(self, flash_data):
        _, _, major, minor, rev, build = self._read_header_at(
            flash_data, SECONDARY_OFFSET)
        assert (major, minor, rev, build) == (1, 0, 0, 50)

    def test_primary_hash_matches(self, flash_data):
        """Independently verify primary image hash is valid."""
        _, img_size, _, _, _, _ = self._read_header_at(
            flash_data, PRIMARY_OFFSET)
        hash_input = flash_data[
            PRIMARY_OFFSET:PRIMARY_OFFSET + HEADER_SIZE + img_size]
        computed = hashlib.sha256(hash_input).digest()
        stored = self._find_tlv_sha256(flash_data, PRIMARY_OFFSET, img_size)
        assert stored is not None, "SHA256 TLV not found in primary slot"
        assert stored == computed, "Primary image hash should be valid"

    def test_secondary_hash_mismatches(self, flash_data):
        """Independently verify secondary image hash is corrupted."""
        _, img_size, _, _, _, _ = self._read_header_at(
            flash_data, SECONDARY_OFFSET)
        hash_input = flash_data[
            SECONDARY_OFFSET:SECONDARY_OFFSET + HEADER_SIZE + img_size]
        computed = hashlib.sha256(hash_input).digest()
        stored = self._find_tlv_sha256(flash_data, SECONDARY_OFFSET, img_size)
        assert stored is not None, "SHA256 TLV not found in secondary slot"
        assert stored != computed, "Secondary image hash should NOT match"

    def test_primary_trailer_magic(self, flash_data):
        """Independently verify primary trailer boot magic."""
        magic_off = PRIMARY_OFFSET + SLOT_SIZE - 16
        for i, expected in enumerate(BOOT_MAGIC):
            val = struct.unpack_from('<I', flash_data, magic_off + i * 4)[0]
            assert val == expected, f"Boot magic word {i} mismatch"

    def test_primary_trailer_flags(self, flash_data):
        """Independently verify primary trailer swap flags."""
        magic_off = PRIMARY_OFFSET + SLOT_SIZE - 16
        swap_type = flash_data[magic_off - 3]
        copy_done = flash_data[magic_off - 2]
        image_ok = flash_data[magic_off - 1]
        assert swap_type == 2, \
            f"swap_type should be 2 (test), got {swap_type}"
        assert copy_done == 1, \
            f"copy_done should be 1, got {copy_done}"
        assert image_ok == 0xFF, \
            f"image_ok should be 0xFF, got {image_ok:#x}"

    def test_secondary_trailer_no_magic(self, flash_data):
        """Independently verify secondary trailer has no boot magic."""
        magic_off = SECONDARY_OFFSET + SLOT_SIZE - 16
        for i in range(16):
            assert flash_data[magic_off + i] == 0xFF, \
                f"Secondary trailer byte {i} should be 0xFF"
