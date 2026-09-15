#!/usr/bin/env python3

"""
SQLite WAL Forensics Tool

Parses SQLite Write-Ahead Log files at the binary level, validates
chained checksums, identifies transaction boundaries, and reconstructs
database states at arbitrary transaction points.

WAL file format (from SQLite documentation):
- 32-byte header: magic(4) version(4) page_size(4) ckpt_seq(4) salt1(4) salt2(4) cksum1(4) cksum2(4)
- Frames: 24-byte header + page_size data each
  - Frame header: page_no(4) db_size(4) salt1(4) salt2(4) cksum1(4) cksum2(4)
- All multi-byte integers in the file are big-endian
- Checksums use a custom algorithm processing 8-byte chunks as two 32-bit words
- The word-read byte order is determined by the magic number:
  0x377f0682 = little-endian (native on x86), 0x377f0683 = big-endian
- Checksums are chained: each frame's checksum is seeded from the previous frame's
"""

import struct
import shutil
import os

WAL_HEADER_SIZE = 32
FRAME_HEADER_SIZE = 24
WAL_MAGIC_LE = 0x377f0682
WAL_MAGIC_BE = 0x377f0683


def _wal_checksum(data, s1=0, s2=0, big_endian=False):
    """
    Compute SQLite WAL checksum.

    Processes data in 8-byte chunks. Each chunk is read as two 32-bit words
    (w1, w2) in the byte order indicated by big_endian:
        s1 += w1 + s2
        s2 += w2 + s1
    All arithmetic wraps at 32 bits.

    The byte order for reading words is independent of the byte order used
    to store checksum values in the file (which is always big-endian).
    """
    fmt = '>II' if big_endian else '<II'
    for i in range(0, len(data), 8):
        w1, w2 = struct.unpack(fmt, data[i:i + 8])
        s1 = (s1 + w1 + s2) & 0xFFFFFFFF
        s2 = (s2 + w2 + s1) & 0xFFFFFFFF
    return s1, s2


def parse_wal_header(wal_path):
    """Parse the 32-byte WAL file header."""
    with open(wal_path, 'rb') as f:
        header = f.read(WAL_HEADER_SIZE)

    if len(header) < WAL_HEADER_SIZE:
        raise ValueError(f"WAL header too short: {len(header)} bytes")

    magic = struct.unpack('>I', header[0:4])[0]
    version = struct.unpack('>I', header[4:8])[0]
    page_size = struct.unpack('>I', header[8:12])[0]
    checkpoint_seq = struct.unpack('>I', header[12:16])[0]
    salt1 = struct.unpack('>I', header[16:20])[0]
    salt2 = struct.unpack('>I', header[20:24])[0]
    cksum1 = struct.unpack('>I', header[24:28])[0]
    cksum2 = struct.unpack('>I', header[28:32])[0]

    big_endian = (magic == WAL_MAGIC_BE)

    computed_s1, computed_s2 = _wal_checksum(header[0:24], 0, 0, big_endian)
    header_valid = (computed_s1 == cksum1 and computed_s2 == cksum2)

    return {
        'magic': magic,
        'version': version,
        'page_size': page_size,
        'checkpoint_seq': checkpoint_seq,
        'salt1': salt1,
        'salt2': salt2,
        'checksum1': cksum1,
        'checksum2': cksum2,
        'big_endian_checksums': big_endian,
        'header_checksum_valid': header_valid,
    }


