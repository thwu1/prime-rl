#!/usr/bin/env python3
"""MCUboot flash dump forensic analyzer.

Parses an nRF52840 flash dump to extract MCUboot image headers, validate
image integrity via SHA256 hash verification against TLV entries, read
swap status from image trailers, and diagnose boot failure root cause.
"""
import struct
import hashlib
import json

# --- MCUboot constants ---
FLASH_SIZE = 0x100000
PRIMARY_OFFSET = 0x0C000
SECONDARY_OFFSET = 0x7E000
SLOT_SIZE = 0x72000
HEADER_SIZE = 0x200
TRAILER_SIZE = 0x1000

IMAGE_MAGIC = 0x96f3b83d
TLV_INFO_MAGIC = 0x6907
TLV_SHA256 = 0x10

# MCUboot boot magic (from bootutil_misc.c)
BOOT_MAGIC = [0xf395c277, 0x7fefd260, 0x0f505235, 0x8079b62c]

SWAP_TYPE_NAMES = {
    1: "none",
    2: "test",
    3: "perm",
    4: "revert",
    0xFF: "none",
}


def parse_image_header(data, offset):
    """Parse the 32-byte MCUboot image header at the given flash offset.

    Header layout (little-endian):
        offset  0: uint32 ih_magic
        offset  4: uint32 ih_load_addr
        offset  8: uint16 ih_hdr_size
        offset 10: uint16 ih_protect_tlv_size
        offset 12: uint32 ih_img_size
        offset 16: uint32 ih_flags
        offset 20: uint8  iv_major
        offset 21: uint8  iv_minor
        offset 22: uint16 iv_revision
        offset 24: uint32 iv_build_num
        offset 28: uint32 _pad1
    """
    magic = struct.unpack_from('<I', data, offset)[0]
    load_addr = struct.unpack_from('<I', data, offset + 4)[0]
    hdr_size = struct.unpack_from('<H', data, offset + 8)[0]
    protect_tlv_size = struct.unpack_from('<H', data, offset + 10)[0]
    img_size = struct.unpack_from('<I', data, offset + 12)[0]
    flags = struct.unpack_from('<I', data, offset + 16)[0]
    major = data[offset + 20]
    minor = data[offset + 21]
    revision = struct.unpack_from('<H', data, offset + 22)[0]
    build_num = struct.unpack_from('<I', data, offset + 24)[0]

    return {
        'magic_valid': magic == IMAGE_MAGIC,
        'version': f"{major}.{minor}.{revision}+{build_num}",
        'image_size': img_size,
        'header_size': hdr_size,
        'flags': flags,
        'protect_tlv_size': protect_tlv_size,
        'load_addr': load_addr,
    }


def find_tlv_sha256(data, slot_offset, hdr_size, img_size):
    """Locate and return the SHA256 hash stored in the TLV area.

    The TLV area begins immediately after the image payload:
        slot_offset + hdr_size + img_size

    TLV info header (4 bytes):
        uint16 it_magic   (0x6907)
        uint16 it_tlv_tot (total size including this header)

    Each TLV entry (4 + value_len bytes):
        uint8  it_type
        uint8  _pad
        uint16 it_len
        byte[] value
    """
    tlv_offset = slot_offset + hdr_size + img_size
    if tlv_offset + 4 > len(data):
        return None

    tlv_magic = struct.unpack_from('<H', data, tlv_offset)[0]
    if tlv_magic != TLV_INFO_MAGIC:
        return None

    tlv_total = struct.unpack_from('<H', data, tlv_offset + 2)[0]
    pos = tlv_offset + 4
    end = tlv_offset + tlv_total

    while pos + 4 <= end:
        tlv_type = data[pos]
        tlv_len = struct.unpack_from('<H', data, pos + 2)[0]
        if tlv_type == TLV_SHA256 and tlv_len == 32:
            return data[pos + 4:pos + 4 + 32]
        pos += 4 + tlv_len

    return None


def verify_image_hash(data, slot_offset, header_info):
    """Verify image integrity by comparing SHA256 of header+payload with TLV.

    MCUboot computes the hash over ih_hdr_size bytes of header followed
    by ih_img_size bytes of payload.
    """
    hdr_size = header_info['header_size']
    img_size = header_info['image_size']

    stored_hash = find_tlv_sha256(data, slot_offset, hdr_size, img_size)
    if stored_hash is None:
        return False, None, None

    hash_region = data[slot_offset:slot_offset + hdr_size + img_size]
    computed_hash = hashlib.sha256(hash_region).digest()

    return (stored_hash == computed_hash), stored_hash.hex(), computed_hash.hex()


