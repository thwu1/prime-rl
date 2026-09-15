#!/usr/bin/env python3
"""Generate synthetic nRF52840 flash dump for MCUboot forensic analysis task."""
import struct
import hashlib
import random
import os

FLASH_SIZE = 0x100000
PRIMARY_OFFSET = 0x0C000
SECONDARY_OFFSET = 0x7E000
SLOT_SIZE = 0x72000
HEADER_SIZE = 0x200
TRAILER_SIZE = 0x1000
IMAGE_MAGIC = 0x96f3b83d
TLV_INFO_MAGIC = 0x6907
TLV_SHA256 = 0x10
TLV_KEYHASH = 0x01
BOOT_MAGIC = [0xf395c277, 0x7fefd260, 0x0f505235, 0x8079b62c]
BOOT_SWAP_TYPE_TEST = 2
IMG_SIZE = 0x60000


def make_header(major, minor, revision, build_num):
    """Create a 512-byte MCUboot image header."""
    # ih_magic (4) + ih_load_addr (4) + ih_hdr_size (2) + ih_protect_tlv_size (2)
    hdr = struct.pack('<IIHH', IMAGE_MAGIC, 0, HEADER_SIZE, 0)
    # ih_img_size (4) + ih_flags (4)
    hdr += struct.pack('<II', IMG_SIZE, 0)
    # ih_ver: major (1) + minor (1) + revision (2) + build_num (4)
    hdr += struct.pack('<BBHI', major, minor, revision, build_num)
    # _pad1 (4)
    hdr += struct.pack('<I', 0)
    assert len(hdr) == 32
    hdr += b'\xff' * (HEADER_SIZE - 32)
    return hdr


def make_tlv(sha256_hash):
    """Create TLV area containing SHA256 image hash and key hash."""
    sha_entry = struct.pack('<BBH', TLV_SHA256, 0, 32) + sha256_hash
    keyhash = hashlib.sha256(b'nrf52840_signing_key_v1').digest()
    key_entry = struct.pack('<BBH', TLV_KEYHASH, 0, 32) + keyhash
    tlv_data = sha_entry + key_entry
    # TLV info header: magic (2) + total_size including this header (2)
    tlv_info = struct.pack('<HH', TLV_INFO_MAGIC, len(tlv_data) + 4)
    return tlv_info + tlv_data


def make_trailer(swap_type, copy_done, image_ok, has_magic=True):
    """Create image trailer (last TRAILER_SIZE bytes of slot).

    Layout from end of trailer (working backwards):
      -16..-1:  boot magic (4 x uint32 LE)
      -17:      image_ok flag
      -18:      copy_done flag
      -19:      swap_type byte
    """
    trailer = bytearray(b'\xff' * TRAILER_SIZE)
    if has_magic:
        off = TRAILER_SIZE - 16
        for i, m in enumerate(BOOT_MAGIC):
            struct.pack_into('<I', trailer, off + i * 4, m)
        trailer[off - 1] = image_ok
        trailer[off - 2] = copy_done
        trailer[off - 3] = swap_type
    return bytes(trailer)


def assemble_slot(header, firmware, stored_hash, swap_type, copy_done,
                  image_ok, has_magic=True):
    """Assemble a complete slot: header + firmware + TLV + padding + trailer."""
    tlv = make_tlv(stored_hash)
    trailer = make_trailer(swap_type, copy_done, image_ok, has_magic)
    content = header + firmware + tlv
    pad_size = SLOT_SIZE - len(content) - TRAILER_SIZE
    assert pad_size >= 0
    return content + (b'\xff' * pad_size) + trailer


def main():
    os.makedirs('/app', exist_ok=True)
    flash = bytearray(b'\xff' * FLASH_SIZE)

    # --- MBR region (0x0000): ARM Cortex-M4 vector table ---
    struct.pack_into('<I', flash, 0, 0x20040000)   # Initial SP (top of 256KB RAM)
    struct.pack_into('<I', flash, 4, 0x00001001)   # Reset vector (thumb mode)

    # --- MCUboot bootloader region (0x1000): vector table + code ---
    struct.pack_into('<I', flash, 0x1000, 0x20040000)
    struct.pack_into('<I', flash, 0x1004, 0x00001101)
    rng_boot = random.Random(42)
    for i in range(0x1100, 0x5000):
        flash[i] = rng_boot.getrandbits(8)

    # --- PRIMARY SLOT: v1.2.0+100 ---
    # Valid image, test swap completed but never confirmed (image_ok unset)
    primary_hdr = make_header(1, 2, 0, 100)
    rng_p = random.Random(1234)
    primary_fw = rng_p.randbytes(IMG_SIZE)
    # MCUboot hash covers header + payload
    primary_hash = hashlib.sha256(primary_hdr + primary_fw).digest()
    primary_slot = assemble_slot(
        primary_hdr, primary_fw, primary_hash,
        swap_type=BOOT_SWAP_TYPE_TEST, copy_done=0x01, image_ok=0xFF,
        has_magic=True
    )
    flash[PRIMARY_OFFSET:PRIMARY_OFFSET + SLOT_SIZE] = primary_slot

    # --- SECONDARY SLOT: v1.0.0+50 ---
    # Original firmware that was swapped out; data corrupted during DFU write
    secondary_hdr = make_header(1, 0, 0, 50)
    rng_s = random.Random(5678)
    secondary_fw_orig = rng_s.randbytes(IMG_SIZE)
    # Hash was computed from correct data before corruption
    secondary_hash = hashlib.sha256(secondary_hdr + secondary_fw_orig).digest()
    # Corrupt 256 bytes to simulate interrupted DFU write
    secondary_fw = bytearray(secondary_fw_orig)
    rng_c = random.Random(9999)
    positions = []
    seen = set()
    while len(positions) < 256:
        p = rng_c.randint(0, IMG_SIZE - 1)
        if p not in seen:
            positions.append(p)
            seen.add(p)
    for p in positions:
        secondary_fw[p] ^= rng_c.randint(1, 255)
    secondary_slot = assemble_slot(
        secondary_hdr, bytes(secondary_fw), secondary_hash,
        swap_type=0xFF, copy_done=0xFF, image_ok=0xFF,
        has_magic=False  # No boot magic in secondary trailer
    )
    flash[SECONDARY_OFFSET:SECONDARY_OFFSET + SLOT_SIZE] = secondary_slot

    with open('/app/flash_dump.bin', 'wb') as f:
        f.write(flash)

    print(f"Generated /app/flash_dump.bin ({len(flash)} bytes)")


if __name__ == '__main__':
    main()
