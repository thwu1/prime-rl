
import hashlib
import json
import os
import struct
import subprocess

import pytest

# --------------- Pure-Python XXH64 (spec-compliant, no external deps) ------
_P1 = 0x9E3779B185EBCA87
_P2 = 0xC2B2AE3D27D4EB4F
_P3 = 0x165667B19E3779F9
_P4 = 0x85EBCA77C2B2AE63
_P5 = 0x27D4EB2F165667C5
_M  = 0xFFFFFFFFFFFFFFFF


def _r64(x, r):
    return ((x << r) | (x >> (64 - r))) & _M


def _rnd(acc, inp):
    acc = (acc + inp * _P2) & _M
    acc = _r64(acc, 31)
    return (acc * _P1) & _M


def _merge(acc, val):
    val = _rnd(0, val)
    acc = (acc ^ val) & _M
    return (acc * _P1 + _P4) & _M


def xxh64(data, seed=0):
    n = len(data)
    p = 0
    if n >= 32:
        v1 = (seed + _P1 + _P2) & _M
        v2 = (seed + _P2) & _M
        v3 = seed & _M
        v4 = (seed - _P1) & _M
        while p + 32 <= n:
            v1 = _rnd(v1, int.from_bytes(data[p:p+8], 'little'))
            v2 = _rnd(v2, int.from_bytes(data[p+8:p+16], 'little'))
            v3 = _rnd(v3, int.from_bytes(data[p+16:p+24], 'little'))
            v4 = _rnd(v4, int.from_bytes(data[p+24:p+32], 'little'))
            p += 32
        h = (_r64(v1, 1) + _r64(v2, 7) + _r64(v3, 12) + _r64(v4, 18)) & _M
        h = _merge(h, v1)
        h = _merge(h, v2)
        h = _merge(h, v3)
        h = _merge(h, v4)
    else:
        h = (seed + _P5) & _M
    h = (h + n) & _M
    while p + 8 <= n:
        k = _rnd(0, int.from_bytes(data[p:p+8], 'little'))
        h = (_r64(h ^ k, 27) * _P1 + _P4) & _M
        p += 8
    while p + 4 <= n:
        k = int.from_bytes(data[p:p+4], 'little')
        h = (_r64(h ^ ((k * _P1) & _M), 23) * _P2 + _P3) & _M
        p += 4
    while p < n:
        h = (_r64(h ^ ((data[p] * _P5) & _M), 11) * _P1) & _M
        p += 1
    h = ((h ^ (h >> 33)) * _P2) & _M
    h = ((h ^ (h >> 29)) * _P3) & _M
    h = (h ^ (h >> 32)) & _M
    return h

# -------------------------------------------------------------------

ARCHIVE_PATH = "/app/output/repaired_archive.zst"
MANIFEST_PATH = "/opt/taskdata/manifest.json"
FRAMES_DIR = "/opt/taskdata/frames"

SKIPPABLE_MAGIC_SEEKABLE = 0x184D2A5E
SEEKABLE_FOOTER_MAGIC = 0x8F92EAB1
ZSTD_MAGIC = 0xFD2FB528


def load_manifest():
    with open(MANIFEST_PATH) as f:
        return json.load(f)


def read_archive():
    with open(ARCHIVE_PATH, "rb") as f:
        return f.read()