def parse_image_trailer(data, slot_offset):
    """Parse the image trailer at the end of a slot.

    The trailer occupies the last TRAILER_SIZE bytes of the slot.
    Layout from end of slot (working backwards):
        -16..-1:  Boot magic (4 x uint32 LE)
        -17:      image_ok   (0x01 = confirmed, 0xFF = unconfirmed)
        -18:      copy_done  (0x01 = done, 0xFF = not done)
        -19:      swap_type  (1=none, 2=test, 3=perm, 4=revert, 0xFF=none)
    """
    magic_offset = slot_offset + SLOT_SIZE - 16

    # Check boot magic
    magic_words = []
    for i in range(4):
        val = struct.unpack_from('<I', data, magic_offset + i * 4)[0]
        magic_words.append(val)

    magic_valid = (magic_words == BOOT_MAGIC)

    if not magic_valid:
        return {
            'magic_valid': False,
            'swap_type': None,
            'copy_done': None,
            'image_ok': None,
        }

    image_ok_byte = data[magic_offset - 1]
    copy_done_byte = data[magic_offset - 2]
    swap_type_byte = data[magic_offset - 3]

    return {
        'magic_valid': True,
        'swap_type': SWAP_TYPE_NAMES.get(swap_type_byte,
                                          f"unknown({swap_type_byte})"),
        'swap_type_raw': swap_type_byte,
        'copy_done': copy_done_byte == 0x01,
        'image_ok': image_ok_byte == 0x01,
    }


def diagnose_boot_failure(pri_hdr, pri_hash_valid, pri_trailer,
                          sec_hdr, sec_hash_valid, sec_trailer):
    """Synthesize all analysis results into a boot failure diagnosis."""
    issues = []

    # Check for unconfirmed test swap
    test_swap_unconfirmed = (
        pri_trailer['magic_valid']
        and pri_trailer['swap_type'] == 'test'
        and pri_trailer['copy_done']
        and not pri_trailer['image_ok']
    )
    if test_swap_unconfirmed:
        issues.append(
            "Primary image was loaded via test swap but never confirmed "
            "(IMAGE_OK not set by application). MCUboot will attempt revert."
        )

    # Check secondary image integrity
    if not sec_hash_valid:
        issues.append(
            "Secondary slot image data is corrupted (SHA256 hash mismatch). "
            "Revert target is unusable."
        )

    if test_swap_unconfirmed and not sec_hash_valid:
        return {
            'boot_failure_reason': (
                'unconfirmed_test_swap_with_corrupted_revert_target'),
            'swap_state': 'revert_pending',
            'details': issues,
            'explanation': (
                f"Device performed a test swap to {pri_hdr['version']}. "
                f"The application never confirmed itself (boot_set_confirmed() "
                f"not called), so MCUboot attempts to revert to the secondary "
                f"image ({sec_hdr['version']}). However, the secondary image "
                f"data is corrupted (hash mismatch from interrupted DFU write),"
                f" making revert impossible. Device is stuck in a boot loop."
            ),
        }

    if test_swap_unconfirmed:
        return {
            'boot_failure_reason': 'unconfirmed_test_swap',
            'swap_state': 'revert_pending',
            'details': issues,
        }

    if not sec_hash_valid:
        return {
            'boot_failure_reason': 'corrupted_secondary_image',
            'swap_state': 'none',
            'details': issues,
        }

    return {
        'boot_failure_reason': 'unknown',
        'swap_state': 'unknown',
    }


def main():
    with open('/app/flash_dump.bin', 'rb') as f:
        data = f.read()

    assert len(data) == FLASH_SIZE, (
        f"Expected {FLASH_SIZE} byte flash dump, got {len(data)}")

    # --- Analyze primary slot ---
    pri_hdr = parse_image_header(data, PRIMARY_OFFSET)
    pri_hash_ok, pri_stored, pri_computed = verify_image_hash(
        data, PRIMARY_OFFSET, pri_hdr)
    pri_trailer = parse_image_trailer(data, PRIMARY_OFFSET)

    # --- Analyze secondary slot ---
    sec_hdr = parse_image_header(data, SECONDARY_OFFSET)
    sec_hash_ok, sec_stored, sec_computed = verify_image_hash(
        data, SECONDARY_OFFSET, sec_hdr)
    sec_trailer = parse_image_trailer(data, SECONDARY_OFFSET)

    # --- Diagnose ---
    diagnosis = diagnose_boot_failure(
        pri_hdr, pri_hash_ok, pri_trailer,
        sec_hdr, sec_hash_ok, sec_trailer,
    )

    report = {
        'primary_slot': {
            'offset': PRIMARY_OFFSET,
            'header_valid': pri_hdr['magic_valid'],
            'version': pri_hdr['version'],
            'image_size': pri_hdr['image_size'],
            'flags': pri_hdr['flags'],
            'hash_valid': pri_hash_ok,
            'stored_hash': pri_stored,
            'computed_hash': pri_computed,
        },
        'secondary_slot': {
            'offset': SECONDARY_OFFSET,
            'header_valid': sec_hdr['magic_valid'],
            'version': sec_hdr['version'],
            'image_size': sec_hdr['image_size'],
            'flags': sec_hdr['flags'],
            'hash_valid': sec_hash_ok,
            'stored_hash': sec_stored,
            'computed_hash': sec_computed,
        },
        'primary_trailer': {
            'magic_valid': pri_trailer['magic_valid'],
            'swap_type': pri_trailer['swap_type'],
            'copy_done': pri_trailer['copy_done'],
            'image_ok': pri_trailer['image_ok'],
        },
        'secondary_trailer': {
            'magic_valid': sec_trailer['magic_valid'],
            'swap_type': sec_trailer.get('swap_type'),
            'copy_done': sec_trailer.get('copy_done'),
            'image_ok': sec_trailer.get('image_ok'),
        },
        'diagnosis': diagnosis,
    }

    with open('/app/report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print("Analysis complete. Report written to /app/report.json")


if __name__ == '__main__':
    main()
