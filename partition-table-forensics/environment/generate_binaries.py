#!/usr/bin/env python3
"""Generate flash dump files with corrupted/missing partition tables.

Each dump simulates raw ESP32 flash memory where the partition table region
at offset 0x8000 has been destroyed, but the actual content (firmware, NVS,
OTA data, PHY calibration) remains intact. The forensics tool must analyze
these content signatures to reconstruct valid partition tables.
"""
import struct
import hashlib
import os
import zlib

# --- Flash constants ---
SECTOR = 0x1000  # 4KB sector

# --- Content signature constants ---
APP_MAGIC = 0xE9
NVS_PAGE_ACTIVE = 0xFFFFFFFE
NVS_PAGE_FULL = 0xFFFFFFFC
NVS_VERSION = 0xFE
PHY_MAGIC = bytes([0x04, 0x02, 0x00, 0x00])

# --- Partition table constants ---
PT_MAGIC = b'\xaa\x50'
PT_STRUCT = '<2sBBLL16sL'
MD5_MARKER = b'\xeb\xeb' + b'\xff' * 14
MAX_PT_LEN = 0xC00

APP_TYPE = 0x00
DATA_TYPE = 0x01


def make_app_region(entry_addr, segment_count=3, chip_id=0x0000, num_sectors=1):
    """Create an APP image region spanning num_sectors 4KB sectors.

    First sector contains a valid esp_image_header_t (24 bytes) plus a fake
    segment header and data. Remaining sectors are filled with distinguishable
    non-zero, non-0xFF data (simulating firmware code/data).
    """
    # 24-byte esp_image_header_t
    header = struct.pack(
        '<BBBI B3s HB 2s2s 4sB',
        APP_MAGIC,                # magic
        segment_count,            # segment_count
        0x00,                     # spi_mode (QIO)
        entry_addr,               # entry_addr (includes spi_speed_size byte due to packing)
        0xEE,                     # wp_pin
        b'\x0F\x0F\x0F',         # spi_pin_drv
        chip_id,                  # chip_id
        0x00,                     # min_chip_rev
        b'\x00\x00',             # min_chip_rev_full
        b'\xFF\xFF',             # max_chip_rev_full
        b'\x00\x00\x00\x00',    # reserved
        0x01,                     # hash_appended
    )
    # Actually, let's use the correct struct for the 24-byte header
    # to avoid any packing ambiguity
    header = bytearray(24)
    header[0] = APP_MAGIC
    header[1] = segment_count
    header[2] = 0x00  # spi_mode
    header[3] = 0x1F  # spi_speed_size
    struct.pack_into('<I', header, 4, entry_addr)
    header[8] = 0xEE  # wp_pin
    header[9:12] = b'\x0F\x0F\x0F'  # spi_pin_drv
    struct.pack_into('<H', header, 12, chip_id)
    header[14] = 0x00  # min_chip_rev
    header[15:17] = b'\x00\x00'  # min_chip_rev_full
    header[17:19] = b'\xFF\xFF'  # max_chip_rev_full
    header[19:23] = b'\x00\x00\x00\x00'  # reserved
    header[23] = 0x01  # hash_appended
    header = bytes(header)

    # Fake segment header + data
    seg_hdr = struct.pack('<II', 0x3F400010, 0x80)  # load_addr, data_len=128
    seg_data = bytes(range(128))

    content = header + seg_hdr + seg_data  # ~160 bytes
    first_sector = content + b'\x5A' * (SECTOR - len(content))

    remaining = b''
    for i in range(1, num_sectors):
        # Fill with non-zero, non-0xFF pattern that won't match any signature
        fill_byte = (i % 128) + 0x10  # Range 0x11-0x8F, avoids 0x00/0xE9/0xFF
        remaining += bytes([fill_byte]) * SECTOR

    return first_sector + remaining


def make_nvs_page(seq_no, state=NVS_PAGE_ACTIVE):
    """Create a single NVS page (one 4KB sector) with valid header and CRC."""
    state_bytes = struct.pack('<I', state)
    # CRC payload: bytes 4-11 of header (seq_number + version + unused)
    crc_payload = struct.pack('<I', seq_no) + bytes([NVS_VERSION]) + b'\xFF\xFF\xFF'
    crc = zlib.crc32(crc_payload) & 0xFFFFFFFF
    header = state_bytes + crc_payload + struct.pack('<I', crc)  # 16 bytes
    # Fill rest with simulated NVS entry data
    page_data = header + b'\xFF' * (SECTOR - len(header))
    return page_data


def make_ota_data_region():
    """Create OTA data partition (0x2000 = 2 sectors) with valid CRC entries."""
    def make_ota_select(seq, state=0xFFFFFFFF):
        payload = struct.pack('<I', seq) + b'\xFF' * 20 + struct.pack('<I', state)
        crc = zlib.crc32(payload) & 0xFFFFFFFF
        return payload + struct.pack('<I', crc)  # 32 bytes

    sector1 = make_ota_select(1, 0x10)  # ota_seq=1, state=NEW
    sector1 += b'\xFF' * (SECTOR - len(sector1))
    sector2 = make_ota_select(0)  # unused slot
    sector2 += b'\xFF' * (SECTOR - len(sector2))
    return sector1 + sector2