def parse_seek_table(data):
    """Parse the seek table from the end of the archive binary."""
    # Footer: last 9 bytes = [num_frames(4)][descriptor(1)][magic(4)]
    footer_start = len(data) - 9
    num_frames = struct.unpack("<I", data[footer_start : footer_start + 4])[0]
    descriptor = data[footer_start + 4]
    footer_magic = struct.unpack("<I", data[footer_start + 5 : footer_start + 9])[0]

    has_checksum = bool(descriptor & 0x80)
    entry_size = 12 if has_checksum else 8
    entries_size = num_frames * entry_size
    seek_content_size = entries_size + 9

    # Skippable frame header: magic(4) + frame_size(4)
    skippable_start = len(data) - 8 - seek_content_size
    skippable_magic = struct.unpack("<I", data[skippable_start : skippable_start + 4])[0]
    frame_size = struct.unpack("<I", data[skippable_start + 4 : skippable_start + 8])[0]

    entries_start = skippable_start + 8
    entries = []
    for i in range(num_frames):
        off = entries_start + i * entry_size
        comp = struct.unpack("<I", data[off : off + 4])[0]
        decomp = struct.unpack("<I", data[off + 4 : off + 8])[0]
        cksum = struct.unpack("<I", data[off + 8 : off + 12])[0] if has_checksum else None
        entries.append((comp, decomp, cksum))

    return {
        "num_frames": num_frames,
        "descriptor": descriptor,
        "footer_magic": footer_magic,
        "skippable_magic": skippable_magic,
        "frame_size": frame_size,
        "seek_content_size": seek_content_size,
        "has_checksum": has_checksum,
        "entries": entries,
        "skippable_start": skippable_start,
    }


class TestArchiveExists:
    def test_output_file_exists(self):
        assert os.path.exists(ARCHIVE_PATH), f"Output not found at {ARCHIVE_PATH}"

    def test_output_file_nonempty(self):
        assert os.path.getsize(ARCHIVE_PATH) > 0, "Output archive is empty"


class TestDecompression:
    def test_decompresses_successfully(self):
        result = subprocess.run(
            ["zstd", "-d", "-c", ARCHIVE_PATH], capture_output=True
        )
        assert result.returncode == 0, (
            f"zstd decompression failed: {result.stderr.decode()[:500]}"
        )

    def test_decompressed_sha256_matches(self):
        manifest = load_manifest()
        result = subprocess.run(
            ["zstd", "-d", "-c", ARCHIVE_PATH], capture_output=True, check=True
        )
        sha256 = hashlib.sha256(result.stdout).hexdigest()
        assert sha256 == manifest["expected_sha256"], (
            f"SHA-256 mismatch: got {sha256}, expected {manifest['expected_sha256']}"
        )


class TestSeekTableFooter:
    def test_footer_magic_present(self):
        data = read_archive()
        magic = struct.unpack("<I", data[-4:])[0]
        assert magic == SEEKABLE_FOOTER_MAGIC, (
            f"Footer magic: got 0x{magic:08X}, expected 0x{SEEKABLE_FOOTER_MAGIC:08X}"
        )

    def test_frame_count_correct(self):
        manifest = load_manifest()
        data = read_archive()
        st = parse_seek_table(data)
        assert st["num_frames"] == manifest["num_frames"], (
            f"Frame count: got {st['num_frames']}, expected {manifest['num_frames']}"
        )

    def test_checksum_flag_set(self):
        data = read_archive()
        st = parse_seek_table(data)
        assert st["has_checksum"], (
            f"Checksum_Flag not set in descriptor: 0x{st['descriptor']:02X}"
        )

    def test_reserved_bits_zero(self):
        data = read_archive()
        st = parse_seek_table(data)
        reserved = (st["descriptor"] >> 2) & 0x1F
        assert reserved == 0, (
            f"Reserved bits in descriptor must be 0, got 0x{reserved:02X}"
        )


class TestSkippableFrame:
    def test_skippable_magic(self):
        data = read_archive()
        st = parse_seek_table(data)
        assert st["skippable_magic"] == SKIPPABLE_MAGIC_SEEKABLE, (
            f"Skippable magic: got 0x{st['skippable_magic']:08X}, "
            f"expected 0x{SKIPPABLE_MAGIC_SEEKABLE:08X}"
        )

    def test_frame_size_field(self):
        data = read_archive()
        st = parse_seek_table(data)
        assert st["frame_size"] == st["seek_content_size"], (
            f"Frame_Size field: got {st['frame_size']}, "
            f"expected {st['seek_content_size']}"
        )