def parse_frames(wal_path):
    """
    Parse all WAL frames, validating chained checksums.

    Each frame's checksum is computed by continuing the chain from the
    previous frame (or the WAL header for the first frame):
    1. Checksum the first 8 bytes of the frame header (page_no + db_size)
       using the previous checksum as seed.
    2. Continue the checksum over the full page data.
    3. Compare with the stored checksum in the frame header.

    Parsing stops at the first frame with an invalid checksum or salt mismatch.
    """
    header = parse_wal_header(wal_path)
    page_size = header['page_size']
    big_endian = header['big_endian_checksums']
    h_salt1 = header['salt1']
    h_salt2 = header['salt2']

    prev_s1, prev_s2 = header['checksum1'], header['checksum2']

    frames = []

    with open(wal_path, 'rb') as f:
        frame_offset = WAL_HEADER_SIZE
        frame_index = 0

        while True:
            f.seek(frame_offset)
            fh = f.read(FRAME_HEADER_SIZE)
            if len(fh) < FRAME_HEADER_SIZE:
                break

            page_data = f.read(page_size)
            if len(page_data) < page_size:
                break

            page_number = struct.unpack('>I', fh[0:4])[0]
            db_size = struct.unpack('>I', fh[4:8])[0]
            f_salt1 = struct.unpack('>I', fh[8:12])[0]
            f_salt2 = struct.unpack('>I', fh[12:16])[0]
            stored_c1 = struct.unpack('>I', fh[16:20])[0]
            stored_c2 = struct.unpack('>I', fh[20:24])[0]

            salt_valid = (f_salt1 == h_salt1 and f_salt2 == h_salt2)

            # Chained checksum: header bytes then page data
            s1, s2 = _wal_checksum(fh[0:8], prev_s1, prev_s2, big_endian)
            s1, s2 = _wal_checksum(page_data, s1, s2, big_endian)

            checksum_valid = (s1 == stored_c1 and s2 == stored_c2)
            is_commit = (db_size > 0)

            frame = {
                'index': frame_index,
                'offset': frame_offset,
                'page_number': page_number,
                'db_size_after_commit': db_size,
                'salt1': f_salt1,
                'salt2': f_salt2,
                'stored_checksum': (stored_c1, stored_c2),
                'computed_checksum': (s1, s2),
                'checksum_valid': checksum_valid,
                'salt_valid': salt_valid,
                'is_commit': is_commit,
            }
            frames.append(frame)

            if not (checksum_valid and salt_valid):
                break

            prev_s1, prev_s2 = stored_c1, stored_c2
            frame_offset += FRAME_HEADER_SIZE + page_size
            frame_index += 1

    return frames


def identify_transactions(wal_path):
    """Group valid frames into transactions delimited by commit markers."""
    frames = parse_frames(wal_path)
    transactions = []
    current = []

    for frame in frames:
        if not (frame['checksum_valid'] and frame['salt_valid']):
            break
        current.append(frame)
        if frame['is_commit']:
            transactions.append({
                'index': len(transactions),
                'frame_count': len(current),
                'frames': list(current),
                'db_size': frame['db_size_after_commit'],
                'pages_modified': [f['page_number'] for f in current],
            })
            current = []

    return transactions


def validate_checksums(wal_path):
    """Validate header and all frame checksums."""
    header = parse_wal_header(wal_path)
    frames = parse_frames(wal_path)
    return {
        'header_valid': header['header_checksum_valid'],
        'frames': [
            {'index': f['index'], 'valid': f['checksum_valid'],
             'page_number': f['page_number']}
            for f in frames
        ],
    }


def reconstruct_at_transaction(db_path, wal_path, txn_index, output_path):
    """
    Reconstruct the database state after the specified transaction.

    1. Copy the original database file (base state before any WAL writes).
    2. Build a page map: for each page modified up to txn_index, keep the
       latest version from the WAL.
    3. Extend or truncate the file to match the committed database size.
    4. Overlay WAL pages onto the copy.
    5. Patch the SQLite header (bytes 18-19) to rollback journal mode so the
       database is self-contained without a WAL file.
    """
    header = parse_wal_header(wal_path)
    page_size = header['page_size']
    transactions = identify_transactions(wal_path)

    if txn_index < 0 or txn_index >= len(transactions):
        raise ValueError(
            f"txn_index {txn_index} out of range [0, {len(transactions) - 1}]")

    # Latest page version up to target transaction
    page_map = {}
    with open(wal_path, 'rb') as f:
        for tidx in range(txn_index + 1):
            for frame in transactions[tidx]['frames']:
                f.seek(frame['offset'] + FRAME_HEADER_SIZE)
                page_map[frame['page_number']] = f.read(page_size)

    # Copy base database
    shutil.copy2(db_path, output_path)

    # Remove any WAL/SHM for the output path
    for ext in ('-wal', '-shm'):
        try:
            os.remove(output_path + ext)
        except FileNotFoundError:
            pass

    db_size_pages = transactions[txn_index]['db_size']
    target_size = db_size_pages * page_size

    with open(output_path, 'r+b') as f:
        # Extend if needed
        f.seek(0, 2)
        current_size = f.tell()
        if current_size < target_size:
            f.write(b'\x00' * (target_size - current_size))

        # Overlay WAL pages
        for page_number, data in page_map.items():
            f.seek((page_number - 1) * page_size)
            f.write(data)

        # Set correct file size
        f.truncate(target_size)

        # Patch header for standalone operation (no WAL needed)
        # Bytes 18-19: read/write version — 0x01 = rollback journal
        f.seek(18)
        f.write(b'\x01\x01')

        # Bytes 28-31: database size in pages (big-endian)
        f.seek(28)
        f.write(struct.pack('>I', db_size_pages))

    return output_path