def make_phy_region():
    """Create PHY init data (1 sector) with magic header."""
    data = PHY_MAGIC + bytes(range(124))
    return data + b'\xFF' * (SECTOR - len(data))


def make_bootloader_region():
    """Create bootloader region (1 sector at 0x1000)."""
    return make_app_region(entry_addr=0x40078000, segment_count=1, num_sectors=1)


def write_region(flash, offset, data):
    """Write data to flash bytearray at given offset."""
    flash[offset:offset + len(data)] = data


def make_pt_entry(name, ptype, subtype, offset, size, flags=0):
    """Create a single partition table entry (32 bytes)."""
    name_bytes = name.encode('ascii')[:16].ljust(16, b'\x00')
    return struct.pack(PT_STRUCT, PT_MAGIC, ptype, subtype, offset, size, name_bytes, flags)


def main():
    os.makedirs('/app/dumps', exist_ok=True)

    bl = make_bootloader_region()
    phy = make_phy_region()
    ota = make_ota_data_region()

    # ===== flash_simple.bin: Factory-only layout (256KB) =====
    # Layout: bootloader(0x1000), PT(0x8000, zeroed), nvs(0x9000, 6 pages),
    #         phy(0xF000), factory(0x10000 to end)
    flash_size = 0x40000
    flash = bytearray(b'\xFF' * flash_size)
    write_region(flash, 0x1000, bl)
    flash[0x8000:0x9000] = b'\x00' * SECTOR  # zeroed PT
    for i in range(6):
        state = NVS_PAGE_FULL if i < 3 else NVS_PAGE_ACTIVE
        write_region(flash, 0x9000 + i * SECTOR, make_nvs_page(i, state))
    write_region(flash, 0xF000, phy)
    app_sectors = (flash_size - 0x10000) // SECTOR  # 48 sectors
    write_region(flash, 0x10000, make_app_region(0x40080000, 3, num_sectors=app_sectors))
    with open('/app/dumps/flash_simple.bin', 'wb') as f:
        f.write(flash)

    # ===== flash_ota.bin: OTA layout with 3 app slots (1MB) =====
    # Layout: bootloader(0x1000), PT(0x8000, zeroed), nvs(0x9000, 4 pages),
    #         otadata(0xD000, 2 sectors), phy(0xF000),
    #         factory(0x10000, 320KB), ota_0(0x60000, 320KB), ota_1(0xB0000, 320KB)
    flash_size = 0x100000
    flash = bytearray(b'\xFF' * flash_size)
    write_region(flash, 0x1000, bl)
    flash[0x8000:0x9000] = b'\x00' * SECTOR
    for i in range(4):
        write_region(flash, 0x9000 + i * SECTOR, make_nvs_page(i))
    write_region(flash, 0xD000, ota)
    write_region(flash, 0xF000, phy)
    write_region(flash, 0x10000, make_app_region(0x40080000, 5, num_sectors=0x50))
    write_region(flash, 0x60000, make_app_region(0x40090000, 4, num_sectors=0x50))
    write_region(flash, 0xB0000, make_app_region(0x400A0000, 3, num_sectors=0x50))
    with open('/app/dumps/flash_ota.bin', 'wb') as f:
        f.write(flash)

    # ===== flash_complex.bin: OTA layout with PARTIAL partition table (1MB) =====
    # Same content as flash_ota, but PT has first 2 entries intact (nvs, otadata),
    # remaining entries zeroed (no MD5, no end marker). The tool must merge
    # intact PT entries with scan-detected regions.
    flash_size = 0x100000
    flash = bytearray(b'\xFF' * flash_size)
    write_region(flash, 0x1000, bl)
    # Partial partition table: 2 valid entries, rest zeroed
    pt_data = bytearray(b'\x00' * SECTOR)
    pt_data[0:32] = make_pt_entry('nvs', DATA_TYPE, 0x02, 0x9000, 0x4000)
    pt_data[32:64] = make_pt_entry('otadata', DATA_TYPE, 0x00, 0xD000, 0x2000)
    flash[0x8000:0x9000] = pt_data
    # Same content regions as flash_ota
    for i in range(4):
        write_region(flash, 0x9000 + i * SECTOR, make_nvs_page(i))
    write_region(flash, 0xD000, ota)
    write_region(flash, 0xF000, phy)
    write_region(flash, 0x10000, make_app_region(0x40080000, 5, num_sectors=0x50))
    write_region(flash, 0x60000, make_app_region(0x40090000, 4, num_sectors=0x50))
    write_region(flash, 0xB0000, make_app_region(0x400A0000, 3, num_sectors=0x50))
    with open('/app/dumps/flash_complex.bin', 'wb') as f:
        f.write(flash)


if __name__ == '__main__':
    main()