class TestSeekTableEntries:
    def test_all_compressed_sizes_positive(self):
        data = read_archive()
        st = parse_seek_table(data)
        for i, (comp, decomp, _cksum) in enumerate(st["entries"]):
            assert comp > 0, f"Frame {i}: compressed_size is 0"

    def test_all_decompressed_sizes_positive(self):
        data = read_archive()
        st = parse_seek_table(data)
        for i, (comp, decomp, _cksum) in enumerate(st["entries"]):
            assert decomp > 0, f"Frame {i}: decompressed_size is 0"

    def test_compressed_sizes_sum_to_data_region(self):
        data = read_archive()
        st = parse_seek_table(data)
        total = sum(comp for comp, _, _ in st["entries"])
        assert total == st["skippable_start"], (
            f"Sum of compressed sizes ({total}) != "
            f"seek table offset ({st['skippable_start']})"
        )

    def test_compressed_sizes_match_original_frames(self):
        data = read_archive()
        st = parse_seek_table(data)
        for i, (comp, _, _) in enumerate(st["entries"]):
            frame_path = os.path.join(FRAMES_DIR, f"frame_{i:02d}.zst")
            expected = os.path.getsize(frame_path)
            assert comp == expected, (
                f"Frame {i}: compressed_size in seek table ({comp}) "
                f"!= original frame file size ({expected})"
            )

    def test_decompressed_sizes_match_actual(self):
        data = read_archive()
        st = parse_seek_table(data)
        for i, (_, decomp, _) in enumerate(st["entries"]):
            frame_path = os.path.join(FRAMES_DIR, f"frame_{i:02d}.zst")
            result = subprocess.run(
                ["zstd", "-d", "-c", frame_path], capture_output=True, check=True
            )
            actual = len(result.stdout)
            assert decomp == actual, (
                f"Frame {i}: decompressed_size ({decomp}) != actual ({actual})"
            )


class TestSeekTableChecksums:
    def test_checksums_correct(self):
        data = read_archive()
        st = parse_seek_table(data)
        assert st["has_checksum"], "Checksum_Flag must be set"

        frame_offset = 0
        for i, (comp, decomp, stored_cksum) in enumerate(st["entries"]):
            frame_data = data[frame_offset : frame_offset + comp]

            result = subprocess.run(
                ["zstd", "-d", "-c"], input=frame_data, capture_output=True
            )
            assert result.returncode == 0, f"Frame {i} decompression failed"
            decompressed = result.stdout

            assert len(decompressed) == decomp, (
                f"Frame {i}: decompressed length {len(decompressed)} != {decomp}"
            )

            expected_cksum = xxh64(decompressed, seed=0) & 0xFFFFFFFF
            assert stored_cksum == expected_cksum, (
                f"Frame {i}: checksum 0x{stored_cksum:08X} != "
                f"expected 0x{expected_cksum:08X}"
            )

            frame_offset += comp


class TestFrameIntegrity:
    def test_each_frame_has_zstd_magic(self):
        data = read_archive()
        st = parse_seek_table(data)

        frame_offset = 0
        for i, (comp, _, _) in enumerate(st["entries"]):
            magic = struct.unpack("<I", data[frame_offset : frame_offset + 4])[0]
            assert magic == ZSTD_MAGIC, (
                f"Frame {i} at offset {frame_offset}: "
                f"magic 0x{magic:08X} != 0x{ZSTD_MAGIC:08X}"
            )
            frame_offset += comp

    def test_frames_are_contiguous(self):
        """Verify no gaps or padding between frames and seek table."""
        data = read_archive()
        st = parse_seek_table(data)

        total_frame_bytes = sum(comp for comp, _, _ in st["entries"])
        skippable_frame_total = 8 + st["seek_content_size"]
        expected_total = total_frame_bytes + skippable_frame_total
        assert len(data) == expected_total, (
            f"Archive size {len(data)} != frames ({total_frame_bytes}) "
            f"+ seek table ({skippable_frame_total})"
        )

    def test_data_region_matches_reference_frames(self):
        """Verify the data region is byte-identical to the concatenated reference frames."""
        data = read_archive()
        st = parse_seek_table(data)

        data_region = data[: st["skippable_start"]]
        expected = b""
        for i in range(st["num_frames"]):
            frame_path = os.path.join(FRAMES_DIR, f"frame_{i:02d}.zst")
            with open(frame_path, "rb") as f:
                expected += f.read()

        assert data_region == expected, (
            "Data region does not match concatenated reference frames"
        )
